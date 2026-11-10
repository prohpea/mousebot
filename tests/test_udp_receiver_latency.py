"""L1-L15: OBS_UDP_Receiver latency, slot and lifecycle contracts (plan §6.3).

Rewritten from the single-case version: the old file only proved that one
single-packet frame decoded under 1.5 ms and skipped the whole class when
TurboJPEG was missing. These cases cover the default port, the size-1 slot,
zero backlog, stats keys, timer refcounting, thread priority, disconnect
cleanup, bind failure and the logging bridge.

Latency assertions use p50/p95 and skip individually (never class-wide) when
TurboJPEG or Windows is unavailable.
"""

import os
import socket
import sys
import threading
import time
import unittest
from unittest import mock

import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.capture import OBS_UDP  # noqa: E402
from src.capture.OBS_UDP import (  # noqa: E402
    FRAME_TIMEOUT_SEC,
    OBS_UDP_Receiver,
)

try:
    import turbojpeg

    _TURBOJPEG_AVAILABLE = True
except Exception:
    turbojpeg = None
    _TURBOJPEG_AVAILABLE = False

_IS_WINDOWS = sys.platform == "win32"
_SKIP_DECODE = "TurboJPEG unavailable" if not _TURBOJPEG_AVAILABLE else None


def _jpeg_of(color, size=128):
    """A real JPEG (needed for L2/L3/L6). Caller must check TurboJPEG first."""
    encoder = turbojpeg.TurboJPEG()
    image = np.zeros((size, size, 3), dtype=np.uint8)
    image[:, :] = color
    return encoder.encode(image)


_TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00"
    b"\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19"
    b"\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05"
    b"\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07"
    b"\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
)


def _encode_any(color, size=128):
    """Encode with TurboJPEG when available, else OpenCV (both 128x128)."""
    image = np.zeros((size, size, 3), dtype=np.uint8)
    image[:, :] = color
    if _TURBOJPEG_AVAILABLE:
        return turbojpeg.TurboJPEG().encode(image)
    try:
        import cv2
        ok, encoded = cv2.imencode(".jpg", image)
        if ok:
            return encoded.tobytes()
    except Exception:
        pass
    return _TINY_JPEG


