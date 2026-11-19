"""Detection timing budget: the ROI must actually shrink the work.

A latency target that is only asserted end-to-end cannot tell "the ROI made it
faster" from "the machine happened to be fast". These tests measure the ROI path
against the full-frame path in the same process and require the cost to scale
with the analysed area, which is what catches a ROI that silently degrades to
full-frame.

The absolute ceilings are deliberately generous (they run on arbitrary CI
hardware) and can be skipped with ``CVM_SKIP_PERF=1``. Skipping is not evidence
of anything; the relative scaling test still runs unless skipped too.
"""
import os
import statistics
import sys
import time
import unittest

import numpy as np
import cv2

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.utils.config import config
from src.utils import detection

SKIP_PERF = os.environ.get("CVM_SKIP_PERF", "") == "1"
SKIP_REASON = "CVM_SKIP_PERF=1: perf assertions skipped on this machine (not a pass)"


def _frame(width=1920, height=1080, blobs=8):
    img = np.zeros((height, width, 3), np.uint8)
    rng = np.random.RandomState(7)
    for _ in range(blobs):
        x = int(rng.randint(0, max(1, width - 120)))
        y = int(rng.randint(0, max(1, height - 160)))
        cv2.rectangle(img, (x, y), (x + 30, y + 52), (163, 69, 161), -1)
    return img


def _measure(fn, repeats=7):
    """Median and p95 wall time in ms over ``repeats`` calls."""
    fn()  # Warmup cache / OpenCV buffers
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    median = statistics.median(samples)
    index = min(len(samples) - 1, int(round(0.95 * (len(samples) - 1))))
    return median, samples[index]


# Loosen the detection filters so the synthetic blobs are actually detected; the
# timing itself is dominated by cvtColor/inRange/morphology, but a fixture that
# finds nothing would make the structural assertions vacuous.
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


class TestDetectionPerfBudget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = _frame()

    def setUp(self):
        # Pin config BEFORE load_model(): HSV bounds (and therefore every mask
        # and every timing) depend on config.color at load time.
        self._sandbox = _ConfigSandbox(**PINNED_DETECTION, detection_roi_max_fraction=1.0)
        self._sandbox.__enter__()
        self.addCleanup(self._sandbox.__exit__, None, None, None)
        detection.load_model()
        self.model = detection._model
        if self.model is None:
            self.skipTest("HSV model unavailable")

    @unittest.skipIf(SKIP_PERF, SKIP_REASON)
    def test_roi_640_meets_the_budget(self):
        roi = (640, 220, 1280, 860)  # 640x640
        median, p95 = _measure(
            lambda: detection.analyze(self.model, self.image, roi=roi), repeats=9
        )
        self.assertLessEqual(median, 3.8, f"median {median:.3f} ms over 3.8 ms")
        self.assertLessEqual(p95, 4.8, f"p95 {p95:.3f} ms over 4.8 ms")

    @unittest.skipIf(SKIP_PERF, SKIP_REASON)
    def test_cost_scales_with_roi_area_not_frame_area(self):
        """A ROI that silently ran on the whole frame would cost full-frame time.

        Note on the threshold: the plan proposed "640x640 vs 1280x720 cost ratio
        < 2.0" as the leak detector, but the 1280x720 crop covers 2.25x the
        pixels, so a *correct* linear implementation already lands near 2.25 and
        that bound would fail on working code. The property that really
        distinguishes "cropped" from "leaked to full frame" is that the cropped
        time must be clearly below the full-frame time and must grow with the
        analysed area. Both are asserted instead.
        """
        small_roi = (640, 220, 1280, 860)      # 640x640
        large_roi = (320, 180, 1600, 900)      # 1280x720 = 2.25x the pixels

        small_median, _ = _measure(
            lambda: detection.analyze(self.model, self.image, roi=small_roi), repeats=9
        )
        large_median, _ = _measure(
            lambda: detection.analyze(self.model, self.image, roi=large_roi), repeats=9
        )
        full_median, _ = _measure(
            lambda: detection.analyze(self.model, self.image), repeats=9
        )

        self.assertGreater(small_median, 0.0)
        # A full-frame leak makes both crops cost the full-frame time (ratio ~1).
        ratio = large_median / small_median
        self.assertGreater(
            ratio, 1.2,
            f"cost ratio {ratio:.2f} for a 2.25x area increase looks like full-frame work",
        )
        # And the crop must be a real saving over processing the whole frame.
        self.assertLess(
            small_median, full_median * 0.75,
            f"640x640 ROI costs {small_median:.3f} ms vs {full_median:.3f} ms full frame",
        )

    @unittest.skipIf(SKIP_PERF, SKIP_REASON)
    def test_full_frame_is_slower_than_a_640_roi(self):
        roi = (640, 220, 1280, 860)
        roi_median, _ = _measure(
            lambda: detection.analyze(self.model, self.image, roi=roi), repeats=7
        )
        full_median, _ = _measure(
            lambda: detection.analyze(self.model, self.image), repeats=7
        )
        self.assertLess(roi_median, full_median, "the ROI did not reduce detection time")

    def test_roi_never_produces_more_detections_than_full_frame(self):
        """Cheap structural guard that runs even when perf is skipped."""
        small_roi = (640, 220, 1280, 860)
        roi_result = detection.analyze(self.model, self.image, roi=small_roi)
        full_result = detection.analyze(self.model, self.image)

        self.assertLessEqual(len(roi_result.detections), len(full_result.detections))
        full_boxes = [tuple(d["bbox"]) for d in full_result.detections]
        for det in roi_result.detections:
            self.assertIn(tuple(det["bbox"]), full_boxes)


class TestDetectionAllocationHygiene(unittest.TestCase):
    def setUp(self):
        self._sandbox = _ConfigSandbox(**PINNED_DETECTION, detection_roi_max_fraction=1.0)
        self._sandbox.__enter__()
        self.addCleanup(self._sandbox.__exit__, None, None, None)
        detection.load_model()
        self.model = detection._model
        if self.model is None:
            self.skipTest("HSV model unavailable")

    def test_full_mask_is_not_allocated_until_requested(self):
        image = _frame(width=640, height=480, blobs=3)
        roi = (100, 100, 400, 400)
        result = detection.analyze(self.model, image, roi=roi)

        self.assertTrue(result.roi_used, "the ROI was dropped, so this proves nothing")
        self.assertIsNone(result._full_mask, "the full-frame mask was allocated eagerly")
        self.assertEqual(
            result.mask.shape,
            (roi[3] - roi[1], roi[2] - roi[0]),
            "the mask should cover the ROI only",
        )

    def test_full_mask_is_cached_across_calls(self):
        image = _frame(width=640, height=480, blobs=3)
        result = detection.analyze(self.model, image, roi=(100, 100, 400, 400))
        first = result.full_mask()
        second = result.full_mask()
        self.assertIs(first, second)
        self.assertEqual(first.shape, image.shape[:2])


if __name__ == "__main__":
    unittest.main()
