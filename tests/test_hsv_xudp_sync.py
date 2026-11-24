import json
from pathlib import Path
import unittest

import numpy as np

from src.utils.config import config
from src.utils import detection


class XUdpHsvSyncTests(unittest.TestCase):
    def setUp(self):
        self._saved = {
            "color": config.color,
            "custom_hsv_min_h": config.custom_hsv_min_h,
            "custom_hsv_min_s": config.custom_hsv_min_s,
            "custom_hsv_min_v": config.custom_hsv_min_v,
            "custom_hsv_max_h": config.custom_hsv_max_h,
            "custom_hsv_max_s": config.custom_hsv_max_s,
            "custom_hsv_max_v": config.custom_hsv_max_v,
        }

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(config, k, v)
        detection.load_model()

    def test_purple_preset_matches_xudp_v2_1_and_rejects_dimmed_bg(self):
        config.color = "purple"
        model, _ = detection.load_model()
        self.assertIsNotNone(model)
        self.assertEqual(model[0].tolist(), [120, 188, 115])
        self.assertEqual(model[1].tolist(), [160, 255, 255])

        # Pixel 0: dimmed background (S < 90), Pixel 1: xUDP boosted purple outline (S >= 190, V >= 115)
        hsv = np.array([[[140, 85, 130], [140, 195, 140]]], dtype=np.uint8)
        mask = detection.compute_hsv_mask(hsv, model)
        self.assertEqual(int(mask[0, 0]), 0)
        self.assertEqual(int(mask[0, 1]), 255)

    def test_yellow_preset_matches_xudp_range(self):
        config.color = "yellow"
        model, _ = detection.load_model()
        self.assertEqual(model[0].tolist(), [20, 100, 100])
        self.assertEqual(model[1].tolist(), [30, 255, 255])

    def test_red_preset_matches_both_xudp_wraparound_ranges(self):
        config.color = "red"
        model, _ = detection.load_model()
        self.assertEqual(len(model), 3)

        # Low-hue red (H=5), high-hue red (H=172), and non-red purple (H=140)
        hsv = np.array([[[5, 180, 150], [172, 180, 150], [140, 200, 200]]], dtype=np.uint8)
        mask = detection.compute_hsv_mask(hsv, model)
        self.assertEqual(int(mask[0, 0]), 255)
        self.assertEqual(int(mask[0, 1]), 255)
        self.assertEqual(int(mask[0, 2]), 0)

    def test_active_config_json_custom_hsv_matches_xudp_purple(self):
        cfg_path = Path(__file__).resolve().parents[1] / "config.json"
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.assertEqual(data["custom_hsv_min_h"], 120)
        self.assertEqual(data["custom_hsv_min_s"], 188)
        self.assertEqual(data["custom_hsv_min_v"], 115)
        self.assertEqual(data["custom_hsv_max_h"], 160)
        self.assertEqual(data["custom_hsv_max_s"], 255)
        self.assertEqual(data["custom_hsv_max_v"], 255)


if __name__ == "__main__":
    unittest.main()
