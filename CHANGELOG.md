# Changelog & Version History

All notable changes, bug fixes, and tuning updates to the CVM-colorBot WindMouse aim system are documented in this file.

---

## [v2.1.0] - 2026-11-09 ("Flick V2 UI & Valorant Calibration")

### 🎯 Flick V2 UI
- **Dedicated `Flick V2` tab** (Combat sub-nav) with a Main and a Secondary column, a Calibration card and a collapsible Diagnostics panel.
- **Seven parameters per channel**: `Gain`, `Settle Delay` *(new)*, `Max Counts / Step`, `Convergence Budget`, `Max Iterations`, `Deadzone`, and advanced `Target Switch Radius` *(new)*. Main and Sec are built from one shared spec, so they can no longer drift apart.
- **Derived readouts**: `effective_steps = min(max_iterations, floor(budget / max(settle,1)) + 1)`, estimated max travel, and a `Settle ≥ Budget` warning with a one-click `Auto-fix` (`budget = settle + 50`). A fresh default budget of **240 ms** finally honours the advertised 4 iterations at `settle = 70 ms`.
- **Live diagnostics**: last reason, iterations, counts, residual, clamped steps, calibration source and gain, plus `Copy diagnostics` and `Reset state`.
- `Calibrate` on the compact Main/Sec card jumps to the Flick V2 tab with the Valorant source selected.

### 📐 Calibration — Valorant
- **Three explicit sources** with a stored `calibration_source`: `valorant` (0.07 °/count at sens 1.0), `measured` (impulse + signed pixel shift), `analytic` (legacy 54.54 cm/rev, marked `LEGACY`).
- Valorant preset is **recomputed from the current sensitivity** without a restart: sens 0.23 → **62.112 counts/deg**, 51.63 cm/360, 30 px ≈ 139.8 counts. Users can see the 4.594× gap against the legacy model.
- Measured workflow requires **both axes**, **≥ 5 samples per axis** and **R² ≥ 0.99**; the fit refuses to extrapolate a missing axis and records `calibration_r2`, `calibration_samples`, `calibration_sens_at_measurement`.
- Provenance is displayed (source, samples, R², updated-at, geometry frame/FOV/focal/°/px). A measured scale that drifts > 20 % from the Valorant preset raises a warning banner.
- Schema-2 configs are migrated: `62.11 @ sens 0.23` is recognised as the Valorant preset (not "measured"), an unbacked legacy scale is demoted to `analytic` with a warning.

### ⚡ Performance
- **Move queue dispatches per tag**: `calib` is exclusive, `flick` impulses stay whole, `track`/`rcs` batch within their own tag. Cross-tag summation (which added a flick impulse to a tracking step and a recoil tick) is gone; `move_queue_per_tag_dispatch=False` restores the old behaviour.
- **Preview throttled** to `ui_preview_max_fps` (default 30) with a single `waitKey`, and overlays no longer draw when preview is off.
- **Anti-smoke** computes the nearest bbox once per frame and caches contour plausibility per `(bbox, detector, mask)` version.
- **Unified UI scheduler** replaces six independent timers and stops working while the window is iconised; the debug log only formats when the Telemetry tab is open and the log version changed.
- **Geometry/calibration caches** in `aim_math` (LRU, signature-keyed) and a signature-gated `FlickController.configure`, so the hot path stops rebuilding dataclasses and re-running trigonometry every frame.
- Head estimation no longer allocates `np.where` + median arrays per detection, and `log_move` is gated by telemetry/debug flags.

### 🐛 Fixes
- Calibration impulses are exclusive: the aim pipeline is suppressed during a calibration session so a stray `track`/`flick` cannot contaminate the measurement.
- `FlickController.rollback_step()` now restores `_last_step_time`, `last_sent`, `total_sent` and `clamped_steps`, so a rejected impulse no longer burns the settle window or the convergence budget.
- `mode_flick` propagates `settle_ms` and `switch_radius_px` through `configure()`, so moving the Settle slider takes effect immediately.
- `_last_runtime_settings_lock_state` caching removes the 500 ms full widget-tree traversal.
- Destroyed debug widgets are cleared (`_clear_content`), so the 10 Hz log update stops raising.
- Config is loaded **once** before `AimTracker` construction; `ui_pro_mode` is persisted again.
- Unconditional ROI drawing in `_estimate_head_positions` is fixed.

### 🧹 Cleanup & versioning
- Removed the dead Magnet Trigger UI tab, `_show_tb_tab`'s unreachable ~350-line body, and unused helpers/imports in `ui.py`.
- `src/version.py` is the single source of truth for the version: title, badge, README, CHANGELOG, updater and startup print all read it. `version.json` now carries `codename` and `schema`.
- AppUserModelID is stabilised to `mycompany.colorbot` (no version), so Windows stops creating a duplicate taskbar icon every release.
- Config schema → 3 with `calibration_source`, `flick_switch_radius_px`, `flick_telemetry_enabled`, `ui_preview_max_fps`, `move_queue_per_tag_dispatch`.

---

## [v2.0.0] - 2026-11-08 ("Major UI & Functional Overhaul - Burst & Spray Pro")

### 🚀 Major Highlights & Redesign
- **Modern 5-Pillar UI Overhaul**:
  - Upgraded window title and branding to **CVM colorBot v2.0 PRO**.
  - New high-contrast Emerald/Cyan dashboard badges with real-time status indicators.
  - Added dedicated **"Recoil & RCS"** control pillar inside the Combat tab for live ballistics tuning.
  - Added one-click **"Enable RCS (Burst & Spray)"** master switch directly onto the Main Aimbot dashboard.
- **Two-Stage Ballistics Engine (Burst & Spray)**:
  - **140ms Burst Immunity**: For the first 1-3 bullets (< 140ms hold), RCS pull-down is inhibited, allowing first-bullet headshot priority with `aim_type: head` and `aim_offsetY: -3`.
  - **Auto Spray Compensation**: Holding fire beyond 140ms automatically engages vertical pull-down (`rcs_pull_speed: 9`), while aimbot smoothly releases the vertical axis (`dy = 0`) and maintains horizontal tracking.
  - **Auto Y-Recovery**: Smoothly restores pitch angles after spray release (`0.35s` recovery duration).
- **Pro-Calibrated Defaults (253 eDPI)**:
  - Default hardware standard set to **1100 DPI** and **0.23 In-Game Sensitivity**.
  - Default activation mode set to **Toggle** on **Side Mouse 4 Button (XBUTTON1)**.
- **Dedicated Ranked Presets**:
  - `configs/ranked_tryhard_burst_spray.json`: Dedicated preset for competitive high-tier play.
  - `configs/toggle_edpi253_dpi1100.json`: Dedicated preset for clean toggle aiming.

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
