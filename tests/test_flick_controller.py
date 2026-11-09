"""Convergence tests for the closed-loop Flick controller (plan section 8.2)."""

import math
import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aim_system.aim_math import Calibration, geometry_from_native  # noqa: E402
from src.aim_system.flick_controller import (  # noqa: E402
    FlickController,
    quantize_with_residual,
    scale_vector_to_limit,
)

GEOM = geometry_from_native(native_w=1920, native_h=1080, hfov_deg=103.0)
#: 285 counts/deg == the analytic scale at sens 0.23 / dpi 1100.
CALIB = Calibration(counts_per_deg_x=285.0, counts_per_deg_y=285.0)


class FakeClock:
    def __init__(self, start=1000.0):
        self.now = float(start)

    def __call__(self):
        return self.now

    def advance_ms(self, ms):
        self.now += float(ms) / 1000.0


def counts_to_px(counts_x, counts_y):
    """Inverse of the controller's conversion (how the screen would move)."""
    deg_x, deg_y = CALIB.counts_to_deg(counts_x, counts_y)
    return GEOM.deg_to_px(deg_x, deg_y)


class SimHarness:
    """Simulates a stationary target with a perfect (noiseless) screen."""

    def __init__(self, controller, start_x, start_y):
        self.controller = controller
        self.error = [float(start_x), float(start_y)]
        self.steps = []
        self.target_moves = 0.0

    def run(self, frames=8):
        for _ in range(frames):
            step = self.controller.step(
                self.error[0], self.error[1], geometry=GEOM, calibration=CALIB, target_key="t1"
            )
            if step.move:
                self.steps.append(step.counts)
                px = counts_to_px(*step.counts)
                self.error[0] -= px[0]
                self.error[1] -= px[1]
                self.target_moves += math.hypot(*step.counts) / 285.0
            if self.controller.state.released_reason:
                break
        return self.error


class TestVectorHelpers(unittest.TestCase):
    def test_scale_preserves_direction(self):
        dx, dy = scale_vector_to_limit(3000.0, 4000.0, 1000.0)
        self.assertAlmostEqual(math.hypot(dx, dy), 1000.0, places=6)
        self.assertAlmostEqual(dy / dx, 4000.0 / 3000.0, places=9)

    def test_scale_noop_below_limit(self):
        self.assertEqual(scale_vector_to_limit(10.0, -5.0, 1000.0), (10.0, -5.0))

    def test_scale_does_not_truncate_one_axis(self):
        # Per-axis clipping would give (1000, 1000) -> 45 degrees. Scaling must not.
        dx, dy = scale_vector_to_limit(10000.0, 100.0, 1000.0)
        self.assertAlmostEqual(dx, 1000.0, delta=0.1)
        self.assertLess(abs(dy), 10.0)

    def test_quantize_carries_residual(self):
        out_x, out_y, residual = quantize_with_residual(0.4, -0.6, (0.0, 0.0))
        self.assertEqual((out_x, out_y), (0.0, -1.0))
        self.assertAlmostEqual(residual[0], 0.4, places=9)
        self.assertAlmostEqual(residual[1], 0.4, places=9)


