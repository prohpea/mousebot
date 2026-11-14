"""
Triggerbot module.
"""
import math
import random
import threading
import time

try:
    import cv2
except Exception:
    cv2 = None

try:
    import numpy as np
except Exception:
    np = None

from src.utils.config import config
from src.utils.debug_logger import log_print
from src.utils.activation import get_active_trigger_fov, is_binding_pressed
from src.utils import preview_throttle
from .trigger_strafe_helper import apply_manual_wait_gate, reset_strafe_runtime_state, run_with_auto_strafe


_triggerbot_state = {
    "last_trigger_time": 0.0,
    "current_cooldown": 0.0,
    "enter_range_time": None,
    "random_delay": None,
    "burst_state": None,  # None, waiting, bursting
    "burst_thread": None,
    "confirm_count": 0,
    "activation_last_pressed": False,
    "activation_toggle_state": False,
    "active_trigger_type": "current",
    "deactivation_release_sent": False,
    "strafe_manual_neutral_since": None,
    "burst_lock": threading.Lock(),
}


def _safe_destroy_window(name):
    if cv2 is None:
        return
    try:
        preview_throttle.destroy(name)
    except Exception:
        pass


def _close_trigger_debug_windows():
    _safe_destroy_window("ROI")
    _safe_destroy_window("Mask")


def _is_configured_binding(value):
    if value is None:
        return False
    return bool(str(value).strip())


def _safe_binding_pressed(value):
    if not _is_configured_binding(value):
        return False
    try:
        return bool(is_binding_pressed(value))
    except Exception:
        return False


def _ensure_bgr(roi):
    if roi is None or roi.size == 0:
        return roi
    if len(roi.shape) == 2:
        return cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR)
    if roi.shape[2] == 3:
        return roi
    if roi.shape[2] == 4:
        return cv2.cvtColor(roi, cv2.COLOR_BGRA2BGR)
    return roi[:, :, :3]


def evaluate_trigger_metrics(pixel_count, roi_area, min_pixels, min_ratio):
    """Return detected flag and ratio based on pixel/ratio thresholds."""
    safe_area = max(int(roi_area), 1)
    ratio = float(pixel_count) / float(safe_area)
    detected = int(pixel_count) >= int(min_pixels) and ratio >= float(min_ratio)
    return detected, ratio


def resolve_confirm_frames(frame_period_s=None):
    """Required confirm frames, from ``trigger_confirm_ms`` when it is > 0.

    ``trigger_confirm_frames`` stays the default so nothing changes for existing
    configs. A positive ``trigger_confirm_ms`` expresses the same budget in time
    (e.g. 6.94 ms == one frame at 144 Hz), which is what makes the click delay
    independent of the configured frame rate.
    """
    frames = max(1, int(getattr(config, "trigger_confirm_frames", 2)))
    try:
        confirm_ms = float(getattr(config, "trigger_confirm_ms", 0.0) or 0.0)
    except Exception:
        confirm_ms = 0.0
    if confirm_ms <= 0.0:
        return frames

    period_ms = None
    if frame_period_s is not None:
        try:
            period_ms = max(0.001, float(frame_period_s) * 1000.0)
        except Exception:
            period_ms = None
    if period_ms is None:
        try:
            period_ms = 1000.0 / max(1.0, float(getattr(config, "target_fps", 200)))
        except Exception:
            period_ms = 5.0
    # A budget of exactly one frame must yield one frame: without the epsilon,
    # 6.944444444444445 / 6.944444444444444 rounds up to 2.
    return max(1, int(math.ceil((confirm_ms / period_ms) - 1e-9)))


def update_confirm_counter(current_count, detected, confirm_frames):
    """Advance/reset trigger confirm counter."""
    required = max(1, int(confirm_frames))
    if not detected:
        return 0, False
    next_count = min(int(current_count) + 1, required)
    return next_count, next_count >= required


def _has_target_in_trigger_fov(targets, fov_radius):
    if not targets:
        return False
    radius = max(0.0, float(fov_radius))
    if radius <= 0:
        return True
    for target in targets:
        if len(target) < 3:
            continue
        try:
            distance = float(target[2])
        except Exception:
            continue
        if distance <= radius:
            return True
    return False


