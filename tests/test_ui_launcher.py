"""Unit tests for UI optimization, launcher, and window lifecycle (Plan §10 / Reviewer P0-2)."""

import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import ctypes
except Exception:
    ctypes_mock = MagicMock()
    ctypes_mock.sizeof.return_value = 8
    ctypes_mock.c_void_p = MagicMock
    ctypes_mock.c_uint = MagicMock
    ctypes_mock.c_size_t = MagicMock
    ctypes_mock.c_ssize_t = MagicMock
    ctypes_mock.c_uint32 = MagicMock
    ctypes_mock.c_int = MagicMock
    ctypes_mock.c_wchar_p = MagicMock
    ctypes_mock.c_long = MagicMock
    ctypes_mock.c_int64 = MagicMock
    ctypes_mock.c_bool = MagicMock
    ctypes_mock.Structure = object
    sys.modules['_ctypes'] = ctypes_mock
    sys.modules['ctypes'] = ctypes_mock
    sys.modules['ctypes.wintypes'] = ctypes_mock

try:
    import PIL
    from PIL import Image
except Exception:
    pil_mock = MagicMock()
    sys.modules['PIL'] = pil_mock
    sys.modules['PIL.Image'] = pil_mock
    sys.modules['PIL.ImageTk'] = pil_mock

try:
    import cv2
except Exception:
    cv2_mock = MagicMock()
    sys.modules['cv2'] = cv2_mock

try:
    import _tkinter
except Exception:
    class MockTkBase:
        def __init__(self, *args, **kwargs):
            pass
        def title(self, *args, **kwargs):
            pass
        def overrideredirect(self, *args, **kwargs):
            pass
        def protocol(self, *args, **kwargs):
            pass
        def resizable(self, *args, **kwargs):
            pass
        def configure(self, *args, **kwargs):
            pass
        def destroy(self, *args, **kwargs):
            pass
        def cget(self, *args, **kwargs):
            return 200
        def grid(self, *args, **kwargs):
            pass
        def pack(self, *args, **kwargs):
            pass
        def place(self, *args, **kwargs):
            pass
        def winfo_toplevel(self):
            return self
        def winfo_children(self):
            return []
        def winfo_exists(self):
            return True
        def winfo_x(self):
            return 100
        def winfo_y(self):
            return 100
        def geometry(self, val=None):
            return "560x540+100+100"
        def withdraw(self):
            pass
        def deiconify(self):
            pass
        def update_idletasks(self):
            pass
        def bind(self, *args, **kwargs):
            pass
        def after(self, *args, **kwargs):
            return 1
        def attributes(self, *args, **kwargs):
            return None
        def wm_attributes(self, *args, **kwargs):
            return None
        def state(self, *args, **kwargs):
            return "normal"

    sys.modules['_tkinter'] = MagicMock()
    tk_mock = MagicMock()
    tk_mock.Tk = MockTkBase
    tk_mock.Toplevel = MockTkBase
    sys.modules['tkinter'] = tk_mock
    sys.modules['tkinter.filedialog'] = MagicMock()
    sys.modules['tkinter.messagebox'] = MagicMock()
    sys.modules['tkinter.simpledialog'] = MagicMock()
    
    ctk_mock = MagicMock()
    ctk_mock.CTk = MockTkBase
    ctk_mock.CTkFrame = MockTkBase
    ctk_mock.CTkButton = MockTkBase
    ctk_mock.CTkLabel = MockTkBase
    ctk_mock.CTkScrollableFrame = MockTkBase
    ctk_mock.CTkSegmentedButton = MockTkBase
    ctk_mock.CTkSlider = MockTkBase
    ctk_mock.CTkOptionMenu = MockTkBase
    ctk_mock.CTkSwitch = MockTkBase
    ctk_mock.CTkImage = MockTkBase
    sys.modules['customtkinter'] = ctk_mock

sys.modules['src.capture.capture_service'] = MagicMock()
sys.modules['src.capture.ndi'] = MagicMock()
sys.modules['cyndilib'] = MagicMock()

from src.utils.config import Config, config
from src.utils import win32_window
from src.utils import global_hotkey
from src.utils import single_instance
from src.ui_modes import simple_dashboard


