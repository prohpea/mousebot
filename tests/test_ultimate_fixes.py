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

    def test_obs_udp_size1_slot_and_single_packet_fast_path(self):
        img = np.zeros((320, 320, 3), dtype=np.uint8)
        img[100:200, 100:200] = (200, 20, 200)
        ok, enc = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        self.assertTrue(ok)
        raw_jpeg = enc.tobytes()

        receiver = OBS_UDP_Receiver("127.0.0.1", 5000)
        # Send two single-packet frames without consumer running -> size-1 slot overwrites oldest
        receiver._process_mjpeg_data(raw_jpeg, 1.0)
        receiver._process_mjpeg_data(raw_jpeg, 1.01)

        stats = receiver.get_performance_stats()
        self.assertEqual(stats["buffer_size_bytes"], 0)  # bypassed mjpeg_buffer completely
        self.assertEqual(stats["queue_size"], 1)
        self.assertEqual(stats["queue_drops"], 1)
        self.assertIn("TurboJPEG", stats["decoder_backend"])

    def test_obs_udp_fragment_size_validation_and_single_packet_clears_pending(self):
        receiver = OBS_UDP_Receiver("127.0.0.1", 5000)
        # Mis-sized fragment pair (claims total_size=70000, delivers only 20 bytes)
        bad0 = struct.pack("<IHH", 70000, 0, 2) + b"\xff\xd8" + b"A" * 8
        bad1 = struct.pack("<IHH", 70000, 1, 2) + b"B" * 10
        is_f0, out0 = receiver._try_reassemble_xudp_fragment(bad0, 1.0)
        is_f1, out1 = receiver._try_reassemble_xudp_fragment(bad1, 1.0)
        self.assertTrue(is_f0 and is_f1)
        self.assertIsNone(out0)
        self.assertIsNone(out1)
        self.assertEqual(receiver.reassembly_drops, 1)

        # Pending incomplete fragment must be dropped when a fresh single-packet frame arrives
        receiver._try_reassemble_xudp_fragment(bad0, 1.0)
        self.assertEqual(len(receiver._frag_chunks), 1)
        img = np.zeros((32, 32, 3), dtype=np.uint8)
        _, enc = cv2.imencode(".jpg", img)
        receiver._process_mjpeg_data(enc.tobytes(), 1.0)
        self.assertEqual(len(receiver._frag_chunks), 0)
        self.assertEqual(receiver.reassembly_drops, 2)

    def test_obs_udp_fast_disconnect_and_frame_seq_sync(self):
        import socket
        import time

        # Pick an ephemeral localhost UDP port
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        receiver = OBS_UDP_Receiver("127.0.0.1", port, target_fps=144)
        self.assertTrue(receiver.connect())
        try:
            img = np.zeros((320, 320, 3), dtype=np.uint8)
            img[120:180, 120:180] = (230, 10, 230)
            _, enc = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            payload = enc.tobytes()

            sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sender.sendto(payload, ("127.0.0.1", port))
                frame, seq = receiver.wait_for_new_frame(0, timeout=0.5)
                self.assertIsNotNone(frame)
                self.assertEqual(frame.shape, (320, 320, 3))
                self.assertGreaterEqual(seq, 1)

                # Dedup: waiting with current seq times out cleanly when no new packet sent
                dup_frame, seq2 = receiver.wait_for_new_frame(seq, timeout=0.02)
                self.assertIsNone(dup_frame)
                self.assertEqual(seq2, seq)
            finally:
                sender.close()
        finally:
            t0 = time.perf_counter()
            receiver.disconnect()
            dt = time.perf_counter() - t0
            self.assertLess(dt, 0.5, f"UDP disconnect hung for {dt:.3f}s")

    def test_bbox_stabilizer_tracks_micro_strafe_and_retains_far_head_peek(self):
        from src.utils import detection

        detection._PREV_STABLE_RECTS = []
        detection._PREV_STABLE_TS = 0.0

        # Frame 1 -> Frame 2 shifts by 4px on one edge: must track immediately instead of freezing
        r1 = detection._stabilize_detected_rects([(140, 160, 24, 36)])
        r2 = detection._stabilize_detected_rects([(140, 156, 24, 40)])
        self.assertEqual(r1, [(140, 160, 24, 36)])
        self.assertEqual(r2, [(140, 156, 24, 40)])

        # Distant / head-glitch target (w/h = 1.8, raw_px = 12) must not be dropped
        raw_mask = np.zeros((100, 100), dtype=np.uint8)
        raw_mask[20:23, 30:34] = 255  # 12 raw pixels inside an 18x10 head-peek box
        kept = detection._filter_false_positive_rects([(25, 18, 18, 10)], raw_mask)
        self.assertEqual(kept, [(25, 18, 18, 10)])

    def test_roi_offset_keeps_stabilizer_and_head_mask_aligned(self):
        from src.utils import detection

        tracker = main_mod.AimTracker.__new__(main_mod.AimTracker)
        img = np.zeros((320, 320, 3), dtype=np.uint8)
        # Target at full-frame x=150..170, y=130..180; head pixels at x=165 (right side of bbox)
        roi_mask = np.zeros((192, 192), dtype=np.uint8)
        roi_offset = (64, 64)
        # In ROI-local coords: x=86..106, y=66..116 -> bright cluster at x=101 (full-frame 165)
        roi_mask[68:82, 99:104] = 255  # 14*5 = 70 pixels (>= head_refine_min_pixels)

        heads = tracker._estimate_head_positions(150, 130, 170, 180, img, mask=roi_mask, roi_offset=roi_offset)
        self.assertEqual(len(heads), 1)
        self.assertGreaterEqual(heads[0][0], 164)
        self.assertLessEqual(heads[0][0], 166)

        # ADS ROI toggle shift must not jump stabilized full-frame coords
        detection._PREV_STABLE_RECTS = []
        detection._PREV_STABLE_TS = 0.0
        img_target = np.zeros((320, 320, 3), dtype=np.uint8)
        img_target[130:180, 148:172] = (230, 20, 230)
        img_target[138:172, 154:166] = (20, 20, 20)
        model = detection.XUDP_HSV_PRESETS["purple"][0]
        r_hip, _ = detection.perform_detection(model, img_target[64:256, 64:256], roi_offset=(64, 64))
        r_ads, _ = detection.perform_detection(model, img_target[84:236, 84:236], roi_offset=(84, 84))
        self.assertEqual(len(r_hip), 1)
        self.assertEqual(len(r_ads), 1)
        self.assertEqual(r_hip[0]["bbox"], r_ads[0]["bbox"])

    def test_config_from_dict_blocks_callables_and_clamps_hsv(self):
        from src.utils.config import Config

        cfg = Config()
        cfg.from_dict({
            "save_to_file": "corrupted",
            "_private": "bad",
            "custom_hsv_min_h": -10,
            "custom_hsv_max_h": 250,
            "custom_hsv_min_s": 999,
        })
        self.assertTrue(callable(cfg.save_to_file))
        self.assertFalse(hasattr(cfg, "_private"))
        self.assertEqual(cfg.custom_hsv_min_h, 0)
        self.assertEqual(cfg.custom_hsv_max_h, 179)
        self.assertEqual(cfg.custom_hsv_min_s, 255)

    def test_head_estimator_handles_shoulder_top_sideways_and_head_peek(self):
        tracker = main_mod.AimTracker.__new__(main_mod.AimTracker)
        img = np.zeros((320, 320, 3), dtype=np.uint8)

        # 1) Torso/upper-body box (36x38) with heavier left-shoulder outline:
        #    Geometric baseline MUST stay inside [y1, y2] (never lift into empty space above y1=140)
        #    and keep X symmetric near center (158) rather than pulling onto thick left shoulder.
        mask_torso = np.zeros((320, 320), dtype=np.uint8)
        mask_torso[140:178, 140:154] = 255
        mask_torso[140:178, 172:176] = 255
        heads_torso = tracker._estimate_head_positions(140, 140, 176, 178, img, mask=mask_torso)
        self.assertEqual(len(heads_torso), 1)
        hx_t, hy_t, _ = heads_torso[0]
        self.assertGreaterEqual(hy_t, 141, "Geometric baseline must never aim above y1 into empty space")
        self.assertLessEqual(hy_t, 146)
        self.assertGreaterEqual(hx_t, 156)
        self.assertLessEqual(hx_t, 160)

        # 2) Full-standing sideways enemy WITH head crown (h=90, w=36; head at x=150..160, torso+gun x=144..180):
        #    Must lock X onto narrow top-12% head crown (~155) and Y onto head (~109), not chest or empty air.
        mask_side = np.zeros((320, 320), dtype=np.uint8)
        mask_side[100:113, 150:160] = 255
        mask_side[113:190, 144:180] = 255
        heads_side = tracker._estimate_head_positions(144, 100, 180, 190, img, mask=mask_side)
        self.assertEqual(len(heads_side), 1)
        hx_s, hy_s, _ = heads_side[0]
        self.assertGreaterEqual(hx_s, 153)
        self.assertLessEqual(hx_s, 157)
        self.assertGreaterEqual(hy_s, 106)
        self.assertLessEqual(hy_s, 112)

        # 3) Head-only peek behind cover (16x18): must stay inside head box.
        mask_peek = np.zeros((320, 320), dtype=np.uint8)
        mask_peek[120:138, 152:168] = 255
        heads_peek = tracker._estimate_head_positions(152, 120, 168, 138, img, mask=mask_peek)
        self.assertEqual(len(heads_peek), 1)
        hx_p, hy_p, _ = heads_peek[0]
        self.assertGreaterEqual(hy_p, 124)
        self.assertLessEqual(hy_p, 130)
        self.assertGreaterEqual(hx_p, 158)
        self.assertLessEqual(hx_p, 162)


if __name__ == "__main__":
    unittest.main()
