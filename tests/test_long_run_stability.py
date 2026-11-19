"""Long-run stability: no silent death of the threads a 2-PC session depends on.

Every failure covered here has the same shape: the component keeps reporting
itself healthy while it has actually stopped working.

* the MAKCU listener dies on one ``SerialException`` and leaves
  ``is_connected`` True with every button dead, or a stalled USB TX endpoint
  blocks ``move()`` forever because ``write_timeout`` was None;
* the UDP receiver exits on a transient ``ConnectionResetError`` (WinError
  10054) and never rebinds, or a half-received MJPEG frame survives long enough
  to hand its timestamp to a later frame;
* a rebuilt UDP receiver restarts its sequence at 0, so a stale ``after_seq``
  makes the tracker wait for a frame number that will never arrive;
* a backwards wall-clock jump (NTP/PTP) freezes the WindMouse reaction window;
* the idle preview worker never pumps HighGUI, so the window is marked
  "Not Responding";
* one exception in a Tk ``after()`` loop stops it from ever rescheduling.

Everything runs offline: fake serial ports, fake/patched sockets, a fake clock
and a fake Tk root. No hardware, no bound UDP port, no window.
"""
import os
import socket
import sys
import threading
import time
import types
import unittest
from unittest import mock

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import serial

from src.capture.OBS_UDP import OBS_UDP_Receiver, MJPEG_BUFFER_MAX_AGE_S
from src.capture.capture_service import CaptureService
from src.utils.mouse import SerialAPI, state


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeMakcuSerial:
    """Minimal stand-in for ``serial.Serial``.

    Deliberately has no ``write_timeout`` attribute: the code must only pass the
    kwarg when *opening* a port, never touch it on an existing object.
    """

    def __init__(self, port="COM3", baudrate=115_200, chunks=None):
        self.port = port
        self.baudrate = baudrate
        self.is_open = True
        self.written = []
        self.flush_calls = 0
        self._rx = bytearray()
        if chunks:
            for chunk in chunks:
                self._rx.extend(chunk)
        self._lock = threading.Lock()
        self.fail_write = None

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
        if self.fail_write is not None:
            raise self.fail_write
        self.written.append(bytes(data))

    def flush(self):
        self.flush_calls += 1

    def reset_input_buffer(self):
        with self._lock:
            self._rx.clear()

    def close(self):
        self.is_open = False

    def joined(self):
        return b"".join(self.written).decode("ascii", "ignore")


class FakeRecvSocket:
    """Socket double: yields scripted results, one per ``recvfrom`` call.

    Script entries are payload bytes, a ``BaseException`` to raise, or the
    sentinel ``"stop"`` which asks the loop to shut down. Anything past the end
    of the script behaves like a quiet socket (``socket.timeout``).
    """

    def __init__(self, script, on_call=None):
        self.script = list(script)
        self.calls = 0
        self.closed = 0
        self.on_call = on_call
        self.stop_requested = False

    def recvfrom(self, bufsize):
        index = self.calls
        self.calls += 1
        if self.on_call is not None:
            self.on_call(index)
        action = self.script[index] if index < len(self.script) else "stop"
        if action == "stop":
            self.stop_requested = True
            time.sleep(0.001)
            raise socket.timeout("scripted end")
        if isinstance(action, BaseException):
            raise action
        return action, ("127.0.0.1", 9)

    def close(self):
        self.closed += 1

    def setsockopt(self, *args, **kwargs):
        pass

    def getsockopt(self, *args, **kwargs):
        return 8 * 1024 * 1024

    def settimeout(self, value):
        pass

    def bind(self, addr):
        pass


class FakeUdpReceiver:
    """Receiver double for the CaptureService freshness contract."""

    def __init__(self, connected=True, stopped=False, seq=5):
        self.is_connected = connected
        self.stop_event = threading.Event()
        if stopped:
            self.stop_event.set()
        self._seq = seq
        self.after_seqs = []
        self.current_frame_calls = 0

    def wait_for_new_frame(self, after_seq, timeout=0.0):
        self.after_seqs.append(after_seq)
        return np.zeros((4, 4, 3), np.uint8), self._seq

    def get_current_frame_with_seq(self):
        self.current_frame_calls += 1
        return np.zeros((4, 4, 3), np.uint8), self._seq


class FakeTkRoot:
    """Enough of a Tk root to observe ``after()`` calls from a loop body."""

    def __init__(self):
        self.jobs = []
        self.exists = True

    def after(self, delay, callback=None):
        job_id = f"job-{len(self.jobs)}"
        self.jobs.append((delay, callback, job_id))
        return job_id

    def winfo_exists(self):
        return self.exists


# ---------------------------------------------------------------------------
# Serial: open parameters, hot path, TX failure, listener, reconnect
# ---------------------------------------------------------------------------


class SerialTestBase(unittest.TestCase):
    def setUp(self):
        state.reset_button_states()
        state.mask_applied_idx = None
        self._saved_stop = SerialAPI._listener_stop_event.is_set()
        self._saved_config = SerialAPI._last_port_config
        self._saved_release = SerialAPI._last_release_time
        SerialAPI._last_release_time = 0.0
        SerialAPI._listener_stop_event.set()

    def tearDown(self):
        SerialAPI._listener_stop_event.set()
        state.set_connected(False, "Serial")
        SerialAPI._sync_public_connection_state()
        state.makcu = None
        if state.listener_thread is not None and state.listener_thread.is_alive():
            state.listener_thread.join(timeout=0.3)
        state.listener_thread = None
        state.reset_button_states()
        state.mask_applied_idx = None
        SerialAPI._last_port_config = self._saved_config
        SerialAPI._last_release_time = self._saved_release
        if not self._saved_stop:
            SerialAPI._listener_stop_event.clear()


