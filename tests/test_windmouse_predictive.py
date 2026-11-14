import os
import sys
import time
import unittest

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.aim_system.windmouse_smooth import SmoothAiming


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
        self.smooth_max_step_ratio = 0.15
        self.smooth_target_area_ratio = 0.05
        self.smooth_acceleration = 0.8
        self.smooth_deceleration = 0.6


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


# =====================================================
# 144 Hz profile / frame-budget regression tests
# =====================================================

from types import SimpleNamespace

from src.aim_system import normal as normal_mod
from src.aim_system.target_smoother import TargetSmoother
from src.utils.config import Config, config as live_config

PROFILE_PATH = os.path.join(PROJECT_ROOT, "configs", "udp_144hz_fast_cvm.json")
DEFAULT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")

# The 23 tuned keys of the 144 Hz profile (plan section 3.5 + the two per-aimbot
# Sec reaction keys that used to be written by the UI into names Config did not
# declare, so they were dropped by `from_dict`).
PROFILE_KEYS = (
    "wm_gravity",
    "wm_wind",
    "wm_max_step",
    "wm_min_step",
    "wm_min_delay",
    "wm_max_delay",
    "wm_distance_threshold",
    "smooth_reaction_min",
    "smooth_reaction_max",
    "smooth_close_range",
    "smooth_close_speed",
    "smooth_far_range",
    "smooth_far_speed",
    "smooth_max_step_ratio",
    "smooth_target_area_ratio",
    "smooth_acceleration",
    "smooth_deceleration",
    "smooth_reaction_min_sec",
    "smooth_reaction_max_sec",
    "wm_frame_gain",
    "wm_frame_max_step_px",
    "wm_settle_radius_px",
    "wm_deadzone_px",
)

# Keys that only landed in Config as part of this change.
NEW_CONFIG_KEYS = (
    "smooth_reaction_min",
    "smooth_reaction_max",
    "smooth_close_range",
    "smooth_close_speed",
    "smooth_far_range",
    "smooth_far_speed",
    "smooth_max_step_ratio",
    "smooth_target_area_ratio",
    "smooth_acceleration",
    "smooth_deceleration",
    "smooth_reaction_min_sec",
    "smooth_reaction_max_sec",
    "wm_frame_gain",
    "wm_frame_max_step_px",
    "wm_settle_radius_px",
    "wm_deadzone_px",
)

FRAME_DT = 1.0 / 144.0


def _load_json(path):
    import json

    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_profile():
    return _load_json(PROFILE_PATH)


def _profile_namespace(data=None):
    """SimpleNamespace of the profile, with the cosmetic `_comment` removed."""
    data = _load_profile() if data is None else data
    return SimpleNamespace(**{k: v for k, v in data.items() if k != "_comment"})


class FakeClock:
    """Deterministic replacement for `windmouse_smooth.time`."""

    def __init__(self, start=1_000.0, dt=FRAME_DT):
        self.now = float(start)
        self.dt = float(dt)

    def time(self):
        return self.now

    def advance(self, dt=None):
        self.now += self.dt if dt is None else float(dt)
        return self.now

    def reset(self, start=1_000.0):
        self.now = float(start)


class MockTracker:
    """Minimal AimTracker stand-in: move queue + the fields WindMouse reads."""

    def __init__(self, max_speed=1000.0):
        import queue

        self.move_queue = queue.Queue(maxsize=50)
        self.max_speed = float(max_speed)
        self.in_game_sens = 0.235
        self.mouse_dpi = 1100
        self.normal_x_speed = 100
        self.normal_y_speed = 70
        self.normal_x_speed_sec = 2
        self.normal_y_speed_sec = 2

    def _clip_movement(self, dx, dy):
        return dx, dy

    def drain(self):
        moves = []
        while True:
            try:
                dx, dy, _ = self.move_queue.get_nowait()
            except Exception:
                break
            moves.append((dx, dy))
        return moves


