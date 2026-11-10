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

class TestTitleBar(unittest.TestCase):
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

    def test_title_bar_pills(self):
        from src.ui import ViewerApp
        tracker_mock = MagicMock()
        capture_mock = MagicMock()
        app = ViewerApp(tracker=tracker_mock, capture_service=capture_mock)
        app.withdraw()

        # Check telemetry pills exist in title bar
        self.assertTrue(hasattr(app, "pill_fps"), "Title bar should have pill_fps")
        self.assertTrue(hasattr(app, "pill_delay"), "Title bar should have pill_delay")
        self.assertTrue(hasattr(app, "pill_hardware"), "Title bar should have pill_hardware")

        # Test telemetry update
        app.pill_fps.update_value("120 FPS", dot_color="#10B981")
        self.assertIn("120", app.pill_fps.value_text)

        app.pill_delay.update_value("0.8 ms", dot_color="#06B6D4")
        self.assertIn("0.8", app.pill_delay.value_text)

        app.destroy()

if __name__ == "__main__":
    unittest.main()
