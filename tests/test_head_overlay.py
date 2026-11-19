"""The tracking thread must not mutate the frame it was handed.

``_estimate_head_positions`` used to paint a yellow head-roi rectangle directly
onto ``bgr_img``. That image is the frame the UDP receiver still owns and the one
``Triggerbot`` reads, so the overlay (a) mutated shared state across threads and
(b) with ``config.color == "yellow"`` could make the bot detect its own marker.

The rectangle is now returned to the caller and painted on the display copy.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

import numpy as np
import cv2

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.utils.config import config
from src.utils import detection


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


def _make_tracker():
    from main import AimTracker

    tracker = AimTracker.__new__(AimTracker)  # bypass model load / thread start
    tracker.fovsize = float(getattr(config, "fovsize", 100))
    tracker.fovsize_sec = float(getattr(config, "fovsize_sec", 150))
    tracker.tbfovsize = float(getattr(config, "tbfovsize", 60))
    tracker.anti_smoke_detector = MagicMock()
    tracker.anti_smoke_detector.is_enabled.return_value = False
    tracker.anti_smoke_detector_sec = MagicMock()
    tracker.anti_smoke_detector_sec.is_enabled.return_value = False
    return tracker


class TestHeadEstimateDoesNotMutateFrame(unittest.TestCase):
    def test_source_frame_is_byte_identical_after_the_call(self):
        tracker = _make_tracker()
        img = np.zeros((200, 200, 3), np.uint8)
        img[40:160, 70:130] = (120, 120, 120)
        before = img.copy()

        results = tracker._estimate_head_positions(70, 40, 130, 160, img)

        np.testing.assert_array_equal(img, before, "the source frame was modified")
        self.assertEqual(len(results), 1)
        head_cx, head_cy, head_rect = results[0]
        self.assertIsInstance(head_cx, int)
        self.assertIsInstance(head_cy, int)
        self.assertEqual(len(head_rect), 4)

    def test_no_yellow_pixels_are_added_even_for_a_yellow_bot(self):
        """With color="yellow", a yellow head marker would be a self-trigger."""
        tracker = _make_tracker()
        img = np.zeros((200, 200, 3), np.uint8)
        before_yellow = int(np.count_nonzero(img[:, :, 2] > 200))  # BGR: index 2 = R

        with _ConfigSandbox(color="yellow"):
            tracker._estimate_head_positions(70, 40, 130, 160, img)

        after_yellow = int(np.count_nonzero(img[:, :, 2] > 200))
        self.assertEqual(
            after_yellow, before_yellow,
            "a yellow overlay was drawn into the detection frame",
        )

    def test_head_roi_is_returned_for_the_display_copy(self):
        tracker = _make_tracker()
        img = np.zeros((200, 200, 3), np.uint8)

        [(head_cx, head_cy, (x1, y1, x2, y2))] = tracker._estimate_head_positions(
            70, 40, 130, 160, img
        )

        self.assertLess(x1, head_cx)
        self.assertGreater(x2, head_cx)
        self.assertLess(y1, head_cy)
        self.assertGreater(y2, head_cy)
        self.assertGreaterEqual(x1, 0)
        self.assertGreaterEqual(y1, 0)
        self.assertLessEqual(x2, img.shape[1])
        self.assertLessEqual(y2, img.shape[0])

    def test_returned_rect_stays_inside_the_frame_at_the_border(self):
        tracker = _make_tracker()
        img = np.zeros((120, 120, 3), np.uint8)

        for bbox in [(0, 0, 40, 60), (80, 60, 120, 120), (0, 60, 30, 120)]:
            for _cx, _cy, (x1, y1, x2, y2) in tracker._estimate_head_positions(*bbox, img):
                self.assertGreaterEqual(x1, 0)
                self.assertGreaterEqual(y1, 0)
                self.assertLessEqual(x2, 120)
                self.assertLessEqual(y2, 120)
                self.assertLessEqual(x1, x2)
                self.assertLessEqual(y1, y2)


class TestTrackFrameKeepsSourceClean(unittest.TestCase):
    """End-to-end: after a full ``_track_frame`` pass the source frame is intact."""

    def test_track_frame_does_not_write_into_bgr_img(self):
        tracker = _make_tracker()
        tracker.app = MagicMock()
        tracker.app.capture.get_frame_meta.return_value = {}
        tracker.app.capture.apply_mode_fov.side_effect = lambda frame: frame
        tracker._last_frame_seq = 1
        tracker.perf = {}
        tracker._frame_count = 0
        tracker._last_frame_log_time = 0.0
        tracker._target_smoother = MagicMock()
        tracker._aim_and_move = MagicMock()
        tracker._draw_enhanced_detection = MagicMock(side_effect=lambda img, *a: img)
        tracker._draw_fovs = MagicMock()
        tracker._draw_body = MagicMock()
        tracker._draw_head_bbox = MagicMock()
        tracker._update_raw_stream_windows = MagicMock()

        img = np.zeros((240, 320, 3), np.uint8)
        img[60:200, 130:190] = (163, 69, 161)
        before = img.copy()

        with _ConfigSandbox(
            color="purple",
            enable_target_temporal_smoothing=False,
            show_opencv_windows=False,
            show_opencv_mask=False,
            show_opencv_detection=False,
            enableaim=True,
            enabletb=True,
            detection_roi_enabled=False,
            detection_min_contour_points=4,
            detection_min_bbox_area=48,
            detection_min_contour_area=10,
            detection_min_fill_ratio=0.08,
            detection_min_width=3,
            detection_min_height=4,
            detection_min_aspect=0.04,
            detection_max_aspect=6.0,
            detection_require_vertical_line=False,
            detection_border_margin=0,
            detection_legacy_kernel_w=15,
            detection_legacy_kernel_h=9,
            detection_legacy_dilate_iterations=1,
            detection_morph_mode="legacy",
        ):
            # The model must be loaded while the pinned colour is active, since
            # HSV_MIN/HSV_MAX are captured at load time.
            detection.load_model()
            tracker.model = detection._model
            self.assertIsNotNone(tracker.model, "HSV model unavailable")

            # Sanity: the pass must actually see the blob, otherwise an intact
            # frame proves nothing (detection never ran).
            detected = detection.analyze(tracker.model, img)
            self.assertGreaterEqual(len(detected.detections), 1, "fixture blob not detected")

            tracker._track_frame(img)

        np.testing.assert_array_equal(
            img, before, "the tracking pass wrote overlays into the source frame"
        )


class TestCompactTargetMarkers(unittest.TestCase):
    """The preview marker must not hide the head it is pointing at.

    The best-target marker used to be a filled ``cv2.circle(..., 8, -1)`` disc,
    17 px across: on a distant 5x5 head it covered the target completely. Both
    markers are now thin rings with a single centre pixel, drawn only on the
    display copy.
    """

    _DISPLAY_OFF = dict(
        show_crosshair=False,
        enableaim=False,
        enableaim_sec=False,
        enabletb=False,
        show_mode_text=False,
        show_aimbot_status=False,
        show_triggerbot_status=False,
        show_distance_text=False,
        show_target_count=False,
    )

    @staticmethod
    def _painted_mask(before, after):
        """Boolean mask of pixels the overlay changed."""
        return np.any(before != after, axis=2)

    def test_best_target_marker_is_compact_and_leaves_the_head_visible(self):
        from main import FrameInfo

        tracker = _make_tracker()
        img = np.zeros((200, 200, 3), np.uint8)
        img[98:103, 98:103] = (0, 255, 0)  # a 5x5 distant head, BGR green
        before = img.copy()

        with _ConfigSandbox(**self._DISPLAY_OFF):
            out = tracker._draw_enhanced_detection(
                img, [(100.0, 100.0, 0.0, None, None)], FrameInfo(200, 200)
            )

        self.assertIs(out, img)
        painted = self._painted_mask(before, out)

        window = painted[90:111, 90:111]
        self.assertLessEqual(int(np.count_nonzero(window)), 60,
                             "the best-target marker is still a large disc")
        ys, xs = np.nonzero(painted)
        self.assertTrue(len(xs), "the best-target marker was not drawn at all")
        self.assertLessEqual(int(xs.max() - xs.min()) + 1, 9,
                             "marker is wider than 9 px")
        self.assertLessEqual(int(ys.max() - ys.min()) + 1, 9,
                             "marker is taller than 9 px")

        # The head itself must stay readable underneath the marker. The 7 px ring
        # overlaps the head's border pixels by design (that is what a thin ring
        # does), so the meaningful invariants are: the 3x3 core is untouched
        # except for the single centre dot, and the large majority of the head
        # survives -- the old filled r=8 disc left none of it.
        core = out[99:102, 99:102]
        core_green = int(np.count_nonzero(np.all(core == (0, 255, 0), axis=2)))
        self.assertGreaterEqual(core_green, 6,
                                "the marker painted over the head's core pixels")

        head_visible = int(np.count_nonzero(
            np.all(out[98:103, 98:103] == (0, 255, 0), axis=2)
        ))
        self.assertGreaterEqual(head_visible, 12,
                                "the marker covered most of the 5x5 head")

    def test_head_bbox_marker_is_compact(self):
        tracker = _make_tracker()
        img = np.zeros((60, 60, 3), np.uint8)
        before = img.copy()

        out = tracker._draw_head_bbox(img, 30, 30)

        self.assertIsNone(out)  # draws in place, like the rest of the overlay code
        painted = self._painted_mask(before, img)
        self.assertLessEqual(int(np.count_nonzero(painted)), 60,
                             "_draw_head_bbox paints too many pixels")
        ys, xs = np.nonzero(painted)
        self.assertTrue(len(xs), "_draw_head_bbox painted nothing")
        self.assertLessEqual(int(xs.max() - xs.min()) + 1, 9)
        self.assertLessEqual(int(ys.max() - ys.min()) + 1, 9)


if __name__ == "__main__":
    unittest.main()
