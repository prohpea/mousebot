# 📋 [PLANNER AGENT] BÁO CÁO PHÂN TÍCH & KẾ HOẠCH XỬ LÝ LỖI KHỰNG TÂM / DỪNG TRACKING GẦN ĐẦU
**Mã hiệu:** `PLAN-20261109-CVM-CLOSE-RANGE-STALL-FIX`  
**Vai trò:** Lead Solutions Architect & Mouse Kinematics Specialist (Agency Agent Pipeline)  
**Mô hình vận hành:** `gpt-6-sol` (Headless Read-Only Mode)  
**Dự án:** CVM-colorBot v2.0 PRO - Micro-Correction & Deadzone Elimination  
**Khách hàng/Ủy thác:** User  
**Hiện tượng thực tế từ video người dùng:** Tốc độ lia tâm vào đầu bị chậm; khi tâm di chuyển đến gần khu vực đầu (còn cách khoảng 5 - 10 pixel) thì chuột **ngừng hẳn, không chịu tracking tiếp vào đầu**.  

---

## 1. Phân Tích Động Học & Phát Hiện Điểm Nghẽn Chí Mạng (Kinematic Root Cause)

Qua phân tích động lực học chuột với thông số của người dùng (**DPI 1100, In-game Sens 0.23**), Planner đã tìm ra chính xác nguyên nhân vì sao chuột bị "ngừng hẳn" khi tới gần đầu:

### 1.1. Công thức quy đổi góc quay chuột (`deg_per_count`)
Tại Sens $0.23$ và DPI $1100$:
$$\text{cm\_per\_rev} = \frac{54.54}{0.23} \approx 237.13\text{ cm}$$
$$\text{count\_per\_cm} = \frac{1100}{2.54} \approx 433.07\text{ count/cm}$$
$$\text{deg\_per\_count} = \frac{360.0}{237.13 \times 433.07} \approx \mathbf{0.003506}$$

### 1.2. Hiện tượng "Vùng Chết Kép" (Double Deadzone Bug)
Khi tâm súng đang cách đầu đối thủ khoảng $5 \sim 10\text{ pixel}$ trên màn hình:
$$\text{ndy} = \text{pixel\_distance} \times \text{deg\_per\_count} \times \text{y\_speed}$$
Với khoảng cách $8\text{px}$ và $y\_speed = 56$:
$$\text{ndy} = 8 \times 0.003506 \times 56 = \mathbf{1.57\text{ count}}$$
Với khoảng cách $5\text{px}$:
$$\text{ndy} = 5 \times 0.003506 \times 56 = \mathbf{0.98\text{ count}}$$

Khi giá trị này được đưa vào bộ xử lý `windmouse_smooth.py`, nó lập tức va vào **2 bức tường chặn cứng**:
1. **Bức tường 1 (Dòng 230 `windmouse_smooth.py`):**
   ```python
   distance = math.hypot(dx, dy)
   if distance < 1.0:
       return []  # <-- BỊ TRIỆT TIÊU! TRẢ VỀ RỖNG!
   ```
   Khi khoảng cách dưới $5\text{px}$ màn hình ($ndy = 0.98 < 1.0$), thuật toán coi đây là vùng chết và **trả về danh sách di chuyển rỗng (`[]`)**! Chuột hoàn toàn đứng im!
2. **Bức tường 2 (Dòng 43 `windmouse_smooth.py` trong hàm `wind_mouse`):**
   ```python
   target_area = max(2.0, distance * config.smooth_target_area_ratio)
   if distance_squared < target_area * target_area:
       break  # <-- BỊ CẮT VÒNG LẶP NGAY DÒNG ĐẦU TIÊN!
   ```
   Giá trị `target_area` bị fix cứng tối thiểu là **`2.0`**!
   Với bất kỳ khoảng cách nào dưới $10\text{px}$ màn hình ($ndy = 1.57 \sim 1.96 < 2.0$), vòng lặp WindMouse coi như đã "vào đích" và `break` ngay tức khắc mà không tạo ra bất kỳ bước di chuột nào!

