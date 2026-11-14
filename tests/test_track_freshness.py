"""A frame must be processed at most once, and the API must stay compatible.

Two independent layers are covered:

* OBS_UDP_Receiver: every decoded frame bumps a monotonic publish sequence, and
  a consumer can wait for "anything newer than seq N". get_current_frame() keeps
  its old zero-copy behaviour for existing callers.
* AimTracker.track_once(): the same frame handed out twice must not reach the
  detection pipeline twice.
"""
import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.capture.capture_service import CaptureService
from src.capture.OBS_UDP import OBS_UDP_Receiver


class TestReceiverFrameSequence(unittest.TestCase):
    def setUp(self):
        self.receiver = OBS_UDP_Receiver(ip="127.0.0.1", port=13111, target_fps=144)
        self.frame = np.zeros((8, 8, 3), dtype=np.uint8)

    def tearDown(self):
        self.receiver.disconnect()

    def test_sequence_starts_at_zero_and_frame_is_none(self):
        frame, seq = self.receiver.get_current_frame_with_seq()
        self.assertIsNone(frame)
        self.assertEqual(seq, 0)

    def test_sequence_increases_per_publish(self):
        seqs = []
        for _ in range(5):
            self.receiver._update_frame(self.frame)
            frame, seq = self.receiver.get_current_frame_with_seq()
            self.assertIs(frame, self.frame)
            seqs.append(seq)

        self.assertEqual(seqs, sorted(seqs))
        self.assertEqual(len(set(seqs)), 5, seqs)
        self.assertTrue(all(b > a for a, b in zip(seqs, seqs[1:])), seqs)

    def test_get_current_frame_still_returns_the_array(self):
        """Existing callers (capture_service, ui) rely on this exact behaviour."""
        self.receiver._update_frame(self.frame)
        frame = self.receiver.get_current_frame()
        self.assertIsInstance(frame, np.ndarray)
        self.assertEqual(frame.shape, (8, 8, 3))

    def test_stats_expose_frame_seq(self):
        self.receiver._update_frame(self.frame)
        stats = self.receiver.get_performance_stats()
        self.assertIn("frame_seq", stats)
        self.assertEqual(stats["frame_seq"], 1)

    def test_five_reads_of_same_seq_report_nothing_new(self):
        self.receiver._update_frame(self.frame)
        _, seq = self.receiver.get_current_frame_with_seq()

        newest = []
        for _ in range(5):
            _, got = self.receiver.wait_for_new_frame(seq, timeout=0.0)
            newest.append(got)
        self.assertEqual(newest, [seq] * 5, "stale frame reported as new")

    def test_one_publish_produces_exactly_one_new_frame(self):
        self.receiver._update_frame(self.frame)
        _, seq = self.receiver.get_current_frame_with_seq()

        self.receiver._update_frame(self.frame)
        frame, got = self.receiver.wait_for_new_frame(seq, timeout=0.0)
        self.assertEqual(got, seq + 1)
        self.assertIs(frame, self.frame)
        # And nothing new after that one publish.
        _, again = self.receiver.wait_for_new_frame(got, timeout=0.0)
        self.assertEqual(again, got)

    def test_wait_wakes_up_on_publish(self):
        _, seq = self.receiver.get_current_frame_with_seq()
        result = {}

        def publish_later():
            time.sleep(0.05)
            self.receiver._update_frame(self.frame)

        producer = threading.Thread(target=publish_later, daemon=True)
        producer.start()
        started = time.perf_counter()
        frame, got = self.receiver.wait_for_new_frame(seq, timeout=1.0)
        waited = time.perf_counter() - started
        producer.join(timeout=1.0)

        self.assertGreater(got, seq)
        self.assertIs(frame, self.frame)
        self.assertLess(waited, 0.5, f"waited {waited:.3f}s for a 50ms publish")

    def test_disconnect_wakes_waiters(self):
        """A blocked consumer must not sit out its timeout after disconnect."""
        _, seq = self.receiver.get_current_frame_with_seq()
        result = {}

        def wait_here():
            result["value"] = self.receiver.wait_for_new_frame(seq, timeout=5.0)

        waiter = threading.Thread(target=wait_here, daemon=True)
        waiter.start()
        time.sleep(0.05)
        started = time.perf_counter()
        self.receiver.disconnect()
        waiter.join(timeout=1.0)
        waited = time.perf_counter() - started

        self.assertFalse(waiter.is_alive(), "waiter ignored disconnect")
        self.assertLess(waited, 1.0, f"disconnect took {waited:.3f}s to wake waiter")
        _, got = result["value"]
        self.assertGreater(got, seq)


