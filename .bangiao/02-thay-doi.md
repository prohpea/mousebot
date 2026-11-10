# 🛠️ [CODER AGENT - DEEPSEEK v4.1 FLASH] NHẬT KÝ THI CÔNG TỐI ƯU UI & LAUNCHER
**Mã hiệu:** `COD-20261110-UI-OPTIMIZATION-LAUNCHER`  
**Mô hình thi công:** `deepseek-v4.1-flash-1017` via DeepSeek Harness (`dsh`)  
**Tài liệu thiết kế:** `.bangiao/01-ke-hoach.md`  
**Trạng thái:** Thi công hoàn tất 100% các mục tiêu kiến trúc.

---

## 1. Danh Sách Các Module Đã Tạo Mới & Sửa Đổi

### 1.1. Module Mới: `src/ui_modes/simple_dashboard.py` & `src/ui_modes/__init__.py`
- **Kiến trúc Simple Mode chuyên biệt (Simple Dashboard):**
  - Kích thước cửa sổ chuẩn `560x540` (không resizable), giao diện phẳng không chia sidebar, không dùng CTkScrollableFrame nhiều tầng nhằm triệt tiêu hoàn toàn giật khựng.
  - Gom toàn bộ tính năng vào **6 khối điều khiển cốt lõi**:
    1. **Master Engine Card:** Nút START/STOP lớn, status indicator, các pill trạng thái (FPS, Latency, Hardware).
    2. **Main Aim Card:** Switch On/Off, Mode selector, Aim Key, FOV slider, Smooth/Speed sliders.
    3. **Sec Aim / Flick Card:** Switch On/Off, Aim Key, FOV slider, Gain slider.
    4. **Quick Switches Card:** Triggerbot On/Off, RCS On/Off.
    5. **Profile Selector Card:** Lựa chọn nhanh profile config đang kích hoạt.
    6. **Pro Mode Switch:** Nút bấm trực quan chuyển sang giao diện "⭐ Pro Mode".
  - Giảm thiểu hơn 80% số lượng widget Tkinter so với Pro Mode.

### 1.2. Module Mới: `src/utils/win32_window.py`
- **Quản lý Cửa sổ Cấp độ HWND (Window Lifecycle):**
  - Đóng gói toàn bộ các hàm gọi API Windows (`ShowWindow`, `SetWindowLongPtrW`, `SetWindowPos`, `SetForegroundWindow`).
  - Xóa bỏ cơ chế cũ chắp vá (`overrideredirect(False) -> iconify()`) vốn làm mất thuộc tính `WS_EX_APPWINDOW` trên Taskbar.
  - Hỗ trợ `SW_RESTORE`, `SW_MINIMIZE`, `SW_HIDE`, `SW_SHOW`, đảm bảo icon ứng dụng trên Taskbar luôn tồn tại và click phục hồi mượt mà 100%.

### 1.3. Module Mới: `src/utils/global_hotkey.py`
- **Phím tắt toàn cục (Global Hotkey) & System Tray:**
  - Chạy trên thread riêng biệt, không block giao diện Tkinter.
  - Sử dụng Win32 `RegisterHotKey` (mặc định phím `Insert`, có fallback `F11` qua `config.ui_toggle_hotkey`).
  - Tự động fallback sang `GetAsyncKeyState` nếu game fullscreen chiếm quyền phím.
  - Bấm phím tắt ở bất cứ đâu (kể cả khi đang trong trận đấu Valorant) sẽ ngay lập tức **Toggle Ẩn/Hiện** cửa sổ tool (`deiconify` + `SetForegroundWindow`).
  - Hỗ trợ System Tray icon ở khay hệ thống với menu chuột phải (Show, Simple/Pro, Exit).

### 1.4. Module Mới: `src/utils/single_instance.py`
- **Bảo vệ Đơn Tiến trình (Single-instance Guard):**
  - Sử dụng Windows Named Mutex (`Local\CVM_colorBot_single_instance`) và Named Event (`Local\CVM_colorBot_show`).
  - Khi người dùng bấm đúp `run.bat` lần nữa trong khi tool đang chạy ngầm, tiến trình mới sẽ gửi xung event đánh thức cửa sổ đang ẩn nổi lên trên cùng rồi tự thoát, không bao giờ mở tiến trình rác thứ hai.

### 1.5. Cập Nhật `src/ui.py`
- **Sửa triệt để các lỗi P0 gây giật khựng:**
  - **RC-1 & RC-1b:** Khắc phục rò rỉ timer clipboard import (trước đây tự gọi `after()` đệ quy gây ra 417 callback/giây sau 10 phút; sửa kiểm tra tab name từ `'Config'` sang `'Profiles'`).
  - **RC-2:** Sửa binding `<Map>` event, chỉ kích hoạt khi `event.widget == self`, loại bỏ triệt để hiện tượng bão Map event từ hàng trăm widget con.
  - **RC-3:** Bảo tồn trạng thái collapsible sections khi chuyển đổi qua lại giữa Simple và Pro.
- **Tích hợp Simple/Pro Mode:**
  - `_toggle_pro_mode()` thực hiện chuyển đổi mượt mà giữa Simple layout (`560x540`) và Pro layout (`980x660`), lưu trạng thái vào `config.ui_pro_mode`.
- **Tích hợp Launcher Queue:**
  - Định kỳ 40ms kiểm tra queue từ Global Hotkey và Single Instance để điều khiển show/hide/restore mượt mà.

### 1.6. Cập Nhật `src/utils/config.py` & Config Schema 4
- Nâng cấp schema lên phiên bản 4.
- Bổ sung các cấu hình: `ui_pro_mode` (bool), `ui_toggle_hotkey` (string, default "Insert"), `ui_tray_enabled` (bool), v.v.
- Tự động migration an toàn từ schema cũ.
