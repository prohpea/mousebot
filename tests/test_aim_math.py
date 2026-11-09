"""Pure-math tests for the single pixel -> count conversion (plan section 8.1)."""

import math
import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aim_system.aim_math import (  # noqa: E402
    Calibration,
    FrameGeometry,
    counts_per_deg_from_slope,
    fit_calibration,
    geometry_from_native,
    hfov_from_focal,
    legacy_exact_counts,
    px_to_counts,
    resolve_calibration,
    resolve_crop_info,
    resolve_geometry,
    vfov_from_hfov,
)


class TestFrameGeometry(unittest.TestCase):
    def setUp(self):
        # 1920x1080, 103 deg horizontal FOV -> focal_x = 763.62 px
        self.geom = geometry_from_native(
            native_w=1920, native_h=1080, hfov_deg=103.0
        )

    def test_focal_length_at_center(self):
        self.assertAlmostEqual(self.geom.focal_x, 763.62, places=1)
        self.assertAlmostEqual(self.geom.hfov_deg, 103.0, places=6)

    def test_px_to_deg_30px(self):
        deg_x, deg_y = self.geom.px_to_deg(30.0, 0.0)
        self.assertAlmostEqual(deg_x, 2.2502, places=3)
        self.assertAlmostEqual(deg_y, 0.0, places=9)

    def test_deg_to_px_roundtrip(self):
        dx, dy = self.geom.deg_to_px(2.2502, -1.5)
        back_x, back_y = self.geom.px_to_deg(dx, dy)
        self.assertAlmostEqual(back_x, 2.2502, places=6)
        self.assertAlmostEqual(back_y, -1.5, places=6)

    def test_square_pixels_give_equal_focal_lengths(self):
        self.assertAlmostEqual(self.geom.focal_x, self.geom.focal_y, places=6)
        self.assertAlmostEqual(self.geom.aspect, 16.0 / 9.0, places=9)

    def test_vfov_derived_from_aspect(self):
        vfov = vfov_from_hfov(103.0, 1920, 1080)
        self.assertAlmostEqual(vfov, self.geom.vfov_deg, places=6)
        # tan(half_v) = tan(half_h) * 9/16
        expected = math.degrees(
            2.0 * math.atan(math.tan(math.radians(103.0 / 2)) * (1080 / 1920))
        )
        self.assertAlmostEqual(vfov, expected, places=9)

    def test_square_aspect_vfov_equals_hfov(self):
        vfov = vfov_from_hfov(90.0, 512, 512)
        self.assertAlmostEqual(vfov, 90.0, places=9)

    def test_invalid_geometry_rejected(self):
        with self.assertRaises(ValueError):
            FrameGeometry(frame_w=0, frame_h=1080, hfov_deg=103.0, vfov_deg=70.0)
        with self.assertRaises(ValueError):
            FrameGeometry(frame_w=1920, frame_h=1080, hfov_deg=0.0, vfov_deg=70.0)


class TestCropGeometry(unittest.TestCase):
    """A centre crop keeps the angular scale; a downscale increases deg/px."""

    def test_crop_preserves_focal_length_and_reduces_fov(self):
        full = geometry_from_native(native_w=1920, native_h=1080, hfov_deg=103.0)
        # 512x512 centre crop of a 1920x1080 source (udp_fov=256 -> 2*256)
        crop = geometry_from_native(
            native_w=1920,
            native_h=1080,
            hfov_deg=103.0,
            region_w=512,
            region_h=512,
            source="crop",
        )
        self.assertAlmostEqual(crop.focal_x, full.focal_x, places=6)
        self.assertLess(crop.hfov_deg, full.hfov_deg)
        self.assertGreater(crop.deg_per_px_at_center()[0], 0.0)

    def test_crop_cores_degrees_scale_with_width(self):
        full = geometry_from_native(native_w=1920, native_h=1080, hfov_deg=103.0)
        crop = geometry_from_native(
            native_w=1920, native_h=1080, hfov_deg=103.0, region_w=480, region_h=270
        )
        # A centre crop keeps the focal length, so the FOV follows atan(), not a
        # linear width ratio.
        expected = math.degrees(2.0 * math.atan((480 / 2.0) / full.focal_x))
        self.assertAlmostEqual(crop.hfov_deg, expected, places=6)
        self.assertLess(crop.hfov_deg, full.hfov_deg)

    def test_smaller_frame_has_larger_deg_per_px(self):
        """Same 103 deg FOV in fewer pixels => each pixel covers more angle."""
        big = resolve_geometry(frame_w=1920, frame_h=1080, cfg={"hfov_deg": 103.0, "vfov_deg": 0.0})
        small = resolve_geometry(frame_w=256, frame_h=256, cfg={"hfov_deg": 103.0, "vfov_deg": 0.0})
        self.assertGreater(
            small.deg_per_px_at_center()[0], big.deg_per_px_at_center()[0]
        )
        # 1920/256 ratio == 7.5x wider pixels for the same FOV
        ratio = small.deg_per_px_at_center()[0] / big.deg_per_px_at_center()[0]
        self.assertAlmostEqual(ratio, 1920.0 / 256.0, places=6)

    def test_square_crop_uses_square_aspect(self):
        geom = resolve_geometry(frame_w=256, frame_h=256, cfg={"hfov_deg": 103.0, "vfov_deg": 0.0})
        self.assertAlmostEqual(geom.aspect, 1.0, places=9)
        self.assertAlmostEqual(geom.focal_x, geom.focal_y, places=6)

    def test_resolve_crop_info_udp_half_extent(self):
        crop = resolve_crop_info(
            capture_mode="UDP",
            udp_fov_enabled=True,
            udp_fov=108,
            native_w=1920,
            native_h=1080,
        )
        self.assertTrue(crop.is_cropped)
        self.assertEqual((crop.crop_w, crop.crop_h), (216, 216))

    def test_resolve_crop_info_disabled_is_not_cropped(self):
        crop = resolve_crop_info(
            capture_mode="UDP",
            udp_fov_enabled=False,
            udp_fov=108,
            native_w=1920,
            native_h=1080,
        )
        self.assertFalse(crop.is_cropped)

    def test_resolve_geometry_uses_frame_when_no_crop(self):
        geom = resolve_geometry(
            frame_w=1920,
            frame_h=1080,
            cfg={
                "hfov_deg": 103.0,
                "vfov_deg": 0.0,
                "capture_mode": "UDP",
                "udp_fov_enabled": False,
                "capture_width": 1920,
                "capture_height": 1080,
            },
        )
        self.assertEqual(geom.frame_w, 1920)
        self.assertEqual(geom.source, "analytic")