class TestSerialPortOpenParameters(SerialTestBase):
    def test_connect_opens_port_with_bounded_write_and_no_flow_control(self):
        created = []

        def fake_serial(port, baud, **kwargs):
            handle = FakeMakcuSerial(port=port, baudrate=baud)
            created.append((port, baud, kwargs, handle))
            return handle

        # Pinned so the assertion does not depend on the user's config.json.
        with (
            mock.patch.object(SerialAPI, "BAUD_RATES", [115_200]),
            mock.patch.object(SerialAPI.serial, "Serial", side_effect=fake_serial),
            mock.patch.object(SerialAPI, "km_version_ok", return_value=True),
            mock.patch.object(SerialAPI, "find_com_ports", return_value=[("COM3", "MAKCU")]),
            mock.patch.object(SerialAPI.time, "sleep", return_value=None),
            mock.patch.object(SerialAPI, "_start_listener_thread", return_value=None),
        ):
            self.assertTrue(SerialAPI.connect())

        self.assertTrue(created, "connect() never opened a port")
        for port, baud, kwargs, _handle in created:
            self.assertEqual(kwargs.get("write_timeout"), 0.25, (port, baud, kwargs))
            self.assertIs(kwargs.get("dsrdtr"), False, kwargs)
            self.assertIs(kwargs.get("rtscts"), False, kwargs)
            self.assertIs(kwargs.get("xonxoff"), False, kwargs)
            # The probe needs a longer read timeout than the live port.
            self.assertIn(kwargs.get("timeout"), (0.1, 0.3), kwargs)

        # The live port (last open) is the one kept.
        self.assertEqual(created[-1][3], state.makcu)
        self.assertTrue(state.is_connected)

    def test_switch_to_4m_opens_the_new_baud_safely(self):
        opened = []

        def fake_serial(port, baud, **kwargs):
            handle = FakeMakcuSerial(port=port, baudrate=baud)
            opened.append((baud, kwargs, handle))
            return handle

        state.makcu = FakeMakcuSerial(baudrate=115_200)
        state.set_connected(True, "Serial")
        SerialAPI._listener_stop_event.clear()

        with (
            mock.patch.object(SerialAPI.serial, "Serial", side_effect=fake_serial),
            mock.patch.object(SerialAPI, "km_version_ok", return_value=True),
            mock.patch.object(SerialAPI.time, "sleep", return_value=None),
            mock.patch.object(SerialAPI, "_start_listener_thread", return_value=None),
        ):
            self.assertTrue(SerialAPI.switch_to_4m())

        self.assertTrue(opened)
        for baud, kwargs, _handle in opened:
            self.assertEqual(kwargs.get("write_timeout"), 0.25, (baud, kwargs))

    def test_remembered_port_config_is_recorded_after_a_successful_connect(self):
        with (
            mock.patch.object(SerialAPI, "BAUD_RATES", [115_200]),
            mock.patch.object(SerialAPI.serial, "Serial", side_effect=lambda p, b, **kw: FakeMakcuSerial(port=p, baudrate=b)),
            mock.patch.object(SerialAPI, "km_version_ok", return_value=True),
            mock.patch.object(SerialAPI, "find_com_ports", return_value=[("COM7", "MAKCU")]),
            mock.patch.object(SerialAPI.time, "sleep", return_value=None),
            mock.patch.object(SerialAPI, "_start_listener_thread", return_value=None),
        ):
            self.assertTrue(SerialAPI.connect())

        self.assertEqual(SerialAPI._last_port_config, ("COM7", 115_200, False))


class TestSerialHotPathHasNoFlush(SerialTestBase):
    def setUp(self):
        super().setUp()
        self.ser = FakeMakcuSerial()
        state.makcu = self.ser
        state.set_connected(True, "Serial")

    def _assert_no_flush(self, fn, *args):
        before = self.ser.flush_calls
        fn(*args)
        self.assertEqual(self.ser.flush_calls, before, f"{fn.__name__} still flushes on the hot path")
        self.assertTrue(self.ser.written, f"{fn.__name__} wrote nothing")

    def test_move_does_not_flush(self):
        self._assert_no_flush(SerialAPI.move, 5, 6)
        self.assertIn("km.move(5,6)", self.ser.joined())

    def test_move_bezier_does_not_flush(self):
        self._assert_no_flush(SerialAPI.move_bezier, 5, 6, 3, 1, 2)
        self.assertIn("km.move(5,6,3,1,2)", self.ser.joined())

    def test_button_helpers_do_not_flush(self):
        self._assert_no_flush(SerialAPI.left, 1)
        self._assert_no_flush(SerialAPI.left, 0)
        self._assert_no_flush(SerialAPI.right, 1)
        self._assert_no_flush(SerialAPI.middle, 1)
        out = self.ser.joined()
        self.assertIn("km.left(1)", out)
        self.assertIn("km.right(1)", out)
        self.assertIn("km.middle(1)", out)

    def test_no_wait_command_path_does_not_flush(self):
        self._assert_no_flush(SerialAPI._send_cmd_no_wait, "lock_ml(1)")
        self.assertIn("km.lock_ml(1)", self.ser.joined())

    def test_probe_and_release_still_flush(self):
        # These runs are off the hot path and *must* drain so the next command
        # is not interleaved with a half-written handshake.
        before = self.ser.flush_calls
        SerialAPI._release_stale_state(self.ser)
        self.assertGreater(self.ser.flush_calls, before, "_release_stale_state must flush")

        self.ser.reset_input_buffer()
        before = self.ser.flush_calls
        SerialAPI.km_version_ok(self.ser)
        self.assertGreater(self.ser.flush_calls, before, "km_version_ok must flush")


class TestSerialTxFailureIsContained(SerialTestBase):
    def setUp(self):
        super().setUp()
        # A live session: the transport-loss path only engages when no shutdown
        # has been requested.
        SerialAPI._listener_stop_event.clear()
        self.ser = FakeMakcuSerial()
        self.ser.fail_write = serial.SerialException("USB TX stalled")
        state.makcu = self.ser
        state.set_connected(True, "Serial")
        self.recovery = mock.patch.object(SerialAPI, "_start_recovery_thread")
        self.started = self.recovery.start()
        self.addCleanup(self.recovery.stop)

    def test_move_never_raises_and_reports_the_transport_lost(self):
        SerialAPI.move(10, 10)  # must not raise: move queue would die

        self.assertFalse(state.is_connected, "a dead transport still reports connected")
        self.assertIsNone(state.makcu, "the dead port was left installed")
        self.assertFalse(self.ser.is_open, "the dead port was left open")
        self.assertEqual(self.started.call_count, 1, "recovery was not scheduled exactly once")

    def test_public_mouse_state_is_synced_on_transport_loss(self):
        from src.utils import mouse as mouse_backend

        mouse_backend.is_connected = True
        try:
            SerialAPI.left(1)
            self.assertFalse(state.is_connected)
            self.assertFalse(
                mouse_backend.is_connected,
                "mouse.is_connected stayed True: the UI keeps showing a live device",
            )
        finally:
            mouse_backend._sync_public_state()

    def test_no_recovery_when_shutdown_already_started(self):
        SerialAPI._listener_stop_event.set()
        state.set_connected(True, "Serial")
        state.makcu = self.ser

        SerialAPI.move(1, 1)

        self.assertEqual(self.started.call_count, 0, "reconnect was attempted during shutdown")
        self.assertTrue(state.is_connected, "shutdown path must not report a transport loss")


