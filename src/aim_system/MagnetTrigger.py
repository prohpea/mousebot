"""
Magnet Trigger runtime.

Magnet Trigger 鎵撻€犵偤鐙珛 module:
- 鏀寔 Magnet 鐙珛 aim mode / trigger mode
- click 浣跨敤 thread + lock锛宲ress -> delay -> release
- 鍚屼竴鏅傞枔鍙厑璁歌€佷竴鍊媍lick worker 鍦ㄨ窇
"""
import math
import random
import threading
import time
from contextlib import contextmanager

try:
    import cv2
except Exception:
    cv2 = None

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy ships with the app
    np = None

from src.utils.activation import is_binding_pressed
from src.utils.config import config
from src.utils.debug_logger import log_print

from . import mode_bezier, mode_flick, mode_ncaf, mode_normal, mode_pid, mode_silent, mode_windmouse
from .RGBTrigger import _create_rgb_mask


_MODE_HANDLERS = {
    "Normal": mode_normal.apply,
    "Flick": mode_flick.apply,
    "Silent": mode_silent.apply,
    "NCAF": mode_ncaf.apply,
    "WindMouse": mode_windmouse.apply,
    "Bezier": mode_bezier.apply,
    "PID": mode_pid.apply,
}

_magnet_state = {
    "activation_last_pressed": False,
    "activation_toggle_state": False,
    "enter_range_time": None,
    "random_delay": None,
    "confirm_count": 0,
    "last_fire_time": 0.0,
    "current_cooldown": 0.0,
    "click_thread": None,
    "click_thread_lock": threading.Lock(),
    "click_runtime_lock": threading.Lock(),
    "deactivation_release_sent": False,
}


def _normalize_mode(value):
    raw = str(value or "").strip().lower()
    mapping = {
        "normal": "Normal",
        "flick": "Flick",
        "silent": "Silent",
        "ncaf": "NCAF",
        "windmouse": "WindMouse",
        "bezier": "Bezier",
        "pid": "PID",
        "pid controller": "PID",
        "pid controller (risk)": "PID",
        "pid controller ( risk )": "PID",
    }
    return mapping.get(raw, "Normal")


def _is_configured_binding(value):
    if value is None:
        return False
    text = str(value).strip()
    return bool(text)


def _resolve_activation():
    binding = getattr(config, "magnet_keybind", 0)
    if not _is_configured_binding(binding):
        return False, "BUTTON_NOT_CONFIGURED"

    mode = str(getattr(config, "magnet_activation_type", "hold_enable")).strip().lower()
    if mode not in {"hold_enable", "hold_disable", "toggle"}:
        mode = "hold_enable"

    pressed = bool(is_binding_pressed(binding))
    if mode == "hold_enable":
        active = pressed
    elif mode == "hold_disable":
        active = not pressed
    else:
        last_pressed = bool(_magnet_state.get("activation_last_pressed", False))
        toggle_state = bool(_magnet_state.get("activation_toggle_state", False))
        if (not last_pressed) and pressed:
            toggle_state = not toggle_state
        _magnet_state["activation_toggle_state"] = toggle_state
        active = toggle_state

    _magnet_state["activation_last_pressed"] = pressed
    return active, None


def _reset_trigger_state():
    _magnet_state["enter_range_time"] = None
    _magnet_state["random_delay"] = None
    _magnet_state["confirm_count"] = 0
    _magnet_state["miss_count"] = 0


def _get_best_target(targets, center_x, center_y, fov_radius):
    if not targets:
        return None

    best = None
    best_distance = None
    max_radius = max(0.0, float(fov_radius))
    for target in targets:
        if len(target) < 2:
            continue
        try:
            cx = float(target[0])
            cy = float(target[1])
        except Exception:
            continue
        distance = math.hypot(cx - center_x, cy - center_y)
        if max_radius > 0.0 and distance > max_radius:
            continue
        if best is None or distance < best_distance:
            best = (cx, cy, distance)
            best_distance = distance
    return best


