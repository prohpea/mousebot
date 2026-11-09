"""Synthetic benchmark for ``AimTracker.track_once`` (plan 7.1 / 12.4).

Run on the target machine — NOT in CI (frame timing is inherently flaky):

    python tools/bench_track_once.py --frames 500 --size 640x360
    python tools/bench_track_once.py --frames 500 --size 1280x720 --csv out.csv

It builds a synthetic frame, fakes the capture service and detection model so no
NDI/UDP/OBS source and no real mouse are required, then reports the p50/p95/p99
latency of one tracking iteration.
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time
from types import SimpleNamespace


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def parse_size(text):
    try:
        width, height = str(text).lower().split("x")
        return int(width), int(height)
    except Exception as exc:
        raise argparse.ArgumentTypeError(f"invalid size {text!r}; expected WxH") from exc


def percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


class FakeCapture:
    """CaptureService stand-in returning the same synthetic frame every call."""

    def __init__(self, frame):
        self._frame = frame
        self.mode = "BENCH"

    def is_connected(self):
        return True

    def read_frame(self, apply_fov=False):
        return self._frame

    def apply_mode_fov(self, frame):
        return frame

    def get_frame_dimensions(self):
        return self._frame.shape[1], self._frame.shape[0]


class FakeMouse:
    def move(self, dx, dy):
        return None


def build_tracker(capture, frame, detection_fn):
    """Minimal AimTracker without threads, model loading or a Tk app."""
    import numpy as np

    import main as main_module

    tracker = main_module.AimTracker.__new__(main_module.AimTracker)
    tracker.app = SimpleNamespace(capture=capture)
    tracker.controller = FakeMouse()
    tracker.move_queue = __import__("queue").Queue(maxsize=200)
    tracker._move_batch_size = 4
    tracker._stop_event = __import__("threading").Event()
    tracker.flick_status = {}
    tracker.calibration_session = False
    tracker._preview_last_time = 0.0
    tracker._frame_count = 0
    tracker._last_frame_log_time = time.time()
    tracker.model = None
    tracker.class_names = []
    tracker._aim_frame = None
    tracker._last_frame = None
    tracker.anti_smoke_detector = None
    tracker.anti_smoke_detector_sec = None
    tracker._target_smoother = SimpleNamespace(
        reset=lambda: None,
        stabilize=lambda targets, cx, cy: targets,
        last_target=None,
        stable_candidate=None,
        stable_count=0,
    )
    tracker.fovsize = 300.0
    tracker.fovsize_sec = 150.0
    tracker.aim_offsetX = 0.0
    tracker.aim_offsetY = 0.0
    tracker.aim_offsetX_sec = 0.0
    tracker.aim_offsetY_sec = 0.0
    tracker.max_speed = 6000.0
    tracker.in_game_sens = 0.23
    tracker.mouse_dpi = 1100.0
    tracker.normal_x_speed = 3.0
    tracker.normal_y_speed = 3.0
    tracker.normalsmooth = 30.0
    tracker.normalsmoothfov = 30.0
    tracker.rcs_pull_speed = 9
    tracker.rcs_activation_delay = 140
    tracker.rcs_rapid_click_threshold = 180
    tracker.tbdelay_min = 0.08
    tracker.tbdelay_max = 0.15
    tracker.tbhold_min = 40
    tracker.tbhold_max = 60
    tracker.tbcooldown_min = 0.0
    tracker.tbcooldown_max = 0.0
    tracker.tbburst_count_min = 1
    tracker.tbburst_count_max = 1
    tracker.tbburst_interval_min = 0.0
    tracker.tbburst_interval_max = 0.0
    tracker.trigger_roi_size = 8
    tracker.trigger_min_pixels = 4
    tracker.trigger_min_ratio = 0.03
    tracker.trigger_confirm_frames = 2
    tracker.silent_distance = 1.0
    tracker.silent_delay = 100.0
    tracker.silent_move_delay = 500.0
    tracker.silent_return_delay = 500.0
    tracker.selector = None
    return tracker


def run_benchmark(size, frames, warmup, csv_path=None):
    import numpy as np

    import main as main_module
    from src.utils import config as config_module

    width, height = size
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    # A plausible blob so the detection path has work to do.
    frame[height // 2 - 40 : height // 2 + 40, width // 2 - 25 : width // 2 + 25] = (40, 40, 230)

    capture = FakeCapture(frame)
    tracker = build_tracker(capture, frame, None)

    # Disable preview drawing: the benchmark measures the tracking pipeline.
    config = config_module.config
    saved = {
        "show_opencv_windows": config.show_opencv_windows,
        "show_opencv_detection": config.show_opencv_detection,
        "show_opencv_mask": config.show_opencv_mask,
    }
    config.show_opencv_windows = False
    config.show_opencv_detection = False
    config.show_opencv_mask = False

    samples = []
    detection_times = []
    try:
        for index in range(warmup + frames):
            start = time.perf_counter()
            tracker.track_once()
            elapsed = (time.perf_counter() - start) * 1000.0
            if index >= warmup:
                samples.append(elapsed)
    finally:
        for key, value in saved.items():
            setattr(config, key, value)

    result = {
        "frame_size": f"{width}x{height}",
        "frames": len(samples),
        "p50_ms": percentile(samples, 0.50),
        "p95_ms": percentile(samples, 0.95),
        "p99_ms": percentile(samples, 0.99),
        "mean_ms": statistics.fmean(samples) if samples else 0.0,
        "max_ms": max(samples) if samples else 0.0,
    }

    if csv_path:
        with open(csv_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(result.keys()))
            writer.writeheader()
            writer.writerow(result)

    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=500, help="measured iterations")
    parser.add_argument("--warmup", type=int, default=50, help="discarded iterations")
    parser.add_argument(
        "--size",
        type=parse_size,
        default=(640, 360),
        help="frame size, e.g. 640x360 or 1280x720",
    )
    parser.add_argument("--csv", default=None, help="optional CSV output path")
    args = parser.parse_args(argv)

    result = run_benchmark(args.size, args.frames, args.warmup, args.csv)
    print(f"frame_size : {result['frame_size']}")
    print(f"frames     : {result['frames']}")
    print(f"p50        : {result['p50_ms']:.3f} ms")
    print(f"p95        : {result['p95_ms']:.3f} ms")
    print(f"p99        : {result['p99_ms']:.3f} ms")
    print(f"mean       : {result['mean_ms']:.3f} ms")
    print(f"max        : {result['max_ms']:.3f} ms")
    if args.csv:
        print(f"csv        : {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
