import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import customtkinter as ctk
except Exception:
    ctk = None

class TestThemePresets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import _tkinter
            from unittest.mock import MagicMock
            if ctk is None or isinstance(_tkinter, MagicMock) or not hasattr(_tkinter, "__file__"):
                raise unittest.SkipTest("real tkinter unavailable")
        except Exception as exc:
            raise unittest.SkipTest(f"customtkinter unavailable: {exc}")

    def test_theme_presets_structure(self):
        from src.ui import THEME_PRESETS
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
        if ctk is None:
            raise unittest.SkipTest("customtkinter unavailable")
        themes_dir = os.path.join(PROJECT_ROOT, "themes")
        for theme_file in ["nord.json", "emerald.json", "dracula.json", "ocean.json"]:
            path = os.path.join(themes_dir, theme_file)
            self.assertTrue(os.path.exists(path), f"Theme file {theme_file} does not exist")
            # Should not raise exception
            ctk.ThemeManager.load_theme(path)


if __name__ == "__main__":
    unittest.main()
