"""Tests for 2-target anti-merge, target stickiness hysteresis, anti-midpoint smoothing, and FOV 15 snap."""
import os
import sys
import math
import unittest
import cv2
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.utils.config import config
from src.utils import detection
from src.aim_system import normal as normal_mod
from src.aim_system.target_smoother import TargetSmoother
from src.aim_system.windmouse_smooth import smooth_aimer


class TestTargetAntiMergeAndStickiness(unittest.TestCase):
    def setUp(self):
        detection.load_model()
        self.model = detection._model

    def test_two_adjacent_enemies_detected_separately(self):
        """Two adjacent enemies (12 px gap) must be detected as 2 distinct boxes, not merged into center air."""
        img = np.zeros((300, 300, 3), dtype=np.uint8)
        color_hsv = np.uint8([[[145, 180, 220]]])
        color_bgr = tuple(int(c) for c in cv2.cvtColor(color_hsv, cv2.COLOR_HSV2BGR)[0, 0])

        # Enemy 1: x=120..142 (w=22, h=60)
        # Enemy 2: x=154..176 (w=22, h=60)
        cv2.rectangle(img, (120, 100), (142, 160), color_bgr, 2)
        cv2.rectangle(img, (154, 100), (176, 160), color_bgr, 2)

        res = detection.analyze(self.model, img)
        self.assertEqual(len(res.detections), 2, f"Expected 2 separate detections, got {len(res.detections)}")

        centers_x = sorted([d["bbox"][0] + d["bbox"][2] / 2.0 for d in res.detections])
        # Enemy 1 center is ~131, Enemy 2 center is ~165. Empty air is ~148.
        self.assertAlmostEqual(centers_x[0], 131, delta=5)
        self.assertAlmostEqual(centers_x[1], 165, delta=5)
        # Verify neither detection is in the empty space between them (144..152)
        for cx in centers_x:
            self.assertFalse(144 <= cx <= 152, f"Center {cx} is inside empty air between players")

    def test_two_overlapping_enemies_decomposed(self):
        """Two enemies overlapping by 2 px must be decomposed into 2 targets, not 1 in the middle."""
        img = np.zeros((300, 300, 3), dtype=np.uint8)
        color_hsv = np.uint8([[[145, 180, 220]]])
        color_bgr = tuple(int(c) for c in cv2.cvtColor(color_hsv, cv2.COLOR_HSV2BGR)[0, 0])

        # Enemy 1: x=120..142 (w=22, h=60)
        # Enemy 2: x=140..162 (w=22, h=60) -> 2 px overlap
        cv2.rectangle(img, (120, 100), (142, 160), color_bgr, 2)
        cv2.rectangle(img, (140, 100), (162, 160), color_bgr, 2)

        res = detection.analyze(self.model, img)
        self.assertGreaterEqual(len(res.detections), 2, "Overlapping enemies were merged into 1 midpoint box")

        centers_x = sorted([d["bbox"][0] + d["bbox"][2] / 2.0 for d in res.detections])
        self.assertLess(centers_x[0], 136.0, "Left player center too close to midpoint")
        self.assertGreater(centers_x[-1], 146.0, "Right player center too close to midpoint")

    def test_target_stickiness_hysteresis_prevents_flipping(self):
        """Once locked to Target 1, slight distance competition from Target 2 must not cause target flipping."""
        class DummyTracker:
            pass

        tracker = DummyTracker()
        # Initial frame: Target 1 at distance 12 px, Target 2 at distance 14 px
        # Targets: (cx, cy, distance, head_y_min, body_y_max)
        t1 = (130.0, 100.0, 12.0, 95.0, 155.0)
        t2 = (150.0, 100.0, 14.0, 95.0, 155.0)

        first_pick = normal_mod._select_sticky_target([t1, t2], tracker, is_sec=False)
        self.assertEqual(first_pick, t1, "Initial lock should be closest target (t1)")

        # Next frame: Target 2 moves slightly closer to center (dist 11.0), while Target 1 is dist 12.0
        # Without stickiness, it would flip to t2.
        # With stickiness (bonus = 12 px), t1's effective score is 12.0 - 12.0 = 0.0 vs t2's 11.0.
        t1_next = (130.0, 100.0, 12.0, 95.0, 155.0)
        t2_closer = (148.0, 100.0, 11.0, 95.0, 155.0)

        second_pick = normal_mod._select_sticky_target([t1_next, t2_closer], tracker, is_sec=False)
        self.assertEqual(second_pick, t1_next, "Lock should stick to t1 despite t2 being marginally closer")

    def test_target_smoother_no_midpoint_on_target_switch(self):
        """When switching targets across space, TargetSmoother must NOT interpolate into empty air."""
        clock = [100.0]
        smoother = TargetSmoother(ema_alpha=0.5, switch_confirm_frames=2,
                                  switch_radius_px=10.0, clock=lambda: clock[0])

        # Track Target 1 at x=120
        t1 = [(120.0, 100.0, 10.0, 90.0, 150.0)]
        smoother.stabilize(t1, 150.0, 150.0)

        # Switch to Target 2 at x=160
        t2 = [(160.0, 100.0, 10.0, 90.0, 150.0)]
        clock[0] += 0.01
        res1 = smoother.stabilize(t2, 150.0, 150.0) # Confirm frame 1: holds t1 (120)
        self.assertAlmostEqual(res1[0][0], 120.0, delta=1.0)

        clock[0] += 0.01
        res2 = smoother.stabilize(t2, 150.0, 150.0) # Confirm frame 2: switch confirmed!
        # Must snap directly to 160, NEVER average to (120+160)/2 = 140!
        self.assertAlmostEqual(res2[0][0], 160.0, delta=1.0,
                               msg=f"Target smoother emitted midpoint {res2[0][0]} instead of snapping to 160")

    def test_critical_damping_prevents_subcount_overshoot(self):
        """Sub-count error (< 1 count) must not round up to a full count if doing so overshoots."""
        class MockTrackerWithQueue:
            def __init__(self):
                self.moves = []
            def _clip_movement(self, dx, dy):
                return dx, dy

        tracker = MockTrackerWithQueue()
        # Test error of 1.0 px (with cpp ~ 0.358, desired is ~ 0.36 counts).
        # Emitting 1 count would move 2.79 px, causing overshoot to -1.79 px.
        # Critical damping should ensure emit_x is 0 and carry accumulates.
        from types import SimpleNamespace
        wm_cfg = SimpleNamespace(
            wm_frame_gain=0.50,
            wm_frame_max_step_px=8.0,
            wm_settle_radius_px=0.5, # Small settle so budget is evaluated
            smooth_reaction_min=0.01,
            smooth_reaction_max=0.02,
        )

        import time
        smooth_aimer.calculate_smooth_path(1.0, 0.0, wm_cfg)
        time.sleep(0.04)
        normal_mod._emit_windmouse_budget(tracker, 1.0, 0.0, wm_cfg, is_sec=False)
        carry_x, _ = normal_mod._wm_carry(tracker, is_sec=False)
        # Verify carry accumulated without a premature 1-count jump
        self.assertGreater(carry_x, 0.0)


if __name__ == "__main__":
    unittest.main()