class WindMouseProfileCase(unittest.TestCase):
    """Shared 144 Hz closed-loop simulation helpers."""

    def setUp(self):
        import src.aim_system.windmouse_smooth as wm_module

        self._wm_module = wm_module
        self._real_time = wm_module.time
        self.clock = FakeClock()
        wm_module.time = self.clock

        self._saved_config = {}
        self.profile = _load_profile()
        self.profile_ns = _profile_namespace(self.profile)
        for key in PROFILE_KEYS:
            self._saved_config[key] = getattr(live_config, key, None)
            setattr(live_config, key, self.profile[key])

        # Deterministic path generation: swap the module singleton's rng.
        import random as _random

        self._saved_rng = wm_module.smooth_aimer.rng
        self._saved_wm_rng = wm_module.smooth_aimer.windmouse.rng
        rng = _random.Random(1234)
        wm_module.smooth_aimer.rng = rng
        wm_module.smooth_aimer.windmouse.rng = rng
        wm_module.smooth_aimer.reset_tracking_state()

    def tearDown(self):
        self._wm_module.time = self._real_time
        self._wm_module.smooth_aimer.rng = self._saved_rng
        self._wm_module.smooth_aimer.windmouse.rng = self._saved_wm_rng
        self._wm_module.smooth_aimer.reset_tracking_state()
        for key, value in self._saved_config.items():
            setattr(live_config, key, value)

    # -- helpers -----------------------------------------------------
    def counts_per_pixel(self):
        ndx, ndy = normal_mod.calculate_movement(1.0, 1.0, 0.235, 1100)
        return ndx * 100, ndy * 70

    def run_frames(self, tracker, err_x, err_y, frames, target_velocity=(0.0, 0.0), reset_clock=True):
        """Closed loop: aim at the current error, apply the emitted move, restock.

        One iteration == one 144 Hz frame. `target_velocity` is the target's
        own screen velocity in px/s; it grows the error between frames, which
        is what produces the steady-state lag in the strafe test.

        Returns a list of ((err_x, err_y) before the frame, emitted move).
        """
        if reset_clock:
            self.clock.reset()
            self._wm_module.smooth_aimer.reset_tracking_state()
        records = []
        ex, ey = float(err_x), float(err_y)
        cpp_x, cpp_y = self.counts_per_pixel()
        for _ in range(frames):
            self.clock.advance()
            before = (ex, ey)
            normal_mod._apply_windmouse_aim(ex, ey, tracker, is_sec=False)
            moves = tracker.drain()
            move = moves[-1] if moves else (0, 0)
            ex -= move[0] / cpp_x
            ey -= move[1] / cpp_y
            ex += target_velocity[0] * FRAME_DT
            ey += target_velocity[1] * FRAME_DT
            records.append((before, move))
        return records


