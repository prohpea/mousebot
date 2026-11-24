"""Preview rendering must never block the tracking thread.

cv2.imshow/waitKey were called from the tracker thread, and a single
waitKey(1) costs ~2 ms (16 ms without timeBeginPeriod), stealing whole frames
from a 5 ms budget. preview_throttle now funnels every HighGUI call through one
daemon worker; imshow()/destroy() only enqueue.

The stub here sleeps 16 ms per imshow *and* per waitKey, which is the worst
measured case: submitting 200 frames must still take far less than one of
those renders.
"""
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.utils import preview_throttle

_RENDER_STUB_S = 0.016


class TestPreviewDoesNotBlockCaller(unittest.TestCase):
    def setUp(self):
        preview_throttle.shutdown()
        self.rendered = []
        self.pumped = []
        self.destroyed = []
        self.lock = threading.Lock()

        def slow_imshow(name, image):
            time.sleep(_RENDER_STUB_S)
            with self.lock:
                self.rendered.append(name)

        def slow_wait_key(delay):
            time.sleep(_RENDER_STUB_S)
            with self.lock:
                self.pumped.append(delay)
            return -1

        def record_destroy(name):
            with self.lock:
                self.destroyed.append(name)

        self._patches = [
            patch.object(preview_throttle, "_cv2_imshow", slow_imshow),
            patch.object(preview_throttle, "_cv2_wait_key", slow_wait_key),
            patch.object(preview_throttle, "_cv2_destroy", record_destroy),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        preview_throttle.shutdown()
        preview_throttle.reset()

    def test_submit_is_cheap_and_worker_paints(self):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)

        started = time.perf_counter()
        for _ in range(200):
            preview_throttle.imshow("Detection", image)
        submit_s = time.perf_counter() - started

        self.assertLess(
            submit_s, 0.1,
            f"200 imshow submits took {submit_s * 1000:.1f} ms on the caller thread",
        )

        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline and not self.rendered:
            time.sleep(0.005)

        stats = preview_throttle.stats()
        self.assertGreaterEqual(stats["rendered"], 1, "worker never painted a frame")
        self.assertGreaterEqual(len(self.rendered), 1)
        self.assertLessEqual(
            stats["rendered"], 5,
            f"worker replayed {stats['rendered']} stale frames instead of the newest",
        )

    def test_shutdown_joins_quickly(self):
        image = np.zeros((16, 16, 3), dtype=np.uint8)
        preview_throttle.imshow("MASK", image)

        started = time.perf_counter()
        preview_throttle.shutdown(timeout=2.0)
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 2.0, f"shutdown took {elapsed:.2f}s")
        self.assertFalse(preview_throttle.stats()["worker_alive"])

    def test_destroy_only_for_created_windows(self):
        preview_throttle.destroy("NeverShown")
        time.sleep(0.05)
        self.assertEqual(self.destroyed, [])

        image = np.zeros((16, 16, 3), dtype=np.uint8)
        preview_throttle.imshow("ROI", image)
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline and not self.rendered:
            time.sleep(0.005)

        preview_throttle.destroy("ROI")
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline and "ROI" not in self.destroyed:
            time.sleep(0.005)
        self.assertIn("ROI", self.destroyed)

    def test_stale_frame_is_replaced_not_queued(self):
        preview_throttle.imshow("Detection", np.zeros((8, 8, 3), dtype=np.uint8))
        preview_throttle.imshow("Detection", np.ones((8, 8, 3), dtype=np.uint8))

        stats = preview_throttle.stats()
        self.assertLessEqual(stats["pending"], 1, "more than one frame queued per window")
        self.assertGreaterEqual(stats["overwritten"], 1)

    def test_worker_restarts_after_shutdown(self):
        image = np.zeros((8, 8, 3), dtype=np.uint8)
        preview_throttle.imshow("Detection", image)
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline and not self.rendered:
            time.sleep(0.005)

        preview_throttle.shutdown(timeout=2.0)
        self.assertFalse(preview_throttle.stats()["worker_alive"])

        before = len(self.rendered)
        preview_throttle.imshow("Detection", image)
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline and len(self.rendered) <= before:
            time.sleep(0.005)
        self.assertGreater(len(self.rendered), before, "worker did not restart")


class TestThrottleHelpers(unittest.TestCase):
    def tearDown(self):
        preview_throttle.reset()

    def test_render_if_due_is_rate_limited(self):
        preview_throttle.reset()
        self.assertTrue(preview_throttle.render_if_due("Detection"))
        self.assertFalse(preview_throttle.render_if_due("Detection"))


if __name__ == "__main__":
    unittest.main()
