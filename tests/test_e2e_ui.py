import unittest
import sys
import os
from unittest.mock import MagicMock
import customtkinter as ctk

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ui import ViewerApp
from src.utils.config import config
from src.utils.i18n import i18n

class TestE2EUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("Dark")

    def test_e2e_ui_workflow(self):
        tracker_mock = MagicMock()
        capture_mock = MagicMock()
        app = ViewerApp(tracker=tracker_mock, capture_service=capture_mock)
        app.withdraw()

        # 1. Test language switch to Vietnamese
        app._on_language_changed("Tiếng Việt")
        self.assertEqual(i18n.language, "vi", "i18n language should be set to 'vi'")
        
        # Test language switch back to English
        app._on_language_changed("English")
        self.assertEqual(i18n.language, "en", "i18n language should be set to 'en'")

        # 2. Test Pro/Simple mode toggle
        initial_mode = app._ui_pro_mode
        app._toggle_pro_mode()
        self.assertNotEqual(app._ui_pro_mode, initial_mode, "Pro mode should be toggled")
        app._toggle_pro_mode()
        self.assertEqual(app._ui_pro_mode, initial_mode, "Pro mode should be restored")

        # 3. Test geometry constraints
        app.update_idletasks()
        req_width = app.winfo_reqwidth()
        width = app.winfo_width()
        self.assertTrue(width >= 960 or req_width >= 960, f"Window width ({width}) or reqwidth ({req_width}) should be >= 960")

        # 4. Test 5-Pillar Navigation across all tabs
        app._show_aimbot_tab()
        self.assertEqual(app._active_tab_name, "Main Aimbot")
        self.assertTrue(hasattr(app, "card_targeting"))

        app._show_sec_aimbot_tab()
        self.assertEqual(app._active_tab_name, "Sec Aimbot")
        self.assertTrue(hasattr(app, "card_targeting_sec"))

        app._show_vision_tab()
        self.assertEqual(app._active_tab_name, "Vision")
        self.assertTrue(hasattr(app, "card_color_preset"))
        self.assertTrue(hasattr(app, "card_hsv_tuning"))

        app._show_general_tab()
        self.assertEqual(app._active_tab_name, "Hardware")
        self.assertTrue(hasattr(app, "card_mouse_api"))
        self.assertTrue(hasattr(app, "card_capture_service"))

        app._show_config_tab()
        self.assertEqual(app._active_tab_name, "Profiles")
        self.assertTrue(hasattr(app, "card_profile_manager"))

        app._show_debug_tab()
        self.assertEqual(app._active_tab_name, "Telemetry")
        self.assertTrue(hasattr(app, "card_mouse_monitor"))
        self.assertTrue(hasattr(app, "card_system_logs"))

        # 5. Test Status Pills
        self.assertTrue(hasattr(app, "pill_fps"))
        self.assertTrue(hasattr(app, "pill_delay"))
        self.assertTrue(hasattr(app, "pill_hardware"))

        # 6. Test Master Runtime Engine Button
        self.assertTrue(hasattr(app, "runtime_btn"))
        self.assertEqual(app.runtime_btn.cget("height"), 38)

        app.destroy()

if __name__ == "__main__":
    unittest.main()
