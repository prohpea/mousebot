"""Verify device-side mouse locks are cleared on connect and on disconnect.

The locks live in the MAKCU firmware, not in this process, so they survive a
hard kill and strand the physical mouse. These tests use a fake serial port so
they never touch real hardware.
"""
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.utils.mouse import SerialAPI
from src.utils.mouse import state


class FakeSerial:
    def __init__(self):
        self.written = []

    def write(self, data):
        self.written.append(data)

    def flush(self):
        pass

    def joined(self):
        return b"".join(self.written).decode("ascii", "ignore")


class ReleaseStaleStateTest(unittest.TestCase):
    def setUp(self):
        state.reset_button_states()

    def test_release_covers_every_button_and_axis_lock(self):
        ser = FakeSerial()
        SerialAPI._release_stale_state(ser)
        out = ser.joined()

        # All five button locks, both axis locks, all three buttons released.
        for expected in (
            "km.lock_ml(0)",
            "km.lock_mr(0)",
            "km.lock_mm(0)",
            "km.lock_ms1(0)",
            "km.lock_ms2(0)",
            "km.lock_mx(0)",
            "km.lock_my(0)",
            "km.left(0)",
            "km.right(0)",
            "km.middle(0)",
        ):
            self.assertIn(expected, out, f"missing release: {expected}")

    def test_release_never_presses_anything(self):
        """A release helper must not be able to press or move the mouse."""
        ser = FakeSerial()
        SerialAPI._release_stale_state(ser)
        out = ser.joined()

        for forbidden in ("km.left(1)", "km.right(1)", "km.middle(1)", "km.move("):
            self.assertNotIn(forbidden, out, f"must not send: {forbidden}")

    def test_release_failure_does_not_raise(self):
        class Broken:
            def write(self, data):
                raise OSError("port vanished")

            def flush(self):
                pass

        SerialAPI._release_stale_state(Broken())  # must not raise

    def test_disconnect_releases_before_closing_port(self):
        ser = FakeSerial()
        state.makcu = ser
        state.set_connected(True, "Serial")
        try:
            SerialAPI.disconnect()
            self.assertIn("km.left(0)", ser.joined())
            self.assertIsNone(state.makcu)
            self.assertFalse(state.is_connected)
        finally:
            state.makcu = None
            state.set_connected(False, "Serial")


class ClosePathTest(unittest.TestCase):
    def test_on_close_cleans_up_mouse(self):
        """The window-close handler must release mouse state, not just capture."""
        source = (ROOT / "src" / "ui.py").read_text(encoding="utf-8", errors="replace")
        close_start = source.index("def _on_close")
        close_body = source[close_start:close_start + 2500]
        self.assertIn("Mouse.cleanup()", close_body)


if __name__ == "__main__":
    unittest.main()