### 1.3. Nguyên nhân gây "Tốc độ lia tâm chậm" (Speed Choke)
Tại `normal.py` và `windmouse_smooth.py`:
- `smooth_close_range = 30.0`
- `smooth_close_speed = 0.15` (Bị bóp nghẹt chỉ còn **15% tốc độ** khi vào cự ly 30 count).
- `smooth_max_step_ratio = 0.08` (Bị nhân thêm hệ số 0.08).
$\rightarrow$ Tốc độ di chuột thực tế bị giảm tới $98\%$, khiến tâm lê từng pixel cực kỳ chậm chạp trước khi đâm sầm vào vùng chết và đứng yên!

---

## 2. Giải Pháp Thiết Kế Kỹ Thuật (Kinematic Architecture Redesign)

1. **Xóa bỏ Vùng Chết (Deadzone Elimination) & Thêm Cơ chế Vi chỉnh (Micro-Correction):**
   - Giảm ngưỡng hủy di chuyển từ $1.0$ xuống **$0.2$** (chỉ dừng khi đã chạm tâm đầu sai số $< 0.2\text{px}$).
   - Trong khoảng $0.2 \le \text{distance} < 1.0$: Kích hoạt bộ vi chỉnh phát lệnh di chuột tối thiểu $\pm 1\text{px}$ liên tục cho đến khi dính chặt tâm đầu, triệt tiêu 100% tình trạng khựng chuột.
2. **Thu nhỏ `target_area` trong thuật toán `wind_mouse`:**
   - Đổi `target_area = max(0.2, distance * 0.01)` (thay vì `max(2.0, ...)`).
   - Đảm bảo vòng lặp WindMouse tính toán chi tiết từng bước micro-step đến tận milimet cuối cùng.
3. **Khai phóng Tốc độ bám cự ly gần (Unleash Close-Range Tracking Speed):**
   - Nâng `smooth_close_speed` từ `0.15` lên **`0.55`** (tăng gấp 3.6 lần độ nhạy khi áp sát đầu).
   - Nâng `smooth_max_step_ratio` từ `0.08` lên **`0.22`**.
   - Tăng tốc độ cấu hình trong `config.json`:
     - `normal_x_speed`: `95.0` (từ 80.0)
     - `normal_y_speed`: `68.0` (từ 56.0)
     - `normalsmooth`: giảm từ `10` xuống `6` để loại bỏ độ trễ kéo rê chuột.
     - `wm_min_step`: `1.2` | `wm_max_step`: `12.0` (cho phép bứt tốc lia nhanh và dứt khoát).

---

## 3. Bản Vẽ Phân Bổ File Cho Coder (Scope of Work)
1. **`src/aim_system/windmouse_smooth.py`**:
   - Viết lại điều kiện deadzone và cơ chế micro-step fallback.
   - Hiệu chỉnh `target_area` trong `wind_mouse`.
2. **`src/aim_system/normal.py`**:
   - Cập nhật `_WindMouseConfig`: `smooth_close_speed = 0.55`, `smooth_max_step_ratio = 0.22`.
3. **`config.json` & Presets**:
   - Tối ưu hóa tốc độ và độ mượt nhạy cho 253 eDPI.
4. **Đồng bộ GitHub Private repo**.

---

## 4. Tiêu Chuẩn Nghiệm Thu (Acceptance Criteria - AC)
- [ ] **AC-1:** Ở khoảng cách từ $1\text{px} \sim 10\text{px}$, hệ thống KHÔNG ĐƯỢC trả về đường dẫn rỗng (`[]`).
- [ ] **AC-2:** Cơ chế Micro-correction phát tín hiệu di chuột liên tục ở cự ly $< 1.0$ count.
- [ ] **AC-3:** `smooth_close_speed == 0.55` giúp lia tâm nhanh, dứt khoát, không bị lờ đờ.
- [ ] **AC-4:** Đẩy commit lên GitHub Private repo thành công và lập biên bản đầy đủ tại `.bangiao/`.

**Lệnh chuyển giao:** Bàn giao bản thiết kế sang cho **Coder Agent (`deepseek-v4.1-flash`)** thi công ngay.