class TestSerialListenerDoesNotDieSilently(SerialTestBase):
    def test_listener_reports_transport_loss_instead_of_leaving_a_dead_session(self):
        ser = FakeMakcuSerial()

        def explode(n=1):
            raise serial.SerialException("device disappeared")

        ser.read = explode  # type: ignore[assignment]
        state.makcu = ser
        state.set_connected(True, "Serial")
        SerialAPI._listener_stop_event.clear()

        with mock.patch.object(SerialAPI, "_start_recovery_thread") as recovery:
            thread = threading.Thread(target=SerialAPI._listener_loop, daemon=True)
            thread.start()
            thread.join(timeout=2.0)

        self.assertFalse(thread.is_alive(), "listener thread hung on a serial error")
        self.assertFalse(state.is_connected, "listener died but the session still claims to be up")
        self.assertEqual(recovery.call_count, 1, "the dead listener did not schedule a reconnect")

    def test_listener_exits_quietly_when_stop_arrives_during_a_read(self):
        ser = FakeMakcuSerial()

        def explode(n=1):
            # Shutdown lands between the loop condition and the read.
            SerialAPI._listener_stop_event.set()
            raise serial.SerialException("closing")

        ser.read = explode  # type: ignore[assignment]
        state.makcu = ser
        state.set_connected(True, "Serial")
        SerialAPI._listener_stop_event.clear()

        with mock.patch.object(SerialAPI, "_start_recovery_thread") as recovery:
            SerialAPI._listener_loop()

        self.assertEqual(recovery.call_count, 0, "a shutdown-time error triggered a reconnect")
        self.assertTrue(state.is_connected, "shutdown must not be reported as a failure")


class TestSerialRecoveryLoop(SerialTestBase):
    def setUp(self):
        super().setUp()
        SerialAPI._listener_stop_event.clear()
        SerialAPI._last_port_config = ("COM9", 115_200, True)
        state.makcu = None
        state.set_connected(False, "Serial")

    def test_recovery_reopens_the_remembered_port_and_releases_stale_state(self):
        fresh = FakeMakcuSerial(port="COM9", baudrate=115_200)
        opened = []

        def fake_open(port, baud, timeout=None):
            opened.append((port, baud))
            return fresh

        with (
            mock.patch.object(SerialAPI, "_open_serial", side_effect=fake_open),
            mock.patch.object(SerialAPI, "km_version_ok", return_value=True),
            mock.patch.object(SerialAPI, "_start_listener_thread") as listener,
            mock.patch.object(SerialAPI, "_RECONNECT_DELAYS", (0.0,)),
        ):
            SerialAPI._recovery_loop()

        self.assertEqual(opened, [("COM9", 115_200)], "recovery did not reuse the remembered port")
        self.assertIs(state.makcu, fresh)
        self.assertTrue(state.is_connected)
        self.assertIsNone(state.mask_applied_idx, "mask_applied_idx was not reset on reconnect")
        out = fresh.joined()
        self.assertIn("km.buttons(1)", out, "the device was not re-primed after reconnect")
        self.assertIn("km.left(0)", out, "stale firmware state was not released after reconnect")
        self.assertEqual(listener.call_count, 1, "the listener was not restarted")

    def test_recovery_stops_immediately_when_stop_event_is_set(self):
        with mock.patch.object(SerialAPI, "_open_serial") as opener:
            SerialAPI._listener_stop_event.set()
            SerialAPI._recovery_loop()

        opener.assert_not_called()
        self.assertFalse(state.is_connected)

    def test_recovery_retries_with_backoff_until_the_port_answers(self):
        attempts = []

        def flaky_open(port, baud, timeout=None):
            attempts.append(port)
            if len(attempts) < 3:
                raise serial.SerialException("device still booting")
            return FakeMakcuSerial(port=port, baudrate=baud)

        with (
            mock.patch.object(SerialAPI, "_open_serial", side_effect=flaky_open),
            mock.patch.object(SerialAPI, "km_version_ok", return_value=True),
            mock.patch.object(SerialAPI, "_start_listener_thread"),
            mock.patch.object(SerialAPI, "_RECONNECT_DELAYS", (0.0,)),
        ):
            SerialAPI._recovery_loop()

        self.assertEqual(len(attempts), 3, "recovery gave up before the device came back")
        self.assertTrue(state.is_connected)

    def test_disconnect_blocks_any_later_reconnect(self):
        state.makcu = FakeMakcuSerial()
        state.set_connected(True, "Serial")

        SerialAPI.disconnect()

        self.assertTrue(SerialAPI._listener_stop_event.is_set())
        with mock.patch.object(SerialAPI, "_open_serial") as opener:
            SerialAPI._recovery_loop()
            SerialAPI._start_recovery_thread()
        opener.assert_not_called()
        self.assertIsNone(SerialAPI._recovery_thread, "a recovery thread was started after disconnect")


# ---------------------------------------------------------------------------
# UDP receiver: transient errors, rebind, MJPEG expiry
# ---------------------------------------------------------------------------


