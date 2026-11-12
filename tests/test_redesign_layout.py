"""Regression tests for the redesign layout invariants.

Covers the two defects found while porting the redesign into src/ui.py:
1. The sidebar declared 210px but allocated 301px, because CTkFrame's
   grid_propagate() is a no-op and the frame grew to fit its packed children.
2. Pages are two columns, so any child wider than its column gets clipped.
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

from src.ui import ViewerApp


class TestRedesignLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("Dark")

    def setUp(self):
        self.app = ViewerApp(tracker=MagicMock(), capture_service=MagicMock())
        self.app.withdraw()
        self.app.geometry("1180x740")
        self.app.update_idletasks()

    def tearDown(self):
        try:
            self.app.destroy()
        except Exception:
            pass

    def test_sidebar_honours_declared_width(self):
        """The sidebar must not grow past its declared width."""
        declared = int(self.app.sidebar.cget("width"))
        actual = self.app.sidebar.winfo_width()
        self.assertEqual(
            declared,
            actual,
            f"Sidebar declared {declared}px but allocated {actual}px; "
            "width is being overridden by its children",
        )

    def test_no_content_is_clipped_on_any_page(self):
        """Every mapped label must get at least the width it asked for."""
        pages = [
            ("Combat", self.app._show_aimbot_tab),
            ("Vision", self.app._show_vision_tab),
            ("Hardware", self.app._show_general_tab),
            ("Profiles", self.app._show_config_tab),
            ("Telemetry", self.app._show_debug_tab),
        ]
        for name, show in pages:
            with self.subTest(page=name):
                show()
                self.app.update_idletasks()
                self.app.update()
                for widget in self._walk(self.app.content_frame):
                    if not isinstance(widget, (ctk.CTkLabel, ctk.CTkButton)):
                        continue
                    if not widget.winfo_ismapped():
                        continue
                    try:
                        text = widget.cget("text")
                    except Exception:
                        continue
                    if not text:
                        continue
                    requested = widget.winfo_reqwidth()
                    actual = widget.winfo_width()
                    self.assertGreaterEqual(
                        actual + 1,
                        requested,
                        f"{name}: {type(widget).__name__} '{text[:30]}' "
                        f"needs {requested}px but has {actual}px",
                    )

    def test_vision_columns_split_evenly(self):
        """Vision is two columns; the split must be even and collapse when HSV hides."""
        from src.utils.config import config
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
        """The title bar heading follows the active page."""
        self.app._show_aimbot_tab()
        self.app.update_idletasks()
        self.assertEqual(self.app.page_title_label.cget("text"), "Main Aimbot")

        self.app._show_debug_tab()
        self.app.update_idletasks()
        self.assertEqual(self.app.page_title_label.cget("text"), "Debug & Telemetry")

    def test_hardware_secondary_cards_use_both_columns(self):
        """Settings / Mouse Lock / Button Mask are cards in the two-column grid.

        They used to be full-width collapsible sections stacked below the grid, so the
        right column stayed half empty. Each card must sit in a column and match it.
        """
        self._open_hardware_page()
        for name in ("card_interface", "card_mouse_lock", "card_button_mask"):
            card = getattr(self.app, name, None)
            self.assertIsNotNone(card, f"{name} missing from the Hardware page")
            self.assertTrue(card.winfo_ismapped(), f"{name} is not mapped")

        left = self.app.card_mouse_api.master
        right = self.app.card_capture_service.master
        self.assertAlmostEqual(left.winfo_width(), right.winfo_width(), delta=2)
        # Both right-column cards must fill that column, not overflow it.
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
        from src.utils.config import config
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

    def _build_hardware_page(self):
        """Build the Hardware page after the serial probe settles.

        A connection-status loop can rebuild this page once the probe ends, which
        destroys the widgets built by the first call.
        """
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
