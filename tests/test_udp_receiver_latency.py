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

    def test_single_slot_decode_latency(self):
        self.receiver.is_connected = True
        self.receiver.processing_thread = None
        if hasattr(self.receiver, '_decode_worker_loop'):
            import threading
            self.receiver.processing_thread = threading.Thread(target=self.receiver._decode_worker_loop, daemon=True)
            self.receiver.processing_thread.start()

        # Send frame
        now = time.perf_counter()
        self.receiver._process_mjpeg_data(self.jpeg_bytes, now)
        time.sleep(0.05)

        stats = self.receiver.get_performance_stats()
        self.assertIn('decode_delay_ms', stats)
        self.assertIn('receive_delay_ms', stats)
        # Verify decode latency is under 1.5ms (usually 0.3ms with TurboJPEG)
        self.assertLess(stats['decode_delay_ms'], 1.5)
        # Verify frame was received and decoded
        frame = self.receiver.get_current_frame()
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape[:2], (128, 128))

if __name__ == '__main__':
    unittest.main()
