"""Receiver hot path: fragment expiry, socket sizing, single-slot, metadata.

Each assertion here covers a failure mode that is invisible in production:

* a half-assembled fragment set survives a lost fragment and is spliced onto the
  next frame (decodes to garbage, not to an error),
* SO_RCVBUF is requested but silently clamped by the OS, so only the value read
  back with getsockopt is evidence,
* the decoder slot keeps a backlog instead of decoding the newest frame,
* latency metadata describes a different frame than the one published.
"""
import os
import struct
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.capture.OBS_UDP import OBS_UDP_Receiver, FRAGMENT_HEADER

PORT_BASE = 13210


def _fragment(total_size, frag_idx, total_frags, payload):
    return FRAGMENT_HEADER.pack(total_size, frag_idx, total_frags) + payload


def _jpeg_stub(tag, size=200):
    """Byte string that looks like a JPEG to _deliver_jpeg and the stubs."""
    body = (tag.encode() * size)[:size]
    return b"\xff\xd8" + body + b"\xff\xd9"


class _FakeSocket:
    """Records setsockopt and reports a configurable granted buffer size."""

    def __init__(self, granted):
        self.granted = granted
        self.requested = None

    def setsockopt(self, level, opt, value):
        self.requested = value

    def getsockopt(self, level, opt):
        return self.granted


class _ConfigSandbox:
    """Pin config values so these tests do not depend on the user's config.json."""

    def __init__(self, **values):
        self.values = values
        self.previous = {}

    def __enter__(self):
        from src.utils.config import config
        for key, value in self.values.items():
            self.previous[key] = getattr(config, key, "__missing__")
            setattr(config, key, value)
        return self

    def __exit__(self, *exc_info):
        from src.utils.config import config
        for key, value in self.previous.items():
            if value == "__missing__":
                try:
                    delattr(config, key)
                except AttributeError:
                    pass
            else:
                setattr(config, key, value)
        return False


class TestFragmentReassembly(unittest.TestCase):
    def setUp(self):
        self._sandbox = _ConfigSandbox(receiver_fragment_timeout_ms=8.0)
        self._sandbox.__enter__()
        self.addCleanup(self._sandbox.__exit__, None, None, None)
        self.receiver = OBS_UDP_Receiver(ip="127.0.0.1", port=PORT_BASE, target_fps=144)
        self.delivered = []
        self.receiver._deliver_jpeg = lambda data, start: self.delivered.append((data, start))

    def tearDown(self):
        self.receiver.disconnect()

    def test_fragments_arriving_out_of_order_rebuild_the_frame(self):
        parts = [b"AAAA", b"BBBB", b"CCCC"]
        for idx in (2, 0, 1):
            self.receiver._try_reassemble_fragment(
                _fragment(200_000, idx, 3, parts[idx]), 1.0
            )

        self.assertEqual(len(self.delivered), 1)
        self.assertEqual(self.delivered[0][0], b"".join(parts))

    def test_reassembled_frame_starts_at_first_fragment_time(self):
        self.receiver._try_reassemble_fragment(_fragment(200_000, 0, 2, b"AA"), 5.0)
        self.receiver._try_reassemble_fragment(_fragment(200_000, 1, 2, b"BB"), 5.004)

        self.assertEqual(len(self.delivered), 1)
        self.assertEqual(self.delivered[0][1], 5.0, "frame start must be the first fragment")

    def test_expired_partial_frame_is_dropped_and_counted(self):
        self.receiver._try_reassemble_fragment(_fragment(200_000, 1, 3, b"BB"), 10.000)
        self.assertEqual(self.receiver.fragment_drops, 0)

        # 20 ms later, well past the 8 ms default deadline.
        self.receiver._try_reassemble_fragment(_fragment(200_000, 2, 3, b"CC"), 10.020)

        self.assertEqual(self.receiver.fragment_drops, 1)
        self.assertEqual(len(self.delivered), 0, "stale parts must never complete a frame")

    def test_old_fragments_plus_new_fragment_zero_do_not_make_a_frame(self):
        """The splice bug: frame N lost its fragment 0, frame N+1 starts over."""
        # Frame N: same size/count, missing fragment 0.
        self.receiver._try_reassemble_fragment(_fragment(200_000, 1, 3, b"OLD1"), 20.000)
        self.receiver._try_reassemble_fragment(_fragment(200_000, 2, 3, b"OLD2"), 20.001)

        # Frame N+1, fragment 0, after the reassembly deadline.
        self.receiver._try_reassemble_fragment(_fragment(200_000, 0, 3, b"NEW0"), 20.050)

        self.assertEqual(self.delivered, [], "two different frames were spliced together")
        self.assertEqual(self.receiver.fragment_drops, 1, "the drop must be counted once")

    def test_repeated_index_restarts_assembly_without_splicing(self):
        self.receiver._try_reassemble_fragment(_fragment(200_000, 0, 2, b"AA"), 30.000)
        self.receiver._try_reassemble_fragment(_fragment(200_000, 0, 2, b"XX"), 30.001)

        self.assertEqual(len(self.delivered), 0)
        self.assertEqual(self.receiver._frag_parts, {0: b"XX"})

    def test_single_packet_jpeg_passes_through_byte_for_byte(self):
        payload = _jpeg_stub("single")
        consumed_as_fragment = self.receiver._try_reassemble_fragment(payload, 40.0)

        self.assertFalse(consumed_as_fragment, "a whole JPEG must not be treated as a fragment")
        self.assertEqual(self.delivered, [])

        self.receiver._process_mjpeg_data(payload, 40.0)
        self.assertEqual(len(self.delivered), 1)
        self.assertEqual(self.delivered[0][0], payload)


