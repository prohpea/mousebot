import unittest
import sys
import os
from unittest.mock import MagicMock
import customtkinter as ctk

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ui import ViewerApp
from src.utils.config import config

class TestCombatTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("Dark")

    def test_combat_tab_cards(self):
        tracker_mock = MagicMock()
        capture_mock = MagicMock()
        app = ViewerApp(tracker=tracker_mock, capture_service=capture_mock)
        app.withdraw()
        app._show_aimbot_tab()

        self.assertEqual(app._active_tab_name, "Main Aimbot")

        # Verify 4 modern cards exist on Combat tab
        self.assertTrue(hasattr(app, "card_targeting"), "Combat tab should have card_targeting")
        self.assertTrue(hasattr(app, "card_windmouse"), "Combat tab should have card_windmouse")
        self.assertTrue(hasattr(app, "card_speeds"), "Combat tab should have card_speeds")
        self.assertTrue(hasattr(app, "card_humanization"), "Combat tab should have card_humanization")

        # Test FOV slider update syncs to config
        app._on_fovsize_changed(35)
        self.assertEqual(config.fovsize, 35)

        # Test Secondary Aimbot tab
        app._show_sec_aimbot_tab()
        self.assertEqual(app._active_tab_name, "Sec Aimbot")
        self.assertTrue(hasattr(app, "card_targeting_sec"))
        self.assertTrue(hasattr(app, "card_windmouse_sec"))

        app.destroy()

    def test_sens_dpi_persistence_on_close(self):
        tracker_mock = MagicMock()
        tracker_mock.in_game_sens = 0.235
        tracker_mock.mouse_dpi = 800
        capture_mock = MagicMock()
        app = ViewerApp(tracker=tracker_mock, capture_service=capture_mock)
        app.withdraw()
        app._show_aimbot_tab()

        # Wait for initial timers
        app.update()

        # Simulate user typing new sens and pressing Enter
        app.sens_entry.delete(0, "end")
        app.sens_entry.insert(0, "0.65")
        app.sens_entry._entry.focus_set()
        app.sens_entry._entry.event_generate("<Return>")
        app.update()
        self.assertEqual(config.in_game_sens, 0.65)

        # Close app and verify config is not overwritten by tracker
        app._on_close()
        self.assertEqual(config.in_game_sens, 0.65)

        # Restore default
        config.in_game_sens = 0.235
        config.save_to_file()

if __name__ == "__main__":
    unittest.main()
