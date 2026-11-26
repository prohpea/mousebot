"""ABCurves Continuous Planner + Global Renderer integration for CVM."""
from __future__ import annotations

from collections import deque
import math
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

from src.utils.activation import get_active_aim_fov
from src.utils.app_paths import get_bundle_dir
from src.utils.config import config
from src.utils.debug_logger import log_move, log_print
from src.utils.mouse import update_movement_lock

# Calibrated to eDPI = sens * dpi = 0.35 * 800 = 280 so X/Y Speed = 1.0 gives ~1.40 counts/px.
_REF_EDPI = 280.0
_BASE_COUNTS_PER_PX = 1.40
_IDLE_RESET_SECONDS = 0.25
_CAPTURE_LAG_SECONDS = 0.028
_INFLIGHT_WEIGHT = 1.00
_MAX_QUEUE_BACKLOG = 24
_MIN_STEP_US = 1_000
_MAX_STEP_US = 20_000
_FIRST_FRAME_US = 12_000

_ABCURVES_IMPORT_ATTEMPTED = False
_ABCURVES_MODULES: Optional[Tuple[Any, Any, float]] = None
_DEFAULT_PROFILE_CACHE: Optional[np.ndarray] = None
_STATE_LOCK = threading.Lock()
_PREVIEW_PIPE_CACHE: Dict[str, Any] = {}


def _find_abcurves_root() -> Optional[Path]:
    cvm_root = Path(__file__).resolve().parents[2]
    candidates = [
        get_bundle_dir() / "ABCurves",
        cvm_root / "ABCurves",
        cvm_root.parent / "ABCurves",
    ]
    for candidate in candidates:
        if (candidate / "abcurves" / "__init__.py").is_file():
            return candidate
    return None


def _ensure_abcurves_loaded() -> Tuple[Any, Any, float]:
    global _ABCURVES_IMPORT_ATTEMPTED, _ABCURVES_MODULES
    if _ABCURVES_MODULES is not None:
        return _ABCURVES_MODULES

    if not _ABCURVES_IMPORT_ATTEMPTED:
        _ABCURVES_IMPORT_ATTEMPTED = True
        repo_root = _find_abcurves_root()
        if repo_root is not None:
            repo_str = str(repo_root)
            if repo_str not in sys.path:
                sys.path.insert(0, repo_str)

    from abcurves import ContinuousPipeline, CountTransform
    from abcurves.continuous import COMMON_RADIANS_PER_COUNT

    _ABCURVES_MODULES = (ContinuousPipeline, CountTransform, float(COMMON_RADIANS_PER_COUNT))
    return _ABCURVES_MODULES


def _load_default_profile() -> np.ndarray:
    global _DEFAULT_PROFILE_CACHE
    if _DEFAULT_PROFILE_CACHE is not None:
        return _DEFAULT_PROFILE_CACHE

    repo_root = _find_abcurves_root()
    if repo_root is not None:
        sample_path = repo_root / "examples" / "data" / "human_start.npz"
        if sample_path.is_file():
            with np.load(sample_path) as data:
                if "profile_hardware" in data:
                    _DEFAULT_PROFILE_CACHE = np.asarray(data["profile_hardware"], dtype=np.int16).copy()
                    return _DEFAULT_PROFILE_CACHE

    # Fallback 256 ms 1 kHz profile if bundled example data is unavailable.
    fallback = np.zeros((256, 2), dtype=np.int16)
    fallback[::2, 0] = 1
    _DEFAULT_PROFILE_CACHE = fallback
    return _DEFAULT_PROFILE_CACHE


def _normalize_commitment_ms(value: Any) -> int:
    try:
        ms = int(str(value).lower().replace("ms", "").strip())
    except Exception:
        ms = 32
    return ms if ms in (8, 16, 32) else 32


class _NativeContinuousPipelineAdapter:
    """ContinuousPipeline-compatible adapter backed by abcurves_native C++ DLL (8/16/32 ms)."""

    def __init__(
        self,
        profile_reports: np.ndarray,
        commitment_ms: int = 16,
        seed: int = 7,
        renderer_seed: int = 101,
    ) -> None:
        from abcurves_native import Model, Planner, Renderer

        self.commitment_ms = _normalize_commitment_ms(commitment_ms)
        self._seed = int(seed)
        self._renderer_seed = int(renderer_seed)
        self._model = Model.embedded(self.commitment_ms)
        self._planner = Planner(self._model, seed=self._seed, initial_position=(0.0, 0.0))
        self._renderer = Renderer.embedded()

        canonical = np.asarray(profile_reports, dtype=np.int16).copy()
        if canonical.ndim == 2 and canonical.shape[1] == 2:
            canonical[:, 1] *= -1
        self._renderer.set_profile([(int(row[0]), int(row[1])) for row in canonical])
        self._renderer.reset(seed=self._renderer_seed)

        self._previous = np.zeros(2, dtype=np.float64)
        self._rendered = np.zeros(2, dtype=np.float64)
        self._last_t_us = 0

    @property
    def current_xy(self) -> np.ndarray:
        return self._previous.copy()

    @property
    def rendered_xy(self) -> np.ndarray:
        return self._rendered.copy()

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        renderer_seed: Optional[int] = None,
        initial_xy: Tuple[float, float] = (0.0, 0.0),
        **_kwargs,
    ) -> None:
        if seed is not None:
            self._seed = int(seed)
        if renderer_seed is not None:
            self._renderer_seed = int(renderer_seed)
        ix, iy = float(initial_xy[0]), float(initial_xy[1])
        self._planner.reinitialize(seed=self._seed, initial_position=(ix, iy))
        self._renderer.reset(seed=self._renderer_seed)
        self._previous[:] = (ix, iy)
        self._rendered[:] = (ix, iy)
        self._last_t_us = 0

    def update_target(self, xy: Tuple[float, float], timestamp_us: Optional[int] = None) -> None:
        ts = self._last_t_us if timestamp_us is None else int(timestamp_us)
        self._planner.update_target((float(xy[0]), float(xy[1])), max(0, ts))

    def advance(self, timestamp_us: Optional[int] = None) -> Dict[str, Any]:
        ts = self._last_t_us if timestamp_us is None else int(timestamp_us)
        if ts < self._last_t_us:
            ts = self._last_t_us
        self._last_t_us = ts
        samples = self._planner.advance(ts)
        count = len(samples)
        if count == 0:
            return {"reports": np.zeros((0, 2), dtype=np.int16)}
        reports = np.empty((count, 2), dtype=np.int16)
        for idx in range(count):
            pos = samples[idx].position
            pt_x, pt_y = float(pos.x), float(pos.y)
            rep = self._renderer.step((pt_x - float(self._previous[0]), pt_y - float(self._previous[1])))
            rx = int(rep.dx)
            ry = -int(rep.dy)
            self._previous[0] = pt_x
            self._previous[1] = pt_y
            self._rendered[0] += float(rx)
            self._rendered[1] -= float(ry)
            reports[idx, 0] = rx
            reports[idx, 1] = ry
        return {"reports": reports}

    @property
    def is_stopped_mode(self) -> bool:
        try:
            return int(self._planner.state.mode) == 2
        except Exception:
            return False

    def hold_zero(self) -> None:
        ix, iy = float(self._previous[0]), float(self._previous[1])
        try:
            if hasattr(self._planner, "clear_target"):
                self._planner.clear_target(max(0, int(self._last_t_us)))
            else:
                self._planner.reinitialize(seed=self._seed, initial_position=(ix, iy))
                self._last_t_us = 0
        except Exception:
            pass

    def seed_onset(self, vx0: float = 0.0, vy0: float = 0.0) -> None:
        """Re-anchor C++ planner in active MOVE state at current position with zero un-emitted jump."""
        ix, iy = float(self._previous[0]), float(self._previous[1])
        svx = float(max(-0.30, min(0.30, vx0)))
        svy = float(max(-0.30, min(0.30, vy0)))
        if abs(svx) < 1e-4 and abs(svy) < 1e-4:
            svx = 0.02
        self._planner.reinitialize(
            seed=self._seed,
            initial_position=(ix, iy),
            history=[(svx, svy)] * 160,
        )
        self._last_t_us = 0

    def nudge_anchor(self, rx: int, ry: int) -> None:
        self._previous[0] += float(rx)
        self._previous[1] -= float(ry)
        self._rendered[0] += float(rx)
        self._rendered[1] -= float(ry)
        try:
            self._planner.set_position((float(self._previous[0]), float(self._previous[1])))
        except Exception:
            pass


