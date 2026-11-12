"""Shared safety rails for tests that construct the real ViewerApp.

Two hazards existed and both are fixed here, once, instead of in every test:

1. Real game hardware. ViewerApp schedules after(800, _maybe_auto_start_runtime)
   and config.json ships auto_connect_mouse_api=True, so any test that pumps the
   event loop (app.update()) walks into a real MAKCU on COM3 and starts driving
   the user's physical mouse. serial.Serial is fenced so no port can ever open.

2. Real user config. Config.save_to_file() writes config.json relative to the
   current directory, so closing the app from a test overwrote the user's real
   settings with test values (observed: a default-valued config.json dropped in
   the workspace root). Config is redirected to a throwaway temp file.

Import this before constructing ViewerApp:

    from ui_test_support import fence_game_hardware
    fence_game_hardware()
"""
import os
import sys
import tempfile

_fenced = False


def fence_game_hardware():
    """Block real serial/HID access and redirect config writes to a temp file."""
    global _fenced
    if _fenced:
        return
    _fenced = True

    import serial

    real_serial = serial.Serial

    class FencedSerial:
        """Stands in for serial.Serial; never opens a real port."""

        def __init__(self, port=None, *args, **kwargs):
            raise serial.SerialException(
                f"[test-fence] real serial access blocked for port {port!r}"
            )

    FencedSerial.__name__ = "FencedSerial"
    serial.Serial = FencedSerial
    for module in list(sys.modules.values()):
        if module is not None and getattr(module, "Serial", None) is real_serial:
            setattr(module, "Serial", FencedSerial)

    from src.utils.config import config

    # A test must never launch a live aim session.
    config.auto_connect_mouse_api = False

    # Keep the user's real config.json untouched.
    tmp_dir = tempfile.mkdtemp(prefix="cvm-test-config-")
    scratch = os.path.join(tmp_dir, "config.json")
    config.save_to_file = lambda filename=scratch: _save_to_path(config, scratch)
    return scratch


def _save_to_path(config, path):
    """Write config to an explicit path, mirroring save_to_file's atomic write."""
    import json

    try:
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(config.to_dict(), handle, indent=4)
        os.replace(tmp, path)
    except Exception:
        pass
