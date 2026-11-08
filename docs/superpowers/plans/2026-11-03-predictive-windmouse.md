# Predictive WindMouse Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate mouse stalls and undershoots during target strafing in WindMouse mode by implementing target velocity estimation (lead-in prediction), unfreezing reaction delay during continuous tracking, dynamically scaling speed based on target velocity, and preserving sub-pixel micro-steps.

**Architecture:** Refactor `src/aim_system/windmouse_smooth.py` to add an Exponential Moving Average (EMA) velocity estimator that predicts target lead-in offset; fix `_target_changed` to only trigger reaction delays on actual target switches (>120px or >0.35s gap); remove the artificial 70% close-range speed clamp when target is moving; and implement residual carry quantization in `_apply_smoothing_filters` to avoid dropping 1px steps.

**Tech Stack:** Python 3.10+, NumPy, Math, Time, Pytest / Unittest.

**Spec:** `docs/superpowers/specs/2026-11-03-predictive-windmouse-design.md`

## Global Constraints
- Must remain fully backward-compatible with existing configuration keys and UI sliders.
- Zero external package dependencies (standard library + existing numpy).
- Execution time per frame in `calculate_smooth_path` must remain <= 1.0ms.
- Retain human-like organic motion (no instant robotic snaps).

## Review Focus
1. Target strafing horizontally at 15-30 px/100ms: bot must continuously produce non-empty movement paths matching the direction and speed of the strafe.
2. Rapid direction reversal (AD-AD strafe): EMA velocity smoother must adapt without producing erratic oscillations or large overshoots.
3. Target near center (< 15px): movements must not collapse to 0 or stall due to integer truncation.
4. Target lost or switching to a new enemy (> 120px): reaction delay must trigger normally to simulate human acquisition delay.
5. Inactive aimbot: fatigue and velocity states must reset cleanly when not aiming.

---

### Task 1: Create Unit Test Suite for Predictive WindMouse

**Files:**
- Create: `tests/test_windmouse_predictive.py`

- [ ] **Step 1: Write test cases in `tests/test_windmouse_predictive.py`**
  Cover:
  - `test_continuous_strafe_no_stall`: Simulates a target moving 4 pixels per frame across 10 frames. Asserts no empty paths are returned after initial acquisition.
  - `test_velocity_lead_calculation`: Verifies that when a target moves horizontally, the predicted lead offset shifts destination in the direction of movement.
  - `test_subpixel_preservation`: Verifies that micro-movements (1px steps) are not truncated to 0 in `_apply_smoothing_filters`.
  - `test_target_switch_detection`: Verifies that a small movement (< 60px) does not reset reaction delay, while a large jump (> 120px) properly triggers reaction delay.

- [ ] **Step 2: Run test suite to verify initial failure**
  Command: `& "venv\Scripts\python.exe" -m unittest tests/test_windmouse_predictive.py`
  Expected: Failure on continuous strafe and velocity prediction before implementation.

---

### Task 2: Implement Velocity Estimation & Anti-Stall in `windmouse_smooth.py`

**Files:**
- Modify: `src/aim_system/windmouse_smooth.py`

- [ ] **Step 1: Add VelocityEstimator class / state in `SmoothAiming`**
  - Add `last_target_pos = None`, `last_target_time = 0.0`, `velocity_x = 0.0`, `velocity_y = 0.0`.
  - Calculate velocity using delta time and apply EMA smoothing:
    `alpha = 0.65`
    `self.velocity_x = alpha * inst_vx + (1.0 - alpha) * self.velocity_x`
  - Compute lead destination:
    `lead_time = 0.030` (30ms latency compensation)
    `pred_dx = dx + self.velocity_x * lead_time`
    `pred_dy = dy + self.velocity_y * lead_time`

- [ ] **Step 2: Fix `_target_changed` logic**
  - Only reset reaction delay if target is `None` or if jump distance > `target_switch_threshold` (120px) or `elapsed_time > 0.35s`.
  - Do NOT trigger reaction delay during continuous tracking of the same target.

- [ ] **Step 3: Update speed scaling at close range**
  - Replace static `speed_multiplier = 0.3` with velocity-aware scaling:
    When target speed is significant (`target_speed > 20px/s`), scale `speed_multiplier` up to `0.85 - 1.0` so the mouse does not lag behind the running target.

- [ ] **Step 4: Fix sub-pixel truncation in `_apply_smoothing_filters`**
  - Implement carry accumulation (`carry_dx`, `carry_dy`) so `final_dx = int(round(acc_dx))` instead of truncating `int(dx * multiplier) = 0`.

- [ ] **Step 5: Run tests to verify all pass**
  Command: `& "venv\Scripts\python.exe" -m unittest tests/test_windmouse_predictive.py`
  Expected: All tests pass.

---

### Task 3: Runtime Verification and Regression Testing

**Files:**
- Modify: `tests/test_windmouse_predictive.py` (if additional edge cases needed)
- Verify: `src/aim_system/normal.py` and `main.py` compatibility

- [ ] **Step 1: Run comprehensive regression test**
  Verify that `_WindMouseConfig` and `_apply_windmouse_aim` in `normal.py` interface smoothly with `smooth_aimer.calculate_smooth_path`.
  Command: `& "venv\Scripts\python.exe" -c "import src.aim_system.windmouse_smooth as wms; import src.aim_system.normal as norm; print('Import and interface OK!')"`

- [ ] **Step 2: Benchmark latency**
  Ensure execution time of `calculate_smooth_path` is under 1.0ms across 100 iterations.
