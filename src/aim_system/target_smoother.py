"""
Target hysteresis + EMA / One Euro smoothing helper for aiming stability.
"""
import math
import time


class OneEuroFilter1D:
    """1€ Filter (Casiez et al., 2012) for adaptive, zero-lag target tracking.

    At low speeds, cutoff frequency drops to min_cutoff to eliminate jitter.
    At high speeds, cutoff frequency increases proportionally to speed (beta * |dx|)
    to eliminate phase lag during rapid flicks and strafes.
    """
    def __init__(self, min_cutoff=1.0, beta=0.05, d_cutoff=1.0):
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self.x_prev = None
        self.dx_prev = 0.0
        self.t_prev = None

    @staticmethod
    def _alpha(rate, cutoff):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        te = 1.0 / rate
        return 1.0 / (1.0 + tau / te)

    def reset(self):
        self.x_prev = None
        self.dx_prev = 0.0
        self.t_prev = None

    def filter(self, t, x):
        if self.t_prev is None or self.x_prev is None:
            self.x_prev = float(x)
            self.dx_prev = 0.0
            self.t_prev = float(t)
            return float(x)

        dt = float(t) - self.t_prev
        self.t_prev = float(t)
        if dt <= 1e-6:
            return self.x_prev

        rate = 1.0 / dt
        # Estimate derivative
        dx = (float(x) - self.x_prev) * rate
        # Filter derivative
        a_d = self._alpha(rate, self.d_cutoff)
        dx_hat = a_d * dx + (1.0 - a_d) * self.dx_prev
        self.dx_prev = dx_hat

        # Filter signal with velocity-dependent cutoff
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(rate, cutoff)
        x_hat = a * float(x) + (1.0 - a) * self.x_prev
        self.x_prev = x_hat
        return x_hat


class TargetSmoother:
    def __init__(self, ema_alpha=0.35, switch_confirm_frames=3, switch_radius_px=18.0,
                 reacquire_gap_s=0.05, clock=None, use_one_euro=False,
                 min_cutoff=1.0, beta=0.05, d_cutoff=1.0):
        self.ema_alpha = float(ema_alpha)
        self.switch_confirm_frames = max(1, int(switch_confirm_frames))
        self.switch_radius_px = float(switch_radius_px)
        # A detection gap longer than this means the target was actually lost:
        # main.py only calls `stabilize` while at least one target exists, so the
        # gap between two calls is the only dropout signal available in production.
        # 50 ms is a few frames at 144 Hz and is also long enough for a strafing
        # target (400 px/s) to have left `switch_radius_px`, which is exactly when
        # the frozen position stops describing the target we now see.
        self.reacquire_gap_s = max(0.0, float(reacquire_gap_s))
        self._clock = clock if clock is not None else time.monotonic
        self._last_call_time = None
        self.last_target = None
        self.stable_candidate = None
        self.stable_count = 0

        self.use_one_euro = bool(use_one_euro)
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self._euro_x = OneEuroFilter1D(min_cutoff=self.min_cutoff, beta=self.beta, d_cutoff=self.d_cutoff)
        self._euro_y = OneEuroFilter1D(min_cutoff=self.min_cutoff, beta=self.beta, d_cutoff=self.d_cutoff)

    @staticmethod
    def _unpack_target(target):
        if len(target) >= 5:
            cx, cy, _, head_y_min, body_y_max = target[:5]
        else:
            cx, cy, _ = target[:3]
            head_y_min, body_y_max = None, None
        return float(cx), float(cy), head_y_min, body_y_max

    @staticmethod
    def _same_candidate(a, b, radius):
        if a is None or b is None:
            return False
        return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1])) <= float(radius)

    def _clear_candidate(self):
        self.stable_candidate = None
        self.stable_count = 0

    def _reset_euro(self):
        if self.use_one_euro:
            self._euro_x.reset()
            self._euro_y.reset()

    def _forget_target(self):
        self._clear_candidate()
        # Keeping the frozen position made the first frame after re-acquiring a
        # target chase the stale coordinates (candidate_far, stable_count <
        # switch_confirm_frames -> old position for a frame, then a reversal).
        self.last_target = None
        self._reset_euro()

    def stabilize(self, targets, center_x, center_y):
        now = self._clock()
        gap = None if self._last_call_time is None else now - self._last_call_time
        self._last_call_time = now

        # Production call site (`main.py`) is guarded by `if targets_all and ...`,
        # so `stabilize([], ...)` never runs there. A dropout therefore shows up
        # only as a gap between two calls: forget the switch-confirmation state
        # on that gap, otherwise the first frame after re-acquisition is spent
        # confirming a "switch" that already happened.
        lost_since_last_call = (
            gap is not None and self.reacquire_gap_s > 0.0 and gap > self.reacquire_gap_s
        )
        if lost_since_last_call:
            self._clear_candidate()

        if not targets:
            self._forget_target()
            return []

        best_target = min(targets, key=lambda t: t[2])
        cand_x, cand_y, cand_head_y_min, cand_body_y_max = self._unpack_target(best_target)
        switch_radius = max(6.0, self.switch_radius_px)

        # After a dropout the frozen position is only worth keeping when the new
        # detection is still the same target (small jump); a far one is a fresh
        # acquisition and must not be eased from where the lost target used to be.
        if (lost_since_last_call and self.last_target is not None
                and math.hypot(cand_x - self.last_target[0],
                               cand_y - self.last_target[1]) > switch_radius):
            self.last_target = None
            self._reset_euro()

        if self.last_target is None:
            self.last_target = (cand_x, cand_y, cand_head_y_min, cand_body_y_max)
            self._reset_euro()
            if self.use_one_euro:
                self._euro_x.filter(now, cand_x)
                self._euro_y.filter(now, cand_y)
            distance = math.hypot(cand_x - center_x, cand_y - center_y)
            return [(cand_x, cand_y, distance, cand_head_y_min, cand_body_y_max)]

        last_x, last_y, last_head_y_min, last_body_y_max = self.last_target
        candidate_far = math.hypot(cand_x - last_x, cand_y - last_y) > switch_radius

        desired_x = cand_x
        desired_y = cand_y
        desired_head_y_min = cand_head_y_min
        desired_body_y_max = cand_body_y_max

        if candidate_far:
            if self._same_candidate(self.stable_candidate, (cand_x, cand_y), switch_radius):
                self.stable_count += 1
            else:
                self.stable_candidate = (cand_x, cand_y)
                self.stable_count = 1

            if self.stable_count < self.switch_confirm_frames:
                desired_x = last_x
                desired_y = last_y
                desired_head_y_min = last_head_y_min
                desired_body_y_max = last_body_y_max
            else:
                self._clear_candidate()
                self._reset_euro()
        else:
            self._clear_candidate()

        if self.use_one_euro:
            smooth_x = self._euro_x.filter(now, desired_x)
            smooth_y = self._euro_y.filter(now, desired_y)
        else:
            alpha = max(0.0, min(1.0, self.ema_alpha))
            smooth_x = last_x + alpha * (desired_x - last_x)
            smooth_y = last_y + alpha * (desired_y - last_y)

        self.last_target = (smooth_x, smooth_y, desired_head_y_min, desired_body_y_max)
        distance = math.hypot(smooth_x - center_x, smooth_y - center_y)
        return [(smooth_x, smooth_y, distance, desired_head_y_min, desired_body_y_max)]
