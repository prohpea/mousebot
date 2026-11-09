"""
tuning — an immutable snapshot of the Flick parameters for one frame.

``mode_flick`` used to call ``resolve_geometry()``, ``resolve_calibration()``,
``controller.configure()`` and a dozen ``getattr(config, ...)`` reads on EVERY
frame, even though none of those values change between frames. That is 20-50 µs
of pure overhead per frame per channel, and it also meant the hot path read the
global mutable config object while the UI thread was writing to it.

``FlickTuning`` freezes the values once. ``signature()`` is a cheap hashable key:
when it is unchanged, ``mode_flick`` skips ``configure()`` entirely.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Optional, Tuple

from .aim_math import (
    Calibration,
    FrameGeometry,
    resolve_calibration_cached,
    resolve_geometry,
)

#: Defaults mirroring ``config.Config`` and ``flick_controller``.
DEFAULT_GAIN = 1.0
DEFAULT_MAX_COUNTS = 6000.0
DEFAULT_MAX_ITERATIONS = 4
DEFAULT_BUDGET_MS = 240.0
DEFAULT_DEADZONE_PX = 1.5
DEFAULT_DEADZONE_PX_SEC = 2.0
DEFAULT_SETTLE_MS = 70.0
DEFAULT_SWITCH_RADIUS_PX = 64.0


def _read(cfg: Any, name: str, default: Any, tracker: Any = None) -> Any:
    """Read ``name`` from a dict, a config object, then the tracker."""
    if cfg is None:
        try:
            from src.utils.config import config as cfg  # local import avoids a cycle
        except Exception:  # pragma: no cover
            return default
    if isinstance(cfg, dict):
        value = cfg.get(name, None)
    else:
        value = getattr(cfg, name, None)
    if value is None and tracker is not None:
        value = getattr(tracker, name, None)
    return default if value is None else value


def _f(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return float(default)
    return parsed


def _i(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _b(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    return bool(value)


@dataclass(frozen=True)
class FlickTuning:
    """Immutable per-frame Flick configuration snapshot."""

    gain: float = DEFAULT_GAIN
    max_counts: float = DEFAULT_MAX_COUNTS
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    budget_ms: float = DEFAULT_BUDGET_MS
    deadzone_px: float = DEFAULT_DEADZONE_PX
    settle_ms: float = DEFAULT_SETTLE_MS
    switch_radius_px: int = int(DEFAULT_SWITCH_RADIUS_PX)
    engine: str = "v2"
    telemetry_enabled: bool = False

    def signature(self) -> Tuple:
        """Hashable key covering every field (cheap change detection)."""
        return tuple(getattr(self, item.name) for item in fields(self))

    def for_controller(self) -> dict:
        """Keyword arguments for ``FlickController.configure``."""
        return {
            "gain": self.gain,
            "max_counts": self.max_counts,
            "max_iterations": self.max_iterations,
            "budget_ms": self.budget_ms,
            "deadzone_px": self.deadzone_px,
            "settle_ms": self.settle_ms,
            "switch_radius_px": float(self.switch_radius_px),
        }

    @property
    def effective_steps(self) -> int:
        from .flick_controller import effective_steps

        return effective_steps(self.max_iterations, self.budget_ms, self.settle_ms)

    @property
    def is_legacy(self) -> bool:
        return str(self.engine).strip().lower() == "legacy"


def snapshot_flick_tuning(cfg: Any = None, is_sec: bool = False, tracker: Any = None) -> FlickTuning:
    """Read every Flick knob for one channel into an immutable snapshot."""
    suffix = "_sec" if is_sec else ""
    default_deadzone = DEFAULT_DEADZONE_PX_SEC if is_sec else DEFAULT_DEADZONE_PX

    gain = _f(
        _read(cfg, f"flick_gain{suffix}", None, tracker),
        _f(_read(cfg, f"flick_strength_x{suffix}", DEFAULT_GAIN, tracker), DEFAULT_GAIN),
    )
    max_counts = _f(
        _read(cfg, f"flick_max_counts{suffix}", None, tracker),
        _f(_read(cfg, "max_speed", DEFAULT_MAX_COUNTS, tracker), DEFAULT_MAX_COUNTS),
    )
    max_iterations = _i(
        _read(cfg, f"flick_max_iterations{suffix}", DEFAULT_MAX_ITERATIONS, tracker),
        DEFAULT_MAX_ITERATIONS,
    )
    budget_ms = _f(
        _read(cfg, f"flick_budget_ms{suffix}", None, tracker),
        _f(
            _read(cfg, "sec_flick_cooldown_ms", DEFAULT_BUDGET_MS, tracker)
            if is_sec
            else DEFAULT_BUDGET_MS,
            DEFAULT_BUDGET_MS,
        ),
    )
    deadzone = _f(
        _read(cfg, f"flick_deadzone_px{suffix}", None, tracker),
        _f(
            _read(
                cfg,
                "sec_aim_deadzone" if is_sec else "aim_deadzone",
                default_deadzone,
                tracker,
            ),
            default_deadzone,
        ),
    )
    settle_ms = _f(
        _read(
            cfg,
            f"flick_settle_ms{suffix}",
            _read(cfg, "flick_settle_ms", DEFAULT_SETTLE_MS, tracker),
            tracker,
        ),
        DEFAULT_SETTLE_MS,
    )
    switch_radius = _i(
        _read(
            cfg,
            f"flick_switch_radius_px{suffix}",
            _read(cfg, "flick_switch_radius_px", DEFAULT_SWITCH_RADIUS_PX, tracker),
            tracker,
        ),
        int(DEFAULT_SWITCH_RADIUS_PX),
    )
    engine = str(_read(cfg, "flick_engine", "v2", tracker) or "v2").strip().lower()
    telemetry = _b(_read(cfg, "flick_telemetry_enabled", False, tracker))

    return FlickTuning(
        gain=max(0.0, gain),
        max_counts=max(1.0, abs(max_counts)),
        max_iterations=max(1, max_iterations),
        budget_ms=max(0.0, budget_ms),
        deadzone_px=max(0.0, deadzone),
        settle_ms=max(0.0, settle_ms),
        switch_radius_px=max(16, min(256, switch_radius)),
        engine="legacy" if engine == "legacy" else "v2",
        telemetry_enabled=bool(telemetry),
    )


def resolve_frame_context(
    *,
    frame: Any = None,
    cfg: Any = None,
    tracker: Any = None,
    geometry: Optional[FrameGeometry] = None,
    calibration: Optional[Calibration] = None,
) -> Tuple[FrameGeometry, Calibration]:
    """Geometry + calibration for this frame, through the caches."""
    if geometry is None:
        geometry = resolve_geometry(frame=frame, cfg=cfg, tracker=tracker)
    if calibration is None:
        calibration = resolve_calibration_cached(cfg=cfg, tracker=tracker)
    return geometry, calibration
