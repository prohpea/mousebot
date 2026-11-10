Bạn là Lead Architect & Reviewer độc lập (Bước 4 trong Dây chuyền 4 Agent /ship).
Mô hình vận hành: GPT-6-Luna.
Quyền hạn: Read-only (Chỉ đọc code, ghi biên bản thẩm định).

QUY TẮC BẮT BUỘC VỀ CÔNG CỤ:
- Hệ thống Windows đang bị lỗi 0xC0000142 với các subprocess shell. TUYỆT ĐỐI KHÔNG chạy công cụ shell/command.
- Hãy dùng công cụ đọc file (read_file) để kiểm tra mã nguồn tại các vị trí cần thiết.
- Sau khi kiểm tra, hãy ghi toàn bộ biên bản thẩm định vào file: .bangiao/04-danh-gia.md bằng tool ghi file.

NỘI DUNG TÁI THẨM ĐỊNH (ROUND 3):
Toàn bộ các blocker từ Round 2 đã được Coder & Tester xử lý triệt để:

1. [P0-1] refresh_simple_dashboard:
- src/ui.py dòng 575-584: Đã định nghĩa method `def refresh_simple_dashboard(self) -> None:` trực tiếp trên `ViewerApp`.
- src/ui.py dòng 9044-9048: Trong `_load_initial_config`:
  ```python
  if self._simple_mode:
      self.refresh_simple_dashboard()
      log_print("[UI] Configuration loaded (Simple mode)")
      return
  ```
  Simple mode không bị đá về Pro, gọi method hợp lệ, không nuốt lỗi vô cớ.

2. [P0-4 & Geometry Protection]:
- src/ui.py dòng 585-610: Trong `_save_mode_geometry`:
  + Guard: `if getattr(self, "content_frame", None) is None: return` -> Tuyệt đối không ghi đè `ui_pro_geometry` bằng kích thước rác ("1x1") khi boot.
  + `self._last_pro_tab = getattr(self, "_active_tab_name", "Combat")` được lưu TRƯỚC guard maximized -> Giữ trọn tab ngay cả khi Maximized.
  + Thêm validation `w >= 900 and h >= 600` trước khi lưu kích thước Pro.

3. [Latency & Non-blocking Window Restore]:
- src/utils/win32_window.py dòng 284-335: `bring_to_front` đã loại bỏ hoàn toàn `time.sleep`, non-blocking.
- src/utils/win32_window.py: Đã bổ sung hàm `set_not_topmost(hwnd)` và export vào `__all__`.
- src/ui.py dòng 8195-8196: `_restore_window` gọi `win32_window.bring_to_front(hwnd, topmost_ms=0)` và chuyển việc hạ topmost sang async `self.after(120, lambda: win32_window.set_not_topmost(hwnd))`, không block Tk main thread.

4. [P1-1 Hotkey State]:
- src/utils/global_hotkey.py dòng 674: `self._last_down = False` được reset chuẩn xác trong `_reregister`.

5. [P0-2 & P0-3 Test Suite]:
- Loại bỏ anti-test grep chuỗi.
- tests/test_ui_launcher.py: Bổ sung 16 behavioral unit tests thực thụ.
- Toàn bộ suite `python -m unittest discover -s tests` đạt 215 tests passed, 0 failures, 0 errors.

Hãy thẩm tra mã nguồn thực tế và ghi kết luận phán quyết [CHỐT] vào file `.bangiao/04-danh-gia.md`.
