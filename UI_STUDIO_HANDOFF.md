# Handoff: áp UI "Studio Workspace" (bộ 2) vào CVM colorBot

Tài liệu này để đưa cho một AI/developer khác tự thực hiện. Mô tả đích đến, điểm cắm trong code thật, và prompt sẵn copy ở cuối.

---

## 1. Tham chiếu thiết kế

- Mockup tương tác: `ui_concepts.html` → mở `#c2` (nút **02 / Studio Workspace**).
- Ảnh chốt: `ui_concept2.png` (1280×820) — đây là màn **General**.
- Đặc trưng cần đạt: nền `#F5F7FB`, sidebar trắng 232px, header trắng 66px, card trắng bo 13px viền 1px `#E6EBF3`, accent xanh `#2563EB`, success `#10B981`, chữ `#172033`, muted `#94A3B8`. Font đích `Inter`, nhưng máy không có Inter/Roboto → dùng `Segoe UI`.

## 2. Nguyên tắc bắt buộc

1. **Chỉ sửa lớp UI.** Không đụng `aim_system`, `capture`, `detection`, `mouse`, thuật toán hay config payload của runtime.
2. **Thêm style thứ 3**, không xóa `classic`/`neon`; nút "UI Style" chuyển vòng 3 mode.
3. **Giữ nguyên mọi callback** (`command=...`, `variable=...`, `_ignore_settings_events`, runtime lock). Chỉ đổi container/appearance.
4. Không ép pixel-perfect: `customtkinter 5.2.2` không có `box-shadow`, gradient, blur. Bỏ bóng hoặc giả bằng frame lệch 1–2 px; không thêm dependency.
5. Mọi text mới đi qua `t()` / `heading()` từ `src.utils.i18n` để không vỡ đa ngôn ngữ.

## 3. Bản đồ code (đo tại thời điểm viết)

| File | Vị trí | Vai trò |
|---|---|---|
| `src/ui.py` | `THEME_PRESETS` (~dòng 31) | 2 preset `neon` / `classic`, gồm `COLOR_*` và `FONT_*` |
| `src/ui.py` | `_apply_theme_preset()` (~73) | Đổ preset vào `globals()` |
| `src/ui.py` | `ViewerApp.__init__` (~243) | Đọc `config.legacy_ui_mode`, áp preset, `overrideredirect(True)` |
| `src/ui.py` | `_build_layout()` (~394) | grid: title bar (row 0) + sidebar (col 0) + `content_frame` (col 1) |
| `src/ui.py` | `_build_title_bar()` (~415) | Title bar tự vẽ, nút `_ / [] / X` |
| `src/ui.py` | `_build_sidebar()` (~515) | Nav, status, FPS/delay, nút START/STOP, Settings |
| `src/ui.py` | `_show_general_tab()` (~1254) | Màn cần dựng lại đúng demo |
| `src/ui.py` | `_show_aimbot_tab()` (~4660), `_show_sec_aimbot_tab()` (~4958), `_show_tb_tab()` (~5252), `_show_magnet_trigger_tab()` (~5607), `_show_rcs_tab()` (~5612), `_show_config_tab()` (~5682), `_show_debug_tab()` (~5715) | 7 tab còn lại (phase 2) |
| `src/ui.py` | `_create_collapsible_section()` (~5976), `_add_slider_in_frame()` (~6067), `_add_switch_in_frame()` (~6149), `_add_option_row_in_frame()` (~6100), `_add_range_slider_in_frame()` (~6227) | **Helper quan trọng**: đã nhận `parent` → tái dùng được |
| `src/ui.py` | `_toggle_ui_style()` (~1214), `_rebuild_layout_for_ui_style()` (~1219) | Chuyển style + rebuild; có `tab_map` 8 màn cần cập nhật |
| `src/ui.py` | `UpdateDialog` (~11011), `SettingsWindow` (~11226) | 2 cửa sổ phụ (phase 2) |
| `src/utils/config.py` | dòng 283 (`__init__`), 607 (`to_dict`), 935 (`load`) | `self.legacy_ui_mode` — mẫu để thêm `ui_style` |
| `main.py` | dòng 1119–1121 | `ctk.set_appearance_mode("Dark")` + `set_default_color_theme("themes/metal.json")` |
| `themes/metal.json` | toàn file | Theme JSON hiện tại (dark) — mẫu để làm `studio.json` |

