import math
import random
import time
import numpy as np

class WindMouse:
    """
    WindMouse algorithm for human-like mouse movement.
    Based on the original WindMouse algorithm with enhancements for smoothness.
    """
    
    def __init__(self):
        self.last_x = 0
        self.last_y = 0
        self.last_time = time.time()
        
    def wind_mouse(self, start_x, start_y, dest_x, dest_y, gravity, wind, 
                   min_wait, max_wait, max_step, target_area, distance_threshold=50.0):
        """
        Generate human-like mouse movement path from start to destination.
        
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
                # Ensure micro-step is preserved if breaking on close approach
                if not path and (abs(dx_to_target) >= 0.15 or abs(dy_to_target) >= 0.15):
                    s_x = 1 if dx_to_target >= 0.15 else (-1 if dx_to_target <= -0.15 else 0)
                    s_y = 1 if dy_to_target >= 0.15 else (-1 if dy_to_target <= -0.15 else 0)
                    if s_x != 0 or s_y != 0:
                        path.append((s_x, s_y, min_wait))
                break
            
            # Calculate distance for threshold check
            distance = math.sqrt(distance_squared) if distance_squared > 1 else 0.0
            
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
            wind_x = wind_x / sqrt3 + (random.random() - 0.5) * effective_wind * 2
            wind_y = wind_y / sqrt3 + (random.random() - 0.5) * effective_wind * 2
            
            # Calculate gravitational pull towards target - optimized
            if distance_squared > 1:
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
            delay = random.uniform(min_wait, max_wait)

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
    """
    
    def __init__(self):
        self.windmouse = WindMouse()
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

    def update_velocity(self, dx, dy, current_time):
        """
        Estimate target velocity with anti-tremor deadband and directional consistency filtering.
        Eliminates derivative noise caused by hand tremors.
        """
        if self.last_target_pos is not None and self.last_target_time > 0:
            dt = current_time - self.last_target_time
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
                
            elif dt > 0.35:
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
        lead_scale = max(0.0, min(1.0, (distance / 20.0) ** 2))
        
        lead_dx = dx + self.velocity_x * self.lead_time * lead_scale
        # Recoil Immunity: Keep Y-axis lead static (lead_dy = dy) so gun recoil kick
        # does not cause violent vertical oscillations during firing.
        lead_dy = dy
        return lead_dx, lead_dy
        
    def calculate_smooth_path(self, dx, dy, config):
        """
        Calculate smooth movement path to target with anti-tremor filtering and velocity prediction.
        """
        current_time = time.time()
        
        # Skip only when already dead-center on target (< 0.20 count)
        distance = math.hypot(dx, dy)
        if distance < 0.20:
            return []

        # Micro-correction guarantee: if very close (0.20 <= distance < 1.0),
        # emit a deterministic 1px step so tracking NEVER stalls near the head!
        if distance < 1.0:
            m_dx = 1 if dx >= 0.15 else (-1 if dx <= -0.15 else 0)
            m_dy = 1 if dy >= 0.15 else (-1 if dy <= -0.15 else 0)
            if m_dx != 0 or m_dy != 0:
                delay = getattr(config, "smooth_min_delay", 0.002)
                return [(m_dx, m_dy, delay)]
            return []

        # Update velocity model with anti-tremor filtering
        self.update_velocity(dx, dy, current_time)
        target_speed = math.hypot(self.velocity_x, self.velocity_y)

        # Human reaction time simulation: ONLY on fresh target acquisition or large switch (> 120px)
        if self._is_target_switch(dx, dy, current_time):
            self.reaction_delay = random.uniform(config.smooth_reaction_min, config.smooth_reaction_max)
            self.last_target = (dx, dy)
            self.last_reaction_time = current_time
            self.velocity_x = 0.0
            self.velocity_y = 0.0
            self.dir_history_x.clear()
            self.dir_history_y.clear()
            
        # Check if we're still in initial reaction delay
        if current_time - self.last_reaction_time < self.reaction_delay:
            return []
        
        self.last_target = (dx, dy)

        # Dynamic speed scaling:
        # Only boost speed when real strafing is detected (speed > 80 px/s, well above hand tremors)
        if target_speed > 80.0:
            boosted_close = max(config.smooth_close_speed, min(0.90, target_speed / 200.0))
        else:
            boosted_close = config.smooth_close_speed

        if distance < config.smooth_close_range:
            speed_multiplier = boosted_close
        elif distance > config.smooth_far_range:
            speed_multiplier = config.smooth_far_speed
        else:
            ratio = (distance - config.smooth_close_range) / (config.smooth_far_range - config.smooth_close_range)
            speed_multiplier = boosted_close + ratio * (config.smooth_far_speed - boosted_close)
        
        # Calculate WindMouse parameters based on config
        gravity = config.smooth_gravity
        # Reduce wind significantly when near target to prevent fighting user's natural hand movement
        if distance < 20.0:
            wind = max(0.5, config.smooth_wind * 0.4)
        else:
            wind = config.smooth_wind
        
        # Dynamic step size (preserve smooth micro-steps near center)
        max_step = distance * speed_multiplier * config.smooth_max_step_ratio
        if target_speed > 80.0 and distance > 15.0:
            max_step = max(max_step, min(config.smooth_max_step, target_speed * 0.04))
        max_step = max(config.smooth_min_step, min(max_step, config.smooth_max_step))
        
        # Target area: tightened to 0.25 to prevent stall on close head approach
        if target_speed > 80.0:
            target_area = max(0.20, distance * 0.01)
        else:
            target_area = max(0.25, distance * config.smooth_target_area_ratio)
        
        # Get distance threshold from config
        distance_threshold = getattr(config, 'smooth_distance_threshold', 50.0)
        
        # Compute predicted target coordinates with lead-in
        lead_dx, lead_dy = self.get_predicted_lead(dx, dy)
        
        # Generate movement path
        path = self.windmouse.wind_mouse(
            0, 0, lead_dx, lead_dy,
            gravity=gravity,
            wind=wind,
            min_wait=config.smooth_min_delay,
            max_wait=config.smooth_max_delay,
            max_step=max_step,
            target_area=target_area,
            distance_threshold=distance_threshold
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
        if self.last_target_time > 0.0 and (current_time - self.last_target_time > 0.35):
            return True
        
        last_dx, last_dy = self.last_target
        jump_dist = math.hypot(dx - last_dx, dy - last_dy)
        # Only treat large position jumps (> 120px) as target switching
        return jump_dist > 120.0

    def _target_changed(self, dx, dy, threshold=120):
        """Backward-compatible alias for target switch check."""
        return self._is_target_switch(dx, dy)
    
    def _apply_smoothing_filters(self, path, config):
        """
        Apply humanization curves to path with sub-pixel carry accumulation
        to prevent dropping 1px micro-movements.
        """
        if len(path) < 2:
            return path
        
        smoothed_path = []
        carry_dx = 0.0
        carry_dy = 0.0
        
        # Apply acceleration/deceleration curves
        for i, (dx, dy, delay) in enumerate(path):
            progress = i / len(path)
            
            # Ease-in-out curve for more natural acceleration
            if progress < 0.3:
                multiplier = self._ease_in(progress / 0.3) * config.smooth_acceleration
            elif progress > 0.7:
                multiplier = self._ease_out((progress - 0.7) / 0.3) * config.smooth_deceleration
            else:
                multiplier = 1.0

            multiplier = max(multiplier, 0.6)  # Prevent steps from collapsing too much

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
            final_delay = delay * random.uniform(0.9, 1.1)
            
            if final_dx != 0 or final_dy != 0:
                smoothed_path.append((final_dx, final_dy, final_delay))
        
        # If accumulated sub-pixel carry rounds to a non-zero pixel, append it
        if carry_dx != 0.0 or carry_dy != 0.0:
            rem_dx = int(round(carry_dx))
            rem_dy = int(round(carry_dy))
            if rem_dx != 0 or rem_dy != 0:
                fallback_delay = path[-1][2] if path else 0.001
                smoothed_path.append((rem_dx, rem_dy, fallback_delay))
        
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
