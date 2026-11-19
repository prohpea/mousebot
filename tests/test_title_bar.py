"""HUD telemetry pill contract.

The pills moved from the old title bar into the tactical header, but their public
contract is unchanged: `label_prefix`, `value_text`, `dot`, `update_value()`.
`HudPill` is the HUD name for the same widget, so both names must stay in sync.
"""
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
from src.ui_components import HudPill, StatusPill


class TestTitleBar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("Dark")

    def test_title_bar_pills(self):
        app = ViewerApp(tracker=MagicMock(), capture_service=MagicMock())
        app.withdraw()

        # Check telemetry pills exist in the tactical header
        self.assertTrue(hasattr(app, "pill_fps"), "Header should have pill_fps")
        self.assertTrue(hasattr(app, "pill_delay"), "Header should have pill_delay")
        self.assertTrue(hasattr(app, "pill_hardware"), "Header should have pill_hardware")

        # Test telemetry update
        app.pill_fps.update_value("120", dot_color="#10B981")
        self.assertIn("120", app.pill_fps.value_text)

        app.pill_delay.update_value("0.8 ms", dot_color="#06B6D4")
        self.assertIn("0.8", app.pill_delay.value_text)

        app.destroy()

    def test_hud_pill_alias_and_dot(self):
        """HudPill is the same widget as StatusPill and keeps a recolorable dot."""
        self.assertIs(HudPill, StatusPill)
        root = ctk.CTk()
        root.withdraw()
        try:
            pill = HudPill(root, "FPS", "--", dot_color="#10B981")
            self.assertEqual(pill.label_prefix, "FPS")
            self.assertEqual(pill.value_text, "--")
            self.assertEqual(pill.dot.cget("text_color"), "#10B981")

            pill.update_value("240", dot_color="#FF2A5F")
            self.assertEqual(pill.value_text, "240")
            self.assertEqual(pill.dot.cget("text_color"), "#FF2A5F")
            self.assertIn("240", pill.text_label.cget("text"))

            pill.set_dot_color("#00E5FF")
            self.assertEqual(pill.dot.cget("text_color"), "#00E5FF")
        finally:
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
