from . import mode_abcurves, mode_bezier, mode_flick, mode_ncaf, mode_normal, mode_pid, mode_silent, mode_windmouse


_MODE_HANDLERS = {
    "ABCurves": mode_abcurves.apply,
    "Normal": mode_normal.apply,
    "Flick": mode_flick.apply,
    "Silent": mode_silent.apply,
    "NCAF": mode_ncaf.apply,
    "WindMouse": mode_windmouse.apply,
    "Bezier": mode_bezier.apply,
    "PID": mode_pid.apply,
}


def normalize_mode(mode):
    raw = str(mode or "").strip().lower()
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
        "abcurves": "ABCurves",
        "ab curves": "ABCurves",
    }
    return mapping.get(raw, "ABCurves")


def dispatch(dx, dy, distance_to_center, mode, tracker, is_sec=False):
    mode_name = normalize_mode(mode)
    if mode_name != "PID":
        mode_pid.reset(tracker, is_sec=is_sec)
    if mode_name != "ABCurves":
        mode_abcurves.reset(tracker, is_sec=is_sec)
    handler = _MODE_HANDLERS.get(mode_name, mode_abcurves.apply)
    handler(dx, dy, distance_to_center, tracker, is_sec=is_sec)
