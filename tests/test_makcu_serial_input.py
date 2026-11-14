"""Regression tests for MAKCU Serial button input, 4M auto-switch, and idle lock spam."""
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from main import AimTracker
from src.utils import mouse as mouse_backend
from src.utils.mouse import SerialAPI, state


class FakeMakcuSerial:
    def __init__(self, port="COM3", baudrate=115_200, chunks=None):
        self.port = port
        self.baudrate = baudrate
        self.is_open = True
        self.written = []
        self._rx = bytearray()
        if chunks:
            for c in chunks:
                self._rx.extend(c)
        self._lock = threading.Lock()

    @property
    def in_waiting(self):
        with self._lock:
            return len(self._rx)

    def push_rx(self, data: bytes):
        with self._lock:
            self._rx.extend(data)

    def read(self, n=1):
        deadline = time.time() + 0.02
        while True:
            with self._lock:
                if self._rx:
                    out = bytes(self._rx[:n])
                    del self._rx[:n]
                    return out
            if time.time() >= deadline or not self.is_open:
                return b""
            time.sleep(0.002)

    def write(self, data):
        self.written.append(data)

    def flush(self):
        pass

    def reset_input_buffer(self):
        with self._lock:
            self._rx.clear()

    def close(self):
        self.is_open = False


class TestSerialButtonParser(unittest.TestCase):
    def setUp(self):
        state.reset_button_states()

    def test_parses_km_prefixed_single_and_combo_masks_including_0a_and_0d(self):
        prefix = b""
        # Left click (0x01)
        prefix = SerialAPI._feed_listener_chunk(b"km.\x01\r\n>>> ", prefix)
        self.assertTrue(state.button_states[0])
        self.assertFalse(state.button_states[1])

        # Right + Side4 (0x0A == '\n') — previously dropped by (0x0A, 0x0D) filter
        prefix = SerialAPI._feed_listener_chunk(b"km.\x0a\r\n>>> ", prefix)
        self.assertFalse(state.button_states[0])
        self.assertTrue(state.button_states[1])
        self.assertTrue(state.button_states[3])

        # Left + Middle + Side4 (0x0D == '\r') — previously dropped
        prefix = SerialAPI._feed_listener_chunk(b"km.\x0d\r\n>>> ", prefix)
        self.assertTrue(state.button_states[0])
        self.assertFalse(state.button_states[1])
        self.assertTrue(state.button_states[2])
        self.assertTrue(state.button_states[3])

        # Release all (0x00)
        prefix = SerialAPI._feed_listener_chunk(b"km.\x00\r\n>>> ", prefix)
        self.assertEqual(dict(state.button_states), {i: False for i in range(5)})

    def test_parses_split_chunks_and_ignores_command_echoes(self):
        prefix = b""
        # Command echoes contain 'km.' followed by ASCII >= 0x20 and '\r\n>>> '
        prefix = SerialAPI._feed_listener_chunk(
            b"km.buttons(1)\r\n>>> km.lock_ml(0)\r\n>>> ", prefix
        )
        self.assertEqual(dict(state.button_states), {i: False for i in range(5)})

        # Frame split right after "km." with Side5 (0x10) in second chunk
        prefix = SerialAPI._feed_listener_chunk(b"km.", prefix)
        prefix = SerialAPI._feed_listener_chunk(b"\x10\r\n>>> ", prefix)
        self.assertTrue(state.button_states[4])
        self.assertFalse(state.button_states[0])

    def test_keeps_bare_single_byte_mask_compatibility(self):
        prefix = SerialAPI._feed_listener_chunk(b"\x02")
        self.assertTrue(state.button_states[1])
        prefix = SerialAPI._feed_listener_chunk(b"\x00", prefix)
        self.assertFalse(state.button_states[1])