def _create_abcurves_pipeline(
    seed: int,
    kernel_backend: str,
    commitment_ms: int = 32,
):
    commit_ms = _normalize_commitment_ms(commitment_ms)
    profile = _load_default_profile()
    if commit_ms in (8, 16):
        return _NativeContinuousPipelineAdapter(
            profile,
            commitment_ms=commit_ms,
            seed=seed,
            renderer_seed=seed + 94,
        )

    try:
        ContinuousPipeline, CountTransform, common_rad = _ensure_abcurves_loaded()
        transform = CountTransform(common_rad, y_down=True)
        chosen_kernel = kernel_backend if kernel_backend in ("numba", "numpy") else "numba"
        try:
            return ContinuousPipeline(
                profile,
                transform=transform,
                seed=seed,
                renderer_seed=seed + 94,
                initial_xy=(0.0, 0.0),
                kernel_backend=chosen_kernel,
                prewarm=True,
            )
        except Exception:
            if chosen_kernel != "numpy":
                return ContinuousPipeline(
                    profile,
                    transform=transform,
                    seed=seed,
                    renderer_seed=seed + 94,
                    initial_xy=(0.0, 0.0),
                    kernel_backend="numpy",
                    prewarm=True,
                )
            raise
    except Exception:
        return _NativeContinuousPipelineAdapter(
            profile,
            commitment_ms=32,
            seed=seed,
            renderer_seed=seed + 94,
        )


def _compute_counts_per_px(sens: float, dpi: float, x_speed: float, y_speed: float) -> Tuple[float, float]:
    edpi = max(float(sens) * float(dpi), 10.0)
    edpi_scale = max(0.2, min(5.0, _REF_EDPI / edpi))
    base = _BASE_COUNTS_PER_PX * edpi_scale
    return max(0.05, base * max(0.05, float(x_speed))), max(0.05, base * max(0.05, float(y_speed)))


def _flush_exact_steps(tracker) -> Tuple[int, int]:
    """Remove pending ABCurves exact-step items from move_queue and return unexecuted totals."""
    move_q = getattr(tracker, "move_queue", None)
    if move_q is None:
        return 0, 0

    flush_lock = getattr(tracker, "_move_flush_lock", None)
    kept = []
    flushed_dx = 0
    flushed_dy = 0

    def _drain_and_requeue() -> None:
        nonlocal flushed_dx, flushed_dy
        pending_item = getattr(tracker, "_pending_exact_item", None)
        if pending_item is not None:
            setattr(tracker, "_pending_exact_item", None)
            if isinstance(pending_item, tuple) and len(pending_item) >= 4 and bool(pending_item[3]):
                flushed_dx += int(round(float(pending_item[0])))
                flushed_dy += int(round(float(pending_item[1])))
        try:
            while True:
                item = move_q.get_nowait()
                if isinstance(item, tuple) and len(item) >= 4 and bool(item[3]):
                    flushed_dx += int(round(float(item[0])))
                    flushed_dy += int(round(float(item[1])))
                else:
                    kept.append(item)
        except queue.Empty:
            pass

        for item in kept:
            try:
                move_q.put_nowait(item)
            except queue.Full:
                break

    if flush_lock is not None:
        with flush_lock:
            _drain_and_requeue()
    else:
        _drain_and_requeue()

    return flushed_dx, flushed_dy


def _rewind_axis_history(old_val: int, new_val: int, flushed: int) -> int:
    if flushed > 0:
        return min(int(old_val), int(new_val))
    if flushed < 0:
        return max(int(old_val), int(new_val))
    return int(old_val)


def _flush_and_rewind(tracker, pipe, state: Dict[str, Any]) -> Tuple[int, int]:
    """Flush pending ABCurves steps and monotonically rewind sent history so inflight never flips sign."""
    flushed_dx, flushed_dy = _flush_exact_steps(tracker)
    if (flushed_dx != 0 or flushed_dy != 0) and state.get("active", False):
        new_cx = int(state["cum_sent_x"]) - flushed_dx
        new_cy = int(state["cum_sent_y"]) - flushed_dy
        state["cum_sent_x"] = new_cx
        state["cum_sent_y"] = new_cy
        hist = state["sent_history"]
        for idx in range(len(hist) - 1, -1, -1):
            ts, hx, hy = hist[idx]
            rx = _rewind_axis_history(hx, new_cx, flushed_dx)
            ry = _rewind_axis_history(hy, new_cy, flushed_dy)
            if rx == hx and ry == hy:
                break
            hist[idx] = (ts, rx, ry)
    return flushed_dx, flushed_dy


