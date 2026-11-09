# 🛠️ [CODER AGENT - DEEPSEEK v4.1 FLASH] NHẬT KÝ THI CÔNG KIẾN TRÚC FLICK AIM V2
**Mã hiệu:** `COD-20261109-FLICK-BALLISTICS-V2`  
**Mô hình thi công:** `deepseek-v4.1-flash-1017` via DeepSeek Harness (`dsh`)  
**Tài liệu thiết kế:** `.bangiao/01-ke-hoach.md`  
**Trạng thái:** Thi công hoàn tất 10-bước chuẩn xác theo kiến trúc.

---

## 1. Danh Sách Các Module Đã Tạo Mới & Sửa Đổi

### 1.1. Module Mới: `src/aim_system/aim_math.py`
- **Nguồn chân lý duy nhất (Single Source of Truth)** cho toàn bộ quy đổi pixel → count chuột:
  - `FrameGeometry`: Tính toán tiêu cự `fx, fy` từ kích thước frame thực và horizontal FOV. Bảo toàn hình học khi frame bị crop (crop FOV tỷ lệ với crop resolution).
  - `Calibration`: Hỗ trợ 2 cơ chế:
    - `analytic`: Tính toán giải tích từ `sens` và `dpi`.
    - `measured`: Dựa trên số đo góc quay thực nghiệm (`counts_per_deg_x/y`).
  - `resolve_geometry(tracker, frame)`: Trích xuất hình học từ khung hình thực tế (`frame.xres`, `frame.yres`) và cấu hình crop (OBS UDP / MSS / Capture Card).
  - `px_to_counts(...)`: Hàm chuẩn duy nhất chuyển sai lệch pixel `(dx, dy)` thành xung chuột `(cx, cy)` có góc chuẩn.
  - Các hàm tiện ích: `fit_calibration`, `counts_per_deg_from_slope`.

### 1.2. Module Mới: `src/aim_system/flick_controller.py`
- **FlickController (Bộ điều khiển vòng kín có ngân sách):**
  - **Gain vật lý = 1.0:** Loại bỏ núm cảm giác `strength` cũ.
  - **Scale cả vector giữ hướng (Direction-Preserving Vector Clamping):** Không cắt cụt độc lập từng trục $X/Y$ gây méo hướng flick.
  - **Residual Carry:** Tích lũy phần dư số thực của counts giữa các nhịp để không bao giờ nuốt sai số $<0.5$ count.
  - **Ngân sách hội tụ (Budget & Iterations):** Thay vì cooldown mù huỷ frame, controller cấp ngân sách tối đa `flick_budget_ms` (mặc định 120ms) và `flick_max_iterations` (mặc định 4 nhịp) để tâm ngắm tự sửa đến khi rơi vào `deadzone`.
  - **Bảo vệ Target-Key Drift:** Áp dụng `switch_radius_px = 64px`, tránh việc tâm ngắm dịch chuyển làm thay đổi target ID làm reset residual/budget.
  - Cơ chế `rollback_step()` khi queue đầy.

### 1.3. Cập Nhật `src/utils/config.py` & `config.json`
- **Schema tham số mới:**
  - `hfov_deg = 103.0`, `vfov_deg = 70.5`
  - `flick_gain = 1.0`, `flick_gain_sec = 1.0`
  - `flick_max_counts = 6000`, `flick_max_counts_sec = 6000`
  - `flick_max_iterations = 4`, `flick_budget_ms = 120.0`
  - `flick_deadzone_px = 1.5`, `flick_deadzone_px_sec = 2.0`
  - `counts_per_deg_x = None`, `counts_per_deg_y = None`
  - `max_speed = 6000` (được đưa vào schema chuẩn, loại bỏ fallback ma 1000)
  - `flick_engine = "v2"` (có cờ `"legacy"` để A/B rollback)
- **Tự động di chuyển (Migration):**
  - Tự động map `flick_strength_x/y` sang `flick_gain = 1.0` khi nâng cấp config cũ.
  - Kiểm tra và clamp phạm vi an toàn cho tất cả tham số.
  - Đồng bộ cập nhật toàn bộ profile mẫu trong `configs/`.

### 1.4. Cập Nhật `src/aim_system/mode_dispatcher.py` & `main.py`
- Khai báo metadata `_MODE_CAPS`:
  - `Flick`: `closed_loop: False`, `uses_smoother: False` $\to$ **Bypass hoàn toàn `TargetSmoother`**.
  - Flick nhận tọa độ thô từ khung hình hiện tại, không bị trễ bởi bộ lọc EMA.
- `main.py`:
  - Gắn tag định danh lệnh chuột trong `_process_move_queue` (`flick`, `rcs`, `track`, `calib`). Không gộp chéo lệnh flick với lệnh di chuột thường.
  - Vector clamping bảo toàn hướng ngắm.
  - Truyền `FrameInfo` thực tế vào pipeline tính toán.

### 1.5. Cập Nhật `src/aim_system/mode_flick.py` & `src/aim_system/normal.py`
- `mode_flick.py` trở thành adapter chính thức gọi `FlickController.step(...)`.
- `normal.py`:
  - Gộp 2 tầng offset thành 1 tầng duy nhất.
  - Khai tử hàm lỗi thứ nguyên `calculate_movement`.
  - Giữ `calculate_exact_counts` làm wrapper tương thích ngược trỏ vào `aim_math.px_to_counts`.

### 1.6. Bộ Unit Tests Mới
- `tests/test_aim_math.py`: Kiểm thử chuyển đổi pixel sang độ, kiểm thử bảo toàn góc quay khi crop FOV, đối xứng trục, và fit tuyến tính calibration.
- `tests/test_flick_controller.py`: Mô phỏng vòng đời flick, hội tụ trong deadzone, overshoot $\le 10\%$, bảo toàn residual, và thoát budget đúng hạn.
