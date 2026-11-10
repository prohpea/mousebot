"""HWND-level window lifecycle helpers (plan §8.1).

This module is the ONLY place in the project that calls ``ShowWindow``,
``SetWindowLongPtrW``, ``SetWindowPos`` and ``SetForegroundWindow`` for the main
window. ``ui.py`` delegates here instead of scattering ``ctypes.windll.user32``
calls, because the previous ad-hoc approach (``overrideredirect(False)`` +
``iconify()`` + ``withdraw``/``deiconify``) destroyed ``WS_EX_APPWINDOW`` and the
taskbar button with it.

Design rules:

* no import of ``tkinter``/``customtkinter`` — this module takes an ``int`` HWND,
  so it is trivially mockable in tests and importable on Linux;
* 64-bit safe: ``GetWindowLongPtrW``/``SetWindowLongPtrW`` are used when the
  platform provides them, with a ``GetWindowLongW``/``SetWindowLongW`` fallback;
* every ``argtypes``/``restype`` is declared, so a bad handle is an exception
  instead of a silently truncated pointer;
* every function is a no-op returning a falsy value off Windows.
"""

from __future__ import annotations

import ctypes
import os
import re

IS_WINDOWS = os.name == "nt"

_POSITION_PARTS_RE = re.compile(r"^([+-]\d{1,5})([+-]\d{1,5})$")

# --- Constants (winuser.h) -------------------------------------------------
GWL_EXSTYLE = -20
GWL_STYLE = -16

WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000

SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_MAXIMIZE = 3
SW_SHOWNOACTIVATE = 4
SW_SHOW = 5
SW_MINIMIZE = 6
SW_RESTORE = 9

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040

HWND_TOP = 0
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

GA_ROOT = 2

#: ``GetAsyncKeyState`` mask for "the key is down right now".
KEY_PRESSED_MASK = 0x8000


def _load_user32():
    """Return a configured ``user32`` handle, or ``None`` off Windows/mocked."""
    if not IS_WINDOWS:
        return None
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
    except Exception:
        return None

    is_64 = ctypes.sizeof(ctypes.c_void_p) == 8
    long_ptr = ctypes.c_int64 if is_64 else ctypes.c_long

    try:
        user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.GetAncestor.restype = ctypes.c_void_p

        user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = long_ptr
        user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, long_ptr]
        user32.SetWindowLongPtrW.restype = long_ptr
    except AttributeError:
        # 32-bit Windows only exports the non-Ptr names.
        user32.GetWindowLongPtrW = user32.GetWindowLongW
        user32.SetWindowLongPtrW = user32.SetWindowLongW
        user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_long
        user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
        user32.SetWindowLongPtrW.restype = ctypes.c_long

    try:
        user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.ShowWindow.restype = ctypes.c_bool

        user32.IsWindow.argtypes = [ctypes.c_void_p]
        user32.IsWindow.restype = ctypes.c_bool

        user32.IsIconic.argtypes = [ctypes.c_void_p]
        user32.IsIconic.restype = ctypes.c_bool

        user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        user32.IsWindowVisible.restype = ctypes.c_bool

        user32.SetWindowPos.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = ctypes.c_bool

        user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        user32.SetForegroundWindow.restype = ctypes.c_bool

        user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
        user32.BringWindowToTop.restype = ctypes.c_bool

        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = ctypes.c_void_p

        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
    except Exception:
        return None

    return user32


USER32 = _load_user32()


def is_available() -> bool:
    """True when a usable ``user32`` handle was loaded."""
    return USER32 is not None


def root_hwnd(tk_widget) -> int:
    """Return the real top-level HWND for a Tk widget (``GetAncestor(GA_ROOT)``)."""
    if not is_available():
        return 0
    try:
        hwnd = int(tk_widget.winfo_id())
    except Exception:
        return 0
    if not hwnd:
        return 0
    try:
        root = USER32.GetAncestor(ctypes.c_void_p(hwnd), GA_ROOT)
        if root:
            return int(root)
    except Exception:
        pass
    return hwnd


def is_window(hwnd: int) -> bool:
    if not is_available() or not hwnd:
        return False
    try:
        return bool(USER32.IsWindow(ctypes.c_void_p(int(hwnd))))
    except Exception:
        return False


def get_exstyle(hwnd: int) -> int:
    if not is_available() or not hwnd:
        return 0
    try:
        return int(USER32.GetWindowLongPtrW(ctypes.c_void_p(int(hwnd)), GWL_EXSTYLE))
    except Exception:
        return 0


def set_exstyle(hwnd: int, exstyle: int) -> bool:
    if not is_available() or not hwnd:
        return False
    try:
        USER32.SetWindowLongPtrW(
            ctypes.c_void_p(int(hwnd)), GWL_EXSTYLE, int(exstyle)
        )
        return True
    except Exception:
        return False


