# 📋 [PLANNER AGENT] BẢN THIẾT KẾ & KẾ HOẠCH KHẮC PHỤC LỖI TÂM KÉO QUÁ CAO (HEAD LOCK OVERSHOOT)
**Mã hiệu:** `PLN-20261109-CVM-AIM-OVER-HEAD-FIX`  
**Vai trò:** Chief Architect & Lead Planner (Agency Agent Pipeline)  
**Mô hình vận hành:** `gpt-6-sol` (Headless Read-Only Planning Mode)  
**Tệp mục tiêu:** `main.py`, `src/utils/config.py`, `config.json`, `configs/*.json`

---

## 1. Bản Chất Kỹ Thuật Của Hiện Tượng "Kéo Quá Cao"

Người dùng phản ánh: *"giờ thì lại kéo quá cao"*.  
Sau khi thẩm tra toàn diện luồng tính toán tọa độ đích $Y$ (`cy`) và động học di chuyển chuột trục dọc:

### 1.1. Lỗi định vị đỉnh đầu thay vì tâm đầu (`main.py` dòng 918-924)
- Trong hàm `_estimate_head_positions`:
  ```python
  top_head_cutoff = np.min(ys) + max(4, int(upper_h * 0.40))
  top_head_ys = ys[ys <= top_head_cutoff]
  if len(top_head_ys) > 0:
      heady_base = float(my1 + np.median(top_head_ys))
  ```
- Biến `np.min(ys)` là dòng pixel có màu tím/vàng **cao nhất** của nhân vật (chóp nón / đỉnh tóc).
- Việc lọc `ys <= top_head_cutoff` rồi lấy `np.median(top_head_ys)` dẫn tới việc `heady_base` được neo cứng vào khoảng cách chỉ $2 - 4\text{px}$ bên dưới mép trên của bounding box.
- Trong Valorant, chiều cao cơ thể người từ đỉnh đầu đến cằm chiếm khoảng $15\% - 18\%$ tổng chiều cao cơ thể. Tâm điểm của hitbox đầu (mũi / mắt / miệng) nằm ở cự ly khoảng **$11\% - 14\%$ tính từ đỉnh đầu**.
- Việc gán `heady_base` ở vị trí sát rạt đỉnh tóc khiến tâm ngắm bị kéo lên đỉnh đầu hoặc lơ lửng bên trên đầu địch trong không trung!

### 1.2. Giá trị âm của `aim_offsetY` gây kéo ngược lên trời
- Trong `src/aim_system/normal.py`:
  $$dy = (cy + \text{aim\_offsetY}) - \text{center\_y}$$
- Hệ tọa độ màn hình Windows: gốc $(0,0)$ ở góc trên bên trái, trục $Y$ càng nhỏ thì càng hướng lên đỉnh màn hình (trời).
- Hiện tại cấu hình mặc định đang đặt:
  $$\text{aim\_offsetY} = -2, \quad \text{aim\_offsetY\_sec} = -4$$
- Giá trị âm đã vô tình **trừ thêm 2 đến 4 pixel** theo trục $Y$, đẩy điểm ngắm lên cao hơn nữa ra ngoài hitbox đầu địch!

### 1.3. Vận tốc trục dọc quá lớn (`normal_y_speed = 68.0`) tạo quán tính vượt đỉnh (Overshoot)
- Trong Valorant, kẻ địch chủ yếu di chuyển ngang (A-D strafe). Biên độ di chuyển trục dọc rất hẹp ($5\text{px} - 15\text{px}$).
- Việc đẩy `normal_y_speed` lên $68.0$ kết hợp với lực hút trọng trường WindMouse khiến gia tốc trục $Y$ tăng vọt, chuột bị "văng" vượt qua đầu trước khi kịp hãm tốc.

---

## 2. Kế Hoạch Cải Tiến Kỹ Thuật (Specification)

### 2.1. Tái cấu trúc hàm tinh chỉnh tọa độ đầu trong `main.py`
- Thay vì lấy trung vị của các pixel sát mép đỉnh nón/tóc:
  - Xác định `head_top = np.min(ys)` (đỉnh viền đầu).
  - Tính khoảng cách từ đỉnh đầu xuống tâm đầu thực tế:
    $$\Delta y_{\text{head\_center}} = \max(3.0, \text{height} \times 0.11)$$
  - Tọa độ tâm đầu chuẩn xác:
    $$\text{heady\_base} = \text{my1} + \text{head\_top} + \Delta y_{\text{head\_center}}$$
  - Đồng thời cho phép áp dụng bù trừ người dùng nếu có (`offset_y`).
- Cập nhật tỷ lệ ước tính hình học mặc định `head_estimate_ratio` từ `0.09` lên `0.13` (phòng trường hợp không có mask).

### 2.2. Chuẩn hóa `aim_offsetY` về giá trị cân bằng
- Đổi `aim_offsetY = 0` (hoặc `+1` để hơi ghìm về phía cằm/cổ, tối ưu cho burst/spray chống giật đạn).
- Đổi `aim_offsetY_sec = 0`.

### 2.3. Điều chỉnh vận tốc trục dọc `normal_y_speed`
- Giảm `normal_y_speed` từ `68.0` xuống **`48.0`** (giữ nguyên `normal_x_speed = 95.0`).
- Giúp trục dọc di chuyển đầm chắc, triệt tiêu hoàn toàn hiện tượng văng vượt quá đầu.

---

## 3. Danh Mục File Can Thiệp
1. `main.py`: Cập nhật logic `_estimate_head_positions`.
2. `src/utils/config.py`: Chuẩn hóa default `aim_offsetY = 0`, `head_estimate_ratio = 0.13`.
3. `config.json`: Đặt `aim_offsetY: 0`, `aim_offsetY_sec: 0`, `normal_y_speed: 48.0`, `head_estimate_ratio: 0.13`.
4. `configs/*.json`: Đồng bộ toàn bộ các profile cấu hình hiện hành.
