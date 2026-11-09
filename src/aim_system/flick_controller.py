"""
flick_controller — closed-loop, budgeted Flick mode.

The old Flick implementation was a single open-loop impulse:

    counts = px_to_counts(error) * flick_strength      # strength 1.8 / 0.55
    counts = clip_per_axis(counts, 1000)                # max_speed, no schema
    send()
    then ignore every correction frame for 85 ms        # cooldown "return"

An open-loop impulse on top of a wrong scale cannot converge: the overshoot is
systematic, it pushes the target out of the FOV, and the cooldown throws away the
frames that would have corrected it.

This controller keeps the "flick" feel (fast, decisive, few steps) but makes it
convergent:

  * gain is physical (default 1.0), not a feel knob;
  * the clamp is a *budget* on the whole vector, and it preserves direction
    instead of truncating each axis independently;
  * sub-count residual is carried across steps (both main and secondary);
  * ``flick_max_iterations`` / ``flick_budget_ms`` bound the correction, and when
    they expire the controller *disarms* instead of ignoring frames forever;
  * a change of target resets the state cleanly (no residual carried over).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Tuple

from .aim_math import (
    Calibration,
    FrameGeometry,
    px_to_counts,
    resolve_calibration,
    resolve_geometry,
)

#: Defaults. Every one of these has a config key with the same name.
DEFAULT_GAIN: float = 1.0
DEFAULT_MAX_COUNTS: float = 6000.0
DEFAULT_MAX_ITERATIONS: int = 4
DEFAULT_BUDGET_MS: float = 120.0
DEFAULT_DEADZONE_PX: float = 1.5
DEFAULT_DEADZONE_PX_SEC: float = 2.0

#: How far the target may move before it counts as a DIFFERENT target.
#: A target's screen position drifts by roughly the aim error while the crosshair
#: converges (bounded by the FOV, ~20-30 px). Comparing positions for exact
#: equality would therefore fire a "target switch" on almost every frame, which
#: would wipe the residual and the iteration budget. A gross jump is required.
DEFAULT_SWITCH_RADIUS_PX: float = 64.0

#: A single step below this many counts is not worth a mouse report; it is kept
#: as residual instead of being rounded away.
MIN_STEP_COUNTS: float = 0.5


def _cfg_get(cfg: Any, name: str, default: Any, tracker: Any = None) -> Any:
    if cfg is None:
        try:
            from src.utils.config import config as cfg
        except Exception:  # pragma: no cover
            return default
    if isinstance(cfg, dict):
        return cfg.get(name, default)
    value = getattr(cfg, name, None)
    if value is None:
        value = getattr(tracker, name, default)
    return value if value is not None else default


def _as_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return float(default)
    return parsed


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def scale_vector_to_limit(dx: float, dy: float, limit: float) -> Tuple[float, float]:
    """Scale the WHOLE vector so its magnitude fits ``limit``.

    Direction is preserved. Per-axis truncation (``min(dx, cap), min(dy, cap)``)
    bends the aim line towards the diagonal and is never used here.
    """
    limit = abs(float(limit))
    magnitude = math.hypot(float(dx), float(dy))
    if magnitude <= 1e-12 or limit <= 0.0 or magnitude <= limit:
        return float(dx), float(dy)
    scale = limit / magnitude
    return float(dx) * scale, float(dy) * scale


def quantize_with_residual(
    dx: float,
    dy: float,
    residual: Tuple[float, float],
) -> Tuple[float, float, Tuple[float, float]]:
    """Round to whole counts, returning the carried residual.

    ``sum = value + residual``; ``out = round(sum)``; ``new_residual = sum - out``.
    The accumulated integer output therefore tracks the float request to within
    +/-0.5 counts no matter how many steps are taken.
    """
    sum_x = float(dx) + float(residual[0])
    sum_y = float(dy) + float(residual[1])
    out_x = float(round(sum_x))
    out_y = float(round(sum_y))
    return out_x, out_y, (sum_x - out_x, sum_y - out_y)


@dataclass
class FlickState:
    """Everything the controller remembers between frames."""

    armed: bool = False
    target_key: Any = None
    iterations: int = 0
    t0: float = 0.0
    residual: Tuple[float, float] = (0.0, 0.0)
    last_error: Tuple[float, float] = (0.0, 0.0)
    last_counts: Tuple[float, float] = (0.0, 0.0)
    last_sent: Tuple[float, float] = (0.0, 0.0)
    total_sent: Tuple[float, float] = (0.0, 0.0)
    last_step_time: float = 0.0
    released_reason: str = ""
    clamped_steps: int = 0


@dataclass
class FlickStep:
    """One decision produced by :meth:`FlickController.step`."""

    move: bool = False
    counts: Tuple[float, float] = (0.0, 0.0)
    residual: Tuple[float, float] = (0.0, 0.0)
    armed: bool = False
    iterations: int = 0
    reason: str = ""
    clamped: bool = False
    error_px: Tuple[float, float] = (0.0, 0.0)

    def as_tuple(self) -> Tuple[float, float, bool]:
        return float(self.counts[0]), float(self.counts[1]), bool(self.move)


class FlickController:
    """Closed-loop flick: converges within a configurable budget."""

    def __init__(
        self,
        *,
        geometry: Optional[FrameGeometry] = None,
        calibration: Optional[Calibration] = None,
        gain: float = DEFAULT_GAIN,
        max_counts: float = DEFAULT_MAX_COUNTS,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        budget_ms: float = DEFAULT_BUDGET_MS,
        deadzone_px: float = DEFAULT_DEADZONE_PX,
        settle_ms: float = 0.0,
        switch_radius_px: float = DEFAULT_SWITCH_RADIUS_PX,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.geometry = geometry
        self.calibration = calibration
        self.gain = max(0.0, float(gain))
        self.max_counts = max(1.0, abs(float(max_counts)))
        self.max_iterations = max(1, int(max_iterations))
        self.budget_ms = max(0.0, float(budget_ms))
        self.deadzone_px = max(0.0, float(deadzone_px))
        self.settle_ms = max(0.0, float(settle_ms))
        self._switch_radius_px = max(1.0, float(switch_radius_px))
        self._clock = clock or time.perf_counter
        self._pre_step_residual: Tuple[float, float] = (0.0, 0.0)
        self._last_step_time: float = 0.0
        self.state = FlickState()

    # -- configuration ------------------------------------------------------
    @classmethod
    def from_config(
        cls,
        *,
        is_sec: bool = False,
        cfg: Any = None,
        tracker: Any = None,
        frame: Any = None,
        geometry: Optional[FrameGeometry] = None,
    ) -> "FlickController":
        suffix = "_sec" if is_sec else ""
        gain = _as_float(
            _cfg_get(cfg, f"flick_gain{suffix}", None, tracker),
            _as_float(_cfg_get(cfg, f"flick_strength_x{suffix}", DEFAULT_GAIN, tracker), DEFAULT_GAIN),
        )
        max_counts = _as_float(
            _cfg_get(cfg, f"flick_max_counts{suffix}", None, tracker),
            _as_float(_cfg_get(cfg, "max_speed", DEFAULT_MAX_COUNTS, tracker), DEFAULT_MAX_COUNTS),
        )
        max_iterations = _as_int(
            _cfg_get(cfg, f"flick_max_iterations{suffix}", DEFAULT_MAX_ITERATIONS, tracker),
            DEFAULT_MAX_ITERATIONS,
        )
        budget_ms = _as_float(
            _cfg_get(cfg, f"flick_budget_ms{suffix}", None, tracker),
            _as_float(
                # Legacy alias: the old name only existed for the sec channel.
                _cfg_get(cfg, "sec_flick_cooldown_ms", DEFAULT_BUDGET_MS, tracker),
                DEFAULT_BUDGET_MS,
            ),
        )
        deadzone = _as_float(
            _cfg_get(cfg, f"flick_deadzone_px{suffix}", None, tracker),
            _as_float(
                _cfg_get(cfg, "sec_aim_deadzone" if is_sec else "aim_deadzone", DEFAULT_DEADZONE_PX, tracker),
                DEFAULT_DEADZONE_PX_SEC if is_sec else DEFAULT_DEADZONE_PX,
            ),
        )
        settle_ms = _as_float(
            _cfg_get(cfg, f"flick_settle_ms{suffix}", _cfg_get(cfg, "flick_settle_ms", 70.0, tracker), tracker),
            70.0,
        )
        if geometry is None:
            geometry = resolve_geometry(frame=frame, cfg=cfg, tracker=tracker)
        return cls(
            geometry=geometry,
            calibration=resolve_calibration(cfg=cfg, tracker=tracker),
            gain=gain,
            max_counts=max_counts,
            max_iterations=max_iterations,
            budget_ms=budget_ms,
            deadzone_px=deadzone,
            settle_ms=settle_ms,
        )

    def configure(
        self,
        *,
        geometry: Optional[FrameGeometry] = None,
        calibration: Optional[Calibration] = None,
        gain: Optional[float] = None,
        max_counts: Optional[float] = None,
        max_iterations: Optional[int] = None,
        budget_ms: Optional[float] = None,
        deadzone_px: Optional[float] = None,
        settle_ms: Optional[float] = None,
    ) -> "FlickController":
        if geometry is not None:
            self.geometry = geometry
        if calibration is not None:
            self.calibration = calibration
        if gain is not None:
            self.gain = max(0.0, float(gain))
        if max_counts is not None:
            self.max_counts = max(1.0, abs(float(max_counts)))
        if max_iterations is not None:
            self.max_iterations = max(1, int(max_iterations))
        if budget_ms is not None:
            self.budget_ms = max(0.0, float(budget_ms))
        if deadzone_px is not None:
            self.deadzone_px = max(0.0, float(deadzone_px))
        if settle_ms is not None:
            self.settle_ms = max(0.0, float(settle_ms))
        return self

    # -- lifecycle ----------------------------------------------------------
    def reset(self, reason: str = "reset") -> None:
        """Drop all state: next error starts a brand new flick."""
        self.state = FlickState(released_reason=reason)
        self._pre_step_residual = (0.0, 0.0)

    @property
    def switch_radius_px(self) -> float:
        return float(self._switch_radius_px)

    def _target_switched(self, old_key: Any, new_key: Any) -> bool:
        """True only when the keys describe clearly different positions."""
        if old_key == new_key:
            return False
        try:
            old_x, old_y = float(old_key[0]), float(old_key[1])
            new_x, new_y = float(new_key[0]), float(new_key[1])
        except (TypeError, ValueError, IndexError):
            # Non-positional key: fall back to exact comparison.
            return old_key != new_key
        return math.hypot(new_x - old_x, new_y - old_y) > self._switch_radius_px

    @property
    def armed(self) -> bool:
        return bool(self.state.armed)

    @property
    def is_measured(self) -> bool:
        return bool(self.calibration is not None and self.calibration.is_measured)

    def _budget_expired(self, now: float) -> bool:
        if self.state.t0 <= 0.0:
            return False
        elapsed_ms = (now - self.state.t0) * 1000.0
        return elapsed_ms > self.budget_ms

    def rollback_step(self) -> None:
        """Undo the bookkeeping of the last step that could not be delivered.

        Called when the move queue rejected the impulse: the counts were never
        sent, so the iteration must not be charged and the residual must go back
        to what it was. Otherwise the budget burns on commands that never moved
        the mouse, and the flick silently gives up.
        """
        if self.state.iterations > 0:
            self.state.iterations -= 1
        self.state.residual = self._pre_step_residual
        if self.state.iterations <= 0:
            self.state.t0 = 0.0

    # -- the algorithm ------------------------------------------------------
    def step(
        self,
        dx: float,
        dy: float,
        *,
        geometry: Optional[FrameGeometry] = None,
        calibration: Optional[Calibration] = None,
        target_key: Any = None,
    ) -> FlickStep:
        """Compute the next correction for pixel error ``(dx, dy)``.

        Returns a :class:`FlickStep`; ``move`` is False when there is nothing to
        send (in deadzone, budget exhausted, sub-count residual only).
        """
        now = self._clock()
        error_x, error_y = float(dx), float(dy)
        distance = math.hypot(error_x, error_y)

        # 1. Nothing to do (hit, or no target at all) -> disarm cleanly.
        if distance <= self.deadzone_px + 1e-9:
            self.reset(reason="deadzone")
            return FlickStep(
                move=False,
                armed=False,
                reason="deadzone",
                error_px=(error_x, error_y),
            )

        geometry = geometry or self.geometry
        calibration = calibration or self.calibration
        if geometry is None or calibration is None:
            self.reset(reason="no_geometry")
            return FlickStep(
                move=False,
                armed=False,
                reason="no_geometry",
                error_px=(error_x, error_y),
            )

        # 2. Target switched mid-flick -> clean slate, then re-arm immediately.
        #    The key is a screen POSITION, so it drifts while the crosshair
        #    converges. Only a gross jump counts as a switch; an exact comparison
        #    would reset the residual and budget on nearly every frame.
        if target_key is not None and self.state.target_key is not None:
            if self._target_switched(self.state.target_key, target_key):
                self.reset(reason="target_changed")
        if not self.state.armed:
            self.state.armed = True
            self.state.iterations = 0
            self.state.t0 = now
            self.state.residual = (0.0, 0.0)
            self.state.total_sent = (0.0, 0.0)
            self.state.target_key = target_key
        elif target_key is not None:
            self.state.target_key = target_key

        # 3. Budget exhausted -> release so the next frame starts a new flick.
        if self.state.iterations >= self.max_iterations:
            self.reset(reason="max_iterations")
            return FlickStep(
                move=False,
                armed=False,
                iterations=0,
                reason="max_iterations",
                error_px=(error_x, error_y),
            )
        if self._budget_expired(now):
            self.reset(reason="budget_expired")
            return FlickStep(
                move=False,
                armed=False,
                iterations=0,
                reason="budget_expired",
                error_px=(error_x, error_y),
            )

        # 3.5 Inter-step settling: wait for video pipeline latency before measuring again
        if self.settle_ms > 0.0 and self._last_step_time > 0.0:
            if (now - self._last_step_time) < (self.settle_ms / 1000.0):
                return FlickStep(
                    move=False,
                    armed=self.state.armed,
                    iterations=self.state.iterations,
                    reason="settling",
                    error_px=(error_x, error_y),
                )

        # 4. Physical conversion, then the (physical) gain.
        counts_x, counts_y = calibration.px_to_counts(geometry, error_x, error_y)
        counts_x *= self.gain
        counts_y *= self.gain

        # 5. Carry sub-count residual from previous steps.
        self._pre_step_residual = self.state.residual
        counts_x += self.state.residual[0]
        counts_y += self.state.residual[1]

        # 6. Budget clamp: scale the whole vector, never truncate an axis.
        requested = (counts_x, counts_y)
        clamped_x, clamped_y = scale_vector_to_limit(counts_x, counts_y, self.max_counts)
        was_clamped = (clamped_x, clamped_y) != requested

        # 7. Split whole counts from the carried remainder.
        out_x, out_y, residual = quantize_with_residual(clamped_x, clamped_y, (0.0, 0.0))

        self.state.iterations += 1
        self.state.last_error = (error_x, error_y)
        self.state.last_counts = requested
        self.state.residual = residual
        if was_clamped:
            self.state.clamped_steps += 1

        if out_x == 0.0 and out_y == 0.0:
            # Only a fraction of a count was asked for: keep it as residual and
            # let the next frame add to it instead of losing the correction.
            return FlickStep(
                move=False,
                counts=(0.0, 0.0),
                residual=residual,
                armed=True,
                iterations=self.state.iterations,
                reason="sub_count",
                clamped=was_clamped,
                error_px=(error_x, error_y),
            )

        self.state.last_sent = (out_x, out_y)
        self._last_step_time = now
        self.state.total_sent = (
            self.state.total_sent[0] + out_x,
            self.state.total_sent[1] + out_y,
        )
        return FlickStep(
            move=True,
            counts=(out_x, out_y),
            residual=residual,
            armed=True,
            iterations=self.state.iterations,
            reason="clamped" if was_clamped else "aim",
            clamped=was_clamped,
            error_px=(error_x, error_y),
        )

    # -- introspection ------------------------------------------------------
    def describe(self) -> str:
        calib = self.calibration.describe() if self.calibration else "Calibration(none)"
        geom = "none"
        if self.geometry is not None:
            geom = (
                f"geometry({self.geometry.frame_w}x{self.geometry.frame_h}, "
                f"hfov={self.geometry.hfov_deg:.3f}, vfov={self.geometry.vfov_deg:.3f}, "
                f"source={self.geometry.source})"
            )
        return (
            f"FlickController(gain={self.gain:.3f}, max_counts={self.max_counts:.1f}, "
            f"max_iterations={self.max_iterations}, budget_ms={self.budget_ms:.1f}, "
            f"deadzone_px={self.deadzone_px:.2f}, {geom}, {calib})"
        )
