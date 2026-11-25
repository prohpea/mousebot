import math
import threading
import time

from src.utils.debug_logger import log_print
import cv2
import numpy as np

from src.utils.config import config


_model = None
_class_names = {}
HSV_MIN = None
HSV_MAX = None
_PREV_STABLE_RECTS = []
_PREV_STABLE_TS = 0.0
_STABILIZE_LOCK = threading.Lock()

_OPENCL_AVAILABLE = False
_OPENCL_DEVICE_NAME = "CPU"
_OPENCL_SHORT_NAME = "CPU"
_CPU_KERNEL_CACHE = {}
_UMAT_KERNEL_CACHE = {}


def _shorten_gpu_name(name: str) -> str:
    txt = str(name or "").strip()
    for prefix in ("NVIDIA GeForce ", "AMD Radeon ", "Intel(R) ", "NVIDIA "):
        if txt.startswith(prefix):
            txt = txt[len(prefix):]
    return txt[:18].strip() or "GPU"


def _init_opencl_gpu():
    global _OPENCL_AVAILABLE, _OPENCL_DEVICE_NAME, _OPENCL_SHORT_NAME
    try:
        if cv2.ocl.haveOpenCL():
            cv2.ocl.setUseOpenCL(True)
            dev = cv2.ocl.Device.getDefault()
            dev_name = str(dev.name() or "").strip()
            # OpenCL CL_DEVICE_TYPE_GPU == 4
            if dev_name and int(dev.type()) == 4:
                _OPENCL_AVAILABLE = True
                _OPENCL_DEVICE_NAME = dev_name
                _OPENCL_SHORT_NAME = _shorten_gpu_name(dev_name)
                log_print(f"[GPU] OpenCL GPU ready: {dev_name}")
                return
    except Exception as exc:
        log_print(f"[GPU] OpenCL init fallback to CPU: {exc}")
    _OPENCL_AVAILABLE = False
    _OPENCL_DEVICE_NAME = "CPU"
    _OPENCL_SHORT_NAME = "CPU"


_init_opencl_gpu()


def is_gpu_opencl_active() -> bool:
    return bool(_OPENCL_AVAILABLE and getattr(config, "gpu_opencl_enabled", True))


def get_compute_backend_info() -> dict:
    active = is_gpu_opencl_active()
    return {
        "gpu_available": bool(_OPENCL_AVAILABLE),
        "gpu_enabled": bool(getattr(config, "gpu_opencl_enabled", True)),
        "active_backend": "GPU" if active else "CPU",
        "device_name": _OPENCL_DEVICE_NAME if active else "CPU (SIMD)",
        "short_name": _OPENCL_SHORT_NAME if active else "CPU",
    }


def _get_kernel(shape, use_umat: bool = False):
    key = (int(shape[0]), int(shape[1]))
    cpu_k = _CPU_KERNEL_CACHE.get(key)
    if cpu_k is None:
        cpu_k = np.ones(key, np.uint8)
        _CPU_KERNEL_CACHE[key] = cpu_k
    if not use_umat:
        return cpu_k
    u_k = _UMAT_KERNEL_CACHE.get(key)
    if u_k is None:
        u_k = cv2.UMat(cpu_k)
        _UMAT_KERNEL_CACHE[key] = u_k
    return u_k


def test():
    log_print("HSV Detection test initialized")
    dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
    _ = cv2.cvtColor(dummy_img, cv2.COLOR_BGR2HSV)
    log_print("HSV conversion done")