class TestProfileConfiguration(WindMouseProfileCase):
    def test_profile_matches_default_config(self):
        profile = _load_profile()
        default = _load_json(DEFAULT_CONFIG_PATH)
        for key in PROFILE_KEYS:
            self.assertIn(key, profile, f"{key} missing from udp_144hz_fast_cvm.json")
            self.assertIn(key, default, f"{key} missing from config.json")
            self.assertAlmostEqual(
                float(profile[key]), float(default[key]), places=9,
                msg=f"{key} differs between profile and config.json",
            )
        self.assertEqual(profile["mode"], "WindMouse")
        self.assertEqual(profile["mode_sec"], "WindMouse")
        self.assertAlmostEqual(float(profile["in_game_sens"]), 0.235)
        self.assertEqual(int(profile["mouse_dpi"]), 1100)
        self.assertTrue(profile["enable_target_temporal_smoothing"])
        self.assertAlmostEqual(float(profile["ema_alpha"]), 0.5)
        self.assertEqual(int(profile["switch_confirm_frames"]), 2)

    def test_new_keys_round_trip(self):
        cfg = Config()
        dumped = cfg.to_dict()
        for key in NEW_CONFIG_KEYS:
            self.assertIn(key, dumped, f"{key} missing from Config.to_dict()")

        cfg.from_dict({
            "smooth_reaction_min": -5.0,
            "smooth_reaction_max": 99.0,
            "smooth_close_speed": -1.0,
            "smooth_max_step_ratio": 50.0,
            "smooth_acceleration": 0.0,
            "smooth_deceleration": 0.0,
            "smooth_reaction_min_sec": 99.0,
            "smooth_reaction_max_sec": -1.0,
            "wm_frame_gain": 4.0,
            "wm_frame_max_step_px": -3.0,
            "wm_settle_radius_px": 1e6,
            "wm_deadzone_px": "garbage",
        })
        self.assertGreaterEqual(cfg.smooth_reaction_min, 0.0)
        self.assertLessEqual(cfg.smooth_reaction_max, 0.5)
        self.assertLessEqual(cfg.smooth_reaction_min, cfg.smooth_reaction_max)
        self.assertGreaterEqual(cfg.smooth_close_speed, 0.01)
        self.assertLessEqual(cfg.smooth_max_step_ratio, 1.0)
        self.assertGreaterEqual(cfg.smooth_acceleration, 0.05)
        self.assertGreaterEqual(cfg.smooth_deceleration, 0.05)
        self.assertLessEqual(cfg.smooth_reaction_max_sec, 0.5)
        self.assertGreaterEqual(cfg.smooth_reaction_min_sec, 0.0)
        self.assertLessEqual(cfg.smooth_reaction_min_sec, cfg.smooth_reaction_max_sec)
        self.assertLessEqual(cfg.wm_frame_gain, 1.0)
        self.assertGreaterEqual(cfg.wm_frame_max_step_px, 0.5)
        self.assertLessEqual(cfg.wm_settle_radius_px, 6.0)
        self.assertGreaterEqual(cfg.wm_deadzone_px, 0.05)

    def test_settle_radius_covers_quantization(self):
        cpp_x, cpp_y = self.counts_per_pixel()
        px_per_count_x = 1.0 / cpp_x
        px_per_count_y = 1.0 / cpp_y
        settle = float(self.profile["wm_settle_radius_px"])
        self.assertGreater(
            settle, 0.5 * max(px_per_count_x, px_per_count_y),
            "settle radius smaller than half a count: one count would leave the settle zone",
        )
        self.assertLess(float(self.profile["wm_deadzone_px"]), 1.0)

    def test_deadzone_is_pixel_scaled(self):
        """2 px of error with the real counts-per-pixel ratio must still produce a path.

        Regression for the count-space dead zone: the old code stopped at
        `max(2.0 counts)` = 5.6 px (X) / 8.0 px (Y), so anything closer was
        silently ignored.
        """
        cpp_x, cpp_y = self.counts_per_pixel()
        aimer = self._wm_module.smooth_aimer
        aimer.reset_tracking_state()
        # First call is the acquisition frame (reaction window); consume it.
        aimer.calculate_smooth_path(2.0, 0.0, self.profile_ns, counts_per_pixel=(cpp_x, cpp_y))
        self.clock.advance(0.05)
        path = aimer.calculate_smooth_path(
            2.0, 0.0, self.profile_ns, counts_per_pixel=(cpp_x, cpp_y)
        )
        self.assertTrue(path, "2 px error produced an empty path (count-space dead zone)")
        self.assertGreater(sum(step[0] for step in path), 0)

    def test_deterministic_with_seed(self):
        cpp = self.counts_per_pixel()

        def run():
            self.clock.now = 5000.0
            aimer = self._wm_module.SmoothAiming(seed=7)
            # Acquisition frame opens the reaction window; skip past it.
            aimer.calculate_smooth_path(30.0, 12.0, self.profile_ns, counts_per_pixel=cpp)
            paths = []
            for _ in range(3):
                self.clock.advance(0.05)
                paths.append(
                    aimer.calculate_smooth_path(30.0, 12.0, self.profile_ns, counts_per_pixel=cpp)
                )
            return paths

        first, second = run(), run()
        self.assertEqual(first, second, "seeded SmoothAiming is not reproducible")
        self.assertTrue(any(first), "seeded run produced no movement at all")

    def test_config_representation_is_interchangeable(self):
        """The profile JSON (`wm_*` keys) and the internal pack (`smooth_*`) must agree.

        Regression: both failing call sites handed `calculate_smooth_path` the raw
        profile namespace and crashed on `config.smooth_gravity`. The public config
        surface only ever spells the geometry `wm_*`, so the pixel-scaled path has
        to resolve those names instead of assuming the internal pack's vocabulary.
        """
        cpp = self.counts_per_pixel()
        pack = normal_mod._WindMouseConfig(is_sec=False)

        def run(cfg):
            self.clock.now = 7000.0
            aimer = self._wm_module.SmoothAiming(seed=11)
            paths = [aimer.calculate_smooth_path(28.0, 9.0, cfg, counts_per_pixel=cpp)]
            for _ in range(2):
                self.clock.advance(0.05)
                paths.append(aimer.calculate_smooth_path(28.0, 9.0, cfg, counts_per_pixel=cpp))
            return paths

        from_profile = run(self.profile_ns)
        from_pack = run(pack)
        self.assertEqual(
            from_profile, from_pack,
            "profile namespace and _WindMouseConfig produced different paths",
        )
        self.assertTrue(any(from_profile), "neither representation produced a path")

    def test_profile_geometry_overrides_hardcoded_defaults(self):
        """Tuned `wm_*` values must reach the core, never the historical literals."""
        resolve = self._wm_module._config_float
        for name, default, tuned in (
            ("smooth_gravity", 9.0, 1.2),
            ("smooth_wind", 3.0, 0.35),
            ("smooth_max_step", 15.0, 4.0),
            ("smooth_min_step", 2.0, 1.2),
        ):
            self.assertAlmostEqual(
                resolve(self.profile_ns, name, default), tuned,
                msg=f"{name} fell back to the hardcoded default for a profile namespace",
            )
        # The internal pack keeps its own spelling and must resolve to the same numbers.
        pack = normal_mod._WindMouseConfig(is_sec=False)
        for name, default, tuned in (
            ("smooth_gravity", 9.0, 1.2),
            ("smooth_wind", 3.0, 0.35),
            ("smooth_max_step", 15.0, 4.0),
            ("smooth_min_step", 2.0, 1.2),
        ):
            self.assertAlmostEqual(
                resolve(pack, name, default), tuned,
                msg=f"{name} not read from the config pack",
            )