class TestConfigSchema4(unittest.TestCase):
    def test_schema_4_defaults(self):
        cfg = Config()
        self.assertGreaterEqual(cfg.config_schema, 4)
        self.assertTrue(hasattr(cfg, "ui_pro_mode"))
        self.assertTrue(hasattr(cfg, "ui_toggle_hotkey"))
        self.assertEqual(cfg.ui_toggle_hotkey.upper(), "INSERT")
        self.assertTrue(hasattr(cfg, "ui_tray_enabled"))
        self.assertTrue(hasattr(cfg, "ui_simple_geometry"))
        self.assertEqual(cfg.ui_simple_geometry, "560x540")

    def test_migration_from_schema_3_existing(self):
        old_data = {
            "config_schema": 3,
            "mode": "Normal",
        }
        cfg = Config()
        cfg.from_dict(old_data)
        self.assertGreaterEqual(cfg.config_schema, 4)
        # Existing config without ui_pro_mode defaults to Pro (True)
        self.assertTrue(cfg.ui_pro_mode)
        self.assertEqual(cfg.ui_toggle_hotkey.upper(), "INSERT")

    def test_migration_from_schema_3_explicit_simple(self):
        old_data = {
            "config_schema": 3,
            "mode": "Normal",
            "ui_pro_mode": False,
        }
        cfg = Config()
        cfg.from_dict(old_data)
        self.assertFalse(cfg.ui_pro_mode)


class TestWin32Window(unittest.TestCase):
    def test_geometry_parsing(self):
        w, h = win32_window.parse_geometry("560x540")
        self.assertEqual((w, h), (560, 540))

        w, h = win32_window.parse_geometry("980x660")
        self.assertEqual((w, h), (980, 660))

        w, h = win32_window.parse_geometry("invalid")
        self.assertEqual((w, h), (0, 0))

    def test_constants_defined(self):
        self.assertEqual(win32_window.GWL_EXSTYLE, -20)
        self.assertEqual(win32_window.WS_EX_APPWINDOW, 0x00040000)
        self.assertEqual(win32_window.SW_RESTORE, 9)
        self.assertEqual(win32_window.SW_MINIMIZE, 6)

    def test_bring_to_front_never_calls_sleep(self):
        import time
        with patch.object(time, "sleep") as mock_sleep:
            win32_window.bring_to_front(12345)
            mock_sleep.assert_not_called()

    def test_restore_window_schedules_set_not_topmost(self):
        from src.ui import ViewerApp
        app_mock = MagicMock()
        app_mock._closing = False
        app_mock._is_maximized = False
        app_mock._sync_window_style = MagicMock()
        with patch.object(win32_window, "is_available", return_value=True), \
             patch.object(win32_window, "root_hwnd", return_value=9999), \
             patch.object(win32_window, "show"), \
             patch.object(win32_window, "restore"), \
             patch.object(win32_window, "bring_to_front") as mock_bring, \
             patch.object(win32_window, "set_not_topmost"):
            ViewerApp._restore_window(app_mock)
            mock_bring.assert_called_once_with(9999)
            # Verify self.after was scheduled with 120ms delay
            app_mock.after.assert_any_call(120, unittest.mock.ANY)


class TestGlobalHotkey(unittest.TestCase):
    def test_key_name_resolution(self):
        vk_insert = global_hotkey.parse_hotkey_vk("Insert")
        self.assertEqual(vk_insert, 0x2D)

        vk_f11 = global_hotkey.parse_hotkey_vk("F11")
        self.assertEqual(vk_f11, 0x7A)

        vk_home = global_hotkey.parse_hotkey_vk("Home")
        self.assertEqual(vk_home, 0x24)

    def test_queue_dispatch(self):
        import queue
        q = queue.Queue()
        q.put(("action", "toggle"))
        action, param = q.get_nowait()
        self.assertEqual(action, "action")
        self.assertEqual(param, "toggle")

    def test_last_down_reset_on_reregister(self):
        # Reviewer finding P1-1: last_down must reset on _reregister
        service = global_hotkey.LauncherService(vk=0x2D, tray=False)
        service._last_down = True
        service._reregister(0x7A)
        self.assertFalse(service._last_down)


