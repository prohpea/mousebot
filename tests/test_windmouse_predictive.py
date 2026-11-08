import os
import sys
import time
import unittest

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aim_system.windmouse_smooth import SmoothAiming, WindMouse


class MockWindMouseConfig:
    def __init__(self):
        self.smooth_gravity = 10.5
        self.smooth_wind = 2.2
        self.smooth_max_step = 22.0
        self.smooth_min_step = 2.0
        self.smooth_min_delay = 0.001
        self.smooth_max_delay = 0.0025
        self.smooth_distance_threshold = 45.0
        self.smooth_reaction_min = 0.02
        self.smooth_reaction_max = 0.08
        self.smooth_close_range = 30.0
        self.smooth_close_speed = 0.3
        self.smooth_far_range = 200.0
        self.smooth_far_speed = 0.8
        self.smooth_fatigue_effect = 0.5
        self.smooth_max_step_ratio = 0.15
        self.smooth_target_area_ratio = 0.05
        self.smooth_acceleration = 0.8
        self.smooth_deceleration = 0.6
        self.smooth_micro_corrections = 0


class TestPredictiveWindMouse(unittest.TestCase):
    def setUp(self):
        self.aimer = SmoothAiming()
        self.config = MockWindMouseConfig()

    def test_continuous_strafe_no_stall(self):
        """
        Verify that a target strafing across frames does NOT trigger repeated reaction delays
        and returns non-empty movement paths during tracking.
        """
        # Initial detection
        self.aimer.last_target = None
        self.aimer.last_reaction_time = 0

        # Prime initial reaction
        _ = self.aimer.calculate_smooth_path(20.0, 0.0, self.config)
        # Fast-forward past initial reaction delay
        self.aimer.last_reaction_time = time.time() - 0.2

        # Simulate continuous strafing over 6 frames (e.g. target moving +5px every 16ms)
        non_empty_count = 0
        curr_x = 25.0
        for _ in range(6):
            time.sleep(0.016)
            path = self.aimer.calculate_smooth_path(curr_x, 0.0, self.config)
            if len(path) > 0:
                non_empty_count += 1
            curr_x += 5.0

        # Must produce movement for the majority of strafe frames, not stall to 0
        self.assertGreaterEqual(non_empty_count, 4, f"Aimbot stalled during strafe: only {non_empty_count}/6 frames produced paths")

    def test_velocity_lead_prediction(self):
        """
        Verify that target velocity is estimated and lead prediction applies in the direction of motion.
        """
        self.assertTrue(hasattr(self.aimer, "velocity_x") and hasattr(self.aimer, "get_predicted_lead"),
                        "SmoothAiming must implement velocity tracking attributes")

        now = time.time()
        self.aimer.update_velocity(10.0, 0.0, now)
        self.aimer.update_velocity(15.0, 0.0, now + 0.025)
        self.aimer.update_velocity(20.0, 0.0, now + 0.050)

        self.assertGreater(self.aimer.velocity_x, 30.0, f"Expected positive X velocity, got {self.aimer.velocity_x}")
        lead_x, lead_y = self.aimer.get_predicted_lead(20.0, 0.0)
        self.assertGreater(lead_x, 20.0, f"Expected lead_x > 20.0, got {lead_x}")

    def test_hand_tremor_suppression(self):
        """
        Verify that high-frequency hand tremors (+-2px) do NOT trigger erratic velocity amplification.
        """
        now = time.time()
        tremor_series = [15.0, 17.0, 14.2, 16.5, 13.8, 16.0]
        for i, val in enumerate(tremor_series):
            self.aimer.update_velocity(val, 0.0, now + i * 0.016)

        # Velocity must remain low and dampened, not exploding to 100+ px/s
        self.assertLess(abs(self.aimer.velocity_x), 35.0,
                        f"Hand tremor was amplified into high velocity: {self.aimer.velocity_x:.1f} px/s")

    def test_subpixel_preservation(self):
        """
        Verify that small steps in path are preserved and not zeroed out by integer truncation.
        """
        test_path = [(1, 0, 0.001), (1, 0, 0.001), (1, 0, 0.001), (1, 0, 0.001)]
        smoothed = self.aimer._apply_smoothing_filters(test_path, self.config)
        total_dx = sum(step[0] for step in smoothed)
        self.assertGreater(total_dx, 0, "Sub-pixel steps were all truncated to zero")

    def test_target_switch_detection(self):
        """
        Verify that a small movement does NOT trigger target switch, but a large jump does.
        """
        now = time.time()
        self.aimer.last_target = (10.0, 5.0)
        self.aimer.last_target_time = now
        self.aimer.last_reaction_time = now

        # Small movement (strafe 15px) should NOT be classified as target switch
        is_switch_small = self.aimer._is_target_switch(25.0, 5.0, now + 0.016)
        self.assertFalse(is_switch_small, "Small strafe movement wrongly detected as target switch")

        # Large jump (150px) SHOULD be classified as target switch
        is_switch_large = self.aimer._is_target_switch(170.0, 5.0, now + 0.016)
        self.assertTrue(is_switch_large, "Large target jump not detected as target switch")

    def test_rapid_direction_reversal(self):
        """
        Verify that sudden AD strafe reversals do not cause math crashes or excessive overshoots.
        """
        now = time.time()
        for i in range(5):
            self.aimer.update_velocity(10.0 + i * 4.0, 0.0, now + i * 0.016)
        self.assertGreater(self.aimer.velocity_x, 0.0)

        for i in range(5):
            self.aimer.update_velocity(26.0 - i * 4.0, 0.0, now + (5 + i) * 0.016)
        self.assertLess(self.aimer.velocity_x, 50.0)

    def test_performance_benchmark(self):
        """
        Ensure average execution latency of calculate_smooth_path is well below 1.0ms.
        """
        self.aimer.last_reaction_time = time.time() - 1.0
        self.aimer.last_target_time = time.time()

        start_time = time.perf_counter()
        iterations = 100
        for i in range(iterations):
            _ = self.aimer.calculate_smooth_path(15.0 + (i % 5), 10.0, self.config)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        avg_latency = elapsed_ms / iterations

        self.assertLess(avg_latency, 1.0, f"Average execution latency too high: {avg_latency:.3f}ms per call (budget <= 1.0ms)")


if __name__ == "__main__":
    unittest.main()
