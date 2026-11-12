import os
import sys
import unittest
import customtkinter as ctk

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import ui_components
from src.ui import THEME_PRESETS
from src.utils.config import config


THEME_TOKEN_KEYS = {
    "COLOR_CARD",
    "COLOR_CARD_BORDER",
    "COLOR_CARD_HEADER",
    "COLOR_INPUT",
    "COLOR_ACCENT_2",
    "COLOR_BADGE_BG",
}
EXPECTED_THEME_KEY_COUNT = 23


def _relative_luminance(hex_color):
    """WCAG 2.x relative luminance of a #RRGGBB color."""
    hex_color = str(hex_color).lstrip("#")
    channels = []
    for offset in (0, 2, 4):
        srgb = int(hex_color[offset:offset + 2], 16) / 255.0
        if srgb <= 0.03928:
            channels.append(srgb / 12.92)
        else:
            channels.append(((srgb + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast_ratio(hex_a, hex_b):
    """WCAG contrast ratio between two #RRGGBB colors."""
    lum_a = _relative_luminance(hex_a)
    lum_b = _relative_luminance(hex_b)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


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

    def test_all_themes_have_theme_tokens(self):
        for theme_name, theme_dict in THEME_PRESETS.items():
            self.assertEqual(
                len(theme_dict),
                EXPECTED_THEME_KEY_COUNT,
                f"Theme '{theme_name}' should have {EXPECTED_THEME_KEY_COUNT} keys, "
                f"got {len(theme_dict)}",
            )
            for key in THEME_TOKEN_KEYS:
                self.assertIn(
                    key,
                    theme_dict,
                    f"Theme '{theme_name}' is missing theme token '{key}'",
                )
        tactical = THEME_PRESETS["tactical"]
        self.assertEqual(tactical["COLOR_ACCENT"], "#F59E0B")
        self.assertEqual(tactical["COLOR_ACCENT_2"], "#22D3EE")
        for font_key in ("FONT_MAIN", "FONT_BOLD", "FONT_TITLE"):
            self.assertTrue(
                str(tactical[font_key][0]).startswith("Consolas"),
                f"tactical '{font_key}' should use Consolas",
            )

    def test_apply_theme_updates_ui_components(self):
        saved = dict(ui_components._TOKENS)
        self.addCleanup(lambda: ui_components._TOKENS.update(saved))
        tactical = THEME_PRESETS["tactical"]
        ui_components.apply_theme(tactical)
        self.assertEqual(
            ui_components.get_token("COLOR_CARD"),
            tactical["COLOR_CARD"],
        )

    def test_card_bg_contrast(self):
        for theme_name, theme_dict in THEME_PRESETS.items():
            ratio = _contrast_ratio(theme_dict["COLOR_CARD"], theme_dict["COLOR_BG"])
            self.assertGreaterEqual(
                ratio,
                1.5,
                f"Theme '{theme_name}' card/bg contrast is {ratio:.2f}:1, below 1.5:1",
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
