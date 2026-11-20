import time

from src.utils.debug_logger import log_print
import cv2
import numpy as np

from src.utils.config import config


_model = None
_class_names = {}
HSV_MIN = None
HSV_MAX = None

# Wider HSV presets to better tolerate compression/lighting variance. One table
# only: the AI enemy-outline guard reads the exact same band the colour pass
# uses, so "purple" can never mean two different things in two engines.
ENEMY_OUTLINE_HSV_PRESETS = {
    "yellow": ((18, 80, 80), (40, 255, 255)),
    "purple": ((125, 60, 80), (170, 255, 255)),
    "red": ((0, 95, 95), (4, 235, 255)),
}

_AI_OUTLINE_LOG_INTERVAL = 2.0
_last_ai_outline_log_time = 0.0


def enemy_outline_hsv_range(color=None, config_module=None):
    """Return ``(hsv_min, hsv_max)`` for the enemy highlight colour.

    This is the single source of the HSV band: ``load_model`` uses it for the
    colour pass and the AI enemy-outline guard uses it to verify that a box
    really has the enemy highlight drawn around it. ``color`` defaults to
    ``config.color``; ``custom`` reads the ``custom_hsv_*`` fields.

    Raises ``ValueError`` for an unknown colour **and** for a reversed custom
    band (``min > max`` on any channel) so callers can decide between failing
    closed (colour pass) and failing open (AI guard). A reversed band is not
    merely "no match": ``cv2.inRange`` returns an all-zero mask, so the colour
    pass would detect nothing and the AI guard would drop every box -- both
    silently, which is exactly the failure mode this validation exists to stop.
    """
    module = config_module if config_module is not None else config
    name = str(color if color is not None else getattr(module, "color", "purple")).strip().lower()
    if name in ENEMY_OUTLINE_HSV_PRESETS:
        low, high = ENEMY_OUTLINE_HSV_PRESETS[name]
        return (
            np.array(low, dtype=np.uint8),
            np.array(high, dtype=np.uint8),
        )
    if name == "custom":
        try:
            low = [
                int(round(float(getattr(module, "custom_hsv_min_h", 0)))),
                int(round(float(getattr(module, "custom_hsv_min_s", 0)))),
                int(round(float(getattr(module, "custom_hsv_min_v", 0)))),
            ]
            high = [
                int(round(float(getattr(module, "custom_hsv_max_h", 179)))),
                int(round(float(getattr(module, "custom_hsv_max_s", 255)))),
                int(round(float(getattr(module, "custom_hsv_max_v", 255)))),
            ]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid custom HSV band: {exc}") from exc
        # Config.from_dict does not clamp the custom HSV fields (the HUD sliders
        # do, but a hand-edited config.json or an imported profile does not), so
        # the band has to be checked where it is consumed, not where it is typed.
        if any(lo > hi for lo, hi in zip(low, high)):
            raise ValueError(f"Reversed custom HSV band: MIN={low} MAX={high}")
        try:
            return (
                np.array(low, dtype=np.uint8),
                np.array(high, dtype=np.uint8),
            )
        except Exception as exc:
            # Out-of-range values must not reach ``cv2.inRange`` (numpy either
            # refuses them or wraps them, and a wrapped band silently matches
            # the wrong pixels); report the band as unusable instead.
            raise ValueError(f"Invalid custom HSV band: {exc}") from exc
    raise ValueError(f"Unknown color {name}")


def test():
    log_print("HSV Detection test initialized")
    dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
    _ = cv2.cvtColor(dummy_img, cv2.COLOR_BGR2HSV)
    log_print("HSV conversion done")


