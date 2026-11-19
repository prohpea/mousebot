"""Shell regression tests for the Tactical HUD Top-Nav architecture.

The left 210px sidebar is gone; the shell is now four stacked tiers:
header (#06090f) -> nav & power bar (#080c14) -> workspace (#0b0f17) -> footer
(#06090f). These assertions replace the old "sidebar is >= 200px wide" check with
stricter ones: no sidebar at all, every tier mapped, the five nav tabs grouped
ENGINE / PLATFORM, and a right-hand dock whose ENGINE button drives the real
runtime.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

import customtkinter as ctk

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# Fence real game hardware and the user's real config.json before building the app.
from ui_test_support import fence_game_hardware

fence_game_hardware()

from src.ui import ViewerApp
from src.utils.config import config


class TestSidebar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("Dark")

    def _build(self):
        # HUD captions are localized; pin English so assertions are deterministic
        # regardless of the language stored in the developer's config.json.
        from src.utils.i18n import i18n

        previous_language = i18n.language
        config.language = i18n.set_language("en")
        self.addCleanup(lambda: config.__setattr__("language", i18n.set_language(previous_language)))

        app = ViewerApp(tracker=MagicMock(), capture_service=MagicMock())
        # Height/width and ismapped assertions need real geometry.
        app.deiconify()
        app.update()
        self.addCleanup(lambda: self._safe_destroy(app))
        return app

    @staticmethod
    def _safe_destroy(app):
        try:
            app.destroy()
        except Exception:
            pass

    @staticmethod
    def _hud_width(app):
        """Allocated width, falling back to the requested geometry for withdrawn windows."""
        width = int(app.winfo_width())
        if width > 1:
            return width
        try:
            return int(str(app.geometry()).split("x", 1)[0])
        except Exception:
            return width

    def test_left_sidebar_is_gone(self):
        """The HUD must not allocate any left rail: the workspace spans the width."""
        app = self._build()
        self.assertFalse(
            hasattr(app, "sidebar"),
            "ViewerApp still exposes a left sidebar; the HUD uses a top nav bar",
        )
        for attr in ("header_bar", "nav_bar", "content_frame", "footer_bar"):
            widget = getattr(app, attr, None)
            self.assertIsNotNone(widget, f"{attr} missing from the HUD shell")
            self.assertTrue(widget.winfo_exists(), f"{attr} was destroyed")
        self.assertEqual(int(app.header_bar.grid_info().get("row", -1)), 0)
        self.assertEqual(int(app.nav_bar.grid_info().get("row", -1)), 1)
        self.assertEqual(int(app.main_host.grid_info().get("row", -1)), 2)
        self.assertEqual(int(app.footer_bar.grid_info().get("row", -1)), 3)
        # Only the workspace row may grow.
        self.assertEqual(int(app.grid_rowconfigure(2)["weight"]), 1)
        for row in (0, 1, 3):
            self.assertEqual(int(app.grid_rowconfigure(row)["weight"]), 0)

    def test_header_carries_brand_pills_mode_and_window_controls(self):
        app = self._build()
        import src.ui as ui_module

        self.assertEqual(app.header_bar.cget("fg_color"), ui_module.COLOR_HUD_HEADER)
        self.assertEqual(app.hud_brand_badge.cget("text"), "CVM")
        self.assertEqual(app.brand_label.cget("text"), "COLORBOT")
        self.assertEqual(app.brand_sep_label.cget("text"), "//")
        self.assertTrue(app.version_lbl.cget("text").startswith("v"))
        self.assertIn("--", app.pill_fps.value_text)

        for pill, label in (
            (app.pill_fps, "FPS"),
            (app.pill_delay, "PING"),
            (app.pill_hardware, "HW"),
        ):
            self.assertEqual(pill.label_prefix, label)

        self.assertEqual(app.hud_mode_btn.cget("text"), "Simple")
        window_texts = [
            btn.cget("text")
            for btn in (app.minimize_btn, app.maximize_btn, app.close_btn)
        ]
        self.assertEqual(window_texts, ["_", "[]", "X"])

    def test_nav_bar_tabs_groups_and_active_state(self):
        app = self._build()
        import src.ui as ui_module

        self.assertEqual(app.nav_bar.cget("fg_color"), ui_module.COLOR_HUD_NAV)

        for name in ("Combat", "Vision", "Hardware", "Profiles", "Telemetry"):
            self.assertIn(name, app.nav_buttons, f"{name} tab missing from the nav bar")
        # Legacy aliases must keep pointing at a live tab.
        for alias in ("Main Aimbot", "Sec Aimbot", "General", "Config", "Debug"):
            self.assertIn(alias, app.nav_buttons)

        self.assertEqual(app.nav_group_labels["ENGINE"].cget("text"), "ENGINE")
        self.assertEqual(app.nav_group_labels["PLATFORM"].cget("text"), "PLATFORM")

        app._show_aimbot_tab()
        app.update_idletasks()

        combat = app.nav_buttons["Combat"]
        self.assertEqual(int(combat.cget("border_width")), 1)
        self.assertEqual(combat.cget("border_color"), ui_module.COLOR_ACCENT)
        self.assertEqual(combat.cget("text_color"), "#FFFFFF")

        underline = app.nav_indicators["Combat"]
        self.assertEqual(int(underline.cget("height")), 2)
        self.assertTrue(underline.winfo_ismapped(), "active tab has no underline")
        self.assertFalse(
            app.nav_indicators["Vision"].winfo_ismapped(),
            "inactive tab must not paint an underline",
        )

        app._show_vision_tab()
        app.update_idletasks()
        self.assertTrue(app.nav_indicators["Vision"].winfo_ismapped())
        self.assertFalse(app.nav_indicators["Combat"].winfo_ismapped())

    def test_right_dock_has_profile_settings_and_engine(self):
        app = self._build()
        self.assertIn("CFG", app.cfg_pill.winfo_children()[0].cget("text").upper())
        self.assertTrue(app.active_profile_label.cget("text"))

        self.assertTrue(callable(app.settings_btn.cget("command")))
        self.assertNotEqual(str(app.settings_btn.cget("command")).strip(), "")

        self.assertIn("START ENGINE", app.runtime_btn.cget("text"))
        self.assertEqual(int(app.runtime_btn.cget("height")), 20)

        called = []
        original = app._toggle_runtime
        app._toggle_runtime = lambda: called.append(True)
        app.runtime_btn.invoke()
        app._toggle_runtime = original
        self.assertTrue(called, "START ENGINE must call _toggle_runtime")

    def test_runtime_state_repaints_engine_button_and_footer(self):
        app = self._build()
        app._runtime_active = True
        app._runtime_busy = False
        app._refresh_runtime_button()
        self.assertIn("STOP ENGINE", app.runtime_btn.cget("text"))
        self.assertEqual(app.runtime_btn.cget("fg_color"), "#FF2A5F")
        self.assertIn("RUNNING", app.footer_state_label.cget("text"))

        app._runtime_active = False
        app._refresh_runtime_button()
        self.assertIn("START ENGINE", app.runtime_btn.cget("text"))
        self.assertIn("READY", app.footer_state_label.cget("text"))

    def test_footer_shows_real_status_hotkey_and_udp(self):
        app = self._build()
        from src.ui import BUTTONS

        self.assertIn("READY", app.footer_state_label.cget("text"))
        self.assertIn(
            str(BUTTONS[int(config.selected_mouse_button)]).upper(),
            app.footer_hotkey_label.cget("text"),
        )
        self.assertIn(
            f"{config.udp_ip}:{config.udp_port}",
            app.footer_udp_label.cget("text"),
        )
        self.assertIn("English", app.lang_btn.cget("text"))
        self.assertIn("Dark", app.theme_btn.cget("text"))
        self.assertIn("Emerald", app.accent_btn.cget("text"))

    def test_hud_mode_toggle_switches_geometry_and_saves(self):
        app = self._build()
        original = getattr(config, "ui_hud_mode", "simple")
        try:
            app._apply_hud_mode("simple")
            app.update_idletasks()
            width = self._hud_width(app)
            self.assertTrue(780 <= width <= 840, f"Simple HUD width is {width}")
            self.assertFalse(app.nav_group_labels["ENGINE"].winfo_ismapped())
            self.assertFalse(app.cfg_pill.winfo_ismapped())

            app._toggle_hud_mode()
            app.update_idletasks()
            width = self._hud_width(app)
            self.assertTrue(1040 <= width <= 1120, f"Wide HUD width is {width}")

            self.assertTrue(app.nav_group_labels["ENGINE"].winfo_ismapped())
            self.assertTrue(app.cfg_pill.winfo_ismapped())
            self.assertEqual(config.ui_hud_mode, "wide")
            self.assertEqual(app.hud_mode_btn.cget("text"), "Wide")
        finally:
            config.ui_hud_mode = original
            app._apply_hud_mode(original)

    def test_hud_config_fields_round_trip_and_clamp(self):
        """ui_hud_mode / ui_accent / ui_theme_variant persist and self-heal."""
        from src.utils.config import Config

        original = (
            getattr(config, "ui_hud_mode", "simple"),
            getattr(config, "ui_accent", "emerald"),
            getattr(config, "ui_theme_variant", "dark"),
        )
        try:
            config.ui_hud_mode = "wide"
            config.ui_accent = "crimson"
            config.ui_theme_variant = "midnight"
            payload = config.to_dict()
            for key in ("ui_hud_mode", "ui_accent", "ui_theme_variant"):
                self.assertIn(key, payload, f"{key} missing from config.to_dict()")

            # Build a Config without touching config.json: from_dict() only sets attrs.
            clone = Config.__new__(Config)
            clone.__dict__.update(config.__dict__)
            clone.from_dict(payload)
            self.assertEqual(clone.ui_hud_mode, "wide")
            self.assertEqual(clone.ui_accent, "crimson")
            self.assertEqual(clone.ui_theme_variant, "midnight")

            # Garbage values must normalize instead of raising.
            clone.from_dict({
                "ui_hud_mode": "gigantic",
                "ui_accent": "pink",
                "ui_theme_variant": "noon",
            })
            self.assertEqual(clone.ui_hud_mode, "simple")
            self.assertEqual(clone.ui_accent, "emerald")
            self.assertEqual(clone.ui_theme_variant, "dark")
        finally:
            (config.ui_hud_mode, config.ui_accent, config.ui_theme_variant) = original

    def test_accent_cycle_matches_reference_palette(self):
        app = self._build()
        import src.ui as ui_module

        original = getattr(config, "ui_accent", "emerald")
        try:
            config.ui_accent = "emerald"
            seen = []
            for expected in ("cyan", "amber", "crimson", "emerald"):
                app._cycle_accent()
                app.update_idletasks()
                seen.append(config.ui_accent)
                self.assertEqual(config.ui_accent, expected)
                # The live palette must follow the cycle, not just the config field.
                self.assertEqual(
                    ui_module.ACCENT_PRESETS[config.ui_accent]["accent"],
                    ui_module.COLOR_ACCENT,
                )
                self.assertEqual(
                    ui_module.ui_components.get_token("COLOR_ACCENT"),
                    ui_module.ACCENT_PRESETS[config.ui_accent]["accent"],
                )
                self.assertEqual(
                    app.accent_btn.cget("text").lower(),
                    config.ui_accent,
                )
            self.assertEqual(list(seen), ["cyan", "amber", "crimson", "emerald"])
        finally:
            config.ui_accent = original
            ui_module._apply_theme_preset(
                app._ui_theme,
                accent=original,
                variant=getattr(config, "ui_theme_variant", "dark"),
            )
            app._rebuild_layout_for_ui_style()


if __name__ == "__main__":
    unittest.main()
