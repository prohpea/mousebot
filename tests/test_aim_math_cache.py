"""Cache + source-aware calibration tests (plan 7.3 / 10.3 / C5).

``resolve_calibration`` used to ignore the source entirely and only read
``counts_per_deg_x/y`` when they were > 0, so a Valorant preset did not follow
the sensitivity: 0.23 -> 0.40 kept 62.11 c/deg, i.e. 42 % too much travel.
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aim_system.aim_math import (  # noqa: E402
    Calibration,
    SOURCE_ANALYTIC,
    SOURCE_MEASURED,
    SOURCE_VALORANT,
    cache_sizes,
    clear_caches,
    resolve_calibration,
    resolve_calibration_cached,
    resolve_geometry,
)


def base_cfg(**overrides):
    payload = {
        "in_game_sens": 0.23,
        "mouse_dpi": 1100,
        "cm_per_rev": 54.54,
        "hfov_deg": 103.0,
        "vfov_deg": 0.0,
        "valorant_deg_per_count": 0.07,
        "counts_per_deg_x": 0.0,
        "counts_per_deg_y": 0.0,
        "calibration_r2": 0.0,
        "calibration_samples": 0,
        "calibration_sens_at_measurement": 0.0,
        "calibration_source": "valorant",
    }
    payload.update(overrides)
    return payload


class TestValorantSource(unittest.TestCase):
    def test_declared_value_at_0_23(self):
        calibration = resolve_calibration(cfg=base_cfg())
        self.assertEqual(calibration.source, SOURCE_VALORANT)
        self.assertAlmostEqual(calibration.counts_per_deg_x, 62.1118, places=3)
        self.assertAlmostEqual(calibration.counts_per_deg_y, 62.1118, places=3)

    def test_follows_sensitivity_live(self):
        """0.23 -> 0.40 must change the scale without a restart."""
        low = resolve_calibration(cfg=base_cfg(in_game_sens=0.23))
        high = resolve_calibration(cfg=base_cfg(in_game_sens=0.40))
        self.assertAlmostEqual(low.counts_per_deg_x, 62.1118, places=3)
        self.assertAlmostEqual(high.counts_per_deg_x, 35.7143, places=3)
        self.assertLess(high.counts_per_deg_x, low.counts_per_deg_x)

    def test_documented_table(self):
        table = {
            0.10: 142.857,
            0.23: 62.112,
            0.235: 60.790,
            0.40: 35.714,
        }
        for sens, expected in table.items():
            with self.subTest(sens=sens):
                calibration = resolve_calibration(cfg=base_cfg(in_game_sens=sens))
                self.assertAlmostEqual(calibration.counts_per_deg_x, expected, delta=0.01)

    def test_cm_per_360_cross_check(self):
        calibration = resolve_calibration(cfg=base_cfg(in_game_sens=0.23))
        # 360 / (0.07*0.23) / (1100/2.54) = 51.63 cm
        self.assertAlmostEqual(calibration.cm_per_360(), 51.63, delta=0.02)

    def test_counts_for_30px(self):
        geometry = resolve_geometry(frame_w=1920, frame_h=1080, cfg=base_cfg())
        calibration = resolve_calibration(cfg=base_cfg())
        deg_per_px = geometry.deg_per_px_at_center()[0]
        counts = 30.0 * deg_per_px * calibration.counts_per_deg_x
        self.assertAlmostEqual(counts, 139.8, delta=0.5)

    def test_legacy_gap_is_4_594x(self):
        calibration = resolve_calibration(cfg=base_cfg())
        legacy = calibration.analytic_counts_per_deg()
        self.assertAlmostEqual(legacy / calibration.counts_per_deg_x, 4.593, places=2)

    def test_out_of_range_sens_warns(self):
        calibration = Calibration(source=SOURCE_VALORANT, sens=0.01)
        self.assertTrue(calibration.needs_recalibration_warning())


class TestMeasuredSource(unittest.TestCase):
    def test_measured_pair_is_used(self):
        cfg = base_cfg(
            calibration_source="measured",
            counts_per_deg_x=140.0,
            counts_per_deg_y=141.0,
            calibration_r2=0.995,
            calibration_samples=10,
        )
        calibration = resolve_calibration(cfg=cfg)
        self.assertEqual(calibration.source, SOURCE_MEASURED)
        self.assertAlmostEqual(calibration.counts_per_deg_x, 140.0)
        self.assertAlmostEqual(calibration.counts_per_deg_y, 141.0)
        self.assertTrue(calibration.is_measured)

    def test_measured_does_not_follow_sens(self):
        cfg = base_cfg(
            calibration_source="measured",
            counts_per_deg_x=140.0,
            counts_per_deg_y=140.0,
            calibration_samples=10,
            in_game_sens=0.40,
        )
        calibration = resolve_calibration(cfg=cfg)
        self.assertAlmostEqual(calibration.counts_per_deg_x, 140.0)

    def test_measured_without_pair_falls_back(self):
        cfg = base_cfg(calibration_source="measured")
        calibration = resolve_calibration(cfg=cfg)
        self.assertEqual(calibration.source, SOURCE_ANALYTIC)

    def test_sens_drift_warns(self):
        cfg = base_cfg(
            calibration_source="measured",
            counts_per_deg_x=140.0,
            counts_per_deg_y=140.0,
            calibration_samples=10,
            calibration_sens_at_measurement=0.23,
            in_game_sens=0.30,
        )
        calibration = resolve_calibration(cfg=cfg)
        self.assertGreater(abs(calibration.sens_drift()), 0.02)
        self.assertTrue(calibration.needs_recalibration_warning())

    def test_divergence_from_valorant(self):
        cfg = base_cfg(
            calibration_source="measured",
            counts_per_deg_x=140.0,
            counts_per_deg_y=140.0,
            calibration_samples=10,
        )
        calibration = resolve_calibration(cfg=cfg)
        # 140 vs 62.11 preset is > 100 % apart.
        self.assertGreater(abs(calibration.divergence_from_valorant), 0.20)


class TestAnalyticSource(unittest.TestCase):
    def test_analytic_uses_cm_per_rev(self):
        cfg = base_cfg(calibration_source="analytic")
        calibration = resolve_calibration(cfg=cfg)
        self.assertEqual(calibration.source, SOURCE_ANALYTIC)
        self.assertAlmostEqual(calibration.counts_per_deg_x, 285.26, delta=0.1)

    def test_analytic_always_warns(self):
        calibration = Calibration(source=SOURCE_ANALYTIC)
        self.assertTrue(calibration.needs_recalibration_warning())

    def test_unset_source_with_pair_is_measured(self):
        cfg = base_cfg(
            calibration_source="",
            counts_per_deg_x=140.0,
            counts_per_deg_y=140.0,
        )
        self.assertEqual(resolve_calibration(cfg=cfg).source, SOURCE_MEASURED)

    def test_unset_source_without_pair_is_analytic(self):
        cfg = base_cfg(calibration_source="")
        self.assertEqual(resolve_calibration(cfg=cfg).source, SOURCE_ANALYTIC)


class TestGeometryCache(unittest.TestCase):
    def setUp(self):
        clear_caches()

    def test_cache_hit_returns_same_object(self):
        cfg = base_cfg()
        first = resolve_geometry(frame_w=1920, frame_h=1080, cfg=cfg)
        second = resolve_geometry(frame_w=1920, frame_h=1080, cfg=cfg)
        self.assertIs(first, second)
        geometry_entries, _ = cache_sizes()
        self.assertEqual(geometry_entries, 1)

    def test_frame_size_invalidates(self):
        cfg = base_cfg()
        first = resolve_geometry(frame_w=1920, frame_h=1080, cfg=cfg)
        second = resolve_geometry(frame_w=1280, frame_h=720, cfg=cfg)
        self.assertIsNot(first, second)
        self.assertEqual(second.frame_w, 1280)
        self.assertEqual(cache_sizes()[0], 2)

    def test_hfov_change_invalidates(self):
        first = resolve_geometry(frame_w=1920, frame_h=1080, cfg=base_cfg(hfov_deg=103.0))
        second = resolve_geometry(frame_w=1920, frame_h=1080, cfg=base_cfg(hfov_deg=90.0))
        self.assertAlmostEqual(second.hfov_deg, 90.0, places=3)
        self.assertNotAlmostEqual(first.hfov_deg, second.hfov_deg, places=1)

    def test_cached_false_bypasses(self):
        cfg = base_cfg()
        first = resolve_geometry(frame_w=1920, frame_h=1080, cfg=cfg)
        fresh = resolve_geometry(frame_w=1920, frame_h=1080, cfg=cfg, cached=False)
        self.assertEqual(first.frame_w, fresh.frame_w)
        self.assertAlmostEqual(first.hfov_deg, fresh.hfov_deg, places=9)

    def test_crop_invalidates_and_changes_geometry(self):
        native = resolve_geometry(
            frame_w=1920,
            frame_h=1080,
            cfg=base_cfg(capture_mode="UDP", udp_fov_enabled=False),
        )
        cropped = resolve_geometry(
            frame_w=256,
            frame_h=256,
            cfg=base_cfg(
                capture_mode="UDP",
                udp_fov_enabled=True,
                udp_fov=128,
                capture_width=1920,
                capture_height=1080,
            ),
        )
        self.assertEqual(cropped.source, "crop")
        self.assertLess(cropped.hfov_deg, native.hfov_deg)
        # A centre crop preserves focal length.
        self.assertAlmostEqual(cropped.focal_x, native.focal_x, delta=1.0)

    def test_cache_is_bounded(self):
        for width in range(100, 200):
            resolve_geometry(frame_w=width, frame_h=100, cfg=base_cfg())
        self.assertLessEqual(cache_sizes()[0], 32)


class TestCalibrationCache(unittest.TestCase):
    def setUp(self):
        clear_caches()

    def test_cache_hit(self):
        cfg = base_cfg()
        first = resolve_calibration_cached(cfg=cfg)
        second = resolve_calibration_cached(cfg=cfg)
        self.assertIs(first, second)
        self.assertEqual(cache_sizes()[1], 1)

    def test_sens_change_invalidates_for_valorant(self):
        low = resolve_calibration_cached(cfg=base_cfg(in_game_sens=0.23))
        high = resolve_calibration_cached(cfg=base_cfg(in_game_sens=0.40))
        self.assertIsNot(low, high)
        self.assertAlmostEqual(high.counts_per_deg_x, 35.714, delta=0.01)

    def test_measurement_change_invalidates(self):
        first = resolve_calibration_cached(
            cfg=base_cfg(
                calibration_source="measured",
                counts_per_deg_x=140.0,
                counts_per_deg_y=140.0,
            )
        )
        second = resolve_calibration_cached(
            cfg=base_cfg(
                calibration_source="measured",
                counts_per_deg_x=150.0,
                counts_per_deg_y=150.0,
            )
        )
        self.assertAlmostEqual(first.counts_per_deg_x, 140.0)
        self.assertAlmostEqual(second.counts_per_deg_x, 150.0)

    def test_cache_is_bounded(self):
        for sens in (0.1, 0.11, 0.12):
            resolve_calibration_cached(cfg=base_cfg(in_game_sens=sens))
        self.assertLessEqual(cache_sizes()[1], 32)

    def test_clear_caches(self):
        resolve_calibration_cached(cfg=base_cfg())
        resolve_geometry(frame_w=800, frame_h=600, cfg=base_cfg())
        self.assertEqual(cache_sizes(), (1, 1))
        clear_caches()
        self.assertEqual(cache_sizes(), (0, 0))


if __name__ == "__main__":
    unittest.main()
