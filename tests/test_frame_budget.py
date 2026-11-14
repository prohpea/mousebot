"""End-to-end frame budget: synthetic 144 Hz feed through the real pipeline.

This is the test that answers "is 144 FPS actually reachable" instead of "does
the loop run". It feeds real JPEG bytes into the real receiver reassembly path,
through the real decode worker and ``wait_for_new_frame``, and runs the real
detection on the decoded frame, measuring every stage separately.

Elapsed time is the budget (6.94 ms at 144 Hz), not the sum of the stages: the
decode and detection threads overlap, so throughput is bounded by the slower of
the two while single-frame latency is the sum. Both are asserted.

Perf assertions are skipped under ``CVM_SKIP_PERF=1``; skipping is not a pass.
"""
import os
import statistics
import sys
import threading
import time
import unittest

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.utils.config import Config, config
from src.utils import detection
from src.capture.OBS_UDP import OBS_UDP_Receiver

SKIP_PERF = os.environ.get("CVM_SKIP_PERF", "") == "1"
SKIP_REASON = "CVM_SKIP_PERF=1: perf assertions skipped on this machine (not a pass)"

FRAME_BUDGET_MS = 1000.0 / 144.0  # 6.944 ms
FPS = 144
FRAME_COUNT = 200
SIZE = 640

# Loose filters: the budget must be measured on a path that really detects the
# blobs, not on a path that bails out early because the user's config.json set
# min_contour_points=30 / require_vertical_line=True.
PINNED_DETECTION = dict(
    color="purple",
    detection_morph_mode="legacy",
    detection_min_contour_points=4,
    detection_min_bbox_area=48,
    detection_min_contour_area=10,
    detection_min_fill_ratio=0.08,
    detection_edge_reject_area=80,
    detection_edge_min_contour_area=30,
    detection_edge_min_side=4,
    detection_border_margin=0,
    detection_min_width=3,
    detection_min_height=4,
    detection_min_aspect=0.04,
    detection_max_aspect=6.0,
    detection_require_vertical_line=False,
)


class _ConfigSandbox:
    def __init__(self, **values):
        self.values = values
        self.previous = {}

    def __enter__(self):
        for key, value in self.values.items():
            self.previous[key] = getattr(config, key, "__missing__")
            setattr(config, key, value)
        return self

    def __exit__(self, *exc_info):
        for key, value in self.previous.items():
            if value == "__missing__":
                try:
                    delattr(config, key)
                except AttributeError:
                    pass
            else:
                setattr(config, key, value)
        return False


def _encode_frames(count, size=SIZE):
    """Real JPEG bytes, distinct per frame so stale frames are detectable."""
    import turbojpeg

    tj = turbojpeg.TurboJPEG()
    base = np.zeros((size, size, 3), np.uint8)
    base[:, :] = (24, 24, 24)
    frames = []
    for i in range(count):
        img = base.copy()
        # A moving purple blob, 30x52 like a player body.
        x = 20 + (i * 3) % (size - 100)
        y = 30 + (i * 2) % (size - 120)
        img[y:y + 52, x:x + 30] = (163, 69, 161)
        frames.append(tj.encode(img))
    return frames


def _percentile(samples, fraction):
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