def _damp_axis_on_turn(
    pipe,
    target_xy: Tuple[float, float],
    delta_cnt: Tuple[float, float],
    turn_x: bool = False,
    turn_y: bool = False,
) -> None:
    """On a verified direction reversal, re-anchor history cleanly with gentle onset velocity."""
    if not (turn_x or turn_y) or not hasattr(pipe, "movement"):
        return
    rt = pipe.movement
    pl = rt.planner
    if turn_x:
        v0_x = float(np.clip(float(delta_cnt[0]) * 0.032, -0.70, 0.70))
        rt._target_history[:, 0] = float(target_xy[0])
        rt._history[:, 0] = v0_x
    if turn_y:
        v0_y = float(np.clip(-float(delta_cnt[1]) * 0.032, -0.70, 0.70))
        rt._target_history[:, 1] = float(target_xy[1])
        rt._history[:, 1] = v0_y
    rt._pending_index = 32
    pl.previous_valid = False
    pl.mode = 0
    pl.stop_integral = 0.0


def _state_attr(is_sec: bool) -> str:
    return "_abcurves_state_sec" if is_sec else "_abcurves_state_main"


def _clear_tracking_counters(state: Dict[str, Any]) -> None:
    state["active"] = False
    state["activated_at_s"] = 0.0
    state["last_t_us"] = 0
    state["last_call_s"] = 0.0
    state["cum_sent_x"] = 0
    state["cum_sent_y"] = 0
    state["ema_tx"] = None
    state["ema_ty"] = None
    state["prev_raw_tx"] = None
    state["prev_raw_ty"] = None
    state["ema_vx"] = 0.0
    state["ema_vy"] = 0.0
    state["last_sent_px_x"] = 0.0
    state["last_sent_px_y"] = 0.0
    state["prev_dx"] = 0.0
    state["prev_dy"] = 0.0
    state["sig_dx"] = 0.0
    state["sig_dy"] = 0.0
    state["last_turn_x_s"] = -1.0
    state["last_turn_y_s"] = -1.0
    state["zero_frames"] = 0
    state["was_held"] = False
    state["sent_history"].clear()
    state["world_history"].clear()


def reset_abcurves_state(tracker, is_sec: bool = False) -> None:
    """Reset ABCurves stream and flush pending ABCurves steps when inactive."""
    state: Optional[Dict[str, Any]] = getattr(tracker, _state_attr(is_sec), None)
    if not state or not state.get("active", False):
        return

    pipe = state.get("pipe")
    if pipe is not None:
        try:
            pipe.reset(renderer_seed=state.get("seed", 7) + 94)
        except Exception as exc:
            log_print(f"[ABCurves reset error] {exc}")
            state["pipe"] = None

    _clear_tracking_counters(state)
    _flush_exact_steps(tracker)


def _get_or_create_state(
    tracker,
    is_sec: bool,
    seed: int,
    kernel_backend: str,
    commitment_ms: int = 32,
) -> Dict[str, Any]:
    with _STATE_LOCK:
        return _get_or_create_state_locked(tracker, is_sec, seed, kernel_backend, commitment_ms)


def _get_or_create_state_locked(
    tracker,
    is_sec: bool,
    seed: int,
    kernel_backend: str,
    commitment_ms: int = 32,
) -> Dict[str, Any]:
    commit_ms = _normalize_commitment_ms(commitment_ms)
    attr = _state_attr(is_sec)
    state: Optional[Dict[str, Any]] = getattr(tracker, attr, None)

    needs_rebuild = (
        state is None
        or state.get("pipe") is None
        or state.get("kernel_backend") != kernel_backend
        or state.get("commitment_ms") != commit_ms
    )

    if not needs_rebuild and state.get("seed") != seed:
        try:
            state["pipe"].reset(seed=seed, renderer_seed=seed + 94)
            state["seed"] = seed
            _clear_tracking_counters(state)
        except Exception:
            needs_rebuild = True

    if needs_rebuild:
        pipe = _create_abcurves_pipeline(
            seed=seed,
            kernel_backend=kernel_backend,
            commitment_ms=commit_ms,
        )

        state = {
            "pipe": pipe,
            "seed": seed,
            "kernel_backend": kernel_backend,
            "commitment_ms": commit_ms,
            "sent_history": deque(maxlen=128),
            "world_history": deque(maxlen=8),
            "active": False,
            "activated_at_s": 0.0,
            "last_t_us": 0,
            "last_call_s": 0.0,
            "cum_sent_x": 0,
            "cum_sent_y": 0,
            "ema_tx": None,
            "ema_ty": None,
            "prev_raw_tx": None,
            "prev_raw_ty": None,
            "ema_vx": 0.0,
            "ema_vy": 0.0,
            "last_sent_px_x": 0.0,
            "last_sent_px_y": 0.0,
            "prev_dx": 0.0,
            "prev_dy": 0.0,
            "sig_dx": 0.0,
            "sig_dy": 0.0,
            "last_turn_x_s": -1.0,
            "last_turn_y_s": -1.0,
            "zero_frames": 0,
        }
        setattr(tracker, attr, state)

    return state


def prewarm_abcurves_async(tracker) -> None:
    """Pre-load ABCurves pipeline in background so first hotkey press has zero stutter."""
    def _worker():
        try:
            seed = int(getattr(config, "abcurves_seed", 7))
            commit_ms = _normalize_commitment_ms(getattr(config, "abcurves_commitment_ms", 32))
            kb = str(getattr(config, "abcurves_kernel_backend", "numpy") or "numpy").strip().lower()
            if kb not in ("numba", "numpy"):
                kb = "numpy"
            _get_or_create_state(tracker, is_sec=False, seed=seed, kernel_backend=kb, commitment_ms=commit_ms)
        except Exception as exc:
            log_print(f"[ABCurves prewarm error] {exc}")

    threading.Thread(target=_worker, daemon=True, name="ABCurvesPrewarm").start()


