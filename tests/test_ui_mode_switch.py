"""Unit tests for UI mode switching state transitions and contracts (Plan §10.1 / §12.2 T5 / Reviewer Round 4)."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.config import config
from src.ui import ViewerApp


class TestUIModeSwitchStateMachine(unittest.TestCase):
    def test_save_mode_geometry_skips_when_content_frame_is_none(self):
        # Initial boot protection
        app = MagicMock()
        app.winfo_exists.return_value = True
        app.content_frame = None

        config.ui_pro_geometry = "1200x800"
        ViewerApp._save_mode_geometry(app)

        # Must not overwrite config with "1x1" or default
        self.assertEqual(config.ui_pro_geometry, "1200x800")

    def test_save_mode_geometry_validates_min_pro_dimensions(self):
        app = MagicMock()
        app.winfo_exists.return_value = True
        app.content_frame = object()
        app._ui_mode = "pro"
        app._is_maximized = False
        app.geometry.return_value = "100x100+0+0"

        config.ui_pro_geometry = "1200x800"
        ViewerApp._save_mode_geometry(app)

        # Discard invalid dimension 100x100 < 900x600
        self.assertEqual(config.ui_pro_geometry, "1200x800")

    def test_save_mode_geometry_persists_valid_pro_dimensions(self):
        app = MagicMock()
        app.winfo_exists.return_value = True
        app.content_frame = object()
        app._ui_mode = "pro"
        app._is_maximized = False
        app.geometry.return_value = "1400x900+50+50"

        ViewerApp._save_mode_geometry(app)
        self.assertEqual(config.ui_pro_geometry, "1400x900")

    def test_tab_preserved_when_maximized(self):
        app = MagicMock()
        app.winfo_exists.return_value = True
        app.content_frame = object()
        app._ui_mode = "pro"
        app._active_tab_name = "Hardware & Capture"
        app._is_maximized = True

        ViewerApp._save_mode_geometry(app)
        self.assertEqual(app._last_pro_tab, "Hardware & Capture")

    def test_apply_ui_mode_idempotent_when_same_mode(self):
        app = MagicMock()
        app._ui_mode = "pro"
        app.content_frame = object()
        app._save_mode_geometry = MagicMock()

        # Switching to same mode when content_frame already exists is a no-op
        ViewerApp._apply_ui_mode(app, "pro", rebuild=True)
        app._save_mode_geometry.assert_not_called()

    def test_ensure_pro_mode_switches_from_simple(self):
        app = MagicMock()
        app._ui_mode = "simple"
        app._apply_ui_mode = MagicMock()

        ret = ViewerApp._ensure_pro_mode(app, initial_tab="Vision")
        self.assertTrue(ret)
        app._apply_ui_mode.assert_called_once_with("pro", rebuild=True, persist=True, initial_tab="Vision")

    def test_ensure_pro_mode_noop_when_already_pro(self):
        app = MagicMock()
        app._ui_mode = "pro"
        app._apply_ui_mode = MagicMock()

        ret = ViewerApp._ensure_pro_mode(app)
        self.assertFalse(ret)
        app._apply_ui_mode.assert_not_called()

    def test_enter_simple_mode_helper(self):
        app = MagicMock()
        app._apply_ui_mode = MagicMock()

        ViewerApp._enter_simple_mode(app, rebuild=True, persist=False)
        app._apply_ui_mode.assert_called_once_with("simple", rebuild=True, persist=False)

    def test_enter_pro_mode_helper(self):
        app = MagicMock()
        app._apply_ui_mode = MagicMock()

        ViewerApp._enter_pro_mode(app, rebuild=False, persist=True)
        app._apply_ui_mode.assert_called_once_with("pro", rebuild=False, persist=True)

    def test_teardown_layout_drops_references_cleanly(self):
        class DummyApp:
            def __init__(self):
                self.content_frame = object()
                self.sidebar = object()
                self.runtime_btn = object()
                self._slider_widgets = {"test": 1}
                self._option_widgets = {"test": 2}
            def _cancel_binding_capture(self):
                pass
            def _cancel_pid_preview(self):
                pass
            def _drop_config_caches(self):
                pass

        app = DummyApp()
        ViewerApp._teardown_layout(app)

        self.assertFalse(hasattr(app, "content_frame"))
        self.assertFalse(hasattr(app, "sidebar"))
        self.assertFalse(hasattr(app, "runtime_btn"))
        self.assertEqual(app._slider_widgets, {})
        self.assertEqual(app._option_widgets, {})

    def test_mode_switch_preserves_runtime_active_state(self):
        app = MagicMock()
        app._runtime_active = True
        app._ui_mode = "simple"
        app.content_frame = object()
        app._teardown_layout = MagicMock()
        app._build_pro_layout = MagicMock()
        app._save_mode_geometry = MagicMock()
        app._cancel_binding_capture = MagicMock()
        app._cancel_pid_preview = MagicMock()
        app._refresh_runtime_button = MagicMock()
        app.update_idletasks = MagicMock()
        app._sync_window_style = MagicMock()

        ViewerApp._apply_ui_mode(app, "pro", rebuild=True)

        self.assertEqual(app._ui_mode, "pro")
        self.assertTrue(app._runtime_active)

    def test_twenty_cycles_mode_switch_no_leak(self):
        # Plan §12.2 T5 Core: 20 round-trip mode switches
        app = MagicMock()
        app._ui_mode = "pro"
        app.content_frame = object()
        app._teardown_layout = MagicMock()
        app._build_pro_layout = MagicMock()
        app._build_simple_layout = MagicMock()
        app._save_mode_geometry = MagicMock()
        app._cancel_binding_capture = MagicMock()
        app._cancel_pid_preview = MagicMock()
        app._refresh_runtime_button = MagicMock()
        app.update_idletasks = MagicMock()
        app._sync_window_style = MagicMock()

        for cycle in range(20):
            # Pro -> Simple
            ViewerApp._apply_ui_mode(app, "simple", rebuild=True, persist=False)
            self.assertEqual(app._ui_mode, "simple")
            # Simple -> Pro
            ViewerApp._apply_ui_mode(app, "pro", rebuild=True, persist=False)
            self.assertEqual(app._ui_mode, "pro")

        # Verify teardown was invoked exactly 40 times (clean destruction every switch)
        self.assertEqual(app._teardown_layout.call_count, 40)
        self.assertEqual(app._save_mode_geometry.call_count, 40)


if __name__ == "__main__":
    unittest.main()
