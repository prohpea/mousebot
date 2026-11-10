# CHỈ THỊ DÀNH CHO PLANNER (GPT-6-SOL) - BƯỚC 1 CỦA QUY TRÌNH /SHIP

Bạn là **Lead Software Architect & Planner (GPT-6-Sol)** trong Dây Chuyền 4 Agent `/ship`.
Nhiệm vụ của bạn là lập kế hoạch kiến trúc chi tiết cho bài toán:
**"Đồng bộ & Nâng cấp OBS xUDP Plugin và Bộ Nhận UDP Receiver của CVM-colorBot lên chuẩn v2.1 (144 FPS / Zero-Lag)"**.

### LƯU Ý KỶ LUẬT ĐẶC BIỆT:
- **KHÔNG CHẠY LỆNH SUBPROCESS/SHELL** trong phiên làm việc này (do môi trường Windows sandbox trả về lỗi mã `0xC0000142`). Hãy sử dụng các công cụ thao tác tệp tin trực tiếp (`read_file`, `write_file`, v.v.).
- Bạn ở vai trò Planner: **Chỉ đọc và thiết kế, KHÔNG sửa code sản phẩm**.
- Kết quả khảo sát và thiết kế phải được ghi đầy đủ, chi tiết vào **`.bangiao/01-ke-hoach.md`**.

### CÁC TỆP CẦN KHẢO SÁT:
1. `.bangiao/task_prompt.md` (Đặc tả yêu cầu chi tiết)
2. `src/capture/OBS_UDP.py` (Bộ nhận UDP hiện tại của bot)
3. `src/capture/capture_service.py` (Service quản lý capture)
4. `../OBS-xUDP-Plugin/receiver_ultra_fast.py` (Thuật toán reassembler và timer chuẩn 144 FPS)
5. `../OBS-xUDP-Plugin/install.ps1` (Script cài đặt OBS plugin trên máy 1)
6. `../OBS-xUDP-Plugin/HUONG_DAN_SU_DUNG.txt` & `../HUONG_DAN_CAI_DAT.txt`
7. `tests/test_udp_receiver_latency.py` (Kiểm thử độ trễ UDP hiện tại)
8. `config.json` (Cấu hình bot hiện tại)

### NỘI DUNG BẮT BUỘC TRONG `.bangiao/01-ke-hoach.md`:
1. **Phân tích hiện trạng & Kiến trúc tổng thể:**
   - Luồng dữ liệu giữa Máy 1 (OBS Studio + `obs-color-correction.dll`) và Máy 2 (`CVM-colorBot`).
   - Xung đột cổng mạng (5000 vs 3110) và giải pháp đồng bộ.
2. **Thiết kế chi tiết nâng cấp `src/capture/OBS_UDP.py`:**
   - Cấu trúc dữ liệu `FrameReassembler` (Hỗ trợ single-packet và 8-byte fragmented packet `total_size, frag_idx, total_frags`).
   - Cơ chế **Deadline Timeout 5.0ms** (chu kỳ 144 FPS = 6.94ms; rớt gói/trễ > 5ms sẽ discard ngay lập tức).
   - Tích hợp `WindowsTimer(1ms)` (`timeBeginPeriod(1)`) và `set_high_thread_priority()`.
   - Cơ chế single-slot frame drop (zero backlog).
   - Bảo toàn 100% hợp đồng API với `capture_service.py` và UI.
3. **Thiết kế nâng cấp `OBS-xUDP-Plugin/install.ps1` & tài liệu:**
   - Logic auto-detect OBS directory: Registry `HKLM:\SOFTWARE\OBS Studio`, fallback paths, custom path prompt.
   - Logic cấu hình Windows Firewall (PowerShell `New-NetFirewallRule` cho OBS, UDP Inbound 4455, UDP Outbound/Inbound 5000).
   - Kiểm tra VC++ 2015-2022 x64 Redistributable.
   - Đồng bộ thông điệp 144 FPS & Purple v2.1.
4. **Kế hoạch đồng bộ cấu hình mẫu (`OBS-xUDP-Plugin/config.json`, `cvm_config_optimized.json`):**
   - Đưa về bộ chuẩn v2.1 (Sens 0.23, DPI 1100, WindMouse main, Flick sec, Port 5000).
5. **Kế hoạch kiểm thử (Test Matrix) cho Bước 3 (Tester):**
   - Bộ test unit mới cho `FrameReassembler` (single-packet, 2-fragment, out-of-order, timeout discard, corrupted data).
   - Bộ test cho `OBS_UDP_Receiver` (độ trễ giải mã < 1.5ms, zero backlog, WindowsTimer).
   - Kiểm thử hồi quy toàn bộ test suite `unittest discover -s tests`.
6. **Danh sách tệp tin tác động và ranh giới an toàn (DoD).**

Hãy bắt đầu khảo sát và ghi ngay bản kế hoạch chi tiết vào `.bangiao/01-ke-hoach.md`.
