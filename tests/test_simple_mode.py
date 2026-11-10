"""Unit tests for Simple mode layout, behavior, and callbacks (Plan §10.1 / §12.2 T2 / Reviewer Round 4)."""

import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from tests import test_ui_launcher
except Exception:
    pass

from src.utils.config import config
try:
    from src.ui import ViewerApp
except Exception:
    ViewerApp = None


class TestSimpleDashboardPureLogic(unittest.TestCase):
    """Tests for constants, budgets, formatting and row logic (no Tk root required)."""

    def test_widget_budget_limit(self):
        from src.ui_modes.simple_dashboard import SIMPLE_WIDGET_BUDGET
        self.assertLessEqual(SIMPLE_WIDGET_BUDGET, 150)

    def test_default_mode_options(self):
        from src.ui_modes.simple_dashboard import _DEFAULT_MODE_OPTIONS
        self.assertIn("Normal", _DEFAULT_MODE_OPTIONS)
        self.assertIn("Flick", _DEFAULT_MODE_OPTIONS)
        self.assertIn("WindMouse", _DEFAULT_MODE_OPTIONS)

    def test_slider_row_format_float(self):
        from src.ui_modes.simple_dashboard import SimpleSliderRow
        row = object.__new__(SimpleSliderRow)
        row.is_float = True
        self.assertEqual(row._format(1.234), "1.23")
        self.assertEqual(row._format(0.5), "0.50")

    def test_slider_row_format_int(self):
        from src.ui_modes.simple_dashboard import SimpleSliderRow
        row = object.__new__(SimpleSliderRow)
        row.is_float = False
        self.assertEqual(row._format(15.7), "16")
        self.assertEqual(row._format(10.0), "10")

    def test_slider_row_clamp_on_moved(self):
        from src.ui_modes.simple_dashboard import SimpleSliderRow
        row = object.__new__(SimpleSliderRow)
        row.is_float = True
        row.min_val = 0.1
        row.max_val = 20.0
        row.value_lbl = MagicMock()
        row.command = MagicMock()

        row._on_moved(25.0)  # Beyond max
        self.assertEqual(row._value, 20.0)
        row.command.assert_called_once_with(20.0)

    def test_slider_row_set_display_updates_widget(self):
        from src.ui_modes.simple_dashboard import SimpleSliderRow
        row = object.__new__(SimpleSliderRow)
        row.is_float = False
        row.min_val = 1
        row.max_val = 100
        row.slider = MagicMock()
        row.value_lbl = MagicMock()
        row.command = MagicMock()

        row.set_display(42)
        self.assertEqual(row._value, 42.0)
        row.slider.set.assert_called_once_with(42.0)
        row.command.assert_not_called()  # Must not re-trigger callback


