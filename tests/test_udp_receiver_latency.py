import os
import sys
import unittest
import numpy as np
import time
import turbojpeg

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.capture.OBS_UDP import OBS_UDP_Receiver

class TestUDPReceiverOptimization(unittest.TestCase):
    def setUp(self):
        self.receiver = OBS_UDP_Receiver(ip="127.0.0.1", port=13110, target_fps=144)
        self.tj = turbojpeg.TurboJPEG()
        test_img = np.zeros((128, 128, 3), dtype=np.uint8)
        test_img[30:60, 30:60] = [255, 100, 50]
        self.jpeg_bytes = self.tj.encode(test_img)

    def tearDown(self):
        self.receiver.disconnect()

    def test_decode_cost_is_low(self):
        """Decode cost must stay low.

        Measured synchronously on purpose: stats['decode_delay_ms'] is wall-clock
        time spent on the worker thread, so it also counts GIL/scheduler delay.
        Measured here it is ~0.06ms idle but ~96ms median with the CPU saturated,
        which made the old '< 1.5ms' assertion fail under load while decode itself
        was unaffected. Assert the work this test is actually about.
        """
        samples = []
        for _ in range(20):
            t0 = time.perf_counter()
            frame = self.receiver._decode_jpeg_frame_raw(self.jpeg_bytes)
            samples.append((time.perf_counter() - t0) * 1000.0)
            self.assertIsNotNone(frame)
            self.assertEqual(frame.shape[:2], (128, 128))

        samples.sort()
        median = samples[len(samples) // 2]
        self.assertLess(median, 1.5, f"median decode {median:.3f}ms exceeds 1.5ms")

    def test_single_slot_delivers_latest_frame(self):
        """The single-slot pipeline must decode a complete JPEG and expose it."""
        self.receiver.is_connected = True
        self.receiver.processing_thread = None
        import threading
        self.receiver.processing_thread = threading.Thread(
            target=self.receiver._decode_worker_loop, daemon=True
        )
        self.receiver.processing_thread.start()

        now = time.perf_counter()
        self.receiver._process_mjpeg_data(self.jpeg_bytes, now)

        deadline = time.perf_counter() + 2.0
        frame = None
        while time.perf_counter() < deadline:
            frame = self.receiver.get_current_frame()
            if frame is not None:
                break
            time.sleep(0.005)

        self.assertIsNotNone(frame, "worker never published a frame")
        self.assertEqual(frame.shape[:2], (128, 128))

        stats = self.receiver.get_performance_stats()
        self.assertIn('decode_delay_ms', stats)
        self.assertIn('receive_delay_ms', stats)

if __name__ == '__main__':
    unittest.main()