def _lookup_captured_counts(history: deque, target_time_s: float) -> Tuple[float, float]:
    """Linearly interpolate cumulative sent counts at target_time_s to prevent staircase sawtooth jitter."""
    if not history:
        return 0.0, 0.0
    if target_time_s <= history[0][0]:
        return float(history[0][1]), float(history[0][2])
    if target_time_s >= history[-1][0]:
        return float(history[-1][1]), float(history[-1][2])

    prev_ts, prev_x, prev_y = history[0]
    for ts, cx, cy in history:
        if ts >= target_time_s:
            span = ts - prev_ts
            if span <= 1e-6:
                return float(cx), float(cy)
            frac = (target_time_s - prev_ts) / span
            return (
                float(prev_x) + frac * float(cx - prev_x),
                float(prev_y) + frac * float(cy - prev_y),
            )
        prev_ts, prev_x, prev_y = ts, cx, cy
    return float(history[-1][1]), float(history[-1][2])


def _enqueue_exact_reports(
    tracker,
    reports: np.ndarray,
    max_step: float,
    dx: float = 0.0,
    dy: float = 0.0,
    budget_x: Optional[float] = None,
    budget_y: Optional[float] = None,
) -> Tuple[int, int]:
    """Coalesce (0, 0) ticks into step delays and queue genuine 1 kHz humanized moves without overshooting budget."""
    steps = []
    cap = abs(float(max_step)) if max_step > 0 else 50.0
    total_dx = 0
    total_dy = 0
    pending_delay = 0.0

    net_dx = int(reports[:, 0].sum()) if len(reports) > 0 else 0
    net_dy = int(reports[:, 1].sum()) if len(reports) > 0 else 0
    suppress_x = (abs(dx) <= 0.45) or (dx > 0.45 and net_dx < 0) or (dx < -0.45 and net_dx > 0)
    suppress_y = (abs(dy) <= 0.45) or (dy > 0.45 and net_dy < 0) or (dy < -0.45 and net_dy > 0)
    rem_x = None if budget_x is None else max(0, int(math.floor(abs(float(budget_x)) + 0.5)))
    rem_y = None if budget_y is None else max(0, int(math.floor(abs(float(budget_y)) + 0.5)))
    acc_x = 0
    acc_y = 0

    for row in reports:
        raw_dx = 0 if suppress_x else int(row[0])
        raw_dy = 0 if suppress_y else int(row[1])
        if (dx > 0.45 and raw_dx < 0) or (dx < -0.45 and raw_dx > 0):
            raw_dx = 0
        if (dy > 0.45 and raw_dy < 0) or (dy < -0.45 and raw_dy > 0):
            raw_dy = 0
        if raw_dx != 0 or raw_dy != 0:
            cdx, cdy = tracker._clip_movement(raw_dx, raw_dy)
            sdx = int(round(max(-cap, min(cap, float(cdx)))))
            sdy = int(round(max(-cap, min(cap, float(cdy)))))
            if rem_x is not None and sdx != 0:
                avail_x = max(0, rem_x - acc_x)
                sdx = int(math.copysign(min(abs(sdx), avail_x), sdx)) if avail_x > 0 else 0
                acc_x += abs(sdx)
            if rem_y is not None and sdy != 0:
                avail_y = max(0, rem_y - acc_y)
                sdy = int(math.copysign(min(abs(sdy), avail_y), sdy)) if avail_y > 0 else 0
                acc_y += abs(sdy)
        else:
            sdx, sdy = 0, 0

        if sdx == 0 and sdy == 0:
            if steps:
                px, py, pdelay = steps[-1]
                steps[-1] = (px, py, min(0.006, pdelay + 0.001))
            else:
                pending_delay = min(0.006, pending_delay + 0.001)
        else:
            steps.append((sdx, sdy, min(0.006, 0.001 + pending_delay)))
            pending_delay = 0.0

    for sdx, sdy, sdelay in steps:
        try:
            tracker.move_queue.put_nowait((sdx, sdy, sdelay, True))
            total_dx += sdx
            total_dy += sdy
        except queue.Full:
            break

    return total_dx, total_dy