class TestSocketConfiguration(unittest.TestCase):
    def setUp(self):
        self.receiver = OBS_UDP_Receiver(ip="127.0.0.1", port=PORT_BASE + 1, target_fps=144)

    def tearDown(self):
        self.receiver.disconnect()

    def test_requests_at_least_eight_megabytes(self):
        with _ConfigSandbox(receiver_rcvbuf_mb=8):
            fake = _FakeSocket(granted=8 * 1024 * 1024)
            self.receiver._configure_socket(fake)

        self.assertGreaterEqual(
            fake.requested, 8 * 1024 * 1024, "receiver must ask for the same 8 MB as the sender"
        )

    def test_stats_report_the_granted_size_not_the_requested_one(self):
        # Windows clamps: 8 MB requested, 1 MB granted.
        with _ConfigSandbox(receiver_rcvbuf_mb=8):
            fake = _FakeSocket(granted=1024 * 1024)
            self.receiver._configure_socket(fake)
            stats = self.receiver.get_performance_stats()

        self.assertEqual(stats["rcvbuf_requested_bytes"], fake.requested)
        self.assertEqual(stats["rcvbuf_actual_bytes"], 1024 * 1024)
        self.assertNotEqual(
            stats["rcvbuf_actual_bytes"],
            stats["rcvbuf_requested_bytes"],
            "stats must expose the clamp, not echo the request",
        )

    def test_stats_always_carry_the_new_counters(self):
        stats = self.receiver.get_performance_stats()
        for key in ("fragment_drops", "rcvbuf_requested_bytes", "rcvbuf_actual_bytes"):
            self.assertIn(key, stats)


