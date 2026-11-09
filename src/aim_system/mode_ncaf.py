def apply(dx, dy, distance_to_center, tracker, is_sec=False, **kwargs):
    from . import normal as legacy_normal

    return legacy_normal._apply_ncaf_aim(dx, dy, distance_to_center, tracker, is_sec)
