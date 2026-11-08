# 📋 [PLANNER AGENT] BẢN THIẾT KẾ & KẾ HOẠCH NÂNG CẤP ĐẠI TU CVM-COLORBOT BẢN 2.0 PRO
**Mã hiệu:** `PLAN-20261108-CVM-V2.0-MAJOR-UPGRADE`  
**Vai trò:** Lead Solutions Architect & Systems Engineering Director (Agency Agent Pipeline)  
**Mô hình vận hành:** `gpt-6-sol` (Headless Read-Only Mode)  
**Dự án:** CVM-colorBot v2.0.0 PRO - Enterprise Architecture Overhaul  
**Khách hàng/Ủy thác:** User  
**Yêu cầu người dùng:** Tối ưu lại toàn bộ cả giao diện và chức năng, sau đó cập nhật toàn bộ dự án lên phiên bản 2.0.  

---

## 1. Phân Tích Hiện Trạng & Tầm Nhìn Bản 2.0 (Architectural Vision)

### 1.1. Hiện trạng phiên bản cũ (v1.2.1)
- **Giao diện người dùng (UI):**
  - Tiêu đề và nhãn hiển thị vẫn mang mã hiệu cũ `v1.2.1`.
  - Tab RCS bị ẩn/chuyển hướng (`_show_rcs_tab` chỉ đơn thuần redirect về Combat) khiến người dùng không có công cụ trực quan để tinh chỉnh độ trễ Burst & Sấy (RCS delay) hoặc tốc độ kéo chuột (pull speed) ngay trên giao diện.
  - Hàng công tắc Master (Master Switches) ở Main Aimbot chỉ có Aimbot và Anti-Smoke, thiếu công tắc nhanh cho tính năng sấy bù giật RCS.
- **Cấu hình & Dữ liệu cốt lõi:**
  - File `src/utils/config.py` vẫn giữ các giá trị mặc định khởi thủy cũ (DPI 800, Sens 0.235, RCS tắt, delay 100ms).
- **Hệ thống phiên bản & Tài liệu:**
  - `version.json`, `CHANGELOG.md`, `README.md` đang dừng lại ở bản 1.2.1 / 2.10.2 chưa đồng bộ.

### 1.2. Mục tiêu chiến lược Bản 2.0.0 PRO (Core Directives)
1. **Đại tu giao diện người dùng (Modern High-Precision Dashboard v2.0):**
   - Nâng cấp Header: Cửa sổ frameless viền sắc nét, tiêu đề `CVM colorBot v2.0 PRO`, huy hiệu phiên bản cao cấp `v2.0.0 PRO` với tone màu Cyber Emerald/Cyan.
   - Bổ sung công tắc nhanh **"Enable RCS (Burst & Spray)"** ngay trên thanh điều khiển Master của tab Combat.
   - Khôi phục và tái thiết lập toàn diện **Tab RCS & Recoil Control** trong phân hệ Combat:
     - Card điều khiển chuyên sâu: Tốc độ ghìm (`rcs_pull_speed`), Độ trễ phân kỳ Burst/Sấy (`rcs_activation_delay` với chú thích trực quan), Ngưỡng nhấp nhanh (`rcs_rapid_click_threshold`), Tự động trả tâm Y (`rcs_release_y`).
   - Cập nhật huy hiệu thuật toán: Chuyển toàn bộ badge `v1.2 Algo` sang `v2.0 Pro Engine`.
2. **Tối ưu hóa chức năng & Động lực học (Core Physics Optimization):**
   - Tích hợp chuẩn hoá bộ giá trị mặc định của hệ thống trong `src/utils/config.py`:
     - Mouse DPI: `1100` | In-game Sens: `0.23` (253 eDPI).
     - Phím kích hoạt: `Side Mouse 4 Button` (Mã `3`) với chế độ `Toggle`.
     - Phím sấy: `Left Mouse Button` (Mã `0`) tự động kích hoạt RCS sau `140ms`.
   - Bảo toàn cấu trúc nạp preset: Đồng bộ hóa toàn diện giữa `config.json` và thư mục `configs/`.
3. **Cập nhật hệ thống siêu dữ liệu & Phát hành (Release Engineering):**
   - Nâng cấp `version.json` lên `"2.0.0"`.
   - Cập nhật nhật ký phát hành `CHANGELOG.md` bản 2.0.0 hoành tráng.
   - Cập nhật `README.md` với huy hiệu Version 2.0.0 PRO và tài liệu hướng dẫn mới nhất.

---

## 2. Bản Vẽ Phân Bổ File Cho Coder (Scope of Work)

### 2.1. Phân hệ Giao diện: `src/ui.py`
- Sửa tiêu đề cửa sổ: `self.title("CVM colorBot v2.0 PRO")`.
- Cập nhật thanh header: Logo, nhãn phiên bản `v2.0.0 PRO`.
- Sửa thanh điều hướng phụ của Combat: `["Main Aimbot", "Sec Aimbot", "Recoil & RCS"]`.
- Bổ sung công tắc RCS nhanh trên `master_row` của `_show_aimbot_tab()`.
- Xây dựng lại hoàn chỉnh hàm `_show_rcs_tab()` với giao diện ModernCard và các slider điều khiển thời gian thực.

### 2.2. Phân hệ Cấu hình: `src/utils/config.py`
- Cập nhật giá trị khởi tạo mặc định trong `Config.__init__()` khớp chuẩn v2.0.

### 2.3. Phân hệ Phiên bản: `version.json`, `CHANGELOG.md`, `README.md`
- Đẩy toàn bộ định danh dự án lên `2.0.0`.

### 2.4. Đồng bộ GitHub:
- Commit toàn bộ các thay đổi và push lên remote `prohpea/CVM-colorBot` nhánh `main`.

---

## 3. Tiêu Chuẩn Nghiệm Thu (Acceptance Criteria - AC)
- [ ] **AC-1:** Giao diện `src/ui.py` có tiêu đề v2.0 PRO, tab Recoil & RCS hoàn chỉnh, công tắc nhanh RCS hoạt động mượt mà.
- [ ] **AC-2:** File `src/utils/config.py` đồng bộ mặc định DPI 1100, Sens 0.23, Toggle Side Mouse 4, RCS delay 140ms.
- [ ] **AC-3:** `version.json` phản ánh chính xác `"version": "2.0.0"`.
- [ ] **AC-4:** `CHANGELOG.md` và `README.md` ghi nhận đầy đủ tính năng v2.0.0.
- [ ] **AC-5:** Khởi chạy kiểm thử cú pháp Python không phát sinh bất kỳ lỗi cú pháp hay import nào.
- [ ] **AC-6:** Đẩy commit lên GitHub Private repo thành công và lập biên bản đầy đủ tại `.bangiao/`.

**Lệnh chuyển giao:** Bàn giao bản thiết kế sang cho **Coder Agent (`deepseek-v4.1-flash`)** thi công ngay.