class TestSingleSlotDecoder(unittest.TestCase):
    def setUp(self):
        self.receiver = OBS_UDP_Receiver(ip="127.0.0.1", port=PORT_BASE + 2, target_fps=144)
        self.decoded = []
        self.receiver._decode_fn = self._record_decode

    def tearDown(self):
        self.receiver.stop_event.set()
        self.receiver.is_connected = False
        self.receiver.disconnect()

    def _record_decode(self, jpeg_data):
        self.decoded.append(jpeg_data)
        return np.zeros((4, 4, 3), np.uint8)

    def test_three_queued_jpegs_cost_one_decode_and_it_is_the_last(self):
        # Nothing is running yet: the slot is overwritten twice before the
        # decoder thread ever looks at it.
        for tag in ("first", "middle", "last"):
            self.receiver._deliver_jpeg(_jpeg_stub(tag), time.perf_counter())

        self.receiver.is_connected = True
        worker = threading.Thread(target=self.receiver._decode_worker_loop, daemon=True)
        worker.start()

        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline and not self.decoded:
            time.sleep(0.005)
        self.receiver.stop_event.set()
        worker.join(timeout=1.0)

        self.assertEqual(len(self.decoded), 1, f"decoded {len(self.decoded)} frames for 3 arrivals")
        self.assertIn(b"last", self.decoded[0])

    def test_middle_frame_is_skipped_while_the_decoder_is_busy(self):
        """A blocked decoder must not queue the backlog behind it."""
        gate = threading.Event()
        started = threading.Event()
        order = []

        def blocking_decode(jpeg_data):
            order.append(jpeg_data)
            if len(order) == 1:
                started.set()
                gate.wait(timeout=2.0)
            return np.zeros((4, 4, 3), np.uint8)

        self.receiver._decode_fn = blocking_decode
        self.receiver.is_connected = True
        worker = threading.Thread(target=self.receiver._decode_worker_loop, daemon=True)
        worker.start()

        self.receiver._deliver_jpeg(_jpeg_stub("first"), time.perf_counter())
        self.assertTrue(started.wait(timeout=2.0), "decoder never started")
        self.receiver._deliver_jpeg(_jpeg_stub("middle"), time.perf_counter())
        self.receiver._deliver_jpeg(_jpeg_stub("last"), time.perf_counter())
        gate.set()

        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline and len(order) < 2:
            time.sleep(0.005)
        self.receiver.stop_event.set()
        worker.join(timeout=1.0)

        self.assertIn(b"last", order[-1], "the newest frame must be the one decoded next")
        self.assertFalse(
            any(b"middle" in item for item in order), "the superseded frame was still decoded"
        )


class TestFrameMetadata(unittest.TestCase):
    def setUp(self):
        self.receiver = OBS_UDP_Receiver(ip="127.0.0.1", port=PORT_BASE + 3, target_fps=144)

    def tearDown(self):
        self.receiver.disconnect()

    def test_metadata_is_empty_before_the_first_frame(self):
        self.assertEqual(self.receiver.get_last_frame_meta(), {})

    def test_metadata_describes_the_published_frame(self):
        frame = np.zeros((4, 4, 3), np.uint8)
        self.receiver.decode_delay = 1.25
        self.receiver._update_frame(frame, t_published=100.005, t_frame_start=100.000)

        meta = self.receiver.get_last_frame_meta()
        self.assertEqual(meta["frame_seq"], 1)
        self.assertAlmostEqual(meta["published_at"], 100.005, places=6)
        self.assertAlmostEqual(meta["publish_latency_ms"], 5.0, places=3)
        self.assertAlmostEqual(meta["decode_ms"], 1.25, places=3)

    def test_metadata_is_visible_before_the_frame_wakes_a_waiter(self):
        """A waiter woken by the publish must see THAT frame's metadata.

        Writing the metadata after notify_all() leaves a window where the
        consumer reads the previous frame's timing, which silently mislabels
        every latency sample.
        """
        frame = np.zeros((4, 4, 3), np.uint8)
        _, seq = self.receiver.get_current_frame_with_seq()
        observed = {}

        def wait_and_read():
            _frame, got = self.receiver.wait_for_new_frame(seq, timeout=2.0)
            observed["meta"] = self.receiver.get_last_frame_meta()

        waiter = threading.Thread(target=wait_and_read, daemon=True)
        waiter.start()
        time.sleep(0.05)
        self.receiver._update_frame(frame, t_published=50.0, t_frame_start=49.999)
        waiter.join(timeout=2.0)

        self.assertIn("meta", observed)
        self.assertEqual(
            observed["meta"].get("frame_seq"), 1,
            "the woken consumer saw metadata for a different frame",
        )
        self.assertAlmostEqual(observed["meta"].get("published_at"), 50.0, places=6)

    def test_metadata_follows_the_newest_publish(self):
        self.receiver._update_frame(np.zeros((4, 4, 3), np.uint8), t_published=10.0,
                                   t_frame_start=9.999)
        self.receiver._update_frame(np.zeros((4, 4, 3), np.uint8), t_published=20.0,
                                   t_frame_start=19.999)

        meta = self.receiver.get_last_frame_meta()
        self.assertEqual(meta["frame_seq"], 2)
        self.assertAlmostEqual(meta["published_at"], 20.0, places=6)

    def test_meta_is_a_copy_not_the_live_dict(self):
        self.receiver._update_frame(np.zeros((4, 4, 3), np.uint8))
        first = self.receiver.get_last_frame_meta()
        first["frame_seq"] = 999
        self.assertNotEqual(self.receiver.get_last_frame_meta()["frame_seq"], 999)

    def test_two_tuple_contract_is_unchanged(self):
        """test_track_freshness.py asserts this shape; it must not grow."""
        frame, seq = self.receiver.wait_for_new_frame(None, 0.0)
        self.assertIsNone(frame)
        self.assertEqual(seq, 0)


