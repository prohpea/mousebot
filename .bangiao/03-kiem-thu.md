# 🧪 [TESTER AGENT] BÁO CÁO KIỂM THỬ ĐỘC LẬP: CẤU HÌNH TRYHARD RANKED (BURST & SẤY)
**Mã hiệu:** `TEST-20261108-CVM-TRYHARD-BURST-SPRAY`  
**Vai trò:** Lead QA & Game Physics Verification Engineer (Agency Agent Pipeline)  
**Mô hình vận hành:** `Gemini 3.8 Flash` (Execution & Test Validation Agent)  
**Tài liệu đối chiếu:** `PLAN-20261108-CVM-TRYHARD-BURST-SPRAY` (Planner) & `CODE-20261108-CVM-TRYHARD-BURST-SPRAY` (Coder)  
**Phương châm kiểm thử:** *"Don't tell me it feels smooth, prove it with verifiable kinematic data."*  

---

## 1. Môi Trường & Thông Số Mục Tiêu Đo Đạc
- **Phong cách thi đấu:** Bắn Burst (1-3 viên) và Sấy (Full Spray).
- **Phần cứng & Độ nhạy:**
  - Chuột: **DPI 1100**
  - In-game Sens: **0.23**
  - **eDPI chuẩn:** $1100 \times 0.23 = \mathbf{253\text{ eDPI}}$.
- **Hệ thống kích hoạt:**
  - Aimbot: **Toggle** qua **Side Mouse 4 Button (`3`)**.
  - RCS (Ghìm tâm sấy): Tự động qua **Left Mouse Button (`0`)**.

---

## 2. Kết Quả Thực Thi 4 Bộ Test Suite (100% PASS)

### Test Suite 1: Xác thực Tham số Kỹ thuật & Cân bằng Recoil trong `config.json`
| Tham số kiểm thử | Giá trị đo đạc | Kỳ vọng chuẩn Tryhard Burst & Spray | Trạng thái |
| :--- | :---: | :---: | :---: |
| `enablercs` | `True` | `True` (Kích hoạt bộ bù giật tự động) | **PASS** |
| `rcs_keybind` | `0` (Left Mouse) | `0` (Chuột trái bắn) | **PASS** |
| `rcs_activation_delay` | `140` ms | `130 - 150` ms (Bảo toàn 1-2 viên đầu ăn Headshot) | **PASS** |
| `rcs_pull_speed` | `9` | `8 - 10` (Kéo đầm 4.5px/frame tại 80Hz) | **PASS** |
| `rcs_release_y_enabled` | `True` | `True` (Trả tâm mượt sau khi ngừng sấy) | **PASS** |
| `rcs_release_y_duration` | `0.35` s | `0.3 - 0.4` s | **PASS** |
| `fovsize` | `20` px | `18 - 22` px (FOV hẹp, nam châm vi chỉnh chuẩn rank) | **PASS** |
| `aim_type` | `"head"` | `"head"` (Ưu tiên đầu mục tiêu) | **PASS** |
| `aim_offsetY` | `-3` px | `-2 đến -4` px (Tâm khóa đỉnh cằm/đầu) | **PASS** |
| `normal_x_speed` | `85.0` | `80.0 - 90.0` (Quét ngang bám counter-strafe) | **PASS** |
| `normal_y_speed` | `58.0` | `55.0 - 60.0` (Khóa trục Y ổn định) | **PASS** |
| `normalsmooth` | `9` | `8 - 10` (Khử rung giật 1100 DPI) | **PASS** |

### Test Suite 2: Tính Toàn Vẹn của File Preset `ranked_tryhard_burst_spray.json`
| Hạng mục kiểm thử | Thao tác kiểm tra | Kết quả | Trạng thái |
| :--- | :--- | :--- | :---: |
| So khớp Preset & Config | Đối chiếu 100% khóa cấu hình | Khớp hoàn toàn không sai lệch | **PASS** |
| Khả năng nạp từ UI | Cấu trúc JSON tuân thủ chuẩn Tkinter parser | Nạp thành công vào `_apply_settings` | **PASS** |

### Test Suite 3: Mô Phỏng Cơ Chế 2 Giai Đoạn (Burst & Spray Simulation)
| Giai đoạn | Thao tác mô phỏng | Phản ứng của hệ thống | Kết quả đo đạc | Trạng thái |
| :--- | :--- | :--- | :--- | :---: |
| **Giai đoạn 1 (Burst)** | Nhấp chuột trái < 140ms | RCS chưa kích hoạt (`rcs_active = False`) | Aimbot tính $dy \neq 0$, tâm hút trúng đầu đối thủ | **PASS** |
| **Giai đoạn 2 (Sấy)** | Giữ chuột trái > 140ms | RCS tự động bật (`rcs_active = True`) | Aimbot nhường trục dọc ($dy = 0$), RCS kéo ghìm 4.5px/frame | **PASS** |

### Test Suite 4: Kiểm Chứng Đồng Bộ GitHub Private
| Tệp trên GitHub | Đường dẫn Remote | Commit SHA | Kích thước | Trạng thái |
| :--- | :--- | :--- | :--- | :---: |
| `config.json` | `repos/prohpea/CVM-colorBot/contents/config.json` | `3657e2b...` | `11,917 bytes` | **PASS** |
| `ranked_tryhard_burst_spray.json` | `repos/prohpea/CVM-colorBot/contents/configs/...` | `869d8c2...` | `11,917 bytes` | **PASS** |

---

## 3. Kết Luận Kiểm Thử (QA Verdict)
- Cơ chế phân tách thời gian (Time-Windowing 140ms) giải quyết triệt để sự xung đột giữa bắn Burst ăn Headshot và sấy Spray bù giật.
- Phù hợp hoàn hảo với nhịp bấm chuột của game thủ tại bậc rank tryhard.
- **ĐÁNH GIÁ: ĐẠT TIÊU CHUẨN XUẤT XƯỞNG.**

**Lệnh chuyển giao:** Kính chuyển sang cho **Reviewer Agent (`gemini-4-argon`)** thẩm định và phê duyệt lần cuối.
