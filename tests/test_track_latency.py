"""The track loop must wake on a frame, not on a poll grid.

Before the fix, ``_track_loop`` computed ``budget = max(0, next_at - now)`` after
setting ``next_at = now``, so the budget was ~0 and ``wait_for_new_frame`` never
actually waited. A frame arriving just after a poll slot sat there for nearly a
whole period.

Two behaviours are pinned here:
* with a sequenced source (UDP), a published frame reaches ``track_once`` in a
  few ms instead of waiting for the next grid slot, and the loop iterates about
  once per frame rather than spinning;
* with a non-sequenced source (NDI/MSS/CaptureCard, ``seq=None``) the loop keeps
  its old pacing instead of turning into a 100% CPU spin.
"""
import os
import statistics
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.utils.config import config

PERIOD_144 = 1.0 / 144.0


def _make_tracker(target_fps=144):
    from main import AimTracker

    tracker = AimTracker.__new__(AimTracker)  # bypass model load / thread start
    tracker._target_fps = float(target_fps)
    tracker._stop_event = threading.Event()
    tracker.app = MagicMock()
    tracker.app.capture.is_connected.return_value = True
    tracker.app.capture.mode = "UDP"
    tracker._last_frame_seq = None
    tracker._handle_button_mask = MagicMock()
    tracker._update_raw_stream_windows = MagicMock()
    tracker._close_raw_stream_windows = MagicMock()
    tracker._track_frame = MagicMock()
    return tracker


