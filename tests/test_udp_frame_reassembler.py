"""R1-R18: FrameReassembler contract tests (plan §6.2).

The reassembler is the P0 fix: the plugin fragments any JPEG above 65 000 B
with an 8-byte header ``<IHH`` and the pre-v2.1 bot glued bytes together, so
every fragmented frame was corrupt. These tests pin the classification order
(header BEFORE SOI), the 5.0 ms deadline, duplicate detection and the counters
that telemetry/QA rely on.

No socket, no TurboJPEG, no Tk: pure unit tests.
"""

import os
import struct
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.capture.OBS_UDP import (  # noqa: E402
    FRAGMENT_MIN_TOTAL,
    MAX_FRAME_BYTES,
    FrameReassembler,
)


def make_jpeg(payload_len=70000):
    """A fake but structurally valid JPEG of exactly ``payload_len`` bytes."""
    body = b"F" * (payload_len - 4)
    return b"\xff\xd8" + body + b"\xff\xd9"


def fragments(jpeg, count=2):
    """Split ``jpeg`` into ``count`` plugin-style fragments."""
    chunk = (len(jpeg) + count - 1) // count
    out = []
    for idx in range(count):
        start = idx * chunk
        end = min(start + chunk, len(jpeg))
        out.append(struct.pack("<IHH", len(jpeg), idx, count) + jpeg[start:end])
    return out


