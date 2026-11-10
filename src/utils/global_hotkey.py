"""Global hotkey + tray launcher (plan §8.5).

The window is borderless, so once it is hidden there is no taskbar button left to
click. This module owns a small Windows message loop on a daemon thread that:

* registers the toggle hotkey with ``RegisterHotKey`` — it keeps working while a
  borderless game owns the foreground;
* falls back to edge-detected ``GetAsyncKeyState`` polling when the game already
  owns the combination and ``RegisterHotKey`` fails;
* optionally adds a notification-area icon with a ``Show / Simple / Pro / Exit``
  menu;
* pushes every action into a :class:`queue.Queue` that the Tk thread drains.

Hard rule: **no Tk call happens on this thread.** This module never imports
tkinter; ``ui.py`` polls the queue with ``after(40)``.

The hotkey is registered against the *thread* (``RegisterHotKey(None, ...)``),
not against a window: that keeps it working even if the hidden tray window could
not be created, and ``PostThreadMessageW`` can drive an update/shutdown from the
outside. Registration is thread-affine, so every register/unregister happens on
the launcher thread itself.
"""

from __future__ import annotations

import ctypes
import os
import queue
import threading
import time
from typing import Callable, Optional

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    _LIB_SUFFIX = "W"
else:  # pragma: no cover - the module is a no-op off Windows
    _LIB_SUFFIX = ""

# --- minimal win32 type aliases (no ctypes.wintypes dependency) ------------
HWND = ctypes.c_void_p
UINT = ctypes.c_uint
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
DWORD = ctypes.c_uint32
BOOL = ctypes.c_int
LPCWSTR = ctypes.c_wchar_p

_WINFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
_WNDPROC = _WINFUNCTYPE(HWND, UINT, WPARAM, LPARAM)


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", HWND),
        ("message", UINT),
        ("wParam", WPARAM),
        ("lParam", LPARAM),
        ("time", DWORD),
        ("pt", POINT),
        ("lPrivate", DWORD),
    ]

    def __init__(self, *args, **kwargs):
        try:
            super().__init__(*args, **kwargs)
        except Exception:
            pass
        self.message = getattr(self, "message", 0)
        self.wParam = getattr(self, "wParam", 0)
        self.lParam = getattr(self, "lParam", 0)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", HWND),
        ("hIcon", HWND),
        ("hCursor", HWND),
        ("hbrBackground", HWND),
        ("lpszMenuName", LPCWSTR),
        ("lpszClassName", LPCWSTR),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", DWORD),
        ("hWnd", HWND),
        ("uID", UINT),
        ("uFlags", UINT),
        ("uCallbackMessage", UINT),
        ("hIcon", HWND),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", DWORD),
        ("dwStateMask", DWORD),
        ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", UINT),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", HWND),
    ]


# --- winuser.h / shellapi.h constants --------------------------------------
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_HOTKEY = 0x0312
WM_APP = 0x8000
WM_NULL = 0x0000
WM_TRAY = WM_APP + 1
WM_APP_REREGISTER = WM_APP + 2
WM_QUIT = 0x0012
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B

PM_REMOVE = 0x0001
PM_NOREMOVE = 0x0000

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002

NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

IDI_APPLICATION = 32512

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
TPM_LEFTALIGN = 0x0000
TPM_RIGHTBUTTON = 0x0002
TPM_BOTTOMALIGN = 0x0020
TPM_RETURNCMD = 0x0100

HOTKEY_ID = 1
HWND_MESSAGE = -3

#: Tray menu command ids -> queue actions.
_TRAY_COMMANDS = {
    1001: "toggle_ui",
    1002: "show",
    1003: "mode:simple",
    1004: "mode:pro",
    1005: "exit",
}

DEFAULT_VK = 0x2D  # Insert