def load_model(model_path=None):
    global _model, _class_names, HSV_MIN, HSV_MAX
    config.model_load_error = ""

    try:
        log_print("Loading HSV parameters...")
        HSV_MIN, HSV_MAX = enemy_outline_hsv_range(config.color)
        if str(config.color).strip().lower() == "custom":
            log_print(f"Loaded custom HSV: MIN={HSV_MIN}, MAX={HSV_MAX}")
        else:
            log_print(f"Loaded HSV for {config.color}")

        _model = (HSV_MIN, HSV_MAX)
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

    # Merged bounding box geometry
    nx1 = min(x1, x2)
    ny1 = min(y1, y2)
    nx2 = max(x1r, x2r)
    ny2 = max(y1r, y2r)
    merged_w = nx2 - nx1
    merged_h = ny2 - ny1

    h_overlap = _overlap_len(x1, x1r, x2, x2r)
    v_overlap = _overlap_len(y1, y1r, y2, y2r)
    min_h = min(h1, h2)
    max_h = max(h1, h2)
    min_w = min(w1, w2)
    max_w = max(w1, w2)

    a1 = max(1, _bbox_area(r1))
    a2 = max(1, _bbox_area(r2))

    # Anti-bridge rule 1: Reject horizontal side-by-side merging of distinct player silhouettes.
    # If two boxes share vertical overlap (standing next to each other), but merging them
    # would create an unnaturally wide box (> 1.20 * individual box width or aspect ratio > 0.55),
    # they are separate entities and MUST NOT be merged unless one is > 80% nested inside the other.
    if min_h >= 25 and v_overlap >= 0.40 * min_h:
        if merged_w > 1.20 * max_w or (merged_w / float(max_h)) > 0.55:
            overlap_area = h_overlap * v_overlap
            if overlap_area < 0.80 * min(a1, a2):
                return False

    # Anti-bridge rule 2: If both boxes are independently viable player bboxes, do not merge.
    min_bbox_area = int(getattr(config, "detection_min_bbox_area", 90))
    if a1 >= min_bbox_area and a2 >= min_bbox_area and h1 >= 25 and h2 >= 25:
        overlap_area = h_overlap * v_overlap
        if overlap_area < 0.80 * min(a1, a2):
            return False

    if _boxes_overlap(r1, r2):
        return True

    h_gap = max(0, max(x1, x2) - min(x1r, x2r))
    v_gap = max(0, max(y1, y2) - min(y1r, y2r))

    size_ratio = min(a1, a2) / max(a1, a2)
    # Merge mainly fragment-like splits; avoid merging similarly sized players.
    small_fragment = size_ratio <= 0.80
    if not small_fragment:
        return False

    close_h = h_gap <= dist_threshold and v_overlap >= 0.60 * min_h
    close_v = v_gap <= dist_threshold and h_overlap >= 0.60 * min_w
    return close_h or close_v


def _build_rect_grid(rects, cell):
    """Bucket rect indices into a uniform grid (linear in rect count)."""
    grid = {}
    for idx, (x, y, w, h) in enumerate(rects):
        x = int(x)
        y = int(y)
        gx0, gx1 = x // cell, (x + int(w)) // cell
        gy0, gy1 = y // cell, (y + int(h)) // cell
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                grid.setdefault((gx, gy), []).append(idx)
    return grid


def _expand_candidates(grid, cell, nx1, ny1, nx2, ny2):
    """Indices of rects inside the aggregate bbox grown by one cell, ascending.

    _boxes_should_merge only true when the gap is <= dist_threshold on at least
    one axis, and cell >= dist_threshold, so the grown bbox is a complete
    superset of merge candidates.

    Candidates are returned in ascending index order. Greedy merging tests
    against the growing aggregate bbox, so its outcome depends on visit order:
    unsorted dict-bucket order produced different clusters than the original
    linear scan. Sorting restores exact parity with that scan.
    """
    gx0, gx1 = (nx1 - cell) // cell, (nx2 + cell) // cell
    gy0, gy1 = (ny1 - cell) // cell, (ny2 + cell) // cell
    if (gx1 - gx0 + 1) * (gy1 - gy0 + 1) > len(grid):
        # Aggregate spans more cells than there are buckets to probe; a single
        # set union over all rects is cheaper and still a superset.
        return sorted({idx for bucket in grid.values() for idx in bucket})
    found = set()
    for gx in range(gx0, gx1 + 1):
        for gy in range(gy0, gy1 + 1):
            bucket = grid.get((gx, gy))
            if bucket:
                found.update(bucket)
    return sorted(found)