class TestUdpReceiveLoopSurvivesTransientErrors(unittest.TestCase):
    def setUp(self):
        self.receiver = OBS_UDP_Receiver(ip="127.0.0.1", port=13400, target_fps=144)

    def tearDown(self):
        self.receiver.is_connected = False
        self.receiver.stop_event.set()

    def _run(self, script):
        self.receiver.is_connected = True
        self.receiver.stop_event.clear()
        received = []

        def record(data, receive_time):
            received.append(data)

        self.receiver._process_mjpeg_data = record

        def stop_when_exhausted(index):
            if index >= len(script):
                self.receiver.stop_event.set()

        sock = FakeRecvSocket(script, on_call=stop_when_exhausted)
        self.receiver.socket = sock

        thread = threading.Thread(target=self.receiver._receive_loop, daemon=True)
        thread.start()
        thread.join(timeout=5.0)
        self.receiver.stop_event.set()
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive(), "the receive loop did not stop")
        return received

    def test_connection_reset_does_not_end_the_loop(self):
        received = self._run(
            [ConnectionResetError(10054, "reset"), b"first", b"second"]
        )

        self.assertEqual(received, [b"first", b"second"], "a transient reset stopped the receiver")

    def test_blocking_and_interrupted_errors_are_ignored(self):
        received = self._run(
            [BlockingIOError("would block"), InterruptedError("signal"), b"payload"]
        )

        self.assertEqual(received, [b"payload"])

    def test_hard_socket_error_rebinds_instead_of_exiting(self):
        self.receiver.is_connected = True
        self.receiver.stop_event.clear()
        rebuilds = []

        def fake_recover(delay=0.0):
            rebuilds.append(delay)
            self.receiver.stop_event.set()

        with mock.patch.object(self.receiver, "_recover_socket", side_effect=fake_recover):
            sock = FakeRecvSocket([OSError(10038, "not a socket")])
            self.receiver.socket = sock
            self.receiver._receive_loop()

        self.assertEqual(len(rebuilds), 1, "a broken socket was not rebuilt")
        self.assertTrue(
            self.receiver.is_connected,
            "the stream was reported dead instead of rebinding in place",
        )

    def test_loop_exits_on_oserror_only_when_stop_was_requested(self):
        self.receiver.is_connected = True
        self.receiver.stop_event.set()
        sock = FakeRecvSocket([OSError(10038, "not a socket")])
        self.receiver.socket = sock

        with mock.patch.object(self.receiver, "_recover_socket") as recover:
            self.receiver._receive_loop()

        recover.assert_not_called()
        self.assertEqual(sock.closed, 0, "shutdown must not tear the socket down twice")


class TestUdpSocketRecovery(unittest.TestCase):
    def setUp(self):
        self.receiver = OBS_UDP_Receiver(ip="127.0.0.1", port=13401, target_fps=144)
        self.receiver.is_connected = True
        self.receiver._bind_addr = ("0.0.0.0", 13401)

    def tearDown(self):
        # No receive thread was started for these instances; just make sure a
        # stray timer cannot keep anything alive.
        self.receiver.is_connected = False
        self.receiver.stop_event.set()

    def test_recover_socket_rebinds_and_resets_stream_state(self):
        old = FakeRecvSocket([])
        self.receiver.socket = old
        self.receiver.mjpeg_buffer.extend(b"\xff\xd8partial")
        self.receiver._frame_start_time = 1.0
        self.receiver._frag_parts = {0: b"x"}
        fresh = FakeRecvSocket([])

        bound = []

        def fake_socket(*args, **kwargs):
            return fresh

        with (
            mock.patch("src.capture.OBS_UDP.socket.socket", side_effect=fake_socket),
            mock.patch.object(fresh, "bind", side_effect=lambda addr: bound.append(addr)),
        ):
            self.receiver._recover_socket(0.0)

        self.assertEqual(old.closed, 1, "the broken socket was not closed")
        self.assertIs(self.receiver.socket, fresh)
        self.assertEqual(bound, [("0.0.0.0", 13401)], "the socket was not rebound to the same address")
        self.assertEqual(bytes(self.receiver.mjpeg_buffer), b"")
        self.assertIsNone(self.receiver._frame_start_time)
        self.assertEqual(self.receiver._frag_parts, {})
        self.assertTrue(self.receiver.is_connected, "a successful rebind must keep the stream live")

    def test_rebind_failure_keeps_the_stream_marked_connected(self):
        self.receiver.socket = FakeRecvSocket([])

        def failing_socket(*args, **kwargs):
            raise OSError(10048, "address already in use")

        with mock.patch("src.capture.OBS_UDP.socket.socket", side_effect=failing_socket):
            self.receiver._recover_socket(0.0)

        self.assertIsNone(self.receiver.socket)
        self.assertTrue(
            self.receiver.is_connected,
            "a squatted port must look starved, not disconnected",
        )


class TestMjpegBufferExpiry(unittest.TestCase):
    def setUp(self):
        self.receiver = OBS_UDP_Receiver(ip="127.0.0.1", port=13402, target_fps=144)
        self.delivered = []
        self.receiver._deliver_jpeg = lambda data, start: self.delivered.append((data, start))

    def tearDown(self):
        # The receive thread was never started for these instances, and
        # disconnect() bumps the publish sequence; nothing to join either way.
        self.receiver.is_connected = False
        self.receiver.stop_event.set()

    def test_partial_frame_older_than_the_limit_is_dropped(self):
        self.receiver._process_mjpeg_data(b"\xff\xd8" + b"A" * 64, 10.0)
        self.assertEqual(len(self.receiver.mjpeg_buffer), 66)
        self.assertEqual(self.receiver._frame_start_time, 10.0)

        stale_at = 10.0 + MJPEG_BUFFER_MAX_AGE_S + 0.01
        self.receiver._process_mjpeg_data(b"B" * 8, stale_at)

        buffered = bytes(self.receiver.mjpeg_buffer)
        self.assertNotIn(b"A", buffered, "the expired partial frame survived")
        self.assertIn(b"B", buffered)
        self.assertIsNone(self.receiver._frame_start_time)

    def test_expired_partial_does_not_date_the_next_complete_frame(self):
        self.receiver._process_mjpeg_data(b"\xff\xd8" + b"A" * 64, 20.0)
        stale_at = 20.0 + MJPEG_BUFFER_MAX_AGE_S + 0.5

        jpeg = b"\xff\xd8" + b"C" * 200 + b"\xff\xd9"
        self.receiver._process_mjpeg_data(jpeg, stale_at)

        self.assertEqual(len(self.delivered), 1)
        _data, frame_start = self.delivered[0]
        self.assertEqual(frame_start, stale_at, "the new frame inherited the expired frame's timestamp")

    def test_fresh_partial_frame_is_kept(self):
        self.receiver._process_mjpeg_data(b"\xff\xd8" + b"A" * 64, 30.0)
        self.receiver._process_mjpeg_data(b"B" * 8, 30.0 + MJPEG_BUFFER_MAX_AGE_S * 0.5)

        buffered = bytes(self.receiver.mjpeg_buffer)
        self.assertIn(b"A", buffered, "a still-viable partial frame was thrown away")
        self.assertEqual(self.receiver._frame_start_time, 30.0)


