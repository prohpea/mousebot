"""Flick V2 UI + Calibration tests (plan 12.2).

These build a real ``ViewerApp`` on a withdrawn Tk window (the existing UI test
suite does the same), then assert:

* the Flick V2 tab exists and exposes all seven parameters per channel,
* ``Settle Delay`` reaches the config (the P0 gap G1),
* a callback propagates immediately into the live controller (C14),
* the derived ``effective steps`` warning is computed from the real numbers,
* the Valorant preset updates counts + source, and follows sensitivity,
* a measured fit refuses an incomplete axis and keeps the SIGNED shift.
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class _UIBase(unittest.TestCase):
    """Shared Tk setup; skipped cleanly when Tk is unavailable."""

    @classmethod
    def setUpClass(cls):
        try:
            import _tkinter
            from unittest.mock import MagicMock
            if isinstance(_tkinter, MagicMock) or not hasattr(_tkinter, "__file__"):
                raise unittest.SkipTest("real tkinter unavailable")
            import customtkinter as ctk

            ctk.set_appearance_mode("Dark")
        except Exception as exc:  # pragma: no cover - environment dependent
            raise unittest.SkipTest(f"customtkinter unavailable: {exc}")

    def setUp(self):
        from src.utils.config import config

        # Snapshot and restore the global config so tests never leak into each
        # other or into config.json.
        self._saved = dict(config.to_dict())
        config.calibration_source = "valorant"
        config.in_game_sens = 0.23
        config.mouse_dpi = 1100
        config.valorant_deg_per_count = 0.07
        config.counts_per_deg_x = 0.0
        config.counts_per_deg_y = 0.0
        config.calibration_r2 = 0.0
        config.calibration_samples = 0
        config.flick_settle_ms = 70.0
        config.flick_settle_ms_sec = 70.0
        config.flick_budget_ms = 240.0
        config.flick_budget_ms_sec = 240.0
        config.flick_max_iterations = 4
        config.flick_max_iterations_sec = 4
        config.flick_switch_radius_px = 64
        config.flick_switch_radius_px_sec = 64
        config.mode = "Flick"
        config.mode_sec = "Flick"
        config.ui_pro_mode = True

        from src.aim_system.aim_math import clear_caches

        clear_caches()

    def tearDown(self):
        from src.utils.config import config

        for key, value in self._saved.items():
            try:
                setattr(config, key, value)
            except Exception:
                pass
        from src.aim_system.aim_math import clear_caches

        clear_caches()

    def make_app(self):
        from unittest.mock import MagicMock

        import customtkinter as ctk

        from src.ui import ViewerApp

        ctk.set_appearance_mode("Dark")
        tracker = MagicMock()
        tracker.flick_status = {}
        tracker.calibration_session = False
        tracker._aim_frame = None
        # MagicMock auto-creates attributes, so the flick controller cache must be
        # cleared explicitly or mode_flick would "find" a mock controller.
        tracker.capture_service = None
        tracker.capture = None
        for attr in (
            "_flick_controller_main",
            "_flick_controller_sec",
            "_flick_tuning_sig_main",
            "_flick_tuning_sig_sec",
        ):
            setattr(tracker, attr, None)
        capture = MagicMock()
        app = ViewerApp(tracker=tracker, capture_service=capture)
        app.withdraw()
        self.addCleanup(app.destroy)
        return app


class TestFlickV2Tab(_UIBase):
    SPEC_KEYS = (
        "flick_gain",
        "flick_settle_ms",
        "flick_max_counts",
        "flick_budget_ms",
        "flick_max_iterations",
        "flick_deadzone_px",
        "flick_switch_radius_px",
    )

    def test_tab_builds_and_registers_sliders(self):
        app = self.make_app()
        app._show_flick_v2_tab()
        self.assertEqual(app._active_tab_name, "Flick V2")
        self.assertTrue(hasattr(app, "card_flick_main"))
        self.assertTrue(hasattr(app, "card_flick_sec"))
        self.assertIsInstance(getattr(app, "flick_sliders_main", None), dict)
        self.assertIsInstance(getattr(app, "flick_sliders_sec", None), dict)

    def test_all_seven_parameters_on_both_channels(self):
        app = self.make_app()
        app._show_flick_v2_tab()
        for key in self.SPEC_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, app.flick_sliders_main)
                self.assertIn(f"{key}_sec", app.flick_sliders_sec)

    def test_settle_delay_widget_exists(self):
        """G1: the config supported Settle but the UI never exposed it."""
        app = self.make_app()
        app._show_flick_v2_tab()
        self.assertIn("flick_settle_ms", app.flick_sliders_main)
        self.assertIn("flick_settle_ms_sec", app.flick_sliders_sec)

    def test_switch_radius_is_advanced_only(self):
        from src.ui_tabs.common import FLICK_SLIDER_SPECS, FLICK_COMPACT_KEYS

        advanced = [spec[0] for spec in FLICK_SLIDER_SPECS if spec[8]]
        self.assertIn("flick_switch_radius_px", advanced)
        self.assertNotIn("flick_switch_radius_px", FLICK_COMPACT_KEYS)

    def test_compact_card_on_main_and_sec_tabs(self):
        app = self.make_app()
        app._show_aimbot_tab()
        self.assertTrue(hasattr(app, "card_windmouse"))
        self.assertIn("flick_settle_ms", app._slider_widgets)

        app._show_sec_aimbot_tab()
        self.assertTrue(hasattr(app, "card_windmouse_sec"))
        self.assertIn("flick_settle_ms_sec", app._slider_widgets)

    def test_calibration_card_present(self):
        app = self.make_app()
        app._show_flick_v2_tab()
        self.assertTrue(hasattr(app, "card_calibration"))
        self.assertTrue(hasattr(app, "calibration_source_var"))
        self.assertTrue(hasattr(app, "calibration_valorant_label"))

    def test_calibrate_button_selects_valorant(self):
        app = self.make_app()
        app._show_aimbot_tab()
        app.show_flick_v2_calibration()
        self.assertEqual(app._active_tab_name, "Flick V2")
        self.assertEqual(app.calibration_source_var.get(), "valorant")


class TestFlickCallbacks(_UIBase):
    def test_settle_callback_writes_config(self):
        app = self.make_app()
        app._show_flick_v2_tab()
        app._on_flick_param_changed("flick_settle_ms", 95.0)
        from src.utils.config import config

        self.assertAlmostEqual(config.flick_settle_ms, 95.0)

    def test_settle_sec_callback_writes_config(self):
        app = self.make_app()
        app._show_flick_v2_tab()
        app._on_flick_param_changed("flick_settle_ms_sec", 110.0)
        from src.utils.config import config

        self.assertAlmostEqual(config.flick_settle_ms_sec, 110.0)

    def test_switch_radius_callback_writes_config(self):
        app = self.make_app()
        app._show_flick_v2_tab()
        app._on_flick_param_changed("flick_switch_radius_px", 128)
        from src.utils.config import config

        self.assertEqual(config.flick_switch_radius_px, 128)

    def test_values_are_clamped_to_spec(self):
        app = self.make_app()
        app._show_flick_v2_tab()
        app._on_flick_param_changed("flick_gain", 99.0)
        app._on_flick_param_changed("flick_deadzone_px", -5.0)
        from src.utils.config import config

        self.assertLessEqual(config.flick_gain, 3.0)
        self.assertGreaterEqual(config.flick_deadzone_px, 0.0)

    def test_budget_callback_keeps_legacy_alias(self):
        app = self.make_app()
        app._show_flick_v2_tab()
        app._on_flick_param_changed("flick_budget_ms_sec", 200.0)
        from src.utils.config import config

        self.assertAlmostEqual(config.flick_budget_ms_sec, 200.0)
        self.assertAlmostEqual(config.sec_flick_cooldown_ms, 200.0)

    def test_gain_mirrors_legacy_strength(self):
        app = self.make_app()
        app._on_flick_param_changed("flick_gain", 1.5)
        from src.utils.config import config

        self.assertAlmostEqual(config.flick_gain, 1.5)
        self.assertAlmostEqual(config.flick_strength_x, 1.5)

    def test_configure_propagates_settle_and_switch_radius(self):
        """C14: the slider must reach the LIVE controller, not just config."""
        from src.aim_system import mode_flick
        from src.aim_system.flick_controller import FlickController

        app = self.make_app()
        app._show_flick_v2_tab()
        app._on_flick_param_changed("flick_settle_ms", 130.0)
        app._on_flick_param_changed("flick_switch_radius_px", 120)

        controller, _tuning = mode_flick._get_controller(app.tracker, False)
        self.assertIsInstance(controller, FlickController)
        self.assertAlmostEqual(controller.settle_ms, 130.0)
        self.assertAlmostEqual(controller.switch_radius_px, 120.0)

    def test_telemetry_toggle_writes_config(self):
        import tkinter as tk

        app = self.make_app()
        app._show_flick_v2_tab()
        app.var_flick_telemetry = tk.BooleanVar(value=True)
        app.on_flick_telemetry_changed()
        from src.utils.config import config

        self.assertTrue(config.flick_telemetry_enabled)

    def test_engine_selector_writes_config(self):
        app = self.make_app()
        app._show_flick_v2_tab()
        app.on_flick_engine_selected("legacy")
        from src.utils.config import config

        self.assertEqual(config.flick_engine, "legacy")
        app.on_flick_engine_selected("v2")
        self.assertEqual(config.flick_engine, "v2")


class TestEffectiveStepsUI(_UIBase):
    def test_helper_matches_plan_examples(self):
        from src.ui_tabs.common import effective_steps

        self.assertEqual(effective_steps(4, 120.0, 70.0), 2)
        self.assertEqual(effective_steps(4, 240.0, 70.0), 4)
        self.assertEqual(effective_steps(4, 120.0, 0.0), 4)
        self.assertEqual(effective_steps(4, 40.0, 500.0), 1)

    def test_warning_when_budget_cannot_fund_iterations(self):
        from src.ui_tabs.common import timing_warning

        warning = timing_warning(4, 120.0, 70.0)
        self.assertIn("2", warning)
        self.assertIn("4", warning)

    def test_no_warning_when_consistent(self):
        from src.ui_tabs.common import timing_warning

        self.assertEqual(timing_warning(4, 240.0, 70.0), "")

    def test_readout_label_shows_steps_and_travel(self):
        from src.utils.config import config

        app = self.make_app()
        app._show_flick_v2_tab()
        config.flick_budget_ms = 120.0
        config.flick_settle_ms = 70.0
        config.flick_max_iterations = 4
        config.flick_max_counts = 6000.0
        app._refresh_flick_readouts()
        store = getattr(app, "flick_readouts_main", {})
        text = store["steps"].cget("text")
        self.assertIn("2", text)
        # 2 steps * 6000 counts
        self.assertIn("12,000", text)

    def test_auto_fix_raises_budget(self):
        from src.utils.config import config

        app = self.make_app()
        app._show_flick_v2_tab()
        config.flick_budget_ms = 120.0
        config.flick_settle_ms = 70.0
        app.auto_fix_flick_timing(False)
        self.assertGreater(config.flick_budget_ms, 120.0)
        from src.ui_tabs.common import effective_steps

        self.assertEqual(effective_steps(4, config.flick_budget_ms, 70.0), 4)

    def test_auto_fix_sec_channel(self):
        from src.utils.config import config

        app = self.make_app()
        app._show_flick_v2_tab()
        config.flick_budget_ms_sec = 120.0
        config.flick_settle_ms_sec = 70.0
        app.auto_fix_flick_timing(True)
        self.assertGreater(config.flick_budget_ms_sec, 120.0)


class TestValorantPreset(_UIBase):
    def test_apply_writes_62_112_at_sens_0_23(self):
        from src.utils.config import config
        from src.ui_tabs.calibration_tab import apply_valorant_scale

        app = self.make_app()
        app._show_flick_v2_tab()
        app.calibration_sens_entry.delete(0, "end")
        app.calibration_sens_entry.insert(0, "0.23")
        self.assertTrue(apply_valorant_scale(app))

        self.assertEqual(config.calibration_source, "valorant")
        self.assertAlmostEqual(config.counts_per_deg_x, 62.1118, places=3)
        self.assertAlmostEqual(config.counts_per_deg_y, 62.1118, places=3)
        self.assertEqual(config.calibration_samples, 0)
        self.assertEqual(config.calibration_r2, 0.0)

    def test_apply_follows_sens_change(self):
        from src.utils.config import config
        from src.ui_tabs.calibration_tab import apply_valorant_scale

        app = self.make_app()
        app._show_flick_v2_tab()
        app.calibration_sens_entry.delete(0, "end")
        app.calibration_sens_entry.insert(0, "0.40")
        apply_valorant_scale(app)
        self.assertAlmostEqual(config.counts_per_deg_x, 35.714, delta=0.01)

    def test_overlay_updates_when_sens_changes_without_reapply(self):
        """C5: with source=valorant the scale must follow sens automatically."""
        from src.utils.config import config
        from src.aim_system.aim_math import clear_caches, resolve_calibration

        app = self.make_app()
        app._show_flick_v2_tab()
        app.calibration_sens_entry.delete(0, "end")
        app.calibration_sens_entry.insert(0, "0.23")
        app.on_apply_valorant_scale()
        first = resolve_calibration().counts_per_deg_x

        config.in_game_sens = 0.40
        clear_caches()
        second = resolve_calibration().counts_per_deg_x
        self.assertNotAlmostEqual(first, second, places=2)
        self.assertAlmostEqual(second, 35.714, delta=0.05)

    def test_cm_per_360_readout(self):
        from src.aim_system.aim_math import resolve_calibration
        from src.utils.config import config

        app = self.make_app()
        app._show_flick_v2_tab()
        config.calibration_source = "valorant"
        calibration = resolve_calibration()
        self.assertAlmostEqual(calibration.cm_per_360(), 51.63, delta=0.05)


class TestMeasuredWorkflow(_UIBase):
    def _fill(self, app, axis, points):
        from src.utils.config import config

        for px, counts in points:
            app.calibration_axis_var.set(axis)
            app.calibration_counts_entry.delete(0, "end")
            app.calibration_counts_entry.insert(0, str(counts))
            app.calibration_px_entry.delete(0, "end")
            app.calibration_px_entry.insert(0, str(px))
            app.on_calibration_record_sample()

    def test_record_sample_keeps_sign(self):
        """C10: ``abs()`` destroyed the sign of the measured shift."""
        app = self.make_app()
        app._show_flick_v2_tab()
        app.calibration_axis_var.set("x")
        app.calibration_counts_entry.delete(0, "end")
        app.calibration_counts_entry.insert(0, "100")
        app.calibration_px_entry.delete(0, "end")
        app.calibration_px_entry.insert(0, "-12.5")
        self.assertTrue(app.on_calibration_record_sample())
        self.assertEqual(app._calibration_samples["x"], [(-12.5, 100.0)])

    def test_zero_shift_is_rejected(self):
        app = self.make_app()
        app._show_flick_v2_tab()
        app.calibration_px_entry.delete(0, "end")
        app.calibration_px_entry.insert(0, "0")
        self.assertFalse(app.on_calibration_record_sample())

    def test_fit_needs_both_axes(self):
        """C10: the old fit extrapolated the missing axis from the focal ratio."""
        from src.utils.config import config

        app = self.make_app()
        app._show_flick_v2_tab()
        self._fill(app, "x", [(-24, -100), (-12, -50), (0.1, 0.4), (12, 50), (24, 100)])
        self.assertFalse(app.on_calibration_fit())
        self.assertNotEqual(config.calibration_source, "measured")

    def test_fit_needs_five_samples_per_axis(self):
        from src.utils.config import config

        app = self.make_app()
        app._show_flick_v2_tab()
        points = [(-12, -50), (0.1, 0.4), (12, 50)]
        self._fill(app, "x", points)
        self._fill(app, "y", points)
        self.assertFalse(app.on_calibration_fit())
        self.assertNotEqual(config.calibration_source, "measured")

    def test_fit_accepts_two_full_axes(self):
        from src.utils.config import config

        app = self.make_app()
        app._show_flick_v2_tab()
        points = [(-24, -100), (-12, -50), (0.1, 0.4), (12, 50), (24, 100)]
        self._fill(app, "x", points)
        self._fill(app, "y", points)
        self.assertTrue(app.on_calibration_fit())
        self.assertEqual(config.calibration_source, "measured")
        self.assertGreaterEqual(config.calibration_samples, 10)
        self.assertGreaterEqual(config.calibration_r2, 0.99)

    def test_clear_reverts_to_analytic(self):
        from src.utils.config import config

        app = self.make_app()
        app._show_flick_v2_tab()
        config.calibration_source = "measured"
        config.counts_per_deg_x = 140.0
        config.counts_per_deg_y = 140.0
        config.calibration_samples = 10
        app.on_calibration_clear()
        self.assertEqual(config.calibration_source, "analytic")
        self.assertEqual(config.counts_per_deg_x, 0.0)
        self.assertEqual(config.calibration_samples, 0)


class TestCalibrationSession(_UIBase):
    def test_impulse_opens_calibration_session(self):
        """C2: an impulse must not race a live track/flick command."""
        app = self.make_app()
        app._show_flick_v2_tab()
        app.calibration_axis_var.set("x")
        app.calibration_counts_entry.delete(0, "end")
        app.calibration_counts_entry.insert(0, "100")
        app.on_calibration_send_impulse()
        self.assertTrue(app.tracker.calibration_session)
        app.tracker.move_queue.put_nowait.assert_called()

    def test_impulse_uses_exclusive_tag(self):
        app = self.make_app()
        app._show_flick_v2_tab()
        app.on_calibration_send_impulse()
        item = app.tracker.move_queue.put_nowait.call_args[0][0]
        self.assertEqual(len(item), 4)
        self.assertEqual(item[3], "calib")


class TestDiagnostics(_UIBase):
    def test_status_map_is_read(self):
        app = self.make_app()
        app._show_flick_v2_tab()
        app.tracker.flick_status = {
            "main": {
                "reason": "aim",
                "iterations": 1,
                "max_iterations": 4,
                "effective_steps": 4,
                "counts": (139.8, 0.0),
                "residual": (0.2, 0.0),
                "error_px": (30.0, 0.0),
                "calibration": "valorant",
                "geometry": "crop",
                "gain": 1.0,
                "clamped": 0,
                "armed": True,
            }
        }
        self.assertEqual(app.flick_status_for("main")["reason"], "aim")
        self.assertEqual(app.flick_status_for("sec"), {})

    def test_copy_diagnostics_payload_is_json(self):
        import json

        from src.ui_tabs.flick_tab import copy_diagnostics_payload

        app = self.make_app()
        app._show_flick_v2_tab()
        payload = copy_diagnostics_payload(app)
        decoded = json.loads(payload)
        self.assertEqual(decoded["engine"], "v2")
        self.assertIn("main", decoded)
        self.assertIn("flick_settle_ms", decoded["config"])

    def test_reset_state_clears_status(self):
        app = self.make_app()
        app._show_flick_v2_tab()
        app.tracker.flick_status = {"main": {"reason": "aim"}}
        app.reset_flick_state(None)
        self.assertEqual(app.tracker.flick_status, {})


class TestFlickSpecShared(_UIBase):
    def test_spec_covers_plan_table(self):
        from src.ui_tabs.common import FLICK_SLIDER_SPECS

        keys = {spec[0] for spec in FLICK_SLIDER_SPECS}
        for expected in (
            "flick_gain",
            "flick_settle_ms",
            "flick_max_counts",
            "flick_budget_ms",
            "flick_max_iterations",
            "flick_deadzone_px",
            "flick_switch_radius_px",
        ):
            self.assertIn(expected, keys)

    def test_spec_ranges_match_plan(self):
        from src.ui_tabs.common import spec_for

        gain = spec_for("flick_gain")
        self.assertEqual((gain[2], gain[3]), (0.1, 3.0))
        settle = spec_for("flick_settle_ms")
        self.assertEqual((settle[2], settle[3]), (0.0, 300.0))
        switch = spec_for("flick_switch_radius_px")
        self.assertEqual((switch[2], switch[3]), (16, 256))

    def test_spec_defaults_main_vs_sec(self):
        from src.ui_tabs.common import default_for

        self.assertAlmostEqual(default_for("flick_deadzone_px", False), 1.5)
        self.assertAlmostEqual(default_for("flick_deadzone_px", True), 2.0)
        self.assertAlmostEqual(default_for("flick_budget_ms", False), 240.0)

    def test_channel_key(self):
        from src.ui_tabs.common import channel_key

        self.assertEqual(channel_key("flick_gain", False), "flick_gain")
        self.assertEqual(channel_key("flick_gain", True), "flick_gain_sec")


if __name__ == "__main__":
    unittest.main()
