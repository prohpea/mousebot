"""Config schema-3, provenance and migration tests (plan 10.1/10.2/5.7).

Covers the three defects the plan found in the shipped config:

* ``counts_per_deg = 62.11`` with ``samples = 0, r2 = 0`` was displayed as
  MEASURED although it is the Valorant preset at sens 0.23 (C4);
* ``ui_pro_mode`` was read/written by the UI but absent from the schema, so it
  reset on every launch (C13);
* the new Settle/Switch Radius keys had no schema, clamp or round-trip (G1/G7).
"""

import json
import os
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.config import Config  # noqa: E402


def fresh_config(data=None):
    """A Config built from DEFAULTS only (never the real ``config.json``).

    ``Config.__init__`` calls ``load_from_file()`` with a relative path, so the
    helper runs it from an empty temporary directory: the migration only sees the
    payload we pass in.
    """
    previous = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            cfg = Config()
        finally:
            os.chdir(previous)
    if data is not None:
        cfg.from_dict(data)
    return cfg


class TestFreshDefaults(unittest.TestCase):
    def test_schema_and_calibration_defaults(self):
        cfg = fresh_config()
        self.assertGreaterEqual(cfg.config_schema, 3)
        self.assertEqual(cfg.calibration_source, "valorant")
        self.assertAlmostEqual(cfg.valorant_deg_per_count, 0.07)
        self.assertGreater(cfg.counts_per_deg_x, 0.0)
        self.assertAlmostEqual(
            cfg.counts_per_deg_x, 1.0 / (0.07 * cfg.in_game_sens), places=6
        )

    def test_flick_defaults_honour_iterations(self):
        cfg = fresh_config()
        self.assertAlmostEqual(cfg.flick_budget_ms, 240.0)
        self.assertAlmostEqual(cfg.flick_budget_ms_sec, 240.0)
        self.assertEqual(cfg.flick_max_iterations, 4)
        self.assertAlmostEqual(cfg.flick_settle_ms, 70.0)
        # budget 240 / settle 70 -> floor(3.43)+1 = 4 steps
        self.assertEqual(int(cfg.flick_budget_ms // cfg.flick_settle_ms) + 1, 4)

    def test_switch_radius_defaults(self):
        cfg = fresh_config()
        self.assertEqual(cfg.flick_switch_radius_px, 64)
        self.assertEqual(cfg.flick_switch_radius_px_sec, 64)

    def test_ui_pro_mode_is_persisted(self):
        cfg = fresh_config()
        self.assertFalse(cfg.ui_pro_mode)
        self.assertIn("ui_pro_mode", cfg.to_dict())

    def test_ui_preview_fps_default(self):
        cfg = fresh_config()
        self.assertEqual(cfg.ui_preview_max_fps, 30)


class TestMigrationValorant(unittest.TestCase):
    """62.11 @ sens 0.23 must migrate to source=valorant, NOT measured."""

    def setUp(self):
        self.payload = {
            "in_game_sens": 0.23,
            "mouse_dpi": 1100,
            "counts_per_deg_x": 62.11,
            "counts_per_deg_y": 62.11,
            "calibration_r2": 0.0,
            "calibration_samples": 0,
            "hfov_deg": 103.0,
        }

    def test_migrates_to_valorant_preset(self):
        cfg = fresh_config(self.payload)
        self.assertEqual(cfg.calibration_source, "valorant")
        # The stored 62.11 is kept (it matches the preset within 1 %).
        self.assertAlmostEqual(cfg.counts_per_deg_x, 62.11, delta=0.05)
        self.assertEqual(cfg.calibration_samples, 0)
        self.assertEqual(cfg.calibration_r2, 0.0)

    def test_records_sens_at_calibration(self):
        cfg = fresh_config(self.payload)
        self.assertAlmostEqual(cfg.valorant_sens_at_calibration, 0.23)

    def test_valorant_scale_matches_formula(self):
        cfg = fresh_config(self.payload)
        expected = 1.0 / (0.07 * 0.23)
        self.assertAlmostEqual(cfg.valorant_counts_per_deg(0.23), expected, places=6)
        self.assertAlmostEqual(expected, 62.1118, places=3)


class TestMigrationAnalytic(unittest.TestCase):
    """An unbacked legacy scale (285.28) must be demoted, not trusted."""

    def test_legacy_scale_is_demoted_to_analytic(self):
        payload = {
            "in_game_sens": 0.23,
            "mouse_dpi": 1100,
            # 285.28 is the analytic value, but with no samples/r2 it could also
            # be a hand-typed number: it must not be presented as measured.
            "counts_per_deg_x": 285.28,
            "counts_per_deg_y": 285.28,
            "calibration_r2": 0.0,
            "calibration_samples": 0,
        }
        cfg = fresh_config(payload)
        self.assertEqual(cfg.calibration_source, "analytic")
        self.assertEqual(cfg.counts_per_deg_x, 0.0)
        self.assertEqual(cfg.counts_per_deg_y, 0.0)

    def test_backed_measurement_stays_measured(self):
        payload = {
            "in_game_sens": 0.23,
            "mouse_dpi": 1100,
            "counts_per_deg_x": 140.0,
            "counts_per_deg_y": 141.0,
            "calibration_r2": 0.995,
            "calibration_samples": 10,
        }
        cfg = fresh_config(payload)
        self.assertEqual(cfg.calibration_source, "measured")
        self.assertAlmostEqual(cfg.counts_per_deg_x, 140.0)
        self.assertAlmostEqual(cfg.calibration_sens_at_measurement, 0.23)

    def test_measured_needs_samples_and_r2(self):
        payload = {
            "in_game_sens": 0.23,
            "mouse_dpi": 1100,
            "counts_per_deg_x": 140.0,
            "counts_per_deg_y": 141.0,
            "calibration_r2": 0.5,
            "calibration_samples": 2,
        }
        cfg = fresh_config(payload)
        # Not enough evidence: demoted (and the raw pair zeroed so nothing lies).
        self.assertNotEqual(cfg.calibration_source, "measured")
        self.assertEqual(cfg.counts_per_deg_x, 0.0)

    def test_explicit_source_is_respected(self):
        payload = {
            "in_game_sens": 0.23,
            "counts_per_deg_x": 140.0,
            "counts_per_deg_y": 140.0,
            "calibration_r2": 0.999,
            "calibration_samples": 12,
            "calibration_source": "measured",
        }
        cfg = fresh_config(payload)
        self.assertEqual(cfg.calibration_source, "measured")
        self.assertAlmostEqual(cfg.counts_per_deg_x, 140.0)

    def test_schema_2_file_without_source_key_is_not_assumed_valorant(self):
        """A pre-provenance file must not inherit the fresh "valorant" default."""
        # No counts and no source key: legacy file -> analytic, not a preset.
        cfg = fresh_config({"in_game_sens": 0.23, "mouse_dpi": 1100})
        self.assertEqual(cfg.calibration_source, "analytic")
        self.assertEqual(cfg.counts_per_deg_x, 0.0)

    def test_half_pair_is_rejected(self):
        payload = {
            "in_game_sens": 0.23,
            "counts_per_deg_x": 140.0,
            "counts_per_deg_y": 0.0,
            "calibration_r2": 0.999,
            "calibration_samples": 12,
            "calibration_source": "measured",
        }
        cfg = fresh_config(payload)
        self.assertFalse(cfg.measured_pair_valid())
        self.assertNotEqual(cfg.calibration_source, "measured")


class TestClamping(unittest.TestCase):
    def test_settle_clamped(self):
        cfg = fresh_config({"flick_settle_ms": 9999.0, "flick_settle_ms_sec": -5.0})
        self.assertLessEqual(cfg.flick_settle_ms, 500.0)
        self.assertGreaterEqual(cfg.flick_settle_ms_sec, 0.0)

    def test_switch_radius_clamped(self):
        cfg = fresh_config({"flick_switch_radius_px": 9999, "flick_switch_radius_px_sec": 1})
        self.assertEqual(cfg.flick_switch_radius_px, 256)
        self.assertEqual(cfg.flick_switch_radius_px_sec, 16)

    def test_budget_clamped(self):
        cfg = fresh_config({"flick_budget_ms": 5.0, "flick_budget_ms_sec": 99999})
        self.assertGreaterEqual(cfg.flick_budget_ms, 20.0)
        self.assertLessEqual(cfg.flick_budget_ms_sec, 1000.0)

    def test_valorant_yaw_clamped(self):
        cfg = fresh_config({"valorant_deg_per_count": 5.0})
        self.assertLessEqual(cfg.valorant_deg_per_count, 0.2)

    def test_gain_clamped(self):
        cfg = fresh_config({"flick_gain": 99.0, "flick_gain_sec": 0.0})
        self.assertLessEqual(cfg.flick_gain, 3.0)
        self.assertGreaterEqual(cfg.flick_gain_sec, 0.1)


class TestLegacyBudgetMigration(unittest.TestCase):
    def test_sec_cooldown_maps_to_budget(self):
        cfg = fresh_config({"sec_flick_cooldown_ms": 85.0})
        self.assertAlmostEqual(cfg.flick_budget_ms_sec, 85.0)
        self.assertAlmostEqual(cfg.sec_flick_cooldown_ms, 85.0)

    def test_missing_budget_keeps_old_behaviour(self):
        cfg = fresh_config({"in_game_sens": 0.23})
        self.assertAlmostEqual(cfg.flick_budget_ms, 120.0)
        self.assertAlmostEqual(cfg.flick_budget_ms_sec, 120.0)


class TestRoundTrip(unittest.TestCase):
    def test_to_dict_from_dict_keeps_schema_3_keys(self):
        cfg = fresh_config()
        cfg.calibration_source = "measured"
        cfg.counts_per_deg_x = 140.0
        cfg.counts_per_deg_y = 141.0
        cfg.calibration_r2 = 0.995
        cfg.calibration_samples = 10
        cfg.calibration_sens_at_measurement = 0.24
        cfg.flick_settle_ms = 90.0
        cfg.flick_settle_ms_sec = 95.0
        cfg.flick_switch_radius_px = 80
        cfg.flick_switch_radius_px_sec = 96
        cfg.flick_telemetry_enabled = True
        cfg.ui_pro_mode = True
        cfg.ui_preview_max_fps = 45
        cfg.move_queue_per_tag_dispatch = False

        payload = cfg.to_dict()
        restored = fresh_config(payload)

        self.assertEqual(restored.calibration_source, "measured")
        self.assertAlmostEqual(restored.counts_per_deg_x, 140.0)
        self.assertAlmostEqual(restored.counts_per_deg_y, 141.0)
        self.assertAlmostEqual(restored.calibration_r2, 0.995)
        self.assertEqual(restored.calibration_samples, 10)
        self.assertAlmostEqual(restored.calibration_sens_at_measurement, 0.24)
        self.assertAlmostEqual(restored.flick_settle_ms, 90.0)
        self.assertAlmostEqual(restored.flick_settle_ms_sec, 95.0)
        self.assertEqual(restored.flick_switch_radius_px, 80)
        self.assertEqual(restored.flick_switch_radius_px_sec, 96)
        self.assertTrue(restored.flick_telemetry_enabled)
        self.assertTrue(restored.ui_pro_mode)
        self.assertEqual(restored.ui_preview_max_fps, 45)
        self.assertFalse(restored.move_queue_per_tag_dispatch)

    def test_json_file_round_trip(self):
        cfg = fresh_config()
        cfg.flick_settle_ms = 110.0
        cfg.calibration_source = "valorant"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            cfg.save_to_file(path)
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertGreaterEqual(payload["config_schema"], 3)
            self.assertIn("calibration_source", payload)
            self.assertIn("flick_settle_ms", payload)
            self.assertAlmostEqual(payload["flick_settle_ms"], 110.0)


class TestShippedConfigFiles(unittest.TestCase):
    def test_config_json_is_schema_3(self):
        path = os.path.join(PROJECT_ROOT, "config.json")
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertGreaterEqual(payload.get("config_schema"), 3)
        self.assertEqual(payload.get("calibration_source"), "valorant")
        self.assertIn("flick_switch_radius_px", payload)
        self.assertAlmostEqual(payload.get("counts_per_deg_x"), 62.11, delta=0.01)

    def test_presets_carry_provenance(self):
        presets_dir = os.path.join(PROJECT_ROOT, "configs")
        names = [n for n in os.listdir(presets_dir) if n.endswith(".json")]
        self.assertGreaterEqual(len(names), 6)
        for name in names:
            with self.subTest(preset=name):
                with open(os.path.join(presets_dir, name), "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                self.assertGreaterEqual(payload.get("config_schema"), 3)
                self.assertIn("calibration_source", payload)
                self.assertIn("flick_switch_radius_px", payload)
                self.assertIn("flick_settle_ms", payload)

    def test_shipped_count_per_deg_matches_valorant(self):
        with open(os.path.join(PROJECT_ROOT, "config.json"), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        sens = payload.get("in_game_sens", 0.23)
        expected = 1.0 / (payload.get("valorant_deg_per_count", 0.07) * sens)
        self.assertAlmostEqual(payload.get("counts_per_deg_x"), expected, delta=0.05)


if __name__ == "__main__":
    unittest.main()