class TestCalibration(unittest.TestCase):
    def test_analytic_counts_per_deg(self):
        calib = Calibration(sens=0.23, dpi=1100)
        self.assertFalse(calib.is_measured)
        # 54.54 cm/rev, 1100 dpi, sens 0.23 -> 0.00350555 deg/count
        self.assertAlmostEqual(calib.deg_per_count, 0.00350555, places=7)
        self.assertAlmostEqual(calib.counts_per_deg_x, 285.26, delta=0.05)

    def test_measured_wins_over_analytic(self):
        calib = Calibration(counts_per_deg_x=140.0, counts_per_deg_y=140.0, sens=0.23, dpi=1100)
        self.assertTrue(calib.is_measured)
        self.assertAlmostEqual(calib.counts_per_deg_x, 140.0)

    def test_deg_to_counts_is_linear(self):
        calib = Calibration(counts_per_deg_x=140.0, counts_per_deg_y=70.0)
        cx, cy = calib.deg_to_counts(2.25, -4.0)
        self.assertAlmostEqual(cx, 315.0, places=9)
        self.assertAlmostEqual(cy, -280.0, places=9)

    def test_counts_to_deg_roundtrip(self):
        calib = Calibration(counts_per_deg_x=140.0, counts_per_deg_y=70.0)
        deg = calib.counts_to_deg(315.0, -280.0)
        self.assertAlmostEqual(deg[0], 2.25, places=9)
        self.assertAlmostEqual(deg[1], -4.0, places=9)

    def test_half_measured_pair_falls_back_to_analytic(self):
        calib = Calibration(counts_per_deg_x=140.0, counts_per_deg_y=None)
        self.assertFalse(calib.is_measured)
        self.assertIsNotNone(calib.counts_per_deg_y)

    def test_divergence_warning(self):
        analytic = Calibration(sens=0.23, dpi=1100).counts_per_deg_x
        calib = Calibration(
            counts_per_deg_x=analytic * 1.5, counts_per_deg_y=analytic * 1.5, sens=0.23, dpi=1100
        )
        self.assertTrue(calib.needs_recalibration_warning())


