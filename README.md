# CVM Ultimate (PC2 Minimal 144 FPS Edition)

Công cụ nhận diện màu HSV độ trễ siêu thấp cho **Dual-PC (PC1 OBS xUDP → PC2 CVM-Ultimate + Serial/HID)**, tối ưu hóa cho 144 FPS và thao tác tối giản.

## Kiến trúc & Tính năng chính

- **4 tab tối giản:** `General`, `Main Aimbot`, `Config`, `Debug` (mặc định giao diện `HUD` ít tải GIL; hỗ trợ chuyển Lite/Pro).
- **3 chế độ Aim trọng tâm:** `ABCurves` (8/16ms C++ native), `Normal`, `WindMouse`. Các module thừa (`RCS`, `Triggerbot`, `Magnet Trigger`, `Sec Aimbot`, `Anti-Smoke`) đã được gỡ khỏi UI và khóa tắt ở runtime.
- **Quick Profile chỉ đổi Main Aim:** Bấm đổi nhanh hồ sơ trên thanh HUD chỉ thay đổi thông số Aim và tự lưu, giữ nguyên phần cứng chuột (`Serial/COM`), cấu hình `UDP` và `HSV` đồng bộ OBS.
- **Nhận luồng xUDP siêu thấp trễ (`src/capture/OBS_UDP.py`):**
  - Hàng đợi size-1 (0 frame tồn đọng), fast-path 1 gói JPEG, buffer `8MB SO_RCVBUF`, timeout phân mảnh `5ms` có kiểm tra tổng byte, đồng bộ `frame_seq` tránh xử lý trùng frame.
  - Giải mã trực tiếp bằng `ctypes` `turbojpeg.dll` (~0.3–0.5 ms/frame), tự fallback sang OpenCV nếu thiếu DLL.
- **Nhận diện nhanh (`src/utils/detection.py` + `main.py`):**
  - Tự dùng CPU AVX2/SIMD cho ảnh `<= 400×400` + crop ROI động quanh tâm FOV (~0.26 ms/frame ở `FOV=48`, 320×320).
  - Đồng bộ HSV Purple chuẩn OBS xUDP v2.1 cho cả tầm gần lẫn 50m+: `[120, 95, 90] → [160, 255, 255]`.
  - Tự động co giãn `aim_offsetX/Y` theo chiều cao bbox (`0.72 → 1.00`, tắt/bật trong `Main Aimbot → Offset → Distance Scaling (50m+)`).

## Chạy trên PC2

1. Chạy `run.bat` (dùng sẵn Python 3.11.9 trong `runtime\Scripts\python.exe`).
2. Cấu hình PC1 OBS Studio theo `OBS-xUDP-Plugin\HUONG_DAN_SU_DUNG.txt` (`320×320`, `144 FPS`, `Port 5000`, bật `Enhance Purple Tones` + `Reduce Background Colors`).
3. Trên PC2, bấm **START ENGINE** để kết nối chuột & UDP cổng `5000` *(lưu ý đóng `run_receiver.bat` trước khi kết nối)*.

## Kiểm thử

```bat
run_tests.bat
```