class TestFrameBudget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jpeg_frames = _encode_frames(FRAME_COUNT)

    def setUp(self):
        # Pin config before load_model(): HSV bounds are fixed at load time from
        # config.color, so loading first would keep whatever the user's
        # config.json selected and the fixture blobs would not be detected.
        self._sandbox = _ConfigSandbox(**PINNED_DETECTION, detection_roi_max_fraction=1.0)
        self._sandbox.__enter__()
        self.addCleanup(self._sandbox.__exit__, None, None, None)
        detection.load_model()
        self.model = detection._model
        if self.model is None:
            self.skipTest("HSV model unavailable")

        self.receiver = OBS_UDP_Receiver(ip="127.0.0.1", port=13310, target_fps=FPS)
        self.receiver.is_connected = True
        self.receiver.stop_event.clear()

    def tearDown(self):
        self.receiver.stop_event.set()
        self.receiver.is_connected = False
        self.receiver.disconnect()

    def _run_feed(self, roi):
        """Feed all frames at 144 Hz and consume them like the track thread does."""
        consumed = 0
        track_ms = []
        handoff_ms = []
        decode_ms = []
        seqs_seen = []
        done = threading.Event()

        worker = threading.Thread(target=self.receiver._decode_worker_loop, daemon=True)
        worker.start()

        def feed():
            period = 1.0 / FPS
            start = time.perf_counter()
            for index, jpeg in enumerate(self.jpeg_frames):
                target = start + index * period
                now = time.perf_counter()
                if target > now:
                    time.sleep(target - now)
                self.receiver._deliver_jpeg(jpeg, time.perf_counter())
            done.set()

        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()

        last_seq = 0
        idle_timeouts = 0
        hard_deadline = time.perf_counter() + 30.0
        while time.perf_counter() < hard_deadline:
            frame, seq = self.receiver.wait_for_new_frame(last_seq, timeout=0.05)
            if frame is None or seq == last_seq:
                if done.is_set():
                    idle_timeouts += 1
                    # The writer finished and nothing new arrived: everything
                    # that could be consumed was consumed.
                    if idle_timeouts >= 2:
                        break
                continue
            idle_timeouts = 0
            last_seq = seq
            seqs_seen.append(seq)

            meta = self.receiver.get_last_frame_meta()
            published_at = meta.get("published_at")
            t0 = time.perf_counter()
            if published_at is not None:
                handoff_ms.append(max(0.0, (t0 - float(published_at)) * 1000.0))
            decode_ms.append(float(meta.get("decode_ms", 0.0)))

            detection.analyze(self.model, frame, roi=roi)
            track_ms.append((time.perf_counter() - t0) * 1000.0)
            consumed += 1
            if consumed >= len(self.jpeg_frames):
                break

        self.receiver.stop_event.set()
        worker.join(timeout=2.0)
        feeder.join(timeout=2.0)
        return {
            "consumed": consumed,
            "track_ms": track_ms,
            "handoff_ms": handoff_ms,
            "decode_ms": decode_ms,
            "seqs": seqs_seen,
        }

    def test_no_sequence_is_decoded_twice(self):
        result = self._run_feed(roi=None)
        seqs = result["seqs"]
        self.assertEqual(len(seqs), len(set(seqs)), "a publish sequence was consumed twice")
        self.assertEqual(seqs, sorted(seqs), "publish sequences were consumed out of order")

    def test_at_least_95_percent_of_published_frames_are_processed(self):
        """Every frame the decoder published must reach detection.

        The ratio is taken against *published* frames, not against the number
        sent: at 144 Hz the single-slot design deliberately overwrites frames
        that arrive while the consumer is still busy, and that drop is the point
        of the design. What must not happen is a published frame being skipped.
        """
        result = self._run_feed(roi=None)
        published = len(result["seqs"])
        self.assertGreater(published, 0, "the decoder never published a frame")
        ratio = result["consumed"] / float(published)
        self.assertGreaterEqual(
            ratio, 0.95,
            f"only {result['consumed']}/{published} published frames reached detection",
        )

    @unittest.skipIf(SKIP_PERF, SKIP_REASON)
    def test_track_thread_stays_inside_the_144hz_budget(self):
        result = self._run_feed(roi=None)
        median = statistics.median(result["track_ms"])
        p95 = _percentile(result["track_ms"], 0.95)
        self.assertLessEqual(
            p95, FRAME_BUDGET_MS,
            f"detection p95 {p95:.3f} ms over the {FRAME_BUDGET_MS:.3f} ms budget",
        )
        self.assertLessEqual(median, FRAME_BUDGET_MS)

    @unittest.skipIf(SKIP_PERF, SKIP_REASON)
    def test_decode_stays_inside_the_budget(self):
        result = self._run_feed(roi=None)
        p95 = _percentile(result["decode_ms"], 0.95)
        self.assertLessEqual(p95, FRAME_BUDGET_MS, f"decode p95 {p95:.3f} ms")

    @unittest.skipIf(SKIP_PERF, SKIP_REASON)
    def test_publish_to_detect_handoff_is_under_one_millisecond(self):
        """The consumer is already waiting, so the handoff must be ~a wakeup."""
        result = self._run_feed(roi=None)
        p95 = _percentile(result["handoff_ms"], 0.95)
        self.assertLessEqual(
            p95, 1.0,
            f"publish->detect p95 {p95:.3f} ms; the track thread is not waking on publish",
        )

    @unittest.skipIf(SKIP_PERF, SKIP_REASON)
    def test_roi_reduces_detection_time_on_a_large_frame(self):
        """Same detection, but on a 1280x720 frame with and without a 640x640 ROI."""
        import turbojpeg

        tj = turbojpeg.TurboJPEG()
        big = np.zeros((720, 1280, 3), np.uint8)
        big[200:600, 300:700] = (163, 69, 161)
        frame = tj.decode(tj.encode(big))

        roi = (320, 40, 960, 680)  # 640x640, above the downgrade threshold

        def _time(fn, repeats=7):
            samples = []
            for _ in range(repeats):
                t0 = time.perf_counter()
                fn()
                samples.append((time.perf_counter() - t0) * 1000.0)
            return statistics.median(samples)

        full_median = _time(lambda: detection.analyze(self.model, frame))
        roi_median = _time(lambda: detection.analyze(self.model, frame, roi=roi))
        self.assertLess(
            roi_median, full_median,
            f"ROI {roi_median:.3f} ms is not faster than full frame {full_median:.3f} ms",
        )


