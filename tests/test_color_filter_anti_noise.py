"""Tests for HSV color filter tuning and anti-noise fallback pass."""
import os
import sys
import unittest

import cv2
import numpy as np

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


class TestColorFilterAntiNoise(unittest.TestCase):
    def setUp(self):
        self.sandbox = _ConfigSandbox(
            color="custom",
            custom_hsv_min_h=int(getattr(config, "custom_hsv_min_h", 125)),
            custom_hsv_max_h=int(getattr(config, "custom_hsv_max_h", 165)),
            custom_hsv_min_s=int(getattr(config, "custom_hsv_min_s", 80)),
            custom_hsv_max_s=int(getattr(config, "custom_hsv_max_s", 255)),
            custom_hsv_min_v=int(getattr(config, "custom_hsv_min_v", 85)),
            custom_hsv_max_v=int(getattr(config, "custom_hsv_max_v", 255)),
            detection_morph_mode="legacy",
            detection_min_contour_points=4,
            detection_min_bbox_area=90,
            detection_min_contour_area=30,
            detection_min_fill_ratio=0.10,
            detection_min_width=4,
            detection_min_height=6,
            detection_min_aspect=0.15,
            detection_max_aspect=2.8,
            detection_edge_reject_area=80,
            detection_border_margin=1,
            detection_require_vertical_line=False,
        )
        self.sandbox.__enter__()
        detection.load_model()
        self.model = detection._model

    def tearDown(self):
        self.sandbox.__exit__(None, None, None)

    def test_compressed_purple_enemy_is_detected(self):
        """Realistic compressed enemy outline (H=140, S=100, V=110) must be detected."""
        img = np.zeros((320, 320, 3), dtype=np.uint8)
        # Create a player body (20x50) with purple outline
        # HSV: (140, 100, 110) -> BGR: (108, 67, 107) approx
        color_hsv = np.uint8([[[140, 100, 110]]])
        color_bgr = tuple(int(c) for c in cv2.cvtColor(color_hsv, cv2.COLOR_HSV2BGR)[0, 0])
        cv2.rectangle(img, (150, 130), (170, 180), color_bgr, -1)

        result = detection.analyze(self.model, img)
        self.assertGreaterEqual(len(result.detections), 1, "Compressed purple enemy was not detected")
        bbox = result.detections[0]["bbox"]
        self.assertAlmostEqual(bbox[0], 150, delta=10)
        self.assertAlmostEqual(bbox[1], 130, delta=10)

    def test_horizontal_neon_strip_is_rejected(self):
        """Horizontal neon light (wide and flat, aspect > 2.8) must be rejected."""
        img = np.zeros((320, 320, 3), dtype=np.uint8)
        color_hsv = np.uint8([[[145, 200, 200]]])
        color_bgr = tuple(int(c) for c in cv2.cvtColor(color_hsv, cv2.COLOR_HSV2BGR)[0, 0])
        # Strip: 80 px wide, only 4 px tall -> aspect = 20.0
        cv2.rectangle(img, (100, 100), (180, 104), color_bgr, -1)

        result = detection.analyze(self.model, img)
        self.assertEqual(len(result.detections), 0, "Horizontal neon strip was falsely detected as player")

    def test_tiny_noise_specks_rejected_in_fallback(self):
        """Tiny noise specks (< 36 px bbox area or < min_w/min_h) must not pass fallback."""
        img = np.zeros((320, 320, 3), dtype=np.uint8)
        color_hsv = np.uint8([[[145, 220, 220]]])
        color_bgr = tuple(int(c) for c in cv2.cvtColor(color_hsv, cv2.COLOR_HSV2BGR)[0, 0])
        # 3x3 speck and 2x10 thin sliver
        cv2.rectangle(img, (50, 50), (52, 52), color_bgr, -1)
        cv2.rectangle(img, (200, 200), (201, 209), color_bgr, -1)

        result = detection.analyze(self.model, img)
        self.assertEqual(len(result.detections), 0, "Tiny noise specks falsely detected in fallback pass")


if __name__ == "__main__":
    unittest.main()