class TestTelemetrySnapshotFromLiveReceiver(unittest.TestCase):
    """The snapshot must read the real receiver API, not a parallel shim."""

    def _service_with(self, receiver):
        service = MagicMock()
        service.mode = "UDP"
        service.is_connected.return_value = True
        service.udp_manager.get_receiver.return_value = receiver
        service._ip = "0.0.0.0"
        service._port = PORT_BASE + 9
        return service

    def test_telemetry_snapshot_from_live_receiver(self):
        from src.utils.obs_udp_plugin import build_udp_telemetry_snapshot

        receiver = OBS_UDP_Receiver(ip="127.0.0.1", port=PORT_BASE + 9, target_fps=144)
        try:
            # Publish a frame without ever opening a socket.
            frame = np.zeros((320, 320, 3), np.uint8)
            receiver._update_frame(frame, t_published=200.004, t_frame_start=200.000)
            receiver.current_fps = 143.0
            receiver.decoding_fps = 142.0

            with _ConfigSandbox(
                detection_engine="ai_detection",
                ai_model_path="models/my_yolo_model.onnx",
                udp_fov_enabled=True,
                udp_fov=108,
                ai_udp_bypass_tiny_crop=True,
            ):
                snapshot = build_udp_telemetry_snapshot(
                    self._service_with(receiver),
                    plugin_status={"installed": True, "missing": []},
                )
        finally:
            receiver.disconnect()

        self.assertTrue(snapshot["available"])
        self.assertEqual(snapshot["resolution"], "320x320")
        self.assertEqual((snapshot["width"], snapshot["height"]), (320, 320))
        self.assertAlmostEqual(snapshot["fps"], 143.0, places=1)
        self.assertAlmostEqual(snapshot["decode_fps"], 142.0, places=1)
        # 4 ms publish latency comes from the receiver's own metadata.
        self.assertAlmostEqual(snapshot["receive_ms"], 4.0, places=2)
        self.assertEqual(snapshot["fragment_drops"], 0)
        codes = {w["code"] for w in snapshot["warnings"]}
        self.assertIn("tiny_crop_bypassed", codes)

    def test_telemetry_flags_fragment_drops(self):
        from src.utils.obs_udp_plugin import build_udp_telemetry_snapshot

        receiver = OBS_UDP_Receiver(ip="127.0.0.1", port=PORT_BASE + 10, target_fps=144)
        try:
            receiver._update_frame(np.zeros((320, 320, 3), np.uint8))
            receiver.fragment_drops = 7
            with _ConfigSandbox(detection_engine="ai_detection", udp_fov_enabled=False):
                snapshot = build_udp_telemetry_snapshot(
                    self._service_with(receiver),
                    plugin_status={"installed": True, "missing": []},
                )
        finally:
            receiver.disconnect()

        self.assertEqual(snapshot["fragment_drops"], 7)
        codes = {w["code"] for w in snapshot["warnings"]}
        self.assertIn("fragment_drops", codes)


if __name__ == "__main__":
    unittest.main()