def apply_abcurves_aim(dx, dy, distance_to_center, tracker, is_sec: bool = False) -> None:
    """Generate stabilized 1 kHz closed-loop mouse reports using ABCurves ContinuousPipeline."""
    if is_sec:
        x_speed = float(getattr(config, "abcurves_x_speed_sec", 1.0))
        y_speed = float(getattr(config, "abcurves_y_speed_sec", 1.0))
        max_step = float(getattr(config, "abcurves_max_step_sec", 50.0))
        seed = int(getattr(config, "abcurves_seed_sec", 7))
        commit_ms = _normalize_commitment_ms(getattr(config, "abcurves_commitment_ms_sec", 32))
        label = f"Sec Aimbot (ABCurves {commit_ms}ms)"
    else:
        x_speed = float(getattr(config, "abcurves_x_speed", 1.0))
        y_speed = float(getattr(config, "abcurves_y_speed", 1.0))
        max_step = float(getattr(config, "abcurves_max_step", 50.0))
        seed = int(getattr(config, "abcurves_seed", 7))
        commit_ms = _normalize_commitment_ms(getattr(config, "abcurves_commitment_ms", 32))
        label = f"Main Aimbot (ABCurves {commit_ms}ms)"

    sens = float(getattr(config, "in_game_sens", tracker.in_game_sens))
    dpi = float(getattr(config, "mouse_dpi", tracker.mouse_dpi))
    kernel_backend = str(getattr(config, "abcurves_kernel_backend", "numba") or "numba").strip().lower()
    if kernel_backend not in ("numba", "numpy"):
        kernel_backend = "numba"

    _ = get_active_aim_fov(is_sec=is_sec, fallback=(tracker.fovsize_sec if is_sec else tracker.fovsize))
    counts_per_px_x, counts_per_px_y = _compute_counts_per_px(sens, dpi, x_speed, y_speed)

    state = _get_or_create_state(tracker, is_sec, seed, kernel_backend, commitment_ms=commit_ms)
    pipe = state["pipe"]
    now = time.perf_counter()

    if state["active"] and (now - state["last_call_s"]) > _IDLE_RESET_SECONDS:
        reset_abcurves_state(tracker, is_sec=is_sec)

    # Flush queued exact steps only if consumer falls significantly behind.
    if tracker.move_queue.qsize() >= _MAX_QUEUE_BACKLOG:
        _flush_and_rewind(tracker, pipe, state)

    if not state["active"]:
        state["active"] = True
        state["last_t_us"] = 0
        state["cum_sent_x"] = 0
        state["cum_sent_y"] = 0
        init_tx = float(dx) * counts_per_px_x
        init_ty = -float(dy) * counts_per_px_y
        state["ema_tx"] = init_tx
        state["ema_ty"] = init_ty
        state["prev_raw_tx"] = float(dx) * counts_per_px_x
        state["prev_raw_ty"] = -float(dy) * counts_per_px_y
        state["ema_vx"] = 0.0
        state["ema_vy"] = 0.0
        state["last_sent_px_x"] = 0.0
        state["last_sent_px_y"] = 0.0
        state["prev_dx"] = float(dx)
        state["prev_dy"] = float(dy)
        state["sig_dx"] = float(dx) if abs(float(dx)) >= 3.5 else 0.0
        state["sig_dy"] = float(dy) if abs(float(dy)) >= 3.5 else 0.0
        state["last_turn_x_s"] = -1.0
        state["last_turn_y_s"] = -1.0
        state["zero_frames"] = 0
        state["sent_history"].clear()
        state["world_history"].clear()

        # Seed active onset velocity with zero un-emitted warmup jump so frame 0 responds smoothly.
        try:
            if hasattr(pipe, "seed_onset"):
                pipe.reset(seed=seed, renderer_seed=seed + 94, initial_xy=(0.0, 0.0))
                pipe.seed_onset(init_tx * 0.012, init_ty * 0.012)
            else:
                pipe.reset(seed=seed, renderer_seed=seed + 94, initial_xy=(0.0, 0.0))
                if hasattr(pipe, "movement"):
                    vx0 = float(np.clip(init_tx * 0.012, -0.30, 0.30))
                    vy0 = float(np.clip(init_ty * 0.012, -0.30, 0.30))
                    pipe.movement._history[:, 0] = vx0 if abs(vx0) >= 1e-4 else 0.02
                    pipe.movement._history[:, 1] = vy0
        except Exception as exc:
            log_print(f"[ABCurves init error] {exc}")
            reset_abcurves_state(tracker, is_sec=is_sec)
            return
        now = time.perf_counter()
        state["activated_at_s"] = now
        state["sent_history"].append((now, 0, 0))
        dt_us = 8_000
    else:
        elapsed_us = int(round((now - state["last_call_s"]) * 1_000_000.0))
        dt_us = max(_MIN_STEP_US, min(_MAX_STEP_US, elapsed_us))

    prev_dx_val = float(state.get("prev_dx", dx))
    prev_dy_val = float(state.get("prev_dy", dy))
    prev_sent_px_x = float(state.get("last_sent_px_x", 0.0))
    prev_sent_px_y = float(state.get("last_sent_px_y", 0.0))
    state["last_call_s"] = now
    state["prev_dx"] = float(dx)
    state["prev_dy"] = float(dy)

    def _get_effective_lag_s() -> float:
        if getattr(config, "dynamic_capture_lag_enabled", True):
            est = getattr(tracker, "lag_estimator", None)
            if est is not None and hasattr(est, "get_lag_seconds"):
                try:
                    return float(est.get_lag_seconds())
                except Exception:
                    pass
        return _CAPTURE_LAG_SECONDS

    effective_lag_s = _get_effective_lag_s()
    inflight_scale_x = max(1.0, float(x_speed)) * _INFLIGHT_WEIGHT
    inflight_scale_y = max(1.0, float(y_speed)) * _INFLIGHT_WEIGHT

    def _compute_inflight_delta() -> Tuple[float, float]:
        cap_cx, cap_cy = _lookup_captured_counts(state["sent_history"], now - effective_lag_s)
        inflight_x = float(state["cum_sent_x"]) - cap_cx
        inflight_y = float(state["cum_sent_y"]) - cap_cy
        # Scale inflight subtraction by max(1.0, speed) so x_speed > 1.0 accelerates arrival rate
        # without pumping 2.1x total displacement during the 28ms capture-lag window.
        dtx = float(dx) * counts_per_px_x - inflight_scale_x * inflight_x
        dty = float(dy) * counts_per_px_y - inflight_scale_y * inflight_y
        return dtx, dty

    delta_tx, delta_ty = _compute_inflight_delta()

    dz_px = float(getattr(config, "deadzone_fovsize_sec" if is_sec else "deadzone_fovsize", 3.5))
    if not getattr(config, "deadzone_fov_enabled_sec" if is_sec else "deadzone_fov_enabled", True):
        dz_px = 1.5
    aim_dist = math.hypot(float(dx), float(dy))
    turn_thresh_px = max(2.2, 0.80 * dz_px)

    sig_dx = float(state.get("sig_dx", 0.0))
    sig_dy = float(state.get("sig_dy", 0.0))
    turn_x = (
        (float(dx) * sig_dx < 0.0)
        and (abs(float(dx)) > turn_thresh_px)
        and (abs(delta_tx) >= max(2.0, turn_thresh_px * 0.80 * counts_per_px_x))
        and ((now - float(state.get("last_turn_x_s", -1.0))) >= 0.075)
    )
    turn_y = (
        (float(dy) * sig_dy < 0.0)
        and (abs(float(dy)) > turn_thresh_px)
        and (abs(delta_ty) >= max(2.0, turn_thresh_px * 0.80 * counts_per_px_y))
        and ((now - float(state.get("last_turn_y_s", -1.0))) >= 0.075)
    )
    if abs(float(dx)) > turn_thresh_px and (float(dx) * sig_dx >= 0.0 or turn_x):
        state["sig_dx"] = float(dx)
    if abs(float(dy)) > turn_thresh_px and (float(dy) * sig_dy >= 0.0 or turn_y):
        state["sig_dy"] = float(dy)
    if turn_x:
        state["last_turn_x_s"] = now
    if turn_y:
        state["last_turn_y_s"] = now

    if turn_x or turn_y:
        flushed_dx, flushed_dy = _flush_and_rewind(tracker, pipe, state)
        if flushed_dx != 0 or flushed_dy != 0:
            delta_tx, delta_ty = _compute_inflight_delta()

    anchor_xy = pipe.current_xy
    raw_tx = float(anchor_xy[0]) + delta_tx
    raw_ty = float(anchor_xy[1]) - delta_ty

    was_held = bool(state.pop("was_held", False))
    dt_s = max(0.001, float(dt_us) * 1e-6)
    base_alpha = 1.0 - math.exp(-dt_s / 0.011)
    alpha_x = 1.0 if turn_x else (max(base_alpha, 0.65) if was_held else base_alpha)
    alpha_y = 1.0 if turn_y else (max(base_alpha, 0.65) if was_held else base_alpha)
    ema_tx = raw_tx if state["ema_tx"] is None else (state["ema_tx"] + alpha_x * (raw_tx - state["ema_tx"]))
    ema_ty = raw_ty if state["ema_ty"] is None else (state["ema_ty"] + alpha_y * (raw_ty - state["ema_ty"]))
    state["ema_tx"] = ema_tx
    state["ema_ty"] = ema_ty

    # Differentiate true hardware-referenced world position (cum_sent + delta) rather than
    # pipe.current_xy so internal planner resets/clipping never create phantom velocity spikes,
    # and suppress velocity_lead whenever the player's own hand is pulling away from the target.
    target_tx = ema_tx
    target_ty = ema_ty
    world_tx = float(state["cum_sent_x"]) * inflight_scale_x + delta_tx
    world_ty = -float(state["cum_sent_y"]) * inflight_scale_y - delta_ty
    if turn_x:
        state["ema_vx"] = 0.0
    if turn_y:
        state["ema_vy"] = 0.0
    world_hist = state.get("world_history")
    if world_hist is None:
        world_hist = deque(maxlen=8)
        state["world_history"] = world_hist
    if getattr(config, "velocity_lead_enabled", False):
        hand_diverging_x = (abs(float(dx)) > abs(prev_dx_val) + 0.75) and (prev_dx_val * prev_sent_px_x >= 0.0)
        hand_diverging_y = (abs(float(dy)) > abs(prev_dy_val) + 0.75) and (prev_dy_val * prev_sent_px_y >= 0.0)
        activated_age = now - float(state.get("activated_at_s", now) or now)
        lag_settled = activated_age >= (effective_lag_s + 0.025)
        world_hist.append((now, world_tx, world_ty))
        ref_entry = None
        for wh_ts, wh_x, wh_y in world_hist:
            if (now - wh_ts) >= 0.022:
                ref_entry = (wh_ts, wh_x, wh_y)
        if lag_settled and ref_entry is not None and not was_held:
            span_s = max(0.020, now - ref_entry[0])
            inst_vx = (world_tx - ref_entry[1]) / span_s
            inst_vy = (world_ty - ref_entry[2]) / span_s
            if hand_diverging_x:
                state["ema_vx"] = float(state.get("ema_vx", 0.0)) * 0.35
            elif abs(inst_vx) <= 1200.0 and not turn_x:
                v_alpha = 1.0 - math.exp(-dt_s / 0.025)
                state["ema_vx"] = float(state.get("ema_vx", 0.0)) + v_alpha * (inst_vx - float(state.get("ema_vx", 0.0)))
            if hand_diverging_y:
                state["ema_vy"] = float(state.get("ema_vy", 0.0)) * 0.35
            elif abs(inst_vy) <= 1200.0 and not turn_y:
                v_alpha = 1.0 - math.exp(-dt_s / 0.025)
                state["ema_vy"] = float(state.get("ema_vy", 0.0)) + v_alpha * (inst_vy - float(state.get("ema_vy", 0.0)))
        state["prev_raw_tx"] = world_tx
        state["prev_raw_ty"] = world_ty
        if lag_settled and ref_entry is not None and not (turn_x or turn_y) and not was_held:
            lead_gain = max(0.0, min(1.0, float(getattr(config, "velocity_lead_gain", 0.25))))
            max_lead_px = max(0.0, min(12.0, float(getattr(config, "velocity_lead_max_px", 5.0))))
            lead_s = effective_lag_s * lead_gain
            dead_vx = 28.0 * counts_per_px_x
            dead_vy = 28.0 * counts_per_px_y
            eff_vx = math.copysign(max(0.0, abs(float(state["ema_vx"])) - dead_vx), float(state["ema_vx"]))
            eff_vy = math.copysign(max(0.0, abs(float(state["ema_vy"])) - dead_vy), float(state["ema_vy"]))
            lead_x = 0.0 if hand_diverging_x else max(
                -max_lead_px * counts_per_px_x,
                min(max_lead_px * counts_per_px_x, eff_vx * lead_s),
            )
            lead_y = 0.0 if hand_diverging_y else max(
                -max_lead_px * counts_per_px_y,
                min(max_lead_px * counts_per_px_y, eff_vy * lead_s),
            )
            target_tx = ema_tx + lead_x
            target_ty = ema_ty + lead_y
    else:
        state["prev_raw_tx"] = world_tx
        state["prev_raw_ty"] = world_ty

    t_receipt_us = state["last_t_us"]
    t_next_us = t_receipt_us + dt_us
    try:
        if hasattr(pipe, "movement"):
            rt = pipe.movement
            pl = rt.planner
            pl.mode = 0
            pl.stop_integral = 0.0
            if was_held and not (turn_x or turn_y):
                rt._target_history[:, 0] = float(ema_tx)
                rt._target_history[:, 1] = float(ema_ty)
                rt._pending_index = 32
                pl.previous_valid = False
            if turn_x or turn_y:
                _damp_axis_on_turn(
                    pipe,
                    (ema_tx, ema_ty),
                    (delta_tx, delta_ty),
                    turn_x=turn_x,
                    turn_y=turn_y,
                )
            elif int(state.get("zero_frames", 0)) >= 2 and aim_dist > max(2.0, dz_px) and math.hypot(delta_tx, delta_ty) >= 2.2:
                rt._history[:, 0] = float(np.clip(delta_tx * 0.032, -0.45, 0.45))
                rt._history[:, 1] = float(np.clip(-delta_ty * 0.032, -0.45, 0.45))
                rt._pending_index = 32
                pl.previous_valid = False
                state["zero_frames"] = 0
        elif hasattr(pipe, "seed_onset"):
            stalled_native = (
                (bool(getattr(pipe, "is_stopped_mode", False)) or int(state.get("zero_frames", 0)) >= 4)
                and aim_dist > max(2.0, dz_px)
                and math.hypot(delta_tx, delta_ty) >= 3.0
            )
            if turn_x or turn_y or was_held or stalled_native:
                pipe.seed_onset(delta_tx * 0.014, -delta_ty * 0.014)
                state["zero_frames"] = 0
                t_receipt_us = 0
                state["last_t_us"] = 0
                t_next_us = dt_us
                anc_now = pipe.current_xy
                ema_tx = float(anc_now[0]) + delta_tx
                ema_ty = float(anc_now[1]) - delta_ty
                state["ema_tx"] = ema_tx
                state["ema_ty"] = ema_ty
                target_tx, target_ty = ema_tx, ema_ty
        pipe.update_target((target_tx, target_ty), timestamp_us=t_receipt_us)
        out = pipe.advance(t_next_us)
    except Exception as exc:
        log_print(f"[ABCurves runtime error] {exc}")
        reset_abcurves_state(tracker, is_sec=is_sec)
        return

    state["last_t_us"] = t_next_us

    try:
        if not is_sec:
            lock_x = getattr(config, "mouse_lock_main_x", False)
            lock_y = getattr(config, "mouse_lock_main_y", False)
        else:
            lock_x = getattr(config, "mouse_lock_sec_x", False)
            lock_y = getattr(config, "mouse_lock_sec_y", False)
        if lock_x or lock_y:
            update_movement_lock(lock_x, lock_y, is_main=not is_sec)
    except Exception:
        pass

    # Anti-recoil landing lock: if an axis just crossed zero and is already settled inside the head core
    # (<= turn_thresh_px), suppress reverse pull-back twitches while the other axis finishes converging.
    core_settle_px = turn_thresh_px
    settled_cross_x = (float(dx) * sig_dx < 0.0) and (abs(float(dx)) <= core_settle_px)
    settled_cross_y = (float(dy) * sig_dy < 0.0) and (abs(float(dy)) <= core_settle_px)

    reports = out.get("reports")
    total_dx = 0
    total_dy = 0
    if reports is not None and len(reports) > 0:
        eff_bx = 0.0 if settled_cross_x else (abs(float(delta_tx)) / max(1.0, inflight_scale_x))
        eff_by = 0.0 if settled_cross_y else (abs(float(delta_ty)) / max(1.0, inflight_scale_y))
        total_dx, total_dy = _enqueue_exact_reports(
            tracker,
            reports,
            max_step=max_step,
            dx=0.0 if settled_cross_x else float(delta_tx),
            dy=0.0 if settled_cross_y else float(delta_ty),
            budget_x=eff_bx,
            budget_y=eff_by,
        )
        # Keep planner anchor synchronized with suppressed/clipped steps so stationary targets never drift.
        anchor_after = pipe.current_xy
        planned_dx = float(anchor_after[0]) - float(anchor_xy[0])
        planned_dy_screen = -(float(anchor_after[1]) - float(anchor_xy[1]))
        err_sync_x = float(total_dx) - planned_dx
        err_sync_y = float(total_dy) - planned_dy_screen
        if abs(err_sync_x) > 0.5 or abs(err_sync_y) > 0.5:
            state["ema_tx"] = float(anchor_after[0]) + (delta_tx - float(total_dx) * inflight_scale_x)
            state["ema_ty"] = float(anchor_after[1]) - (delta_ty - float(total_dy) * inflight_scale_y)

    if aim_dist > max(2.0, dz_px) and total_dx == 0 and total_dy == 0:
        state["zero_frames"] = int(state.get("zero_frames", 0)) + 1
    else:
        state["zero_frames"] = 0
    prev_cum_x = int(state["cum_sent_x"])
    prev_cum_y = int(state["cum_sent_y"])
    state["cum_sent_x"] = prev_cum_x + total_dx
    state["cum_sent_y"] = prev_cum_y + total_dy
    state["last_sent_px_x"] = float(total_dx) / max(1e-6, counts_per_px_x)
    state["last_sent_px_y"] = float(total_dy) / max(1e-6, counts_per_px_y)
    t_done = time.perf_counter()
    prev_hist_ts = float(state["sent_history"][-1][0]) if state["sent_history"] else 0.0
    if total_dx != 0 or total_dy != 0:
        t_emit_start = max(now, prev_hist_ts + 1e-6)
        state["sent_history"].append((t_emit_start, prev_cum_x, prev_cum_y))
        state["sent_history"].append((max(t_done + 0.0005, t_emit_start + 0.0005), state["cum_sent_x"], state["cum_sent_y"]))
    else:
        state["sent_history"].append((max(t_done, prev_hist_ts), state["cum_sent_x"], state["cum_sent_y"]))
    if total_dx != 0 or total_dy != 0:
        log_move(total_dx, total_dy, label)