class TestSerialListenerLifecycleAnd4MAutoSwitch(unittest.TestCase):
    def tearDown(self):
        SerialAPI._listener_stop_event.set()
        state.set_connected(False, "Serial")
        state.makcu = None
        if state.listener_thread is not None and state.listener_thread.is_alive():
            state.listener_thread.join(timeout=0.3)
        state.listener_thread = None
        state.reset_button_states()

    def test_switch_to_4m_restarts_listener_thread_and_reads_buttons(self):
        port_115 = FakeMakcuSerial(port="COM3", baudrate=115_200)
        port_4m_probe = FakeMakcuSerial(port="COM3", baudrate=4_000_000)
        port_4m_live = FakeMakcuSerial(
            port="COM3", baudrate=4_000_000, chunks=[b"km.\x08\r\n>>> "]
        )
        created = iter([port_4m_probe, port_4m_live])

        state.makcu = port_115
        state.set_connected(True, "Serial")
        SerialAPI._start_listener_thread()
        old_thread = state.listener_thread
        self.assertTrue(old_thread.is_alive())

        with (
            mock.patch.object(SerialAPI.serial, "Serial", side_effect=lambda *a, **kw: next(created)),
            mock.patch.object(SerialAPI, "km_version_ok", return_value=True),
            mock.patch.object(SerialAPI.time, "sleep", return_value=None),
        ):
            ok = SerialAPI.switch_to_4m()

        self.assertTrue(ok)
        self.assertFalse(old_thread.is_alive())
        self.assertIsNotNone(state.listener_thread)
        self.assertTrue(state.listener_thread.is_alive())

        deadline = time.time() + 0.5
        while time.time() < deadline and not SerialAPI.is_button_pressed(3):
            time.sleep(0.01)
        self.assertTrue(SerialAPI.is_button_pressed(3))

    def test_connect_to_serial_auto_switches_to_4m_when_enabled(self):
        fake_ser = FakeMakcuSerial(port="COM3", baudrate=115_200)
        fake_cfg = types.SimpleNamespace(serial_auto_switch_4m=True)

        def fake_connect(port=None):
            state.makcu = fake_ser
            state.set_connected(True, "Serial")
            return True

        with (
            mock.patch.object(mouse_backend, "_get_serial_settings", return_value=("Auto", "")),
            mock.patch.object(SerialAPI, "connect", side_effect=fake_connect),
            mock.patch.object(SerialAPI, "switch_to_4m", return_value=True) as mock_4m,
            mock.patch("src.utils.config.config", fake_cfg),
        ):
            self.assertTrue(mouse_backend.connect_to_serial())
            mock_4m.assert_called_once()

    def test_connect_to_serial_skips_4m_switch_when_disabled(self):
        fake_ser = FakeMakcuSerial(port="COM3", baudrate=115_200)
        fake_cfg = types.SimpleNamespace(serial_auto_switch_4m=False)

        def fake_connect(port=None):
            state.makcu = fake_ser
            state.set_connected(True, "Serial")
            return True

        with (
            mock.patch.object(mouse_backend, "_get_serial_settings", return_value=("Auto", "")),
            mock.patch.object(SerialAPI, "connect", side_effect=fake_connect),
            mock.patch.object(SerialAPI, "switch_to_4m", return_value=True) as mock_4m,
            mock.patch("src.utils.config.config", fake_cfg),
        ):
            self.assertTrue(mouse_backend.connect_to_serial())
            mock_4m.assert_not_called()


class TestButtonMaskIdleNoSpam(unittest.TestCase):
    def test_handle_button_mask_unlocks_once_when_disabled(self):
        tracker = AimTracker.__new__(AimTracker)
        fake_cfg = types.SimpleNamespace(
            button_mask_enabled=False,
            enableaim=True,
            enableaim_sec=False,
            enabletb=False,
        )
        with (
            mock.patch("main.config", fake_cfg),
            mock.patch.object(mouse_backend, "is_connected", True),
            mock.patch.object(mouse_backend, "unlock_all_locks") as mock_unlock,
        ):
            for _ in range(20):
                tracker._handle_button_mask()
            mock_unlock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