# ---------------------------------------------------------------------------
# Freshness: receiver swap + backwards sequence
# ---------------------------------------------------------------------------


class TestCaptureServiceReceiverSwap(unittest.TestCase):
    def _service(self, receiver):
        service = CaptureService()
        service.mode = "UDP"
        service.udp_manager = mock.MagicMock()
        service.udp_manager.get_receiver.return_value = receiver
        return service

    def test_first_read_keeps_after_seq_for_a_mock_receiver(self):
        receiver = FakeUdpReceiver()
        service = self._service(receiver)

        service.read_frame_with_seq(apply_fov=False, after_seq=42, timeout=0.0)

        self.assertEqual(
            receiver.after_seqs, [42],
            "the very first read must keep the caller's after_seq (mock/hot-start compatibility)",
        )

    def test_swapping_in_a_stopped_receiver_resets_after_seq(self):
        old = FakeUdpReceiver(connected=True, seq=900)
        service = self._service(old)
        service.read_frame_with_seq(apply_fov=False, after_seq=900, timeout=0.0)
        self.assertEqual(old.after_seqs, [900])

        old.is_connected = False
        old.stop_event.set()
        new = FakeUdpReceiver(connected=True, seq=1)
        service.udp_manager.get_receiver.return_value = new
        service.read_frame_with_seq(apply_fov=False, after_seq=900, timeout=0.0)

        # A None after_seq skips wait_for_new_frame entirely, so the new
        # receiver must have been read through the non-blocking path.
        self.assertEqual(
            new.current_frame_calls, 1,
            "the rebuilt receiver kept the old sequence watermark and would wait forever",
        )
        self.assertEqual(new.after_seqs, [])

    def test_swapping_in_a_live_receiver_keeps_after_seq(self):
        """Only a *stopped* predecessor is proof of a real receiver swap."""
        old = FakeUdpReceiver(connected=True, seq=900)
        service = self._service(old)
        service.read_frame_with_seq(apply_fov=False, after_seq=900, timeout=0.0)

        new = FakeUdpReceiver(connected=True, seq=901)
        service.udp_manager.get_receiver.return_value = new
        service.read_frame_with_seq(apply_fov=False, after_seq=900, timeout=0.0)

        self.assertEqual(new.after_seqs, [900], "a live receiver lost the caller's watermark")

    def test_same_receiver_keeps_after_seq(self):
        receiver = FakeUdpReceiver()
        service = self._service(receiver)

        service.read_frame_with_seq(apply_fov=False, after_seq=5, timeout=0.0)
        service.read_frame_with_seq(apply_fov=False, after_seq=6, timeout=0.0)

        self.assertEqual(receiver.after_seqs, [5, 6])


class TestTrackOnceSequenceResync(unittest.TestCase):
    def _tracker(self):
        from main import AimTracker

        tracker = AimTracker.__new__(AimTracker)
        tracker.app = mock.MagicMock()
        tracker.app.capture.is_connected.return_value = True
        tracker.app.capture.mode = "UDP"
        tracker._last_frame_seq = None
        tracker._handle_button_mask = mock.MagicMock()
        tracker._update_raw_stream_windows = mock.MagicMock()
        tracker._track_frame = mock.MagicMock()
        tracker._close_raw_stream_windows = mock.MagicMock()
        return tracker

    def test_backwards_sequence_is_processed_as_a_new_frame(self):
        tracker = self._tracker()
        tracker._last_frame_seq = 500
        frame = np.zeros((8, 8, 3), np.uint8)
        tracker.app.capture.read_frame_with_seq.return_value = (frame, 2)

        self.assertTrue(tracker.track_once(), "a restarted sequence was treated as stale forever")
        self.assertEqual(tracker._last_frame_seq, 2)
        self.assertEqual(tracker._track_frame.call_count, 1)

    def test_forward_sequence_behaviour_is_unchanged(self):
        tracker = self._tracker()
        tracker._last_frame_seq = 3
        frame = np.zeros((8, 8, 3), np.uint8)
        tracker.app.capture.read_frame_with_seq.return_value = (frame, 4)

        self.assertTrue(tracker.track_once())
        self.assertEqual(tracker._last_frame_seq, 4)

    def test_equal_sequence_is_still_skipped(self):
        tracker = self._tracker()
        tracker._last_frame_seq = 4
        frame = np.zeros((8, 8, 3), np.uint8)
        tracker.app.capture.read_frame_with_seq.return_value = (frame, 4)

        self.assertFalse(tracker.track_once())
        tracker._track_frame.assert_not_called()


# ---------------------------------------------------------------------------
# WindMouse: backwards clock
# ---------------------------------------------------------------------------


class _ClockConfig:
    smooth_reaction_min = 0.08
    smooth_reaction_max = 0.20
    smooth_gravity = 10.0
    smooth_wind = 2.0
    smooth_max_step = 22.0
    smooth_min_step = 2.0
    smooth_min_delay = 0.001
    smooth_max_delay = 0.0025
    smooth_distance_threshold = 45.0
    smooth_close_range = 30.0
    smooth_close_speed = 0.3
    smooth_far_range = 200.0
    smooth_far_speed = 0.8
    smooth_max_step_ratio = 0.15
    smooth_target_area_ratio = 0.05
    smooth_acceleration = 0.8
    smooth_deceleration = 0.6
    wm_deadzone_px = 0.4


