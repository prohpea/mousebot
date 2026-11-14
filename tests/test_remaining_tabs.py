import unittest
import sys
import os
from unittest.mock import MagicMock
import customtkinter as ctk

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# Fence real game hardware and the user's real config.json before building the app.
from ui_test_support import fence_game_hardware

fence_game_hardware()

from src.ui import ViewerApp

class TestRemainingTabs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("Dark")

    def test_remaining_tabs_cards(self):
        tracker_mock = MagicMock()
        capture_mock = MagicMock()
        app = ViewerApp(tracker=tracker_mock, capture_service=capture_mock)
        app.withdraw()

        # 1. Vision tab
        app._show_vision_tab()
        self.assertEqual(app._active_tab_name, "Vision")
        self.assertTrue(hasattr(app, "card_color_preset"), "Vision tab should have card_color_preset")
        self.assertTrue(hasattr(app, "card_hsv_tuning"), "Vision tab should have card_hsv_tuning")
        merge_slider = app._slider_widgets.get("detection_merge_distance")
        self.assertIsNotNone(merge_slider, "Vision tab should register detection_merge_distance slider")
        self.assertEqual((merge_slider["min"], merge_slider["max"]), (0, 18))
        self.assertEqual(app.settings_btn.winfo_manager(), "pack", "Sidebar Settings button should be visible")
        self.assertIn("show_opencv_windows", app._checkbox_vars)
        from src.utils.config import config as _cfg
        prev_opencv = bool(getattr(_cfg, "show_opencv_windows", True))
        try:
            app.var_show_opencv_windows.set(not prev_opencv)
            app._on_show_opencv_windows_changed()
            self.assertEqual(_cfg.show_opencv_windows, not prev_opencv)
        finally:
            _cfg.show_opencv_windows = prev_opencv

        # 2. Hardware tab
        app._show_general_tab()
        self.assertEqual(app._active_tab_name, "Hardware")
        self.assertTrue(hasattr(app, "card_mouse_api"), "Hardware tab should have card_mouse_api")
        self.assertTrue(hasattr(app, "card_capture_service"), "Hardware tab should have card_capture_service")

        # 3. Profiles tab
        app._show_config_tab()
        self.assertEqual(app._active_tab_name, "Profiles")
        self.assertTrue(hasattr(app, "card_profile_manager"), "Profiles tab should have card_profile_manager")

        # 4. Telemetry tab
        app._show_debug_tab()
        self.assertEqual(app._active_tab_name, "Telemetry")
        self.assertTrue(hasattr(app, "card_mouse_monitor"), "Telemetry tab should have card_mouse_monitor")
        self.assertTrue(hasattr(app, "card_system_logs"), "Telemetry tab should have card_system_logs")

        app.destroy()

if __name__ == "__main__":
    unittest.main()