class TestFrameBudget(WindMouseProfileCase):
    def test_no_single_frame_lump(self):
        tracker = MockTracker()
        records = self.run_frames(tracker, 40.0, 0.0, 30)
        moves = [entry[1] for entry in records]
        cpp_x, _ = self.counts_per_pixel()

        first_moving = next((m for m in moves if m != (0, 0)), None)
        self.assertIsNotNone(first_moving, "aim never moved at all")
        self.assertLess(
            abs(first_moving[0]), 40.0 * cpp_x * 0.9,
            f"first moving frame emitted (almost) the whole error: {first_moving}",
        )

        max_step_px = float(self.profile["wm_frame_max_step_px"])
        cap_counts = max_step_px * cpp_x + 1.0
        for move in moves:
            self.assertLessEqual(abs(move[0]), cap_counts, f"frame exceeded budget: {move}")

        frames_with_move = sum(1 for move in moves if move != (0, 0))
        self.assertGreaterEqual(frames_with_move, 4, f"too few moving frames: {frames_with_move}")

    def test_no_overshoot_and_converges(self):
        tracker = MockTracker()
        records = self.run_frames(tracker, 40.0, 0.0, 30)
        cpp_x, _ = self.counts_per_pixel()
        total_x = sum(entry[1][0] for entry in records) / cpp_x
        self.assertLessEqual(abs(total_x), 40.0 + 1.0 / cpp_x,
                             f"travelled past the target: {total_x:.2f} px")

        settle = float(self.profile["wm_settle_radius_px"])
        final_err = abs(records[-1][0][0] - records[-1][1][0] / cpp_x)
        self.assertLessEqual(final_err, settle + 1.0 / cpp_x,
                             f"did not converge into the settle radius: {final_err:.2f} px")

        # Convergence must be monotone in the big steps: no frame may undo more
        # than one count of the progress already made.
        for entry in records[1:]:
            move = entry[1]
            if move[0] < 0:
                self.assertGreaterEqual(move[0], -1,
                                        f"corrected backwards by more than one count: {move}")

    def test_no_rattle_in_settle(self):
        """Sub-settle contour noise must never turn into a 1-count buzz."""
        tracker = MockTracker()
        self.run_frames(tracker, 40.0, 0.0, 30)
        noise = (0.8, -0.7, 1.1, -1.0, 0.5, -0.6)
        idle = 0
        for i in range(72):
            self.clock.advance()
            err = noise[i % len(noise)]
            normal_mod._apply_windmouse_aim(err, err * 0.5, tracker, is_sec=False)
            moves = tracker.drain()
            for move in moves:
                self.assertLessEqual(abs(move[0]), 1, f"rattle step too large: {move}")
                self.assertLessEqual(abs(move[1]), 1, f"rattle step too large: {move}")
            if not moves:
                idle += 1
        self.assertGreaterEqual(idle, 60, f"aim kept firing inside the settle radius: {72 - idle}/72")

    def test_strafe_tracking_no_stall(self):
        tracker = MockTracker()
        # Settle onto a stationary target first, then keep chasing the same
        # target as it starts strafing (one continuous acquisition, so no new
        # human reaction window is opened mid-test).
        self.run_frames(tracker, 20.0, 0.0, 30)
        speed_px_s = 400.0
        records = self.run_frames(tracker, 0.0, 0.0, 72,
                                  target_velocity=(speed_px_s, 0.0),
                                  reset_clock=False)
        errors = [abs(entry[0][0]) for entry in records]
        avg_lag = sum(errors) / len(errors)
        self.assertLessEqual(avg_lag, 10.0, f"strafe lag too high: {avg_lag:.2f} px")

        stall_run = 0
        for entry in records:
            err = abs(entry[0][0])
            if entry[1] == (0, 0) and err > 4.0:
                stall_run += 1
                self.assertLess(stall_run, 3, f"{stall_run} consecutive idle frames at {err:.1f} px")
            else:
                stall_run = 0

    def test_y_slower_than_x(self):
        cpp_x, cpp_y = self.counts_per_pixel()
        self.assertGreater(cpp_x, cpp_y)
        tracker = MockTracker()
        records = self.run_frames(tracker, 30.0, 30.0, 30)
        moved = [move for _, move in records if move != (0, 0)]
        self.assertTrue(moved, "diagonal aim never moved")
        # Equal pixel error on both axes must still travel less on Y: the
        # 100/70 speed split is what stops recoil from being pulled down hard.
        total_x = sum(abs(move[0]) for move in moved)
        total_y = sum(abs(move[1]) for move in moved)
        self.assertLess(total_y, total_x,
                        f"Y axis was not slower than X: {total_y} vs {total_x}")

    def test_settle_radius_stops_commands(self):
        tracker = MockTracker()
        self.run_frames(tracker, 40.0, 0.0, 30)
        self.clock.advance()
        # Sub-settle error must produce exactly no command.
        normal_mod._apply_windmouse_aim(1.0, 0.0, tracker, is_sec=False)
        self.assertEqual(tracker.drain(), [], "command emitted inside the settle radius")

    def test_reaction_window_does_not_snap(self):
        """A fresh acquisition must respect the 10-20 ms reaction, then move within budget."""
        tracker = MockTracker()
        self.clock.reset()
        self._wm_module.smooth_aimer.reset_tracking_state()

        normal_mod._apply_windmouse_aim(40.0, 0.0, tracker, is_sec=False)
        self.assertEqual(tracker.drain(), [], "first frame of a new target skipped the reaction delay")

        self.clock.advance(0.05)  # well past smooth_reaction_max = 0.02
        normal_mod._apply_windmouse_aim(40.0, 0.0, tracker, is_sec=False)
        moves = tracker.drain()
        self.assertTrue(moves, "aim still idle after the reaction window elapsed")
        cpp_x, _ = self.counts_per_pixel()
        cap = float(self.profile["wm_frame_max_step_px"]) * cpp_x + 1.0
        self.assertLessEqual(abs(moves[-1][0]), cap, f"post-reaction snap exceeded budget: {moves[-1]}")