class TestFlickConvergence(unittest.TestCase):
    DISTANCES = (5.0, 15.0, 30.0, 60.0, 120.0)

    def _controller(self, clock=None, **kwargs):
        params = dict(
            geometry=GEOM,
            calibration=CALIB,
            gain=1.0,
            max_counts=6000.0,
            max_iterations=4,
            budget_ms=120.0,
            deadzone_px=0.5,
        )
        params.update(kwargs)
        if clock is not None:
            params["clock"] = clock
        return FlickController(**params)

    def test_converges_inside_deadzone_for_all_distances(self):
        for d in self.DISTANCES:
            with self.subTest(distance=d):
                controller = self._controller(deadzone_px=1.5)
                harness = SimHarness(controller, d, 0.0)
                error = harness.run(frames=8)
                self.assertLessEqual(
                    math.hypot(*error), 1.5 + 0.5,
                    f"did not converge at d={d}: residual={error}",
                )

    def test_overshoot_is_at_most_10_percent(self):
        """This is the regression test for the old strength + clamp overshoot."""
        for d in self.DISTANCES:
            with self.subTest(distance=d):
                controller = self._controller(deadzone_px=0.0, max_iterations=4)
                harness = SimHarness(controller, d, 0.0)
                error = harness.run(frames=1)
                # After the FIRST impulse the error must not flip sign past 10%.
                traveled = d - error[0]
                self.assertLessEqual(
                    traveled, d * 1.10 + 0.5,
                    f"overshoot at d={d}: traveled={traveled}",
                )
                self.assertGreater(traveled, 0.0, f"no movement at d={d}")

    def test_no_step_exceeds_max_counts(self):
        controller = self._controller(max_counts=250.0, deadzone_px=0.0)
        harness = SimHarness(controller, 500.0, 0.0)
        harness.run(frames=4)
        for counts in harness.steps:
            # +1 count of slack: integer rounding happens after the vector scale.
            self.assertLessEqual(math.hypot(*counts), 251.0)

    def test_clamped_vector_keeps_direction(self):
        controller = self._controller(max_counts=100.0, deadzone_px=0.0)
        step = controller.step(400.0, 300.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        self.assertTrue(step.move)
        self.assertTrue(step.clamped)
        # Integer quantisation moves the ratio by at most ~1/100 at this size.
        self.assertAlmostEqual(step.counts[1] / step.counts[0], 300.0 / 400.0, delta=0.03)

    def test_residual_accumulates_to_theoretical_total(self):
        """Sum of emitted steps tracks the analytic counts within one count."""
        controller = self._controller(deadzone_px=0.0, max_counts=1e9, max_iterations=50)
        total_x = 0.0
        frames = 40
        for _ in range(frames):
            step = controller.step(
                1.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1"
            )
            if step.move:
                total_x += step.counts[0]
        theoretical, _ = CALIB.px_to_counts(GEOM, 1.0, 0.0)
        # 1.0 px is ~0.075 deg -> ~21.4 counts per frame.
        self.assertAlmostEqual(theoretical, 21.4, delta=0.2)
        self.assertLessEqual(abs(total_x - theoretical * frames), 1.0)

    def test_single_sub_count_request_is_not_lost(self):
        # 0.01 px is ~0.21 counts: below half a count, so nothing is sent yet.
        controller = self._controller(deadzone_px=0.0, max_iterations=50)
        step = controller.step(
            0.01, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1"
        )
        self.assertFalse(step.move)
        self.assertGreater(step.residual[0], 0.0)  # carried, not dropped
        # Repeated sub-count errors must eventually produce a real step.
        sent = False
        for _ in range(200):
            step = controller.step(
                0.01, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1"
            )
            if step.move:
                sent = True
                break
        self.assertTrue(sent, "residual was swallowed instead of accumulating")


class TestFlickBudget(unittest.TestCase):
    def test_budget_exhaustion_releases_instead_of_blocking(self):
        clock = FakeClock()
        controller = FlickController(
            geometry=GEOM,
            calibration=CALIB,
            max_counts=6000.0,
            max_iterations=10,
            budget_ms=50.0,
            deadzone_px=0.0,
            clock=clock,
        )
        first = controller.step(30.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        self.assertTrue(first.move)
        clock.advance_ms(80.0)
        second = controller.step(30.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        self.assertFalse(second.move)
        self.assertEqual(second.reason, "budget_expired")
        self.assertFalse(controller.armed)
        # Crucially: the NEXT frame is free to start a new flick (no blind cooldown).
        third = controller.step(30.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        self.assertTrue(third.move)
        self.assertTrue(controller.armed)

    def test_max_iterations_releases_and_rearms(self):
        controller = FlickController(
            geometry=GEOM,
            calibration=CALIB,
            max_counts=1.0,
            max_iterations=2,
            budget_ms=100000.0,
            deadzone_px=0.0,
        )
        moves = 0
        releases = 0
        for _ in range(9):
            step = controller.step(
                100.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1"
            )
            if step.move:
                moves += 1
            if step.reason == "max_iterations":
                releases += 1
        self.assertEqual(moves, 2 * releases)
        self.assertGreater(releases, 0)

    def test_no_permanent_lockout(self):
        controller = FlickController(
            geometry=GEOM,
            calibration=CALIB,
            max_counts=1.0,
            max_iterations=1,
            budget_ms=1.0,
            deadzone_px=0.0,
        )
        moved = 0
        releases = 0
        for _ in range(10):
            step = controller.step(
                100.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1"
            )
            if step.move:
                moved += 1
            if step.reason in ("max_iterations", "budget_expired"):
                releases += 1
        # One impulse per release: no frame is ever permanently discarded.
        self.assertEqual(moved, releases)
        self.assertGreaterEqual(moved, 4, "controller got stuck in a cooldown")


class TestFlickTargetSwitch(unittest.TestCase):
    def test_target_change_resets_residual(self):
        controller = FlickController(
            geometry=GEOM,
            calibration=CALIB,
            max_counts=6000.0,
            max_iterations=10,
            budget_ms=100000.0,
            deadzone_px=0.0,
        )
        controller.step(3.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="a")
        self.assertNotEqual(controller.state.residual, (0.0, 0.0))
        controller.step(3.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="b")
        self.assertEqual(controller.state.iterations, 1)
        self.assertEqual(controller.state.target_key, "b")

    def test_target_change_clears_iteration_budget(self):
        controller = FlickController(
            geometry=GEOM,
            calibration=CALIB,
            max_counts=1.0,
            max_iterations=3,
            budget_ms=100000.0,
            deadzone_px=0.0,
        )
        for _ in range(3):
            controller.step(100.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="a")
        self.assertEqual(controller.state.iterations, 3)
        step = controller.step(100.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="b")
        # A new target must get a full budget, not inherit the spent one.
        self.assertTrue(step.move)
        self.assertEqual(controller.state.iterations, 1)

    def test_small_target_drift_is_not_a_switch(self):
        """Regression: the target key is a POSITION and drifts as we converge.

        Comparing it for exact equality reset the residual and the iteration
        budget on nearly every frame, which disabled both the budget and the
        sub-count carry in production.
        """
        controller = FlickController(
            geometry=GEOM,
            calibration=CALIB,
            max_counts=1.0,
            max_iterations=5,
            budget_ms=100000.0,
            deadzone_px=0.0,
        )
        for step_px in range(5):
            controller.step(
                100.0, 0.0, geometry=GEOM, calibration=CALIB, target_key=(960.0 + step_px, 540.0)
            )
        # Five 1-px drifts must accumulate five iterations, not restart each frame.
        self.assertEqual(controller.state.iterations, 5)
        self.assertEqual(controller.state.released_reason, "")

    def test_gross_target_jump_is_a_switch(self):
        controller = FlickController(
            geometry=GEOM,
            calibration=CALIB,
            max_counts=1.0,
            max_iterations=5,
            budget_ms=100000.0,
            deadzone_px=0.0,
            switch_radius_px=64.0,
        )
        controller.step(100.0, 0.0, geometry=GEOM, calibration=CALIB, target_key=(900.0, 500.0))
        controller.step(100.0, 0.0, geometry=GEOM, calibration=CALIB, target_key=(1500.0, 500.0))
        self.assertEqual(controller.state.iterations, 1)

    def test_residual_survives_target_jitter(self):
        controller = FlickController(
            geometry=GEOM,
            calibration=CALIB,
            max_counts=1e9,
            max_iterations=50,
            budget_ms=100000.0,
            deadzone_px=0.0,
        )
        controller.step(0.01, 0.0, geometry=GEOM, calibration=CALIB, target_key=(100.0, 100.0))
        first_residual = controller.state.residual[0]
        self.assertGreater(first_residual, 0.0)
        controller.step(0.01, 0.0, geometry=GEOM, calibration=CALIB, target_key=(101.0, 100.0))
        # Drift of 1 px must not zero the carried sub-count remainder.
        self.assertGreater(controller.state.residual[0], first_residual)


class TestFlickDeadzoneAndGain(unittest.TestCase):
    def test_deadzone_disarms(self):
        controller = FlickController(
            geometry=GEOM, calibration=CALIB, deadzone_px=2.0, max_iterations=4
        )
        step = controller.step(1.0, 1.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        self.assertFalse(step.move)
        self.assertEqual(step.reason, "deadzone")
        self.assertFalse(controller.armed)

    def test_gain_scales_the_impulse(self):
        half = FlickController(
            geometry=GEOM, calibration=CALIB, gain=0.5, max_counts=1e9, deadzone_px=0.0
        )
        full = FlickController(
            geometry=GEOM, calibration=CALIB, gain=1.0, max_counts=1e9, deadzone_px=0.0
        )
        s_half = half.step(30.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        s_full = full.step(30.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        self.assertAlmostEqual(s_half.counts[0], s_full.counts[0] / 2.0, delta=1.0)

    def test_gain_one_is_exact_counts(self):
        controller = FlickController(
            geometry=GEOM, calibration=CALIB, gain=1.0, max_counts=1e9, deadzone_px=0.0
        )
        step = controller.step(30.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        expected, _ = CALIB.px_to_counts(GEOM, 30.0, 0.0)
        self.assertAlmostEqual(step.counts[0], expected, delta=0.5)
        self.assertFalse(step.clamped)

    def test_reset_clears_armed_state(self):
        controller = FlickController(
            geometry=GEOM, calibration=CALIB, deadzone_px=0.0, max_counts=1e9
        )
        controller.step(30.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        self.assertTrue(controller.armed)
        controller.reset()
        self.assertFalse(controller.armed)
        self.assertEqual(controller.state.iterations, 0)


class TestFromConfig(unittest.TestCase):
    def test_reads_new_keys(self):
        cfg = {
            "flick_gain": 1.25,
            "flick_max_counts": 4321.0,
            "flick_max_iterations": 3,
            "flick_budget_ms": 90.0,
            "flick_deadzone_px": 2.5,
            "in_game_sens": 0.23,
            "mouse_dpi": 1100,
            "sfov": 1.0,
        }
        controller = FlickController.from_config(
            cfg=cfg, geometry=GEOM, tracker={"in_game_sens": 0.23, "mouse_dpi": 1100}
        )
        self.assertAlmostEqual(controller.gain, 1.25)
        self.assertAlmostEqual(controller.max_counts, 4321.0)
        self.assertEqual(controller.max_iterations, 3)
        self.assertAlmostEqual(controller.budget_ms, 90.0)
        self.assertAlmostEqual(controller.deadzone_px, 2.5)

    def test_sec_suffix_is_preferred(self):
        cfg = {
            "flick_gain": 1.0,
            "flick_gain_sec": 1.4,
            "flick_max_counts": 6000.0,
            "flick_max_counts_sec": 2500.0,
            "in_game_sens": 0.23,
            "mouse_dpi": 1100,
        }
        controller = FlickController.from_config(
            is_sec=True, cfg=cfg, geometry=GEOM,
            tracker={"in_game_sens": 0.23, "mouse_dpi": 1100},
        )
        self.assertAlmostEqual(controller.gain, 1.4)
        self.assertAlmostEqual(controller.max_counts, 2500.0)

    def test_missing_geometry_is_handled(self):
        controller = FlickController(geometry=None, calibration=None)
        step = controller.step(30.0, 0.0)
        self.assertFalse(step.move)
        self.assertEqual(step.reason, "no_geometry")


class TestFlickDeliveryFailure(unittest.TestCase):
    """A rejected impulse must not burn the convergence budget."""

    def test_rollback_restores_iteration_and_residual(self):
        controller = FlickController(
            geometry=GEOM,
            calibration=CALIB,
            max_counts=1e9,
            max_iterations=4,
            budget_ms=100000.0,
            deadzone_px=0.0,
        )
        controller.step(30.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        iterations_before = controller.state.iterations
        residual_before = controller.state.residual
        controller.step(30.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        controller.rollback_step()
        self.assertEqual(controller.state.iterations, iterations_before)
        self.assertEqual(controller.state.residual, residual_before)

    def test_rollback_does_not_go_negative(self):
        controller = FlickController(
            geometry=GEOM, calibration=CALIB, deadzone_px=0.0, max_counts=1e9
        )
        controller.rollback_step()
        self.assertEqual(controller.state.iterations, 0)
        self.assertEqual(controller.state.t0, 0.0)


class TestRollbackRestoresTiming(unittest.TestCase):
    """C3: the old rollback only restored iterations and residual.

    A rejected impulse still set ``_last_step_time`` (so the next frame sat in
    the settle window for a step that never happened), incremented
    ``total_sent``/``last_sent`` (diagnostics claimed travel that never occurred)
    and bumped ``clamped_steps``.
    """

    def _controller(self, clock=None, settle_ms=0.0):
        kwargs = dict(
            geometry=GEOM,
            calibration=CALIB,
            max_counts=1e9,
            max_iterations=6,
            budget_ms=100000.0,
            deadzone_px=0.0,
            settle_ms=settle_ms,
        )
        if clock is not None:
            kwargs["clock"] = clock
        return FlickController(**kwargs)

    def test_snapshot_is_taken_before_mutation(self):
        controller = self._controller()
        controller.step(30.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        self.assertIsNotNone(controller._pre_step_snapshot)

    def test_rollback_restores_last_step_time(self):
        clock = FakeClock()
        controller = self._controller(clock=clock, settle_ms=70.0)
        controller.step(30.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        self.assertGreater(controller._last_step_time, 0.0)
        controller.rollback_step()
        self.assertEqual(controller._last_step_time, 0.0)

    def test_rollback_restores_total_and_last_sent(self):
        controller = self._controller()
        controller.step(30.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        controller.rollback_step()
        self.assertEqual(controller.state.total_sent, (0.0, 0.0))
        self.assertEqual(controller.state.last_sent, (0.0, 0.0))

    def test_rollback_restores_clamped_counter(self):
        controller = FlickController(
            geometry=GEOM,
            calibration=CALIB,
            max_counts=10.0,
            max_iterations=6,
            budget_ms=100000.0,
            deadzone_px=0.0,
        )
        controller.step(300.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        self.assertEqual(controller.state.clamped_steps, 1)
        controller.rollback_step()
        self.assertEqual(controller.state.clamped_steps, 0)

    def test_retry_after_rollback_is_not_blocked_by_settle(self):
        """The frame after a rejected impulse must be able to retry immediately."""
        clock = FakeClock()
        controller = self._controller(clock=clock, settle_ms=70.0)
        first = controller.step(30.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        self.assertTrue(first.move)
        controller.rollback_step()
        clock.advance_ms(1.0)  # much less than the 70 ms settle
        retry = controller.step(30.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        self.assertTrue(retry.move, "rollback left the controller stuck in 'settling'")
        self.assertNotEqual(retry.reason, "settling")

    def test_rollback_twice_does_not_double_count(self):
        controller = self._controller()
        controller.step(30.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        controller.rollback_step()
        controller.rollback_step()
        self.assertEqual(controller.state.iterations, 0)
        self.assertEqual(controller.state.total_sent, (0.0, 0.0))


class TestSettleAndBudget(unittest.TestCase):
    def test_effective_steps_matches_plan_formula(self):
        from src.aim_system.flick_controller import effective_steps

        # settle 70 / budget 120 -> floor(1.71)+1 = 2
        self.assertEqual(effective_steps(4, 120.0, 70.0), 2)
        # fresh default: budget 240 -> floor(3.43)+1 = 4
        self.assertEqual(effective_steps(4, 240.0, 70.0), 4)
        # settle 0 -> every iteration is reachable
        self.assertEqual(effective_steps(4, 120.0, 0.0), 4)
        # budget too small for even two steps
        self.assertEqual(effective_steps(4, 40.0, 120.0), 1)
        # never exceeds max_iterations
        self.assertEqual(effective_steps(2, 1000.0, 10.0), 2)

    def test_controller_reports_effective_steps(self):
        controller = FlickController(
            geometry=GEOM,
            calibration=CALIB,
            max_iterations=4,
            budget_ms=120.0,
            settle_ms=70.0,
        )
        self.assertEqual(controller.effective_steps, 2)
        self.assertTrue(controller.budget_advice())

    def test_budget_advice_empty_when_consistent(self):
        controller = FlickController(
            geometry=GEOM,
            calibration=CALIB,
            max_iterations=4,
            budget_ms=240.0,
            settle_ms=70.0,
        )
        self.assertEqual(controller.budget_advice(), "")

    def test_settle_blocks_second_step(self):
        clock = FakeClock()
        controller = FlickController(
            geometry=GEOM,
            calibration=CALIB,
            max_counts=1e9,
            max_iterations=6,
            budget_ms=100000.0,
            deadzone_px=0.0,
            settle_ms=70.0,
            clock=clock,
        )
        first = controller.step(200.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        self.assertTrue(first.move)
        clock.advance_ms(10.0)
        blocked = controller.step(200.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        self.assertFalse(blocked.move)
        self.assertEqual(blocked.reason, "settling")
        clock.advance_ms(70.0)
        allowed = controller.step(200.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        self.assertTrue(allowed.move)

    def test_suggested_budget_funds_all_iterations(self):
        controller = FlickController(
            geometry=GEOM,
            calibration=CALIB,
            max_iterations=4,
            budget_ms=120.0,
            settle_ms=70.0,
        )
        suggestion = controller.suggested_budget_ms()
        self.assertGreaterEqual(
            __import__(
                "src.aim_system.flick_controller", fromlist=["effective_steps"]
            ).effective_steps(4, suggestion, 70.0),
            4,
        )


class TestSwitchRadius(unittest.TestCase):
    def test_switch_radius_default_is_64(self):
        controller = FlickController(geometry=GEOM, calibration=CALIB)
        self.assertAlmostEqual(controller.switch_radius_px, 64.0)

    def test_configure_updates_switch_radius(self):
        controller = FlickController(geometry=GEOM, calibration=CALIB)
        controller.configure(switch_radius_px=128.0)
        self.assertAlmostEqual(controller.switch_radius_px, 128.0)

    def test_larger_radius_suppresses_switch(self):
        controller = FlickController(
            geometry=GEOM,
            calibration=CALIB,
            max_counts=1.0,
            max_iterations=5,
            budget_ms=100000.0,
            deadzone_px=0.0,
            switch_radius_px=200.0,
        )
        controller.step(100.0, 0.0, geometry=GEOM, calibration=CALIB, target_key=(900.0, 500.0))
        controller.step(100.0, 0.0, geometry=GEOM, calibration=CALIB, target_key=(1000.0, 500.0))
        # 100 px apart, radius 200 -> still the same target, two iterations.
        self.assertEqual(controller.state.iterations, 2)

    def test_configure_reads_settle_from_config(self):
        cfg = {"flick_settle_ms": 125.0, "flick_switch_radius_px": 90}
        controller = FlickController.from_config(cfg=cfg, geometry=GEOM)
        self.assertAlmostEqual(controller.settle_ms, 125.0)
        self.assertAlmostEqual(controller.switch_radius_px, 90.0)

    def test_configure_settle_takes_effect_immediately(self):
        clock = FakeClock()
        controller = FlickController(
            geometry=GEOM,
            calibration=CALIB,
            max_counts=1e9,
            max_iterations=6,
            budget_ms=100000.0,
            deadzone_px=0.0,
            settle_ms=0.0,
            clock=clock,
        )
        controller.step(200.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        controller.configure(settle_ms=80.0)
        clock.advance_ms(10.0)
        step = controller.step(200.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        self.assertEqual(step.reason, "settling")


class TestStatusPublishing(unittest.TestCase):
    def test_status_has_diagnostics_fields(self):
        controller = FlickController(
            geometry=GEOM, calibration=CALIB, deadzone_px=0.0, max_counts=1e9
        )
        controller.step(30.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        status = controller.status()
        for key in (
            "reason",
            "iterations",
            "effective_steps",
            "counts",
            "residual",
            "calibration",
            "geometry",
            "gain",
            "clamped",
            "armed",
        ):
            self.assertIn(key, status)
        self.assertEqual(status["calibration"], "measured")
        self.assertEqual(status["geometry"], "analytic")
        self.assertTrue(status["armed"])

    def test_status_reports_valorant_source(self):
        from src.aim_system.aim_math import Calibration as Cal

        cal = Cal(source="valorant", sens=0.23)
        controller = FlickController(geometry=GEOM, calibration=cal)
        self.assertEqual(controller.status()["calibration"], "valorant")


class TestFromConfigExtended(unittest.TestCase):
    def test_settle_and_switch_are_read(self):
        cfg = {
            "flick_settle_ms": 90.0,
            "flick_switch_radius_px": 100,
            "flick_gain": 1.0,
            "flick_budget_ms": 240.0,
        }
        controller = FlickController.from_config(cfg=cfg, geometry=GEOM)
        self.assertAlmostEqual(controller.settle_ms, 90.0)
        self.assertEqual(controller.switch_radius_px, 100.0)

    def test_sec_variants_are_preferred(self):
        cfg = {
            "flick_settle_ms": 70.0,
            "flick_settle_ms_sec": 120.0,
            "flick_switch_radius_px": 64,
            "flick_switch_radius_px_sec": 128,
        }
        controller = FlickController.from_config(is_sec=True, cfg=cfg, geometry=GEOM)
        self.assertAlmostEqual(controller.settle_ms, 120.0)
        self.assertEqual(controller.switch_radius_px, 128.0)


class TestFlickTuning(unittest.TestCase):
    def test_snapshot_signature_changes_with_config(self):
        from src.aim_system.tuning import snapshot_flick_tuning

        first = snapshot_flick_tuning(cfg={"flick_settle_ms": 70.0})
        second = snapshot_flick_tuning(cfg={"flick_settle_ms": 90.0})
        self.assertNotEqual(first.signature(), second.signature())

    def test_snapshot_is_stable_for_same_config(self):
        from src.aim_system.tuning import snapshot_flick_tuning

        cfg = {"flick_settle_ms": 70.0, "flick_budget_ms": 240.0}
        self.assertEqual(
            snapshot_flick_tuning(cfg=cfg).signature(),
            snapshot_flick_tuning(cfg=cfg).signature(),
        )

    def test_snapshot_maps_to_controller_kwargs(self):
        from src.aim_system.tuning import snapshot_flick_tuning

        tuning = snapshot_flick_tuning(cfg={"flick_settle_ms": 80.0, "flick_switch_radius_px": 96})
        kwargs = tuning.for_controller()
        self.assertEqual(kwargs["settle_ms"], 80.0)
        self.assertEqual(kwargs["switch_radius_px"], 96.0)

    def test_sec_channel_uses_sec_keys(self):
        from src.aim_system.tuning import snapshot_flick_tuning

        cfg = {"flick_gain": 1.0, "flick_gain_sec": 1.8}
        self.assertAlmostEqual(snapshot_flick_tuning(cfg=cfg, is_sec=True).gain, 1.8)
        self.assertAlmostEqual(snapshot_flick_tuning(cfg=cfg, is_sec=False).gain, 1.0)

    def test_tuning_effective_steps(self):
        from src.aim_system.tuning import snapshot_flick_tuning

        tuning = snapshot_flick_tuning(
            cfg={"flick_max_iterations": 4, "flick_budget_ms": 120.0, "flick_settle_ms": 70.0}
        )
        self.assertEqual(tuning.effective_steps, 2)


class TestNoLegacyOvershoot(unittest.TestCase):
    """The three mechanisms that made the old flick diverge must be gone."""

    def test_30px_flick_does_not_require_the_ghost_1000_clamp(self):
        controller = FlickController(
            geometry=GEOM, calibration=CALIB, gain=1.0, max_counts=6000.0, deadzone_px=0.0
        )
        step = controller.step(30.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        self.assertFalse(step.clamped)
        self.assertLess(math.hypot(*step.counts), 1000.0)

    def test_old_strength_would_have_overshot(self):
        """Documents the historical 1.8x + clamp(1000) failure for contrast."""
        counts, _ = CALIB.px_to_counts(GEOM, 30.0, 0.0)
        legacy = min(counts * 1.8, 1000.0)
        self.assertGreater(legacy / counts, 1.5)
        controller = FlickController(
            geometry=GEOM, calibration=CALIB, gain=1.0, max_counts=6000.0, deadzone_px=0.0
        )
        step = controller.step(30.0, 0.0, geometry=GEOM, calibration=CALIB, target_key="t1")
        self.assertLess(abs(step.counts[0] / counts - 1.0), 0.05)

    def test_legacy_values_from_the_plan_would_fail_this_suite(self):
        """Quantifies the starting defect: strength 1.8 clipped to 1000 counts."""
        counts, _ = CALIB.px_to_counts(GEOM, 30.0, 0.0)  # ~642 counts
        self.assertAlmostEqual(counts, 641.9, delta=1.0)
        legacy_impulse = min(counts * 1.8, 1000.0)
        # ~1.56x overshoot: the crosshair lands ~47 px past a 30 px aim error,
        # i.e. outside the 30 px FOV, so no later frame can correct it.
        self.assertAlmostEqual(legacy_impulse / counts, 1.558, delta=0.01)
        overshoot_px = (legacy_impulse / counts - 1.0) * 30.0
        self.assertAlmostEqual(overshoot_px, 16.7, delta=0.5)
        self.assertGreater(overshoot_px, 16.0)


if __name__ == "__main__":
    unittest.main()
