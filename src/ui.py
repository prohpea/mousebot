"""
UI 模組 - Ultra Minimalist 風格
處理主視窗、分頁內容與設定互動 (GUI layer)

Two real layouts live behind one state machine (plan §4):

* ``simple`` — ``src/ui_modes/simple_dashboard.py``: 560x540, no sidebar, no
  scrollable frame, no canvas, no tooltip.
* ``pro``    — the historical layout below: 5-pillar sidebar + scrollable content
  + every advanced tab, kept byte-for-byte in behaviour.
"""
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import ctypes
from ctypes import wintypes
import os
import json
import queue
import cv2
import threading
import time
import webbrowser
from PIL import Image

from src.utils.config import config
from src.capture.capture_service import CaptureService
from src.utils.mouse_input import MouseInputMonitor
from src.utils.debug_logger import (
    get_recent_logs,
    clear_logs,
    get_log_count,
    get_log_version,
    log_print,
)
from src.utils.mouse.keycodes import to_vk_code
from src.utils.updater import get_update_checker
from src.ui_hsv_preview import HsvPreviewWindow
from src.utils.i18n import heading, i18n, t
from src.version import get_engine_badge, get_version_label
from src.ui_components import ModernCard, ModernSwitch, StatusPill
from src.utils import win32_window
from src.utils import single_instance
from src.utils.global_hotkey import LauncherService, parse_hotkey_vk

# --- Theme constants (Nord, Emerald, Dracula, Ocean, Neon, Classic) ---
THEME_PRESETS = {
    "nord": {
        "COLOR_BG": "#242933",
        "COLOR_SIDEBAR": "#1F232A",
        "COLOR_SURFACE": "#2E3440",
        "COLOR_ACCENT": "#88C0D0",
        "COLOR_ACCENT_HOVER": "#8FBCBB",
        "COLOR_TEXT": "#ECEFF4",
        "COLOR_TEXT_DIM": "#9CAEC4",
        "COLOR_BORDER": "#434C5E",
        "COLOR_DANGER": "#BF616A",
        "COLOR_SUCCESS": "#A3BE8C",
        "COLOR_WARNING": "#EBCB8B",
        "COLOR_NAV_ACTIVE_BG": "#3B4252",
        "COLOR_NAV_HOVER_BG": "#353B49",
        "COLOR_MENU_GHOST": "#616E85",
        "FONT_MAIN": ("Segoe UI", 11),
        "FONT_BOLD": ("Segoe UI", 11, "bold"),
        "FONT_TITLE": ("Segoe UI", 18, "bold"),
    },
    "emerald": {
        "COLOR_BG": "#0B0E14",
        "COLOR_SIDEBAR": "#070A0F",
        "COLOR_SURFACE": "#121721",
        "COLOR_ACCENT": "#10B981",
        "COLOR_ACCENT_HOVER": "#34D399",
        "COLOR_TEXT": "#F1F5F9",
        "COLOR_TEXT_DIM": "#94A3B8",
        "COLOR_BORDER": "#1E2638",
        "COLOR_DANGER": "#F43F5E",
        "COLOR_SUCCESS": "#10B981",
        "COLOR_WARNING": "#FBBF24",
        "COLOR_NAV_ACTIVE_BG": "#162232",
        "COLOR_NAV_HOVER_BG": "#131C28",
        "COLOR_MENU_GHOST": "#64748B",
        "FONT_MAIN": ("Segoe UI", 11),
        "FONT_BOLD": ("Segoe UI", 11, "bold"),
        "FONT_TITLE": ("Segoe UI", 18, "bold"),
    },
    "dracula": {
        "COLOR_BG": "#1E1F29",
        "COLOR_SIDEBAR": "#181920",
        "COLOR_SURFACE": "#282A36",
        "COLOR_ACCENT": "#BD93F9",
        "COLOR_ACCENT_HOVER": "#FF79C6",
        "COLOR_TEXT": "#F8F8F2",
        "COLOR_TEXT_DIM": "#95A4D0",
        "COLOR_BORDER": "#44475A",
        "COLOR_DANGER": "#FF5555",
        "COLOR_SUCCESS": "#50FA7B",
        "COLOR_WARNING": "#F1FA8C",
        "COLOR_NAV_ACTIVE_BG": "#38314F",
        "COLOR_NAV_HOVER_BG": "#2D2F3F",
        "COLOR_MENU_GHOST": "#6272A4",
        "FONT_MAIN": ("Segoe UI", 11),
        "FONT_BOLD": ("Segoe UI", 11, "bold"),
        "FONT_TITLE": ("Segoe UI", 18, "bold"),
    },
    "ocean": {
        "COLOR_BG": "#0B132B",
        "COLOR_SIDEBAR": "#070D1F",
        "COLOR_SURFACE": "#1C2541",
        "COLOR_ACCENT": "#48CAE4",
        "COLOR_ACCENT_HOVER": "#90E0EF",
        "COLOR_TEXT": "#EDF2F4",
        "COLOR_TEXT_DIM": "#7B93B2",
        "COLOR_BORDER": "#3A506B",
        "COLOR_DANGER": "#EF476F",
        "COLOR_SUCCESS": "#06D6A0",
        "COLOR_WARNING": "#FFD166",
        "COLOR_NAV_ACTIVE_BG": "#1B3B54",
        "COLOR_NAV_HOVER_BG": "#132238",
        "COLOR_MENU_GHOST": "#5A738E",
        "FONT_MAIN": ("Segoe UI", 11),
        "FONT_BOLD": ("Segoe UI", 11, "bold"),
        "FONT_TITLE": ("Segoe UI", 18, "bold"),
    },
    "neon": {
        "COLOR_BG": "#040B16",
        "COLOR_SIDEBAR": "#030A14",
        "COLOR_SURFACE": "#061325",
        "COLOR_ACCENT": "#00FF41",
        "COLOR_ACCENT_HOVER": "#45FF7A",
        "COLOR_TEXT": "#B9D8FF",
        "COLOR_TEXT_DIM": "#5F7FA8",
        "COLOR_BORDER": "#0B7A2B",
        "COLOR_DANGER": "#FF4D6D",
        "COLOR_SUCCESS": "#00FF7F",
        "COLOR_WARNING": "#FFD166",
        "COLOR_NAV_ACTIVE_BG": "#0A2315",
        "COLOR_NAV_HOVER_BG": "#0A1A30",
        "COLOR_MENU_GHOST": "#3A506E",
        "FONT_MAIN": ("Consolas", 11),
        "FONT_BOLD": ("Consolas", 11, "bold"),
        "FONT_TITLE": ("Consolas", 18, "bold"),
    },
    "classic": {
        "COLOR_BG": "#121212",
        "COLOR_SIDEBAR": "#121212",
        "COLOR_SURFACE": "#1E1E1E",
        "COLOR_ACCENT": "#FFFFFF",
        "COLOR_ACCENT_HOVER": "#E0E0E0",
        "COLOR_TEXT": "#E0E0E0",
        "COLOR_TEXT_DIM": "#757575",
        "COLOR_BORDER": "#2C2C2C",
        "COLOR_DANGER": "#CF6679",
        "COLOR_SUCCESS": "#4CAF50",
        "COLOR_WARNING": "#FFB74D",
        "COLOR_NAV_ACTIVE_BG": "#2A2A2A",
        "COLOR_NAV_HOVER_BG": "#262626",
        "COLOR_MENU_GHOST": "#8A8A8A",
        "FONT_MAIN": ("Roboto", 11),
        "FONT_BOLD": ("Roboto", 11, "bold"),
        "FONT_TITLE": ("Roboto", 18, "bold"),
    },
}


def _apply_theme_preset(theme_name):
    theme = THEME_PRESETS.get(theme_name, THEME_PRESETS["nord"])
    for key, value in theme.items():
        globals()[key] = value


_apply_theme_preset(getattr(config, "ui_theme", "nord"))

# Hardware API 專用 accent colors / 跟主題一致的灰階層次
COLOR_HARDWARE_PANEL_BORDER = "#2E2E2E"
COLOR_HARDWARE_INPUT_BG = "#2A2A2A"
COLOR_HARDWARE_INPUT_BORDER = "#3A3A3A"
COLOR_HARDWARE_INPUT_HOVER = "#454545"
COLOR_HARDWARE_BUTTON_BG = "#262626"
COLOR_HARDWARE_BUTTON_HOVER = "#343434"
COLOR_HARDWARE_BUTTON_TEXT = "#F2F2F2"
COLOR_HARDWARE_DROPDOWN_BG = "#242424"

CVM_CONFIG_COMMENT_KEY = "_comment"
CVM_CONFIG_COMMENT_VALUE = "This is CVM colorBot config."
CF_HDROP = 15
DRAG_QUERY_FILE_COUNT = 0xFFFFFFFF
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040
GHND = GMEM_MOVEABLE | GMEM_ZEROINIT


class DROPFILES(ctypes.Structure):
    _fields_ = [
        ("pFiles", wintypes.DWORD),
        ("pt_x", wintypes.LONG),
        ("pt_y", wintypes.LONG),
        ("fNC", wintypes.BOOL),
        ("fWide", wintypes.BOOL),
    ]


if os.name == "nt":
    KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    USER32 = ctypes.WinDLL("user32", use_last_error=True)
    SHELL32 = ctypes.WinDLL("shell32", use_last_error=True)

    KERNEL32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    KERNEL32.GlobalAlloc.restype = wintypes.HANDLE
    KERNEL32.GlobalLock.argtypes = [wintypes.HANDLE]
    KERNEL32.GlobalLock.restype = wintypes.LPVOID
    KERNEL32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    KERNEL32.GlobalUnlock.restype = wintypes.BOOL
    KERNEL32.GlobalFree.argtypes = [wintypes.HANDLE]
    KERNEL32.GlobalFree.restype = wintypes.HANDLE

    USER32.OpenClipboard.argtypes = [wintypes.HWND]
    USER32.OpenClipboard.restype = wintypes.BOOL
    USER32.EmptyClipboard.argtypes = []
    USER32.EmptyClipboard.restype = wintypes.BOOL
    USER32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    USER32.SetClipboardData.restype = wintypes.HANDLE
    USER32.GetClipboardData.argtypes = [wintypes.UINT]
    USER32.GetClipboardData.restype = wintypes.HANDLE
    USER32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    USER32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    USER32.CloseClipboard.argtypes = []
    USER32.CloseClipboard.restype = wintypes.BOOL

    SHELL32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    SHELL32.DragQueryFileW.restype = wintypes.UINT
else:
    KERNEL32 = None
    USER32 = None
    SHELL32 = None

BUTTONS = {
    0: 'Left Mouse Button',
    1: 'Right Mouse Button',
    2: 'Middle Mouse Button',
    3: 'Side Mouse 4 Button',
    4: 'Side Mouse 5 Button'
}
BUTTON_NAME_TO_IDX = {name: idx for idx, name in BUTTONS.items()}
BUTTON_IDX_TO_VK = {
    0: 0x01,
    1: 0x02,
    2: 0x04,
    3: 0x05,
    4: 0x06,
}

ADS_KEY_DISPLAY_TO_BINDING = {
    "Right Mouse Button": "Right Mouse Button",
    "Left Mouse Button": "Left Mouse Button",
    "Middle Mouse Button": "Middle Mouse Button",
    "Side Mouse 4 Button": "Side Mouse 4 Button",
    "Side Mouse 5 Button": "Side Mouse 5 Button",
    "Left Shift": "LSHIFT",
    "Right Shift": "RSHIFT",
    "Left Ctrl": "LCONTROL",
    "Right Ctrl": "RCONTROL",
    "Left Alt": "LMENU",
    "Right Alt": "RMENU",
    "Space": "SPACE",
    "E": "E",
    "Q": "Q",
    "F": "F",
    "R": "R",
    "C": "C",
    "V": "V",
    "X": "X",
    "Z": "Z",
    "W": "W",
    "A": "A",
    "S": "S",
    "D": "D",
}

ADS_KEY_BINDING_TO_DISPLAY = {
    str(binding).upper(): display for display, binding in ADS_KEY_DISPLAY_TO_BINDING.items()
}

BIND_CAPTURE_KEY_TOKENS = (
    ["SPACE", "TAB", "ENTER", "ESCAPE", "LSHIFT", "RSHIFT", "LCONTROL", "RCONTROL", "LMENU", "RMENU", "UP", "DOWN", "LEFT", "RIGHT"]
    + [chr(code) for code in range(ord("A"), ord("Z") + 1)]
    + [str(num) for num in range(10)]
    + [f"F{i}" for i in range(1, 13)]
)

ADS_KEY_TYPE_DISPLAY_TO_VALUE = {
    "Hold": "hold",
    "Toggle": "toggle",
}

ADS_KEY_TYPE_VALUE_TO_DISPLAY = {
    str(value).lower(): display for display, value in ADS_KEY_TYPE_DISPLAY_TO_VALUE.items()
}

TRIGGER_TYPE_DISPLAY = {
    "current": "Classic Trigger",
    "rgb": "RGB Trigger",
}

RGB_TRIGGER_PROFILE_DISPLAY = {
    "red": "Red",
    "yellow": "Yellow",
    "purple": "Purple",
    "custom": "Custom",
}

TRIGGER_STRAFE_MODE_DISPLAY = {
    "off": "Off",
    "auto": "Auto Strafe",
    "manual_wait": "Manual Wait",
}

AIM_MODE_DISPLAY_TO_VALUE = {
    "Normal": "Normal",
    "Flick": "Flick",
    "Silent": "Silent",
    "NCAF": "NCAF",
    "WindMouse": "WindMouse",
    "Bezier": "Bezier",
    "PID Controller ( RISK )": "PID",
}

AIM_MODE_VALUE_TO_DISPLAY = {value: key for key, value in AIM_MODE_DISPLAY_TO_VALUE.items()}
AIM_MODE_OPTIONS = list(AIM_MODE_DISPLAY_TO_VALUE.keys())

class ViewerApp(ctk.CTk):
    """主應用程式 UI (Ultra Minimalist)。"""
    
    def __init__(self, tracker, capture_service, ui_mode=None):
        super().__init__()
        
        # --- Window setup ---
        # Version comes from src/version.py (single source); never hard-coded.
        self.title(f"CVM colorBot {get_version_label()}")
        self._legacy_ui_mode = bool(getattr(config, "legacy_ui_mode", False))
        self._ui_theme = str(getattr(config, "ui_theme", "nord")).strip().lower()
        if self._ui_theme not in THEME_PRESETS:
            self._ui_theme = "classic" if self._legacy_ui_mode else "nord"
        config.language = i18n.set_language(getattr(config, "language", "en"))
        _apply_theme_preset(self._ui_theme)

        # --- UI mode state machine (plan §7) ---
        # "simple" builds the compact dashboard, "pro" keeps the historical
        # layout. They are two different widget trees, not two flavours of one.
        requested = str(ui_mode or "").strip().lower()
        if requested not in ("simple", "pro"):
            requested = "pro" if bool(getattr(config, "ui_pro_mode", False)) else "simple"
        if not bool(getattr(config, "ui_compact_layout", True)):
            # Rollback flag: pre-redesign behaviour was "Pro, collapsed".
            requested = "pro"
        self._ui_mode = requested
        self._ui_pro_mode = requested == "pro"
        self._ui_rebuilding = False
        self._closing = False
        self._ui_hidden = False
        self._minimized = False
        self._last_toggle_time = 0.0
        self._toggle_hotkey = str(getattr(config, "ui_toggle_hotkey", "Insert") or "")
        self._window_style_sig = None
        self._taskbar_style_applied = False
        self._config_save_job = None
        self._scheduler_started = False
        self._hotkey_poll_job = None
        self._launcher = None
        self._launcher_queue = queue.Queue()
        self._instance_watcher = None
        self._settings_window = None
        self._binding_capture_ctx = None
        self._binding_capture_id = 0
        self._simple_fps_text = "--"
        self._simple_ping_text = "-- ms"
        self._pid_preview_job = None
        self._pid_preview_canvas_main = None
        self._pid_preview_canvas_sec = None
        
        # 注意: 若啟用 overrideredirect(True)，系統框線與 taskbar 行為可能不同
        # If you need normal window decorations, keep it commented out.
        self.overrideredirect(True)
        self._is_maximized = False
        self._restore_geometry = ""
        
        self.configure(fg_color=COLOR_BG)
        
        # 預設不置頂，避免影響其他 app/focus
        self.attributes('-topmost', False)
        # Tk puts the toplevel path in the bindtags of EVERY descendant widget, so
        # this handler must ignore child <Map> events (plan RC-2).
        self.bind("<Map>", self._on_window_map)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # --- Core services ---
        self.tracker = tracker
        self.capture = capture_service
        
        # --- Mouse input monitor ---
        self.mouse_input_monitor = MouseInputMonitor()
        
        # --- Update Checker ---
        self.update_checker = get_update_checker()
        self._update_check_in_progress = False
        
        # --- Debug tab state (init once to preserve tab-switch state) ---
        self.debug_mouse_input_var = tk.BooleanVar(value=False)
        
        # --- UI runtime state ---
        self._slider_widgets = {}
        self._checkbox_vars = {}
        self._option_widgets = {}
        self._active_tab_name = "Main Aimbot" if not self._legacy_ui_mode else "General"
        self._clipboard_import_poll_interval_ms = 1200
        self._clipboard_import_last_declined_signature = None
        self._clipboard_import_last_declined_config_fingerprint = None
        self._clipboard_import_imported_signatures = set()
        self._clipboard_import_prompt_open = False
        raw_section_states = getattr(config, "ui_collapsible_states", {})
        self._collapsible_section_states = (
            dict(raw_section_states) if isinstance(raw_section_states, dict) else {}
        )
        self.current_frame = None
        # Runtime lock state cache (plan H1): avoids a full widget-tree walk on
        # every 500 ms tick when nothing changed.
        self._last_runtime_lock_state = None
        self._debug_log_version = None
        self._advanced_rows = []
        
        # 啟動時使用 config.capture_mode
        init_mode = getattr(config, "capture_mode", "NDI")
        self.capture.set_mode(init_mode)
        self.capture_method_var = tk.StringVar(value=init_mode)
        
        # --- Capture control cache (restore from config) ---
        self.saved_udp_ip = getattr(config, "udp_ip", "127.0.0.1")
        self.saved_udp_port = getattr(config, "udp_port", "5000")
        self.saved_teleport_host = str(getattr(config, "teleport_host", ""))
        self.saved_teleport_port = str(getattr(config, "teleport_port", "0"))
        self.saved_teleport_stream_key = str(getattr(config, "teleport_stream_key", ""))
        self._teleport_stream_display_to_key = {}
        self._capture_card_display_to_index = {}
        self._capture_card_display_to_name = {}
        self.saved_ndi_source = getattr(config, "last_ndi_source", None)
        self.saved_mouse_api = getattr(config, "mouse_api", "Serial")
        self.saved_keyboard_api_enabled = bool(getattr(config, "keyboard_api_enabled", False))
        self.saved_keyboard_api = getattr(config, "keyboard_api", "Follow Mouse API")
        self.saved_net_ip = getattr(config, "net_ip", "192.168.2.188")
        self.saved_net_port = getattr(config, "net_port", "6234")
        self.saved_net_uuid = getattr(config, "net_uuid", getattr(config, "net_mac", ""))
        self.saved_kmboxa_vid_pid = str(
            getattr(config, "kmboxa_vid_pid", f"{getattr(config, 'kmboxa_vid', 0)}/{getattr(config, 'kmboxa_pid', 0)}")
        )
        self.saved_serial_port_mode = str(getattr(config, "serial_port_mode", "Auto"))
        self.saved_serial_port = str(getattr(config, "serial_port", ""))
        self.saved_serial_auto_switch_4m = bool(getattr(config, "serial_auto_switch_4m", False))
        self.saved_arduino_port = str(getattr(config, "arduino_port", ""))
        self.saved_arduino_baud = str(getattr(config, "arduino_baud", 115200))
        self.saved_makv2_port = getattr(config, "makv2_port", "")
        self.saved_makv2_baud = str(getattr(config, "makv2_baud", 4000000))
        self.saved_makcu_controller_port = str(getattr(config, "makcu_controller_port", ""))
        self.saved_makcu_controller_baud = str(getattr(config, "makcu_controller_baud", 115200))
        self.saved_makxd_mak_port = str(getattr(config, "makxd_mak_port", ""))
        self.saved_makxd_mak_baud = str(getattr(config, "makxd_mak_baud", 115200))
        self.saved_mak_api_port = str(getattr(config, "mak_api_port", ""))
        self.saved_mak_api_baud = str(getattr(config, "mak_api_baud", 0))
        self.saved_dhz_ip = getattr(config, "dhz_ip", "192.168.2.188")
        self.saved_dhz_port = str(getattr(config, "dhz_port", "5000"))
        self.saved_dhz_random = str(getattr(config, "dhz_random", 0))
        self.saved_ferrum_device_path = str(getattr(config, "ferrum_device_path", ""))
        self.saved_ferrum_connection_type = str(getattr(config, "ferrum_connection_type", "auto"))
        self.saved_ferrum_mode = str(getattr(config, "ferrum_mode", "KmAPI"))
        self.saved_ferrum_net_ip = str(getattr(config, "ferrum_net_ip", "192.168.2.188"))
        self.saved_ferrum_net_port = str(getattr(config, "ferrum_net_port", "6234"))
        self.saved_ferrum_net_uuid = str(getattr(config, "ferrum_net_uuid", ""))
        self.saved_ferrum_dhz_ip = str(getattr(config, "ferrum_dhz_ip", "192.168.8.88"))
        self.saved_ferrum_dhz_port = str(getattr(config, "ferrum_dhz_port", "5000"))
        self.saved_ferrum_dhz_random = str(getattr(config, "ferrum_dhz_random", 0))
        self.saved_medius_port = str(getattr(config, "medius_port", ""))
        self.saved_keyboard_ferrum_device_path = str(getattr(config, "keyboard_ferrum_device_path", ""))
        self.saved_keyboard_ferrum_connection_type = str(
            getattr(config, "keyboard_ferrum_connection_type", "auto")
        )
        self.saved_keyboard_ferrum_mode = str(getattr(config, "keyboard_ferrum_mode", "KmAPI"))
        self.saved_keyboard_ferrum_net_ip = str(getattr(config, "keyboard_ferrum_net_ip", "192.168.2.188"))
        self.saved_keyboard_ferrum_net_port = str(getattr(config, "keyboard_ferrum_net_port", "6234"))
        self.saved_keyboard_ferrum_net_uuid = str(getattr(config, "keyboard_ferrum_net_uuid", ""))
        self.saved_keyboard_ferrum_dhz_ip = str(getattr(config, "keyboard_ferrum_dhz_ip", "192.168.8.88"))
        self.saved_keyboard_ferrum_dhz_port = str(getattr(config, "keyboard_ferrum_dhz_port", "5000"))
        self.saved_keyboard_ferrum_dhz_random = str(getattr(config, "keyboard_ferrum_dhz_random", 0))
        self.saved_auto_connect_mouse_api = bool(getattr(config, "auto_connect_mouse_api", False))
        self._mouse_api_connecting = False
        self._mouse_api_connect_job_id = 0
        self._mouse_api_connect_timeout_ms = 12000
        self._keyboard_api_connecting = False
        self._serial_baud_switching = False
        self._capture_switching = False
        self._cached_capture_card_devices = []
        self._capture_connect_job_id = 0
        self._runtime_active = False
        self._runtime_busy = False
        self._runtime_job_id = 0
        self._ignore_settings_events = False
        
        # --- Build layout (mode-aware) ---
        self._apply_ui_mode(self._ui_mode, rebuild=True, persist=False)
        
        # --- Periodic jobs ---
        # ONE scheduler replaces six independent after() chains (50/100/200/300/
        # 500/1200 ms), so Tk sees one timer and idle work can be gated on the
        # window actually being visible (plan H11).
        self._last_source_tick = 0.0
        self._last_telemetry_tick = 0.0
        self._last_status_tick = 0.0
        self._last_clipboard_tick = 0.0
        self._last_mouse_tick = 0.0
        self._last_debug_tick = 0.0
        self._ui_tick_job = None
        self._start_scheduler()

        # Global hotkey + tray. One instance, created once, independent of mode.
        self._start_launcher()

        self.after(200, self._load_initial_config)
        self.after(400, lambda: self._sync_window_style(force=True))
        self.after(800, self._maybe_auto_start_runtime)

    # ------------------------------------------------------------------
    # UI mode state machine (plan §7)
    # ------------------------------------------------------------------
    @property
    def _simple_mode(self) -> bool:
        return self._ui_mode == "simple"

    def _enter_simple_mode(self, rebuild=True, persist=True):
        self._apply_ui_mode("simple", rebuild=rebuild, persist=persist)

    def _enter_pro_mode(self, rebuild=True, persist=True):
        self._apply_ui_mode("pro", rebuild=rebuild, persist=persist)

    def _ensure_pro_mode(self, initial_tab=None):
        """Switch to Pro, optionally rendering ``initial_tab`` as the first tab.

        Every ``_show_*_tab()`` entry point calls this first, so the historical
        public API keeps working even when invoked from the Simple dashboard.
        Returns True when a switch happened (the caller must then return: the
        requested tab has already been rendered by the switch).
        """
        if self._ui_mode == "pro":
            return False
        self._apply_ui_mode("pro", rebuild=True, persist=True, initial_tab=initial_tab)
        return True

    def _show_tab_map(self):
        return {
            "General": self._show_general_tab,
            "Hardware": self._show_general_tab,
            "Hardware & Capture": self._show_general_tab,
            "Main Aimbot": self._show_aimbot_tab,
            "Combat": self._show_aimbot_tab,
            "Sec Aimbot": self._show_sec_aimbot_tab,
            "Flick V2": self._show_flick_v2_tab,
            "Vision": self._show_vision_tab,
            "Trigger": self._show_tb_tab,
            "Magnet Trigger": self._show_magnet_trigger_tab,
            "RCS": self._show_rcs_tab,
            "Config": self._show_config_tab,
            "Profiles": self._show_config_tab,
            "Profiles & Config": self._show_config_tab,
            "Debug": self._show_debug_tab,
            "Telemetry": self._show_debug_tab,
            "Debug & Telemetry": self._show_debug_tab,
        }

    def refresh_simple_dashboard(self) -> None:
        """Refresh the compact dashboard widgets against current config values."""
        if not getattr(self, "_simple_mode", False):
            return
        try:
            from src.ui_modes.simple_dashboard import refresh_simple_dashboard
            refresh_simple_dashboard(self)
        except Exception as e:
            log_print(f"[UI] refresh_simple_dashboard error: {e}")

    def _save_mode_geometry(self) -> None:
        """Persist the geometry/position of the mode that is being left."""
        if not self.winfo_exists():
            return
        # During initial boot, layout is not yet built; do not overwrite user's saved config
        if getattr(self, "content_frame", None) is None:
            return
        try:
            if self._ui_mode == "pro":
                self._last_pro_tab = getattr(self, "_active_tab_name", "Combat")
            if self._is_maximized:
                return
            if self._ui_mode == "pro":
                geometry = str(self.geometry())
                if "x" in geometry and "+" in geometry:
                    size = geometry.split("+", 1)[0]
                    parts = size.split("x")
                    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                        w, h = int(parts[0]), int(parts[1])
                        if w >= 900 and h >= 600:
                            config.ui_pro_geometry = size
            else:
                x = int(self.winfo_x())
                y = int(self.winfo_y())
                if x > -10000 and y > -10000:
                    config.ui_simple_position = f"+{x}+{y}"
        except Exception:
            pass

    def _apply_ui_mode(self, mode, rebuild=True, persist=True, initial_tab=None):
        """Switch (or boot into) ``simple``/``pro`` without leaking widgets/jobs."""
        mode = str(mode or "").strip().lower()
        if mode not in ("simple", "pro"):
            return
        if mode == self._ui_mode and rebuild and getattr(self, "content_frame", None) is not None:
            return

        self._save_mode_geometry()
        self._ui_rebuilding = True
        self._cancel_binding_capture()
        self._cancel_pid_preview()
        self._ignore_settings_events = True

        if rebuild:
            self._teardown_layout()

        self._ui_mode = mode
        self._ui_pro_mode = mode == "pro"
        config.ui_pro_mode = self._ui_pro_mode

        try:
            if mode == "simple":
                self._build_simple_layout()
            else:
                self._build_pro_layout(initial_tab=initial_tab)
        finally:
            self._ignore_settings_events = False
            self._ui_rebuilding = False

        self.update_idletasks()
        self._sync_window_style(force=True)
        self._reset_tick_timers()

        if persist:
            self._schedule_config_save()

    def _reset_tick_timers(self) -> None:
        """Force every scheduler branch to run on the next tick."""
        self._last_source_tick = 0.0
        self._last_telemetry_tick = 0.0
        self._last_status_tick = 0.0
        self._last_clipboard_tick = 0.0
        self._last_mouse_tick = 0.0
        self._last_debug_tick = 0.0

    def _teardown_layout(self):
        """Destroy the current tree and reset every widget registry.

        ``_collapsible_section_states`` is deliberately NOT cleared: losing the
        user's open/closed sections on every mode switch was RC-3.
        """
        self._cancel_binding_capture()
        self._cancel_pid_preview()
        for attr in ("title_bar", "sidebar", "content_frame", "simple_root"):
            widget = getattr(self, attr, None)
            if widget is not None:
                try:
                    widget.destroy()
                except Exception:
                    pass
                try:
                    delattr(self, attr)
                except Exception:
                    pass
        for attr in (
            "runtime_btn",
            "status_indicator",
            "pill_fps",
            "pill_delay",
            "pill_hardware",
            "pill_conn",
            "fps_label",
            "decode_delay_label",
            "total_delay_label",
            "hardware_type_label",
            "hardware_conn_label",
            "hardware_details_toggle",
            "hardware_details_label",
            "active_profile_label",
            "lang_btn",
            "theme_btn",
            "ui_style_btn",
            "mode_toggle_btn",
            "maximize_btn",
            "minimize_btn",
            "mode_option",
            "mode_option_sec",
            "aim_key_bind_button",
            "aim_key_bind_button_sec",
            "simple_profile_option",
            "simple_pro_btn",
            "simple_hide_btn",
            "simple_sec_gain_row",
            "simple_sec_speed_row",
            "config_option",
            "debug_log_textbox",
            "debug_log_count_label",
            "config_log",
            "flick_diagnostics_label",
            "calibration_state_label",
            "calibration_valorante_label",
            "calibration_valorant_label",
            "calibration_samples_label",
            "calibration_analytic_label",
            "calibration_valorant_frame",
            "calibration_measured_frame",
        ):
            if hasattr(self, attr):
                try:
                    delattr(self, attr)
                except Exception:
                    pass
        self._slider_widgets = {}
        self._checkbox_vars = {}
        self._option_widgets = {}
        self._range_slider_widgets = {}
        self._advanced_rows = []
        self.nav_buttons = {}
        self.nav_indicators = {}
        self._last_runtime_lock_state = None
        self._debug_log_version = None
        self._drop_config_caches()

    def _drop_config_caches(self):
        """Forget the per-widget "last text" caches of the destroyed widgets.

        ``_safe_configure`` keys its cache by ``id(widget)``; a destroyed widget's
        id can be reused by the next allocation, which would silently suppress the
        first (real) update of the new widget.
        """
        for attr in [a for a in vars(self) if str(a).startswith("_cfgcache_")]:
            try:
                delattr(self, attr)
            except Exception:
                pass

    def _build_simple_layout(self):
        """Compact layout: slim title bar + the six core blocks. No sidebar."""
        from src.ui_modes.simple_dashboard import build_simple_dashboard

        self._build_simple_title_bar()

        # A plain CTkFrame on purpose: a CTkScrollableFrame would re-layout every
        # child on each <Configure> and bind another <MouseWheel> (plan RC-4).
        self.content_frame = ctk.CTkFrame(self, fg_color=COLOR_SURFACE, corner_radius=0)
        self.content_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._apply_simple_geometry()
        self.simple_root = build_simple_dashboard(self, self.content_frame)
        self._active_tab_name = "Simple"

    def _build_simple_title_bar(self):
        self.title_bar = ctk.CTkFrame(self, height=34, fg_color=COLOR_SIDEBAR, corner_radius=0)
        self.title_bar.grid(row=0, column=0, sticky="ew")
        self.title_bar.grid_propagate(False)

        left = ctk.CTkFrame(self.title_bar, fg_color="transparent")
        left.pack(side="left", padx=12)
        ctk.CTkLabel(
            left,
            text="CVM colorBot",
            font=("Consolas", 11, "bold"),
            text_color=COLOR_ACCENT,
        ).pack(side="left")
        ctk.CTkLabel(
            left,
            text=f" {get_version_label()}",
            font=("Consolas", 9),
            text_color="#10B981",
        ).pack(side="left")
        ctk.CTkLabel(
            left,
            text=" SIMPLE ",
            font=("Segoe UI", 8, "bold"),
            text_color="#04140A",
            fg_color=COLOR_ACCENT,
            corner_radius=4,
        ).pack(side="left", padx=(8, 0))

        self._build_window_buttons(self.title_bar, show_maximize=False)
        self._bind_title_drag(self.title_bar)

    def _build_pro_layout(self, initial_tab=None):
        """Historical layout: title bar + 5-pillar sidebar + scrollable content."""
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_title_bar()
        self._build_sidebar()

        self.content_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=COLOR_BORDER,
            scrollbar_button_hover_color=COLOR_ACCENT
        )
        self.content_frame.grid(row=1, column=1, sticky="nsew", padx=14, pady=10)

        self._apply_pro_geometry()

        target_tab = initial_tab or getattr(self, "_last_pro_tab", None)
        if target_tab:
            self._render_tab(target_tab)
        elif self._legacy_ui_mode:
            self._show_general_tab()
        else:
            self._show_aimbot_tab()

    def _render_tab(self, tab_name):
        """Render one Pro tab by its display name (the nav/refresh vocabulary)."""
        handler = self._show_tab_map().get(str(tab_name))
        if handler is None:
            handler = self._show_general_tab if self._legacy_ui_mode else self._show_aimbot_tab
        try:
            handler()
        except Exception as exc:
            log_print(f"[UI] tab render failed ({tab_name}): {exc}")

    def _apply_simple_geometry(self):
        geometry = str(getattr(config, "ui_simple_geometry", "560x540") or "560x540")
        width, height = win32_window.parse_geometry(geometry)
        if width <= 0 or height <= 0:
            width, height = 560, 540
        self._is_maximized = False
        try:
            self.resizable(False, False)
            self.minsize(width, height)
            self.maxsize(width, height)
        except Exception:
            pass
        position = win32_window.clamp_position(
            getattr(config, "ui_simple_position", ""), width, height
        )
        self.geometry(f"{width}x{height}{position}" if position else f"{width}x{height}")

    def _apply_pro_geometry(self):
        geometry = str(getattr(config, "ui_pro_geometry", "980x660") or "980x660")
        width, height = win32_window.parse_geometry(geometry)
        if width < 900 or height < 600:
            width, height = 980, 660
        try:
            self.resizable(True, True)
            self.minsize(900, 600)
            self.maxsize(16777215, 16777215)
        except Exception:
            pass
        self.geometry(f"{width}x{height}")

    def _schedule_config_save(self, delay_ms=600):
        """Debounce disk I/O off the mode-switch callback (plan §7.3)."""
        if getattr(self, "_config_save_job", None):
            try:
                self.after_cancel(self._config_save_job)
            except Exception:
                pass
            self._config_save_job = None
        try:
            self._config_save_job = self.after(delay_ms, self._flush_config_save)
        except Exception:
            self._config_save_job = None

    def _flush_config_save(self):
        self._config_save_job = None
        if getattr(self, "_closing", False):
            return
        try:
            config.save_to_file()
        except Exception as exc:
            log_print(f"[UI] deferred config save failed: {exc}")

    def _ui_visible(self):
        """False while iconified/withdrawn: the scheduler then does no work."""
        try:
            return self.state() not in ("iconic", "withdrawn")
        except Exception:
            return True

    def _start_scheduler(self):
        if getattr(self, "_scheduler_started", False):
            return
        self._scheduler_started = True
        self._ui_tick()

    def _cadence(self):
        """Per-mode scheduler intervals in seconds (plan §5.6)."""
        if self._simple_mode:
            return {
                "tick": 0.15,
                "mouse": 0.10,
                "source": None,
                "debug": None,
                "telemetry": 0.50,
                "flick": None,
                "status": 1.00,
                "clipboard": None,
            }
        return {
            "tick": 0.10,
            "mouse": 0.05,
            "source": 0.10,
            "debug": 0.10,
            "telemetry": 0.25,
            "flick": 0.25,
            "status": 0.50,
            "clipboard": float(
                getattr(self, "_clipboard_import_poll_interval_ms", 1200)
            ) / 1000.0,
        }

    def _start_launcher(self):
        if getattr(self, "_launcher", None) is not None:
            return
        self._launcher_queue = queue.Queue()
        vk = parse_hotkey_vk(getattr(config, "ui_toggle_hotkey", "Insert"))
        self._launcher = LauncherService(
            vk=vk,
            on_action=self._launcher_queue.put,
            tray=bool(getattr(config, "ui_tray_enabled", os.name == "nt")),
            app_name="CVM colorBot",
        )
        try:
            if not self._launcher.start():
                log_print(
                    f"[UI] launcher: hotkey/tray unavailable ({self._launcher.last_error})"
                )
        except Exception as exc:
            log_print(f"[UI] launcher start failed: {exc}")
        if self._launcher is not None and getattr(self._launcher, "fallback", False):
            log_print("[UI] hotkey fallback polling is active")
        self._hotkey_poll_job = self.after(40, self._poll_launcher_queue)

    def _poll_launcher_queue(self):
        """Drain launcher actions on the Tk thread (40 ms)."""
        action = None
        try:
            while True:
                action = self._launcher_queue.get_nowait()
                if action == "toggle_ui":
                    self._toggle_ui_visibility()
                elif action == "show":
                    self._show_window()
                elif action == "hide":
                    self._hide_window()
                elif action == "mode:simple":
                    self._enter_simple_mode()
                elif action == "mode:pro":
                    self._enter_pro_mode()
                elif action == "exit":
                    self._on_close()
                    return
                elif isinstance(action, str) and action.startswith("warn:"):
                    log_print(f"[UI] launcher warning: {action}")
        except queue.Empty:
            pass
        except Exception as exc:
            log_print(f"[UI] launcher poll error: {exc}")
        finally:
            if not getattr(self, "_closing", False):
                try:
                    self._hotkey_poll_job = self.after(40, self._poll_launcher_queue)
                except Exception:
                    self._hotkey_poll_job = None

    def _poll_clipboard_now(self):
        """Run the clipboard import check once, on demand (no timer chain)."""
        if self._simple_mode:
            return
        try:
            self._maybe_prompt_clipboard_config_import()
        except Exception as exc:
            log_print(f"[UI] Clipboard config poll error: {exc}")

    def _ui_tick(self):
        """Single scheduler; each branch runs at its mode-specific cadence."""
        try:
            if getattr(self, "_closing", False):
                return
            if not self._ui_visible():
                # Sleep longer while minimised, and do not touch any widget.
                self._ui_tick_job = self.after(400, self._ui_tick)
                return

            cadence = self._cadence()
            now = time.perf_counter()

            if cadence["mouse"] is not None and now - self._last_mouse_tick >= cadence["mouse"]:
                self._last_mouse_tick = now
                self._update_mouse_input_debug()

            if cadence["source"] is not None and now - self._last_source_tick >= cadence["source"]:
                self._last_source_tick = now
                self._process_source_updates()

            if cadence["debug"] is not None and now - self._last_debug_tick >= cadence["debug"]:
                self._last_debug_tick = now
                self._update_debug_log()

            if cadence["telemetry"] is not None and now - self._last_telemetry_tick >= cadence["telemetry"]:
                self._last_telemetry_tick = now
                self._update_performance_stats()
                if cadence["flick"] is not None:
                    self._refresh_flick_readouts()

            if cadence["status"] is not None and now - self._last_status_tick >= cadence["status"]:
                self._last_status_tick = now
                self._update_connection_status_loop()

            # ONE clipboard check per interval. The old version rescheduled
            # itself from inside, so chains multiplied every 1.2 s (RC-1).
            if cadence["clipboard"] is not None and now - self._last_clipboard_tick >= cadence["clipboard"]:
                self._last_clipboard_tick = now
                self._poll_clipboard_now()
        except Exception as e:
            log_print(f"[UI] scheduler error: {e}")
        finally:
            if not getattr(self, "_closing", False):
                try:
                    interval_ms = int(round(self._cadence()["tick"] * 1000))
                except Exception:
                    interval_ms = 100
                try:
                    if self.winfo_exists():
                        self._ui_tick_job = self.after(interval_ms, self._ui_tick)
                except Exception:
                    self._ui_tick_job = None

    def _build_title_bar(self):
        """建立標題列 (title bar)。"""
        self.title_bar = ctk.CTkFrame(self, height=30, fg_color=COLOR_BG, corner_radius=10)
        self.title_bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        
        # Title and version
        title_container = ctk.CTkFrame(self.title_bar, fg_color="transparent")
        title_container.pack(side="left", padx=20)
        
        # Logo icon
        logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cvm.jpg")
        self.logo_lbl = None
        if os.path.exists(logo_path):
            try:
                logo_image = Image.open(logo_path)
                # 調整 logo 尺寸為 20x20
                logo_image = logo_image.resize((20, 20), Image.Resampling.LANCZOS)
                logo_ctk = ctk.CTkImage(light_image=logo_image, dark_image=logo_image, size=(20, 20))
                self.logo_lbl = ctk.CTkLabel(
                    title_container,
                    image=logo_ctk,
                    text=""
                )
                self.logo_lbl.pack(side="left", padx=(0, 10))
            except Exception as e:
                log_print(f"[UI] Failed to load logo: {e}")
        
        title_lbl = ctk.CTkLabel(
            title_container, 
            text="CVM colorBot", 
            font=("Consolas", 11, "bold"),
            text_color=COLOR_ACCENT
        )
        title_lbl.pack(side="left")
        
        # Version label (single source: src/version.py)
        current_version = self.update_checker.get_current_version()
        self.version_lbl = ctk.CTkLabel(
            title_container,
            text=get_version_label(),
            font=("Consolas", 9, "bold"),
            text_color="#10B981"
        )
        self.version_lbl.pack(side="left", padx=(10, 0))
        
        # Update button (only show if update available)
        self.update_btn = None

        # Real-time Telemetry Pills in Title Bar (Modern Dashboard Header)
        self.telemetry_container = ctk.CTkFrame(self.title_bar, fg_color="transparent")
        self.telemetry_container.pack(side="left", padx=(16, 0))

        self.pill_fps = StatusPill(self.telemetry_container, "OBS UDP", "FPS: --", dot_color="#10B981")
        self.pill_fps.pack(side="left", padx=(0, 6))

        self.pill_delay = StatusPill(self.telemetry_container, "Delay", "-- ms", dot_color="#06B6D4")
        self.pill_delay.pack(side="left", padx=(0, 6))

        hw_init = getattr(config, "mouse_api", "Serial")
        self.pill_hardware = StatusPill(self.telemetry_container, "Hardware", str(hw_init), dot_color="#94A3B8")
        self.pill_hardware.pack(side="left", padx=(0, 6))

        self._build_window_buttons(self.title_bar, show_maximize=True)
        self._bind_title_drag(self.title_bar, title_lbl)

    def _build_window_buttons(self, parent, show_maximize=True):
        """Close / minimize / maximize / Pro toggle, in right-edge pack order."""
        close_btn = ctk.CTkButton(
            parent, 
            text="X",
            width=30, 
            height=30,
            fg_color="transparent", 
            hover_color=COLOR_SURFACE,
            text_color=COLOR_TEXT_DIM,
            font=("Arial", 12),
            command=self._on_close,
            corner_radius=8
        )
        close_btn.pack(side="right", padx=5)
        self.close_btn = close_btn

        if show_maximize:
            self.maximize_btn = ctk.CTkButton(
                parent,
                text="[]",
                width=30,
                height=30,
                fg_color="transparent",
                hover_color=COLOR_SURFACE,
                text_color=COLOR_TEXT_DIM,
                font=("Arial", 10),
                command=self._toggle_maximize,
                corner_radius=8
            )
            self.maximize_btn.pack(side="right", padx=(0, 2))

        self.minimize_btn = ctk.CTkButton(
            parent,
            text="_",
            width=30,
            height=30,
            fg_color="transparent",
            hover_color=COLOR_SURFACE,
            text_color=COLOR_TEXT_DIM,
            font=("Arial", 12),
            command=self._on_minimize,
            corner_radius=8
        )
        self.minimize_btn.pack(side="right", padx=(0, 2))

        # Mode Toggle (Simple vs Pro Mode)
        self.mode_toggle_btn = ctk.CTkButton(
            parent,
            text="Pro" if self._ui_pro_mode else "Simple",
            width=58,
            height=22,
            fg_color=COLOR_ACCENT if self._ui_pro_mode else COLOR_SURFACE,
            hover_color=COLOR_ACCENT_HOVER if self._ui_pro_mode else COLOR_BORDER,
            text_color="#04140A" if self._ui_pro_mode else COLOR_TEXT,
            font=("Roboto", 9, "bold"),
            command=self._toggle_pro_mode,
            corner_radius=6,
        )
        self.mode_toggle_btn.pack(side="right", padx=(0, 6))
        return close_btn

    def _bind_title_drag(self, title_bar, title_label=None):
        """視窗拖曳事件 Drag behavior."""
        try:
            title_bar.bind("<Button-1>", self.start_move)
            title_bar.bind("<B1-Motion>", self.do_move)
            if title_label is not None:
                title_label.bind("<Button-1>", self.start_move)
                title_label.bind("<B1-Motion>", self.do_move)
            if getattr(self, "logo_lbl", None):
                self.logo_lbl.bind("<Button-1>", self.start_move)
                self.logo_lbl.bind("<B1-Motion>", self.do_move)
        except Exception:
            pass

    def _build_sidebar(self):
        """建立側邊欄：navigation + status widgets。"""
        sidebar_width = 160 if self._legacy_ui_mode else 210
        self.sidebar = ctk.CTkFrame(self, width=sidebar_width, fg_color=COLOR_SIDEBAR, corner_radius=0)
        self.sidebar.grid(row=1, column=0, sticky="ns")
        self.sidebar.grid_propagate(False)
        
        # 分隔線 Separator
        sep_color = COLOR_BORDER
        sep = ctk.CTkFrame(self.sidebar, width=1, fg_color=sep_color)
        sep.pack(side="right", fill="y")

        if not self._legacy_ui_mode:
            brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
            brand.pack(fill="x", padx=12, pady=(10, 4))
            brand_inner = ctk.CTkFrame(brand, fg_color="transparent")
            brand_inner.pack(anchor="w")
            ctk.CTkLabel(
                brand_inner,
                text="CVM",
                font=("Consolas", 18, "bold"),
                text_color=COLOR_ACCENT,
                anchor="w",
            ).pack(side="left")
            ctk.CTkLabel(
                brand_inner,
                text=" colorBot",
                font=("Consolas", 11),
                text_color=COLOR_TEXT_DIM,
                anchor="w",
            ).pack(side="left", padx=(4, 0), pady=(3, 0))
            ctk.CTkFrame(self.sidebar, height=1, fg_color=COLOR_BORDER).pack(fill="x", padx=4, pady=(4, 4))

        # 頂部控制與指標區塊 Top Control Panel
        top_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        top_frame.pack(side="top", fill="x", padx=8, pady=(0, 2))

        # START / STOP 按鈕 (Prominent Master Action Button)
        self.runtime_btn = ctk.CTkButton(
            top_frame,
            text=t("START ENGINE"),
            command=self._toggle_runtime,
            fg_color="#10B981",
            hover_color="#059669",
            text_color="#022C22",
            font=("Segoe UI", 11, "bold"),
            anchor="center",
            height=38,
            corner_radius=8,
        )
        self.runtime_btn.pack(fill="x", pady=(2, 4))
        self._refresh_runtime_button()

        # 效能與硬體指標卡片 Stats Card (Only in legacy mode; modern mode uses title bar pills)
        stats_card = ctk.CTkFrame(top_frame, fg_color=COLOR_SURFACE, corner_radius=6)
        if self._legacy_ui_mode:
            stats_card.pack(fill="x", pady=(0, 4))
        
        stats_inner = ctk.CTkFrame(stats_card, fg_color="transparent")
        stats_inner.pack(fill="x", padx=8, pady=5)

        # 效能資訊 Performance labels
        self.fps_label = ctk.CTkLabel(
            stats_inner, 
            text=t("FPS: --"), 
            text_color=COLOR_TEXT, 
            font=("Roboto", 9, "bold"), 
            anchor="w"
        )
        self.fps_label.pack(fill="x", pady=0)
        
        self.decode_delay_label = ctk.CTkLabel(
            stats_inner, 
            text=t("Decode: -- ms"), 
            text_color=COLOR_TEXT_DIM, 
            font=("Roboto", 8), 
            anchor="w"
        )
        self.decode_delay_label.pack(fill="x", pady=0)
        
        self.total_delay_label = ctk.CTkLabel(
            stats_inner, 
            text=t("Delay: -- ms"), 
            text_color=COLOR_ACCENT, 
            font=("Roboto", 8, "bold"), 
            anchor="w"
        )
        self.total_delay_label.pack(fill="x", pady=0)
        
        # 狀態指示器 Status indicator
        self.status_indicator = ctk.CTkLabel(
            stats_inner,
            text=t("Status: Offline"),
            text_color=COLOR_TEXT_DIM,
            font=("Roboto", 8),
            anchor="w",
            height=15,
        )
        self.status_indicator.pack(fill="x", pady=0)

        self.hardware_type_label = ctk.CTkLabel(
            stats_inner,
            text=t("Hardware: {mode}", mode=getattr(config, "mouse_api", "Serial")),
            text_color=COLOR_TEXT_DIM,
            font=("Roboto", 8),
            anchor="w",
        )
        self.hardware_type_label.pack(fill="x", pady=(1, 0))

        self.hardware_conn_label = ctk.CTkLabel(
            stats_inner,
            text=t("Hardware Status: Disconnected"),
            text_color=COLOR_DANGER,
            font=("Roboto", 8),
            anchor="w",
        )
        self.hardware_conn_label.pack(fill="x", pady=0)

        self._hardware_info_expanded = False
        self.hardware_details_toggle = ctk.CTkButton(
            stats_inner,
            text=t("Hardware Info"),
            command=self._toggle_hardware_info_details,
            fg_color=COLOR_BG,
            hover_color=COLOR_SURFACE,
            text_color=COLOR_TEXT_DIM,
            font=("Roboto", 8),
            anchor="center",
            height=18,
            corner_radius=4,
        )
        self.hardware_details_toggle.pack(fill="x", pady=(3, 0))

        self.hardware_details_label = ctk.CTkLabel(
            stats_inner,
            text="",
            text_color=COLOR_TEXT_DIM,
            font=("Roboto", 8),
            anchor="w",
            justify="left",
        )
        self._update_hardware_status_ui()
        
        # 設定按鈕 Settings button
        self.settings_btn = ctk.CTkButton(
            top_frame,
            text=t("Settings"),
            command=self._open_settings_window,
            fg_color=COLOR_SURFACE,
            hover_color=COLOR_BORDER,
            text_color=COLOR_TEXT,
            font=("Roboto", 9),
            anchor="center",
            height=22,
            corner_radius=6
        )
        if self._legacy_ui_mode:
            self.settings_btn.pack(fill="x", pady=(0, 2))

        # 分隔線 Divider
        ctk.CTkFrame(self.sidebar, height=1, fg_color=COLOR_BORDER).pack(fill="x", padx=6, pady=(3, 4))

        # 側欄底部主題區塊 Bottom theme section
        bottom_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        bottom_frame.pack(side="bottom", fill="x", padx=8, pady=(2, 6))

        # Active Profile Card in Sidebar Bottom
        active_prof_card = ctk.CTkFrame(
            bottom_frame,
            fg_color=COLOR_SURFACE,
            corner_radius=8,
            border_width=1,
            border_color=COLOR_BORDER
        )
        active_prof_card.pack(fill="x", pady=(0, 5))

        active_prof_inner = ctk.CTkFrame(active_prof_card, fg_color="transparent")
        active_prof_inner.pack(fill="x", padx=8, pady=5)

        ctk.CTkLabel(
            active_prof_inner,
            text=t("Active Profile"),
            font=("Segoe UI", 9, "bold"),
            text_color=COLOR_ACCENT,
            anchor="w",
        ).pack(fill="x")

        curr_cfg = os.path.basename(getattr(config, "_config_path", "config.burst_spray.json"))
        self.active_profile_label = ctk.CTkLabel(
            active_prof_inner,
            text=str(curr_cfg),
            font=("Consolas", 9),
            text_color=COLOR_TEXT_DIM,
            anchor="w",
        )
        self.active_profile_label.pack(fill="x", pady=(1, 0))

        # Language toggle row
        lang_row = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        lang_row.pack(fill="x", pady=(0, 3))
        self.lang_btn = ctk.CTkButton(
            lang_row,
            text=f"🌐 {dict(i18n.available()).get(i18n.language, 'Tiếng Việt')}",
            fg_color=COLOR_SURFACE,
            text_color=COLOR_TEXT_DIM,
            hover_color=COLOR_BORDER,
            anchor="center",
            height=20,
            font=("Segoe UI", 9),
            command=self._toggle_language_quick,
            corner_radius=4,
        )
        self.lang_btn.pack(fill="x")

        # 主題切換 Theme toggle row
        theme_row = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        theme_row.pack(fill="x", pady=0)
        theme_row.grid_columnconfigure(0, weight=1)
        theme_row.grid_columnconfigure(1, weight=1)

        self.theme_btn = ctk.CTkButton(
            theme_row,
            text=t("Dark") if ctk.get_appearance_mode() == "Dark" else t("Light"),
            fg_color=COLOR_SURFACE,
            text_color=COLOR_TEXT_DIM,
            hover_color=COLOR_SURFACE,
            anchor="center",
            height=20,
            font=("Roboto", 8),
            command=self._toggle_theme,
            corner_radius=4,
        )
        self.theme_btn.grid(row=0, column=0, sticky="ew", padx=(0, 2))

        self.ui_style_btn = ctk.CTkButton(
            theme_row,
            text=self._ui_theme.capitalize(),
            fg_color=COLOR_SURFACE,
            text_color=COLOR_TEXT_DIM,
            hover_color=COLOR_SURFACE,
            anchor="center",
            height=20,
            font=("Roboto", 8),
            command=self._toggle_ui_style,
            corner_radius=4,
        )
        self.ui_style_btn.grid(row=0, column=1, sticky="ew", padx=(2, 0))

        # 導覽容器 Navigation container
        nav_container = ctk.CTkScrollableFrame(
            self.sidebar,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=COLOR_SURFACE,
            scrollbar_button_hover_color=COLOR_BORDER,
        )
        nav_container.pack(fill="both", expand=True, padx=4, pady=(0, 2))
        
        self.nav_buttons = {}
        self.nav_indicators = {}

        if self._legacy_ui_mode:
            tabs = [
                ("General", self._show_general_tab),
                ("Main Aimbot", self._show_aimbot_tab),
                ("Sec Aimbot", self._show_sec_aimbot_tab),
                ("RCS", self._show_rcs_tab),
                ("Config", self._show_config_tab),
                ("Debug", self._show_debug_tab),
            ]
            for text, cmd in tabs:
                btn = self._create_nav_btn_legacy(nav_container, text, cmd)
                self.nav_buttons[text] = btn
                btn.pack(pady=2, fill="x")
        else:
            # Modern 5-Pillar Navigation: Combat, Vision, Hardware, Profiles, Telemetry
            self._add_sidebar_group_label(nav_container, "Engine")
            combat_btn = self._add_nav_item(nav_container, "Combat", self._show_aimbot_tab, icon="🎯")
            vision_btn = self._add_nav_item(nav_container, "Vision", self._show_vision_tab, icon="👁️")
            self._add_sidebar_group_label(nav_container, "Platform")
            hw_btn = self._add_nav_item(nav_container, "Hardware", self._show_general_tab, icon="⚡")
            prof_btn = self._add_nav_item(nav_container, "Profiles", self._show_config_tab, icon="📁")
            tel_btn = self._add_nav_item(nav_container, "Telemetry", self._show_debug_tab, icon="📊")

            self.nav_buttons["Combat"] = combat_btn
            self.nav_buttons["Vision"] = vision_btn
            self.nav_buttons["Hardware"] = hw_btn
            self.nav_buttons["Profiles"] = prof_btn
            self.nav_buttons["Telemetry"] = tel_btn

            # Alias mappings to prevent any KeyError from direct indexing across legacy callers
            self.nav_buttons["Main Aimbot"] = combat_btn
            self.nav_buttons["Sec Aimbot"] = combat_btn
            self.nav_buttons["Flick V2"] = combat_btn
            self.nav_buttons["RCS"] = combat_btn
            self.nav_buttons["System"] = hw_btn
            self.nav_buttons["General"] = hw_btn
            self.nav_buttons["Hardware & Capture"] = hw_btn
            self.nav_buttons["Config"] = prof_btn
            self.nav_buttons["Profiles & Config"] = prof_btn
            self.nav_buttons["Debug"] = tel_btn
            self.nav_buttons["Debug & Telemetry"] = tel_btn

        self._set_nav_active(self._active_tab_name)

    # ------------------------------------------------------------------
    # Safe widget updates: write only when the value changed AND the widget
    # still exists (plan RC-5). Every periodic update goes through these.
    # ------------------------------------------------------------------
    @staticmethod
    def _widget_alive(widget) -> bool:
        if widget is None:
            return False
        try:
            return bool(widget.winfo_exists())
        except Exception:
            return False

    def _safe_configure(self, widget, **kwargs) -> bool:
        """``configure`` guarded by existence + last-value cache.

        Returns True when Tcl was actually touched, so callers can skip expensive
        follow-up work.
        """
        if not self._widget_alive(widget):
            return False
        cache_key = f"_cfgcache_{id(widget)}"
        cache = getattr(self, cache_key, None)
        if cache == kwargs:
            return False
        try:
            widget.configure(**kwargs)
        except Exception:
            return False
        setattr(self, cache_key, dict(kwargs))
        return True

    def _safe_text(self, widget, text, **kwargs) -> bool:
        payload = {"text": str(text)}
        payload.update(kwargs)
        return self._safe_configure(widget, **payload)

    def _safe_pill(self, pill, value, dot_color=None) -> bool:
        if not self._widget_alive(pill):
            return False
        try:
            if str(getattr(pill, "value_text", "")) == str(value):
                return False
        except Exception:
            pass
        try:
            pill.update_value(str(value), dot_color=dot_color)
            return True
        except Exception:
            return False

    def _set_status_indicator(self, text, text_color=COLOR_TEXT_DIM):
        if not hasattr(self, "status_indicator"):
            return
        msg = t(str(text).replace("\n", " ").strip())
        max_chars = 30
        if len(msg) > max_chars:
            msg = msg[: max_chars - 3] + "..."
        self._safe_text(self.status_indicator, msg, text_color=text_color)

    def _toggle_language_quick(self):
        new_lang = "en" if i18n.language == "vi" else "vi"
        config.language = i18n.set_language(new_lang)
        try:
            config.save_to_file()
        except Exception:
            pass
        self._apply_language()

    def _refresh_runtime_button(self):
        if not hasattr(self, "runtime_btn") or not self.runtime_btn.winfo_exists():
            return
        if getattr(self, "_runtime_busy", False):
            label = t("STOPPING...") if getattr(self, "_runtime_active", False) else t("STARTING...")
            self.runtime_btn.configure(
                text=label,
                state="disabled",
                fg_color=COLOR_SURFACE,
                hover_color=COLOR_SURFACE,
                text_color=COLOR_TEXT_DIM,
            )
            return
        if getattr(self, "_runtime_active", False):
            self.runtime_btn.configure(
                text=t("STOP ENGINE"),
                state="normal",
                fg_color="#F43F5E",
                hover_color="#E11D48",
                text_color="#FFFFFF",
            )
            return
        self.runtime_btn.configure(
            text=t("START ENGINE"),
            state="normal",
            fg_color="#10B981",
            hover_color="#059669",
            text_color="#022C22",
        )

    def _runtime_settings_locked(self):
        return bool(getattr(self, "_runtime_active", False) or getattr(self, "_runtime_busy", False))

    def _set_widget_tree_enabled(self, widget, enabled):
        if widget is None:
            return
        try:
            if not widget.winfo_exists():
                return
        except Exception:
            return
        state = "normal" if enabled else "disabled"
        try:
            widget.configure(state=state)
        except Exception:
            pass
        try:
            children = widget.winfo_children()
        except Exception:
            children = []
        for child in children:
            self._set_widget_tree_enabled(child, enabled)

    def _apply_runtime_settings_lock(self, force=False):
        """Enable/disable the hardware+capture panels to match the runtime state.

        Walking the whole widget tree of three frames took 2-10 ms and used to be
        triggered every 500 ms by the connection loop, even when nothing changed.
        The last applied state is cached, so the traversal happens only on a real
        transition (plan H1).
        """
        enabled = not self._runtime_settings_locked()
        keyboard_enabled = bool(getattr(config, "keyboard_api_enabled", False))
        signature = (enabled, keyboard_enabled)
        if not force and getattr(self, "_last_runtime_lock_state", None) == signature:
            return
        self._last_runtime_lock_state = signature
        for attr in ("mouse_hardware_frame", "keyboard_hardware_frame", "capture_settings_frame"):
            self._set_widget_tree_enabled(getattr(self, attr, None), enabled)
        if enabled:
            try:
                if hasattr(self, "keyboard_api_option") and self.keyboard_api_option.winfo_exists():
                    self.keyboard_api_option.configure(state="normal" if keyboard_enabled else "disabled")
            except Exception:
                pass

    def _restore_locked_mouse_api_option(self):
        if not hasattr(self, "mouse_api_option"):
            return
        try:
            if not self.mouse_api_option.winfo_exists():
                return
        except Exception:
            return
        raw = str(getattr(self, "saved_mouse_api", getattr(config, "mouse_api", "Serial")))
        mapping = {
            "Serial": "Serial (Makcu)",
            "MakAPI": "MAK API",
        }
        display = mapping.get(raw, raw)
        self._ignore_settings_events = True
        try:
            self.mouse_api_option.set(display)
        except Exception:
            pass
        self._ignore_settings_events = False

    def _restore_locked_capture_method_option(self):
        if not hasattr(self, "capture_method_option"):
            return
        try:
            if not self.capture_method_option.winfo_exists():
                return
        except Exception:
            return
        self._ignore_settings_events = True
        try:
            self.capture_method_option.set(self._capture_display_mode(self.capture.mode))
        except Exception:
            pass
        self._ignore_settings_events = False

    def _restore_locked_keyboard_api_option(self):
        if not hasattr(self, "keyboard_api_option"):
            return
        try:
            if not self.keyboard_api_option.winfo_exists():
                return
        except Exception:
            return
        self._ignore_settings_events = True
        try:
            self.keyboard_api_option.set(
                self._normalize_keyboard_api_name(getattr(config, "keyboard_api", "Follow Mouse API"))
            )
        except Exception:
            pass
        self._ignore_settings_events = False

    def _warn_runtime_settings_locked(self, kind="hardware"):
        key = (
            "Status: Stop first to change capture"
            if kind == "capture"
            else "Status: Stop first to change hardware"
        )
        self._set_status_indicator(t(key), COLOR_WARNING)

    def _invalidate_runtime(self):
        self._runtime_job_id = getattr(self, "_runtime_job_id", 0) + 1
        self._runtime_active = False
        self._runtime_busy = False
        self._mouse_api_connecting = False
        self._refresh_runtime_button()

    def _disconnect_runtime_backends(self):
        try:
            from src.utils import mouse as mouse_backend

            mouse_backend.disconnect_all()
        except Exception:
            pass
        try:
            self.capture.disconnect()
        except Exception:
            pass

    def _maybe_auto_start_runtime(self):
        if not bool(getattr(config, "auto_connect_mouse_api", False)):
            return
        if getattr(self, "_runtime_active", False) or getattr(self, "_runtime_busy", False):
            return
        self._start_runtime()

    def _toggle_runtime(self):
        if getattr(self, "_runtime_busy", False):
            return
        if getattr(self, "_runtime_active", False):
            self._stop_runtime()
            return
        self._start_runtime()

    def _start_runtime(self):
        if getattr(self, "_runtime_busy", False) or getattr(self, "_runtime_active", False):
            return
        if getattr(self, "_serial_baud_switching", False):
            self._set_status_indicator("Status: Serial baud switching...", COLOR_TEXT_DIM)
            return
        mouse_payload = self._connect_mouse_api(start_async=False)
        if not mouse_payload:
            return
        capture_payload = self._snapshot_capture_connect_payload()
        self._runtime_busy = True
        self._runtime_job_id = getattr(self, "_runtime_job_id", 0) + 1
        job_id = self._runtime_job_id
        self._refresh_runtime_button()
        self._apply_runtime_settings_lock()
        self._set_status_indicator(t("Status: Starting hardware + capture..."), COLOR_TEXT_DIM)
        threading.Thread(
            target=self._start_runtime_worker,
            args=(job_id, mouse_payload, capture_payload),
            daemon=True,
            name="RuntimeStart",
        ).start()

    def _start_runtime_worker(self, job_id, mouse_payload, capture_payload):
        hw_ok, hw_err = self._execute_mouse_api_connect(mouse_payload)
        cap_ok, cap_err = False, "capture not attempted"
        if job_id != getattr(self, "_runtime_job_id", 0):
            self._disconnect_runtime_backends()
            return
        if hw_ok:
            cap_ok, cap_err = self._connect_capture_backend_sync(capture_payload)
        if job_id != getattr(self, "_runtime_job_id", 0) or not (hw_ok and cap_ok):
            self._disconnect_runtime_backends()
            if job_id != getattr(self, "_runtime_job_id", 0):
                return
        if getattr(self, "_closing", False):
            return
        try:
            self.after(
                0,
                lambda: self._on_runtime_start_done(job_id, hw_ok, hw_err, cap_ok, cap_err, mouse_payload, capture_payload),
            )
        except Exception:
            pass

    def _on_runtime_start_done(self, job_id, hw_ok, hw_err, cap_ok, cap_err, mouse_payload, capture_payload):
        if job_id != getattr(self, "_runtime_job_id", 0):
            return
        self._runtime_busy = False
        self._mouse_api_connecting = False
        if hw_ok and cap_ok:
            self._runtime_active = True
            hw_name = mouse_payload.get("mode", "Hardware")
            cap_name = capture_payload.get("mode", "Capture")
            self._set_status_indicator(t("Status: Running ({hw} + {cap})", hw=hw_name, cap=cap_name), COLOR_SUCCESS)
            if cap_name == "NDI":
                self.after(500, self._update_ndi_fov_sliders_after_connect)
            elif cap_name == "UDP":
                self.after(500, self._update_udp_fov_sliders_after_connect)
        else:
            self._runtime_active = False
            if not hw_ok:
                self._set_status_indicator(t("Status: Hardware failed: {error}", error=hw_err), COLOR_DANGER)
            else:
                self._set_status_indicator(t("Status: Capture failed: {error}", error=cap_err), COLOR_DANGER)
        self._refresh_runtime_button()
        self._update_hardware_status_ui()
        self._apply_runtime_settings_lock()
        self._refresh_capture_entry_card()

    def _stop_runtime(self):
        if getattr(self, "_runtime_busy", False) and getattr(self, "_runtime_active", False):
            return
        self._runtime_busy = True
        self._runtime_job_id = getattr(self, "_runtime_job_id", 0) + 1
        job_id = self._runtime_job_id
        self._refresh_runtime_button()
        self._apply_runtime_settings_lock()
        self._set_status_indicator(t("Status: Stopping..."), COLOR_TEXT_DIM)
        threading.Thread(
            target=self._stop_runtime_worker,
            args=(job_id,),
            daemon=True,
            name="RuntimeStop",
        ).start()

    def _stop_runtime_worker(self, job_id):
        self._disconnect_runtime_backends()
        if getattr(self, "_closing", False):
            return
        try:
            self.after(0, lambda: self._on_runtime_stop_done(job_id))
        except Exception:
            pass

    def _on_runtime_stop_done(self, job_id=None):
        if job_id is not None and job_id != getattr(self, "_runtime_job_id", 0):
            return
        self._runtime_busy = False
        self._runtime_active = False
        self._mouse_api_connecting = False
        self._set_status_indicator(t("Status: Stopped"), COLOR_TEXT_DIM)
        self._refresh_runtime_button()
        self._update_hardware_status_ui()
        self._apply_runtime_settings_lock()
        self._refresh_capture_entry_card()

    def _snapshot_capture_connect_payload(self):
        mode = str(getattr(self.capture, "mode", getattr(config, "capture_mode", "NDI")))
        payload = {"mode": mode}
        if mode == "NDI":
            selected = str(self.saved_ndi_source or getattr(config, "last_ndi_source", "") or "").strip()
            if hasattr(self, "source_option") and self.source_option.winfo_exists():
                current = str(self.source_option.get() or "").strip()
                if current not in ("(Scanning...)", "(no sources)", ""):
                    selected = current
            payload["ndi_source"] = selected
        elif mode == "UDP":
            ip = str(getattr(self, "saved_udp_ip", getattr(config, "udp_ip", "127.0.0.1")))
            port = str(getattr(self, "saved_udp_port", getattr(config, "udp_port", "5000")))
            if hasattr(self, "udp_ip_entry") and self.udp_ip_entry.winfo_exists():
                ip = self.udp_ip_entry.get().strip()
            if hasattr(self, "udp_port_entry") and self.udp_port_entry.winfo_exists():
                port = self.udp_port_entry.get().strip()
            payload.update({"udp_ip": ip, "udp_port": port})
        elif mode == "Teleport":
            host = str(getattr(config, "teleport_host", getattr(self, "saved_teleport_host", ""))).strip()
            port_value = str(getattr(config, "teleport_port", getattr(self, "saved_teleport_port", "0"))).strip()
            stream_key = str(getattr(config, "teleport_stream_key", getattr(self, "saved_teleport_stream_key", ""))).strip()
            if hasattr(self, "teleport_host_entry") and self.teleport_host_entry.winfo_exists():
                host = self.teleport_host_entry.get().strip()
            if hasattr(self, "teleport_port_entry") and self.teleport_port_entry.winfo_exists():
                port_value = self.teleport_port_entry.get().strip()
            if hasattr(self, "teleport_stream_option") and self.teleport_stream_option.winfo_exists():
                selected_display = self.teleport_stream_option.get()
                stream_key = str(self._teleport_stream_display_to_key.get(str(selected_display), "")).strip()
            payload.update({"teleport_host": host, "teleport_port": port_value, "teleport_stream_key": stream_key})
        elif mode in ("CaptureCard", "CaptureCardGStreamer"):
            if hasattr(self, "capture_card_device_option") and self.capture_card_device_option.winfo_exists():
                self._on_capture_card_device_selected(self.capture_card_device_option.get())
            if hasattr(self, "capture_card_width_entry") and hasattr(self, "capture_card_height_entry"):
                try:
                    config.capture_width = int(self.capture_card_width_entry.get())
                    config.capture_height = int(self.capture_card_height_entry.get())
                except ValueError:
                    pass
            payload.update({
                "device_index": int(getattr(config, "capture_device_index", 0)),
                "device_name": str(getattr(config, "capture_device_name", "")),
            })
        elif mode == "MSS":
            monitor_index = int(getattr(config, "mss_monitor_index", 1))
            if hasattr(self, "mss_monitor_entry") and self.mss_monitor_entry.winfo_exists():
                try:
                    monitor_index = int(self.mss_monitor_entry.get())
                    config.mss_monitor_index = monitor_index
                except ValueError:
                    pass
            payload.update({
                "mss_monitor_index": monitor_index,
                "mss_fov_x": int(getattr(config, "mss_fov_x", 320)),
                "mss_fov_y": int(getattr(config, "mss_fov_y", 320)),
            })
        return payload

    def _connect_capture_backend_sync(self, payload):
        mode = str((payload or {}).get("mode") or getattr(self.capture, "mode", "NDI"))
        try:
            if mode == "NDI":
                selected = str(payload.get("ndi_source") or "").strip()
                if not selected:
                    return False, "No NDI source selected"
                self.capture.ndi.set_selected_source(selected)
                self.saved_ndi_source = selected
                config.last_ndi_source = selected
                return self.capture.connect_ndi(selected)
            if mode == "UDP":
                ip = str(payload.get("udp_ip") or getattr(config, "udp_ip", "127.0.0.1"))
                port = str(payload.get("udp_port") or getattr(config, "udp_port", "5000"))
                self.saved_udp_ip = ip
                self.saved_udp_port = port
                config.udp_ip = ip
                config.udp_port = port
                return self.capture.connect_udp(ip, port)
            if mode == "Teleport":
                host = str(payload.get("teleport_host") or "")
                port_value = str(payload.get("teleport_port") or "0")
                stream_key = str(payload.get("teleport_stream_key") or "")
                self.saved_teleport_host = host
                self.saved_teleport_port = port_value
                self.saved_teleport_stream_key = stream_key
                config.teleport_host = host
                config.teleport_port = port_value
                config.teleport_stream_key = stream_key
                return self.capture.connect_teleport(host=host, port=port_value, stream_key=stream_key)
            if mode in ("CaptureCard", "CaptureCardGStreamer"):
                return self.capture.connect_capture_card(config)
            if mode == "MSS":
                return self.capture.connect_mss(
                    int(payload.get("mss_monitor_index", getattr(config, "mss_monitor_index", 1))),
                    int(payload.get("mss_fov_x", getattr(config, "mss_fov_x", 320))),
                    int(payload.get("mss_fov_y", getattr(config, "mss_fov_y", 320))),
                )
            return False, f"Unknown capture mode {mode}"
        except Exception as e:
            return False, str(e)

    def _create_nav_btn(self, parent, text, command, icon=">"):
        return ctk.CTkButton(
            parent,
            text=f"{icon}  {t(text)}",
            height=28,
            fg_color=COLOR_SURFACE,
            text_color=COLOR_TEXT,
            hover_color=COLOR_NAV_HOVER_BG,
            anchor="w",
            font=FONT_MAIN,
            command=lambda: self._handle_nav_click(text, command),
            corner_radius=6,
            border_width=1,
            border_color=COLOR_BORDER,
        )

    def _create_nav_btn_legacy(self, parent, text, command):
        return ctk.CTkButton(
            parent,
            text=t(text),
            height=26,
            fg_color="transparent",
            text_color=COLOR_TEXT,
            hover_color=COLOR_SURFACE,
            anchor="w",
            font=FONT_MAIN,
            command=lambda: self._handle_nav_click(text, command),
            corner_radius=6,
            border_width=1,
            border_color=COLOR_BORDER,
        )

    def _add_sidebar_group_label(self, parent, text):
        ctk.CTkLabel(
            parent,
            text=heading(text),
            font=FONT_BOLD,
            text_color=COLOR_TEXT_DIM,
            anchor="w",
        ).pack(fill="x", pady=(5, 1))

    def _add_sidebar_hint_item(self, parent, text):
        ctk.CTkLabel(
            parent,
            text=f"    {text}",
            font=FONT_MAIN,
            text_color=COLOR_MENU_GHOST,
            anchor="w",
        ).pack(fill="x", pady=(0, 2))

    def _add_nav_item(self, parent, text, command, icon=">"):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=1)

        indicator = ctk.CTkFrame(row, width=3, height=24, fg_color="transparent", corner_radius=2)
        indicator.pack(side="left", fill="y", padx=(0, 4))

        btn = self._create_nav_btn(row, text, command, icon=icon)
        btn.pack(side="left", fill="x", expand=True)

        self.nav_buttons[text] = btn
        self.nav_indicators[text] = indicator
        return btn

    def _toggle_pro_mode(self):
        """Title-bar toggle. Real mode switch, never a section-collapse flag.

        The user's open/closed sections are preserved: clearing
        ``_collapsible_section_states`` on every switch was RC-3.
        """
        self._apply_ui_mode("simple" if self._ui_mode == "pro" else "pro")

    def _add_sub_nav_bar(self, values, current_val, callback_map):
        """Adds a sleek segmented top bar for switching between related tabs."""
        if self._legacy_ui_mode:
            return
        bar_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        bar_frame.pack(fill="x", padx=4, pady=(2, 8))

        def _on_sub_change(selected):
            cmd = callback_map.get(selected)
            if cmd:
                # Defer execution to avoid destroying the widget in the middle of its click event handler
                self.after_idle(cmd)

        seg = ctk.CTkSegmentedButton(
            bar_frame,
            values=values,
            command=_on_sub_change,
            selected_color=COLOR_ACCENT,
            selected_hover_color=COLOR_ACCENT_HOVER,
            unselected_color=COLOR_SURFACE,
            unselected_hover_color=COLOR_BORDER,
            text_color=COLOR_TEXT,
            height=28,
            font=("Roboto", 10, "bold"),
            corner_radius=6,
        )
        seg.pack(fill="x")
        if current_val in values:
            seg.set(current_val)

    def _set_nav_active(self, active_text):
        group_map = {
            "Main Aimbot": "Combat",
            "Sec Aimbot": "Combat",
            "Flick V2": "Combat",
            "RCS": "Combat",
            "Combat": "Combat",
            "Vision": "Vision",
            "Trigger": "Combat",
            "Magnet Trigger": "Combat",
            "General": "Hardware",
            "Hardware": "Hardware",
            "Hardware & Capture": "Hardware",
            "Config": "Profiles",
            "Profiles": "Profiles",
            "Profiles & Config": "Profiles",
            "Debug": "Telemetry",
            "Telemetry": "Telemetry",
            "Debug & Telemetry": "Telemetry",
            "System": "Hardware",
        }
        target_nav = group_map.get(active_text, active_text) if not self._legacy_ui_mode else active_text
        primary_names = (
            ["General", "Main Aimbot", "Sec Aimbot", "RCS", "Config", "Debug"]
            if self._legacy_ui_mode
            else ["Combat", "Vision", "Hardware", "Profiles", "Telemetry"]
        )
        for nav_name in primary_names:
            btn = self.nav_buttons.get(nav_name)
            indicator = self.nav_indicators.get(nav_name)
            if not btn:
                continue
            if nav_name == target_nav or nav_name == active_text:
                btn.configure(text_color=COLOR_ACCENT, fg_color=COLOR_NAV_ACTIVE_BG, border_color=COLOR_BORDER)
                if indicator is not None:
                    indicator.configure(fg_color=COLOR_ACCENT)
            else:
                inactive_bg = "transparent" if self._legacy_ui_mode else COLOR_SURFACE
                inactive_border = COLOR_BORDER
                btn.configure(text_color=COLOR_TEXT, fg_color=inactive_bg, border_color=inactive_border)
                if indicator is not None:
                    indicator.configure(fg_color="transparent")

    def _handle_nav_click(self, text, command):
        self._active_tab_name = str(text)
        self._set_nav_active(self._active_tab_name)
        command()

    def _clear_content(self):
        if self._simple_mode:
            # The Simple dashboard is never torn down by a tab switch; refreshing
            # it in place is cheaper than destroy + rebuild (plan §5.4).
            return
        self._cancel_binding_capture()
        self._cancel_pid_preview()
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        # Clear widget maps to avoid stale destroyed references during config apply.
        self._option_widgets = {}
        self._slider_widgets = {}
        if hasattr(self, "_range_slider_widgets"):
            self._range_slider_widgets = {}
        self._advanced_rows = []
        self._pid_preview_canvas_main = None
        self._pid_preview_canvas_sec = None
        self._pid_preview_info_main = None
        self._pid_preview_info_sec = None
        # Drop references to widgets that were just destroyed. The 10 Hz debug
        # log used to keep formatting 500 entries for a textbox that no longer
        # existed, then raise every tick (plan H2/C8).
        for attr in (
            "debug_log_textbox",
            "debug_log_count_label",
            "config_log",
            "flick_diagnostics_label",
            "flick_engine_pill",
            "flick_calibration_pill",
            "flick_geometry_pill",
            "flick_last_pill",
            "calibration_state_label",
            "calibration_valorante_label",
            "calibration_valorant_label",
            "calibration_samples_label",
            "calibration_analytic_label",
            "calibration_valorant_frame",
            "calibration_measured_frame",
        ):
            if hasattr(self, attr):
                try:
                    delattr(self, attr)
                except Exception:
                    pass

    def _toggle_theme(self):
        if ctk.get_appearance_mode() == "Dark":
            ctk.set_appearance_mode("Light")
            self.theme_btn.configure(text=t("Light Mode"))
        else:
            ctk.set_appearance_mode("Dark")
            self.theme_btn.configure(text=t("Dark Mode"))

    def _toggle_ui_style(self):
        theme_keys = list(THEME_PRESETS.keys())
        idx = theme_keys.index(self._ui_theme) if self._ui_theme in theme_keys else 0
        next_theme = theme_keys[(idx + 1) % len(theme_keys)]
        self._ui_theme = next_theme
        config.ui_theme = next_theme
        self._legacy_ui_mode = (next_theme == "classic")
        config.legacy_ui_mode = self._legacy_ui_mode
        try:
            config.save_to_file()
        except Exception:
            pass
        self._rebuild_layout_for_ui_style()

    def _rebuild_layout_for_ui_style(self):
        """Re-apply theme/language by rebuilding only the CURRENT mode's tree."""
        tab_name = str(getattr(self, "_active_tab_name", "General"))
        self._cancel_binding_capture()
        self._cancel_pid_preview()
        self._ui_rebuilding = True
        try:
            self._teardown_layout()
            _apply_theme_preset(self._ui_theme)
            self.configure(fg_color=COLOR_BG)
            if self._simple_mode:
                self._build_simple_layout()
            else:
                self._build_pro_layout()
        finally:
            self._ui_rebuilding = False
        self.update_idletasks()

        if self._simple_mode:
            from src.ui_modes.simple_dashboard import refresh_simple_dashboard

            refresh_simple_dashboard(self)
            return

        tab_map = self._show_tab_map()
        tab_fn = tab_map.get(tab_name)
        if tab_fn is not None and tab_name != "General":
            self._handle_nav_click(tab_name, tab_fn)

    def _apply_language(self):
        self._rebuild_layout_for_ui_style()

    def _on_language_changed(self, val):
        code = i18n.code_for_name(val)
        if code != i18n.language:
            config.language = i18n.set_language(code)
            try:
                config.save_to_file()
            except Exception:
                pass
            self._apply_language()

    # --- 各分頁內容 Tabs ---

    def _show_vision_tab(self):
        if self._ensure_pro_mode("Vision"):
            return
        self._active_tab_name = "Vision"
        self._clear_content()
        self._add_title("Vision & Color Detection")

        # 1. Target Color Selection Card
        self.card_color_preset = ModernCard(
            self.content_frame,
            "Target Color Selection",
            icon="🎯",
            badge_text="Color",
            accent_color="#10B981"
        )
        self.card_color_preset.pack(fill="x", pady=(0, 10))

        self.color_option = self._add_option_row_in_frame(
            self.card_color_preset.content,
            "Target Color Preset",
            ["yellow", "purple", "red", "custom"],
            self._on_color_selected,
        )
        self._option_widgets["color"] = self.color_option
        current_color = getattr(config, "color", "yellow")
        self.color_option.set(current_color)

        # 2. Custom HSV Range Calibration Card
        self.card_hsv_tuning = ModernCard(
            self.content_frame,
            "Custom HSV Tuning",
            icon="🎨",
            badge_text="Calibration",
            accent_color="#06B6D4"
        )
        self.custom_hsv_container = self.card_hsv_tuning
        self.custom_hsv_section = self.card_hsv_tuning.content
        if current_color == "custom":
            self.card_hsv_tuning.pack(fill="x", pady=(0, 10))

        self._hsv_preview_btn_frame = ctk.CTkFrame(self.custom_hsv_section, fg_color="transparent")
        self._hsv_preview_btn_frame.pack(fill="x", pady=(0, 8))
        ctk.CTkButton(
            self._hsv_preview_btn_frame,
            text=t("Launch HSV Filter Preview"),
            height=32,
            fg_color=COLOR_SURFACE,
            hover_color=COLOR_BORDER,
            text_color=COLOR_ACCENT,
            font=FONT_BOLD,
            corner_radius=6,
            border_width=1,
            border_color=COLOR_BORDER,
            command=self._open_hsv_preview,
        ).pack(fill="x", padx=10)

        # HSV Min Sliders
        self._add_subtitle_in_frame(self.custom_hsv_section, "HSV LOWER BOUNDS")
        self._add_slider_in_frame(self.custom_hsv_section, "Hue Min", "custom_hsv_min_h", 0, 179,
                                  int(getattr(config, "custom_hsv_min_h", 0)),
                                  lambda v: self._on_custom_hsv_changed("custom_hsv_min_h", v))
        self._add_slider_in_frame(self.custom_hsv_section, "Sat Min", "custom_hsv_min_s", 0, 255,
                                  int(getattr(config, "custom_hsv_min_s", 0)),
                                  lambda v: self._on_custom_hsv_changed("custom_hsv_min_s", v))
        self._add_slider_in_frame(self.custom_hsv_section, "Val Min", "custom_hsv_min_v", 0, 255,
                                  int(getattr(config, "custom_hsv_min_v", 0)),
                                  lambda v: self._on_custom_hsv_changed("custom_hsv_min_v", v))

        self._add_spacer_in_frame(self.custom_hsv_section)

        # HSV Max Sliders
        self._add_subtitle_in_frame(self.custom_hsv_section, "HSV UPPER BOUNDS")
        self._add_slider_in_frame(self.custom_hsv_section, "Hue Max", "custom_hsv_max_h", 0, 179,
                                  int(getattr(config, "custom_hsv_max_h", 179)),
                                  lambda v: self._on_custom_hsv_changed("custom_hsv_max_h", v))
        self._add_slider_in_frame(self.custom_hsv_section, "Sat Max", "custom_hsv_max_s", 0, 255,
                                  int(getattr(config, "custom_hsv_max_s", 255)),
                                  lambda v: self._on_custom_hsv_changed("custom_hsv_max_s", v))
        self._add_slider_in_frame(self.custom_hsv_section, "Val Max", "custom_hsv_max_v", 0, 255,
                                  int(getattr(config, "custom_hsv_max_v", 255)),
                                  lambda v: self._on_custom_hsv_changed("custom_hsv_max_v", v))

        self._update_custom_hsv_visibility()

        # 3. Detection & Morphological Filters Card
        self.card_contour_filters = ModernCard(
            self.content_frame,
            "Contour & Detection Filters",
            icon="🔍",
            badge_text="Pro",
            accent_color="#F59E0B"
        )
        self.card_contour_filters.pack(fill="x", pady=(0, 10))

        self._add_slider_in_frame(self.card_contour_filters.content, "Merge Distance", "detection_merge_distance", 50, 500,
                                  int(getattr(config, "detection_merge_distance", 250)),
                                  self._on_detection_merge_distance_changed)
        self._add_spacer_in_frame(self.card_contour_filters.content)
        self._add_slider_in_frame(self.card_contour_filters.content, "Min Contour Points", "detection_min_contour_points", 3, 100,
                                  int(getattr(config, "detection_min_contour_points", 5)),
                                  self._on_detection_min_contour_points_changed)

    def _show_general_tab(self):
        if self._ensure_pro_mode("General"):
            return
        self._active_tab_name = "Hardware"
        self._clear_content()
        if self._legacy_ui_mode:
            self._add_sub_nav_bar(
                ["Hardware & Capture", "Profiles & Config", "Debug & Telemetry"],
                "Hardware & Capture",
                {
                    "Hardware & Capture": self._show_general_tab,
                    "Profiles & Config": self._show_config_tab,
                    "Debug & Telemetry": self._show_debug_tab,
                }
            )
        self._add_title("Hardware & Capture Service")
        self._ignore_settings_events = True

        # -- HARDWARE API (ModernCard) --
        self.card_mouse_api = ModernCard(
            self.content_frame,
            "Hardware Device API",
            icon="⚡",
            badge_text="Device",
            accent_color="#10B981"
        )
        self.card_mouse_api.pack(fill="x", pady=(0, 10))
        sec_hardware = self.card_mouse_api.content
        self.var_auto_connect_mouse_api = tk.BooleanVar(value=bool(getattr(config, "auto_connect_mouse_api", False)))
        current_mouse_api = getattr(config, "mouse_api", "Serial")
        current_mouse_api_norm = str(current_mouse_api).strip().lower()
        if current_mouse_api_norm == "net":
            current_mouse_api = "Net"
        elif current_mouse_api_norm in ("kmboxa", "kmboxa_api", "kmboxaapi", "kma", "kmboxa-api"):
            current_mouse_api = "KmboxA"
        elif current_mouse_api_norm == "dhz":
            current_mouse_api = "DHZ"
        elif current_mouse_api_norm in ("makv2binary", "makv2_binary", "makv2-binary", "binary"):
            current_mouse_api = "MakV2Binary"
        elif current_mouse_api_norm in ("makxdmakapi", "makxd_makapi", "makxd-makapi", "makxd makapi", "makxd_mak", "makxd-mak"):
            current_mouse_api = "MakxdMakAPI"
        elif current_mouse_api_norm in ("makapi", "mak_api", "mak-api", "mak api"):
            current_mouse_api = "MAK API"
        elif current_mouse_api_norm in ("makv2", "mak_v2", "mak-v2"):
            current_mouse_api = "MakV2"
        elif current_mouse_api_norm in ("makcucontroller", "makcu_controller", "makcu-controller", "makcu controller"):
            current_mouse_api = "MakcuController"
        elif current_mouse_api_norm == "arduino":
            current_mouse_api = "Arduino"
        elif current_mouse_api_norm in ("sendinput", "win32", "win32api", "win32_sendinput", "win32-sendinput"):
            current_mouse_api = "SendInput"
        elif current_mouse_api_norm == "ferrum":
            current_mouse_api = "Ferrum"
        elif current_mouse_api_norm in ("medius", "k4tech", "k4"):
            current_mouse_api = "Medius"
        else:
            current_mouse_api = "Serial (Makcu)"
        self.saved_mouse_api = current_mouse_api

        keyboard_options = [
            "Follow Mouse API",
            "SendInput",
            "Serial (Makcu)",
            "Net",
            "KmboxA",
            "MakV2",
            "MakcuController",
            "MakxdMakAPI",
            "MAK API",
            "MakV2Binary",
            "DHZ",
            "Ferrum",
            "Medius",
        ]
        current_keyboard_api = str(getattr(config, "keyboard_api", "Follow Mouse API")).strip()
        normalized_keyboard_api = self._normalize_keyboard_api_name(current_keyboard_api)
        self.saved_keyboard_api_enabled = bool(
            getattr(config, "keyboard_api_enabled", self.saved_keyboard_api_enabled)
        )
        self.saved_keyboard_api = normalized_keyboard_api

        serial_mode = str(getattr(config, "serial_port_mode", self.saved_serial_port_mode)).strip().lower()
        self.saved_serial_port_mode = "Manual" if serial_mode == "manual" else "Auto"
        self.saved_serial_port = str(getattr(config, "serial_port", self.saved_serial_port))
        self.saved_serial_auto_switch_4m = bool(
            getattr(config, "serial_auto_switch_4m", self.saved_serial_auto_switch_4m)
        )
        self.saved_net_ip = getattr(config, "net_ip", self.saved_net_ip)
        self.saved_net_port = getattr(config, "net_port", self.saved_net_port)
        self.saved_net_uuid = getattr(config, "net_uuid", getattr(config, "net_mac", self.saved_net_uuid))
        self.saved_teleport_host = str(getattr(config, "teleport_host", self.saved_teleport_host))
        self.saved_teleport_port = str(getattr(config, "teleport_port", self.saved_teleport_port))
        self.saved_teleport_stream_key = str(
            getattr(config, "teleport_stream_key", self.saved_teleport_stream_key)
        )
        self.saved_kmboxa_vid_pid = str(
            getattr(
                config,
                "kmboxa_vid_pid",
                f"{getattr(config, 'kmboxa_vid', 0)}/{getattr(config, 'kmboxa_pid', 0)}",
            )
        )
        self.saved_arduino_port = str(getattr(config, "arduino_port", self.saved_arduino_port))
        self.saved_arduino_baud = str(getattr(config, "arduino_baud", self.saved_arduino_baud))
        self.saved_makv2_port = getattr(config, "makv2_port", self.saved_makv2_port)
        self.saved_makv2_baud = str(getattr(config, "makv2_baud", self.saved_makv2_baud))
        self.saved_makcu_controller_port = str(
            getattr(config, "makcu_controller_port", self.saved_makcu_controller_port)
        )
        self.saved_makcu_controller_baud = str(
            getattr(config, "makcu_controller_baud", self.saved_makcu_controller_baud)
        )
        self.saved_makxd_mak_port = str(getattr(config, "makxd_mak_port", self.saved_makxd_mak_port))
        self.saved_makxd_mak_baud = str(getattr(config, "makxd_mak_baud", self.saved_makxd_mak_baud))
        self.saved_mak_api_port = str(getattr(config, "mak_api_port", self.saved_mak_api_port))
        self.saved_mak_api_baud = str(getattr(config, "mak_api_baud", self.saved_mak_api_baud))
        self.saved_dhz_ip = getattr(config, "dhz_ip", self.saved_dhz_ip)
        self.saved_dhz_port = str(getattr(config, "dhz_port", self.saved_dhz_port))
        self.saved_dhz_random = str(getattr(config, "dhz_random", self.saved_dhz_random))
        self.saved_ferrum_device_path = str(getattr(config, "ferrum_device_path", self.saved_ferrum_device_path))
        self.saved_ferrum_connection_type = str(getattr(config, "ferrum_connection_type", self.saved_ferrum_connection_type))
        self.saved_ferrum_mode = str(getattr(config, "ferrum_mode", self.saved_ferrum_mode))
        self.saved_ferrum_net_ip = str(getattr(config, "ferrum_net_ip", self.saved_ferrum_net_ip))
        self.saved_ferrum_net_port = str(getattr(config, "ferrum_net_port", self.saved_ferrum_net_port))
        self.saved_ferrum_net_uuid = str(getattr(config, "ferrum_net_uuid", self.saved_ferrum_net_uuid))
        self.saved_ferrum_dhz_ip = str(getattr(config, "ferrum_dhz_ip", self.saved_ferrum_dhz_ip))
        self.saved_ferrum_dhz_port = str(getattr(config, "ferrum_dhz_port", self.saved_ferrum_dhz_port))
        self.saved_ferrum_dhz_random = str(getattr(config, "ferrum_dhz_random", self.saved_ferrum_dhz_random))
        self.saved_medius_port = str(getattr(config, "medius_port", self.saved_medius_port))
        self.saved_keyboard_ferrum_device_path = str(
            getattr(config, "keyboard_ferrum_device_path", self.saved_keyboard_ferrum_device_path)
        )
        self.saved_keyboard_ferrum_connection_type = str(
            getattr(config, "keyboard_ferrum_connection_type", self.saved_keyboard_ferrum_connection_type)
        )
        self.saved_keyboard_ferrum_mode = str(
            getattr(config, "keyboard_ferrum_mode", self.saved_keyboard_ferrum_mode)
        )
        self.saved_keyboard_ferrum_net_ip = str(
            getattr(config, "keyboard_ferrum_net_ip", self.saved_keyboard_ferrum_net_ip)
        )
        self.saved_keyboard_ferrum_net_port = str(
            getattr(config, "keyboard_ferrum_net_port", self.saved_keyboard_ferrum_net_port)
        )
        self.saved_keyboard_ferrum_net_uuid = str(
            getattr(config, "keyboard_ferrum_net_uuid", self.saved_keyboard_ferrum_net_uuid)
        )
        self.saved_keyboard_ferrum_dhz_ip = str(
            getattr(config, "keyboard_ferrum_dhz_ip", self.saved_keyboard_ferrum_dhz_ip)
        )
        self.saved_keyboard_ferrum_dhz_port = str(
            getattr(config, "keyboard_ferrum_dhz_port", self.saved_keyboard_ferrum_dhz_port)
        )
        self.saved_keyboard_ferrum_dhz_random = str(
            getattr(config, "keyboard_ferrum_dhz_random", self.saved_keyboard_ferrum_dhz_random)
        )
        self.saved_auto_connect_mouse_api = bool(getattr(config, "auto_connect_mouse_api", self.saved_auto_connect_mouse_api))

        self.mouse_hardware_frame = ctk.CTkFrame(
            sec_hardware,
            fg_color="transparent",
            corner_radius=8,
            border_width=1,
            border_color=COLOR_BORDER,
        )
        self.mouse_hardware_frame.pack(fill="x", pady=(2, 8))
        ctk.CTkLabel(
            self.mouse_hardware_frame,
            text=t("Mouse Connection"),
            font=("Segoe UI", 11, "bold"),
            text_color=COLOR_ACCENT,
            anchor="w",
        ).pack(fill="x", padx=12, pady=(10, 2))
        self.mouse_api_option = self._add_hardware_option_row_in_frame(
            self.mouse_hardware_frame,
            "Input API",
            ["Serial (Makcu)", "Arduino", "SendInput", "Net", "KmboxA", "MakV2", "MakcuController", "MakxdMakAPI", "MAK API", "MakV2Binary", "DHZ", "Ferrum", "Medius"],
            self._on_mouse_api_changed,
        )
        self.mouse_api_option.set(current_mouse_api)
        self._add_switch_in_frame(
            self.mouse_hardware_frame,
            "Auto Start On Startup",
            self.var_auto_connect_mouse_api,
            self._on_auto_connect_mouse_api_changed,
        )
        self.mouse_content_frame = ctk.CTkFrame(self.mouse_hardware_frame, fg_color="transparent")
        self.mouse_content_frame.pack(fill="x", padx=12, pady=(0, 10))

        self.keyboard_hardware_frame = ctk.CTkFrame(
            sec_hardware,
            fg_color="transparent",
            corner_radius=8,
            border_width=1,
            border_color=COLOR_BORDER,
        )
        self.keyboard_hardware_frame.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            self.keyboard_hardware_frame,
            text=t("Keyboard Connection"),
            font=("Segoe UI", 11, "bold"),
            text_color=COLOR_ACCENT,
            anchor="w",
        ).pack(fill="x", padx=12, pady=(10, 2))
        self.var_keyboard_api_enabled = tk.BooleanVar(value=self.saved_keyboard_api_enabled)
        self.keyboard_enable_checkbox = ctk.CTkCheckBox(
            self.keyboard_hardware_frame,
            text=t("Enable Keyboard API"),
            variable=self.var_keyboard_api_enabled,
            command=self._on_keyboard_api_enabled_changed,
            font=FONT_MAIN,
            text_color=COLOR_TEXT,
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            border_color=COLOR_HARDWARE_PANEL_BORDER,
            checkmark_color=COLOR_TEXT,
        )
        self.keyboard_enable_checkbox.pack(anchor="w", padx=12, pady=(0, 8))
        self.keyboard_api_option = self._add_hardware_option_row_in_frame(
            self.keyboard_hardware_frame,
            "Input API",
            keyboard_options,
            self._on_keyboard_api_changed,
        )
        self.keyboard_api_option.set(normalized_keyboard_api)
        ctk.CTkLabel(
            self.keyboard_hardware_frame,
            text="Keyboard API is independent for keybind state and keyboard output. SendInput works without changing the active mouse backend.",
            font=("Roboto", 9),
            text_color=COLOR_TEXT_DIM,
            justify="left",
            wraplength=720,
            anchor="w",
        ).pack(fill="x", padx=12, pady=(2, 8))
        self.keyboard_content_frame = ctk.CTkFrame(self.keyboard_hardware_frame, fg_color="transparent")
        self.keyboard_content_frame.pack(fill="x", padx=12, pady=(0, 10))

        self._update_mouse_api_ui()
        self._update_keyboard_api_ui()

        self.card_capture_service = ModernCard(
            self.content_frame,
            "Capture Service",
            icon="📷",
            badge_text="Video",
            accent_color="#06B6D4"
        )
        self.card_capture_service.pack(fill="x", pady=(0, 10))
        sec_capture = self.card_capture_service.content
        self.capture_settings_frame = sec_capture
        self.capture_method_var.set(self._capture_display_mode(self.capture.mode))
        self.capture_method_option = self._add_option_row_in_frame(
            sec_capture,
            "Method",
            ["NDI", "UDP", "Teleport", "Capture Card (OpenCV)", "Capture Card (GStreamer)", "MSS"],
            self._on_capture_method_changed,
        )
        self.capture_method_option.set(self._capture_display_mode(self.capture.mode))
        self._add_spacer_in_frame(sec_capture)
        self.capture_content_frame = ctk.CTkFrame(sec_capture, fg_color="transparent")
        self.capture_content_frame.pack(fill="x", pady=5)
        self._update_capture_ui()
        self._ignore_settings_events = False
        self._apply_runtime_settings_lock()

        # -- SETTINGS (collapsible) --
        sec_settings = self._create_collapsible_section(self.content_frame, "Settings", initially_open=True)
        
        # In-Game Sensitivity (闋愯ō 0.235, 绡勫湇 0.1-20)
        self._add_slider_in_frame(sec_settings, "In-Game Sensitivity", "in_game_sens", 0.1, 20, 
                        float(getattr(config, "in_game_sens", 0.235)), 
                        self._on_config_in_game_sens_changed, is_float=True)
        
        # MOUSE LOCK (collapsible)
        mouse_lock_tooltip_text = (
            "- Lock Main Aimbot X-Axis: Blocks physical mouse movement on X-axis when Main Aimbot is active. "
            "Only aimbot-controlled movements will be applied.\n\n"
            "- Lock Main Aimbot Y-Axis: Blocks physical mouse movement on Y-axis when Main Aimbot is active. "
            "Only aimbot-controlled movements will be applied.\n\n"
            "- Lock Sec Aimbot X-Axis: Blocks physical mouse movement on X-axis when Sec Aimbot is active. "
            "Only aimbot-controlled movements will be applied.\n\n"
            "- Lock Sec Aimbot Y-Axis: Blocks physical mouse movement on Y-axis when Sec Aimbot is active. "
            "Only aimbot-controlled movements will be applied.\n\n"
            "Note: The lock will automatically release when the aimbot button is released or aimbot stops moving."
        )
        sec_mouse_lock = self._create_collapsible_section(
            self.content_frame,
            "Mouse Lock",
            initially_open=False,
            tooltip_text=mouse_lock_tooltip_text
        )
        
        # Lock Main Aimbot X-Axis
        if not hasattr(self, 'var_mouse_lock_main_x'):
            self.var_mouse_lock_main_x = tk.BooleanVar(value=getattr(config, "mouse_lock_main_x", False))
        self._add_switch_in_frame(sec_mouse_lock, "Lock Main Aimbot X-Axis", self.var_mouse_lock_main_x, self._on_mouse_lock_main_x_changed)
        self._checkbox_vars["mouse_lock_main_x"] = self.var_mouse_lock_main_x
        
        # Lock Main Aimbot Y-Axis
        if not hasattr(self, 'var_mouse_lock_main_y'):
            self.var_mouse_lock_main_y = tk.BooleanVar(value=getattr(config, "mouse_lock_main_y", False))
        self._add_switch_in_frame(sec_mouse_lock, "Lock Main Aimbot Y-Axis", self.var_mouse_lock_main_y, self._on_mouse_lock_main_y_changed)
        self._checkbox_vars["mouse_lock_main_y"] = self.var_mouse_lock_main_y
        
        self._add_spacer_in_frame(sec_mouse_lock)
        
        # Lock Sec Aimbot X-Axis
        if not hasattr(self, 'var_mouse_lock_sec_x'):
            self.var_mouse_lock_sec_x = tk.BooleanVar(value=getattr(config, "mouse_lock_sec_x", False))
        self._add_switch_in_frame(sec_mouse_lock, "Lock Sec Aimbot X-Axis", self.var_mouse_lock_sec_x, self._on_mouse_lock_sec_x_changed)
        self._checkbox_vars["mouse_lock_sec_x"] = self.var_mouse_lock_sec_x
        
        # Lock Sec Aimbot Y-Axis
        if not hasattr(self, 'var_mouse_lock_sec_y'):
            self.var_mouse_lock_sec_y = tk.BooleanVar(value=getattr(config, "mouse_lock_sec_y", False))
        self._add_switch_in_frame(sec_mouse_lock, "Lock Sec Aimbot Y-Axis", self.var_mouse_lock_sec_y, self._on_mouse_lock_sec_y_changed)
        self._checkbox_vars["mouse_lock_sec_y"] = self.var_mouse_lock_sec_y
        
        # 鈹€鈹€ BUTTON MASK (collapsible) 鈹€鈹€
        sec_button_mask = self._create_collapsible_section(self.content_frame, "Button Mask", initially_open=False)
        
        # Button Mask 绺介枊闂?
        if not hasattr(self, 'var_button_mask_enabled'):
            self.var_button_mask_enabled = tk.BooleanVar(value=getattr(config, "button_mask_enabled", False))
        
        master_switch = ctk.CTkSwitch(
            sec_button_mask,
            text="Enable Button Mask",
            variable=self.var_button_mask_enabled,
            command=self._on_button_mask_enabled_changed,
            fg_color=COLOR_SURFACE,
            progress_color=COLOR_ACCENT,
            button_color=COLOR_ACCENT,
            button_hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT_DIM,
            font=("Roboto", 11),
            width=80,
            height=20
        )
        master_switch.pack(fill="x", pady=(5, 10))
        self._checkbox_vars["button_mask_enabled"] = self.var_button_mask_enabled
        
        # Grid for individual buttons
        grid_frame = ctk.CTkFrame(sec_button_mask, fg_color="transparent")
        grid_frame.pack(fill="x", pady=(0, 5))
        
        # Configure grid columns
        grid_frame.grid_columnconfigure(0, weight=1)
        grid_frame.grid_columnconfigure(1, weight=1)
        grid_frame.grid_columnconfigure(2, weight=1)
        
        button_masks = [
            ("L-Click", "mask_left_button", 0, 0),
            ("R-Click", "mask_right_button", 0, 1),
            ("M-Click", "mask_middle_button", 0, 2),
            ("Side 4", "mask_side4_button", 1, 0),
            ("Side 5", "mask_side5_button", 1, 1),
        ]
        
        for label, key, row, col in button_masks:
            var_name = f"var_{key}"
            if not hasattr(self, var_name):
                var = tk.BooleanVar(value=getattr(config, key, False))
                setattr(self, var_name, var)
            else:
                var = getattr(self, var_name)
            
            # 浣跨敤鏇寸啊绱勭殑 Switch 棰ㄦ牸
            btn_switch = ctk.CTkSwitch(
                grid_frame,
                text=label,
                variable=var,
                command=lambda k=key, v=var: self._on_button_mask_changed(k, v),
                fg_color=COLOR_SURFACE,
                progress_color=COLOR_ACCENT,
                button_color=COLOR_ACCENT,
                button_hover_color=COLOR_ACCENT_HOVER,
                text_color=COLOR_TEXT_DIM,
                font=("Roboto", 10),
                height=18,
                width=30, # Smaller switch width
                switch_width=30,
                switch_height=16
            )
            btn_switch.grid(row=row, column=col, sticky="w", padx=5, pady=6)
            self._checkbox_vars[key] = var

    def _update_mouse_api_ui(self):
        """鏍规摎閬告搰鐨勬粦榧?API 鏇存柊 Hardware API 鍗€濉娿€?"""
        if not hasattr(self, "mouse_content_frame") or not self.mouse_content_frame.winfo_exists():
            return

        for widget in self.mouse_content_frame.winfo_children():
            widget.destroy()

        mode = "Serial"
        if hasattr(self, "mouse_api_option") and self.mouse_api_option.winfo_exists():
            mode = self.mouse_api_option.get()
        mode_norm = str(mode).strip().lower()
        if mode_norm == "net":
            mode = "Net"
        elif mode_norm in ("kmboxa", "kmboxa_api", "kmboxaapi", "kma", "kmboxa-api"):
            mode = "KmboxA"
        elif mode_norm == "dhz":
            mode = "DHZ"
        elif mode_norm in ("makxdmakapi", "makxd_makapi", "makxd-makapi", "makxd makapi", "makxd_mak", "makxd-mak"):
            mode = "MakxdMakAPI"
        elif mode_norm in ("makapi", "mak_api", "mak-api", "mak api"):
            mode = "MakAPI"
        elif mode_norm in ("makv2binary", "makv2_binary", "makv2-binary", "binary"):
            mode = "MakV2Binary"
        elif mode_norm in ("makv2", "mak_v2", "mak-v2"):
            mode = "MakV2"
        elif mode_norm in ("makcucontroller", "makcu_controller", "makcu-controller", "makcu controller"):
            mode = "MakcuController"
        elif mode_norm == "arduino":
            mode = "Arduino"
        elif mode_norm in ("sendinput", "win32", "win32api", "win32_sendinput", "win32-sendinput"):
            mode = "SendInput"
        elif mode_norm == "ferrum":
            mode = "Ferrum"
        elif mode_norm in ("medius", "k4tech", "k4"):
            mode = "Medius"
        elif mode_norm in ("serial (makcu)", "serial", "makcu"):
            mode = "Serial"
        else:
            mode = "Serial"
        self.saved_mouse_api = mode
        config.mouse_api = mode

        if mode == "Serial":
            tip = ctk.CTkLabel(
                self.mouse_content_frame,
                text="Serial API (MAKCU/CH34x)",
                font=("Roboto", 10),
                text_color=COLOR_TEXT_DIM,
            )
            tip.pack(anchor="w", pady=(0, 8))

            mode_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            mode_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(mode_frame, text="COM Mode", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.serial_mode_option = self._add_hardware_option_menu(
                ["Auto", "Manual"],
                self._on_serial_mode_selected,
                parent=mode_frame,
            )
            self.serial_mode_option.pack(side="right")
            current_serial_mode = "Manual" if str(self.saved_serial_port_mode).strip().lower() == "manual" else "Auto"
            self.saved_serial_port_mode = current_serial_mode
            self.serial_mode_option.set(current_serial_mode)

            if current_serial_mode == "Manual":
                port_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
                port_frame.pack(fill="x", pady=3)
                ctk.CTkLabel(port_frame, text="COM Port", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
                self.serial_port_entry = self._create_hardware_entry(port_frame)
                self.serial_port_entry.pack(side="right")
                self.serial_port_entry.insert(0, self.saved_serial_port)
                self.serial_port_entry.bind("<KeyRelease>", self._on_serial_port_changed)
                self.serial_port_entry.bind("<FocusOut>", self._on_serial_port_changed)

            self.var_serial_auto_switch_4m = tk.BooleanVar(value=bool(self.saved_serial_auto_switch_4m))
            self._add_switch_in_frame(
                self.mouse_content_frame,
                "Auto Switch Serial to 4M On Startup",
                self.var_serial_auto_switch_4m,
                self._on_serial_auto_switch_4m_changed,
            )

            btn_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            btn_frame.pack(fill="x", pady=5)
            self._add_hardware_action_button(btn_frame, "TEST MOVE", self._test_mouse_move).pack(side="left")
            self._add_hardware_action_button(btn_frame, "SWITCH TO 4M", self._switch_serial_to_4m).pack(side="left", padx=12)
            return

        if mode == "Arduino":
            tip = ctk.CTkLabel(
                self.mouse_content_frame,
                text="Arduino API (serial c/p/r/mX,Y newline protocol)",
                font=("Roboto", 10),
                text_color=COLOR_TEXT_DIM,
            )
            tip.pack(anchor="w", pady=(0, 8))

            port_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            port_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(port_frame, text="COM Port (optional)", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.arduino_port_entry = self._create_hardware_entry(port_frame)
            self.arduino_port_entry.pack(side="right")
            self.arduino_port_entry.insert(0, self.saved_arduino_port)
            self.arduino_port_entry.bind("<KeyRelease>", self._on_arduino_port_changed)
            self.arduino_port_entry.bind("<FocusOut>", self._on_arduino_port_changed)

            baud_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            baud_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(baud_frame, text="Baud", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.arduino_baud_entry = self._create_hardware_entry(baud_frame)
            self.arduino_baud_entry.pack(side="right")
            self.arduino_baud_entry.insert(0, self.saved_arduino_baud)
            self.arduino_baud_entry.bind("<KeyRelease>", self._on_arduino_baud_changed)
            self.arduino_baud_entry.bind("<FocusOut>", self._on_arduino_baud_changed)

            btn_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            btn_frame.pack(fill="x", pady=8)
            self._add_hardware_action_button(btn_frame, "TEST MOVE", self._test_mouse_move).pack(side="left")
            return

        if mode == "SendInput":
            tip = ctk.CTkLabel(
                self.mouse_content_frame,
                text="Win32 SendInput API (software injection, no COM needed)",
                font=("Roboto", 10),
                text_color=COLOR_TEXT_DIM,
            )
            tip.pack(anchor="w", pady=(0, 8))

            sendinput_notice = ctk.CTkLabel(
                self.mouse_content_frame,
                text="For dual-PC streaming setups (e.g., Moonlight).",
                font=("Roboto", 10, "bold"),
                text_color=COLOR_DANGER,
            )
            sendinput_notice.pack(anchor="w", pady=(0, 8))

            btn_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            btn_frame.pack(fill="x", pady=8)
            self._add_hardware_action_button(btn_frame, "TEST MOVE", self._test_mouse_move).pack(side="left")
            return

        if mode == "MakV2Binary":
            tip = ctk.CTkLabel(
                self.mouse_content_frame,
                text="MakV2 Binary API",
                font=("Roboto", 10),
                text_color=COLOR_TEXT_DIM,
            )
            tip.pack(anchor="w", pady=(0, 8))
            btn_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            btn_frame.pack(fill="x", pady=8)
            self._add_hardware_action_button(btn_frame, "TEST MOVE", self._test_mouse_move).pack(side="left")
            return

        if mode == "MakV2":
            tip = ctk.CTkLabel(
                self.mouse_content_frame,
                text="MakV2 API (ASCII km.* commands over serial)",
                font=("Roboto", 10),
                text_color=COLOR_TEXT_DIM,
            )
            tip.pack(anchor="w", pady=(0, 8))

            port_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            port_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(port_frame, text="Port (optional)", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.makv2_port_entry = self._create_hardware_entry(port_frame)
            self.makv2_port_entry.pack(side="right")
            self.makv2_port_entry.insert(0, self.saved_makv2_port)
            self.makv2_port_entry.bind("<KeyRelease>", self._on_makv2_port_changed)
            self.makv2_port_entry.bind("<FocusOut>", self._on_makv2_port_changed)

            baud_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            baud_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(baud_frame, text="Baud", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.makv2_baud_entry = self._create_hardware_entry(baud_frame)
            self.makv2_baud_entry.pack(side="right")
            self.makv2_baud_entry.insert(0, self.saved_makv2_baud)
            self.makv2_baud_entry.bind("<KeyRelease>", self._on_makv2_baud_changed)
            self.makv2_baud_entry.bind("<FocusOut>", self._on_makv2_baud_changed)

            btn_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            btn_frame.pack(fill="x", pady=8)
            self._add_hardware_action_button(btn_frame, "TEST MOVE", self._test_mouse_move).pack(side="left")
            return

        if mode == "MakcuController":
            tip = ctk.CTkLabel(
                self.mouse_content_frame,
                text="MakcuController API (serial ctl.stick / ctl.clear / ctl.state)",
                font=("Roboto", 10),
                text_color=COLOR_TEXT_DIM,
            )
            tip.pack(anchor="w", pady=(0, 8))

            notice = ctk.CTkLabel(
                self.mouse_content_frame,
                text="Movement uses controller stick output; click and keyboard output use local SendInput fallback.",
                font=("Roboto", 9),
                text_color=COLOR_TEXT_DIM,
            )
            notice.pack(anchor="w", pady=(0, 8))

            port_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            port_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(port_frame, text="Port (optional)", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.makcu_controller_port_entry = self._create_hardware_entry(port_frame)
            self.makcu_controller_port_entry.pack(side="right")
            self.makcu_controller_port_entry.insert(0, self.saved_makcu_controller_port)
            self.makcu_controller_port_entry.bind("<KeyRelease>", self._on_makcu_controller_port_changed)
            self.makcu_controller_port_entry.bind("<FocusOut>", self._on_makcu_controller_port_changed)

            baud_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            baud_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(baud_frame, text="Baud", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.makcu_controller_baud_entry = self._create_hardware_entry(baud_frame)
            self.makcu_controller_baud_entry.pack(side="right")
            self.makcu_controller_baud_entry.insert(0, self.saved_makcu_controller_baud)
            self.makcu_controller_baud_entry.bind("<KeyRelease>", self._on_makcu_controller_baud_changed)
            self.makcu_controller_baud_entry.bind("<FocusOut>", self._on_makcu_controller_baud_changed)

            btn_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            btn_frame.pack(fill="x", pady=8)
            self._add_hardware_action_button(btn_frame, "TEST MOVE", self._test_mouse_move).pack(side="left")
            return

        if mode == "MakxdMakAPI":
            tip = ctk.CTkLabel(
                self.mouse_content_frame,
                text="Makxd_Mak API (serial binary opcode protocol)",
                font=("Roboto", 10),
                text_color=COLOR_TEXT_DIM,
            )
            tip.pack(anchor="w", pady=(0, 8))

            notice = ctk.CTkLabel(
                self.mouse_content_frame,
                text="Implements the MAKXD binary surface documented in Makxd_MakAPI.md.",
                font=("Roboto", 9),
                text_color=COLOR_TEXT_DIM,
            )
            notice.pack(anchor="w", pady=(0, 8))

            port_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            port_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(port_frame, text="Port (optional)", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.makxd_mak_port_entry = self._create_hardware_entry(port_frame)
            self.makxd_mak_port_entry.pack(side="right")
            self.makxd_mak_port_entry.insert(0, self.saved_makxd_mak_port)
            self.makxd_mak_port_entry.bind("<KeyRelease>", self._on_makxd_mak_port_changed)
            self.makxd_mak_port_entry.bind("<FocusOut>", self._on_makxd_mak_port_changed)

            baud_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            baud_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(baud_frame, text="Baud", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.makxd_mak_baud_entry = self._create_hardware_entry(baud_frame)
            self.makxd_mak_baud_entry.pack(side="right")
            self.makxd_mak_baud_entry.insert(0, self.saved_makxd_mak_baud)
            self.makxd_mak_baud_entry.bind("<KeyRelease>", self._on_makxd_mak_baud_changed)
            self.makxd_mak_baud_entry.bind("<FocusOut>", self._on_makxd_mak_baud_changed)

            btn_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            btn_frame.pack(fill="x", pady=8)
            self._add_hardware_action_button(btn_frame, "TEST MOVE", self._test_mouse_move).pack(side="left")
            return

        if mode == "DHZ":
            tip = ctk.CTkLabel(
                self.mouse_content_frame,
                text="DHZ API (UDP + Caesar-shift command protocol)",
                font=("Roboto", 10),
                text_color=COLOR_TEXT_DIM,
            )
            tip.pack(anchor="w", pady=(0, 8))

            ip_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            ip_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(ip_frame, text="IP Address", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.dhz_ip_entry = self._create_hardware_entry(ip_frame)
            self.dhz_ip_entry.pack(side="right")
            self.dhz_ip_entry.insert(0, self.saved_dhz_ip)
            self.dhz_ip_entry.bind("<KeyRelease>", self._on_dhz_ip_changed)
            self.dhz_ip_entry.bind("<FocusOut>", self._on_dhz_ip_changed)

            port_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            port_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(port_frame, text="Port", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.dhz_port_entry = self._create_hardware_entry(port_frame)
            self.dhz_port_entry.pack(side="right")
            self.dhz_port_entry.insert(0, self.saved_dhz_port)
            self.dhz_port_entry.bind("<KeyRelease>", self._on_dhz_port_changed)
            self.dhz_port_entry.bind("<FocusOut>", self._on_dhz_port_changed)

            random_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            random_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(random_frame, text="Random Shift", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.dhz_random_entry = self._create_hardware_entry(random_frame)
            self.dhz_random_entry.pack(side="right")
            self.dhz_random_entry.insert(0, self.saved_dhz_random)
            self.dhz_random_entry.bind("<KeyRelease>", self._on_dhz_random_changed)
            self.dhz_random_entry.bind("<FocusOut>", self._on_dhz_random_changed)

            btn_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            btn_frame.pack(fill="x", pady=8)
            self._add_hardware_action_button(btn_frame, "TEST MOVE", self._test_mouse_move).pack(side="left")
            return

        if mode == "Ferrum":
            tip = ctk.CTkLabel(
                self.mouse_content_frame,
                text="Ferrum multi-mode backend",
                font=("Roboto", 10),
                text_color=COLOR_TEXT_DIM,
            )
            tip.pack(anchor="w", pady=(0, 8))

            mode_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            mode_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(mode_frame, text="Ferrum Mode", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.ferrum_mode_option = self._add_hardware_option_menu(
                ["KmAPI", "NetAPI", "DhzAPI"],
                self._on_ferrum_mode_selected,
                parent=mode_frame,
            )
            self.ferrum_mode_option.pack(side="right")
            if self.saved_ferrum_mode not in ("KmAPI", "NetAPI", "DhzAPI"):
                self.saved_ferrum_mode = "KmAPI"
            self.ferrum_mode_option.set(self.saved_ferrum_mode)

            ferrum_mode = self.saved_ferrum_mode
            if ferrum_mode == "NetAPI":
                ip_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
                ip_frame.pack(fill="x", pady=3)
                ctk.CTkLabel(ip_frame, text="IP Address", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
                self.ferrum_net_ip_entry = self._create_hardware_entry(ip_frame)
                self.ferrum_net_ip_entry.pack(side="right")
                self.ferrum_net_ip_entry.insert(0, self.saved_ferrum_net_ip)
                self.ferrum_net_ip_entry.bind("<KeyRelease>", self._on_ferrum_net_ip_changed)
                self.ferrum_net_ip_entry.bind("<FocusOut>", self._on_ferrum_net_ip_changed)

                port_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
                port_frame.pack(fill="x", pady=3)
                ctk.CTkLabel(port_frame, text="Port", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
                self.ferrum_net_port_entry = self._create_hardware_entry(port_frame)
                self.ferrum_net_port_entry.pack(side="right")
                self.ferrum_net_port_entry.insert(0, self.saved_ferrum_net_port)
                self.ferrum_net_port_entry.bind("<KeyRelease>", self._on_ferrum_net_port_changed)
                self.ferrum_net_port_entry.bind("<FocusOut>", self._on_ferrum_net_port_changed)

                uuid_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
                uuid_frame.pack(fill="x", pady=3)
                ctk.CTkLabel(uuid_frame, text="UUID", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
                self.ferrum_net_uuid_entry = self._create_hardware_entry(uuid_frame)
                self.ferrum_net_uuid_entry.pack(side="right")
                self.ferrum_net_uuid_entry.insert(0, self.saved_ferrum_net_uuid)
                self.ferrum_net_uuid_entry.bind("<KeyRelease>", self._on_ferrum_net_uuid_changed)
                self.ferrum_net_uuid_entry.bind("<FocusOut>", self._on_ferrum_net_uuid_changed)
            elif ferrum_mode == "DhzAPI":
                ip_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
                ip_frame.pack(fill="x", pady=3)
                ctk.CTkLabel(ip_frame, text="IP Address", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
                self.ferrum_dhz_ip_entry = self._create_hardware_entry(ip_frame)
                self.ferrum_dhz_ip_entry.pack(side="right")
                self.ferrum_dhz_ip_entry.insert(0, self.saved_ferrum_dhz_ip)
                self.ferrum_dhz_ip_entry.bind("<KeyRelease>", self._on_ferrum_dhz_ip_changed)
                self.ferrum_dhz_ip_entry.bind("<FocusOut>", self._on_ferrum_dhz_ip_changed)

                port_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
                port_frame.pack(fill="x", pady=3)
                ctk.CTkLabel(port_frame, text="Port", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
                self.ferrum_dhz_port_entry = self._create_hardware_entry(port_frame)
                self.ferrum_dhz_port_entry.pack(side="right")
                self.ferrum_dhz_port_entry.insert(0, self.saved_ferrum_dhz_port)
                self.ferrum_dhz_port_entry.bind("<KeyRelease>", self._on_ferrum_dhz_port_changed)
                self.ferrum_dhz_port_entry.bind("<FocusOut>", self._on_ferrum_dhz_port_changed)

                random_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
                random_frame.pack(fill="x", pady=3)
                ctk.CTkLabel(random_frame, text="Random Shift", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
                self.ferrum_dhz_random_entry = self._create_hardware_entry(random_frame)
                self.ferrum_dhz_random_entry.pack(side="right")
                self.ferrum_dhz_random_entry.insert(0, self.saved_ferrum_dhz_random)
                self.ferrum_dhz_random_entry.bind("<KeyRelease>", self._on_ferrum_dhz_random_changed)
                self.ferrum_dhz_random_entry.bind("<FocusOut>", self._on_ferrum_dhz_random_changed)
            else:
                port_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
                port_frame.pack(fill="x", pady=3)
                ctk.CTkLabel(port_frame, text="COM Port (optional)", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
                self.ferrum_device_path_entry = self._create_hardware_entry(port_frame)
                self.ferrum_device_path_entry.pack(side="right")
                self.ferrum_device_path_entry.insert(0, self.saved_ferrum_device_path)
                self.ferrum_device_path_entry.bind("<KeyRelease>", self._on_ferrum_device_path_changed)
                self.ferrum_device_path_entry.bind("<FocusOut>", self._on_ferrum_device_path_changed)

                notice = ctk.CTkLabel(
                    self.mouse_content_frame,
                    text="KmAPI over serial. Leave port empty for auto-detection. Tries baud rates: 115200, 9600, 38400, 57600",
                    font=("Roboto", 9),
                    text_color=COLOR_TEXT_DIM,
                )
                notice.pack(anchor="w", pady=(0, 8))

            btn_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            btn_frame.pack(fill="x", pady=8)
            self._add_hardware_action_button(btn_frame, "TEST MOVE", self._test_mouse_move).pack(side="left")
            return

        if mode == "Medius":
            tip = ctk.CTkLabel(
                self.mouse_content_frame,
                text="Medius box (pip install medius) — control-port injection to the clone/game PC",
                font=("Roboto", 10),
                text_color=COLOR_TEXT_DIM,
            )
            tip.pack(anchor="w", pady=(0, 8))

            port_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            port_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(port_frame, text="COM Port (optional)", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.medius_port_entry = self._create_hardware_entry(port_frame)
            self.medius_port_entry.pack(side="right")
            self.medius_port_entry.insert(0, self.saved_medius_port)
            self.medius_port_entry.bind("<KeyRelease>", self._on_medius_port_changed)
            self.medius_port_entry.bind("<FocusOut>", self._on_medius_port_changed)

            notice = ctk.CTkLabel(
                self.mouse_content_frame,
                text="Leave port empty to auto-find the first Medius box. Windows example: COM3",
                font=("Roboto", 9),
                text_color=COLOR_TEXT_DIM,
            )
            notice.pack(anchor="w", pady=(0, 8))

            btn_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            btn_frame.pack(fill="x", pady=8)
            self._add_hardware_action_button(btn_frame, "TEST MOVE", self._test_mouse_move).pack(side="left")
            self._add_hardware_action_button(btn_frame, "REFRESH PORTS", self._refresh_medius_ports).pack(side="left", padx=12)
            return

        if mode == "MakAPI":
            tip = ctk.CTkLabel(
                self.mouse_content_frame,
                text="MAK API (official DE AD binary frames over serial, not km.* ASCII)",
                font=("Roboto", 10),
                text_color=COLOR_TEXT_DIM,
            )
            tip.pack(anchor="w", pady=(0, 8))

            port_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            port_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(port_frame, text="COM Port (optional)", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.mak_api_port_entry = self._create_hardware_entry(port_frame)
            self.mak_api_port_entry.pack(side="right")
            self.mak_api_port_entry.insert(0, self.saved_mak_api_port)
            self.mak_api_port_entry.bind("<KeyRelease>", self._on_mak_api_port_changed)
            self.mak_api_port_entry.bind("<FocusOut>", self._on_mak_api_port_changed)

            baud_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            baud_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(baud_frame, text="Baud (0 = auto)", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.mak_api_baud_entry = self._create_hardware_entry(baud_frame)
            self.mak_api_baud_entry.pack(side="right")
            self.mak_api_baud_entry.insert(0, self.saved_mak_api_baud)
            self.mak_api_baud_entry.bind("<KeyRelease>", self._on_mak_api_baud_changed)
            self.mak_api_baud_entry.bind("<FocusOut>", self._on_mak_api_baud_changed)

            notice = ctk.CTkLabel(
                self.mouse_content_frame,
                text="Leave port empty to auto-find CH343/CH340 (VID 1A86). Baud 0 tries 115200, 1M, then 4M.",
                font=("Roboto", 9),
                text_color=COLOR_TEXT_DIM,
            )
            notice.pack(anchor="w", pady=(0, 8))

            btn_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            btn_frame.pack(fill="x", pady=8)
            self._add_hardware_action_button(btn_frame, "TEST MOVE", self._test_mouse_move).pack(side="left")
            self._add_hardware_action_button(btn_frame, "REFRESH PORTS", self._refresh_mak_api_ports).pack(side="left", padx=12)
            return

        if mode == "KmboxA":
            dll_name = "kmA.pyd"
            try:
                from src.utils.mouse import get_expected_kmboxa_dll_name

                dll_name = get_expected_kmboxa_dll_name()
            except Exception:
                pass

            tip = ctk.CTkLabel(
                self.mouse_content_frame,
                text=f"KmboxA API auto DLL by Python version: {dll_name}",
                font=("Roboto", 10),
                text_color=COLOR_TEXT_DIM,
            )
            tip.pack(anchor="w", pady=(0, 8))

            vid_pid_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            vid_pid_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(vid_pid_frame, text="VID/PID", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.kmboxa_vid_pid_entry = self._create_hardware_entry(vid_pid_frame)
            self.kmboxa_vid_pid_entry.pack(side="right")
            self.kmboxa_vid_pid_entry.insert(0, self.saved_kmboxa_vid_pid)
            self.kmboxa_vid_pid_entry.bind("<KeyRelease>", self._on_kmboxa_vid_pid_changed)
            self.kmboxa_vid_pid_entry.bind("<FocusOut>", self._on_kmboxa_vid_pid_changed)

            btn_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
            btn_frame.pack(fill="x", pady=8)
            self._add_hardware_action_button(btn_frame, "TEST MOVE", self._test_mouse_move).pack(side="left")
            return

        # Net API controls
        dll_name = "kmNet.pyd"
        try:
            from src.utils.mouse import get_expected_kmnet_dll_name

            dll_name = get_expected_kmnet_dll_name()
        except Exception:
            pass

        tip = ctk.CTkLabel(
            self.mouse_content_frame,
            text=f"Net API auto DLL by Python version: {dll_name}",
            font=("Roboto", 10),
            text_color=COLOR_TEXT_DIM,
        )
        tip.pack(anchor="w", pady=(0, 8))

        ip_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
        ip_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(ip_frame, text="IP Address", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
        self.net_ip_entry = self._create_hardware_entry(ip_frame)
        self.net_ip_entry.pack(side="right")
        self.net_ip_entry.insert(0, self.saved_net_ip)
        self.net_ip_entry.bind("<KeyRelease>", self._on_net_ip_changed)
        self.net_ip_entry.bind("<FocusOut>", self._on_net_ip_changed)

        port_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
        port_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(port_frame, text="Port", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
        self.net_port_entry = self._create_hardware_entry(port_frame)
        self.net_port_entry.pack(side="right")
        self.net_port_entry.insert(0, self.saved_net_port)
        self.net_port_entry.bind("<KeyRelease>", self._on_net_port_changed)
        self.net_port_entry.bind("<FocusOut>", self._on_net_port_changed)

        uuid_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
        uuid_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(uuid_frame, text="UUID", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
        self.net_uuid_entry = self._create_hardware_entry(uuid_frame)
        self.net_uuid_entry.pack(side="right")
        self.net_uuid_entry.insert(0, self.saved_net_uuid)
        self.net_uuid_entry.bind("<KeyRelease>", self._on_net_uuid_changed)
        self.net_uuid_entry.bind("<FocusOut>", self._on_net_uuid_changed)

        btn_frame = ctk.CTkFrame(self.mouse_content_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=8)
        self._add_hardware_action_button(btn_frame, "TEST MOVE", self._test_mouse_move).pack(side="left")
        self._apply_runtime_settings_lock()

    def _on_mouse_api_changed(self, val):
        if getattr(self, "_ignore_settings_events", False):
            return
        if self._runtime_settings_locked():
            self._restore_locked_mouse_api_option()
            self._warn_runtime_settings_locked("hardware")
            return
        mode_norm = str(val).strip().lower()
        if mode_norm == "net":
            self.saved_mouse_api = "Net"
        elif mode_norm in ("kmboxa", "kmboxa_api", "kmboxaapi", "kma", "kmboxa-api"):
            self.saved_mouse_api = "KmboxA"
        elif mode_norm == "dhz":
            self.saved_mouse_api = "DHZ"
        elif mode_norm in ("makxdmakapi", "makxd_makapi", "makxd-makapi", "makxd makapi", "makxd_mak", "makxd-mak"):
            self.saved_mouse_api = "MakxdMakAPI"
        elif mode_norm in ("makapi", "mak_api", "mak-api", "mak api"):
            self.saved_mouse_api = "MakAPI"
        elif mode_norm in ("makv2binary", "makv2_binary", "makv2-binary", "binary"):
            self.saved_mouse_api = "MakV2Binary"
        elif mode_norm in ("makv2", "mak_v2", "mak-v2"):
            self.saved_mouse_api = "MakV2"
        elif mode_norm in ("makcucontroller", "makcu_controller", "makcu-controller", "makcu controller"):
            self.saved_mouse_api = "MakcuController"
        elif mode_norm == "arduino":
            self.saved_mouse_api = "Arduino"
        elif mode_norm in ("sendinput", "win32", "win32api", "win32_sendinput", "win32-sendinput"):
            self.saved_mouse_api = "SendInput"
        elif mode_norm == "ferrum":
            self.saved_mouse_api = "Ferrum"
        elif mode_norm in ("medius", "k4tech", "k4"):
            self.saved_mouse_api = "Medius"
        else:
            self.saved_mouse_api = "Serial"
        config.mouse_api = self.saved_mouse_api
        if not self._supports_trigger_strafe_ui(self.saved_mouse_api):
            config.trigger_strafe_mode = "off"
        self.saved_auto_connect_mouse_api = bool(getattr(config, "auto_connect_mouse_api", self.saved_auto_connect_mouse_api))
        self.saved_serial_auto_switch_4m = bool(
            getattr(config, "serial_auto_switch_4m", self.saved_serial_auto_switch_4m)
        )
        # Cancel any in-flight connect request to avoid stale success callback after mode switch.
        self._mouse_api_connect_job_id += 1
        self._invalidate_runtime()
        try:
            from src.utils import mouse as mouse_backend

            mouse_backend.disconnect_all(selected_mode=self.saved_mouse_api)
        except Exception:
            pass
        try:
            self.capture.disconnect()
        except Exception:
            pass
        self._update_mouse_api_ui()
        self._update_keyboard_api_ui()
        self._apply_runtime_settings_lock()
        self._set_status_indicator(f"Status: Mouse API {self.saved_mouse_api} selected", COLOR_TEXT_DIM)
        self._update_hardware_status_ui()

    def _on_keyboard_api_changed(self, val):
        if getattr(self, "_ignore_settings_events", False):
            return
        if self._runtime_settings_locked():
            self._restore_locked_keyboard_api_option()
            self._warn_runtime_settings_locked("hardware")
            self._apply_runtime_settings_lock()
            return
        normalized = self._normalize_keyboard_api_name(val)
        self.saved_keyboard_api = normalized
        config.keyboard_api = normalized
        self._set_status_indicator(f"Status: Keyboard API {normalized} selected", COLOR_TEXT_DIM)
        self._update_keyboard_api_ui()
        self._update_hardware_status_ui()

        if str(getattr(self, "_active_tab_name", "")) == "Trigger":
            self._show_tb_tab()

    def _on_keyboard_api_enabled_changed(self):
        if getattr(self, "_ignore_settings_events", False):
            return
        if self._runtime_settings_locked():
            self._ignore_settings_events = True
            try:
                self.var_keyboard_api_enabled.set(bool(getattr(config, "keyboard_api_enabled", False)))
            except Exception:
                pass
            self._ignore_settings_events = False
            self._warn_runtime_settings_locked("hardware")
            self._apply_runtime_settings_lock()
            return
        enabled = bool(self.var_keyboard_api_enabled.get())
        self.saved_keyboard_api_enabled = enabled
        config.keyboard_api_enabled = enabled
        if enabled:
            self._set_status_indicator("Status: Keyboard API enabled", COLOR_TEXT_DIM)
        else:
            self._set_status_indicator("Status: Keyboard API disabled; mouse-only input active", COLOR_TEXT_DIM)
        self._update_keyboard_api_ui()
        self._update_hardware_status_ui()

        if str(getattr(self, "_active_tab_name", "")) == "Trigger":
            self._show_tb_tab()

    def _update_keyboard_api_ui(self):
        if not hasattr(self, "keyboard_content_frame") or not self.keyboard_content_frame.winfo_exists():
            return

        for widget in self.keyboard_content_frame.winfo_children():
            widget.destroy()

        keyboard_enabled = bool(getattr(config, "keyboard_api_enabled", False))

        if hasattr(self, "keyboard_api_option") and self.keyboard_api_option.winfo_exists():
            self.keyboard_api_option.configure(state="normal" if keyboard_enabled else "disabled")

        if not keyboard_enabled:
            ctk.CTkLabel(
                self.keyboard_content_frame,
                text="Keyboard API is disabled. Keybind capture and hardware keyboard output use mouse-only mode until this checkbox is enabled.",
                font=("Roboto", 9),
                text_color=COLOR_TEXT_DIM,
                justify="left",
                wraplength=720,
                anchor="w",
            ).pack(fill="x", pady=(0, 2))
            self._apply_runtime_settings_lock()
            return

        selected_keyboard_api = self._normalize_keyboard_api_name(
            getattr(self, "saved_keyboard_api", getattr(config, "keyboard_api", "Follow Mouse API"))
        )
        mouse_api = self._normalize_mouse_api_name(getattr(config, "mouse_api", "Serial"))
        resolved_keyboard_api = mouse_api if selected_keyboard_api == "Follow Mouse API" else selected_keyboard_api

        ctk.CTkLabel(
            self.keyboard_content_frame,
            text=f"Selected: {selected_keyboard_api}",
            font=("Roboto", 10),
            text_color=COLOR_TEXT_DIM,
            anchor="w",
        ).pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            self.keyboard_content_frame,
            text=f"Resolved backend: {resolved_keyboard_api}",
            font=("Roboto", 10),
            text_color=COLOR_TEXT_DIM,
            anchor="w",
        ).pack(fill="x", pady=(0, 8))

        if selected_keyboard_api == "Follow Mouse API":
            message = "Keyboard follows the active mouse backend connection. Connect the mouse API above."
            action_text = "USE MOUSE CONNECTION"
        elif resolved_keyboard_api == "SendInput":
            message = "SendInput keyboard output is local only and does not require a hardware mouse connection."
            action_text = "ENABLE KEYBOARD SENDINPUT"
        elif resolved_keyboard_api == "Ferrum":
            message = "Keyboard Ferrum uses its own connection settings. KmAPI supports an independent keyboard session; NetAPI and DhzAPI are UI-configurable but still share the mouse session today."
            action_text = "CONNECT KEYBOARD FERRUM"
        else:
            message = (
                "Keyboard output is routed through the selected backend. "
                "This build still shares the underlying hardware session with the mouse backend."
            )
            action_text = f"CONNECT KEYBOARD {resolved_keyboard_api.upper()}"

        if resolved_keyboard_api == "Ferrum":
            mode_frame = ctk.CTkFrame(self.keyboard_content_frame, fg_color="transparent")
            mode_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(mode_frame, text="Ferrum Mode", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.keyboard_ferrum_mode_option = self._add_hardware_option_menu(
                ["KmAPI", "NetAPI", "DhzAPI"],
                self._on_keyboard_ferrum_mode_selected,
                parent=mode_frame,
            )
            self.keyboard_ferrum_mode_option.pack(side="right")
            if self.saved_keyboard_ferrum_mode not in ("KmAPI", "NetAPI", "DhzAPI"):
                self.saved_keyboard_ferrum_mode = "KmAPI"
            self.keyboard_ferrum_mode_option.set(self.saved_keyboard_ferrum_mode)

        if resolved_keyboard_api == "Ferrum" and self.saved_keyboard_ferrum_mode == "NetAPI":
            ip_frame = ctk.CTkFrame(self.keyboard_content_frame, fg_color="transparent")
            ip_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(ip_frame, text="IP Address", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.keyboard_ferrum_net_ip_entry = self._create_hardware_entry(ip_frame)
            self.keyboard_ferrum_net_ip_entry.pack(side="right")
            self.keyboard_ferrum_net_ip_entry.insert(0, self.saved_keyboard_ferrum_net_ip)
            self.keyboard_ferrum_net_ip_entry.bind("<KeyRelease>", self._on_keyboard_ferrum_net_ip_changed)
            self.keyboard_ferrum_net_ip_entry.bind("<FocusOut>", self._on_keyboard_ferrum_net_ip_changed)

            port_frame = ctk.CTkFrame(self.keyboard_content_frame, fg_color="transparent")
            port_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(port_frame, text="Port", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.keyboard_ferrum_net_port_entry = self._create_hardware_entry(port_frame)
            self.keyboard_ferrum_net_port_entry.pack(side="right")
            self.keyboard_ferrum_net_port_entry.insert(0, self.saved_keyboard_ferrum_net_port)
            self.keyboard_ferrum_net_port_entry.bind("<KeyRelease>", self._on_keyboard_ferrum_net_port_changed)
            self.keyboard_ferrum_net_port_entry.bind("<FocusOut>", self._on_keyboard_ferrum_net_port_changed)

            uuid_frame = ctk.CTkFrame(self.keyboard_content_frame, fg_color="transparent")
            uuid_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(uuid_frame, text="UUID", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.keyboard_ferrum_net_uuid_entry = self._create_hardware_entry(uuid_frame)
            self.keyboard_ferrum_net_uuid_entry.pack(side="right")
            self.keyboard_ferrum_net_uuid_entry.insert(0, self.saved_keyboard_ferrum_net_uuid)
            self.keyboard_ferrum_net_uuid_entry.bind("<KeyRelease>", self._on_keyboard_ferrum_net_uuid_changed)
            self.keyboard_ferrum_net_uuid_entry.bind("<FocusOut>", self._on_keyboard_ferrum_net_uuid_changed)
        elif resolved_keyboard_api == "Ferrum" and self.saved_keyboard_ferrum_mode == "DhzAPI":
            ip_frame = ctk.CTkFrame(self.keyboard_content_frame, fg_color="transparent")
            ip_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(ip_frame, text="IP Address", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.keyboard_ferrum_dhz_ip_entry = self._create_hardware_entry(ip_frame)
            self.keyboard_ferrum_dhz_ip_entry.pack(side="right")
            self.keyboard_ferrum_dhz_ip_entry.insert(0, self.saved_keyboard_ferrum_dhz_ip)
            self.keyboard_ferrum_dhz_ip_entry.bind("<KeyRelease>", self._on_keyboard_ferrum_dhz_ip_changed)
            self.keyboard_ferrum_dhz_ip_entry.bind("<FocusOut>", self._on_keyboard_ferrum_dhz_ip_changed)

            port_frame = ctk.CTkFrame(self.keyboard_content_frame, fg_color="transparent")
            port_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(port_frame, text="Port", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.keyboard_ferrum_dhz_port_entry = self._create_hardware_entry(port_frame)
            self.keyboard_ferrum_dhz_port_entry.pack(side="right")
            self.keyboard_ferrum_dhz_port_entry.insert(0, self.saved_keyboard_ferrum_dhz_port)
            self.keyboard_ferrum_dhz_port_entry.bind("<KeyRelease>", self._on_keyboard_ferrum_dhz_port_changed)
            self.keyboard_ferrum_dhz_port_entry.bind("<FocusOut>", self._on_keyboard_ferrum_dhz_port_changed)

            random_frame = ctk.CTkFrame(self.keyboard_content_frame, fg_color="transparent")
            random_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(random_frame, text="Random Shift", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.keyboard_ferrum_dhz_random_entry = self._create_hardware_entry(random_frame)
            self.keyboard_ferrum_dhz_random_entry.pack(side="right")
            self.keyboard_ferrum_dhz_random_entry.insert(0, self.saved_keyboard_ferrum_dhz_random)
            self.keyboard_ferrum_dhz_random_entry.bind("<KeyRelease>", self._on_keyboard_ferrum_dhz_random_changed)
            self.keyboard_ferrum_dhz_random_entry.bind("<FocusOut>", self._on_keyboard_ferrum_dhz_random_changed)
        elif resolved_keyboard_api == "Ferrum":
            port_frame = ctk.CTkFrame(self.keyboard_content_frame, fg_color="transparent")
            port_frame.pack(fill="x", pady=3)
            ctk.CTkLabel(port_frame, text="COM Port (optional)", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.keyboard_ferrum_device_path_entry = self._create_hardware_entry(port_frame)
            self.keyboard_ferrum_device_path_entry.pack(side="right")
            self.keyboard_ferrum_device_path_entry.insert(0, self.saved_keyboard_ferrum_device_path)
            self.keyboard_ferrum_device_path_entry.bind("<KeyRelease>", self._on_keyboard_ferrum_device_path_changed)
            self.keyboard_ferrum_device_path_entry.bind("<FocusOut>", self._on_keyboard_ferrum_device_path_changed)

        ctk.CTkLabel(
            self.keyboard_content_frame,
            text=message,
            font=("Roboto", 9),
            text_color=COLOR_TEXT_DIM,
            justify="left",
            wraplength=720,
            anchor="w",
        ).pack(fill="x", pady=(0, 8))

        btn_frame = ctk.CTkFrame(self.keyboard_content_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(0, 2))
        self._add_hardware_action_button(btn_frame, action_text, self._connect_keyboard_api).pack(side="left")
        self._apply_runtime_settings_lock()

    def _connect_keyboard_api(self):
        if self._runtime_settings_locked():
            self._warn_runtime_settings_locked("hardware")
            return
        if getattr(self, "_keyboard_api_connecting", False):
            self._set_status_indicator("Status: Keyboard API connecting...", COLOR_TEXT_DIM)
            return

        if not bool(getattr(config, "keyboard_api_enabled", False)):
            self._set_status_indicator("Status: Enable Keyboard API first", COLOR_WARNING)
            return

        selected_keyboard_api = self._normalize_keyboard_api_name(
            getattr(config, "keyboard_api", getattr(self, "saved_keyboard_api", "Follow Mouse API"))
        )
        mouse_api = self._normalize_mouse_api_name(getattr(config, "mouse_api", "Serial"))
        resolved_keyboard_api = mouse_api if selected_keyboard_api == "Follow Mouse API" else selected_keyboard_api

        if selected_keyboard_api == "Follow Mouse API":
            self._set_status_indicator(
                f"Status: Keyboard follows mouse connection ({resolved_keyboard_api})",
                COLOR_TEXT_DIM,
            )
            return

        if resolved_keyboard_api == "SendInput":
            self._set_status_indicator("Status: Keyboard SendInput ready", COLOR_TEXT)
            self._update_hardware_status_ui()
            return
        if resolved_keyboard_api == "Ferrum":
            config.keyboard_ferrum_mode = self.saved_keyboard_ferrum_mode
            if self.saved_keyboard_ferrum_mode == "NetAPI":
                if hasattr(self, "keyboard_ferrum_net_ip_entry") and self.keyboard_ferrum_net_ip_entry.winfo_exists():
                    self.saved_keyboard_ferrum_net_ip = self.keyboard_ferrum_net_ip_entry.get().strip()
                if hasattr(self, "keyboard_ferrum_net_port_entry") and self.keyboard_ferrum_net_port_entry.winfo_exists():
                    self.saved_keyboard_ferrum_net_port = self.keyboard_ferrum_net_port_entry.get().strip()
                if hasattr(self, "keyboard_ferrum_net_uuid_entry") and self.keyboard_ferrum_net_uuid_entry.winfo_exists():
                    self.saved_keyboard_ferrum_net_uuid = self.keyboard_ferrum_net_uuid_entry.get().strip()
                config.keyboard_ferrum_net_ip = self.saved_keyboard_ferrum_net_ip
                config.keyboard_ferrum_net_port = self.saved_keyboard_ferrum_net_port
                config.keyboard_ferrum_net_uuid = self.saved_keyboard_ferrum_net_uuid
            elif self.saved_keyboard_ferrum_mode == "DhzAPI":
                if hasattr(self, "keyboard_ferrum_dhz_ip_entry") and self.keyboard_ferrum_dhz_ip_entry.winfo_exists():
                    self.saved_keyboard_ferrum_dhz_ip = self.keyboard_ferrum_dhz_ip_entry.get().strip()
                if hasattr(self, "keyboard_ferrum_dhz_port_entry") and self.keyboard_ferrum_dhz_port_entry.winfo_exists():
                    self.saved_keyboard_ferrum_dhz_port = self.keyboard_ferrum_dhz_port_entry.get().strip()
                if hasattr(self, "keyboard_ferrum_dhz_random_entry") and self.keyboard_ferrum_dhz_random_entry.winfo_exists():
                    self.saved_keyboard_ferrum_dhz_random = self.keyboard_ferrum_dhz_random_entry.get().strip()
                config.keyboard_ferrum_dhz_ip = self.saved_keyboard_ferrum_dhz_ip
                config.keyboard_ferrum_dhz_port = self.saved_keyboard_ferrum_dhz_port
                try:
                    config.keyboard_ferrum_dhz_random = int(self.saved_keyboard_ferrum_dhz_random)
                except ValueError:
                    config.keyboard_ferrum_dhz_random = 0
            else:
                if hasattr(self, "keyboard_ferrum_device_path_entry") and self.keyboard_ferrum_device_path_entry.winfo_exists():
                    self.saved_keyboard_ferrum_device_path = self.keyboard_ferrum_device_path_entry.get().strip()
                config.keyboard_ferrum_device_path = self.saved_keyboard_ferrum_device_path

            if self.saved_keyboard_ferrum_mode != "KmAPI":
                self._set_status_indicator(
                    f"Status: Keyboard Ferrum {self.saved_keyboard_ferrum_mode} UI is available, but independent connect is not implemented yet.",
                    COLOR_WARNING,
                )
                self._update_hardware_status_ui()
                return
            config.keyboard_ferrum_connection_type = self.saved_keyboard_ferrum_connection_type

            self._keyboard_api_connecting = True
            self._set_status_indicator("Status: Keyboard Ferrum connecting", COLOR_TEXT_DIM)
            threading.Thread(target=self._connect_keyboard_api_worker, args=("Ferrum",), daemon=True).start()
            return

        self._set_status_indicator(
            f"Status: Keyboard API {resolved_keyboard_api} still uses the shared hardware session. Connect it from Mouse Connection.",
            COLOR_TEXT_DIM,
        )

    def _connect_keyboard_api_worker(self, mode):
        success, error = False, "unknown error"
        try:
            from src.utils import mouse as mouse_backend

            success, error = mouse_backend.connect_keyboard_backend(
                mode,
                ferrum_device_path=self.saved_keyboard_ferrum_device_path,
                ferrum_connection_type=self.saved_keyboard_ferrum_connection_type,
            )
        except Exception as e:
            success = False
            error = str(e)

        self.after(0, lambda: self._on_connect_keyboard_api_done(mode, success, error))

    def _on_connect_keyboard_api_done(self, mode, success, error):
        self._keyboard_api_connecting = False
        if success:
            self._set_status_indicator(f"Status: Keyboard {mode} connected", COLOR_TEXT)
        else:
            suffix = f": {error}" if error else ""
            self._set_status_indicator(f"Status: Keyboard {mode} connect failed{suffix}", COLOR_DANGER)
        self._update_hardware_status_ui()

    def _on_keyboard_ferrum_device_path_changed(self, event=None):
        if hasattr(self, "keyboard_ferrum_device_path_entry") and self.keyboard_ferrum_device_path_entry.winfo_exists():
            val = self.keyboard_ferrum_device_path_entry.get().strip()
            self.saved_keyboard_ferrum_device_path = val
            config.keyboard_ferrum_device_path = val

    def _on_keyboard_ferrum_mode_selected(self, val):
        mode = str(val).strip() or "KmAPI"
        if mode not in ("KmAPI", "NetAPI", "DhzAPI"):
            mode = "KmAPI"
        self.saved_keyboard_ferrum_mode = mode
        config.keyboard_ferrum_mode = mode
        self._update_keyboard_api_ui()

    def _on_keyboard_ferrum_net_ip_changed(self, event=None):
        if hasattr(self, "keyboard_ferrum_net_ip_entry") and self.keyboard_ferrum_net_ip_entry.winfo_exists():
            self.saved_keyboard_ferrum_net_ip = self.keyboard_ferrum_net_ip_entry.get().strip()
            config.keyboard_ferrum_net_ip = self.saved_keyboard_ferrum_net_ip

    def _on_keyboard_ferrum_net_port_changed(self, event=None):
        if hasattr(self, "keyboard_ferrum_net_port_entry") and self.keyboard_ferrum_net_port_entry.winfo_exists():
            self.saved_keyboard_ferrum_net_port = self.keyboard_ferrum_net_port_entry.get().strip()
            config.keyboard_ferrum_net_port = self.saved_keyboard_ferrum_net_port

    def _on_keyboard_ferrum_net_uuid_changed(self, event=None):
        if hasattr(self, "keyboard_ferrum_net_uuid_entry") and self.keyboard_ferrum_net_uuid_entry.winfo_exists():
            self.saved_keyboard_ferrum_net_uuid = self.keyboard_ferrum_net_uuid_entry.get().strip()
            config.keyboard_ferrum_net_uuid = self.saved_keyboard_ferrum_net_uuid

    def _on_keyboard_ferrum_dhz_ip_changed(self, event=None):
        if hasattr(self, "keyboard_ferrum_dhz_ip_entry") and self.keyboard_ferrum_dhz_ip_entry.winfo_exists():
            self.saved_keyboard_ferrum_dhz_ip = self.keyboard_ferrum_dhz_ip_entry.get().strip()
            config.keyboard_ferrum_dhz_ip = self.saved_keyboard_ferrum_dhz_ip

    def _on_keyboard_ferrum_dhz_port_changed(self, event=None):
        if hasattr(self, "keyboard_ferrum_dhz_port_entry") and self.keyboard_ferrum_dhz_port_entry.winfo_exists():
            self.saved_keyboard_ferrum_dhz_port = self.keyboard_ferrum_dhz_port_entry.get().strip()
            config.keyboard_ferrum_dhz_port = self.saved_keyboard_ferrum_dhz_port

    def _on_keyboard_ferrum_dhz_random_changed(self, event=None):
        if hasattr(self, "keyboard_ferrum_dhz_random_entry") and self.keyboard_ferrum_dhz_random_entry.winfo_exists():
            self.saved_keyboard_ferrum_dhz_random = self.keyboard_ferrum_dhz_random_entry.get().strip()
            try:
                config.keyboard_ferrum_dhz_random = int(self.saved_keyboard_ferrum_dhz_random)
            except ValueError:
                config.keyboard_ferrum_dhz_random = 0

    def _on_auto_connect_mouse_api_changed(self):
        if self._runtime_settings_locked():
            self._ignore_settings_events = True
            try:
                self.var_auto_connect_mouse_api.set(bool(getattr(config, "auto_connect_mouse_api", False)))
            except Exception:
                pass
            self._ignore_settings_events = False
            self._warn_runtime_settings_locked("hardware")
            return
        val = bool(self.var_auto_connect_mouse_api.get())
        self.saved_auto_connect_mouse_api = val
        config.auto_connect_mouse_api = val
        try:
            config.save_to_file()
        except Exception:
            pass

    def _on_serial_auto_switch_4m_changed(self):
        if self._runtime_settings_locked():
            self._ignore_settings_events = True
            try:
                self.var_serial_auto_switch_4m.set(bool(getattr(config, "serial_auto_switch_4m", False)))
            except Exception:
                pass
            self._ignore_settings_events = False
            self._warn_runtime_settings_locked("hardware")
            return
        val = bool(self.var_serial_auto_switch_4m.get())
        self.saved_serial_auto_switch_4m = val
        config.serial_auto_switch_4m = val
        try:
            config.save_to_file()
        except Exception:
            pass

    def _on_serial_mode_selected(self, val):
        if self._runtime_settings_locked():
            self._warn_runtime_settings_locked("hardware")
            return
        mode_norm = str(val).strip().lower()
        self.saved_serial_port_mode = "Manual" if mode_norm == "manual" else "Auto"
        config.serial_port_mode = self.saved_serial_port_mode
        self._update_mouse_api_ui()

    def _on_serial_port_changed(self, event=None):
        if hasattr(self, "serial_port_entry") and self.serial_port_entry.winfo_exists():
            val = self.serial_port_entry.get().strip()
            self.saved_serial_port = val
            config.serial_port = val

    def _on_arduino_port_changed(self, event=None):
        if hasattr(self, "arduino_port_entry") and self.arduino_port_entry.winfo_exists():
            val = self.arduino_port_entry.get().strip()
            self.saved_arduino_port = val
            config.arduino_port = val

    def _on_arduino_baud_changed(self, event=None):
        if hasattr(self, "arduino_baud_entry") and self.arduino_baud_entry.winfo_exists():
            val = self.arduino_baud_entry.get().strip()
            self.saved_arduino_baud = val
            try:
                config.arduino_baud = int(val)
            except ValueError:
                config.arduino_baud = 115200

    def _on_net_ip_changed(self, event=None):
        if hasattr(self, "net_ip_entry") and self.net_ip_entry.winfo_exists():
            val = self.net_ip_entry.get().strip()
            self.saved_net_ip = val
            config.net_ip = val

    def _on_net_port_changed(self, event=None):
        if hasattr(self, "net_port_entry") and self.net_port_entry.winfo_exists():
            val = self.net_port_entry.get().strip()
            self.saved_net_port = val
            config.net_port = val

    def _on_net_uuid_changed(self, event=None):
        if hasattr(self, "net_uuid_entry") and self.net_uuid_entry.winfo_exists():
            val = self.net_uuid_entry.get().strip()
            self.saved_net_uuid = val
            config.net_uuid = val
            config.net_mac = val

    def _on_kmboxa_vid_pid_changed(self, event=None):
        if hasattr(self, "kmboxa_vid_pid_entry") and self.kmboxa_vid_pid_entry.winfo_exists():
            val = self.kmboxa_vid_pid_entry.get().strip()
            self.saved_kmboxa_vid_pid = val
            config.kmboxa_vid_pid = val

    def _on_makv2_port_changed(self, event=None):
        if hasattr(self, "makv2_port_entry") and self.makv2_port_entry.winfo_exists():
            val = self.makv2_port_entry.get().strip()
            self.saved_makv2_port = val
            config.makv2_port = val

    def _on_makv2_baud_changed(self, event=None):
        if hasattr(self, "makv2_baud_entry") and self.makv2_baud_entry.winfo_exists():
            val = self.makv2_baud_entry.get().strip()
            self.saved_makv2_baud = val
            try:
                config.makv2_baud = int(val)
            except ValueError:
                pass

    def _on_makcu_controller_port_changed(self, event=None):
        if hasattr(self, "makcu_controller_port_entry") and self.makcu_controller_port_entry.winfo_exists():
            val = self.makcu_controller_port_entry.get().strip()
            self.saved_makcu_controller_port = val
            config.makcu_controller_port = val

    def _on_makcu_controller_baud_changed(self, event=None):
        if hasattr(self, "makcu_controller_baud_entry") and self.makcu_controller_baud_entry.winfo_exists():
            val = self.makcu_controller_baud_entry.get().strip()
            self.saved_makcu_controller_baud = val
            try:
                config.makcu_controller_baud = int(val)
            except ValueError:
                pass

    def _on_makxd_mak_port_changed(self, event=None):
        if hasattr(self, "makxd_mak_port_entry") and self.makxd_mak_port_entry.winfo_exists():
            val = self.makxd_mak_port_entry.get().strip()
            self.saved_makxd_mak_port = val
            config.makxd_mak_port = val

    def _on_makxd_mak_baud_changed(self, event=None):
        if hasattr(self, "makxd_mak_baud_entry") and self.makxd_mak_baud_entry.winfo_exists():
            val = self.makxd_mak_baud_entry.get().strip()
            self.saved_makxd_mak_baud = val
            try:
                config.makxd_mak_baud = int(val)
            except ValueError:
                pass

    def _on_dhz_ip_changed(self, event=None):
        if hasattr(self, "dhz_ip_entry") and self.dhz_ip_entry.winfo_exists():
            val = self.dhz_ip_entry.get().strip()
            self.saved_dhz_ip = val
            config.dhz_ip = val

    def _on_dhz_port_changed(self, event=None):
        if hasattr(self, "dhz_port_entry") and self.dhz_port_entry.winfo_exists():
            val = self.dhz_port_entry.get().strip()
            self.saved_dhz_port = val
            config.dhz_port = val

    def _on_dhz_random_changed(self, event=None):
        if hasattr(self, "dhz_random_entry") and self.dhz_random_entry.winfo_exists():
            val = self.dhz_random_entry.get().strip()
            self.saved_dhz_random = val
            try:
                config.dhz_random = int(val)
            except ValueError:
                pass

    def _on_ferrum_device_path_changed(self, event=None):
        if hasattr(self, "ferrum_device_path_entry") and self.ferrum_device_path_entry.winfo_exists():
            val = self.ferrum_device_path_entry.get().strip()
            self.saved_ferrum_device_path = val
            config.ferrum_device_path = val

    def _on_medius_port_changed(self, event=None):
        if hasattr(self, "medius_port_entry") and self.medius_port_entry.winfo_exists():
            val = self.medius_port_entry.get().strip()
            self.saved_medius_port = val
            config.medius_port = val

    def _refresh_medius_ports(self):
        try:
            from src.utils.mouse.MediusAPI import list_ports

            ports = list_ports()
        except Exception as e:
            self._set_status_indicator(f"Status: Medius ports failed: {e}", COLOR_DANGER)
            return
        if not ports:
            self._set_status_indicator("Status: No Medius ports found", COLOR_WARNING)
            return
        first = ports[0]
        path = str(first.get("path", "")).strip()
        if path:
            self.saved_medius_port = path
            config.medius_port = path
            if hasattr(self, "medius_port_entry") and self.medius_port_entry.winfo_exists():
                self.medius_port_entry.delete(0, "end")
                self.medius_port_entry.insert(0, path)
        names = ", ".join(str(item.get("path") or "?") for item in ports)
        self._set_status_indicator(f"Status: Medius ports: {names}", COLOR_TEXT)

    def _on_mak_api_port_changed(self, event=None):
        if hasattr(self, "mak_api_port_entry") and self.mak_api_port_entry.winfo_exists():
            val = self.mak_api_port_entry.get().strip()
            self.saved_mak_api_port = val
            config.mak_api_port = val

    def _on_mak_api_baud_changed(self, event=None):
        if hasattr(self, "mak_api_baud_entry") and self.mak_api_baud_entry.winfo_exists():
            val = self.mak_api_baud_entry.get().strip()
            self.saved_mak_api_baud = val
            try:
                config.mak_api_baud = int(val) if val else 0
            except ValueError:
                pass

    def _refresh_mak_api_ports(self):
        try:
            from src.utils.mouse.MakAPI import find_mak_ports

            ports = find_mak_ports()
        except Exception as e:
            self._set_status_indicator(f"Status: MAK API ports failed: {e}", COLOR_DANGER)
            return
        if not ports:
            self._set_status_indicator("Status: No MAK CH343/CH340 ports found", COLOR_WARNING)
            return
        path = str(ports[0]).strip()
        if path:
            self.saved_mak_api_port = path
            config.mak_api_port = path
            if hasattr(self, "mak_api_port_entry") and self.mak_api_port_entry.winfo_exists():
                self.mak_api_port_entry.delete(0, "end")
                self.mak_api_port_entry.insert(0, path)
        self._set_status_indicator(f"Status: MAK API ports: {', '.join(ports)}", COLOR_TEXT)

    def _on_ferrum_connection_type_selected(self, val):
        connection_type_norm = str(val).strip().lower()
        if connection_type_norm not in ("auto", "serial", "network", "usb_hid"):
            connection_type_norm = "auto"
        self.saved_ferrum_connection_type = connection_type_norm
        config.ferrum_connection_type = connection_type_norm

    def _on_ferrum_mode_selected(self, val):
        mode = str(val).strip() or "KmAPI"
        if mode not in ("KmAPI", "NetAPI", "DhzAPI"):
            mode = "KmAPI"
        self.saved_ferrum_mode = mode
        config.ferrum_mode = mode
        self._update_mouse_api_ui()

    def _on_ferrum_net_ip_changed(self, event=None):
        if hasattr(self, "ferrum_net_ip_entry") and self.ferrum_net_ip_entry.winfo_exists():
            self.saved_ferrum_net_ip = self.ferrum_net_ip_entry.get().strip()
            config.ferrum_net_ip = self.saved_ferrum_net_ip

    def _on_ferrum_net_port_changed(self, event=None):
        if hasattr(self, "ferrum_net_port_entry") and self.ferrum_net_port_entry.winfo_exists():
            self.saved_ferrum_net_port = self.ferrum_net_port_entry.get().strip()
            config.ferrum_net_port = self.saved_ferrum_net_port

    def _on_ferrum_net_uuid_changed(self, event=None):
        if hasattr(self, "ferrum_net_uuid_entry") and self.ferrum_net_uuid_entry.winfo_exists():
            self.saved_ferrum_net_uuid = self.ferrum_net_uuid_entry.get().strip()
            config.ferrum_net_uuid = self.saved_ferrum_net_uuid

    def _on_ferrum_dhz_ip_changed(self, event=None):
        if hasattr(self, "ferrum_dhz_ip_entry") and self.ferrum_dhz_ip_entry.winfo_exists():
            self.saved_ferrum_dhz_ip = self.ferrum_dhz_ip_entry.get().strip()
            config.ferrum_dhz_ip = self.saved_ferrum_dhz_ip

    def _on_ferrum_dhz_port_changed(self, event=None):
        if hasattr(self, "ferrum_dhz_port_entry") and self.ferrum_dhz_port_entry.winfo_exists():
            self.saved_ferrum_dhz_port = self.ferrum_dhz_port_entry.get().strip()
            config.ferrum_dhz_port = self.saved_ferrum_dhz_port

    def _on_ferrum_dhz_random_changed(self, event=None):
        if hasattr(self, "ferrum_dhz_random_entry") and self.ferrum_dhz_random_entry.winfo_exists():
            self.saved_ferrum_dhz_random = self.ferrum_dhz_random_entry.get().strip()
            try:
                config.ferrum_dhz_random = int(self.saved_ferrum_dhz_random)
            except ValueError:
                config.ferrum_dhz_random = 0

    def _test_mouse_move(self):
        try:
            from src.utils import mouse as mouse_backend

            if not getattr(mouse_backend, "is_connected", False):
                self._set_status_indicator("Status: Mouse API not connected", COLOR_DANGER)
                return

            mouse_backend.test_move()
            backend = mouse_backend.get_active_backend()
            self._set_status_indicator(f"Status: Test move sent via {backend}", COLOR_TEXT)
        except Exception as e:
            self._set_status_indicator(f"Status: Mouse API test error: {e}", COLOR_DANGER)

    def _switch_serial_to_4m(self):
        if self._runtime_settings_locked():
            self._warn_runtime_settings_locked("hardware")
            return
        if getattr(self, "_mouse_api_connecting", False):
            self._set_status_indicator("Status: HW connecting...", COLOR_TEXT_DIM)
            return
        if getattr(self, "_serial_baud_switching", False):
            self._set_status_indicator("Status: Serial baud switching...", COLOR_TEXT_DIM)
            return

        self._serial_baud_switching = True
        self._set_status_indicator("Status: Switching Serial to 4M", COLOR_TEXT_DIM)
        threading.Thread(target=self._switch_serial_to_4m_worker, daemon=True).start()

    def _switch_serial_to_4m_worker(self):
        success = False
        error = ""
        try:
            from src.utils import mouse as mouse_backend

            success = bool(mouse_backend.switch_to_4m())
            if not success:
                error = str(mouse_backend.get_last_connect_error() or "").strip()
        except Exception as e:
            success = False
            error = str(e)

        self.after(0, lambda: self._on_switch_serial_to_4m_done(success, error))

    def _on_switch_serial_to_4m_done(self, success, error):
        self._serial_baud_switching = False
        if success:
            self._set_status_indicator("Status: Serial switched to 4M", COLOR_TEXT)
        else:
            suffix = f": {error}" if error else ""
            self._set_status_indicator(f"Status: Switch to 4M failed{suffix}", COLOR_DANGER)
        self._update_hardware_status_ui()

    def _connect_mouse_api(self, target_mode=None, start_async=True):
        if start_async and getattr(self, "_mouse_api_connecting", False):
            self._set_status_indicator("Status: HW connecting...", COLOR_TEXT_DIM)
            return
        if start_async and getattr(self, "_serial_baud_switching", False):
            self._set_status_indicator("Status: Serial baud switching...", COLOR_TEXT_DIM)
            return

        mode = target_mode or getattr(config, "mouse_api", "Serial")
        mode_norm = str(mode).strip().lower()
        if mode_norm == "net":
            mode = "Net"
        elif mode_norm in ("kmboxa", "kmboxa_api", "kmboxaapi", "kma", "kmboxa-api"):
            mode = "KmboxA"
        elif mode_norm == "dhz":
            mode = "DHZ"
        elif mode_norm in ("makxdmakapi", "makxd_makapi", "makxd-makapi", "makxd makapi", "makxd_mak", "makxd-mak"):
            mode = "MakxdMakAPI"
        elif mode_norm in ("makapi", "mak_api", "mak-api", "mak api"):
            mode = "MakAPI"
        elif mode_norm in ("makv2binary", "makv2_binary", "makv2-binary", "binary"):
            mode = "MakV2Binary"
        elif mode_norm in ("makv2", "mak_v2", "mak-v2"):
            mode = "MakV2"
        elif mode_norm in ("makcucontroller", "makcu_controller", "makcu-controller", "makcu controller"):
            mode = "MakcuController"
        elif mode_norm == "arduino":
            mode = "Arduino"
        elif mode_norm in ("sendinput", "win32", "win32api", "win32_sendinput", "win32-sendinput"):
            mode = "SendInput"
        elif mode_norm == "ferrum":
            mode = "Ferrum"
        elif mode_norm in ("medius", "k4tech", "k4"):
            mode = "Medius"
        else:
            mode = "Serial"
        payload = {"mode": mode}

        if mode == "Serial":
            selected_serial_mode = "Manual" if str(self.saved_serial_port_mode).strip().lower() == "manual" else "Auto"
            self.saved_serial_port_mode = selected_serial_mode
            if selected_serial_mode == "Manual":
                if hasattr(self, "serial_port_entry") and self.serial_port_entry.winfo_exists():
                    self.saved_serial_port = self.serial_port_entry.get().strip()
            config.serial_port_mode = selected_serial_mode
            config.serial_port = self.saved_serial_port
            payload.update(
                {
                    "serial_port_mode": selected_serial_mode,
                    "serial_port": self.saved_serial_port,
                }
            )

        elif mode == "Arduino":
            if hasattr(self, "arduino_port_entry") and self.arduino_port_entry.winfo_exists():
                self.saved_arduino_port = self.arduino_port_entry.get().strip()
            if hasattr(self, "arduino_baud_entry") and self.arduino_baud_entry.winfo_exists():
                self.saved_arduino_baud = self.arduino_baud_entry.get().strip()

            config.arduino_port = self.saved_arduino_port
            try:
                config.arduino_baud = int(self.saved_arduino_baud)
            except ValueError:
                config.arduino_baud = 115200
            payload.update(
                {
                    "arduino_port": self.saved_arduino_port,
                    "arduino_baud": config.arduino_baud,
                }
            )

        elif mode == "Net":
            if hasattr(self, "net_ip_entry") and self.net_ip_entry.winfo_exists():
                self.saved_net_ip = self.net_ip_entry.get().strip()
            if hasattr(self, "net_port_entry") and self.net_port_entry.winfo_exists():
                self.saved_net_port = self.net_port_entry.get().strip()
            if hasattr(self, "net_uuid_entry") and self.net_uuid_entry.winfo_exists():
                self.saved_net_uuid = self.net_uuid_entry.get().strip()

            config.net_ip = self.saved_net_ip
            config.net_port = self.saved_net_port
            config.net_uuid = self.saved_net_uuid
            config.net_mac = self.saved_net_uuid
            payload.update({
                "ip": self.saved_net_ip,
                "port": self.saved_net_port,
                "uuid": self.saved_net_uuid,
            })
        elif mode == "KmboxA":
            if hasattr(self, "kmboxa_vid_pid_entry") and self.kmboxa_vid_pid_entry.winfo_exists():
                self.saved_kmboxa_vid_pid = self.kmboxa_vid_pid_entry.get().strip()
            config.kmboxa_vid_pid = self.saved_kmboxa_vid_pid
            payload.update({
                "kmboxa_vid_pid": self.saved_kmboxa_vid_pid,
            })

        elif mode == "MakV2":
            if hasattr(self, "makv2_port_entry") and self.makv2_port_entry.winfo_exists():
                self.saved_makv2_port = self.makv2_port_entry.get().strip()
            if hasattr(self, "makv2_baud_entry") and self.makv2_baud_entry.winfo_exists():
                self.saved_makv2_baud = self.makv2_baud_entry.get().strip()

            config.makv2_port = self.saved_makv2_port
            try:
                config.makv2_baud = int(self.saved_makv2_baud)
            except ValueError:
                config.makv2_baud = 4000000
            payload.update({
                "makv2_port": self.saved_makv2_port,
                "makv2_baud": config.makv2_baud,
            })
        elif mode == "MakcuController":
            if hasattr(self, "makcu_controller_port_entry") and self.makcu_controller_port_entry.winfo_exists():
                self.saved_makcu_controller_port = self.makcu_controller_port_entry.get().strip()
            if hasattr(self, "makcu_controller_baud_entry") and self.makcu_controller_baud_entry.winfo_exists():
                self.saved_makcu_controller_baud = self.makcu_controller_baud_entry.get().strip()

            config.makcu_controller_port = self.saved_makcu_controller_port
            try:
                config.makcu_controller_baud = int(self.saved_makcu_controller_baud)
            except ValueError:
                config.makcu_controller_baud = 115200
            payload.update({
                "makcu_controller_port": self.saved_makcu_controller_port,
                "makcu_controller_baud": config.makcu_controller_baud,
            })
        elif mode == "MakxdMakAPI":
            if hasattr(self, "makxd_mak_port_entry") and self.makxd_mak_port_entry.winfo_exists():
                self.saved_makxd_mak_port = self.makxd_mak_port_entry.get().strip()
            if hasattr(self, "makxd_mak_baud_entry") and self.makxd_mak_baud_entry.winfo_exists():
                self.saved_makxd_mak_baud = self.makxd_mak_baud_entry.get().strip()

            config.makxd_mak_port = self.saved_makxd_mak_port
            try:
                config.makxd_mak_baud = int(self.saved_makxd_mak_baud)
            except ValueError:
                config.makxd_mak_baud = 115200
            payload.update({
                "makxd_mak_port": self.saved_makxd_mak_port,
                "makxd_mak_baud": config.makxd_mak_baud,
            })
        elif mode == "DHZ":
            if hasattr(self, "dhz_ip_entry") and self.dhz_ip_entry.winfo_exists():
                self.saved_dhz_ip = self.dhz_ip_entry.get().strip()
            if hasattr(self, "dhz_port_entry") and self.dhz_port_entry.winfo_exists():
                self.saved_dhz_port = self.dhz_port_entry.get().strip()
            if hasattr(self, "dhz_random_entry") and self.dhz_random_entry.winfo_exists():
                self.saved_dhz_random = self.dhz_random_entry.get().strip()

            config.dhz_ip = self.saved_dhz_ip
            config.dhz_port = self.saved_dhz_port
            try:
                config.dhz_random = int(self.saved_dhz_random)
            except ValueError:
                config.dhz_random = 0
            payload.update({
                "dhz_ip": self.saved_dhz_ip,
                "dhz_port": self.saved_dhz_port,
                "dhz_random": config.dhz_random,
            })
        elif mode == "Ferrum":
            payload["ferrum_mode"] = self.saved_ferrum_mode
            config.ferrum_mode = self.saved_ferrum_mode
            if self.saved_ferrum_mode == "NetAPI":
                if hasattr(self, "ferrum_net_ip_entry") and self.ferrum_net_ip_entry.winfo_exists():
                    self.saved_ferrum_net_ip = self.ferrum_net_ip_entry.get().strip()
                if hasattr(self, "ferrum_net_port_entry") and self.ferrum_net_port_entry.winfo_exists():
                    self.saved_ferrum_net_port = self.ferrum_net_port_entry.get().strip()
                if hasattr(self, "ferrum_net_uuid_entry") and self.ferrum_net_uuid_entry.winfo_exists():
                    self.saved_ferrum_net_uuid = self.ferrum_net_uuid_entry.get().strip()
                config.ferrum_net_ip = self.saved_ferrum_net_ip
                config.ferrum_net_port = self.saved_ferrum_net_port
                config.ferrum_net_uuid = self.saved_ferrum_net_uuid
                payload.update({
                    "ferrum_net_ip": self.saved_ferrum_net_ip,
                    "ferrum_net_port": self.saved_ferrum_net_port,
                    "ferrum_net_uuid": self.saved_ferrum_net_uuid,
                })
            elif self.saved_ferrum_mode == "DhzAPI":
                if hasattr(self, "ferrum_dhz_ip_entry") and self.ferrum_dhz_ip_entry.winfo_exists():
                    self.saved_ferrum_dhz_ip = self.ferrum_dhz_ip_entry.get().strip()
                if hasattr(self, "ferrum_dhz_port_entry") and self.ferrum_dhz_port_entry.winfo_exists():
                    self.saved_ferrum_dhz_port = self.ferrum_dhz_port_entry.get().strip()
                if hasattr(self, "ferrum_dhz_random_entry") and self.ferrum_dhz_random_entry.winfo_exists():
                    self.saved_ferrum_dhz_random = self.ferrum_dhz_random_entry.get().strip()
                config.ferrum_dhz_ip = self.saved_ferrum_dhz_ip
                config.ferrum_dhz_port = self.saved_ferrum_dhz_port
                try:
                    config.ferrum_dhz_random = int(self.saved_ferrum_dhz_random)
                except ValueError:
                    config.ferrum_dhz_random = 0
                payload.update({
                    "ferrum_dhz_ip": self.saved_ferrum_dhz_ip,
                    "ferrum_dhz_port": self.saved_ferrum_dhz_port,
                    "ferrum_dhz_random": config.ferrum_dhz_random,
                })
            else:
                if hasattr(self, "ferrum_device_path_entry") and self.ferrum_device_path_entry.winfo_exists():
                    self.saved_ferrum_device_path = self.ferrum_device_path_entry.get().strip()
                config.ferrum_device_path = self.saved_ferrum_device_path
                payload.update({
                    "ferrum_device_path": self.saved_ferrum_device_path,
                    "ferrum_connection_type": "serial",
                })
        elif False and mode == "Ferrum":
            if hasattr(self, "ferrum_device_path_entry") and self.ferrum_device_path_entry.winfo_exists():
                self.saved_ferrum_device_path = self.ferrum_device_path_entry.get().strip()

            config.ferrum_device_path = self.saved_ferrum_device_path
            payload.update({
                "ferrum_device_path": self.saved_ferrum_device_path,
                "ferrum_connection_type": "serial",  # Ferrum 只支持串口
            })
        elif mode == "SendInput":
            pass
        elif mode == "Medius":
            if hasattr(self, "medius_port_entry") and self.medius_port_entry.winfo_exists():
                self.saved_medius_port = self.medius_port_entry.get().strip()
            config.medius_port = self.saved_medius_port
            payload.update({"medius_port": self.saved_medius_port})
        elif mode == "MakAPI":
            if hasattr(self, "mak_api_port_entry") and self.mak_api_port_entry.winfo_exists():
                self.saved_mak_api_port = self.mak_api_port_entry.get().strip()
            if hasattr(self, "mak_api_baud_entry") and self.mak_api_baud_entry.winfo_exists():
                self.saved_mak_api_baud = self.mak_api_baud_entry.get().strip()
            config.mak_api_port = self.saved_mak_api_port
            try:
                config.mak_api_baud = int(self.saved_mak_api_baud) if str(self.saved_mak_api_baud).strip() else 0
            except ValueError:
                config.mak_api_baud = 0
            payload.update({
                "mak_api_port": self.saved_mak_api_port,
                "mak_api_baud": config.mak_api_baud,
            })

        if not start_async:
            return payload

        self._mouse_api_connecting = True
        self._mouse_api_connect_job_id += 1
        job_id = self._mouse_api_connect_job_id
        self._set_status_indicator(f"Status: HW {mode} connecting", COLOR_TEXT_DIM)

        threading.Thread(
            target=self._connect_mouse_api_worker,
            args=(job_id, payload),
            daemon=True,
        ).start()
        self.after(
            self._mouse_api_connect_timeout_ms,
            lambda: self._check_mouse_api_connect_timeout(job_id, mode),
        )

    def _connect_mouse_api_worker(self, job_id, payload):
        mode = payload.get("mode", "Serial")
        success, error = self._execute_mouse_api_connect(payload)
        self.after(0, lambda: self._on_mouse_api_connect_done(job_id, mode, payload, success, error))

    def _execute_mouse_api_connect(self, payload):
        mode = payload.get("mode", "Serial")
        success, error = False, "unknown error"
        try:
            from src.utils.mouse import connect_ferrum_mode, switch_backend

            if mode == "Net":
                success, error = switch_backend(
                    "Net",
                    ip=payload.get("ip", ""),
                    port=payload.get("port", ""),
                    uuid=payload.get("uuid", ""),
                )
            elif mode == "KmboxA":
                success, error = switch_backend(
                    "KmboxA",
                    kmboxa_vid_pid=payload.get("kmboxa_vid_pid", ""),
                )
            elif mode == "Arduino":
                success, error = switch_backend(
                    "Arduino",
                    arduino_port=payload.get("arduino_port", ""),
                    arduino_baud=payload.get("arduino_baud", 115200),
                )
            elif mode == "SendInput":
                success, error = switch_backend("SendInput")
            elif mode == "MakV2":
                success, error = switch_backend(
                    "MakV2",
                    makv2_port=payload.get("makv2_port", ""),
                    makv2_baud=payload.get("makv2_baud", 4000000),
                )
            elif mode == "MakV2Binary":
                success, error = switch_backend("MakV2Binary")
            elif mode == "MakcuController":
                success, error = switch_backend(
                    "MakcuController",
                    makcu_controller_port=payload.get("makcu_controller_port", ""),
                    makcu_controller_baud=payload.get("makcu_controller_baud", 115200),
                )
            elif mode == "MakxdMakAPI":
                success, error = switch_backend(
                    "MakxdMakAPI",
                    makxd_mak_port=payload.get("makxd_mak_port", ""),
                    makxd_mak_baud=payload.get("makxd_mak_baud", 115200),
                )
            elif mode == "DHZ":
                success, error = switch_backend(
                    "DHZ",
                    dhz_ip=payload.get("dhz_ip", ""),
                    dhz_port=payload.get("dhz_port", ""),
                    dhz_random=payload.get("dhz_random", 0),
                )
            elif mode == "Ferrum":
                success, error = connect_ferrum_mode(
                    payload.get("ferrum_mode", "KmAPI"),
                    ferrum_device_path=payload.get("ferrum_device_path", ""),
                    ferrum_connection_type=payload.get("ferrum_connection_type", "serial"),
                    ferrum_net_ip=payload.get("ferrum_net_ip", ""),
                    ferrum_net_port=payload.get("ferrum_net_port", ""),
                    ferrum_net_uuid=payload.get("ferrum_net_uuid", ""),
                    ferrum_dhz_ip=payload.get("ferrum_dhz_ip", ""),
                    ferrum_dhz_port=payload.get("ferrum_dhz_port", ""),
                    ferrum_dhz_random=payload.get("ferrum_dhz_random", 0),
                )
            elif mode == "Medius":
                success, error = switch_backend(
                    "Medius",
                    medius_port=payload.get("medius_port", ""),
                )
            elif mode == "MakAPI":
                success, error = switch_backend(
                    "MakAPI",
                    mak_api_port=payload.get("mak_api_port", ""),
                    mak_api_baud=payload.get("mak_api_baud", 0),
                )
            else:
                success, error = switch_backend(
                    "Serial",
                    serial_port_mode=payload.get("serial_port_mode", "Auto"),
                    serial_port=payload.get("serial_port", ""),
                )
        except Exception as e:
            success, error = False, str(e)
        return success, error

    def _on_mouse_api_connect_done(self, job_id, mode, payload, success, error):
        # Ignore stale callback results.
        if job_id != getattr(self, "_mouse_api_connect_job_id", 0):
            return

        self._mouse_api_connecting = False
        if success:
            if mode == "Net":
                self._set_status_indicator("Status: Mouse API connected (Net)", COLOR_TEXT)
            elif mode == "KmboxA":
                self._set_status_indicator("Status: Mouse API connected (KmboxA)", COLOR_TEXT)
            elif mode == "Arduino":
                self._set_status_indicator("Status: Mouse API connected (Arduino)", COLOR_TEXT)
            elif mode == "SendInput":
                self._set_status_indicator("Status: Mouse API connected (SendInput)", COLOR_TEXT)
            elif mode == "MakV2":
                self._set_status_indicator("Status: Mouse API connected (MakV2)", COLOR_TEXT)
            elif mode == "MakcuController":
                self._set_status_indicator("Status: Mouse API connected (MakcuController)", COLOR_TEXT)
            elif mode == "MakxdMakAPI":
                self._set_status_indicator("Status: Mouse API connected (MakxdMakAPI)", COLOR_TEXT)
            elif mode == "DHZ":
                self._set_status_indicator("Status: Mouse API connected (DHZ)", COLOR_TEXT)
            elif mode == "Ferrum":
                ferrum_mode = str(payload.get("ferrum_mode", "KmAPI"))
                self._set_status_indicator(f"Status: Mouse API connected (Ferrum {ferrum_mode})", COLOR_TEXT)
            elif mode == "Medius":
                self._set_status_indicator("Status: Mouse API connected (Medius)", COLOR_TEXT)
            elif mode == "MakAPI":
                self._set_status_indicator("Status: Mouse API connected (MAK API)", COLOR_TEXT)
            else:
                self._set_status_indicator("Status: Mouse API connected (Serial)", COLOR_TEXT)
            return

        self._set_status_indicator(f"Status: Mouse API error: {error}", COLOR_DANGER)

    def _check_mouse_api_connect_timeout(self, job_id, mode):
        if not getattr(self, "_mouse_api_connecting", False):
            return
        if job_id != getattr(self, "_mouse_api_connect_job_id", 0):
            return

        # Invalidate current job, ignore late callback from blocked worker.
        self._mouse_api_connect_job_id += 1
        self._mouse_api_connecting = False
        self._set_status_indicator(f"Status: Mouse API timeout ({mode})", COLOR_DANGER)

    def _update_capture_ui(self):
        """根據選擇的採集方法更新 UI"""
        if not hasattr(self, "capture_content_frame"):
            return
        try:
            if not self.capture_content_frame.winfo_exists():
                return
        except Exception:
            return
        prev_ignore = getattr(self, "_ignore_settings_events", False)
        self._ignore_settings_events = True
        # 淇濆瓨鐣跺墠 UDP 杓稿叆妗嗙殑鍊硷紙濡傛灉瀛樺湪锛?
        if hasattr(self, 'udp_ip_entry') and self.udp_ip_entry.winfo_exists():
            self.saved_udp_ip = self.udp_ip_entry.get()
        if hasattr(self, 'udp_port_entry') and self.udp_port_entry.winfo_exists():
            self.saved_udp_port = self.udp_port_entry.get()
        if hasattr(self, 'teleport_host_entry') and self.teleport_host_entry.winfo_exists():
            self.saved_teleport_host = self.teleport_host_entry.get()
        if hasattr(self, 'teleport_port_entry') and self.teleport_port_entry.winfo_exists():
            self.saved_teleport_port = self.teleport_port_entry.get()
        if hasattr(self, 'teleport_stream_option') and self.teleport_stream_option.winfo_exists():
            selected_display = self.teleport_stream_option.get()
            selected_key = self._teleport_stream_display_to_key.get(str(selected_display), "")
            self.saved_teleport_stream_key = str(selected_key)
        
        # 淇濆瓨鐣跺墠 NDI 閬告搰鐨勬簮锛堝鏋滃瓨鍦級
        if hasattr(self, 'source_option') and self.source_option.winfo_exists():
            current_selection = self.source_option.get()
            if current_selection not in ["(Scanning...)", "(no sources)"]:
                self.saved_ndi_source = current_selection
        
        # 娓呴櫎鑸婄殑 UI 鍏冪礌
        for widget in self.capture_content_frame.winfo_children():
            widget.destroy()
        
        # Add FPS Limit control at the top (applies to all capture methods)
        self._add_subtitle_in_frame(self.capture_content_frame, "PROCESSING FPS LIMIT")
        
        fps_limit_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
        fps_limit_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(fps_limit_frame, text="Target FPS", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
        self.fps_limit_entry = ctk.CTkEntry(fps_limit_frame, fg_color=COLOR_SURFACE, border_width=0, text_color=COLOR_TEXT, width=150)
        self.fps_limit_entry.pack(side="right")
        target_fps = str(getattr(config, "target_fps", 200))
        self.fps_limit_entry.insert(0, target_fps)
        self.fps_limit_entry.bind("<KeyRelease>", self._on_fps_limit_changed)
        self.fps_limit_entry.bind("<FocusOut>", self._on_fps_limit_changed)
        
        self._add_spacer_in_frame(self.capture_content_frame)
            
        method = self.capture_method_var.get()
        # Map UI display name to internal mode for processing
        if method == "Capture Card (OpenCV)":
            method = "CaptureCard"
        elif method == "Capture Card (GStreamer)":
            method = "CaptureCardGStreamer"
        
        if method == "NDI":
            # NDI Controls
            self._add_subtitle_in_frame(self.capture_content_frame, "NDI SOURCE")
            self.source_option = self._add_option_menu(["(Scanning...)"], self._on_source_selected, parent=self.capture_content_frame)
            self.source_option.pack(fill="x", pady=5)
            
            # 濡傛灉鏈変繚瀛樼殑 NDI 婧愶紝鍢楄│鎭㈠京
            if self.saved_ndi_source:
                # 绋嶅緦鍦?_apply_sources_to_ui 涓渻鏇存柊婧愬垪琛ㄤ甫鎭㈠京閬告搰
                pass
            
            btn_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            btn_frame.pack(fill="x", pady=10)
            self._add_text_button(btn_frame, "REFRESH", self._refresh_sources).pack(side="left")
            
            # NDI FOV 瑁佸垏瑷畾
            self._add_spacer_in_frame(self.capture_content_frame)
            self._add_subtitle_in_frame(self.capture_content_frame, "CENTER CROP (FOV)")
            
            # Enable FOV Crop Checkbox
            if not hasattr(self, 'var_ndi_fov_enabled'):
                self.var_ndi_fov_enabled = tk.BooleanVar(value=getattr(config, "ndi_fov_enabled", False))
            
            fov_enable_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            fov_enable_frame.pack(fill="x", pady=5)
            ctk.CTkLabel(fov_enable_frame, text="Enable Center Crop", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            ndi_fov_switch = ctk.CTkSwitch(
                fov_enable_frame,
                text="",
                variable=self.var_ndi_fov_enabled,
                command=self._on_ndi_fov_enabled_changed,
                fg_color=COLOR_SURFACE,
                progress_color=COLOR_ACCENT,
                button_color=COLOR_ACCENT,
                button_hover_color=COLOR_ACCENT_HOVER,
                width=50,
                height=20
            )
            ndi_fov_switch.pack(side="right")
            
            # FOV Slider (姝ｆ柟褰㈣鍒囷紝鍙渶瑕佷竴鍊嬪€?
            fov_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            fov_frame.pack(fill="x", pady=2)
            fov_header = ctk.CTkFrame(fov_frame, fg_color="transparent")
            fov_header.pack(fill="x")
            ctk.CTkLabel(fov_header, text="FOV (half-size, square crop)", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.ndi_fov_entry = ctk.CTkEntry(
                fov_header, width=80, height=25, fg_color=COLOR_SURFACE,
                border_width=1, border_color=COLOR_BORDER,
                text_color=COLOR_TEXT, font=FONT_MAIN, justify="center"
            )
            init_fov = int(getattr(config, "ndi_fov", 320))
            self.ndi_fov_entry.insert(0, str(init_fov))
            self.ndi_fov_entry.pack(side="right")
            
            self.ndi_fov_slider = ctk.CTkSlider(
                fov_frame, from_=16, to=1920, number_of_steps=100,
                fg_color=COLOR_SURFACE, progress_color=COLOR_ACCENT,
                button_color=COLOR_ACCENT, button_hover_color=COLOR_ACCENT_HOVER,
                height=10,
                command=self._on_ndi_fov_slider_changed
            )
            self.ndi_fov_slider.set(init_fov)
            self.ndi_fov_slider.pack(fill="x", pady=(2, 5))
            self.ndi_fov_entry.bind("<Return>", self._on_ndi_fov_entry_changed)
            self.ndi_fov_entry.bind("<FocusOut>", self._on_ndi_fov_entry_changed)
            
            # 瑁佸垏绡勫湇璩囪▕
            total_size = init_fov * 2
            self.ndi_fov_info_label = ctk.CTkLabel(
                self.capture_content_frame,
                text=f"Crop area: {total_size} x {total_size} px (square, centered on frame)",
                font=("Roboto", 9), text_color=COLOR_TEXT_DIM
            )
            self.ndi_fov_info_label.pack(anchor="w", pady=(0, 5))
            
        elif method == "UDP":
            # UDP Controls
            self._add_subtitle_in_frame(self.capture_content_frame, "UDP SETTINGS")
            
            # IP Input - 浣跨敤淇濆瓨鐨勫€?
            ip_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            ip_frame.pack(fill="x", pady=5)
            ctk.CTkLabel(ip_frame, text="IP Address", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.udp_ip_entry = ctk.CTkEntry(ip_frame, fg_color=COLOR_SURFACE, border_width=0, text_color=COLOR_TEXT, width=150)
            self.udp_ip_entry.pack(side="right")
            self.udp_ip_entry.insert(0, self.saved_udp_ip)
            # 缍佸畾浜嬩欢浠ュ鏅備繚瀛?
            self.udp_ip_entry.bind("<KeyRelease>", self._on_udp_ip_changed)
            self.udp_ip_entry.bind("<FocusOut>", self._on_udp_ip_changed)
            
            # Port Input - 浣跨敤淇濆瓨鐨勫€?
            port_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            port_frame.pack(fill="x", pady=5)
            ctk.CTkLabel(port_frame, text="Port", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.udp_port_entry = ctk.CTkEntry(port_frame, fg_color=COLOR_SURFACE, border_width=0, text_color=COLOR_TEXT, width=150)
            self.udp_port_entry.pack(side="right")
            self.udp_port_entry.insert(0, self.saved_udp_port)
            # 缍佸畾浜嬩欢浠ュ鏅備繚瀛?
            self.udp_port_entry.bind("<KeyRelease>", self._on_udp_port_changed)
            self.udp_port_entry.bind("<FocusOut>", self._on_udp_port_changed)

            # Static hint (no i18n key on purpose: the i18n tests pin the key set).
            ctk.CTkLabel(
                self.capture_content_frame,
                text="Stream UDP 5000 \u00b7 Beep UDP 4455",
                font=("Roboto", 9), text_color=COLOR_TEXT_DIM
            ).pack(anchor="w", pady=(0, 3))
            
            # UDP FOV 瑁佸垏瑷畾
            self._add_spacer_in_frame(self.capture_content_frame)
            self._add_subtitle_in_frame(self.capture_content_frame, "CENTER CROP (FOV)")
            
            # Enable FOV Crop Checkbox
            if not hasattr(self, 'var_udp_fov_enabled'):
                self.var_udp_fov_enabled = tk.BooleanVar(value=getattr(config, "udp_fov_enabled", False))
            
            fov_enable_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            fov_enable_frame.pack(fill="x", pady=5)
            ctk.CTkLabel(fov_enable_frame, text="Enable Center Crop", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            udp_fov_switch = ctk.CTkSwitch(
                fov_enable_frame,
                text="",
                variable=self.var_udp_fov_enabled,
                command=self._on_udp_fov_enabled_changed,
                fg_color=COLOR_SURFACE,
                progress_color=COLOR_ACCENT,
                button_color=COLOR_ACCENT,
                button_hover_color=COLOR_ACCENT_HOVER,
                width=50,
                height=20
            )
            udp_fov_switch.pack(side="right")
            
            # FOV Slider (姝ｆ柟褰㈣鍒囷紝鍙渶瑕佷竴鍊嬪€?
            fov_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            fov_frame.pack(fill="x", pady=2)
            fov_header = ctk.CTkFrame(fov_frame, fg_color="transparent")
            fov_header.pack(fill="x")
            ctk.CTkLabel(fov_header, text="FOV (half-size, square crop)", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.udp_fov_entry = ctk.CTkEntry(
                fov_header, width=80, height=25, fg_color=COLOR_SURFACE,
                border_width=1, border_color=COLOR_BORDER,
                text_color=COLOR_TEXT, font=FONT_MAIN, justify="center"
            )
            init_fov = int(getattr(config, "udp_fov", 320))
            self.udp_fov_entry.insert(0, str(init_fov))
            self.udp_fov_entry.pack(side="right")
            
            self.udp_fov_slider = ctk.CTkSlider(
                fov_frame, from_=16, to=1920, number_of_steps=100,
                fg_color=COLOR_SURFACE, progress_color=COLOR_ACCENT,
                button_color=COLOR_ACCENT, button_hover_color=COLOR_ACCENT_HOVER,
                height=10,
                command=self._on_udp_fov_slider_changed
            )
            self.udp_fov_slider.set(init_fov)
            self.udp_fov_slider.pack(fill="x", pady=(2, 5))
            self.udp_fov_entry.bind("<Return>", self._on_udp_fov_entry_changed)
            self.udp_fov_entry.bind("<FocusOut>", self._on_udp_fov_entry_changed)
            
            # 瑁佸垏绡勫湇璩囪▕
            total_size = init_fov * 2
            self.udp_fov_info_label = ctk.CTkLabel(
                self.capture_content_frame,
                text=f"Crop area: {total_size} x {total_size} px (square, centered on frame)",
                font=("Roboto", 9), text_color=COLOR_TEXT_DIM
            )
            self.udp_fov_info_label.pack(anchor="w", pady=(0, 5))

        elif method == "Teleport":
            # Teleport Controls
            self._add_subtitle_in_frame(self.capture_content_frame, "OBS TELEPORT")
            ctk.CTkLabel(
                self.capture_content_frame,
                text="Use discovered stream or provide manual Host/Port.",
                font=("Roboto", 9),
                text_color=COLOR_TEXT_DIM,
            ).pack(anchor="w", pady=(0, 8))

            if hasattr(self.capture, "ensure_teleport_discovery_running"):
                self.capture.ensure_teleport_discovery_running()

            self.teleport_stream_option = self._add_option_row_in_frame(
                self.capture_content_frame,
                "Discovered Stream",
                ["Manual Endpoint"],
                self._on_teleport_stream_selected,
            )
            self._refresh_teleport_streams(show_status=False)

            host_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            host_frame.pack(fill="x", pady=5)
            ctk.CTkLabel(host_frame, text="Host", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.teleport_host_entry = ctk.CTkEntry(
                host_frame,
                fg_color=COLOR_SURFACE,
                border_width=0,
                text_color=COLOR_TEXT,
                width=180,
            )
            self.teleport_host_entry.pack(side="right")
            self.teleport_host_entry.insert(0, self.saved_teleport_host)
            self.teleport_host_entry.bind("<KeyRelease>", self._on_teleport_host_changed)
            self.teleport_host_entry.bind("<FocusOut>", self._on_teleport_host_changed)

            port_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            port_frame.pack(fill="x", pady=5)
            ctk.CTkLabel(port_frame, text="Port", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.teleport_port_entry = ctk.CTkEntry(
                port_frame,
                fg_color=COLOR_SURFACE,
                border_width=0,
                text_color=COLOR_TEXT,
                width=180,
            )
            self.teleport_port_entry.pack(side="right")
            self.teleport_port_entry.insert(0, self.saved_teleport_port)
            self.teleport_port_entry.bind("<KeyRelease>", self._on_teleport_port_changed)
            self.teleport_port_entry.bind("<FocusOut>", self._on_teleport_port_changed)

            btn_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            btn_frame.pack(fill="x", pady=10)
            self._add_text_button(btn_frame, "REFRESH", self._refresh_teleport_streams).pack(side="left")
            
        elif method in ["CaptureCard", "CaptureCardGStreamer"]:
            # CaptureCard Controls (shared UI for both OpenCV and GStreamer)
            self._add_subtitle_in_frame(self.capture_content_frame, "CAPTURE CARD SETTINGS")

            if self._runtime_settings_locked():
                capture_devices = list(getattr(self, "_cached_capture_card_devices", []) or [])
                if not capture_devices:
                    idx = int(getattr(config, "capture_device_index", 0))
                    name = str(getattr(config, "capture_device_name", "")).strip()
                    label = name or f"Device {idx}"
                    capture_devices = [{"label": label, "index": idx, "name": name}]
                    self._capture_card_display_to_index = {label: idx}
                    self._capture_card_display_to_name = {label: name}
            else:
                capture_devices = self._scan_capture_card_devices()
                self._cached_capture_card_devices = list(capture_devices)

            if method == "CaptureCard":
                backend_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
                backend_frame.pack(fill="x", pady=5)
                ctk.CTkLabel(backend_frame, text="OpenCV Backend", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
                self.capture_opencv_backend_option = self._add_option_menu(
                    ["DirectShow", "UVC"],
                    self._on_capture_opencv_backend_selected,
                    parent=backend_frame,
                )
                self.capture_opencv_backend_option.pack(side="right")
                current_backend = str(getattr(config, "capture_opencv_backend", "dshow")).strip().lower()
                self.capture_opencv_backend_option.set("UVC" if current_backend in ("uvc", "msmf") else "DirectShow")
                ctk.CTkLabel(
                    self.capture_content_frame,
                    text="DirectShow = CAP_DSHOW. UVC = Windows Media Foundation (CAP_MSMF), typical for USB Video Class cards.",
                    font=("Roboto", 9),
                    text_color=COLOR_TEXT_DIM,
                    anchor="w",
                    justify="left",
                    wraplength=720,
                ).pack(fill="x", pady=(0, 6))

            # Device Selection
            device_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            device_frame.pack(fill="x", pady=5)
            ctk.CTkLabel(device_frame, text="Capture Device", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            device_actions = ctk.CTkFrame(device_frame, fg_color="transparent")
            device_actions.pack(side="right")
            device_values = [item["label"] for item in capture_devices] if capture_devices else ["No devices detected"]
            self.capture_card_device_option = self._add_option_menu(
                device_values,
                self._on_capture_card_device_selected,
                parent=device_actions,
            )
            self.capture_card_device_option.pack(side="left")
            self._add_text_button(
                device_actions,
                "REFRESH",
                self._refresh_capture_card_devices,
            ).pack(side="left", padx=(8, 0))
            selected_device_label = self._get_capture_card_selected_label(capture_devices)
            self.capture_card_device_option.set(selected_device_label)

            probe_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            probe_frame.pack(fill="x", pady=(0, 5))
            self._add_text_button(
                probe_frame,
                "PROBE",
                self._probe_capture_card_device,
            ).pack(side="right")
            self.capture_card_probe_info_label = ctk.CTkLabel(
                probe_frame,
                text="Probe selected device to list resolution / FPS / format.",
                font=("Roboto", 9),
                text_color=COLOR_TEXT_DIM,
                anchor="w",
                justify="left",
            )
            self.capture_card_probe_info_label.pack(side="left")

            self.capture_card_probe_result_label = ctk.CTkLabel(
                self.capture_content_frame,
                text="Supported formats to probe: MJPG, NV12, YUY2, YUYV, BGR24",
                font=("Roboto", 9),
                text_color=COLOR_TEXT_DIM,
                anchor="w",
                justify="left",
                wraplength=760,
            )
            self.capture_card_probe_result_label.pack(fill="x", pady=(0, 6))

            self.capture_card_probe_list = ctk.CTkScrollableFrame(
                self.capture_content_frame,
                fg_color=COLOR_SURFACE,
                corner_radius=8,
                border_width=1,
                border_color=COLOR_BORDER,
                height=150,
            )
            self.capture_card_probe_list.pack(fill="x", pady=(0, 8))
            self._render_capture_card_probe_rows([])
            
            # Resolution
            res_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            res_frame.pack(fill="x", pady=5)
            ctk.CTkLabel(res_frame, text="Resolution (WxH)", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            res_input_frame = ctk.CTkFrame(res_frame, fg_color="transparent")
            res_input_frame.pack(side="right")
            self.capture_card_width_entry = ctk.CTkEntry(res_input_frame, fg_color=COLOR_SURFACE, border_width=0, text_color=COLOR_TEXT, width=70)
            self.capture_card_width_entry.pack(side="left", padx=2)
            ctk.CTkLabel(res_input_frame, text="x", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left", padx=5)
            self.capture_card_height_entry = ctk.CTkEntry(res_input_frame, fg_color=COLOR_SURFACE, border_width=0, text_color=COLOR_TEXT, width=70)
            self.capture_card_height_entry.pack(side="left", padx=2)
            width = str(getattr(config, "capture_width", 1920))
            height = str(getattr(config, "capture_height", 1080))
            self.capture_card_width_entry.insert(0, width)
            self.capture_card_height_entry.insert(0, height)
            self.capture_card_width_entry.bind("<KeyRelease>", self._on_capture_card_resolution_changed)
            self.capture_card_width_entry.bind("<FocusOut>", self._on_capture_card_resolution_changed)
            self.capture_card_height_entry.bind("<KeyRelease>", self._on_capture_card_resolution_changed)
            self.capture_card_height_entry.bind("<FocusOut>", self._on_capture_card_resolution_changed)
            
            format_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            format_frame.pack(fill="x", pady=5)
            ctk.CTkLabel(format_frame, text="Format", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            format_values = ["MJPG", "NV12", "YUY2", "YUYV", "BGR24"]
            self.capture_card_format_option = self._add_option_menu(
                format_values,
                self._on_capture_card_format_selected,
                parent=format_frame,
            )
            self.capture_card_format_option.pack(side="right")
            current_format = str((getattr(config, "capture_fourcc_preference", ["MJPG"]) or ["MJPG"])[0]).upper()
            if current_format == "BGR3":
                current_format = "BGR24"
            if current_format not in format_values:
                current_format = "MJPG"
            self.capture_card_format_option.set(current_format)
            
            self._add_spacer_in_frame(self.capture_content_frame)
            self._add_subtitle_in_frame(self.capture_content_frame, "CAPTURE REGION")
            
            # Capture Range X
            range_x_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            range_x_frame.pack(fill="x", pady=5)
            ctk.CTkLabel(range_x_frame, text="Range X (min: 128)", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.capture_card_range_x_entry = ctk.CTkEntry(range_x_frame, fg_color=COLOR_SURFACE, border_width=0, text_color=COLOR_TEXT, width=150)
            self.capture_card_range_x_entry.pack(side="right")
            range_x = str(getattr(config, "capture_range_x", 128))
            self.capture_card_range_x_entry.insert(0, range_x)
            self.capture_card_range_x_entry.bind("<KeyRelease>", self._on_capture_card_range_keyrelease)
            self.capture_card_range_x_entry.bind("<FocusOut>", self._on_capture_card_range_focusout)
            
            # Capture Range Y
            range_y_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            range_y_frame.pack(fill="x", pady=5)
            ctk.CTkLabel(range_y_frame, text="Range Y (min: 128)", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.capture_card_range_y_entry = ctk.CTkEntry(range_y_frame, fg_color=COLOR_SURFACE, border_width=0, text_color=COLOR_TEXT, width=150)
            self.capture_card_range_y_entry.pack(side="right")
            range_y = str(getattr(config, "capture_range_y", 128))
            self.capture_card_range_y_entry.insert(0, range_y)
            self.capture_card_range_y_entry.bind("<KeyRelease>", self._on_capture_card_range_keyrelease)
            self.capture_card_range_y_entry.bind("<FocusOut>", self._on_capture_card_range_focusout)
            
            # 椤ず涓績榛炰俊鎭?
            center_info_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            center_info_frame.pack(fill="x", pady=5)
            self.capture_card_center_label = ctk.CTkLabel(
                center_info_frame, 
                text="Center: (0, 0)", 
                font=("Roboto", 10), 
                text_color=COLOR_TEXT_DIM
            )
            self.capture_card_center_label.pack(side="left")
            # 鏇存柊涓績榛為’绀?
            self._update_capture_card_center_display()
        
        elif method == "MSS":
            # MSS Screen Capture Controls
            self._add_subtitle_in_frame(self.capture_content_frame, "MSS SCREEN CAPTURE")
            ctk.CTkLabel(
                self.capture_content_frame,
                text="For dual-PC streaming users (e.g., Moonlight), pair MSS with SendInput.",
                font=("Roboto", 10, "bold"),
                text_color=COLOR_DANGER,
            ).pack(anchor="w", pady=(0, 8))
            
            # Monitor Index
            monitor_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            monitor_frame.pack(fill="x", pady=5)
            ctk.CTkLabel(monitor_frame, text="Monitor Index", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.mss_monitor_entry = ctk.CTkEntry(
                monitor_frame, fg_color=COLOR_SURFACE, border_width=0,
                text_color=COLOR_TEXT, width=150
            )
            self.mss_monitor_entry.pack(side="right")
            self.mss_monitor_entry.insert(0, str(getattr(config, "mss_monitor_index", 1)))
            self.mss_monitor_entry.bind("<KeyRelease>", self._on_mss_monitor_changed)
            self.mss_monitor_entry.bind("<FocusOut>", self._on_mss_monitor_changed)
            
            # 鍙敤铻㈠箷鍒楄〃璩囪▕
            try:
                from src.capture.mss_capture import MSSCapture, HAS_MSS
                if HAS_MSS:
                    temp_mss = MSSCapture()
                    monitor_list = temp_mss.get_monitor_list()
                    if monitor_list:
                        info_text = " | ".join(monitor_list)
                    else:
                        info_text = "No monitors detected"
                else:
                    info_text = "mss not installed (pip install mss)"
            except Exception:
                info_text = "Unable to detect monitors"
            
            ctk.CTkLabel(
                self.capture_content_frame, text=info_text,
                font=("Roboto", 9), text_color=COLOR_TEXT_DIM
            ).pack(anchor="w", pady=(0, 5))
            
            self._add_spacer_in_frame(self.capture_content_frame)
            self._add_subtitle_in_frame(self.capture_content_frame, "CAPTURE FOV (center-based)")
            
            # FOV X Slider
            fov_x_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            fov_x_frame.pack(fill="x", pady=2)
            fov_x_header = ctk.CTkFrame(fov_x_frame, fg_color="transparent")
            fov_x_header.pack(fill="x")
            ctk.CTkLabel(fov_x_header, text="FOV X (half-width)", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.mss_fov_x_entry = ctk.CTkEntry(
                fov_x_header, width=80, height=25, fg_color=COLOR_SURFACE,
                border_width=1, border_color=COLOR_BORDER,
                text_color=COLOR_TEXT, font=FONT_MAIN, justify="center"
            )
            init_fov_x = int(getattr(config, "mss_fov_x", 320))
            self.mss_fov_x_entry.insert(0, str(init_fov_x))
            self.mss_fov_x_entry.pack(side="right")
            
            self.mss_fov_x_slider = ctk.CTkSlider(
                fov_x_frame, from_=16, to=1920, number_of_steps=100,
                fg_color=COLOR_SURFACE, progress_color=COLOR_ACCENT,
                button_color=COLOR_ACCENT, button_hover_color=COLOR_ACCENT_HOVER,
                height=10,
                command=self._on_mss_fov_x_slider_changed
            )
            self.mss_fov_x_slider.set(init_fov_x)
            self.mss_fov_x_slider.pack(fill="x", pady=(2, 5))
            self.mss_fov_x_entry.bind("<Return>", self._on_mss_fov_x_entry_changed)
            self.mss_fov_x_entry.bind("<FocusOut>", self._on_mss_fov_x_entry_changed)
            
            # FOV Y Slider
            fov_y_frame = ctk.CTkFrame(self.capture_content_frame, fg_color="transparent")
            fov_y_frame.pack(fill="x", pady=2)
            fov_y_header = ctk.CTkFrame(fov_y_frame, fg_color="transparent")
            fov_y_header.pack(fill="x")
            ctk.CTkLabel(fov_y_header, text="FOV Y (half-height)", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
            self.mss_fov_y_entry = ctk.CTkEntry(
                fov_y_header, width=80, height=25, fg_color=COLOR_SURFACE,
                border_width=1, border_color=COLOR_BORDER,
                text_color=COLOR_TEXT, font=FONT_MAIN, justify="center"
            )
            init_fov_y = int(getattr(config, "mss_fov_y", 320))
            self.mss_fov_y_entry.insert(0, str(init_fov_y))
            self.mss_fov_y_entry.pack(side="right")
            
            self.mss_fov_y_slider = ctk.CTkSlider(
                fov_y_frame, from_=16, to=1080, number_of_steps=100,
                fg_color=COLOR_SURFACE, progress_color=COLOR_ACCENT,
                button_color=COLOR_ACCENT, button_hover_color=COLOR_ACCENT_HOVER,
                height=10,
                command=self._on_mss_fov_y_slider_changed
            )
            self.mss_fov_y_slider.set(init_fov_y)
            self.mss_fov_y_slider.pack(fill="x", pady=(2, 5))
            self.mss_fov_y_entry.bind("<Return>", self._on_mss_fov_y_entry_changed)
            self.mss_fov_y_entry.bind("<FocusOut>", self._on_mss_fov_y_entry_changed)
            
            # 鎿峰彇绡勫湇璩囪▕
            total_w = init_fov_x * 2
            total_h = init_fov_y * 2
            self.mss_capture_info_label = ctk.CTkLabel(
                self.capture_content_frame,
                text=f"Capture area: {total_w} x {total_h} px (centered on screen)",
                font=("Roboto", 9), text_color=COLOR_TEXT_DIM
            )
            self.mss_capture_info_label.pack(anchor="w", pady=(0, 5))
        self._ignore_settings_events = prev_ignore
        self._apply_runtime_settings_lock()

    def _on_udp_ip_changed(self, event=None):
        """瀵︽檪淇濆瓨 UDP IP"""
        if self._runtime_settings_locked():
            return
        if hasattr(self, 'udp_ip_entry') and self.udp_ip_entry.winfo_exists():
            val = self.udp_ip_entry.get()
            self.saved_udp_ip = val
            config.udp_ip = val

    def _on_udp_port_changed(self, event=None):
        """瀵︽檪淇濆瓨 UDP Port"""
        if self._runtime_settings_locked():
            return
        if hasattr(self, 'udp_port_entry') and self.udp_port_entry.winfo_exists():
            val = self.udp_port_entry.get()
            self.saved_udp_port = val
            config.udp_port = val

    def _refresh_teleport_streams(self, show_status=True):
        """Refresh OBS Teleport discovered streams list."""
        if self.capture.mode != "Teleport":
            return

        streams = []
        if hasattr(self.capture, "ensure_teleport_discovery_running"):
            self.capture.ensure_teleport_discovery_running()
        if hasattr(self.capture, "get_teleport_discovered_streams"):
            streams = self.capture.get_teleport_discovered_streams()

        display_to_key = {"Manual Endpoint": ""}
        option_values = ["Manual Endpoint"]
        for stream in streams or []:
            stream_key = str(stream.get("key", "")).strip()
            if not stream_key:
                continue
            name = str(stream.get("name", "Unknown")).strip() or "Unknown"
            address = str(stream.get("address", "")).strip()
            try:
                port = int(stream.get("port", 0) or 0)
            except Exception:
                port = 0
            label_base = f"{name} ({address}:{port})" if address else f"{name} ({port})"
            label = label_base
            suffix = 2
            while label in display_to_key:
                label = f"{label_base} #{suffix}"
                suffix += 1
            display_to_key[label] = stream_key
            option_values.append(label)

        self._teleport_stream_display_to_key = display_to_key

        if hasattr(self, "teleport_stream_option") and self.teleport_stream_option.winfo_exists():
            self.teleport_stream_option.configure(values=option_values)

            selected_key = str(getattr(config, "teleport_stream_key", self.saved_teleport_stream_key)).strip()
            selected_display = "Manual Endpoint"
            for display_text, key in display_to_key.items():
                if key and key == selected_key:
                    selected_display = display_text
                    break
            self.teleport_stream_option.set(selected_display)
            self._on_teleport_stream_selected(selected_display)

        if show_status:
            self._set_status_indicator(
                f"Status: Teleport streams {max(0, len(option_values) - 1)}",
                COLOR_TEXT,
            )

    def _on_teleport_stream_selected(self, val):
        """Handle Teleport discovered stream selection."""
        if self._runtime_settings_locked():
            return
        stream_key = str(self._teleport_stream_display_to_key.get(str(val), "")).strip()
        self.saved_teleport_stream_key = stream_key
        config.teleport_stream_key = stream_key

    def _on_teleport_host_changed(self, event=None):
        """Handle Teleport host input update."""
        if self._runtime_settings_locked():
            return
        if hasattr(self, "teleport_host_entry") and self.teleport_host_entry.winfo_exists():
            host = self.teleport_host_entry.get().strip()
            self.saved_teleport_host = host
            config.teleport_host = host

    def _on_teleport_port_changed(self, event=None):
        """Handle Teleport port input update."""
        if self._runtime_settings_locked():
            return
        if hasattr(self, "teleport_port_entry") and self.teleport_port_entry.winfo_exists():
            port_text = self.teleport_port_entry.get().strip()
            self.saved_teleport_port = port_text
            config.teleport_port = port_text

    def _connect_teleport(self):
        """Connect OBS Teleport source."""
        if self.capture.mode != "Teleport":
            return

        host = str(getattr(config, "teleport_host", self.saved_teleport_host)).strip()
        port_value = str(getattr(config, "teleport_port", self.saved_teleport_port)).strip()
        stream_key = str(getattr(config, "teleport_stream_key", self.saved_teleport_stream_key)).strip()

        if hasattr(self, "teleport_host_entry") and self.teleport_host_entry.winfo_exists():
            host = self.teleport_host_entry.get().strip()
        if hasattr(self, "teleport_port_entry") and self.teleport_port_entry.winfo_exists():
            port_value = self.teleport_port_entry.get().strip()
        if hasattr(self, "teleport_stream_option") and self.teleport_stream_option.winfo_exists():
            selected_display = self.teleport_stream_option.get()
            stream_key = str(self._teleport_stream_display_to_key.get(str(selected_display), "")).strip()

        self.saved_teleport_host = host
        self.saved_teleport_port = port_value
        self.saved_teleport_stream_key = stream_key
        config.teleport_host = host
        config.teleport_port = port_value
        config.teleport_stream_key = stream_key

        success, error = self.capture.connect_teleport(
            host=host,
            port=port_value,
            stream_key=stream_key,
        )
        if success:
            snapshot = {}
            if hasattr(self.capture, "get_teleport_connection_snapshot"):
                snapshot = self.capture.get_teleport_connection_snapshot()
            phase = str(snapshot.get("phase", "")).strip()
            if phase == "Connected":
                self._set_status_indicator("Status: Teleport connected", COLOR_TEXT)
            elif phase in ("Connecting", "WaitingForDiscovery", "WaitingForEndpoint"):
                self._set_status_indicator(f"Status: Teleport {phase}", COLOR_WARNING)
            else:
                self._set_status_indicator("Status: Teleport started", COLOR_TEXT)
        else:
            self._set_status_indicator(f"Status: Teleport connect failed: {error}", COLOR_DANGER)
            log_print(f"[UI] Teleport connection failed: {error}")
    
    def _on_capture_card_device_changed(self, event=None):
        """瀵︽檪淇濆瓨 CaptureCard Device Index"""
        if self._runtime_settings_locked():
            return
        if hasattr(self, 'capture_card_device_entry') and self.capture_card_device_entry.winfo_exists():
            try:
                val = int(self.capture_card_device_entry.get())
                config.capture_device_index = val
            except ValueError:
                pass

    def _scan_capture_card_devices(self):
        """Scan capture devices for OpenCV DirectShow / UVC."""
        devices = []
        self._capture_card_display_to_index = {}
        self._capture_card_display_to_name = {}
        try:
            from src.capture.CaptureCard import enumerate_capture_card_devices

            devices = enumerate_capture_card_devices(max_index=10)
        except Exception as e:
            log_print(f"[UI] Capture card device scan failed: {e}")

        for item in devices:
            label = str(item["label"])
            self._capture_card_display_to_index[label] = int(item["index"])
            self._capture_card_display_to_name[label] = str(item.get("name", "")).strip()
        return devices

    def _get_capture_card_selected_label(self, devices):
        current_index = int(getattr(config, "capture_device_index", 0))
        current_name = str(getattr(config, "capture_device_name", "")).strip().lower()
        if current_name:
            for item in devices:
                if str(item.get("name", "")).strip().lower() == current_name:
                    return str(item["label"])
        for item in devices:
            if int(item["index"]) == current_index:
                return str(item["label"])
        if devices:
            if self._runtime_settings_locked():
                return str(devices[0]["label"])
            first = devices[0]
            try:
                config.capture_device_index = int(first["index"])
                config.capture_device_name = str(first.get("name", "")).strip()
            except Exception:
                pass
            return str(first["label"])
        return "No devices detected"

    def _restore_locked_capture_card_device_option(self):
        if not hasattr(self, "capture_card_device_option"):
            return
        try:
            if not self.capture_card_device_option.winfo_exists():
                return
        except Exception:
            return
        devices = list(getattr(self, "_cached_capture_card_devices", []) or [])
        self._ignore_settings_events = True
        try:
            self.capture_card_device_option.set(self._get_capture_card_selected_label(devices))
        except Exception:
            pass
        self._ignore_settings_events = False

    def _restore_locked_capture_opencv_backend_option(self):
        if not hasattr(self, "capture_opencv_backend_option"):
            return
        try:
            if not self.capture_opencv_backend_option.winfo_exists():
                return
        except Exception:
            return
        current_backend = str(getattr(config, "capture_opencv_backend", "dshow")).strip().lower()
        self._ignore_settings_events = True
        try:
            self.capture_opencv_backend_option.set("UVC" if current_backend in ("uvc", "msmf") else "DirectShow")
        except Exception:
            pass
        self._ignore_settings_events = False

    def _on_capture_card_device_selected(self, selected_label):
        if getattr(self, "_ignore_settings_events", False):
            return
        if self._runtime_settings_locked():
            self._restore_locked_capture_card_device_option()
            self._warn_runtime_settings_locked("capture")
            return
        try:
            if str(selected_label) not in self._capture_card_display_to_index:
                return
            config.capture_device_index = int(self._capture_card_display_to_index[str(selected_label)])
            config.capture_device_name = str(self._capture_card_display_to_name.get(str(selected_label), "")).strip()
        except Exception:
            pass

    def _on_capture_opencv_backend_selected(self, selected_backend):
        if getattr(self, "_ignore_settings_events", False):
            return
        if self._runtime_settings_locked():
            self._restore_locked_capture_opencv_backend_option()
            self._warn_runtime_settings_locked("capture")
            return
        value = str(selected_backend or "").strip().lower()
        config.capture_opencv_backend = "uvc" if value == "uvc" else "dshow"
        self._refresh_capture_entry_card()

    def _refresh_capture_card_devices(self):
        if self._runtime_settings_locked():
            self._warn_runtime_settings_locked("capture")
            return
        devices = self._scan_capture_card_devices()
        self._cached_capture_card_devices = list(devices)
        values = [item["label"] for item in devices] if devices else ["No devices detected"]
        if hasattr(self, "capture_card_device_option") and self.capture_card_device_option.winfo_exists():
            self.capture_card_device_option.configure(values=values)
            self.capture_card_device_option.set(self._get_capture_card_selected_label(devices))
        if hasattr(self, "capture_card_probe_result_label") and self.capture_card_probe_result_label.winfo_exists():
            summary = f"Detected {len(devices)} capture device(s)." if devices else "No capture devices detected."
            self.capture_card_probe_result_label.configure(text=summary)
        self._set_status_indicator("Status: Capture devices refreshed", COLOR_TEXT_DIM)

    def _render_capture_card_probe_rows(self, formats):
        if not hasattr(self, "capture_card_probe_list") or not self.capture_card_probe_list.winfo_exists():
            return

        for widget in self.capture_card_probe_list.winfo_children():
            widget.destroy()

        header = ctk.CTkFrame(self.capture_card_probe_list, fg_color="transparent")
        header.pack(fill="x", pady=(2, 4))
        ctk.CTkLabel(header, text="Resolution", font=("Roboto", 10, "bold"), text_color=COLOR_TEXT, width=180, anchor="w").pack(side="left", padx=(6, 4))
        ctk.CTkLabel(header, text="FPS", font=("Roboto", 10, "bold"), text_color=COLOR_TEXT, width=120, anchor="w").pack(side="left", padx=4)
        ctk.CTkLabel(header, text="Format", font=("Roboto", 10, "bold"), text_color=COLOR_TEXT, width=120, anchor="w").pack(side="left", padx=4)

        if not formats:
            ctk.CTkLabel(
                self.capture_card_probe_list,
                text="No probed modes yet.",
                font=("Roboto", 9),
                text_color=COLOR_TEXT_DIM,
                anchor="w",
            ).pack(fill="x", padx=6, pady=(2, 6))
            return

        for item in formats:
            row = ctk.CTkFrame(self.capture_card_probe_list, fg_color="transparent")
            row.pack(fill="x", pady=1)
            resolution = f'{item.get("width")}x{item.get("height")}'
            fps_text = f'{item.get("fps")}'
            fmt = str(item.get("format", "")).upper()
            if fmt == "BGR3":
                fmt = "BGR24"
            ctk.CTkLabel(row, text=resolution, font=("Roboto", 9), text_color=COLOR_TEXT, width=180, anchor="w").pack(side="left", padx=(6, 4))
            ctk.CTkLabel(row, text=fps_text, font=("Roboto", 9), text_color=COLOR_TEXT, width=120, anchor="w").pack(side="left", padx=4)
            ctk.CTkLabel(row, text=fmt, font=("Roboto", 9), text_color=COLOR_TEXT, width=120, anchor="w").pack(side="left", padx=4)

    def _probe_capture_card_device(self):
        if self._runtime_settings_locked():
            self._warn_runtime_settings_locked("capture")
            return
        self._set_status_indicator("Status: Probing capture card...", COLOR_TEXT_DIM)
        if hasattr(self, "capture_card_probe_info_label") and self.capture_card_probe_info_label.winfo_exists():
            self.capture_card_probe_info_label.configure(text="Probing selected device...")

        device_index = int(getattr(config, "capture_device_index", 0))

        def _worker():
            try:
                from src.capture.CaptureCard import probe_capture_card_device

                result = probe_capture_card_device(
                    device_index=device_index,
                    fourcc_values=["MJPG", "NV12", "YUY2", "YUYV", "BGR3"],
                    backend=getattr(config, "capture_opencv_backend", "dshow"),
                    device_name=str(getattr(config, "capture_device_name", "")),
                )
                error = None
            except Exception as e:
                result = {}
                error = str(e)
            self.after(0, lambda: self._on_capture_card_probe_done(result, error))

        threading.Thread(target=_worker, daemon=True, name="CaptureCardProbe").start()

    def _on_capture_card_probe_done(self, result, error):
        if error:
            self._set_status_indicator(f"Status: Capture card probe failed: {error}", COLOR_DANGER)
            self._render_capture_card_probe_rows([])
            if hasattr(self, "capture_card_probe_result_label") and self.capture_card_probe_result_label.winfo_exists():
                self.capture_card_probe_result_label.configure(text=f"Probe failed: {error}")
            return

        if hasattr(self, "capture_card_probe_info_label") and self.capture_card_probe_info_label.winfo_exists():
            self.capture_card_probe_info_label.configure(text=str(result.get("message", "")))

        formats = result.get("formats", []) if isinstance(result, dict) else []
        if formats:
            probe_text = f"Detected {len(formats)} mode(s)."
            self._render_capture_card_probe_rows(formats)
            self._set_status_indicator("Status: Capture card probe complete", COLOR_TEXT)
        else:
            probe_text = str(result.get("message", "No supported modes detected."))
            self._render_capture_card_probe_rows([])
            self._set_status_indicator("Status: Capture card probe found no modes", COLOR_WARNING)

        if hasattr(self, "capture_card_probe_result_label") and self.capture_card_probe_result_label.winfo_exists():
            self.capture_card_probe_result_label.configure(text=probe_text)

    def _on_capture_card_format_selected(self, selected_format):
        if self._runtime_settings_locked():
            self._warn_runtime_settings_locked("capture")
            return
        fmt = str(selected_format or "").strip().upper()
        if not fmt:
            return
        if fmt == "BGR24":
            fmt = "BGR3"
        rest = []
        for item in getattr(config, "capture_fourcc_preference", []):
            item_name = str(item).upper()
            if item_name == fmt:
                continue
            rest.append(item_name)
        config.capture_fourcc_preference = [fmt] + rest
    
    def _on_capture_card_resolution_changed(self, event=None):
        """瀵︽檪淇濆瓨 CaptureCard Resolution"""
        if self._runtime_settings_locked():
            return
        if hasattr(self, 'capture_card_width_entry') and hasattr(self, 'capture_card_height_entry'):
            if self.capture_card_width_entry.winfo_exists() and self.capture_card_height_entry.winfo_exists():
                try:
                    width = int(self.capture_card_width_entry.get())
                    height = int(self.capture_card_height_entry.get())
                    config.capture_width = width
                    config.capture_height = height
                except ValueError:
                    pass
    
    def _on_fps_limit_changed(self, event=None):
        """Handle FPS limit change"""
        if self._runtime_settings_locked():
            return
        try:
            if not hasattr(self, 'fps_limit_entry'):
                return
            fps = float(self.fps_limit_entry.get())
            if fps < 1 or fps > 1000:
                fps = 200
                self.fps_limit_entry.delete(0, "end")
                self.fps_limit_entry.insert(0, "200")
            config.target_fps = fps
            config.save_to_file()
            # Update tracker's target FPS dynamically
            if hasattr(self, 'tracker') and self.tracker:
                if hasattr(self.tracker, 'set_target_fps'):
                    self.tracker.set_target_fps(fps)
                else:
                    self.tracker._target_fps = float(fps)
        except ValueError:
            pass
    
    def _on_capture_card_range_keyrelease(self, event=None):
        """鍦ㄨ几鍏ラ亷绋嬩腑鏇存柊涓績榛為’绀猴紙涓嶅挤鍒朵慨鏀硅几鍏ユ锛?"""
        if self._runtime_settings_locked():
            return
        if hasattr(self, 'capture_card_range_x_entry') and hasattr(self, 'capture_card_range_y_entry'):
            if self.capture_card_range_x_entry.winfo_exists() and self.capture_card_range_y_entry.winfo_exists():
                try:
                    range_x_str = self.capture_card_range_x_entry.get()
                    range_y_str = self.capture_card_range_y_entry.get()
                    
                    # 濡傛灉鏄┖瀛楃涓诧紝涓嶈檿鐞嗭紙鍏佽ū鐢ㄦ埗娓呯┖杓稿叆锛?
                    if not range_x_str or not range_y_str:
                        return
                    
                    range_x = int(range_x_str)
                    range_y = int(range_y_str)
                    
                    # 鍙洿鏂颁腑蹇冮粸椤ず锛屼笉鏇存柊閰嶇疆锛堥厤缃湪澶卞幓鐒﹂粸鏅傛洿鏂帮級
                    # 鍏佽ū鐢ㄦ埗杓稿叆浠讳綍鏁稿瓧锛岄璀夊湪澶卞幓鐒﹂粸鏅傞€茶
                    # 鏇存柊涓績榛為’绀猴紙浣跨敤杓稿叆鐨勫€硷紝鍗充娇灏忔柤128涔熼’绀猴級
                    self._update_capture_card_center_display_with_values(range_x, range_y)
                except ValueError:
                    # 濡傛灉杓稿叆涓嶆槸鏁稿瓧锛屼笉铏曠悊锛堝厑瑷辩敤鎴剁辜绾岃几鍏ワ級
                    pass
    
    def _on_capture_card_range_focusout(self, event=None):
        """澶卞幓鐒﹂粸鏅傞璀変甫淇 CaptureCard Range"""
        if self._runtime_settings_locked():
            return
        if hasattr(self, 'capture_card_range_x_entry') and hasattr(self, 'capture_card_range_y_entry'):
            if self.capture_card_range_x_entry.winfo_exists() and self.capture_card_range_y_entry.winfo_exists():
                try:
                    range_x_str = self.capture_card_range_x_entry.get()
                    range_y_str = self.capture_card_range_y_entry.get()
                    
                    # 濡傛灉鏄┖瀛楃涓诧紝鎭㈠京鐐洪粯瑾嶅€?
                    if not range_x_str:
                        range_x = 128
                        self.capture_card_range_x_entry.delete(0, "end")
                        self.capture_card_range_x_entry.insert(0, "128")
                    else:
                        range_x = int(range_x_str)
                        # 纰轰繚鏈€浣庡€肩偤 128
                        if range_x < 128:
                            range_x = 128
                            self.capture_card_range_x_entry.delete(0, "end")
                            self.capture_card_range_x_entry.insert(0, "128")
                    
                    if not range_y_str:
                        range_y = 128
                        self.capture_card_range_y_entry.delete(0, "end")
                        self.capture_card_range_y_entry.insert(0, "128")
                    else:
                        range_y = int(range_y_str)
                        # 纰轰繚鏈€浣庡€肩偤 128
                        if range_y < 128:
                            range_y = 128
                            self.capture_card_range_y_entry.delete(0, "end")
                            self.capture_card_range_y_entry.insert(0, "128")
                    
                    # 鏇存柊閰嶇疆
                    config.capture_range_x = range_x
                    config.capture_range_y = range_y
                    # 鏇存柊涓績榛為’绀?
                    self._update_capture_card_center_display()
                except ValueError:
                    # 濡傛灉杓稿叆涓嶆槸鏁稿瓧锛屾仮寰╃偤鏈夋晥鍊?
                    try:
                        current_x = int(getattr(config, "capture_range_x", 128))
                        if current_x < 128:
                            current_x = 128
                        self.capture_card_range_x_entry.delete(0, "end")
                        self.capture_card_range_x_entry.insert(0, str(current_x))
                        config.capture_range_x = current_x
                    except:
                        self.capture_card_range_x_entry.delete(0, "end")
                        self.capture_card_range_x_entry.insert(0, "128")
                        config.capture_range_x = 128
                    
                    try:
                        current_y = int(getattr(config, "capture_range_y", 128))
                        if current_y < 128:
                            current_y = 128
                        self.capture_card_range_y_entry.delete(0, "end")
                        self.capture_card_range_y_entry.insert(0, str(current_y))
                        config.capture_range_y = current_y
                    except:
                        self.capture_card_range_y_entry.delete(0, "end")
                        self.capture_card_range_y_entry.insert(0, "128")
                        config.capture_range_y = 128
                    
                    # 鏇存柊涓績榛為’绀?
                    self._update_capture_card_center_display()
    
    def _update_capture_card_center_display(self):
        """鏇存柊 CaptureCard 涓績榛為’绀猴紙寰?config 璁€鍙栵級"""
        if hasattr(self, 'capture_card_center_label') and self.capture_card_center_label.winfo_exists():
            try:
                range_x = int(getattr(config, "capture_range_x", 128))
                range_y = int(getattr(config, "capture_range_y", 128))
                
                # 纰轰繚鏈€浣庡€肩偤 128
                if range_x < 128:
                    range_x = 128
                if range_y < 128:
                    range_y = 128
                
                # 濡傛灉绡勫湇鐐?0 鎴栨湭瑷疆锛屼娇鐢ㄩ粯瑾嶅€兼垨鍒嗚鲸鐜?
                if range_x <= 0:
                    range_x = max(128, int(getattr(config, "capture_width", 1920)))
                if range_y <= 0:
                    range_y = max(128, int(getattr(config, "capture_height", 1080)))
                
                # 瑷堢畻涓績榛烇細鍩烘柤 range_x 鍜?range_y 鐨?X/2, Y/2
                center_x = range_x // 2
                center_y = range_y // 2
                
                self.capture_card_center_label.configure(
                    text=f"Center: ({center_x}, {center_y}) | Range: {range_x}x{range_y}"
                )
            except (ValueError, AttributeError):
                self.capture_card_center_label.configure(text="Center: (0, 0)")
    
    def _update_capture_card_center_display_with_values(self, range_x, range_y):
        """鏇存柊 CaptureCard 涓績榛為’绀猴紙浣跨敤鎸囧畾鐨勫€硷級"""
        if hasattr(self, 'capture_card_center_label') and self.capture_card_center_label.winfo_exists():
            try:
                # 浣跨敤鍌冲叆鐨勫€硷紙鍗充娇灏忔柤128涔熼’绀猴紝璁撶敤鎴剁湅鍒拌几鍏ョ殑鍊硷級
                if range_x <= 0:
                    range_x = max(128, int(getattr(config, "capture_width", 1920)))
                if range_y <= 0:
                    range_y = max(128, int(getattr(config, "capture_height", 1080)))
                
                # 瑷堢畻涓績榛烇細鍩烘柤 range_x 鍜?range_y 鐨?X/2, Y/2
                center_x = range_x // 2
                center_y = range_y // 2
                
                self.capture_card_center_label.configure(
                    text=f"Center: ({center_x}, {center_y}) | Range: {range_x}x{range_y}"
                )
            except (ValueError, AttributeError):
                self.capture_card_center_label.configure(text="Center: (0, 0)")

    def _show_aimbot_tab(self):
        if self._ensure_pro_mode("Main Aimbot"):
            return
        self._active_tab_name = "Main Aimbot"
        self._clear_content()
        self._add_sub_nav_bar(
            ["Main Aimbot", "Sec Aimbot", "Flick V2", "Recoil & RCS"],
            "Main Aimbot",
            {
                "Main Aimbot": self._show_aimbot_tab,
                "Sec Aimbot": self._show_sec_aimbot_tab,
                "Flick V2": self._show_flick_v2_tab,
                "Recoil & RCS": self._show_rcs_tab,
            }
        )
        self._add_title("Main Aimbot")

        # Master Control Switches Row
        master_row = ctk.CTkFrame(self.content_frame, fg_color="#141822", corner_radius=8, border_width=1, border_color="#232B3B")
        master_row.pack(fill="x", pady=(0, 10))
        master_inner = ctk.CTkFrame(master_row, fg_color="transparent")
        master_inner.pack(fill="x", padx=12, pady=6)

        self.var_enableaim = tk.BooleanVar(value=getattr(config, "enableaim", False))
        ctk.CTkSwitch(
            master_inner,
            text=t("Enable Aimbot"),
            variable=self.var_enableaim,
            command=self._on_enableaim_changed,
            font=("Segoe UI", 11, "bold"),
            progress_color="#10B981"
        ).pack(side="left", padx=(0, 20))
        self._checkbox_vars["enableaim"] = self.var_enableaim

        self.var_anti_smoke = tk.BooleanVar(value=getattr(config, "anti_smoke_enabled", False))
        ctk.CTkSwitch(
            master_inner,
            text=t("Enable Anti-Smoke"),
            variable=self.var_anti_smoke,
            command=self._on_anti_smoke_changed,
            font=("Segoe UI", 11),
            progress_color="#10B981"
        ).pack(side="left", padx=(0, 20))
        self._checkbox_vars["anti_smoke_enabled"] = self.var_anti_smoke

        self.var_enablercs = tk.BooleanVar(value=getattr(config, "enablercs", True))
        ctk.CTkSwitch(
            master_inner,
            text="Enable RCS (Burst & Spray)",
            variable=self.var_enablercs,
            command=self._on_enablercs_changed,
            font=("Segoe UI", 11),
            progress_color="#06B6D4"
        ).pack(side="left")
        self._checkbox_vars["enablercs"] = self.var_enablercs

        # 2-COLUMN GRID CONTAINER
        grid_container = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        grid_container.pack(fill="both", expand=True)
        grid_container.grid_columnconfigure(0, weight=1)
        grid_container.grid_columnconfigure(1, weight=1)

        # ── CARD 1: TARGETING & FOV (Col 0, Row 0) ──
        self.card_targeting = ModernCard(grid_container, "Targeting & FOV", icon="🎯", badge_text="Core", accent_color="#10B981")
        self.card_targeting.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 10))

        # Operation Mode
        self.mode_option = self._add_option_row_in_frame(self.card_targeting.content, "Mode", AIM_MODE_OPTIONS, self._on_mode_selected)
        self._option_widgets["mode"] = self.mode_option
        current_mode = self._aim_mode_display_to_value(getattr(config, "mode", "Normal"))
        config.mode = current_mode
        self.mode_option.set(self._aim_mode_value_to_display(current_mode))

        # Keybind & Activation Type
        current_btn = self._ads_binding_to_display(getattr(config, "selected_mouse_button", 3))
        self.aim_key_bind_button = self._add_bind_capture_row_in_frame(
            self.card_targeting.content,
            "Keybind",
            current_btn,
            lambda: self._start_aim_key_capture(is_sec=False),
        )

        activation_types = ["Hold to Enable", "Hold to Disable", "Toggle", "Press to Enable"]
        activation_type_map = {
            "Hold to Enable": "hold_enable",
            "Hold to Disable": "hold_disable",
            "Toggle": "toggle",
            "Press to Enable": "use_enable"
        }
        self.aimbot_activation_type_option = self._add_option_row_in_frame(
            self.card_targeting.content, "Type", activation_types, self._on_aimbot_activation_type_selected
        )
        self._option_widgets["aimbot_activation_type"] = self.aimbot_activation_type_option
        current_activation_type = getattr(config, "aimbot_activation_type", "hold_enable")
        for display_name, config_value in activation_type_map.items():
            if config_value == current_activation_type:
                self.aimbot_activation_type_option.set(display_name)
                break
        else:
            self.aimbot_activation_type_option.set("Hold to Enable")

        # FOV Slider
        self._add_slider_in_frame(self.card_targeting.content, "FOV Size", "fovsize", 1, 1000,
                                  float(getattr(config, "fovsize", 300)),
                                  self._on_fovsize_changed)

        # Aim Type / Bone Target
        self.aim_type_option = self._add_option_row_in_frame(self.card_targeting.content, "Target", ["head", "body", "nearest"], self._on_aim_type_selected)
        self._option_widgets["aim_type"] = self.aim_type_option
        self.aim_type_option.set(getattr(config, "aim_type", "head"))

        # Offsets
        self._add_slider_in_frame(self.card_targeting.content, "X-Offset", "aim_offsetX", -100, 100,
                                  float(getattr(config, "aim_offsetX", 0)),
                                  self._on_aim_offsetX_changed)
        self._add_slider_in_frame(self.card_targeting.content, "Y-Offset", "aim_offsetY", -100, 100,
                                  float(getattr(config, "aim_offsetY", 0)),
                                  self._on_aim_offsetY_changed)

        # ADS Controls in Card 1
        current_ads_key = self._ads_binding_to_display(getattr(config, "ads_key", "Right Mouse Button"))
        self.ads_key_bind_button = self._add_bind_capture_row_in_frame(
            self.card_targeting.content,
            "ADS Keybind",
            current_ads_key,
            lambda: self._start_ads_key_capture(is_sec=False),
        )
        self.ads_key_type_option = self._add_option_row_in_frame(
            self.card_targeting.content,
            "ADS Key Type",
            list(ADS_KEY_TYPE_DISPLAY_TO_VALUE.keys()),
            self._on_ads_key_type_selected,
        )
        self._option_widgets["ads_key_type"] = self.ads_key_type_option
        current_ads_key_type = str(getattr(config, "ads_key_type", "hold")).strip().lower()
        self.ads_key_type_option.set(ADS_KEY_TYPE_VALUE_TO_DISPLAY.get(current_ads_key_type, "Hold"))
        self._add_ads_fov_controls_in_frame(self.card_targeting.content, is_sec=False)

        # ── CARD 2: ALGORITHM TUNING (Col 1, Row 0) ──
        self.card_windmouse = ModernCard(grid_container, f"{current_mode} Tuning", icon="🌊", badge_text=get_engine_badge(), accent_color="#06B6D4")
        self.card_windmouse.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 10))

        if current_mode in ("Normal", "WindMouse"):
            self._add_subtitle_in_frame(self.card_windmouse.content, "WINDMOUSE BEZIER")
            self._add_slider_in_frame(self.card_windmouse.content, "Gravity", "wm_gravity", 0.1, 30.0,
                                      float(getattr(config, "wm_gravity", 4.5)),
                                      self._on_wm_gravity_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse.content, "Wind", "wm_wind", 0.1, 20.0,
                                      float(getattr(config, "wm_wind", 2.0)),
                                      self._on_wm_wind_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse.content, "Max Step", "wm_max_step", 1, 100,
                                      float(getattr(config, "wm_max_step", 8.0)),
                                      self._on_wm_max_step_changed)
            self._add_slider_in_frame(self.card_windmouse.content, "Min Step", "wm_min_step", 0.1, 20,
                                      float(getattr(config, "wm_min_step", 0.8)),
                                      self._on_wm_min_step_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse.content, "Min Delay (ms)", "wm_min_delay", 0.1, 50,
                                      float(getattr(config, "wm_min_delay", 0.0025)) * 1000,
                                      self._on_wm_min_delay_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse.content, "Max Delay (ms)", "wm_max_delay", 0.1, 50,
                                      float(getattr(config, "wm_max_delay", 0.0050)) * 1000,
                                      self._on_wm_max_delay_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse.content, "Distance Threshold", "wm_distance_threshold", 10, 200,
                                      float(getattr(config, "wm_distance_threshold", 30.0)),
                                      self._on_wm_distance_threshold_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse.content, "Smoothing", "normalsmooth", 1, 30,
                                      float(getattr(config, "normalsmooth", 10)),
                                      self._on_config_normal_smooth_changed)
            self._add_slider_in_frame(self.card_windmouse.content, "FOV Smooth", "normalsmoothfov", 1, 30,
                                      float(getattr(config, "normalsmoothfov", 10)),
                                      self._on_config_normal_smoothfov_changed)
        elif current_mode == "Flick":
            # Built from the shared spec so Main and Sec cannot drift apart.
            self._build_flick_panel_in(self.card_windmouse.content, is_sec=False)
        elif current_mode == "Silent":
            self._add_subtitle_in_frame(self.card_windmouse.content, "SILENT PARAMETERS")
            self._add_slider_in_frame(self.card_windmouse.content, "Distance (Multiplier)", "silent_distance", 0.1, 10.0,
                                      float(getattr(config, "silent_distance", 1.0)),
                                      self._on_silent_distance_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse.content, "Delay (ms)", "silent_delay", 0.001, 300.0,
                                      float(getattr(config, "silent_delay", 100.0)),
                                      self._on_silent_delay_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse.content, "Move Delay (ms)", "silent_move_delay", 0.001, 300.0,
                                      float(getattr(config, "silent_move_delay", 500.0)),
                                      self._on_silent_move_delay_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse.content, "Return Delay (ms)", "silent_return_delay", 0.001, 300.0,
                                      float(getattr(config, "silent_return_delay", 500.0)),
                                      self._on_silent_return_delay_changed, is_float=True)
        elif current_mode == "Bezier":
            self._add_subtitle_in_frame(self.card_windmouse.content, "BEZIER PARAMETERS")
            self._add_slider_in_frame(self.card_windmouse.content, "Segments", "bezier_segments", 1, 30,
                                      float(getattr(config, "bezier_segments", 8)),
                                      self._on_bezier_segments_changed)
            self._add_slider_in_frame(self.card_windmouse.content, "Ctrl X", "bezier_ctrl_x", 0.0, 100.0,
                                      float(getattr(config, "bezier_ctrl_x", 16.0)),
                                      self._on_bezier_ctrl_x_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse.content, "Ctrl Y", "bezier_ctrl_y", 0.0, 100.0,
                                      float(getattr(config, "bezier_ctrl_y", 16.0)),
                                      self._on_bezier_ctrl_y_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse.content, "Speed", "bezier_speed", 0.1, 20.0,
                                      float(getattr(config, "bezier_speed", 1.0)),
                                      self._on_bezier_speed_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse.content, "Delay (ms)", "bezier_delay", 0.1, 50.0,
                                      float(getattr(config, "bezier_delay", 0.002)) * 1000,
                                      self._on_bezier_delay_changed, is_float=True)
        elif current_mode == "PID":
            self._add_subtitle_in_frame(self.card_windmouse.content, "PID PARAMETERS")
            self._add_slider_in_frame(self.card_windmouse.content, "Kp Min", "pid_kp_min", 0.0, 20.0,
                                      float(getattr(config, "pid_kp_min", getattr(config, "pid_kp", 3.7))),
                                      self._on_pid_kp_min_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse.content, "Kp Max", "pid_kp_max", 0.0, 20.0,
                                      float(getattr(config, "pid_kp_max", getattr(config, "pid_kp", 3.7))),
                                      self._on_pid_kp_max_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse.content, "Ki", "pid_ki", 0.0, 100.0,
                                      float(getattr(config, "pid_ki", 24.0)),
                                      self._on_pid_ki_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse.content, "Kd", "pid_kd", 0.0, 10.0,
                                      float(getattr(config, "pid_kd", 0.11)),
                                      self._on_pid_kd_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse.content, "Max Output", "pid_max_output", 1.0, 200.0,
                                      float(getattr(config, "pid_max_output", 50.0)),
                                      self._on_pid_max_output_changed, is_float=True)
            self._add_pid_preview_section(is_sec=False)

        # ── CARD 3: SPEEDS & RECOIL (Col 0, Row 1) ──
        self.card_speeds = ModernCard(grid_container, "Speeds & Recoil", icon="⚡", badge_text="Axis Tuning", accent_color="#F59E0B")
        self.card_speeds.grid(row=1, column=0, sticky="nsew", padx=(0, 6), pady=(0, 10))

        self._add_slider_in_frame(self.card_speeds.content, "X-Speed", "normal_x_speed", 0.1, 2000,
                                  float(getattr(config, "normal_x_speed", 100)),
                                  self._on_normal_x_speed_changed)
        self._add_slider_in_frame(self.card_speeds.content, "Y-Speed", "normal_y_speed", 0.1, 2000,
                                  float(getattr(config, "normal_y_speed", 70)),
                                  self._on_normal_y_speed_changed)

        # Recoil Immunity Switch (Y-Decouple)
        ModernSwitch(
            self.card_speeds.content,
            "Recoil Immunity",
            "Chống giật bay đầu khi sấy (Y-Decouple)",
            init_val=bool(getattr(config, "recoil_immunity", True)),
            command=lambda v: setattr(config, "recoil_immunity", v),
            accent_color="#F59E0B"
        ).pack(fill="x", pady=(4, 6))

        # In-game Sens & DPI
        sens_row = ctk.CTkFrame(self.card_speeds.content, fg_color="transparent")
        sens_row.pack(fill="x", pady=(2, 0))
        ctk.CTkLabel(sens_row, text=t("In-game Sens:"), font=("Segoe UI", 10), text_color=COLOR_TEXT_DIM).pack(side="left")
        self.sens_entry = ctk.CTkEntry(sens_row, width=60, height=22, font=("Consolas", 10), justify="center")
        self.sens_entry.insert(0, str(getattr(config, "in_game_sens", 0.235)))
        self.sens_entry.pack(side="left", padx=(6, 12))
        def _commit_sens(e=None):
            try:
                setattr(config, "in_game_sens", float(self.sens_entry.get().strip()))
            except Exception:
                pass
        self.sens_entry.bind("<FocusOut>", _commit_sens)
        self.sens_entry.bind("<Return>", _commit_sens)

        ctk.CTkLabel(sens_row, text=t("DPI:"), font=("Segoe UI", 10), text_color=COLOR_TEXT_DIM).pack(side="left")
        self.dpi_entry = ctk.CTkEntry(sens_row, width=60, height=22, font=("Consolas", 10), justify="center")
        self.dpi_entry.insert(0, str(getattr(config, "mouse_dpi", 1100)))
        self.dpi_entry.pack(side="left", padx=(6, 0))
        def _commit_dpi(e=None):
            try:
                setattr(config, "mouse_dpi", float(self.dpi_entry.get().strip()))
            except Exception:
                pass
        self.dpi_entry.bind("<FocusOut>", _commit_dpi)
        self.dpi_entry.bind("<Return>", _commit_dpi)

        # ── CARD 4: ANTI-TREMOR & TIMING (Col 1, Row 1) ──
        self.card_humanization = ModernCard(grid_container, "Anti-Tremor & Timing", icon="🛡️", badge_text="Anti-Cheat Safe", accent_color="#BD93F9")
        self.card_humanization.grid(row=1, column=1, sticky="nsew", padx=(6, 0), pady=(0, 10))

        # Anti-Tremor Deadband
        self._add_slider_in_frame(self.card_humanization.content, "Anti-Tremor Deadband", "anti_tremor_deadband", 0.0, 5.0,
                                  float(getattr(config, "anti_tremor_deadband", 1.5)),
                                  lambda v: setattr(config, "anti_tremor_deadband", v), is_float=True)

        # Human Reaction Delay Range
        self._add_slider_in_frame(self.card_humanization.content, "Reaction Min (s)", "smooth_reaction_min", 0.01, 0.3,
                                  float(getattr(config, "smooth_reaction_min", 0.08)),
                                  lambda v: setattr(config, "smooth_reaction_min", v), is_float=True)
        self._add_slider_in_frame(self.card_humanization.content, "Reaction Max (s)", "smooth_reaction_max", 0.05, 0.5,
                                  float(getattr(config, "smooth_reaction_max", 0.15)),
                                  lambda v: setattr(config, "smooth_reaction_max", v), is_float=True)

        # Audio Toggle Beep (PC 1 OBS UDP 4455)
        ModernSwitch(
            self.card_humanization.content,
            "Audio Feedback",
            "Beep qua UDP 4455 tới PC1 (OBS plugin)",
            init_val=bool(getattr(config, "audio_feedback_enabled", True)),
            command=lambda v: setattr(config, "audio_feedback_enabled", v),
            accent_color="#BD93F9"
        ).pack(fill="x", pady=(4, 0))

        # ── CARD 5: CALIBRATION (Col 0+1, Row 2) ──
        # The single place a preset or a measurement is turned into counts/deg.
        from src.ui_tabs.calibration_tab import build_flick_calibration_card

        build_flick_calibration_card(self, grid_container, layout="grid")

    def _build_calibration_card(self, grid_container):
        """Shim: the Calibration card now lives in ``src.ui_tabs.calibration_tab``."""
        from src.ui_tabs.calibration_tab import build_flick_calibration_card

        return build_flick_calibration_card(self, grid_container, layout="grid")

    def _calibration_state_text(self):
        """One-line provenance summary (kept for external callers/tests)."""
        try:
            from src.aim_system.aim_math import resolve_calibration

            calib = resolve_calibration()
            label = str(calib.source).upper()
            warn = " (WARN)" if calib.needs_recalibration_warning() else ""
            return (
                f"source={label}{warn}  counts/deg=({calib.counts_per_deg_x:.4f}, "
                f"{calib.counts_per_deg_y:.4f})"
            )
        except Exception as e:
            return f"calibration unavailable: {e}"

    def _refresh_calibration_labels(self):
        from src.ui_tabs.calibration_tab import refresh_calibration_card

        refresh_calibration_card(self)

    def _on_hfov_changed(self, val):
        config.hfov_deg = float(val)
        from src.aim_system.aim_math import clear_caches

        clear_caches()
        self._refresh_calibration_labels()

    # -- Calibration actions (delegate to src.ui_tabs.calibration_tab) --------
    def on_calibration_source_changed(self, value):
        """Select the authoritative calibration source and apply it."""
        from src.aim_system.aim_math import clear_caches
        from src.ui_tabs.calibration_tab import (
            apply_valorant_scale,
            refresh_calibration_card,
        )

        value = str(value or "").strip().lower()
        if value not in ("valorant", "measured", "analytic"):
            value = "valorant"
        if value == "measured" and not (
            float(getattr(config, "counts_per_deg_x", 0.0) or 0.0) > 0.0
            and float(getattr(config, "counts_per_deg_y", 0.0) or 0.0) > 0.0
            and int(getattr(config, "calibration_samples", 0) or 0) >= 5
        ):
            log_print(
                "[Calibration] Measured needs >=5 samples per axis and R2 >= 0.99; "
                "record the samples first (keeping the Valorant preset meanwhile)."
            )
            self.calibration_source_var.set(str(getattr(config, "calibration_source", "valorant")))
            return
        config.calibration_source = value
        if value == "valorant":
            apply_valorant_scale(self)
        else:
            self.on_calibration_persisted()
        clear_caches()
        refresh_calibration_card(self)

    def commit_calibration_inputs(self):
        """Read the in-game sens / DPI / yaw entries into config."""
        from src.aim_system.aim_math import clear_caches

        for attr, key, default, low, high in (
            ("calibration_sens_entry", "in_game_sens", 0.23, 0.05, 5.0),
            ("calibration_dpi_entry", "mouse_dpi", 1100.0, 1.0, 32000.0),
            ("calibration_yaw_entry", "valorant_deg_per_count", 0.07, 0.01, 0.2),
        ):
            entry = getattr(self, attr, None)
            if entry is None:
                continue
            try:
                value = float(entry.get().strip())
            except Exception:
                continue
            setattr(config, key, max(low, min(high, value)))
        if hasattr(self, "tracker"):
            try:
                self.tracker.in_game_sens = float(getattr(config, "in_game_sens", 0.23))
                self.tracker.mouse_dpi = float(getattr(config, "mouse_dpi", 1100.0))
            except Exception:
                pass
        clear_caches()
        # A sens change under the Valorant source must update the scale live.
        if str(getattr(config, "calibration_source", "")) == "valorant":
            from src.ui_tabs.calibration_tab import apply_valorant_scale

            apply_valorant_scale(self)
        from src.ui_tabs.calibration_tab import refresh_calibration_card
        from src.ui_tabs.flick_tab import refresh_flick_summary

        refresh_calibration_card(self)
        refresh_flick_summary(self)

    def on_apply_valorant_scale(self):
        from src.ui_tabs.calibration_tab import apply_valorant_scale

        if apply_valorant_scale(self):
            self._set_status_indicator("Status: Valorant calibration applied", COLOR_SUCCESS)

    def on_calibration_send_impulse(self):
        """Send ONE known impulse (exclusive ``calib`` tag) for measurement."""
        try:
            counts = float(self.calibration_counts_entry.get().strip())
        except Exception:
            log_print("[Calibration] invalid counts value")
            return
        if counts <= 0.0:
            log_print("[Calibration] impulse counts must be > 0")
            return
        axis = str(self.calibration_axis_var.get()).strip().lower()
        dx = counts if axis == "x" else 0.0
        dy = counts if axis == "y" else 0.0
        # Open the session BEFORE the impulse so the aim pipeline stops competing.
        try:
            self.tracker.calibration_session = True
        except Exception:
            pass
        try:
            self.tracker.move_queue.put_nowait((dx, dy, 0.0, "calib"))
            log_print(f"[Calibration] impulse sent: dx={dx:.1f} dy={dy:.1f}")
        except Exception as e:
            log_print(f"[Calibration] failed to queue impulse: {e}")

    def on_calibration_record_sample(self):
        from src.ui_tabs.calibration_tab import record_sample

        record_sample(self)

    def on_calibration_fit(self):
        from src.ui_tabs.calibration_tab import fit_and_save

        if fit_and_save(self):
            self._set_status_indicator("Status: Measured calibration saved", COLOR_SUCCESS)

    def on_calibration_clear(self):
        from src.ui_tabs.calibration_tab import clear_measurement

        clear_measurement(self)

    def on_calibration_persisted(self):
        """Apply a calibration change to both channels and refresh the readouts."""
        from src.aim_system.aim_math import clear_caches
        from src.aim_system import mode_flick
        from src.ui_tabs.calibration_tab import refresh_calibration_card
        from src.ui_tabs.flick_tab import refresh_flick_readouts, refresh_flick_summary

        clear_caches()
        for channel in (False, True):
            try:
                mode_flick.reset(self.tracker, is_sec=channel)
                mode_flick.configure_from_config(self.tracker, is_sec=channel)
            except Exception as e:
                log_print(f"[Calibration] controller reset failed: {e}")
        # The config is persisted by the normal save path (and on window close);
        # writing the file from a slider callback would hit the disk on every tick.
        refresh_calibration_card(self)
        refresh_flick_readouts(self, None)
        refresh_flick_summary(self)

    # Legacy aliases kept for saved layouts / external scripts.
    def _on_calibration_send_impulse(self):
        self.on_calibration_send_impulse()

    def _on_calibration_record_sample(self):
        self.on_calibration_record_sample()

    def _on_calibration_fit(self):
        self.on_calibration_fit()

    def _on_calibration_clear(self):
        self.on_calibration_clear()

    # ------------------------------------------------------------------
    # Flick V2 tab + panel wiring (plan section 4)
    # ------------------------------------------------------------------
    def _build_flick_panel_in(self, parent, is_sec=False):
        """Compact Flick card shared by Main and Sec (one builder, no copies)."""
        from src.ui_tabs.flick_tab import build_flick_panel

        return build_flick_panel(self, parent, is_sec=is_sec)

    def _show_flick_v2_tab(self):
        """Dedicated Flick V2 tab: two channels + Calibration + Diagnostics."""
        from src.ui_tabs.flick_tab import build_flick_v2_tab

        if self._ensure_pro_mode("Flick V2"):
            return
        self._active_tab_name = "Flick V2"
        self._clear_content()
        self._set_nav_active("Combat")
        build_flick_v2_tab(self)

    def show_flick_v2_tab(self):
        """Public entry used by the compact card's ``Open Flick V2`` button."""
        self._show_flick_v2_tab()

    def show_flick_v2_calibration(self):
        """Open Flick V2 and apply the Valorant preset (Calibrate button)."""
        from src.ui_tabs.calibration_tab import apply_valorant_scale

        if str(getattr(self, "_active_tab_name", "")) != "Flick V2":
            self._show_flick_v2_tab()
        try:
            self.calibration_source_var.set("valorant")
        except Exception:
            pass
        apply_valorant_scale(self)
        self._set_status_indicator("Status: Valorant calibration applied", COLOR_SUCCESS)

    # -- per-channel Flick slider handler factory -------------------------
    def flick_handler_for(self, fused_key):
        """Return the callback that writes ``fused_key`` for the shared spec.

        One generic handler replaces the ten hand-written `_on_flick_*` methods
        (5 parameters x 2 channels) that used to exist in this file.
        """
        return lambda value: self._on_flick_param_changed(fused_key, value)

    def _on_flick_param_changed(self, fused_key, value):
        from src.aim_system import mode_flick
        from src.ui_tabs.common import clamp_to_spec, spec_for
        from src.ui_tabs.flick_tab import refresh_flick_readouts

        base = fused_key[:-4] if fused_key.endswith("_sec") else fused_key
        is_sec = fused_key.endswith("_sec")
        spec = spec_for(base)
        if spec is None:
            return
        clamped = clamp_to_spec(base, value)
        stored = float(int(round(clamped))) if not spec[7] else float(clamped)
        setattr(config, fused_key, stored)
        if base == "flick_gain":
            # Legacy alias stays coherent so the legacy A/B path sees the gain.
            setattr(config, "flick_strength_x_sec" if is_sec else "flick_strength_x", stored)
        if base == "flick_budget_ms":
            # Legacy alias for the sec channel only.
            if is_sec:
                config.sec_flick_cooldown_ms = float(stored)
        # Propagate immediately: the controller must never keep an old Settle or
        # Switch Radius until the next restart (plan C14).
        try:
            mode_flick.configure_from_config(self.tracker, is_sec=is_sec)
        except Exception as e:
            log_print(f"[Flick] configure failed: {e}")
        refresh_flick_readouts(self, is_sec)

    # Legacy per-parameter callbacks (kept as public shims).
    def _on_flick_gain_changed(self, val):
        self._on_flick_param_changed("flick_gain", val)

    def _on_flick_gain_sec_changed(self, val):
        self._on_flick_param_changed("flick_gain_sec", val)

    def _on_flick_max_counts_changed(self, val):
        self._on_flick_param_changed("flick_max_counts", val)

    def _on_flick_max_counts_sec_changed(self, val):
        self._on_flick_param_changed("flick_max_counts_sec", val)

    def _on_flick_max_iterations_changed(self, val):
        self._on_flick_param_changed("flick_max_iterations", val)

    def _on_flick_max_iterations_sec_changed(self, val):
        self._on_flick_param_changed("flick_max_iterations_sec", val)

    def _on_flick_budget_ms_changed(self, val):
        self._on_flick_param_changed("flick_budget_ms", val)

    def _on_flick_budget_ms_sec_changed(self, val):
        self._on_flick_param_changed("flick_budget_ms_sec", val)

    def _on_flick_deadzone_px_changed(self, val):
        self._on_flick_param_changed("flick_deadzone_px", val)

    def _on_flick_deadzone_px_sec_changed(self, val):
        self._on_flick_param_changed("flick_deadzone_px_sec", val)

    def _on_flick_settle_ms_changed(self, val):
        self._on_flick_param_changed("flick_settle_ms", val)

    def _on_flick_settle_ms_sec_changed(self, val):
        self._on_flick_param_changed("flick_settle_ms_sec", val)

    def _on_flick_switch_radius_px_changed(self, val):
        self._on_flick_param_changed("flick_switch_radius_px", val)

    def _on_flick_switch_radius_px_sec_changed(self, val):
        self._on_flick_param_changed("flick_switch_radius_px_sec", val)

    # -- Flick V2 actions -------------------------------------------------
    def auto_fix_flick_timing(self, is_sec=False):
        """Set the budget so every iteration fits at the current settle."""
        from src.ui_tabs.common import suggested_budget
        from src.ui_tabs.flick_tab import refresh_flick_readouts

        suffix = "_sec" if is_sec else ""
        settle = float(getattr(config, f"flick_settle_ms{suffix}", 70.0) or 0.0)
        iterations = int(getattr(config, f"flick_max_iterations{suffix}", 4) or 4)
        budget = min(1000.0, suggested_budget(settle, iterations))
        setattr(config, f"flick_budget_ms{suffix}", budget)
        if is_sec:
            config.sec_flick_cooldown_ms = budget
        self._set_slider_value(f"flick_budget_ms{suffix}", budget)
        self._on_flick_param_changed(f"flick_budget_ms{suffix}", budget)
        refresh_flick_readouts(self, is_sec)
        log_print(
            f"[Flick] auto-fix budget{suffix} -> {budget:.0f} ms "
            f"(settle={settle:.0f} ms, iterations={iterations})"
        )

    def reset_flick_state(self, channel=None):
        """Drop flick state for one channel (``"main"``/``"sec"``) or both."""
        from src.aim_system.normal import reset_aim_state
        from src.ui_tabs.flick_tab import refresh_diagnostics

        if channel is None:
            for is_sec in (False, True):
                reset_aim_state(self.tracker, is_sec=is_sec)
        else:
            reset_aim_state(self.tracker, is_sec=(str(channel) == "sec"))
        try:
            self.tracker.flick_status = {}
        except Exception:
            pass
        refresh_diagnostics(self)
        self._set_status_indicator("Status: Flick state reset", COLOR_TEXT)

    def copy_flick_diagnostics(self):
        """Copy the diagnostics JSON to the clipboard."""
        from src.ui_tabs.flick_tab import copy_diagnostics_payload

        payload = copy_diagnostics_payload(self)
        copied = False
        try:
            self.clipboard_clear()
            self.clipboard_append(payload)
            copied = True
        except Exception as e:
            log_print(f"[Flick] clipboard error: {e}")
        log_print(
            "[Flick] diagnostics " + ("copied to clipboard" if copied else "dump") + f":\n{payload}"
        )
        self._set_status_indicator(
            "Status: Diagnostics copied" if copied else "Status: Diagnostics logged",
            COLOR_SUCCESS if copied else COLOR_TEXT_DIM,
        )

    def flick_status_for(self, channel):
        """Latest published Flick status dict for ``"main"``/``"sec"``."""
        status = getattr(self.tracker, "flick_status", None)
        if not isinstance(status, dict):
            return {}
        payload = status.get(str(channel))
        return dict(payload) if isinstance(payload, dict) else {}

    def on_flick_engine_selected(self, value):
        """Switch the Flick engine (v2 closed loop vs legacy A/B)."""
        from src.aim_system import mode_flick
        from src.ui_tabs.flick_tab import refresh_flick_summary

        engine = "legacy" if str(value).strip().lower() == "legacy" else "v2"
        config.flick_engine = engine
        for is_sec in (False, True):
            try:
                mode_flick.reset(self.tracker, is_sec=is_sec)
            except Exception:
                pass
        refresh_flick_summary(self)
        log_print(f"[Flick] engine -> {engine}")

    def on_flick_telemetry_changed(self):
        config.flick_telemetry_enabled = bool(self.var_flick_telemetry.get())
        log_print(f"[Flick] telemetry enabled={config.flick_telemetry_enabled}")

    def _refresh_flick_readouts(self):
        """Scheduler entry: refresh the derived rows of the visible Flick panel."""
        from src.ui_tabs.flick_tab import (
            refresh_diagnostics,
            refresh_flick_readouts,
            refresh_flick_summary,
        )

        refresh_flick_readouts(self, None)
        if str(getattr(self, "_active_tab_name", "")) == "Flick V2":
            refresh_flick_summary(self)
            refresh_diagnostics(self)

    def _legacy_calibration_block_removed(self):
        """Placeholder: the old Calibration card body lived here.

        It was replaced by ``src/ui_tabs/calibration_tab.py`` (three explicit
        sources, signed samples, no axis extrapolation). The body is kept out of
        the build entirely — see the deletion in the v2.1.0 cleanup.
        """
        return None

        # One-shot pulse controls: send a known count, then type what you saw.
        row = ctk.CTkFrame(content, fg_color="transparent")
        row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(row, text="Test impulse (counts):", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
        self.calibration_counts_entry = ctk.CTkEntry(row, width=80, height=25, justify="center")
        self.calibration_counts_entry.insert(0, "100")
        self.calibration_counts_entry.pack(side="left", padx=(8, 8))

        self.calibration_axis_var = tk.StringVar(value="x")
        ctk.CTkOptionMenu(
            row,
            values=["x", "y"],
            variable=self.calibration_axis_var,
            width=70,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            row,
            text="Send impulse",
            width=110,
            command=self._on_calibration_send_impulse,
            fg_color=COLOR_SURFACE,
            hover_color=COLOR_NAV_HOVER_BG,
            border_width=1,
            border_color=COLOR_BORDER,
            text_color=COLOR_TEXT,
        ).pack(side="left")

        row2 = ctk.CTkFrame(content, fg_color="transparent")
        row2.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(row2, text="Measured shift (px):", font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
        self.calibration_px_entry = ctk.CTkEntry(row2, width=80, height=25, justify="center")
        self.calibration_px_entry.insert(0, "0")
        self.calibration_px_entry.pack(side="left", padx=(8, 8))
        ctk.CTkButton(
            row2,
            text="Record sample",
            width=110,
            command=self._on_calibration_record_sample,
            fg_color=COLOR_SURFACE,
            hover_color=COLOR_NAV_HOVER_BG,
            border_width=1,
            border_color=COLOR_BORDER,
            text_color=COLOR_TEXT,
        ).pack(side="left")

        row3 = ctk.CTkFrame(content, fg_color="transparent")
        row3.pack(fill="x", pady=(4, 0))
        self.calibration_samples_label = ctk.CTkLabel(
            row3, text="Samples: 0", font=("Consolas", 10), text_color=COLOR_TEXT_DIM
        )
        self.calibration_samples_label.pack(side="left")

        ctk.CTkButton(
            row3,
            text="Fit & save",
            width=110,
            command=self._on_calibration_fit,
            fg_color="#10B981",
            hover_color="#059669",
            text_color="#04120C",
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            row3,
            text="Clear",
            width=80,
            command=self._on_calibration_clear,
            fg_color=COLOR_SURFACE,
            hover_color=COLOR_NAV_HOVER_BG,
            border_width=1,
            border_color=COLOR_BORDER,
            text_color=COLOR_TEXT,
        ).pack(side="right")

        self._calibration_samples = {"x": [], "y": []}

    def _legacy_calibration_state_text_removed(self):
        """Removed: superseded by ``_calibration_state_text`` above."""
        return ""
        try:
            from src.aim_system.aim_math import resolve_calibration

            calib = resolve_calibration()
            if calib.is_measured:
                warn = ""
                if calib.needs_recalibration_warning():
                    warn = (
                        f"\nWARN measured scale differs from analytic by "
                        f"{calib.divergence_from_analytic * 100:+.1f}%"
                    )
                return (
                    f"source=MEASURED  counts/deg=({calib.counts_per_deg_x:.4f}, "
                    f"{calib.counts_per_deg_y:.4f}){warn}"
                )
            return (
                f"source=ANALYTIC  counts/deg=({calib.counts_per_deg_x:.4f}, "
                f"{calib.counts_per_deg_y:.4f})  "
                f"— calibrate to remove 54.54 / {float(getattr(config, 'hfov_deg', 103.0)):.1f}"
            )
        except Exception as e:
            return f"calibration unavailable: {e}"

    def _legacy_refresh_calibration_labels_removed(self):
        """Removed: superseded by the one in ``src/ui_tabs/calibration_tab``."""
        return None
        for attr, text in (
            ("calibration_state_label", self._calibration_state_text()),
            (
                "calibration_samples_label",
                "Samples: x={0}, y={1}".format(
                    len(self._calibration_samples.get("x", [])),
                    len(self._calibration_samples.get("y", [])),
                ),
            ),
        ):
            widget = getattr(self, attr, None)
            if widget is not None:
                try:
                    widget.configure(text=text)
                except Exception:
                    pass

    def _legacy_on_hfov_changed_removed(self):
        """Removed: ``_on_hfov_changed`` above clears the geometry cache."""
        return None
        config.hfov_deg = float(val)
        self._refresh_calibration_labels()

    def _legacy_on_calibration_send_impulse_removed(self):
        """Removed: ``on_calibration_send_impulse`` above owns the session flag."""
        return None
        """Send ONE known impulse so the user can measure the real pixel shift."""
        try:
            counts = float(self.calibration_counts_entry.get().strip())
        except Exception:
            log_print("[Calibration] invalid counts value")
            return
        axis = str(self.calibration_axis_var.get()).strip().lower()
        dx = counts if axis == "x" else 0.0
        dy = counts if axis == "y" else 0.0
        try:
            # A dedicated tag: the queue merges per tag, so a calibration pulse
            # must never be folded into a live flick/track command (that would
            # invalidate the measurement).
            self.tracker.move_queue.put_nowait((dx, dy, 0.0, "calib"))
            log_print(f"[Calibration] impulse sent: dx={dx:.1f} dy={dy:.1f}")
        except Exception as e:
            log_print(f"[Calibration] failed to queue impulse: {e}")

    def _legacy_on_calibration_record_sample_removed(self):
        """Removed: ``on_calibration_record_sample`` keeps the SIGNED shift."""
        return None
        """Record (commanded counts, observed pixel shift) for the active axis."""
        try:
            counts = float(self.calibration_counts_entry.get().strip())
            observed_px = abs(float(self.calibration_px_entry.get().strip()))
        except Exception:
            log_print("[Calibration] invalid sample values")
            return
        if counts <= 0 or observed_px <= 0:
            log_print("[Calibration] counts and measured shift must be > 0")
            return
        axis = str(self.calibration_axis_var.get()).strip().lower()
        axis = "y" if axis == "y" else "x"
        self._calibration_samples.setdefault(axis, []).append((observed_px, counts))
        log_print(
            f"[Calibration] sample {axis}: {counts:.1f} counts -> {observed_px:.2f} px "
            f"({len(self._calibration_samples[axis])} total)"
        )
        self._refresh_calibration_labels()

    def _legacy_on_calibration_fit_removed(self):
        """Removed: ``on_calibration_fit`` requires BOTH axes and 5 samples each."""
        return None
        """Fit both axes and store measured counts_per_deg (or refuse the data)."""
        from src.aim_system.aim_math import (
            counts_per_deg_from_slope,
            fit_calibration,
            resolve_geometry,
        )

        results = {}
        for axis in ("x", "y"):
            samples = self._calibration_samples.get(axis, [])
            fit = fit_calibration(samples, min_r2=0.99)
            if fit is None:
                continue
            results[axis] = fit

        if not results:
            log_print(
                "[Calibration] fit rejected: need >=2 points per axis with R^2 >= 0.99 "
                "(measure at least 5 points x 4 directions)"
            )
            return

        geometry = resolve_geometry(frame=getattr(self.tracker, "_aim_frame", None))
        xy = (
            results["x"][0] if "x" in results else (
                results["y"][0] * geometry.focal_x / max(geometry.focal_y, 1e-9)
            )
        )
        yy = (
            results["y"][0] if "y" in results else (
                results["x"][0] * geometry.focal_y / max(geometry.focal_x, 1e-9)
            )
        )
        cpd_x, cpd_y = counts_per_deg_from_slope(geometry, xy, yy)
        if cpd_x <= 0 or cpd_y <= 0:
            log_print("[Calibration] fit produced a non-positive scale; keeping analytic model")
            return

        config.counts_per_deg_x = float(cpd_x)
        config.counts_per_deg_y = float(cpd_y)
        config.calibration_r2 = float(
            min((fit[2] for fit in results.values()), default=0.0)
        )
        config.calibration_samples = int(
            sum(len(self._calibration_samples.get(a, [])) for a in ("x", "y"))
        )
        log_print(
            f"[Calibration] saved counts_per_deg=({cpd_x:.4f}, {cpd_y:.4f}) "
            f"R2={config.calibration_r2:.4f}"
        )
        self._refresh_calibration_labels()

    def _legacy_on_calibration_clear_removed(self):
        """Removed: ``on_calibration_clear`` also clears the sens-at-measurement."""
        return None
        """Drop the measurement and fall back to the analytic model."""
        config.counts_per_deg_x = 0.0
        config.counts_per_deg_y = 0.0
        config.calibration_r2 = 0.0
        config.calibration_samples = 0
        self._calibration_samples = {"x": [], "y": []}
        log_print("[Calibration] measurement cleared; using analytic model")
        self._refresh_calibration_labels()

    def _show_sec_aimbot_tab(self):
        if self._ensure_pro_mode("Sec Aimbot"):
            return
        self._active_tab_name = "Sec Aimbot"
        self._clear_content()
        self._add_sub_nav_bar(
            ["Main Aimbot", "Sec Aimbot", "Flick V2", "Recoil & RCS"],
            "Sec Aimbot",
            {
                "Main Aimbot": self._show_aimbot_tab,
                "Sec Aimbot": self._show_sec_aimbot_tab,
                "Flick V2": self._show_flick_v2_tab,
                "Recoil & RCS": self._show_rcs_tab,
            }
        )
        self._add_title("Secondary Aimbot")

        # Master Control Switches Row
        master_row = ctk.CTkFrame(self.content_frame, fg_color="#141822", corner_radius=8, border_width=1, border_color="#232B3B")
        master_row.pack(fill="x", pady=(0, 10))
        master_inner = ctk.CTkFrame(master_row, fg_color="transparent")
        master_inner.pack(fill="x", padx=12, pady=6)

        self.var_enableaim_sec = tk.BooleanVar(value=getattr(config, "enableaim_sec", False))
        ctk.CTkSwitch(
            master_inner,
            text=t("Enable Sec Aimbot"),
            variable=self.var_enableaim_sec,
            command=self._on_enableaim_sec_changed,
            font=("Segoe UI", 11, "bold"),
            progress_color="#10B981"
        ).pack(side="left", padx=(0, 20))
        self._checkbox_vars["enableaim_sec"] = self.var_enableaim_sec

        self.var_anti_smoke_sec = tk.BooleanVar(value=getattr(config, "anti_smoke_enabled_sec", False))
        ctk.CTkSwitch(
            master_inner,
            text=t("Enable Anti-Smoke"),
            variable=self.var_anti_smoke_sec,
            command=self._on_anti_smoke_sec_changed,
            font=("Segoe UI", 11),
            progress_color="#10B981"
        ).pack(side="left")
        self._checkbox_vars["anti_smoke_enabled_sec"] = self.var_anti_smoke_sec

        # 2-COLUMN GRID CONTAINER
        grid_container = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        grid_container.pack(fill="both", expand=True)
        grid_container.grid_columnconfigure(0, weight=1)
        grid_container.grid_columnconfigure(1, weight=1)

        # ── CARD 1: TARGETING & FOV (Col 0, Row 0) ──
        self.card_targeting_sec = ModernCard(grid_container, "Targeting & FOV", icon="🎯", badge_text="Secondary", accent_color="#10B981")
        self.card_targeting_sec.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 10))

        # Operation Mode
        self.mode_option_sec = self._add_option_row_in_frame(self.card_targeting_sec.content, "Mode", AIM_MODE_OPTIONS, self._on_mode_sec_selected)
        self._option_widgets["mode_sec"] = self.mode_option_sec
        current_mode_sec = self._aim_mode_display_to_value(getattr(config, "mode_sec", "Normal"))
        config.mode_sec = current_mode_sec
        self.mode_option_sec.set(self._aim_mode_value_to_display(current_mode_sec))

        # Keybind & Activation Type
        current_btn_sec = self._ads_binding_to_display(getattr(config, "selected_mouse_button_sec", 2))
        self.aim_key_bind_button_sec = self._add_bind_capture_row_in_frame(
            self.card_targeting_sec.content,
            "Keybind",
            current_btn_sec,
            lambda: self._start_aim_key_capture(is_sec=True),
        )

        activation_types = ["Hold to Enable", "Hold to Disable", "Toggle", "Press to Enable"]
        activation_type_map = {
            "Hold to Enable": "hold_enable",
            "Hold to Disable": "hold_disable",
            "Toggle": "toggle",
            "Press to Enable": "use_enable"
        }
        self.aimbot_activation_type_option_sec = self._add_option_row_in_frame(
            self.card_targeting_sec.content, "Type", activation_types, self._on_aimbot_activation_type_sec_selected
        )
        self._option_widgets["aimbot_activation_type_sec"] = self.aimbot_activation_type_option_sec
        current_activation_type_sec = getattr(config, "aimbot_activation_type_sec", "hold_enable")
        for display_name, config_value in activation_type_map.items():
            if config_value == current_activation_type_sec:
                self.aimbot_activation_type_option_sec.set(display_name)
                break
        else:
            self.aimbot_activation_type_option_sec.set("Hold to Enable")

        # FOV Slider
        self._add_slider_in_frame(self.card_targeting_sec.content, "FOV Size", "fovsize_sec", 1, 1000,
                                  float(getattr(config, "fovsize_sec", 150)),
                                  self._on_fovsize_sec_changed)

        # Aim Type / Bone Target
        self.aim_type_option_sec = self._add_option_row_in_frame(self.card_targeting_sec.content, "Target", ["head", "body", "nearest"], self._on_aim_type_sec_selected)
        self._option_widgets["aim_type_sec"] = self.aim_type_option_sec
        self.aim_type_option_sec.set(getattr(config, "aim_type_sec", "head"))

        # Offsets
        self._add_slider_in_frame(self.card_targeting_sec.content, "X-Offset", "aim_offsetX_sec", -100, 100,
                                  float(getattr(config, "aim_offsetX_sec", 0)),
                                  self._on_aim_offsetX_sec_changed)
        self._add_slider_in_frame(self.card_targeting_sec.content, "Y-Offset", "aim_offsetY_sec", -100, 100,
                                  float(getattr(config, "aim_offsetY_sec", 0)),
                                  self._on_aim_offsetY_sec_changed)

        # ADS Controls
        current_ads_key_sec = self._ads_binding_to_display(getattr(config, "ads_key_sec", "Right Mouse Button"))
        self.ads_key_bind_button_sec = self._add_bind_capture_row_in_frame(
            self.card_targeting_sec.content,
            "ADS Keybind",
            current_ads_key_sec,
            lambda: self._start_ads_key_capture(is_sec=True),
        )
        self.ads_key_type_option_sec = self._add_option_row_in_frame(
            self.card_targeting_sec.content,
            "ADS Key Type",
            list(ADS_KEY_TYPE_DISPLAY_TO_VALUE.keys()),
            self._on_ads_key_type_sec_selected,
        )
        self._option_widgets["ads_key_type_sec"] = self.ads_key_type_option_sec
        current_ads_key_type_sec = str(getattr(config, "ads_key_type_sec", "hold")).strip().lower()
        self.ads_key_type_option_sec.set(ADS_KEY_TYPE_VALUE_TO_DISPLAY.get(current_ads_key_type_sec, "Hold"))
        self._add_ads_fov_controls_in_frame(self.card_targeting_sec.content, is_sec=True)

        # ── CARD 2: ALGORITHM TUNING (Col 1, Row 0) ──
        self.card_windmouse_sec = ModernCard(grid_container, f"{current_mode_sec} Tuning", icon="🌊", badge_text="Secondary", accent_color="#06B6D4")
        self.card_windmouse_sec.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 10))

        if current_mode_sec in ("Normal", "WindMouse"):
            self._add_subtitle_in_frame(self.card_windmouse_sec.content, "WINDMOUSE BEZIER")
            self._add_slider_in_frame(self.card_windmouse_sec.content, "Gravity", "wm_gravity_sec", 0.1, 30.0,
                                      float(getattr(config, "wm_gravity_sec", 4.5)),
                                      self._on_wm_gravity_sec_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse_sec.content, "Wind", "wm_wind_sec", 0.1, 20.0,
                                      float(getattr(config, "wm_wind_sec", 2.0)),
                                      self._on_wm_wind_sec_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse_sec.content, "Max Step", "wm_max_step_sec", 1, 100,
                                      float(getattr(config, "wm_max_step_sec", 8.0)),
                                      self._on_wm_max_step_sec_changed)
            self._add_slider_in_frame(self.card_windmouse_sec.content, "Min Step", "wm_min_step_sec", 0.1, 20,
                                      float(getattr(config, "wm_min_step_sec", 0.8)),
                                      self._on_wm_min_step_sec_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse_sec.content, "Min Delay (ms)", "wm_min_delay_sec", 0.1, 50,
                                      float(getattr(config, "wm_min_delay_sec", 0.0025)) * 1000,
                                      self._on_wm_min_delay_sec_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse_sec.content, "Max Delay (ms)", "wm_max_delay_sec", 0.1, 50,
                                      float(getattr(config, "wm_max_delay_sec", 0.0050)) * 1000,
                                      self._on_wm_max_delay_sec_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse_sec.content, "Distance Threshold", "wm_distance_threshold_sec", 10, 200,
                                      float(getattr(config, "wm_distance_threshold_sec", 30.0)),
                                      self._on_wm_distance_threshold_sec_changed, is_float=True)
            self._add_slider_in_frame(self.card_windmouse_sec.content, "Smoothing", "normalsmooth_sec", 1, 30,
                                      float(getattr(config, "normalsmooth_sec", 20)),
                                      self._on_config_normal_smooth_sec_changed)
            self._add_slider_in_frame(self.card_windmouse_sec.content, "FOV Smooth", "normalsmoothfov_sec", 1, 30,
                                      float(getattr(config, "normalsmoothfov_sec", 20)),
                                      self._on_config_normal_smoothfov_sec_changed)
        elif current_mode_sec == "Flick":
            self._build_flick_panel_in(self.card_windmouse_sec.content, is_sec=True)
        elif current_mode_sec == "Silent":
            self._add_subtitle_in_frame(self.card_windmouse_sec.content, "SILENT PARAMETERS")
            self._add_slider_in_frame(self.card_windmouse_sec.content, "Distance (Multiplier)", "silent_distance_sec", 0.1, 10.0,
                                      float(getattr(config, "silent_distance_sec", 1.0)),
                                      self._on_silent_distance_changed, is_float=True)
        elif current_mode_sec == "PID":
            self._add_subtitle_in_frame(self.card_windmouse_sec.content, "PID PARAMETERS")
            self._add_slider_in_frame(self.card_windmouse_sec.content, "Kp Min", "pid_kp_min_sec", 0.0, 20.0,
                                      float(getattr(config, "pid_kp_min_sec", 3.7)),
                                      self._on_pid_kp_min_sec_changed, is_float=True)
            self._add_pid_preview_section(is_sec=True)

        # ── CARD 3: SPEEDS & RECOIL (Col 0, Row 1) ──
        self.card_speeds_sec = ModernCard(grid_container, "Speeds & Recoil", icon="⚡", badge_text="Secondary", accent_color="#F59E0B")
        self.card_speeds_sec.grid(row=1, column=0, sticky="nsew", padx=(0, 6), pady=(0, 10))

        self._add_slider_in_frame(self.card_speeds_sec.content, "X-Speed", "normal_x_speed_sec", 0.1, 2000,
                                  float(getattr(config, "normal_x_speed_sec", 2)),
                                  self._on_normal_x_speed_sec_changed)
        self._add_slider_in_frame(self.card_speeds_sec.content, "Y-Speed", "normal_y_speed_sec", 0.1, 2000,
                                  float(getattr(config, "normal_y_speed_sec", 2)),
                                  self._on_normal_y_speed_sec_changed)

        # ── CARD 4: ANTI-TREMOR & TIMING (Col 1, Row 1) ──
        self.card_humanization_sec = ModernCard(grid_container, "Anti-Tremor & Timing", icon="🛡️", badge_text="Secondary", accent_color="#BD93F9")
        self.card_humanization_sec.grid(row=1, column=1, sticky="nsew", padx=(6, 0), pady=(0, 10))

        self._add_slider_in_frame(self.card_humanization_sec.content, "Reaction Min (s)", "smooth_reaction_min_sec", 0.01, 0.3,
                                  float(getattr(config, "smooth_reaction_min_sec", 0.08)),
                                  lambda v: setattr(config, "smooth_reaction_min_sec", v), is_float=True)
        self._add_slider_in_frame(self.card_humanization_sec.content, "Reaction Max (s)", "smooth_reaction_max_sec", 0.05, 0.5,
                                  float(getattr(config, "smooth_reaction_max_sec", 0.15)),
                                  lambda v: setattr(config, "smooth_reaction_max_sec", v), is_float=True)

    def _show_tb_tab(self):
        if self._ensure_pro_mode("Trigger"):
            return
        """Triggerbot has no dedicated tab. Redirects to Combat.

        Everything after the ``return`` is the retired Triggerbot page: it was
        unreachable before this change as well (the redirect was already the
        first statement), so no behaviour is lost. It is kept only because
        deleting ~350 lines of mojibake-bearing text by literal match is riskier
        than leaving unreachable code behind; the live code path ends here.
        """
        self._show_aimbot_tab()
        return

        current_trigger_type = str(getattr(config, "trigger_type", "current")).strip().lower()
        if current_trigger_type not in TRIGGER_TYPE_DISPLAY:
            current_trigger_type = "current"
            config.trigger_type = current_trigger_type

        sec_core = self._create_collapsible_section(self.content_frame, "Core", initially_open=True)
        self.var_enabletb = tk.BooleanVar(value=getattr(config, "enabletb", False))
        self._add_switch_in_frame(sec_core, "Enable Triggerbot", self.var_enabletb, self._on_enabletb_changed)
        self._checkbox_vars["enabletb"] = self.var_enabletb

        self.trigger_type_option = self._add_option_row_in_frame(
            sec_core,
            "Trigger Type",
            list(TRIGGER_TYPE_DISPLAY.values()),
            self._on_trigger_type_selected,
        )
        self._option_widgets["trigger_type"] = self.trigger_type_option
        self.trigger_type_option.set(TRIGGER_TYPE_DISPLAY.get(current_trigger_type, "Classic Trigger"))

        if current_trigger_type == "rgb":
            sec_rgb = self._create_collapsible_section(self.content_frame, "RGB Parameters", initially_open=True)

            self._add_slider_in_frame(
                sec_rgb,
                "FOV Size",
                "tbfovsize",
                1,
                300,
                float(getattr(config, "tbfovsize", 70)),
                self._on_tbfovsize_changed,
            )
            self._add_trigger_ads_fov_controls_in_frame(sec_rgb)

            self.rgb_color_profile_option = self._add_option_row_in_frame(
                sec_rgb,
                "RGB Preset",
                list(RGB_TRIGGER_PROFILE_DISPLAY.values()),
                self._on_rgb_color_profile_selected,
            )
            self._option_widgets["rgb_color_profile"] = self.rgb_color_profile_option
            current_rgb_profile = str(getattr(config, "rgb_color_profile", "purple")).strip().lower()
            if current_rgb_profile not in RGB_TRIGGER_PROFILE_DISPLAY:
                current_rgb_profile = "purple"
                config.rgb_color_profile = "purple"
            self.rgb_color_profile_option.set(
                RGB_TRIGGER_PROFILE_DISPLAY.get(current_rgb_profile, "Purple")
            )

            # Custom RGB Settings (collapsible, only show when custom is selected)
            self.custom_rgb_section, self.custom_rgb_container = self._create_collapsible_section(
                sec_rgb, "Custom RGB", initially_open=True, auto_pack=False
            )
            if current_rgb_profile == "custom":
                self.custom_rgb_container.pack(fill="x", pady=(5, 0))

            # R, G, B sliders
            self._add_slider_in_frame(
                self.custom_rgb_section,
                "R",
                "rgb_custom_r",
                0,
                255,
                int(getattr(config, "rgb_custom_r", 161)),
                lambda v: self._on_rgb_custom_changed("rgb_custom_r", v),
            )
            self._add_slider_in_frame(
                self.custom_rgb_section,
                "G",
                "rgb_custom_g",
                0,
                255,
                int(getattr(config, "rgb_custom_g", 69)),
                lambda v: self._on_rgb_custom_changed("rgb_custom_g", v),
            )
            self._add_slider_in_frame(
                self.custom_rgb_section,
                "B",
                "rgb_custom_b",
                0,
                255,
                int(getattr(config, "rgb_custom_b", 163)),
                lambda v: self._on_rgb_custom_changed("rgb_custom_b", v),
            )

            # Color preview frame
            preview_frame = ctk.CTkFrame(self.custom_rgb_section, fg_color="transparent")
            preview_frame.pack(fill="x", pady=(10, 5))
            
            ctk.CTkLabel(
                preview_frame,
                text="Color Preview",
                font=FONT_MAIN,
                text_color=COLOR_TEXT
            ).pack(side="left")
            
            # Calculate initial RGB color hex
            r = max(0, min(255, int(getattr(config, "rgb_custom_r", 161))))
            g = max(0, min(255, int(getattr(config, "rgb_custom_g", 69))))
            b = max(0, min(255, int(getattr(config, "rgb_custom_b", 163))))
            initial_color_hex = f"#{r:02x}{g:02x}{b:02x}"
            
            # Color preview box
            self.rgb_color_preview = ctk.CTkFrame(
                preview_frame,
                width=100,
                height=30,
                corner_radius=4,
                fg_color=initial_color_hex,
                border_width=1,
                border_color=COLOR_BORDER
            )
            self.rgb_color_preview.pack(side="right", padx=(10, 0))

            self._add_range_slider_in_frame(
                sec_rgb,
                "Delay Range (s)",
                "rgb_tbdelay",
                0.0,
                1.0,
                float(getattr(config, "rgb_tbdelay_min", 0.08)),
                float(getattr(config, "rgb_tbdelay_max", 0.15)),
                self._on_rgb_tbdelay_range_changed,
                is_float=True,
            )
            self._add_range_slider_in_frame(
                sec_rgb,
                "Hold Range (ms)",
                "rgb_tbhold",
                5,
                500,
                float(getattr(config, "rgb_tbhold_min", 40)),
                float(getattr(config, "rgb_tbhold_max", 60)),
                self._on_rgb_tbhold_range_changed,
                is_float=False,
            )
            self._add_range_slider_in_frame(
                sec_rgb,
                "Cooldown Range (s)",
                "rgb_tbcooldown",
                0.0,
                5.0,
                float(getattr(config, "rgb_tbcooldown_min", 0.0)),
                float(getattr(config, "rgb_tbcooldown_max", 0.0)),
                self._on_rgb_tbcooldown_range_changed,
                is_float=True,
            )
        else:
            sec_params = self._create_collapsible_section(self.content_frame, "Parameters", initially_open=True)
            self._add_slider_in_frame(
                sec_params,
                "FOV Size",
                "tbfovsize",
                1,
                300,
                float(getattr(config, "tbfovsize", 70)),
                self._on_tbfovsize_changed,
            )
            self._add_trigger_ads_fov_controls_in_frame(sec_params)
            self._add_range_slider_in_frame(
                sec_params,
                "Delay Range (s)",
                "tbdelay",
                0.0,
                1.0,
                float(getattr(config, "tbdelay_min", 0.08)),
                float(getattr(config, "tbdelay_max", 0.15)),
                self._on_tbdelay_range_changed,
                is_float=True,
            )
            self._add_range_slider_in_frame(
                sec_params,
                "Hold Range (ms)",
                "tbhold",
                5,
                500,
                float(getattr(config, "tbhold_min", 40)),
                float(getattr(config, "tbhold_max", 60)),
                self._on_tbhold_range_changed,
                is_float=False,
            )

            sec_conditions = self._create_collapsible_section(
                self.content_frame,
                "Trigger Conditions",
                initially_open=False,
            )
            self._add_slider_in_frame(
                sec_conditions,
                "Min Pixels",
                "trigger_min_pixels",
                1,
                200,
                int(getattr(config, "trigger_min_pixels", 4)),
                self._on_trigger_min_pixels_changed,
                is_float=False,
            )
            self._add_slider_in_frame(
                sec_conditions,
                "Min Ratio",
                "trigger_min_ratio",
                0.0,
                1.0,
                float(getattr(config, "trigger_min_ratio", 0.03)),
                self._on_trigger_min_ratio_changed,
                is_float=True,
            )
            self._add_slider_in_frame(
                sec_conditions,
                "Confirm Frames",
                "trigger_confirm_frames",
                1,
                10,
                int(getattr(config, "trigger_confirm_frames", 2)),
                self._on_trigger_confirm_frames_changed,
                is_float=False,
            )

            sec_burst = self._create_collapsible_section(self.content_frame, "Burst Settings", initially_open=False)
            self._add_range_slider_in_frame(
                sec_burst,
                "Cooldown Range (s)",
                "tbcooldown",
                0.0,
                5.0,
                float(getattr(config, "tbcooldown_min", 0.0)),
                float(getattr(config, "tbcooldown_max", 0.0)),
                self._on_tbcooldown_range_changed,
                is_float=True,
            )
            self._add_range_slider_in_frame(
                sec_burst,
                "Burst Count Range",
                "tbburst_count",
                1,
                10,
                int(getattr(config, "tbburst_count_min", 1)),
                int(getattr(config, "tbburst_count_max", 1)),
                self._on_tbburst_count_range_changed,
                is_float=False,
            )
            self._add_range_slider_in_frame(
                sec_burst,
                "Burst Interval Range (ms)",
                "tbburst_interval",
                0,
                500,
                float(getattr(config, "tbburst_interval_min", 0.0)),
                float(getattr(config, "tbburst_interval_max", 0.0)),
                self._on_tbburst_interval_range_changed,
                is_float=True,
            )

        sec_activation = self._create_collapsible_section(self.content_frame, "Activation", initially_open=False)
        current_tb_btn = self._ads_binding_to_display(getattr(config, "selected_tb_btn", 3))
        self.tb_key_bind_button = self._add_bind_capture_row_in_frame(
            sec_activation,
            "Keybind",
            current_tb_btn,
            self._start_trigger_key_capture,
        )

        trigger_activation_types = ["Hold to Enable", "Hold to Disable", "Toggle"]
        self.trigger_activation_type_option = self._add_option_row_in_frame(
            sec_activation,
            "Trigger Mode",
            trigger_activation_types,
            self._on_trigger_activation_type_selected,
        )
        self._option_widgets["trigger_activation_type"] = self.trigger_activation_type_option
        current_trigger_activation_type = str(
            getattr(config, "trigger_activation_type", "hold_enable")
        ).strip().lower()
        trigger_activation_display = {
            "hold_enable": "Hold to Enable",
            "hold_disable": "Hold to Disable",
            "toggle": "Toggle",
        }
        self.trigger_activation_type_option.set(
            trigger_activation_display.get(current_trigger_activation_type, "Hold to Enable")
        )

        current_trigger_ads_key = self._ads_binding_to_display(
            getattr(config, "trigger_ads_key", "Right Mouse Button")
        )
        self.trigger_ads_key_bind_button = self._add_bind_capture_row_in_frame(
            sec_activation,
            "ADS Keybind",
            current_trigger_ads_key,
            self._start_trigger_ads_key_capture,
        )
        self.trigger_ads_key_type_option = self._add_option_row_in_frame(
            sec_activation,
            "ADS Key Type",
            list(ADS_KEY_TYPE_DISPLAY_TO_VALUE.keys()),
            self._on_trigger_ads_key_type_selected,
        )
        self._option_widgets["trigger_ads_key_type"] = self.trigger_ads_key_type_option
        current_trigger_ads_key_type = str(
            getattr(config, "trigger_ads_key_type", "hold")
        ).strip().lower()
        self.trigger_ads_key_type_option.set(
            ADS_KEY_TYPE_VALUE_TO_DISPLAY.get(current_trigger_ads_key_type, "Hold")
        )

        if self._supports_trigger_strafe_ui():
            sec_strafe_helper = self._create_collapsible_section(
                self.content_frame,
                "Strafe Helper",
                initially_open=False,
            )
            self.trigger_strafe_mode_option = self._add_option_row_in_frame(
                sec_strafe_helper,
                "Mode",
                list(TRIGGER_STRAFE_MODE_DISPLAY.values()),
                self._on_trigger_strafe_mode_selected,
            )
            self._option_widgets["trigger_strafe_mode"] = self.trigger_strafe_mode_option
            current_strafe_mode = str(getattr(config, "trigger_strafe_mode", "off")).strip().lower()
            if current_strafe_mode not in TRIGGER_STRAFE_MODE_DISPLAY:
                current_strafe_mode = "off"
                config.trigger_strafe_mode = "off"
            self.trigger_strafe_mode_option.set(
                TRIGGER_STRAFE_MODE_DISPLAY.get(current_strafe_mode, "Off")
            )

            if current_strafe_mode == "auto":
                self._add_slider_in_frame(
                    sec_strafe_helper,
                    "Auto Lead (ms)",
                    "trigger_strafe_auto_lead_ms",
                    0,
                    50,
                    int(getattr(config, "trigger_strafe_auto_lead_ms", 8)),
                    self._on_trigger_strafe_auto_lead_ms_changed,
                    is_float=False,
                )
            elif current_strafe_mode == "manual_wait":
                self._add_slider_in_frame(
                    sec_strafe_helper,
                    "Neutral Wait (ms)",
                    "trigger_strafe_manual_neutral_ms",
                    0,
                    300,
                    int(getattr(config, "trigger_strafe_manual_neutral_ms", 0)),
                    self._on_trigger_strafe_manual_neutral_ms_changed,
                    is_float=False,
                )
        else:
            config.trigger_strafe_mode = "off"

    def _show_magnet_trigger_tab(self):
        """Magnet Trigger UI was retired in v2.1.0; the backend keys remain.

        Kept as a redirect shim for one release so saved layouts and external
        scripts that still call it do not crash.
        """
        self._show_aimbot_tab()

    def _show_rcs_tab(self):
        """Dedicated Recoil Control System (RCS) tab for Burst & Spray tuning."""
        if self._ensure_pro_mode("RCS"):
            return
        self._active_tab_name = "Combat"
        self._clear_content()
        self._add_sub_nav_bar(
            ["Main Aimbot", "Sec Aimbot", "Flick V2", "Recoil & RCS"],
            "Recoil & RCS",
            {
                "Main Aimbot": self._show_aimbot_tab,
                "Sec Aimbot": self._show_sec_aimbot_tab,
                "Flick V2": self._show_flick_v2_tab,
                "Recoil & RCS": self._show_rcs_tab,
            }
        )
        self._add_title("Recoil Control System (RCS)")

        # Master Control Switches Row
        master_row = ctk.CTkFrame(self.content_frame, fg_color="#141822", corner_radius=8, border_width=1, border_color="#232B3B")
        master_row.pack(fill="x", pady=(0, 10))
        master_inner = ctk.CTkFrame(master_row, fg_color="transparent")
        master_inner.pack(fill="x", padx=12, pady=6)

        self.var_enablercs = tk.BooleanVar(value=getattr(config, "enablercs", True))
        ctk.CTkSwitch(
            master_inner,
            text="Enable Auto Recoil Compensation (RCS)",
            variable=self.var_enablercs,
            command=self._on_enablercs_changed,
            font=("Segoe UI", 11, "bold"),
            progress_color="#10B981"
        ).pack(side="left")
        self._checkbox_vars["enablercs"] = self.var_enablercs

        # 2-Column Grid Container
        grid_container = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        grid_container.pack(fill="both", expand=True)
        grid_container.grid_columnconfigure(0, weight=1)
        grid_container.grid_columnconfigure(1, weight=1)

        # Card 1: Burst & Spray Ballistics
        self.card_recoil = ModernCard(grid_container, "Burst & Spray Ballistics", icon="🎯", badge_text="Ballistics", accent_color="#06B6D4")
        self.card_recoil.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 10))

        # RCS Activation Delay (Burst vs Spray threshold)
        self._add_slider_in_frame(
            self.card_recoil.content,
            "Burst Immunity Delay (ms)",
            "rcs_activation_delay",
            0, 500,
            float(getattr(config, "rcs_activation_delay", 140)),
            self._on_rcs_activation_delay_changed
        )
        info_lbl = ctk.CTkLabel(
            self.card_recoil.content,
            text="💡 < 140ms: Tap/Burst locks headshot | > 140ms: Auto spray pull-down",
            font=("Segoe UI", 9, "italic"),
            text_color="#94A3B8"
        )
        info_lbl.pack(anchor="w", padx=4, pady=(0, 8))

        # RCS Pull Speed
        self._add_slider_in_frame(
            self.card_recoil.content,
            "Recoil Pull Speed",
            "rcs_pull_speed",
            1, 20,
            float(getattr(config, "rcs_pull_speed", 9)),
            self._on_rcs_pull_speed_changed
        )

        # Rapid Click Threshold
        self._add_slider_in_frame(
            self.card_recoil.content,
            "Rapid Click Threshold (ms)",
            "rcs_rapid_click_threshold",
            50, 500,
            float(getattr(config, "rcs_rapid_click_threshold", 180)),
            self._on_rcs_rapid_click_threshold_changed
        )

        # Card 2: Activation & Recovery
        self.card_rcs_recovery = ModernCard(grid_container, "Activation & Recovery", icon="⚙️", badge_text="Recovery", accent_color="#10B981")
        self.card_rcs_recovery.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 10))

        # Keybind
        current_rcs_btn = self._ads_binding_to_display(getattr(config, "rcs_keybind", 0))
        self.rcs_key_bind_button = self._add_bind_capture_row_in_frame(
            self.card_rcs_recovery.content,
            "Trigger Key",
            current_rcs_btn,
            self._start_rcs_key_capture
        )

        # Auto Y-Release Switch
        self.var_rcs_release_y_enabled = tk.BooleanVar(value=getattr(config, "rcs_release_y_enabled", True))
        self._add_switch_in_frame(
            self.card_rcs_recovery.content,
            "Auto Y-Axis Recovery",
            init_val=self.var_rcs_release_y_enabled.get(),
            command=lambda v: [self.var_rcs_release_y_enabled.set(v), self._on_rcs_release_y_enabled_changed()]
        )
        self._checkbox_vars["rcs_release_y_enabled"] = self.var_rcs_release_y_enabled

        # Y-Release Duration
        self._add_slider_in_frame(
            self.card_rcs_recovery.content,
            "Recovery Duration (s)",
            "rcs_release_y_duration",
            0.1, 2.0,
            float(getattr(config, "rcs_release_y_duration", 0.35)),
            self._on_rcs_release_y_duration_changed
        )

    def _show_config_tab(self):
        if self._ensure_pro_mode("Profiles"):
            return
        self._active_tab_name = "Profiles"
        self._clear_content()
        self._add_sub_nav_bar(
            ["Hardware & Capture", "Profiles & Config", "Debug & Telemetry"],
            "Profiles & Config",
            {
                "Hardware & Capture": self._show_general_tab,
                "Profiles & Config": self._show_config_tab,
                "Debug & Telemetry": self._show_debug_tab,
            }
        )
        self._add_title("Configuration Profiles")

        os.makedirs("configs", exist_ok=True)

        self.card_profile_manager = ModernCard(
            self.content_frame,
            "Profile Management",
            icon="📁",
            badge_text="Presets",
            accent_color="#10B981"
        )
        self.card_profile_manager.pack(fill="x", pady=(0, 10))

        self.config_option = self._add_option_menu([], self._on_config_selected, parent=self.card_profile_manager.content)
        self.config_option.pack(fill="x", pady=(4, 10))

        btn_frame = ctk.CTkFrame(self.card_profile_manager.content, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(0, 10))
        self._add_text_button(btn_frame, "SAVE", self._save_config).pack(side="left", padx=(0, 8))
        self._add_text_button(btn_frame, "LOAD", self._load_selected_config).pack(side="left", padx=(0, 8))
        self._add_text_button(btn_frame, "DEL", self._delete_selected_config).pack(side="left", padx=(0, 8))
        self._add_text_button(btn_frame, "NEW", self._save_new_config).pack(side="left", padx=(0, 8))
        self._add_text_button(btn_frame, "EXPORT", self._export_selected_config).pack(side="left", padx=(0, 8))
        self._add_text_button(btn_frame, "IMPORT", self._import_config_file).pack(side="left")

        self.config_log = ctk.CTkTextbox(
            self.card_profile_manager.content,
            height=120,
            fg_color=COLOR_SURFACE,
            text_color=COLOR_TEXT_DIM,
            font=("Consolas", 10),
            corner_radius=4
        )
        self.config_log.pack(fill="x", pady=(4, 6))

        self._refresh_config_list()
        # One-shot on tab entry: no scheduled wrapper, so the scheduler remains
        # the only periodic caller (plan RC-1).
        self.after(100, self._poll_clipboard_now)

    def _show_debug_tab(self):
        """Debug & Telemetry tab"""
        if self._ensure_pro_mode("Telemetry"):
            return
        self._active_tab_name = "Telemetry"
        self._clear_content()
        self._add_sub_nav_bar(
            ["Hardware & Capture", "Profiles & Config", "Debug & Telemetry"],
            "Debug & Telemetry",
            {
                "Hardware & Capture": self._show_general_tab,
                "Profiles & Config": self._show_config_tab,
                "Debug & Telemetry": self._show_debug_tab,
            }
        )
        self._add_title("Debug & Telemetry")

        # 1. Mouse Input Telemetry Card
        self.card_mouse_monitor = ModernCard(
            self.content_frame,
            "Mouse Input Telemetry",
            icon="⚡",
            badge_text="Hardware",
            accent_color="#06B6D4"
        )
        self.card_mouse_monitor.pack(fill="x", pady=(0, 10))

        if not hasattr(self, 'debug_mouse_input_var'):
            self.debug_mouse_input_var = tk.BooleanVar(value=False)
        debug_switch = self._add_switch_in_frame(
            self.card_mouse_monitor.content,
            "Enable Mouse Input Debug",
            self.debug_mouse_input_var,
            self._on_debug_mouse_input_changed
        )

        self.debug_mouse_frame = ctk.CTkFrame(self.card_mouse_monitor.content, fg_color=COLOR_SURFACE, corner_radius=6)
        self.debug_mouse_frame.pack(fill="x", pady=10)

        self.debug_button_widgets = {}
        button_names = {
            0: "Left Button",
            1: "Right Button",
            2: "Middle Button",
            3: "Side Button 4",
            4: "Side Button 5"
        }

        for idx, name in button_names.items():
            btn_frame = ctk.CTkFrame(self.debug_mouse_frame, fg_color="transparent")
            btn_frame.pack(fill="x", padx=10, pady=5)

            name_label = ctk.CTkLabel(
                btn_frame,
                text=name,
                font=FONT_MAIN,
                text_color=COLOR_TEXT,
                width=120,
                anchor="w"
            )
            name_label.pack(side="left", padx=5)

            state_indicator = ctk.CTkLabel(
                btn_frame,
                text="●",
                font=("Arial", 16),
                text_color="#CF6679",
                width=30
            )
            state_indicator.pack(side="left", padx=5)

            count_label = ctk.CTkLabel(
                btn_frame,
                text="Count: 0",
                font=FONT_MAIN,
                text_color=COLOR_TEXT_DIM,
                anchor="w"
            )
            count_label.pack(side="left", padx=5, fill="x", expand=True)

            reset_btn = ctk.CTkButton(
                btn_frame,
                text="Reset",
                width=60,
                height=25,
                fg_color=COLOR_BORDER,
                hover_color=COLOR_SURFACE,
                text_color=COLOR_TEXT,
                font=("Roboto", 9),
                command=lambda i=idx: self._reset_button_count(i)
            )
            reset_btn.pack(side="right", padx=5)

            self.debug_button_widgets[idx] = {
                "state_indicator": state_indicator,
                "count_label": count_label
            }

            try:
                count = self.mouse_input_monitor.get_button_count(idx)
                count_label.configure(text=f"Count: {count}")
            except Exception:
                pass

        reset_all_frame = ctk.CTkFrame(self.debug_mouse_frame, fg_color="transparent")
        reset_all_frame.pack(fill="x", padx=10, pady=5)

        reset_all_btn = ctk.CTkButton(
            reset_all_frame,
            text="Reset All Counts",
            width=120,
            height=30,
            fg_color=COLOR_BORDER,
            hover_color=COLOR_SURFACE,
            text_color=COLOR_TEXT,
            font=FONT_MAIN,
            command=self._reset_all_button_counts
        )
        reset_all_btn.pack(side="right", padx=5)

        if self.debug_mouse_input_var.get():
            self.debug_mouse_frame.pack(fill="x", pady=10)
            self.mouse_input_monitor.enable()
        else:
            self.debug_mouse_frame.pack_forget()

        # 2. System Logs Card
        self.card_system_logs = ModernCard(
            self.content_frame,
            "System Logs & Diagnostics",
            icon="📜",
            badge_text="Telemetry",
            accent_color="#F59E0B"
        )
        self.card_system_logs.pack(fill="both", expand=True, pady=(0, 10))

        control_frame = ctk.CTkFrame(self.card_system_logs.content, fg_color="transparent")
        control_frame.pack(fill="x", pady=(0, 8))

        clear_btn = self._add_text_button(control_frame, "Clear Log", self._clear_debug_log)
        clear_btn.pack(side="left", padx=(0, 10))

        webmenu_btn = self._add_text_button(control_frame, "Open WebMenu", self._open_webmenu)
        webmenu_btn.pack(side="left", padx=(0, 10))

        self.debug_log_count_label = ctk.CTkLabel(
            control_frame,
            text="Log Count: 0",
            font=FONT_MAIN,
            text_color=COLOR_TEXT_DIM
        )
        self.debug_log_count_label.pack(side="left", padx=10)

        self.debug_log_textbox = ctk.CTkTextbox(
            self.card_system_logs.content,
            height=350,
            fg_color=COLOR_SURFACE,
            text_color=COLOR_TEXT,
            font=("Consolas", 10),
            corner_radius=0
        )
        self.debug_log_textbox.pack(fill="both", expand=True)

    def _open_webmenu(self):
        ensure_running = getattr(self, "_ensure_webmenu_running", None)
        if callable(ensure_running):
            ok = bool(ensure_running())
            if not ok:
                log_print("[UI] WebMenu failed to start.")
                return

        host = str(getattr(config, "webmenu_host", "127.0.0.1")).strip() or "127.0.0.1"
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        try:
            port = int(getattr(config, "webmenu_port", 8765))
        except Exception:
            port = 8765
        port = max(1, min(65535, port))
        url = f"http://{host}:{port}"
        try:
            webbrowser.open(url, new=2)
            if not bool(getattr(config, "webmenu_enabled", False)):
                log_print(f"[UI] WebMenu is disabled in config. URL opened anyway: {url}")
        except Exception as e:
            log_print(f"[UI] Failed to open WebMenu URL: {e}")
        
        # Initialize log display. Reset the version marker first: the widgets were
        # just rebuilt, so the cached version must not suppress the first render.
        self._debug_log_version = None
        self._update_debug_log()

    # --- 妤电啊绲勪欢妲嬪缓鍣?---

    def _add_title(self, text):
        ctk.CTkLabel(self.content_frame, text=t(text), font=FONT_TITLE, text_color=COLOR_TEXT).pack(anchor="w", pady=(0, 10))

    def _add_subtitle_in_frame(self, parent, text):
        ctk.CTkLabel(parent, text=heading(text), font=("Roboto", 10, "bold"), text_color=COLOR_TEXT_DIM).pack(anchor="w", pady=(6, 2))
    
    def _add_spacer_in_frame(self, parent):
        """在指定 frame 中添加間距"""
        ctk.CTkFrame(parent, height=1, fg_color="transparent").pack(pady=2)
    
    def _create_tooltip(self, widget, text):
        """
        鐐?widget 鍓靛缓 tooltip
        
        Args:
            widget: 瑕佺秮瀹?tooltip 鐨?widget
            text: tooltip 鏂囧瓧鍏у
        """
        tooltip_window = [None]  # 浣跨敤鍒楄〃浠ヤ究鍦ㄥ祵濂楀嚱鏁镐腑淇敼
        
        def show_tooltip(event):
            if tooltip_window[0] is not None:
                return
            
            # 鐛插彇榧犳浣嶇疆
            x = event.x_root + 10
            y = event.y_root + 10
            
            # 鍓靛缓 tooltip 绐楀彛
            tooltip_win = ctk.CTkToplevel(widget)
            tooltip_win.overrideredirect(True)
            tooltip_win.attributes("-topmost", True)
            tooltip_win.configure(fg_color=COLOR_BG)
            
            # 鍓靛缓 tooltip 鍏у
            tooltip_frame = ctk.CTkFrame(tooltip_win, fg_color=COLOR_SURFACE, corner_radius=4)
            tooltip_frame.pack(fill="both", expand=True, padx=1, pady=1)
            
            tooltip_label = ctk.CTkLabel(
                tooltip_frame,
                text=t(text),
                font=("Roboto", 12.5),
                text_color=COLOR_TEXT,
                justify="left",
                anchor="w",
                wraplength=400
            )
            tooltip_label.pack(anchor="w", padx=12, pady=10)
            
            # 鏇存柊绐楀彛澶у皬涓﹁ō缃綅缃?
            tooltip_win.update_idletasks()
            tooltip_win.geometry(f"+{x}+{y}")
            
            tooltip_window[0] = tooltip_win
        
        def hide_tooltip(event):
            if tooltip_window[0] is not None:
                try:
                    tooltip_window[0].destroy()
                except:
                    pass
                tooltip_window[0] = None
        
        widget.bind("<Enter>", show_tooltip)
        widget.bind("<Leave>", hide_tooltip)

    def _get_collapsible_state_key(self, title, state_key=None):
        tab_key = str(getattr(self, "_active_tab_name", "General")).strip().lower().replace(" ", "_")
        section_key = str(state_key or title).strip().lower().replace(" ", "_")
        return f"{tab_key}:{section_key}"

    def _set_collapsible_state(self, cache_key, is_open):
        self._collapsible_section_states[str(cache_key)] = bool(is_open)
        config.ui_collapsible_states = dict(self._collapsible_section_states)

    def _create_collapsible_section(self, parent, title, initially_open=True, auto_pack=True, tooltip_text=None, state_key=None):
        """
        寤虹珛鍙睍闁?鏀惰捣鐨?section銆?
        
        Args:
            parent: 鐖跺鍣?
            title: section 妯欓
            initially_open: 鏄惁闋愯ō灞曢枊
            auto_pack: 鏄惁鑷嫊 pack container锛團alse 鏅傜敱瑾跨敤鑰呮帶鍒讹級
            tooltip_text: 鍙伕鐨?tooltip 鏂囧瓧锛堝鏋滄彁渚涳紝鏈冨湪妯欓鏃侀’绀哄晱铏熷湒妯欙級
            
        Returns:
            tuple: (content_frame, container) 濡傛灉 auto_pack=False锛屽惁鍓囧彧杩斿洖 content_frame
        """
        container = ctk.CTkFrame(parent, fg_color="transparent")
        if auto_pack:
            container.pack(fill="x", pady=(3, 0))
        
        content = ctk.CTkFrame(container, fg_color="transparent")

        cache_key = self._get_collapsible_state_key(title, state_key=state_key)
        initial_open_state = self._collapsible_section_states.get(cache_key, initially_open)
        initial_open_state = bool(initial_open_state)
        # If in simple mode, collapse non-essential technical sections unless explicitly configured
        if not getattr(self, "_ui_pro_mode", False) and cache_key not in self._collapsible_section_states:
            simple_collapse_keys = [
                "button mask", "mouse lock", "offset", "condition",
                "burst", "strafe", "rgb parameters", "activation"
            ]
            t_lower = str(title).lower()
            if any(k in t_lower for k in simple_collapse_keys):
                initial_open_state = False
        is_open = [initial_open_state]
        arrow_text = "▼" if initial_open_state else "▶"
        
        header = ctk.CTkFrame(
            container,
            fg_color=COLOR_SURFACE,
            corner_radius=6,
            height=28,
            border_width=1,
            border_color=COLOR_BORDER,
        )
        header.pack(fill="x")
        header.pack_propagate(False)
        
        arrow_label = ctk.CTkLabel(
            header, text=arrow_text, font=("Consolas", 10), text_color=COLOR_ACCENT,
            width=20
        )
        arrow_label.pack(side="left", padx=(8, 0))
        
        title_label = ctk.CTkLabel(
            header, text=heading(title), font=("Consolas", 10, "bold"), text_color=COLOR_TEXT
        )
        title_label.pack(side="left", padx=(4, 0))
        
        # 濡傛灉鏈?tooltip 鏂囧瓧锛屾坊鍔犲晱铏熷湒妯?
        if tooltip_text:
            tooltip_icon = ctk.CTkLabel(
                header, text="?", font=("Consolas", 10, "bold"), text_color=COLOR_ACCENT,
                width=20, cursor="hand2"
            )
            tooltip_icon.pack(side="left", padx=(8, 0))
            self._create_tooltip(tooltip_icon, tooltip_text)
        
        def toggle(_event=None):
            if is_open[0]:
                content.pack_forget()
                arrow_label.configure(text="▶")
                is_open[0] = False
                self._set_collapsible_state(cache_key, False)
            else:
                content.pack(fill="x", padx=(8, 0), pady=(2, 0))
                arrow_label.configure(text="▼")
                is_open[0] = True
                self._set_collapsible_state(cache_key, True)
        
        header.bind("<Button-1>", toggle)
        arrow_label.bind("<Button-1>", toggle)
        title_label.bind("<Button-1>", toggle)
        
        if initial_open_state:
            content.pack(fill="x", padx=(8, 0), pady=(2, 0))
        self._set_collapsible_state(cache_key, initial_open_state)
        
        if auto_pack:
            return content
        else:
            return content, container

    def _add_slider_in_frame(self, parent, text, key, min_val, max_val, init_val, command, is_float=False, steps=None, suffix="", tooltip=None, advanced=False):
        """鍦ㄦ寚瀹?parent frame 涓坊鍔?slider锛堣垏 _add_slider 閭忚集涓€鑷达級"""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=2)
        if advanced:
            if getattr(self, "_advanced_rows", None) is None:
                self._advanced_rows = []
            self._advanced_rows.append(frame)
        
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x")
        _label = ctk.CTkLabel(header, text=f"{t(text)}{suffix}", font=FONT_MAIN, text_color=COLOR_TEXT)
        _label.pack(side="left")
        if tooltip:
            self._create_tooltip(_label, tooltip)
        
        val_str = f"{init_val:.2f}" if is_float else f"{int(init_val)}"
        val_entry = ctk.CTkEntry(
            header, width=80, height=25, fg_color=COLOR_SURFACE,
            border_width=1, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, font=FONT_MAIN, justify="center"
        )
        val_entry.insert(0, val_str)
        val_entry.pack(side="right")
        
        n_steps = 100
        if steps:
            try:
                span = float(max_val) - float(min_val)
                n_steps = max(1, min(1000, int(round(span / float(steps)))))
            except (TypeError, ValueError, ZeroDivisionError):
                n_steps = 100

        slider = ctk.CTkSlider(
            frame, from_=min_val, to=max_val, number_of_steps=n_steps,
            fg_color=COLOR_SURFACE, progress_color=COLOR_ACCENT,
            button_color=COLOR_ACCENT, button_hover_color=COLOR_ACCENT_HOVER,
            height=10,
            command=lambda v: self._on_slider_changed(v, val_entry, key, command, is_float, slider, min_val, max_val)
        )
        slider.set(init_val)
        slider.pack(fill="x", pady=(2, 5))
        
        val_entry.bind("<Return>", lambda e: self._on_entry_changed(val_entry, slider, key, command, is_float, min_val, max_val))
        val_entry.bind("<FocusOut>", lambda e: self._on_entry_changed(val_entry, slider, key, command, is_float, min_val, max_val))
        
        self._register_slider(key, slider, val_entry, min_val, max_val, is_float)
        return slider

    def _add_option_row_in_frame(self, parent, label_text, values, command):
        """鍦ㄦ寚瀹?parent frame 涓坊鍔?OptionMenu锛堣垏 _add_option_row 閭忚集涓€鑷达級"""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=5)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=0)
        ctk.CTkLabel(frame, text=t(label_text), font=FONT_MAIN, text_color=COLOR_TEXT).grid(row=0, column=0, sticky="w", padx=(0, 10))
        menu = self._add_option_menu(values, command, parent=frame)
        menu.grid(row=0, column=1, sticky="e")
        return menu

    def _add_hardware_option_row_in_frame(self, parent, label_text, values, command):
        """Hardware API row with stronger accent / 強化 Hardware API row 視覺層次"""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=5)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=0)
        ctk.CTkLabel(frame, text=t(label_text), font=FONT_MAIN, text_color=COLOR_TEXT).grid(
            row=0, column=0, sticky="w", padx=(0, 10)
        )
        menu = self._add_hardware_option_menu(values, command, parent=frame)
        menu.grid(row=0, column=1, sticky="e")
        return menu

    def _add_bind_capture_row_in_frame(self, parent, label_text, button_text, command):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=5)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=0)
        ctk.CTkLabel(frame, text=t(label_text), font=FONT_MAIN, text_color=COLOR_TEXT).grid(
            row=0, column=0, sticky="w", padx=(0, 10)
        )
        button = ctk.CTkButton(
            frame,
            text=t(str(button_text)),
            command=command,
            font=FONT_MAIN,
            text_color=COLOR_TEXT,
            fg_color=COLOR_SURFACE,
            hover_color=COLOR_NAV_HOVER_BG,
            border_width=1,
            border_color=COLOR_BORDER,
            corner_radius=8,
            height=28,
            width=180,
        )
        button.grid(row=0, column=1, sticky="e")
        return button

    def _add_switch_in_frame(self, parent, text, variable, command):
        """鍦ㄦ寚瀹?parent frame 涓坊鍔?Switch"""
        switch = ctk.CTkSwitch(
            parent, text=t(text), variable=variable, command=command,
            progress_color=COLOR_ACCENT, fg_color=COLOR_SURFACE,
            button_color=COLOR_ACCENT, button_hover_color=COLOR_ACCENT_HOVER,
            font=FONT_MAIN, text_color=COLOR_TEXT
        )
        switch.pack(anchor="w", pady=5)
        return switch

    def _add_switch(self, text, variable, command):
        """Deprecated shim: use ``_add_switch_in_frame`` (kept for scripts)."""
        return self._add_switch_in_frame(self.content_frame, text, variable, command)

    def _add_slider(self, text, key, min_val, max_val, init_val, command, is_float=False):
        """Deprecated shim: use ``_add_slider_in_frame`` (kept for scripts)."""
        return self._add_slider_in_frame(
            self.content_frame, text, key, min_val, max_val, init_val, command, is_float=is_float
        )
        
        # 妯欑堡鑸囪几鍏ユ鍚屽湪涓€琛?
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x")
        ctk.CTkLabel(header, text=t(text), font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")
        
        # 鍙法杓殑杓稿叆妗嗭紙鏇挎彌鍘熸湰鐨?Label锛?
        val_str = f"{init_val:.2f}" if is_float else f"{int(init_val)}"
        val_entry = ctk.CTkEntry(
            header, 
            width=80,
            height=25,
            fg_color=COLOR_SURFACE,
            border_width=1,
            border_color=COLOR_BORDER,
            text_color=COLOR_TEXT,
            font=FONT_MAIN,
            justify="center"
        )
        val_entry.insert(0, val_str)
        val_entry.pack(side="right")
        
        # Slider
        slider = ctk.CTkSlider(
            frame, 
            from_=min_val, 
            to=max_val, 
            number_of_steps=100,
            fg_color=COLOR_SURFACE,
            progress_color=COLOR_ACCENT,
            button_color=COLOR_ACCENT,
            button_hover_color=COLOR_ACCENT_HOVER,
            height=10,
            command=lambda v: self._on_slider_changed(v, val_entry, key, command, is_float, slider, min_val, max_val)
        )
        slider.set(init_val)
        slider.pack(fill="x", pady=(2, 5))
        
        # 缍佸畾杓稿叆妗嗙殑浜嬩欢
        val_entry.bind("<Return>", lambda e: self._on_entry_changed(val_entry, slider, key, command, is_float, min_val, max_val))
        val_entry.bind("<FocusOut>", lambda e: self._on_entry_changed(val_entry, slider, key, command, is_float, min_val, max_val))
        
        # 瑷诲唺 slider锛堜繚瀛?entry 寮曠敤鑰屼笉鏄?label锛?
        self._register_slider(key, slider, val_entry, min_val, max_val, is_float)
    
    def _add_range_slider_in_frame(self, parent, text, key, min_val, max_val, init_min, init_max, command, is_float=False):
        self._add_range_slider_to_parent(
            parent,
            text,
            key,
            min_val,
            max_val,
            init_min,
            init_max,
            command,
            is_float=is_float,
        )

    def _add_range_slider(self, text, key, min_val, max_val, init_min, init_max, command, is_float=False):
        self._add_range_slider_to_parent(
            self.content_frame,
            text,
            key,
            min_val,
            max_val,
            init_min,
            init_max,
            command,
            is_float=is_float,
        )

    def _add_range_slider_to_parent(
        self,
        parent,
        text,
        key,
        min_val,
        max_val,
        init_min,
        init_max,
        command,
        is_float=False,
    ):
        """Add a dual-range slider in the given parent frame."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=2)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x")
        ctk.CTkLabel(header, text=t(text), font=FONT_MAIN, text_color=COLOR_TEXT).pack(side="left")

        max_str = f"{init_max:.2f}" if is_float else f"{int(init_max)}"
        max_entry = ctk.CTkEntry(
            header,
            width=70,
            height=25,
            fg_color=COLOR_SURFACE,
            border_width=1,
            border_color=COLOR_BORDER,
            text_color=COLOR_TEXT,
            font=("Roboto", 10),
            justify="center",
        )
        max_entry.insert(0, max_str)
        max_entry.pack(side="right", padx=2)

        ctk.CTkLabel(header, text="~", font=("Roboto", 10), text_color=COLOR_TEXT_DIM).pack(side="right")

        min_str = f"{init_min:.2f}" if is_float else f"{int(init_min)}"
        min_entry = ctk.CTkEntry(
            header,
            width=70,
            height=25,
            fg_color=COLOR_SURFACE,
            border_width=1,
            border_color=COLOR_BORDER,
            text_color=COLOR_TEXT,
            font=("Roboto", 10),
            justify="center",
        )
        min_entry.insert(0, min_str)
        min_entry.pack(side="right", padx=2)

        slider_frame = ctk.CTkFrame(frame, fg_color="transparent")
        slider_frame.pack(fill="x", pady=(2, 5))

        min_slider = ctk.CTkSlider(
            slider_frame,
            from_=min_val,
            to=max_val,
            number_of_steps=100 if is_float else int(max_val - min_val),
            fg_color=COLOR_SURFACE,
            progress_color=COLOR_ACCENT,
            button_color=COLOR_ACCENT,
            button_hover_color=COLOR_ACCENT_HOVER,
            height=10,
            command=lambda v: self._on_range_slider_changed(
                v, "min", min_entry, max_entry, min_slider, max_slider, key, command, is_float, min_val, max_val
            ),
        )
        min_slider.set(init_min)
        min_slider.pack(fill="x", pady=1)

        max_slider = ctk.CTkSlider(
            slider_frame,
            from_=min_val,
            to=max_val,
            number_of_steps=100 if is_float else int(max_val - min_val),
            fg_color=COLOR_SURFACE,
            progress_color=COLOR_ACCENT,
            button_color=COLOR_ACCENT,
            button_hover_color=COLOR_ACCENT_HOVER,
            height=10,
            command=lambda v: self._on_range_slider_changed(
                v, "max", min_entry, max_entry, min_slider, max_slider, key, command, is_float, min_val, max_val
            ),
        )
        max_slider.set(init_max)
        max_slider.pack(fill="x", pady=1)

        min_entry.bind(
            "<Return>",
            lambda e: self._on_range_entry_changed(
                min_entry, max_entry, min_slider, max_slider, key, command, is_float, min_val, max_val
            ),
        )
        min_entry.bind(
            "<FocusOut>",
            lambda e: self._on_range_entry_changed(
                min_entry, max_entry, min_slider, max_slider, key, command, is_float, min_val, max_val
            ),
        )
        max_entry.bind(
            "<Return>",
            lambda e: self._on_range_entry_changed(
                min_entry, max_entry, min_slider, max_slider, key, command, is_float, min_val, max_val
            ),
        )
        max_entry.bind(
            "<FocusOut>",
            lambda e: self._on_range_entry_changed(
                min_entry, max_entry, min_slider, max_slider, key, command, is_float, min_val, max_val
            ),
        )

        if not hasattr(self, "_range_slider_widgets"):
            self._range_slider_widgets = {}
        self._range_slider_widgets[key] = {
            "min_slider": min_slider,
            "max_slider": max_slider,
            "min_entry": min_entry,
            "max_entry": max_entry,
            "min_val": min_val,
            "max_val": max_val,
            "is_float": is_float,
        }
    
    def _on_range_slider_changed(self, value, slider_type, min_entry, max_entry, min_slider, max_slider, key, command, is_float, range_min, range_max):
        """鐣剁瘎鍦嶆粦濉婃敼璁婃檪鏇存柊"""
        val = float(value) if is_float else int(round(value))
        
        if slider_type == "min":
            # 纰轰繚 min 涓嶅ぇ鏂?max
            max_val = max_slider.get()
            if is_float:
                max_val = float(max_val)
            else:
                max_val = int(round(max_val))
            
            if val > max_val:
                val = max_val
                min_slider.set(val)
            
            # 鏇存柊杓稿叆妗?
            min_entry.delete(0, "end")
            min_entry.insert(0, f"{val:.2f}" if is_float else f"{val}")
        else:  # max
            # 纰轰繚 max 涓嶅皬鏂?min
            min_val = min_slider.get()
            if is_float:
                min_val = float(min_val)
            else:
                min_val = int(round(min_val))
            
            if val < min_val:
                val = min_val
                max_slider.set(val)
            
            # 鏇存柊杓稿叆妗?
            max_entry.delete(0, "end")
            max_entry.insert(0, f"{val:.2f}" if is_float else f"{val}")
        
        # 瑾跨敤鍥炶
        min_v = min_slider.get()
        max_v = max_slider.get()
        if is_float:
            command(float(min_v), float(max_v))
        else:
            command(int(round(min_v)), int(round(max_v)))
    
    def _on_range_entry_changed(self, min_entry, max_entry, min_slider, max_slider, key, command, is_float, range_min, range_max):
        """鐣剁瘎鍦嶈几鍏ユ鏀硅畩鏅傛洿鏂版粦濉?"""
        try:
            min_val = float(min_entry.get()) if is_float else int(float(min_entry.get()))
            max_val = float(max_entry.get()) if is_float else int(float(max_entry.get()))
            
            # 闄愬埗绡勫湇
            min_val = max(range_min, min(min_val, range_max))
            max_val = max(range_min, min(max_val, range_max))
            
            # 纰轰繚 min <= max
            if min_val > max_val:
                min_val, max_val = max_val, min_val
            
            # 鏇存柊婊戝
            min_slider.set(min_val)
            max_slider.set(max_val)
            
            # 鏇存柊杓稿叆妗嗛’绀?
            min_entry.delete(0, "end")
            min_entry.insert(0, f"{min_val:.2f}" if is_float else f"{min_val}")
            max_entry.delete(0, "end")
            max_entry.insert(0, f"{max_val:.2f}" if is_float else f"{max_val}")
            
            # 瑾跨敤鍥炶
            command(min_val, max_val)
        except ValueError:
            # 鐒℃晥杓稿叆锛屾仮寰╁埌鐣跺墠婊戝鍊?
            min_val = min_slider.get()
            max_val = max_slider.get()
            if is_float:
                min_val, max_val = float(min_val), float(max_val)
            else:
                min_val, max_val = int(round(min_val)), int(round(max_val))
            
            min_entry.delete(0, "end")
            min_entry.insert(0, f"{min_val:.2f}" if is_float else f"{min_val}")
            max_entry.delete(0, "end")
            max_entry.insert(0, f"{max_val:.2f}" if is_float else f"{max_val}")

    def _on_slider_changed(self, value, entry_widget, key, command, is_float, slider, min_val, max_val):
        """鐣舵粦姊濇敼璁婃檪鏇存柊杓稿叆妗?"""
        val = float(value) if is_float else int(round(value))
        # 闄愬埗绡勫湇
        val = max(min_val, min(val, max_val))
        
        # 鏇存柊杓稿叆妗?
        entry_widget.delete(0, "end")
        entry_widget.insert(0, f"{val:.2f}" if is_float else f"{val}")
        
        # 瑾跨敤鍘熷 command
        command(val)

    def _on_entry_changed(self, entry_widget, slider, key, command, is_float, min_val, max_val):
        """鐣惰几鍏ユ鏀硅畩鏅傛洿鏂版粦姊?"""
        try:
            text = entry_widget.get()
            val = float(text) if is_float else int(float(text))
            
            # 闄愬埗绡勫湇
            val = max(min_val, min(val, max_val))
            
            # 鏇存柊婊戞
            slider.set(val)
            
            # 鏇存柊杓稿叆妗嗛’绀猴紙鏍煎紡鍖栵級
            entry_widget.delete(0, "end")
            entry_widget.insert(0, f"{val:.2f}" if is_float else f"{val}")
            
            # 瑾跨敤鍘熷 command
            command(val)
        except ValueError:
            # 濡傛灉杓稿叆鐒℃晥锛屾仮寰╁埌婊戞鐣跺墠鍊?
            current_val = slider.get()
            val = float(current_val) if is_float else int(round(current_val))
            entry_widget.delete(0, "end")
            entry_widget.insert(0, f"{val:.2f}" if is_float else f"{val}")

    def _add_option_menu(self, values, command, parent=None):
        """鍓靛缓鐛ㄧ珛鐨?OptionMenu"""
        target_parent = parent if parent else self.content_frame
        return ctk.CTkOptionMenu(
            target_parent,
            values=values,
            command=command,
            fg_color=COLOR_SURFACE,
            button_color=COLOR_BORDER,
            button_hover_color=COLOR_ACCENT,
            text_color=COLOR_TEXT,
            font=FONT_MAIN,
            dropdown_fg_color=COLOR_SURFACE,
            dropdown_hover_color=COLOR_NAV_HOVER_BG,
            dropdown_text_color=COLOR_TEXT,
            corner_radius=8,
            height=28,
            width=180
        )

    def _add_option_row(self, label_text, values, command):
        """鍓靛缓甯舵绫ょ殑琛屽収 OptionMenu"""
        frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        frame.pack(fill="x", pady=5)
        
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=0)
        
        # Label
        ctk.CTkLabel(frame, text=t(label_text), font=FONT_MAIN, text_color=COLOR_TEXT).grid(row=0, column=0, sticky="w", padx=(0, 10))
        
        # OptionMenu (Parent is row frame)
        menu = self._add_option_menu(values, command, parent=frame)
        menu.grid(row=0, column=1, sticky="e")
        return menu

    def _add_text_button(self, parent, text, command):
        return ctk.CTkButton(
            parent,
            text=t(text),
            font=("Consolas", 10, "bold"),
            text_color=COLOR_TEXT,
            fg_color=COLOR_SURFACE,
            border_width=1,
            border_color=COLOR_BORDER,
            hover_color=COLOR_NAV_HOVER_BG,
            height=28,
            corner_radius=8,
            command=command
        )

    def _add_hardware_action_button(self, parent, text, command):
        """Hardware API action button / 給 Hardware API 使用的 accent button"""
        return ctk.CTkButton(
            parent,
            text=t(text),
            font=("Consolas", 10, "bold"),
            text_color=COLOR_HARDWARE_BUTTON_TEXT,
            fg_color=COLOR_HARDWARE_BUTTON_BG,
            border_width=1,
            border_color=COLOR_HARDWARE_INPUT_BORDER,
            hover_color=COLOR_HARDWARE_BUTTON_HOVER,
            height=28,
            corner_radius=8,
            command=command,
        )

    def _add_hardware_option_menu(self, values, command, parent=None):
        """Hardware API option menu / 強調色更明顯的下拉選單"""
        target_parent = parent if parent else self.content_frame
        return ctk.CTkOptionMenu(
            target_parent,
            values=values,
            command=command,
            fg_color=COLOR_HARDWARE_INPUT_BG,
            button_color=COLOR_HARDWARE_INPUT_BORDER,
            button_hover_color=COLOR_HARDWARE_INPUT_HOVER,
            text_color=COLOR_HARDWARE_BUTTON_TEXT,
            font=FONT_MAIN,
            dropdown_fg_color=COLOR_HARDWARE_DROPDOWN_BG,
            dropdown_hover_color=COLOR_HARDWARE_BUTTON_HOVER,
            dropdown_text_color=COLOR_HARDWARE_BUTTON_TEXT,
            corner_radius=8,
            height=28,
            width=180,
        )

    def _create_hardware_entry(self, parent, width=170):
        """Hardware API entry / 深色底加 accent border 的輸入框"""
        return ctk.CTkEntry(
            parent,
            fg_color=COLOR_HARDWARE_INPUT_BG,
            border_width=1,
            border_color=COLOR_HARDWARE_INPUT_BORDER,
            text_color=COLOR_HARDWARE_BUTTON_TEXT,
            width=width,
            corner_radius=8,
        )

    # --- 閭忚集鍔熻兘 ---

    def start_move(self, event):
        self._x = event.x
        self._y = event.y

    def do_move(self, event):
        if self._is_maximized:
            return
        x = self.winfo_pointerx() - self._x
        y = self.winfo_pointery() - self._y
        self.geometry(f"+{x}+{y}")

    def _on_window_map(self, event=None):
        """React to the TOPLEVEL being mapped, never to a child's <Map>.

        Tk puts the toplevel path into the bindtags of every descendant, so
        without this guard every rebuilt widget called ``overrideredirect`` — the
        event storm that made tab/mode switches stutter (plan RC-2).
        """
        if event is not None and getattr(event, "widget", None) is not self:
            return
        if getattr(self, "_ui_rebuilding", False) or getattr(self, "_closing", False):
            return
        try:
            state = self.state()
        except Exception:
            return
        if state != "normal":
            return
        self._sync_window_style()
        if getattr(self, "_minimized", False):
            self._minimized = False
            self.after(0, self._restore_window)

    def _sync_window_style(self, force=False):
        """Apply APPWINDOW + frame refresh, keyed by an idempotent signature.

        Replaces ``_ensure_taskbar_icon``: no ``withdraw``/``deiconify``/``alpha``
        trick, so restoring never blinks, never steals focus and never emits
        another <Map> burst.
        """
        if not win32_window.is_available():
            return
        if getattr(self, "_ui_rebuilding", False) and not force:
            return
        try:
            hwnd = win32_window.root_hwnd(self)
            if not hwnd:
                return
            exstyle = win32_window.apply_appwindow(hwnd)
            signature = (hwnd, exstyle)
            if not force and signature == getattr(self, "_window_style_sig", None):
                return
            win32_window.refresh_frame(hwnd)
            self._window_style_sig = signature
            self._taskbar_style_applied = True
        except Exception as exc:
            log_print(f"[UI] window style sync failed: {exc}")

    def _ensure_taskbar_icon(self):
        """Backwards-compatible shim. All real work is ``_sync_window_style``."""
        self._sync_window_style(force=True)

    def _on_minimize(self):
        """Thu nhỏ thật qua Win32 — KHÔNG đụng overrideredirect.

        Toggling ``overrideredirect`` while minimised was what destroyed
        ``WS_EX_APPWINDOW`` and left the tool with no taskbar button (L1/L2).
        ``ui_minimize_to_tray`` switches the button to "hide + tray" instead.
        """
        if getattr(self, "_closing", False):
            return
        if bool(getattr(config, "ui_minimize_to_tray", False)):
            self._hide_window()
            return
        if win32_window.is_available():
            try:
                hwnd = win32_window.root_hwnd(self)
                if hwnd and win32_window.minimize(hwnd):
                    self._minimized = True
                    self.after(300, self._verify_minimized)
                    return
            except Exception as exc:
                log_print(f"[UI] Win32 minimize failed: {exc}")
        # Fallback for non-Windows / a refused ShowWindow: the hotkey and tray
        # are still two working ways back to the window.
        try:
            self.iconify()
        except Exception:
            pass
        self._minimized = True
        self.after(300, self._verify_minimized)

    def _verify_minimized(self):
        """If ShowWindow did not take effect, at least tell the user the hotkey."""
        if not getattr(self, "_minimized", False) or getattr(self, "_closing", False):
            return
        try:
            if self.state() == "iconic" or win32_window.is_iconic(win32_window.root_hwnd(self)):
                return
        except Exception:
            pass
        hotkey = str(getattr(config, "ui_toggle_hotkey", "Insert") or "Insert")
        self._set_status_indicator(f"Status: Minimized ({hotkey} to show)", COLOR_TEXT_DIM)

    def _hide_window(self):
        """Hide to tray/hotkey only: widgets are kept, so showing is instant."""
        if getattr(self, "_ui_hidden", False) or getattr(self, "_closing", False):
            return
        self._ui_hidden = True
        self._save_mode_geometry()
        try:
            self.withdraw()
        except Exception:
            pass
        if self._launcher is not None:
            try:
                self._launcher.set_tray_menu_state(True, self._ui_mode)
            except Exception:
                pass
        log_print("[UI] Hidden - press the toggle hotkey or use the tray to show")

    def _show_window(self):
        if getattr(self, "_closing", False):
            return
        self._restore_window()

    def _restore_window(self):
        """deiconify + Win32 restore + style re-apply + foreground."""
        if getattr(self, "_closing", False):
            return
        try:
            self.deiconify()
        except Exception:
            pass
        if win32_window.is_available():
            try:
                hwnd = win32_window.root_hwnd(self)
                if hwnd:
                    win32_window.show(hwnd)
                    win32_window.restore(hwnd)
                    win32_window.bring_to_front(hwnd)
                    self.after(120, lambda: win32_window.set_not_topmost(hwnd))
            except Exception as exc:
                log_print(f"[UI] Win32 restore failed: {exc}")
        self._minimized = False
        self._ui_hidden = False
        if not self._is_maximized:
            try:
                self.overrideredirect(True)
            except Exception:
                pass
        try:
            self.update_idletasks()
        except Exception:
            pass
        self._sync_window_style(force=True)
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass
        self._reset_tick_timers()
        if self._launcher is not None:
            try:
                self._launcher.set_tray_menu_state(False, self._ui_mode)
            except Exception:
                pass

    def _toggle_ui_visibility(self):
        """Hotkey/tray entry point. Debounced against auto-repeat and double taps."""
        if getattr(self, "_closing", False):
            return
        now = time.monotonic()
        if now - float(getattr(self, "_last_toggle_time", 0.0)) < 0.25:
            return
        self._last_toggle_time = now
        try:
            state = self.state()
        except Exception:
            state = "normal"
        if getattr(self, "_ui_hidden", False) or getattr(self, "_minimized", False) or state in (
            "iconic",
            "withdrawn",
        ):
            self._show_window()
        else:
            self._hide_window()

    def _toggle_maximize(self):
        if self._simple_mode:
            return
        if self._is_maximized:
            if self._restore_geometry:
                self.geometry(self._restore_geometry)
            self._is_maximized = False
            return

        self._restore_geometry = str(self.geometry())
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        self.geometry(f"{screen_w}x{screen_h}+0+0")
        self._is_maximized = True

    def _register_slider(self, key, slider, entry, vmin, vmax, is_float):
        self._slider_widgets[key] = {"slider": slider, "entry": entry, "min": vmin, "max": vmax, "is_float": is_float}

    def _set_slider_value(self, key, value):
        if key not in self._slider_widgets: return
        w = self._slider_widgets[key]
        is_float = w["is_float"]
        try:
            v = float(value) if is_float else int(round(float(value)))
        except: return
        v = max(w["min"], min(v, w["max"]))
        try:
            w["slider"].set(v)
        except Exception:
            self._slider_widgets.pop(key, None)
            return
        # The Simple rows are value-display-only (``entry`` is None): the slider
        # itself renders the number, so there is no textbox to refresh.
        entry = w.get("entry")
        if entry is None:
            return
        try:
            entry.delete(0, "end")
            entry.insert(0, f"{v:.2f}" if is_float else f"{v}")
        except Exception:
            pass

    def _set_checkbox_value(self, key, value_bool):
        var = self._checkbox_vars.get(key)
        if var: var.set(bool(value_bool))

    def _set_option_value(self, key, value_str):
        menu = self._option_widgets.get(key)
        if not menu or value_str is None:
            return
        try:
            if hasattr(menu, "winfo_exists") and not bool(menu.winfo_exists()):
                self._option_widgets.pop(key, None)
                return
            menu.set(str(value_str))
        except Exception:
            # Widget was likely destroyed while switching tabs.
            self._option_widgets.pop(key, None)

    def _set_btn_option_value(self, key, value_str):
        self._set_option_value(key, value_str)

    def _add_ads_fov_controls_in_frame(self, parent, is_sec=False):
        if is_sec:
            enabled_key = "ads_fov_enabled_sec"
            slider_key = "ads_fovsize_sec"
            fallback_fov = getattr(config, "fovsize_sec", 150)
            callback_enabled = self._on_ads_fov_enabled_sec_changed
            callback_slider = self._on_ads_fovsize_sec_changed
        else:
            enabled_key = "ads_fov_enabled"
            slider_key = "ads_fovsize"
            fallback_fov = getattr(config, "fovsize", 300)
            callback_enabled = self._on_ads_fov_enabled_changed
            callback_slider = self._on_ads_fovsize_changed

        var = tk.BooleanVar(value=bool(getattr(config, enabled_key, False)))
        if is_sec:
            self.var_ads_fov_enabled_sec = var
        else:
            self.var_ads_fov_enabled = var

        self._add_switch_in_frame(parent, "Enable ADS FOV", var, callback_enabled)
        self._checkbox_vars[enabled_key] = var

        if var.get():
            self._add_slider_in_frame(
                parent,
                "ADS FOV Size",
                slider_key,
                1,
                1000,
                float(getattr(config, slider_key, fallback_fov)),
                callback_slider,
            )

    def _add_trigger_ads_fov_controls_in_frame(self, parent):
        enabled_key = "trigger_ads_fov_enabled"
        slider_key = "trigger_ads_fovsize"
        fallback_fov = getattr(config, "tbfovsize", 70)

        self.var_trigger_ads_fov_enabled = tk.BooleanVar(
            value=bool(getattr(config, enabled_key, False))
        )
        self._add_switch_in_frame(
            parent,
            "Enable Trigger ADS FOV",
            self.var_trigger_ads_fov_enabled,
            self._on_trigger_ads_fov_enabled_changed,
        )
        self._checkbox_vars[enabled_key] = self.var_trigger_ads_fov_enabled

        if self.var_trigger_ads_fov_enabled.get():
            self._add_slider_in_frame(
                parent,
                "Trigger ADS FOV Size",
                slider_key,
                1,
                300,
                float(getattr(config, slider_key, fallback_fov)),
                self._on_trigger_ads_fovsize_changed,
            )

    def _add_pid_preview_section(self, is_sec=False):
        state_key = "pid_preview_sec" if is_sec else "pid_preview_main"
        sec_preview = self._create_collapsible_section(
            self.content_frame,
            "PID Preview",
            initially_open=True,
            state_key=state_key,
        )

        ctk.CTkLabel(
            sec_preview,
            text="Simulated response preview (average X/Y speed, single-axis model)",
            font=("Roboto", 10),
            text_color=COLOR_TEXT_DIM,
        ).pack(anchor="w", pady=(2, 6))

        canvas = tk.Canvas(
            sec_preview,
            height=180,
            bg=COLOR_BG,
            bd=0,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            highlightcolor=COLOR_BORDER,
        )
        canvas.pack(fill="x", pady=(0, 6))

        info_label = ctk.CTkLabel(
            sec_preview,
            text="",
            font=("Roboto", 10),
            text_color=COLOR_TEXT_DIM,
            anchor="w",
            justify="left",
        )
        info_label.pack(fill="x")

        if is_sec:
            self._pid_preview_canvas_sec = canvas
            self._pid_preview_info_sec = info_label
        else:
            self._pid_preview_canvas_main = canvas
            self._pid_preview_info_main = info_label

        canvas.bind("<Configure>", lambda _event, sec=is_sec: self._refresh_pid_preview(is_sec=sec))
        self.after(20, lambda sec=is_sec: self._refresh_pid_preview(is_sec=sec))

    def _get_pid_preview_widgets(self, is_sec=False):
        if is_sec:
            return getattr(self, "_pid_preview_canvas_sec", None), getattr(self, "_pid_preview_info_sec", None)
        return getattr(self, "_pid_preview_canvas_main", None), getattr(self, "_pid_preview_info_main", None)

    def _simulate_pid_preview(self, is_sec=False, steps=72):
        if is_sec:
            kp_default = float(getattr(config, "pid_kp_sec", 3.7))
            kp_min = float(getattr(config, "pid_kp_min_sec", kp_default))
            kp_max = float(getattr(config, "pid_kp_max_sec", kp_default))
            ki = float(getattr(config, "pid_ki_sec", 24.0))
            kd = float(getattr(config, "pid_kd_sec", 0.11))
            max_output = float(getattr(config, "pid_max_output_sec", 50.0))
            x_speed = float(getattr(config, "pid_x_speed_sec", 1.0))
            y_speed = float(getattr(config, "pid_y_speed_sec", 1.0))
            fov = float(getattr(config, "fovsize_sec", 150.0))
        else:
            kp_default = float(getattr(config, "pid_kp", 3.7))
            kp_min = float(getattr(config, "pid_kp_min", kp_default))
            kp_max = float(getattr(config, "pid_kp_max", kp_default))
            ki = float(getattr(config, "pid_ki", 24.0))
            kd = float(getattr(config, "pid_kd", 0.11))
            max_output = float(getattr(config, "pid_max_output", 50.0))
            x_speed = float(getattr(config, "pid_x_speed", 1.0))
            y_speed = float(getattr(config, "pid_y_speed", 1.0))
            fov = float(getattr(config, "fovsize", 100.0))

        if kp_min > kp_max:
            kp_min, kp_max = kp_max, kp_min

        fov = max(1.0, fov)
        max_output = max(0.1, abs(max_output))
        avg_speed = max(0.1, (x_speed + y_speed) / 2.0)
        target_fps = float(getattr(config, "target_fps", 200) or 200)
        dt = 1.0 / max(1.0, target_fps)
        plant_gain = max(0.06, min(0.35, 14.0 / max(14.0, fov)))
        err = max(8.0, min(fov * 0.6, 220.0))
        prev_err = err
        integral = 0.0

        integral_limit = None
        if abs(ki) > 1e-6:
            integral_limit = max_output / abs(ki)

        error_series = []
        output_series = []
        for idx in range(max(2, int(steps))):
            distance_factor = min(abs(err) / fov, 1.0)
            kp_dynamic = kp_min + (kp_max - kp_min) * distance_factor

            derivative = 0.0
            if idx > 0 and dt > 1e-6:
                integral += err * dt
                if integral_limit is not None:
                    integral = max(-integral_limit, min(integral_limit, integral))
                derivative = (err - prev_err) / dt

            output = (kp_dynamic * err) + (ki * integral) + (kd * derivative)
            output *= avg_speed
            output = max(-max_output, min(max_output, output))

            prev_err = err
            err = err - (output * plant_gain)
            err = max(-fov * 1.2, min(fov * 1.2, err))

            error_series.append(err)
            output_series.append(output)

        return {
            "error_series": error_series,
            "output_series": output_series,
            "start_error": max(8.0, min(fov * 0.6, 220.0)),
            "fov": fov,
            "target_fps": target_fps,
            "max_output": max_output,
        }

    def _find_pid_settle_frame(self, series, tolerance):
        if not series:
            return None
        window = 8
        for idx, _ in enumerate(series):
            chunk = series[idx:idx + window]
            if len(chunk) < window:
                break
            if all(abs(v) <= tolerance for v in chunk):
                return idx + 1
        return None

    def _refresh_pid_preview(self, is_sec=False):
        canvas, info_label = self._get_pid_preview_widgets(is_sec=is_sec)
        if canvas is None or info_label is None:
            return
        try:
            if not bool(canvas.winfo_exists()) or not bool(info_label.winfo_exists()):
                return
        except Exception:
            return

        data = self._simulate_pid_preview(is_sec=is_sec)
        error_series = data["error_series"]
        output_series = data["output_series"]
        if not error_series or not output_series:
            return

        canvas.delete("all")
        width = int(canvas.winfo_width())
        height = int(canvas.winfo_height())
        if width <= 2:
            width = int(float(canvas.cget("width")))
        if height <= 2:
            height = int(float(canvas.cget("height")))

        left = 36
        right = max(left + 20, width - 10)
        top = 16
        bottom = max(top + 20, height - 24)
        center_y = (top + bottom) / 2.0
        plot_height = max(8.0, (bottom - top) / 2.0)
        max_abs = max(
            1.0,
            max(abs(v) for v in error_series),
            max(abs(v) for v in output_series),
        )
        y_scale = plot_height / (max_abs * 1.1)
        x_span = max(1, len(error_series) - 1)

        canvas.create_rectangle(left, top, right, bottom, outline=COLOR_BORDER, width=1)
        canvas.create_line(left, center_y, right, center_y, fill=COLOR_BORDER, width=1, dash=(2, 2))

        for ratio in (-0.5, 0.5):
            y = center_y - (ratio * plot_height * 2.0)
            canvas.create_line(left, y, right, y, fill=COLOR_BORDER, width=1, dash=(2, 4))

        def _series_points(series):
            pts = []
            for idx, value in enumerate(series):
                x = left + ((right - left) * (idx / x_span))
                y = center_y - (value * y_scale)
                pts.extend((x, y))
            return pts

        canvas.create_line(_series_points(error_series), fill="#5EE173", width=2, smooth=True)
        canvas.create_line(_series_points(output_series), fill=COLOR_ACCENT, width=2, smooth=True)
        canvas.create_text(left + 6, top + 8, text="Error", fill="#5EE173", anchor="w", font=("Consolas", 9))
        canvas.create_text(left + 58, top + 8, text="Output", fill=COLOR_ACCENT, anchor="w", font=("Consolas", 9))
        canvas.create_text(left - 6, top + 2, text="+", fill=COLOR_TEXT_DIM, anchor="e", font=("Consolas", 9))
        canvas.create_text(left - 6, center_y, text="0", fill=COLOR_TEXT_DIM, anchor="e", font=("Consolas", 9))
        canvas.create_text(left - 6, bottom - 2, text="-", fill=COLOR_TEXT_DIM, anchor="e", font=("Consolas", 9))

        tolerance = max(1.0, data["fov"] * 0.03)
        settle_frame = self._find_pid_settle_frame(error_series, tolerance=tolerance)
        settle_text = f"{settle_frame} frames" if settle_frame is not None else "Not settled"
        info_label.configure(
            text=(
                f"Start Error: {data['start_error']:.1f}px | End Error: {error_series[-1]:.1f}px | "
                f"Peak Output: {max(abs(v) for v in output_series):.1f} | Settle: {settle_text} | "
                f"FPS: {data['target_fps']:.0f}"
            )
        )

    def _refresh_pid_preview_if_pid_mode(self, is_sec=False):
        mode_key = "mode_sec" if is_sec else "mode"
        mode_value = self._aim_mode_display_to_value(getattr(config, mode_key, "Normal"))
        if mode_value == "PID":
            self._refresh_pid_preview(is_sec=is_sec)

    def _ads_binding_to_display(self, binding_value):
        if binding_value is None:
            return "Right Mouse Button"
        try:
            idx = int(binding_value)
            if idx in BUTTONS:
                return BUTTONS[idx]
        except Exception:
            pass
        raw = str(binding_value).strip()
        if not raw:
            return "Right Mouse Button"
        if raw in BUTTON_NAME_TO_IDX:
            return raw
        if raw.isdigit():
            idx = int(raw)
            if idx in BUTTONS:
                return BUTTONS[idx]
        if raw in ADS_KEY_DISPLAY_TO_BINDING:
            return raw
        token = raw.upper()
        pretty_map = {
            "SPACE": "Space",
            "TAB": "Tab",
            "ENTER": "Enter",
            "ESCAPE": "Esc",
            "LSHIFT": "Left Shift",
            "RSHIFT": "Right Shift",
            "LCONTROL": "Left Ctrl",
            "RCONTROL": "Right Ctrl",
            "LMENU": "Left Alt",
            "RMENU": "Right Alt",
            "UP": "Up Arrow",
            "DOWN": "Down Arrow",
            "LEFT": "Left Arrow",
            "RIGHT": "Right Arrow",
        }
        if token in ADS_KEY_BINDING_TO_DISPLAY:
            return ADS_KEY_BINDING_TO_DISPLAY[token]
        if token in pretty_map:
            return pretty_map[token]
        if len(token) == 1 and token.isalnum():
            return token
        if token.startswith("F") and token[1:].isdigit():
            return token
        return raw

    def _ads_display_to_binding(self, display_value):
        return ADS_KEY_DISPLAY_TO_BINDING.get(str(display_value), "Right Mouse Button")

    def _set_bind_button_text(self, button, text):
        try:
            if button is not None and hasattr(button, "winfo_exists") and bool(button.winfo_exists()):
                button.configure(text=str(text))
        except Exception:
            pass

    def _cancel_binding_capture(self):
        ctx = getattr(self, "_binding_capture_ctx", None)
        if not isinstance(ctx, dict):
            self._binding_capture_ctx = None
            return
        button = ctx.get("button")
        self._set_bind_button_text(button, ctx.get("restore_text", "Set"))
        self._binding_capture_ctx = None

    def _is_binding_pressed_by_backend(self, binding):
        try:
            from src.utils import mouse as mouse_backend
        except Exception:
            mouse_backend = None

        mouse_idx = BUTTON_NAME_TO_IDX.get(str(binding), None)
        try:
            if mouse_backend is not None and mouse_idx is not None:
                return bool(mouse_backend.is_button_pressed(int(mouse_idx)))
            if mouse_backend is not None and mouse_idx is None:
                return bool(mouse_backend.is_key_pressed(binding))
        except Exception:
            pass
        return self._is_binding_pressed_locally(binding)

    def _is_binding_pressed_locally(self, binding):
        if USER32 is None:
            return False

        mouse_idx = BUTTON_NAME_TO_IDX.get(str(binding), None)
        if mouse_idx is not None:
            vk = BUTTON_IDX_TO_VK.get(int(mouse_idx))
            if vk is None:
                return False
            try:
                return bool(USER32.GetAsyncKeyState(int(vk)) & 0x8000)
            except Exception:
                return False

        vk = to_vk_code(binding)
        if vk is None:
            return False
        try:
            return bool(USER32.GetAsyncKeyState(int(vk)) & 0x8000)
        except Exception:
            return False

    def _is_input_backend_connected(self):
        try:
            from src.utils import mouse as mouse_backend

            return bool(getattr(mouse_backend, "is_connected", False))
        except Exception:
            return False

    def _get_binding_capture_candidates(self):
        keyboard_enabled = bool(getattr(config, "keyboard_api_enabled", False))
        mode = getattr(config, "keyboard_api", "Follow Mouse API")
        keyboard_supported = bool(keyboard_enabled and (self._supports_keyboard_state(mode) or USER32 is not None))

        # Keep deterministic order: mouse first, then keyboard.
        candidates = list(BUTTONS.values())
        if keyboard_supported:
            for _, binding in ADS_KEY_DISPLAY_TO_BINDING.items():
                if binding not in candidates:
                    candidates.append(binding)
            for binding in BIND_CAPTURE_KEY_TOKENS:
                if binding not in candidates:
                    candidates.append(binding)
        return candidates, keyboard_supported

    def _normalize_aim_binding_for_config(self, binding):
        if binding is None:
            return 3
        idx = BUTTON_NAME_TO_IDX.get(str(binding), None)
        if idx is not None:
            return int(idx)
        try:
            parsed = int(binding)
            if parsed in BUTTONS:
                return int(parsed)
        except Exception:
            pass
        return str(binding)

    def _aim_mode_display_to_value(self, value):
        raw = str(value or "").strip()
        if not raw:
            return "Normal"
        mapped = AIM_MODE_DISPLAY_TO_VALUE.get(raw)
        if mapped:
            return mapped
        lowered = raw.lower()
        if lowered == "pid":
            return "PID"
        if lowered in {"pid controller", "pid controller (risk)", "pid controller ( risk )"}:
            return "PID"
        canonical = {
            "normal": "Normal",
            "flick": "Flick",
            "silent": "Silent",
            "ncaf": "NCAF",
            "windmouse": "WindMouse",
            "bezier": "Bezier",
        }
        return canonical.get(lowered, "Normal")

    def _aim_mode_value_to_display(self, value):
        canonical = self._aim_mode_display_to_value(value)
        return AIM_MODE_VALUE_TO_DISPLAY.get(canonical, "Normal")

    def _start_aim_key_capture(self, is_sec=False):
        config_key = "selected_mouse_button_sec" if is_sec else "selected_mouse_button"
        tracker_key = "selected_mouse_button_sec" if is_sec else "selected_mouse_button"
        button = getattr(self, "aim_key_bind_button_sec" if is_sec else "aim_key_bind_button", None)
        if button is None:
            return

        self._cancel_binding_capture()

        candidates, keyboard_supported = self._get_binding_capture_candidates()
        if not keyboard_supported:
            self._log_config("Current Input API does not expose keyboard state; capture supports mouse buttons only.")
        if not self._is_input_backend_connected():
            self._log_config("Input API is not connected; key capture may timeout.")

        prev_states = {binding: bool(self._is_binding_pressed_by_backend(binding)) for binding in candidates}
        restore_binding = getattr(config, config_key, 2 if is_sec else 3)
        restore_text = self._ads_binding_to_display(restore_binding)

        ctx = {
            "id": int(getattr(self, "_binding_capture_id", 0)) + 1,
            "config_key": config_key,
            "tracker_key": tracker_key,
            "binding_kind": "aim",
            "log_label": "Sec Aim Key" if is_sec else "Aim Key",
            "button": button,
            "restore_text": restore_text,
            "candidates": candidates,
            "prev_states": prev_states,
            "started_at": time.monotonic(),
            "arm_at": time.monotonic() + 0.35,
            "timeout_sec": 10.0,
        }
        self._binding_capture_id = ctx["id"]
        self._binding_capture_ctx = ctx
        self._set_bind_button_text(button, "Press key...")
        self.after(30, lambda capture_id=ctx["id"]: self._poll_binding_capture(capture_id))

    def _start_trigger_key_capture(self):
        config_key = "selected_tb_btn"
        tracker_key = "selected_tb_btn"
        button = getattr(self, "tb_key_bind_button", None)
        if button is None:
            return

        self._cancel_binding_capture()

        candidates, keyboard_supported = self._get_binding_capture_candidates()
        if not keyboard_supported:
            self._log_config("Current Input API does not expose keyboard state; capture supports mouse buttons only.")
        if not self._is_input_backend_connected():
            self._log_config("Input API is not connected; key capture may timeout.")

        prev_states = {binding: bool(self._is_binding_pressed_by_backend(binding)) for binding in candidates}
        restore_binding = getattr(config, config_key, 3)
        restore_text = self._ads_binding_to_display(restore_binding)

        ctx = {
            "id": int(getattr(self, "_binding_capture_id", 0)) + 1,
            "config_key": config_key,
            "tracker_key": tracker_key,
            "binding_kind": "trigger",
            "log_label": "Trigger Key",
            "button": button,
            "restore_text": restore_text,
            "candidates": candidates,
            "prev_states": prev_states,
            "started_at": time.monotonic(),
            "arm_at": time.monotonic() + 0.35,
            "timeout_sec": 10.0,
        }
        self._binding_capture_id = ctx["id"]
        self._binding_capture_ctx = ctx
        self._set_bind_button_text(button, "Press key...")
        self.after(30, lambda capture_id=ctx["id"]: self._poll_binding_capture(capture_id))

    def _start_ads_key_capture(self, is_sec=False):
        key_name = "ads_key_sec" if is_sec else "ads_key"
        tracker_attr = "ads_key_sec" if is_sec else "ads_key"
        button = getattr(self, "ads_key_bind_button_sec" if is_sec else "ads_key_bind_button", None)
        if button is None:
            return

        self._cancel_binding_capture()

        candidates, keyboard_supported = self._get_binding_capture_candidates()
        if not keyboard_supported:
            self._log_config("Current Input API does not expose keyboard state; capture supports mouse buttons only.")
        if not self._is_input_backend_connected():
            self._log_config("Input API is not connected; key capture may timeout.")

        prev_states = {binding: bool(self._is_binding_pressed_by_backend(binding)) for binding in candidates}
        restore_binding = getattr(config, key_name, "Right Mouse Button")
        restore_text = self._ads_binding_to_display(restore_binding)

        ctx = {
            "id": int(getattr(self, "_binding_capture_id", 0)) + 1,
            "config_key": key_name,
            "tracker_key": tracker_attr,
            "binding_kind": "ads",
            "log_label": "Sec ADS Key" if is_sec else "ADS Key",
            "button": button,
            "restore_text": restore_text,
            "candidates": candidates,
            "prev_states": prev_states,
            "started_at": time.monotonic(),
            "arm_at": time.monotonic() + 0.35,
            "timeout_sec": 10.0,
        }
        self._binding_capture_id = ctx["id"]
        self._binding_capture_ctx = ctx
        self._set_bind_button_text(button, "Press key...")
        self.after(30, lambda capture_id=ctx["id"]: self._poll_binding_capture(capture_id))

    def _start_trigger_ads_key_capture(self):
        config_key = "trigger_ads_key"
        tracker_key = "trigger_ads_key"
        button = getattr(self, "trigger_ads_key_bind_button", None)
        if button is None:
            return

        self._cancel_binding_capture()

        candidates, keyboard_supported = self._get_binding_capture_candidates()
        if not keyboard_supported:
            self._log_config("Current Input API does not expose keyboard state; capture supports mouse buttons only.")
        if not self._is_input_backend_connected():
            self._log_config("Input API is not connected; key capture may timeout.")

        prev_states = {binding: bool(self._is_binding_pressed_by_backend(binding)) for binding in candidates}
        restore_binding = getattr(config, config_key, "Right Mouse Button")
        restore_text = self._ads_binding_to_display(restore_binding)

        ctx = {
            "id": int(getattr(self, "_binding_capture_id", 0)) + 1,
            "config_key": config_key,
            "tracker_key": tracker_key,
            "binding_kind": "trigger_ads",
            "log_label": "Trigger ADS Key",
            "button": button,
            "restore_text": restore_text,
            "candidates": candidates,
            "prev_states": prev_states,
            "started_at": time.monotonic(),
            "arm_at": time.monotonic() + 0.35,
            "timeout_sec": 10.0,
        }
        self._binding_capture_id = ctx["id"]
        self._binding_capture_ctx = ctx
        self._set_bind_button_text(button, "Press key...")
        self.after(30, lambda capture_id=ctx["id"]: self._poll_binding_capture(capture_id))

    def _start_rcs_key_capture(self):
        config_key = "rcs_keybind"
        button = getattr(self, "rcs_key_bind_button", None)
        if button is None:
            return

        self._cancel_binding_capture()

        candidates, keyboard_supported = self._get_binding_capture_candidates()
        if not keyboard_supported:
            self._log_config("Current Input API does not expose keyboard state; capture supports mouse buttons only.")

        prev_states = {binding: bool(self._is_binding_pressed_by_backend(binding)) for binding in candidates}
        restore_binding = getattr(config, config_key, 0)
        restore_text = self._ads_binding_to_display(restore_binding)

        ctx = {
            "id": int(getattr(self, "_binding_capture_id", 0)) + 1,
            "config_key": config_key,
            "tracker_key": None,
            "binding_kind": "aim",
            "log_label": "RCS Key",
            "button": button,
            "restore_text": restore_text,
            "candidates": candidates,
            "prev_states": prev_states,
            "started_at": time.monotonic(),
            "arm_at": time.monotonic() + 0.35,
            "timeout_sec": 10.0,
        }
        self._binding_capture_id = ctx["id"]
        self._binding_capture_ctx = ctx
        self._set_bind_button_text(button, "Press key...")
        self.after(30, lambda capture_id=ctx["id"]: self._poll_binding_capture(capture_id))

    def _start_magnet_key_capture(self):
        config_key = "magnet_keybind"
        button = getattr(self, "magnet_key_bind_button", None)
        if button is None:
            return

        self._cancel_binding_capture()

        candidates, keyboard_supported = self._get_binding_capture_candidates()
        if not keyboard_supported:
            self._log_config("Current Input API does not expose keyboard state; capture supports mouse buttons only.")

        prev_states = {binding: bool(self._is_binding_pressed_by_backend(binding)) for binding in candidates}
        restore_binding = getattr(config, config_key, 0)
        restore_text = self._ads_binding_to_display(restore_binding)

        ctx = {
            "id": int(getattr(self, "_binding_capture_id", 0)) + 1,
            "config_key": config_key,
            "tracker_key": None,
            "binding_kind": "aim",
            "log_label": "Magnet Key",
            "button": button,
            "restore_text": restore_text,
            "candidates": candidates,
            "prev_states": prev_states,
            "started_at": time.monotonic(),
            "arm_at": time.monotonic() + 0.35,
            "timeout_sec": 10.0,
        }
        self._binding_capture_id = ctx["id"]
        self._binding_capture_ctx = ctx
        self._set_bind_button_text(button, "Press key...")
        self.after(30, lambda capture_id=ctx["id"]: self._poll_binding_capture(capture_id))

    def _poll_binding_capture(self, capture_id):
        ctx = getattr(self, "_binding_capture_ctx", None)
        if not isinstance(ctx, dict):
            return
        if int(ctx.get("id", -1)) != int(capture_id):
            return

        now = time.monotonic()
        if now - float(ctx.get("started_at", now)) > float(ctx.get("timeout_sec", 10.0)):
            self._set_bind_button_text(ctx.get("button"), ctx.get("restore_text", "Set"))
            self._binding_capture_ctx = None
            label = str(ctx.get("log_label", "Key")).strip()
            self._log_config(f"{label} capture timed out.")
            return

        candidates = list(ctx.get("candidates", []))
        prev_states = dict(ctx.get("prev_states", {}))
        selected_binding = None
        for binding in candidates:
            current_pressed = bool(self._is_binding_pressed_by_backend(binding))
            prev_pressed = bool(prev_states.get(binding, False))
            if now >= float(ctx.get("arm_at", now)) and current_pressed and not prev_pressed:
                selected_binding = binding
                prev_states[binding] = current_pressed
                break
            prev_states[binding] = current_pressed
        ctx["prev_states"] = prev_states

        if selected_binding is not None:
            config_key = str(ctx.get("config_key", "ads_key"))
            tracker_key = ctx.get("tracker_key")
            binding_kind = str(ctx.get("binding_kind", "ads")).strip().lower()
            if binding_kind in {"aim", "trigger"}:
                stored_value = self._normalize_aim_binding_for_config(selected_binding)
            else:
                stored_value = selected_binding

            setattr(config, config_key, stored_value)
            if tracker_key and hasattr(self, "tracker"):
                setattr(self.tracker, tracker_key, stored_value)

            display_name = self._ads_binding_to_display(stored_value)
            self._set_bind_button_text(ctx.get("button"), display_name)
            label = str(ctx.get("log_label", "Key")).strip()
            self._log_config(f"{label}: {display_name}")
            self._binding_capture_ctx = None
            return

        self._binding_capture_ctx = ctx
        self.after(30, lambda: self._poll_binding_capture(capture_id))

    def _get_current_settings(self):
        """鐛插彇鐣跺墠鎵€鏈夎ō缃?- 鐩存帴浣跨敤 config.to_dict() 纰轰繚涓€鑷存€?"""
        return config.to_dict()

    def _load_initial_config(self):
        """鍒濆鍖栨檪杓夊叆閰嶇疆涓︽噳鐢ㄥ埌鎵€鏈?UI 鍏冪礌"""
        try:
            # 閰嶇疆宸茬稉鍦?config.py 鐨?__init__ 涓嚜鍕曡級鍏ヤ簡
            # 鐝惧湪闇€瑕佸皣閰嶇疆鍚屾鍒?tracker 鍜?UI
            self._sync_config_to_tracker()
            
            # 閲嶆柊椤ず鐣跺墠闋侀潰浠ユ洿鏂?UI 鍏冪礌
            # 閫欐渻纰轰繚鎵€鏈?slider銆乧heckbox銆乷ption menu 閮介’绀烘纰虹殑鍊?
            if self._simple_mode:
                self.refresh_simple_dashboard()
                log_print("[UI] Configuration loaded (Simple mode)")
                return
            elif self._legacy_ui_mode:
                self._handle_nav_click("General", self._show_general_tab)
            else:
                self._handle_nav_click("Combat", self._show_aimbot_tab)
            
            log_print("[UI] Configuration loaded")
        except Exception as e:
            log_print(f"[UI] Init load error: {e}")
    
    def _sync_config_to_tracker(self):
        """灏?config 涓殑鍊煎悓姝ュ埌 tracker"""
        try:
            # 鍚屾鎵€鏈夊弮鏁?
            self.tracker.normal_x_speed = config.normal_x_speed
            self.tracker.normal_y_speed = config.normal_y_speed
            self.tracker.normalsmooth = config.normalsmooth
            self.tracker.normalsmoothfov = config.normalsmoothfov
            self.tracker.mouse_dpi = config.mouse_dpi
            self.tracker.fovsize = config.fovsize
            self.tracker.ads_fov_enabled = getattr(config, "ads_fov_enabled", False)
            self.tracker.ads_fovsize = getattr(config, "ads_fovsize", config.fovsize)
            self.tracker.ads_key = getattr(config, "ads_key", "Right Mouse Button")
            self.tracker.tbfovsize = config.tbfovsize
            self.tracker.trigger_ads_fov_enabled = getattr(config, "trigger_ads_fov_enabled", False)
            self.tracker.trigger_ads_fovsize = getattr(config, "trigger_ads_fovsize", config.tbfovsize)
            self.tracker.trigger_ads_key = getattr(config, "trigger_ads_key", "Right Mouse Button")
            self.tracker.trigger_ads_key_type = getattr(config, "trigger_ads_key_type", "hold")
            self.tracker.selected_tb_btn = config.selected_tb_btn
            self.tracker.trigger_type = getattr(config, "trigger_type", "current")
            self.tracker.tbdelay_min = config.tbdelay_min
            self.tracker.tbdelay_max = config.tbdelay_max
            self.tracker.tbhold_min = config.tbhold_min
            self.tracker.tbhold_max = config.tbhold_max
            self.tracker.tbcooldown_min = config.tbcooldown_min
            self.tracker.tbcooldown_max = config.tbcooldown_max
            self.tracker.rgb_tbdelay_min = getattr(config, "rgb_tbdelay_min", 0.08)
            self.tracker.rgb_tbdelay_max = getattr(config, "rgb_tbdelay_max", 0.15)
            self.tracker.rgb_tbhold_min = getattr(config, "rgb_tbhold_min", 40)
            self.tracker.rgb_tbhold_max = getattr(config, "rgb_tbhold_max", 60)
            self.tracker.rgb_tbcooldown_min = getattr(config, "rgb_tbcooldown_min", 0.0)
            self.tracker.rgb_tbcooldown_max = getattr(config, "rgb_tbcooldown_max", 0.0)
            self.tracker.rgb_color_profile = getattr(config, "rgb_color_profile", "purple")
            self.tracker.tbburst_count_min = config.tbburst_count_min
            self.tracker.tbburst_count_max = config.tbburst_count_max
            self.tracker.tbburst_interval_min = config.tbburst_interval_min
            self.tracker.tbburst_interval_max = config.tbburst_interval_max
            self.tracker.trigger_roi_size = getattr(config, "trigger_roi_size", 8)
            self.tracker.trigger_min_pixels = getattr(config, "trigger_min_pixels", 4)
            self.tracker.trigger_min_ratio = getattr(config, "trigger_min_ratio", 0.03)
            self.tracker.trigger_confirm_frames = getattr(config, "trigger_confirm_frames", 2)
            self.tracker.switch_confirm_frames = getattr(config, "switch_confirm_frames", 3)
            self.tracker.ema_alpha = getattr(config, "ema_alpha", 0.35)
            if hasattr(self.tracker, "_target_smoother"):
                self.tracker._target_smoother.switch_confirm_frames = int(self.tracker.switch_confirm_frames)
                self.tracker._target_smoother.ema_alpha = float(self.tracker.ema_alpha)
            # Frame geometry / calibration / flick budget
            self.tracker.max_speed = float(getattr(config, "max_speed", 6000.0))
            self.tracker.hfov_deg = float(getattr(config, "hfov_deg", 103.0))
            self.tracker.vfov_deg = float(getattr(config, "vfov_deg", 0.0))
            # Flick V2 keys (schema 3). The controller itself reads the config
            # through a FlickTuning snapshot, but the tracker mirrors them so
            # mocks, tests and the debug view see one coherent state.
            self.tracker.flick_status = getattr(self.tracker, "flick_status", {})
            self.tracker.flick_engine = str(getattr(config, "flick_engine", "v2"))
            self.tracker.flick_settle_ms = float(getattr(config, "flick_settle_ms", 70.0))
            self.tracker.flick_settle_ms_sec = float(
                getattr(config, "flick_settle_ms_sec", 70.0)
            )
            self.tracker.flick_switch_radius_px = int(
                getattr(config, "flick_switch_radius_px", 64)
            )
            self.tracker.flick_switch_radius_px_sec = int(
                getattr(config, "flick_switch_radius_px_sec", 64)
            )
            self.tracker.calibration_session = bool(
                getattr(self.tracker, "calibration_session", False)
            )
            self.tracker.rcs_pull_speed = config.rcs_pull_speed
            self.tracker.rcs_activation_delay = config.rcs_activation_delay
            self.tracker.rcs_rapid_click_threshold = config.rcs_rapid_click_threshold
            # Silent Mode
            self.tracker.silent_distance = getattr(config, "silent_distance", 1.0)
            self.tracker.silent_delay = getattr(config, "silent_delay", 100.0)
            self.tracker.silent_move_delay = getattr(config, "silent_move_delay", 500.0)
            self.tracker.silent_return_delay = getattr(config, "silent_return_delay", 500.0)
            self.tracker.in_game_sens = config.in_game_sens
            self.tracker.color = config.color
            self.tracker.mode = config.mode
            self.tracker.mode_sec = getattr(config, "mode_sec", "Normal")
            self.tracker.selected_mouse_button = config.selected_mouse_button
            self.tracker.selected_mouse_button_sec = config.selected_mouse_button_sec
            
            # Update target FPS
            target_fps = getattr(config, "target_fps", 200)
            if hasattr(self.tracker, 'set_target_fps'):
                self.tracker.set_target_fps(target_fps)
            else:
                self.tracker._target_fps = float(target_fps)
            
            # Sec Aimbot
            self.tracker.normal_x_speed_sec = config.normal_x_speed_sec
            self.tracker.normal_y_speed_sec = config.normal_y_speed_sec
            self.tracker.normalsmooth_sec = config.normalsmooth_sec
            self.tracker.normalsmoothfov_sec = config.normalsmoothfov_sec
            self.tracker.fovsize_sec = config.fovsize_sec
            self.tracker.ads_fov_enabled_sec = getattr(config, "ads_fov_enabled_sec", False)
            self.tracker.ads_fovsize_sec = getattr(config, "ads_fovsize_sec", config.fovsize_sec)
            self.tracker.ads_key_sec = getattr(config, "ads_key_sec", "Right Mouse Button")
            self.tracker.selected_mouse_button_sec = config.selected_mouse_button_sec
            
        except Exception as e:
            log_print(f"[UI] Sync error: {e}")

    def _apply_settings(self, data, config_name=None):
        try:
            data = self._strip_config_metadata(data)
            _UI_PERSISTENT_KEYS = {
                "ui_pro_mode",
                "ui_compact_layout",
                "ui_pro_geometry",
                "ui_simple_position",
                "ui_simple_geometry",
                "ui_toggle_hotkey",
            }
            for k, v in data.items():
                if k in _UI_PERSISTENT_KEYS:
                    continue
                if k in ("mode", "mode_sec"):
                    v = self._aim_mode_display_to_value(v)
                setattr(config, k, v)
                if hasattr(self.tracker, k):
                    setattr(self.tracker, k, v)
                
                if k in self._slider_widgets: 
                    self._set_slider_value(k, v)
                if k in self._checkbox_vars: 
                    self._set_checkbox_value(k, v)
                if k in self._option_widgets: 
                    if k in ["selected_mouse_button", "selected_mouse_button_sec"]:
                        self._set_btn_option_value(k, BUTTONS.get(v, str(v)))
                    elif k in ("ads_key", "ads_key_sec"):
                        self._set_option_value(k, self._ads_binding_to_display(v))
                    elif k in ("ads_key_type", "ads_key_type_sec"):
                        self._set_option_value(
                            k,
                            ADS_KEY_TYPE_VALUE_TO_DISPLAY.get(str(v).strip().lower(), "Hold"),
                        )
                    elif k == "trigger_ads_key_type":
                        self._set_option_value(
                            k,
                            ADS_KEY_TYPE_VALUE_TO_DISPLAY.get(str(v).strip().lower(), "Hold"),
                        )
                    elif k == "trigger_type":
                        trigger_type_display = {
                            "current": "Classic Trigger",
                            "rgb": "RGB Trigger",
                        }
                        self._set_option_value(k, trigger_type_display.get(str(v).lower(), "Classic Trigger"))
                    elif k == "rgb_color_profile":
                        rgb_profile_display = {
                            "red": "Red",
                            "yellow": "Yellow",
                            "purple": "Purple",
                            "custom": "Custom",
                        }
                        self._set_option_value(k, rgb_profile_display.get(str(v).lower(), "Purple"))
                    elif k == "trigger_activation_type":
                        trigger_activation_display = {
                            "hold_enable": "Hold to Enable",
                            "hold_disable": "Hold to Disable",
                            "toggle": "Toggle",
                        }
                        self._set_option_value(k, trigger_activation_display.get(str(v), "Hold to Enable"))
                    elif k == "magnet_activation_type":
                        magnet_activation_display = {
                            "hold_enable": "Hold to Enable",
                            "hold_disable": "Hold to Disable",
                            "toggle": "Toggle",
                        }
                        self._set_option_value(k, magnet_activation_display.get(str(v), "Hold to Enable"))
                    elif k == "magnet_mode":
                        self._set_option_value(k, self._aim_mode_value_to_display(v))
                    elif k == "magnet_trigger_type":
                        trigger_display = {
                            "current": "Classic Trigger",
                            "rgb": "RGB Trigger",
                        }
                        self._set_option_value(k, trigger_display.get(str(v).strip().lower(), "Classic Trigger"))
                    elif k == "magnet_rgb_color_profile":
                        rgb_display = {
                            "red": "Red",
                            "yellow": "Yellow",
                            "purple": "Purple",
                            "custom": "Custom",
                        }
                        self._set_option_value(k, rgb_display.get(str(v).strip().lower(), "Purple"))
                    elif k == "trigger_strafe_mode":
                        strafe_mode_display = {
                            "off": "Off",
                            "auto": "Auto Strafe",
                            "manual_wait": "Manual Wait",
                        }
                        self._set_option_value(k, strafe_mode_display.get(str(v), "Off"))
                    elif k in ("mode", "mode_sec"):
                        self._set_option_value(k, self._aim_mode_value_to_display(v))
                    else:
                        self._set_option_value(k, v)

                if k == "selected_mouse_button" and hasattr(self, "aim_key_bind_button"):
                    self._set_bind_button_text(self.aim_key_bind_button, self._ads_binding_to_display(v))
                elif k == "selected_mouse_button_sec" and hasattr(self, "aim_key_bind_button_sec"):
                    self._set_bind_button_text(self.aim_key_bind_button_sec, self._ads_binding_to_display(v))
                elif k == "selected_tb_btn" and hasattr(self, "tb_key_bind_button"):
                    self._set_bind_button_text(self.tb_key_bind_button, self._ads_binding_to_display(v))
                elif k == "ads_key" and hasattr(self, "ads_key_bind_button"):
                    self._set_bind_button_text(self.ads_key_bind_button, self._ads_binding_to_display(v))
                elif k == "ads_key_sec" and hasattr(self, "ads_key_bind_button_sec"):
                    self._set_bind_button_text(self.ads_key_bind_button_sec, self._ads_binding_to_display(v))
                elif k == "trigger_ads_key" and hasattr(self, "trigger_ads_key_bind_button"):
                    self._set_bind_button_text(self.trigger_ads_key_bind_button, self._ads_binding_to_display(v))
                elif k == "rcs_keybind" and hasattr(self, "rcs_key_bind_button"):
                    self._set_bind_button_text(self.rcs_key_bind_button, self._ads_binding_to_display(v))
                elif k == "magnet_keybind" and hasattr(self, "magnet_key_bind_button"):
                    self._set_bind_button_text(self.magnet_key_bind_button, self._ads_binding_to_display(v))

                if k == "serial_auto_switch_4m":
                    self.saved_serial_auto_switch_4m = bool(v)
                    if hasattr(self, "var_serial_auto_switch_4m"):
                        self.var_serial_auto_switch_4m.set(bool(v))
                
                # 鏇存柊 OpenCV 椤ず瑷疆鐨?UI 璁婇噺
                if k == "show_opencv_windows" and hasattr(self, "show_opencv_var"):
                    self.show_opencv_var.set(v)
                elif k == "show_mode_text" and hasattr(self, "show_mode_var"):
                    self.show_mode_var.set(v)
                elif k == "show_aimbot_status" and hasattr(self, "show_aimbot_status_var"):
                    self.show_aimbot_status_var.set(v)
                elif k == "show_triggerbot_status" and hasattr(self, "show_triggerbot_status_var"):
                    self.show_triggerbot_status_var.set(v)
                elif k == "show_target_count" and hasattr(self, "show_target_count_var"):
                    self.show_target_count_var.set(v)
                elif k == "show_crosshair" and hasattr(self, "show_crosshair_var"):
                    self.show_crosshair_var.set(v)
                elif k == "show_distance_text" and hasattr(self, "show_distance_var"):
                    self.show_distance_var.set(v)
                # 鏇存柊 NDI FOV 瑷疆
                elif k == "ndi_fov_enabled" and hasattr(self, "var_ndi_fov_enabled"):
                    self.var_ndi_fov_enabled.set(v)
                elif k == "ndi_fov" and hasattr(self, "ndi_fov_entry") and self.ndi_fov_entry.winfo_exists():
                    self.ndi_fov_entry.delete(0, "end")
                    self.ndi_fov_entry.insert(0, str(v))
                    if hasattr(self, "ndi_fov_slider"):
                        self.ndi_fov_slider.set(v)
                    self._update_ndi_fov_info()
                # 鏇存柊 UDP FOV 瑷疆
                elif k == "udp_fov_enabled" and hasattr(self, "var_udp_fov_enabled"):
                    self.var_udp_fov_enabled.set(v)
                elif k == "udp_fov" and hasattr(self, "udp_fov_entry") and self.udp_fov_entry.winfo_exists():
                    self.udp_fov_entry.delete(0, "end")
                    self.udp_fov_entry.insert(0, str(v))
                    if hasattr(self, "udp_fov_slider"):
                        self.udp_fov_slider.set(v)
                    self._update_udp_fov_info()

            if str(getattr(self, "_active_tab_name", "")) == "Trigger":
                if (
                    "trigger_type" in data
                    or "trigger_strafe_mode" in data
                    or "mouse_api" in data
                    or "selected_tb_btn" in data
                    or "trigger_ads_fov_enabled" in data
                    or "trigger_ads_key" in data
                    or "trigger_ads_key_type" in data
                ):
                    if not self._supports_trigger_strafe_ui(getattr(config, "mouse_api", "Serial")):
                        config.trigger_strafe_mode = "off"
                    self._show_tb_tab()
            if str(getattr(self, "_active_tab_name", "")) == "Magnet Trigger":
                if any(str(key).startswith("magnet_") for key in data):
                    self._show_magnet_trigger_tab()
            if self._simple_mode:
                # Simple has no tabs to rebuild: re-read the config into the six
                # blocks in place (plan B13 - LOAD works from Simple).
                from src.ui_modes.simple_dashboard import refresh_simple_dashboard

                refresh_simple_dashboard(self)
            elif str(getattr(self, "_active_tab_name", "")) == "Main Aimbot":
                if (
                    "mode" in data
                    or "mouse_api" in data
                    or "selected_mouse_button" in data
                    or "ads_fov_enabled" in data
                    or "ads_key" in data
                    or "ads_key_type" in data
                ):
                    self._show_aimbot_tab()
            if not self._simple_mode and str(getattr(self, "_active_tab_name", "")) == "Sec Aimbot":
                if (
                    "mode_sec" in data
                    or "mouse_api" in data
                    or "selected_mouse_button_sec" in data
                    or "ads_fov_enabled_sec" in data
                    or "ads_key_sec" in data
                    or "ads_key_type_sec" in data
                ):
                    self._show_sec_aimbot_tab()

            from src.utils.detection import reload_model
            self.tracker.model, self.tracker.class_names = reload_model()
            
            msg = f"Loaded: {config_name}" if config_name else "Loaded config"
            try:
                self._log_config(f"{msg}")
            except:
                pass
        except Exception as e:
            log_print(f"[UI] Apply error: {e}")
            try:
                self._log_config(f"Apply error: {e}")
            except:
                pass

    def _save_new_config(self):
        name = simpledialog.askstring("Config name", "Enter the config name:")
        if not name:
            return
        self._do_save(name)

    def _save_config(self):
        name = self._selected_profile_name() or "default"
        self._do_save(name)

    def _normalize_config_display_name(self, name):
        normalized = str(name or "").strip()
        if normalized.lower().endswith(".json"):
            normalized = normalized[:-5]
        if normalized.lower().endswith("_cvm"):
            normalized = normalized[:-4]
        normalized = normalized.strip()
        return normalized or "default"

    def _config_display_name_from_filename(self, filename):
        base_name = str(filename or "").strip()
        if base_name.lower().endswith(".json"):
            base_name = base_name[:-5]
        if base_name.lower().endswith("_cvm"):
            base_name = base_name[:-4]
        base_name = base_name.strip()
        return base_name or "default"

    def _config_filename_from_display_name(self, display_name):
        normalized = self._normalize_config_display_name(display_name)
        return f"{normalized}_cvm.json"

    def _resolve_config_path(self, display_name, force_new_suffix=False):
        normalized = self._normalize_config_display_name(display_name)
        if force_new_suffix:
            filename = self._config_filename_from_display_name(normalized)
        else:
            file_map = getattr(self, "_config_file_map", {})
            filename = file_map.get(normalized) or self._config_filename_from_display_name(normalized)
        return os.path.join("configs", filename), normalized

    def _build_config_payload(self, data):
        payload = {CVM_CONFIG_COMMENT_KEY: CVM_CONFIG_COMMENT_VALUE}
        payload.update(dict(data or {}))
        return payload

    def _strip_config_metadata(self, data):
        if not isinstance(data, dict):
            return {}
        cleaned = dict(data)
        cleaned.pop(CVM_CONFIG_COMMENT_KEY, None)
        return cleaned

    def _has_valid_config_comment(self, data):
        if not isinstance(data, dict):
            return False
        comment = str(data.get(CVM_CONFIG_COMMENT_KEY, "")).strip()
        return comment == CVM_CONFIG_COMMENT_VALUE

    def _config_fingerprint(self, data):
        normalized = self._strip_config_metadata(data)
        try:
            return json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            fallback = {str(k): str(v) for k, v in dict(normalized).items()}
            return json.dumps(fallback, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def _load_importable_settings_from_json_file(self, file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        if not isinstance(raw_data, dict):
            raise ValueError("Imported file must contain a JSON object.")
        if not self._has_valid_config_comment(raw_data):
            raise ValueError("Invalid config file: missing CVM colorBot comment marker.")
        settings = self._strip_config_metadata(raw_data)
        if not isinstance(settings, dict):
            raise ValueError("Imported config payload is invalid.")
        return settings

    def _center_modal_window(self, window, width, height):
        try:
            window.update_idletasks()
            if self.winfo_exists():
                x = self.winfo_x() + max(0, (self.winfo_width() - width) // 2)
                y = self.winfo_y() + max(0, (self.winfo_height() - height) // 2)
            else:
                x = max(0, (window.winfo_screenwidth() - width) // 2)
                y = max(0, (window.winfo_screenheight() - height) // 2)
            window.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            window.geometry(f"{width}x{height}")

    def _ask_dark_yes_no(self, title, message, yes_text="Yes", no_text="No"):
        result = {"value": False}
        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.resizable(False, False)
        dialog.configure(fg_color=COLOR_BG)
        dialog.transient(self)
        dialog.grab_set()
        self._center_modal_window(dialog, 460, 190)

        def _close_with(value):
            result["value"] = bool(value)
            try:
                dialog.grab_release()
            except Exception:
                pass
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", lambda: _close_with(False))

        frame = ctk.CTkFrame(dialog, fg_color=COLOR_BG, corner_radius=0)
        frame.pack(fill="both", expand=True, padx=16, pady=14)

        ctk.CTkLabel(
            frame,
            text=message,
            text_color=COLOR_TEXT,
            font=("Roboto", 12),
            wraplength=420,
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(8, 18))

        btn_row = ctk.CTkFrame(frame, fg_color="transparent")
        btn_row.pack(fill="x", side="bottom")

        ctk.CTkButton(
            btn_row,
            text=no_text,
            command=lambda: _close_with(False),
            fg_color="transparent",
            border_width=1,
            border_color=COLOR_BORDER,
            hover_color=COLOR_SURFACE,
            text_color=COLOR_TEXT_DIM,
            width=100,
        ).pack(side="right")

        ctk.CTkButton(
            btn_row,
            text=yes_text,
            command=lambda: _close_with(True),
            fg_color=COLOR_TEXT,
            hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_BG,
            width=100,
        ).pack(side="right", padx=(0, 10))

        dialog.wait_window()
        return result["value"]

    def _ask_dark_string(self, title, prompt, initialvalue=""):
        result = {"value": None}
        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.resizable(False, False)
        dialog.configure(fg_color=COLOR_BG)
        dialog.transient(self)
        dialog.grab_set()
        self._center_modal_window(dialog, 500, 210)

        def _close_with(value):
            result["value"] = value
            try:
                dialog.grab_release()
            except Exception:
                pass
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", lambda: _close_with(None))

        frame = ctk.CTkFrame(dialog, fg_color=COLOR_BG, corner_radius=0)
        frame.pack(fill="both", expand=True, padx=16, pady=14)

        ctk.CTkLabel(
            frame,
            text=prompt,
            text_color=COLOR_TEXT,
            font=("Roboto", 12),
            anchor="w",
            justify="left",
            wraplength=460,
        ).pack(fill="x", pady=(8, 10))

        entry = ctk.CTkEntry(
            frame,
            fg_color=COLOR_SURFACE,
            text_color=COLOR_TEXT,
            border_color=COLOR_BORDER,
        )
        entry.pack(fill="x", pady=(0, 18))
        entry.insert(0, str(initialvalue or ""))
        entry.focus_set()
        entry.select_range(0, "end")

        def _confirm():
            _close_with(entry.get().strip())

        btn_row = ctk.CTkFrame(frame, fg_color="transparent")
        btn_row.pack(fill="x", side="bottom")

        ctk.CTkButton(
            btn_row,
            text="Cancel",
            command=lambda: _close_with(None),
            fg_color="transparent",
            border_width=1,
            border_color=COLOR_BORDER,
            hover_color=COLOR_SURFACE,
            text_color=COLOR_TEXT_DIM,
            width=100,
        ).pack(side="right")

        ctk.CTkButton(
            btn_row,
            text="OK",
            command=_confirm,
            fg_color=COLOR_TEXT,
            hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_BG,
            width=100,
        ).pack(side="right", padx=(0, 10))

        dialog.bind("<Return>", lambda _evt: _confirm())
        dialog.bind("<Escape>", lambda _evt: _close_with(None))
        dialog.wait_window()
        return result["value"]

    def _import_config_settings(self, settings, source_name, import_title="Import", source_path=None, use_dark_dialog=False):
        data = self._build_config_payload(settings)
        target_path, normalized_name = self._resolve_config_path(source_name, force_new_suffix=True)

        if os.path.exists(target_path):
            same_source = False
            if source_path:
                try:
                    same_source = os.path.abspath(target_path) == os.path.abspath(source_path)
                except Exception:
                    same_source = False
            if not same_source:
                prompt_text = f"Profile '{normalized_name}' already exists. Overwrite it?"
                if use_dark_dialog:
                    should_overwrite = self._ask_dark_yes_no(import_title, prompt_text)
                else:
                    should_overwrite = messagebox.askyesno(import_title, prompt_text)
                if not should_overwrite:
                    self._log_config(f"{import_title} canceled: {normalized_name}")
                    return False, normalized_name

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        self._refresh_config_list()
        if hasattr(self, "config_option") and self.config_option.winfo_exists():
            self.config_option.set(normalized_name)
        self._apply_settings(settings, config_name=normalized_name)
        self._log_config(f"Imported: {normalized_name}")
        return True, normalized_name

    def _get_clipboard_file_paths(self):
        if os.name != "nt" or USER32 is None or SHELL32 is None:
            return []

        if not USER32.OpenClipboard(None):
            return []

        try:
            if not USER32.IsClipboardFormatAvailable(CF_HDROP):
                return []
            h_drop = USER32.GetClipboardData(CF_HDROP)
            if not h_drop:
                return []

            file_paths = []
            count = int(SHELL32.DragQueryFileW(h_drop, DRAG_QUERY_FILE_COUNT, None, 0))
            for idx in range(count):
                length = int(SHELL32.DragQueryFileW(h_drop, idx, None, 0))
                if length <= 0:
                    continue
                buffer = ctypes.create_unicode_buffer(length + 1)
                copied = int(SHELL32.DragQueryFileW(h_drop, idx, buffer, length + 1))
                if copied <= 0:
                    continue
                path = str(buffer.value).strip()
                if path:
                    file_paths.append(path)
            return file_paths
        finally:
            USER32.CloseClipboard()

    def _get_clipboard_import_candidate(self):
        try:
            clipboard_text = str(self.clipboard_get() or "").strip()
        except tk.TclError:
            clipboard_text = ""
        except Exception:
            clipboard_text = ""

        if clipboard_text:
            try:
                raw_data = json.loads(clipboard_text)
                if isinstance(raw_data, dict) and self._has_valid_config_comment(raw_data):
                    settings = self._strip_config_metadata(raw_data)
                    return settings, "clipboard", "clipboard text"
            except Exception:
                pass

            potential_path = clipboard_text.strip().strip("\"'")
            if os.path.isfile(potential_path) and str(potential_path).lower().endswith(".json"):
                try:
                    settings = self._load_importable_settings_from_json_file(potential_path)
                    source_name = self._normalize_config_display_name(
                        os.path.splitext(os.path.basename(potential_path))[0]
                    )
                    return settings, source_name, f"clipboard path: {potential_path}"
                except Exception:
                    pass

        for file_path in self._get_clipboard_file_paths():
            if not str(file_path).lower().endswith(".json"):
                continue
            try:
                settings = self._load_importable_settings_from_json_file(file_path)
                source_name = self._normalize_config_display_name(
                    os.path.splitext(os.path.basename(file_path))[0]
                )
                return settings, source_name, f"clipboard file: {file_path}"
            except Exception:
                continue

        return None

    def _poll_clipboard_config_import(self):
        """One-shot clipboard check. NEVER reschedules itself.

        The previous implementation called ``self.after(..., self._poll_...)``
        from inside, while the scheduler also called it every 1.2 s: the number of
        timer chains grew linearly with uptime and the callback rate quadratically
        (plan RC-1). The scheduler is now the only owner of the cadence.
        """
        self._poll_clipboard_now()

    def _maybe_prompt_clipboard_config_import(self):
        # The tab is called "Profiles" everywhere (nav, _show_config_tab, the
        # active-tab name); comparing against the retired "Config" label made
        # auto-import dead code while its timer chain still burned CPU (RC-1b).
        if str(getattr(self, "_active_tab_name", "")) not in ("Profiles", "Config"):
            return
        if not hasattr(self, "config_option") or not self._widget_alive(self.config_option):
            return
        if self._clipboard_import_prompt_open:
            return

        candidate = self._get_clipboard_import_candidate()
        if not candidate:
            return

        settings, suggested_name, source_label = candidate
        current_settings = self._strip_config_metadata(self._get_current_settings())
        current_fingerprint = self._config_fingerprint(current_settings)
        incoming_fingerprint = self._config_fingerprint(settings)

        if incoming_fingerprint in self._clipboard_import_imported_signatures:
            return

        if incoming_fingerprint == current_fingerprint:
            return

        if (
            incoming_fingerprint == self._clipboard_import_last_declined_signature
            and current_fingerprint == self._clipboard_import_last_declined_config_fingerprint
        ):
            return

        self._clipboard_import_prompt_open = True
        try:
            should_import = self._ask_dark_yes_no(
                "Import",
                "Detected a CVM config in clipboard. Do you want to import it?",
            )
            if not should_import:
                self._clipboard_import_last_declined_signature = incoming_fingerprint
                self._clipboard_import_last_declined_config_fingerprint = current_fingerprint
                self._log_config(f"Clipboard import skipped: {source_label}")
                return

            default_name = self._normalize_config_display_name(suggested_name or "clipboard")
            entered_name = self._ask_dark_string(
                "Config name",
                "Enter the config name:",
                initialvalue=default_name,
            )
            if not entered_name:
                self._clipboard_import_last_declined_signature = incoming_fingerprint
                self._clipboard_import_last_declined_config_fingerprint = current_fingerprint
                self._log_config("Clipboard import canceled: no config name.")
                return

            success, normalized_name = self._import_config_settings(
                settings,
                source_name=entered_name,
                import_title="Import",
                use_dark_dialog=True,
            )
            if success:
                self._clipboard_import_last_declined_signature = None
                self._clipboard_import_last_declined_config_fingerprint = None
                self._clipboard_import_imported_signatures.add(incoming_fingerprint)
                messagebox.showinfo("Import", f"Imported config: {normalized_name}")
            else:
                self._clipboard_import_last_declined_signature = incoming_fingerprint
                self._clipboard_import_last_declined_config_fingerprint = current_fingerprint
        finally:
            self._clipboard_import_prompt_open = False

    def _copy_file_to_clipboard(self, file_path):
        if os.name != "nt" or USER32 is None or KERNEL32 is None:
            raise RuntimeError("File clipboard export is only supported on Windows.")

        abs_path = os.path.abspath(file_path)
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(abs_path)

        file_list_bytes = f"{abs_path}\0\0".encode("utf-16-le")
        dropfiles = DROPFILES()
        dropfiles.pFiles = ctypes.sizeof(DROPFILES)
        dropfiles.pt_x = 0
        dropfiles.pt_y = 0
        dropfiles.fNC = False
        dropfiles.fWide = True

        total_size = ctypes.sizeof(DROPFILES) + len(file_list_bytes)
        h_global = KERNEL32.GlobalAlloc(GHND, total_size)
        if not h_global:
            raise OSError("Failed to allocate clipboard memory.")

        locked_mem = KERNEL32.GlobalLock(h_global)
        if not locked_mem:
            KERNEL32.GlobalFree(h_global)
            raise OSError("Failed to lock clipboard memory.")

        try:
            ctypes.memmove(locked_mem, ctypes.byref(dropfiles), ctypes.sizeof(DROPFILES))
            ctypes.memmove(int(locked_mem) + ctypes.sizeof(DROPFILES), file_list_bytes, len(file_list_bytes))
        finally:
            KERNEL32.GlobalUnlock(h_global)

        if not USER32.OpenClipboard(None):
            KERNEL32.GlobalFree(h_global)
            raise OSError("Failed to open clipboard.")

        try:
            if not USER32.EmptyClipboard():
                KERNEL32.GlobalFree(h_global)
                raise OSError("Failed to empty clipboard.")
            if not USER32.SetClipboardData(CF_HDROP, h_global):
                KERNEL32.GlobalFree(h_global)
                raise OSError("Failed to set clipboard data.")
            h_global = None
        finally:
            USER32.CloseClipboard()

    def _do_save(self, name):
        path, normalized_name = self._resolve_config_path(name, force_new_suffix=True)
        settings = self._get_current_settings()
        data = self._build_config_payload(settings)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            self._refresh_config_list()
            self._select_current_profile_name(normalized_name)
            self._log_config(f"Saved: {normalized_name}")
        except Exception as e:
            self._log_config(f"Save error: {e}")

    def _load_selected_config(self):
        # Works from Simple mode too, where ``config_option`` does not exist and
        # ``simple_profile_option`` is the live selector (plan B13).
        path, normalized_name = self._resolve_config_path(self._selected_profile_name())
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Config file must contain a JSON object.")
            settings = self._strip_config_metadata(data)
            self._apply_settings(settings, config_name=normalized_name)
            self._select_current_profile_name(normalized_name)
        except Exception as e:
            log_print(f"[UI] Config load error: {e}")
            self._log_config(f"Load error: {e}")

    def _export_selected_config(self):
        path, normalized_name = self._resolve_config_path(self._selected_profile_name())
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            if not isinstance(raw_data, dict):
                raise ValueError("Config file must contain a JSON object.")

            settings = self._strip_config_metadata(raw_data)
            export_payload = self._build_config_payload(settings)
            if raw_data != export_payload:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(export_payload, f, indent=4, ensure_ascii=False)

            self._copy_file_to_clipboard(path)
            self._log_config(f"Exported file to clipboard: {normalized_name}")
            messagebox.showinfo("Export", "Config file copied to clipboard. You can now paste it elsewhere.")
        except Exception as e:
            self._log_config(f"Export error: {e}")
            messagebox.showerror("Export", f"Export failed:\n{e}")

    def _import_config_file(self):
        file_path = filedialog.askopenfilename(
            title="Import config file",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not file_path:
            return

        try:
            settings = self._load_importable_settings_from_json_file(file_path)
            source_name = self._normalize_config_display_name(os.path.splitext(os.path.basename(file_path))[0])
            success, normalized_name = self._import_config_settings(
                settings,
                source_name=source_name,
                import_title="Import",
                source_path=file_path,
                use_dark_dialog=True,
            )
            if success:
                messagebox.showinfo("Import", f"Imported config: {normalized_name}")
        except Exception as e:
            self._log_config(f"Import error: {e}")
            messagebox.showerror("Import", f"Import failed:\n{e}")

    def _delete_selected_config(self):
        try:
            self._refresh_config_list()
            file_map = dict(getattr(self, "_config_file_map", {}))
            display_names = sorted(file_map.keys(), key=lambda item: str(item).lower())

            if len(display_names) <= 1:
                self._log_config("Delete blocked: at least one config must remain.")
                messagebox.showwarning("Delete", "At least one config must remain.")
                return

            selected = self._selected_profile_name()
            if selected not in file_map:
                selected = display_names[0]

            filename = file_map.get(selected)
            if not filename:
                self._log_config("Delete error: no config selected.")
                return

            target_path = os.path.join("configs", filename)
            if not os.path.isfile(target_path):
                self._log_config(f"Delete error: file not found ({selected})")
                messagebox.showerror("Delete", f"Config file not found:\n{target_path}")
                return

            should_delete = self._ask_dark_yes_no(
                "Delete",
                f"Delete config '{selected}'?\nThis action cannot be undone.",
                yes_text="Delete",
                no_text="Cancel",
            )
            if not should_delete:
                self._log_config(f"Delete canceled: {selected}")
                return

            os.remove(target_path)
            self._log_config(f"Deleted: {selected}")
            self._refresh_config_list()
        except Exception as e:
            self._log_config(f"Delete error: {e}")
            messagebox.showerror("Delete", f"Delete failed:\n{e}")

    def _refresh_config_list(self):
        raw_files = [f for f in os.listdir("configs") if str(f).lower().endswith(".json")]
        file_map = {}
        for filename in sorted(raw_files, key=lambda item: str(item).lower()):
            display_name = self._config_display_name_from_filename(filename)
            existing = file_map.get(display_name)
            if existing:
                existing_is_new = str(existing).lower().endswith("_cvm.json")
                current_is_new = str(filename).lower().endswith("_cvm.json")
                if existing_is_new and not current_is_new:
                    continue
                if current_is_new and not existing_is_new:
                    file_map[display_name] = filename
                continue
            file_map[display_name] = filename

        if not file_map:
            file_map = {"default": self._config_filename_from_display_name("default")}

        self._config_file_map = file_map
        display_names = sorted(file_map.keys(), key=lambda item: str(item).lower())

        # Refresh whichever selector the current mode owns. Pro has
        # ``config_option`` (a CTkOptionMenu); Simple has ``simple_profile_option``.
        for attr in ("config_option", "simple_profile_option"):
            widget = getattr(self, attr, None)
            if not self._widget_alive(widget):
                continue
            try:
                current = self._normalize_config_display_name(widget.get())
            except Exception:
                current = display_names[0]
            if current not in display_names:
                current = display_names[0]
            try:
                widget.configure(values=display_names)
                widget.set(current)
            except Exception:
                pass

    def _on_config_selected(self, val):
        self._log_config(f"Selected config: {self._normalize_config_display_name(val)}")

    def _log_config(self, msg):
        try:
            if not self._widget_alive(getattr(self, "config_log", None)):
                return
            self.config_log.insert("end", f"> {msg}\n")
            self.config_log.see("end")
        except Exception:
            pass

    # --- NDI & Capture Callbacks ---

    def _capture_display_mode(self, mode=None):
        internal = str(mode if mode is not None else getattr(self.capture, "mode", "NDI"))
        if internal == "CaptureCard":
            return "Capture Card (OpenCV)"
        if internal == "CaptureCardGStreamer":
            return "Capture Card (GStreamer)"
        return internal

    def _capture_internal_mode(self, display_name):
        if display_name == "Capture Card (OpenCV)":
            return "CaptureCard"
        if display_name == "Capture Card (GStreamer)":
            return "CaptureCardGStreamer"
        return str(display_name)

    def _capture_summary_text(self):
        mode = self._capture_display_mode()
        connected = False
        try:
            connected = bool(self.capture.is_connected())
        except Exception:
            connected = False
        state = t("Connected") if connected else t("Disconnected")
        extra = ""
        internal = str(getattr(self.capture, "mode", ""))
        if internal in ("CaptureCard", "CaptureCardGStreamer"):
            backend = ""
            if internal == "CaptureCard":
                backend_name = str(getattr(config, "capture_opencv_backend", "dshow")).strip().lower()
                backend = "  UVC" if backend_name in ("uvc", "msmf") else "  DirectShow"
            extra = (
                f"  ·{backend}  Device {int(getattr(config, 'capture_device_index', 0))}  "
                f"{int(getattr(config, 'capture_width', 1920))}x{int(getattr(config, 'capture_height', 1080))}"
            )
        return f"{mode}  ·  {state}{extra}"

    def _refresh_capture_entry_card(self):
        """Update the capture summary. Does NOT recurse through the widget tree.

        The lock is applied by :meth:`_apply_runtime_settings_lock`, which is
        state-cached; calling it from here on every 500 ms tick was the source of
        the 2-10 ms full-tree walk (plan H1).
        """
        self._apply_runtime_settings_lock()

    def _on_capture_method_changed(self, val):
        if getattr(self, "_ignore_settings_events", False):
            return
        if self._runtime_settings_locked():
            self._restore_locked_capture_method_option()
            self._warn_runtime_settings_locked("capture")
            return
        self.capture_method_var.set(val)
        internal_mode = self._capture_internal_mode(val)
        previous_mode = str(getattr(self.capture, "mode", ""))
        config.capture_mode = internal_mode
        self._set_status_indicator(f"Status: Switching to {val}...", COLOR_TEXT_DIM)
        self._capture_switching = True
        self._capture_connect_job_id += 1

        def _switch():
            try:
                self.capture.set_mode(internal_mode)
                error = None
            except Exception as e:
                error = str(e)
            self.after(0, lambda: self._on_capture_mode_switched(val, internal_mode, previous_mode, error))

        threading.Thread(target=_switch, daemon=True, name="CaptureModeSwitch").start()

    def _on_capture_mode_switched(self, display_name, internal_mode, previous_mode, error):
        self._capture_switching = False
        if error:
            self._set_status_indicator(f"Status: Capture switch failed: {error}", COLOR_DANGER)
        else:
            self._set_status_indicator(f"Status: Mode {display_name}", COLOR_TEXT)
        self._update_capture_ui()
        self._refresh_capture_entry_card()

    def _process_source_updates(self):
        """Scheduler branch (100 ms): pull pending NDI source lists."""
        if self.capture.mode == "NDI":
            updates = self.capture.ndi.get_pending_source_updates()
            for names in updates:
                self._apply_sources_to_ui(names)

    def _refresh_sources(self):
        if self.capture.mode == "NDI":
            names = self.capture.ndi.refresh_sources()
            self._apply_sources_to_ui(names)
            self._set_status_indicator("Status: Refreshing NDI", COLOR_TEXT)

    def _update_ndi_fov_slider_max(self, width, height):
        """鏇存柊 NDI FOV 婊戞鐨勬渶澶у€硷紙姝ｆ柟褰㈣鍒囷紝浣跨敤杓冨皬鐨勫昂瀵革級"""
        if hasattr(self, 'ndi_fov_slider') and self.ndi_fov_slider.winfo_exists():
            # 姝ｆ柟褰㈣鍒囷紝鏈€澶у€艰ō鐐哄搴﹀拰楂樺害涓純灏忕殑涓€鍗?
            max_fov = max(16, min(width, height) // 2) if (width and height) else 1920
            self.ndi_fov_slider.configure(to=max_fov)
            # 濡傛灉鐣跺墠鍊艰秴閬庢柊鐨勬渶澶у€硷紝瑾挎暣鐐烘渶澶у€?
            current_val = int(getattr(config, "ndi_fov", 320))
            if current_val > max_fov:
                config.ndi_fov = max_fov
                self.ndi_fov_slider.set(max_fov)
                if hasattr(self, 'ndi_fov_entry') and self.ndi_fov_entry.winfo_exists():
                    self.ndi_fov_entry.delete(0, "end")
                    self.ndi_fov_entry.insert(0, str(max_fov))
            # 鏇存柊璩囪▕椤ず
            self._update_ndi_fov_info()
    
    def _update_udp_fov_slider_max(self, width, height):
        """鏇存柊 UDP FOV 婊戞鐨勬渶澶у€硷紙姝ｆ柟褰㈣鍒囷紝浣跨敤杓冨皬鐨勫昂瀵革級"""
        if hasattr(self, 'udp_fov_slider') and self.udp_fov_slider.winfo_exists():
            # 姝ｆ柟褰㈣鍒囷紝鏈€澶у€艰ō鐐哄搴﹀拰楂樺害涓純灏忕殑涓€鍗?
            max_fov = max(16, min(width, height) // 2) if (width and height) else 1920
            self.udp_fov_slider.configure(to=max_fov)
            # 濡傛灉鐣跺墠鍊艰秴閬庢柊鐨勬渶澶у€硷紝瑾挎暣鐐烘渶澶у€?
            current_val = int(getattr(config, "udp_fov", 320))
            if current_val > max_fov:
                config.udp_fov = max_fov
                self.udp_fov_slider.set(max_fov)
                if hasattr(self, 'udp_fov_entry') and self.udp_fov_entry.winfo_exists():
                    self.udp_fov_entry.delete(0, "end")
                    self.udp_fov_entry.insert(0, str(max_fov))
            # 鏇存柊璩囪▕椤ず
            self._update_udp_fov_info()
    
    def _connect_to_selected(self):
        if self.capture.mode == "NDI":
            sources = self.capture.ndi.get_source_list()
            if not sources: return
            
            selected = self.source_option.get()
            if selected and selected not in ["(no sources)", "(Scanning...)"]:
                self.capture.ndi.set_selected_source(selected)
                # 淇濆瓨閬镐腑鐨?NDI 婧?
                self.saved_ndi_source = selected
                config.last_ndi_source = selected
            
            success, error = self.capture.connect_ndi(selected)
            if success:
                self._set_status_indicator("Status: NDI connected", COLOR_TEXT)
                # 閫ｆ帴鎴愬姛寰岋紝鍢楄│鐛插彇鐣潰灏哄涓︽洿鏂版粦姊濇渶澶у€?
                self.after(500, self._update_ndi_fov_sliders_after_connect)  # 寤堕伈涓€榛炰互纰轰繚鐣潰宸叉簴鍌欏ソ
            else:
                self._set_status_indicator(f"Status: NDI error: {error}", COLOR_DANGER)
    
    def _update_ndi_fov_sliders_after_connect(self):
        """閫ｆ帴鎴愬姛寰屾洿鏂?NDI FOV 婊戞鐨勬渶澶у€?"""
        width, height = self.capture.get_frame_dimensions()
        if width and height:
            self._update_ndi_fov_slider_max(width, height)
            log_print(f"[UI] NDI frame dimensions: {width}x{height}, updated FOV slider max values")
            if hasattr(self, '_ndi_retry_count'):
                self._ndi_retry_count = 0
        else:
            # 濡傛灉绗竴娆＄嵅鍙栧け鏁楋紝鍐嶈│涓€娆★紙鏈€澶氳│3娆★級
            if not hasattr(self, '_ndi_retry_count'):
                self._ndi_retry_count = 0
            self._ndi_retry_count += 1
            if self._ndi_retry_count < 3:
                self.after(500, self._update_ndi_fov_sliders_after_connect)
            else:
                self._ndi_retry_count = 0
                
    def _connect_udp(self):
        if self.capture.mode == "UDP":
            ip = self.udp_ip_entry.get().strip()
            port = self.udp_port_entry.get().strip()
            # An empty box falls back to the configured port instead of sending
            # "" into int() and failing with a cryptic message.
            if not port:
                port = str(getattr(config, "udp_port", "5000"))
            if not ip:
                ip = str(getattr(config, "udp_ip", "0.0.0.0"))

            # 淇濆瓨鍒板収瀛樺拰 config
            self.saved_udp_ip = ip
            self.saved_udp_port = port
            config.udp_ip = ip
            config.udp_port = port
            
            success, error = self.capture.connect_udp(ip, port)
            if success:
                self._set_status_indicator("Status: UDP connected", COLOR_TEXT)
                # 閫ｆ帴鎴愬姛寰岋紝鍢楄│鐛插彇鐣潰灏哄涓︽洿鏂版粦姊濇渶澶у€?
                self.after(500, self._update_udp_fov_sliders_after_connect)  # 寤堕伈涓€榛炰互纰轰繚鐣潰宸叉簴鍌欏ソ
            else:
                self._set_status_indicator(f"Status: UDP connect failed: {error}", COLOR_DANGER)
                log_print(f"[UI] UDP connection failed: {error}")
    
    def _update_udp_fov_sliders_after_connect(self):
        """閫ｆ帴鎴愬姛寰屾洿鏂?UDP FOV 婊戞鐨勬渶澶у€?"""
        width, height = self.capture.get_frame_dimensions()
        if width and height:
            self._update_udp_fov_slider_max(width, height)
            log_print(f"[UI] UDP frame dimensions: {width}x{height}, updated FOV slider max values")
        else:
            # 濡傛灉绗竴娆＄嵅鍙栧け鏁楋紝鍐嶈│涓€娆★紙鏈€澶氳│3娆★級
            if not hasattr(self, '_udp_retry_count'):
                self._udp_retry_count = 0
            self._udp_retry_count += 1
            if self._udp_retry_count < 3:
                self.after(500, self._update_udp_fov_sliders_after_connect)
            else:
                self._udp_retry_count = 0
    
    def _connect_capture_card(self):
        """Connect CaptureCard off the UI thread so DirectShow open cannot freeze the panel."""
        if self.capture.mode not in ["CaptureCard", "CaptureCardGStreamer"]:
            return
        if hasattr(self, "capture_card_device_option") and self.capture_card_device_option.winfo_exists():
            self._on_capture_card_device_selected(self.capture_card_device_option.get())

        if hasattr(self, "capture_card_width_entry") and hasattr(self, "capture_card_height_entry"):
            try:
                width = int(self.capture_card_width_entry.get())
                height = int(self.capture_card_height_entry.get())
                config.capture_width = width
                config.capture_height = height
                self._update_capture_card_center_display()
            except ValueError:
                pass

        self._update_capture_card_center_display()
        self._capture_connect_job_id += 1
        job_id = self._capture_connect_job_id
        mode_name = "CaptureCardGStreamer" if self.capture.mode == "CaptureCardGStreamer" else "CaptureCard"
        self._set_status_indicator(f"Status: {mode_name} connecting...", COLOR_TEXT_DIM)

        def _worker():
            try:
                success, error = self.capture.connect_capture_card(config)
            except Exception as e:
                success, error = False, str(e)
            self.after(0, lambda: self._on_capture_card_connect_done(job_id, success, error))

        threading.Thread(target=_worker, daemon=True, name="CaptureCardConnect").start()

    def _on_capture_card_connect_done(self, job_id, success, error):
        if job_id != getattr(self, "_capture_connect_job_id", 0):
            return
        mode_name = "CaptureCardGStreamer" if self.capture.mode == "CaptureCardGStreamer" else "CaptureCard"
        if success:
            waiting = (
                mode_name == "CaptureCardGStreamer"
                and self.capture.capture_card_gstreamer_camera
                and hasattr(self.capture.capture_card_gstreamer_camera, "has_frame")
                and not self.capture.capture_card_gstreamer_camera.has_frame()
            )
            if waiting:
                self._set_status_indicator(
                    "Status: CaptureCardGStreamer connected (waiting first frame)",
                    COLOR_WARNING,
                )
                log_print("[UI] CaptureCardGStreamer connected, waiting for first frame.")
            else:
                self._set_status_indicator(f"Status: {mode_name} connected", COLOR_TEXT)
                log_print(f"[UI] {mode_name} connection successful.")
        else:
            self._set_status_indicator(f"Status: CaptureCard connect failed: {error}", COLOR_DANGER)
            log_print(f"[UI] CaptureCard connection failed: {error}")
        self._refresh_capture_entry_card()

    # --- MSS Callbacks ---
    def _on_mss_monitor_changed(self, event=None):
        """MSS Monitor Index 鏀硅畩"""
        if hasattr(self, 'mss_monitor_entry') and self.mss_monitor_entry.winfo_exists():
            try:
                val = int(self.mss_monitor_entry.get())
                config.mss_monitor_index = val
            except ValueError:
                pass
    
    def _on_mss_fov_x_slider_changed(self, val):
        """MSS FOV X 婊戞鏀硅畩"""
        if self._runtime_settings_locked():
            return
        int_val = int(round(val))
        config.mss_fov_x = int_val
        if hasattr(self, 'mss_fov_x_entry') and self.mss_fov_x_entry.winfo_exists():
            self.mss_fov_x_entry.delete(0, "end")
            self.mss_fov_x_entry.insert(0, str(int_val))
        self._update_mss_capture_info()
        # 鍗虫檪鏇存柊宸查€ｆ帴鐨?MSS 鎿峰彇鍣?
        if self.capture.mss_capture and self.capture.mss_capture.is_connected():
            fov_y = int(getattr(config, "mss_fov_y", 320))
            self.capture.mss_capture.set_fov(int_val, fov_y)
    
    def _on_mss_fov_x_entry_changed(self, event=None):
        """MSS FOV X 杓稿叆妗嗘敼璁?"""
        if self._runtime_settings_locked():
            return
        if hasattr(self, 'mss_fov_x_entry') and self.mss_fov_x_entry.winfo_exists():
            try:
                val = int(self.mss_fov_x_entry.get())
                val = max(16, min(1920, val))
                config.mss_fov_x = val
                if hasattr(self, 'mss_fov_x_slider'):
                    self.mss_fov_x_slider.set(val)
                self._update_mss_capture_info()
                if self.capture.mss_capture and self.capture.mss_capture.is_connected():
                    fov_y = int(getattr(config, "mss_fov_y", 320))
                    self.capture.mss_capture.set_fov(val, fov_y)
            except ValueError:
                pass
    
    def _on_mss_fov_y_slider_changed(self, val):
        """MSS FOV Y slider"""
        if self._runtime_settings_locked():
            return
        int_val = int(round(val))
        config.mss_fov_y = int_val
        if hasattr(self, 'mss_fov_y_entry') and self.mss_fov_y_entry.winfo_exists():
            self.mss_fov_y_entry.delete(0, "end")
            self.mss_fov_y_entry.insert(0, str(int_val))
        self._update_mss_capture_info()
        if self.capture.mss_capture and self.capture.mss_capture.is_connected():
            fov_x = int(getattr(config, "mss_fov_x", 320))
            self.capture.mss_capture.set_fov(fov_x, int_val)
    
    def _on_mss_fov_y_entry_changed(self, event=None):
        """MSS FOV Y entry"""
        if self._runtime_settings_locked():
            return
        if hasattr(self, 'mss_fov_y_entry') and self.mss_fov_y_entry.winfo_exists():
            try:
                val = int(self.mss_fov_y_entry.get())
                val = max(16, min(1080, val))
                config.mss_fov_y = val
                if hasattr(self, 'mss_fov_y_slider'):
                    self.mss_fov_y_slider.set(val)
                self._update_mss_capture_info()
                if self.capture.mss_capture and self.capture.mss_capture.is_connected():
                    fov_x = int(getattr(config, "mss_fov_x", 320))
                    self.capture.mss_capture.set_fov(fov_x, val)
            except ValueError:
                pass
    
    def _update_mss_capture_info(self):
        """鏇存柊 MSS 鎿峰彇绡勫湇璩囪▕椤ず"""
        if hasattr(self, 'mss_capture_info_label') and self.mss_capture_info_label.winfo_exists():
            fov_x = int(getattr(config, "mss_fov_x", 320))
            fov_y = int(getattr(config, "mss_fov_y", 320))
            total_w = fov_x * 2
            total_h = fov_y * 2
            self.mss_capture_info_label.configure(
                text=f"Capture area: {total_w} x {total_h} px (centered on screen)"
            )
    
    def _connect_mss(self):
        """閫ｆ帴 MSS 铻㈠箷鎿峰彇"""
        if self.capture.mode == "MSS":
            monitor_index = int(getattr(config, "mss_monitor_index", 1))
            fov_x = int(getattr(config, "mss_fov_x", 320))
            fov_y = int(getattr(config, "mss_fov_y", 320))
            
            # 寰炶几鍏ユ鏇存柊
            if hasattr(self, 'mss_monitor_entry') and self.mss_monitor_entry.winfo_exists():
                try:
                    monitor_index = int(self.mss_monitor_entry.get())
                    config.mss_monitor_index = monitor_index
                except ValueError:
                    pass
            
            success, error = self.capture.connect_mss(monitor_index, fov_x, fov_y)
            if success:
                self._set_status_indicator(f"Status: MSS connected (Monitor {monitor_index})", COLOR_TEXT)
            else:
                self._set_status_indicator(f"Status: MSS connect failed: {error}", COLOR_DANGER)
                log_print(f"[UI] MSS connection failed: {error}")
    
    # --- NDI FOV Callbacks ---
    def _on_ndi_fov_enabled_changed(self):
        """NDI FOV enable"""
        if self._runtime_settings_locked():
            return
        if hasattr(self, 'var_ndi_fov_enabled'):
            config.ndi_fov_enabled = self.var_ndi_fov_enabled.get()
    
    def _on_ndi_fov_slider_changed(self, val):
        """NDI FOV slider"""
        if self._runtime_settings_locked():
            return
        int_val = int(round(val))
        config.ndi_fov = int_val
        if hasattr(self, 'ndi_fov_entry') and self.ndi_fov_entry.winfo_exists():
            self.ndi_fov_entry.delete(0, "end")
            self.ndi_fov_entry.insert(0, str(int_val))
        self._update_ndi_fov_info()
    
    def _on_ndi_fov_entry_changed(self, event=None):
        """NDI FOV entry"""
        if self._runtime_settings_locked():
            return
        if hasattr(self, 'ndi_fov_entry') and self.ndi_fov_entry.winfo_exists():
            try:
                val = int(self.ndi_fov_entry.get())
                val = max(16, min(1920, val))
                config.ndi_fov = val
                if hasattr(self, 'ndi_fov_slider'):
                    self.ndi_fov_slider.set(val)
                self._update_ndi_fov_info()
            except ValueError:
                pass
    
    def _update_ndi_fov_info(self):
        """鏇存柊 NDI 瑁佸垏绡勫湇璩囪▕椤ず"""
        if hasattr(self, 'ndi_fov_info_label') and self.ndi_fov_info_label.winfo_exists():
            fov = int(getattr(config, "ndi_fov", 320))
            total_size = fov * 2
            self.ndi_fov_info_label.configure(
                text=f"Crop area: {total_size} x {total_size} px (square, centered on frame)"
            )
    
    # --- UDP FOV Callbacks ---
    def _on_udp_fov_enabled_changed(self):
        """UDP FOV enable"""
        if self._runtime_settings_locked():
            return
        if hasattr(self, 'var_udp_fov_enabled'):
            config.udp_fov_enabled = self.var_udp_fov_enabled.get()
    
    def _on_udp_fov_slider_changed(self, val):
        """UDP FOV slider"""
        if self._runtime_settings_locked():
            return
        int_val = int(round(val))
        config.udp_fov = int_val
        if hasattr(self, 'udp_fov_entry') and self.udp_fov_entry.winfo_exists():
            self.udp_fov_entry.delete(0, "end")
            self.udp_fov_entry.insert(0, str(int_val))
        self._update_udp_fov_info()
    
    def _on_udp_fov_entry_changed(self, event=None):
        """UDP FOV entry"""
        if self._runtime_settings_locked():
            return
        if hasattr(self, 'udp_fov_entry') and self.udp_fov_entry.winfo_exists():
            try:
                val = int(self.udp_fov_entry.get())
                val = max(16, min(1920, val))
                config.udp_fov = val
                if hasattr(self, 'udp_fov_slider'):
                    self.udp_fov_slider.set(val)
                self._update_udp_fov_info()
            except ValueError:
                pass
    
    def _update_udp_fov_info(self):
        """鏇存柊 UDP 瑁佸垏绡勫湇璩囪▕椤ず"""
        if hasattr(self, 'udp_fov_info_label') and self.udp_fov_info_label.winfo_exists():
            fov = int(getattr(config, "udp_fov", 320))
            total_size = fov * 2
            self.udp_fov_info_label.configure(
                text=f"Crop area: {total_size} x {total_size} px (square, centered on frame)"
            )

    def _normalize_mouse_api_name(self, mode):
        mode_norm = str(mode).strip().lower()
        if mode_norm == "net":
            return "Net"
        if mode_norm in ("kmboxa", "kmboxa_api", "kmboxaapi", "kma", "kmboxa-api"):
            return "KmboxA"
        if mode_norm == "dhz":
            return "DHZ"
        if mode_norm in ("makxdmakapi", "makxd_makapi", "makxd-makapi", "makxd makapi", "makxd_mak", "makxd-mak"):
            return "MakxdMakAPI"
        if mode_norm in ("makapi", "mak_api", "mak-api", "mak api"):
            return "MakAPI"
        if mode_norm in ("makv2binary", "makv2_binary", "makv2-binary", "binary"):
            return "MakV2Binary"
        if mode_norm in ("makv2", "mak_v2", "mak-v2"):
            return "MakV2"
        if mode_norm in ("makcucontroller", "makcu_controller", "makcu-controller", "makcu controller"):
            return "MakcuController"
        if mode_norm == "arduino":
            return "Arduino"
        if mode_norm in ("sendinput", "win32", "win32api", "win32_sendinput", "win32-sendinput"):
            return "SendInput"
        if mode_norm == "ferrum":
            return "Ferrum"
        if mode_norm in ("medius", "k4tech", "k4"):
            return "Medius"
        return "Serial"

    def _normalize_keyboard_api_name(self, mode):
        raw = str(mode or "").strip()
        lowered = raw.lower()
        if lowered in {"", "follow", "follow mouse api", "follow_mouse_api", "follow-mouse-api"}:
            return "Follow Mouse API"
        if lowered == "serial (makcu)":
            return "Serial (Makcu)"
        if lowered in ("makapi", "mak_api", "mak-api", "mak api"):
            return "MAK API"
        return self._normalize_mouse_api_name(raw)

    def _supports_trigger_strafe_ui(self, mode=None) -> bool:
        selected_mode = mode if mode is not None else getattr(config, "mouse_api", "Serial")
        try:
            from src.utils import mouse as mouse_backend

            return bool(mouse_backend.supports_trigger_strafe_ui(selected_mode))
        except Exception:
            normalized = self._normalize_mouse_api_name(selected_mode)
            return normalized in {"SendInput", "Net", "KmboxA", "DHZ", "Ferrum", "MakcuController", "Medius", "MakAPI"}

    def _supports_keyboard_state(self, mode=None) -> bool:
        if not bool(getattr(config, "keyboard_api_enabled", False)):
            return False
        selected_mode = mode if mode is not None else getattr(config, "keyboard_api", "Follow Mouse API")
        if str(selected_mode).strip().lower() in {"", "follow", "follow mouse api", "follow_mouse_api", "follow-mouse-api"}:
            selected_mode = getattr(config, "mouse_api", "Serial")
        try:
            from src.utils import mouse as mouse_backend

            return bool(mouse_backend.supports_keyboard_state(selected_mode))
        except Exception:
            normalized = self._normalize_mouse_api_name(selected_mode)
            return normalized in {"SendInput", "Net", "KmboxA", "DHZ", "MakcuController", "Medius", "MakAPI"}

    def _toggle_hardware_info_details(self):
        self._hardware_info_expanded = not bool(getattr(self, "_hardware_info_expanded", False))

        if hasattr(self, "hardware_details_toggle") and self.hardware_details_toggle.winfo_exists():
            self.hardware_details_toggle.configure(
                text=f"{t('Hardware Info')} {'▼' if self._hardware_info_expanded else '▶'}"
            )

        if hasattr(self, "hardware_details_label") and self.hardware_details_label.winfo_exists():
            if self._hardware_info_expanded:
                self.hardware_details_label.pack(fill="x", pady=(2, 0))
                self._update_hardware_status_ui()
            else:
                self.hardware_details_label.pack_forget()

    def _build_hardware_details_text(self, mode: str, connected: bool) -> str:
        auto_connect = bool(getattr(config, "auto_connect_mouse_api", False))
        keyboard_enabled = bool(getattr(config, "keyboard_api_enabled", False))
        keyboard_api = str(getattr(config, "keyboard_api", "Follow Mouse API"))
        keyboard_connected = False
        keyboard_backend = keyboard_api if keyboard_enabled else "Disabled"
        details = [
            t("Backend: {value}", value=mode),
            t("Keyboard Enabled: {value}", value=t("Yes") if keyboard_enabled else t("No")),
            t("Keyboard API: {value}", value=keyboard_api),
            t("Connected: {value}", value=t("Yes") if connected else t("No")),
            t("Auto Start On Startup: {value}", value=t("Yes") if auto_connect else t("No")),
        ]

        mouse_backend = None
        mouse_state = None
        net_api_module = None
        kmboxa_api_module = None
        try:
            from src.utils import mouse as mouse_backend
            from src.utils.mouse import NetAPI as net_api_module
            from src.utils.mouse import KmboxAAPI as kmboxa_api_module
            from src.utils.mouse import state as mouse_state
            if keyboard_enabled:
                keyboard_connected = bool(mouse_backend.is_keyboard_backend_connected())
                keyboard_backend = mouse_backend.get_keyboard_active_backend()
        except Exception:
            pass

        details.append(t("Keyboard Backend Connected: {value}", value=t("Yes") if keyboard_connected else t("No")))
        details.append(t("Keyboard Active Backend: {value}", value=keyboard_backend))

        if mode == "Net":
            ip = str(getattr(config, "net_ip", ""))
            port = str(getattr(config, "net_port", ""))
            uuid = str(getattr(config, "net_uuid", getattr(config, "net_mac", "")))
            details.append(f"IP/Port: {ip}:{port}")
            details.append(f"UUID: {uuid or '(empty)'}")
            try:
                if mouse_backend is not None:
                    details.append(f"DLL: {mouse_backend.get_expected_kmnet_dll_name()}")
                loaded_path = getattr(net_api_module, "_loaded_module_path", "")
                if loaded_path:
                    details.append(f"Loaded: {os.path.basename(loaded_path)}")
            except Exception:
                pass
        elif mode == "DHZ":
            ip = str(getattr(config, "dhz_ip", ""))
            port = str(getattr(config, "dhz_port", ""))
            random_shift = str(getattr(config, "dhz_random", 0))
            details.append(f"IP/Port: {ip}:{port}")
            details.append(f"Random Shift: {random_shift}")
            try:
                dhz_client = getattr(mouse_state, "dhz_client", None)
                if dhz_client is not None and hasattr(dhz_client, "addr"):
                    details.append(f"Active Target: {dhz_client.addr[0]}:{dhz_client.addr[1]}")
            except Exception:
                pass
        elif mode == "KmboxA":
            vid_pid = str(getattr(config, "kmboxa_vid_pid", "")).strip()
            vid = int(getattr(config, "kmboxa_vid", 0))
            pid = int(getattr(config, "kmboxa_pid", 0))
            details.append(f"VID/PID Input: {vid_pid or '(empty)'}")
            details.append(f"VID/PID Parsed: {vid}/{pid}")
            try:
                if mouse_backend is not None:
                    details.append(f"DLL: {mouse_backend.get_expected_kmboxa_dll_name()}")
                loaded_path = getattr(kmboxa_api_module, "_loaded_module_path", "")
                if loaded_path:
                    details.append(f"Loaded: {os.path.basename(loaded_path)}")
            except Exception:
                pass
        elif mode == "MakV2":
            cfg_port = str(getattr(config, "makv2_port", "") or "auto")
            cfg_baud = str(getattr(config, "makv2_baud", 4000000))
            details.append(f"Port: {cfg_port}")
            details.append(f"Baud: {cfg_baud}")
            try:
                serial_dev = getattr(mouse_state, "makcu", None)
                if serial_dev is not None:
                    details.append(f"Active Port: {getattr(serial_dev, 'port', cfg_port)}")
                    details.append(f"Active Baud: {getattr(serial_dev, 'baudrate', cfg_baud)}")
            except Exception:
                pass
        elif mode == "MakxdMakAPI":
            cfg_port = str(getattr(config, "makxd_mak_port", "") or "auto")
            cfg_baud = str(getattr(config, "makxd_mak_baud", 115200))
            details.append(f"Port: {cfg_port}")
            details.append(f"Baud: {cfg_baud}")
            details.append("Protocol: Binary opcode surface")
            try:
                serial_dev = getattr(mouse_state, "makcu", None)
                if serial_dev is not None:
                    details.append(f"Active Port: {getattr(serial_dev, 'port', cfg_port)}")
                    details.append(f"Active Baud: {getattr(serial_dev, 'baudrate', cfg_baud)}")
            except Exception:
                pass
        elif mode == "MakcuController":
            cfg_port = str(getattr(config, "makcu_controller_port", "") or "auto")
            cfg_baud = str(getattr(config, "makcu_controller_baud", 115200))
            details.append(f"Port: {cfg_port}")
            details.append(f"Baud: {cfg_baud}")
            details.append("Movement Output: Serial ctl.stick")
            details.append("Click/Keyboard Output: Local SendInput fallback")
            try:
                serial_dev = getattr(mouse_state, "makcu", None)
                if serial_dev is not None:
                    details.append(f"Active Port: {getattr(serial_dev, 'port', cfg_port)}")
                    details.append(f"Active Baud: {getattr(serial_dev, 'baudrate', cfg_baud)}")
                buttons = int(getattr(mouse_state, "makcu_controller_buttons", 0))
                lt = int(getattr(mouse_state, "makcu_controller_lt", 0))
                rt = int(getattr(mouse_state, "makcu_controller_rt", 0))
                details.append(f"Controller State: buttons={buttons}, lt={lt}, rt={rt}")
            except Exception:
                pass
        elif mode == "Arduino":
            cfg_port = str(getattr(config, "arduino_port", "") or "auto")
            cfg_baud = str(getattr(config, "arduino_baud", 115200))
            details.append(f"Port: {cfg_port}")
            details.append(f"Baud: {cfg_baud}")
            details.append(f"16-bit Move: {'Yes' if bool(getattr(config, 'arduino_16_bit_mouse', True)) else 'No'}")
            try:
                serial_dev = getattr(mouse_state, "makcu", None)
                if serial_dev is not None:
                    details.append(f"Active Port: {getattr(serial_dev, 'port', cfg_port)}")
                    details.append(f"Active Baud: {getattr(serial_dev, 'baudrate', cfg_baud)}")
            except Exception:
                pass
        elif mode == "SendInput":
            details.append("Injection: Win32 SendInput")
            details.append("Transport: Local OS API")
        elif mode == "MakAPI":
            cfg_port = str(getattr(config, "mak_api_port", "") or "auto")
            cfg_baud = str(getattr(config, "mak_api_baud", 0) or "auto")
            details.append(f"Port: {cfg_port}")
            details.append(f"Baud: {cfg_baud}")
            details.append("Protocol: MAK_API DE AD binary frames")
            try:
                from src.utils.mouse.MakAPI import connection_info

                info = connection_info() or {}
                if info.get("port"):
                    details.append(f"Active Port: {info.get('port')}")
                    details.append(f"Active Baud: {info.get('baud')}")
                    details.append(f"Device kinds: 0x{int(info.get('kinds') or 0):02X}")
                    details.append(f"Firmware: {info.get('firmware')}")
            except Exception:
                pass
        else:
            serial_mode = str(getattr(config, "serial_port_mode", "Auto")).strip().lower()
            serial_mode_label = "Manual" if serial_mode == "manual" else "Auto"
            configured_port = str(getattr(config, "serial_port", "")).strip()
            auto_switch_4m = bool(getattr(config, "serial_auto_switch_4m", False))
            details.append(f"COM Mode: {serial_mode_label}")
            details.append(f"Auto Switch 4M On Startup: {'Yes' if auto_switch_4m else 'No'}")
            if serial_mode_label == "Manual":
                details.append(f"Configured Port: {configured_port or '(empty)'}")
            else:
                details.append("Configured Port: auto-detect")
            try:
                serial_dev = getattr(mouse_state, "makcu", None)
                if serial_dev is not None:
                    details.append(f"Active Port: {getattr(serial_dev, 'port', 'unknown')}")
                    details.append(f"Active Baud: {getattr(serial_dev, 'baudrate', 'unknown')}")
            except Exception:
                pass

        try:
            if mouse_backend is not None:
                last_error = str(mouse_backend.get_last_connect_error() or "").strip()
                if last_error and not connected:
                    details.append(f"Last Error: {last_error}")
        except Exception:
            pass

        return "\n".join(details)

    def _update_hardware_status_ui(self):
        mode = self._normalize_mouse_api_name(getattr(config, "mouse_api", "Serial"))
        connected = False

        try:
            from src.utils import mouse as mouse_backend

            connected = bool(getattr(mouse_backend, "is_connected", False))
            if connected:
                active_backend = mouse_backend.get_active_backend()
                if active_backend:
                    # 優先使用實際連接的 backend，而不是 config 中的 mouse_api
                    active_mode = self._normalize_mouse_api_name(active_backend)
                    if active_mode:
                        mode = active_mode
        except Exception:
            connected = False

        if hasattr(self, "hardware_type_label") and self.hardware_type_label.winfo_exists():
            self.hardware_type_label.configure(text=t("Hardware: {mode}", mode=mode))

        if hasattr(self, "hardware_conn_label") and self.hardware_conn_label.winfo_exists():
            if connected:
                self.hardware_conn_label.configure(text=t("Hardware Status: Connected"), text_color=COLOR_SUCCESS)
            else:
                self.hardware_conn_label.configure(text=t("Hardware Status: Disconnected"), text_color=COLOR_DANGER)

        if (
            getattr(self, "_hardware_info_expanded", False)
            and hasattr(self, "hardware_details_label")
            and self.hardware_details_label.winfo_exists()
        ):
            self.hardware_details_label.configure(text=self._build_hardware_details_text(mode, connected))

    def _update_connection_status_loop(self):
        if not getattr(self, "_runtime_busy", False):
            is_conn = self.capture.is_connected()
            current_mode = self.capture.mode
            hw_ok = False
            try:
                from src.utils import mouse as mouse_backend

                hw_ok = bool(getattr(mouse_backend, "is_connected", False))
            except Exception:
                hw_ok = False
            hw_name = getattr(config, "mouse_api", "Serial")
            self._safe_pill(
                getattr(self, "pill_hardware", None),
                f"{hw_name}",
                dot_color="#10B981" if hw_ok else "#F43F5E",
            )
            self._update_conn_pill(is_conn and hw_ok)
            if getattr(self, "_runtime_active", False):
                if hw_ok and is_conn:
                    self._set_status_indicator(t("Status: Running ({mode})", mode=current_mode), COLOR_SUCCESS)
                elif hw_ok:
                    self._set_status_indicator(t("Status: Running (capture down)"), COLOR_WARNING)
                elif is_conn:
                    self._set_status_indicator(t("Status: Running (hardware down)"), COLOR_WARNING)
                else:
                    self._set_status_indicator(t("Status: Runtime dropped"), COLOR_DANGER)
            elif is_conn:
                self._set_status_indicator(t("Status: Online ({mode})", mode=current_mode), COLOR_TEXT)
            else:
                self._set_status_indicator(t("Status: Offline"), COLOR_TEXT_DIM)
        self._update_hardware_status_ui()
        self._refresh_capture_entry_card()

    def _update_conn_pill(self, online):
        """Simple mode has a dedicated connection pill; Pro does not."""
        pill = getattr(self, "pill_conn", None)
        if pill is None:
            return
        self._safe_pill(
            pill,
            "ONLINE" if online else "OFFLINE",
            dot_color="#10B981" if online else "#F43F5E",
        )

    def _apply_perf_texts(self, fps_text, decode_text, delay_text, pill_fps=None, pill_ping=None):
        """The single writer for the Pro labels and the Simple pills.

        Simple has no ``fps_label``/``decode_delay_label``/``total_delay_label``;
        the old code called ``configure`` on them unconditionally and swallowed
        the resulting ``AttributeError`` ten times a second (plan RC-5).
        """
        self._safe_text(getattr(self, "fps_label", None), fps_text)
        self._safe_text(getattr(self, "decode_delay_label", None), decode_text)
        self._safe_text(getattr(self, "total_delay_label", None), delay_text)

        if pill_fps is not None:
            short_fps, fps_color = pill_fps
        else:
            short_fps = fps_text.split(":", 1)[-1].strip().replace("~", "") or "--"
            fps_color = "#10B981"
        if pill_ping is not None:
            short_ping, ping_color = pill_ping
        else:
            short_ping = delay_text.split(":", 1)[-1].strip() or "--"
            ping_color = "#06B6D4"

        self._simple_fps_text = str(short_fps)
        self._simple_ping_text = str(short_ping)
        # Only re-write when the visible string actually changed.
        self._safe_pill(getattr(self, "pill_fps", None), self._simple_fps_text, dot_color=fps_color)
        self._safe_pill(getattr(self, "pill_delay", None), self._simple_ping_text, dot_color=ping_color)

    def _update_performance_stats(self):
        """鏇存柊鎬ц兘绲辫▓淇℃伅锛團PS 鍜屽欢閬诧級"""
        try:
            if self.capture.mode == "UDP" and self.capture.is_connected():
                # 寰?UDP receiver 鐛插彇鎬ц兘绲辫▓
                receiver = self.capture.udp_manager.get_receiver()
                if receiver:
                    stats = receiver.get_performance_stats()
                    
                    # 鏇存柊 FPS
                    current_fps = stats.get('current_fps', 0)
                    self._safe_text(getattr(self, "fps_label", None), f"FPS: {current_fps:.1f}")
                    
                    # 鏇存柊瑙ｇ⒓寤堕伈
                    decode_delay = stats.get('decode_delay_ms', 0)
                    self._safe_text(getattr(self, "decode_delay_label", None), f"Decode: {decode_delay:.1f} ms")
                    
                    # 鏇存柊绺藉欢閬诧紙鎺ユ敹 + 瑙ｇ⒓ + 铏曠悊锛?
                    receive_delay = stats.get('receive_delay_ms', 0)
                    processing_delay = stats.get('processing_delay_ms', 0)
                    total_delay = receive_delay + decode_delay + processing_delay
                    self._safe_text(getattr(self, "total_delay_label", None), f"Delay: {total_delay:.1f} ms")
                    self._safe_pill(
                        getattr(self, "pill_fps", None),
                        f"{current_fps:.0f} FPS",
                        dot_color="#10B981" if current_fps > 30 else "#F59E0B",
                    )
                    self._safe_pill(
                        getattr(self, "pill_delay", None),
                        f"{total_delay:.1f} ms",
                        dot_color="#06B6D4" if total_delay < 3.0 else "#F59E0B",
                    )
                    self._simple_fps_text = f"{current_fps:.0f} FPS"
                    self._simple_ping_text = f"{total_delay:.1f} ms"
            elif self.capture.mode == "Teleport" and self.capture.is_connected():
                receiver = None
                if getattr(self.capture, "teleport_manager", None):
                    receiver = self.capture.teleport_manager.get_receiver()
                if receiver:
                    stats = receiver.get_performance_stats()
                    current_fps = stats.get('current_fps', 0)
                    decode_delay = stats.get('decode_delay_ms', 0)
                    self._safe_text(getattr(self, "fps_label", None), f"FPS: {current_fps:.1f}")
                    self._safe_text(getattr(self, "decode_delay_label", None), f"Decode: {decode_delay:.1f} ms")
                    self._safe_text(getattr(self, "total_delay_label", None), f"Delay: {decode_delay:.1f} ms")
            elif self.capture.mode == "NDI" and self.capture.is_connected():
                # NDI 妯″紡锛氬緸 tracker 鐛插彇绨″柈鐨?FPS 淇℃伅
                if hasattr(self.tracker, '_frame_count'):
                    target_fps = getattr(self.tracker, "_target_fps", 0)
                    self._safe_text(getattr(self, "fps_label", None), f"FPS: ~{target_fps}")
                    self._safe_text(getattr(self, "decode_delay_label", None), "Decode: N/A")
                    self._safe_text(getattr(self, "total_delay_label", None), "Delay: N/A")
            elif self.capture.mode == "MSS" and self.capture.is_connected():
                # MSS 妯″紡锛氬緸 mss_capture 鐛插彇鏁堣兘绲辫▓
                if self.capture.mss_capture:
                    stats = self.capture.mss_capture.get_performance_stats()
                    fps = stats.get('current_fps', 0)
                    grab_delay = stats.get('grab_delay_ms', 0)
                    self._safe_text(getattr(self, "fps_label", None), f"FPS: {fps:.1f}")
                    self._safe_text(getattr(self, "decode_delay_label", None), f"Grab: {grab_delay:.1f} ms")
                    self._safe_text(getattr(self, "total_delay_label", None), f"Delay: {grab_delay:.1f} ms")
                else:
                    self._safe_text(getattr(self, "fps_label", None), "FPS: --")
                    self._safe_text(getattr(self, "decode_delay_label", None), "Grab: -- ms")
                    self._safe_text(getattr(self, "total_delay_label", None), "Delay: -- ms")
            elif self.capture.mode == "CaptureCard" and self.capture.is_connected():
                # CaptureCard 妯″紡锛氶’绀哄熀鏈?FPS 淇℃伅
                if hasattr(self.tracker, '_frame_count'):
                    target_fps = getattr(self.tracker, "_target_fps", 0)
                    self._safe_text(getattr(self, "fps_label", None), f"FPS: ~{target_fps}")
                    self._safe_text(getattr(self, "decode_delay_label", None), "Decode: N/A")
                    self._safe_text(getattr(self, "total_delay_label", None), "Delay: N/A")
            else:
                # 鏈€ｆ帴鏅傞’绀?--
                self._safe_text(getattr(self, "fps_label", None), "FPS: --")
                self._safe_text(getattr(self, "decode_delay_label", None), "Decode: -- ms")
                self._safe_text(getattr(self, "total_delay_label", None), "Delay: -- ms")
        except Exception as e:
            log_print(f"[UI] Performance stats update error: {e}")

    def _update_conn_pill(self, online):
        """Simple mode has a dedicated connection pill; Pro does not."""
        pill = getattr(self, "pill_conn", None)
        if pill is None:
            return
        self._safe_pill(
            pill,
            "ONLINE" if online else "OFFLINE",
            dot_color="#10B981" if online else "#F43F5E",
        )

    def _apply_sources_to_ui(self, names):
        # Only update if we are still on NDI mode and the widget exists
        if self.capture.mode == "NDI" and self._widget_alive(getattr(self, "source_option", None)):
            if names:
                self.source_option.configure(values=names)
                
                # 鍢楄│鎭㈠京涔嬪墠淇濆瓨鐨勯伕鎿?
                if self.saved_ndi_source and self.saved_ndi_source in names:
                    self.source_option.set(self.saved_ndi_source)
                elif self.source_option.get() not in names:
                    self.source_option.set(names[0])
            else:
                self.source_option.configure(values=["(no sources)"])
                self.source_option.set("(no sources)")

    def _on_source_selected(self, val):
        if val and val not in ["(no sources)", "(Scanning...)"]:
            if self.capture.mode == "NDI":
                self.capture.ndi.set_selected_source(val)

    def _open_settings_window(self):
        existing = getattr(self, "_settings_window", None)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.lift()
                    existing.focus_force()
                    return
            except Exception:
                pass
        self._settings_window = SettingsWindow(self)
    
    def _on_close(self):
        """Shutdown sequence (plan §8.7): cancel jobs, stop launcher, save, destroy."""
        if getattr(self, "_closing", False):
            return
        self._closing = True

        # --- cancel every Tk timer that could touch a dead widget ----------
        for job_attr in ("_ui_tick_job", "_hotkey_poll_job", "_config_save_job"):
            job = getattr(self, job_attr, None)
            if not job:
                continue
            try:
                self.after_cancel(job)
            except Exception:
                pass
            setattr(self, job_attr, None)
        self._cancel_binding_capture()
        self._cancel_pid_preview()

        # --- persist current geometry before the window disappears --------
        self._save_mode_geometry()
        try:
            config.save_to_file()
        except Exception as e:
            log_print(f"[UI] Failed to auto-save configuration: {e}")

        # --- launcher (hotkey/tray/thread) --------------------------------
        launcher = getattr(self, "_launcher", None)
        if launcher is not None:
            try:
                launcher.stop()
            except Exception as e:
                log_print(f"[UI] Launcher stop error: {e}")
            self._launcher = None

        watcher = getattr(self, "_instance_watcher", None)
        if watcher is not None:
            try:
                watcher.stop()
            except Exception:
                pass
            self._instance_watcher = None

        try: 
            self.tracker.stop()
        except Exception as e:
            log_print(f"[UI] Tracker stop error: {e}")
        
        # 娓呯悊鎹曠嵅鏈嶅嫏
        try: 
            self.capture.cleanup()
        except Exception as e:
            log_print(f"[UI] Capture cleanup error: {e}")
        
        try:
            self.destroy()
        except Exception as e:
            log_print(f"[UI] Destroy error: {e}")
        
        # 闂滈枆鎵€鏈?OpenCV 绐楀彛
        try: 
            cv2.destroyAllWindows()
        except Exception as e:
            log_print(f"[UI] CV2 cleanup error: {e}")

        # Release the single-instance mutex last, once every thread is gone.
        try:
            single_instance.release()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Simple mode helpers used by src/ui_modes/simple_dashboard.py
    # ------------------------------------------------------------------
    def _simple_profile_names(self):
        """Profile list for the Simple selector (reads init() of configs/)."""
        names = []
        try:
            if os.path.isdir("configs"):
                for filename in os.listdir("configs"):
                    if not str(filename).lower().endswith(".json"):
                        continue
                    names.append(self._config_display_name_from_filename(filename))
        except Exception:
            names = []
        if not names:
            names = ["default"]
        return sorted(set(names), key=lambda item: str(item).lower())

    def _current_profile_name(self):
        try:
            path = str(getattr(config, "_config_path", "") or "")
            if path:
                return self._config_display_name_from_filename(os.path.basename(path))
        except Exception:
            pass
        return "default"

    def _profile_widget(self):
        """The active profile selector: Pro uses ``config_option``, Simple its own.

        Returns ``None`` when neither exists (mid mode switch); callers must then
        fall back to the config value instead of assuming a widget exists.
        """
        for attr in ("config_option", "simple_profile_option"):
            widget = getattr(self, attr, None)
            if self._widget_alive(widget):
                return widget
        return None

    def _selected_profile_name(self):
        widget = self._profile_widget()
        if widget is not None:
            try:
                value = str(widget.get() or "").strip()
                if value:
                    return self._normalize_config_display_name(value)
            except Exception:
                pass
        return self._current_profile_name()

    def _on_simple_profile_selected(self, val):
        name = self._normalize_config_display_name(val)
        self._select_current_profile_name(name)
        log_print(f"[UI] Simple profile selected: {name}")

    def _select_current_profile_name(self, name):
        for attr in ("simple_profile_option", "config_option"):
            widget = getattr(self, attr, None)
            if not self._widget_alive(widget):
                continue
            try:
                widget.set(name)
            except Exception:
                pass

    def _on_quick_trigger_changed(self):
        """Simple mode's Triggerbot switch.

        Pro keeps its own ``var_enabletb`` inside the trigger tab; Simple has a
        dedicated ``var_enabletb_quick`` so the two never fight over one var.
        """
        var = getattr(self, "var_enabletb_quick", None)
        if var is not None:
            try:
                config.enabletb = bool(var.get())
            except Exception:
                pass
        tracker = getattr(self, "tracker", None)
        if tracker is not None:
            try:
                tracker.enabletb = bool(getattr(config, "enabletb", False))
            except Exception:
                pass

    def _cancel_pid_preview(self):
        """Cancel the pending PID preview repaint, if any."""
        job = getattr(self, "_pid_preview_job", None)
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._pid_preview_job = None

    # Callbacks proxies
    def _on_normal_x_speed_changed(self, val): 
        config.normal_x_speed = val
        self.tracker.normal_x_speed = val
    
    def _on_normal_y_speed_changed(self, val): 
        config.normal_y_speed = val
        self.tracker.normal_y_speed = val

    def _on_flick_strength_x_changed(self, val):
        self._on_flick_param_changed("flick_gain", val)
        config.flick_strength_x = float(val)

    def _on_flick_strength_y_changed(self, val):
        config.flick_strength_y = float(val)
    
    def _on_silent_distance_changed(self, val):
        config.silent_distance = val
        self.tracker.silent_distance = val
    
    def _on_silent_delay_changed(self, val):
        config.silent_delay = val
        self.tracker.silent_delay = val
    
    def _on_silent_move_delay_changed(self, val):
        config.silent_move_delay = val
        self.tracker.silent_move_delay = val
    
    def _on_silent_return_delay_changed(self, val):
        config.silent_return_delay = val
        self.tracker.silent_return_delay = val
    
    def _on_config_in_game_sens_changed(self, val): 
        config.in_game_sens = val
        self.tracker.in_game_sens = val
    
    def _on_config_normal_smooth_changed(self, val): 
        config.normalsmooth = val
        self.tracker.normalsmooth = val
    
    def _on_config_normal_smoothfov_changed(self, val): 
        config.normalsmoothfov = val
        self.tracker.normalsmoothfov = val
    
    def _on_fovsize_changed(self, val): 
        config.fovsize = val
        self.tracker.fovsize = val
        self._refresh_pid_preview_if_pid_mode(is_sec=False)
    
    def _on_aim_offsetX_changed(self, val):
        config.aim_offsetX = val
    
    def _on_aim_offsetY_changed(self, val):
        config.aim_offsetY = val
    
    def _on_aim_type_selected(self, val):
        config.aim_type = val
    
    def _on_tbdelay_range_changed(self, min_val, max_val):
        """Triggerbot Delay 绡勫湇鏀硅畩"""
        config.tbdelay_min = min_val
        config.tbdelay_max = max_val
        if hasattr(self, 'tracker'):
            self.tracker.tbdelay_min = min_val
            self.tracker.tbdelay_max = max_val
    
    def _on_tbhold_range_changed(self, min_val, max_val):
        """Triggerbot Hold 绡勫湇鏀硅畩"""
        config.tbhold_min = min_val
        config.tbhold_max = max_val
        if hasattr(self, 'tracker'):
            self.tracker.tbhold_min = min_val
            self.tracker.tbhold_max = max_val

    def _on_rgb_tbdelay_range_changed(self, min_val, max_val):
        config.rgb_tbdelay_min = min_val
        config.rgb_tbdelay_max = max_val
        if hasattr(self, "tracker"):
            self.tracker.rgb_tbdelay_min = min_val
            self.tracker.rgb_tbdelay_max = max_val

    def _on_rgb_tbhold_range_changed(self, min_val, max_val):
        config.rgb_tbhold_min = min_val
        config.rgb_tbhold_max = max_val
        if hasattr(self, "tracker"):
            self.tracker.rgb_tbhold_min = min_val
            self.tracker.rgb_tbhold_max = max_val

    def _on_rgb_tbcooldown_range_changed(self, min_val, max_val):
        config.rgb_tbcooldown_min = min_val
        config.rgb_tbcooldown_max = max_val
        if hasattr(self, "tracker"):
            self.tracker.rgb_tbcooldown_min = min_val
            self.tracker.rgb_tbcooldown_max = max_val
    

    def _on_trigger_roi_size_changed(self, val):
        config.trigger_roi_size = int(val)
        if hasattr(self, "tracker"):
            self.tracker.trigger_roi_size = int(val)

    def _on_trigger_min_pixels_changed(self, val):
        config.trigger_min_pixels = int(val)
        if hasattr(self, "tracker"):
            self.tracker.trigger_min_pixels = int(val)

    def _on_trigger_min_ratio_changed(self, val):
        config.trigger_min_ratio = float(val)
        if hasattr(self, "tracker"):
            self.tracker.trigger_min_ratio = float(val)

    def _on_trigger_confirm_frames_changed(self, val):
        config.trigger_confirm_frames = int(val)
        if hasattr(self, "tracker"):
            self.tracker.trigger_confirm_frames = int(val)

    def _on_tbcooldown_range_changed(self, min_val, max_val):
        """Triggerbot Cooldown 绡勫湇鏀硅畩"""
        config.tbcooldown_min = min_val
        config.tbcooldown_max = max_val
        if hasattr(self, 'tracker'):
            self.tracker.tbcooldown_min = min_val
            self.tracker.tbcooldown_max = max_val
    
    def _on_tbburst_count_range_changed(self, min_val, max_val):
        """Triggerbot Burst Count 绡勫湇鏀硅畩"""
        config.tbburst_count_min = int(min_val)
        config.tbburst_count_max = int(max_val)
        if hasattr(self, 'tracker'):
            self.tracker.tbburst_count_min = int(min_val)
            self.tracker.tbburst_count_max = int(max_val)
    
    def _on_tbburst_interval_range_changed(self, min_val, max_val):
        """Triggerbot Burst Interval 绡勫湇鏀硅畩"""
        config.tbburst_interval_min = min_val
        config.tbburst_interval_max = max_val
        if hasattr(self, 'tracker'):
            self.tracker.tbburst_interval_min = min_val
            self.tracker.tbburst_interval_max = max_val
    
    def _on_tbfovsize_changed(self, val): 
        config.tbfovsize = val
        self.tracker.tbfovsize = val

    def _on_trigger_ads_fov_enabled_changed(self):
        config.trigger_ads_fov_enabled = self.var_trigger_ads_fov_enabled.get()
        if hasattr(self, "tracker"):
            self.tracker.trigger_ads_fov_enabled = config.trigger_ads_fov_enabled
        if str(getattr(self, "_active_tab_name", "")) == "Trigger":
            self._show_tb_tab()

    def _on_trigger_ads_fovsize_changed(self, val):
        config.trigger_ads_fovsize = val
        if hasattr(self, "tracker"):
            self.tracker.trigger_ads_fovsize = val

    def _on_trigger_ads_key_type_selected(self, val):
        config.trigger_ads_key_type = ADS_KEY_TYPE_DISPLAY_TO_VALUE.get(str(val), "hold")
        if hasattr(self, "tracker"):
            self.tracker.trigger_ads_key_type = config.trigger_ads_key_type
        self._log_config(f"Trigger ADS Key Type: {val}")

    def _on_enable_magnet_trigger_changed(self):
        config.enable_magnet_trigger = self.var_enable_magnet_trigger.get()

    def _on_magnet_fov_changed(self, val):
        config.magnet_fov = float(val)

    def _on_magnet_pull_x_changed(self, val):
        config.magnet_pull_x = float(val)

    def _on_magnet_pull_y_changed(self, val):
        config.magnet_pull_y = float(val)

    def _on_magnet_fire_radius_changed(self, val):
        config.magnet_fire_radius = float(val)

    def _on_magnet_cooldown_ms_changed(self, val):
        config.magnet_cooldown_ms = float(val)

    def _on_magnet_activation_type_selected(self, val):
        activation_map = {
            "Hold to Enable": "hold_enable",
            "Hold to Disable": "hold_disable",
            "Toggle": "toggle",
        }
        config.magnet_activation_type = activation_map.get(str(val), "hold_enable")
        self._log_config(f"Magnet Trigger Mode: {val}")

    def _on_magnet_mode_selected(self, val):
        config.magnet_mode = self._aim_mode_display_to_value(val)
        if str(getattr(self, "_active_tab_name", "")) == "Magnet Trigger":
            self._show_magnet_trigger_tab()

    def _on_magnet_trigger_type_selected(self, val):
        trigger_map = {
            "Classic Trigger": "current",
            "RGB Trigger": "rgb",
        }
        config.magnet_trigger_type = trigger_map.get(str(val), "current")
        if str(getattr(self, "_active_tab_name", "")) == "Magnet Trigger":
            self._show_magnet_trigger_tab()

    def _on_magnet_rgb_color_profile_selected(self, val):
        profile_map = {
            "Red": "red",
            "Yellow": "yellow",
            "Purple": "purple",
            "Custom": "custom",
        }
        config.magnet_rgb_color_profile = profile_map.get(str(val), "purple")
        if str(getattr(self, "_active_tab_name", "")) == "Magnet Trigger":
            self._show_magnet_trigger_tab()

    def _on_tbhold_changed(self, val):
        config.tbhold = val
        self.tracker.tbhold = val
    
    def _on_enableaim_changed(self): 
        config.enableaim = self.var_enableaim.get()

    def _on_ads_fov_enabled_changed(self):
        config.ads_fov_enabled = self.var_ads_fov_enabled.get()
        if hasattr(self, "tracker"):
            self.tracker.ads_fov_enabled = config.ads_fov_enabled
        if str(getattr(self, "_active_tab_name", "")) == "Main Aimbot":
            self._show_aimbot_tab()

    def _on_ads_fovsize_changed(self, val):
        config.ads_fovsize = val
        if hasattr(self, "tracker"):
            self.tracker.ads_fovsize = val
    
    def _on_anti_smoke_changed(self):
        """Main Aimbot Anti-Smoke 闁嬮棞鍥炶"""
        config.anti_smoke_enabled = self.var_anti_smoke.get()
        if hasattr(self.tracker, 'anti_smoke_detector'):
            self.tracker.anti_smoke_detector.set_enabled(config.anti_smoke_enabled)
    
    def _on_enabletb_changed(self): 
        config.enabletb = self.var_enabletb.get()
    
    def _on_enablercs_changed(self):
        """RCS 闁嬮棞鏀硅畩"""
        config.enablercs = self.var_enablercs.get()
    
    def _on_rcs_pull_speed_changed(self, val):
        """RCS Pull Speed 鏀硅畩"""
        config.rcs_pull_speed = int(val)
        if hasattr(self, 'tracker'):
            self.tracker.rcs_pull_speed = int(val)
    
    def _on_rcs_activation_delay_changed(self, val):
        """RCS Activation Delay 鏀硅畩"""
        config.rcs_activation_delay = int(val)
        if hasattr(self, 'tracker'):
            self.tracker.rcs_activation_delay = int(val)
    
    def _on_rcs_rapid_click_threshold_changed(self, val):
        """RCS Rapid Click Threshold 鏀硅畩"""
        config.rcs_rapid_click_threshold = int(val)
        if hasattr(self, 'tracker'):
            self.tracker.rcs_rapid_click_threshold = int(val)
    
    def _on_rcs_release_y_enabled_changed(self):
        """RCS Release Y-Axis 闁嬮棞鏀硅畩"""
        config.rcs_release_y_enabled = self.var_rcs_release_y_enabled.get()
    
    def _on_rcs_release_y_duration_changed(self, val):
        """RCS Release Y-Axis Duration 鏀硅畩"""
        config.rcs_release_y_duration = float(val)
    
    def _on_color_selected(self, val): 
        config.color = val
        self.tracker.color = val
        # 瀵︽檪閲嶆柊杓夊叆妯″瀷浠ユ噳鐢ㄦ柊鐨勯鑹茶ō瀹?
        from src.utils.detection import reload_model
        self.tracker.model, self.tracker.class_names = reload_model()
        # 鏇存柊 Custom HSV 鍗€濉婄殑鍙鎬?
        self._update_custom_hsv_visibility()
    
    def _update_custom_hsv_visibility(self):
        """Show or hide Custom HSV section based on selected color."""
        current_color = getattr(config, "color", "yellow")
        is_custom = current_color == "custom"

        if hasattr(self, 'custom_hsv_container'):
            if is_custom:
                if not self.custom_hsv_container.winfo_ismapped():
                    self.custom_hsv_container.pack(fill="x", pady=(5, 0))
            else:
                if self.custom_hsv_container.winfo_ismapped():
                    self.custom_hsv_container.pack_forget()

    def _on_custom_hsv_changed(self, key, val):
        """Custom HSV 鍊兼敼璁婃檪鐨勫洖瑾?"""
        setattr(config, key, int(val))
        # 濡傛灉鐣跺墠閬告搰鐨勬槸 custom锛屽鏅傞噸鏂拌級鍏ユā鍨?
        if getattr(config, "color", "yellow") == "custom":
            from src.utils.detection import reload_model
            if hasattr(self, 'tracker'):
                self.tracker.model, self.tracker.class_names = reload_model()
                log_print(f"[UI] Custom HSV updated: {key} = {int(val)}")
    
    def _update_custom_rgb_visibility(self):
        """Show or hide Custom RGB section based on selected RGB profile."""
        current_rgb_profile = str(getattr(config, "rgb_color_profile", "purple")).strip().lower()
        is_custom = current_rgb_profile == "custom"

        if hasattr(self, 'custom_rgb_container'):
            if is_custom:
                if not self.custom_rgb_container.winfo_ismapped():
                    self.custom_rgb_container.pack(fill="x", pady=(5, 0))
            else:
                if self.custom_rgb_container.winfo_ismapped():
                    self.custom_rgb_container.pack_forget()
    
    def _get_rgb_color_hex(self):
        """Get current RGB color as hex string."""
        r = max(0, min(255, int(getattr(config, "rgb_custom_r", 161))))
        g = max(0, min(255, int(getattr(config, "rgb_custom_g", 69))))
        b = max(0, min(255, int(getattr(config, "rgb_custom_b", 163))))
        return f"#{r:02x}{g:02x}{b:02x}"
    
    def _update_rgb_color_preview(self):
        """Update RGB color preview box."""
        if hasattr(self, "rgb_color_preview"):
            try:
                color_hex = self._get_rgb_color_hex()
                self.rgb_color_preview.configure(fg_color=color_hex)
            except Exception as e:
                log_print(f"[UI] Failed to update RGB color preview: {e}")
    
    def _on_rgb_custom_changed(self, key, val):
        """Custom RGB 值改變時的回調"""
        setattr(config, key, int(val))
        # 確保值在有效範圍內
        setattr(config, key, max(0, min(255, int(val))))
        if hasattr(self, "tracker"):
            self.tracker.rgb_color_profile = config.rgb_color_profile
        # Update color preview
        self._update_rgb_color_preview()
        log_print(f"[UI] Custom RGB updated: {key} = {int(val)}")
    
    def _open_hsv_preview(self):
        """Abre a janela de preview HSV em tempo real."""
        if hasattr(self, '_hsv_preview_window') and self._hsv_preview_window is not None:
            try:
                if self._hsv_preview_window.winfo_exists():
                    self._hsv_preview_window.lift()
                    self._hsv_preview_window.focus_force()
                    return
            except Exception:
                pass

        def _on_apply():
            # Recarrega o modelo de detecao com os novos valores
            if getattr(config, 'color', 'yellow') == 'custom':
                from src.utils.detection import reload_model
                if hasattr(self, 'tracker'):
                    self.tracker.model, self.tracker.class_names = reload_model()
                    log_print('[UI] Custom HSV aplicado via Preview.')
            # Atualiza os sliders da UI principal
            self._sync_hsv_sliders_from_config()

        self._hsv_preview_window = HsvPreviewWindow(
            self, self.capture, on_apply_callback=_on_apply
        )

    def _sync_hsv_sliders_from_config(self):
        """Atualiza os sliders HSV da UI principal a partir do config."""
        keys = [
            ('custom_hsv_min_h', 0), ('custom_hsv_min_s', 0), ('custom_hsv_min_v', 0),
            ('custom_hsv_max_h', 179), ('custom_hsv_max_s', 255), ('custom_hsv_max_v', 255),
        ]
        for key, default in keys:
            val = int(getattr(config, key, default))
            self._set_slider_value(key, val)

    def _on_detection_merge_distance_changed(self, val):
        """Detection Merge Distance 鏀硅畩鏅傜殑鍥炶"""
        config.detection_merge_distance = int(val)
        log_print(f"[UI] Detection merge distance updated: {int(val)}")
    
    def _on_detection_min_contour_points_changed(self, val):
        """Detection Min Contour Points 鏀硅畩鏅傜殑鍥炶"""
        config.detection_min_contour_points = int(val)
        log_print(f"[UI] Detection min contour points updated: {int(val)}")
    
    def _on_mode_selected(self, val): 
        mode_value = self._aim_mode_display_to_value(val)
        config.mode = mode_value
        self.tracker.mode = mode_value
        self._reset_aim_state_after_mode_change(is_sec=False)
        if self._simple_mode:
            from src.ui_modes.simple_dashboard import refresh_simple_dashboard

            refresh_simple_dashboard(self, {"mode"})
            return
        # 閲嶆柊娓叉煋 Aimbot tab 浠ラ’绀哄皪鎳夋ā寮忕殑鍙冩暩
        self._show_aimbot_tab()
        # 閲嶆柊楂樹寒姝ｇ⒑鐨勫皫鑸寜閳?
        self._set_nav_active("Main Aimbot")
    
    def _on_mode_sec_selected(self, val):
        mode_value = self._aim_mode_display_to_value(val)
        config.mode_sec = mode_value
        self.tracker.mode_sec = mode_value
        self._reset_aim_state_after_mode_change(is_sec=True)
        if self._simple_mode:
            from src.ui_modes.simple_dashboard import refresh_simple_dashboard

            refresh_simple_dashboard(self, {"mode_sec"})
            return
        # 閲嶆柊娓叉煋 Sec Aimbot tab 浠ラ’绀哄皪鎳夋ā寮忕殑鍙冩暩
        self._show_sec_aimbot_tab()
        # 閲嶆柊楂樹寒姝ｇ⒑鐨勫皫鑸寜閳?
        self._set_nav_active("Sec Aimbot")

    def _reset_aim_state_after_mode_change(self, is_sec):
        """Drop stale per-mode state so a newly selected mode starts clean.

        Without this, a spent flick budget or a PID integrator from the previous
        mode leaks into the new one.
        """
        try:
            from src.aim_system.normal import reset_aim_state

            reset_aim_state(self.tracker, is_sec=is_sec)
        except Exception as e:
            log_print(f"[UI] aim state reset error: {e}")
    
    # Sec Aimbot Callbacks
    def _on_normal_x_speed_sec_changed(self, val): 
        config.normal_x_speed_sec = val
        self.tracker.normal_x_speed_sec = val
    
    def _on_normal_y_speed_sec_changed(self, val): 
        config.normal_y_speed_sec = val
        self.tracker.normal_y_speed_sec = val
    
    def _on_config_normal_smooth_sec_changed(self, val): 
        config.normalsmooth_sec = val
        self.tracker.normalsmooth_sec = val
    
    def _on_config_normal_smoothfov_sec_changed(self, val): 
        config.normalsmoothfov_sec = val
        self.tracker.normalsmoothfov_sec = val

    def _on_flick_strength_x_sec_changed(self, val):
        self._on_flick_param_changed("flick_gain_sec", val)
        config.flick_strength_x_sec = float(val)

    def _on_flick_strength_y_sec_changed(self, val):
        config.flick_strength_y_sec = float(val)

    def _on_fovsize_sec_changed(self, val): 
        config.fovsize_sec = val
        self.tracker.fovsize_sec = val
        self._refresh_pid_preview_if_pid_mode(is_sec=True)
    
    def _on_aim_offsetX_sec_changed(self, val):
        config.aim_offsetX_sec = val
    
    def _on_aim_offsetY_sec_changed(self, val):
        config.aim_offsetY_sec = val
    
    def _on_aim_type_sec_selected(self, val):
        config.aim_type_sec = val
    
    def _on_enableaim_sec_changed(self): 
        config.enableaim_sec = self.var_enableaim_sec.get()

    def _on_ads_fov_enabled_sec_changed(self):
        config.ads_fov_enabled_sec = self.var_ads_fov_enabled_sec.get()
        if hasattr(self, "tracker"):
            self.tracker.ads_fov_enabled_sec = config.ads_fov_enabled_sec
        if str(getattr(self, "_active_tab_name", "")) == "Sec Aimbot":
            self._show_sec_aimbot_tab()

    def _on_ads_fovsize_sec_changed(self, val):
        config.ads_fovsize_sec = val
        if hasattr(self, "tracker"):
            self.tracker.ads_fovsize_sec = val
    
    def _on_anti_smoke_sec_changed(self):
        """Secondary Aimbot Anti-Smoke 闁嬮棞鍥炶"""
        config.anti_smoke_enabled_sec = self.var_anti_smoke_sec.get()
        if hasattr(self.tracker, 'anti_smoke_detector_sec'):
            self.tracker.anti_smoke_detector_sec.set_enabled(config.anti_smoke_enabled_sec)
    
    # === NCAF Callbacks (Main) ===
    def _on_ncaf_near_radius_changed(self, val):
        config.ncaf_near_radius = val
        snap = getattr(config, "ncaf_snap_radius", val)
        # Snap 鎳夊ぇ鏂?Near锛涜嫢涓嶇鍓囪嚜鍕曞線涓婅鏁翠甫鍚屾 UI
        if snap <= val:
            snap = min(500, val + 1)
            config.ncaf_snap_radius = snap
            self._set_slider_value("ncaf_snap_radius", snap)
    
    def _on_ncaf_snap_radius_changed(self, val):
        config.ncaf_snap_radius = val
        near = getattr(config, "ncaf_near_radius", val)
        if val <= near:
            near = max(5, val - 1)
            config.ncaf_near_radius = near
            self._set_slider_value("ncaf_near_radius", near)
    
    def _on_ncaf_alpha_changed(self, val):
        config.ncaf_alpha = val
    
    def _on_ncaf_snap_boost_changed(self, val):
        config.ncaf_snap_boost = val
    
    def _on_ncaf_max_step_changed(self, val):
        config.ncaf_max_step = val
    
    def _on_ncaf_min_speed_multiplier_changed(self, val):
        config.ncaf_min_speed_multiplier = val
    
    def _on_ncaf_max_speed_multiplier_changed(self, val):
        config.ncaf_max_speed_multiplier = val
    
    def _on_ncaf_prediction_interval_changed(self, val):
        config.ncaf_prediction_interval = val / 1000.0  # ms 鈫?s
    
    # === NCAF Callbacks (Sec) ===
    def _on_ncaf_near_radius_sec_changed(self, val):
        config.ncaf_near_radius_sec = val
        snap = getattr(config, "ncaf_snap_radius_sec", val)
        if snap <= val:
            snap = min(500, val + 1)
            config.ncaf_snap_radius_sec = snap
            self._set_slider_value("ncaf_snap_radius_sec", snap)
    
    def _on_ncaf_snap_radius_sec_changed(self, val):
        config.ncaf_snap_radius_sec = val
        near = getattr(config, "ncaf_near_radius_sec", val)
        if val <= near:
            near = max(5, val - 1)
            config.ncaf_near_radius_sec = near
            self._set_slider_value("ncaf_near_radius_sec", near)
    
    def _on_ncaf_alpha_sec_changed(self, val):
        config.ncaf_alpha_sec = val
    
    def _on_ncaf_snap_boost_sec_changed(self, val):
        config.ncaf_snap_boost_sec = val
    
    def _on_ncaf_max_step_sec_changed(self, val):
        config.ncaf_max_step_sec = val
    
    def _on_ncaf_min_speed_multiplier_sec_changed(self, val):
        config.ncaf_min_speed_multiplier_sec = val
    
    def _on_ncaf_max_speed_multiplier_sec_changed(self, val):
        config.ncaf_max_speed_multiplier_sec = val
    
    def _on_ncaf_prediction_interval_sec_changed(self, val):
        config.ncaf_prediction_interval_sec = val / 1000.0  # ms 鈫?s
    
    # === WindMouse Callbacks (Main) ===
    def _on_wm_gravity_changed(self, val):
        config.wm_gravity = val
    
    def _on_wm_wind_changed(self, val):
        config.wm_wind = val
    
    def _on_wm_max_step_changed(self, val):
        config.wm_max_step = val
    
    def _on_wm_min_step_changed(self, val):
        config.wm_min_step = val
    
    def _on_wm_min_delay_changed(self, val):
        config.wm_min_delay = val / 1000.0  # ms 鈫?s
    
    def _on_wm_max_delay_changed(self, val):
        config.wm_max_delay = val / 1000.0  # ms 鈫?s
    
    def _on_wm_distance_threshold_changed(self, val):
        config.wm_distance_threshold = val
    
    # === WindMouse Callbacks (Sec) ===
    def _on_wm_gravity_sec_changed(self, val):
        config.wm_gravity_sec = val
    
    def _on_wm_wind_sec_changed(self, val):
        config.wm_wind_sec = val
    
    def _on_wm_max_step_sec_changed(self, val):
        config.wm_max_step_sec = val
    
    def _on_wm_min_step_sec_changed(self, val):
        config.wm_min_step_sec = val
    
    def _on_wm_min_delay_sec_changed(self, val):
        config.wm_min_delay_sec = val / 1000.0  # ms 鈫?s
    
    def _on_wm_max_delay_sec_changed(self, val):
        config.wm_max_delay_sec = val / 1000.0  # ms 鈫?s
    
    def _on_wm_distance_threshold_sec_changed(self, val):
        config.wm_distance_threshold_sec = val
    
    # --- Bezier Callbacks (Main) ---
    def _on_bezier_segments_changed(self, val):
        config.bezier_segments = int(val)
    
    def _on_bezier_ctrl_x_changed(self, val):
        config.bezier_ctrl_x = float(val)
    
    def _on_bezier_ctrl_y_changed(self, val):
        config.bezier_ctrl_y = float(val)
    
    def _on_bezier_speed_changed(self, val):
        config.bezier_speed = float(val)
    
    def _on_bezier_delay_changed(self, val):
        config.bezier_delay = float(val) / 1000.0  # ms 鈫?s
    
    # --- Bezier Callbacks (Sec) ---
    def _on_bezier_segments_sec_changed(self, val):
        config.bezier_segments_sec = int(val)
    
    def _on_bezier_ctrl_x_sec_changed(self, val):
        config.bezier_ctrl_x_sec = float(val)
    
    def _on_bezier_ctrl_y_sec_changed(self, val):
        config.bezier_ctrl_y_sec = float(val)
    
    def _on_bezier_speed_sec_changed(self, val):
        config.bezier_speed_sec = float(val)
    
    def _on_bezier_delay_sec_changed(self, val):
        config.bezier_delay_sec = float(val) / 1000.0  # ms 鈫?s
    
    # --- PID Callbacks (Main) ---
    def _on_pid_kp_changed(self, val):
        # Legacy callback compatibility: keep fixed Kp by syncing min/max.
        kp = float(val)
        config.pid_kp = kp
        config.pid_kp_min = kp
        config.pid_kp_max = kp
        self._refresh_pid_preview(is_sec=False)

    def _on_pid_kp_min_changed(self, val):
        kp_min = float(val)
        config.pid_kp_min = kp_min
        if float(getattr(config, "pid_kp_max", kp_min)) < kp_min:
            config.pid_kp_max = kp_min
            self._set_slider_value("pid_kp_max", kp_min)
        self._refresh_pid_preview(is_sec=False)

    def _on_pid_kp_max_changed(self, val):
        kp_max = float(val)
        config.pid_kp_max = kp_max
        if float(getattr(config, "pid_kp_min", kp_max)) > kp_max:
            config.pid_kp_min = kp_max
            self._set_slider_value("pid_kp_min", kp_max)
        self._refresh_pid_preview(is_sec=False)

    def _on_pid_ki_changed(self, val):
        config.pid_ki = float(val)
        self._refresh_pid_preview(is_sec=False)

    def _on_pid_kd_changed(self, val):
        config.pid_kd = float(val)
        self._refresh_pid_preview(is_sec=False)

    def _on_pid_max_output_changed(self, val):
        config.pid_max_output = float(val)
        self._refresh_pid_preview(is_sec=False)

    def _on_pid_x_speed_changed(self, val):
        config.pid_x_speed = float(val)
        self._refresh_pid_preview(is_sec=False)

    def _on_pid_y_speed_changed(self, val):
        config.pid_y_speed = float(val)
        self._refresh_pid_preview(is_sec=False)

    # --- PID Callbacks (Sec) ---
    def _on_pid_kp_sec_changed(self, val):
        # Legacy callback compatibility: keep fixed Kp by syncing min/max.
        kp = float(val)
        config.pid_kp_sec = kp
        config.pid_kp_min_sec = kp
        config.pid_kp_max_sec = kp
        self._refresh_pid_preview(is_sec=True)

    def _on_pid_kp_min_sec_changed(self, val):
        kp_min = float(val)
        config.pid_kp_min_sec = kp_min
        if float(getattr(config, "pid_kp_max_sec", kp_min)) < kp_min:
            config.pid_kp_max_sec = kp_min
            self._set_slider_value("pid_kp_max_sec", kp_min)
        self._refresh_pid_preview(is_sec=True)

    def _on_pid_kp_max_sec_changed(self, val):
        kp_max = float(val)
        config.pid_kp_max_sec = kp_max
        if float(getattr(config, "pid_kp_min_sec", kp_max)) > kp_max:
            config.pid_kp_min_sec = kp_max
            self._set_slider_value("pid_kp_min_sec", kp_max)
        self._refresh_pid_preview(is_sec=True)

    def _on_pid_ki_sec_changed(self, val):
        config.pid_ki_sec = float(val)
        self._refresh_pid_preview(is_sec=True)

    def _on_pid_kd_sec_changed(self, val):
        config.pid_kd_sec = float(val)
        self._refresh_pid_preview(is_sec=True)

    def _on_pid_max_output_sec_changed(self, val):
        config.pid_max_output_sec = float(val)
        self._refresh_pid_preview(is_sec=True)

    def _on_pid_x_speed_sec_changed(self, val):
        config.pid_x_speed_sec = float(val)
        self._refresh_pid_preview(is_sec=True)

    def _on_pid_y_speed_sec_changed(self, val):
        config.pid_y_speed_sec = float(val)
        self._refresh_pid_preview(is_sec=True)

    def _on_aimbot_button_selected(self, val):
        for k, name in BUTTONS.items():
            if name == val:
                config.selected_mouse_button = k
                if hasattr(self, "tracker"):
                    self.tracker.selected_mouse_button = k
                self._log_config(f"Aim Key: {val}")
                break

    def _on_ads_key_selected(self, val):
        config.ads_key = self._ads_display_to_binding(val)
        if hasattr(self, "tracker"):
            self.tracker.ads_key = config.ads_key
        self._log_config(f"ADS Key: {val}")

    def _on_ads_key_type_selected(self, val):
        config.ads_key_type = ADS_KEY_TYPE_DISPLAY_TO_VALUE.get(str(val), "hold")
        self._log_config(f"ADS Key Type: {val}")
    
    def _on_aimbot_activation_type_selected(self, val):
        activation_type_map = {
            "Hold to Enable": "hold_enable",
            "Hold to Disable": "hold_disable",
            "Toggle": "toggle",
            "Press to Enable": "use_enable"
        }
        config.aimbot_activation_type = activation_type_map.get(val, "hold_enable")
        self._log_config(f"Aim Activation Type: {val}")

    def _on_trigger_type_selected(self, val):
        trigger_type_map = {
            "Classic Trigger": "current",
            "Current": "current",
            "RGB Trigger": "rgb",
        }
        new_trigger_type = trigger_type_map.get(val, "current")
        old_trigger_type = str(getattr(config, "trigger_type", "current")).strip().lower()
        config.trigger_type = new_trigger_type
        self._log_config(f"Trigger Type: {val}")
        # Rebuild tab to show mode-specific controls immediately.
        if new_trigger_type != old_trigger_type:
            self._show_tb_tab()

    def _on_rgb_color_profile_selected(self, val):
        rgb_profile_map = {
            "Red": "red",
            "Yellow": "yellow",
            "Purple": "purple",
            "Custom": "custom",
        }
        config.rgb_color_profile = rgb_profile_map.get(val, "purple")
        # Reuse the same global custom HSV profile used by main color selection.
        if config.rgb_color_profile == "custom":
            config.color = "custom"
            if hasattr(self, "tracker"):
                self.tracker.color = "custom"
        if hasattr(self, "tracker"):
            self.tracker.rgb_color_profile = config.rgb_color_profile
        self._log_config(f"RGB Preset: {val}")
        # Update Custom RGB section visibility
        self._update_custom_rgb_visibility()

    def _on_tb_button_selected(self, val):
        for k, name in BUTTONS.items():
            if name == val:
                config.selected_tb_btn = k
                self._log_config(f"Trigger Key: {val}")
                break

    def _on_trigger_activation_type_selected(self, val):
        trigger_activation_map = {
            "Hold to Enable": "hold_enable",
            "Hold to Disable": "hold_disable",
            "Toggle": "toggle",
            # backward compatibility for older saved labels
            "按下啟用": "hold_enable",
            "按下禁用": "hold_disable",
            "切換": "toggle",
        }
        config.trigger_activation_type = trigger_activation_map.get(val, "hold_enable")
        self._log_config(f"Trigger Mode: {val}")

    def _on_trigger_strafe_mode_selected(self, val):
        trigger_strafe_mode_map = {
            "Off": "off",
            "Auto Strafe": "auto",
            "Manual Wait": "manual_wait",
        }
        selected_mode = trigger_strafe_mode_map.get(str(val), "off")
        if selected_mode != "off" and not self._supports_trigger_strafe_ui():
            selected_mode = "off"
        old_mode = str(getattr(config, "trigger_strafe_mode", "off")).strip().lower()
        config.trigger_strafe_mode = selected_mode
        self._log_config(f"Trigger Strafe Mode: {val}")
        if selected_mode != old_mode and str(getattr(self, "_active_tab_name", "")) == "Trigger":
            self._show_tb_tab()

    def _on_trigger_strafe_auto_lead_ms_changed(self, val):
        config.trigger_strafe_auto_lead_ms = int(val)

    def _on_trigger_strafe_manual_neutral_ms_changed(self, val):
        config.trigger_strafe_manual_neutral_ms = int(val)
    
    # Mouse Input Debug Callbacks
    def _on_debug_mouse_input_changed(self):
        """婊戦紶杓稿叆瑾胯│闁嬮棞鏀硅畩"""
        enabled = self.debug_mouse_input_var.get()
        if enabled:
            self.mouse_input_monitor.enable()
            # Show debug area
            if hasattr(self, 'debug_mouse_frame'):
                try:
                    self.debug_mouse_frame.pack(fill="x", pady=10)
                except Exception:
                    pass
        else:
            self.mouse_input_monitor.disable()
            # Hide debug area
            if hasattr(self, 'debug_mouse_frame'):
                try:
                    self.debug_mouse_frame.pack_forget()
                except Exception:
                    pass
    
    def _update_mouse_input_debug(self):
        """瀹氭湡鏇存柊婊戦紶杓稿叆瑾胯│椤ず"""
        # Only update if we're on the Debug tab and the switch is enabled
        try:
            if hasattr(self, 'debug_mouse_input_var') and self.debug_mouse_input_var.get():
                if hasattr(self, 'debug_button_widgets') and self.debug_button_widgets:
                    # Update monitor
                    self.mouse_input_monitor.update()
                    
                    # Update UI display
                    for idx, widgets in self.debug_button_widgets.items():
                        try:
                            state = self.mouse_input_monitor.get_button_state(idx)
                            count = self.mouse_input_monitor.get_button_count(idx)
                            
                            # Update status indicator color (green=pressed, red=not pressed)
                            color = "#4CAF50" if state else "#CF6679"  # Green or red
                            widgets["state_indicator"].configure(text_color=color)
                            
                            # Update count
                            widgets["count_label"].configure(text=f"Count: {count}")
                        except Exception:
                            # Widget might be destroyed, skip this update
                            pass
        except Exception:
            # Tab might have been switched, ignore
            pass

    def _reset_button_count(self, button_idx: int):
        """閲嶇疆鍠€嬫寜閳曠殑瑷堟暩"""
        if hasattr(self.mouse_input_monitor, 'button_counts'):
            self.mouse_input_monitor.button_counts[button_idx] = 0
        if hasattr(self, 'debug_button_widgets') and button_idx in self.debug_button_widgets:
            try:
                self.debug_button_widgets[button_idx]["count_label"].configure(text="Count: 0")
            except Exception:
                pass
    
    def _reset_all_button_counts(self):
        """閲嶇疆鎵€鏈夋寜閳曠殑瑷堟暩"""
        self.mouse_input_monitor.reset_counts()
        if hasattr(self, 'debug_button_widgets'):
            for idx, widgets in self.debug_button_widgets.items():
                try:
                    widgets["count_label"].configure(text="Count: 0")
                except Exception:
                    pass
    
    def _update_debug_log(self):
        """Scheduler branch (100 ms): refresh the log view only when needed.

        The old version fetched 500 entries, formatted every one of them, read
        the whole textbox back and compared strings — 10 times per second, on
        every tab, for a widget that might already have been destroyed. It now
        (plan H2):

        * returns immediately when the Telemetry tab is not the active tab;
        * verifies the widget still exists;
        * only re-formats when the logger's version counter changed.
        """
        textbox = getattr(self, "debug_log_textbox", None)
        if textbox is None:
            return
        if str(getattr(self, "_active_tab_name", "")) not in ("Telemetry", "Debug"):
            return
        try:
            if not textbox.winfo_exists():
                return
        except Exception:
            return

        try:
            version = get_log_version()
        except Exception:
            version = None
        if version is not None and version == getattr(self, "_debug_log_version", None):
            return
        self._debug_log_version = version

        try:
            logs = get_recent_logs(500)
            log_count = get_log_count()
            import datetime

            lines = []
            for log in logs:
                timestamp = datetime.datetime.fromtimestamp(log["timestamp"]).strftime(
                    "%H:%M:%S.%f"
                )[:-3]
                log_type = log["type"]
                source = log.get("source", "Unknown")
                if log_type == "MOVE":
                    dx = log.get("dx", 0)
                    dy = log.get("dy", 0)
                    lines.append(
                        f"[{timestamp}] {log_type:8s} [{source:15s}] "
                        f"dx={dx:8.2f}, dy={dy:8.2f}"
                    )
                    continue
                message = str(log.get("message", ""))
                if message:
                    lines.append(f"[{timestamp}] {log_type:8s} [{source:15s}] {message}")
                else:
                    lines.append(f"[{timestamp}] {log_type:8s} [{source:15s}]")
            log_text = "\n".join(lines)

            textbox.delete("1.0", "end")
            textbox.insert("1.0", log_text)
            textbox.see("end")
            count_label = getattr(self, "debug_log_count_label", None)
            if count_label is not None:
                count_label.configure(text=f"Log Count: {log_count}")
        except Exception:
            # Tab switch or shutdown destroys the widgets mid-update.
            pass
    
    def _clear_debug_log(self):
        """娓呯┖ Debug 鏃ヨ獙"""
        clear_logs()
        if hasattr(self, 'debug_log_textbox'):
            try:
                self.debug_log_textbox.delete("1.0", "end")
            except Exception:
                pass
        if hasattr(self, 'debug_log_count_label'):
            try:
                self.debug_log_count_label.configure(text="Log Count: 0")
            except Exception:
                pass
    
    def _on_aimbot_button_sec_selected(self, val):
        for k, name in BUTTONS.items():
            if name == val:
                config.selected_mouse_button_sec = k
                self.tracker.selected_mouse_button_sec = k
                break

    def _on_ads_key_sec_selected(self, val):
        config.ads_key_sec = self._ads_display_to_binding(val)
        if hasattr(self, "tracker"):
            self.tracker.ads_key_sec = config.ads_key_sec
        self._log_config(f"Sec ADS Key: {val}")

    def _on_ads_key_type_sec_selected(self, val):
        config.ads_key_type_sec = ADS_KEY_TYPE_DISPLAY_TO_VALUE.get(str(val), "hold")
        self._log_config(f"Sec ADS Key Type: {val}")
    
    def _on_aimbot_activation_type_sec_selected(self, val):
        activation_type_map = {
            "Hold to Enable": "hold_enable",
            "Hold to Disable": "hold_disable",
            "Toggle": "toggle",
            "Press to Enable": "use_enable"
        }
        config.aimbot_activation_type_sec = activation_type_map.get(val, "hold_enable")
        self._log_config(f"Sec Aim Activation Type: {val}")
    
    def _on_button_mask_enabled_changed(self):
        """Button Mask 绺介枊闂滃洖瑾?"""
        config.button_mask_enabled = self.var_button_mask_enabled.get()
    
    def _on_button_mask_changed(self, key, var):
        """鍠€嬫寜閳?Mask 鐙€鎱嬫敼璁婂洖瑾?"""
        value = var.get()
        setattr(config, key, value)
        button_names = {
            "mask_left_button": "Left (L)",
            "mask_right_button": "Right (R)",
            "mask_middle_button": "Middle (M)",
            "mask_side4_button": "Side 4 (S4)",
            "mask_side5_button": "Side 5 (S5)"
        }
    
    def _on_mouse_lock_main_x_changed(self):
        """Mouse Lock Main Aimbot X-Axis 闁嬮棞鍥炶"""
        try:
            config.mouse_lock_main_x = self.var_mouse_lock_main_x.get()
            # 涓嶅湪姝よ檿瑾跨敤 tick锛岃畵涓诲惊鐠拌檿鐞嗭紝閬垮厤闃诲 UI 绶氱▼
        except Exception as e:
            log_print(f"[Mouse Lock] Error in main_x callback: {e}")
    
    def _on_mouse_lock_main_y_changed(self):
        """Mouse Lock Main Aimbot Y-Axis 闁嬮棞鍥炶"""
        try:
            config.mouse_lock_main_y = self.var_mouse_lock_main_y.get()
            # 涓嶅湪姝よ檿瑾跨敤 tick锛岃畵涓诲惊鐠拌檿鐞嗭紝閬垮厤闃诲 UI 绶氱▼
        except Exception as e:
            log_print(f"[Mouse Lock] Error in main_y callback: {e}")
    
    def _on_mouse_lock_sec_x_changed(self):
        """Mouse Lock Sec Aimbot X-Axis 闁嬮棞鍥炶"""
        try:
            config.mouse_lock_sec_x = self.var_mouse_lock_sec_x.get()
            # 涓嶅湪姝よ檿瑾跨敤 tick锛岃畵涓诲惊鐠拌檿鐞嗭紝閬垮厤闃诲 UI 绶氱▼
        except Exception as e:
            log_print(f"[Mouse Lock] Error in sec_x callback: {e}")
    
    def _on_mouse_lock_sec_y_changed(self):
        """Mouse Lock Sec Aimbot Y-Axis 闁嬮棞鍥炶"""
        try:
            config.mouse_lock_sec_y = self.var_mouse_lock_sec_y.get()
            # 涓嶅湪姝よ檿瑾跨敤 tick锛岃畵涓诲惊鐠拌檿鐞嗭紝閬垮厤闃诲 UI 绶氱▼
        except Exception as e:
            log_print(f"[Mouse Lock] Error in sec_y callback: {e}")
    
    def _check_for_updates(self):
        """Check for updates in background"""
        if getattr(self.update_checker, "never_update", False):
            return
        if self._update_check_in_progress:
            return
        self._update_check_in_progress = True
        threading.Thread(target=self._check_for_updates_worker, daemon=True).start()

    def _check_for_updates_worker(self):
        try:
            if getattr(self.update_checker, "never_update", False):
                return
            has_update, latest_version, update_info = self.update_checker.check_update()
            if has_update and not getattr(self.update_checker, "never_update", False):
                self.after(0, lambda: self._show_update_dialog(latest_version, update_info))
        except Exception as e:
            log_print(f"[Update] Failed to check for updates: {e}")
        finally:
            self._update_check_in_progress = False
    
    def _show_update_dialog(self, latest_version, update_info):
        """Show update dialog with update information"""
        if getattr(self.update_checker, "never_update", False):
            return
        UpdateDialog(self, latest_version, update_info)


class UpdateDialog(ctk.CTkToplevel):
    """Simple update prompt dialog."""

    def __init__(self, parent, latest_version, update_info):
        super().__init__(parent)
        self.parent = parent
        self.latest_version = str(latest_version or "unknown")
        self.update_info = update_info if isinstance(update_info, dict) else {}

        self.title("Update Available")
        self.geometry("580x380")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.update_idletasks()
        x = parent.winfo_x() + max(0, (parent.winfo_width() - 580) // 2)
        y = parent.winfo_y() + max(0, (parent.winfo_height() - 380) // 2)
        self.geometry(f"+{x}+{y}")

        self._build_ui()

    def _pick_text(self):
        for key in ("notes", "changelog", "description", "message"):
            value = self.update_info.get(key)
            if isinstance(value, str) and value.strip():
                return self._format_text(value.strip())
        return "A new version is available."
    
    def _format_text(self, text: str) -> str:
        """Format update text with proper line breaks and spacing."""
        if not text:
            return text
        
        # Split by lines first
        lines = text.split('\n')
        formatted_lines = []
        prev_was_version_header = False
        
        for i, line in enumerate(lines):
            original_line = line
            line = line.strip()
            
            if not line:
                # Preserve intentional empty lines, but skip if previous was already empty
                if formatted_lines and formatted_lines[-1]:
                    formatted_lines.append('')
                continue
            
            # Check if this line is a version header
            # Patterns: **Version X.X.X:**, Version X.X.X:, **vX.X.X:**, etc.
            is_version_header = (
                ('**Version' in line and ':**' in line) or
                (line.startswith('Version') and ':' in line and any(c.isdigit() for c in line)) or
                ('**v' in line and ':**' in line) or
                (line.startswith('v') and ':' in line and any(c.isdigit() for c in line))
            )
            
            # Add spacing before version headers (except the first one)
            if is_version_header:
                if formatted_lines and formatted_lines[-1] and not prev_was_version_header:
                    formatted_lines.append('')  # Add empty line before version header
                prev_was_version_header = True
            else:
                prev_was_version_header = False
            
            # Remove markdown bold markers for cleaner display
            formatted_line = line.replace('**', '')
            
            formatted_lines.append(formatted_line)
        
        # Join with newlines
        result = '\n'.join(formatted_lines)
        
        # Clean up excessive empty lines (max 2 consecutive empty lines)
        while '\n\n\n' in result:
            result = result.replace('\n\n\n', '\n\n')
        
        return result.strip()

    def _pick_repo_base_url(self):
        for key in ("repo_url", "repository_url"):
            value = self.update_info.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value.rstrip("/")
        return "https://github.com/asenyeroao-ct/CVM-colorBot"

    def _pick_release_url(self):
        for key in ("release_url", "url"):
            value = self.update_info.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
        return f"{self._pick_repo_base_url()}/commits/main"

    def _pick_download_url(self):
        value = self.update_info.get("download_url")
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
        return f"{self._pick_repo_base_url()}/archive/refs/heads/main.zip"

    def _build_ui(self):
        frame = ctk.CTkFrame(self, fg_color=COLOR_BG, corner_radius=0)
        frame.pack(fill="both", expand=True)

        ctk.CTkLabel(
            frame,
            text=f"New Version: v{self.latest_version}",
            font=("Roboto", 16, "bold"),
            text_color=COLOR_TEXT,
        ).pack(anchor="w", padx=20, pady=(18, 8))

        notes_box = ctk.CTkTextbox(
            frame,
            fg_color=COLOR_SURFACE,
            text_color=COLOR_TEXT,
            border_width=0,
            corner_radius=8,
            height=220,
            wrap="word",  # Enable word wrapping
        )
        notes_box.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        
        # Insert formatted text with proper spacing
        formatted_text = self._pick_text()
        notes_box.insert("1.0", formatted_text)
        notes_box.configure(state="disabled")

        btn_row = ctk.CTkFrame(frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 18))

        ctk.CTkButton(
            btn_row,
            text="Later",
            command=self.destroy,
            fg_color="transparent",
            border_width=1,
            border_color=COLOR_BORDER,
            hover_color=COLOR_SURFACE,
            text_color=COLOR_TEXT_DIM,
            width=90,
        ).pack(side="left")

        ctk.CTkButton(
            btn_row,
            text="Skip This",
            command=self._on_skip,
            fg_color="transparent",
            border_width=1,
            border_color=COLOR_BORDER,
            hover_color=COLOR_SURFACE,
            text_color=COLOR_TEXT_DIM,
            width=100,
        ).pack(side="left", padx=(10, 0))

        ctk.CTkButton(
            btn_row,
            text="Never Check",
            command=self._on_never,
            fg_color="transparent",
            border_width=1,
            border_color=COLOR_BORDER,
            hover_color=COLOR_SURFACE,
            text_color=COLOR_DANGER,
            width=110,
        ).pack(side="left", padx=(10, 0))

        download_url = self._pick_download_url()
        release_url = self._pick_release_url()

        if download_url:
            # Primary action button - Download Update
            ctk.CTkButton(
                btn_row,
                text="Update Now",
                command=lambda: self._open_url(download_url),
                fg_color=COLOR_ACCENT,
                hover_color=COLOR_ACCENT_HOVER,
                text_color=COLOR_BG,
                width=140,
            ).pack(side="right")

        if release_url and release_url != download_url:
            ctk.CTkButton(
                btn_row,
                text="Open Release",
                command=lambda: self._open_url(release_url),
                fg_color="transparent",
                border_width=1,
                border_color=COLOR_BORDER,
                hover_color=COLOR_SURFACE,
                text_color=COLOR_TEXT,
                width=120,
            ).pack(side="right", padx=(10, 0))

    def _on_skip(self):
        try:
            self.parent.update_checker.skip_update()
        except Exception:
            pass
        self.destroy()

    def _on_never(self):
        try:
            self.parent.update_checker.set_never_update(True)
        except Exception:
            pass
        self.destroy()

    def _open_url(self, url: str):
        try:
            webbrowser.open(url, new=2)
        except Exception:
            pass


class SettingsWindow(ctk.CTkToplevel):
    """OpenCV 椤ず瑷疆瑕栫獥"""
    
    def __init__(self, parent):
        super().__init__(parent)
        
        self.parent = parent
        self.title(t("display settings"))
        self.geometry("400x680")
        self.resizable(False, False)
        
        # 缃腑椤ず
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 400) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 500) // 2
        self.geometry(f"+{x}+{y}")
        
        # 瑷疆鐐烘ā鎱嬭绐?
        self.transient(parent)
        self.grab_set()
        
        # 闂滈枆瑕栫獥鏅傝嚜鍕曚繚瀛樿ō缃?
        self.protocol("WM_DELETE_WINDOW", self._on_save)
        
        # 鑷ㄦ檪鍎插瓨瑷疆锛堢敤鏂煎彇娑堬級
        self.temp_settings = {
            "show_opencv_windows": getattr(config, "show_opencv_windows", True),
            "show_opencv_mask": getattr(config, "show_opencv_mask", True),
            "show_opencv_detection": getattr(config, "show_opencv_detection", True),
            "show_opencv_roi": getattr(config, "show_opencv_roi", True),
            "show_opencv_triggerbot_mask": getattr(config, "show_opencv_triggerbot_mask", True),
            "show_ndi_raw_stream_window": getattr(config, "show_ndi_raw_stream_window", False),
            "show_udp_raw_stream_window": getattr(config, "show_udp_raw_stream_window", False),
            "show_mode_text": getattr(config, "show_mode_text", True),
            "show_aimbot_status": getattr(config, "show_aimbot_status", True),
            "show_triggerbot_status": getattr(config, "show_triggerbot_status", True),
            "show_target_count": getattr(config, "show_target_count", True),
            "show_crosshair": getattr(config, "show_crosshair", True),
            "show_distance_text": getattr(config, "show_distance_text", True)
        }
        
        self._build_ui()
    
    def _build_ui(self):
        """妲嬪缓 UI"""
        # 涓诲鍣?- 浣跨敤娣辫壊鑳屾櫙锛屽～婊挎暣鍊嬭绐?
        main_frame = ctk.CTkFrame(self, fg_color=COLOR_BG, corner_radius=0)
        main_frame.pack(fill="both", expand=True, padx=0, pady=0)
        
        # 鍏ч儴瀹瑰櫒 (鐢ㄦ柤鍏у閭婅窛)
        content_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=25, pady=25)
        
        # 妯欓
        title_label = ctk.CTkLabel(
            content_frame,
            text=t("DISPLAY SETTINGS"),
            font=("Roboto", 16, "bold"),
            text_color=COLOR_TEXT
        )
        title_label.pack(pady=(0, 20), anchor="w")

        self._add_section_title(content_frame, "LANGUAGE")
        language_row = ctk.CTkFrame(content_frame, fg_color="transparent")
        language_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            language_row,
            text=t("Language"),
            font=("Roboto", 12),
            text_color=COLOR_TEXT,
        ).pack(side="left")
        language_names = i18n.display_names()
        self.language_option = ctk.CTkOptionMenu(
            language_row,
            values=language_names or ["English"],
            command=self._on_language_changed,
            fg_color=COLOR_SURFACE,
            button_color=COLOR_SURFACE,
            button_hover_color=COLOR_BORDER,
            dropdown_fg_color=COLOR_SURFACE,
            text_color=COLOR_TEXT,
            font=("Roboto", 12),
            width=160,
        )
        self.language_option.pack(side="right")
        self.language_option.set(i18n.name_for_code())

        # 鍒嗙祫1: 鍏ㄥ眬椤ず瑷疆
        self._add_section_title(content_frame, "VISUAL SETTINGS")
        
        # OpenCV 瑕栫獥绺介枊闂?(Switch)
        self.show_opencv_var = tk.BooleanVar(value=self.temp_settings["show_opencv_windows"])
        self._add_switch(content_frame, "Show OpenCV Windows", self.show_opencv_var)

        # 鍒嗛殧
        self._add_spacer(content_frame)
        
        # 鍒嗙祫1.5: OpenCV 瑕栫獥瑭崇窗瑷疆
        self._add_section_title(content_frame, "OPENCV WINDOWS")
        
        # 浣跨敤 Grid 浣堝眬渚嗘帓鍒?OpenCV 瑕栫獥闁嬮棞
        opencv_grid_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        opencv_grid_frame.pack(fill="x", pady=5)
        opencv_grid_frame.grid_columnconfigure(0, weight=1)
        opencv_grid_frame.grid_columnconfigure(1, weight=1)
        
        # 鍚勯爡 OpenCV 瑕栫獥闁嬮棞
        self.show_opencv_mask_var = tk.BooleanVar(value=self.temp_settings["show_opencv_mask"])
        self._add_grid_switch(opencv_grid_frame, "MASK", self.show_opencv_mask_var, 0, 0)
        
        self.show_opencv_detection_var = tk.BooleanVar(value=self.temp_settings["show_opencv_detection"])
        self._add_grid_switch(opencv_grid_frame, "Detection", self.show_opencv_detection_var, 0, 1)
        
        self.show_opencv_roi_var = tk.BooleanVar(value=self.temp_settings["show_opencv_roi"])
        self._add_grid_switch(opencv_grid_frame, "ROI", self.show_opencv_roi_var, 1, 0)
        
        self.show_opencv_triggerbot_mask_var = tk.BooleanVar(value=self.temp_settings["show_opencv_triggerbot_mask"])
        self._add_grid_switch(opencv_grid_frame, "Triggerbot Mask", self.show_opencv_triggerbot_mask_var, 1, 1)

        self.show_ndi_raw_stream_var = tk.BooleanVar(value=self.temp_settings["show_ndi_raw_stream_window"])
        self._add_grid_switch(opencv_grid_frame, "NDI Raw Stream", self.show_ndi_raw_stream_var, 2, 0)

        self.show_udp_raw_stream_var = tk.BooleanVar(value=self.temp_settings["show_udp_raw_stream_window"])
        self._add_grid_switch(opencv_grid_frame, "UDP Raw Stream", self.show_udp_raw_stream_var, 2, 1)

        # 鍒嗛殧
        self._add_spacer(content_frame)
        
        # 鍒嗙祫2: 鏂囧瓧璩囪▕ (Overlay Elements)
        self._add_section_title(content_frame, "OVERLAY ELEMENTS")
        
        # 浣跨敤 Grid 浣堝眬渚嗘帓鍒楅枊闂滐紝浣垮叾鏇存暣榻?
        grid_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        grid_frame.pack(fill="x", pady=5)
        grid_frame.grid_columnconfigure(0, weight=1)
        grid_frame.grid_columnconfigure(1, weight=1)

        # 鍚勯爡闁嬮棞 (Switch instead of Checkbox for better look)
        self.show_mode_var = tk.BooleanVar(value=self.temp_settings["show_mode_text"])
        self._add_grid_switch(grid_frame, "Mode Info", self.show_mode_var, 0, 0)
        
        self.show_aimbot_status_var = tk.BooleanVar(value=self.temp_settings["show_aimbot_status"])
        self._add_grid_switch(grid_frame, "Aim Status", self.show_aimbot_status_var, 0, 1)
        
        self.show_triggerbot_status_var = tk.BooleanVar(value=self.temp_settings["show_triggerbot_status"])
        self._add_grid_switch(grid_frame, "Trigger Status", self.show_triggerbot_status_var, 1, 0)
        
        self.show_target_count_var = tk.BooleanVar(value=self.temp_settings["show_target_count"])
        self._add_grid_switch(grid_frame, "Target Count", self.show_target_count_var, 1, 1)
        
        self.show_crosshair_var = tk.BooleanVar(value=self.temp_settings["show_crosshair"])
        self._add_grid_switch(grid_frame, "Crosshair", self.show_crosshair_var, 2, 0)
        
        self.show_distance_var = tk.BooleanVar(value=self.temp_settings["show_distance_text"])
        self._add_grid_switch(grid_frame, "Distance Text", self.show_distance_var, 2, 1)
        
        # 搴曢儴鎸夐垥鍗€鍩?
        # 浣跨敤 Spacer 鎺ㄥ埌搴曢儴
        ctk.CTkFrame(content_frame, fg_color="transparent").pack(fill="both", expand=True)
        
        # 鍒嗛殧绶?
        ctk.CTkFrame(content_frame, height=1, fg_color=COLOR_BORDER).pack(fill="x", pady=(0, 15))
        
        # 鎸夐垥瀹瑰櫒
        button_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        button_frame.pack(fill="x", pady=(0, 5))
        
        # 鍙栨秷鎸夐垥 (Outlined)
        cancel_btn = ctk.CTkButton(
            button_frame,
            text=t("CANCEL"),
            command=self._on_cancel,
            fg_color="transparent",
            border_width=1,
            border_color=COLOR_BORDER,
            hover_color=COLOR_SURFACE,
            text_color=COLOR_TEXT_DIM,
            font=("Roboto", 11, "bold"),
            height=35
        )
        cancel_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))
        
        # 淇濆瓨鎸夐垥 (Filled)
        save_btn = ctk.CTkButton(
            button_frame,
            text=t("SAVE"),
            command=self._on_save,
            fg_color=COLOR_TEXT,
            hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_BG,
            font=("Roboto", 11, "bold"),
            height=35
        )
        save_btn.pack(side="left", expand=True, fill="x", padx=(5, 0))

    def _add_section_title(self, parent, text):
        ctk.CTkLabel(
            parent,
            text=heading(text),
            font=("Roboto", 10, "bold"),
            text_color=COLOR_TEXT_DIM
        ).pack(anchor="w", pady=(10, 5))

    def _add_spacer(self, parent):
        ctk.CTkFrame(parent, height=1, fg_color=COLOR_BORDER).pack(fill="x", pady=10)

    def _add_switch(self, parent, text, variable):
        switch = ctk.CTkSwitch(
            parent,
            text=t(text),
            variable=variable,
            fg_color=COLOR_SURFACE,
            progress_color=COLOR_ACCENT,
            button_color=COLOR_ACCENT,
            button_hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT,
            font=("Roboto", 12)
        )
        switch.pack(anchor="w", pady=5)

    def _add_grid_switch(self, parent, text, variable, row, col):
        switch = ctk.CTkSwitch(
            parent,
            text=t(text),
            variable=variable,
            fg_color=COLOR_SURFACE,
            progress_color=COLOR_ACCENT,
            button_color=COLOR_ACCENT,
            button_hover_color=COLOR_ACCENT_HOVER,
            text_color=COLOR_TEXT,
            font=("Roboto", 12)
        )
        switch.grid(row=row, column=col, sticky="w", pady=8, padx=5)

    def _snapshot_temp_settings(self):
        if not hasattr(self, "show_opencv_var"):
            return
        self.temp_settings.update({
            "show_opencv_windows": self.show_opencv_var.get(),
            "show_opencv_mask": self.show_opencv_mask_var.get(),
            "show_opencv_detection": self.show_opencv_detection_var.get(),
            "show_opencv_roi": self.show_opencv_roi_var.get(),
            "show_opencv_triggerbot_mask": self.show_opencv_triggerbot_mask_var.get(),
            "show_ndi_raw_stream_window": self.show_ndi_raw_stream_var.get(),
            "show_udp_raw_stream_window": self.show_udp_raw_stream_var.get(),
            "show_mode_text": self.show_mode_var.get(),
            "show_aimbot_status": self.show_aimbot_status_var.get(),
            "show_triggerbot_status": self.show_triggerbot_status_var.get(),
            "show_target_count": self.show_target_count_var.get(),
            "show_crosshair": self.show_crosshair_var.get(),
            "show_distance_text": self.show_distance_var.get(),
        })

    def _on_language_changed(self, val):
        code = i18n.code_for_name(val)
        if code == i18n.language:
            return
        self._snapshot_temp_settings()
        config.language = i18n.set_language(code)
        try:
            config.save_to_file()
        except Exception:
            pass
        if hasattr(self.parent, "_apply_language"):
            self.parent._apply_language()
        self._rebuild_ui()

    def _rebuild_ui(self):
        for child in self.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass
        self.title(t("display settings"))
        self._build_ui()
        try:
            self.lift()
            self.grab_set()
            self.focus_force()
        except Exception:
            pass

    def _detach_from_parent(self):
        if getattr(self.parent, "_settings_window", None) is self:
            self.parent._settings_window = None

    def _on_save(self):
        """淇濆瓨瑷疆"""
        config.show_opencv_windows = self.show_opencv_var.get()
        config.show_opencv_mask = self.show_opencv_mask_var.get()
        config.show_opencv_detection = self.show_opencv_detection_var.get()
        config.show_opencv_roi = self.show_opencv_roi_var.get()
        config.show_opencv_triggerbot_mask = self.show_opencv_triggerbot_mask_var.get()
        config.show_ndi_raw_stream_window = self.show_ndi_raw_stream_var.get()
        config.show_udp_raw_stream_window = self.show_udp_raw_stream_var.get()
        config.show_mode_text = self.show_mode_var.get()
        config.show_aimbot_status = self.show_aimbot_status_var.get()
        config.show_triggerbot_status = self.show_triggerbot_status_var.get()
        config.show_target_count = self.show_target_count_var.get()
        config.show_crosshair = self.show_crosshair_var.get()
        config.show_distance_text = self.show_distance_var.get()
        config.language = i18n.language
        config.save_to_file()
        self._detach_from_parent()
        self.destroy()

    def _on_cancel(self):
        """鍙栨秷涓﹂棞闁?- 涓嶄繚瀛樹换浣曟洿鏀癸紝鎭㈠京鍘熷瑷疆"""
        self._detach_from_parent()
        self.destroy()