def parse_hotkey_vk(value, default: int = DEFAULT_VK) -> int:
    """Parse a config hotkey name into a Win32 virtual-key code.

    ``""`` means "hotkey disabled" and returns ``0``. Anything unparsable falls
    back to ``default`` (Insert) so the user can always reclaim the window.
    """
    raw = str(value or "").strip()
    if not raw:
        return 0
    try:
        from src.utils.mouse.keycodes import to_vk_code

        vk = to_vk_code(raw)
    except Exception:
        vk = None
    if isinstance(vk, int) and 0 < vk < 0x100:
        return int(vk)
    return int(default)


# --- DLL accessors (module-level so tests can replace them) ----------------
_USER32 = None
_SHELL32 = None
_KERNEL32 = None


def _user32_module():
    global _USER32
    if _USER32 is None and IS_WINDOWS:
        try:
            _USER32 = ctypes.WinDLL("user32", use_last_error=True)
        except Exception:
            _USER32 = None
    return _USER32


def _shell32_module():
    global _SHELL32
    if _SHELL32 is None and IS_WINDOWS:
        try:
            _SHELL32 = ctypes.WinDLL("shell32", use_last_error=True)
        except Exception:
            _SHELL32 = None
    return _SHELL32


def _kernel32_module():
    global _KERNEL32
    if _KERNEL32 is None and IS_WINDOWS:
        try:
            _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except Exception:
            _KERNEL32 = None
    return _KERNEL32


def _fn(module, name):
    if module is None:
        return None
    return getattr(module, name, None)


