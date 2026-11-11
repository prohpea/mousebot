import unittest
import sys
import os
from unittest.mock import MagicMock
import customtkinter as ctk

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
