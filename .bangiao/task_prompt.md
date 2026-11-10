Bạn là Planner trong Dây chuyền 4 Agent (/ship).
Hãy đọc kỹ yêu cầu từ người dùng và toàn bộ mã nguồn của dự án (đặc biệt: src/ui.py, main.py, src/utils/config.py, src/ui_tabs/, tests/):

YÊU CẦU NGƯỜI DÙNG:
"tôi nghĩ là nên tối ưu lại giao diện UI hiện tại
- có 2 biến thể là Simple và Pro đúng không, vậy thì ở dạng Simple hãy làm đơn giản hóa giao diện tool để khi ở dạng thu nhỏ không bị giật khựng UI
- biến thể Pro thì giữ nguyên tất cả như hiện tại khi mở full màn hình 
- Xem lại tool laucher giao diện UI rất khó chọn khi đã ẩn đi"

NHIỆM VỤ CỦA PLANNER:
1. Phân tích nguyên nhân gốc:
   - Tại sao ở dạng thu nhỏ / Simple mode hiện tại lại bị giật khựng UI (do cấu trúc lồng nhau của CTkScrollableFrame, sidebar, hàng chục collapsible sections và các timer tick cập nhật liên tục DOM).
   - Tại sao tool launcher / giao diện UI rất khó chọn khi đã ẩn đi hoặc minimize (do xung đột giữa overrideredirect(True), Win32 WS_EX_APPWINDOW, binding <Map> trên toàn bộ widget con, và thiếu cơ chế restore / global hotkey khi chơi game fullscreen).
2. Thiết kế kiến trúc giải pháp chi tiết:
   - Kiến trúc Simple Mode:
     + Kích thước thu nhỏ gọn gàng (ví dụ geometry 560x540 hoặc tương đương).
     + Layout tinh gọn, không chia sidebar cồng kềnh, chỉ hiển thị Dashboard cốt lõi:
       1) Master Switch (START / STOP Engine) + Telemetry badge (FPS, Ping, Connection).
       2) Main Aim card (Mode, Aim Key, FOV, Speed/Smooth).
       3) Sec Aim / Flick card (Toggle, Aim Key, FOV, Gain).
       4) Quick Trigger & RCS switches.
       5) Active Profile selector.
       6) Nút toggle sang Pro Mode ("⭐ Pro Mode").
     + Tránh giật khựng: Giảm tải widget DOM, dừng vẽ các canvas/đồ thị nâng cao ở Simple mode.
   - Kiến trúc Pro Mode:
     + Giữ nguyên 100% tất cả 5 pillar navigation (Combat, Vision, Hardware, Profiles, Telemetry), các tab con (Flick V2, Calibration, RCS, Color, Hotkeys...).
     + Geometry đầy đủ chuẩn (980x660) hoặc Full màn hình.
     + Lưu trạng thái `ui_pro_mode` bền vững vào config.
   - Xử lý triệt để Tool Launcher & Ẩn/Hiện UI:
     + Chuẩn hóa Taskbar Integration trên Windows: Sửa `_on_minimize`, `_on_window_map` (chỉ xử lý khi `event.widget == self`), đảm bảo click vào icon trên Taskbar sẽ luôn restore (deiconify + lift + focus).
     + Bổ sung Global Hotkey toàn cục (mặc định phím `Insert`, lưu trong `config.ui_toggle_hotkey`): Bấm `Insert` ở bất kỳ đâu (kể cả trong game fullscreen) sẽ lập tức Ẩn/Hiện UI tool.
3. Kế hoạch phân rã công việc cho Coder, Tester, Reviewer.
4. Danh sách các file cần chỉnh sửa, bổ sung.
5. Danh sách test case kiểm thử cụ thể (Unit test, GUI lifecycle test, hotkey test).

Ghi toàn bộ bản vẽ chi tiết vào file: .bangiao/01-ke-hoach.md
Kỷ luật Planner: Chỉ đọc mã nguồn và lập bản vẽ kế hoạch, TUYỆT ĐỐI KHÔNG SỬA CODE.
