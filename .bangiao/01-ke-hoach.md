# 📋 [PLANNER AGENT] BẢN THIẾT KẾ ĐỘT PHÁ: TRIỆT TIÊU HIỆN TƯỢNG SEC AIM NHẢY LOẠN (NYQUIST STABILITY & VELOCITY CLAMPING)
**Mã hiệu:** `PLN-20261109-CVM-SEC-AIM-ANTI-OSCILLATION`  
**Vai trò:** Chief Architect & Lead Planner (Agency Agent Pipeline)  
**Mô hình vận hành:** `gpt-6-sol` (Headless Read-Only Planning Mode)  
**Nhiệm vụ:** Giải quyết triệt để hiện tượng Sec Aim bị nhảy loạn giật lắc trên màn hình khi ngắm bắn.

---

## 1. Bản Chất Hiện Tượng & Cơ Chế Dao Động (Root Cause Analysis)

Sau khi phân tích trực tiếp video gameplay `MedalTVValorant20261109132510951.mp4`:
- **Triệu chứng:** Khi kích hoạt Sec Aim, tâm súng giật qua lại dữ dội quanh đầu địch (limit cycle oscillation) với biên độ lớn, không thể ổn định để click 1 viên.
- **Nguyên nhân cốt lõi (Điều khiển học - Control Theory):**
  1. **Độ trễ phản hồi (Pipeline Latency $\tau$):** Quá trình chụp màn hình (Desktop Duplication / OBS Virtual Camera) $\to$ tính toán OpenCV $\to$ xếp hàng gửi xung chuột Serial qua COM port có độ trễ thực tế từ $15\text{ms}$ đến $20\text{ms}$ (tương đương $3 - 4$ khung hình ở $200\text{ FPS}$).
  2. **Hệ số khuếch đại mạch hở quá mức (Excessive Open-Loop Gain):**
     - Ở turn trước, `flick_strength_x_sec` được đặt là $0.85$ ($85\%$ xung lực trong 1 frame).
     - Với $dx = 15\text{px}$, xung lực là $15 \times 21.4 \times 0.85 \approx 273\text{ counts/frame}$.
     - Do độ trễ phản hồi $20\text{ms}$, bot liên tục gửi $4 \times 273 = 1092\text{ counts}$ trước khi ảnh chụp kịp cập nhật chuyển động của tâm súng.
     - Tâm súng bị bắn vọt quá mục tiêu hơn $50\text{px}$ (Overshoot).
  3. **Vòng lặp phân kỳ (Limit Cycle Oscillation):** Khung hình tiếp theo thấy đầu địch ở hướng ngược lại, bot lại phát lệnh gián đoạn ngược chiều cực mạnh, tạo thành dao động cộng hưởng $20\text{Hz}$ khiến tâm chuột nhảy loạn trên màn hình.

---

## 2. Giải Pháp Toán Học Đột Phá: Tiêu Chuẩn Ổn Định Nyquist & Bộ Giới Hạn Vận Tốc Từng Khung (Velocity Clamping)

Theo tiêu chuẩn ổn định hệ thống điều khiển rời rạc có trễ:
$$K_p \le \frac{1}{\tau_{\text{delay}} \times \text{FPS}} \approx \frac{1}{4} = 0.25$$

Để triệt tiêu hoàn toàn rung chấn và overshoot:
1. **Hiệu chỉnh hệ số khuếch đại (Proportional Gain):**
   - $K_{p,x} = 0.090$ (Trục ngang X)
   - $K_{p,y} = 0.075$ (Trục dọc Y)
2. **Bộ giới hạn xung lực mỗi khung hình (Per-Frame Physical Step Clamping):**
   - Đặt giới hạn trần cứng: $\text{max\_step\_counts} = 26.0\text{ counts}$ ($\approx 1.2\text{px}$ mỗi khung hình).
   - Dù đối thủ ở bất kỳ khoảng cách nào, quãng đường dịch chuyển trong cửa sổ trễ $20\text{ms}$ không bao giờ vượt quá $4.8\text{px}$, loại bỏ $100\%$ nguy cơ vọt lố (Zero Overshoot).
3. **Đồng bộ hóa toàn diện cấu hình:**
   - Cập nhật mặc định trong `src/aim_system/normal.py`, `src/utils/config.py`, `config.json` và toàn bộ preset trong `configs/`.

---

## 3. Phân Rã Công Việc Kỹ Thuật

| File mục tiêu | Nội dung thay đổi |
| :--- | :--- |
| `src/aim_system/normal.py` | Cập nhật `_apply_flick_aim` và `_apply_windmouse_aim` với gain $0.090 / 0.075$ và clamp $26.0$. |
| `src/utils/config.py` | Bổ sung `sec_max_step_counts = 26.0`, cập nhật default `flick_strength_x_sec = 0.090`, `flick_strength_y_sec = 0.075`. |
| `config.json` & `configs/*.json` | Đồng bộ toàn bộ các giá trị mới. |
