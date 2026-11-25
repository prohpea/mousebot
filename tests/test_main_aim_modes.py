import os
import queue
import sys
import time
import types
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.aim_system import normal
from src.aim_system.windmouse_smooth import smooth_aimer
from src.utils import activation, detection
from src.utils.config import config


class _Frame:
    def __init__(self, w=320, h=320):
        self.xres = w
        self.yres = h


class _StubController:
    def __init__(self):
        self.moves = []

    def move(self, dx, dy):
        self.moves.append((float(dx), float(dy)))

    def move_relative(self, dx, dy):
        self.moves.append((float(dx), float(dy)))


def _make_tracker(ctrl):
    return types.SimpleNamespace(
        controller=ctrl,
        move_queue=queue.Queue(),
        _clip_movement=lambda dx, dy: (dx, dy),
        fovsize=120,
        fovsize_sec=120,
        aim_offsetX=0,
        aim_offsetY=0,
        aim_offsetX_sec=0,
        aim_offsetY_sec=0,
        in_game_sens=0.23,
        normal_x_speed=73,
        normal_y_speed=76,
        normalsmooth=12,
        normalsmoothfov=10,
        mouse_dpi=1100,
        deadzone_fovsize=4.0,
        deadzone_stop_delay_min_ms=15.0,
        deadzone_stop_delay_max_ms=45.0,
        _was_main_aimbot_active=False,
    )


def _drain_moves(tracker, ctrl):
    all_moves = list(ctrl.moves)
    while not tracker.move_queue.empty():
        item = tracker.move_queue.get_nowait()
        if isinstance(item, tuple) and len(item) >= 2:
            all_moves.append((float(item[0]), float(item[1])))
    return all_moves


