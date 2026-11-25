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
        chosen_kernel = "numpy" if kernel_backend == "numba" else kernel_backend
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

    kept = []
    flushed_dx = 0
    flushed_dy = 0
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

    return flushed_dx, flushed_dy


def _flush_and_rewind(tracker, pipe, state: Dict[str, Any]) -> Tuple[int, int]:
    """Flush pending ABCurves steps and adjust sent counters to stay in sync."""
    flushed_dx, flushed_dy = _flush_exact_steps(tracker)
    if (flushed_dx != 0 or flushed_dy != 0) and state.get("active", False):
        state["cum_sent_x"] -= flushed_dx
        state["cum_sent_y"] -= flushed_dy
        if state["sent_history"]:
            ts, lx, ly = state["sent_history"][-1]
            state["sent_history"][-1] = (ts, lx - flushed_dx, ly - flushed_dy)
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
        v0_x = float(np.clip(float(delta_cnt[0]) * 0.14 / 16.0, -0.70, 0.70))
        rt._target_history[:, 0] = float(target_xy[0])
        rt._history[:, 0] = v0_x
    if turn_y:
        v0_y = float(np.clip(-float(delta_cnt[1]) * 0.14 / 16.0, -0.70, 0.70))
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
    state["was_held"] = False
    state["sent_history"].clear()


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
            "sent_history": deque(maxlen=64),
            "active": False,
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


def _lookup_captured_counts(history: deque, target_time_s: float) -> Tuple[int, int]:
    if not history:
        return 0, 0
    cap_x, cap_y = history[0][1], history[0][2]
    for ts, cx, cy in history:
        if ts <= target_time_s:
            cap_x, cap_y = cx, cy
        else:
            break
    return cap_x, cap_y


