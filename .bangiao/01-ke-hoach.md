# 📋 [PLANNER AGENT] BẢN THIẾT KẾ BỘ CẤU HÌNH SEC AIM CHUYÊN BIỆT CHO VŨ KHÍ ONE-TAP (SHERIFF, GUARDIAN, MARSHAL)
**Mã hiệu:** `PLN-20261109-CVM-SEC-AIM-ONETAP`  
**Vai trò:** Chief Architect & Lead Planner (Agency Agent Pipeline)  
**Mô hình vận hành:** `gpt-6-sol` (Headless Read-Only Planning Mode)  
**Mục tiêu:** Xây dựng hệ thống cấu hình Sec Aimbot tối ưu chuyên biệt cho lối bắn tap 1 viên vào đầu bằng Sheriff, Guardian, Marshal trong Valorant.

---

## 1. Phân Tích Đặc Thù Động Học Vũ Khí One-Tap

Khác biệt bản chất giữa **Súng sấy / Burst (Vandal, Phantom)** và **Súng One-Tap (Sheriff, Guardian, Marshal)**:

| Tiêu chí | Main Aimbot (Vandal / Phantom) | Sec Aimbot One-Tap (Sheriff / Guardian / Marshal) |
| :--- | :--- | :--- |
| **Lối bắn** | Sấy nhiều viên, kéo ghìm tâm theo nhịp recoil | Click 1 viên duy nhất, yêu cầu đầu đạn trúng ngay tức khắc |
| **Bán kính FOV** | Rộng ($22 - 35\text{px}$) để theo dõi kẻ địch đang chạy | **Gọn gàng ($26 - 28\text{px}$)** để chỉ kích hoạt khi đã kê tâm gần đầu |
| **Thời gian phản xạ** | $35 - 70\text{ms}$ (mô phỏng người thật ghìm súng) | **Cực nhanh: $12 - 25\text{ms}$** (bắt kịp khoảnh khắc đối thủ ló đầu) |
| **Độ thẳng quỹ đạo** | Lượn sóng nhẹ (`wm_wind = 3.0`) để tự nhiên | **Thẳng tắp (`wm_wind = 1.0`, `wm_gravity = 11.0`)** như tia laser |
| **Tốc độ áp sát ($< 30\text{px}$)** | $55\%$ (chống giật nảy) | **$80\%$ (Snap tức thì vào đầu trong $1 - 2$ frame)** |
| **Phím kích hoạt** | Toggle / Phím phụ | **Giữ chuột phải (`Right Mouse Button` - Hold to lock)** |

---

## 2. Kế Hoạch Kiến Trúc & Cải Tiến Mã Nguồn

### 2.1. Phân tách hồ sơ động học trong `_WindMouseConfig` (`src/aim_system/normal.py`)
Hiện tại, `_WindMouseConfig` đang dùng chung các tham số động học nội tại (`smooth_reaction_min`, `smooth_close_speed`, `smooth_acceleration`,...) cho cả Main và Sec.
- **Kế hoạch:** Tách riêng nhánh `if is_sec:` trong `_WindMouseConfig`:
  - `smooth_reaction_min = 0.012`, `smooth_reaction_max = 0.026` (giảm độ trễ khởi động xuống 3 lần).
  - `smooth_close_speed = 0.80` (tăng tốc độ khóa đầu cận đích).
  - `smooth_max_step_ratio = 0.28`.
  - `smooth_acceleration = 0.80`, `smooth_deceleration = 0.70`.
  - `smooth_wind = 1.0` (giảm thiểu độ cong quỹ đạo, snap thẳng góc).
  - `smooth_gravity = 11.0` (lực hút tâm điểm cực mạnh).

### 2.2. Thiết lập thông số Sec Aim chuẩn thi đấu One-Tap trong cấu hình
- `fovsize_sec`: `28.0` (vừa vặn bao quanh vùng đầu khi kê góc).
- `normal_x_speed_sec`: `105.0` (flick ngang cực bén).
- `normal_y_speed_sec`: `52.0` (khóa chuẩn tầm mắt, không nảy cao).
- `normalsmooth_sec`: `4` (loại bỏ sức ỳ).
- `normalsmoothfov_sec`: `28.0`.
- `aim_offsetY_sec`: `0` (chuẩn tâm mặt kết hợp thuật toán $11\%$ đã tối ưu).
- `selected_mouse_button_sec`: `1` (Right Mouse Button).
- `aimbot_activation_type_sec`: `"hold_enable"` (Đè chuột phải là tâm tự động hút dính đầu).
- `mode_sec`: `"WindMouse"`.

### 2.3. Tạo Preset chuyên dụng & Đồng bộ hệ thống
- Tạo tệp cấu hình mới: `configs/onetap_sheriff_guardian_marshal.json`.
- Cập nhật đồng bộ vào `config.json` và các profile hiện hành.