class TestTargetSmootherReset(unittest.TestCase):
    def test_lost_target_resets_last_position(self):
        smoother = TargetSmoother(ema_alpha=0.5, switch_confirm_frames=2)
        first = smoother.stabilize([(60.0, 40.0, 10.0)], 100.0, 100.0)
        self.assertTrue(first)
        self.assertIsNotNone(smoother.last_target)

        self.assertEqual(smoother.stabilize([], 100.0, 100.0), [])
        self.assertIsNone(smoother.last_target,
                          "dropped target left a stale position to snap back to")

        # Re-acquiring elsewhere must jump straight to the new spot (no EMA lag
        # from the old position).
        again = smoother.stabilize([(10.0, 10.0, 50.0)], 100.0, 100.0)
        self.assertAlmostEqual(again[0][0], 10.0)
        self.assertAlmostEqual(again[0][1], 10.0)

    def test_production_dropout_gap_resets_stale_position(self):
        """`main.py` never calls `stabilize([])`: the gap between calls is the signal.

        Regression: `if targets_all and use_temporal_smoothing` in main.py means a
        lost target is simply not seen, so the empty-list branch above is dead in
        production and the frozen position survived the dropout.
        """
        clock = [100.0]
        smoother = TargetSmoother(ema_alpha=0.5, switch_confirm_frames=2,
                                  reacquire_gap_s=0.10, clock=lambda: clock[0])

        smoother.stabilize([(60.0, 40.0, 10.0)], 100.0, 100.0)
        clock[0] += 1.0 / 144.0
        smoother.stabilize([(60.0, 40.0, 10.0)], 100.0, 100.0)

        # Target disappears for a few frames (the call site is skipped entirely).
        clock[0] += 0.20
        again = smoother.stabilize([(10.0, 10.0, 50.0)], 100.0, 100.0)
        self.assertAlmostEqual(again[0][0], 10.0,
                               msg="first frame after a dropout chased the lost target")
        self.assertAlmostEqual(again[0][1], 10.0)

    def test_short_gap_keeps_the_same_target_eased(self):
        """A continuous detection stream must still be EMA-smoothed, not reset."""
        clock = [100.0]
        smoother = TargetSmoother(ema_alpha=0.5, switch_confirm_frames=2,
                                  reacquire_gap_s=0.10, clock=lambda: clock[0])
        smoother.stabilize([(60.0, 40.0, 10.0)], 100.0, 100.0)
        clock[0] += 1.0 / 144.0
        moved = smoother.stabilize([(62.0, 40.0, 10.0)], 100.0, 100.0)
        self.assertAlmostEqual(moved[0][0], 61.0, msg="EMA smoothing was lost on a normal frame")


