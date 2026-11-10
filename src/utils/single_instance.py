"""Single-instance guard + "show the running window" signal (plan §8.6).

Double-clicking ``run.bat`` while the tool is already running used to start a
second ``ViewerApp``: a second taskbar icon, a second capture/mouse backend and a
second hotkey registration (which fails because the first one owns it). The user
saw "nothing happened" because the new window opened behind the old one or behind
the game.

Resolution:

* the first process creates a named mutex and keeps the handle;
* a second process fails ``CreateMutexW`` with ``ERROR_ALREADY_EXISTS``, sets the
  named "show" event and exits 0;
* the first process runs an :class:`InstanceWatcher` thread that waits on that
  event and pushes ``"show"`` into the Tk launcher queue.

The mutex/event are ``Local\\`` (per user session) so two different users can each
run their own copy. Off Windows the guard is a no-op that reports "first".
"""

from __future__ import annotations

import ctypes
import os
import threading
from typing import Callable, Optional

IS_WINDOWS = os.name == "nt"

MUTEX_NAME = "Local\\CVM_colorBot_single_instance"
EVENT_NAME = "Local\\CVM_colorBot_show"

ERROR_ALREADY_EXISTS = 183
INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102

_MUTEX_HANDLE = None
_EVENT_HANDLE = None
_LOCK = threading.Lock()


def _kernel32():
    if not IS_WINDOWS:
        return None
    try:
        return ctypes.WinDLL("kernel32", use_last_error=True)
    except Exception:
        return None


def _create_mutex(kernel32, name):
    create = getattr(kernel32, "CreateMutexW", None)
    if create is None:
        return None, 0
    ctypes.set_last_error(0)
    handle = create(None, False, str(name))
    return handle, int(ctypes.get_last_error() or 0)


def _create_event(kernel32, name):
    create = getattr(kernel32, "CreateEventW", None)
    if create is None:
        return None
    # manual reset = False so a signal is consumed exactly once.
    return create(None, False, False, str(name))


def _open_event(kernel32, name):
    open_fn = getattr(kernel32, "OpenEventW", None)
    if open_fn is None:
        return None
    EVENT_MODIFY_STATE = 0x0002
    try:
        return open_fn(EVENT_MODIFY_STATE, False, str(name))
    except Exception:
        return None


def acquire(name: str = MUTEX_NAME) -> tuple:
    """Return ``(is_first_instance, handle)``.

    The handle must stay alive for the process lifetime; closing it releases the
    mutex and lets the next launch become "first" again.
    """
    global _MUTEX_HANDLE
    if not IS_WINDOWS:
        return True, None
    kernel32 = _kernel32()
    if kernel32 is None:
        return True, None
    with _LOCK:
        try:
            handle, last_error = _create_mutex(kernel32, name)
        except Exception:
            return True, None
        if not handle:
            # Cannot create a mutex at all: better to run than to refuse to start.
            return True, None
        if last_error == ERROR_ALREADY_EXISTS:
            close = getattr(kernel32, "CloseHandle", None)
            if close is not None:
                try:
                    close(handle)
                except Exception:
                    pass
            return False, None
        _MUTEX_HANDLE = handle
        return True, handle


def ensure_show_event(name: str = EVENT_NAME):
    """Create (or reuse) the named event the first instance waits on."""
    global _EVENT_HANDLE
    if not IS_WINDOWS:
        return None
    kernel32 = _kernel32()
    if kernel32 is None:
        return None
    with _LOCK:
        if _EVENT_HANDLE:
            return _EVENT_HANDLE
        try:
            _EVENT_HANDLE = _create_event(kernel32, name)
        except Exception:
            _EVENT_HANDLE = None
        return _EVENT_HANDLE


def signal_existing(name: str = EVENT_NAME) -> bool:
    """Wake the running instance. Called by the second process before exiting."""
    if not IS_WINDOWS:
        return False
    kernel32 = _kernel32()
    if kernel32 is None:
        return False
    handle = _open_event(kernel32, name)
    if not handle:
        # The first instance may not have created it yet; fall back to polling a
        # short while so a fast double-click still works.
        for _ in range(20):
            threading.Event().wait(0.025)
            handle = _open_event(kernel32, name)
            if handle:
                break
    if not handle:
        return False
    try:
        set_event = getattr(kernel32, "SetEvent", None)
        return bool(set_event(handle)) if set_event is not None else False
    except Exception:
        return False
    finally:
        close = getattr(kernel32, "CloseHandle", None)
        if close is not None:
            try:
                close(handle)
            except Exception:
                pass


def release() -> None:
    """Close the mutex/event handles. Safe to call twice."""
    global _MUTEX_HANDLE, _EVENT_HANDLE
    if not IS_WINDOWS:
        return
    kernel32 = _kernel32()
    close = getattr(kernel32, "CloseHandle", None) if kernel32 is not None else None
    with _LOCK:
        for attr in ("_MUTEX_HANDLE", "_EVENT_HANDLE"):
            handle = globals().get(attr)
            if handle and close is not None:
                try:
                    close(handle)
                except Exception:
                    pass
            globals()[attr] = None


class InstanceWatcher(threading.Thread):
    """Wait on the show event; call ``on_show`` (queue.put) when signalled.

    Runs as a daemon thread and never touches Tk. ``stop()`` is idempotent and
    uses a short ``WaitForSingleObject`` timeout so shutdown is not delayed by a
    full second.
    """

    thread_name = "CVMInstanceWatcher"

    def __init__(
        self,
        on_show: Optional[Callable[[], None]] = None,
        name: str = EVENT_NAME,
        poll_ms: int = 250,
    ):
        super().__init__(name=self.thread_name, daemon=True)
        self._on_show = on_show
        self._event_name = str(name)
        self._poll_ms = max(50, int(poll_ms))
        self._stop = threading.Event()
        self._handle = None

    def attach_event(self) -> bool:
        self._handle = ensure_show_event(self._event_name)
        return bool(self._handle)

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        if not IS_WINDOWS:
            return
        kernel32 = _kernel32()
        wait = getattr(kernel32, "WaitForSingleObject", None) if kernel32 else None
        if wait is None:
            return
        if not self._handle:
            self.attach_event()
        if not self._handle:
            return
        max_wait = 0xFFFFFFFF  # INFINITE
        while not self._stop.is_set():
            try:
                result = int(wait(self._handle, self._poll_ms))
            except Exception:
                return
            if result == WAIT_OBJECT_0:
                self._fire()
            elif result == max_wait:
                continue
            elif result != WAIT_TIMEOUT:
                # WAIT_ABANDONED / WAIT_FAILED: nothing left to wait for.
                return

    def _fire(self) -> None:
        if self._on_show is None:
            return
        try:
            self._on_show()
        except Exception:
            pass


__all__ = [
    "EVENT_NAME",
    "InstanceWatcher",
    "MUTEX_NAME",
    "acquire",
    "ensure_show_event",
    "release",
    "signal_existing",
]