# Synchronized with OBS-xUDP-Plugin (VeloNet Color Correction v2.1):
# - Purple (Color Enhancement ON): H[120,160], S[95,255]/V[90,255] retains 50m+ thin
#   outlines while staying above dimmed BG (p95 S<=47, BG ceiling S<90)
# - Yellow (HSV_Color_Ranges.txt): H[20,30], S[100,255], V[100,255]
# - Red (HSV_Color_Ranges.txt): dual wrap-around H[0,10] U H[160,180], S[100,255], V[20,255]
XUDP_HSV_PRESETS = {
    "yellow": (
        (np.array([20, 100, 100], dtype=np.uint8), np.array([30, 255, 255], dtype=np.uint8)),
    ),
    "purple": (
        (np.array([120, 95, 90], dtype=np.uint8), np.array([160, 255, 255], dtype=np.uint8)),
    ),
    "red": (
        (np.array([0, 100, 20], dtype=np.uint8), np.array([10, 255, 255], dtype=np.uint8)),
        (np.array([160, 100, 20], dtype=np.uint8), np.array([180, 255, 255], dtype=np.uint8)),
    ),
}


def compute_hsv_mask(hsv_img, model):
    """Build binary mask from an HSV image and loaded model (supports single or multi-range)."""
    if model is None or hsv_img is None:
        return None
    if len(model) >= 3 and model[2]:
        ranges = model[2]
        mask = cv2.inRange(hsv_img, ranges[0][0], ranges[0][1])
        for lower, upper in ranges[1:]:
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv_img, lower, upper))
        return mask
    return cv2.inRange(hsv_img, model[0], model[1])


def load_model(model_path=None):
    global _model, _class_names, HSV_MIN, HSV_MAX
    config.model_load_error = ""

    try:
        log_print("Loading HSV parameters (xUDP synced)...")
        color_key = str(getattr(config, "color", "purple")).strip().lower()

        if color_key in XUDP_HSV_PRESETS:
            ranges = XUDP_HSV_PRESETS[color_key]
            HSV_MIN = ranges[0][0].copy()
            HSV_MAX = ranges[0][1].copy()
            if len(ranges) > 1:
                _model = (HSV_MIN, HSV_MAX, tuple((lo.copy(), hi.copy()) for lo, hi in ranges))
            else:
                _model = (HSV_MIN, HSV_MAX)
            log_print(f"Loaded xUDP HSV for {color_key}: MIN={HSV_MIN}, MAX={HSV_MAX}")
        elif color_key == "custom":
            HSV_MIN = np.array(
                [
                    getattr(config, "custom_hsv_min_h", 120),
                    getattr(config, "custom_hsv_min_s", 95),
                    getattr(config, "custom_hsv_min_v", 90),
                ],
                dtype=np.uint8,
            )
            HSV_MAX = np.array(
                [
                    getattr(config, "custom_hsv_max_h", 160),
                    getattr(config, "custom_hsv_max_s", 255),
                    getattr(config, "custom_hsv_max_v", 255),
                ],
                dtype=np.uint8,
            )
            _model = (HSV_MIN, HSV_MAX)
            log_print(f"Loaded custom HSV: MIN={HSV_MIN}, MAX={HSV_MAX}")
        else:
            raise ValueError(f"Unknown color {config.color}")

        _class_names = {"color": "Target Color"}
        config.model_classes = list(_class_names.values())
        config.model_file_size = 0
        return _model, _class_names
    except Exception as exc:
        config.model_load_error = f"Failed to load HSV params: {exc}"
        _model, _class_names = None, {}
        return None, {}


def reload_model(model_path=None):
    return load_model(model_path)


def has_color_vertical_line(mask, x, y1, y2):
    x = int(max(0, min(x, mask.shape[1] - 1)))
    y1 = int(max(0, min(y1, mask.shape[0])))
    y2 = int(max(0, min(y2, mask.shape[0])))
    if y2 <= y1:
        return False
    line = mask[y1:y2, x]
    return bool(np.any(line > 0))


def _bbox_area(rect):
    _, _, w, h = rect
    return max(0, int(w)) * max(0, int(h))


def _touches_border(rect, img_w, img_h, margin=1):
    x, y, w, h = rect
    return (
        x <= margin
        or y <= margin
        or (x + w) >= (img_w - margin)
        or (y + h) >= (img_h - margin)
    )


def _boxes_overlap(r1, r2):
    x1, y1, w1, h1 = r1
    x2, y2, w2, h2 = r2
    return (x1 < x2 + w2 and x1 + w1 > x2) and (y1 < y2 + h2 and y1 + h1 > y2)


