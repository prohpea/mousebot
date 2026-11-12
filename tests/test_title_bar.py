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

class TestTitleBar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("Dark")

    def test_title_bar_pills(self):
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
