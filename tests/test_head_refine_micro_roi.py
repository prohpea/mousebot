"""
Unit tests for Head Refinement and Dynamic Micro-ROI.
"""
import unittest
from unittest.mock import MagicMock
import numpy as np

from src.utils.config import config
from main import AimTracker


def _make_mock_tracker():
    tracker = AimTracker.__new__(AimTracker)
    tracker.fovsize = 100.0
    tracker.fovsize_sec = 150.0
    tracker.tbfovsize = 60.0
    tracker.last_target = None
    tracker.app = MagicMock()
    return tracker


class TestHeadRefinementAndMicroRoi(unittest.TestCase):
    def test_head_refine_y_with_upper_mask(self):
        tracker = _make_mock_tracker()
        img = np.zeros((400, 400, 3), np.uint8)
        # Create a synthetic mask with a head blob at y=50..70, x=190..210 inside bbox (180, 50, 220, 250)
        mask = np.zeros((400, 400), np.uint8)
        mask[50:75, 195:205] = 255

        # With head_refine_y_enabled
        config.head_refine_y_enabled = True
        config.head_refine_band_ratio = 0.25
        config.head_refine_min_pixels = 20

        res = tracker._estimate_head_positions(180, 50, 220, 250, img, mask=mask)
        self.assertEqual(len(res), 1)
        head_cx, head_cy, roi_rect = res[0]
        # Bounding box is (180, 50, 220, 250), height=200. Geometric base ratio 0.22 would be y=50 + 44 = 94.
        # But head blob is at y=50..75 (median y ~ 62). Refined Y should be pulled towards 62!
        self.assertLess(head_cy, 90)
        self.assertGreater(head_cy, 55)

    def test_dynamic_micro_roi_encompasses_last_target(self):
        tracker = _make_mock_tracker()
        config.detection_roi_enabled = True
        config.dynamic_micro_roi_enabled = True
        config.enableaim = True
        config.fovsize = 50.0
        config.detection_roi_padding = 20
        config.dynamic_micro_roi_padding = 40

        frame_shape = (720, 1280, 3)
        # Without last target: ROI centered around crosshair (640, 360)
        roi_no_target = tracker._compute_detection_roi(frame_shape)
        self.assertIsNotNone(roi_no_target)
        x0, y0, x1, y1 = roi_no_target
        self.assertTrue(x0 <= 640 <= x1)
        self.assertTrue(y0 <= 360 <= y1)

        # With last target at (800, 450)
        tracker.last_target = (800.0, 450.0, None, None)
        roi_with_target = tracker._compute_detection_roi(frame_shape)
        self.assertIsNotNone(roi_with_target)
        tx0, ty0, tx1, ty1 = roi_with_target
        # Must encompass both crosshair and target
        self.assertTrue(tx0 <= 640 and tx1 >= 800)
        self.assertTrue(ty0 <= 360 and ty1 >= 450)


if __name__ == "__main__":
    unittest.main()
