def apply(dx, dy, distance_to_center, tracker, is_sec=False):
    from .abcurves_controller import apply_abcurves_aim

    apply_abcurves_aim(dx, dy, distance_to_center, tracker, is_sec=is_sec)


def reset(tracker, is_sec=False):
    from .abcurves_controller import reset_abcurves_state

    reset_abcurves_state(tracker, is_sec=is_sec)


def hold(tracker, is_sec=False):
    from .abcurves_controller import hold_abcurves_state

    hold_abcurves_state(tracker, is_sec=is_sec)
