import struct
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

import main as main_mod
from src.capture.OBS_UDP import OBS_UDP_Receiver
from src.utils.config import config
from src.utils.i18n import i18n


class UltimateRegressionTests(unittest.TestCase):
    def test_obs_udp_accepts_dark_contrast_crushed_xudp_frame(self):
        # Pure black frame (e.g. xUDP Reduce Background + Contrast Crush when no enemy is present)
        dark_frame = np.zeros((320, 320, 3), dtype=np.uint8)
        self.assertFalse(OBS_UDP_Receiver._is_frame_corrupted(dark_frame))

        # Invalid/empty frames are still rejected
        self.assertTrue(OBS_UDP_Receiver._is_frame_corrupted(np.zeros((0, 0, 3), dtype=np.uint8)))
        self.assertTrue(OBS_UDP_Receiver._is_frame_corrupted(np.zeros((4, 4, 3), dtype=np.uint8)))

    def test_obs_udp_reassembles_fragmented_xudp_packets(self):
        # Build a valid synthetic JPEG > 65000 bytes (padded with JPEG comment)
        img = np.zeros((64, 64, 3), dtype=np.uint8)
        img[10:50, 10:50] = (200, 0, 200)
        ok, enc = cv2.imencode(".jpg", img)
        self.assertTrue(ok)
        raw_jpeg = enc.tobytes()
        # Pad with harmless trailing bytes inside an oversized total_size simulation (> 65000)
        padded = raw_jpeg[:-2] + (b"\x00" * 66000) + b"\xff\xd9"
        total_size = len(padded)
        self.assertGreater(total_size, 65000)

        mid = total_size // 2
        pkt0 = struct.pack("<IHH", total_size, 0, 2) + padded[:mid]
        pkt1 = struct.pack("<IHH", total_size, 1, 2) + padded[mid:]

        receiver = OBS_UDP_Receiver("127.0.0.1", 5000)
        is_frag0, out0 = receiver._try_reassemble_xudp_fragment(pkt0, 1.0)
        self.assertTrue(is_frag0)
        self.assertIsNone(out0)

        is_frag1, out1 = receiver._try_reassemble_xudp_fragment(pkt1, 1.0)
        self.assertTrue(is_frag1)
        self.assertEqual(out1, padded)

    def test_handle_button_mask_does_not_flood_unlock_when_disabled(self):
        tracker = main_mod.AimTracker.__new__(main_mod.AimTracker)
        tracker._current_masked_buttons = set()

        prev_enabled = getattr(config, "button_mask_enabled", False)
        try:
            config.button_mask_enabled = False
            with mock.patch("src.utils.mouse.unlock_all_locks") as unlock_mock:
                tracker._handle_button_mask()
                tracker._handle_button_mask()
                unlock_mock.assert_not_called()

                # When transitioning from masked -> disabled, unlock ONCE and clear tracked set
                tracker._current_masked_buttons = {4}
                tracker._handle_button_mask()
                unlock_mock.assert_called_once()
                self.assertEqual(tracker._current_masked_buttons, set())

                # Subsequent frames do not flood unlock_all_locks again
                tracker._handle_button_mask()
                unlock_mock.assert_called_once()
        finally:
            config.button_mask_enabled = prev_enabled

    def test_i18n_normalizes_vietnamese_aliases(self):
        for alias in ("vi", "vi-VN", "vi_VN", "vn", "Vietnamese", "Tiếng Việt"):
            self.assertEqual(i18n.normalize(alias), "vi")

    def test_run_bat_prefers_runtime_python(self):
        root = Path(__file__).resolve().parents[1]
        run_bat = (root / "run.bat").read_text(encoding="utf-8")
        self.assertIn(r"runtime\Scripts\python.exe", run_bat)


if __name__ == "__main__":
    unittest.main()