class TestSimpleModeCallbacks(unittest.TestCase):
    """Behavioral tests for Simple mode's real methods on ViewerApp."""

    def setUp(self):
        if ViewerApp is None:
            raise unittest.SkipTest("ViewerApp/Tk unavailable in headless environment")
        self._saved_config = dict(config.to_dict())

    def tearDown(self):
        if hasattr(self, "_saved_config"):
            for k, v in self._saved_config.items():
                setattr(config, k, v)

    def test_quick_trigger_changed_updates_config_and_tracker(self):
        app = MagicMock()
        app.tracker = MagicMock()
        var_trigger = MagicMock()
        var_trigger.get.return_value = True
        app.var_enabletb_quick = var_trigger

        ViewerApp._on_quick_trigger_changed(app)

        self.assertTrue(config.enabletb)
        self.assertTrue(app.tracker.enabletb)

    def test_quick_rcs_changed_updates_config_and_tracker(self):
        app = MagicMock()
        app.tracker = MagicMock()
        var_rcs = MagicMock()
        var_rcs.get.return_value = True
        app.var_enablercs = var_rcs

        ViewerApp._on_enablercs_changed(app)

        self.assertTrue(config.enablercs)
        self.assertTrue(app.tracker.enablercs)

    def test_mode_selected_in_simple_refreshes_dashboard_without_rebuilding_tab(self):
        app = MagicMock()
        app._simple_mode = True
        app.tracker = MagicMock()
        app._aim_mode_display_to_value = lambda x: x
        app._reset_aim_state_after_mode_change = MagicMock()
        app._show_aimbot_tab = MagicMock()

        with patch("src.ui_modes.simple_dashboard.refresh_simple_dashboard") as mock_refresh:
            ViewerApp._on_mode_selected(app, "WindMouse")

            self.assertEqual(config.mode, "WindMouse")
            self.assertEqual(app.tracker.mode, "WindMouse")
            app._reset_aim_state_after_mode_change.assert_called_once_with(is_sec=False)
            mock_refresh.assert_called_once_with(app, {"mode"})
            # In Simple mode, _show_aimbot_tab must NEVER be called
            app._show_aimbot_tab.assert_not_called()

    def test_mode_sec_selected_in_simple_refreshes_dashboard_without_rebuilding_tab(self):
        app = MagicMock()
        app._simple_mode = True
        app.tracker = MagicMock()
        app._aim_mode_display_to_value = lambda x: x
        app._reset_aim_state_after_mode_change = MagicMock()
        app._show_sec_aimbot_tab = MagicMock()

        with patch("src.ui_modes.simple_dashboard.refresh_simple_dashboard") as mock_refresh:
            ViewerApp._on_mode_sec_selected(app, "Flick")

            self.assertEqual(config.mode_sec, "Flick")
            self.assertEqual(app.tracker.mode_sec, "Flick")
            app._reset_aim_state_after_mode_change.assert_called_once_with(is_sec=True)
            mock_refresh.assert_called_once_with(app, {"mode_sec"})
            app._show_sec_aimbot_tab.assert_not_called()

    def test_refresh_simple_dashboard_skips_when_not_simple(self):
        app = MagicMock()
        app._simple_mode = False
        with patch("src.ui_modes.simple_dashboard.refresh_simple_dashboard") as mock_refresh:
            ViewerApp.refresh_simple_dashboard(app)
            mock_refresh.assert_not_called()

    def test_refresh_simple_dashboard_toggles_speed_and_gain_for_normal_mode(self):
        from src.ui_modes.simple_dashboard import refresh_simple_dashboard
        app = MagicMock()
        app._simple_mode = True
        app._option_widgets = {}
        app._slider_widgets = {}
        app._aim_mode_display_to_value = lambda x: x
        app.simple_sec_gain_row = MagicMock()
        app.simple_sec_speed_row = MagicMock()

        config.mode_sec = "Normal"
        refresh_simple_dashboard(app, {"mode_sec"})

        app.simple_sec_gain_row.grid_remove.assert_called_once()
        app.simple_sec_speed_row.grid.assert_called_once()

    def test_refresh_simple_dashboard_toggles_speed_and_gain_for_flick_mode(self):
        from src.ui_modes.simple_dashboard import refresh_simple_dashboard
        app = MagicMock()
        app._simple_mode = True
        app._option_widgets = {}
        app._slider_widgets = {}
        app._aim_mode_display_to_value = lambda x: x
        app.simple_sec_gain_row = MagicMock()
        app.simple_sec_speed_row = MagicMock()

        config.mode_sec = "Flick"
        refresh_simple_dashboard(app, {"mode_sec"})

        app.simple_sec_speed_row.grid_remove.assert_called_once()
        app.simple_sec_gain_row.grid.assert_called_once()

    def test_load_initial_config_in_simple_mode(self):
        app = MagicMock()
        app._simple_mode = True
        app._sync_config_to_tracker = MagicMock()
        app.refresh_simple_dashboard = MagicMock()
        app._handle_nav_click = MagicMock()

        ViewerApp._load_initial_config(app)

        app._sync_config_to_tracker.assert_called_once()
        app.refresh_simple_dashboard.assert_called_once()
        app._handle_nav_click.assert_not_called()

    def test_build_simple_layout_contract(self):
        app = MagicMock()
        app._simple_mode = True
        app.content_frame = MagicMock()
        app._apply_simple_geometry = MagicMock()
        app._register_window_events = MagicMock()
        app._bind_edge_resizing = MagicMock()

        with patch("src.ui_modes.simple_dashboard.build_simple_dashboard") as mock_build:
            ViewerApp._build_simple_layout(app)
            mock_build.assert_called_once_with(app, app.content_frame)
            app._apply_simple_geometry.assert_called_once()

    def test_apply_simple_geometry_geometry_call(self):
        app = MagicMock()
        app.resizable = MagicMock()
        app.geometry = MagicMock()
        config.ui_simple_position = "+150+200"

        with patch("src.utils.win32_window.clamp_position", return_value="+150+200"):
            ViewerApp._apply_simple_geometry(app)

            app.resizable.assert_called_once_with(False, False)
            app.geometry.assert_called_once_with("560x540+150+200")

    def test_simple_profile_names_lists_configs(self):
        app = MagicMock()
        app._config_display_name_from_filename = lambda f: f.replace(".json", "")
        with patch("os.path.isdir", return_value=True), \
             patch("os.listdir", return_value=["cfg1.json", "cfg2.json", "readme.txt"]):
            names = ViewerApp._simple_profile_names(app)
            self.assertIn("cfg1", names)
            self.assertIn("cfg2", names)
            self.assertNotIn("readme.txt", names)

    def test_select_current_profile_matches_active_config(self):
        from src.ui_modes.simple_dashboard import _select_current_profile
        app = MagicMock()
        app._current_profile_name.return_value = "valorant_v1"
        app.simple_profile_option = MagicMock()

        _select_current_profile(app)
        app.simple_profile_option.set.assert_called_once_with("valorant_v1")


class TestSimpleModeRealTk(unittest.TestCase):
    """Integration test when GUI is available (skipped gracefully on headless CI)."""

    @classmethod
    def setUpClass(cls):
        try:
            import _tkinter
            if isinstance(_tkinter, MagicMock) or not hasattr(_tkinter, "__file__"):
                raise unittest.SkipTest("real tkinter unavailable")
            import customtkinter as ctk
            ctk.set_appearance_mode("Dark")
        except Exception as exc:
            raise unittest.SkipTest(f"customtkinter unavailable: {exc}")

    def test_boot_respects_simple_mode_in_real_gui(self):
        config.ui_pro_mode = False
        app = ViewerApp(MagicMock(), MagicMock(), ui_mode="simple")
        app.withdraw()
        self.addCleanup(app.destroy)
        self.assertEqual(app._ui_mode, "simple")
        self.assertFalse(hasattr(app, "sidebar"))


if __name__ == "__main__":
    unittest.main()
