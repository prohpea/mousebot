import os
import sys
import unittest
import customtkinter as ctk

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.ui import THEME_PRESETS
from src.utils.config import config


class TestThemePresets(unittest.TestCase):
    def test_theme_presets_structure(self):
        required_keys = {
            "COLOR_BG",
            "COLOR_SIDEBAR",
            "COLOR_SURFACE",
            "COLOR_ACCENT",
            "COLOR_ACCENT_HOVER",
            "COLOR_TEXT",
            "COLOR_TEXT_DIM",
            "COLOR_BORDER",
            "COLOR_DANGER",
            "COLOR_SUCCESS",
            "COLOR_WARNING",
            "COLOR_NAV_ACTIVE_BG",
            "COLOR_NAV_HOVER_BG",
            "COLOR_MENU_GHOST",
            "FONT_MAIN",
            "FONT_BOLD",
            "FONT_TITLE",
        }
        for theme_name, theme_dict in THEME_PRESETS.items():
            for key in required_keys:
                self.assertIn(
                    key,
                    theme_dict,
                    f"Theme '{theme_name}' is missing required key '{key}'",
                )

    def test_customtkinter_json_themes(self):
        themes_dir = os.path.join(PROJECT_ROOT, "themes")
        for theme_file in ["nord.json", "emerald.json", "dracula.json", "ocean.json"]:
            path = os.path.join(themes_dir, theme_file)
            self.assertTrue(os.path.exists(path), f"Theme file {theme_file} does not exist")
            # Should not raise exception
            ctk.ThemeManager.load_theme(path)


if __name__ == "__main__":
    unittest.main()