def slice_mask_for_roi(source_mask, source_mask_roi, x1, y1, x2, y2):
    """Cut the frame-space ROI ``(x1, y1, x2, y2)`` out of a (possibly offset) mask.

    Returns the slice when it is exactly the requested region as uint8, and
    ``None`` when the mask does not cover it. Callers must then fall back to
    thresholding: a slice of the wrong region is worse than a second inRange,
    because it silently measures colour somewhere else.
    """
    if source_mask is None or np is None:
        return None

    mx0, my0 = 0, 0
    if source_mask_roi is not None:
        try:
            mx0, my0 = int(source_mask_roi[0]), int(source_mask_roi[1])
        except Exception:
            mx0, my0 = 0, 0

    mh, mw = source_mask.shape[:2]
    sx1 = max(0, min(x1 - mx0, mw))
    sy1 = max(0, min(y1 - my0, mh))
    sx2 = max(sx1, min(x2 - mx0, mw))
    sy2 = max(sy1, min(y2 - my0, mh))
    candidate = source_mask[sy1:sy2, sx1:sx2]

    if (
        candidate is None
        or candidate.size == 0
        or candidate.shape[:2] != (y2 - y1, x2 - x1)
        or candidate.dtype != np.uint8
    ):
        return None
    return candidate


def _reset_tracking_state(reset_burst=False):
    with _triggerbot_state["burst_lock"]:
        if reset_burst:
            _triggerbot_state["burst_state"] = None
            _triggerbot_state["activation_toggle_state"] = False
            _triggerbot_state["activation_last_pressed"] = False
            _triggerbot_state["deactivation_release_sent"] = False
        elif _triggerbot_state["burst_state"] == "bursting":
            return
        _triggerbot_state["enter_range_time"] = None
        _triggerbot_state["random_delay"] = None
        _triggerbot_state["confirm_count"] = 0
        reset_strafe_runtime_state(_triggerbot_state)


def _resolve_activation_mode(primary_valid, secondary_valid, selected_tb_btn, selected_2_tb):
    mode = str(getattr(config, "trigger_activation_type", "hold_enable")).strip().lower()
    if mode not in {"hold_enable", "hold_disable", "toggle"}:
        mode = "hold_enable"

    if not primary_valid and not secondary_valid:
        return False, False, "BUTTON_NOT_CONFIGURED"

    pressed_primary = _safe_binding_pressed(selected_tb_btn) if primary_valid else False
    pressed_secondary = _safe_binding_pressed(selected_2_tb) if secondary_valid else False
    is_pressed = bool(pressed_primary or pressed_secondary)

    if mode == "hold_enable":
        active = is_pressed
    elif mode == "hold_disable":
        active = not is_pressed
    else:  # toggle
        last_pressed = bool(_triggerbot_state.get("activation_last_pressed", False))
        toggle_state = bool(_triggerbot_state.get("activation_toggle_state", False))
        if (not last_pressed) and is_pressed:
            toggle_state = not toggle_state
        _triggerbot_state["activation_toggle_state"] = toggle_state
        active = toggle_state

    _triggerbot_state["activation_last_pressed"] = is_pressed
    return active, is_pressed, None


def _resolve_trigger_type():
    trigger_type = str(getattr(config, "trigger_type", "current")).strip().lower()
    if trigger_type not in {"current", "rgb"}:
        trigger_type = "current"
    return trigger_type