class TestFrameReassembler(unittest.TestCase):
    def setUp(self):
        self.reassembler = FrameReassembler(timeout_sec=0.005)

    # -- R1 ---------------------------------------------------------------
    def test_single_packet_returns_same_bytes(self):
        jpeg = make_jpeg(7000)
        result = self.reassembler.process_packet(jpeg)
        self.assertEqual(result, jpeg)
        self.assertEqual(self.reassembler.completed_frames, 1)
        self.assertEqual(self.reassembler.dropped_frames, 0)

    # -- R2 ---------------------------------------------------------------
    def test_single_packet_rejects_short_junk(self):
        self.assertIsNone(self.reassembler.process_packet(b"\x00\x01"))
        self.assertEqual(self.reassembler.invalid_packets, 1)

    # -- R3 ---------------------------------------------------------------
    def test_two_fragments_in_order(self):
        jpeg = make_jpeg(70000)
        frag0, frag1 = fragments(jpeg, 2)
        self.assertIsNone(self.reassembler.process_packet(frag0, now=0.0))
        self.assertEqual(self.reassembler.process_packet(frag1, now=0.001), jpeg)
        self.assertEqual(self.reassembler.completed_frames, 1)
        self.assertEqual(self.reassembler.dropped_frames, 0)

    # -- R4 ---------------------------------------------------------------
    def test_two_fragments_out_of_order(self):
        jpeg = make_jpeg(70000)
        frag0, frag1 = fragments(jpeg, 2)
        self.assertIsNone(self.reassembler.process_packet(frag1, now=0.0))
        self.assertEqual(self.reassembler.process_packet(frag0, now=0.001), jpeg)
        self.assertEqual(self.reassembler.completed_frames, 1)
        self.assertEqual(self.reassembler.dropped_frames, 0)

    # -- R5 ---------------------------------------------------------------
    def test_three_fragments_2_0_1(self):
        jpeg = make_jpeg(90000)
        frags = fragments(jpeg, 3)
        self.assertIsNone(self.reassembler.process_packet(frags[2], now=0.0))
        self.assertIsNone(self.reassembler.process_packet(frags[0], now=0.001))
        self.assertEqual(self.reassembler.process_packet(frags[1], now=0.002), jpeg)
        self.assertEqual(self.reassembler.completed_frames, 1)

    # -- R6 ---------------------------------------------------------------
    def test_duplicate_fragment_restarts(self):
        jpeg = make_jpeg(70000)
        frag0, frag1 = fragments(jpeg, 2)
        self.assertIsNone(self.reassembler.process_packet(frag0, now=0.0))
        self.assertIsNone(self.reassembler.process_packet(frag0, now=0.001))
        self.assertEqual(self.reassembler.process_packet(frag1, now=0.002), jpeg)
        self.assertEqual(self.reassembler.dropped_frames, 1)
        self.assertEqual(self.reassembler.restart_drops, 1)

    # -- R7 ---------------------------------------------------------------
    def test_different_total_size_restarts(self):
        jpeg_a = make_jpeg(70000)
        jpeg_b = make_jpeg(80000)
        frag0_a = fragments(jpeg_a, 2)[0]
        frag0_b = fragments(jpeg_b, 2)[0]
        self.assertIsNone(self.reassembler.process_packet(frag0_a, now=0.0))
        self.assertIsNone(self.reassembler.process_packet(frag0_b, now=0.001))
        self.assertEqual(self.reassembler.dropped_frames, 1)
        self.assertEqual(self.reassembler.restart_drops, 1)

    # -- R8 ---------------------------------------------------------------
    def test_timeout_discards_before_new_frame(self):
        jpeg = make_jpeg(70000)
        frag0 = fragments(jpeg, 2)[0]
        single = make_jpeg(5000)
        self.assertIsNone(self.reassembler.process_packet(frag0, now=1000.000))
        self.assertEqual(
            self.reassembler.process_packet(single, now=1000.006), single
        )
        self.assertEqual(self.reassembler.timeout_drops, 1)
        self.assertEqual(self.reassembler.dropped_frames, 1)

    # -- R9 ---------------------------------------------------------------
    def test_timeout_boundary_is_strict(self):
        jpeg = make_jpeg(70000)
        frag0, frag1 = fragments(jpeg, 2)
        self.assertIsNone(self.reassembler.process_packet(frag0, now=0.0))
        # Exactly at the deadline: the comparison is '>' so this still fits.
        self.assertEqual(self.reassembler.process_packet(frag1, now=0.005), jpeg)
        self.assertEqual(self.reassembler.timeout_drops, 0)

    # -- R10 --------------------------------------------------------------
    def test_single_frame_supersedes_partial(self):
        partial = make_jpeg(70000)
        frag0 = fragments(partial, 2)[0]
        single = make_jpeg(5000)
        self.assertIsNone(self.reassembler.process_packet(frag0, now=0.0))
        self.assertEqual(self.reassembler.process_packet(single, now=0.001), single)
        self.assertEqual(self.reassembler.dropped_frames, 1)
        self.assertEqual(self.reassembler.restart_drops, 1)

    # -- R11 --------------------------------------------------------------
    def test_length_mismatch_is_bad_frame(self):
        # The header promises 70 000 bytes but the fragments only carry 69 990.
        jpeg = b"\xff\xd8" + b"F" * 69988
        self.assertEqual(len(jpeg), 69990)
        header = struct.pack("<IHH", 70000, 0, 2)
        frag0 = header + jpeg[:30000]
        frag1 = struct.pack("<IHH", 70000, 1, 2) + jpeg[30000:]
        self.assertIsNone(self.reassembler.process_packet(frag0, now=0.0))
        self.assertIsNone(self.reassembler.process_packet(frag1, now=0.001))
        self.assertEqual(self.reassembler.bad_frames, 1)
        self.assertEqual(self.reassembler.dropped_frames, 1)

    # -- R12 --------------------------------------------------------------
    def test_reassembled_payload_must_start_soi(self):
        payload = b"XX" + b"F" * 69996
        header = struct.pack("<IHH", len(payload), 0, 2)
        frag0 = header + payload[:35000]
        frag1 = struct.pack("<IHH", len(payload), 1, 2) + payload[35000:]
        self.assertIsNone(self.reassembler.process_packet(frag0, now=0.0))
        self.assertIsNone(self.reassembler.process_packet(frag1, now=0.001))
        self.assertEqual(self.reassembler.bad_frames, 1)
        self.assertEqual(self.reassembler.dropped_frames, 1)

    # -- R13 --------------------------------------------------------------
    def test_oversize_header_rejected(self):
        payload = b"ZZ" + b"F" * 100
        packet = struct.pack("<IHH", MAX_FRAME_BYTES + 1, 0, 2) + payload
        self.assertIsNone(self.reassembler.process_packet(packet, now=0.0))
        self.assertEqual(self.reassembler.oversize_packets, 1)
        self.assertEqual(self.reassembler.invalid_packets, 1)
        self.assertFalse(self.reassembler.pending)

    # -- R14 --------------------------------------------------------------
    def test_empty_fragment_payload_rejected(self):
        packet = struct.pack("<IHH", 70000, 0, 2)  # header only, no payload
        self.assertIsNone(self.reassembler.process_packet(packet, now=0.0))
        self.assertEqual(self.reassembler.invalid_packets, 1)

    # -- R15 --------------------------------------------------------------
    def test_expire_drops_stale_assembly(self):
        jpeg = make_jpeg(70000)
        frag0 = fragments(jpeg, 2)[0]
        self.assertIsNone(self.reassembler.process_packet(frag0, now=0.0))
        self.assertTrue(self.reassembler.expire(now=0.006))
        self.assertEqual(self.reassembler.timeout_drops, 1)
        self.assertEqual(self.reassembler.buffered_bytes, 0)

    # -- R16 --------------------------------------------------------------
    def test_reset_clears_state(self):
        jpeg = make_jpeg(70000)
        frag0 = fragments(jpeg, 2)[0]
        self.assertIsNone(self.reassembler.process_packet(frag0, now=0.0))
        self.reassembler.reset(mark_dropped=True)
        self.assertEqual(self.reassembler.dropped_frames, 1)
        self.assertEqual(self.reassembler.buffered_bytes, 0)
        single = make_jpeg(5000)
        self.assertEqual(self.reassembler.process_packet(single, now=0.001), single)

    # -- R17 --------------------------------------------------------------
    def test_fragment_with_soi_looking_header_wins(self):
        """121 087-byte frame: header bytes are ``FF D8 01 00`` (looks like SOI).

        If the implementation checks SOI before the header, fragment 0 is
        mistaken for a single packet and the frame is lost forever.
        """
        total = 0x0001D8FF  # 121 087
        self.assertGreater(total, FRAGMENT_MIN_TOTAL)
        self.assertLess(total, MAX_FRAME_BYTES)
        jpeg = b"\xff\xd8" + b"F" * (total - 4) + b"\xff\xd9"
        self.assertEqual(len(jpeg), total)
        self.assertEqual(struct.pack("<I", total)[:2], b"\xff\xd8")

        frag0, frag1 = fragments(jpeg, 2)
        self.assertTrue(frag0.startswith(b"\xff\xd8"))
        self.assertIsNone(self.reassembler.process_packet(frag0, now=0.0))
        self.assertEqual(self.reassembler.process_packet(frag1, now=0.001), jpeg)
        self.assertEqual(self.reassembler.completed_frames, 1)
        self.assertEqual(self.reassembler.invalid_packets, 0)

    # -- R18 --------------------------------------------------------------
    def test_real_single_jpeg_not_counted_oversize(self):
        """Every real JPEG starts ``FF D8 FF xx``.

        Read as a little-endian uint32 that is at least ``0x00FFD8FF``
        (~16.8 MB), i.e. always above MAX_FRAME_BYTES, so a single-packet JPEG
        takes the "too big to be a fragment" branch and must then fall through
        to the SOI branch instead of being counted as oversize.
        """
        jpeg = b"\xff\xd8\xff\xe0" + b"F" * 8990 + b"\xff\xd9"
        self.assertEqual(jpeg[:4], b"\xff\xd8\xff\xe0")
        self.assertGreaterEqual(
            struct.unpack_from("<I", jpeg)[0], MAX_FRAME_BYTES
        )
        self.assertEqual(self.reassembler.process_packet(jpeg, now=0.0), jpeg)
        self.assertEqual(self.reassembler.oversize_packets, 0)
        self.assertEqual(self.reassembler.invalid_packets, 0)
        self.assertEqual(self.reassembler.completed_frames, 1)


if __name__ == "__main__":
    unittest.main()