def merge_close_rects(rects, centers, dist_threshold=None):
    if not rects:
        return [], []
    if dist_threshold is None:
        dist_threshold = int(getattr(config, "detection_merge_distance", 12))
    dist_threshold = int(max(0, min(dist_threshold, 18)))

    merged = []
    merged_centers = []
    used = [False] * len(rects)
    cell = max(8, dist_threshold * 2 + 1)
    grid = _build_rect_grid(rects, cell)

    for i, r1 in enumerate(rects):
        if used[i]:
            continue

        x1, y1, w1, h1 = r1
        nx1, ny1 = x1, y1
        nx2, ny2 = x1 + w1, y1 + h1

        changed = True
        while changed:
            changed = False
            current_rect = (nx1, ny1, nx2 - nx1, ny2 - ny1)
            tested = set()
            for j in _expand_candidates(grid, cell, nx1, ny1, nx2, ny2):
                if i == j or used[j] or j in tested:
                    continue
                tested.add(j)
                r2 = rects[j]
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
    mask = cv2.inRange(hsv_roi, model[0], model[1])
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return bool(np.any(mask > 0))


# Global kernel cache for morphology operations to avoid per-frame allocations
_KERNEL_CACHE = {}

def _get_cached_kernel(h: int, w: int) -> np.ndarray:
    key = (int(h), int(w))
    k = _KERNEL_CACHE.get(key)
    if k is None:
        k = np.ones((int(h), int(w)), np.uint8)
        _KERNEL_CACHE[key] = k
    return k


class DetectionFrame:
    """Result of one :func:`analyze` call, optionally computed on a sub-rectangle.

    ``mask``/``raw_mask`` are sized to ``roi`` when the HSV pass used a ROI, so
    callers that need a full-frame image must ask for one explicitly with
    :meth:`full_mask`. That allocation is therefore only paid on frames where a
    consumer (the throttled MASK preview) actually asks for the image.

    An AI-produced frame carries no mask until something asks for one: its mask
    is nothing but the detected boxes rasterised onto a frame-sized array, so
    building it eagerly cost a full-frame allocation plus a ``countNonZero``
    over ~2 MP on *every* frame, even while the triggerbot that consumes it was
    disabled. ``mask_factory`` defers that work to the first ``mask`` /
    ``raw_mask`` / ``mask_nonzero`` / ``full_mask()`` access. ``has_mask``
    answers "is a mask available" without triggering the build, so the preview
    gate can stay lazy.
    """

    __slots__ = (
        "detections",
        "_mask",
        "_raw_mask",
        "_mask_factory",
        "roi",
        "roi_used",
        "_mask_nonzero",
        "frame_shape",
        "source",
        "_full_mask",
    )

    def __init__(self, detections, mask, raw_mask, roi, roi_used, mask_nonzero, frame_shape,
                 source="hsv", mask_factory=None):
        self.detections = detections
        self._mask = mask
        self._raw_mask = raw_mask
        self._mask_factory = mask_factory
        self.roi = roi
        self.roi_used = roi_used
        self._mask_nonzero = None if mask_nonzero is None else int(mask_nonzero)
        self.frame_shape = frame_shape
        # Which pass produced this frame. An ``ai`` mask is rasterised from the
        # detected boxes, not measured from pixels, so colour statistics such as
        # the anti-smoke fill/density heuristics do not apply to it.
        self.source = source
        self._full_mask = None

    def _materialise_mask(self):
        """Build the deferred mask, at most once."""
        if self._mask is None and self._mask_factory is not None:
            factory, self._mask_factory = self._mask_factory, None
            mask = factory()
            self._mask = mask
            # ``mask`` and ``raw_mask`` are the same array for an AI frame; the
            # raw copy exists for the HSV pass, which keeps an un-morphed mask.
            self._raw_mask = mask
            if self._mask_nonzero is None:
                self._mask_nonzero = (
                    int(cv2.countNonZero(mask)) if mask is not None and mask.size else 0
                )

    @property
    def mask(self):
        self._materialise_mask()
        return self._mask

    @property
    def raw_mask(self):
        self._materialise_mask()
        return self._raw_mask

    @property
    def mask_nonzero(self):
        if self._mask_nonzero is None:
            self._materialise_mask()
        return int(self._mask_nonzero or 0)

    @property
    def has_mask(self):
        """True when a mask image exists or can still be produced on demand.

        Never triggers the deferred build: a consumer that only *checks* would
        otherwise pay the allocation it is trying to avoid.
        """
        if self._mask is not None and self._mask.size > 0:
            return True
        return self._mask_factory is not None

    def empty(self):
        return not self.detections

    def full_mask(self):
        """Return the mask in full-frame coordinates (lazily allocated)."""
        if self._full_mask is not None:
            return self._full_mask
        mask = self.mask
        if self.frame_shape is None:
            self._full_mask = mask
            return mask

        frame_h = int(self.frame_shape[0])
        frame_w = int(self.frame_shape[1])
        if mask is None or mask.size == 0 or self.roi is None:
            # Nothing was analysed (empty/invalid ROI): an all-zero frame-sized
            # mask is the honest answer, and keeps preview code shape-safe.
            self._full_mask = np.zeros((frame_h, frame_w), np.uint8)
            return self._full_mask

        if mask.shape[0] == frame_h and mask.shape[1] == frame_w:
            # Already frame-sized: either no ROI was used, or the ROI happened
            # to equal the frame. Either way nothing to paste.
            self._full_mask = mask
            return mask

        x0, y0, _x1, _y1 = self.roi
        canvas = np.zeros((frame_h, frame_w), np.uint8)
        h = min(mask.shape[0], max(0, frame_h - y0))
        w = min(mask.shape[1], max(0, frame_w - x0))
        if h > 0 and w > 0:
            canvas[y0:y0 + h, x0:x0 + w] = mask[:h, :w]
        self._full_mask = canvas
        return canvas


