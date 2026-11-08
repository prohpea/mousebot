import os
import queue
import sys
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.config import config
from src.utils.activation import (
    reset_activation_state,
    get_aimbot_toggle_state,
)
from src.aim_system.normal import process_normal_mode


class MockFrame:
    def __init__(self, xres=1920, yres=1080):
        self.xres = xres
        self.yres = yres


class MockController:
    def __init__(self):
        self.moves = []

    def move(self, dx, dy):
        self.moves.append((dx, dy))


class MockTracker:
    def __init__(self):
        self.controller = MockController()
        self.move_queue = queue.Queue()
        self.rcs_pull_speed = 0.0
        self.rcs_activation_delay = 0.0
        self.rcs_rapid_click_threshold = 0.0
        self.fovsize = 150.0
        self.fovsize_sec = 100.0
        self.normal_x_speed = 1.0
        self.normal_y_speed = 1.0
        self.normalsmooth = 1.0
        self.normalsmoothfov = 50.0
        self.in_game_sens = 1.0
        self.mouse_dpi = 800.0
        self.aim_offsetX = 0.0
        self.aim_offsetY = 0.0
        self.aim_offsetX_sec = 0.0
        self.aim_offsetY_sec = 0.0
        self.model = None
        self.tbdelay_min = 0
        self.tbdelay_max = 0
        self.tbhold_min = 0
        self.tbhold_max = 0
        self.tbcooldown_min = 0
        self.tbcooldown_max = 0
        self.tbburst_count_min = 0
        self.tbburst_count_max = 0
        self.tbburst_interval_min = 0
        self.tbburst_interval_max = 0

    def _clip_movement(self, dx, dy):
        return float(dx), float(dy)


class TestToggleActivation(unittest.TestCase):
    def setUp(self):
        reset_activation_state(is_sec=False)
        reset_activation_state(is_sec=True)
        self._orig_mode = getattr(config, "mode", "Normal")
        config.mode = "Normal"
        config.enableaim = True
        config.aimbot_activation_type = "toggle"
        config.selected_mouse_button = 1
        config.enabletb = False
        config.enable_magnet_trigger = False

    def tearDown(self):
        reset_activation_state(is_sec=False)
        reset_activation_state(is_sec=True)
        config.mode = getattr(self, "_orig_mode", "Normal")

    @patch("src.utils.activation.is_button_pressed")
    def test_toggle_without_colortarget(self, mock_is_button):
        """
        Test that pressing the toggle key when NO target is present
        successfully toggles the aimbot activation state on and off,
        and controls aiming when targets appear.
        """
        frame = MockFrame()
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        tracker = MockTracker()

        # Initially toggle state is False
        self.assertFalse(get_aimbot_toggle_state(is_sec=False))

        # 1. User presses toggle button when no targets are detected
        mock_is_button.return_value = True
        process_normal_mode(
            targets_main=[],
            frame=frame,
            img=img,
            tracker=tracker,
            targets_sec=[],
            targets_trigger=[],
            trigger_img=img,
        )

        # Toggle state MUST be True now!
        self.assertTrue(
            get_aimbot_toggle_state(is_sec=False),
            "Aimbot toggle state should be True after pressing toggle key, even with no targets!"
        )

        # Target appears inside FOV: aimbot should move
        target = (frame.xres / 2.0 + 10, frame.yres / 2.0 + 10, 14.14, None, None)
        process_normal_mode(
            targets_main=[target],
            frame=frame,
            img=img,
            tracker=tracker,
            targets_sec=[],
            targets_trigger=[],
            trigger_img=img,
        )
        self.assertTrue(tracker.move_queue.qsize() > 0, "Aimbot should aim when toggled ON and target in FOV")
        while not tracker.move_queue.empty():
            tracker.move_queue.get_nowait()

        # 2. Release button
        mock_is_button.return_value = False
        process_normal_mode(
            targets_main=[],
            frame=frame,
            img=img,
            tracker=tracker,
            targets_sec=[],
            targets_trigger=[],
            trigger_img=img,
        )
        self.assertTrue(get_aimbot_toggle_state(is_sec=False), "Toggle state should remain ON after release")

        # 3. Press toggle button again without targets to turn OFF
        mock_is_button.return_value = True
        process_normal_mode(
            targets_main=[],
            frame=frame,
            img=img,
            tracker=tracker,
            targets_sec=[],
            targets_trigger=[],
            trigger_img=img,
        )
        self.assertFalse(
            get_aimbot_toggle_state(is_sec=False),
            "Aimbot toggle state should be False after pressing toggle key second time!"
        )

        # Target appears inside FOV: aimbot should NOT move now that it's toggled OFF
        process_normal_mode(
            targets_main=[target],
            frame=frame,
            img=img,
            tracker=tracker,
            targets_sec=[],
            targets_trigger=[],
            trigger_img=img,
        )
        self.assertEqual(tracker.move_queue.qsize(), 0, "Aimbot should NOT aim when toggled OFF")



if __name__ == "__main__":
    unittest.main()
