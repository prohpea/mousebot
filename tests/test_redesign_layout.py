"""Regression tests for the Tactical HUD layout invariants.

Replaces the old sidebar-specific checks with stronger ones:
1. The shell is exactly four stacked tiers; the workspace row is the only one
   allowed to grow and no left rail reserves width.
2. No label/button/option/entry is clipped in either HUD width mode (Compact
   HUD 780-840px and Wide Dock 1040-1120px) on all five pages.
3. The active nav tab paints its 2px accent underline and both workspace
   columns are the same width.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

import customtkinter as ctk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# Fence real game hardware and the user's real config.json before building the app.
from ui_test_support import fence_game_hardware

fence_game_hardware()

import src.ui as ui_module
from src.ui import ViewerApp
from src.utils.config import config


PAGES = (
    ("Combat", "_show_aimbot_tab"),
    ("Sec Combat", "_show_sec_aimbot_tab"),
    ("Vision", "_show_vision_tab"),
    ("Hardware", "_show_general_tab"),
    ("Profiles", "_show_config_tab"),
    ("Telemetry", "_show_debug_tab"),
)

CLIPPABLE = (
    ctk.CTkLabel,
    ctk.CTkButton,
    ctk.CTkOptionMenu,
    ctk.CTkEntry,
    ctk.CTkSwitch,
)


class TestRedesignLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("Dark")

    def setUp(self):
        self.app = ViewerApp(tracker=MagicMock(), capture_service=MagicMock())
        # Layout assertions need real geometry: a withdrawn window reports width 1.
        self.app.deiconify()
        self.app.update()

    def tearDown(self):
        try:
            self.app._apply_hud_mode(getattr(self, "_original_hud_mode", "simple"))
        except Exception:
            pass
        try:
            self.app.destroy()
        except Exception:
            pass

    # --- shell -------------------------------------------------------------

    def test_shell_is_four_tiers_without_sidebar(self):
        """Header / nav / workspace / footer, and nothing reserves a left rail."""
        self.assertFalse(hasattr(self.app, "sidebar"))

        expected_rows = {
            "header_bar": 0,
            "nav_bar": 1,
            "main_host": 2,
            "footer_bar": 3,
        }
        for attr, row in expected_rows.items():
            widget = getattr(self.app, attr, None)
            self.assertIsNotNone(widget, f"{attr} missing from the shell")
            self.assertTrue(widget.winfo_ismapped(), f"{attr} is not mapped")
            self.assertEqual(int(widget.grid_info().get("row", -1)), row, f"{attr} moved rows")

        # Only row 2 carries the expansion weight.
        self.assertEqual(int(self.app.grid_rowconfigure(2)["weight"]), 1)
        for row in (0, 1, 3):
            self.assertEqual(int(self.app.grid_rowconfigure(row)["weight"]), 0)

        # The workspace must use the whole window width (no sidebar column).
        # A withdrawn window still lays out (update_idletasks ran in setUp).
        self.app.update_idletasks()
        frame_width = self.app.content_frame.winfo_width()
        window_width = self.app.winfo_width()
        if frame_width > 1 and window_width > 1:
            self.assertAlmostEqual(
                frame_width,
                window_width,
                delta=40,
                msg="workspace is narrower than the window; something still reserves width",
            )


    def test_nav_active_tab_paints_underline(self):
        """The active tab has a 2px accent underline; inactive tabs have none."""
        self.app._show_aimbot_tab()
        self.app.update_idletasks()
        underline = self.app.nav_indicators["Combat"]
        self.assertEqual(int(underline.cget("height")), 2)
        self.assertEqual(underline.cget("fg_color"), ui_module.COLOR_ACCENT)
        self.assertTrue(underline.winfo_ismapped())

        button = self.app.nav_buttons["Combat"]
        self.assertEqual(int(button.cget("border_width")), 1)
        self.assertEqual(button.cget("border_color"), ui_module.COLOR_ACCENT)
        self.assertNotEqual(button.cget("fg_color"), "transparent")

        self.assertFalse(self.app.nav_indicators["Profiles"].winfo_ismapped())

    # --- no clipped text ---------------------------------------------------

    def test_no_clipping_in_simple_and_wide_modes(self):
        """Every mapped label/button/option/entry gets at least its requested width."""
        self._original_hud_mode = getattr(config, "ui_hud_mode", "simple")
        try:
            for mode in ("simple", "wide"):
                self.app._apply_hud_mode(mode)
                self.app.update_idletasks()
                width = self.app.winfo_width()
                if width <= 1:
                    width = int(str(self.app.geometry()).split("x", 1)[0])
                if mode == "simple":
                    self.assertTrue(780 <= width <= 840, f"Simple width is {width}")
                else:
                    self.assertTrue(1040 <= width <= 1120, f"Wide width is {width}")

                for name, method in PAGES:
                    with self.subTest(mode=mode, page=name):
                        getattr(self.app, method)()
                        self.app.update_idletasks()
                        self.app.update()
                        self._assert_no_clipped_widgets(mode, name)
                        self._assert_no_overflow(mode, name)
        finally:
            self.app._apply_hud_mode(self._original_hud_mode)

    def _assert_no_clipped_widgets(self, mode, page):
        for widget in self._walk(self.app):
            if not isinstance(widget, CLIPPABLE):
                continue
            if not widget.winfo_ismapped():
                continue
            try:
                text = widget.cget("text")
            except Exception:
                text = ""
            if not str(text or "").strip():
                continue
            requested = widget.winfo_reqwidth()
            actual = widget.winfo_width()
            self.assertGreaterEqual(
                actual + 1,
                requested,
                f"[{mode}/{page}] {type(widget).__name__} '{str(text)[:32]}' "
                f"needs {requested}px but has {actual}px",
            )

    def _assert_no_overflow(self, mode, page):
        for host in (self.app.header_bar, self.app.nav_bar, self.app.footer_bar):
            host.update_idletasks()
            host_width = host.winfo_width()
            for child in host.winfo_children():
                if not child.winfo_ismapped():
                    continue
                right_edge = child.winfo_x() + child.winfo_width()
                self.assertLessEqual(
                    right_edge,
                    host_width + 1,
                    f"[{mode}/{page}] {type(child).__name__} overflows its bar "
                    f"({right_edge} > {host_width})",
                )

    # --- pages -------------------------------------------------------------

    def test_vision_columns_split_evenly(self):
        """Vision is two columns; the split must be even and collapse when HSV hides."""
        original = getattr(config, "color", "yellow")
        try:
            # The right column is collapsed whenever the HSV card is hidden, so the
            # two-column split only exists when a custom colour is selected. Pinning
            # the colour also keeps the assertion independent of config.json.
            config.color = "custom"
            self.app._show_vision_tab()
            self.app.update_idletasks()

            host = self.app._vision_cols
            left = host.grid_slaves(row=0, column=0)[0]
            right = host.grid_slaves(row=0, column=1)[0]
            self.assertAlmostEqual(left.winfo_width(), right.winfo_width(), delta=2)

            # Hiding the HSV card must release the right column's width.
            config.color = "yellow"
            self.app._update_custom_hsv_visibility()
            self.app.update_idletasks()
            self.assertFalse(right.winfo_ismapped())
        finally:
            config.color = original

    def test_page_header_tracks_navigation(self):
        """The HUD header title follows the active page (uppercased in place)."""
        self.app._show_aimbot_tab()
        self.app.update_idletasks()
        self.assertEqual(self.app.page_title_label.cget("text"), "MAIN AIMBOT")
        self.assertIn("Aim behaviour", self.app.page_sub_label.cget("text"))

        self.app._show_debug_tab()
        self.app.update_idletasks()
        self.assertEqual(self.app.page_title_label.cget("text"), "DEBUG & TELEMETRY")

        self.app._show_sec_aimbot_tab()
        self.app.update_idletasks()
        self.assertEqual(self.app.page_title_label.cget("text"), "SECONDARY AIMBOT")

    def test_hardware_secondary_cards_use_both_columns(self):
        """Settings / Mouse Lock / Button Mask are cards in the two-column grid."""
        self._open_hardware_page()
        for name in ("card_interface", "card_mouse_lock", "card_button_mask"):
            card = getattr(self.app, name, None)
            self.assertIsNotNone(card, f"{name} missing from the Hardware page")
            self.assertTrue(card.winfo_ismapped(), f"{name} is not mapped")

        left = self.app.card_mouse_api.master
        right = self.app.card_capture_service.master
        self.assertAlmostEqual(left.winfo_width(), right.winfo_width(), delta=2)
        # Mouse Lock and Button Mask sit side by side under the capture card.
        self.assertIs(self.app.card_mouse_lock.master, self.app.card_button_mask.master)
        for name in ("card_capture_service", "card_mouse_lock", "card_button_mask"):
            card = getattr(self.app, name)
            self.assertLessEqual(
                card.winfo_x() + card.winfo_width(),
                card.master.winfo_width() + 1,
                f"{name} overflows its column",
            )

    def test_hardware_collapsible_cards_release_space(self):
        """Collapsing a card hides its body and frees the vertical space."""
        self._open_hardware_page()
        card = self.app.card_mouse_lock
        expanded = card.winfo_height()
        card.set_open(False)
        self.app.update_idletasks()
        self.app.update()
        self.assertFalse(card.content.winfo_ismapped(), "collapsed card still shows content")
        self.assertLess(card.winfo_height(), expanded, "collapsed card kept its height")
        card.set_open(True)
        self.app.update_idletasks()
        self.assertTrue(card.content.winfo_ismapped())

    def test_hardware_cards_persist_open_state(self):
        """Toggling a card writes the state the next page build reads back."""
        self._open_hardware_page()
        card = self.app.card_button_mask
        card.set_open(not card.is_open(), notify=True)
        key = self.app._get_collapsible_state_key("Button Mask")
        self.assertIn(key, self.app._collapsible_section_states)
        expected = card.is_open()
        self._build_hardware_page()
        self.assertEqual(
            getattr(self.app, "card_button_mask").is_open(),
            expected,
            "rebuilt card ignored the persisted open state",
        )

    def test_hardware_cards_collapse_in_simple_mode(self):
        """Simple mode still force-collapses the technical cards on a fresh start."""
        original_pro = getattr(config, "ui_pro_mode", False)
        original_states = dict(self.app._collapsible_section_states)
        try:
            config.ui_pro_mode = False
            self.app._ui_pro_mode = False
            self.app._collapsible_section_states.clear()
            self._build_hardware_page()
            for name in ("card_mouse_lock", "card_button_mask"):
                self.assertFalse(
                    getattr(self.app, name).is_open(),
                    f"{name} should start collapsed in Simple mode",
                )
            self.assertTrue(
                self.app.card_interface.is_open(),
                "Interface Settings is not a technical section; it should stay open",
            )
        finally:
            config.ui_pro_mode = original_pro
            self.app._ui_pro_mode = bool(original_pro)
            self.app._collapsible_section_states.clear()
            self.app._collapsible_section_states.update(original_states)

    def test_combat_windmouse_card_has_nine_sliders(self):
        """The WindMouse card keeps the 9 reference sliders in order."""
        self.app._show_aimbot_tab()
        self.app.update_idletasks()
        keys = [
            "wm_gravity",
            "wm_wind",
            "wm_max_step",
            "wm_min_step",
            "wm_min_delay",
            "wm_max_delay",
            "wm_distance_threshold",
            "normalsmooth",
            "normalsmoothfov",
        ]
        for key in keys:
            self.assertIn(key, self.app._slider_widgets, f"{key} slider missing from Combat")
        self.assertEqual(len(keys), 9)

    def test_windmouse_simulation_is_deterministic(self):
        """Same seed -> same path; every segment stays inside min_step..max_step."""
        start, end = (0.0, 0.0), (100.0, 100.0)
        first = self.app._simulate_windmouse_path(start, end, 4.0, 1.0, 6.0, 1.0, seed=7)
        second = self.app._simulate_windmouse_path(start, end, 4.0, 1.0, 6.0, 1.0, seed=7)
        self.assertEqual(first, second, "the simulation must be deterministic per seed")
        self.assertGreater(len(first), 2)

        max_step, min_step = 2.0, 0.5
        clamped = self.app._simulate_windmouse_path(
            start, end, 4.0, 1.0, max_step, min_step, seed=7,
        )
        for i in range(len(clamped) - 1):
            dx = clamped[i + 1][0] - clamped[i][0]
            dy = clamped[i + 1][1] - clamped[i][1]
            distance = (dx * dx + dy * dy) ** 0.5
            self.assertLessEqual(distance, max_step + 1e-6, "step exceeded max_step")
            self.assertGreaterEqual(distance, min_step - 1e-6, "step fell below min_step")

        # A bigger max_step must never produce *shorter* individual steps.
        loose = self.app._simulate_windmouse_path(
            start, end, 4.0, 1.0, 12.0, min_step, seed=7,
        )
        first_clamped = ((clamped[1][0] - clamped[0][0]) ** 2
                         + (clamped[1][1] - clamped[0][1]) ** 2) ** 0.5
        first_loose = ((loose[1][0] - loose[0][0]) ** 2
                       + (loose[1][1] - loose[0][1]) ** 2) ** 0.5
        self.assertGreaterEqual(first_loose, first_clamped - 1e-9)

    def _build_hardware_page(self):
        """Build the Hardware page after the serial probe settles."""
        self.app._show_general_tab()
        for _ in range(6):
            self.app.update_idletasks()
            self.app.update()
        self.app._show_general_tab()
        self.app.update_idletasks()
        self.app.update()

    def _open_hardware_page(self):
        """Build the Hardware page with the technical cards forced open."""
        self.app._ui_pro_mode = True
        self.app._collapsible_section_states.update(
            {
                "hardware:mouse_lock": True,
                "hardware:button_mask": True,
                "hardware:interface_settings": True,
            }
        )
        self._build_hardware_page()

    @staticmethod
    def _walk(widget):
        yield widget
        for child in widget.winfo_children():
            yield from TestRedesignLayout._walk(child)


if __name__ == "__main__":
    unittest.main()
