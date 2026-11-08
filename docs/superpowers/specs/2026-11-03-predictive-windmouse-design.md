# Predictive WindMouse with Velocity Tracking & Anti-Stall Design

## 1. Intent & Why
Currently, in `windmouse_smooth.py`, mouse movements stall and fail to catch up to strafing targets. Users experience "undershoot" where the crosshair cannot reach moving targets. This is caused by an artificial close-range speed cap (30%), a misplaced reaction delay timer that triggers on continuous target movement, integer truncation dropping micro-movements, and lack of target velocity prediction.

The goal is to enable the WindMouse aiming mode to lock on and track moving/strafing targets with high precision while preserving the organic, human-like motion curve of the WindMouse algorithm.

## 2. Goals, Non-Goals, and Anti-Goals
- **Goals:**
  - Maintain continuous tracking when targets strafe horizontally or vertically within the FOV.
  - Dynamically compensate for target velocity using Exponential Moving Average (EMA) velocity prediction.
  - Eliminate the artificial 20–80ms freeze caused by `_target_changed` during active tracking of the same target.
  - Prevent sub-pixel micro-movement loss during smoothing filter quantization.
- **Non-Goals:**
  - Replacing WindMouse with raw linear aimbot or snap flick algorithms.
  - Altering color detection or HSV pipeline (OBS stream already delivers boosted purple tones).
- **Anti-Goals:**
  - Creating robotic, perfectly linear instant snaps that trigger anti-cheat heuristic flags.
  - Introducing heavy overshoots or oscillations when targets suddenly change strafe directions.

## 3. Constraints
- Must remain compatible with existing UI sliders and `_WindMouseConfig`.
- Zero new external heavy library dependencies (pure Python with `math`, `time`, standard library).
- Execution budget per frame must remain under 1.5ms to avoid frame drops in the main tracking loop.

## 4. Approaches Considered
- **Approach 1: Static Parameter & Bug Fixes Only**
  - Gỡ bỏ bộ trễ `_target_changed` và hãm tốc độ 70%.
  - *Trade-off:* Không còn bị đứng hình nhưng vẫn bị trễ 1-2 frame sau đuôi địch khi địch strafe đổi hướng nhanh (vì chỉ ngắm tọa độ tĩnh).
- **Approach 2: WindMouse kết hợp Dự đoán vận tốc mục tiêu (Selected by User)**
  - Bao gồm sửa lỗi Approach 1, cộng thêm bộ ước lượng vector vận tốc $(\vec{v}_x, \vec{v}_y)$ có bộ lọc EMA và bù trừ tọa độ đón đầu.
  - *Trade-off:* Cần bổ sung thuật toán quản lý trạng thái vận tốc nhưng đảm bảo tâm dính chặt 100% vào đầu đối phương khi đang di chuyển.

## 5. Technical Specification
### A. Velocity Estimation & Lead-In (Target Tracking)
- Maintain target state `(last_target_x, last_target_y, last_time, filtered_vx, filtered_vy)`.
- When the same target updates between frames:
  - $\Delta t = \text{current\_time} - \text{last\_time}$
  - Instantaneous velocity: $v_{x, \text{inst}} = \frac{\Delta x}{\Delta t}, \quad v_{y, \text{inst}} = \frac{\Delta y}{\Delta t}$
  - Smooth velocity using EMA: $v_{\text{filt}} = \alpha \cdot v_{\text{inst}} + (1 - \alpha) \cdot v_{\text{filt}}$ (with $\alpha \approx 0.65$)
  - Apply lead prediction: $\text{dest}_x = \text{target}_x + v_{x, \text{filt}} \cdot t_{\text{lead}}$, where $t_{\text{lead}} \approx 0.025 - 0.035\,\text{s}$ (compensating capture, inference, and mouse queue latency).

### B. Intelligent Target Switching Detection
- Only trigger `reaction_delay` when switching to an entirely different target (target lost for $> 0.35\,\text{s}$ or sudden jump $> 120\,\text{px}$).
- Do NOT trigger reaction delay when tracking the same target moving continuously.

### C. Dynamic Velocity-Aware Close Range Scaling
- In `SmoothAiming.calculate_smooth_path`:
  - When target has high velocity, avoid slashing speed down to $30\%$. Keep dynamic speed scaling proportional to velocity so that mouse speed $\ge$ target speed.

### D. Sub-pixel Quantization & Accumulation
- In `_apply_smoothing_filters`:
  - Use residual carry accumulation for `dx` and `dy` instead of raw `int()` truncation to prevent dropping 1px steps.

## 6. What's Left to Builder
- Clean modular implementation in `src/aim_system/windmouse_smooth.py`.
- Unit tests verifying velocity tracking, zero freeze during continuous movement, and sub-pixel preservation.