class TestPxToCounts(unittest.TestCase):
    def setUp(self):
        self.geom = geometry_from_native(native_w=1920, native_h=1080, hfov_deg=103.0)
        self.calib = Calibration(counts_per_deg_x=285.0, counts_per_deg_y=285.0)

    def test_matches_analytic_30px(self):
        counts_x, _ = px_to_counts(30.0, 0.0, geometry=self.geom, calibration=self.calib)
        # 2.2502 deg * 285 counts/deg = 641.3 counts
        self.assertAlmostEqual(counts_x, 641.3, delta=0.5)

    def test_sign_symmetry(self):
        pos = px_to_counts(30.0, -12.0, geometry=self.geom, calibration=self.calib)
        neg = px_to_counts(-30.0, 12.0, geometry=self.geom, calibration=self.calib)
        self.assertAlmostEqual(pos[0], -neg[0], places=9)
        self.assertAlmostEqual(pos[1], -neg[1], places=9)

    def test_zero_error_is_zero(self):
        self.assertEqual(
            px_to_counts(0.0, 0.0, geometry=self.geom, calibration=self.calib), (0.0, 0.0)
        )

    def test_axis_independence(self):
        counts_x, counts_y = px_to_counts(10.0, 0.0, geometry=self.geom, calibration=self.calib)
        self.assertAlmostEqual(counts_y, 0.0, places=9)

    def test_legacy_wrapper_matches_documented_value(self):
        # Plan section 3.1: 30 px at sens 0.23 / dpi 1100 -> 641.9 counts.
        counts_x, _ = legacy_exact_counts(30.0, 0.0, 0.23, 1100)
        self.assertAlmostEqual(counts_x, 641.9, delta=1.0)

    def test_px_to_counts_from_cfg(self):
        cfg = {
            "in_game_sens": 0.23,
            "mouse_dpi": 1100,
            "counts_per_deg_x": 0.0,
            "counts_per_deg_y": 0.0,
            "hfov_deg": 103.0,
            "vfov_deg": 0.0,
        }
        counts_x, _ = px_to_counts(
            30.0, 0.0, cfg=cfg, geometry=geometry_from_native(1920, 1080, 103.0)
        )
        self.assertAlmostEqual(counts_x, 641.9, delta=1.0)


class TestResolveCalibration(unittest.TestCase):
    def test_measured_config_is_used(self):
        cfg = {
            "in_game_sens": 0.23,
            "mouse_dpi": 1100,
            "counts_per_deg_x": 140.0,
            "counts_per_deg_y": 140.0,
        }
        calib = resolve_calibration(cfg=cfg)
        self.assertTrue(calib.is_measured)
        self.assertAlmostEqual(calib.counts_per_deg_x, 140.0)

    def test_zero_measurement_falls_back_to_analytic(self):
        cfg = {
            "in_game_sens": 0.23,
            "mouse_dpi": 1100,
            "counts_per_deg_x": 0.0,
            "counts_per_deg_y": 0.0,
        }
        calib = resolve_calibration(cfg=cfg)
        self.assertFalse(calib.is_measured)
        self.assertGreater(calib.counts_per_deg_x, 0.0)


class TestCalibrationFitting(unittest.TestCase):
    def test_fit_perfect_line(self):
        samples = [(25, 40), (50, 80), (100, 160), (200, 320), (400, 640)]
        fit = fit_calibration(samples)
        self.assertIsNotNone(fit)
        slope, intercept, r2 = fit
        self.assertAlmostEqual(slope, 1.6, places=6)
        self.assertAlmostEqual(intercept, 0.0, places=6)
        self.assertAlmostEqual(r2, 1.0, places=9)

    def test_fit_line_with_offset(self):
        samples = [(10, 20), (20, 35), (30, 50), (40, 65)]
        fit = fit_calibration(samples)
        self.assertIsNotNone(fit)
        slope, intercept, r2 = fit
        self.assertAlmostEqual(slope, 1.5, places=6)
        self.assertAlmostEqual(intercept, 5.0, places=6)
        self.assertAlmostEqual(r2, 1.0, places=9)

    def test_fit_rejects_noise(self):
        samples = [(25, 400), (50, 80), (100, 9), (200, 320), (400, 640)]
        self.assertIsNone(fit_calibration(samples, min_r2=0.99))

    def test_fit_needs_two_points(self):
        self.assertIsNone(fit_calibration([(10, 20)]))
        self.assertIsNone(fit_calibration([]))

    def test_slope_to_counts_per_deg(self):
        geom = geometry_from_native(1920, 1080, 103.0)
        deg_per_px_x, deg_per_px_y = geom.deg_per_px_at_center()
        cpd_x, cpd_y = counts_per_deg_from_slope(geom, 0.21, 0.21)
        self.assertAlmostEqual(cpd_x, 0.21 / deg_per_px_x, places=9)
        self.assertAlmostEqual(cpd_y, 0.21 / deg_per_px_y, places=9)


class TestNoMagicConstants(unittest.TestCase):
    """Measured calibration must remove 54.54 and 103.0 from the result."""

    def test_measured_scale_is_independent_of_54_54(self):
        geom = geometry_from_native(1920, 1080, 103.0)
        a = Calibration(counts_per_deg_x=140.0, counts_per_deg_y=140.0, cm_per_rev=54.54)
        b = Calibration(counts_per_deg_x=140.0, counts_per_deg_y=140.0, cm_per_rev=999.0)
        self.assertEqual(
            a.px_to_counts(geom, 30.0, 20.0), b.px_to_counts(geom, 30.0, 20.0)
        )

    def test_two_legacy_models_differed_by_about_1_4x(self):
        """Documents the old conflict the plan measured (sanity, not behaviour)."""
        deg_per_px_centre = geometry_from_native(1920, 1080, 103.0).deg_per_px_at_center()[0]
        naive = 103.0 / 1920.0
        self.assertAlmostEqual(deg_per_px_centre / naive, 1.3986, places=3)


if __name__ == "__main__":
    unittest.main()