Quy mô: `src/ui.py` 11.535 dòng / 541 KB; 228 `fg_color=`, 188 `font=`, 420 `.pack()`. Không viết lại toàn file.

## 4. Token màu (demo → giá trị code)

| Dùng cho | Demo CSS | Giá trị đưa vào CTk |
|---|---|---|
| Nền app | `#F5F7FB` | `COLOR_BG` |
| Sidebar / header / card | `#FFFFFF` | `COLOR_SURFACE` |
| Viền card | `#E6EBF3` | `COLOR_BORDER` |
| Accent / active nav / CTA | `#2563EB` | `COLOR_ACCENT` |
| Accent hover | `#1D4ED8` | `COLOR_ACCENT_HOVER` |
| Success / connected | `#10B981` | `COLOR_SUCCESS` |
| Chữ chính | `#172033` | `COLOR_TEXT` |
| Chữ phụ | `#94A3B8` | `COLOR_TEXT_DIM` |
| Active nav bg | `#EAF1FF` | `COLOR_NAV_ACTIVE_BG` |
| Hover nav bg | `#F1F5FB` | `COLOR_NAV_HOVER_BG` |
| Font | `Inter` | `("Segoe UI", 11)`, bold `("Segoe UI", 11, "bold")`, title `("Segoe UI", 18, "bold")` |

## 5. Ánh xạ component

| Demo | CTk |
|---|---|
| Sidebar 232px, nhóm WORKSPACE / AIM / TRIGGER | `CTkFrame(width=232)` + `CTkLabel` nhóm + `CTkButton(anchor="w", fg_color="transparent")` |
| Nav item active (pill xanh nhạt) | `CTkButton(fg_color=COLOR_NAV_ACTIVE_BG, text_color=COLOR_ACCENT)` |
| Header 66px, title + subtitle + pill profile | `CTkFrame(height=66)` + `CTkLabel` |
| Card trắng bo 13px, viền 1px | `CTkFrame(corner_radius=13, border_width=1, border_color=COLOR_BORDER, fg_color=COLOR_SURFACE)` |
| Banner "Almost ready" | `CTkFrame` + `CTkLabel` + `CTkButton(link)` |
| Segmented (Medius / Serial / …) | Dùng `CTkSegmentedButton` hoặc cụm `CTkButton` giả (dễ style active hơn) |
| Slider track/fill/knob | `CTkSlider(progress_color=COLOR_ACCENT, button_color=COLOR_SURFACE, button_hover_color=COLOR_ACCENT)` — giữ nguyên `command` |
| Toggle 34×19 | `CTkSwitch(button_length=0, progress_color=COLOR_ACCENT, fg_color=...)` |
| Progress 3 bước | `CTkProgressBar(progress_color=COLOR_ACCENT)` + 3 `CTkLabel` |
| Stats 4 ô | `CTkFrame` lưới `grid(row, column)` |
| CTA "START ENGINE" | `CTkButton(fg_color=COLOR_ACCENT, text_color="white", command=self._toggle_runtime)` |

## 6. Các bước thực hiện

### Phase 1 — Shell + màn General đúng demo (phạm vi nên làm trước)

