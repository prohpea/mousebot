import unittest
import sys
import os
from unittest.mock import MagicMock
try:
    import customtkinter as ctk
except Exception:
    ctk = None

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.config import config

class TestSidebar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import _tkinter
            if ctk is None or isinstance(_tkinter, MagicMock) or not hasattr(_tkinter, "__file__"):
                raise unittest.SkipTest("real tkinter unavailable")
            ctk.set_appearance_mode("Dark")
            config.ui_pro_mode = True
        except Exception as exc:
            raise unittest.SkipTest(f"customtkinter unavailable: {exc}")

    def test_sidebar_structure(self):
        from src.ui import ViewerApp
        tracker_mock = MagicMock()
        capture_mock = MagicMock()
        app = ViewerApp(tracker=tracker_mock, capture_service=capture_mock)
        app.withdraw()

        # Check sidebar width
        self.assertGreaterEqual(app.sidebar.cget("width"), 200, "Sidebar should be at least 200px wide")

        # Check master runtime button
        self.assertTrue(hasattr(app, "runtime_btn"), "App should have runtime_btn")
        self.assertEqual(app.runtime_btn.cget("height"), 38, "Runtime button height should be 38 for prominence")

        # Check navigation buttons
        self.assertTrue(hasattr(app, "nav_buttons"))
        self.assertIn("Combat", app.nav_buttons)
        self.assertIn("Vision", app.nav_buttons)
        self.assertIn("Hardware", app.nav_buttons)
        self.assertIn("Profiles", app.nav_buttons)
        self.assertIn("Telemetry", app.nav_buttons)

        # Check active profile widget
        self.assertTrue(hasattr(app, "active_profile_label"), "Sidebar should have active_profile_label")

        app.destroy()

if __name__ == "__main__":
    unittest.main()