def _enqueue_exact_reports(
    tracker,
    reports: np.ndarray,
    max_step: float,
    dx: float = 0.0,
    dy: float = 0.0,
) -> Tuple[int, int]:
    """Coalesce (0, 0) ticks into step delays and queue genuine 1 kHz humanized moves."""
    steps = []
    cap = abs(float(max_step)) if max_step > 0 else 50.0
    total_dx = 0
    total_dy = 0

    net_dx = int(reports[:, 0].sum()) if len(reports) > 0 else 0
    net_dy = int(reports[:, 1].sum()) if len(reports) > 0 else 0
    suppress_x = (dx > 0.5 and net_dx < 0) or (dx < -0.5 and net_dx > 0)
    suppress_y = (dy > 0.5 and net_dy < 0) or (dy < -0.5 and net_dy > 0)

    for row in reports:
        raw_dx = 0 if suppress_x else int(row[0])
        raw_dy = 0 if suppress_y else int(row[1])
        if raw_dx != 0 or raw_dy != 0:
            cdx, cdy = tracker._clip_movement(raw_dx, raw_dy)
            sdx = int(round(max(-cap, min(cap, float(cdx)))))
            sdy = int(round(max(-cap, min(cap, float(cdy)))))
        else:
            sdx, sdy = 0, 0

        if sdx == 0 and sdy == 0:
            if steps:
                px, py, pdelay = steps[-1]
                steps[-1] = (px, py, min(0.004, pdelay + 0.001))
            else:
                steps.append((0, 0, 0.001))
        else:
            steps.append((sdx, sdy, 0.001))
            total_dx += sdx
            total_dy += sdy

    for sdx, sdy, sdelay in steps:
        if sdx == 0 and sdy == 0:
            continue
        try:
            tracker.move_queue.put_nowait((sdx, sdy, sdelay, True))
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
        state["prev_raw_tx"] = init_tx
        state["prev_raw_ty"] = init_ty
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
        state["sent_history"].clear()
        state["sent_history"].append((now, 0, 0))

        # Let planner burn through silent reaction latency cleanly before frame 0 moves.
        try:
            pipe.update_target((init_tx, init_ty), timestamp_us=0)
            for warm_ms in range(10, 145, 10):
                warm_us = warm_ms * 1000
                warm_out = pipe.advance(warm_us)
                state["last_t_us"] = warm_us
                warm_reports = warm_out.get("reports")
                if warm_reports is not None and len(warm_reports) > 0 and np.any(warm_reports != 0):
                    break
            cur_xy = pipe.current_xy
            state["ema_tx"] = float(cur_xy[0]) + init_tx
            state["ema_ty"] = float(cur_xy[1]) + init_ty
            state["prev_raw_tx"] = state["ema_tx"]
            state["prev_raw_ty"] = state["ema_ty"]
        except Exception as exc:
            log_print(f"[ABCurves warmup error] {exc}")
            reset_abcurves_state(tracker, is_sec=is_sec)
            return
        dt_us = _FIRST_FRAME_US
    else:
        elapsed_us = int(round((now - state["last_call_s"]) * 1_000_000.0))
        dt_us = max(_MIN_STEP_US, min(_MAX_STEP_US, elapsed_us))

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

    def _compute_inflight_delta() -> Tuple[float, float]:
        cap_cx, cap_cy = _lookup_captured_counts(state["sent_history"], now - effective_lag_s)
        inflight_x = state["cum_sent_x"] - cap_cx
        inflight_y = state["cum_sent_y"] - cap_cy
        if float(dx) >= 0.0:
            inflight_x = max(0, inflight_x)
            dtx = max(0.0, float(dx) * counts_per_px_x - _INFLIGHT_WEIGHT * float(inflight_x))
        else:
            inflight_x = min(0, inflight_x)
            dtx = min(0.0, float(dx) * counts_per_px_x - _INFLIGHT_WEIGHT * float(inflight_x))
        if float(dy) >= 0.0:
            inflight_y = max(0, inflight_y)
            dty = max(0.0, float(dy) * counts_per_px_y - _INFLIGHT_WEIGHT * float(inflight_y))
        else:
            inflight_y = min(0, inflight_y)
            dty = min(0.0, float(dy) * counts_per_px_y - _INFLIGHT_WEIGHT * float(inflight_y))
        return dtx, dty

    delta_tx, delta_ty = _compute_inflight_delta()

    sig_dx = float(state.get("sig_dx", 0.0))
    sig_dy = float(state.get("sig_dy", 0.0))
    turn_x = (
        (float(dx) * sig_dx < 0.0)
        and (abs(float(dx)) >= 3.5)
        and (abs(delta_tx) >= 3.0 * counts_per_px_x)
        and ((now - float(state.get("last_turn_x_s", -1.0))) >= 0.075)
    )
    turn_y = (
        (float(dy) * sig_dy < 0.0)
        and (abs(float(dy)) >= 3.5)
        and (abs(delta_ty) >= 3.0 * counts_per_px_y)
        and ((now - float(state.get("last_turn_y_s", -1.0))) >= 0.075)
    )
    if abs(float(dx)) >= 3.5:
        state["sig_dx"] = float(dx)
    if abs(float(dy)) >= 3.5:
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
    alpha_x = 1.0 if (turn_x or was_held) else 0.60
    alpha_y = 1.0 if (turn_y or was_held) else 0.60
    ema_tx = raw_tx if state["ema_tx"] is None else (state["ema_tx"] + alpha_x * (raw_tx - state["ema_tx"]))
    ema_ty = raw_ty if state["ema_ty"] is None else (state["ema_ty"] + alpha_y * (raw_ty - state["ema_ty"]))
    state["ema_tx"] = ema_tx
    state["ema_ty"] = ema_ty

    # Velocity lead estimation (activates ema_vx / ema_vy with turn-reversal zeroing)
    target_tx = ema_tx
    target_ty = ema_ty
    if turn_x:
        state["ema_vx"] = 0.0
    if turn_y:
        state["ema_vy"] = 0.0
    if dt_us > 0 and not was_held:
        dt_s = float(dt_us) * 1e-6
        if dt_s >= 0.002 and state.get("prev_raw_tx") is not None:
            inst_vx = (raw_tx - float(state["prev_raw_tx"])) / dt_s
            inst_vy = (raw_ty - float(state["prev_raw_ty"])) / dt_s
            # Filter out noise spikes (>2800 counts/s)
            if abs(inst_vx) <= 2800.0 and not turn_x:
                state["ema_vx"] = float(state.get("ema_vx", 0.0)) + 0.35 * (inst_vx - float(state.get("ema_vx", 0.0)))
            if abs(inst_vy) <= 2800.0 and not turn_y:
                state["ema_vy"] = float(state.get("ema_vy", 0.0)) + 0.35 * (inst_vy - float(state.get("ema_vy", 0.0)))
    state["prev_raw_tx"] = raw_tx
    state["prev_raw_ty"] = raw_ty

    if getattr(config, "velocity_lead_enabled", False) and not (turn_x or turn_y) and not was_held:
        lead_gain = max(0.0, min(1.2, float(getattr(config, "velocity_lead_gain", 0.55))))
        max_lead_px = max(0.0, min(25.0, float(getattr(config, "velocity_lead_max_px", 12.0))))
        lead_s = effective_lag_s * lead_gain
        lead_x = max(-max_lead_px * counts_per_px_x, min(max_lead_px * counts_per_px_x, float(state["ema_vx"]) * lead_s))
        lead_y = max(-max_lead_px * counts_per_px_y, min(max_lead_px * counts_per_px_y, float(state["ema_vy"]) * lead_s))
        target_tx = ema_tx + lead_x
        target_ty = ema_ty + lead_y

    t_receipt_us = state["last_t_us"]
    t_next_us = t_receipt_us + dt_us
    try:
        # Prevent stochastic mid-flight BRAKE recoil while keeping planner responsive to turns.
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
        pipe.update_target((target_tx, target_ty), timestamp_us=t_receipt_us)
        out = pipe.advance(t_next_us)
    except Exception as exc:
        log_print(f"[ABCurves runtime error] {exc}")
        reset_abcurves_state(tracker, is_sec=is_sec)
        return

    state["last_t_us"] = t_next_us

    try:
        from src.utils.mouse import update_movement_lock

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

    reports = out.get("reports")
    if reports is not None and len(reports) > 0:
        total_dx, total_dy = _enqueue_exact_reports(
            tracker,
            reports,
            max_step=max_step,
            dx=float(dx),
            dy=float(dy),
        )
        state["cum_sent_x"] += total_dx
        state["cum_sent_y"] += total_dy
        state["last_sent_px_x"] = float(total_dx) / max(1e-6, counts_per_px_x)
        state["last_sent_px_y"] = float(total_dy) / max(1e-6, counts_per_px_y)
        state["sent_history"].append((now, state["cum_sent_x"], state["cum_sent_y"]))
        if total_dx != 0 or total_dy != 0:
            log_move(total_dx, total_dy, label)
    else:
        state["last_sent_px_x"] = 0.0
        state["last_sent_px_y"] = 0.0
        state["sent_history"].append((now, state["cum_sent_x"], state["cum_sent_y"]))