1. **Config**: trong `src/utils/config.py` thêm `self.ui_style = "classic"` cạnh dòng 283; thêm `"ui_style": self.ui_style` cạnh dòng 607; đọc `self.ui_style = str(getattr(self, "ui_style", "classic"))` cạnh dòng 935. Giữ `legacy_ui_mode` để config cũ vẫn load được.
2. **Theme JSON**: tạo `themes/studio.json` từ `themes/metal.json`, đổi toàn bộ màu sang bảng mục 4 (giá trị `["light-mode", "dark-mode"]` — có thể ghi cùng một giá trị cho cả hai).
3. **Preset**: thêm `THEME_PRESETS["studio"]` với token mục 4; sửa `_apply_theme_preset` để fallback an toàn về `classic`.
4. **Khởi tạo**: `ViewerApp.__init__` đọc `config.ui_style`; gọi `_apply_theme_preset` đúng preset. Trong `main.py`, chọn `ctk.set_appearance_mode("Light")` và `set_default_color_theme("themes/studio.json")` khi `ui_style == "studio"`, ngược lại giữ Dark + `metal.json`. Lưu ý: đổi appearance mode lúc runtime cần rebuild — dùng lại `_rebuild_layout_for_ui_style()`.
5. **Shell**: sửa `_build_layout` / `_build_title_bar` / `_build_sidebar` theo mode `studio`:
   - Sidebar 232px: logo, nhóm `WORKSPACE` (General, Configuration, Debug & logs), `AIM` (Main Aimbot, Secondary Aimbot, RCS), `TRIGGER` (Triggerbot, Magnet Trigger), cuối là card "Getting started 2 of 3" + progress + nút START ENGINE.
   - Header 66px: tiêu đề màn + subtitle, pill profile, pill ngôn ngữ.
   - `content_frame` giữ nguyên là `CTkScrollableFrame`; đổi padx/pady cho thoáng.
6. **Helper mới**: thêm `_studio_card(parent, title, subtitle)` trả về frame nội dung; `_studio_field(...)`, `_studio_toggle_row(...)`, `_studio_slider_row(...)`. **Không** viết lại logic — gọi `_add_slider_in_frame`, `_add_switch_in_frame`, `_add_option_row_in_frame` với `parent` là frame nội dung card.
7. **General**: dựng lại `_show_general_tab()` gồm banner + 2 card cặp (Hardware API, Capture source) + card Detection (full width) + 2 card (Aimbot quick settings, Performance). Giữ y hệt tên biến `tk.BooleanVar`, `_ignore_settings_events`, lệnh `config.* = ...` và `command=` cũ.
8. **Chuyển style**: `_toggle_ui_style()` chuyển vòng `classic → neon → studio → classic`; cập nhật `tab_map` trong `_rebuild_layout_for_ui_style()`; text nút dùng `t("UI Style: {style}", style=...)`.
9. **Không đụng** `_show_aimbot_tab` trở đi ở phase này — chúng vẫn chạy với preset sáng và layout cũ.

### Phase 2 — Đồng bộ toàn app (làm sau khi phase 1 chạy ổn)

10. Migrate 7 tab còn lại sang card, dùng chung `_studio_card`.
11. Style `SettingsWindow` và `UpdateDialog` theo light theme.
12. Thay `Segoe UI` bằng font đúng nếu sau này bundle kèm `Inter.ttf` (không thêm dependency lúc này).

## 7. Checklist nghiệm thu

- [ ] `run.bat` khởi động không traceback; splash đóng bình thường.
- [ ] Nút UI Style chuyển đủ 3 mode; chọn `studio` → reload config vẫn giữ `studio`.
- [ ] General: bật/tắt Hardware/Capture/Detection ghi đúng vào `config` và lưu file config.
- [ ] Khi runtime đang chạy, `_apply_runtime_settings_lock()` vẫn khóa đúng field (không mở khóa ngoài ý muốn).
- [ ] Chuyển tab qua lại 8 màn không lỗi widget bị destroy; `_set_nav_active` highlight đúng item.
- [ ] Đổi ngôn ngữ (Settings) không gặp text hard-code mới.
- [ ] So sánh ảnh chụp màn General với `ui_concept2.png`: khớp bố cục, màu, khoảng cách; chấp nhận khác font/bóng.

