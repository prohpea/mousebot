import math
import random
import time
import numpy as np


# The public config surface spells the WindMouse geometry `wm_*` (every profile
# JSON and `Config.to_dict()`), while `_WindMouseConfig` exposes the same values
# as `smooth_*`. Accept both so a caller may hand over the production pack, the
# live config object, or a raw profile namespace.
_GEOMETRY_ALIASES = {
    "smooth_gravity": ("smooth_gravity", "wm_gravity"),
    "smooth_wind": ("smooth_wind", "wm_wind"),
    "smooth_max_step": ("smooth_max_step", "wm_max_step"),
    "smooth_min_step": ("smooth_min_step", "wm_min_step"),
    "smooth_min_delay": ("smooth_min_delay", "wm_min_delay"),
    "smooth_max_delay": ("smooth_max_delay", "wm_max_delay"),
    "smooth_distance_threshold": ("smooth_distance_threshold", "wm_distance_threshold"),
}


def _config_float(config, name, default):
    """Read a numeric shaping/geometry value from any config representation.

    A raw profile namespace only carries `wm_*` names; the `_WindMouseConfig`
    pack carries `smooth_*`. Resolving both avoids an AttributeError (and, worse,
    a silent fallback to historical literals) depending on which one is passed.
    """
    for attr in _GEOMETRY_ALIASES.get(name, (name,)):
        try:
            value = getattr(config, attr, None)
        except Exception:
            value = None
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return float(default)


class WindMouse:
    """
    WindMouse algorithm for human-like mouse movement.
    Based on the original WindMouse algorithm with enhancements for smoothness.
    """

    def __init__(self, rng=None):
        # Injectable RNG keeps the closed-loop behaviour reproducible in tests.
        self.rng = rng if rng is not None else random
        self.last_x = 0
        self.last_y = 0
        self.last_time = time.time()

    def wind_mouse(self, start_x, start_y, dest_x, dest_y, gravity, wind,
                   min_wait, max_wait, max_step, target_area, distance_threshold=50.0):
        """
        Generate human-like mouse movement path from start to destination.

        All geometry arguments are expressed in mouse counts (the unit of the
        returned deltas). Callers that think in pixels convert before calling.

        Args:
            distance_threshold: Distance threshold where behavior changes.
                                Below this distance, movement becomes more precise and controlled.
        """
        current_x, current_y = float(start_x), float(start_y)
        velocity_x = velocity_y = wind_x = wind_y = 0.0
        path = []
        carry_x = 0.0
        carry_y = 0.0
        total_time = 0.0
        # Pre-calculate constants for performance
        sqrt3 = math.sqrt(3)
        drag_factor = 0.995

        while True:
            # Calculate distance to target (optimized)
            dx_to_target = dest_x - current_x
            dy_to_target = dest_y - current_y
            distance_squared = dx_to_target * dx_to_target + dy_to_target * dy_to_target

            # Break if we're close enough to target
            if distance_squared < target_area * target_area:
                break

            # Calculate distance for threshold check. The core runs in mouse
            # counts, so a 1-count epsilon would erase gravity for every error
            # below ~3 px (one count is 2.8 px on X / 4.0 px on Y at the 144 Hz
            # profile). Use a float epsilon instead: sub-count errors must still
            # be pulled, otherwise `target_area` alone decides and the path is
            # empty — the count-space dead zone this change exists to remove.
            distance = math.sqrt(distance_squared)

            # Dynamic adjustment based on distance threshold
            if distance_threshold > 0 and distance < distance_threshold:
                # Below threshold: reduce wind (less randomness), increase gravity (more precise)
                effective_wind = wind * 0.25  # Heavily reduce randomness near target for zero-jitter
                effective_gravity = gravity * 1.5  # Increase lock-on strength
            else:
                # Above threshold: normal behavior
                effective_wind = wind
                effective_gravity = gravity

            # Update wind (random force) - optimized
            wind_x = wind_x / sqrt3 + (self.rng.random() - 0.5) * effective_wind * 2
            wind_y = wind_y / sqrt3 + (self.rng.random() - 0.5) * effective_wind * 2

            # Calculate gravitational pull towards target - optimized
            if distance > 1e-9:
                gravity_x = effective_gravity * dx_to_target / distance
                gravity_y = effective_gravity * dy_to_target / distance
            else:
                gravity_x = gravity_y = 0

            # Update velocity with wind and gravity
            velocity_x += wind_x + gravity_x
            velocity_y += wind_y + gravity_y

            # Apply drag/friction
            velocity_x *= drag_factor
            velocity_y *= drag_factor

            # Limit maximum step size - optimized
            step_size_squared = velocity_x * velocity_x + velocity_y * velocity_y
            if step_size_squared > max_step * max_step:
                scale = max_step / math.sqrt(step_size_squared)
                velocity_x *= scale
                velocity_y *= scale

            # Calculate next position
            next_x = current_x + velocity_x
            next_y = current_y + velocity_y

            # Calculate delay for this step (human-like timing)
            delay = self.rng.uniform(min_wait, max_wait)

            carry_x += (next_x - current_x)
            carry_y += (next_y - current_y)
            out_dx = int(round(carry_x))
            out_dy = int(round(carry_y))
            carry_x -= out_dx
            carry_y -= out_dy

            # Add to path
            if out_dx != 0 or out_dy != 0:
                path.append((out_dx, out_dy, delay))

            current_x, current_y = next_x, next_y
            total_time += delay

            # Safety break to prevent infinite loops - optimized limits
            if len(path) > 100:  # Further reduced for better performance
                break
            if total_time > 0.25:  # Reduced time budget for faster response
                break
        return path


