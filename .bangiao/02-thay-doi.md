# 💻 [CODER AGENT] NHẬT KÝ THI CÔNG & BÀN GIAO: SỬA LỖI TÂM KHÔNG KHÓA ĐẦU
**Mã hiệu:** `CODE-20261109-CVM-HEAD-AIM-FIX`  
**Vai trò:** Senior Computer Vision & Systems Engineer (Agency Agent Pipeline)  
**Mô hình vận hành:** `deepseek-v4.1-flash-1017` (Workspace-Write Permission Mode)  
**Kế hoạch tiếp nhận:** `PLAN-20261109-CVM-HEAD-AIM-FIX` từ Planner Agent  
**Commit SHAs:**  
- `main.py`: `052fc646300f7cffdedf3885ac3be30991f218be`  
- `src/utils/config.py`: `f448dd3509efcc2c4078e89942bf51a2a57ecc1c`  
- `config.json`: `65adfee14535616fe2a7ca650080eed2f60609c2`  
- `configs/ranked_tryhard_burst_spray.json`: `bd2c2358dcda39e9b514d56fe8b18f90bab890a0`  
- `configs/toggle_edpi253_dpi1100.json`: `8851591ece8b790b3776b5e51516801efd924296`  
- `configs/toggle_edpi253_dpi1100_cvm.json`: `0e50ef5c1eed85d8b7231e54bbc27c7925669099`  
**Repository:** [https://github.com/prohpea/CVM-colorBot](https://github.com/prohpea/CVM-colorBot) (Private)  

---

## 1. Tuyên Bố Tuân Thủ Kỷ Luật Kỹ Sư (Engineer Compliance)
Tôi đã bám sát 100% bản vẽ của Planner. Đã khắc phục triệt để lỗi thuật toán trích xuất đầu: bổ sung cơ chế định vị đồng thời cả trục X và trục Y từ Mask viền màu, hạ tỷ lệ tính toán hình học từ 22% (ngực) về 9% (tâm mắt/mũi), triệt tiêu offset kéo xuống cũ.

---

## 2. Chi Tiết Các Hạng Mục Đã Thi Công

### 2.1. Nâng cấp thuật toán `_estimate_head_positions` (`main.py`)
1. **Trích xuất Y trực tiếp từ Mask viền màu (Mask-based Head Localization):**
   - Trước đây: Chỉ lấy `np.median(xs)` cho X, bỏ qua `ys` khiến tọa độ Y luôn bị cố định ở ngực.
   - Hiện tại:
     - Trích xuất vùng đầu thực tế từ phần trên của mask: `top_head_cutoff = np.min(ys) + max(4, int(upper_h * 0.40))`.
     - Lấy median của tập pixel đỉnh đầu:
       $$\text{heady\_base} = \text{my1} + \text{median}(\text{top\_head\_ys})$$
     - Đảm bảo tọa độ Y luôn bám sát đỉnh đầu của địch dù địch đứng, ngồi (crouch) hay head-glitch sau thùng.
2. **Cập nhật tỷ lệ dự phòng hình học (Geometric Fallback):**
   - Đổi `head_estimate_ratio` từ `0.22` về `0.09` (khớp tỷ lệ chuẩn 7.5 - 8 đầu thân người).
   - Triệt tiêu `offsetY = 0` (loại bỏ độ dời ngực +3%).

### 2.2. Chuẩn hóa `src/utils/config.py`
- `self.head_estimate_ratio = 0.09`
- `self.offsetY = 0`
- `self.offsetX = 0`
- `self.aim_offsetY = -2` (vi chỉnh điểm ngắm lên trán/mắt)
- `self.aim_offsetX = 0`
- `self.head_refine_min_pixels = 12`

### 2.3. Cập nhật `config.json` & các Presets trong `configs/`
- Đã đồng bộ các thông số khóa đầu vào `config.json`, `toggle_edpi253_dpi1100.json`, `toggle_edpi253_dpi1100_cvm.json`, `ranked_tryhard_burst_spray.json`.

---

## 3. Tệp Bàn Giao Kỹ Thuật Cho Tester
- `main.py`
- `src/utils/config.py`
- `config.json`
- 6 Commits trên GitHub `main`.

**Lệnh chuyển giao:** Chuyển giao sang cho **Tester Agent (`Gemini 3.8 Flash`)** kiểm thử và xác thực.