def apply_appwindow(hwnd: int) -> int:
    """Drop ``WS_EX_TOOLWINDOW`` and raise ``WS_EX_APPWINDOW``.

    Returns the new ex-style (``0`` when it could not be read/applied). A
    borderless ``overrideredirect`` window loses the taskbar button unless this
    window bit is set explicitly.
    """
    if not is_available() or not hwnd:
        return 0
    try:
        current = get_exstyle(hwnd)
        wanted = (current & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
        if wanted != current:
            if not set_exstyle(hwnd, wanted):
                return 0
        return wanted
    except Exception:
        return 0


def refresh_frame(hwnd: int) -> bool:
    """Force a non-client frame recalculation without touching visibility.

    ``withdraw()`` + ``deiconify()`` used to be the way to make the shell notice
    a style change; that produced a visible blink, a lost focus and extra
    ``<Map>``/<Unmap>`` pairs. ``SWP_FRAMECHANGED`` does the same job in place.
    """
    if not is_available() or not hwnd:
        return False
    try:
        USER32.SetWindowPos(
            ctypes.c_void_p(int(hwnd)),
            None,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
        return True
    except Exception:
        return False


def _show_window(hwnd: int, command: int) -> bool:
    if not is_available() or not hwnd:
        return False
    try:
        return bool(USER32.ShowWindow(ctypes.c_void_p(int(hwnd)), int(command)))
    except Exception:
        return False


def minimize(hwnd: int) -> bool:
    """``ShowWindow(SW_MINIMIZE)`` — keeps the style and the taskbar button."""
    return _show_window(hwnd, SW_MINIMIZE)


def restore(hwnd: int) -> bool:
    """``ShowWindow(SW_RESTORE)`` — un-minimises and activates."""
    return _show_window(hwnd, SW_RESTORE)


def show(hwnd: int) -> bool:
    """``ShowWindow(SW_SHOW)`` — makes a hidden window visible without restoring."""
    return _show_window(hwnd, SW_SHOW)


def hide(hwnd: int) -> bool:
    """``ShowWindow(SW_HIDE)`` — removes the window from the screen."""
    return _show_window(hwnd, SW_HIDE)


def is_iconic(hwnd: int) -> bool:
    if not is_available() or not hwnd:
        return False
    try:
        return bool(USER32.IsIconic(ctypes.c_void_p(int(hwnd))))
    except Exception:
        return False


def is_visible(hwnd: int) -> bool:
    if not is_available() or not hwnd:
        return False
    try:
        return bool(USER32.IsWindowVisible(ctypes.c_void_p(int(hwnd))))
    except Exception:
        return False


def bring_to_front(hwnd: int) -> bool:
    """Activate the window and pin it as HWND_TOPMOST without blocking the Tk loop.

    Windows refuses ``SetForegroundWindow`` from a background process unless the
    target window is temporarily elevated to topmost. Caller schedules
    ``set_not_topmost`` asynchronously via ``after(120, ...)`` to restore
    normal Z-order without blocking.
    """
    if not is_available() or not hwnd:
        return False
    handle = ctypes.c_void_p(int(hwnd))
    try:
        USER32.SetWindowPos(
            handle,
            ctypes.c_void_p(HWND_TOPMOST),
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
        USER32.SetForegroundWindow(handle)
        USER32.BringWindowToTop(handle)
        return True
    except Exception:
        return False


def set_not_topmost(hwnd: int) -> bool:
    """Clear HWND_TOPMOST flag from the window asynchronously."""
    if not is_available() or not hwnd:
        return False
    handle = ctypes.c_void_p(int(hwnd))
    try:
        USER32.SetWindowPos(
            handle,
            ctypes.c_void_p(HWND_NOTOPMOST),
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
        return True
    except Exception:
        return False


def is_key_down(vk: int) -> bool:
    """Edge-agnostic key state; used by the hotkey fallback poller."""
    if not is_available() or not vk:
        return False
    try:
        return bool(USER32.GetAsyncKeyState(int(vk)) & KEY_PRESSED_MASK)
    except Exception:
        return False


def virtual_screen_rect() -> tuple:
    """``(left, top, width, height)`` of the whole virtual desktop."""
    if not is_available():
        return (0, 0, 0, 0)
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        rect = RECT()
        SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
        SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
        left = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
        top = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
        width = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
        height = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
        if width <= 0 or height <= 0:
            return (0, 0, 0, 0)
        return (left, top, width, height)
    except Exception:
        return (0, 0, 0, 0)


def clamp_position(position: str, width: int, height: int) -> str:
    """Clamp a ``"+x+y"`` string so the window is at least partly on screen."""
    text = str(position or "").strip()
    if not text:
        return ""
    # Imported lazily: config owns the parsing rules and must stay Tk-free.
    from src.utils.config import _normalize_position

    normalized = _normalize_position(text)
    if not normalized:
        return ""
    match = _POSITION_PARTS_RE.match(normalized)
    if not match:
        return ""
    x, y = int(match.group(1)), int(match.group(2))
    left, top, screen_w, screen_h = virtual_screen_rect()
    if screen_w <= 0 or screen_h <= 0:
        return normalized
    # Keep the whole title bar reachable: never leave the window fully outside.
    min_x = left - max(0, int(width) - 120)
    max_x = left + screen_w - 120
    min_y = top
    max_y = top + screen_h - 40
    x = max(min_x, min(max_x, x))
    y = max(min_y, min(max_y, y))
    return f"+{x}+{y}" if x >= 0 and y >= 0 else f"{x:+d}{y:+d}"


def parse_geometry(geometry: str) -> tuple:
    """``"560x540"`` -> ``(560, 540)``; ``(0, 0)`` when unparsable."""
    text = str(geometry or "").strip().lower()
    if "x" not in text:
        return (0, 0)
    width_text, _, height_text = text.partition("x")
    try:
        return (int(width_text.strip()), int(height_text.strip()))
    except Exception:
        return (0, 0)


__all__ = [
    "IS_WINDOWS",
    "USER32",
    "apply_appwindow",
    "bring_to_front",
    "clamp_position",
    "get_exstyle",
    "hide",
    "is_available",
    "is_iconic",
    "is_key_down",
    "is_visible",
    "is_window",
    "minimize",
    "parse_geometry",
    "refresh_frame",
    "restore",
    "root_hwnd",
    "set_exstyle",
    "set_not_topmost",
    "show",
    "virtual_screen_rect",
]