def _overlap_len(a0, a1, b0, b1):
    return max(0, min(a1, b1) - max(a0, b0))


def _boxes_should_merge(r1, r2, dist_threshold):
    x1, y1, w1, h1 = r1
    x2, y2, w2, h2 = r2
    x1r, y1r = x1 + w1, y1 + h1
    x2r, y2r = x2 + w2, y2 + h2
    h_overlap = _overlap_len(x1, x1r, x2, x2r)
    merged_w = max(x1r, x2r) - min(x1, x2)
    merged_h = max(y1r, y2r) - min(y1, y2)

    # Do not merge two side-by-side player-sized boxes into a wide multi-target box.
    if h1 >= 22 and h2 >= 22 and min(w1, w2) >= 12:
        if h_overlap < 0.45 * min(w1, w2) and merged_w > 0.82 * max(1, merged_h):
            return False

    if _boxes_overlap(r1, r2):
        return True

    h_gap = max(0, max(x1, x2) - min(x1r, x2r))
    v_gap = max(0, max(y1, y2) - min(y1r, y2r))
    v_overlap = _overlap_len(y1, y1r, y2, y2r)

    a1 = max(1, _bbox_area(r1))
    a2 = max(1, _bbox_area(r2))
    size_ratio = min(a1, a2) / max(a1, a2)
    # Merge mainly fragment-like splits; avoid merging similarly sized players.
    small_fragment = size_ratio <= 0.80
    if not small_fragment:
        return False

    intra_dist = (
        max(int(dist_threshold), 8)
        if merged_w <= 0.80 * max(1, merged_h)
        else int(dist_threshold)
    )
    close_h = h_gap <= intra_dist and v_overlap >= 0.55 * min(h1, h2)
    close_v = v_gap <= intra_dist and h_overlap >= 0.45 * min(w1, w2)
    return close_h or close_v


def _split_single_wide_rect(rect, raw_mask, mask, depth=0):
    """Split a wide horizontal cluster of adjacent targets along its upper-body vertical valley."""
    x, y, w, h = rect
    if depth >= 2 or h < 32 or w < 48 or (float(w) / float(h)) < 0.85:
        return [rect]
    upper_h = max(8, int(h * 0.45))
    upper_roi = (raw_mask[y : y + upper_h, x : x + w] > 0).astype(np.float64)
    upper_cols = upper_roi.sum(axis=0)
    smooth = np.convolve(upper_cols, np.ones(3, dtype=np.float64) / 3.0, mode="same")
    min_sub_w = max(14, int(h * 0.42))
    if w < 2 * min_sub_w + 2:
        return [rect]
    s0, s1 = min_sub_w, w - min_sub_w
    best_split = None
    best_score = 1e9
    for k in range(s0, s1):
        l_peak = float(smooth[max(0, k - 30) : max(1, k - 2)].max())
        r_peak = float(smooth[min(w - 1, k + 2) : min(w, k + 30)].max())
        val = float(smooth[k])
        if l_peak >= 4.0 and r_peak >= 4.0 and val <= 0.35 * min(l_peak, r_peak):
            score = val / max(1.0, min(l_peak, r_peak))
            if score < best_score:
                best_score = score
                best_split = k
    if best_split is None:
        return [rect]
    out = []
    for x0, x1 in ((0, best_split), (best_split, w)):
        sub_mask = mask[y : y + h, x + x0 : x + x1]
        ys, xs = np.nonzero(sub_mask)
        if len(xs) < 20:
            continue
        nx = int(x + x0 + xs.min())
        ny = int(y + ys.min())
        nw = int(xs.max() - xs.min() + 1)
        nh = int(ys.max() - ys.min() + 1)
        if nw >= 10 and nh >= 16 and nw * nh >= 120:
            out.extend(_split_single_wide_rect((nx, ny, nw, nh), raw_mask, mask, depth + 1))
    return out if len(out) >= 2 else [rect]


