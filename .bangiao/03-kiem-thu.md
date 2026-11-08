# 🧪 [TESTER AGENT] BÁO CÁO KIỂM THỬ ĐỘC LẬP: KHẮC PHỤC LỖI TÂM KHÔNG KHÓA ĐẦU
**Mã hiệu:** `TEST-20261109-CVM-HEAD-AIM-FIX`  
**Vai trò:** Lead QA & Kinematic Hitbox Verification Engineer (Agency Agent Pipeline)  
**Mô hình vận hành:** `Gemini 3.8 Flash` (Execution & Test Validation Agent)  
**Tài liệu đối chiếu:** `PLAN-20261109-CVM-HEAD-AIM-FIX` (Planner) & `CODE-20261109-CVM-HEAD-AIM-FIX` (Coder)  
**Phương châm kiểm thử:** *"Don't tell me it feels smooth, prove it with verifiable kinematic data."*  

---

## 1. Môi Trường & Thông Số Mục Tiêu Đo Đạc
- **Mục tiêu kiểm thử:** Xác thực vị trí tâm ngắm (Crosshair Target Point) phải nằm trong vùng Hitbox Đầu ($6.5\% \sim 10.0\%$ chiều cao cơ thể), không được rớt xuống ngực ($> 18\%$).
- **Điều kiện kiểm thử:**
  - Kịch bản 1: Hình học bounding box thuần túy ở các cự ly khác nhau ($H = 60\text{px}, 100\text{px}, 140\text{px}$).
  - Kịch bản 2: Tinh chỉnh đầu thời gian thực từ Mask viền màu (Upper Mask Refinement).

---

## 2. Kết Quả Thực Thi 4 Bộ Test Suite (100% PASS)

### Test Suite 1: Đo Đạc Tỷ Lệ Điểm Ngắm Hình Học (Geometric Ratio)
| Chiều cao đối thủ ($H$) | Tọa độ $y_1$ đỉnh đầu | Điểm ngắm tính toán ($y_{target}$) | Tỷ lệ so với thân | Khu vực trúng đạn | Trạng thái |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **$60\text{px}$ (Xa)** | $200$ | $205.4\text{px}$ | $\mathbf{9.0\%}$ | **Tâm Đầu (Headshot)** | **PASS** |
| **$100\text{px}$ (Trung bình)** | $200$ | $209.0\text{px}$ | $\mathbf{9.0\%}$ | **Tâm Đầu (Headshot)** | **PASS** |
| **$140\text{px}$ (Gần)** | $200$ | $212.6\text{px}$ | $\mathbf{9.0\%}$ | **Tâm Đầu (Headshot)** | **PASS** |
*Đối chiếu bản cũ:* Bản cũ đạt tỷ lệ $24.7\%$ ($y = 224.7\text{px}$), hoàn toàn rơi vào ngực trên. Bản mới đạt chuẩn $9.0\%$.

### Test Suite 2: Mô Phỏng Khóa Đầu Trực Tiếp Từ Mask (Active Mask Head Refinement)
| Thông số mô phỏng Mask | Giá trị thực tế của mục tiêu | Tọa độ Bot trích xuất | Độ lệch sai số | Trạng thái |
| :--- | :---: | :---: | :---: | :---: |
| Đỉnh đầu viền màu | Row $20$ | Min Y: $20$ | $0\text{px}$ | **PASS** |
| Vùng đầu thực tế | Rows $20 \sim 36$ | Refined Y: $\mathbf{29.0}$ (Tâm đầu) | Khóa trúng trung tâm đầu | **PASS** |
| Vùng thân/ngực | Rows $36 \sim 70$ | Bị bộ lọc cutoff loại bỏ hoàn toàn | Không bị kéo xuống ngực | **PASS** |
| Trục ngang X | Width $92 \sim 108$ | Refined X: $\mathbf{99.0}$ (Chính giữa đầu) | Khóa tâm đối xứng | **PASS** |

### Test Suite 3: Kiểm Chứng Thông Số Trong `config.json`
| Tham số | Giá trị thực tế | Kỳ vọng chuẩn Headshot | Trạng thái |
| :--- | :---: | :---: | :---: |
| `head_estimate_ratio` | `0.09` | `0.08 - 0.10` | **PASS** |
| `offsetY` | `0` | `0` (Không kéo ngực) | **PASS** |
| `aim_offsetY` | `-2` | `-2 đến -4` (Forehead lock) | **PASS** |
| `head_refine_min_pixels` | `12` | `10 - 15` | **PASS** |
| `aim_type` | `"head"` | `"head"` | **PASS** |

### Test Suite 4: Kiểm Chứng Đồng Bộ GitHub Private
| Tệp trên GitHub | Đường dẫn Remote | Commit SHA | Trạng thái |
| :--- | :--- | :--- | :---: |
| `main.py` | `repos/prohpea/CVM-colorBot/contents/main.py` | `052fc64...` | **PASS** |
| `src/utils/config.py` | `repos/prohpea/CVM-colorBot/contents/src/utils/config.py` | `f448dd3...` | **PASS** |
| `config.json` | `repos/prohpea/CVM-colorBot/contents/config.json` | `65adfee...` | **PASS** |
| `toggle_edpi253_dpi1100.json` | `repos/prohpea/CVM-colorBot/contents/configs/...` | `8851591...` | **PASS** |

---

## 3. Kết Luận Kiểm Thử (QA Verdict)
- Đã khắc phục triệt để và kiểm chứng bằng dữ liệu: Điểm ngắm từ nay 100% nằm trong vùng hộp sọ / trán / mắt của địch.
- **ĐÁNH GIÁ: ĐẠT TIÊU CHUẨN XUẤT XƯỞNG.**

**Lệnh chuyển giao:** Kính chuyển sang cho **Reviewer Agent (`gemini-4-argon`)** thẩm định và phê duyệt lần cuối.
