"""Runtime path, single-instance lock, and splash helpers for source and single-EXE execution."""

from __future__ import annotations

import atexit
import ctypes
import os
import shutil
import socket
import sys
from pathlib import Path

_INSTANCE_MUTEX_NAME = "Local\\CVM_ColorBot_SingleInstance_v1"
_INSTANCE_MUTEX_HANDLE = None
_ERROR_ALREADY_EXISTS = 183
_SW_RESTORE = 9


def get_bundle_dir() -> Path:
    """Return directory containing bundled read-only resources (themes, locales, ABCurves)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[2]


def get_app_dir() -> Path:
    """Return writable application directory containing config.json and configs/."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def get_configs_dir() -> Path:
    """Return writable directory storing saved CVM configuration presets."""
    return get_app_dir() / "configs"


def detect_local_ipv4() -> str:
    """Detect this machine's primary non-loopback LAN IPv4 address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
    except Exception:
        pass
    try:
        _, _, ips = socket.gethostbyname_ex(socket.gethostname())
        for ip in ips:
            if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
    except Exception:
        pass
    return "127.0.0.1"


def _get_kernel32():
    """Return kernel32 WinDLL configured with explicit mutex handle signatures."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_bool
    return kernel32


def _release_single_instance_lock() -> None:
    """Close the process-wide Windows mutex handle during clean shutdown."""
    global _INSTANCE_MUTEX_HANDLE
    handle = _INSTANCE_MUTEX_HANDLE
    _INSTANCE_MUTEX_HANDLE = None
    if handle and os.name == "nt":
        try:
            _get_kernel32().CloseHandle(handle)
        except Exception:
            pass


def focus_existing_instance(window_title: str = "CVM colorBot") -> bool:
    """Restore and focus an already-running CVM window on Windows."""
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        user32.FindWindowW.restype = ctypes.c_void_p
        user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.ShowWindow.restype = ctypes.c_bool
        user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        user32.SetForegroundWindow.restype = ctypes.c_bool

        hwnd = user32.FindWindowW(None, window_title)
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, _SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def acquire_single_instance_lock() -> bool:
    """Acquire a Windows named mutex so only one CVM instance runs at a time."""
    global _INSTANCE_MUTEX_HANDLE
    if os.name != "nt" or _INSTANCE_MUTEX_HANDLE is not None:
        return True

    try:
        kernel32 = _get_kernel32()
        handle = kernel32.CreateMutexW(None, False, _INSTANCE_MUTEX_NAME)
        err = ctypes.get_last_error()
        if err == _ERROR_ALREADY_EXISTS:
            if handle:
                kernel32.CloseHandle(handle)
            focus_existing_instance()
            return False
        if handle:
            _INSTANCE_MUTEX_HANDLE = handle
            atexit.register(_release_single_instance_lock)
            return True
    except Exception:
        return True
    return True


def update_splash_text(text: str) -> None:
    """Update PyInstaller native splash screen status text when running as a frozen EXE."""
    if not getattr(sys, "frozen", False):
        return
    try:
        import pyi_splash  # type: ignore[import-not-found]

        if pyi_splash.is_alive():
            pyi_splash.update_text(str(text))
    except Exception:
        pass


def close_splash_screen() -> None:
    """Close PyInstaller native splash screen if active."""
    if not getattr(sys, "frozen", False):
        return
    try:
        import pyi_splash  # type: ignore[import-not-found]

        if pyi_splash.is_alive():
            pyi_splash.close()
    except Exception:
        pass


def ensure_runtime_environment() -> None:
    """Prepare frozen EXE runtime stdio, working directory, and default config preset."""
    if not getattr(sys, "frozen", False):
        return

    # Guard --noconsole builds where sys.stdout/stderr start as None.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="ignore")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="ignore")

    app_dir = get_app_dir()
    try:
        os.chdir(str(app_dir))
    except OSError:
        pass

    configs_dir = app_dir / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)
    bundled_configs = get_bundle_dir() / "configs"
    if bundled_configs.is_dir() and not any(configs_dir.glob("*.json")):
        default_src = bundled_configs / "default_cvm.json"
        if default_src.is_file():
            try:
                shutil.copy2(default_src, configs_dir / "default_cvm.json")
            except OSError:
                pass