class MainAimModesTests(unittest.TestCase):
    _SAVED_KEYS = (
        "enableaim",
        "enableaim_sec",
        "mode",
        "aimbot_activation_type",
        "selected_mouse_button",
        "fovsize",
        "aim_type",
        "aim_offsetX",
        "aim_offsetY",
        "deadzone_fov_enabled",
        "deadzone_fovsize",
        "deadzone_stop_delay_min_ms",
        "deadzone_stop_delay_max_ms",
        "ads_fov_enabled",
        "in_game_sens",
        "mouse_dpi",
        "normal_x_speed",
        "normal_y_speed",
        "normalsmooth",
        "abcurves_x_speed",
        "abcurves_y_speed",
        "abcurves_max_step",
        "abcurves_commitment_ms",
        "abcurves_seed",
        "wm_gravity",
        "wm_wind",
        "wm_max_step",
        "wm_min_step",
        "wm_min_delay",
        "wm_max_delay",
        "wm_distance_threshold",
        "gpu_opencl_enabled",
    )

    def setUp(self):
        self._orig = {k: getattr(config, k, None) for k in self._SAVED_KEYS}
        config.enableaim = True
        config.enableaim_sec = False
        config.aimbot_activation_type = "toggle"
        config.selected_mouse_button = 4
        config.fovsize = 120
        config.aim_type = "head"
        config.aim_offsetX = 0
        config.aim_offsetY = 0
        config.deadzone_fov_enabled = False
        config.ads_fov_enabled = False
        config.in_game_sens = 0.23
        config.mouse_dpi = 1100
        config.normal_x_speed = 73
        config.normal_y_speed = 76
        config.normalsmooth = 12
        config.abcurves_x_speed = 1.55
        config.abcurves_y_speed = 1.35
        config.abcurves_max_step = 50.0
        config.abcurves_commitment_ms = 16
        config.abcurves_seed = 942
        config.wm_gravity = 9.0
        config.wm_wind = 3.0
        config.wm_max_step = 15
        config.wm_min_step = 2
        config.wm_min_delay = 0.001
        config.wm_max_delay = 0.003
        config.wm_distance_threshold = 50
        self.img = np.zeros((320, 320, 3), dtype=np.uint8)

    def tearDown(self):
        for k, v in self._orig.items():
            if v is not None:
                setattr(config, k, v)
        activation.reset_activation_state(is_sec=False)

    def test_gpu_opencl_detection_matches_cpu_for_main_aim(self):
        img = np.zeros((320, 320, 3), dtype=np.uint8)
        img[100:180, 140:176] = (230, 20, 230)
        img[112:168, 148:168] = (20, 20, 20)
        model = detection.XUDP_HSV_PRESETS["purple"][0]

        detection._PREV_STABLE_RECTS.clear()
        config.gpu_opencl_enabled = False
        dets_cpu, mask_cpu = detection.perform_detection(model, img)

        detection._PREV_STABLE_RECTS.clear()
        config.gpu_opencl_enabled = True
        dets_gpu, mask_gpu = detection.perform_detection(model, img)

        self.assertEqual(dets_cpu, dets_gpu)
        self.assertTrue(len(dets_cpu) >= 1)
        self.assertTrue(np.array_equal(mask_cpu, mask_gpu))

    def test_abcurves_main_aim_tracks_target_and_respects_deadzone(self):
        config.mode = "ABCurves"
        ctrl = _StubController()
        tracker = _make_tracker(ctrl)
        with patch.object(normal, "check_aimbot_activation", side_effect=lambda btn, act, is_sec=False: not is_sec):
            for _ in range(4):
                normal.process_normal_mode([(220.0, 130.0, 67.08, None, None)], _Frame(), self.img, tracker)
        moves = _drain_moves(tracker, ctrl)
        self.assertGreater(len(moves), 0)
        self.assertGreater(sum(m[0] for m in moves), 0.0)
        self.assertLess(sum(m[1] for m in moves), 0.0)

        # Inside deadzone with 0ms stop delay -> 0 moves
        config.deadzone_fov_enabled = True
        config.deadzone_fovsize = 8.0
        config.deadzone_stop_delay_min_ms = 0.0
        config.deadzone_stop_delay_max_ms = 0.0
        ctrl2 = _StubController()
        tracker2 = _make_tracker(ctrl2)
        tracker2.deadzone_fovsize = 8.0
        tracker2.deadzone_stop_delay_min_ms = 0.0
        tracker2.deadzone_stop_delay_max_ms = 0.0
        with patch.object(normal, "check_aimbot_activation", side_effect=lambda btn, act, is_sec=False: not is_sec):
            normal.process_normal_mode([(162.0, 159.0, 2.23, None, None)], _Frame(), self.img, tracker2)
        self.assertEqual(len(_drain_moves(tracker2, ctrl2)), 0)

    def test_normal_main_aim_tracks_target_and_nearest_y_clamp(self):
        config.mode = "Normal"
        ctrl = _StubController()
        tracker = _make_tracker(ctrl)
        with patch.object(normal, "check_aimbot_activation", side_effect=lambda btn, act, is_sec=False: not is_sec):
            for _ in range(3):
                normal.process_normal_mode([(220.0, 130.0, 67.08, None, None)], _Frame(), self.img, tracker)
        moves = _drain_moves(tracker, ctrl)
        self.assertGreater(len(moves), 0)
        self.assertGreater(sum(m[0] for m in moves), 0.0)
        self.assertLess(sum(m[1] for m in moves), 0.0)

        # Nearest Y-clamping
        config.aim_type = "nearest"
        ctrl2 = _StubController()
        tracker2 = _make_tracker(ctrl2)
        with patch.object(normal, "check_aimbot_activation", side_effect=lambda btn, act, is_sec=False: not is_sec):
            normal.process_normal_mode([(190.0, 150.0, 31.6, 130.0, 200.0)], _Frame(), self.img, tracker2)
        moves2 = _drain_moves(tracker2, ctrl2)
        self.assertGreater(len(moves2), 0)
        self.assertTrue(all(m[1] == 0.0 for m in moves2))
        self.assertGreater(sum(m[0] for m in moves2), 0.0)

    def test_windmouse_main_aim_tracks_target_after_reaction_delay(self):
        config.mode = "WindMouse"
        ctrl = _StubController()
        tracker = _make_tracker(ctrl)
        smooth_aimer.last_target = None
        smooth_aimer.last_reaction_time = 0.0
        with patch.object(normal, "check_aimbot_activation", side_effect=lambda btn, act, is_sec=False: not is_sec):
            # First frame triggers reaction timer, then advance past reaction delay
            normal.process_normal_mode([(220.0, 130.0, 67.08, None, None)], _Frame(), self.img, tracker)
            smooth_aimer.last_reaction_time = time.time() - 1.0
            normal.process_normal_mode([(220.0, 130.0, 67.08, None, None)], _Frame(), self.img, tracker)
        moves = _drain_moves(tracker, ctrl)
        self.assertGreater(len(moves), 0)
        self.assertGreater(sum(m[0] for m in moves), 0.0)
        self.assertLess(sum(m[1] for m in moves), 0.0)

    def test_distance_scaled_aim_offset_preserves_close_and_scales_50m(self):
        config.mode = "Normal"
        config.aim_type = "head"
        config.aim_offsetX = 2.0
        config.aim_offsetY = -4.0
        config.aim_offset_distance_scaling = True
        config.aim_offset_ref_height = 64.0
        config.deadzone_fov_enabled = False

        # Close/medium (<=25m, h=68px -> scale=1.0): full offset x=+2, y=-4
        ctrl_close = _StubController()
        tracker_close = _make_tracker(ctrl_close)
        tracker_close._target_offset_scales = {(160.0, 164.0): 1.0}
        dispatched_close = []
        with (
            patch.object(normal, "check_aimbot_activation", side_effect=lambda btn, act, is_sec=False: not is_sec),
            patch.object(normal, "_dispatch_aimbot", side_effect=lambda dx, dy, *a, **kw: dispatched_close.append((dx, dy))),
        ):
            normal.process_normal_mode([(160.0, 164.0, 4.0, None, None)], _Frame(), self.img, tracker_close)
        self.assertEqual(len(dispatched_close), 1)
        self.assertAlmostEqual(dispatched_close[0][0], 2.0, places=3)
        self.assertAlmostEqual(dispatched_close[0][1], 0.0, places=3)  # 164 + (-4) - 160 = 0

        # Far (50m+, h=28px -> scale=0.72 + 0.28*(28/64)=0.8425): stays on head, never drops to chest
        far_scale = 0.72 + 0.28 * (28.0 / 64.0)
        ctrl_far = _StubController()
        tracker_far = _make_tracker(ctrl_far)
        tracker_far._target_offset_scales = {(160.0, 164.0): far_scale}
        dispatched_far = []
        with (
            patch.object(normal, "check_aimbot_activation", side_effect=lambda btn, act, is_sec=False: not is_sec),
            patch.object(normal, "_dispatch_aimbot", side_effect=lambda dx, dy, *a, **kw: dispatched_far.append((dx, dy))),
        ):
            normal.process_normal_mode([(160.0, 164.0, 4.0, None, None)], _Frame(), self.img, tracker_far)
        self.assertEqual(len(dispatched_far), 1)
        self.assertAlmostEqual(dispatched_far[0][0], 2.0 * far_scale, places=3)
        self.assertAlmostEqual(dispatched_far[0][1], 4.0 - 4.0 * far_scale, places=3)


if __name__ == "__main__":
    unittest.main()
