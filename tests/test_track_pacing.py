"""The tracking loop must actually reach target_fps, not "almost".

time.sleep() on Windows rounds up to the next timer tick, so the old
``sleep(period - elapsed)`` scheme measured 127.7 fps at target 144 and 162.6
at target 200. The loop now paces on an absolute deadline and spins only the
last fraction of a millisecond.

The real-time tests are deliberately coarse (0.95 x target over ~1.5 s) and are
compared against the old scheme measured in the same process, so a busy machine
cannot turn them into a coin flip.
"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from main import AimTracker, _pacing_deadline


class TestPacingDeadlineMath(unittest.TestCase):
    def test_deadline_is_kept_while_on_schedule(self):
        self.assertEqual(_pacing_deadline(1.000, 1.004, 0.005), 1.000)

    def test_resync_after_overrun(self):
        """Falling behind by more than a period must not queue missed slots."""
        self.assertEqual(_pacing_deadline(1.000, 1.020, 0.005), 1.020)

    def test_resync_when_next_deadline_is_too_far(self):
        """Raising target_fps moves the deadline out; resync instead of stalling."""
        self.assertEqual(_pacing_deadline(1.050, 1.000, 0.005), 1.000)

    def test_exact_period_is_not_a_resync(self):
        self.assertEqual(_pacing_deadline(1.005, 1.000, 0.005), 1.005)


class _LoopHarness:
    """Run AimTracker._track_loop with a fake track_once of known cost."""

    def __init__(self, target_fps, work_s):
        self.tracker = AimTracker.__new__(AimTracker)  # bypass model/thread start
        self.tracker._target_fps = float(target_fps)
        self.tracker._stop_event = threading.Event()
        self.work_s = work_s
        self.iterations = 0
        self.lock = threading.Lock()

        def fake_track_once(frame_timeout=0.0):
            end = time.perf_counter() + self.work_s
            while time.perf_counter() < end:
                pass
            with self.lock:
                self.iterations += 1

        self.tracker.track_once = fake_track_once

    def measure(self, duration_s):
        thread = threading.Thread(target=self.tracker._track_loop, daemon=True)
        started = time.perf_counter()
        thread.start()
        time.sleep(duration_s)
        self.tracker._stop_event.set()
        thread.join(timeout=3.0)
        elapsed = time.perf_counter() - started
        with self.lock:
            iterations = self.iterations
        return iterations / elapsed if elapsed > 0 else 0.0

    def measure_legacy(self, duration_s):
        """The old ``sleep(period - elapsed)`` scheme, same process, same work."""
        stop = threading.Event()
        counter = {"n": 0}

        def loop():
            while not stop.is_set():
                start = time.perf_counter()
                end = start + self.work_s
                while time.perf_counter() < end:
                    pass
                counter["n"] += 1
                period = 1.0 / float(self.tracker._target_fps)
                to_sleep = period - (time.perf_counter() - start)
                if to_sleep > 0.0005:
                    time.sleep(to_sleep)

        thread = threading.Thread(target=loop, daemon=True)
        started = time.perf_counter()
        thread.start()
        time.sleep(duration_s)
        stop.set()
        thread.join(timeout=3.0)
        elapsed = time.perf_counter() - started
        return counter["n"] / elapsed if elapsed > 0 else 0.0


class TestTrackLoopThroughput(unittest.TestCase):
    duration_s = 1.5

    def _assert_reaches(self, target_fps):
        harness = _LoopHarness(target_fps, work_s=0.0009)
        measured = harness.measure(self.duration_s)
        self.assertGreaterEqual(
            measured,
            0.95 * target_fps,
            f"track loop reached {measured:.1f} fps, target {target_fps}",
        )
        return measured

    def test_144_hz_target(self):
        self._assert_reaches(144)

    def test_200_hz_target(self):
        self._assert_reaches(200)

    def test_faster_than_period_minus_elapsed_sleep(self):
        target_fps = 200
        harness = _LoopHarness(target_fps, work_s=0.0009)
        legacy = harness.measure_legacy(self.duration_s)
        current = harness.measure(self.duration_s)
        self.assertGreaterEqual(
            current,
            legacy + 3.0,
            f"deadline+spin {current:.1f} fps is not clearly above "
            f"sleep(period-elapsed) {legacy:.1f} fps",
        )


if __name__ == "__main__":
    unittest.main()