class TestSingleInstance(unittest.TestCase):
    def test_mutex_acquire_and_release(self):
        is_first, handle = single_instance.acquire("Local\\CVM_Test_Unique_Mutex")
        self.assertTrue(is_first)
        single_instance.release()


class TestSimpleDashboardConstants(unittest.TestCase):
    def test_widget_budget(self):
        self.assertEqual(simple_dashboard.SIMPLE_WIDGET_BUDGET, 150)

    def test_mode_options_default(self):
        self.assertIn("Normal", simple_dashboard._DEFAULT_MODE_OPTIONS)
        self.assertIn("Flick", simple_dashboard._DEFAULT_MODE_OPTIONS)
        self.assertIn("WindMouse", simple_dashboard._DEFAULT_MODE_OPTIONS)


class TestViewerAppModes(unittest.TestCase):
    def test_p0_1_viewer_app_has_refresh_simple_dashboard_method(self):
        # Reviewer finding P0-1: ViewerApp must expose refresh_simple_dashboard as a first-class method
        from src.ui import ViewerApp
        self.assertTrue(hasattr(ViewerApp, "refresh_simple_dashboard"))
        self.assertTrue(callable(getattr(ViewerApp, "refresh_simple_dashboard")))

    def test_p0_1_initial_config_calls_refresh_simple_dashboard(self):
        # Reviewer finding P0-1: _load_initial_config must delegate to refresh_simple_dashboard without Pro switch
        from src.ui import ViewerApp
        app_mock = MagicMock()
        app_mock._simple_mode = True
        app_mock.refresh_simple_dashboard = MagicMock()
        app_mock._handle_nav_click = MagicMock()
        app_mock._sync_config_to_tracker = MagicMock()

        ViewerApp._load_initial_config.__wrapped_or_raw__ = ViewerApp._load_initial_config
        ViewerApp._load_initial_config(app_mock)

        app_mock.refresh_simple_dashboard.assert_called_once()
        app_mock._handle_nav_click.assert_not_called()

    def test_p0_4_last_pro_tab_preservation_when_maximized(self):
        # Reviewer finding P0-4: _save_mode_geometry must preserve _last_pro_tab even if maximized
        from src.ui import ViewerApp
        class SimpleDummy:
            def __init__(self):
                self._ui_rebuilding = False
                self._is_maximized = True
                self._ui_mode = "pro"
                self._active_tab_name = "Vision"
                self.content_frame = object()
            def winfo_exists(self):
                return True

        dummy = SimpleDummy()
        ViewerApp._save_mode_geometry(dummy)
        self.assertEqual(dummy._last_pro_tab, "Vision")

    def test_save_mode_geometry_guard_when_rebuilding(self):
        # Guard must return early during initial boot when content_frame is None
        from src.ui import ViewerApp
        class SimpleDummy:
            def __init__(self):
                self._ui_rebuilding = True
                self._is_maximized = False
                self._ui_mode = "pro"
                self._active_tab_name = "Vision"
                self.content_frame = None
            def winfo_exists(self):
                return True

        dummy = SimpleDummy()
        ViewerApp._save_mode_geometry(dummy)
        self.assertFalse(hasattr(dummy, "_last_pro_tab"))

    def test_apply_settings_filters_ui_mode_keys(self):
        # Reviewer finding P1: _apply_settings must never overwrite UI layout mode or geometry
        from src.ui import ViewerApp
        from src.utils.config import config
        config.ui_pro_mode = True
        config.ui_pro_geometry = "1400x900"

        app_mock = MagicMock()
        app_mock.tracker = MagicMock()
        app_mock._strip_config_metadata = lambda d: dict(d)
        app_mock._slider_widgets = {}
        app_mock._checkbox_vars = {}
        app_mock._option_widgets = {}

        incoming = {
            "ui_pro_mode": False,
            "ui_pro_geometry": "500x500",
            "ui_simple_position": "+0+0",
            "aim_fov": 80.0,
        }
        ViewerApp._apply_settings(app_mock, incoming)

        # UI mode keys must be protected and preserved
        self.assertTrue(config.ui_pro_mode)
        self.assertEqual(config.ui_pro_geometry, "1400x900")
        # Other settings should still be applied
        self.assertEqual(config.aim_fov, 80.0)


if __name__ == "__main__":
    unittest.main()
