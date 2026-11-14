"""ROI-aware detection: full-frame parity, offsets, clamping, ROI downgrade.

The ROI path exists to cut milliseconds, so the only thing that makes it safe is
that it produces *the same answer* as the full-frame path when the ROI covers
everything, and a correctly offset answer when it does not. Both properties are
asserted against a live call, never against a checked-in expectation image.
"""
import os
import sys
import unittest

import numpy as np
import cv2

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.utils.config import config
from src.utils import detection


def _synthetic_frame(width=640, height=480):
    """Frame with a few purple blobs (the default config colour)."""
    img = np.zeros((height, width, 3), np.uint8)
    blobs = [
        (60, 80, 26, 44),
        (300, 200, 30, 52),
        (520, 120, 24, 40),
        (480, 400, 28, 46),
    ]
    for x, y, w, h in blobs:
        cv2.rectangle(img, (x, y), (x + w, y + h), (163, 69, 161), -1)
    return img


class _ConfigSandbox:
    """Apply temporary config values and restore them afterwards."""

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


# Detection knobs pinned so the assertions do not depend on the user's
# config.json (which may set min_contour_points=30, require_vertical_line=True,
# etc.). With those, synthetic rectangles produce no detections at all and every
# parity assertion below would pass vacuously.
PINNED_DETECTION = dict(
    color="purple",
    detection_morph_mode="legacy",
    detection_merge_distance=12,
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
    detection_legacy_kernel_w=15,
    detection_legacy_kernel_h=9,
    detection_legacy_dilate_iterations=1,
    detection_roi_max_fraction=0.70,
)


class DetectionTestCase(unittest.TestCase):
    def setUp(self):
        # Config is pinned BEFORE load_model(): HSV bounds are captured at load
        # time from config.color, so loading first would keep config.json's
        # custom colour and the purple fixture blobs would never match.
        self.sandbox = _ConfigSandbox(**PINNED_DETECTION)
        self.sandbox.__enter__()
        self.addCleanup(self.sandbox.__exit__, None, None, None)
        detection.load_model()
        self.model = detection._model
        self.assertIsNotNone(self.model, "model failed to load")
        self.image = _synthetic_frame()

    def bboxes(self, result):
        return [tuple(int(v) for v in det["bbox"]) for det in result.detections]

    def test_fixture_actually_detects_something(self):
        """Guard: a fixture that finds nothing makes every parity test vacuous."""
        self.assertGreaterEqual(len(detection.analyze(self.model, self.image).detections), 4)


class TestFullFrameParity(DetectionTestCase):
    def test_full_frame_roi_matches_perform_detection_exactly(self):
        legacy_detections, legacy_mask = detection.perform_detection(self.model, self.image)
        h, w = self.image.shape[:2]

        with _ConfigSandbox(detection_roi_max_fraction=1.0):
            result = detection.analyze(self.model, self.image, roi=(0, 0, w, h))

        self.assertTrue(result.roi_used, "an exact full-frame ROI must still be used")
        self.assertEqual(
            [tuple(d["bbox"]) for d in result.detections],
            [tuple(d["bbox"]) for d in legacy_detections],
        )
        self.assertEqual(
            [d["class"] for d in result.detections],
            [d["class"] for d in legacy_detections],
        )
        np.testing.assert_array_equal(result.full_mask(), legacy_mask)

    def test_no_roi_is_identical_to_roi_none(self):
        plain = detection.analyze(self.model, self.image)
        explicit = detection.analyze(self.model, self.image, roi=None)

        self.assertFalse(plain.roi_used)
        self.assertEqual(self.bboxes(plain), self.bboxes(explicit))

    def test_analyze_without_roi_matches_perform_detection(self):
        legacy_detections, _ = detection.perform_detection(self.model, self.image)
        result = detection.analyze(self.model, self.image)

        self.assertEqual(self.bboxes(result), [tuple(d["bbox"]) for d in legacy_detections])

    def test_perform_detection_wrapper_returns_two_tuple(self):
        detections, mask = detection.perform_detection(self.model, self.image)
        self.assertIsInstance(detections, list)
        self.assertEqual(mask.shape, self.image.shape[:2])


class TestRoiOffsets(DetectionTestCase):
    def test_bboxes_are_reported_in_full_frame_coordinates(self):
        # A ROI that fully contains exactly one blob.
        roi = (20, 40, 140, 180)
        result = detection.analyze(self.model, self.image, roi=roi)
        self.assertTrue(result.roi_used)

        full = detection.analyze(self.model, self.image)
        x0, y0 = roi[0], roi[1]
        for bbox in self.bboxes(result):
            self.assertGreaterEqual(bbox[0], x0)
            self.assertGreaterEqual(bbox[1], y0)
            # The same blob, found by the full-frame pass.
            self.assertIn(bbox, self.bboxes(full), f"{bbox} not present in full-frame pass")

    def test_mask_is_roi_sized_and_full_mask_is_frame_sized(self):
        roi = (20, 40, 140, 180)
        result = detection.analyze(self.model, self.image, roi=roi)

        self.assertEqual(result.mask.shape, (roi[3] - roi[1], roi[2] - roi[0]))
        self.assertEqual(result.full_mask().shape, self.image.shape[:2])

    def test_pixels_outside_the_roi_are_zero_in_the_full_mask(self):
        roi = (20, 40, 140, 180)
        result = detection.analyze(self.model, self.image, roi=roi)
        canvas = result.full_mask()

        self.assertEqual(int(canvas[: roi[1], :].max()), 0)
        self.assertEqual(int(canvas[:, : roi[0]].max()), 0)
        self.assertEqual(int(canvas[roi[3]:, :].max()), 0)
        self.assertEqual(int(canvas[:, roi[2]:].max()), 0)

    def test_two_crops_compose_without_double_offset(self):
        """udp_fov crop + detection ROI: the offset is applied exactly once."""
        inner = self.image[100:400, 100:500]  # stand-in for apply_mode_fov
        roi = (30, 20, 330, 220)              # ROI inside the cropped image

        result = detection.analyze(self.model, inner, roi=roi)
        expected = detection.analyze(self.model, inner)

        for bbox in self.bboxes(result):
            self.assertIn(bbox, self.bboxes(expected))

        # A blob visible in full frame at (300,200,30,52) -> inner (200,100)
        # -> bbox reported in inner coordinates must stay >= 0.
        for bbox in self.bboxes(result):
            self.assertGreaterEqual(bbox[0], 0)
            self.assertGreaterEqual(bbox[1], 0)


