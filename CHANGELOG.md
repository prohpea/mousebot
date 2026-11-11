# Changelog & Version History

All notable changes, bug fixes, and tuning updates to the CVM-colorBot WindMouse aim system are documented in this file.

---

## [v1.2.1] - 2026-11-03 ("Toggle Audio & Visual Feedback")

### 🔔 New Features
- **Integrated OBS Audio Feedback (PC 1)**:
  - Recompiled `obs-color-correction.dll` with an integrated non-blocking UDP listener on port `4455`.
  - Directly calls native Windows `Beep()` API inside OBS on PC 1 without needing any extra Python scripts or background tools.
  - **Beep High (1200 Hz, 60ms)**: Triggered immediately when Aimbot Toggle is turned **ON / ACTIVE**.
  - **Beep Low (600 Hz, 70ms)**: Triggered immediately when Aimbot Toggle is turned **OFF / STANDBY**.
- **Real-Time Visual Toggle HUD (PC 2)**:
  - Fixed legacy logic in OpenCV detection window where aimbot status was statically reading config instead of actual toggle runtime state.
  - Added a high-visibility status banner at the top-right of the `Detection` window:
    - **Vibrant Green Box `[ AIM: ACTIVE ]`**: Clearly visible when toggle is active.
    - **Dark Red Box `[ AIM: STANDBY ]`**: Clearly visible when toggle is standby.
- **Ultra-Fast UDP State Dispatcher (`src/utils/network_feedback.py`)**:
  - Non-blocking UDP packet transmission directly to `config.udp_ip:4455` on every toggle key event.

---

## [v1.2] - 2026-11-03 (Release - "Humanized Burst & Spray")

### 🎯 Key Enhancements & Features
- **Ultra-Smooth Burst & Spray Tuning**:
  - Re-tuned vertical and horizontal speed ratio (`normal_x_speed: 100`, `normal_y_speed: 70`) to eliminate crosshair snapping/flying over the enemy's head when firing.
  - Decreased WindMouse gravity from `10.5` down to `4.5` for gentle, human-like pull instead of robotic lock-on.
  - Adjusted step sizes (`wm_max_step: 8.0`, `wm_min_step: 0.8`) and delays (`2.5ms - 5.0ms`) to support continuous spray tracking without jitter.
- **Natural Reaction Simulation**:
  - Reaction time set to realistic human threshold (`80ms - 200ms`).
  - Far-range approach speed attenuated (`smooth_far_speed: 0.35`, `smooth_close_speed: 0.15`).

### 🛡️ Core Algorithmic Upgrades
- **Recoil Immunity (Y-Axis Decoupling)**:
  - Lead-in velocity prediction strictly isolated to X-axis (`lead_dx = dx + vx * lead_time`). Vertical gun recoil kick on Y-axis is untouched (`lead_dy = dy`), completely preventing violent vertical oscillations while firing.
- **Anti-Tremor Deadband & Directional Flip Filter**:
  - 1.5px deadband for minor sensor/hand jitter.
  - Directional flip detection tracking the last 5 frames: rapid back-and-forth oscillations suppress velocity estimation (`alpha = 0.05`), while consistent strafing maintains solid tracking (`alpha = 0.25`).
- **Sub-pixel Carry Accumulator**:
  - Sub-pixel movements are preserved with carry accumulation, preventing 1px micro-step truncation.
- **Anti-Stall on Continuous Strafe**:
  - Target-switch detection improved to only trigger full reaction delays on genuine target switches (> 120px jump or target disappearance > 0.35s). Enemy AD strafing maintains continuous smooth tracking.

### ⚡ Infrastructure & Decoding
- **TurboJPEG Native Acceleration**:
  - Multi-path DLL resolver installed at `C:\libjpeg-turbo64\bin\turbojpeg.dll` and integrated into `src/capture/OBS_UDP.py`. UDP frame decompression latency reduced to < 0.5ms.

### 📋 Recommended Settings Snapshot
```json
{
  "in_game_sens": 0.23,
  "mouse_dpi": 1100,
  "fovsize": 28,
  "normal_x_speed": 100,
  "normal_y_speed": 70,
  "wm_gravity": 4.5,
  "wm_wind": 2.0,
  "wm_max_step": 8.0,
  "wm_min_step": 0.8,
  "wm_min_delay": 0.0025,
  "wm_max_delay": 0.0050,
  "wm_distance_threshold": 30.0
}
```

---

## [v1.1] - 2026-11-03 (Internal Experimental)
- Initial Predictive WindMouse implementation.
- Added velocity estimation with EMA smoothing.
- Fixed TurboJPEG loader in `src/capture/OBS_UDP.py`.
- Added unit test suite `tests/test_windmouse_predictive.py`.

---

## [v1.0] - Baseline
- Original WindMouse and Flick implementation with OBS UDP receiver.
