import unittest

from src.aim_system.target_smoother import TargetSmoother


class TargetSmootherTests(unittest.TestCase):
    def test_first_target_is_returned_immediately(self):
        smoother = TargetSmoother(ema_alpha=1.0)
        result = smoother.stabilize([(10.0, 20.0, 0.5)], 0.0, 0.0)
        self.assertEqual(len(result), 1)
        x, y, distance, head_y_min, body_y_max = result[0]
        self.assertEqual((x, y), (10.0, 20.0))
        self.assertAlmostEqual(distance, (10.0 ** 2 + 20.0 ** 2) ** 0.5)
        self.assertIsNone(head_y_min)
        self.assertIsNone(body_y_max)

    def test_lowest_score_target_wins(self):
        smoother = TargetSmoother(ema_alpha=1.0)
        result = smoother.stabilize([(0.0, 0.0, 0.9), (50.0, 50.0, 0.1)], 0.0, 0.0)
        self.assertEqual(result[0][:2], (50.0, 50.0))

    def test_far_candidate_needs_confirmation_before_switch(self):
        smoother = TargetSmoother(
            ema_alpha=1.0, switch_confirm_frames=3, switch_radius_px=18.0
        )
        smoother.stabilize([(100.0, 100.0, 0.1)], 0.0, 0.0)
        for _ in range(2):
            result = smoother.stabilize([(300.0, 100.0, 0.1)], 0.0, 0.0)
            self.assertEqual(result[0][:2], (100.0, 100.0))
        result = smoother.stabilize([(300.0, 100.0, 0.1)], 0.0, 0.0)
        self.assertEqual(result[0][:2], (300.0, 100.0))

    def test_nearby_target_is_ema_smoothed(self):
        smoother = TargetSmoother(ema_alpha=0.5, switch_radius_px=18.0)
        smoother.stabilize([(100.0, 100.0, 0.1)], 0.0, 0.0)
        result = smoother.stabilize([(110.0, 100.0, 0.1)], 0.0, 0.0)
        self.assertEqual(result[0][:2], (105.0, 100.0))

    def test_empty_input_resets_confirmation_state(self):
        smoother = TargetSmoother(ema_alpha=1.0, switch_confirm_frames=2)
        smoother.stabilize([(100.0, 100.0, 0.1)], 0.0, 0.0)
        smoother.stabilize([(300.0, 100.0, 0.1)], 0.0, 0.0)
        self.assertEqual(smoother.stabilize([], 0.0, 0.0), [])
        self.assertIsNone(smoother.stable_candidate)
        self.assertEqual(smoother.stable_count, 0)


if __name__ == "__main__":
    unittest.main()