def _free_udp_port():
    """Reserve-then-release a loopback UDP port (never 5000 in CI)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class _ReceiverTestCase(unittest.TestCase):
    """Creates a receiver that never binds 5000 and always cleans up."""

    def make_receiver(self, **kwargs):
        receiver = OBS_UDP_Receiver(
            ip="127.0.0.1", port=_free_udp_port(), target_fps=144, **kwargs
        )
        self.addCleanup(receiver.disconnect)
        return receiver

    def start_decode_worker(self, receiver):
        receiver.is_connected = True
        receiver.stop_event.clear()
        receiver.processing_thread = threading.Thread(
            target=receiver._decode_worker_loop, daemon=True
        )
        receiver.processing_thread.start()
        return receiver.processing_thread


class TestDefaults(_ReceiverTestCase):
    # -- L1 ---------------------------------------------------------------
    def test_default_port_is_5000(self):
        receiver = OBS_UDP_Receiver()
        self.addCleanup(receiver.disconnect)
        self.assertEqual(receiver.port, 5000)
        self.assertEqual(receiver.ip, "0.0.0.0")
        self.assertEqual(OBS_UDP.DEFAULT_UDP_PORT, 5000)
        self.assertEqual(OBS_UDP.DEFAULT_UDP_IP, "0.0.0.0")
        self.assertAlmostEqual(receiver.reassembly_timeout, FRAME_TIMEOUT_SEC)
        self.assertAlmostEqual(FRAME_TIMEOUT_SEC, 0.005)


@unittest.skipIf(_SKIP_DECODE, _SKIP_DECODE)
@unittest.skipUnless(_IS_WINDOWS, "latency thresholds are defined for Windows")
class TestDecodeLatency(_ReceiverTestCase):
    def _measure(self, count=30, warmup=5):
        receiver = self.make_receiver()
        self.start_decode_worker(receiver)
        jpeg = _jpeg_of((255, 100, 50))
        delays = []
        for index in range(warmup + count):
            receiver._process_mjpeg_data(jpeg, time.perf_counter())
            deadline = time.perf_counter() + 0.2
            while receiver.get_performance_stats()["frames_decoded"] <= index:
                if time.perf_counter() > deadline:
                    self.fail("decode worker did not consume the frame in time")
                time.sleep(0.001)
            if index >= warmup:
                delays.append(receiver.get_performance_stats()["decode_delay_ms"])
        frame = receiver.get_current_frame()
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape[:2], (128, 128))
        return sorted(delays)

    @staticmethod
    def _percentile(sorted_values, fraction):
        index = min(len(sorted_values) - 1, int(round(fraction * (len(sorted_values) - 1))))
        return sorted_values[index]

    # -- L2 ---------------------------------------------------------------
    def test_single_packet_decode_latency_p50(self):
        p50 = self._percentile(self._measure(), 0.50)
        self.assertLess(p50, 1.5, f"decode p50={p50:.3f} ms >= 1.5 ms")

    # -- L3 ---------------------------------------------------------------
    def test_decode_latency_p95(self):
        p95 = self._percentile(self._measure(), 0.95)
        self.assertLess(p95, 3.0, f"decode p95={p95:.3f} ms >= 3.0 ms")


class TestPipeline(_ReceiverTestCase):
    # -- L4 ---------------------------------------------------------------
    def test_opencv_fallback_decodes(self):
        cv2_mod = getattr(OBS_UDP, "cv2", None)
        if cv2_mod is None or isinstance(cv2_mod, mock.MagicMock) or not hasattr(cv2_mod, "__file__"):
            raise unittest.SkipTest("real OpenCV unavailable in headless environment")
        receiver = self.make_receiver(force_opencv=True)
        jpeg = _encode_any((10, 200, 40))  # BGR green

        frame = receiver._decode_jpeg_frame_raw(jpeg)
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape[:2], (128, 128))
        stats = receiver.get_performance_stats()
        self.assertIn("OpenCV", stats["decoder_backend"])

    # -- L5 ---------------------------------------------------------------
    def test_slot_depth_never_exceeds_one(self):
        receiver = self.make_receiver()
        # No decode thread on purpose: the slot must overwrite, not queue.
        jpeg = b"\xff\xd8" + b"Q" * 500 + b"\xff\xd9"
        for _ in range(5):
            receiver._process_mjpeg_data(jpeg, time.perf_counter())

        stats = receiver.get_performance_stats()
        self.assertEqual(stats["queue_size"], 1)
        self.assertEqual(stats["queue_drops"], 4)
        self.assertEqual(stats["frames_received"], 5)

    # -- L6 ---------------------------------------------------------------
    @unittest.skipIf(_SKIP_DECODE, _SKIP_DECODE)
    def test_zero_backlog_keeps_latest_frame(self):
        receiver = self.make_receiver()
        self.start_decode_worker(receiver)
        first = _jpeg_of((0, 0, 255))
        second = _jpeg_of((255, 0, 0))
        # Reference decode of the NEWEST frame: comparison is channel-order
        # agnostic, unlike asserting a specific BGR value.
        expected = receiver._decode_jpeg_frame_raw(second)
        self.assertIsNotNone(expected)

        # Push both before the worker gets scheduled: the slot keeps the last.
        receiver._process_mjpeg_data(first, time.perf_counter())
        receiver._process_mjpeg_data(second, time.perf_counter())

        deadline = time.perf_counter() + 0.5
        while time.perf_counter() < deadline:
            frame = receiver.get_current_frame()
            if frame is not None and np.array_equal(frame, expected):
                return
            time.sleep(0.001)
        self.fail(
            "the slot never delivered the newest frame "
            f"(frames_decoded={receiver.get_performance_stats()['frames_decoded']})"
        )

    # -- L7 ---------------------------------------------------------------
    @unittest.skipIf(_SKIP_DECODE, _SKIP_DECODE)
    def test_receive_delay_non_negative(self):
        receiver = self.make_receiver()
        self.start_decode_worker(receiver)
        receiver._process_mjpeg_data(_jpeg_of((0, 255, 0)), time.perf_counter())

        deadline = time.perf_counter() + 0.5
        while receiver.get_performance_stats()["frames_decoded"] == 0:
            if time.perf_counter() > deadline:
                self.fail("decode worker never decoded the frame")
            time.sleep(0.001)

        stats = receiver.get_performance_stats()
        self.assertGreaterEqual(stats["receive_delay_ms"], 0.0)
        self.assertGreaterEqual(stats["decode_delay_ms"], 0.0)

    # -- L8 ---------------------------------------------------------------
    def test_stats_contract_keys(self):
        receiver = self.make_receiver()
        stats = receiver.get_performance_stats()

        legacy_float = (
            "current_fps", "processing_fps", "decoding_fps",
            "receive_delay_ms", "decode_delay_ms", "processing_delay_ms",
        )
        legacy_int = ("buffer_size_bytes", "queue_size", "max_workers")

        for key in legacy_float:
            self.assertIn(key, stats)
            self.assertIsInstance(stats[key], float, key)
        for key in legacy_int:
            self.assertIn(key, stats)
            self.assertIsInstance(stats[key], int, key)
        self.assertIn("target_fps", stats)
        self.assertIsInstance(stats["target_fps"], int)
        self.assertIsInstance(stats["is_connected"], bool)
        self.assertIsInstance(stats["is_receiving"], bool)

        for key in (
            "queue_drops", "reassembly_drops", "timeout_drops", "restart_drops",
            "invalid_packets", "oversize_packets", "bad_frames", "frames_received",
            "frames_decoded", "decode_errors", "packets_received", "bytes_received",
            "timer_active", "rcvbuf_bytes", "receive_priority_ok",
            "decode_priority_ok", "last_frame_id",
        ):
            self.assertIn(key, stats, key)
            self.assertIsInstance(stats[key], int, key)
        self.assertIsInstance(stats["decoder_backend"], str)
        self.assertIn(stats["decoder_backend"], ("TurboJPEG", "OpenCV", "OpenCV (forced)"))

    # -- L9 ---------------------------------------------------------------
    def test_corrupt_jpeg_returns_none(self):
        receiver = self.make_receiver()
        self.assertIsNone(receiver._decode_jpeg_frame_raw(b"not a jpeg"))
        self.assertIsNone(receiver._decode_jpeg_frame_raw(b"\xff\xd8" + b"x" * 200))

        self.start_decode_worker(receiver)
        receiver._process_mjpeg_data(b"\xff\xd8" + b"x" * 200 + b"\xff\xd9", time.perf_counter())
        deadline = time.perf_counter() + 0.5
        while receiver.get_performance_stats()["decode_errors"] == 0:
            if time.perf_counter() > deadline:
                self.fail("decode worker never recorded a decode error")
            time.sleep(0.001)


class TestPrimitives(_ReceiverTestCase):
    # -- L10 --------------------------------------------------------------
    def test_windows_timer_idempotent(self):
        fake_winmm = mock.MagicMock()
        fake_winmm.timeBeginPeriod.return_value = 0
        fake_winmm.timeEndPeriod.return_value = 0

        with mock.patch.object(OBS_UDP.sys, "platform", "win32"), \
                mock.patch.object(OBS_UDP.ctypes, "WinDLL", return_value=fake_winmm):
            OBS_UDP._TIMER_REFCOUNT = 0
            OBS_UDP._TIMER_ACTIVE = False
            timer = OBS_UDP.WindowsTimer(1)
            self.assertTrue(timer.enable())
            self.assertTrue(timer.enable())  # idempotent for the same instance
            self.assertEqual(OBS_UDP._TIMER_REFCOUNT, 1)
            self.assertEqual(fake_winmm.timeBeginPeriod.call_count, 1)

            second = OBS_UDP.WindowsTimer(1)
            self.assertTrue(second.enable())
            self.assertEqual(OBS_UDP._TIMER_REFCOUNT, 2)
            self.assertEqual(fake_winmm.timeBeginPeriod.call_count, 1)

            second.disable()
            second.disable()  # must not raise nor underflow
            self.assertEqual(OBS_UDP._TIMER_REFCOUNT, 1)
            self.assertEqual(fake_winmm.timeEndPeriod.call_count, 0)

            timer.disable()
            self.assertEqual(OBS_UDP._TIMER_REFCOUNT, 0)
            self.assertEqual(fake_winmm.timeEndPeriod.call_count, 1)
            self.assertFalse(OBS_UDP._TIMER_ACTIVE)

        with mock.patch.object(OBS_UDP.sys, "platform", "linux"):
            self.assertFalse(OBS_UDP.WindowsTimer(1).enable())

    # -- L11 --------------------------------------------------------------
    def test_high_thread_priority_never_raises(self):
        result = OBS_UDP.set_high_thread_priority()
        self.assertIsInstance(result, bool)

        with mock.patch.object(OBS_UDP.ctypes, "WinDLL", side_effect=OSError("boom")):
            self.assertFalse(OBS_UDP.set_high_thread_priority())


class TestLifecycle(_ReceiverTestCase):
    # -- L12 --------------------------------------------------------------
    def test_disconnect_clears_frame_and_slot(self):
        receiver = self.make_receiver()
        self.start_decode_worker(receiver)
        receiver._process_mjpeg_data(_encode_any((0, 255, 0)), time.perf_counter())

        deadline = time.perf_counter() + 0.5
        while receiver.get_current_frame() is None:
            if time.perf_counter() > deadline:
                break
            time.sleep(0.001)

        receiver.disconnect()
        self.assertIsNone(receiver.get_current_frame())
        self.assertEqual(receiver.get_performance_stats()["queue_size"], 0)
        self.assertFalse(receiver.is_connected)
        self.assertFalse(receiver.is_receiving)

    # -- L13 --------------------------------------------------------------
    def test_connect_busy_port_returns_false(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        blocker.bind(("127.0.0.1", 0))
        port = blocker.getsockname()[1]
        self.addCleanup(blocker.close)

        receiver = OBS_UDP_Receiver(ip="127.0.0.1", port=port)
        self.addCleanup(receiver.disconnect)
        with mock.patch("builtins.print"):
            self.assertFalse(receiver.connect())
        self.assertFalse(receiver.is_connected)
        self.assertFalse(receiver._timer_active)

    # -- L14 --------------------------------------------------------------
    def test_legacy_api_surface(self):
        receiver = self.make_receiver()
        for name in (
            "set_target_fps", "update_connection_params", "set_frame_callback",
            "set_frame_callback_async", "_frame_processing_loop",
            "_process_mjpeg_data", "_decode_worker_loop", "_decode_jpeg_frame",
            "_decode_jpeg_frame_raw", "_is_frame_corrupted", "_update_frame",
            "get_current_frame", "get_performance_stats",
            "connect", "disconnect", "connect_async", "disconnect_async",
        ):
            self.assertTrue(hasattr(receiver, name), name)

        self.assertIsNone(receiver.get_current_frame())
        self.assertIsInstance(receiver.get_performance_stats(), dict)
        self.assertIsInstance(receiver._is_frame_corrupted(np.zeros((4, 4, 3), np.uint8)), bool)

        receiver.set_target_fps(240)
        self.assertEqual(receiver.target_fps, 240)
        receiver.update_connection_params("127.0.0.1", 6000)
        self.assertEqual((receiver.ip, receiver.port), ("127.0.0.1", 6000))


class TestLogBridge(_ReceiverTestCase):
    # -- L15 --------------------------------------------------------------
    def test_log_bridge_reaches_debug_logger(self):
        try:
            from src.utils import debug_logger
        except Exception as exc:  # pragma: no cover - only if the module is absent
            self.skipTest(f"debug_logger unavailable: {exc}")

        # Three receivers still install exactly one handler.
        receivers = [self.make_receiver() for _ in range(3)]
        handlers = [
            handler
            for handler in OBS_UDP.logger.handlers
            if isinstance(handler, OBS_UDP._DebugLoggerBridge)
        ]
        self.assertEqual(len(handlers), 1)
        self.assertFalse(OBS_UDP.logger.propagate)

        debug_logger.clear_logs()

        blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        blocker.bind(("127.0.0.1", 0))
        port = blocker.getsockname()[1]
        self.addCleanup(blocker.close)

        busy = OBS_UDP_Receiver(ip="127.0.0.1", port=port)
        self.addCleanup(busy.disconnect)
        self.assertFalse(busy.connect())

        messages = " ".join(str(entry.get("message", "")) for entry in debug_logger.get_recent_logs(200))
        self.assertIn("bind", messages.lower())
        self.assertIn(str(port), messages)
        # Sanity: the receivers created above are still healthy objects.
        self.assertEqual(len(receivers), 3)


if __name__ == "__main__":
    unittest.main()