class TestCaptureServiceReadFrameWithSeq(unittest.TestCase):
    def _service_with_receiver(self, receiver):
        service = CaptureService()
        service.mode = "UDP"
        service.udp_manager = MagicMock()
        service.udp_manager.get_receiver.return_value = receiver
        return service

    def test_udp_returns_frame_and_sequence(self):
        receiver = MagicMock()
        receiver.wait_for_new_frame.return_value = (np.zeros((4, 4, 3), np.uint8), 7)
        service = self._service_with_receiver(receiver)

        frame, seq = service.read_frame_with_seq(apply_fov=False, after_seq=6, timeout=0.01)
        self.assertIsNotNone(frame)
        self.assertEqual(seq, 7)
        receiver.wait_for_new_frame.assert_called_once_with(6, 0.01)

    def test_udp_unchanged_sequence_returns_no_frame(self):
        receiver = MagicMock()
        receiver.wait_for_new_frame.return_value = (np.zeros((4, 4, 3), np.uint8), 6)
        service = self._service_with_receiver(receiver)

        frame, seq = service.read_frame_with_seq(apply_fov=False, after_seq=6, timeout=0.01)
        self.assertIsNone(frame, "stale frame was handed to the caller")
        self.assertEqual(seq, 6)

    def test_non_udp_modes_have_no_sequence(self):
        service = CaptureService()
        service.mode = "MSS"
        service.read_frame = MagicMock(return_value=np.zeros((4, 4, 3), np.uint8))

        frame, seq = service.read_frame_with_seq(apply_fov=False)
        self.assertIsNotNone(frame)
        self.assertIsNone(seq, "non-UDP capture must stay 'always new'")


class TestTrackOnceFreshness(unittest.TestCase):
    def _tracker(self):
        from main import AimTracker

        tracker = AimTracker.__new__(AimTracker)  # bypass model load / thread start
        tracker.app = MagicMock()
        tracker.app.capture.is_connected.return_value = True
        tracker.app.capture.mode = "UDP"
        tracker._last_frame_seq = None
        tracker._handle_button_mask = MagicMock()
        tracker._update_raw_stream_windows = MagicMock()
        tracker._track_frame = MagicMock()
        tracker._close_raw_stream_windows = MagicMock()
        return tracker

    def test_same_frame_is_processed_once(self):
        tracker = self._tracker()
        frame = np.zeros((16, 16, 3), dtype=np.uint8)
        tracker.app.capture.read_frame_with_seq.side_effect = [
            (frame, 1),
            (frame, 1),
            (frame, 1),
        ]

        results = [tracker.track_once() for _ in range(3)]

        self.assertEqual(results, [True, False, False])
        self.assertEqual(tracker._track_frame.call_count, 1)

    def test_new_frame_is_processed_again(self):
        tracker = self._tracker()
        tracker.app.capture.read_frame_with_seq.side_effect = [
            (np.zeros((16, 16, 3), dtype=np.uint8), 1),
            (np.ones((16, 16, 3), dtype=np.uint8), 2),
        ]

        self.assertTrue(tracker.track_once())
        self.assertTrue(tracker.track_once())
        self.assertEqual(tracker._track_frame.call_count, 2)
        self.assertEqual(tracker._last_frame_seq, 2)

    def test_housekeeping_still_runs_on_a_stale_iteration(self):
        tracker = self._tracker()
        tracker.app.capture.read_frame_with_seq.side_effect = [(None, 4), (None, 4)]
        tracker._last_frame_seq = 4

        self.assertFalse(tracker.track_once())
        self.assertFalse(tracker.track_once())
        self.assertEqual(tracker._handle_button_mask.call_count, 2)

    def test_after_seq_is_forwarded_to_capture(self):
        tracker = self._tracker()
        tracker._last_frame_seq = 11
        tracker.app.capture.read_frame_with_seq.return_value = (None, 11)

        tracker.track_once(frame_timeout=0.002)

        _, kwargs = tracker.app.capture.read_frame_with_seq.call_args
        self.assertEqual(kwargs["after_seq"], 11)
        self.assertEqual(kwargs["timeout"], 0.002)

    def test_disconnected_capture_does_not_touch_frames(self):
        tracker = self._tracker()
        tracker.app.capture.is_connected.return_value = False

        self.assertFalse(tracker.track_once())
        tracker.app.capture.read_frame_with_seq.assert_not_called()
        self.assertEqual(tracker._track_frame.call_count, 0)


if __name__ == "__main__":
    unittest.main()
