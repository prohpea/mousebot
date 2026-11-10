Bạn là Coder trong Dây chuyền 4 Agent (/ship).
Mô hình vận hành: deepseek-v4.1-flash-1017.
Quyền hạn: workspace-write, approval-policy never.

Nhiệm vụ:
1. Đọc kỹ toàn bộ bản vẽ thiết kế tại: .bangiao/01-ke-hoach.md
2. Thi công chính xác 100% bản vẽ kiến trúc đã được Planner vạch ra:
   - Sửa các lỗi P0 gây giật khựng UI:
     + RC-1 & RC-1b: Sửa triệt để rò rỉ timer clipboard import (chỉ schedule từ 1 nguồn duy nhất, fix tab name 'Profiles' thay vì 'Config').
     + RC-2: Sửa binding `<Map>` trong `src/ui.py` để chỉ xử lý khi `event.widget == self`, loại bỏ triệt để hiện tượng bão Map event từ widget con.
     + RC-3: Lưu trữ và bảo toàn trạng thái collapsible section khi chuyển đổi Simple/Pro.
   - Xây dựng Biến thể Simple Mode chuyên biệt (Simple Dashboard):
     + Tạo module `src/ui_modes/simple_dashboard.py` (hoặc tích hợp vào kiến trúc UI) với kích thước gọn gàng 560x540.
     + Không chia sidebar phức tạp, không lồng ghép CTkScrollableFrame nhiều tầng.
     + Hiển thị 6 khối điều khiển cốt lõi:
       1) Master Start/Stop Engine + Telemetry badge.
       2) Main Aim (Mode, Key, FOV, Speed/Smooth).
       3) Sec Aim / Flick (Mode, Key, FOV, Gain).
       4) Quick Switches: Triggerbot & RCS.
       5) Active Profile selector.
       6) Nút chuyển đổi sang Pro Mode ("⭐ Pro Mode").
   - Giữ nguyên 100% Biến thể Pro Mode:
     + Bảo toàn đầy đủ 5 pillar navigation (Combat, Vision, Hardware, Profiles, Telemetry), các tab Flick V2, Calibration và toàn bộ controls nâng cao.
     + Kích thước chuẩn khi ở Pro (980x660 hoặc restore geometry).
   - Xử lý triệt để Tool Launcher & Quản lý Cửa sổ / Ẩn hiện:
     + Cải tiến Window Management (`src/utils/win32_window.py` hoặc trong `src/ui.py`): Xử lý `_on_minimize` và restore đúng chuẩn Win32, reset `_taskbar_style_applied` khi cần để icon taskbar luôn bấm phục hồi được 100%.
     + Tích hợp Global Hotkey (`src/utils/global_hotkey.py`):
       - Mặc định phím `Insert` (hoặc `F11`, đọc từ `config.ui_toggle_hotkey`).
       - Dùng Win32 `RegisterHotKey` (hoặc hook phím nền) để khi đang trong game hoặc ngoài desktop, bấm phím này sẽ lập tức Toggle Ẩn / Hiện giao diện tool (`deiconify`, `lift`, `focus_force`).
     + Single Instance Check (`src/utils/single_instance.py` hoặc mutex trong `main.py`): Khi user chạy `run.bat` lần nữa trong khi tool đang chạy, nó sẽ tự gửi tín hiệu restore cửa sổ đang ẩn thay vì mở instance thứ 2.
   - Cập nhật `src/utils/config.py`:
     + Schema 4 migration an toàn, thêm các trường: `ui_pro_mode`, `ui_toggle_hotkey` (mặc định "Insert"), v.v.
   - Giữ gìn chất lượng mã nguồn: Python syntax chuẩn xác, không làm hỏng các bài test hiện có.
3. Ghi chép chi tiết toàn bộ các file đã tạo/sửa đổi vào: .bangiao/02-thay-doi.md.

Lưu ý: Trong môi trường dsh, hãy dùng các công cụ đọc/ghi/sửa file (read_file, write_file, edit_file, glob, grep). Bắt đầu thi công ngay!