def _execute_burst_sequence(
    controller,
    burst_count_min,
    burst_count_max,
    hold_min,
    hold_max,
    interval_min,
    interval_max,
):
    burst_count = random.randint(int(burst_count_min), int(burst_count_max))
    with _triggerbot_state["burst_lock"]:
        _triggerbot_state["burst_state"] = "bursting"
        _triggerbot_state["deactivation_release_sent"] = False

    button_pressed = False
    try:
        for shot_index in range(burst_count):
            random_hold = random.uniform(float(hold_min), float(hold_max))
            def _fire_single_shot():
                nonlocal button_pressed
                try:
                    controller.press()
                    button_pressed = True
                    time.sleep(max(0.0, random_hold) / 1000.0)
                except Exception as exc:
                    log_print(f"[Triggerbot press error] {exc}")
                finally:
                    try:
                        if button_pressed:
                            controller.release()
                            button_pressed = False
                    except Exception as exc:
                        log_print(f"[Triggerbot release error] {exc}")

            run_with_auto_strafe(_fire_single_shot)

            if shot_index < burst_count - 1:
                try:
                    random_interval = random.uniform(float(interval_min), float(interval_max))
                    if random_interval > 0:
                        time.sleep(random_interval / 1000.0)
                except Exception as exc:
                    log_print(f"[Triggerbot interval error] {exc}")
    except Exception as exc:
        log_print(f"[Triggerbot burst sequence error] {exc}")
    finally:
        try:
            if button_pressed:
                controller.release()
        except Exception as exc:
            log_print(f"[Triggerbot final release error] {exc}")
        with _triggerbot_state["burst_lock"]:
            _triggerbot_state["burst_state"] = None
            _triggerbot_state["burst_thread"] = None
            _triggerbot_state["deactivation_release_sent"] = False


