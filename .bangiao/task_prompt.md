# YÊU CẦU DỰ ÁN: ĐỒNG BỘ & NÂNG CẤP OBS XUDP PLUGIN & UDP RECEIVER (v2.1)

## Mục Tiêu & Phạm Vi:
1. **Đồng bộ hóa cổng kết nối UDP giữa OBS Plugin (PC 1) và Bot (PC 2):**
   - Đặt cổng mặc định đồng nhất là **5000** trên toàn bộ hệ thống (`CVM-colorBot/config.json`, `OBS_UDP.py`, `capture_service.py`, `OBS-xUDP-Plugin/config.json`, `HUONG_DAN_SU_DUNG.txt`).
   - Đảm bảo cơ chế tự động fallback và cấu hình IP/Port của Audio Feedback (UDP 4455) thông suốt, có thông báo log rõ ràng.

2. **Nâng cấp `CVM-colorBot/src/capture/OBS_UDP.py`:**
   - Kế thừa và tích hợp các công nghệ siêu tốc từ `OBS-xUDP-Plugin/receiver_ultra_fast.py`:
     - Bộ ghép mảnh gói tin `FrameReassembler` với **Deadline Timeout 5.0ms** (chu kỳ 144 FPS là 6.94ms; gói tin bị trễ hoặc rớt mảnh quá 5ms sẽ bị drop ngay lập tức, triệt tiêu hoàn toàn lag tích lũy buffer bloat).
     - Hỗ trợ cả 2 dạng packet: Single-packet (SOI `\xff\xd8`) và Fragmented packet (Header 8 bytes: `[total_size (4B)] [frag_idx (2B)] [total_frags (2B)]`).
     - Tích hợp `WindowsTimer(1ms)` (`timeBeginPeriod(1)`) và `set_high_thread_priority()` cho luồng nhận và giải mã frame.
     - Tối ưu giải mã phần cứng TurboJPEG và OpenCV fallback; hàng đợi size-1 slot đơn bảo đảm frame nhận được luôn là frame mới nhất.
     - Giữ nguyên 100% tương thích ngược API với `capture_service.py` (`get_current_frame()`, `connect()`, `disconnect()`, `get_performance_stats()`, v.v.).

3. **Nâng cấp bộ cài đặt `OBS-xUDP-Plugin`:**
   - Cập nhật `OBS-xUDP-Plugin/install.ps1`:
     - Tự động dò tìm thư mục OBS Studio thông qua Registry Windows (`HKLM:\SOFTWARE\OBS Studio`), đường dẫn mặc định `C:\Program Files\obs-studio`, ổ `D:\`, `E:\`, và Steam library.
     - Tự động thêm rule Windows Defender Firewall cho OBS Studio và mở các cổng cần thiết (UDP Inbound 4455 cho Beep, UDP Outbound/Inbound 5000).
     - Kiểm tra sự tồn tại của VC++ 2015-2022 Redistributable (x64) và cảnh báo người dùng nếu thiếu.
     - Cập nhật thông điệp hiển thị chuẩn 144 FPS & Purple v2.1.
   - Cập nhật `HUONG_DAN_SU_DUNG.txt` và `HUONG_DAN_CAI_DAT.txt`:
     - Hướng dẫn rõ ràng cách cấu hình IP PC 1 / PC 2, giải thích cổng 5000 (Stream) và cổng 4455 (Beep).

4. **Đồng bộ cấu hình mẫu trong `OBS-xUDP-Plugin`:**
   - Cập nhật `config.json` và `cvm_config_optimized.json` trong `OBS-xUDP-Plugin` khớp với cấu hình chuẩn v2.1 (Sens 0.23, DPI 1100, WindMouse main, Flick sec, port 5000).

5. **Kiểm thử tự động:**
   - Mở rộng `tests/test_udp_receiver_latency.py` kiểm tra ghép mảnh gói UDP, deadline timeout 5ms, giải mã TurboJPEG và OpenCV fallback.
   - Đảm bảo toàn bộ test suite (`python -m unittest discover -s tests`) vượt qua 100%.
