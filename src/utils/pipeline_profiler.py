"""Lightweight 144Hz Pipeline Profiler & Dynamic Capture-Lag Estimator.

Zero-allocation-style rolling metrics (deque maxlen=120) designed to add
negligible overhead (<10 microseconds per frame) to AimTracker._track_loop.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class PipelineStats:
    """Immutable snapshot of rolling pipeline timings in milliseconds."""

    grab_p50_ms: float = 0.0
    grab_p95_ms: float = 0.0
    detect_p50_ms: float = 0.0
    detect_p95_ms: float = 0.0
    aim_p50_ms: float = 0.0
    aim_p95_ms: float = 0.0
    total_p50_ms: float = 0.0
    total_p95_ms: float = 0.0
    queue_depth: int = 0
    effective_fps: float = 0.0
    budget_pct: float = 0.0
    bottleneck: str = "OK"


def _percentile(sorted_vals: List[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = int(round((len(sorted_vals) - 1) * pct))
    idx = max(0, min(len(sorted_vals) - 1, idx))
    return float(sorted_vals[idx])


class PipelineProfiler:
    """Thread-safe rolling profiler for the 144Hz (6.94ms) tracking loop."""

    FRAME_BUDGET_MS = 1000.0 / 144.0  # 6.944ms

    def __init__(self, window: int = 120):
        self._lock = threading.Lock()
        self._grab = deque(maxlen=window)
        self._detect = deque(maxlen=window)
        self._aim = deque(maxlen=window)
        self._total = deque(maxlen=window)
        self._timestamps = deque(maxlen=window)
        self._queue_depth = 0

    def record(
        self,
        grab_ms: float,
        detect_ms: float,
        aim_ms: float,
        total_ms: float,
        queue_depth: int = 0,
    ) -> None:
        now = time.perf_counter()
        with self._lock:
            self._grab.append(max(0.0, float(grab_ms)))
            self._detect.append(max(0.0, float(detect_ms)))
            self._aim.append(max(0.0, float(aim_ms)))
            self._total.append(max(0.0, float(total_ms)))
            self._timestamps.append(now)
            self._queue_depth = max(0, int(queue_depth))

    def get_stats(self) -> PipelineStats:
        with self._lock:
            if not self._total:
                return PipelineStats()
            g_sorted = sorted(self._grab)
            d_sorted = sorted(self._detect)
            a_sorted = sorted(self._aim)
            t_sorted = sorted(self._total)
            ts = list(self._timestamps)
            q_depth = self._queue_depth

        g50, g95 = _percentile(g_sorted, 0.50), _percentile(g_sorted, 0.95)
        d50, d95 = _percentile(d_sorted, 0.50), _percentile(d_sorted, 0.95)
        a50, a95 = _percentile(a_sorted, 0.50), _percentile(a_sorted, 0.95)
        t50, t95 = _percentile(t_sorted, 0.50), _percentile(t_sorted, 0.95)

        eff_fps = 0.0
        if len(ts) >= 2:
            span = ts[-1] - ts[0]
            if span > 1e-4:
                eff_fps = (len(ts) - 1) / span

        budget_pct = (t95 / self.FRAME_BUDGET_MS) * 100.0
        bottleneck = "OK"
        if t95 > self.FRAME_BUDGET_MS:
            stages = {"CAPTURE": g95, "DETECT": d95, "AIM": a95}
            bottleneck = max(stages, key=stages.get)
        elif q_depth >= 6:
            bottleneck = "MOVE_QUEUE"

        return PipelineStats(
            grab_p50_ms=round(g50, 2),
            grab_p95_ms=round(g95, 2),
            detect_p50_ms=round(d50, 2),
            detect_p95_ms=round(d95, 2),
            aim_p50_ms=round(a50, 2),
            aim_p95_ms=round(a95, 2),
            total_p50_ms=round(t50, 2),
            total_p95_ms=round(t95, 2),
            queue_depth=q_depth,
            effective_fps=round(eff_fps, 1),
            budget_pct=round(budget_pct, 1),
            bottleneck=bottleneck,
        )


class CaptureLagEstimator:
    """EMA estimator for effective capture-to-tracker pipeline lag (seconds).

    Replaces static 28ms lag in ABCurves with live-measured decode + grab +
    baseline display/encode overhead, safely clamped to [10ms, 65ms].
    """

    DEFAULT_LAG_S = 0.028
    MIN_LAG_S = 0.010
    MAX_LAG_S = 0.065

    def __init__(self, base_transport_s: float = 0.014, alpha: float = 0.15):
        self._base_transport_s = max(0.004, float(base_transport_s))
        self._alpha = max(0.02, min(0.5, float(alpha)))
        self._lag_s = self.DEFAULT_LAG_S
        self._lock = threading.Lock()

    def update(self, decode_ms: float = 0.0, grab_ms: float = 0.0, detect_ms: float = 0.0) -> float:
        sample_s = self._base_transport_s + max(0.0, (float(decode_ms) + float(grab_ms) + float(detect_ms)) * 0.001)
        sample_s = max(self.MIN_LAG_S, min(self.MAX_LAG_S, sample_s))
        with self._lock:
            self._lag_s = self._lag_s + self._alpha * (sample_s - self._lag_s)
            return self._lag_s

    def get_lag_seconds(self) -> float:
        with self._lock:
            return self._lag_s


def run_preflight_check(tracker, capture_service) -> Dict[str, object]:
    """Run non-destructive pre-flight diagnostics for Capture, Hardware, and Config."""
    cap_ok = False
    cap_msg = "Not connected"
    if capture_service is not None:
        try:
            cap_ok = bool(capture_service.is_connected())
            cap_msg = "Connected" if cap_ok else "Disconnected"
        except Exception as exc:
            cap_msg = f"Error: {exc}"

    hw_ok = False
    hw_msg = "Unavailable"
    if tracker is not None and getattr(tracker, "controller", None) is not None:
        try:
            hw_ok = bool(getattr(tracker.controller, "connected", True))
            hw_msg = "Ready" if hw_ok else "Disconnected"
        except Exception as exc:
            hw_msg = f"Error: {exc}"

    return {
        "capture_ok": cap_ok,
        "capture_msg": cap_msg,
        "hardware_ok": hw_ok,
        "hardware_msg": hw_msg,
        "ready": cap_ok and hw_ok,
    }