def _resolve_rgb_profile():
    profile_key = str(getattr(config, "magnet_rgb_color_profile", "purple")).strip().lower()
    if profile_key == "custom":
        custom_r = max(0, min(255, int(getattr(config, "magnet_rgb_custom_r", 161))))
        custom_g = max(0, min(255, int(getattr(config, "magnet_rgb_custom_g", 69))))
        custom_b = max(0, min(255, int(getattr(config, "magnet_rgb_custom_b", 163))))
        tolerance = max(0, min(255, int(getattr(config, "magnet_rgb_tolerance", 30))))
        return profile_key, (custom_r, custom_g, custom_b), tolerance

    presets = {
        "red": ((180, 40, 40), 30),
        "yellow": ((230, 230, 80), 35),
        "purple": ((161, 69, 163), 30),
    }
    if profile_key not in presets:
        profile_key = "purple"
    rgb_value, tolerance = presets[profile_key]
    tolerance = max(0, min(255, int(getattr(config, "magnet_rgb_tolerance", tolerance))))
    return profile_key, rgb_value, tolerance


def _evaluate_rgb_trigger(frame, source_img):
    if cv2 is None:
        return False, "RGB_UNAVAILABLE"
    if frame is None or source_img is None:
        return False, "NO_IMAGE"

    try:
        cx0, cy0 = int(frame.xres // 2), int(frame.yres // 2)
        roi_size = max(2, int(getattr(config, "magnet_trigger_roi_size", 9)))
        x1, y1 = max(cx0 - roi_size, 0), max(cy0 - roi_size, 0)
        x2 = min(cx0 + roi_size, source_img.shape[1])
        y2 = min(cy0 + roi_size, source_img.shape[0])
        roi = source_img[y1:y2, x1:x2]
        if roi is None or roi.size == 0:
            return False, "INVALID_ROI"

        _, target_rgb, tolerance = _resolve_rgb_profile()
        mask = _create_rgb_mask(roi, target_rgb, tolerance)
        rgb_pixels = int(cv2.countNonZero(mask)) if mask.size else 0

        # Also evaluate HSV color band for maximum lighting and compression immunity
        try:
            if np is None:
                raise RuntimeError("numpy unavailable")
            hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            color_preset = str(getattr(config, "color", "purple")).strip().lower()
            if color_preset == "yellow":
                hsv_min = np.array([18, 80, 80], dtype=np.uint8)
                hsv_max = np.array([40, 255, 255], dtype=np.uint8)
            elif color_preset == "red":
                hsv_min = np.array([0, 95, 95], dtype=np.uint8)
                hsv_max = np.array([4, 235, 255], dtype=np.uint8)
            else:
                hsv_min = np.array([125, 60, 80], dtype=np.uint8)
                hsv_max = np.array([170, 255, 255], dtype=np.uint8)
            hsv_mask = cv2.inRange(hsv_roi, hsv_min, hsv_max)
            hsv_pixels = int(cv2.countNonZero(hsv_mask)) if hsv_mask.size else 0
        except Exception:
            hsv_pixels = 0

        pixel_count = max(rgb_pixels, hsv_pixels)
        min_pixels = max(1, int(getattr(config, "trigger_min_pixels", 2)))
        return pixel_count >= min_pixels, f"RGB_PIXELS={pixel_count}/{min_pixels}"
    except Exception as exc:
        log_print(f"[MagnetTrigger RGB error] {exc}")
        return False, "RGB_ERROR"


@contextmanager
def _magnet_mode_context(tracker):
    override_pairs = {
        "fovsize": float(getattr(config, "magnet_fov", 45.0)),
        "ads_fov_enabled": False,
        "ads_fovsize": float(getattr(config, "magnet_fov", 45.0)),
        "normal_x_speed": float(getattr(config, "magnet_normal_x_speed", 3.0)),
        "normal_y_speed": float(getattr(config, "magnet_normal_y_speed", 3.0)),
        "normalsmooth": float(getattr(config, "magnet_normalsmooth", 30.0)),
        "normalsmoothfov": float(getattr(config, "magnet_normalsmoothfov", 30.0)),
        # Flick uses a physical gain now; magnet_flick_strength_* are legacy keys
        # that only exist so old config files keep loading.
        "flick_gain": float(
            getattr(
                config,
                "magnet_flick_gain",
                getattr(config, "flick_gain", 1.0),
            )
        ),
        "flick_max_counts": float(
            getattr(config, "magnet_flick_max_counts", getattr(config, "flick_max_counts", 6000.0))
        ),
        "flick_max_iterations": int(
            getattr(
                config,
                "magnet_flick_max_iterations",
                getattr(config, "flick_max_iterations", 4),
            )
        ),
        "flick_budget_ms": float(
            getattr(config, "magnet_flick_budget_ms", getattr(config, "flick_budget_ms", 120.0))
        ),
        "flick_deadzone_px": float(
            getattr(
                config,
                "magnet_flick_deadzone_px",
                getattr(config, "flick_deadzone_px", 1.5),
            )
        ),
        "ncaf_snap_radius": float(getattr(config, "magnet_ncaf_snap_radius", 150.0)),
        "ncaf_near_radius": float(getattr(config, "magnet_ncaf_near_radius", 50.0)),
        "ncaf_alpha": float(getattr(config, "magnet_ncaf_alpha", 1.5)),
        "ncaf_snap_boost": float(getattr(config, "magnet_ncaf_snap_boost", 0.3)),
        "ncaf_max_step": float(getattr(config, "magnet_ncaf_max_step", 50.0)),
        "ncaf_min_speed_multiplier": float(getattr(config, "magnet_ncaf_min_speed_multiplier", 0.01)),
        "ncaf_max_speed_multiplier": float(getattr(config, "magnet_ncaf_max_speed_multiplier", 10.0)),
        "ncaf_prediction_interval": float(getattr(config, "magnet_ncaf_prediction_interval", 0.016)),
        "wm_gravity": float(getattr(config, "magnet_wm_gravity", 9.0)),
        "wm_wind": float(getattr(config, "magnet_wm_wind", 3.0)),
        "wm_max_step": float(getattr(config, "magnet_wm_max_step", 15.0)),
        "wm_min_step": float(getattr(config, "magnet_wm_min_step", 2.0)),
        "wm_min_delay": float(getattr(config, "magnet_wm_min_delay", 0.001)),
        "wm_max_delay": float(getattr(config, "magnet_wm_max_delay", 0.003)),
        "wm_distance_threshold": float(getattr(config, "magnet_wm_distance_threshold", 50.0)),
        "bezier_segments": int(getattr(config, "magnet_bezier_segments", 8)),
        "bezier_ctrl_x": float(getattr(config, "magnet_bezier_ctrl_x", 16.0)),
        "bezier_ctrl_y": float(getattr(config, "magnet_bezier_ctrl_y", 16.0)),
        "bezier_speed": float(getattr(config, "magnet_bezier_speed", 1.0)),
        "bezier_delay": float(getattr(config, "magnet_bezier_delay", 0.002)),
        "pid_kp_min": float(getattr(config, "magnet_pid_kp_min", 3.7)),
        "pid_kp_max": float(getattr(config, "magnet_pid_kp_max", 3.7)),
        "pid_ki": float(getattr(config, "magnet_pid_ki", 24.0)),
        "pid_kd": float(getattr(config, "magnet_pid_kd", 0.11)),
        "pid_max_output": float(getattr(config, "magnet_pid_max_output", 50.0)),
        "pid_x_speed": float(getattr(config, "magnet_pid_x_speed", 1.0)),
        "pid_y_speed": float(getattr(config, "magnet_pid_y_speed", 1.0)),
    }
    tracker_pairs = {
        "fovsize": float(getattr(config, "magnet_fov", 45.0)),
        "silent_distance": float(getattr(config, "magnet_silent_distance", 1.0)),
        "silent_delay": float(getattr(config, "magnet_silent_delay", 100.0)),
        "silent_move_delay": float(getattr(config, "magnet_silent_move_delay", 500.0)),
        "silent_return_delay": float(getattr(config, "magnet_silent_return_delay", 500.0)),
    }

    old_config = {key: getattr(config, key) for key in override_pairs}
    old_tracker = {key: getattr(tracker, key, None) for key in tracker_pairs}
    try:
        for key, value in override_pairs.items():
            setattr(config, key, value)
        for key, value in tracker_pairs.items():
            setattr(tracker, key, value)
        yield
    finally:
        for key, value in old_config.items():
            setattr(config, key, value)
        for key, value in old_tracker.items():
            setattr(tracker, key, value)


def _apply_magnet_aim(tracker, dx, dy, distance_to_center, frame=None, target_pos=None):
    mode = _normalize_mode(getattr(config, "magnet_mode", "Normal"))
    handler = _MODE_HANDLERS.get(mode, mode_normal.apply)
    with _magnet_mode_context(tracker):
        if mode != "PID":
            mode_pid.reset(tracker, is_sec=False)
        if mode == "Flick":
            # Flick needs the real frame geometry (crop-aware) and the target's
            # position. The controller only treats a GROSS jump as a switch, so
            # the drift from the converging crosshair does not reset the budget.
            handler(
                dx,
                dy,
                distance_to_center,
                tracker,
                is_sec=False,
                frame=frame,
                target_id=target_pos if target_pos is not None else (float(dx), float(dy)),
            )
        else:
            handler(dx, dy, distance_to_center, tracker, is_sec=False)


def _get_trigger_window(trigger_type):
    if trigger_type == "rgb":
        delay_min = float(getattr(config, "magnet_rgb_trigger_delay_min", 0.08))
        delay_max = float(getattr(config, "magnet_rgb_trigger_delay_max", 0.15))
        hold_min = float(getattr(config, "magnet_rgb_trigger_hold_min", 40.0))
        hold_max = float(getattr(config, "magnet_rgb_trigger_hold_max", 60.0))
        cooldown_min = float(getattr(config, "magnet_rgb_trigger_cooldown_min", 0.0))
        cooldown_max = float(getattr(config, "magnet_rgb_trigger_cooldown_max", 0.0))
    else:
        delay_min = float(getattr(config, "magnet_trigger_delay_min", 0.08))
        delay_max = float(getattr(config, "magnet_trigger_delay_max", 0.15))
        hold_min = float(getattr(config, "magnet_trigger_hold_min", 40.0))
        hold_max = float(getattr(config, "magnet_trigger_hold_max", 60.0))
        cooldown_min = float(getattr(config, "magnet_trigger_cooldown_min", 0.0))
        cooldown_max = float(getattr(config, "magnet_trigger_cooldown_max", 0.0))
    return (
        min(delay_min, delay_max),
        max(delay_min, delay_max),
        min(hold_min, hold_max),
        max(hold_min, hold_max),
        min(cooldown_min, cooldown_max),
        max(cooldown_min, cooldown_max),
    )


def _should_fire(trigger_detected, now, trigger_type):
    confirm_frames = max(1, int(getattr(config, "magnet_trigger_confirm_frames", 1)))
    if not trigger_detected:
        miss_count = int(_magnet_state.get("miss_count", 0)) + 1
        _magnet_state["miss_count"] = miss_count
        if miss_count >= 2:
            _reset_trigger_state()
        return False, "NO_TRIGGER"

    _magnet_state["miss_count"] = 0
    _magnet_state["confirm_count"] = min(int(_magnet_state.get("confirm_count", 0)) + 1, confirm_frames)
    if _magnet_state["confirm_count"] < confirm_frames:
        return False, f"CONFIRMING ({_magnet_state['confirm_count']}/{confirm_frames})"

    delay_min, delay_max, _, _, cooldown_min, cooldown_max = _get_trigger_window(trigger_type)
    current_cooldown = float(_magnet_state.get("current_cooldown", 0.0))
    last_fire_time = float(_magnet_state.get("last_fire_time", 0.0))
    if cooldown_max > 0 and current_cooldown > 0 and (now - last_fire_time) < current_cooldown:
        remaining = current_cooldown - (now - last_fire_time)
        return False, f"COOLDOWN ({remaining:.2f}s)"

    enter_time = _magnet_state.get("enter_range_time")
    random_delay = _magnet_state.get("random_delay")
    if enter_time is None:
        random_delay = random.uniform(delay_min, delay_max)
        _magnet_state["enter_range_time"] = now
        _magnet_state["random_delay"] = random_delay
        if random_delay <= 0.001:
            enter_time = now
        else:
            return False, "WAITING_DELAY"

    if random_delay is None:
        random_delay = random.uniform(delay_min, delay_max)
        _magnet_state["random_delay"] = random_delay

    elapsed = now - float(enter_time)
    if elapsed < float(random_delay):
        return False, f"WAITING ({elapsed:.3f}s/{float(random_delay):.3f}s)"

    _, _, hold_min, hold_max, cooldown_min, cooldown_max = _get_trigger_window(trigger_type)
    return True, (hold_min, hold_max, cooldown_min, cooldown_max)


def _safe_release_click(controller):
    """Guaranteed release of left mouse click over hardware serial interface."""
    if controller is None:
        return
    for _ in range(3):
        try:
            controller.release()
        except Exception:
            pass
        time.sleep(0.002)


def process_magnet_trigger(frame, source_img, tracker, targets, center_x, center_y, aimbot_active=False):
    controller = getattr(tracker, "controller", None) if tracker is not None else None
    if not bool(getattr(config, "enable_magnet_trigger", False)):
        _reset_trigger_state()
        if not bool(_magnet_state.get("deactivation_release_sent", False)) or bool(_magnet_state.get("button_pressed", False)):
            _safe_release_click(controller)
            _magnet_state["button_pressed"] = False
            _magnet_state["deactivation_release_sent"] = True
        return "DISABLED"

    active, reason = _resolve_activation()
    if not active:
        _reset_trigger_state()
        if not bool(_magnet_state.get("deactivation_release_sent", False)) or bool(_magnet_state.get("button_pressed", False)):
            _safe_release_click(controller)
            _magnet_state["button_pressed"] = False
            _magnet_state["deactivation_release_sent"] = True
        return reason or "INACTIVE"

    _magnet_state["deactivation_release_sent"] = False

    fov = float(getattr(config, "magnet_fov", 45.0))
    best = _get_best_target(targets, center_x, center_y, fov)
    if best is None:
        _reset_trigger_state()
        if bool(_magnet_state.get("button_pressed", False)):
            _safe_release_click(controller)
            _magnet_state["button_pressed"] = False
        return "NO_TARGET"

    cx, cy, distance = best
    dx = cx - center_x
    dy = cy - center_y

    if not aimbot_active:
        _apply_magnet_aim(tracker, dx, dy, distance, frame=frame, target_pos=(float(cx), float(cy)))

    trigger_type = str(getattr(config, "magnet_trigger_type", "current")).strip().lower()
    if trigger_type not in {"current", "rgb"}:
        trigger_type = "current"

    fire_radius = max(1.0, float(getattr(config, "magnet_fire_radius", 6.0)))
    if trigger_type == "rgb":
        rgb_detected, _ = _evaluate_rgb_trigger(frame, source_img)
        # Smart Hybrid Trigger:
        # 1. Direct Head Target: Crosshair is directly on the estimated head position (inside face/hair)
        # 2. RGB Outline: Crosshair is crossing the colored outline
        trigger_detected = (distance <= fire_radius) or rgb_detected
    else:
        trigger_detected = distance <= fire_radius

    now = time.time()
    should_fire, fire_meta = _should_fire(trigger_detected, now, trigger_type)
    if not should_fire:
        return fire_meta

    hold_min, hold_max, cooldown_min, cooldown_max = fire_meta
    with _magnet_state["click_thread_lock"]:
        current_thread = _magnet_state.get("click_thread")
        if current_thread is not None and current_thread.is_alive():
            return "CLICK_IN_PROGRESS"
        click_thread = threading.Thread(
            target=_execute_click_sequence,
            args=(tracker.controller, hold_min, hold_max),
            daemon=True,
        )
        _magnet_state["click_thread"] = click_thread
        _magnet_state["last_fire_time"] = now
        _magnet_state["enter_range_time"] = None
        _magnet_state["random_delay"] = None
        _magnet_state["confirm_count"] = 0
        _magnet_state["current_cooldown"] = (
            random.uniform(cooldown_min, cooldown_max) if cooldown_max > 0 else 0.0
        )
        click_thread.start()
    return "FIRED"


def _execute_click_sequence(controller, hold_min_ms, hold_max_ms):
    button_pressed = False
    hold_min_ms = max(5.0, float(hold_min_ms))
    hold_max_ms = max(hold_min_ms, float(hold_max_ms))
    hold_ms = random.uniform(hold_min_ms, hold_max_ms)
    try:
        with _magnet_state["click_runtime_lock"]:
            controller.press()
            button_pressed = True
            _magnet_state["button_pressed"] = True
            time.sleep(hold_ms / 1000.0)
            _safe_release_click(controller)
            button_pressed = False
            _magnet_state["button_pressed"] = False
    except Exception as exc:
        log_print(f"[MagnetTrigger click worker error] {exc}")
    finally:
        if button_pressed or bool(_magnet_state.get("button_pressed", False)):
            _safe_release_click(controller)
            button_pressed = False
            _magnet_state["button_pressed"] = False
        with _magnet_state["click_thread_lock"]:
            _magnet_state["click_thread"] = None
