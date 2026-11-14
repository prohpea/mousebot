"""Anti-smoke: one contour analysis per bbox, two independent decisions.

`is_bbox_plausible` used to redo `findContours`/`convexHull`/`contourArea` on
every call, and main.py called it once per detector per target: 12 contour
analyses per frame for 6 targets. Features are now computed once and shared.

Two properties must survive that refactor:
* the decision for any bbox is bit-identical to the old, self-contained logic,
* the contour analysis really happens once, not twice.
"""
import os
import sys
import unittest
from unittest.mock import patch

import numpy as np
import cv2

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.aim_system.anti_smoke_detector import AntiSmokeDetector


def _reference_is_bbox_plausible(detector, bbox, mask, frame_shape, roi=None):
    """Verbatim copy of the pre-refactor logic, used as the oracle."""
    if not detector.enabled:
        return True
    if bbox is None or mask is None or frame_shape is None:
        return True
    if len(bbox) < 4:
        return True

    frame_h = int(frame_shape[0]) if len(frame_shape) >= 1 else 0
    frame_w = int(frame_shape[1]) if len(frame_shape) >= 2 else 0
    if frame_h <= 0 or frame_w <= 0:
        return True

    x, y, w, h = [int(v) for v in bbox[:4]]
    if w <= 0 or h <= 0:
        return False

    x1 = max(0, min(x, frame_w - 1))
    y1 = max(0, min(y, frame_h - 1))
    x2 = max(x1 + 1, min(x + w, frame_w))
    y2 = max(y1 + 1, min(y + h, frame_h))
    bw = x2 - x1
    bh = y2 - y1
    bbox_area = float(max(1, bw * bh))
    if bbox_area < float(detector.bbox_min_area):
        return False

    ox, oy = (int(roi[0]), int(roi[1])) if roi is not None else (0, 0)
    roi_patch = mask[y1 - oy:y2 - oy, x1 - ox:x2 - ox]
    if roi_patch is None or roi_patch.size == 0:
        return False

    if len(roi_patch.shape) == 3:
        roi_patch = cv2.cvtColor(roi_patch, cv2.COLOR_BGR2GRAY)
    if roi_patch.dtype != np.uint8:
        roi_patch = roi_patch.astype(np.uint8)
    if cv2.countNonZero(roi_patch) <= 0:
        return False

    roi_bin = np.ascontiguousarray((roi_patch > 0).astype(np.uint8) * 255)
    contours, _ = cv2.findContours(roi_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return False

    valid_contours = []
    for contour in contours:
        contour_area = float(cv2.contourArea(contour))
        if contour_area >= float(detector.bbox_min_contour_area):
            valid_contours.append((contour, contour_area))

    if not valid_contours:
        return False

    component_count = len(valid_contours)
    largest_contour, contour_area = max(valid_contours, key=lambda item: item[1])
    fill_ratio = contour_area / bbox_area
    if fill_ratio < float(detector.bbox_min_fill_ratio):
        return False

    _, _, lw, lh = cv2.boundingRect(largest_contour)
    if lh <= 0:
        return False
    aspect_ratio = float(lw) / float(lh)

    hull = cv2.convexHull(largest_contour)
    hull_area = float(cv2.contourArea(hull))
    solidity = contour_area / hull_area if hull_area > 0.0 else 0.0

    frame_area = float(max(1, frame_h * frame_w))
    bbox_area_ratio = bbox_area / frame_area

    if aspect_ratio >= float(detector.bbox_wide_aspect_ratio) and fill_ratio >= 0.16:
        return False
    if solidity < float(detector.bbox_min_solidity) and fill_ratio >= 0.16:
        return False
    if (
        fill_ratio >= float(detector.bbox_dense_fill_ratio)
        and component_count <= int(detector.bbox_dense_component_max)
    ):
        return False
    if (
        bbox_area_ratio >= float(detector.bbox_large_area_ratio)
        and fill_ratio >= float(detector.bbox_large_fill_ratio)
    ):
        return False

    return True


def _synthetic_cases(count=20, seed=11):
    """A mask plus ``count`` bboxes spanning the decision space.

    Boxes are deliberately varied: solid blobs (dense -> rejected), tall thin
    shapes (accepted), wide shapes (rejected), fragmented shapes, empty regions
    and boxes at the frame border.
    """
    rng = np.random.RandomState(seed)
    frame_h, frame_w = 360, 480
    mask = np.zeros((frame_h, frame_w), np.uint8)

    shapes = []
    for _ in range(count):
        x = int(rng.randint(2, frame_w - 90))
        y = int(rng.randint(2, frame_h - 90))
        w = int(rng.randint(6, 60))
        h = int(rng.randint(5, 80))
        kind = int(rng.randint(0, 5))
        if kind == 0:      # filled rectangle
            cv2.rectangle(mask, (x, y), (x + w, y + h), 255, -1)
        elif kind == 1:    # tall thin body
            cv2.rectangle(mask, (x, y), (x + max(3, w // 4), y + h), 255, -1)
        elif kind == 2:    # wide bar
            cv2.rectangle(mask, (x, y), (x + w, y + max(3, h // 5)), 255, -1)
        elif kind == 3:    # fragmented (several small pieces)
            for dx in range(0, w, 14):
                cv2.rectangle(mask, (x + dx, y), (x + dx + 6, y + h), 255, -1)
        elif kind == 4:    # ring: high perimeter, low solidity
            cv2.circle(mask, (x + w // 2, y + h // 2), max(4, min(w, h) // 2), 255, 2)
        shapes.append((x, y, w, h))

    # Deterministic edge cases on top of the random ones.
    shapes.extend([
        (0, 0, 30, 40),
        (frame_w - 20, frame_h - 20, 40, 40),
        (100, 100, 2, 2),      # below bbox_min_area
        (150, 150, 0, 10),     # degenerate
        (200, 200, 70, 70),    # large area ratio
    ])
    return mask, shapes


class TestFeatureParity(unittest.TestCase):
    def setUp(self):
        self.detector = AntiSmokeDetector()
        self.detector.set_enabled(True)
        self.mask, self.shapes = _synthetic_cases()

    def test_shared_features_match_the_old_self_contained_logic(self):
        frame_shape = self.mask.shape
        mismatches = []
        for bbox in self.shapes:
            expected = _reference_is_bbox_plausible(
                self.detector, bbox, self.mask, frame_shape
            )
            features = self.detector.compute_bbox_features(bbox, self.mask, frame_shape)
            actual = self.detector.is_bbox_plausible(
                bbox, self.mask, frame_shape, features=features
            )
            if expected != actual:
                mismatches.append((bbox, expected, actual, features))

        self.assertEqual(mismatches, [], f"{len(mismatches)} decision(s) diverged")

    def test_calling_without_features_also_matches(self):
        frame_shape = self.mask.shape
        for bbox in self.shapes:
            expected = _reference_is_bbox_plausible(self.detector, bbox, self.mask, frame_shape)
            self.assertEqual(
                expected,
                self.detector.is_bbox_plausible(bbox, self.mask, frame_shape),
                f"bbox {bbox}",
            )

    def test_reference_and_implementation_both_reject_something(self):
        """Guard against a fixture where every case returns True (no signal)."""
        frame_shape = self.mask.shape
        decisions = [
            self.detector.is_bbox_plausible(bbox, self.mask, frame_shape)
            for bbox in self.shapes
        ]
        self.assertIn(True, decisions)
        self.assertIn(False, decisions)

    def test_roi_offset_mask_matches_full_frame_mask(self):
        """Same pixels, different coordinate space: the decision must not move."""
        frame_h, frame_w = self.mask.shape
        x0, y0 = 37, 23
        sub_mask = self.mask[y0:frame_h, x0:frame_w]
        roi = (x0, y0, frame_w, frame_h)

        compared = 0
        for bbox in self.shapes:
            if bbox[0] < x0 or bbox[1] < y0:
                continue  # not representable in the cropped mask
            if bbox[0] + bbox[2] > frame_w or bbox[1] + bbox[3] > frame_h:
                continue  # clipped differently by the two coordinate spaces
            full = self.detector.is_bbox_plausible(bbox, self.mask, self.mask.shape)
            offset = self.detector.is_bbox_plausible(
                bbox, sub_mask, self.mask.shape, roi=roi
            )
            self.assertEqual(full, offset, f"bbox {bbox} changed decision under a ROI")
            compared += 1

        self.assertGreaterEqual(compared, 10, "too few bboxes were actually comparable")


class TestFeaturesAreComputedOnce(unittest.TestCase):
    def setUp(self):
        self.detector_main = AntiSmokeDetector()
        self.detector_main.set_enabled(True)
        self.detector_sec = AntiSmokeDetector()
        self.detector_sec.set_enabled(True)
        self.mask, self.shapes = _synthetic_cases()

    def _analysable_bboxes(self):
        """Bboxes that reach the contour analysis inside ``is_bbox_plausible``.

        Mirrors its early exits (minimum bbox area, then feature extraction), so
        the expected contour-pass count matches what the code really does.
        """
        frame_shape = self.mask.shape
        frame_h, frame_w = int(frame_shape[0]), int(frame_shape[1])
        found = []
        for bbox in self.shapes:
            x, y, w, h = [int(v) for v in bbox[:4]]
            if w <= 0 or h <= 0:
                continue
            x1 = max(0, min(x, frame_w - 1))
            y1 = max(0, min(y, frame_h - 1))
            x2 = max(x1 + 1, min(x + w, frame_w))
            y2 = max(y1 + 1, min(y + h, frame_h))
            if float(max(1, (x2 - x1) * (y2 - y1))) < float(self.detector_main.bbox_min_area):
                continue
            features = self.detector_main.compute_bbox_features(bbox, self.mask, frame_shape)
            if features and "component_count" in features:
                found.append(bbox)
        return found

    def _count_contour_passes(self, bboxes, shared):
        real_find_contours = cv2.findContours
        calls = {"n": 0}

        def counting_find_contours(*args, **kwargs):
            calls["n"] += 1
            return real_find_contours(*args, **kwargs)

        frame_shape = self.mask.shape
        with patch.object(cv2, "findContours", side_effect=counting_find_contours):
            for bbox in bboxes:
                if shared:
                    features = self.detector_main.compute_bbox_features(
                        bbox, self.mask, frame_shape
                    )
                    self.detector_main.is_bbox_plausible(
                        bbox, self.mask, frame_shape, features=features
                    )
                    self.detector_sec.is_bbox_plausible(
                        bbox, self.mask, frame_shape, features=features
                    )
                else:
                    self.detector_main.is_bbox_plausible(bbox, self.mask, frame_shape)
                    self.detector_sec.is_bbox_plausible(bbox, self.mask, frame_shape)
        return calls["n"]

    def test_two_detectors_share_one_contour_pass_per_bbox(self):
        bboxes = self._analysable_bboxes()
        self.assertGreaterEqual(len(bboxes), 8, "the fixture produced too little contour work")

        shared = self._count_contour_passes(bboxes, shared=True)
        separate = self._count_contour_passes(bboxes, shared=False)

        self.assertEqual(
            shared, len(bboxes),
            f"{shared} contour passes for {len(bboxes)} bboxes in the shared path",
        )
        self.assertEqual(
            separate, 2 * len(bboxes),
            f"{separate} contour passes for {len(bboxes)} bboxes in the unshared path",
        )
        self.assertEqual(
            shared, separate // 2,
            "sharing features did not halve the contour analysis",
        )

    def test_stats_hold_no_contour_references(self):
        features = self.detector_main.compute_bbox_features(
            self._analysable_bboxes()[0], self.mask, self.mask.shape
        )
        for value in features.values():
            self.assertIsInstance(value, (int, float, bool), f"{value!r} is not a plain scalar")

    def test_disabled_detector_short_circuits_before_analysis(self):
        disabled = AntiSmokeDetector()
        disabled.set_enabled(False)
        with patch.object(cv2, "findContours") as mocked:
            self.assertTrue(disabled.is_bbox_plausible((10, 10, 30, 40), self.mask, self.mask.shape))
        mocked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
