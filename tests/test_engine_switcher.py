"""
Unit tests for Detection Engine Switcher (Colorbot vs AI Detection) and In-Game Hotkey Toggle.
"""
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from src.utils.config import Config, config
from src.utils import detection
from main import AimTracker


def _make_mock_tracker():
    tracker = AimTracker.__new__(AimTracker)
    tracker.fovsize = 100.0
    tracker.fovsize_sec = 150.0
    tracker.tbfovsize = 60.0
    tracker.last_target = None
    tracker._last_engine_toggle_key_state = False
    tracker._frame_count = 0
    tracker._last_frame_log_time = 0.0
    tracker.app = MagicMock()
    tracker.app.capture.apply_mode_fov = lambda img: img
    tracker.app.capture.get_frame_meta = lambda: {}
    tracker._target_smoother = MagicMock()
    tracker._target_smoother.stabilize.return_value = []
    tracker._target_smoother.last_target = None
    tracker._target_smoother.stable_candidate = None
    tracker._target_smoother.stable_count = 0
    tracker._aim_and_move = MagicMock()
    tracker.model = None
    tracker._last_frame_seq = 1
    tracker.perf = {}
    tracker._draw_enhanced_detection = MagicMock(side_effect=lambda img, *a: img)
    tracker._draw_fovs = MagicMock()
    tracker._draw_body = MagicMock()
    tracker._draw_head_bbox = MagicMock()
    tracker._update_raw_stream_windows = MagicMock()
    return tracker


class TestEngineSwitcher(unittest.TestCase):
    def test_config_engine_synchronization(self):
        c = Config()
        c.from_dict({"detection_engine": "ai_detection"})
        self.assertEqual(c.detection_engine, "ai_detection")
        self.assertTrue(c.ai_detection_enabled)

        c.from_dict({"detection_engine": "colorbot"})
        self.assertEqual(c.detection_engine, "colorbot")
        self.assertFalse(c.ai_detection_enabled)

    def test_config_to_dict_preserves_engine_keys(self):
        c = Config()
        c.detection_engine = "ai_detection"
        c.ai_toggle_key = "F5"
        d = c.to_dict()
        self.assertEqual(d.get("detection_engine"), "ai_detection")
        self.assertEqual(d.get("ai_toggle_key"), "F5")

    def test_hotkey_toggle_transitions_engine(self):
        tracker = _make_mock_tracker()
        config.ai_toggle_key = "F5"
        config.detection_engine = "colorbot"
        config.ai_detection_enabled = False

        dummy_img = np.zeros((200, 200, 3), dtype=np.uint8)

        # Press 1: Key down
        with patch("src.utils.activation.is_binding_pressed", return_value=True):
            tracker._track_frame(dummy_img)
            self.assertEqual(config.detection_engine, "ai_detection")
            self.assertTrue(config.ai_detection_enabled)

        # Holding key down: should stay ai_detection (edge-triggered, no flip-flop)
        with patch("src.utils.activation.is_binding_pressed", return_value=True):
            tracker._track_frame(dummy_img)
            self.assertEqual(config.detection_engine, "ai_detection")

        # Key release
        with patch("src.utils.activation.is_binding_pressed", return_value=False):
            tracker._track_frame(dummy_img)
            self.assertEqual(config.detection_engine, "ai_detection")

        # Press 2: Key down again -> toggle back to colorbot
        with patch("src.utils.activation.is_binding_pressed", return_value=True):
            tracker._track_frame(dummy_img)
            self.assertEqual(config.detection_engine, "colorbot")
            self.assertFalse(config.ai_detection_enabled)


if __name__ == "__main__":
    unittest.main()
