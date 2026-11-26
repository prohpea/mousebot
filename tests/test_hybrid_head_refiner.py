import os
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import main as main_mod
from src.utils.config import config
from src.utils.hybrid_head_refiner import (
    HybridHeadRefiner,
    decode_yolo_detections,
    inspect_onnx_model,
)


class HybridHeadRefinerTests(unittest.TestCase):
    def setUp(self):
        self._saved = {
            "hybrid_ai_enabled": getattr(config, "hybrid_ai_enabled", False),
            "hybrid_ai_model_path": getattr(config, "hybrid_ai_model_path", "models/v11_192_Valorant_180.onnx"),
            "hybrid_ai_conf_threshold": getattr(config, "hybrid_ai_conf_threshold", 0.35),
            "hybrid_ai_sync_mode": getattr(config, "hybrid_ai_sync_mode", False),
            "offsetX": getattr(config, "offsetX", 0),
            "offsetY": getattr(config, "offsetY", 0),
        }
        config.offsetX = 0
        config.offsetY = 0

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(config, k, v)

    def test_inspect_onnx_model_validates_staged_models_and_missing_file(self):
        rep_missing = inspect_onnx_model("models/does_not_exist.onnx")
        self.assertFalse(rep_missing.compatible)
        self.assertEqual(rep_missing.verdict, "INCOMPATIBLE")

        v11_path = "models/v11_192_Valorant_180.onnx"
        rep_v11 = inspect_onnx_model(v11_path, run_benchmark=True)
        self.assertTrue(rep_v11.exists)
        self.assertTrue(rep_v11.compatible)
        self.assertEqual(rep_v11.input_hw, (192, 192))
        self.assertTrue(rep_v11.single_class_mode)
        self.assertGreater(rep_v11.latency_ms, 0.0)

        v8_path = "models/v8_128_valo_ihack_v2.onnx"
        rep_v8 = inspect_onnx_model(v8_path, run_benchmark=False)
        self.assertTrue(rep_v8.compatible)
        self.assertEqual(rep_v8.input_hw, (128, 128))
        self.assertEqual(rep_v8.head_class_ids, (1,))
        self.assertFalse(rep_v8.single_class_mode)

    def test_decode_yolo_detections_supports_v8_v5_and_end2end(self):
        # 1) YOLOv8/v11 transposed [1, 6, 336] for 128x128 (2 classes: player=0, head=1)
        out_v8 = np.zeros((1, 6, 336), dtype=np.float32)
        out_v8[0, :, 10] = [64.0, 48.0, 12.0, 14.0, 0.05, 0.82]
        dets_v8 = decode_yolo_detections(out_v8, 128, 128, conf_threshold=0.35)
        self.assertEqual(len(dets_v8), 1)
        self.assertEqual(dets_v8[0][5], 1)
        self.assertAlmostEqual(dets_v8[0][0], 64.0, places=2)
        self.assertAlmostEqual(dets_v8[0][1], 48.0, places=2)

        # 2) YOLOv5 [1, 100, 7] (obj_conf * cls_conf)
        out_v5 = np.zeros((1, 100, 7), dtype=np.float32)
        out_v5[0, 5, :] = [50.0, 40.0, 10.0, 12.0, 0.90, 0.10, 0.85]
        dets_v5 = decode_yolo_detections(out_v5, 192, 192, conf_threshold=0.35)
        self.assertEqual(len(dets_v5), 1)
        self.assertEqual(dets_v5[0][5], 1)

        # 3) End-to-end NMS [1, 10, 6] (x1, y1, x2, y2, score, cls_id)
        out_e2e = np.zeros((1, 10, 6), dtype=np.float32)
        out_e2e[0, 0, :] = [90.0, 70.0, 102.0, 84.0, 0.77, 0.0]
        dets_e2e = decode_yolo_detections(out_e2e, 192, 192, conf_threshold=0.35)
        self.assertEqual(len(dets_e2e), 1)
        self.assertAlmostEqual(dets_e2e[0][0], 96.0, places=2)
        self.assertAlmostEqual(dets_e2e[0][1], 77.0, places=2)

    def test_tracker_hybrid_refiner_locks_true_head_and_tracks_relative_anchor(self):
        tracker = main_mod.AimTracker.__new__(main_mod.AimTracker)
        refiner = HybridHeadRefiner(start_worker=False)
        tracker.hybrid_head_refiner = refiner

        img = np.zeros((320, 320, 3), dtype=np.uint8)
        mask = np.zeros((320, 320), dtype=np.uint8)
        # Headless torso bbox at x=144..180, y=155..193; true head sits above y1 at (164, 150)
        mask[155:193, 144:158] = 255
        mask[155:193, 174:180] = 255

        config.hybrid_ai_enabled = True
        config.hybrid_ai_sync_mode = True
        config.hybrid_ai_model_path = "models/v11_192_Valorant_180.onnx"

        # Blank synthetic frame -> 0 AI detections -> must safely stay inside [y1, y2] without aiming into empty space
        heads_fallback = tracker._estimate_head_positions(144, 155, 180, 193, img, mask=mask)
        self.assertEqual(len(heads_fallback), 1)
        self.assertGreaterEqual(heads_fallback[0][1], 156)

        # Simulated AI head detection at crop local coords matching full-frame (164.0, 149.0):
        # crop_cx = 162, crop_cy = round(155 + min(18, 0.25*38)) = 164 -> ox0 = 162-96=66, oy0 = 164-96=68
        # So full (164, 149) corresponds to local (98.0, 81.0)
        fake_raw = np.zeros((1, 5, 756), dtype=np.float32)
        fake_raw[0, :, 0] = [98.0, 81.0, 11.0, 14.0, 0.78]
        refiner.ensure_model_loaded("models/v11_192_Valorant_180.onnx")
        with patch.object(refiner._runner, "infer", return_value=fake_raw):
            heads_ai = tracker._estimate_head_positions(144, 155, 180, 193, img, mask=mask)
            self.assertEqual(heads_ai[0][0], 164)
            self.assertEqual(heads_ai[0][1], 149)

            # Switch to async 144Hz mode and shift enemy +6px right (150..186):
            # Smooth ramp blends toward (170, 149) without abrupt step jump, reaching full lock after 3 hits.
            config.hybrid_ai_sync_mode = False
            for _ in range(2):
                refiner._run_crop_inference(img, (150, 155, 186, 193), 0.28)
            hx_async, hy_async, used = refiner.refine_head(
                150, 155, 186, 193, img, 168.0, 160.0, model_path="models/v11_192_Valorant_180.onnx", sync=False
            )
            self.assertTrue(used)
            self.assertAlmostEqual(hx_async, 170.0, places=1)
            self.assertAlmostEqual(hy_async, 149.0, places=1)

    def test_far_43m_foveated_detection_recovers_jpeg_diluted_enemy_and_rejects_dim_wall(self):
        from src.utils import detection

        model = detection.XUDP_HSV_PRESETS["purple"][0]
        # 1) Dimmed flat purple wall (S=58, V=120) must produce 0 detections
        wall = np.zeros((320, 320, 3), dtype=np.uint8)
        wall_hsv = np.full((320, 320, 3), (140, 58, 120), dtype=np.uint8)
        wall = np.ascontiguousarray(cv2.cvtColor(wall_hsv, cv2.COLOR_HSV2BGR))
        dets_wall, _ = detection.perform_detection(model, wall, stabilize=False)
        self.assertEqual(dets_wall, [])

        # 2) Simulated 43m distant enemy near crosshair whose 1px purple outline dropped to S=75..92, H=162
        far_hsv = np.full((320, 320, 3), (20, 30, 150), dtype=np.uint8)
        far_hsv[152:165, 156:158] = (162, 86, 165)  # left diluted outline (below S=95 & H>160!)
        far_hsv[152:165, 163:165] = (158, 78, 155)  # right diluted outline
        far_bgr = np.ascontiguousarray(cv2.cvtColor(far_hsv, cv2.COLOR_HSV2BGR))
        dets_far, _ = detection.perform_detection(model, far_bgr, stabilize=False)
        self.assertEqual(len(dets_far), 1)
        bx, by, bw, bh = dets_far[0]["bbox"]
        self.assertGreaterEqual(bw, 6)
        self.assertLessEqual(bw, 20)
        self.assertGreaterEqual(bh, 8)
        self.assertLessEqual(bh, 24)

        # 3) AT-06: Textured wall with JPEG compression noise (S=50..76) + peripheral 6x6 speck vs min_bbox_area=120
        rng = np.random.default_rng(42)
        tex_hsv = np.zeros((320, 320, 3), dtype=np.uint8)
        tex_hsv[:, :, 0] = rng.integers(122, 164, size=(320, 320), dtype=np.uint8)
        tex_hsv[:, :, 1] = rng.integers(35, 71, size=(320, 320), dtype=np.uint8)
        tex_hsv[:, :, 2] = rng.integers(95, 165, size=(320, 320), dtype=np.uint8)
        tex_bgr = cv2.cvtColor(tex_hsv, cv2.COLOR_HSV2BGR)
        ok, enc = cv2.imencode(".jpg", tex_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        self.assertTrue(ok)
        jpg_wall = cv2.imdecode(enc, cv2.IMREAD_COLOR)
        dets_jpg_wall, _ = detection.perform_detection(model, jpg_wall, stabilize=False)
        self.assertEqual(dets_jpg_wall, [], "JPEG-compressed low-saturation purple wall must produce 0 ghost locks")

        # Peripheral 6x6 (36px^2) blob at x=40,y=40 must be rejected when detection_min_bbox_area=120
        periph = np.zeros((320, 320, 3), dtype=np.uint8)
        periph[40:44, 40:44] = (220, 20, 220)
        dets_periph, _ = detection.perform_detection(model, periph, stabilize=False)
        self.assertEqual(dets_periph, [])

    def test_abcurves_lagged_plant_converges_without_overshoot_at_both_gentle_and_aggressive_speeds(self):
        import queue
        from collections import deque
        from src.aim_system import abcurves_controller as abc

        class _SimTracker:
            def __init__(self):
                self.in_game_sens = 0.23
                self.mouse_dpi = 1100
                self.fovsize = 25
                self.fovsize_sec = 150
                self.aim_offsetX = 0.0
                self.aim_offsetY = 0.0
                self.move_queue = queue.Queue(maxsize=50)
                self._move_flush_lock = main_mod.threading.Lock()
                self._pending_exact_item = None
                self.lag_estimator = None

            def _clip_movement(self, dx, dy):
                return dx, dy

        saved = {
            k: getattr(config, k)
            for k in (
                "in_game_sens",
                "mouse_dpi",
                "abcurves_commitment_ms",
                "abcurves_x_speed",
                "abcurves_y_speed",
                "abcurves_max_step",
                "deadzone_fovsize",
                "velocity_lead_enabled",
            )
        }
        try:
            # Fixed physical game plant scale (speed=1.0 -> ~1.5494 counts/px, NEVER scaled by x_speed!)
            config.in_game_sens = 0.23
            config.mouse_dpi = 1100
            plant_kx, plant_ky = abc._compute_counts_per_px(0.23, 1100, 1.0, 1.0)
            for commit_ms, xs, ys, lead_on in ((16, 1.20, 1.05, False), (8, 2.10, 1.75, True), (32, 1.15, 1.00, False)):
                config.abcurves_commitment_ms = commit_ms
                config.abcurves_x_speed = xs
                config.abcurves_y_speed = ys
                config.abcurves_max_step = 50.0
                config.deadzone_fovsize = 3.0
                config.velocity_lead_enabled = lead_on

                trk = _SimTracker()
                true_tx, true_ty = 18.0, -12.0
                cur_x, cur_y = 0.0, 0.0
                # Timestamped 28ms camera observation delay (immune to Windows 15.6ms sleep granularity)
                t_start = time.perf_counter()
                obs_hist = deque([(t_start - 0.10, 0.0, 0.0)])
                peak_overshoot_x = 0.0
                sign_flips_x = 0
                prev_err_sign = 1

                winmm = main_mod.ctypes.windll.winmm if hasattr(main_mod, "ctypes") and hasattr(main_mod.ctypes, "windll") else None
                if winmm is not None:
                    winmm.timeBeginPeriod(1)
                try:
                    for _ in range(42):
                        now_t = time.perf_counter()
                        obs_x, obs_y = 0.0, 0.0
                        for ts_h, hx_h, hy_h in obs_hist:
                            if ts_h <= now_t - 0.028:
                                obs_x, obs_y = hx_h, hy_h
                            else:
                                break
                        dx = true_tx - obs_x
                        dy = true_ty - obs_y
                        dist = (dx * dx + dy * dy) ** 0.5
                        if dist <= 3.0:
                            abc.hold_abcurves_state(trk, is_sec=False)
                        else:
                            abc.apply_abcurves_aim(dx, dy, dist, trk, is_sec=False)

                        mx_tot, my_tot = 0, 0
                        while not trk.move_queue.empty():
                            mx, my, _, _ = trk.move_queue.get_nowait()
                            mx_tot += mx
                            my_tot += my
                        cur_x += mx_tot / plant_kx
                        cur_y += my_tot / plant_ky
                        obs_hist.append((time.perf_counter(), cur_x, cur_y))

                        real_err_x = true_tx - cur_x
                        if real_err_x < 0.0:
                            peak_overshoot_x = max(peak_overshoot_x, -real_err_x)
                        cur_sign = 1 if real_err_x >= -0.5 else -1
                        if cur_sign != prev_err_sign:
                            sign_flips_x += 1
                            prev_err_sign = cur_sign
                        time.sleep(0.0065)
                finally:
                    if winmm is not None:
                        winmm.timeEndPeriod(1)

                final_err = ((true_tx - cur_x) ** 2 + (true_ty - cur_y) ** 2) ** 0.5
                self.assertLessEqual(
                    peak_overshoot_x,
                    2.5,
                    f"ABCurves {commit_ms}ms (x_speed={xs}) overshot by {peak_overshoot_x:.2f}px!",
                )
                self.assertLessEqual(sign_flips_x, 1, f"ABCurves {commit_ms}ms ping-ponged ({sign_flips_x} flips)")
                self.assertLessEqual(final_err, 3.5, f"ABCurves {commit_ms}ms stalled at {final_err:.2f}px")
        finally:
            for k, v in saved.items():
                setattr(config, k, v)

    def test_single_class_body_vs_head_and_subpixel_float_continuity(self):
        tracker = main_mod.AimTracker.__new__(main_mod.AimTracker)
        refiner = HybridHeadRefiner(start_worker=False)
        tracker.hybrid_head_refiner = refiner
        refiner.ensure_model_loaded("models/v11_192_Valorant_180.onnx")
        rep = refiner.report
        self.assertIsNotNone(rep)
        self.assertTrue(rep.single_class_mode)

        # AT-05: Full-body (22x42) and crouched (26x36) single-class boxes MUST map to top 10% head, NEVER 50% stomach!
        for bw, bh in ((22, 42), (26, 36), (14, 28)):
            x1, y1 = 150, 140
            x2, y2 = x1 + bw, y1 + bh
            # Detection covering full bbox centered at (x1+bw/2, y1+bh/2) in crop coords (ox0=60, oy0=60)
            dets = [(float(x1 - 60) + bw * 0.5, float(y1 - 60) + bh * 0.5, float(bw), float(bh), 0.72, 0)]
            matched = refiner._select_best_head_for_bbox(dets, 60, 60, (x1, y1, x2, y2), rep)
            self.assertIsNotNone(matched)
            _, hy, _ = matched
            self.assertLessEqual(hy, y1 + 0.22 * bh, f"Body box {bw}x{bh} aimed too low at hy={hy:.1f} (stomach!)")
            self.assertGreaterEqual(hy, y1 - 0.15 * bh)

        # H-1: _estimate_head_positions preserves sub-pixel float coordinates without int(round) staircasing
        img = np.zeros((320, 320, 3), dtype=np.uint8)
        config.hybrid_ai_enabled = False
        heads = tracker._estimate_head_positions(145, 140, 176, 183, img, mask=None)
        self.assertIsInstance(heads[0][0], float)
        self.assertIsInstance(heads[0][1], float)

    def test_sent_history_rewind_monotonic_and_toggle_breakaway_flushes_queue(self):
        import queue
        from src.aim_system import abcurves_controller as abc
        from src.aim_system import normal as normal_mod

        class _MockTracker:
            def __init__(self):
                self.in_game_sens = 0.23
                self.mouse_dpi = 1100
                self.fovsize = 25
                self.fovsize_sec = 150
                self.aim_offsetX = 0.0
                self.aim_offsetY = 0.0
                self.aim_offsetX_sec = 0.0
                self.aim_offsetY_sec = 0.0
                self.move_queue = queue.Queue(maxsize=50)
                self._move_flush_lock = main_mod.threading.Lock()
                self._pending_exact_item = (5, 0, 0.001, True)
                self.lag_estimator = None

            def _clip_movement(self, dx, dy):
                return dx, dy

        trk = _MockTracker()
        trk.move_queue.put_nowait((10, 0, 0.001, True))
        trk.move_queue.put_nowait((9, 0, 0.001, True))
        st = abc._get_or_create_state(trk, False, 942, "numba", commitment_ms=16)
        st["active"] = True
        st["cum_sent_x"] = 30
        st["cum_sent_y"] = 0
        st["sent_history"].clear()
        t0 = time.perf_counter()
        st["sent_history"].extend([(t0 - 0.020, 10, 0), (t0 - 0.010, 20, 0), (t0, 30, 0)])

        # C-3: Rewinding 24 unexecuted counts (5 pending + 19 queued) leaves cum_sent_x = 6;
        # historical entries must be clamped <= 6 so inflight never becomes negative (-14)!
        flushed_x, _ = abc._flush_and_rewind(trk, st["pipe"], st)
        self.assertEqual(flushed_x, 24)
        self.assertEqual(st["cum_sent_x"], 6)
        cap_x, _ = abc._lookup_captured_counts(st["sent_history"], t0 - 0.012)
        self.assertGreaterEqual(st["cum_sent_x"] - cap_x, 0.0)

        # M-2: 200ms firing deadzone boost survives 1-frame recoil excursion outside boosted radius
        saved_dz_en = getattr(config, "deadzone_fov_enabled", True)
        saved_dz = getattr(config, "deadzone_fovsize", 3.5)
        saved_fb = getattr(config, "firing_deadzone_boost_enabled", True)
        try:
            config.deadzone_fov_enabled = True
            config.deadzone_fovsize = 3.0
            config.firing_deadzone_boost_enabled = True
            with patch.object(normal_mod, "is_button_pressed", return_value=True):
                self.assertTrue(normal_mod._should_pause_in_stop_fov(trk, 4.2, 0.0, is_sec=False))
            with patch.object(normal_mod, "is_button_pressed", return_value=False):
                # 1-frame recoil excursion to 6.2px (> 5.5px) must NOT wipe the remaining 200ms boost!
                self.assertFalse(normal_mod._should_pause_in_stop_fov(trk, 6.2, 0.0, is_sec=False))
                self.assertTrue(normal_mod._is_inside_stop_fov(4.5, 0.0, is_sec=False, tracker=trk))

            # H-4 & H-5: Sustained LMB spray (>160ms) yields upward Y pull, and intentional toggle breakaway
            # pauses tracking + clears _toggle_breakaway_until cleanly on target loss / reset.
            dispatched = []
            dummy_img = np.zeros((200, 200, 3), dtype=np.uint8)
            dummy_frame = type("DummyFrame", (), {"xres": 200, "yres": 200})()
            saved_vals = {
                k: getattr(config, k, None)
                for k in (
                    "enableaim",
                    "selected_mouse_button",
                    "fovsize",
                    "aimbot_activation_type",
                    "enableaim_sec",
                    "deadzone_fov_enabled",
                    "aim_offsetX",
                    "aim_offsetY",
                )
            }
            try:
                config.enableaim = True
                config.selected_mouse_button = 4
                config.fovsize = 25.0
                config.aimbot_activation_type = "toggle"
                config.enableaim_sec = False
                config.deadzone_fov_enabled = False
                config.aim_offsetX = 0.0
                config.aim_offsetY = 0.0
                trk._lmb_down_since = time.perf_counter() - 0.25
                with patch.object(normal_mod, "check_aimbot_activation", return_value=True), patch.object(
                    normal_mod, "is_button_pressed", return_value=True
                ), patch.object(
                    normal_mod, "_dispatch_aimbot", side_effect=lambda dx, dy, dist, mode, t, is_sec=False: dispatched.append((dx, dy))
                ):
                    # Target at (108, 92) relative to center (100, 100) -> dx=+8, dy=-8; sustained spray must yield dy to 0.0!
                    normal_mod.process_normal_mode([(108.0, 92.0, 11.31, 90.0, 120.0)], dummy_frame, dummy_img, trk)
                self.assertEqual(len(dispatched), 1)
                self.assertAlmostEqual(dispatched[0][0], 8.0, places=3)
                self.assertEqual(dispatched[0][1], 0.0)

                # Intentional manual hand pull away (+12px jump on X against center) triggers breakaway pause
                dispatched.clear()
                with patch.object(normal_mod, "check_aimbot_activation", return_value=True), patch.object(
                    normal_mod, "is_button_pressed", return_value=False
                ), patch.object(
                    normal_mod, "_dispatch_aimbot", side_effect=lambda dx, dy, dist, mode, t, is_sec=False: dispatched.append((dx, dy))
                ):
                    normal_mod.process_normal_mode([(120.0, 100.0, 20.0, 90.0, 120.0)], dummy_frame, dummy_img, trk)
                    self.assertEqual(len(dispatched), 0)
                    self.assertGreater(getattr(trk, "_toggle_breakaway_until", 0.0), time.perf_counter() - 0.01)
                    # Exiting FOV resets _toggle_breakaway_until back to 0.0 immediately
                    trk._last_main_aim_dist = 30.0
                    normal_mod.process_normal_mode([], dummy_frame, dummy_img, trk)
                    self.assertEqual(getattr(trk, "_toggle_breakaway_until", -1.0), 0.0)
            finally:
                for k, v in saved_vals.items():
                    setattr(config, k, v)
        finally:
            config.deadzone_fov_enabled = saved_dz_en
            config.deadzone_fovsize = saved_dz
            config.firing_deadzone_boost_enabled = saved_fb


if __name__ == "__main__":
    unittest.main()
