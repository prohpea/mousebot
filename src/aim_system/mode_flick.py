"""
Flick mode entry point.

The heavy lifting lives in :mod:`src.aim_system.flick_controller` (closed loop,
budgeted, direction-preserving). This module is only the adapter between the
dispatcher signature and the controller, plus the state kept on the tracker.

Legacy path: setting ``config.flick_engine = "legacy"`` routes to the old
open-loop impulse for A/B comparison. It is scheduled for removal at step 10 of
the plan and must not be the default.
"""

from .aim_math import resolve_calibration, resolve_geometry
from .flick_controller import FlickController, _cfg_get
from src.utils.debug_logger import log_move, log_print

_STATE_ATTR = "_flick_state_{channel}"
_CONTROLLER_ATTR = "_flick_controller_{channel}"
_QUEUE_TAG = "flick"


def _channel(is_sec):
    return "sec" if is_sec else "main"


def _engine_name():
    engine = str(_cfg_get(None, "flick_engine", "v2") or "v2").strip().lower()
    return "legacy" if engine == "legacy" else "v2"


def _target_key(dx, dy, target_id=None):
    """Identity used to detect a target switch mid-flick.

    ``target_id`` is the target's screen position when the caller has it. It is
    NOT an exact-equality key: the controller ignores small movement, because
    the position legitimately drifts as the crosshair converges.
    """
    if target_id is not None:
        return target_id
    return (float(dx), float(dy))


def _get_controller(tracker, is_sec, frame=None):
    attr = _CONTROLLER_ATTR.format(channel=_channel(is_sec))
    controller = getattr(tracker, attr, None)
    if controller is None:
        controller = FlickController.from_config(is_sec=is_sec, tracker=tracker, frame=frame)
        setattr(tracker, attr, controller)
        return controller

    suffix = "_sec" if is_sec else ""
    controller.configure(
        geometry=resolve_geometry(frame=frame, tracker=tracker),
        calibration=resolve_calibration(tracker=tracker),
        gain=_cfg_get(None, f"flick_gain{suffix}", controller.gain, tracker),
        max_counts=_cfg_get(None, f"flick_max_counts{suffix}", controller.max_counts, tracker),
        max_iterations=_cfg_get(
            None, f"flick_max_iterations{suffix}", controller.max_iterations, tracker
        ),
        budget_ms=_cfg_get(None, f"flick_budget_ms{suffix}", controller.budget_ms, tracker),
        deadzone_px=_cfg_get(
            None, f"flick_deadzone_px{suffix}", controller.deadzone_px, tracker
        ),
    )
    return controller


def _enqueue(tracker, dx, dy, delay=0.0):
    from .normal import _queue_move

    return _queue_move(tracker, dx, dy, delay, drop_oldest=False, tag=_QUEUE_TAG)


def _update_movement_lock(tracker, is_sec):
    try:
        from src.utils.mouse import update_movement_lock
        from src.utils.config import config

        if is_sec:
            lock_x = getattr(config, "mouse_lock_sec_x", False)
            lock_y = getattr(config, "mouse_lock_sec_y", False)
        else:
            lock_x = getattr(config, "mouse_lock_main_x", False)
            lock_y = getattr(config, "mouse_lock_main_y", False)
        if lock_x or lock_y:
            update_movement_lock(lock_x, lock_y, is_main=not is_sec)
    except Exception:
        pass


def apply(dx, dy, distance_to_center, tracker, is_sec=False, frame=None, target_id=None):
    """Run one flick step for the given pixel error."""
    if _engine_name() == "legacy":
        from . import normal as legacy_normal

        return legacy_normal._apply_flick_aim(dx, dy, tracker, is_sec)

    controller = _get_controller(tracker, is_sec, frame=frame)
    # ``_get_controller`` already refreshed geometry/calibration for this frame.
    step = controller.step(
        dx,
        dy,
        geometry=controller.geometry,
        calibration=controller.calibration,
        target_key=_target_key(dx, dy, target_id),
    )

    setattr(tracker, _STATE_ATTR.format(channel=_channel(is_sec)), controller.state)

    if not step.move:
        return step

    _update_movement_lock(tracker, is_sec)

    qdx = int(round(step.counts[0]))
    qdy = int(round(step.counts[1]))
    if qdx == 0 and qdy == 0:
        return step

    if not _enqueue(tracker, qdx, qdy, 0.0):
        # The queue rejected the impulse: it never reached the mouse, so do not
        # charge the iteration or consume the residual. The next frame retries.
        controller.rollback_step()
        return step

    label = "Sec Aimbot (Flick v2)" if is_sec else "Main Aimbot (Flick v2)"
    log_move(qdx, qdy, label)
    return step


def reset(tracker, is_sec=False):
    """Clear flick state/controller for one channel."""
    channel = _channel(is_sec)
    attr = _CONTROLLER_ATTR.format(channel=channel)
    controller = getattr(tracker, attr, None)
    if controller is not None:
        controller.reset(reason="external_reset")
    # Legacy state as well, so a mode switch never leaves a stale cooldown.
    if hasattr(tracker, "_last_sec_flick_time"):
        try:
            tracker._last_sec_flick_time = 0.0
        except Exception:
            pass


def describe(tracker, is_sec=False):
    controller = getattr(tracker, _CONTROLLER_ATTR.format(channel=_channel(is_sec)), None)
    if controller is None:
        return "FlickController(not initialised)"
    return controller.describe()
