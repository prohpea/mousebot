# 💻 [CODER AGENT] NHẬT KÝ THI CÔNG & HIỆU CHỈNH CẤU HÌNH TOGGLE MODE (DPI 1100 - SENS 0.23)
**Mã hiệu:** `CODE-20261108-CVM-TOGGLE-253EDPI`  
**Vai trò:** Senior Systems & Game Input Physics Engineer (Agency Agent Pipeline)  
**Mô hình vận hành:** `deepseek-v4.1-flash-1017` (Workspace-Write Permission Mode)  
**Kế hoạch tiếp nhận:** `PLAN-20261108-CVM-TOGGLE-253EDPI` từ Planner Agent  
**Commit SHAs mới nhất:**  
- `config.json`: `5d4b09689b5b1cb7844af757702120cd08a47432`  
- `configs/toggle_edpi253_dpi1100.json`: `eb20e2ebda50ba1faeeb584c3bb4367d298bf572`  
**Repository:** [https://github.com/prohpea/CVM-colorBot](https://github.com/prohpea/CVM-colorBot) (Private)  

---

## 1. Nguyên Nhân Người Dùng Chưa Thấy Thay Đổi Trước Đó
Qua kiểm tra dấu vết runtime:
1. **Tiến trình UI ghi đè khi tắt:** Lúc 22:12, ứng dụng UI đang mở. Khi đóng cửa sổ UI, hàm `_on_closing()` gọi `config.save_to_file()`, vô tình ghi đè lại các thông số cũ trong RAM (Hold chuột trái, DPI 800, Sens 0.235) lên file `config.json`.
2. **Khóa thông số:** Hiện tại toàn bộ tiến trình Python đã tắt. File `config.json` và preset đã được cập nhật cứng trực tiếp và khóa toàn bộ tham số Toggle + 1100 DPI + 0.23 Sens.

---

## 2. Chi Tiết Các Hạng Mục Đã Thi Công Thực Tế

### 2.1. Cập nhật `config.json` trực tiếp trên máy
1. **Thông số phần cứng và độ nhạy:**
   - `in_game_sens`: `0.23` (Hiển thị trực tiếp vào ô In-game Sens trên UI).
   - `mouse_dpi`: `1100` (Hiển thị trực tiếp vào ô Mouse DPI trên UI).
   - $\text{eDPI} = 1100 \times 0.23 = \mathbf{253\text{ eDPI}}$.
2. **Chuyển đổi kích hoạt sang Toggle Mode (Bật/Tắt 1 lần bấm):**
   - `aimbot_activation_type`: `"toggle"` (Bấm phím 1 lần là BẬT liên tục; bấm lần nữa là TẮT).
   - `selected_mouse_button`: `3` (Nút phụ hông chuột 4 / XBUTTON1 / "Side Mouse 4 Button").
3. **Thu gọn vùng ngắm (Tight FOV - Nam châm vi chỉnh):**
   - `fovsize`: `22` (Thu gọn từ 30 xuống 22x22 pixel).
   - `normalsmoothfov`: `22`.
4. **Cân chỉnh tốc độ & gia tốc:**
   - `normal_x_speed`: `80.0`
   - `normal_y_speed`: `56.0` (Tỷ lệ trục Y:X là 0.70).
   - `normalsmooth`: `10`
5. **Hiệu chỉnh vật lý đường cong WindMouse:**
   - `wm_gravity`: `5.0`
   - `wm_wind`: `1.8`
   - `wm_max_step`: `8.5` | `wm_min_step`: `0.8`
   - `anti_tremor_deadband`: `1.5`
   - `smooth_reaction_min`: `0.04` | `smooth_reaction_max`: `0.08`

### 2.2. Đóng gói Preset mẫu chuyên dụng
- File preset đồng bộ: `configs/toggle_edpi253_dpi1100.json`.

### 2.3. Đồng bộ hóa lên Private GitHub Repository
- Repo `https://github.com/prohpea/CVM-colorBot`:
  - `config.json`: Commit `5d4b09689b5b1cb7844af757702120cd08a47432`
  - `configs/toggle_edpi253_dpi1100.json`: Commit `eb20e2ebda50ba1faeeb584c3bb4367d298bf572`

---

## 3. Tệp Bàn Giao Kỹ Thuật Cho Tester
- `config.json`
- `configs/toggle_edpi253_dpi1100.json`

**Lệnh chuyển giao:** Chuyển giao sang cho **Tester Agent (`Gemini 3.8 Flash`)** kiểm thử và xác thực.