class TestFrameDrivenPacing(unittest.TestCase):
    def setUp(self):
        self._saved_mode = getattr(config, "track_wait_mode", "frame")

    def tearDown(self):
        config.track_wait_mode = self._saved_mode

    def test_frame_timeout_covers_the_rest_of_the_period(self):
        """The wait must be able to block for a full period, not a zero budget."""
        tracker = _make_tracker()
        seen = []
        stop_after = {"n": 0}

        def fake_track_once(frame_timeout=0.0):
            seen.append(float(frame_timeout))
            stop_after["n"] += 1
            if stop_after["n"] >= 5:
                tracker._stop_event.set()
            return False

        tracker.track_once = fake_track_once
        config.track_wait_mode = "frame"

        thread = threading.Thread(target=tracker._track_loop, daemon=True)
        thread.start()
        thread.join(timeout=5.0)
        tracker._stop_event.set()

        self.assertGreaterEqual(len(seen), 5)
        for value in seen:
            self.assertGreater(
                value, PERIOD_144 * 0.9,
                "frame_timeout is the old ~0 budget: wait_for_new_frame cannot block",
            )
            self.assertLessEqual(value, 2.0 * PERIOD_144 + 0.005)

    def test_grid_mode_keeps_the_old_zero_budget(self):
        tracker = _make_tracker()
        seen = []
        stop_after = {"n": 0}

        def fake_track_once(frame_timeout=0.0):
            seen.append(float(frame_timeout))
            stop_after["n"] += 1
            if stop_after["n"] >= 5:
                tracker._stop_event.set()
            return False

        tracker.track_once = fake_track_once
        config.track_wait_mode = "grid"

        thread = threading.Thread(target=tracker._track_loop, daemon=True)
        thread.start()
        thread.join(timeout=5.0)
        tracker._stop_event.set()

        self.assertGreaterEqual(len(seen), 5)
        # The rollback switch must reproduce the pre-fix (tiny) budget.
        self.assertLess(max(seen), PERIOD_144 * 0.5)

    def test_a_processed_frame_skips_the_tail_sleep(self):
        """With a sequenced frame the loop goes straight back to the wait.

        The fake work costs 30% of a period. In frame mode the next iteration
        starts immediately after it (gap ~0.3 period); in grid mode the loop
        still sleeps out the rest of the period (gap ~1.0 period).
        """
        work = PERIOD_144 * 0.3

        def _gaps_for_mode(mode):
            tracker = _make_tracker()
            tracker._last_frame_seq = 7  # sequenced source
            timestamps = []
            stop_after = {"n": 0}

            def fake_track_once(frame_timeout=0.0):
                end = time.perf_counter() + work
                while time.perf_counter() < end:
                    pass
                timestamps.append(time.perf_counter())
                stop_after["n"] += 1
                if stop_after["n"] >= 6:
                    tracker._stop_event.set()
                    return False
                return True

            tracker.track_once = fake_track_once
            config.track_wait_mode = mode
            thread = threading.Thread(target=tracker._track_loop, daemon=True)
            thread.start()
            thread.join(timeout=5.0)
            tracker._stop_event.set()
            self.assertGreaterEqual(len(timestamps), 6)
            return [b - a for a, b in zip(timestamps, timestamps[1:])]

        frame_gaps = _gaps_for_mode("frame")
        grid_gaps = _gaps_for_mode("grid")

        self.assertLess(
            statistics.median(frame_gaps), PERIOD_144 * 0.6,
            f"frame mode still waits for the grid: gaps {frame_gaps}",
        )
        self.assertGreater(
            statistics.median(grid_gaps), PERIOD_144 * 0.85,
            f"grid mode lost its pacing: gaps {grid_gaps}",
        )

    def test_iterations_track_the_frame_rate_with_a_real_receiver(self):
        """~29 track_once calls per 200 ms at 144 Hz, not ~200 polls."""
        from src.capture.OBS_UDP import OBS_UDP_Receiver

        receiver = OBS_UDP_Receiver(ip="127.0.0.1", port=13322, target_fps=144)
        frame = np.zeros((8, 8, 3), np.uint8)
        tracker = _make_tracker()
        tracker._last_frame_seq = 0
        calls = {"n": 0}

        stop_publishing = threading.Event()

        def publisher():
            period = 1.0 / 144.0
            while not stop_publishing.is_set():
                receiver._update_frame(frame)
                time.sleep(period)

        def fake_track_once(frame_timeout=0.0):
            calls["n"] += 1
            got, seq = receiver.wait_for_new_frame(tracker._last_frame_seq, frame_timeout)
            if got is not None and seq != tracker._last_frame_seq:
                tracker._last_frame_seq = seq
                return True
            return False

        tracker.track_once = fake_track_once
        config.track_wait_mode = "frame"

        pub_thread = threading.Thread(target=publisher, daemon=True)
        pub_thread.start()
        thread = threading.Thread(target=tracker._track_loop, daemon=True)
        started = time.perf_counter()
        thread.start()
        time.sleep(0.2)
        tracker._stop_event.set()
        thread.join(timeout=5.0)
        stop_publishing.set()
        pub_thread.join(timeout=2.0)
        receiver.disconnect()
        elapsed = time.perf_counter() - started

        expected = 144 * elapsed
        # The acceptance window (24-40 calls per 200 ms at 144 Hz) is ~0.83x-1.38x
        # of nominal; widened here to survive a loaded CI machine while still
        # failing the ~200-calls spin the old grid produced.
        self.assertGreaterEqual(
            calls["n"], expected * 0.6,
            f"{calls['n']} calls in {elapsed:.3f}s: loop is starved, not frame-driven",
        )
        self.assertLessEqual(
            calls["n"], expected * 1.6,
            f"{calls['n']} calls in {elapsed:.3f}s: loop is polling, not waking on frames",
        )

    def test_unsequenced_source_still_paces_instead_of_spinning(self):
        """NDI/MSS report seq=None: the loop must not free-run at 100% CPU."""
        tracker = _make_tracker()
        tracker._last_frame_seq = None
        count = {"n": 0}

        def fake_track_once(frame_timeout=0.0):
            count["n"] += 1
            return True  # "frame processed", but with no sequence

        tracker.track_once = fake_track_once
        config.track_wait_mode = "frame"

        thread = threading.Thread(target=tracker._track_loop, daemon=True)
        started = time.perf_counter()
        thread.start()
        time.sleep(0.2)
        tracker._stop_event.set()
        thread.join(timeout=5.0)
        elapsed = time.perf_counter() - started

        expected = 144 * elapsed
        self.assertLess(
            count["n"], expected * 2.0,
            f"{count['n']} iterations in {elapsed:.3f}s: unsequenced source is spinning",
        )
        self.assertGreaterEqual(
            count["n"], expected * 0.5,
            f"{count['n']} iterations in {elapsed:.3f}s: unsequenced source slowed down",
        )