def hold_abcurves_state(tracker, is_sec: bool = False) -> None:
    """Softly settle ABCurves at current position inside Stop Aim FOV and flush excess coasting steps."""
    state: Optional[Dict[str, Any]] = getattr(tracker, _state_attr(is_sec), None)
    if not state or not state.get("active", False):
        return
    pipe = state.get("pipe")
    if pipe is None:
        return

    now = time.perf_counter()
    if (now - state.get("last_call_s", 0.0)) > _IDLE_RESET_SECONDS:
        reset_abcurves_state(tracker, is_sec=is_sec)
        return

    # Flush any unexecuted tail steps so the cursor stops cleanly inside Deadzone without coasting past head.
    _flush_and_rewind(tracker, pipe, state)

    state["last_call_s"] = now
    state["prev_dx"] = 0.0
    state["prev_dy"] = 0.0
    state["sig_dx"] = 0.0
    state["sig_dy"] = 0.0
    state["last_sent_px_x"] = 0.0
    state["last_sent_px_y"] = 0.0
    state["ema_vx"] = 0.0
    state["ema_vy"] = 0.0
    state["was_held"] = True

    if hasattr(pipe, "movement"):
        pipe.movement._history[:] = 0.0
    elif hasattr(pipe, "hold_zero"):
        pipe.hold_zero()
    state["zero_frames"] = 0

    anchor_xy = pipe.current_xy
    state["ema_tx"] = float(anchor_xy[0])
    state["ema_ty"] = float(anchor_xy[1])
    state["prev_raw_tx"] = float(state["cum_sent_x"])
    state["prev_raw_ty"] = -float(state["cum_sent_y"])
    t_done = time.perf_counter()
    prev_hist_ts = float(state["sent_history"][-1][0]) if state["sent_history"] else 0.0
    state["sent_history"].append((max(t_done, prev_hist_ts), state["cum_sent_x"], state["cum_sent_y"]))