class SmoothAiming:
    """
    Advanced smooth aiming system with anti-tremor filtering,
    target velocity estimation (lead-in prediction), and anti-stall tracking.

    Public units are PIXELS: every threshold below (`distance < 1.0`,
    `distance < 20.0`, target speed, deadband, jump detection) is measured on
    the pixel error the caller passes in. The core WindMouse still works in
    mouse counts, so `calculate_smooth_path` converts using the caller supplied
    `counts_per_pixel` ratio.
    """

    # Pixel-space constants (were previously compared against raw counts).
    DEADZONE_PX = 1.0
    NEAR_TAPER_PX = 20.0
    SPEED_BOOST_PX_S = 80.0
    TARGET_SWITCH_PX = 120.0
    TARGET_LOST_S = 0.35
    # Absolute lower bound for the ease-in/ease-out envelope of a path step. It
    # only keeps a degenerate (zero) step from disappearing from the arithmetic.
    # It must never sit above a configurable coefficient: the old hard-coded
    # floor of 0.6 was above `smooth_deceleration` (0.40 default / 0.55 tuned),
    # so every deceleration value <= 0.6 was silently replaced by 0.6 and the
    # whole ease-out tail (and its config knob) was inert.
    MIN_STEP_SCALE = 1e-3

    def __init__(self, seed=None):
        # A seeded RNG makes the whole path deterministic (tests, A/B tuning).
        self.rng = random.Random(seed) if seed is not None else random
        self.windmouse = WindMouse(rng=self.rng)
        self.last_target = None
        self.last_target_pos = None
        self.last_target_time = 0.0
        self.target_history = []
        self.aim_fatigue = 0.0
        self.reaction_delay = 0.0
        self.last_reaction_time = 0.0
        self.velocity_x = 0.0
        self.velocity_y = 0.0
        self.lead_time = 0.025  # 25ms latency compensation for target prediction
        self.dir_history_x = []
        self.dir_history_y = []
        # Set by calculate_smooth_path when the current frame starts a new target,
        # so the caller can drop any sub-count carry accumulated on the old one.
        self.last_switch = False

    def update_velocity(self, dx, dy, current_time):
        """
        Estimate target velocity with anti-tremor deadband and directional consistency filtering.
        Eliminates derivative noise caused by hand tremors.
        """
        if self.last_target_pos is not None and self.last_target_time > 0:
            dt = current_time - self.last_target_time
            if dt < 0:
                # The wall clock jumped backwards (NTP/PTP correction, manual
                # clock change). A negative interval is not a velocity sample:
                # zero the estimate and re-anchor so the next frame is valid.
                self.velocity_x = 0.0
                self.velocity_y = 0.0
                self.dir_history_x.clear()
                self.dir_history_y.clear()
                self.last_target_pos = (dx, dy)
                self.last_target_time = current_time
                return
            if 0.005 <= dt <= 0.25:  # Valid frame interval (4fps - 200fps)
                step_x = dx - self.last_target_pos[0]
                step_y = dy - self.last_target_pos[1]

                # 1. Anti-Tremor Deadband:
                # Small micro-fluctuations (< 1.5px) are natural hand tremors / sensor noise
                if abs(step_x) < 1.5:
                    inst_vx = 0.0
                else:
                    inst_vx = step_x / dt

                if abs(step_y) < 1.5:
                    inst_vy = 0.0
                else:
                    inst_vy = step_y / dt

                # Clamp extreme outlier velocities (max 1000 px/s)
                max_v = 1000.0
                inst_vx = max(-max_v, min(max_v, inst_vx))
                inst_vy = max(-max_v, min(max_v, inst_vy))

                # 2. Directional Consistency Filter (Anti-Tremor Suppressor):
                # Hand tremor oscillates back and forth rapidly (+ - + -).
                # Real enemy strafing is consistently directional (+ + + +).
                dir_x = 1 if step_x > 0.8 else (-1 if step_x < -0.8 else 0)
                dir_y = 1 if step_y > 0.8 else (-1 if step_y < -0.8 else 0)

                self.dir_history_x.append(dir_x)
                self.dir_history_y.append(dir_y)
                if len(self.dir_history_x) > 5:
                    self.dir_history_x.pop(0)
                if len(self.dir_history_y) > 5:
                    self.dir_history_y.pop(0)

                # Count rapid direction reversals
                flips_x = sum(1 for a, b in zip(self.dir_history_x[:-1], self.dir_history_x[1:]) if a != 0 and b != 0 and a != b)
                flips_y = sum(1 for a, b in zip(self.dir_history_y[:-1], self.dir_history_y[1:]) if a != 0 and b != 0 and a != b)

                if flips_x >= 2:
                    # Hand tremor detected in X axis: heavily suppress velocity
                    alpha_x = 0.05
                    self.velocity_x *= 0.5
                else:
                    alpha_x = 0.25  # Smooth, stable tracking for real movement

                if flips_y >= 2:
                    # Hand tremor detected in Y axis
                    alpha_y = 0.05
                    self.velocity_y *= 0.5
                else:
                    alpha_y = 0.25

                # Apply EMA smoothing
                self.velocity_x = alpha_x * inst_vx + (1.0 - alpha_x) * self.velocity_x
                self.velocity_y = alpha_y * inst_vy + (1.0 - alpha_y) * self.velocity_y

            elif dt > self.TARGET_LOST_S:
                # Target was absent or paused too long; reset velocity
                self.velocity_x = 0.0
                self.velocity_y = 0.0
                self.dir_history_x.clear()
                self.dir_history_y.clear()

        self.last_target_pos = (dx, dy)
        self.last_target_time = current_time

    def get_predicted_lead(self, dx, dy):
        """
        Calculate predicted target destination accounting for velocity lead-in.
        Tapers lead-in smoothly to zero near target (< 20px) to prevent near-crosshair shake.
        Only predicts horizontal movement (X-axis strafe); suppresses vertical (Y-axis) weapon recoil kick.
        """
        distance = math.hypot(dx, dy)
        lead_scale = max(0.0, min(1.0, (distance / self.NEAR_TAPER_PX) ** 2))

        lead_dx = dx + self.velocity_x * self.lead_time * lead_scale
        # Recoil Immunity: Keep Y-axis lead static (lead_dy = dy) so gun recoil kick
        # does not cause violent vertical oscillations during firing.
        lead_dy = dy
        return lead_dx, lead_dy

    def in_reaction_delay(self, current_time=None):
        """True while the simulated human reaction window is still open.

        Callers use this to avoid treating the deliberate reaction pause as a
        stall and firing an immediate full-budget correction.
        """
        if current_time is None:
            current_time = time.time()
        if current_time < self.last_reaction_time:
            # Clock moved backwards: the window can never elapse, so nothing is
            # being waited for.
            return False
        return (current_time - self.last_reaction_time) < self.reaction_delay

    def reset_tracking_state(self):
        """Forget the current target so the next detection starts a fresh acquisition."""
        self.last_target = None
        self.last_target_pos = None
        self.last_target_time = 0.0
        self.velocity_x = 0.0
        self.velocity_y = 0.0
        self.reaction_delay = 0.0
        self.last_reaction_time = 0.0
        self.dir_history_x.clear()
        self.dir_history_y.clear()
        self.last_switch = False

    def calculate_smooth_path(self, dx, dy, config, counts_per_pixel=(1.0, 1.0)):
        """
        Calculate smooth movement path to target with anti-tremor filtering and velocity prediction.

        Args:
            dx, dy: remaining error in PIXELS (target minus crosshair).
            config: parameter pack; geometry fields are in pixels.
            counts_per_pixel: (x, y) mouse counts per pixel of screen movement.

        Returns:
            list of (dx_counts, dy_counts, delay) steps.
        """
        current_time = time.time()
        self.last_switch = False

        # Clock jump guard. `reaction_delay` is measured against
        # `last_reaction_time`; if the wall clock steps backwards (NTP/PTP
        # correction, DST/manual change) that difference stays negative and the
        # reaction window never closes, freezing the aim forever. Re-anchor
        # instead: the frame then behaves exactly like a normal post-reaction
        # frame.
        if self.last_reaction_time > 0.0 and current_time < self.last_reaction_time:
            self.last_reaction_time = 0.0
            self.reaction_delay = 0.0

        try:
            cpp_x = float(counts_per_pixel[0])
        except Exception:
            cpp_x = 1.0
        try:
            cpp_y = float(counts_per_pixel[1])
        except Exception:
            cpp_y = 1.0
        # A disabled axis (zero/negative speed) must never divide by zero.
        cpp_x = cpp_x if cpp_x > 1e-6 else 1e-6
        cpp_y = cpp_y if cpp_y > 1e-6 else 1e-6

        # Skip if movement is too small (deadzone, in pixels)
        distance = math.hypot(dx, dy)
        if distance < self.DEADZONE_PX:
            return []

        # Update velocity model with anti-tremor filtering
        self.update_velocity(dx, dy, current_time)
        target_speed = math.hypot(self.velocity_x, self.velocity_y)

        # Human reaction time simulation: ONLY on fresh target acquisition or large switch (> 120px)
        if self._is_target_switch(dx, dy, current_time):
            reaction_min = _config_float(config, "smooth_reaction_min", 0.08)
            reaction_max = _config_float(config, "smooth_reaction_max", 0.20)
            if reaction_max < reaction_min:
                reaction_min, reaction_max = reaction_max, reaction_min
            self.reaction_delay = self.rng.uniform(reaction_min, reaction_max)
            self.last_target = (dx, dy)
            self.last_reaction_time = current_time
            self.velocity_x = 0.0
            self.velocity_y = 0.0
            self.dir_history_x.clear()
            self.dir_history_y.clear()
            self.last_switch = True

        # Check if we're still in initial reaction delay
        if current_time - self.last_reaction_time < self.reaction_delay:
            return []

        self.last_target = (dx, dy)

        close_speed = _config_float(config, "smooth_close_speed", 0.15)
        far_speed = _config_float(config, "smooth_far_speed", 0.35)
        close_range = _config_float(config, "smooth_close_range", 30.0)
        far_range = _config_float(config, "smooth_far_range", 200.0)
        max_step_cfg = _config_float(config, "smooth_max_step", 15.0)
        min_step_cfg = _config_float(config, "smooth_min_step", 2.0)

        # Dynamic speed scaling:
        # Only boost speed when real strafing is detected (speed > 80 px/s, well above hand tremors)
        if target_speed > self.SPEED_BOOST_PX_S:
            boosted_close = max(close_speed, min(0.90, target_speed / 200.0))
        else:
            boosted_close = close_speed

        if distance < close_range:
            speed_multiplier = boosted_close
        elif distance > far_range:
            speed_multiplier = far_speed
        else:
            span = max(far_range - close_range, 1e-6)
            ratio = (distance - close_range) / span
            speed_multiplier = boosted_close + ratio * (far_speed - boosted_close)

        # WindMouse parameters, still expressed in pixels here.
        gravity_px = _config_float(config, "smooth_gravity", 9.0)
        wind_cfg = _config_float(config, "smooth_wind", 3.0)
        # Reduce wind significantly when near target to prevent fighting user's natural hand movement
        if distance < self.NEAR_TAPER_PX:
            wind_px = max(0.5, wind_cfg * 0.4)
        else:
            wind_px = wind_cfg

        # Dynamic step size (preserve smooth micro-steps near center)
        max_step_px = distance * speed_multiplier * _config_float(config, "smooth_max_step_ratio", 0.08)
        if target_speed > self.SPEED_BOOST_PX_S and distance > 15.0:
            max_step_px = max(max_step_px, min(max_step_cfg, target_speed * 0.04))
        max_step_px = max(min_step_cfg, min(max_step_px, max_step_cfg))

        # Target area: a soft stop radius in pixels, no hard count-space floor.
        deadzone_px = _config_float(config, "wm_deadzone_px", 0.40)
        if target_speed > self.SPEED_BOOST_PX_S:
            target_area_px = max(deadzone_px, min(1.0, distance * 0.02))
        else:
            target_area_px = max(deadzone_px, distance * _config_float(config, "smooth_target_area_ratio", 0.05))

        # Distance threshold from config (pixels)
        distance_threshold_px = _config_float(config, "smooth_distance_threshold", 50.0)

        # Compute predicted target coordinates with lead-in
        lead_dx, lead_dy = self.get_predicted_lead(dx, dy)

        # Convert the pixel-space geometry into the count space the core expects.
        dest_x = lead_dx * cpp_x
        dest_y = lead_dy * cpp_y
        lead_px = math.hypot(lead_dx, lead_dy)
        if lead_px > 1e-9:
            cpp_eff = math.hypot(dest_x, dest_y) / lead_px
        else:
            cpp_eff = math.hypot(cpp_x, cpp_y) / math.sqrt(2.0)

        path = self.windmouse.wind_mouse(
            0.0, 0.0, dest_x, dest_y,
            gravity=gravity_px * cpp_eff,
            wind=wind_px * cpp_eff,
            min_wait=_config_float(config, "smooth_min_delay", 0.001),
            max_wait=_config_float(config, "smooth_max_delay", 0.0025),
            max_step=max_step_px * cpp_eff,
            target_area=target_area_px * cpp_eff,
            distance_threshold=distance_threshold_px * cpp_eff
        )

        # Apply smoothing and filtering with residual carry accumulation
        filtered_path = self._apply_smoothing_filters(path, config)
        return filtered_path

    def _is_target_switch(self, dx, dy, current_time=None):
        """
        Check if target has switched to a completely different enemy.
        Continuous strafing of the same target will return False.
        """
        if self.last_target is None:
            return True
        if current_time is None:
            current_time = time.time()

        # If target has been absent for more than 0.35s, consider it a new target
        if self.last_target_time > 0.0 and (current_time - self.last_target_time > self.TARGET_LOST_S):
            return True

        last_dx, last_dy = self.last_target
        jump_dist = math.hypot(dx - last_dx, dy - last_dy)
        # Only treat large position jumps (> 120px) as target switching
        return jump_dist > self.TARGET_SWITCH_PX

    def _target_changed(self, dx, dy, threshold=120):
        """Backward-compatible alias for target switch check."""
        return self._is_target_switch(dx, dy)

    def _apply_smoothing_filters(self, path, config):
        """
        Apply humanization curves to path with sub-pixel carry accumulation
        to prevent dropping 1px micro-movements.

        The envelope is continuous and monotone on both ends:
        acceleration ramps the step scale from `smooth_acceleration` up to 1.0,
        deceleration ramps it from 1.0 down to `smooth_deceleration`. Both
        coefficients therefore have a visible, tunable effect (the old code
        multiplied by an ease curve and then floored at 0.6, which swallowed
        every deceleration <= 0.6 and any acceleration below 0.6).

        At most one count per axis is dropped by the integer truncation of the
        last step; the sub-count remainder is intentionally handed back to the
        emitter's own carry instead of being flushed as a phantom final step.
        """
        if len(path) < 2:
            return path

        smoothed_path = []
        carry_dx = 0.0
        carry_dy = 0.0
        acceleration = _config_float(config, "smooth_acceleration", 0.50)
        deceleration = _config_float(config, "smooth_deceleration", 0.40)
        acceleration = max(0.0, min(1.0, acceleration))
        deceleration = max(0.0, min(1.0, deceleration))

        last_index = len(path) - 1
        for i, (dx, dy, delay) in enumerate(path):
            progress = i / last_index

            if progress < 0.3:
                # Ease-in: start at the configured fraction of a full step and
                # reach a full step exactly where the ramp ends (no jump).
                multiplier = acceleration + (1.0 - acceleration) * self._ease_in(progress / 0.3)
            elif progress > 0.7:
                # Ease-out: full step at the start of the tail, decaying to the
                # configured fraction on the final step (no jump either). The
                # remainder that this shrinkage leaves behind is exactly what
                # makes the path decelerate before the target instead of
                # overshooting it.
                tail = (progress - 0.7) / 0.3
                multiplier = 1.0 - (1.0 - deceleration) * self._ease_out(tail)
            else:
                multiplier = 1.0

            multiplier = max(multiplier, self.MIN_STEP_SCALE)

            # Sub-pixel accumulation
            step_dx = float(dx)
            step_dy = float(dy)
            acc_dx = step_dx * multiplier + carry_dx
            acc_dy = step_dy * multiplier + carry_dy

            final_dx = int(round(acc_dx))
            final_dy = int(round(acc_dy))

            carry_dx = acc_dx - final_dx
            carry_dy = acc_dy - final_dy

            # Add slight delay variation
            final_delay = delay * self.rng.uniform(0.9, 1.1)

            if final_dx != 0 or final_dy != 0:
                smoothed_path.append((final_dx, final_dy, final_delay))

        # `carry_dx/carry_dy` are always within (-0.5, 0.5) here, so rounding
        # them would always yield 0: the leftover sub-count is deliberately left
        # for the next frame's plan instead of being flushed as a phantom step.
        return smoothed_path

    def _ease_in(self, t):
        """Ease-in function for smooth acceleration."""
        return t * t

    def _ease_out(self, t):
        """Ease-out function for smooth deceleration."""
        return 1.0 - (1.0 - t) * (1.0 - t)

    def reset_fatigue(self):
        """Reset aim fatigue and velocity state (call when not aiming)."""
        self.aim_fatigue = max(0.0, self.aim_fatigue - 0.1)
        self.velocity_x = 0.0
        self.velocity_y = 0.0
        self.dir_history_x.clear()
        self.dir_history_y.clear()
        self.last_target_pos = None


# Global smooth aiming instance
smooth_aimer = SmoothAiming()