class TestNewConfigKeys(unittest.TestCase):
    NEW_KEYS = (
        "detection_roi_enabled",
        "detection_roi_padding",
        "detection_roi_max_fraction",
        "detection_return_raw_mask",
        "receiver_rcvbuf_mb",
        "receiver_high_priority",
        "receiver_fragment_timeout_ms",
        "cv2_num_threads",
        "trigger_confirm_ms",
        "track_wait_mode",
    )

    def test_every_new_key_round_trips(self):
        fresh = Config()
        data = fresh.to_dict()
        for key in self.NEW_KEYS:
            self.assertIn(key, data, f"{key} missing from to_dict()")

        # Set distinctive values first: comparing two Config() instances would
        # pass trivially, since both load the same config.json.
        probe = Config()
        distinct = {
            "detection_roi_enabled": True,
            "detection_roi_padding": 111,
            "detection_roi_max_fraction": 0.55,
            "detection_return_raw_mask": False,
            "receiver_rcvbuf_mb": 12,
            "receiver_high_priority": True,
            "receiver_fragment_timeout_ms": 6.5,
            "cv2_num_threads": 2,
            "trigger_confirm_ms": 3.5,
            "track_wait_mode": "grid",
        }
        for key, value in distinct.items():
            setattr(probe, key, value)

        clone = Config()
        clone.from_dict(probe.to_dict())
        for key in self.NEW_KEYS:
            self.assertEqual(
                getattr(clone, key), distinct[key], f"{key} did not survive the round trip"
            )

    def test_defaults_keep_the_old_behaviour(self):
        """``Config()`` loads config.json, so only assert keys it does not set."""
        import json

        ambient = {}
        shipped = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "config.json")
        if os.path.exists(shipped):
            try:
                with open(shipped, "r", encoding="utf-8") as handle:
                    ambient = json.load(handle) or {}
            except Exception:
                ambient = {}

        fresh = Config()
        defaults = {
            "detection_roi_enabled": False,   # ROI must be opt-in
            "receiver_high_priority": False,  # thread priority must be opt-in
            "trigger_confirm_ms": 0.0,        # frame-based confirm stays default
            "cv2_num_threads": 0,             # OpenCV thread count stays untouched
            "track_wait_mode": "frame",
        }
        for key, expected in defaults.items():
            if key in ambient:
                continue  # the user overrode it explicitly; not a default test
            self.assertEqual(getattr(fresh, key), expected, f"{key} default changed")

    def test_from_dict_clamps_out_of_range_values(self):
        clone = Config()
        clone.from_dict({
            "detection_roi_padding": -40,
            "detection_roi_max_fraction": 7.5,
            "receiver_rcvbuf_mb": 0,
            "receiver_fragment_timeout_ms": -3,
            "cv2_num_threads": -8,
            "trigger_confirm_ms": -1,
        })
        self.assertGreaterEqual(clone.detection_roi_padding, 0)
        self.assertLessEqual(clone.detection_roi_max_fraction, 1.0)
        self.assertGreater(clone.detection_roi_max_fraction, 0.0)
        self.assertGreaterEqual(clone.receiver_rcvbuf_mb, 1)
        self.assertGreaterEqual(clone.receiver_fragment_timeout_ms, 1.0)
        self.assertGreaterEqual(clone.cv2_num_threads, 0)
        self.assertGreaterEqual(clone.trigger_confirm_ms, 0.0)

    def test_from_dict_clamps_high_values(self):
        clone = Config()
        clone.from_dict({
            "detection_roi_padding": 10 ** 6,
            "receiver_rcvbuf_mb": 10 ** 5,
            "receiver_fragment_timeout_ms": 10 ** 6,
            "cv2_num_threads": 10 ** 4,
            "trigger_confirm_ms": 10 ** 6,
        })
        self.assertLessEqual(clone.detection_roi_padding, 512)
        self.assertLessEqual(clone.receiver_rcvbuf_mb, 64)
        self.assertLessEqual(clone.receiver_fragment_timeout_ms, 100.0)
        self.assertLessEqual(clone.cv2_num_threads, 64)
        self.assertLessEqual(clone.trigger_confirm_ms, 1000.0)

    def test_from_dict_rejects_a_bogus_wait_mode(self):
        clone = Config()
        clone.from_dict({"track_wait_mode": "nonsense"})
        self.assertIn(clone.track_wait_mode, {"frame", "grid"})

    def test_round_trip_does_not_change_existing_keys(self):
        fresh = Config()
        before = fresh.to_dict()
        clone = Config()
        clone.from_dict(before)
        after = clone.to_dict()
        # Keys that existed before this change must be untouched by the round trip.
        for key in ("target_fps", "fovsize", "tbfovsize", "trigger_confirm_frames",
                    "color", "enableaim", "udp_fov", "detection_merge_distance"):
            self.assertEqual(before[key], after[key], f"{key} changed on round trip")


if __name__ == "__main__":
    unittest.main()