class LauncherService:
    """Hotkey + tray owner. One per process; ``stop()`` is idempotent."""

    thread_name = "CVMHotkey"

    def __init__(
        self,
        vk: int,
        on_action: Optional[Callable[[str], None]] = None,
        tray: bool = True,
        app_name: str = "CVM colorBot",
        fallback_poll_ms: int = 50,
    ):
        self._vk = int(vk or 0)
        self._on_action = on_action
        self._tray_enabled = bool(tray)
        self._app_name = str(app_name or "CVM colorBot")
        self._fallback_poll_ms = max(10, int(fallback_poll_ms))
        self._thread: Optional[threading.Thread] = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._stop_flag = threading.Event()
        self._started = False
        self._registered = False
        self._hwnd = 0
        self._hwnd_lock = threading.Lock()
        self._wndproc_ref = None
        self._tray_added = False
        self._tip = self._app_name
        self._status_lock = threading.Lock()
        self.fallback_active = False
        self._last_down = False
        self.last_error: Optional[str] = None

    # -- public API ---------------------------------------------------------
    @property
    def vk(self) -> int:
        return self._vk

    @property
    def registered(self) -> bool:
        return self._registered

    @property
    def hwnd(self) -> int:
        with self._hwnd_lock:
            return self._hwnd

    @property
    def started(self) -> bool:
        return self._started

    @property
    def fallback(self) -> bool:
        return self.fallback_active

    def start(self) -> bool:
        """Spawn the message thread and wait (max 1 s) for it to settle.

        A failed ``RegisterHotKey`` is *not* a start failure: the polling
        fallback takes over and this still returns True.
        """
        if self._started:
            return True
        self._started = True
        if not IS_WINDOWS:
            self.last_error = "not running on Windows"
            return False
        self._thread = threading.Thread(
            target=self._run, name=self.thread_name, daemon=True
        )
        self._thread.start()
        self._ready.wait(1.0)
        return bool(self._registered or self.fallback_active)

    def stop(self, timeout: float = 1.0) -> None:
        """Unregister the hotkey, delete the tray icon, end the message loop."""
        if not self._started:
            return
        self._stop_flag.set()
        thread_id = self._thread_id
        post = _fn(_user32_module(), "PostThreadMessageW")
        if post is not None and thread_id:
            try:
                post(int(thread_id), WM_QUIT, 0, 0)
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        self._thread = None
        self._thread_id = 0
        self._started = False
        self._registered = False
        self.fallback_active = False
        self._remove_tray()
        with self._hwnd_lock:
            self._hwnd = 0

    def update_hotkey(self, vk: int) -> bool:
        """Ask the launcher thread to re-register (thread-affine API)."""
        self._vk = int(vk or 0)
        if not self._started or not IS_WINDOWS:
            return False
        post = _fn(_user32_module(), "PostThreadMessageW")
        if post is None or not self._thread_id:
            return False
        try:
            post(int(self._thread_id), WM_APP_REREGISTER, int(self._vk), 0)
        except Exception:
            return False
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            if self._registered or not self._vk:
                return True
            time.sleep(0.01)
        return bool(self._registered)

    def set_tray_tooltip(self, text: str) -> None:
        self._tip = (str(text or self._app_name))[:120]
        if self._tray_added:
            self._modify_tray()

    def set_tray_menu_state(self, hidden: bool, mode: str) -> None:
        label = "Show" if hidden else "Hide"
        self.set_tray_tooltip(f"{self._app_name} — {label} ({mode})")

    # -- message thread -----------------------------------------------------
    def _emit(self, action: str) -> None:
        callback = self._on_action
        if callback is None:
            return
        try:
            callback(action)
        except Exception:
            pass

    def _run(self) -> None:
        kernel32 = _kernel32_module()
        get_tid = _fn(kernel32, "GetCurrentThreadId")
        if get_tid is not None:
            try:
                self._thread_id = int(get_tid())
            except Exception:
                self._thread_id = 0

        # The tray icon needs a window; a failure here must not disable the
        # hotkey, which is registered against the thread.
        if self._tray_enabled:
            try:
                self._create_message_window()
                if self.hwnd:
                    self._add_tray()
            except Exception as exc:
                self.last_error = f"tray unavailable: {exc}"

        self._register()
        if not self._vk:
            self.last_error = "hotkey disabled"
        elif not self._registered and not self.fallback_active:
            self.fallback_active = True
            self.last_error = (
                f"RegisterHotKey failed for vk=0x{self._vk:02X}; "
                "falling back to GetAsyncKeyState polling"
            )
            self._emit("warn:hotkey_fallback")
        if self._tray_added:
            self._modify_tray()

        self._ready.set()
        self._message_loop()

        self._unregister()
        self._remove_tray()

    def _message_loop(self) -> None:
        user32 = _user32_module()
        msg = MSG()
        get_message = _fn(user32, "GetMessageW")
        peek_message = _fn(user32, "PeekMessageW")
        translate = _fn(user32, "TranslateMessage")
        dispatch = _fn(user32, "DispatchMessageW")
        if get_message is None or dispatch is None:
            self.last_error = "user32 message API unavailable"
            return

        self._last_down = False
        while not self._stop_flag.is_set():
            if self.fallback_active and peek_message is not None:
                handled = peek_message(ctypes.byref(msg), None, 0, 0, PM_REMOVE)
                if handled:
                    if msg.message == WM_QUIT:
                        break
                    if msg.message == WM_HOTKEY:
                        self._on_hotkey()
                    elif msg.message == WM_APP_REREGISTER:
                        self._reregister(int(msg.wParam))
                    else:
                        if translate is not None:
                            translate(ctypes.byref(msg))
                        dispatch(ctypes.byref(msg))
                if self._vk:
                    down = self._is_key_down(self._vk)
                    if down and not self._last_down:
                        self._on_hotkey()
                    self._last_down = down
                time.sleep(self._fallback_poll_ms / 1000.0)
                continue

            result = get_message(ctypes.byref(msg), None, 0, 0)
            if result is None or int(result) in (0, -1):
                break
            if msg.message == WM_QUIT:
                break
            if msg.message == WM_HOTKEY:
                if int(msg.wParam) == HOTKEY_ID:
                    self._on_hotkey()
                continue
            if msg.message == WM_APP_REREGISTER:
                self._reregister(int(msg.wParam))
                continue
            if translate is not None:
                translate(ctypes.byref(msg))
            dispatch(ctypes.byref(msg))

    def _is_key_down(self, vk: int) -> bool:
        if not vk:
            return False
        get_state = _fn(_user32_module(), "GetAsyncKeyState")
        if get_state is None:
            return False
        try:
            return bool(int(get_state(int(vk))) & 0x8000)
        except Exception:
            return False

    def _on_hotkey(self) -> None:
        """Queue ``toggle_ui``. Debouncing lives on the Tk side (250 ms)."""
        self._emit("toggle_ui")

    # -- Win32 plumbing -----------------------------------------------------
    def _create_message_window(self) -> None:
        user32 = _user32_module()
        kernel32 = _kernel32_module()
        if user32 is None or kernel32 is None:
            raise RuntimeError("user32/kernel32 unavailable")

        get_module = _fn(kernel32, "GetModuleHandleW")
        h_instance = get_module(None) if get_module is not None else None
        class_name = f"CVMColorBotLauncher_{os.getpid()}"
        self._wndproc_ref = _WNDPROC(self._wndproc)

        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = h_instance
        wc.lpszClassName = class_name
        register_class = _fn(user32, "RegisterClassW")
        if register_class is not None:
            register_class(ctypes.byref(wc))

        create_window = _fn(user32, "CreateWindowExW")
        if create_window is None:
            raise RuntimeError("CreateWindowExW unavailable")
        hwnd = create_window(
            0,
            class_name,
            self._app_name,
            0,
            0,
            0,
            0,
            0,
            HWND(HWND_MESSAGE),
            None,
            h_instance,
            None,
        )
        if not hwnd:
            raise RuntimeError("CreateWindowExW failed")
        with self._hwnd_lock:
            self._hwnd = int(hwnd)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            msg_id = int(msg)
            if msg_id == WM_HOTKEY:
                if int(wparam) == HOTKEY_ID:
                    self._on_hotkey()
                return 0
            if msg_id == WM_APP_REREGISTER:
                self._reregister(int(wparam))
                return 0
            if msg_id == WM_TRAY:
                event = int(lparam) & 0xFFFF
                if event == WM_LBUTTONUP:
                    self._emit("toggle_ui")
                elif event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._show_tray_menu()
                return 0
            if msg_id == WM_COMMAND:
                self._handle_tray_command(int(wparam) & 0xFFFF)
                return 0
            if msg_id in (WM_CLOSE, WM_DESTROY):
                self._stop_flag.set()
                post_quit = _fn(_user32_module(), "PostQuitMessage")
                if post_quit is not None:
                    post_quit(0)
                return 0
        except Exception:
            pass
        return self._def_window_proc(hwnd, msg, wparam, lparam)

    def _def_window_proc(self, hwnd, msg, wparam, lparam):
        proc = _fn(_user32_module(), "DefWindowProcW")
        if proc is None:
            return 0
        try:
            return proc(hwnd, msg, wparam, lparam)
        except Exception:
            return 0

    def _handle_tray_command(self, command: int) -> None:
        action = _TRAY_COMMANDS.get(int(command or 0))
        if action:
            self._emit(action)

    def _show_tray_menu(self) -> None:
        user32 = _user32_module()
        if user32 is None:
            return
        create_menu = _fn(user32, "CreatePopupMenu")
        append = _fn(user32, "AppendMenuW")
        track = _fn(user32, "TrackPopupMenu")
        destroy = _fn(user32, "DestroyMenu")
        set_fg = _fn(user32, "SetForegroundWindow")
        post = _fn(user32, "PostMessageW")
        if create_menu is None or append is None or track is None:
            return
        try:
            menu = create_menu()
            if not menu:
                return
            append(menu, MF_STRING, 1001, "Show / Hide")
            append(menu, MF_STRING, 1002, "Show Window")
            append(menu, MF_SEPARATOR, 0, None)
            append(menu, MF_STRING, 1003, "Simple Mode")
            append(menu, MF_STRING, 1004, "Pro Mode")
            append(menu, MF_SEPARATOR, 0, None)
            append(menu, MF_STRING, 1005, "Exit")

            x, y = self._tray_anchor()
            hwnd = self.hwnd
            if set_fg is not None and hwnd:
                set_fg(HWND(hwnd))
            command = track(
                menu,
                TPM_LEFTALIGN | TPM_RIGHTBUTTON | TPM_BOTTOMALIGN | TPM_RETURNCMD,
                x,
                y,
                0,
                HWND(hwnd) if hwnd else None,
                None,
            )
            if post is not None and hwnd:
                post(HWND(hwnd), WM_NULL, 0, 0)
            if destroy is not None:
                destroy(menu)
            self._handle_tray_command(int(command or 0))
        except Exception:
            pass

    def _tray_anchor(self) -> tuple:
        point = POINT()
        get_pos = _fn(_user32_module(), "GetCursorPos")
        if get_pos is not None:
            try:
                get_pos(ctypes.byref(point))
                return int(point.x), int(point.y)
            except Exception:
                pass
        return 0, 0

    def _notify_icon_data(self) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = HWND(self.hwnd)
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        load_icon = _fn(_user32_module(), "LoadIconW")
        if load_icon is not None:
            try:
                nid.hIcon = load_icon(None, LPCWSTR(IDI_APPLICATION))
            except Exception:
                nid.hIcon = None
        nid.szTip = (self._tip or self._app_name)[:127]
        return nid

    def _add_tray(self) -> bool:
        shell32 = _shell32_module()
        notify = _fn(shell32, "Shell_NotifyIconW")
        if notify is None or not self.hwnd:
            return False
        try:
            nid = self._notify_icon_data()
            self._tray_added = bool(notify(NIM_ADD, ctypes.byref(nid)))
        except Exception:
            self._tray_added = False
        return self._tray_added

    def _modify_tray(self) -> None:
        notify = _fn(_shell32_module(), "Shell_NotifyIconW")
        if notify is None or not self.hwnd:
            return
        try:
            nid = self._notify_icon_data()
            notify(NIM_MODIFY, ctypes.byref(nid))
        except Exception:
            pass

    def _remove_tray(self) -> None:
        if not self._tray_added:
            return
        notify = _fn(_shell32_module(), "Shell_NotifyIconW")
        if notify is not None and self.hwnd:
            try:
                nid = self._notify_icon_data()
                notify(NIM_DELETE, ctypes.byref(nid))
            except Exception:
                pass
        self._tray_added = False

    def _reregister(self, vk: int) -> None:
        """Called on the launcher thread only."""
        self._vk = int(vk or 0)
        self._last_down = False
        self._unregister()
        self._register()

    def _register(self) -> bool:
        if not self._vk:
            self._registered = False
            return False
        register = _fn(_user32_module(), "RegisterHotKey")
        if register is None:
            self._registered = False
            return False
        try:
            ok = bool(register(None, HOTKEY_ID, MOD_NOREPEAT, int(self._vk)))
        except Exception as exc:
            self.last_error = f"RegisterHotKey raised: {exc}"
            ok = False
        self._registered = ok
        if ok:
            self.fallback_active = False
        return ok

    def _unregister(self) -> None:
        if not self._registered:
            return
        unregister = _fn(_user32_module(), "UnregisterHotKey")
        try:
            if unregister is not None:
                unregister(None, HOTKEY_ID)
        except Exception:
            pass
        self._registered = False


def make_launcher(
    vk: int, on_action: Callable[[str], None], tray: bool = True
) -> LauncherService:
    """Convenience factory used by ``ViewerApp._start_launcher``."""
    return LauncherService(vk=vk, on_action=on_action, tray=tray)


def new_action_queue() -> "queue.Queue":
    return queue.Queue()


__all__ = [
    "DEFAULT_VK",
    "HOTKEY_ID",
    "LauncherService",
    "MOD_NOREPEAT",
    "NIM_ADD",
    "NIM_DELETE",
    "NIM_MODIFY",
    "WM_HOTKEY",
    "WM_TRAY",
    "make_launcher",
    "new_action_queue",
    "parse_hotkey_vk",
]