def hold_abcurves_state(tracker, is_sec: bool = False) -> None:
    """Softly settle ABCurves at current position inside Stop Aim FOV without harsh reset."""
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

    elapsed_us = int(round((now - state["last_call_s"]) * 1_000_000.0))
    dt_us = max(_MIN_STEP_US, min(_MAX_STEP_US, elapsed_us))
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

    # Let any remaining final tail steps in move_queue coast to a natural stop cleanly.
    if hasattr(pipe, "movement"):
        pipe.movement._history[:] = 0.0

    anchor_xy = pipe.current_xy
    state["ema_tx"] = float(anchor_xy[0])
    state["ema_ty"] = float(anchor_xy[1])
    state["prev_raw_tx"] = float(anchor_xy[0])
    state["prev_raw_ty"] = float(anchor_xy[1])
    t_receipt_us = state["last_t_us"]
    t_next_us = t_receipt_us + dt_us
    try:
        pipe.update_target((state["ema_tx"], state["ema_ty"]), timestamp_us=t_receipt_us)
        pipe.advance(t_next_us)
        state["last_t_us"] = t_next_us
    except Exception:
        reset_abcurves_state(tracker, is_sec=is_sec)
        return
    state["sent_history"].append((now, state["cum_sent_x"], state["cum_sent_y"]))


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