def simulate_abcurves_preview_path(
    target_dx_px: float = 55.0,
    target_dy_px: float = -22.0,
    is_sec: bool = False,
) -> Dict[str, Any]:
    """Simulate a 2D closed-loop ABCurves curve from (0, 0) to (target_dx_px, target_dy_px)."""
    if is_sec:
        x_speed = float(getattr(config, "abcurves_x_speed_sec", 1.0))
        y_speed = float(getattr(config, "abcurves_y_speed_sec", 1.0))
        max_step = float(getattr(config, "abcurves_max_step_sec", 50.0))
        seed = int(getattr(config, "abcurves_seed_sec", 7))
        commit_ms = _normalize_commitment_ms(getattr(config, "abcurves_commitment_ms_sec", 32))
        dz_enabled = bool(getattr(config, "deadzone_fov_enabled_sec", False))
        dz_size = float(getattr(config, "deadzone_fovsize_sec", 6.0))
    else:
        x_speed = float(getattr(config, "abcurves_x_speed", 1.0))
        y_speed = float(getattr(config, "abcurves_y_speed", 1.0))
        max_step = float(getattr(config, "abcurves_max_step", 50.0))
        seed = int(getattr(config, "abcurves_seed", 7))
        commit_ms = _normalize_commitment_ms(getattr(config, "abcurves_commitment_ms", 32))
        dz_enabled = bool(getattr(config, "deadzone_fov_enabled", False))
        dz_size = float(getattr(config, "deadzone_fovsize", 6.0))

    sens = float(getattr(config, "in_game_sens", 0.23))
    dpi = float(getattr(config, "mouse_dpi", 1100))
    kernel_backend = str(getattr(config, "abcurves_kernel_backend", "numpy") or "numpy").strip().lower()
    chosen_kernel = "numpy" if kernel_backend not in ("numpy", "numba") else "numpy"
    counts_per_px_x, counts_per_px_y = _compute_counts_per_px(sens, dpi, x_speed, y_speed)
    cap = abs(float(max_step)) if max_step > 0 else 50.0

    points = [(0.0, 0.0)]
    frame_points = [(0.0, 0.0)]
    steps_count = 0
    peak_step = 0.0

    try:
        with _STATE_LOCK:
            cache_key = (chosen_kernel, commit_ms)
            pipe = _PREVIEW_PIPE_CACHE.get(cache_key)
            if pipe is None:
                pipe = _create_abcurves_pipeline(
                    seed=seed,
                    kernel_backend=chosen_kernel,
                    commitment_ms=commit_ms,
                )
                _PREVIEW_PIPE_CACHE[cache_key] = pipe
            else:
                pipe.reset(seed=seed, renderer_seed=seed + 94, initial_xy=(0.0, 0.0))

            init_tx = float(target_dx_px) * counts_per_px_x
            init_ty = -float(target_dy_px) * counts_per_px_y
            pipe.update_target((init_tx, init_ty), timestamp_us=0)

            t_us = 0
            for warm_ms in range(10, 145, 10):
                t_us = warm_ms * 1000
                warm_out = pipe.advance(t_us)
                warm_reports = warm_out.get("reports")
                if warm_reports is not None and len(warm_reports) > 0 and np.any(warm_reports != 0):
                    break
            pipe._rendered[:] = (0.0, 0.0)

            cur_cnt_x = 0.0
            cur_cnt_y = 0.0
            ema_tx = init_tx
            ema_ty = init_ty
            sent_hist = deque([(0.0, 0, 0)], maxlen=64)

            for frame_idx in range(24):
                sim_now = (frame_idx + 1) * 0.016
                rem_dx_px = float(target_dx_px) - (cur_cnt_x / counts_per_px_x)
                rem_dy_px = float(target_dy_px) - (cur_cnt_y / counts_per_px_y)
                if dz_enabled and dz_size > 0.0 and (rem_dx_px * rem_dx_px + rem_dy_px * rem_dy_px) ** 0.5 <= dz_size:
                    break

                cap_cx, cap_cy = _lookup_captured_counts(sent_hist, sim_now - _CAPTURE_LAG_SECONDS)
                inflight_x = cur_cnt_x - cap_cx
                inflight_y = cur_cnt_y - cap_cy

                anchor_xy = pipe.rendered_xy
                raw_tx = float(anchor_xy[0]) + rem_dx_px * counts_per_px_x - _INFLIGHT_WEIGHT * float(inflight_x)
                raw_ty = float(anchor_xy[1]) - (rem_dy_px * counts_per_px_y - _INFLIGHT_WEIGHT * float(inflight_y))
                ema_tx = ema_tx + 0.42 * (raw_tx - ema_tx)
                ema_ty = ema_ty + 0.42 * (raw_ty - ema_ty)

                pipe.update_target((ema_tx, ema_ty), timestamp_us=t_us)
                t_us += 16_000
                out = pipe.advance(t_us)
                reports = out.get("reports")
                if reports is not None and len(reports) > 0:
                    for row in reports:
                        sdx = int(round(max(-cap, min(cap, float(row[0])))))
                        sdy = int(round(max(-cap, min(cap, float(row[1])))))
                        if sdx == 0 and sdy == 0:
                            continue
                        cur_cnt_x += sdx
                        cur_cnt_y += sdy
                        steps_count += 1
                        peak_step = max(peak_step, float(abs(sdx)), float(abs(sdy)))
                        points.append((cur_cnt_x / counts_per_px_x, cur_cnt_y / counts_per_px_y))
                sent_hist.append((sim_now, int(round(cur_cnt_x)), int(round(cur_cnt_y))))
                frame_points.append((cur_cnt_x / counts_per_px_x, cur_cnt_y / counts_per_px_y))
    except Exception as exc:
        log_print(f"[ABCurves preview error] {exc}")

    path_len = 0.0
    for idx in range(1, len(points)):
        px0, py0 = points[idx - 1]
        px1, py1 = points[idx]
        path_len += float(((px1 - px0) ** 2 + (py1 - py0) ** 2) ** 0.5)

    end_x, end_y = points[-1]
    chord_len = max(1e-6, float((end_x ** 2 + end_y ** 2) ** 0.5))
    end_error_px = float(((target_dx_px - end_x) ** 2 + (target_dy_px - end_y) ** 2) ** 0.5)
    return {
        "points": points,
        "frame_points": frame_points,
        "target": (float(target_dx_px), float(target_dy_px)),
        "steps_count": int(steps_count),
        "peak_step": int(round(peak_step)),
        "end_error_px": float(end_error_px),
        "curve_ratio": float(path_len / chord_len) if steps_count > 0 else 1.0,
    }