class TestSmoothAimingClockJumps(unittest.TestCase):
    def setUp(self):
        import src.aim_system.windmouse_smooth as wm_module

        self.module = wm_module
        self._real_time = wm_module.time
        self.clock = types.SimpleNamespace(now=1000.0)
        self.clock.time = lambda: self.clock.now
        wm_module.time = self.clock
        self.aimer = wm_module.SmoothAiming(seed=5)
        self.config = _ClockConfig()

    def tearDown(self):
        self.module.time = self._real_time

    def test_backwards_jump_does_not_freeze_the_reaction_window(self):
        self.aimer.calculate_smooth_path(60.0, 0.0, self.config)
        self.assertGreater(self.aimer.reaction_delay, 0.0, "no reaction window was opened")
        self.assertEqual(self.aimer.calculate_smooth_path(60.0, 0.0, self.config), [])

        # NTP correction: the clock steps back 5 s.
        self.clock.now -= 5.0
        self.aimer.calculate_smooth_path(60.0, 0.0, self.config)

        self.assertEqual(self.aimer.reaction_delay, 0.0, "the reaction window stayed open after a clock jump")
        self.assertFalse(self.aimer.in_reaction_delay(), "aim would stay frozen after a clock jump")

        # The next frames must actually move again.
        paths = []
        for _ in range(6):
            self.clock.now += 1.0 / 144.0
            paths.append(self.aimer.calculate_smooth_path(60.0, 0.0, self.config))
        self.assertTrue(any(paths), "aiming never resumed after the clock jumped backwards")

    def test_in_reaction_delay_is_false_when_the_clock_moved_backwards(self):
        self.aimer.reaction_delay = 0.2
        self.aimer.last_reaction_time = 500.0

        self.assertFalse(self.aimer.in_reaction_delay(400.0))

    def test_update_velocity_discards_a_negative_interval(self):
        self.aimer.update_velocity(10.0, 0.0, 1000.0)
        self.aimer.update_velocity(20.0, 0.0, 1000.02)
        self.assertGreater(abs(self.aimer.velocity_x), 0.0)

        self.aimer.update_velocity(30.0, 0.0, 900.0)

        self.assertEqual(self.aimer.velocity_x, 0.0, "a negative dt produced velocity")
        self.assertEqual(self.aimer.velocity_y, 0.0)
        self.assertEqual(self.aimer.dir_history_x, [])
        self.assertEqual(self.aimer.last_target_time, 900.0, "the velocity model was not re-anchored")

        # A normal forward interval right after the re-anchor still works.
        self.aimer.update_velocity(60.0, 0.0, 900.02)
        self.assertGreater(self.aimer.velocity_x, 0.0)


# ---------------------------------------------------------------------------
# Preview renderer: idle HighGUI pump
# ---------------------------------------------------------------------------


class TestPreviewIdlePump(unittest.TestCase):
    def setUp(self):
        from src.utils import preview_throttle

        self.preview = preview_throttle
        self.preview.shutdown()
        self.pumped = []
        self.painted = []
        self._patches = [
            mock.patch.object(self.preview, "_cv2_imshow", lambda name, image: self.painted.append(name)),
            mock.patch.object(self.preview, "_cv2_wait_key", self._record_pump),
            mock.patch.object(self.preview, "_cv2_destroy", lambda name: None),
        ]
        for patch in self._patches:
            patch.start()

    def _record_pump(self, delay):
        self.pumped.append(delay)
        return -1

    def tearDown(self):
        for patch in self._patches:
            patch.stop()
        self.preview.shutdown()
        self.preview.reset()

    def test_idle_worker_pumps_waitkey_for_a_created_window(self):
        image = np.zeros((8, 8, 3), np.uint8)
        self.preview.imshow("Detection", image)

        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline and not self.painted:
            time.sleep(0.005)
        self.assertTrue(self.painted, "the worker never painted the submitted frame")

        base = len(self.pumped)
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline and len(self.pumped) <= base:
            time.sleep(0.01)

        self.assertGreater(
            len(self.pumped), base,
            "the idle worker never pumped HighGUI: the window would be marked Not Responding",
        )
        # The paint itself pumped once; the additions come from the idle loop.
        self.assertIn(1, self.pumped, "the idle pump must use waitKey(1)")

    def test_idle_pump_does_not_block_the_caller(self):
        image = np.zeros((8, 8, 3), np.uint8)
        self.preview.imshow("Detection", image)
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline and not self.painted:
            time.sleep(0.005)

        started = time.perf_counter()
        for _ in range(200):
            self.preview.imshow("Detection", image)
        submit_s = time.perf_counter() - started

        self.assertLess(submit_s, 0.1, f"200 submits took {submit_s * 1000:.1f} ms")

    def test_shutdown_still_joins_quickly_while_idle(self):
        image = np.zeros((8, 8, 3), np.uint8)
        self.preview.imshow("Detection", image)
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline and not self.painted:
            time.sleep(0.005)

        started = time.perf_counter()
        self.preview.shutdown(timeout=2.0)
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 2.0, f"shutdown took {elapsed:.2f}s")
        self.assertFalse(self.preview.stats()["worker_alive"])


class TestPreviewCountersArePerSession(unittest.TestCase):
    """``stats()`` must describe the current renderer, not the whole process.

    The counters used to live for the lifetime of the interpreter: after a
    shutdown/restart cycle the next worker inherited every paint of the
    previous one, so one submitted frame was reported as several renders and
    the "worker replays stale frames" symptom appeared with no backlog at all.
    """

    def setUp(self):
        from src.utils import preview_throttle

        self.preview = preview_throttle
        self.preview.shutdown()
        self.preview.reset()
        self.painted = []
        self._patches = [
            mock.patch.object(self.preview, "_cv2_imshow", lambda name, image: self.painted.append(name)),
            mock.patch.object(self.preview, "_cv2_wait_key", lambda delay: -1),
            mock.patch.object(self.preview, "_cv2_destroy", lambda name: None),
        ]
        for patch in self._patches:
            patch.start()

    def tearDown(self):
        for patch in self._patches:
            patch.stop()
        self.preview.shutdown()
        self.preview.reset()

    def _paint_one_and_wait(self):
        image = np.zeros((8, 8, 3), np.uint8)
        before = len(self.painted)
        self.preview.imshow("Detection", image)
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline and len(self.painted) <= before:
            time.sleep(0.005)
        self.assertGreater(len(self.painted), before, "the worker never painted")

    def test_counters_restart_with_a_new_worker(self):
        self._paint_one_and_wait()
        self.assertGreaterEqual(self.preview.stats()["rendered"], 1)
        self.preview.shutdown(timeout=2.0)

        # A brand-new session: exactly one submit, so at most one render.
        self._paint_one_and_wait()
        stats = self.preview.stats()
        self.assertEqual(
            stats["submitted"], 1,
            f"the new session inherited {stats['submitted']} submits from the previous one",
        )
        self.assertLessEqual(
            stats["rendered"], 2,
            f"the new session counted {stats['rendered']} renders for a single submit",
        )

    def test_reset_zeroes_the_counters(self):
        self._paint_one_and_wait()
        self.assertGreaterEqual(self.preview.stats()["rendered"], 1)

        self.preview.reset()

        self.assertEqual(
            self.preview.stats()["rendered"], 0, "reset() left the previous session's renders behind"
        )
        self.assertEqual(self.preview.stats()["submitted"], 0)


