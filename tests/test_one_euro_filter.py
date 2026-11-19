"""
Unit tests for One Euro Filter (1€ Filter) and TargetSmoother integration.
"""
import math
import unittest

from src.aim_system.target_smoother import OneEuroFilter1D, TargetSmoother


class TestOneEuroFilter1D(unittest.TestCase):
    def test_constant_signal_converges_immediately(self):
        f = OneEuroFilter1D(min_cutoff=1.0, beta=0.05, d_cutoff=1.0)
        t = 0.0
        val = 100.0
        out1 = f.filter(t, val)
        self.assertAlmostEqual(out1, 100.0)

        for i in range(1, 20):
            t += 1.0 / 144.0
            out = f.filter(t, val)
            self.assertAlmostEqual(out, 100.0, places=4)

    def test_jitter_suppression_at_rest(self):
        """At rest with +/- 1.5px jitter, the filter should heavily attenuate high frequency noise."""
        f = OneEuroFilter1D(min_cutoff=1.0, beta=0.005, d_cutoff=1.0)
        t = 0.0
        base = 200.0
        f.filter(t, base)

        filtered_vals = []
        for i in range(1, 50):
            t += 1.0 / 144.0
            noisy = base + (1.5 if i % 2 == 0 else -1.5)
            filtered_vals.append(f.filter(t, noisy))

        # The filtered oscillation amplitude should be much smaller than raw +/- 1.5
        max_dev = max(abs(v - base) for v in filtered_vals[10:])
        self.assertLess(max_dev, 0.65, f"Jitter was not suppressed: max_dev={max_dev}")

    def test_rapid_motion_increases_cutoff_and_reduces_lag(self):
        """During fast flicks (high velocity), adaptive cutoff should follow quickly."""
        f_euro = OneEuroFilter1D(min_cutoff=1.0, beta=0.1, d_cutoff=1.0)
        t = 0.0
        f_euro.filter(t, 0.0)

        # Fast ramp: moving 500 px/s
        vals = []
        for i in range(1, 30):
            t += 1.0 / 144.0
            curr = 500.0 * t
            vals.append((curr, f_euro.filter(t, curr)))

        # In steady fast ramp, lag should be small (within a few pixels at 144Hz)
        raw_last, filtered_last = vals[-1]
        lag = abs(raw_last - filtered_last)
        self.assertLess(lag, 5.0, f"Euro filter lag too large during fast movement: {lag}")

    def test_reset_clears_state(self):
        f = OneEuroFilter1D()
        f.filter(0.0, 100.0)
        f.reset()
        self.assertIsNone(f.x_prev)
        self.assertIsNone(f.t_prev)
        self.assertEqual(f.dx_prev, 0.0)


class TestTargetSmootherEuroIntegration(unittest.TestCase):
    def test_smoother_one_euro_mode_returns_expected_signature(self):
        clock = [10.0]
        smoother = TargetSmoother(use_one_euro=True, min_cutoff=1.0, beta=0.05,
                                  clock=lambda: clock[0])
        res = smoother.stabilize([(100.0, 120.0, 25.0, 110.0, 150.0)], 200.0, 200.0)
        self.assertEqual(len(res), 1)
        sx, sy, dist, h_min, b_max = res[0]
        self.assertAlmostEqual(sx, 100.0)
        self.assertAlmostEqual(sy, 120.0)
        self.assertAlmostEqual(h_min, 110.0)
        self.assertAlmostEqual(b_max, 150.0)

    def test_smoother_one_euro_smooths_subsequent_frames(self):
        clock = [10.0]
        smoother = TargetSmoother(use_one_euro=True, min_cutoff=1.0, beta=0.05,
                                  clock=lambda: clock[0])
        smoother.stabilize([(100.0, 100.0, 10.0)], 200.0, 200.0)
        clock[0] += 1.0 / 144.0
        res = smoother.stabilize([(104.0, 104.0, 10.0)], 200.0, 200.0)
        sx, sy, _, _, _ = res[0]
        self.assertGreater(sx, 100.0)
        self.assertLess(sx, 104.0)

    def test_smoother_one_euro_dropout_resets_cleanly(self):
        clock = [10.0]
        smoother = TargetSmoother(use_one_euro=True, reacquire_gap_s=0.05,
                                  clock=lambda: clock[0])
        smoother.stabilize([(100.0, 100.0, 10.0)], 200.0, 200.0)
        # Big gap (target dropout)
        clock[0] += 0.20
        # Reacquire at far position
        res = smoother.stabilize([(300.0, 300.0, 10.0)], 200.0, 200.0)
        sx, sy, _, _, _ = res[0]
        self.assertAlmostEqual(sx, 300.0)
        self.assertAlmostEqual(sy, 300.0)


if __name__ == "__main__":
    unittest.main()