def process_triggerbot(
    frame,
    img,
    model,
    controller,
    tbdelay_min,
    tbdelay_max,
    tbhold_min,
    tbhold_max,
    tbcooldown_min,
    tbcooldown_max,
    tbburst_count_min,
    tbburst_count_max,
    tbburst_interval_min,
    tbburst_interval_max,
    targets=None,
    source_img=None,
    source_mask=None,
    source_mask_roi=None,
):
    """Evaluate the trigger path for one frame.

    ``source_mask``/``source_mask_roi`` let the caller hand over the raw HSV mask
    already produced by ``detection.analyze`` for this exact frame. When given,
    the centre ROI is sliced out of that mask instead of paying a second
    ``cvtColor``+``inRange`` over the same pixels. The slice is byte-identical to
    recomputing it, which is what the trigger tests assert.
    """
    if not getattr(config, "enabletb", False):
        _reset_tracking_state(reset_burst=True)
        _close_trigger_debug_windows()
        return "DISABLED"
    if cv2 is None:
        return "ERROR: OpenCV unavailable"

    # Monotonic decision deadline for this call. perf_counter never jumps when
    # the wall clock is corrected (NTP, manual change), so cooldown/delay maths
    # cannot fire early or hang. Every timestamp stored in ``_triggerbot_state``
    # must use this same clock, otherwise two different epochs get compared.
    decision_start = time.perf_counter()

    trigger_type = _resolve_trigger_type()
    previous_trigger_type = str(_triggerbot_state.get("active_trigger_type", "current")).strip().lower()
    if previous_trigger_type != trigger_type:
        _reset_tracking_state(reset_burst=True)
        try:
            controller.release()
        except Exception:
            pass
        _close_trigger_debug_windows()
    _triggerbot_state["active_trigger_type"] = trigger_type

    if trigger_type == "rgb":
        try:
            from .RGBTrigger import process_rgb_triggerbot

            rgb_source_img = source_img if source_img is not None else img
            return process_rgb_triggerbot(
                frame=frame,
                img=rgb_source_img,
                controller=controller,
                state_dict=_triggerbot_state,
                close_debug_windows=_close_trigger_debug_windows,
            )
        except Exception as exc:
            log_print("[RGB Trigger dispatch error]", exc)
            return f"ERROR: {str(exc)}"

    selected_tb_btn = getattr(config, "selected_tb_btn", None)
    selected_2_tb = getattr(config, "selected_2_tb", None)
    primary_valid = _is_configured_binding(selected_tb_btn)
    secondary_valid = _is_configured_binding(selected_2_tb)

    activation_active, activation_pressed, activation_error = _resolve_activation_mode(
        primary_valid, secondary_valid, selected_tb_btn, selected_2_tb
    )
    if activation_error is not None:
        _reset_tracking_state(reset_burst=True)
        _close_trigger_debug_windows()
        return activation_error

    if not activation_active:
        reset_strafe_runtime_state(_triggerbot_state)
        should_release = False
        with _triggerbot_state["burst_lock"]:
            if _triggerbot_state["burst_state"] != "bursting":
                _triggerbot_state["enter_range_time"] = None
                _triggerbot_state["random_delay"] = None
                _triggerbot_state["confirm_count"] = 0
                _triggerbot_state["burst_state"] = None
                _triggerbot_state["deactivation_release_sent"] = False
            else:
                if not bool(_triggerbot_state.get("deactivation_release_sent", False)):
                    _triggerbot_state["deactivation_release_sent"] = True
                    should_release = True
        if should_release:
            try:
                controller.release()
            except Exception as exc:
                log_print(f"[Triggerbot button release error] {exc}")
        mode = str(getattr(config, "trigger_activation_type", "hold_enable")).strip().lower()
        _close_trigger_debug_windows()
        if mode == "toggle":
            return "TOGGLE_OFF"
        if mode == "hold_disable":
            return "BUTTON_HELD_DISABLED"
        return "BUTTON_NOT_PRESSED"
    with _triggerbot_state["burst_lock"]:
        _triggerbot_state["deactivation_release_sent"] = False
        if _triggerbot_state.get("burst_state") == "bursting":
            return "BURSTING"

    manual_wait_allowed, manual_wait_status = apply_manual_wait_gate(_triggerbot_state)
    if not manual_wait_allowed:
        with _triggerbot_state["burst_lock"]:
            if _triggerbot_state["burst_state"] != "bursting":
                _triggerbot_state["enter_range_time"] = None
                _triggerbot_state["random_delay"] = None
                _triggerbot_state["burst_state"] = None
            _triggerbot_state["confirm_count"] = 0
        _close_trigger_debug_windows()
        return manual_wait_status or "STRAFE_WAIT"

    try:
        detect_img = source_img if source_img is not None else img
        cx0, cy0 = int(frame.xres // 2), int(frame.yres // 2)
        tb_fov = float(get_active_trigger_fov(fallback=getattr(config, "tbfovsize", 0)))
        if not _has_target_in_trigger_fov(targets, tb_fov):
            with _triggerbot_state["burst_lock"]:
                if _triggerbot_state["burst_state"] != "bursting":
                    _triggerbot_state["enter_range_time"] = None
                    _triggerbot_state["random_delay"] = None
                    _triggerbot_state["burst_state"] = None
                _triggerbot_state["confirm_count"] = 0
            _close_trigger_debug_windows()
            return "OUT_OF_FOV"

        # Use Trigger FOV as the only ROI scale source.
        roi_size = max(1, int(tb_fov)) if tb_fov > 0 else 8
        x1, y1 = max(cx0 - roi_size, 0), max(cy0 - roi_size, 0)
        x2, y2 = min(cx0 + roi_size, detect_img.shape[1]), min(cy0 + roi_size, detect_img.shape[0])
        roi = detect_img[y1:y2, x1:x2]
        if roi.size == 0:
            _close_trigger_debug_windows()
            return "INVALID_ROI"

        roi_bgr = _ensure_bgr(roi)
        mask = None
        if source_mask is not None:
            # Slice the shared raw mask in frame coordinates. It was produced
            # from the same frame and the same HSV bounds, so this is exactly
            # cv2.inRange(cv2.cvtColor(roi_bgr)) without the second colour pass.
            mask = slice_mask_for_roi(source_mask, source_mask_roi, x1, y1, x2, y2)

        if mask is None:
            hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
            hsv_upper = model[1]
            hsv_lower = model[0]
            mask = cv2.inRange(hsv, hsv_lower, hsv_upper)

        pixel_count = int(cv2.countNonZero(mask))
        roi_area = int(mask.shape[0] * mask.shape[1])
        min_pixels = max(1, int(getattr(config, "trigger_min_pixels", 4)))
        min_ratio = max(0.0, float(getattr(config, "trigger_min_ratio", 0.03)))
        confirm_frames = resolve_confirm_frames()
        detected, ratio = evaluate_trigger_metrics(pixel_count, roi_area, min_pixels, min_ratio)

        show_windows = bool(getattr(config, "show_opencv_windows", True))
        show_roi = bool(getattr(config, "show_opencv_roi", True))
        show_mask = bool(getattr(config, "show_opencv_triggerbot_mask", True))
        # Preview windows are throttled and painted by the preview render
        # worker; submitting an image here never blocks the tracking thread.
        if show_windows and show_roi:
            if preview_throttle.render_if_due("ROI"):
                preview_throttle.imshow("ROI", roi)
        else:
            _safe_destroy_window("ROI")
        if show_windows and show_mask:
            if preview_throttle.render_if_due("Mask"):
                preview_throttle.imshow("Mask", mask)
        else:
            _safe_destroy_window("Mask")

        now = time.perf_counter()

        if not detected:
            with _triggerbot_state["burst_lock"]:
                if _triggerbot_state["burst_state"] != "bursting":
                    _triggerbot_state["enter_range_time"] = None
                    _triggerbot_state["random_delay"] = None
                    _triggerbot_state["burst_state"] = None
                _triggerbot_state["confirm_count"] = 0
            return "NO_TARGET"

        with _triggerbot_state["burst_lock"]:
            confirm_count, is_confirmed = update_confirm_counter(
                _triggerbot_state.get("confirm_count", 0),
                detected,
                confirm_frames,
            )
            _triggerbot_state["confirm_count"] = confirm_count

        if not is_confirmed:
            return f"CONFIRMING ({confirm_count}/{confirm_frames})"

        # From here on the frame has enough colour in the centre ROI: this is the
        # point that decides whether a click is issued, and its latency is what
        # "time to click" means.
        try:
            _triggerbot_state["last_decision_ms"] = (time.perf_counter() - decision_start) * 1000.0
        except Exception:
            pass

        cv2.putText(
            img,
            f"TARGET DETECTED px:{pixel_count} r:{ratio:.3f}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2,
        )

        with _triggerbot_state["burst_lock"]:
            current_state = _triggerbot_state["burst_state"]
            enter_time = _triggerbot_state["enter_range_time"]
            last_trigger = _triggerbot_state["last_trigger_time"]
            random_delay = _triggerbot_state.get("random_delay")

        current_cooldown = float(_triggerbot_state.get("current_cooldown", 0.0))
        if float(tbcooldown_max) > 0 and current_cooldown > 0:
            if (now - last_trigger) < current_cooldown:
                remaining = current_cooldown - (now - last_trigger)
                return f"COOLDOWN ({remaining:.2f}s)"

        if current_state == "bursting":
            return "BURSTING"

        if enter_time is None:
            random_delay = random.uniform(float(tbdelay_min), float(tbdelay_max))
            with _triggerbot_state["burst_lock"]:
                _triggerbot_state["enter_range_time"] = now
                _triggerbot_state["random_delay"] = random_delay
                _triggerbot_state["burst_state"] = "waiting"
            enter_time = now
        elif random_delay is None:
            random_delay = random.uniform(float(tbdelay_min), float(tbdelay_max))
            with _triggerbot_state["burst_lock"]:
                _triggerbot_state["random_delay"] = random_delay

        elapsed = now - enter_time
        if random_delay <= 0 or elapsed >= random_delay:
            with _triggerbot_state["burst_lock"]:
                if (
                    _triggerbot_state["burst_thread"] is not None
                    and _triggerbot_state["burst_thread"].is_alive()
                ):
                    return "BURST_IN_PROGRESS"

                burst_thread = threading.Thread(
                    target=_execute_burst_sequence,
                    args=(
                        controller,
                        tbburst_count_min,
                        tbburst_count_max,
                        tbhold_min,
                        tbhold_max,
                        tbburst_interval_min,
                        tbburst_interval_max,
                    ),
                    daemon=True,
                )
                _triggerbot_state["burst_thread"] = burst_thread
                _triggerbot_state["burst_state"] = "bursting"
                _triggerbot_state["last_trigger_time"] = now
                _triggerbot_state["enter_range_time"] = None
                _triggerbot_state["random_delay"] = None
                _triggerbot_state["confirm_count"] = 0
                if float(tbcooldown_max) > 0:
                    _triggerbot_state["current_cooldown"] = random.uniform(
                        float(tbcooldown_min), float(tbcooldown_max)
                    )
                else:
                    _triggerbot_state["current_cooldown"] = 0.0

            burst_thread.start()
            return f"BURST_STARTED ({tbburst_count_min}-{tbburst_count_max} shots)"

        return f"WAITING ({elapsed:.3f}s/{random_delay:.3f}s)"
    except Exception as exc:
        log_print("[Triggerbot error]", exc)
        return f"ERROR: {str(exc)}"