## 8. Prompt sẵn copy cho AI

```text
Nhiệm vụ: áp concept UI "Studio Workspace" vào tool CVM colorBot (Python + customtkinter 5.2.2) tại C:\Users\TeamOS\Desktop\CVM Source Code\CVM.

Tham chiếu thiết kế: mở ui_concepts.html#c2 hoặc ảnh ui_concept2.png. Màn cần khớp là General. Chi tiết token màu, ánh xạ widget, điểm cắm code: đọc file UI_STUDIO_HANDOFF.md trong thư mục dự án trước khi sửa.

RÀNG BUỘC:
- Chỉ sửa lớp UI. Không đụng src/aim_system, src/capture, src/utils/detection.py, src/utils/mouse*, logic runtime trong main.py ngoài đoạn set appearance/theme.
- Không thêm dependency. Giữ classic/neon; thêm mode thứ 3 tên "studio". Giữ nguyên mọi callback, BooleanVar, lệnh ghi config, runtime lock và i18n t().
- Không viết lại src/ui.py (11.5k dòng). Dùng helper có sẵn nhận parent: _add_slider_in_frame, _add_switch_in_frame, _add_option_row_in_frame, _create_collapsible_section / card helper mới.
- Font thay Inter bằng Segoe UI. Không cố dựng box-shadow/gradient bằng CTk thuần.

LÀM THEO THỨ TỰ:
1) Thêm config.ui_style (init/serialize/load) cạnh legacy_ui_mode trong src/utils/config.py.
2) Tạo themes/studio.json (light) từ themes/metal.json; thêm THEME_PRESETS["studio"] và cập nhật _apply_theme_preset trong src/ui.py.
3) main.py: chọn Light + studio.json khi ui_style=="studio", ngược lại Dark + metal.json.
4) src/ui.py: _build_layout/_build_title_bar/_build_sidebar nhánh studio = sidebar trắng 232px (nhóm WORKSPACE/AIM/TRIGGER + card Getting started + START ENGINE), header 66px, content_frame scrollable.
5) Thêm helper _studio_card/_studio_field/_studio_toggle_row/_studio_slider_row.
6) Dựng lại _show_general_tab đúng mockup: banner, 2 card Hardware API & Capture source, card Detection full-width, 2 card Aimbot quick settings & Performance. Giữ nguyên handler/config cũ.
7) _toggle_ui_style chuyển vòng 3 mode; cập nhật tab_map trong _rebuild_layout_for_ui_style.
8) Dừng ở đây. 7 tab còn lại và 2 cửa sổ phụ giữ nguyên, báo rõ phần chưa migrate.

KIỂM TRA: chạy run.bat; mở app; chuyển 3 style; bật/tắt từng điều khiển ở General; đổi tab qua lại; reload config; đảm bảo runtime lock vẫn khóa field. Báo kết quả thực tế (có/không lỗi), không chỉ nói "xong".

Nếu phát hiện xung đột với code thật, dừng và hỏi trước khi đổi thiết kế.
```

---

## 9. Phạm vi & rủi ro đã biết

- **Không đạt được**: font Inter (máy không có), box-shadow của card, bo/knob slider y hệt CSS. Đây là limits của customtkinter, không phải lỗi implementation.
- **Rủi ro lớn nhất**: rebuild layout trong lúc runtime đang chạy → mất reference widget. Phải dùng `_apply_runtime_settings_lock()` và `winfo_exists()` như code hiện tại.
- **Rủi ro thứ hai**: đổi appearance mode sau khi widget đã tạo có thể không apply màu đúng; luôn rebuild layout sau khi đổi.
- Phase 1 chỉ khớp đúng màn General; 7 tab còn lại mang layout cũ nhưng vẫn dùng palette sáng — đây là điểm cần chốt với người dùng trước khi làm phase 2.