def _resolve_roi(roi, frame_w, frame_h):
    """Normalise a caller-supplied ROI.

    Returns ``(use_roi, box, invalid)``. ``box`` is clamped to the frame and
    ``use_roi`` is False when the ROI covers so much of the frame that cropping
    would only add offset arithmetic and border noise. ``invalid`` is True when
    the caller asked for a ROI that contains no pixel at all (``x1 <= x0`` or
    ``y1 <= y0``): the track thread must get an empty result instead of an
    exception.
    """
    if roi is None:
        return False, None, False
    try:
        x0, y0, x1, y1 = [int(round(float(v))) for v in tuple(roi)[:4]]
    except Exception:
        return False, None, False

    x0 = max(0, min(x0, frame_w - 1))
    y0 = max(0, min(y0, frame_h - 1))
    x1 = max(0, min(x1, frame_w))
    y1 = max(0, min(y1, frame_h))
    if x1 <= x0 or y1 <= y0:
        return True, None, True

    try:
        max_fraction = float(getattr(config, "detection_roi_max_fraction", 0.70))
    except Exception:
        max_fraction = 0.70
    if max_fraction < 1.0:
        frame_area = float(max(1, frame_w * frame_h))
        if ((x1 - x0) * (y1 - y0)) / frame_area >= max_fraction:
            return False, None, False
    return True, (x0, y0, x1, y1), False


