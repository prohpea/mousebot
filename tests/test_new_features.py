"""Unit tests for the 4 CVM-Ultimate Architecture & Feature Upgrades."""

import unittest

import numpy as np

from src.utils.config import Config
from src.utils.hsv_calibrator import compute_lighting_v_floor, solve_contrast_hsv
from src.utils.pipeline_profiler import CaptureLagEstimator, PipelineProfiler, run_preflight_check
from src.utils.profile_manager import compute_profile_diff, normalize_pinned_profiles


class TestArchitectureUpgrades(unittest.TestCase):
    def test_pipeline_profiler_computes_percentiles_and_bottleneck(self):
        prof = PipelineProfiler(window=20)
        for _ in range(10):
            prof.record(grab_ms=0.8, detect_ms=2.1, aim_ms=0.4, total_ms=3.3, queue_depth=1)
        st = prof.get_stats()
        self.assertAlmostEqual(st.grab_p95_ms, 0.8, places=1)
        self.assertAlmostEqual(st.detect_p95_ms, 2.1, places=1)
        self.assertEqual(st.bottleneck, "OK")
        self.assertLess(st.budget_pct, 100.0)

        # Exceeding 6.94ms budget flags the slowest stage
        for _ in range(20):
            prof.record(grab_ms=1.0, detect_ms=6.5, aim_ms=0.5, total_ms=8.0, queue_depth=0)
        st2 = prof.get_stats()
        self.assertEqual(st2.bottleneck, "DETECT")
        self.assertGreater(st2.budget_pct, 100.0)

    def test_capture_lag_estimator_clamps_and_smooths(self):
        est = CaptureLagEstimator(base_transport_s=0.014, alpha=0.5)
        lag1 = est.update(decode_ms=2.0, grab_ms=1.0, detect_ms=1.0)
        self.assertGreaterEqual(lag1, CaptureLagEstimator.MIN_LAG_S)
        self.assertLessEqual(lag1, CaptureLagEstimator.MAX_LAG_S)
        # Extreme outlier still clamped safely
        for _ in range(10):
            lag_hi = est.update(decode_ms=500.0, grab_ms=0.0, detect_ms=0.0)
        self.assertAlmostEqual(lag_hi, CaptureLagEstimator.MAX_LAG_S, places=3)

    def test_preflight_check_reports_status(self):
        class DummyCap:
            def is_connected(self):
                return True

        class DummyTracker:
            class controller:
                connected = True

        res = run_preflight_check(DummyTracker(), DummyCap())
        self.assertTrue(res["ready"])
        self.assertTrue(res["capture_ok"])
        self.assertTrue(res["hardware_ok"])

    def test_solve_contrast_hsv_separates_target_from_background(self):
        target_samples = [(140, 180, 190), (144, 195, 210), (138, 170, 185)]
        bg_samples = [(142, 60, 70), (141, 75, 80)]
        h_lo, h_hi, s_lo, s_hi, v_lo, v_hi = solve_contrast_hsv(target_samples, bg_samples)
        self.assertLessEqual(h_lo, 138)
        self.assertGreaterEqual(h_hi, 144)
        self.assertGreater(s_lo, 75)
        self.assertGreater(v_lo, 80)

    def test_compute_lighting_v_floor_adapts_within_bounds(self):
        dark_img = np.full((64, 64, 3), 20, dtype=np.uint8)
        bright_img = np.full((64, 64, 3), 230, dtype=np.uint8)
        v_dark = compute_lighting_v_floor(dark_img, base_v_min=90)
        v_bright = compute_lighting_v_floor(bright_img, base_v_min=90)
        self.assertLess(v_dark, 90)
        self.assertGreater(v_bright, 90)

    def test_profile_diff_and_pinned_profiles(self):
        cfg = Config()
        diff = compute_profile_diff(
            cfg,
            {"fovsize": 75, "capture_mode": "NDI", "custom_hsv_min_s": 150},
            aim_keys={"fovsize", "abcurves_x_speed"},
        )
        self.assertEqual(len(diff.aim_changes), 1)
        self.assertEqual(diff.aim_changes[0][0], "fovsize")
        self.assertTrue(any(k == "capture_mode" for k, _, _ in diff.system_changes))

        pinned = normalize_pinned_profiles(
            ["rank_balanced", "missing_cfg", "rank_balanced", "2aim"],
            ["rank_balanced", "2aim", "default"],
            max_slots=6,
        )
        self.assertEqual(pinned, ["rank_balanced", "2aim"])

    def test_ui_path_replay_slot_and_profile_cycle_methods_exist(self):
        from src.ui import ViewerApp
        self.assertTrue(hasattr(ViewerApp, "_poll_profile_cycle_hotkey"))
        self.assertTrue(hasattr(ViewerApp, "_cycle_pinned_profile"))
        self.assertTrue(hasattr(ViewerApp, "_show_status_toast"))
        self.assertTrue(hasattr(ViewerApp, "_on_mouse_path_slot_selected"))


if __name__ == "__main__":
    unittest.main()