class TestRoiClamping(DetectionTestCase):
    def test_roi_beyond_the_frame_edges_is_clamped(self):
        """A ROI larger than the frame clamps to the frame, not past it."""
        h, w = self.image.shape[:2]
        with _ConfigSandbox(detection_roi_max_fraction=1.0):
            result = detection.analyze(self.model, self.image, roi=(-500, -500, w + 500, h + 500))

        self.assertTrue(result.roi_used, "clamping must not turn this into a full-frame call")
        self.assertEqual(result.mask.shape, (h, w))
        self.assertEqual(self.bboxes(result), self.bboxes(detection.analyze(self.model, self.image)))

    def test_roi_clamped_from_the_right_and_bottom_edges(self):
        h, w = self.image.shape[:2]
        with _ConfigSandbox(detection_roi_max_fraction=1.0):
            result = detection.analyze(self.model, self.image, roi=(w - 100, h - 100, w + 400, h + 400))

        self.assertTrue(result.roi_used)
        self.assertEqual(result.mask.shape, (100, 100))

    def test_roi_with_no_area_returns_empty_instead_of_raising(self):
        for bad_roi in [(100, 100, 100, 200), (100, 100, 200, 100), (400, 400, 50, 50)]:
            result = detection.analyze(self.model, self.image, roi=bad_roi)
            self.assertEqual(result.detections, [], f"{bad_roi} must yield no detections")
            self.assertEqual(result.mask_nonzero, 0)
            np.testing.assert_array_equal(result.full_mask(), np.zeros(self.image.shape[:2], np.uint8))

    def test_roi_of_one_pixel_does_not_raise(self):
        result = detection.analyze(self.model, self.image, roi=(10, 10, 11, 11))
        self.assertIsInstance(result.detections, list)

    def test_large_roi_falls_back_to_full_frame(self):
        h, w = self.image.shape[:2]
        # 0.9 of the frame, above the 0.70 default threshold.
        with _ConfigSandbox(detection_roi_max_fraction=0.70):
            result = detection.analyze(self.model, self.image, roi=(0, 0, w, int(h * 0.9)))

        self.assertFalse(result.roi_used, "a near-full-frame ROI must be dropped")
        self.assertEqual(result.mask.shape, (h, w))
        self.assertEqual(self.bboxes(result), self.bboxes(detection.analyze(self.model, self.image)))

    def test_roi_just_below_the_threshold_is_used(self):
        # 448x470 of 640x480 = 0.685, i.e. just under the 0.70 default.
        with _ConfigSandbox(detection_roi_max_fraction=0.70):
            result = detection.analyze(self.model, self.image, roi=(0, 0, 448, 470))

        self.assertTrue(result.roi_used)
        self.assertEqual(result.mask.shape, (470, 448))

    def test_invalid_roi_argument_is_ignored(self):
        result = detection.analyze(self.model, self.image, roi=("not", "a", "roi"))
        self.assertFalse(result.roi_used)
        self.assertEqual(self.bboxes(result), self.bboxes(detection.analyze(self.model, self.image)))


class TestRoiSensitiveThresholds(DetectionTestCase):
    def test_area_thresholds_still_use_the_full_frame_area(self):
        """Cropping must not rescale min_bbox_area into 'relative to the crop'."""
        full = detection.analyze(self.model, self.image)
        h, w = self.image.shape[:2]
        # 200 px wide: cuts between blobs so nothing is clipped by the ROI edge,
        # which would legitimately change a bbox and hide what this test checks.
        roi = (0, 0, 200, h)
        with _ConfigSandbox(detection_roi_max_fraction=1.0):
            cropped = detection.analyze(self.model, self.image, roi=roi)

        self.assertTrue(cropped.roi_used)
        self.assertGreaterEqual(len(cropped.detections), 1, "the ROI found nothing")
        for bbox in self.bboxes(cropped):
            self.assertIn(bbox, self.bboxes(full))

    def test_empty_frame_yields_no_detections_and_no_exception(self):
        blank = np.zeros((240, 320, 3), np.uint8)
        result = detection.analyze(self.model, blank, roi=(10, 10, 200, 200))
        self.assertEqual(result.detections, [])
        self.assertIsInstance(result.mask, np.ndarray)

    def test_none_inputs_are_tolerated(self):
        self.assertEqual(detection.analyze(None, self.image).detections, [])
        self.assertEqual(detection.analyze(self.model, None).detections, [])


if __name__ == "__main__":
    unittest.main()
