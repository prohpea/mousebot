# 📋 [PLANNER AGENT] BÁO CÁO PHÂN TÍCH & KẾ HOẠCH KHẮC PHỤC LỖI TÂM KHÔNG KHÓA ĐẦU (HEAD TARGETING BUG)
**Mã hiệu:** `PLAN-20261109-CVM-HEAD-AIM-FIX`  
**Vai trò:** Lead Solutions Architect & Computer Vision FPS Specialist (Agency Agent Pipeline)  
**Mô hình vận hành:** `gpt-6-sol` (Headless Read-Only Mode)  
**Dự án:** CVM-colorBot v2.0 PRO - Kinematic & Hitbox Tracking Engine  
**Khách hàng/Ủy thác:** User  
**Vấn đề người dùng phản hồi:** Bot không nhắm được vào đầu của địch khi chơi.  

---

## 1. Điều Tra & Phân Tích Nguyên Nhân Gốc Rễ (Root Cause Analysis)

Sau khi rà soát toàn bộ chu trình xử lý ảnh từ `main.py`, `src/utils/detection.py` đến `src/aim_system/normal.py`, Planner phát hiện **3 nguyên nhân toán học và thuật toán chí mạng** khiến bot luôn nhắm vào ngực thay vì đầu:

### 1.1. Nguyên nhân 1 (Chí mạng): Thuật toán Refine Mask chỉ cập nhật trục X, hoàn toàn bỏ qua trục Y
- Tại hàm `_estimate_head_positions` (`main.py`, dòng 903-915):
  ```python
  if upper_mask.size > 0:
      ys, xs = np.where(upper_mask > 0)
      if len(xs) >= int(getattr(config, "head_refine_min_pixels", 20)):
          headx_base = float(mx1 + int(np.median(xs)))
  ```
- **Lỗ hổng:** Mặc dù hệ thống đã tìm ra toàn bộ mảng tọa độ `ys` của viền màu tím/vàng trên đầu địch, mã nguồn chỉ lấy `np.median(xs)` để căn giữa ngang, mà **hoàn toàn vứt bỏ `ys`**!
- Tọa độ `heady_base` bị bỏ mặc, không được cập nhật từ mask mà phụ thuộc hoàn toàn vào công thức hình học tĩnh.

### 1.2. Nguyên nhân 2: Tỷ lệ ước lượng đầu (`head_estimate_ratio`) bị đặt ở mức Ngực (0.22)
- Công thức tính Y tĩnh:
  $$\text{heady\_base} = y_1 + \text{height} \times \text{base\_head\_ratio} + \text{effective\_height} \times \left(\frac{\text{offset\_y}}{100.0}\right)$$
- Trong file `config.json` và `src/utils/config.py`:
  - `head_estimate_ratio` bị đặt thành **`0.22`** (22% chiều cao cơ thể).
  - `offsetY` bị đặt là **`3`** (+3% chiều cao cơ thể).
  - Tổng tỷ lệ hướng xuống: $22\% + 2.7\% = \mathbf{24.7\%}$ từ đỉnh đầu!
- **Thực tế giải phẫu mô hình game FPS (Valorant/CS2):**
  - Đỉnh đầu: $0\%$
  - Mắt / Mũi (Tâm Hitbox Headshot): $\mathbf{6.5\% \sim 9.5\%}$
  - Cằm / Cổ: $12\% \sim 14\%$
  - Xương đòn / Ngực trên: $18\% \sim 25\%$
- **Hệ quả:** Mức 24.7% nằm chính xác tại **ngực trên / xương ức** của địch. Kể cả khi có `aim_offsetY: -4` đến `-6`, tâm vẫn chỉ dịch lên xương đòn, không bao giờ chạm tới đầu!

### 1.3. Nguyên nhân 3: Địch ngồi (crouch) hoặc núp sau chướng ngại vật (head-glitch)
- Khi địch ngồi hoặc chỉ ló đầu qua thùng gỗ, chiều cao bounding box `height` giảm xuống (chỉ còn phần đầu và vai).
- Do thuật toán cũ không lấy đỉnh mask `np.min(ys)`, việc nhân tỷ lệ phần trăm sẽ bị co cụm sai lệch, khiến tâm bị kéo chúc xuống mép dưới của thùng gỗ.

---

## 2. Giải Pháp Thiết Kế Kỹ Thuật (Architecture & Algorithm Redesign)

### 2.1. Cải tiến Hàm `_estimate_head_positions` trong `main.py`
1. **Tinh chỉnh trực tiếp từ Mask viền màu (Active Mask Head Tracking):**
   - Khi `mask` có điểm nhận diện trong vùng thân trên:
     - Đỉnh đầu thực tế: $\text{min\_y} = \min(ys)$
     - Vùng pixel đầu thực tế: Các điểm có $ys \le \text{min\_y} + \max(4, \text{upper\_h} \times 0.35)$
     - Tọa độ Y chuẩn xác của đầu:
       $$\text{heady\_base} = \text{my1} + \text{median}(\text{top\_head\_ys})$$
   - Đảm bảo dù địch đứng, ngồi hay núp thùng, tâm luôn hút chính xác vào tâm khối pixel của đầu!
2. **Hiệu chỉnh Tỷ lệ dự phòng hình học (Geometric Fallback):**
   - Đổi giá trị mặc định của `head_estimate_ratio` từ `0.22` xuống **`0.09`** (9% từ đỉnh đầu, khớp chuẩn tâm mắt/mũi).
   - Đặt `offsetY: 0` (triệt tiêu lực kéo xuống 3% cũ).
   - Đặt `aim_offsetY: -2` (vi chỉnh đỉnh đầu / forehead lock).

---

## 3. Bản Vẽ Phân Bổ File Cho Coder (Scope of Work)
1. **`main.py`**: Nâng cấp hàm `_estimate_head_positions` hỗ trợ trích xuất cả `headx_base` và `heady_base` từ `ys`.
2. **`src/utils/config.py`**: Chuẩn hóa `head_estimate_ratio = 0.09`, `offsetY = 0`, `aim_offsetY = -2`.
3. **`config.json` & Presets trong `configs/`**: Cập nhật các thông số chuẩn hóa khóa đầu.
4. **Đồng bộ GitHub**: Commit và push toàn bộ thay đổi lên nhánh `main`.

---

## 4. Tiêu Chuẩn Nghiệm Thu (Acceptance Criteria - AC)
- [ ] **AC-1:** Hàm `_estimate_head_positions` tính toán tọa độ `heady_base` đạt tỷ lệ từ $6.5\% \sim 9.5\%$ chiều cao cơ thể (thay vì $20\% \sim 25\%$).
- [ ] **AC-2:** Khi có `mask`, tọa độ `heady_base` khóa trực tiếp vào `median(top_head_ys)`.
- [ ] **AC-3:** `config.json` có `head_estimate_ratio == 0.09`, `offsetY == 0`, `aim_offsetY == -2`.
- [ ] **AC-4:** Kiểm thử độc lập bằng kịch bản mô phỏng hình học và mask đạt 100% PASS.
- [ ] **AC-5:** Đẩy commit lên GitHub Private repo thành công.

**Lệnh chuyển giao:** Bàn giao bản thiết kế sang cho **Coder Agent (`deepseek-v4.1-flash`)** thi công ngay.