# ---------------------------------------------------------------------------
# UI periodic loops
# ---------------------------------------------------------------------------


class _LoopHost:
    """Minimal ViewerApp stand-in for the four periodic loops.

    Uses the real bound methods but a fake Tk root, so ``after()`` is observable
    without constructing any widget.
    """

    def __init__(self, failing=False):
        from src.ui import ViewerApp

        self._app = ViewerApp
        self._closing = False
        self._root = FakeTkRoot()
        self.capture = mock.MagicMock()
        self.capture.mode = "NDI"
        self.capture.is_connected.return_value = True
        self.capture.ndi.get_pending_source_updates.return_value = []
        self._runtime_busy = False
        self._runtime_active = False
        self._active_tab_name = "Telemetry"
        self._telemetry_job_id = None
        self.after_calls = []
        self.telemetry_canvas = mock.MagicMock()
        self.telemetry_canvas.winfo_exists.return_value = True
        self.tele_dxdy = None
        self.tele_baud = None
        self.tele_step = None
        self._draw_telemetry_waveform = mock.MagicMock()
        self._update_hardware_status_ui = mock.MagicMock()
        self._refresh_capture_entry_card = mock.MagicMock()
        self._set_status_indicator = mock.MagicMock()
        self._udp_stream_starved = mock.MagicMock(return_value=False)
        self._apply_sources_to_ui = mock.MagicMock()
        self._telemetry_baudrate = mock.MagicMock(return_value="4,000,000")
        self._telemetry_step_text = mock.MagicMock(return_value="1.00 ms")
        self._telemetry_history = []

        if failing:
            self.capture.is_connected.side_effect = RuntimeError("capture exploded")
            self.capture.ndi.get_pending_source_updates.side_effect = RuntimeError("ndi exploded")
            self._update_hardware_status_ui.side_effect = RuntimeError("hw exploded")
            self._draw_telemetry_waveform.side_effect = RuntimeError("canvas exploded")
            self._set_footer_state_error = True
            self.footer_state_label = mock.MagicMock()
            self.footer_state_label.winfo_exists.side_effect = RuntimeError("widget gone")
        else:
            self._set_footer_state_error = False

    def __getattr__(self, name):
        """Resolve unset helpers to the real ViewerApp methods, bound here.

        ``__init__`` pins every helper the four loops touch, but binding the
        remainder from the real class keeps this fake from silently drifting
        away from the production surface (and needs no Tk widget).
        """
        try:
            viewer = object.__getattribute__(self, "_app")
        except AttributeError:
            raise AttributeError(name) from None
        try:
            attribute = getattr(viewer, name)
        except AttributeError:
            raise AttributeError(name) from None
        if callable(attribute):
            return types.MethodType(attribute, self)
        return attribute

    # The bound methods use exactly these three hooks.
    def after(self, delay, callback=None):
        self.after_calls.append((delay, callback))
        return self._root.after(delay, callback)

    def winfo_exists(self):
        return self._root.winfo_exists()

    def _schedule_periodic(self, delay_ms, callback):
        return self._app._schedule_periodic(self, delay_ms, callback)

    def _set_footer_state(self):
        if getattr(self, "_set_footer_state_error", False):
            raise RuntimeError("footer chip exploded")


def _bind(host, name):
    """Bind a real ViewerApp loop method onto the host."""
    from src.ui import ViewerApp

    return types.MethodType(getattr(ViewerApp, name), host)


class TestUiPeriodicLoopsSurviveExceptions(unittest.TestCase):
    LOOPS = (
        ("_update_connection_status_loop", 500),
        ("_blink_footer_state", 600),
        ("_process_source_updates", 100),
        ("_update_telemetry_hud", 120),
    )

    def test_each_loop_reschedules_after_the_body_raises(self):
        for name, delay in self.LOOPS:
            with self.subTest(loop=name):
                host = _LoopHost(failing=True)
                _bind(host, name)()

                self.assertEqual(
                    len(host.after_calls), 1,
                    f"{name} did not reschedule after an exception",
                )
                self.assertEqual(host.after_calls[0][0], delay)
                self.assertEqual(
                    host.after_calls[0][1].__name__, name,
                    f"{name} rescheduled something else",
                )

    def test_each_loop_reschedules_on_the_happy_path(self):
        for name, delay in self.LOOPS:
            with self.subTest(loop=name):
                host = _LoopHost(failing=False)
                _bind(host, name)()

                self.assertEqual(len(host.after_calls), 1, f"{name} did not reschedule")
                self.assertEqual(host.after_calls[0][0], delay)

    def test_no_loop_reschedules_after_closing(self):
        for name, _delay in self.LOOPS:
            with self.subTest(loop=name):
                host = _LoopHost(failing=False)
                host._closing = True
                _bind(host, name)()

                self.assertEqual(host.after_calls, [], f"{name} re-armed itself after close")

    def test_no_loop_reschedules_when_the_window_is_gone(self):
        for name, _delay in self.LOOPS:
            with self.subTest(loop=name):
                host = _LoopHost(failing=False)
                host._root.exists = False
                _bind(host, name)()

                self.assertEqual(host.after_calls, [], f"{name} re-armed itself on a dead window")

    def test_telemetry_keeps_its_tab_closed_contract(self):
        host = _LoopHost(failing=False)
        host._active_tab_name = "Main"
        _bind(host, "_update_telemetry_hud")()

        self.assertEqual(host.after_calls, [], "the telemetry HUD kept running with its tab closed")
        self.assertIsNone(host._telemetry_job_id)

    def test_telemetry_stops_when_the_canvas_is_gone(self):
        host = _LoopHost(failing=False)
        host.telemetry_canvas.winfo_exists.return_value = False
        _bind(host, "_update_telemetry_hud")()

        self.assertEqual(host.after_calls, [])

    def test_telemetry_records_its_job_id(self):
        host = _LoopHost(failing=False)
        _bind(host, "_update_telemetry_hud")()

        self.assertIsNotNone(host._telemetry_job_id, "_telemetry_job_id was not updated")

    def test_each_loop_recovers_on_the_next_tick(self):
        """The reschedule must point at the same loop, so the failure is one-shot."""
        for name, _delay in self.LOOPS:
            with self.subTest(loop=name):
                host = _LoopHost(failing=True)
                method = _bind(host, name)
                method()

                self.assertEqual(len(host.after_calls), 1)
                _delay, callback = host.after_calls[0]
                self.assertEqual(getattr(callback, "__func__", None), getattr(method, "__func__", None))


