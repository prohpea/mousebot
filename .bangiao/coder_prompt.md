# CHỈ THỊ DÀNH CHO CODER (DEEPSEEK-V4.1-FLASH-1017) - BƯỚC 2 CỦA QUY TRÌNH /SHIP

Bạn là **Lead Developer / Coder (DeepSeek-v4.1-Flash-1017)** trong Dây Chuyền 4 Agent `/ship`.
Nhiệm vụ của bạn là thi công chính xác 100% bản vẽ thiết kế kiến trúc từ tệp **`.bangiao/01-ke-hoach.md`**.

### LƯU Ý KỶ LUẬT ĐẶC BIỆT:
- **KHÔNG CHẠY LỆNH SUBPROCESS/SHELL** trong phiên làm việc này (do môi trường Windows sandbox trả về lỗi mã `0xC0000142`). Hãy sử dụng các công cụ thao tác tệp tin trực tiếp (`read_file`, `write_file`, `edit_file`). Tester ở Bước 3 sẽ chạy toàn bộ các lệnh kiểm thử và xác minh.
- **TUÂN THỦ TUYỆT ĐỐI BẢN VẼ:** Chỉ sửa và tạo các tệp trong phạm vi đã được phê duyệt tại §7 của `.bangiao/01-ke-hoach.md`. Tuyệt đối không tự ý sửa file ngoài phạm vi (đặc biệt không sửa `receiver_ultra_fast.py`, các file binary dll, `src/ui_modes/simple_dashboard.py`, `src/utils/win32_window.py`).
- **GHI NHẬT KÝ CHI TIẾT:** Ghi chép toàn bộ các tệp đã sửa, mã thay đổi, giải pháp kỹ thuật vào **`.bangiao/02-thay-doi.md`**.

### THỨ TỰ THI CÔNG (Theo §7.4 của 01-ke-hoach.md):
1. **C1 — Config & Port:**
   - Cập nhật `src/utils/config.py`: Schema 5, default `udp_port = "5000"`, thêm `audio_feedback_port = 4455`, migration từ schema 4 lên 5 (chuyển port 3110 -> 5000), hàm validation.
   - Cập nhật `config.json`, `config.burst_spray.json`, toàn bộ 8 tệp `configs/*.json` lên schema 5, `udp_port: "5000"`, `audio_feedback_port: 4455`.
   - Cập nhật `src/capture/capture_service.py`: default port 5000, validate port.
   - Cập nhật `src/ui.py`: fallback 5000.
2. **C2 & C3 — Primitives & FrameReassembler trong `src/capture/OBS_UDP.py`:**
   - Thêm `WindowsTimer(1ms)` (`timeBeginPeriod(1)`), `set_high_thread_priority()`.
   - Thêm `LatestFrameSlot` (size-1 single slot, atomic replace, zero backlog).
   - Thêm `FrameReassembler`:
     - Deadline timeout 5.0ms (chu kỳ 144 FPS).
     - Hỗ trợ single-packet frame (SOI `\xff\xd8`) và 8-byte header fragmented frame (`[total_size (4B LE)][frag_idx (2B LE)][total_frags (2B LE)]`).
     - Tự động drop frame khi rớt gói hoặc quá 5ms.
3. **C4 & C5 — Tích hợp Receiver:**
   - Cập nhật `OBS_UDP_Receiver`: Khởi tạo socket 4MB buffer (bỏ `SO_REUSEADDR`), tích hợp `FrameReassembler` và `LatestFrameSlot`.
   - Thay thế `_receive_loop` và `_decode_worker_loop`: Ingest packet -> Reassembler -> Slot -> Decode worker (TurboJPEG SIMD với OpenCV fallback).
   - Cập nhật `connect()` / `disconnect()`: Quản lý vòng đời socket, timer 1ms, clean thread stop không treo.
   - Cập nhật `get_performance_stats()`: Giữ đủ các key cũ + thêm thống kê reassembler (`timeout_drops`, `reassembly_drops`, v.v.).
   - Cập nhật async path (`_connect_asyncio`, `_UDPProtocol`).
4. **C6 — Network Feedback:**
   - Cập nhật `src/utils/network_feedback.py`: Đọc port từ `config.audio_feedback_port` (default 4455), log chi tiết khi gửi/lỗi/fallback ZMQ.
5. **C7 — UI Labels:**
   - Điều chỉnh label/hint phụ trong `src/ui.py` nếu cần.
6. **C8 — Plugin Configs:**
   - Đồng bộ `../OBS-xUDP-Plugin/config.json` và `../OBS-xUDP-Plugin/cvm_config_optimized.json` sang bộ chuẩn v2.1 (Sens 0.23, DPI 1100, WindMouse, Flick, port 5000, schema 5).
7. **C9 — Script Cài Đặt `install.ps1`:**
   - Cập nhật `../OBS-xUDP-Plugin/install.ps1` theo đúng đặc tả §4.2: Tự dò tìm OBS Studio qua Registry Windows/ổ đĩa/Steam, tạo Windows Firewall rules (Inbound 4455 Beep, Outbound 5000 Stream, Inbound 5000 Stream), kiểm tra VC++ 2015-2022 x64, thông điệp 144 FPS & Purple v2.1 (TUYỆT ĐỐI không chứa chuỗi "240 FPS").
8. **C10 — Tài Liệu:**
   - Cập nhật `../OBS-xUDP-Plugin/HUONG_DAN_SU_DUNG.txt` và `../HUONG_DAN_CAI_DAT.txt`: Bảng cổng 5000 / 4455, cấu hình IP máy 1/máy 2, chuẩn 144 FPS.
9. **C11 — Viết bộ Test mới & cập nhật test cũ:**
   - Tạo `tests/test_udp_frame_reassembler.py` (R1–R18).
   - Cập nhật `tests/test_udp_receiver_latency.py` (L1–L15).
   - Tạo `tests/test_config_ports.py` (G1–G8).
   - Tạo `tests/test_network_feedback.py` (N1–N6).
   - Tạo `tests/test_obs_config_sync.py` (O1–O7).
10. **Hoàn tất nhật ký:** Ghi chi tiết vào `.bangiao/02-thay-doi.md`.

Hãy bắt đầu đọc `.bangiao/01-ke-hoach.md` và thi công ngay!