def _split_wide_multi_target_rects(rects, raw_mask, mask):
    """Separate multi-target horizontal blobs before merging boxes."""
    split_rects = []
    split_centers = []
    for r in rects:
        for sr in _split_single_wide_rect(r, raw_mask, mask, depth=0):
            sx, sy, sw, sh = sr
            split_rects.append(sr)
            split_centers.append((sx + sw // 2, sy + sh // 2))
    return split_rects, split_centers


def merge_close_rects(rects, centers, dist_threshold=None):
    if dist_threshold is None:
        dist_threshold = int(getattr(config, "detection_merge_distance", 24))
    dist_threshold = int(max(0, min(dist_threshold, 28)))

    merged = []
    merged_centers = []
    used = [False] * len(rects)

    for i, (r1, c1) in enumerate(zip(rects, centers)):
        if used[i]:
            continue

        x1, y1, w1, h1 = r1
        nx1, ny1 = x1, y1
        nx2, ny2 = x1 + w1, y1 + h1

        changed = True
        while changed:
            changed = False
            current_rect = (nx1, ny1, nx2 - nx1, ny2 - ny1)
            for j, r2 in enumerate(rects):
                if i == j or used[j]:
                    continue
                if _boxes_should_merge(current_rect, r2, dist_threshold):
                    x2, y2, w2, h2 = r2
                    nx1 = min(nx1, x2)
                    ny1 = min(ny1, y2)
                    nx2 = max(nx2, x2 + w2)
                    ny2 = max(ny2, y2 + h2)
                    used[j] = True
                    changed = True

        used[i] = True
        final_w = max(1, nx2 - nx1)
        final_h = max(1, ny2 - ny1)
        final_cx = int(nx1 + final_w // 2)
        final_cy = int(ny1 + final_h // 2)
        merged.append((nx1, ny1, final_w, final_h))
        merged_centers.append((final_cx, final_cy))

    sort_idx = sorted(range(len(merged)), key=lambda idx: _bbox_area(merged[idx]), reverse=True)
    merged = [merged[idx] for idx in sort_idx]
    merged_centers = [merged_centers[idx] for idx in sort_idx]

    return merged, merged_centers


def triggerbot_detect(model, roi):
    if model is None or roi is None:
        return False
    hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = compute_hsv_mask(hsv_roi, model)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return bool(np.any(mask > 0))


def _stabilize_axis_edges(e1, e2, pe1, pe2, hold_count, shimmer_tol):
    """Damp 1px stationary shimmer while tracking micro-strafes and head/body updates immediately."""
    d1 = e1 - pe1
    d2 = e2 - pe2
    ad1 = abs(d1)
    ad2 = abs(d2)
    max_d = max(ad1, ad2)
    min_d = min(ad1, ad2)
    if max_d <= 1 or (min_d <= 1 and max_d <= shimmer_tol and hold_count < 3):
        return pe1, pe2, True
    if max_d <= 3:
        se1 = int(round(pe1 + 0.65 * d1))
        se2 = int(round(pe2 + 0.65 * d2))
        return se1, se2, False
    return e1, e2, False


def _stabilize_detected_rects(rects):
    """Temporally stabilize bounding box edges across consecutive frames to prevent stationary flicker."""
    global _PREV_STABLE_RECTS, _PREV_STABLE_TS
    now = time.perf_counter()
    with _STABILIZE_LOCK:
        if (now - _PREV_STABLE_TS) > 0.25 or not _PREV_STABLE_RECTS:
            _PREV_STABLE_RECTS = [(int(x), int(y), int(w), int(h), 0) for (x, y, w, h) in rects]
            _PREV_STABLE_TS = now
            return rects

        used = [False] * len(_PREV_STABLE_RECTS)
        stabilized = []
        next_state = []

        for x, y, w, h in rects:
            x, y, w, h = int(x), int(y), int(w), int(h)
            cx = x + 0.5 * w
            cy = y + 0.5 * h
            max_center_dist = max(8.0, 0.25 * max(w, h))

            best_idx = -1
            best_dist = 1e9
            for idx, (px, py, pw, ph, _) in enumerate(_PREV_STABLE_RECTS):
                if used[idx]:
                    continue
                if abs(w - pw) > max(10.0, 0.35 * pw) or abs(h - ph) > max(12.0, 0.35 * ph):
                    continue
                dist = math.hypot(cx - (px + 0.5 * pw), cy - (py + 0.5 * ph))
                if dist <= max_center_dist and dist < best_dist:
                    best_dist = dist
                    best_idx = idx

            if best_idx < 0:
                rect = (x, y, w, h)
                stabilized.append(rect)
                next_state.append((x, y, w, h, 0))
                continue

            used[best_idx] = True
            px, py, pw, ph, hold_count = _PREV_STABLE_RECTS[best_idx]
            sx1, sx2, held_x = _stabilize_axis_edges(x, x + w, px, px + pw, hold_count, shimmer_tol=2)
            sy1, sy2, held_y = _stabilize_axis_edges(y, y + h, py, py + ph, hold_count, shimmer_tol=2)
            sw = max(1, sx2 - sx1)
            sh = max(1, sy2 - sy1)
            new_hold = (hold_count + 1) if (held_x or held_y) else 0
            rect = (sx1, sy1, sw, sh)
            stabilized.append(rect)
            next_state.append((sx1, sy1, sw, sh, new_hold))

        _PREV_STABLE_RECTS = next_state
        _PREV_STABLE_TS = now
        return stabilized


def _filter_false_positive_rects(rects, raw_mask):
    """Apply optional upright-aspect, strict raw-pixel, and size-aware hollow checks after target splitting."""
    upright_on = bool(getattr(config, "detection_upright_filter_enabled", True))
    hollow_on = bool(getattr(config, "detection_hollow_filter_enabled", True))
    strict_noise_on = bool(getattr(config, "detection_disable_empty_fallback", True))
    anti_vfx_on = bool(getattr(config, "detection_anti_vfx_enabled", True))
    if not upright_on and not hollow_on and not strict_noise_on and not anti_vfx_on:
        return rects

    img_h, img_w = (raw_mask.shape[:2] if raw_mask is not None else (0, 0))
    kept = []
    for x, y, w, h in rects:
        ix, iy, iw, ih = int(x), int(y), int(w), int(h)
        if iw <= 0 or ih <= 0:
            continue

        if upright_on and (float(iw) / float(ih)) > 2.2:
            continue

        rx1, ry1 = max(0, ix), max(0, iy)
        rx2, ry2 = min(img_w, ix + iw), min(img_h, iy + ih)
        raw_px = (
            int(cv2.countNonZero(raw_mask[ry1:ry2, rx1:rx2]))
            if (raw_mask is not None and img_w > 0 and img_h > 0 and rx2 > rx1 and ry2 > ry1)
            else -1
        )
        if strict_noise_on and raw_px >= 0 and raw_px < 8:
            continue

        # Only run hollow-interior check on medium/close targets so distant enemies still lock.
        if hollow_on and raw_mask is not None and iw >= 18 and ih >= 32 and img_w > 0 and img_h > 0:
            cx1 = max(0, ix + int(round(iw * 0.30)))
            cx2 = min(img_w, ix + int(round(iw * 0.70)))
            cy1 = max(0, iy + int(round(ih * 0.28)))
            cy2 = min(img_h, iy + int(round(ih * 0.68)))
            core_area = max(0, cx2 - cx1) * max(0, cy2 - cy1)
            if core_area >= 16:
                core_fill = float(cv2.countNonZero(raw_mask[cy1:cy2, cx1:cx2])) / float(core_area)
                box_area = max(1, (rx2 - rx1) * (ry2 - ry1))
                raw_box_fill = float(max(0, raw_px)) / float(box_area)
                if core_fill >= 0.55 and raw_box_fill >= 0.38:
                    continue

        # Valorant Anti-VFX filter: reject circular/square purple orbs (Reyna Leer, Astra Star, Omen Blind)
        # and low ground-only ability strips while preserving upright human outline silhouettes.
        if anti_vfx_on and raw_mask is not None and iw >= 16 and ih >= 22 and img_w > 0 and img_h > 0:
            aspect = float(iw) / float(ih)
            if 0.78 <= aspect <= 1.35 and ih <= 85:
                cx1 = max(0, ix + int(round(iw * 0.25)))
                cx2 = min(img_w, ix + int(round(iw * 0.75)))
                cy1 = max(0, iy + int(round(ih * 0.25)))
                cy2 = min(img_h, iy + int(round(ih * 0.75)))
                c_area = max(0, cx2 - cx1) * max(0, cy2 - cy1)
                if c_area >= 12:
                    c_fill = float(cv2.countNonZero(raw_mask[cy1:cy2, cx1:cx2])) / float(c_area)
                    if c_fill >= 0.35:
                        continue
            if iw >= 20 and ih >= 42:
                top_y2 = min(img_h, ry1 + max(4, ih // 4))
                bot_y1 = max(0, ry2 - max(4, ih // 4))
                top_area = max(1, (rx2 - rx1) * max(1, top_y2 - ry1))
                bot_area = max(1, (rx2 - rx1) * max(1, ry2 - bot_y1))
                top_fill = float(cv2.countNonZero(raw_mask[ry1:top_y2, rx1:rx2])) / float(top_area)
                bot_fill = float(cv2.countNonZero(raw_mask[bot_y1:ry2, rx1:rx2])) / float(bot_area)
                if top_fill < 0.015 and bot_fill >= 0.28:
                    continue

        kept.append((ix, iy, iw, ih))
    return kept


def _build_masks_cpu(image, model, morph_mode: str):
    hsv_img = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    raw_mask = compute_hsv_mask(hsv_img, model)

    if morph_mode == "stable":
        open_kernel_size = int(getattr(config, "detection_open_kernel", 3))
        close_kernel_size = int(getattr(config, "detection_close_kernel", 5))
        blur_kernel_size = int(getattr(config, "detection_mask_blur", 3))
        open_kernel_size = max(1, min(open_kernel_size, 9))
        close_kernel_size = max(1, min(close_kernel_size, 13))
        blur_kernel_size = max(1, min(blur_kernel_size, 7))
        if open_kernel_size % 2 == 0:
            open_kernel_size += 1
        if close_kernel_size % 2 == 0:
            close_kernel_size += 1
        if blur_kernel_size % 2 == 0:
            blur_kernel_size += 1
        open_kernel = _get_kernel((open_kernel_size, open_kernel_size), use_umat=False)
        close_kernel = _get_kernel((close_kernel_size, close_kernel_size), use_umat=False)
        mask = cv2.morphologyEx(raw_mask, cv2.MORPH_OPEN, open_kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel)
        if blur_kernel_size >= 3:
            mask = cv2.medianBlur(mask, blur_kernel_size)
    else:
        legacy_kernel_h = int(getattr(config, "detection_legacy_kernel_h", 9))
        legacy_dilate_iterations = int(getattr(config, "detection_legacy_dilate_iterations", 1))
        legacy_kernel_h = max(1, min(legacy_kernel_h, 30))
        legacy_dilate_iterations = max(0, min(legacy_dilate_iterations, 2))
        close_h = max(11, min(legacy_kernel_h, 15))
        close_kernel = _get_kernel((close_h, 7), use_umat=False)
        mask = cv2.morphologyEx(raw_mask, cv2.MORPH_CLOSE, close_kernel)
        if legacy_dilate_iterations > 0:
            dilate_kernel = _get_kernel((5, 5), use_umat=False)
            mask = cv2.dilate(mask, dilate_kernel, iterations=1)
    return raw_mask, mask


def _build_masks_gpu_opencl(image, model, morph_mode: str):
    """Execute BGR->HSV, inRange, and morphology on OpenCL GPU (UMat) to share load with CPU."""
    u_img = cv2.UMat(image)
    u_hsv = cv2.cvtColor(u_img, cv2.COLOR_BGR2HSV)
    u_raw_mask = compute_hsv_mask(u_hsv, model)

    if morph_mode == "stable":
        open_kernel_size = int(getattr(config, "detection_open_kernel", 3))
        close_kernel_size = int(getattr(config, "detection_close_kernel", 5))
        blur_kernel_size = int(getattr(config, "detection_mask_blur", 3))
        open_kernel_size = max(1, min(open_kernel_size, 9))
        close_kernel_size = max(1, min(close_kernel_size, 13))
        blur_kernel_size = max(1, min(blur_kernel_size, 7))
        if open_kernel_size % 2 == 0:
            open_kernel_size += 1
        if close_kernel_size % 2 == 0:
            close_kernel_size += 1
        if blur_kernel_size % 2 == 0:
            blur_kernel_size += 1
        open_kernel = _get_kernel((open_kernel_size, open_kernel_size), use_umat=True)
        close_kernel = _get_kernel((close_kernel_size, close_kernel_size), use_umat=True)
        u_mask = cv2.morphologyEx(u_raw_mask, cv2.MORPH_OPEN, open_kernel)
        u_mask = cv2.morphologyEx(u_mask, cv2.MORPH_CLOSE, close_kernel)
        if blur_kernel_size >= 3:
            u_mask = cv2.medianBlur(u_mask, blur_kernel_size)
    else:
        legacy_kernel_h = int(getattr(config, "detection_legacy_kernel_h", 9))
        legacy_dilate_iterations = int(getattr(config, "detection_legacy_dilate_iterations", 1))
        legacy_kernel_h = max(1, min(legacy_kernel_h, 30))
        legacy_dilate_iterations = max(0, min(legacy_dilate_iterations, 2))
        close_h = max(11, min(legacy_kernel_h, 15))
        close_kernel = _get_kernel((close_h, 7), use_umat=True)
        u_mask = cv2.morphologyEx(u_raw_mask, cv2.MORPH_CLOSE, close_kernel)
        if legacy_dilate_iterations > 0:
            dilate_kernel = _get_kernel((5, 5), use_umat=True)
            u_mask = cv2.dilate(u_mask, dilate_kernel, iterations=1)

    return u_raw_mask.get(), u_mask.get()


def perform_detection(model, image, roi_offset=(0, 0), stabilize: bool = True):
    if model is None or image is None:
        return [], None

    img_h, img_w = image.shape[:2]
    frame_area = max(1, img_h * img_w)

    # Reference-like morphology path (close + dilate) is the default because it
    # keeps thin color edges that OPEN often removes completely.
    # For small frames (<= 400x400, e.g. xUDP 320x320 or FOV ROI), CPU AVX2/SIMD is ~3.8x
    # faster than OpenCL UMat due to PCIe upload/readback overhead.
    morph_mode = str(getattr(config, "detection_morph_mode", "legacy")).strip().lower()
    if frame_area > 160000 and is_gpu_opencl_active():
        try:
            raw_mask, mask = _build_masks_gpu_opencl(image, model, morph_mode)
        except Exception:
            raw_mask, mask = _build_masks_cpu(image, model, morph_mode)
    else:
        raw_mask, mask = _build_masks_cpu(image, model, morph_mode)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    # If morphology erased all pixels, fall back to raw mask instead of returning empty.
    if not contours and cv2.countNonZero(raw_mask) > 0:
        mask = raw_mask
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rects, centers = [], []
    min_bbox_area = int(getattr(config, "detection_min_bbox_area", max(36, int(frame_area * 0.00025))))
    min_contour_area = float(
        getattr(config, "detection_min_contour_area", max(8, int(frame_area * 0.00008)))
    )
    min_fill_ratio = float(getattr(config, "detection_min_fill_ratio", 0.03))
    edge_reject_area = int(
        getattr(config, "detection_edge_reject_area", max(80, int(frame_area * 0.0006)))
    )
    edge_min_contour_area = float(
        getattr(config, "detection_edge_min_contour_area", max(30, int(frame_area * 0.0002)))
    )
    edge_min_side = int(getattr(config, "detection_edge_min_side", 4))
    border_margin = int(getattr(config, "detection_border_margin", 0))
    min_w = int(getattr(config, "detection_min_width", 3))
    min_h = int(getattr(config, "detection_min_height", 4))
    min_aspect = float(getattr(config, "detection_min_aspect", 0.04))
    max_aspect = float(getattr(config, "detection_max_aspect", 6.0))
    require_vertical_line = bool(getattr(config, "detection_require_vertical_line", False))
    min_contour_points = int(getattr(config, "detection_min_contour_points", 5))

    if morph_mode != "stable":
        # Prevent stale strict settings from killing detection in legacy mode.
        min_bbox_area = min(min_bbox_area, max(48, int(frame_area * 0.00045)))
        min_contour_area = min(min_contour_area, max(10, int(frame_area * 0.00010)))
        min_fill_ratio = min(min_fill_ratio, 0.08)

    for c in contours:
        contour_area = float(cv2.contourArea(c))
        if len(c) < min_contour_points and not (
            len(c) >= 4 and contour_area >= max(40.0, min_contour_area * 2.5)
        ):
            continue

        x, y, w, h = cv2.boundingRect(c)
        bbox_area = int(w) * int(h)
        if contour_area < min_contour_area:
            continue
        if bbox_area < min_bbox_area:
            continue
        if int(w) < min_w or int(h) < min_h:
            continue

        fill_ratio = contour_area / max(float(bbox_area), 1.0)
        if fill_ratio < min_fill_ratio:
            continue

        aspect = float(w) / max(float(h), 1.0)
        if aspect < min_aspect or aspect > max_aspect:
            continue

        touches_border = _touches_border((x, y, w, h), img_w, img_h, margin=border_margin)
        if touches_border:
            if bbox_area < edge_reject_area:
                continue
            if contour_area < edge_min_contour_area:
                continue
            if min(int(w), int(h)) < edge_min_side:
                continue

        cx, cy = x + w // 2, y + h // 2
        if require_vertical_line and not has_color_vertical_line(mask, cx, y, y + h):
            continue

        rects.append((x, y, w, h))
        centers.append((cx, cy))

    # Fallback pass on raw mask with minimal checks if filtered pass found nothing.
    if (
        not rects
        and not bool(getattr(config, "detection_disable_empty_fallback", True))
        and cv2.countNonZero(raw_mask) > 0
    ):
        raw_contours, _ = cv2.findContours(raw_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        loose_min_area = max(20, int(min_bbox_area * 0.5))
        for c in raw_contours:
            x, y, w, h = cv2.boundingRect(c)
            if int(w) * int(h) < loose_min_area:
                continue
            cx, cy = x + w // 2, y + h // 2
            rects.append((x, y, w, h))
            centers.append((cx, cy))

    if not rects:
        return [], mask

    rects, centers = _split_wide_multi_target_rects(rects, raw_mask, mask)

    rects_centers = sorted(zip(rects, centers), key=lambda rc: _bbox_area(rc[0]), reverse=True)
    rects = [rc[0] for rc in rects_centers]
    centers = [rc[1] for rc in rects_centers]

    merged_rects, _ = merge_close_rects(rects, centers)
    merged_rects = _filter_false_positive_rects(merged_rects, raw_mask)
    if not merged_rects:
        return [], mask
    ox, oy = int(roi_offset[0]), int(roi_offset[1])
    if ox != 0 or oy != 0:
        merged_rects = [(rx + ox, ry + oy, rw, rh) for (rx, ry, rw, rh) in merged_rects]
    if stabilize:
        merged_rects = _stabilize_detected_rects(merged_rects)
    return [{"class": "player", "bbox": r, "confidence": 1.0} for r in merged_rects], mask


def get_class_names():
    return _class_names


def get_model_size(model_path=None):
    return 0