# ---------------------------------------------------------------------------
# Main loops
# ---------------------------------------------------------------------------


class TestMoveQueueLoopStability(unittest.TestCase):
    def _tracker(self):
        from main import AimTracker
        import queue as queue_module

        tracker = AimTracker.__new__(AimTracker)
        tracker._stop_event = threading.Event()
        tracker.move_queue = queue_module.Queue(maxsize=50)
        tracker._move_batch_size = 4
        tracker._move_batch_small_step = 3.0
        tracker.controller = mock.MagicMock()
        return tracker

    def test_loop_survives_a_failing_move_and_keeps_consuming(self):
        tracker = self._tracker()
        tracker.controller.move.side_effect = [RuntimeError("driver hiccup"), None]

        thread = threading.Thread(target=tracker._process_move_queue, daemon=True)
        thread.start()
        try:
            tracker.move_queue.put((1.0, 1.0, 0.0))
            deadline = time.perf_counter() + 2.0
            while time.perf_counter() < deadline and tracker.controller.move.call_count < 1:
                time.sleep(0.005)
            self.assertEqual(tracker.controller.move.call_count, 1)

            # The next command must still be delivered: one driver error must
            # not end the move thread.
            tracker.move_queue.put((2.0, 2.0, 0.0))
            deadline = time.perf_counter() + 2.0
            while time.perf_counter() < deadline and tracker.controller.move.call_count < 2:
                time.sleep(0.005)
            self.assertTrue(thread.is_alive(), "one failing move killed the move-queue thread")
            self.assertGreaterEqual(
                tracker.controller.move.call_count, 2,
                "the move thread stopped consuming after one failing move",
            )
        finally:
            tracker._stop_event.set()
            thread.join(timeout=2.0)

    def test_loop_exits_after_stop_even_with_a_continuous_producer(self):
        tracker = self._tracker()
        stop_producing = threading.Event()

        def produce():
            while not stop_producing.is_set() and not tracker._stop_event.is_set():
                try:
                    tracker.move_queue.put((1.0, 0.0, 0.0), timeout=0.01)
                except Exception:
                    pass

        thread = threading.Thread(target=tracker._process_move_queue, daemon=True)
        producer = threading.Thread(target=produce, daemon=True)
        thread.start()
        producer.start()
        time.sleep(0.05)
        tracker._stop_event.set()
        thread.join(timeout=2.0)
        stop_producing.set()
        producer.join(timeout=1.0)

        self.assertFalse(thread.is_alive(), "the move queue never observed the stop event")

    def test_stop_skips_a_long_remaining_delay(self):
        tracker = self._tracker()
        tracker.move_queue.put((1.0, 0.0, 5.0))  # a 5 s inter-step delay

        thread = threading.Thread(target=tracker._process_move_queue, daemon=True)
        thread.start()
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline and tracker.controller.move.call_count < 1:
            time.sleep(0.01)
        tracker._stop_event.set()
        thread.join(timeout=2.0)

        self.assertFalse(thread.is_alive(), "shutdown waited out a queued step delay")


class TestTrackLoopStability(unittest.TestCase):
    def test_loop_survives_an_exception_in_its_own_body(self):
        """An exception outside track_once must not end the thread either."""
        from main import AimTracker

        class FlakyFps:
            """Fails once, then behaves: the loop must recover, not exit."""

            def __init__(self):
                self.calls = 0

            def __float__(self):
                self.calls += 1
                if self.calls == 2:
                    raise TypeError("config was being reloaded")
                return 200.0

        tracker = AimTracker.__new__(AimTracker)
        tracker._stop_event = threading.Event()
        tracker._target_fps = FlakyFps()
        tracker._last_frame_seq = None
        iterations = {"n": 0}

        def fake_track_once(frame_timeout=0.0):
            iterations["n"] += 1
            if iterations["n"] >= 6:
                tracker._stop_event.set()
            return False

        tracker.track_once = fake_track_once
        thread = threading.Thread(target=tracker._track_loop, daemon=True)
        thread.start()
        thread.join(timeout=5.0)
        tracker._stop_event.set()

        self.assertFalse(thread.is_alive(), "the track loop never stopped")
        self.assertGreater(
            iterations["n"], 3,
            "the track loop stopped after an exception in its own body",
        )

    def test_stop_ends_the_final_spin_promptly(self):
        from main import AimTracker

        tracker = AimTracker.__new__(AimTracker)
        tracker._stop_event = threading.Event()
        tracker._target_fps = 200.0
        tracker._last_frame_seq = None
        tracker.track_once = lambda frame_timeout=0.0: False

        thread = threading.Thread(target=tracker._track_loop, daemon=True)
        thread.start()
        time.sleep(0.05)
        started = time.perf_counter()
        tracker._stop_event.set()
        thread.join(timeout=2.0)
        elapsed = time.perf_counter() - started

        self.assertFalse(thread.is_alive(), "the track loop ignored the stop event")
        self.assertLess(elapsed, 1.0, f"stop took {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