class TestSecReactionWindow(unittest.TestCase):
    def test_sec_pack_reads_its_own_reaction_keys(self):
        """The Sec sliders write `smooth_reaction_*_sec`; the pack must honour them.

        Regression: `Config` did not declare those names, `from_dict` skipped them
        (`hasattr` guard), and `_WindMouseConfig` read the shared key for both
        aimbots, so the Sec sliders never changed anything.
        """
        saved = {}
        for key in ("smooth_reaction_min", "smooth_reaction_max",
                    "smooth_reaction_min_sec", "smooth_reaction_max_sec"):
            saved[key] = getattr(live_config, key, None)
        try:
            live_config.smooth_reaction_min = 0.08
            live_config.smooth_reaction_max = 0.20
            live_config.smooth_reaction_min_sec = 0.01
            live_config.smooth_reaction_max_sec = 0.02

            main_pack = normal_mod._WindMouseConfig(is_sec=False)
            sec_pack = normal_mod._WindMouseConfig(is_sec=True)

            self.assertAlmostEqual(main_pack.smooth_reaction_min, 0.08)
            self.assertAlmostEqual(main_pack.smooth_reaction_max, 0.20)
            self.assertAlmostEqual(sec_pack.smooth_reaction_min, 0.01)
            self.assertAlmostEqual(sec_pack.smooth_reaction_max, 0.02)
        finally:
            for key, value in saved.items():
                setattr(live_config, key, value)

    def test_sec_reaction_round_trips_through_config(self):
        cfg = Config()
        dumped = cfg.to_dict()
        for key in ("smooth_reaction_min_sec", "smooth_reaction_max_sec"):
            self.assertIn(key, dumped, f"{key} missing from Config.to_dict()")


