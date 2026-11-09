"""UI scheduler / lock-cache tests (plan 12.2, H1/H2/H11).

The 500 ms connection loop used to call ``_apply_runtime_settings_lock`` which
recursed through the whole widget tree of three hardware frames every tick, even
when the runtime state had not changed. These tests pin the state cache.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class TestRuntimeLockCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import customtkinter as ctk

            ctk.set_appearance_mode("Dark")
        except Exception as exc:  # pragma: no cover
            raise unittest.SkipTest(f"customtkinter unavailable: {exc}")

    def _app(self):
        from src.ui import ViewerApp

        app = ViewerApp(tracker=MagicMock(), capture_service=MagicMock())
        app.withdraw()
        self.addCleanup(app.destroy)
        return app

    def test_second_identical_call_does_not_traverse(self):
        app = self._app()
        app._runtime_active = False
        app._runtime_busy = False
        app._last_runtime_lock_state = None

        calls = {"count": 0}
        original = app._set_widget_tree_enabled

        def counting(widget, enabled):
            calls["count"] += 1
            return original(widget, enabled)

        app._set_widget_tree_enabled = counting

        app._apply_runtime_settings_lock()
        first = calls["count"]
        app._apply_runtime_settings_lock()
        second = calls["count"]

        self.assertEqual(first, second, "second call re-traversed the widget tree")

    def test_state_change_forces_traversal(self):
        app = self._app()
        app._runtime_active = False
        app._runtime_busy = False
        app._last_runtime_lock_state = None

        calls = {"count": 0}
        original = app._set_widget_tree_enabled

        def counting(widget, enabled):
            calls["count"] += 1
            return original(widget, enabled)

        app._set_widget_tree_enabled = counting
        app._apply_runtime_settings_lock()
        before = calls["count"]
        app._runtime_active = True
        app._apply_runtime_settings_lock()
        self.assertGreater(calls["count"], before)

    def test_force_bypasses_cache(self):
        app = self._app()
        app._last_runtime_lock_state = None
        app._apply_runtime_settings_lock()

        calls = {"count": 0}
        original = app._set_widget_tree_enabled

        def counting(widget, enabled):
            calls["count"] += 1
            return original(widget, enabled)

        app._set_widget_tree_enabled = counting
        app._apply_runtime_settings_lock(force=True)
        self.assertGreater(calls["count"], 0)


class TestContentCleanupDropsWidgetRefs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import customtkinter as ctk

            ctk.set_appearance_mode("Dark")
        except Exception as exc:  # pragma: no cover
            raise unittest.SkipTest(f"customtkinter unavailable: {exc}")

    def test_clear_content_removes_debug_widget_refs(self):
        from src.ui import ViewerApp

        app = ViewerApp(tracker=MagicMock(), capture_service=MagicMock())
        app.withdraw()
        self.addCleanup(app.destroy)

        app.debug_log_textbox = MagicMock()
        app._clear_content()
        self.assertFalse(hasattr(app, "debug_log_textbox"))

    def test_clear_content_resets_slider_registry(self):
        from src.ui import ViewerApp

        app = ViewerApp(tracker=MagicMock(), capture_service=MagicMock())
        app.withdraw()
        self.addCleanup(app.destroy)

        app._slider_widgets = {"ghost": {"slider": MagicMock()}}
        app._clear_content()
        self.assertEqual(app._slider_widgets, {})


class TestDebugLogGating(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import customtkinter as ctk

            ctk.set_appearance_mode("Dark")
        except Exception as exc:  # pragma: no cover
            raise unittest.SkipTest(f"customtkinter unavailable: {exc}")

    def test_no_format_when_tab_not_telemetry(self):
        from src.ui import ViewerApp

        app = ViewerApp(tracker=MagicMock(), capture_service=MagicMock())
        app.withdraw()
        self.addCleanup(app.destroy)

        from src.utils.debug_logger import log_print

        log_print("[Test] scheduler gating probe")
        app._active_tab_name = "Main Aimbot"
        app.debug_log_textbox = MagicMock()
        app._debug_log_version = None
        app._update_debug_log()
        app.debug_log_textbox.delete.assert_not_called()

    def test_formats_once_per_version(self):
        from src.ui import ViewerApp

        app = ViewerApp(tracker=MagicMock(), capture_service=MagicMock())
        app.withdraw()
        self.addCleanup(app.destroy)

        from src.utils.debug_logger import log_print

        app._active_tab_name = "Telemetry"
        app.debug_log_textbox = MagicMock()
        app.debug_log_textbox.winfo_exists.return_value = True
        app._debug_log_version = None

        log_print("[Test] debug log render probe")
        app._update_debug_log()
        first = app.debug_log_textbox.delete.call_count
        self.assertGreaterEqual(first, 1)

        # Same log version -> no second reformat.
        app._update_debug_log()
        self.assertEqual(app.debug_log_textbox.delete.call_count, first)


class TestLogVersion(unittest.TestCase):
    def test_log_version_increases(self):
        from src.utils import debug_logger

        before = debug_logger.get_log_version()
        debug_logger.log_print("[Test] version bump")
        after = debug_logger.get_log_version()
        self.assertGreater(after, before)

    def test_clear_bumps_version(self):
        from src.utils import debug_logger

        before = debug_logger.get_log_version()
        debug_logger.clear_logs()
        self.assertGreater(debug_logger.get_log_version(), before)

    def test_move_logging_is_gated(self):
        from src.utils import debug_logger
        from src.utils.config import config

        saved = bool(getattr(config, "flick_telemetry_enabled", False))
        debug_logger.set_move_logging(False)
        config.flick_telemetry_enabled = False
        try:
            before = debug_logger.get_log_count()
            for _ in range(20):
                debug_logger.log_move(1, 1, "Test")
            self.assertEqual(debug_logger.get_log_count(), before)

            config.flick_telemetry_enabled = True
            debug_logger.log_move(1, 1, "Test")
            self.assertGreater(debug_logger.get_log_count(), before)
        finally:
            config.flick_telemetry_enabled = saved
            debug_logger.set_move_logging(False)


if __name__ == "__main__":
    unittest.main()