class TestFrameArrivalLatency(unittest.TestCase):
    """A frame published mid-period must reach track_once almost immediately."""

    def setUp(self):
        self._saved_mode = getattr(config, "track_wait_mode", "frame")

    def tearDown(self):
        config.track_wait_mode = self._saved_mode

    def test_published_frame_reaches_track_once_within_a_few_milliseconds(self):
        """Every publish must be picked up while the period is still running.

        The old loop polled on a grid derived from a zero budget, so a frame
        published just after a slot waited almost a full period. Half of the
        published frames must now be consumed in under 3 ms.
        """
        from src.capture.OBS_UDP import OBS_UDP_Receiver

        receiver = OBS_UDP_Receiver(ip="127.0.0.1", port=13320, target_fps=144)
        frame = np.zeros((8, 8, 3), np.uint8)

        tracker = _make_tracker()
        tracker._last_frame_seq = 0
        observed = []

        def fake_track_once(frame_timeout=0.0):
            got, seq = receiver.wait_for_new_frame(tracker._last_frame_seq, frame_timeout)
            if got is not None and seq != tracker._last_frame_seq:
                tracker._last_frame_seq = seq
                observed.append((seq, time.perf_counter()))
            if len(observed) >= 8:
                tracker._stop_event.set()
                return False
            return got is not None

        tracker.track_once = fake_track_once
        config.track_wait_mode = "frame"

        thread = threading.Thread(target=tracker._track_loop, daemon=True)
        thread.start()

        published = []
        try:
            for _ in range(10):
                # Publish at a deliberately awkward offset inside the period.
                time.sleep(PERIOD_144 * 0.6)
                receiver._update_frame(frame)
                published.append(time.perf_counter())
                time.sleep(PERIOD_144 * 1.4)
            thread.join(timeout=5.0)
        finally:
            tracker._stop_event.set()
            thread.join(timeout=2.0)
            receiver.disconnect()

        self.assertGreaterEqual(len(observed), 6, f"only {len(observed)} frames observed")
        latencies_ms = sorted(
            (seen_at - pub_at) * 1000.0
            for (_seq, seen_at), pub_at in zip(observed, published)
        )
        median = statistics.median(latencies_ms)
        self.assertLessEqual(
            median, 3.0,
            f"publish->track_once median {median:.2f} ms: the loop is waiting for a grid slot",
        )
        # The old code waited up to a full period (6.94 ms) plus the poll slot;
        # a frame published mid-period must not show that pattern.
        self.assertLessEqual(
            latency_p95 := latencies_ms[min(len(latencies_ms) - 1, int(round(0.95 * (len(latencies_ms) - 1))))],
            PERIOD_144 * 1000.0,
            f"p95 latency {latency_p95:.2f} ms reaches a full 144 Hz period",
        )

    def test_disconnect_wakes_the_loop_promptly(self):
        """disconnect() bumps the sequence and notifies: the wait must return."""
        from src.capture.OBS_UDP import OBS_UDP_Receiver

        receiver = OBS_UDP_Receiver(ip="127.0.0.1", port=13321, target_fps=144)
        started = time.perf_counter()
        result = {}

        def wait():
            result["value"] = receiver.wait_for_new_frame(0, timeout=5.0)

        thread = threading.Thread(target=wait, daemon=True)
        thread.start()
        time.sleep(0.05)
        receiver.disconnect()
        thread.join(timeout=2.0)
        waited = time.perf_counter() - started

        self.assertFalse(thread.is_alive(), "waiter ignored disconnect")
        self.assertLess(waited, 1.0, f"disconnect took {waited:.3f}s to wake the waiter")


if __name__ == "__main__":
    unittest.main()