def _analyze_region(model, sub_image, frame_w, frame_h, offset_x, offset_y):
    """Run the HSV detection chain on ``sub_image`` and return frame-space rects.

    Thresholds are derived from the *full* frame area, not from the analysed
    rectangle, so cropping the region does not silently rescale the size
    filters. Border rejection is evaluated in frame coordinates for the same
    reason: a bbox touching the inner edge of a ROI is not touching the frame.
    """
    hsv_img = cv2.cvtColor(sub_image, cv2.COLOR_BGR2HSV)
    raw_mask = cv2.inRange(hsv_img, model[0], model[1])
    # Morphology below always returns a fresh array, so raw_mask stays intact
    # without a defensive copy.
    mask = raw_mask
    raw_nonzero = cv2.countNonZero(raw_mask)

    # Reference-like morphology path (close + dilate) is the default because it
    # keeps thin color edges that OPEN often removes completely.
    morph_mode = str(getattr(config, "detection_morph_mode", "legacy")).strip().lower()
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
        open_kernel = _get_cached_kernel(open_kernel_size, open_kernel_size)
        close_kernel = _get_cached_kernel(close_kernel_size, close_kernel_size)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel)
        if blur_kernel_size >= 3:
            mask = cv2.medianBlur(mask, blur_kernel_size)
    else:
        legacy_kernel_w = int(getattr(config, "detection_legacy_kernel_w", 7))
        legacy_kernel_h = int(getattr(config, "detection_legacy_kernel_h", 5))
        legacy_dilate_iterations = int(getattr(config, "detection_legacy_dilate_iterations", 0))
        legacy_kernel_w = max(1, min(legacy_kernel_w, 40))
        legacy_kernel_h = max(1, min(legacy_kernel_h, 30))
        legacy_dilate_iterations = max(0, min(legacy_dilate_iterations, 3))
        legacy_kernel = _get_cached_kernel(legacy_kernel_h, legacy_kernel_w)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, legacy_kernel)
        if legacy_dilate_iterations > 0:
            mask = cv2.dilate(mask, legacy_kernel, iterations=legacy_dilate_iterations)

    # If morphology erased all pixels, fall back to raw mask instead of returning empty.
    # One countNonZero for the raw mask: the same value answers both this
    # decision and the raw fallback pass below.
    if cv2.countNonZero(mask) == 0 and raw_nonzero > 0:
        mask = raw_mask

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rects, centers = [], []

    frame_area = max(1, int(frame_w) * int(frame_h))
    # Thresholds are the configured ones, used verbatim. The legacy morphology
    # branch used to clamp them down (bbox/contour to 48/10 px, fill ratio to
    # 0.08) which let the 15x9 close+dilate kernel turn a 3x3 dust speck into a
    # "player": the clamp, not the user's config, decided what a target was.
    # A missing key falls back to the Config default (120/40/0.16), never lower.
    min_bbox_area = int(getattr(config, "detection_min_bbox_area", 120))
    min_contour_area = float(getattr(config, "detection_min_contour_area", 40))
    min_fill_ratio = float(getattr(config, "detection_min_fill_ratio", 0.16))
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

    # Evidence measured on the *un-morphed* mask. The legacy kernel may join
    # colour fragments, but it must not create size: a 3x3 speck that close+
    # dilate turns into an ~18x12 blob still has raw_rw=raw_rh=3 here, and a
    # 2x40 scratch still has raw_rh=2. Measuring on ``mask`` would re-apply the
    # kernel's own growth and let the noise through.
    min_raw_pixels = max(12, int(min_contour_area))

    def _raw_evidence(x, y, w, h):
        """Original-pixel evidence for one candidate box.

        Returns ``(pixels, raw_w, raw_h)``: how many *un-morphed* pixels the box
        really holds, and the extent those pixels actually span inside it. The
        kernel can connect fragments, so the raw crop is tighter than the box;
        that gap is precisely what a dilated speck exploits.
        """
        raw_crop = raw_mask[y:y + int(h), x:x + int(w)]
        if raw_crop.size == 0:
            return 0, 0, 0
        pixels = int(cv2.countNonZero(raw_crop))
        if pixels <= 0:
            return 0, 0, 0
        columns = np.flatnonzero(np.any(raw_crop > 0, axis=0))
        rows = np.flatnonzero(np.any(raw_crop > 0, axis=1))
        if columns.size == 0 or rows.size == 0:
            return pixels, 0, 0
        raw_w = int(columns[-1]) - int(columns[0]) + 1
        raw_h = int(rows[-1]) - int(rows[0]) + 1
        return pixels, raw_w, raw_h

    for c in contours:
        if len(c) < min_contour_points:
            continue

        x, y, w, h = cv2.boundingRect(c)
        bbox_area = int(w) * int(h)
        contour_area = float(cv2.contourArea(c))
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

        # Reject tiny noise specks that were artificially inflated by dilation:
        # the candidate needs enough original pixels and the original pixels
        # themselves must already span the minimum target size. Evaluated last
        # among the cheap filters so the extent scan only runs on survivors
        # (the ROI perf budget is 3.8 ms per frame).
        raw_pixels, raw_rw, raw_rh = _raw_evidence(x, y, w, h)
        if raw_pixels < min_raw_pixels:
            continue
        if raw_rw < min_w or raw_rh < min_h:
            continue

        touches_border = _touches_border(
            (x + offset_x, y + offset_y, w, h), frame_w, frame_h, margin=border_margin
        )
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

        # Composite fused-player decomposition:
        # A single human player silhouette has aspect ratio w/h typically 0.20 to 0.50.
        # When two adjacent enemies fuse into one contour (aspect >= 0.58 and w >= 32, h >= 35),
        # decompose into two distinct entities so aimbot locks onto an actual head rather than empty air between them.
        if aspect >= 0.58 and int(w) >= 32 and int(h) >= 35:
            half_w = int(w) // 2
            rects.append((x + offset_x, y + offset_y, half_w, h))
            centers.append((x + offset_x + half_w // 2, y + offset_y + h // 2))
            rects.append((x + offset_x + half_w, y + offset_y, int(w) - half_w, h))
            centers.append((x + offset_x + half_w + (int(w) - half_w) // 2, y + offset_y + h // 2))
        else:
            rects.append((x + offset_x, y + offset_y, w, h))
            centers.append((cx + offset_x, cy + offset_y))

    # Fallback pass on the raw mask when the filtered pass found nothing but the
    # frame does contain colour. It exists to recover a frame the morphology
    # erased -- it is *not* a back door for noise: it applies the same evidence
    # gates as the main pass (full bbox area, contour points, fill ratio, and
    # the raw pixel/extent gate), with no halved thresholds.
    if not rects and raw_nonzero > 0:
        raw_contours, _ = cv2.findContours(raw_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in raw_contours:
            if len(c) < min_contour_points:
                continue
            x, y, w, h = cv2.boundingRect(c)
            bbox_area = int(w) * int(h)
            if bbox_area < min_bbox_area:
                continue
            if int(w) < min_w or int(h) < min_h:
                continue
            contour_area = float(cv2.contourArea(c))
            fill_ratio = contour_area / max(float(bbox_area), 1.0)
            if fill_ratio < min_fill_ratio:
                continue
            aspect = float(w) / max(float(h), 1.0)
            if aspect < min_aspect or aspect > max_aspect:
                continue
            if _touches_border((x + offset_x, y + offset_y, w, h), frame_w, frame_h, margin=border_margin):
                if bbox_area < edge_reject_area:
                    continue
            raw_pixels, raw_rw, raw_rh = _raw_evidence(x, y, w, h)
            if raw_pixels < min_raw_pixels:
                continue
            if raw_rw < min_w or raw_rh < min_h:
                continue
            cx, cy = x + w // 2, y + h // 2
            rects.append((x + offset_x, y + offset_y, w, h))
            centers.append((cx + offset_x, cy + offset_y))

    if not rects:
        return [], mask, raw_mask

    rects_centers = sorted(zip(rects, centers), key=lambda rc: _bbox_area(rc[0]), reverse=True)
    rects = [rc[0] for rc in rects_centers]
    centers = [rc[1] for rc in rects_centers]

    merged_rects, _ = merge_close_rects(rects, centers)
    return [{"class": "player", "bbox": r, "confidence": 1.0} for r in merged_rects], mask, raw_mask


def _ai_detection_mask(ai_detections, frame_h, frame_w):
    """Rasterise AI bboxes into the same mask contract the HSV pass produces.

    The rest of the pipeline (Triggerbot FOV slicing, MASK preview, anti-smoke
    features, head refinement) reads ``mask``/``raw_mask`` and assumes they
    cover the pixels it asks about. Returning ``None`` there used to be
    harmless because only the HSV pass could produce detections; now an AI-only
    run (no HSV params loaded) also returns detections, and a ``None`` mask
    makes ``Triggerbot`` fall back to ``cv2.inRange(hsv, model[0], model[1])``
    on a ``None`` model -- a per-frame ``TypeError`` swallowed by
    ``normal.py``, i.e. a silently dead triggerbot.

    The mask is full-frame rather than ROI-sized on purpose: the trigger ROI is
    selected independently of the detection ROI, and a mask that does not cover
    it cannot be sliced (``slice_mask_for_roi`` returns ``None``), which drops
    the caller back onto the same missing-model path. A full-frame mask is
    always sliceable, and detections are already reported in frame coordinates.
    """
    mask = np.zeros((max(1, int(frame_h)), max(1, int(frame_w))), np.uint8)
    mask_h, mask_w = mask.shape
    for det in ai_detections or []:
        try:
            bx, by, bw, bh = [int(round(float(v))) for v in det["bbox"][:4]]
        except Exception:
            continue
        mx1 = max(0, min(bx, mask_w))
        my1 = max(0, min(by, mask_h))
        mx2 = max(mx1, min(bx + max(1, bw), mask_w))
        my2 = max(my1, min(by + max(1, bh), mask_h))
        if mx2 > mx1 and my2 > my1:
            mask[my1:my2, mx1:mx2] = 255
    return mask


def _ready_ai_detector():
    """The configured AI detector when it can actually run, else ``None``.

    An enabled-but-unusable AI setup (no ``onnxruntime``, model file missing,
    load failure) must not silently detect nothing: callers fall back to the
    colour pass, which is what ``models/README.md`` promises.
    """
    if not bool(getattr(config, "ai_detection_enabled", False)):
        return None
    try:
        from src.utils.ai_detection import get_ai_detector
        detector = get_ai_detector()
    except Exception as exc:
        log_print(f"[AI] Detector unavailable: {exc}")
        return None
    return detector if detector is not None and detector.is_ready() else None


def _enemy_outline_filter_mode():
    """Normalise ``config.ai_enemy_outline_filter`` to ``auto``/``on``/``off``."""
    raw = str(getattr(config, "ai_enemy_outline_filter", "auto")).strip().lower()
    return raw if raw in ("auto", "on", "off") else "auto"


def _should_filter_enemy_outline(detector, mode):
    """Whether the enemy-outline guard must run for this detector and mode.

    ``auto`` is deliberately narrow: it only fires for a *real* detector whose
    ``class_names`` is an actual ``list``/``tuple`` without a ``teammate``
    class. The ``isinstance`` test comes first because the whole existing AI
    test-suite drives ``analyze`` with a plain ``MagicMock`` detector and a
    black frame: a mock's ``class_names`` is another mock, so the guard stays
    out of those tests instead of silently filtering every box away.
    """
    if mode == "off":
        return False
    if mode == "on":
        return True
    try:
        names = getattr(detector, "class_names", None)
        if not isinstance(names, (list, tuple)):
            return False
        return not bool(detector.supports_teammate_class())
    except Exception:
        return False


def _log_enemy_outline_result(kept, total, mode):
    """Throttled one-liner: the guard runs at frame rate, the log must not."""
    global _last_ai_outline_log_time
    now = time.monotonic()
    if (now - _last_ai_outline_log_time) < _AI_OUTLINE_LOG_INTERVAL:
        return
    _last_ai_outline_log_time = now
    try:
        clue = str(getattr(config, "color", "purple"))
        min_px = int(getattr(config, "ai_enemy_outline_min_pixels", 4))
    except Exception:
        clue, min_px = "purple", 4
    log_print(
        f"[AI] Enemy outline guard: kept {kept}/{total} boxes "
        f"(color={clue}, min_px={min_px}, mode={mode})"
    )


def analyze(model, image, roi=None, engine=None):
    """Run the detection engine the caller asked for on ``image``.

    ``roi`` optionally restricts the analysed rectangle to ``(x0, y0, x1, y1)``.

    ``engine`` is ``"ai"``, ``"hsv"`` or ``None``. **Engine selection belongs to
    the caller, not to ambient config.** Reading ``ai_detection_enabled`` on its
    own used to hijack every colour caller: with the shipped ``config.json``
    (``ai_detection_enabled: true``) a caller that explicitly handed in an HSV
    model still got ONNX detections -- or an empty AI frame when the model found
    nothing -- so the colour pass became unreachable and every HSV suite
    (parity, ROI, masks, perf budgets) silently measured a different engine.
    ``main`` knows which engine the user selected and says so.

    With ``engine=None`` the arguments decide: a supplied HSV model means "run
    the colour pass", ``model is None`` means "use the AI engine when enabled".
    ``engine="ai"`` prefers the AI engine and downgrades to the colour pass only
    when the detector is unusable (never when it simply found nothing: an empty
    AI frame is a real answer, not a failure).

    Only ``image is None`` short-circuits. An AI detector that is enabled but
    not ready yields an empty frame instead of raising when there is no colour
    model either, so the tracking thread never dies.

    Detections are always reported in full-frame coordinates. ``roi_used`` says
    whether the crop actually happened (it is skipped for a near-full-frame ROI,
    and for a caller ROI that clamps to nothing the result is empty rather than
    an exception, because the caller is a tracking thread that must not die).

    ``mask`` and ``raw_mask`` cover the analysed rectangle; ``full_mask()``
    expands the mask on demand, so the full-frame allocation is only paid when
    a consumer such as the MASK preview actually renders. An AI result has no
    mask until one is read (``mask_factory``): its mask is always full-frame
    (see ``_ai_detection_mask``) so every consumer can slice it without falling
    back to HSV parameters that may not exist. ``roi_used`` stays False in that
    case, because no colour mask was computed on a crop.
    """
    if image is None:
        return DetectionFrame([], None, None, None, False, 0, None)

    frame_shape = image.shape
    frame_h, frame_w = int(frame_shape[0]), int(frame_shape[1])

    use_roi, box, invalid = _resolve_roi(roi, frame_w, frame_h)
    if invalid:
        empty_mask = np.zeros((0, 0), np.uint8)
        return DetectionFrame([], empty_mask, None, None, True, 0, frame_shape)

    if use_roi:
        offset_x, offset_y = box[0], box[1]
        sub_image = image[box[1]:box[3], box[0]:box[2]]
    else:
        box = (0, 0, frame_w, frame_h)
        offset_x = offset_y = 0
        sub_image = image

    requested = str(engine).strip().lower() if engine is not None else None
    if requested == "ai":
        want_ai = True
    elif requested == "hsv":
        want_ai = False
    else:
        want_ai = model is None and bool(getattr(config, "ai_detection_enabled", False))

    ai_detector = _ready_ai_detector() if want_ai else None
    if ai_detector is not None:
        try:
            ai_detections = ai_detector.detect(image, roi=box if use_roi else None)
        except Exception as exc:
            log_print(f"[AI] Error during AI detection: {exc}")
        else:
            mode = _enemy_outline_filter_mode()
            if _should_filter_enemy_outline(ai_detector, mode):
                # Verify the enemy highlight around every box *before* the mask
                # is created from them: a teammate box that survives here would
                # be aimed at, and a mask that still covered it would make the
                # Triggerbot and the preview disagree with the aim targets.
                # The filter sees the full frame because ``detect`` already
                # reported boxes in full-frame coordinates (ROI offset added).
                try:
                    from src.utils.ai_detection import filter_enemy_detections

                    raw_count = len(ai_detections)
                    ai_detections = filter_enemy_detections(
                        ai_detections, image, detector=ai_detector
                    )
                    _log_enemy_outline_result(len(ai_detections), raw_count, mode)
                except Exception as exc:
                    log_print(f"[AI] Enemy outline guard failed (raw boxes kept): {exc}")
            # ``detection_return_raw_mask`` exists to avoid holding a second
            # full-frame HSV mask; here ``mask`` and ``raw_mask`` are the same
            # array, so honouring the flag would only hand Triggerbot a ``None``
            # mask it cannot regenerate without HSV parameters. Building that
            # array is deferred to the first consumer: a frame whose triggerbot
            # is off must not pay a full-frame allocation plus a full-frame
            # ``countNonZero`` for a mask nobody reads.
            def _ai_mask(detections=ai_detections, h=frame_h, w=frame_w):
                return _ai_detection_mask(detections, h, w)

            return DetectionFrame(
                ai_detections,
                None,
                None,
                (0, 0, frame_w, frame_h),
                False,
                None,
                frame_shape,
                source="ai",
                mask_factory=_ai_mask if ai_detections else None,
            )

    if model is None:
        # No colour model and no usable AI detector: nothing can be analysed.
        return DetectionFrame([], None, None, box, use_roi, 0, frame_shape)

    detections, mask, raw_mask = _analyze_region(
        model, sub_image, frame_w, frame_h, offset_x, offset_y
    )

    if not bool(getattr(config, "detection_return_raw_mask", True)):
        raw_mask = None

    return DetectionFrame(
        detections,
        mask,
        raw_mask,
        box,
        use_roi,
        cv2.countNonZero(mask) if mask is not None and mask.size else 0,
        frame_shape,
    )


def perform_detection(model, image):
    """Backward-compatible wrapper: ``(detections, mask)`` for the whole frame."""
    result = analyze(model, image)
    return result.detections, result.full_mask()


def get_class_names():
    return _class_names


def get_model_size(model_path=None):
    return 0
