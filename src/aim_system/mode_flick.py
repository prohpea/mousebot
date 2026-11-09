"""
Flick mode entry point.

The heavy lifting lives in :mod:`src.aim_system.flick_controller` (closed loop,
budgeted, direction-preserving). This module is only the adapter between the
dispatcher signature and the controller, plus the state kept on the tracker.

Two performance/behaviour rules (plan H6/C14):

* ``FlickTuning`` freezes the config once per frame and ``configure()`` is only
  called when its signature actually changed. Geometry/calibration come from the
  ``aim_math`` caches, so the hot path no longer rebuilds dataclasses or runs
  trigonometry on every frame.
* ``configure()`` propagates **every** knob, including ``settle_ms`` and
  ``switch_radius_px``. Omitting them meant the Settle/Switch sliders wrote the
  config but the live controller silently kept its old values.

Legacy path: setting ``config.flick_engine = "legacy"`` routes to the old
open-loop impulse for A/B comparison. It must never be the default.
"""

from .aim_math import resolve_calibration_cached, resolve_geometry
from .flick_controller import FlickController, _cfg_get
from .tuning import FlickTuning, snapshot_flick_tuning
from src.utils.debug_logger import log_move, log_print

_STATE_ATTR = "_flick_state_{channel}"
_CONTROLLER_ATTR = "_flick_controller_{channel}"
_TUNING_SIGNATURE_ATTR = "_flick_tuning_sig_{channel}"
_QUEUE_TAG = "flick"
_STATUS_ATTR = "flick_status"


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


def _telemetry_wanted(tuning=None, app=None):
    """Publish status only when the user asked for it or is looking at it."""
    if tuning is not None and tuning.telemetry_enabled:
        return True
    try:
        from src.utils.config import config

        if bool(getattr(config, "flick_telemetry_enabled", False)):
            return True
    except Exception:
        pass
    tab = str(getattr(app, "_active_tab_name", "")) if app is not None else ""
    return tab in ("Flick V2", "Main Aimbot", "Sec Aimbot")


def _publish_status(tracker, is_sec, controller, tuning, app=None):
    """Store a small dict on ``tracker.flick_status[channel]`` (atomic rebind)."""
    if not _telemetry_wanted(tuning, app):
        return
    status = getattr(tracker, _STATUS_ATTR, None)
    if not isinstance(status, dict):
        status = {}
    payload = controller.status()
    payload["engine"] = tuning.engine
    status[_channel(is_sec)] = payload
    # Rebind rather than mutate: the UI thread may be reading the old dict.
    tracker.flick_status = status


def _get_controller(tracker, is_sec, frame=None):
    """Return the channel controller, reconfiguring it only when needed."""
    attr = _CONTROLLER_ATTR.format(channel=_channel(is_sec))
    tuning = snapshot_flick_tuning(is_sec=is_sec, tracker=tracker)
    signature_attr = _TUNING_SIGNATURE_ATTR.format(channel=_channel(is_sec))
    controller = getattr(tracker, attr, None)

    if controller is None:
        geometry = resolve_geometry(frame=frame, tracker=tracker)
        controller = FlickController(
            geometry=geometry,
            calibration=resolve_calibration_cached(tracker=tracker),
            gain=tuning.gain,
            max_counts=tuning.max_counts,
            max_iterations=tuning.max_iterations,
            budget_ms=tuning.budget_ms,
            deadzone_px=tuning.deadzone_px,
            settle_ms=tuning.settle_ms,
            switch_radius_px=float(tuning.switch_radius_px),
        )
        setattr(tracker, attr, controller)
        setattr(tracker, signature_attr, tuning.signature())
        return controller, tuning

    signature = tuning.signature()
    if getattr(tracker, signature_attr, None) != signature:
        # Geometry/calibration are cache hits unless the frame changed shape or
        # the user moved a calibration/sensitivity value.
        controller.configure(
            geometry=resolve_geometry(frame=frame, tracker=tracker),
            calibration=resolve_calibration_cached(tracker=tracker),
            **tuning.for_controller(),
        )
        setattr(tracker, signature_attr, signature)
    elif frame is not None:
        # Same tuning, but the frame may still have changed size (capture switch,
        # FOV crop). The geometry cache makes this a signature comparison.
        controller.configure(geometry=resolve_geometry(frame=frame, tracker=tracker))
    return controller, tuning


def configure_from_config(tracker, is_sec=False):
    """Force a reconfigure (used by the UI callbacks after a slider change)."""
    attr = _CONTROLLER_ATTR.format(channel=_channel(is_sec))
    controller = getattr(tracker, attr, None)
    if controller is None:
        return None
    tuning = snapshot_flick_tuning(is_sec=is_sec, tracker=tracker)
    controller.configure(
        geometry=resolve_geometry(tracker=tracker),
        calibration=resolve_calibration_cached(tracker=tracker),
        **tuning.for_controller(),
    )
    setattr(
        tracker,
        _TUNING_SIGNATURE_ATTR.format(channel=_channel(is_sec)),
        tuning.signature(),
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

    controller, tuning = _get_controller(tracker, is_sec, frame=frame)
    step = controller.step(
        dx,
        dy,
        geometry=controller.geometry,
        calibration=controller.calibration,
        target_key=_target_key(dx, dy, target_id),
    )

    setattr(tracker, _STATE_ATTR.format(channel=_channel(is_sec)), controller.state)
    _publish_status(
        tracker,
        is_sec,
        controller,
        tuning,
        app=getattr(tracker, "app", None),
    )

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


def status(tracker, is_sec=False):
    """Latest published status dict for a channel (or an empty dict)."""
    status_map = getattr(tracker, _STATUS_ATTR, None)
    if not isinstance(status_map, dict):
        return {}
    payload = status_map.get(_channel(is_sec))
    return dict(payload) if isinstance(payload, dict) else {}