class TestDecelerationEnvelope(unittest.TestCase):
    """`smooth_deceleration` / `smooth_acceleration` must actually shape the path.

    Regression: the multiplier was floored at 0.6 while the ease-out branch is at
    most `deceleration` (0.40 default, 0.55 tuned), so every value <= 0.6 was
    silently replaced and the knob did nothing.
    """

    def _total(self, aimer, path, config):
        return sum(abs(step[0]) for step in aimer._apply_smoothing_filters(path, config))

    def test_deceleration_below_old_floor_changes_the_tail(self):
        path = [(10, 0, 0.001)] * 12

        def run(deceleration):
            config = MockWindMouseConfig()
            config.smooth_deceleration = deceleration
            aimer = SmoothAiming(seed=3)
            return self._total(aimer, path, config)

        slow_tail = run(0.20)
        fast_tail = run(0.90)
        self.assertLess(
            slow_tail, fast_tail,
            "smooth_deceleration had no effect on the ease-out tail",
        )

    def test_acceleration_below_old_floor_changes_the_head(self):
        path = [(10, 0, 0.001)] * 12

        def run(acceleration):
            config = MockWindMouseConfig()
            config.smooth_acceleration = acceleration
            aimer = SmoothAiming(seed=3)
            return self._total(aimer, path, config)

        self.assertLess(run(0.10), run(0.90),
                        "smooth_acceleration had no effect on the ease-in head")

    def test_envelope_stays_continuous(self):
        """No step may exceed its original size and the profile must be monotone."""
        config = MockWindMouseConfig()
        config.smooth_acceleration = 0.5
        config.smooth_deceleration = 0.5
        aimer = SmoothAiming(seed=5)
        path = [(8, 4, 0.001)] * 15
        smoothed = aimer._apply_smoothing_filters(path, config)
        self.assertTrue(smoothed)
        for dx, dy, _delay in smoothed:
            self.assertLessEqual(abs(dx), 8)
            self.assertLessEqual(abs(dy), 4)
        # The middle of the path is at full speed: the envelope must not shrink
        # the whole path (that would make the aim lag behind the target).
        total = sum(abs(dx) + abs(dy) for dx, dy, _ in smoothed)
        self.assertGreaterEqual(total, 15 * 12 * 0.6)


if __name__ == "__main__":
    unittest.main()
