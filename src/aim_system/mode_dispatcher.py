"""
Mode dispatcher — routes an aim decision to its mode handler.

It also publishes per-mode capabilities so the pipeline can stop applying
closed-loop smoothing to an open-loop (one-shot) mode. Applying an EMA to Flick
means flick aims where the target *was*, which is only correct for modes that
re-measure every frame.
"""

from . import mode_bezier, mode_flick, mode_ncaf, mode_normal, mode_pid, mode_silent, mode_windmouse


_MODE_HANDLERS = {
    "Normal": mode_normal.apply,
    "Flick": mode_flick.apply,
    "Silent": mode_silent.apply,
    "NCAF": mode_ncaf.apply,
    "WindMouse": mode_windmouse.apply,
    "Bezier": mode_bezier.apply,
    "PID": mode_pid.apply,
}


#: Capabilities per mode.
#:   closed_loop    -> re-measures the error every frame and keeps correcting
#:   uses_smoother  -> may consume the temporally smoothed target position
#:   uses_budget    -> consumes flick_budget_ms / flick_max_iterations
#:   one_shot       -> emits a decisive impulse (reset state when it ends)
_MODE_CAPS = {
    "Flick":     {"closed_loop": False, "uses_smoother": False, "uses_budget": True,  "one_shot": True},
    "Normal":    {"closed_loop": True,  "uses_smoother": True,  "uses_budget": False, "one_shot": False},
    "PID":       {"closed_loop": True,  "uses_smoother": True,  "uses_budget": False, "one_shot": False},
    "NCAF":      {"closed_loop": True,  "uses_smoother": True,  "uses_budget": False, "one_shot": False},
    "WindMouse": {"closed_loop": True,  "uses_smoother": True,  "uses_budget": False, "one_shot": False},
    "Bezier":    {"closed_loop": True,  "uses_smoother": True,  "uses_budget": False, "one_shot": False},
    "Silent":    {"closed_loop": False, "uses_smoother": False, "uses_budget": False, "one_shot": True},
}

_DEFAULT_CAPS = dict(_MODE_CAPS["Normal"])

_MODE_ALIASES = {
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


def normalize_mode(mode):
    raw = str(mode or "").strip().lower()
    return _MODE_ALIASES.get(raw, "Normal")


def get_mode_caps(mode):
    """Capability dict for ``mode`` (never None)."""
    return dict(_MODE_CAPS.get(normalize_mode(mode), _DEFAULT_CAPS))


def mode_uses_smoother(mode):
    return bool(get_mode_caps(mode)["uses_smoother"])


def mode_is_closed_loop(mode):
    return bool(get_mode_caps(mode)["closed_loop"])


def any_mode_uses_smoother(*modes):
    """True when at least one active mode wants the temporal smoother."""
    return any(mode_uses_smoother(mode) for mode in modes if mode is not None)


def reset(tracker, mode=None, is_sec=False):
    """Drop per-mode transient state (PID integrators, flick budget state...)."""
    try:
        if normalize_mode(mode) != "PID":
            mode_pid.reset(tracker, is_sec=is_sec)
    except Exception:
        pass
    try:
        mode_flick.reset(tracker, is_sec=is_sec)
    except Exception:
        pass


def dispatch(dx, dy, distance_to_center, mode, tracker, is_sec=False, **kwargs):
    mode_name = normalize_mode(mode)
    if mode_name != "PID":
        mode_pid.reset(tracker, is_sec=is_sec)
    handler = _MODE_HANDLERS.get(mode_name, mode_normal.apply)
    if kwargs:
        return handler(dx, dy, distance_to_center, tracker, is_sec=is_sec, **kwargs)
    return handler(dx, dy, distance_to_center, tracker, is_sec=is_sec)
