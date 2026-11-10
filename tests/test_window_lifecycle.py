"""Unit tests for window lifecycle, Win32 restore/minimize, and hotkey debounce (Plan §10.1 / §12.2 T3)."""

import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from tests import test_ui_launcher
except Exception:
    pass

from src.utils import win32_window
from src.utils.config import config
try:
    from src.ui import ViewerApp
except Exception:
    ViewerApp = None


class TestWindowLifecycleBasics(unittest.TestCase):
    def test_bring_to_front_without_hwnd_returns_false(self):
        self.assertFalse(win32_window.bring_to_front(0))

    def test_set_not_topmost_without_hwnd_returns_false(self):
        self.assertFalse(win32_window.set_not_topmost(0))

    def test_clamp_position_in_bounds(self):
        clamped = win32_window.clamp_position("+100+100", 560, 540)
        self.assertIn("+", clamped)

    def test_clamp_position_off_screen_negative(self):
        clamped = win32_window.clamp_position("-99999-99999", 560, 540)
        self.assertTrue(len(clamped) > 0)

    def test_window_map_child_widget_ignored_with_normal_state(self):
        app = MagicMock()
        app._sync_window_style = MagicMock()
        app._ui_rebuilding = False
        app._closing = False
        app.state.return_value = "normal"
        child_widget = MagicMock()

        # Event from a descendant widget inside the window
        event = types.SimpleNamespace(widget=child_widget)
        ViewerApp._on_window_map(app, event)

        # Child map event must be rejected by the widget-identity check
        app._sync_window_style.assert_not_called()

    def test_window_map_root_widget_processed(self):
        app = MagicMock()
        app._sync_window_style = MagicMock()
        app._ui_rebuilding = False
        app._closing = False
        app._minimized = False
        app.state.return_value = "normal"

        event = types.SimpleNamespace(widget=app)
        ViewerApp._on_window_map(app, event)

        app._sync_window_style.assert_called_once()

    def test_window_map_when_rebuilding_ignored(self):
        app = MagicMock()
        app._sync_window_style = MagicMock()
        app._ui_rebuilding = True
        app._closing = False
        app.state.return_value = "normal"

        event = types.SimpleNamespace(widget=app)
        ViewerApp._on_window_map(app, event)

        app._sync_window_style.assert_not_called()

    def test_window_map_when_iconic_state_ignored(self):
        app = MagicMock()
        app._sync_window_style = MagicMock()
        app._ui_rebuilding = False
        app._closing = False
        app.state.return_value = "iconic"

        event = types.SimpleNamespace(widget=app)
        ViewerApp._on_window_map(app, event)

        app._sync_window_style.assert_not_called()

    def test_toggle_ui_visibility_debounce_with_normal_state(self):
        import time
        app = MagicMock()
        app._closing = False
        app._last_toggle_time = time.monotonic()
        app._ui_hidden = False
        app._minimized = False
        app.state.return_value = "normal"
        app._hide_window = MagicMock()
        app._show_window = MagicMock()

        # Calling within debounce period (< 250ms) must be dropped
        ViewerApp._toggle_ui_visibility(app)
        app._hide_window.assert_not_called()
        app._show_window.assert_not_called()

        # Calling after debounce period (>= 250ms, e.g. 300ms ago) must trigger hide
        app._last_toggle_time = time.monotonic() - 0.30
        ViewerApp._toggle_ui_visibility(app)
        app._hide_window.assert_called_once()
        app._show_window.assert_not_called()

    def test_restore_window_state_reset(self):
        app = MagicMock()
        app._closing = False
        app._minimized = True
        app._ui_hidden = True
        app._is_maximized = False
        app._sync_window_style = MagicMock()

        with patch.object(win32_window, "is_available", return_value=False):
            ViewerApp._restore_window(app)
            self.assertFalse(app._minimized)
            self.assertFalse(app._ui_hidden)
            app.deiconify.assert_called_once()
            app._sync_window_style.assert_called_once_with(force=True)

    def test_hide_window_state(self):
        app = MagicMock()
        app._ui_hidden = False
        app._closing = False
        app._launcher = None
        app._save_mode_geometry = MagicMock()
        app.withdraw = MagicMock()

        with patch.object(win32_window, "is_available", return_value=False):
            ViewerApp._hide_window(app)
            self.assertTrue(app._ui_hidden)
            app.withdraw.assert_called_once()
            app._save_mode_geometry.assert_called_once()

    def test_on_minimize_does_not_modify_overrideredirect(self):
        # Crucial fix for RC-2 / L1 / L2: minimizing must never call overrideredirect
        app = MagicMock()
        app._closing = False
        app.overrideredirect = MagicMock()
        config.ui_minimize_to_tray = False

        with patch.object(win32_window, "is_available", return_value=True), \
             patch.object(win32_window, "root_hwnd", return_value=1234), \
             patch.object(win32_window, "minimize", return_value=True):
            ViewerApp._on_minimize(app)
            self.assertTrue(app._minimized)
            app.overrideredirect.assert_not_called()

    def test_on_minimize_to_tray_when_configured(self):
        app = MagicMock()
        app._closing = False
        app._hide_window = MagicMock()
        config.ui_minimize_to_tray = True

        ViewerApp._on_minimize(app)
        app._hide_window.assert_called_once()
        config.ui_minimize_to_tray = False

    def test_on_close_stops_launcher_and_destroys(self):
        app = MagicMock()
        app._closing = False
        mock_launcher = MagicMock()
        app._launcher = mock_launcher
        app._ui_tick_job = 101
        app._config_save_job = 102
        app.after_cancel = MagicMock()
        app.destroy = MagicMock()
        app._save_mode_geometry = MagicMock()

        ViewerApp._on_close(app)

        self.assertTrue(app._closing)
        mock_launcher.stop.assert_called_once()
        self.assertIsNone(app._launcher)
        app.after_cancel.assert_any_call(101)
        app.after_cancel.assert_any_call(102)
        app.destroy.assert_called_once()

    def test_on_close_idempotent(self):
        app = MagicMock()
        app._closing = True
        app._launcher = MagicMock()
        app.destroy = MagicMock()

        ViewerApp._on_close(app)

        # Must exit early without re-invoking cleanup
        app._launcher.stop.assert_not_called()
        app.destroy.assert_not_called()

    def test_sync_window_style_signature_cache(self):
        app = MagicMock()
        app._ui_rebuilding = False
        hwnd = 8888
        exstyle = 0x00040080
        app._window_style_sig = (hwnd, exstyle)

        with patch.object(win32_window, "is_available", return_value=True), \
             patch.object(win32_window, "root_hwnd", return_value=hwnd), \
             patch.object(win32_window, "apply_appwindow", return_value=exstyle), \
             patch.object(win32_window, "refresh_frame") as mock_refresh:
            ViewerApp._sync_window_style(app, force=False)
            mock_refresh.assert_not_called()

            # When force=True, signature match must be bypassed
            ViewerApp._sync_window_style(app, force=True)
            mock_refresh.assert_called_once_with(hwnd)


if __name__ == "__main__":
    unittest.main()
