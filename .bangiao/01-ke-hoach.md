# 01 — KẾ HOẠCH TÁI KIẾN TRÚC UI: SIMPLE MODE NHẸ, PRO MODE NGUYÊN VẸN, LAUNCHER ẨN/HIỆN CHẮC CHẮN

**Mã hiệu:** `PLAN-20261111-UI-SIMPLE-PRO-LAUNCHER`
**Vai trò:** Planner (Dây chuyền 4 Agent `/ship`)
**Trạng thái:** Chỉ đọc mã nguồn — phân tích — thiết kế — lập kế hoạch. **Không sửa một dòng mã nguồn nào.**
**Tài liệu được thay thế:** `.bangiao/01-ke-hoach.md` phiên bản `PLAN-20261109-FLICK-V2-UI-210`. Lõi Flick V2/Calibration của bản đó **đã thi công xong** và được coi là baseline không được phá vỡ.
**Phạm vi đọc:** `main.py`; `src/ui.py` (11.789 dòng); `src/ui_components.py`; `src/ui_tabs/{common,flick_tab,calibration_tab,magnet_trigger_tab}.py`; `src/ui_hsv_preview.py`; `src/utils/config.py`; `src/utils/{i18n,activation,network_feedback,debug_logger,mouse_input}.py`; `src/utils/mouse/{__init__,keycodes,state}.py`; `src/version.py`; `run.bat`; `setup.bat`; `config.json`; `locales/*.json`; toàn bộ `tests/*.py`; `docs/superpowers/{specs,plans}/2026-11-07-modern-gaming-dashboard-ui-redesign.md`; `CHANGELOG.md`.

> **Ghi chú môi trường:** trong phiên Planner này, mọi lệnh `pwsh` trả về `0xC0000142` (DLL init failed) nên **không thể chạy test/benchmark hay đo thời gian thực**. Mọi kết luận dưới đây là phân tích tĩnh, đối chiếu số dòng và hành vi Tk/customtkinter đọc trực tiếp từ `venv/Lib/site-packages/customtkinter/`. Các lệnh kiểm chứng được liệt kê ở §13 để Coder/Tester chạy trong bước thi công.

---

## 1. KẾT LUẬN ĐIỀU HÀNH

Yêu cầu của người dùng gồm ba phần, và cả ba đều đúng — nhưng nguyên nhân không nằm ở "CSS" hay "theme", mà ở **kiến trúc vòng đời cửa sổ và vòng lặp timer**:

1. **"Có 2 biến thể Simple và Pro đúng không?"** — Đúng trên nhãn, **sai trên thực tế**. `ui_pro_mode` chỉ đổi màu/chữ của một nút và đóng bớt vài section; **không có layout Simple nào tồn tại**. Kích thước cửa sổ vẫn `980x660`, sidebar 210 px vẫn dựng, `CTkScrollableFrame` vẫn bọc content, và mọi card vẫn được build. Vì vậy "Simple" hiện tại = "Pro thu nhỏ bằng tay", kéo theo toàn bộ chi phí layout của Pro.
2. **"Simple bị giật khựng khi thu nhỏ"** — Có **bốn nguồn giật độc lập**, trong đó hai nguồn là lỗi thật (không phải cảm giác):
   - **Rò rỉ chuỗi timer clipboard**: mỗi 1,2 s scheduler gọi `_poll_clipboard_config_import()`, và chính hàm này lại tự `after()` chính nó. Số chuỗi timer tăng tuyến tính theo thời gian, số callback mỗi giây tăng **bậc hai**. Sau ~10 phút mở app có thể có ~500 chuỗi → ~400 callback/giây, kể cả khi cửa sổ đang thu nhỏ. Đây là "giật khựng tích lũy" đúng nghĩa.
   - **Bão sự kiện `<Map>`**: `self.bind("<Map>", self._on_window_map)` trên toplevel. Tk đưa **tên toplevel vào bindtags của mọi widget con**, nên mỗi widget con được map (mỗi lần đổi tab, mở section, đổi mode, mở tooltip…) đều gọi `_on_window_map`, hàm này gọi `overrideredirect(True)` — một thao tác style Win32 có thể phát sinh map/unmap tiếp. Đây là vòng khuếch đại sự kiện, không phải "vẽ nhiều".
   - **Rebuild đồng bộ cả tab** trong callback đổi mode/ADS/theme/ngôn ngữ, cộng với `_toggle_pro_mode()` xóa sạch `_collapsible_section_states` rồi rebuild → mất trạng thái người dùng và tạo 50–150 ms freeze mỗi lần.
   - **Cập nhật widget mù**: `_update_performance_stats()` gọi `configure()` trên 3 label mỗi 250 ms dù chuỗi không đổi; `_update_connection_status_loop()` gọi thêm 3–5 `configure()` mỗi 500 ms; `_set_status_indicator()` gọi `t()` + `configure()` mỗi tick. Ở cửa sổ nhỏ, mỗi lần `configure` là một lần Tcl → Tk → Win32 invalidate.
3. **"Tool launcher rất khó chọn khi đã ẩn đi"** — Có **chuỗi lỗi nhân quả rõ ràng**:
   - `_on_minimize()` gọi `overrideredirect(False)` rồi `iconify()`. Việc tắt overrideredirect khi cửa sổ đang mapped khiến Tk/Win32 tạo lại style; `WS_EX_APPWINDOW` bị mất.
   - `_taskbar_style_applied` **không bao giờ được reset**, nên `_on_window_map()` không gọi lại `_ensure_taskbar_icon()` sau khi restore → **icon taskbar biến mất vĩnh viễn** cho tới khi restart.
   - `_ensure_taskbar_icon()` dùng thủ thuật `withdraw()` + `deiconify()` + `alpha=0` để "làm mới shell" → tạo thêm Map/Unmap, nháy cửa sổ, và có thể mất focus.
   - **Không có global hotkey, không có tray icon, không có single-instance guard.** Cửa sổ borderless không nằm trong Alt-Tab đáng tin cậy; người dùng bấm lại `run.bat` thì lại mở **instance thứ hai** (không thấy cửa sổ cũ), tạo thêm icon/tranh chấp hotkey.
   - Khi cửa sổ bị `withdraw()` (nếu tương lai có hide), nó **không còn taskbar button** — không có hotkey/tray thì không thể quay lại nếu game đang fullscreen.

**Kết luận:** cần một **mode state machine thật** (Simple là layout riêng, không phải Pro thu nhỏ), **một scheduler duy nhất không nhân bản**, **một lớp Win32 window lifecycle** thay cho các thủ thuật `overrideredirect`/`withdraw/deiconify`, và **một launcher toàn cục** (hotkey + tray + single-instance + taskbar restore). Pro phải được chứng minh **không đổi hành vi** bằng checklist và test hồi quy.

---

## 2. HIỆN TRẠNG ĐO ĐƯỢC (BẰNG CHỨNG MÃ NGUỒN)

### 2.1. "Simple" hiện tại là gì

| # | Bằng chứng | Hệ quả |
|---|---|---|
| S1 | `ui.py:328` `self.geometry("980x660")` — không có nhánh nào đổi geometry theo `ui_pro_mode` | Simple vẫn 980×660 |
| S2 | `ui.py:686` sidebar luôn được dựng, width 210 | Simple vẫn có sidebar |
| S3 | `ui.py:543` `content_frame = ctk.CTkScrollableFrame(...)` luôn được dựng | Simple vẫn có scrollable lồng |
| S4 | `ui.py:1449-1474` `_toggle_pro_mode()` chỉ đổi text/màu nút, `clear()` state, rồi gọi lại handler tab | Không có layout mới; còn **xóa state section của người dùng** |
| S5 | `ui.py:6910-6917` heuristic "Simple thì đóng section kỹ thuật" chỉ áp dụng **một lần** khi cache key chưa tồn tại; nhưng `_create_collapsible_section` luôn ghi state (`:6970`) | Sau lần build đầu, heuristic **không bao giờ chạy lại** |
| S6 | `config.py:437` `ui_pro_mode=False`; `config.py:914`, `:1373` persist/validate | Persist đã đúng (C13 cũ đã sửa), nhưng giá trị này không điều khiển layout |
| S7 | `config.json:354` `"ui_pro_mode": true` | Máy hiện tại luôn khởi động ở "Pro nhãn" |

**Kết luận S:** Không thể "tối ưu Simple" bằng cách thêm `if` vào layout hiện tại. Phải có **builder riêng** và **teardown riêng**.

### 2.2. Kiểm kê chi phí widget / timer

| Hạng mục | Số liệu | Ghi chú |
|---|---|---|
| Constructor `ctk.CTk*` trong `ui.py` | **390** lời gọi (grep `CTkLabel|CTkFrame|CTkButton|CTkEntry|CTkSwitch|CTkSlider|CTkOptionMenu|CTkSegmentedButton|CTkTextbox`) | Mỗi `CTkFrame` = `tk.Frame` + `tk.Canvas`; mỗi `CTkSlider` = frame + 2 canvas. Tổng widget Tk thực tế **lớn hơn nhiều lần** con số 390 |
| Tab Combat (`_show_aimbot_tab`) | 4 `ModernCard` + card Calibration + ~30 slider/option rows | Mỗi lần đổi mode → destroy + rebuild toàn bộ |
| `CTkScrollableFrame` | 4 chỗ: content (`:543`), sidebar nav (`:933`), probe list (`:4204`), HSV preview (`ui_hsv_preview.py:143`) | Mỗi cái `bind_all("<MouseWheel>")` + `bind("<Configure>")` + canvas window |
| Timer `after()` trực tiếp | 33 lời gọi | Chưa kể các chain tự nhân bản |
| Chain clipboard | `_ui_tick` gọi `_poll_clipboard_config_import()` (`:521`); hàm này tự `after()` chính nó (`:9015`) | **Nhân bản chuỗi** — xem §3.1 |
| PID preview | `ui.py:7715` tạo `tk.Canvas`; `:7743` bind `<Configure>`; `:7744` `after(20, _refresh_pid_preview)` | Vẽ lại toàn bộ canvas mỗi lần resize; không có job id để cancel |
| Cập nhật label định kỳ | 3 label @250 ms (`:10070-10125`) + 3–5 label @500 ms (`:10013-10020`) + status @100 ms | Không so sánh giá trị trước khi `configure` |

### 2.3. Chuỗi minimize → restore hiện tại (tái hiện lỗi)

```
Người dùng bấm "_"
  └─ _on_minimize()                         ui.py:7531
       ├─ self.overrideredirect(False)      ← Tk/Win32 đổi style, có thể tạo lại HWND state
       └─ self.iconify()                    ← cửa sổ vào taskbar
            │
            ├─ Tk phát <Unmap>/<Map> cho nhiều widget con
            │     └─ _on_window_map(event)  ui.py:7525  (bindtags: con → class → TOPLEVEL → all)
            │           ├─ if state == "normal": ...
            │           └─ overrideredirect(True)  ← tranh chấp với trạng thái minimized
            │
            └─ _taskbar_style_applied vẫn = True   (đặt từ lần đầu, ui.py:7598)
                  └─ _ensure_taskbar_icon() KHÔNG chạy lại
                        └─ WS_EX_APPWINDOW đã mất → KHÔNG còn icon taskbar
Người dùng bấm icon taskbar (nếu còn) / Alt-Tab
  └─ Tk deiconify → _on_window_map
       ├─ overrideredirect(True)             ← trả lại borderless
       └─ KHÔNG re-apply WS_EX_APPWINDOW     ← icon vẫn mất
```

Nếu người dùng đóng bằng `X`, `_on_close()` (`:10161`) **destroy hẳn** app — không có "ẩn". Nếu họ muốn ẩn để chơi game, lựa chọn duy nhất là minimize, và minimize đang tự phá taskbar integration.

### 2.4. Vì sao bấm lại `run.bat` không "gọi" được cửa sổ cũ

- `run.bat:38` chạy `venv\Scripts\python.exe main.py` **không truyền tham số**, không kiểm tra instance.
- `main.py:1265-1334` không có mutex/single-instance; mỗi lần chạy là một `ViewerApp` mới, một `AimTracker` mới (mở capture/mouse), một hotkey mới (nếu có).
- Kết quả: người dùng thấy "không có gì xảy ra" (cửa sổ mới mở sau cửa sổ cũ, hoặc bị game che), hoặc thấy 2 icon, hoặc tranh chấp thiết bị.

---

## 3. PHÂN TÍCH NGUYÊN NHÂN GỐC (ROOT CAUSE)

### 3.1. RC-1 (P0): Chuỗi timer clipboard nhân bản theo cấp số nhân

**Cơ chế:**

```python
# ui.py:517-521  (trong _ui_tick, mỗi ~1.2 s)
self._poll_clipboard_config_import()

# ui.py:9007-9017
def _poll_clipboard_config_import(self):
    try:
        self._maybe_prompt_clipboard_config_import()
    finally:
        self.after(self._clipboard_import_poll_interval_ms,   # 1200 ms
                   self._poll_clipboard_config_import)        # ← tự nhân bản
```

Gọi hàm này một lần = tạo thêm **một chuỗi vĩnh viễn**. Scheduler gọi nó mỗi 1,2 s → sau `t` giây có `C(t) ≈ t / 1.2` chuỗi; mỗi chuỗi bắn 1 callback/1,2 s → tốc độ callback `≈ t / 1.44` **mỗi giây**. Ở phút thứ 10: ~417 callback/giây. Mỗi callback khi đang ở tab Profiles còn gọi `clipboard_get()` (mở clipboard Win32) — tranh chấp clipboard với game/OBS và gây khựng rõ rệt. Khi cửa sổ thu nhỏ, `_ui_tick` ngủ 500 ms nhưng **các chuỗi đã sinh vẫn tiếp tục chạy**, nên "thu nhỏ càng lâu càng giật".

Ngoài ra `_show_config_tab()` còn `self.after(100, self._maybe_prompt_clipboard_config_import)` (`:6617`) — mỗi lần vào tab lại gieo thêm một hạt giống timer.

**Chi tiết còn tệ hơn — tính năng đã chết nhưng chi phí vẫn còn:** `_maybe_prompt_clipboard_config_import()` mở đầu bằng

```python
if str(getattr(self, "_active_tab_name", "")) != "Config":
    return
```

(`ui.py:9020`) nhưng `_show_config_tab()` đặt `self._active_tab_name = "Profiles"` (`ui.py:6570`). Vì `"Profiles" != "Config"`, **hàm luôn return ngay** → clipboard auto-import hiện **không bao giờ chạy**. Nghĩa là chuỗi timer nhân bản chỉ tạo ra **100 % overhead, 0 % tính năng**. Đây là bằng chứng mạnh nhất rằng phải bỏ self-reschedule thay vì "tối ưu nhẹ".

**Đây là lỗi P0 số một và giải thích chính xác triệu chứng "để một lúc thì giật, thu nhỏ càng giật".**

### 3.2. RC-2 (P0): `<Map>` binding lan xuống toàn bộ widget con

Tk gán bindtags mặc định cho mọi widget: `(widgetPath, className, toplevelPath, "all")`. Vì `self` là toplevel, `self.bind("<Map>", ...)` **nhận cả sự kiện Map của mọi widget con**. Trong một lần rebuild tab có thể có hàng trăm widget con được map → hàng trăm lần:

```python
self.overrideredirect(True)     # ui.py:7527
self.after(0, self._ensure_taskbar_icon)   # nếu chưa applied
```

`overrideredirect` trên Windows là thay đổi style cửa sổ, có thể làm cửa sổ re-map → sinh thêm `<Map>` → vòng lặp. Đây là lý do đổi tab/đổi mode/mở section bị "khựng" ngay cả khi cửa sổ lớn, và tệ hơn khi cửa sổ nhỏ vì mỗi lần invalidate đắt hơn tương đối.

**Sửa bắt buộc:** `if event is not None and event.widget is not self: return`, cộng thêm cờ `_ui_rebuilding` và một hàm `_sync_window_style()` idempotent (chỉ gọi Win32 khi style signature đổi).

### 3.3. RC-3 (P0): Rebuild đồng bộ + xóa state khi đổi mode

- `_toggle_pro_mode()` (`:1449`): `self._collapsible_section_states.clear()` → mất toàn bộ trạng thái mở/đóng người dùng đã set; sau đó gọi handler tab → `_clear_content()` destroy toàn bộ widget → build lại. Trên máy chậm: 50–150 ms freeze; trên máy nhanh: nháy trắng + mất scroll position.
- `_on_mode_selected()` (`:10579`) và `_on_mode_sec_selected()` (`:10589`) gọi thẳng `_show_aimbot_tab()` / `_show_sec_aimbot_tab()`.
- `_on_ads_fov_enabled_changed()` (`:10411`) và `_on_ads_fov_enabled_sec_changed()` (`:10653`) cũng rebuild cả tab.
- `_toggle_ui_style()` (`:1602`) và `_apply_language()` (`:1652`) rebuild **toàn bộ layout** (title bar + sidebar + content).

**Hệ quả:** mọi thao tác cấu hình phổ biến đều là thao tác "phá và dựng lại DOM". Với Simple mode, đây là điều tối kỵ.

### 3.4. RC-4 (P1): Cấu trúc widget lồng nhau quá sâu

Một card điển hình: `CTkScrollableFrame` → `CTkFrame` (ModernCard) → `CTkFrame` header → `CTkFrame` title_left → `CTkLabel`; content → row `CTkFrame` → header `CTkFrame` → label + entry + `CTkSlider` (2 canvas). Mỗi slider thực tế ~8–10 widget Tk. Một tab 30 slider ≈ 250–300 widget Tk, chưa kể option menu (menu + dropdown toplevel), tooltip, sidebar.

Khi cửa sổ nhỏ, `CTkScrollableFrame` phải:
- `bind("<Configure>")` trên chính nó → `scrollregion = bbox("all")` (duyệt toàn bộ item),
- `bind("<Configure>")` trên canvas → `itemconfigure(width=...)` → ép **toàn bộ** widget con re-layout,
- `bind_all("<MouseWheel>")` trên mỗi scrollable (4 cái) → mỗi sự kiện chuột chạy qua 4 handler, mỗi handler đệ quy `check_if_master_is_canvas` lên chuỗi master.

Đây là chi phí O(số widget) cho **mỗi** pixel thay đổi kích thước. Simple mode phải **không có scrollable** và **không có sidebar**.

### 3.5. RC-5 (P1): Scheduler cập nhật mù, không so sánh giá trị

`_update_performance_stats()` (`:10059`) chạy 4 lần/giây, mỗi lần `configure()` 3 label (kể cả khi text y hệt). `_update_connection_status_loop()` (`:10029`) chạy 2 lần/giây, gọi `_update_hardware_status_ui()` (`:9995`) → 2 `configure()` + có thể build chuỗi hardware details; gọi `_refresh_capture_entry_card()`. `_set_status_indicator()` (`:989`) gọi `t()` (tra từ điển) + `configure()` mỗi lần.

Trong Simple mode, các label này **không tồn tại** → `AttributeError` bị nuốt bởi `except` và `log_print` mỗi 250 ms → log phình + `_update_debug_log` format. Phải chuyển sang mô hình "tính một lần → chỉ ghi khi đổi → chỉ ghi nếu widget tồn tại".

### 3.6. RC-6 (P1): Collapsible state bị ghi đè và không bao giờ "trả lại"

`_create_collapsible_section()` luôn `_set_collapsible_state(cache_key, initial_open_state)` (`:6970`) và ghi vào `config.ui_collapsible_states`. Vì vậy:
- Lần đầu mở app, mọi section đều có state → heuristic Simple (`:6910`) không bao giờ áp dụng lại.
- `_toggle_pro_mode()` xóa state → rebuild → ghi lại state theo mặc định của Pro → quay về Simple vẫn thấy y như Pro.
- `config.json` phình theo số tab đã mở.

### 3.7. RC-7 (P0 — launcher): `overrideredirect` + taskbar + thiếu hotkey/tray/single-instance

Chi tiết ở §2.3 và §2.4. Bổ sung các điểm kỹ thuật:

| # | Vấn đề | Bằng chứng | Hệ quả |
|---|---|---|---|
| L1 | Tắt overrideredirect khi minimize rồi bật lại khi map | `:7531-7533`, `:7525-7529` | Style Win32 bị tái tạo, mất `WS_EX_APPWINDOW`, nháy title bar native |
| L2 | `_taskbar_style_applied` không reset | `:7598`, `:7551`, `:7528` | Không bao giờ re-apply sau restore |
| L3 | "Shell refresh" bằng `withdraw()+deiconify()+alpha=0` | `:7582-7597` | Nháy cửa sổ, mất focus, sinh Map/Unmap |
| L4 | Không có global hotkey | grep `RegisterHotKey|WM_HOTKEY` = 0 | Không thể hiện UI khi game fullscreen |
| L5 | Không có tray icon | grep `Shell_NotifyIcon|pystray` = 0 | Không có điểm neo khi cửa sổ withdrawn |
| L6 | Không có single-instance | `main.py` không có mutex/event | Bấm lại `run.bat` mở instance thứ hai |
| L7 | `-topmost` luôn False | `:346` | Cửa sổ có thể nằm sau cửa sổ khác; restore không nổi lên |
| L8 | Maximize = `screen_w x screen_h +0+0` | `:7544-7547` | Che taskbar; khi minimize từ fullscreen, hình học restore có thể sai |
| L9 | `_on_close` destroy ngay, không dọn hotkey/tray (vì chưa có) | `:10161` | Nếu thêm hotkey/tray mà không dọn sẽ treo tiến trình |
| L10 | `run.bat` dùng `python.exe` (có console), không truyền `--show` | `run.bat:38` | Console chiếm focus; không thể "gọi" instance cũ |

### 3.8. Tổng hợp nhân quả

```
Thiếu layout Simple thật (S1–S7)
        │
        ├──► vẫn dựng 390 constructor + sidebar + 4 scrollable
        │           │
        │           ├──► resize nhỏ → mỗi <Configure> re-layout O(widget)
        │           └──► mỗi widget con map → _on_window_map → overrideredirect
        │
        ├──► mọi thay đổi mode/ADS/theme → destroy + rebuild cả tab (freeze)
        │
        └──► scheduler 10 Hz cập nhật label mù + RC-1 nhân bản timer
                                │
                                └──► sau vài phút: hàng trăm callback/giây
                                        └──► "giật khựng", tệ nhất khi thu nhỏ

Minimize dùng overrideredirect + iconify (L1–L2)
        │
        ├──► mất WS_EX_APPWINDOW → mất icon taskbar
        ├──► không hotkey/tray (L4–L5) → không đường quay lại
        └──► bấm run.bat → instance thứ hai (L6) → càng rối
```

---

## 4. KIẾN TRÚC ĐÍCH

### 4.1. Nguyên tắc thiết kế

1. **Hai layout là hai cây widget khác nhau**, không phải hai bộ `if` trên cùng cây. Simple có builder riêng; Pro giữ nguyên builder hiện tại.
2. **Một scheduler duy nhất**, không bao giờ tự nhân bản; mỗi nhánh có cadence riêng theo mode; mọi update đi qua helper "chỉ ghi khi đổi + chỉ ghi nếu widget tồn tại".
3. **Một lớp Win32 window lifecycle** (`src/utils/win32_window.py`) là nơi duy nhất gọi `ShowWindow`, `SetWindowLongPtrW`, `SetWindowPos`, `SetForegroundWindow`. `ui.py` không tự gọi `ctypes.windll.user32` rải rác cho cửa sổ chính.
4. **Hotkey/tray/single-instance nằm ngoài Tk thread**, giao tiếp với UI qua `queue.Queue` + poll `after(40)` — không gọi Tk API từ thread phụ.
5. **Pro là hợp đồng bất biến**: mọi attribute/hành vi hiện có phải còn; test hồi quy + checklist §6.4 là bằng chứng.
6. **Mọi thay đổi có rollback flag** trong config, không cần revert code khi gặp sự cố trên máy người dùng.
7. **Không thêm dependency mới** (không `pystray`, không `keyboard`, không `pywin32`): chỉ `ctypes` + stdlib.

### 4.2. Sơ đồ module đích

```
main.py
 ├─ single_instance.acquire_or_activate("CVM_colorBot")   (MỚI)
 │     ├─ CreateMutexW  → đã tồn tại? SetEvent(named) + exit 0
 │     └─ instance watcher thread (chỉ instance đầu)
 ├─ config.load_from_file()
 ├─ CaptureService / AimTracker
 └─ ViewerApp
      ├─ ui_mode = "simple" | "pro"        (config.ui_pro_mode)
      ├─ scheduler duy nhất _ui_tick (100 ms; 400 ms khi ẩn)
      ├─ _poll_launcher_queue (40 ms, chạy cả khi ẩn)
      │
      ├─ SIMPLE: src/ui_modes/simple_dashboard.py
      │     build_simple_dashboard(app, parent)
      │     refresh_simple_dashboard(app, changed=set())
      │     └─ KHÔNG sidebar, KHÔNG scrollable, KHÔNG canvas, KHÔNG tooltip
      │
      ├─ PRO: các builder hiện có trong ui.py (giữ nguyên)
      │     title bar + sidebar 5 pillar + content CTkScrollableFrame
      │
      └─ launcher layer
            ├─ src/utils/win32_window.py   (style, show/hide, minimize/restore, foreground)
            ├─ src/utils/global_hotkey.py  (message window + RegisterHotKey + tray + queue)
            └─ src/utils/single_instance.py(mutex + named event + watcher)
```

### 4.3. Mode state machine

```
                    ┌──────────────────────────────┐
                    │  BOOT                        │
                    │  đọc config.ui_pro_mode      │
                    └──────────┬───────────────────┘
                               │
              ┌────────────────┴─────────────────┐
              ▼                                  ▼
      ┌───────────────┐                  ┌───────────────┐
      │ SIMPLE        │  _enter_pro()    │ PRO           │
      │ 560×540       │ ───────────────► │ 980×660       │
      │ no sidebar    │ ◄─────────────── │ 5 pillar      │
      │ no scrollable │  _enter_simple() │ full tabs     │
      └───────┬───────┘                  └───────┬───────┘
              │                                  │
              └──────────┬───────────────────────┘
                         ▼
              ┌──────────────────────┐
              │ HIDDEN (withdrawn)   │  hotkey Insert / tray / single-instance
              │ scheduler 400 ms     │  ─────────────────────────────────────►
              │ launcher poll 40 ms  │  _show_window() → quay lại mode trước
              └──────────────────────┘
```

**Bất biến (invariants):**

| ID | Bất biến | Cách đảm bảo |
|---|---|---|
| I1 | Đúng một `_ui_tick` chain | `_scheduler_started` guard; không khởi động lại khi rebuild |
| I2 | Đúng một clipboard poll mỗi 1,2 s, chỉ Pro + tab Profiles + visible | bỏ self-reschedule; scheduler gọi one-shot |
| I3 | Đúng một hotkey poll 40 ms | tạo ở `__init__`, không tạo lại khi đổi mode |
| I4 | Đúng một `GlobalHotkey` + một tray icon | `LauncherService` khởi tạo một lần, `shutdown()` idempotent |
| I5 | `_collapsible_section_states` không bị xóa khi đổi mode | bỏ `clear()`; chỉ ghi khi người dùng bấm |
| I6 | Simple không có `sidebar`, `content_frame` là `CTkFrame` thường | builder riêng; test assert |
| I7 | Pro giữ đủ 5 nav + sub-nav + 4 card Combat + Calibration + Flick V2 | checklist §6.4 + test cũ |
| I8 | Không rò rỉ widget/timer sau 20 lần đổi mode | test `after info` + đếm widget |
| I9 | Ẩn/hiện không làm mất taskbar style | `_sync_window_style(force=True)` sau mỗi show |
| I10 | Đóng app dọn sạch hotkey/tray/thread | shutdown sequence §8.7 |

---

## 5. ĐẶC TẢ SIMPLE MODE

### 5.1. Hình học & ràng buộc cửa sổ

| Thuộc tính | Giá trị | Ghi chú |
|---|---|---|
| Geometry mặc định | **560×540** (`config.ui_simple_geometry`) | Người dùng có thể chỉnh trong config; clamp 480×420 … 720×700 |
| Resizable | `False, False` | Loại bỏ hoàn toàn reflow khi kéo chuột — nguồn giật lớn nhất |
| Min/max size | khóa bằng `minsize/maxsize` cùng giá trị | tránh CTk ghi đè |
| Vị trí | lưu `ui_simple_position`, clamp vào virtual screen | không mở ngoài màn hình |
| Maximize | **ẩn nút**; phím tắt maximize bị bỏ qua | Simple không có fullscreen |
| Title bar | cao 34 px, chỉ: logo text + `SIMPLE` pill + `⚙` + `─` + `✕` | không có telemetry pill ở đây (đưa vào card Engine) |
| Scrollable | **không** | toàn bộ nội dung fit trong 540 px |
| Sidebar | **không dựng** (không `pack_forget`, mà không tạo) | cắt ~25 widget + 1 scrollable |
| Tooltip | **tắt** trong Simple (tránh tạo `CTkToplevel` mỗi hover) | Pro giữ nguyên |
| Canvas/đồ thị | **không** | PID preview, HSV preview chỉ ở Pro |
| Debug log / Clipboard poll / Profile textbox | **không** | xem §5.6 |

### 5.2. Wireframe (560×540)

```
┌──────────────────────────────────────────────────────────────┐ 34
│ CVM colorBot v2.1.0   [SIMPLE]              ⚙   ─   ✕        │
├──────────────────────────────────────────────────────────────┤
│ ┌ ENGINE ──────────────────────────────────────────────────┐ │
│ │  [        ▶ START ENGINE        ]  (height 40)           │ │
│ │  ● 144 FPS    ● 8.4 ms    ● COM3    ● OFFLINE            │ │
│ │  Status: Offline                                         │ │
│ └──────────────────────────────────────────────────────────┘ │
│ ┌ MAIN AIM ────────────────┐ ┌ SEC AIM / FLICK ────────────┐ │
│ │ [x] Enable Aimbot        │ │ [x] Enable Sec / Flick      │ │
│ │ Mode   [ Normal      ▾ ] │ │ Mode   [ Flick        ▾ ]   │ │
│ │ Aim Key[ RMB         ]   │ │ Aim Key[ SMB4         ]     │ │
│ │ FOV    [====|=====] 100  │ │ FOV    [==|=======]  30     │ │
│ │ Speed  [===|======] 3.0  │ │ Gain   [====|=====] 1.00    │ │
│ │ Smooth [====|=====] 30   │ │ Smooth [==|=======]   4     │ │
│ └──────────────────────────┘ └─────────────────────────────┘ │
│ ┌ QUICK ───────────────────────────────────────────────────┐ │
│ │ Trigger [ ]    RCS [x]    Profile [ default ▾ ]  [LOAD]  │ │
│ └──────────────────────────────────────────────────────────┘ │
│  [ ⭐ Pro Mode ]                                  [ Hide (Ins) ]│
└──────────────────────────────────────────────────────────────┘
```

Chiều cao dự kiến: title 34 + Engine 96 + 2 card 210 + Quick 54 + footer 40 + padding 40 ≈ **474 < 540**. Có 66 px dư để chịu DPI 125 %.

### 5.3. Thành phần & ánh xạ điều khiển

| # | Khối | Widget | Config key | Callback | Ghi chú |
|---|---|---|---|---|---|
| 1 | Master | `CTkButton` `runtime_btn` (cao 40) | — | `_toggle_runtime` | Giữ đúng tên attribute để `_refresh_runtime_button()` dùng lại |
| 1b | Telemetry | 4 × `StatusPill`: `pill_fps`, **`pill_delay`** (nhãn "Ping"), `pill_hardware`, `pill_conn` | — | — | `pill_delay` giữ tên cũ để scheduler/test không vỡ; nghĩa "ping/độ trễ" |
| 1c | Status | `CTkLabel` `status_indicator` | — | — | `_set_status_indicator()` dùng lại |
| 2 | Main Aim | `CTkSwitch` + `var_enableaim` | `enableaim` | `_on_enableaim_changed` | |
| 2b | | `CTkOptionMenu` `mode_option` | `mode` | `_on_mode_selected` (đã sửa để không rebuild) | đăng ký `_option_widgets["mode"]` |
| 2c | | `CTkButton` `aim_key_bind_button` | `selected_mouse_button` | `_start_aim_key_capture(False)` | Đúng tên attribute để `_ads_binding_to_display` + `_apply_settings` cập nhật |
| 2d | | slider `fovsize` | `fovsize` | `_on_fovsize_changed` | range 1–1000 |
| 2e | | slider `normal_x_speed` | `normal_x_speed` | `_on_normal_x_speed_changed` | nhãn "Speed" |
| 2f | | slider `normalsmooth` | `normalsmooth` | `_on_config_normal_smooth_changed` | nhãn "Smooth" |
| 3 | Sec/Flick | `CTkSwitch` + `var_enableaim_sec` | `enableaim_sec` | `_on_enableaim_sec_changed` | |
| 3b | | `CTkOptionMenu` `mode_option_sec` | `mode_sec` | `_on_mode_sec_selected` (đã sửa) | |
| 3c | | `CTkButton` `aim_key_bind_button_sec` | `selected_mouse_button_sec` | `_start_aim_key_capture(True)` | |
| 3d | | slider `fovsize_sec` | `fovsize_sec` | `_on_fovsize_sec_changed` | |
| 3e | | slider `flick_gain_sec` | `flick_gain_sec` | `flick_handler_for("flick_gain_sec")` | nhãn "Gain"; chỉ hiển thị khi `mode_sec == Flick`, ngược lại đổi nhãn thành "Speed" gắn `normal_x_speed_sec`? **Quyết định:** luôn hiển thị Gain cho Flick, và thêm 1 slider `normal_x_speed_sec` ẩn/hiện bằng `pack_forget` (không destroy) — xem §5.4 |
| 3f | | slider `normalsmooth_sec` | `normalsmooth_sec` | `_on_config_normal_smooth_sec_changed` | |
| 4 | Quick | `CTkSwitch` `var_enabletb_quick` | `enabletb` | `_on_quick_trigger_changed` (**mới**) | `var_enabletb` cũ chỉ tồn tại trong code chết của `_show_tb_tab` → không dùng lại |
| 4b | | `CTkSwitch` `var_enablercs` | `enablercs` | `_on_enablercs_changed` | Giữ tên `var_enablercs` |
| 4c | | `CTkOptionMenu` `simple_profile_option` | — | `_on_simple_profile_selected` | |
| 4d | | `CTkButton` "LOAD" | — | `_load_selected_config` | refactor đọc widget active |
| 5 | Footer | `CTkButton` "⭐ Pro Mode" | — | `_enter_pro_mode` | |
| 5b | | `CTkButton` "Hide (Ins)" | — | `_hide_window` | hiển thị hotkey hiện tại |

> **Quyết định có chủ đích:** card Sec/Flick hiển thị **5 hàng cố định** (Enable, Mode, Key, FOV, Gain/Speed, Smooth). Hàng thứ 5 dùng **một trong hai slider** được build sẵn và `pack_forget`/`pack` theo mode — **không destroy**, để giữ chi phí chuyển mode ở mức ~0.

### 5.4. Chuyển đổi phụ thuộc mode trong Simple (không rebuild)

```python
def refresh_simple_dashboard(app, changed=None):
    changed = set(changed or ())
    # 1) nhãn/giá trị chỉ ghi khi đổi
    safe_text(app.simple_mode_value, AIM_MODE_VALUE_TO_DISPLAY[config.mode])
    # 2) hàng tuning của Sec: Flick -> Gain, còn lại -> Speed
    if "mode_sec" in changed or changed is None:
        if config.mode_sec == "Flick":
            app.simple_sec_gain_row.pack(fill="x", pady=2)
            app.simple_sec_speed_row.pack_forget()
        else:
            app.simple_sec_speed_row.pack(fill="x", pady=2)
            app.simple_sec_gain_row.pack_forget()
    # 3) badge cảnh báo nếu Main ở Flick nhưng đang chỉnh Speed
    ...
```

`_on_mode_selected()` / `_on_mode_sec_selected()` sửa thành:

```python
def _after_aim_mode_changed(self, is_sec):
    self._reset_aim_state_after_mode_change(is_sec=is_sec)
    if self._ui_mode == "simple":
        refresh_simple_dashboard(self, {"mode_sec" if is_sec else "mode"})
        return
    # Pro: giữ hành vi cũ (rebuild tab) nhưng hoãn bằng after_idle để không
    # destroy widget ngay trong callback của chính nó.
    self.after_idle(self._show_sec_aimbot_tab if is_sec else self._show_aimbot_tab)
```

**Pro vẫn rebuild như cũ** (đúng yêu cầu "giữ nguyên"), chỉ thêm `after_idle` để tránh destroy-widget-trong-callback (một nguồn crash/khựng nhỏ).

### 5.5. Ngân sách widget & chi phí

| Hạng mục | Pro (Combat) | Simple (mục tiêu) |
|---|---|---|
| Widget Tk ước tính | 700–1.200 | **≤ 150** |
| `CTkScrollableFrame` | 2 (content + sidebar) | **0** |
| `CTkSlider` | ~30 | **6** |
| `CTkOptionMenu` | ~10 | **3** |
| `CTkToplevel` (tooltip) | nhiều | **0** |
| Canvas vẽ đồ thị | 1 (PID) | **0** |
| Thời gian build | 50–150 ms | **≤ 60 ms** |
| Timer chain | 1 scheduler + N clipboard + PID | **1 scheduler + 1 hotkey poll** |

Đo bằng helper test (đệ quy `winfo_children()` đếm widget, `app.tk.call("after", "info")` đếm timer).

### 5.6. Scheduler profile cho Simple

| Nhánh | Pro | Simple | Ghi chú |
|---|---|---|---|
| `_ui_tick` nhịp | 100 ms | 150 ms | ít việc hơn |
| Nguồn NDI | 100 ms | **tắt** | chỉ Pro/Hardware |
| Debug log | 100 ms (gate tab) | **tắt** | |
| Telemetry (FPS/ping) | 250 ms | 500 ms | đủ mượt cho người xem |
| Flick readouts | 250 ms | **tắt** | Simple không có derived rows |
| Connection/hardware | 500 ms | 1.000 ms | |
| Clipboard | 1.200 ms, chỉ Pro+Profiles | **tắt** | |
| PID preview | theo canvas | **tắt** | |
| Khi ẩn | 400–500 ms | 400–500 ms | chỉ poll hotkey |
| Hotkey poll | 40 ms | 40 ms | luôn chạy |

`_ui_tick` đọc `self._ui_mode` và một dict cadence; **không** gọi hàm nếu mode không cần.

### 5.7. Những gì Simple **không** có (và vì sao)

- Sidebar & 5 pillar → không gian 560 px không đủ; người dùng muốn Pro thì bấm nút.
- `CTkScrollableFrame` → nguồn reflow O(widget); nội dung đã fit.
- Collapsible sections → mỗi section là thêm widget + state + bind; Simple chỉ có 4 card tĩnh.
- Tooltip → mỗi hover tạo `CTkToplevel` + Map event; bỏ để giảm jank.
- PID canvas, HSV preview, profile textbox, debug textbox, hardware detail → chỉ Pro.
- Nút maximize / fullscreen → Simple là cửa sổ tiện ích cố định.
- Sub-nav bar → không cần vì chỉ một màn hình.

---

## 6. ĐẶC TẢ PRO MODE (BẤT BIẾN)

### 6.1. Hình học

| Trạng thái | Giá trị |
|---|---|
| Mặc định | `980x660` (`config.ui_pro_geometry`) |
| Min size | `900x600` (đặt `minsize`) — hiện chưa đặt, gây reflow méo dưới 900 |
| Resizable | `True, True` |
| Maximize | giữ nguyên hành vi `_toggle_maximize` (full screen) **nhưng** lưu `ui_pro_geometry` trước khi maximize và khôi phục đúng khi bấm lần 2 |
| Fullscreen | giữ nguyên; khi chuyển sang Simple lúc đang maximize → tự restore hình học trước |
| Sidebar | 210 px, 5 pillar + alias cũ (giữ nguyên `nav_buttons`) |
| Content | `CTkScrollableFrame` (giữ nguyên) |

### 6.2. Thành phần phải còn nguyên (checklist)

| Nhóm | Phải còn |
|---|---|
| Title bar | `logo_lbl`, `version_lbl`, `pill_fps`, `pill_delay`, `pill_hardware`, `mode_toggle_btn`, `maximize_btn`, `minimize_btn`, close |
| Sidebar | `sidebar` (width ≥ 200), `runtime_btn` (height 38), `fps_label`, `decode_delay_label`, `total_delay_label`, `status_indicator`, `hardware_type_label`, `hardware_conn_label`, `hardware_details_toggle`, `hardware_details_label`, `active_profile_label`, `lang_btn`, `theme_btn`, `ui_style_btn`, `nav_buttons` (Combat/Vision/Hardware/Profiles/Telemetry + alias), `nav_indicators` |
| Combat | `card_targeting`, `card_windmouse`, `card_speeds`, `card_humanization`, `card_calibration`, sub-nav 4 mục, toàn bộ slider/option hiện có |
| Combat phụ | `_show_sec_aimbot_tab`, `_show_flick_v2_tab` (`card_flick_main/sec`, `flick_sliders_*`, `flick_readouts_*`, diagnostics), `_show_rcs_tab` |
| Vision | `card_color_preset`, `card_hsv_tuning`, `card_contour_filters`, HSV preview button |
| Hardware | `card_mouse_api`, `card_capture_service`, `mouse_hardware_frame`, `keyboard_hardware_frame`, `capture_settings_frame`, toàn bộ backend UI |
| Profiles | `card_profile_manager`, `config_option`, `config_log`, SAVE/LOAD/DEL/NEW/EXPORT/IMPORT, clipboard auto-import |
| Telemetry | `card_mouse_monitor`, `card_system_logs`, `debug_log_textbox`, `debug_button_widgets` |
| Hành vi | theme cycle, language switch, `_toggle_maximize`, collapsible, tooltip, PID preview, binding capture, profile load/save |

### 6.3. Thay đổi **tối thiểu** được phép trong Pro

Chỉ những thay đổi không quan sát được bằng mắt/hành vi:

1. `_show_*_tab()` gọi `_ensure_pro_mode()` nếu đang Simple (để API cũ vẫn hoạt động).
2. Callback đổi mode/ADS dùng `after_idle` thay vì rebuild ngay trong event handler.
3. `_apply_runtime_settings_lock`, `_update_*` dùng helper "chỉ ghi khi đổi" — cùng kết quả hiển thị.
4. `_on_window_map` thêm guard `event.widget is not self` — không đổi giao diện.
5. `_on_minimize` chuyển sang `ShowWindow(SW_MINIMIZE)` — cùng kết quả (thu nhỏ), nhưng không phá taskbar.
6. `_ensure_taskbar_icon` không còn `withdraw/deiconify` — bỏ nháy.
7. Bỏ self-reschedule clipboard — không đổi tính năng, chỉ bỏ nhân bản.
8. `_toggle_pro_mode` **không** xóa `_collapsible_section_states`.

### 6.4. Cách chứng minh "Pro không đổi"

- Chạy toàn bộ test hiện có (194+ case) — phải xanh.
- Test mới `test_pro_mode_contract.py`: assert đủ attribute trong bảng §6.2; assert `nav_buttons` có đủ 5 + alias; assert `sidebar.cget("width") >= 200`; assert `runtime_btn.cget("height") == 38`; assert `mode_toggle_btn` text; assert geometry 980×660.
- Ảnh chụp trước/sau (nếu có thể) cho 5 tab; Reviewer đối chiếu thủ công.
- So sánh `config.to_dict()` trước/sau khi chỉ chuyển mode: **không** key nào ngoài `ui_pro_mode`, `ui_simple_geometry`, `ui_pro_geometry`, `ui_simple_position` thay đổi.

---

## 7. CHUYỂN MODE — THIẾT KẾ CHI TIẾT

### 7.1. API

```python
# src/ui.py (ViewerApp)
def _enter_simple_mode(self, *, rebuild: bool = True, persist: bool = True) -> None
def _enter_pro_mode(self, *, rebuild: bool = True, persist: bool = True) -> None
def _apply_ui_mode(self, mode: str, *, rebuild: bool = True, persist: bool = True) -> None
def _ensure_pro_mode(self) -> None          # dùng bởi _show_*_tab()
def _teardown_layout(self) -> None          # destroy + reset registry + cancel job
def _schedule_config_save(self, delay_ms: int = 600) -> None
```

### 7.2. Trình tự `_apply_ui_mode`

```
1. if mode == self._ui_mode and not force: return
2. self._ui_rebuilding = True
3. Lưu hình học mode đang rời:
     nếu đang Pro: config.ui_pro_geometry = self.geometry() (nếu không maximized)
     nếu đang Simple: config.ui_simple_position = "+x+y"
4. Hủy công việc gắn widget:
     _cancel_binding_capture()
     cancel _pid_preview_job (nếu có)
     self._ignore_settings_events = True
5. _teardown_layout():
     destroy title_bar, sidebar (nếu có), content_frame
     self._slider_widgets = {}; _checkbox_vars = {}; _option_widgets = {}
     self._range_slider_widgets = {}; _advanced_rows = []
     _pid_preview_* = None; debug_log_textbox = None; config_option = None
     self._collapsible_section_states giữ nguyên (KHÔNG clear)
6. self._ui_mode = mode; config.ui_pro_mode = (mode == "pro")
7. Dựng layout:
     Simple: _build_simple_layout()   → title bar rút gọn + simple_dashboard
     Pro:    _build_layout()          → title bar đầy đủ + sidebar + content
8. Áp hình học:
     Simple: resizable(False, False); geometry(ui_simple_geometry); minsize=maxsize=...
     Pro:    resizable(True, True);  geometry(ui_pro_geometry hoặc 980x660)
9. self.update_idletasks()
10. self._sync_window_style(force=True)
11. self._ui_rebuilding = False
12. if persist: self._schedule_config_save()
13. if mode == "pro": khôi phục tab đang xem (nếu còn hợp lệ) hoặc Combat
    if mode == "simple": refresh_simple_dashboard(self)
14. self._reset_ticks(); self._ui_tick_once_soon()
```

### 7.3. Quy tắc chống giật khi chuyển mode

- **Không** gọi `config.save_to_file()` đồng bộ trong callback; dùng `after(600, ...)` debounce (đĩa I/O trên UI thread gây khựng trên máy HDD).
- **Không** rebuild hai lần (nếu đang ở Pro và bấm Pro → return ngay).
- **Không** destroy widget bên trong event handler của chính widget đó; dùng `after_idle`.
- **Không** build Simple bằng cách `pack_forget` sidebar: phải **destroy** để cắt chi phí layout.
- **Không** giữ tham chiếu widget đã destroy trong `_slider_widgets`… (dọn registry).
- **Không** reset `_runtime_active`, `_runtime_busy`, `capture`, `tracker`, `mouse_input_monitor` — chuyển mode là thay "da", không thay "nội tạng".
- Nếu đang chạy engine: giữ nguyên; Simple hiển thị đúng trạng thái qua `_refresh_runtime_button()`.

### 7.4. Lưu / khôi phục

| Key | Kiểu | Mặc định | Ghi chú |
|---|---|---|---|
| `ui_pro_mode` | bool | `False` (Simple lần đầu) | đã có; giữ |
| `ui_simple_geometry` | str | `"560x540"` | validate regex `^\d{3,4}x\d{3,4}$`, clamp |
| `ui_simple_position` | str | `""` | `"+x+y"`; clamp vào virtual screen |
| `ui_pro_geometry` | str | `"980x660"` | lưu khi rời Pro |
| `ui_start_hidden` | bool | `False` | nếu True, khởi động = ẩn + hotkey |
| `ui_toggle_hotkey` | str | `"Insert"` | parse qua `to_vk_code`; `""` = tắt |
| `ui_tray_enabled` | bool | `True` (Windows) | tray icon native |
| `ui_minimize_to_tray` | bool | `False` | nếu True, `─` = hide + tray thay vì taskbar minimize |
| `ui_config_schema` (dùng `config_schema`) | int | **4** | migration |

---

## 8. LAUNCHER / WINDOW LIFECYCLE

### 8.1. Module `src/utils/win32_window.py` (MỚI)

Trách nhiệm duy nhất: thao tác HWND. Không import Tk, không import `src.ui`.

```python
from __future__ import annotations
import ctypes, os, sys
from ctypes import wintypes

IS_WINDOWS = os.name == "nt"

GWL_EXSTYLE      = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW  = 0x00040000
SW_HIDE          = 0
SW_SHOW          = 5
SW_MINIMIZE      = 6
SW_RESTORE       = 9
SWP_NOSIZE       = 0x0001
SWP_NOMOVE       = 0x0002
SWP_NOZORDER     = 0x0004
SWP_NOACTIVATE   = 0x0010
SWP_FRAMECHANGED = 0x0020
HWND_TOP         = 0
HWND_TOPMOST     = -1
HWND_NOTOPMOST   = -2


def root_hwnd(tk_widget) -> int:
    """HWND thật của toplevel (GetAncestor GA_ROOT)."""


def get_exstyle(hwnd: int) -> int: ...
def set_exstyle(hwnd: int, exstyle: int) -> None: ...
def apply_appwindow(hwnd: int) -> int:
    """Bỏ TOOLWINDOW, bật APPWINDOW; trả về exstyle mới."""


def refresh_frame(hwnd: int) -> None:
    """SetWindowPos(... SWP_FRAMECHANGED) — KHÔNG withdraw/deiconify."""


def minimize(hwnd: int) -> bool: ...      # ShowWindow(SW_MINIMIZE)
def restore(hwnd: int) -> bool: ...       # ShowWindow(SW_RESTORE)
def show(hwnd: int) -> bool: ...          # ShowWindow(SW_SHOW)
def hide(hwnd: int) -> bool: ...          # ShowWindow(SW_HIDE)


def bring_to_front(hwnd: int, topmost_ms: int = 350) -> None:
    """SetForegroundWindow + tạm TOPMOST rồi trả về NOTOPMOST."""
```

**Quy tắc 64-bit:** dùng `GetWindowLongPtrW`/`SetWindowLongPtrW` nếu có, fallback `GetWindowLongW`/`SetWindowLongW`; khai báo `argtypes/restype` đầy đủ (`wintypes.HWND`, `wintypes.LONG`, `wintypes.LPARAM`). Không dùng `ctypes.windll` trực tiếp trong `ui.py`.

### 8.2. Taskbar integration (thay `_ensure_taskbar_icon`)

```python
def _sync_window_style(self, force: bool = False) -> None:
    if os.name != "nt":
        return
    if self._ui_rebuilding and not force:
        return
    try:
        hwnd = win32_window.root_hwnd(self)
        exstyle = win32_window.apply_appwindow(hwnd)
        signature = (hwnd, exstyle)
        if not force and signature == getattr(self, "_window_style_sig", None):
            return
        win32_window.refresh_frame(hwnd)
        self._window_style_sig = signature
        self._taskbar_style_applied = True
    except Exception as exc:
        log_print(f"[UI] window style sync failed: {exc}")
```

**Khác biệt cốt lõi so với hiện tại:**
- Không `withdraw()` / `deiconify()` / `alpha=0` → không nháy, không mất focus, không sinh Map.
- Không đặt `_taskbar_style_applied=True` vĩnh viễn: signature cho phép re-apply khi HWND/style đổi.
- Gọi lại sau **mỗi** show/restore/minimize-fallback.

### 8.3. `_on_window_map` / `_on_minimize` / `_restore_window`

```python
def _on_window_map(self, event=None):
    # 1) Bỏ qua Map của widget con — đây là bug P0 hiện tại
    if event is not None and getattr(event, "widget", None) is not self:
        return
    if getattr(self, "_ui_rebuilding", False):
        return
    try:
        state = self.state()
    except Exception:
        return
    if state != "normal":
        return
    self._sync_window_style()
    if getattr(self, "_minimized", False):
        self._minimized = False
        self.after(0, self._restore_window)


def _on_minimize(self):
    """Thu nhỏ thật qua Win32 — KHÔNG đụng overrideredirect."""
    if os.name == "nt":
        try:
            hwnd = win32_window.root_hwnd(self)
            if win32_window.minimize(hwnd):
                self._minimized = True
                self.after(300, self._verify_minimized)
                return
        except Exception as exc:
            log_print(f"[UI] Win32 minimize failed: {exc}")
    # Fallback đa nền tảng / khi Win32 lỗi
    self.iconify()
    self._minimized = True


def _verify_minimized(self):
    """Nếu ShowWindow không ăn, dùng withdraw + tray/hotkey làm lối thoát."""
    if not getattr(self, "_minimized", False):
        return
    try:
        if self.state() == "iconic":
            return
    except Exception:
        pass
    # Không còn taskbar button? Ít nhất vẫn còn hotkey/tray
    self._set_status_indicator("Status: Minimized (Insert to show)", COLOR_TEXT_DIM)


def _restore_window(self):
    if getattr(self, "_closing", False):
        return
    try:
        self.deiconify()
    except Exception:
        pass
    if os.name == "nt":
        try:
            hwnd = win32_window.root_hwnd(self)
            win32_window.show(hwnd)
            win32_window.restore(hwnd)
        except Exception:
            pass
    if not self._is_maximized:
        self.overrideredirect(True)
    self._minimized = False
    self._ui_hidden = False
    self.update_idletasks()
    self._sync_window_style(force=True)
    self.lift()
    self.focus_force()
    win32_window.bring_to_front(win32_window.root_hwnd(self)) if os.name == "nt" else None
    self._refresh_after_show()
```

> **Vì sao không tắt `overrideredirect` khi minimize?** Vì nó là nguyên nhân L1/L2. `ShowWindow(SW_MINIMIZE)` giữ nguyên style, giữ taskbar button, và Windows tự restore khi người dùng click icon. Nếu máy nào đó không hỗ trợ (hiếm), fallback `iconify()` vẫn còn hotkey/tray.

### 8.4. Ẩn / hiện (hide/show)

```python
def _hide_window(self):
    if self._ui_hidden or self._closing:
        return
    self._ui_hidden = True
    self._save_mode_geometry()
    self.withdraw()                      # bỏ khỏi taskbar + Alt-Tab
    self._set_status_after_show()        # không cần; chỉ log
    log_print("[UI] Hidden — press Insert or use tray to show")


def _show_window(self):
    if self._closing:
        return
    self._restore_window()
    self._poll_launcher_queue_now()      # xử lý yêu cầu đang chờ
```

- **Không** destroy widget khi ẩn → hiện lại tức thì.
- Scheduler tự động giảm nhịp khi `withdraw` (đã có `_ui_visible()`), nhưng **hotkey poll vẫn chạy 40 ms**.
- Khi ẩn, **không** có taskbar button; tray icon + hotkey là hai lối quay lại (đúng yêu cầu "launcher dễ chọn").

### 8.5. Global hotkey (`src/utils/global_hotkey.py` — MỚI)

**Thiết kế:** một daemon thread sở hữu một **hidden message window** (WNDCLASSW riêng), đăng ký `RegisterHotKey(hwnd, id, MOD_NOREPEAT, vk)` và (tuỳ chọn) tray icon `Shell_NotifyIconW`. Mọi hành động đẩy vào `queue.Queue`; Tk poll 40 ms.

```python
WM_HOTKEY   = 0x0312
WM_APP      = 0x8000
WM_TRAY     = WM_APP + 1
WM_COMMAND  = 0x0111
MOD_NOREPEAT = 0x4000
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4

class LauncherService:
    """Hotkey + tray + queue. Không bao giờ gọi Tk API từ thread này."""

    def __init__(self, vk: int, on_action: Callable[[str], None] | None = None,
                 tray: bool = True, app_name: str = "CVM colorBot"): ...

    def start(self) -> bool: ...
    def stop(self) -> None: ...          # idempotent, join(timeout=1.0)
    def update_hotkey(self, vk: int) -> bool: ...
    def set_tray_tooltip(self, text: str) -> None: ...
    def set_tray_menu_state(self, hidden: bool, mode: str) -> None: ...
```

**Hành vi:**

| Tình huống | Kết quả |
|---|---|
| `RegisterHotKey` thành công | thread chờ `GetMessageW`; `WM_HOTKEY` → queue `"toggle_ui"` |
| `RegisterHotKey` thất bại (phím bị game chiếm) | log WARN; bật **fallback polling** `GetAsyncKeyState(vk)` mỗi 50 ms trong cùng thread, edge-detect; queue `"toggle_ui"` |
| Tray click trái | queue `"toggle_ui"` |
| Tray menu | `Show/Hide`, `Simple Mode`, `Pro Mode`, `Exit` |
| `Exit` | queue `"exit"` → Tk `after(0, _on_close)` (an toàn vì chạy trên Tk thread) |
| `stop()` | `UnregisterHotKey`, `Shell_NotifyIcon(NIM_DELETE)`, `PostMessageW(hwnd, WM_CLOSE)`, join 1 s |

**Tk-side:**

```python
def _start_launcher(self):
    self._launcher_queue = queue.Queue()
    self._launcher = LauncherService(
        vk=parse_hotkey_vk(config.ui_toggle_hotkey),
        tray=bool(config.ui_tray_enabled),
        on_action=self._launcher_queue.put,
    )
    if not self._launcher.start():
        log_print("[UI] Launcher service failed to start; hotkey disabled")
    self._hotkey_poll_job = self.after(40, self._poll_launcher_queue)


def _poll_launcher_queue(self):
    try:
        while True:
            action = self._launcher_queue.get_nowait()
            if action == "toggle_ui":
                self._toggle_ui_visibility()
            elif action == "show":
                self._show_window()
            elif action == "mode:simple":
                self._enter_simple_mode()
            elif action == "mode:pro":
                self._enter_pro_mode()
            elif action == "exit":
                self._on_close()
                return
    except queue.Empty:
        pass
    finally:
        if not getattr(self, "_closing", False):
            self._hotkey_poll_job = self.after(40, self._poll_launcher_queue)


def _toggle_ui_visibility(self):
    if getattr(self, "_closing", False):
        return
    now = time.monotonic()
    if now - getattr(self, "_last_toggle_time", 0.0) < 0.25:
        return                            # chống double-trigger / auto-repeat
    self._last_toggle_time = now
    if self._ui_hidden or self._minimized or self.state() in ("iconic", "withdrawn"):
        self._show_window()
    else:
        self._hide_window()
```

**Vì sao dùng Windows message loop thay vì `GetAsyncKeyState` trong `_ui_tick`?**
- `RegisterHotKey` hoạt động **kể cả khi game fullscreen** (trừ khi game dùng raw input/exclusive và chặn hotkey — khi đó fallback polling).
- Không phụ thuộc backend chuột (`is_key_pressed` yêu cầu `state.is_connected`, xem `mouse/__init__.py:933`).
- Không gọi Tk từ thread phụ.

**Parse hotkey:**

```python
def parse_hotkey_vk(value: str) -> int:
    raw = str(value or "").strip()
    if not raw:
        return 0
    try:
        vk = to_vk_code(raw)
    except Exception:
        vk = None
    if isinstance(vk, int) and 0 < vk < 0x100:
        return vk
    return 0x2D   # Insert
```

### 8.6. Single instance (`src/utils/single_instance.py` — MỚI)

```python
MUTEX_NAME = "Local\\CVM_colorBot_single_instance"
EVENT_NAME = "Local\\CVM_colorBot_show"

def acquire() -> tuple[bool, int | None]:
    """Trả (is_first, handle). is_first=False nghĩa là đã có instance."""

def signal_existing() -> bool:
    """SetEvent(EVENT_NAME) — gọi từ instance thứ hai."""

class InstanceWatcher(threading.Thread):
    """Instance đầu chờ event; khi được signal → queue 'show' cho Tk."""
```

`main.py`:

```python
is_first, handle = single_instance.acquire()
if not is_first:
    single_instance.signal_existing()
    print("[Main] Another instance is running; requested show.")
    raise SystemExit(0)
...
app = ViewerApp(...)
app.attach_instance_watcher(single_instance.InstanceWatcher(...))
app.mainloop()
```

`run.bat`: truyền `--show` và giữ `%*`:

```bat
"venv\Scripts\python.exe" main.py --show %*
```

**Kết quả:** double-click `run.bat` khi app đang ẩn → instance cũ hiện lên; không tạo instance thứ hai; không tranh chấp capture/mouse/hotkey.

### 8.7. Shutdown sequence (chống treo tiến trình)

`_on_close()` sửa thành:

```python
def _on_close(self):
    if getattr(self, "_closing", False):
        return
    self._closing = True
    try:
        self._cancel_binding_capture()
    except Exception:
        pass
    try:
        if getattr(self, "_hotkey_poll_job", None):
            self.after_cancel(self._hotkey_poll_job)
    except Exception:
        pass
    try:
        if getattr(self, "_ui_tick_job", None):
            self.after_cancel(self._ui_tick_job)
    except Exception:
        pass
    try:
        if getattr(self, "_launcher", None):
            self._launcher.stop()
    except Exception as exc:
        log_print(f"[UI] launcher stop error: {exc}")
    try:
        config.save_to_file()
    except Exception as exc:
        log_print(f"[UI] save error: {exc}")
    try:
        self.tracker.stop()
    except Exception:
        pass
    try:
        self.capture.cleanup()
    except Exception:
        pass
    try:
        self.destroy()
    except Exception:
        pass
    try:
        cv2.destroyAllWindows()
    except Exception:
        pass
    single_instance.release()   # ReleaseMutex/CloseHandle (nếu có)
```

### 8.8. Hành vi trong game fullscreen — giới hạn cần nói thật

| Chế độ game | Hotkey | Cửa sổ hiện lên |
|---|---|---|
| Windowed | Có | Có, `bring_to_front` + tạm topmost |
| Borderless fullscreen | Có | Có (topmost) |
| Exclusive fullscreen | Thường có (RegisterHotKey), fallback polling nếu bị chặn | **Không đảm bảo** vẽ đè; Windows có thể minimize game. Kế hoạch ghi rõ trong tooltip/README: dùng borderless |
| Game chặn hotkey (anti-cheat/raw input) | Fallback `GetAsyncKeyState` 50 ms | Như trên |

Không hứa "overlay trên exclusive fullscreen" — đó là giới hạn của Windows, không phải bug của tool.

---

## 9. CONFIG SCHEMA 4

### 9.1. Key mới/đổi

| Key | Kiểu | Mặc định | Validate / clamp | Ghi chú |
|---|---|---|---|---|
| `config_schema` | int | **4** | `max(1, int)` | bump từ 3 |
| `ui_pro_mode` | bool | **False** | bool | giữ; lần đầu = Simple |
| `ui_toggle_hotkey` | str | `"Insert"` | parse VK; invalid → `"Insert"` + WARN | `""` = tắt hotkey |
| `ui_simple_geometry` | str | `"560x540"` | regex; clamp 480×420…720×700 | |
| `ui_pro_geometry` | str | `"980x660"` | regex; clamp ≥ 900×600 | |
| `ui_simple_position` | str | `""` | `+x+y`; clamp vào virtual screen | |
| `ui_start_hidden` | bool | `False` | bool | |
| `ui_tray_enabled` | bool | `True` | bool | Windows only |
| `ui_minimize_to_tray` | bool | `False` | bool | `─` → hide thay vì taskbar |
| `ui_compact_layout` | bool | `True` | bool | **rollback flag**: False = Simple cũ (chỉ collapse section) |

### 9.2. Migration schema 3 → 4

1. Nếu `ui_toggle_hotkey` thiếu → `"Insert"`.
2. Nếu `ui_simple_geometry` thiếu → `"560x540"`; `ui_pro_geometry` thiếu → `"980x660"`.
3. Nếu `ui_pro_mode` thiếu → **giữ nguyên hành vi cũ**: `True` cho config đã tồn tại (người dùng đang dùng Pro), `False` cho fresh install. Cách phân biệt: `data` là dict không rỗng → `True`; fresh `Config()` → `False`.
4. `ui_compact_layout` thiếu → `True`.
5. `ui_tray_enabled` thiếu → `True` trên Windows, `False` nơi khác.
6. `config_schema = 4`.
7. Log migration một lần: `[Config] schema 3 -> 4: ui_toggle_hotkey=Insert, ...`.

### 9.3. `to_dict()` / `from_dict()`

- Thêm 8 key trên vào `to_dict()` cạnh `ui_pro_mode` (`config.py:914`).
- Trong `from_dict()`, thêm block validate ngay sau `self.ui_pro_mode = bool(...)` (`config.py:1373`):

```python
self.ui_pro_mode = bool(getattr(self, "ui_pro_mode", False))
self.ui_toggle_hotkey = _normalize_hotkey(getattr(self, "ui_toggle_hotkey", "Insert"))
self.ui_simple_geometry = _normalize_geometry(
    getattr(self, "ui_simple_geometry", "560x540"), 480, 420, 720, 700, "560x540")
self.ui_pro_geometry = _normalize_geometry(
    getattr(self, "ui_pro_geometry", "980x660"), 900, 600, 5120, 2880, "980x660")
self.ui_simple_position = _normalize_position(getattr(self, "ui_simple_position", ""))
self.ui_start_hidden = bool(getattr(self, "ui_start_hidden", False))
self.ui_tray_enabled = bool(getattr(self, "ui_tray_enabled", os.name == "nt"))
self.ui_minimize_to_tray = bool(getattr(self, "ui_minimize_to_tray", False))
self.ui_compact_layout = bool(getattr(self, "ui_compact_layout", True))
```

- Helper thuần (đặt trong `config.py`, không import Tk):

```python
_GEOMETRY_RE = re.compile(r"^\s*(\d{3,4})\s*x\s*(\d{3,4})\s*$")

def _normalize_geometry(raw, min_w, min_h, max_w, max_h, default):
    match = _GEOMETRY_RE.match(str(raw or ""))
    if not match:
        return default
    w = max(min_w, min(max_w, int(match.group(1))))
    h = max(min_h, min(max_h, int(match.group(2))))
    return f"{w}x{h}"
```

### 9.4. Không đổi

- Toàn bộ key aim/Flick/calibration/hardware/capture hiện có.
- `config_schema` chỉ dùng để migrate; không được dùng thay version app.
- `config.json` hiện tại (`ui_pro_mode: true`) sau migrate vẫn Pro → **không làm người dùng bất ngờ**.

---

## 10. DANH SÁCH FILE CẦN TẠO / SỬA

### 10.1. Tạo mới

| File | Nội dung | Ưu tiên |
|---|---|---|
| `src/ui_modes/__init__.py` | export `build_simple_dashboard`, `refresh_simple_dashboard` | P0 |
| `src/ui_modes/simple_dashboard.py` | Builder + refresh cho Simple (4 card, ≤150 widget, không scrollable/sidebar/canvas) | P0 |
| `src/utils/win32_window.py` | HWND helpers: style, show/hide/minimize/restore, foreground, 64-bit-safe | P0 |
| `src/utils/global_hotkey.py` | `LauncherService`: message window, `RegisterHotKey`, fallback polling, tray, queue | P0 (tray P1) |
| `src/utils/single_instance.py` | Mutex + named event + watcher | P0 |
| `tests/test_simple_mode.py` | Layout, widget budget, không sidebar/scrollable, callback, profile, trigger | P0 |
| `tests/test_window_lifecycle.py` | Map guard, minimize/restore, style re-apply, hide/show, shutdown | P0 |
| `tests/test_global_hotkey.py` | VK parse, register success/fail, fallback, debounce, stop | P0 |
| `tests/test_ui_mode_config.py` | Schema 4, migration, roundtrip, invalid geometry/hotkey | P0 |
| `tests/test_pro_mode_contract.py` | Checklist §6.2, geometry, nav, sidebar | P0 |
| `tests/test_launcher_single_instance.py` | Mutex/event (mock kernel32) | P1 |

### 10.2. Sửa

| File | Hành động | Ưu tiên |
|---|---|---|
| `src/ui.py` | Mode state machine; `_build_simple_layout`; sửa `_on_window_map`/`_on_minimize`/`_ensure_taskbar_icon`; scheduler de-dup; safe update helpers; profile widget abstraction; trigger callback; `_on_close` shutdown; bỏ clear collapsible; `_show_*` ensure Pro | P0 |
| `src/utils/config.py` | Schema 4 + 8 key + migration + validate + `to_dict` | P0 |
| `main.py` | Single-instance acquire/signal; `--show`; attach watcher; khởi động theo `ui_start_hidden` | P0 |
| `run.bat` | Truyền `--show %*` | P1 |
| `src/ui_tabs/calibration_tab.py` | Không đổi logic; chỉ đảm bảo `_show_flick_v2_tab` gọi `_ensure_pro_mode` (nếu cần) | P2 |
| `locales/vi.json`, `en.json`, `zh-CN.json` | Key mới: `Simple Mode`, `Pro Mode`, `Hide (Ins)`, `Ping`, `Profile`, `Quick`, `Main Aim`, `Sec Aim / Flick`, `Press Insert to show`, `Minimized` | P1 |
| `tests/test_sidebar.py` | Pin `ui_pro_mode=True` trước khi tạo app (tránh phụ thuộc `config.json`) | P0 |
| `tests/test_e2e_ui.py` | Tách assert geometry Pro/Simple; không assert 960 khi đang Simple | P0 |
| `tests/test_title_bar.py` | Pin Pro; thêm case Simple có pills | P1 |
| `tests/test_combat_tab.py`, `test_remaining_tabs.py`, `test_flick_ui.py` | Pin Pro trong setUp (hoặc dùng `ViewerApp(..., ui_mode="pro")`) | P0 |
| `CHANGELOG.md` | Mục `Unreleased`/`v2.2.0` mô tả Simple/Pro + launcher | P2 |
| `README.md` | Hướng dẫn Insert/tray/single-instance; giới hạn exclusive fullscreen | P2 |

### 10.3. Không sửa (ranh giới cứng)

- `src/aim_system/**` (aim math, flick controller, mode dispatcher, normal, RCS…).
- `src/capture/**`, `src/utils/mouse/**`, `src/utils/detection.py`.
- `version.json` / `src/version.py` (trừ khi PO yêu cầu bump).
- Lịch sử `CHANGELOG.md`.
- `docs/superpowers/**`.
- Không mass-reencode các chuỗi mojibake hiện có; chỉ sửa block được chạm.

---

## 11. HIỆU NĂNG — MỤC TIÊU & CÁCH ĐO

| Chỉ số | Hiện tại (ước tính tĩnh) | Mục tiêu | Cách đo |
|---|---|---|---|
| Callback timer / giây sau 10 phút | ~400 (do RC-1) | **≤ 12** | `len(app.tk.call("after","info"))` ổn định; đếm `_ui_tick` |
| Widget Tk Simple | ~700–1.200 (dùng Pro) | **≤ 150** | đệ quy `winfo_children()` |
| Widget Tk Pro Combat | 700–1.200 | **không tăng > 5 %** | so trước/sau |
| Thời gian build Simple | — | **≤ 60 ms** | `perf_counter` quanh builder |
| Thời gian chuyển mode | 50–150 ms + nháy | **≤ 120 ms**, không nháy | đo 10 lần, p95 |
| CPU idle Simple | 3–8 % | **< 1.5 %** | Task Manager/Perfmon 60 s |
| CPU idle Pro | 3–8 % | **< 3 %** | |
| Rò rỉ timer sau 20 lần đổi mode | không đo | **0** | so `after info` trước/sau |
| Rò rỉ widget sau 20 lần đổi mode | không đo | **0** | so số widget |
| Hotkey → phản hồi | — | **≤ 80 ms** | đo bằng log timestamp |
| Ẩn → hiện | — | **≤ 150 ms** | đo bằng log timestamp |
| Single-instance | mở instance 2 | **instance 1 hiện lên, instance 2 exit 0** | chạy 2 lần |

**Test chống hồi quy RC-1:**

```python
def test_clipboard_poll_does_not_reschedule_itself(app):
    before = set(app.tk.call("after", "info"))
    app._poll_clipboard_config_import()
    after = set(app.tk.call("after", "info"))
    new = after - before
    # Không được có timer mới trỏ tới chính nó
    assert len(new) <= 1   # chỉ timer của scheduler nếu có
```

**Test chống hồi quy RC-2:**

```python
def test_child_map_does_not_touch_window_style(app):
    calls = []
    app._sync_window_style = lambda *a, **k: calls.append(1)
    child = app.content_frame.winfo_children()[0]
    app._on_window_map(SimpleNamespace(widget=child))
    assert calls == []
    app._on_window_map(SimpleNamespace(widget=app))
    assert calls == [1]
```

---

## 12. PHÂN RÃ CÔNG VIỆC

### 12.1. Coder (8 task, thứ tự bắt buộc)

| ID | Task | File | Nội dung | DoD |
|---|---|---|---|---|
| C1 | Config schema 4 | `src/utils/config.py` | 8 key, validate, migration, `to_dict/from_dict`, helpers thuần | `test_ui_mode_config.py` xanh; config cũ load không mất key |
| C2 | Win32 window layer | `src/utils/win32_window.py` | HWND, style, show/hide/minimize/restore/foreground, 64-bit | Unit test mock user32; không import Tk |
| C3 | Launcher service | `src/utils/global_hotkey.py` | Message window + hotkey + fallback + tray + queue; stop idempotent | `test_global_hotkey.py` xanh; không gọi Tk từ thread |
| C4 | Single instance | `src/utils/single_instance.py`, `main.py`, `run.bat` | Mutex + event + watcher; `--show` | Chạy 2 lần: lần 2 exit 0, lần 1 hiện |
| C5 | Scheduler & update an toàn | `src/ui.py` | Bỏ self-reschedule; cadence theo mode; `_safe_text/_safe_configure`; cache text; gộp telemetry | `after info` ổn định; không log error khi Simple |
| C6 | Mode state machine | `src/ui.py` | `_apply_ui_mode`, `_teardown_layout`, `_enter_simple/pro`, `_ensure_pro_mode`, geometry, persist debounce | Đổi mode 20 lần không rò rỉ; Pro contract test xanh |
| C7 | Simple dashboard | `src/ui_modes/simple_dashboard.py` | 4 card, ≤150 widget, không scrollable/sidebar/canvas; đăng ký registry; profile/trigger | `test_simple_mode.py` xanh; ảnh chụp 560×540 |
| C8 | Window lifecycle + hotkey wiring | `src/ui.py` | `_on_window_map` guard, `_on_minimize`, `_restore_window`, `_hide/_show`, `_toggle_ui_visibility`, `_poll_launcher_queue`, `_on_close` | `test_window_lifecycle.py` xanh; manual taskbar OK |
| C9 | i18n + tài liệu | `locales/*.json`, `README.md`, `CHANGELOG.md` | Key mới; hướng dẫn Ins/tray; giới hạn fullscreen | Không key thô trong UI |
| C10 | Dọn dẹp | `src/ui.py` | Bỏ `_ensure_taskbar_icon` cũ, code chết liên quan, import thừa; giữ shim public | `compileall` sạch; `ui.py` không tăng dòng |

**Quy tắc thi công:**
- Không commit C6+C7 chung với C5 (dễ khoanh vùng lỗi).
- Không sửa `src/aim_system/**`.
- Mỗi task phải chạy `python -m compileall -q src main.py` trước khi báo xong.
- Nếu `RegisterHotKey`/tray không hoạt động trên máy test: giữ code sau flag `ui_tray_enabled=False`, hotkey vẫn phải chạy qua fallback.

### 12.2. Tester

| ID | Task | File | Nội dung | DoD |
|---|---|---|---|---|
| T1 | Config tests | `tests/test_ui_mode_config.py` | default/migrate/roundtrip/invalid hotkey/geometry/clamp/`ui_pro_mode` | ≥ 20 case |
| T2 | Simple layout tests | `tests/test_simple_mode.py` | sidebar vắng, scrollable vắng, geometry, widget budget, pills, trigger/profile, callback không rebuild | ≥ 18 case |
| T3 | Lifecycle tests | `tests/test_window_lifecycle.py` | Map guard, minimize không đổi overrideredirect, restore re-apply style, hide/show, close dọn hotkey | ≥ 15 case |
| T4 | Hotkey tests | `tests/test_global_hotkey.py` | VK parse, success/fail/fallback, debounce 250 ms, stop không treo, queue không gọi Tk | ≥ 15 case |
| T5 | Mode switch/leak | `tests/test_ui_mode_switch.py` | 20 vòng, đếm `after`, đếm widget, state section giữ nguyên, runtime không reset | ≥ 10 case |
| T6 | Pro contract | `tests/test_pro_mode_contract.py` | checklist §6.2, 5 nav, 4 card, Flick/Calibration, theme/lang | ≥ 15 case |
| T7 | Regression | toàn bộ `tests/` | 194+ case cũ + mới | 100 % pass |
| T8 | Manual QA + soak | `.bangiao/03-kiem-thu.md` | Ma trận §13.4; soak 30 phút; báo cáo số timer/CPU | Có screenshot/log |

**Tester phải chứng minh test "có răng":**
- Cố tình revert `_on_window_map` guard → test T3 phải fail.
- Cố tình thêm lại self-reschedule → test T5 phải fail.
- Cố tình bỏ `_sync_window_style` sau restore → test T3 phải fail.
- Cố tình để Simple dựng sidebar → test T2 phải fail.

### 12.3. Reviewer

| ID | Nội dung | Tiêu chí |
|---|---|---|
| R1 | Soát diff `ui.py` | Không đổi logic aim/capture; chỉ UI/lifecycle |
| R2 | Đối chiếu Pro contract | §6.2 đủ; test T6 xanh; không mất tính năng |
| R3 | Soát Win32 | 64-bit safe, argtypes, không gọi từ thread sai, stop idempotent, không rò HWND/thread |
| R4 | Soát scheduler | Chỉ một chain; clipboard one-shot; không update widget đã destroy |
| R5 | Soát test | Test thực sự bắt lỗi (mutation check); không chỉ assert `hasattr` |
| R6 | Đo hiệu năng | §11; soak 30 phút; kết luận ĐẠT/KHÔNG ĐẠT |

---

## 13. KẾ HOẠCH KIỂM THỬ

### 13.1. Lệnh (chạy khi shell hoạt động)

```powershell
.\venv\Scripts\python.exe -m compileall -q src main.py
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe -m unittest tests.test_ui_mode_config tests.test_simple_mode tests.test_window_lifecycle tests.test_global_hotkey tests.test_ui_mode_switch tests.test_pro_mode_contract -v
.\venv\Scripts\python.exe -c "import tkinter as tk; print(tk.TkVersion)"
```

### 13.2. Unit test chi tiết

#### A. Config (`test_ui_mode_config.py`)

| # | Case | Kỳ vọng |
|---|---|---|
| A1 | Fresh `Config()` | `ui_pro_mode is False`, `ui_toggle_hotkey == "Insert"`, `ui_simple_geometry == "560x540"`, `config_schema == 4` |
| A2 | `from_dict({"ui_pro_mode": True})` | Pro, các key mới default |
| A3 | `ui_toggle_hotkey = "F8"` | giữ "F8"; `parse_hotkey_vk` = 0x77 |
| A4 | `ui_toggle_hotkey = "not-a-key"` | fallback "Insert", WARN một lần |
| A5 | `ui_simple_geometry = "100x100"` | clamp `480x420` |
| A6 | `ui_simple_geometry = "abc"` | default `560x540` |
| A7 | `ui_pro_geometry = "980x660"` roundtrip | giữ nguyên |
| A8 | `to_dict()` chứa đủ 8 key mới | assert set |
| A9 | Migration dict schema 3 có `ui_pro_mode=True` | vẫn Pro, schema 4, không mất key |
| A10 | Migration dict rỗng | Simple, schema 4 |
| A11 | `ui_simple_position = "+1920+0"` | giữ; position invalid → `""` |
| A12 | `ui_start_hidden=True` roundtrip | giữ |
| A13 | `ui_compact_layout=False` | Simple cũ (test ở T2) |

#### B. Simple layout (`test_simple_mode.py`)

| # | Case | Kỳ vọng |
|---|---|---|
| B1 | `config.ui_pro_mode=False`; tạo app | `app._ui_mode == "simple"` |
| B2 | | `not hasattr(app, "sidebar")` hoặc sidebar đã destroy |
| B3 | | `app.geometry()` bắt đầu bằng `560x540` |
| B4 | | `app.resizable() == (False, False)` (qua `wm_resizable`) |
| B5 | | `isinstance(app.content_frame, ctk.CTkFrame)` và **không** phải `CTkScrollableFrame` |
| B6 | | Có `runtime_btn` height 40, `pill_fps`, `pill_delay`, `pill_hardware`, `pill_conn` |
| B7 | | Có `mode_option`, `aim_key_bind_button`, slider `fovsize`, `normal_x_speed`, `normalsmooth` trong `_slider_widgets` |
| B8 | | Có `mode_option_sec`, `aim_key_bind_button_sec`, `fovsize_sec`, `flick_gain_sec`, `normalsmooth_sec` |
| B9 | | Có `var_enabletb_quick`, `var_enablercs`, `simple_profile_option` |
| B10 | Bấm `var_enabletb_quick.set(True); app._on_quick_trigger_changed()` | `config.enabletb is True` |
| B11 | `app._on_mode_selected("Flick")` | `config.mode == "Flick"`; **không** có `card_targeting`; không destroy dashboard |
| B12 | `app._on_mode_sec_selected("Normal")` | hàng Gain ẩn, hàng Speed hiện |
| B13 | `_load_selected_config()` khi chỉ có simple widget | không `AttributeError`; config đổi |
| B14 | Đếm widget đệ quy | `<= 150` |
| B15 | `app.tk.call("after","info")` sau `update()` 3 s | `<= 40` |
| B16 | `_update_performance_stats()` | không raise, không log error |
| B17 | `_set_status_indicator("Status: Offline")` | text cập nhật đúng |
| B18 | Simple → Pro → Simple | vẫn còn `pill_fps`, không nhân đôi widget |

#### C. Window lifecycle (`test_window_lifecycle.py`)

| # | Case | Kỳ vọng |
|---|---|---|
| C1 | `_on_window_map(SimpleNamespace(widget=child))` | `_sync_window_style` **không** gọi |
| C2 | `_on_window_map(SimpleNamespace(widget=app))`, state normal | gọi đúng 1 lần |
| C3 | `_ui_rebuilding=True` | không gọi |
| C4 | `_on_minimize()` với user32 mock trả True | `ShowWindow(SW_MINIMIZE)`; `overrideredirect` **không** đổi |
| C5 | user32 mock trả False | fallback `iconify()`; `_minimized=True` |
| C6 | `_restore_window()` | `deiconify` + `ShowWindow(SW_RESTORE)` + `_sync_window_style(force=True)` + `lift` + `focus_force` |
| C7 | `_hide_window()` | `withdraw()`; `_ui_hidden=True`; không destroy widget |
| C8 | `_show_window()` sau hide | `deiconify`; style force |
| C9 | `_toggle_ui_visibility()` gọi 2 lần trong 100 ms | chỉ đổi trạng thái 1 lần (debounce) |
| C10 | `_on_close()` | `launcher.stop()` gọi 1 lần; `after_cancel` cho 2 job; `destroy` gọi |
| C11 | `_on_close()` gọi 2 lần | không raise, không stop 2 lần |
| C12 | `_sync_window_style()` gọi 2 lần cùng style | `SetWindowPos` chỉ 1 lần (signature cache) |
| C13 | `_sync_window_style(force=True)` | gọi lại dù signature giống |
| C14 | `_on_window_map` khi state `iconic` | không gọi style |
| C15 | Trình tự minimize → map self → `_restore_window` | `_minimized` về False; style được re-apply |

#### D. Hotkey (`test_global_hotkey.py`)

| # | Case | Kỳ vọng |
|---|---|---|
| D1 | `parse_hotkey_vk("Insert")` | `0x2D` |
| D2 | `parse_hotkey_vk("F8")` | `0x77` |
| D3 | `parse_hotkey_vk("")` | `0` |
| D4 | `parse_hotkey_vk("xxx")` | `0x2D` |
| D5 | `LauncherService` với user32 giả `RegisterHotKey` trả 1 | `start()` True; `fallback=False` |
| D6 | `RegisterHotKey` trả 0 | `start()` True; `fallback=True`; WARN |
| D7 | Gọi `_on_hotkey()` | queue nhận đúng 1 `"toggle_ui"` |
| D8 | Gọi `_on_hotkey()` 3 lần trong 100 ms | debounce ở Tk (C9) chỉ toggle 1 lần — test tích hợp |
| D9 | `stop()` | `UnregisterHotKey` gọi; `Shell_NotifyIcon(NIM_DELETE)` gọi; join < 1 s |
| D10 | `stop()` 2 lần | không raise |
| D11 | `update_hotkey(0x77)` | unregister cũ + register mới |
| D12 | Tray menu "Exit" | queue `"exit"` |
| D13 | Thread không gọi Tk | assert không có `app.after` trong thread (dùng flag) |
| D14 | `MOD_NOREPEAT` | assert giá trị `0x4000` trong lời gọi |
| D15 | Không rò thread sau stop | `not any(t.name == "CVMHotkey" for t in threading.enumerate())` |

#### E. Mode switch / leak (`test_ui_mode_switch.py`)

| # | Case | Kỳ vọng |
|---|---|---|
| E1 | Simple → Pro | `sidebar` tồn tại; `_ui_mode=="pro"`; geometry 980×660 |
| E2 | Pro → Simple | không sidebar; geometry 560×540 |
| E3 | 20 vòng đổi mode | `len(after info)` không tăng; số widget không tăng |
| E4 | Đổi mode khi engine đang chạy | `_runtime_active` giữ nguyên; `runtime_btn` text đúng |
| E5 | Đổi mode giữ `_collapsible_section_states` | dict bằng trước |
| E6 | Đổi mode không gọi `config.save_to_file` quá 1 lần | mock đếm |
| E7 | Pro → Simple khi đang maximize | hình học Simple đúng; `_is_maximized=False` |
| E8 | Simple → Pro rồi mở tab Flick V2 | `card_flick_main` tồn tại |
| E9 | `_show_aimbot_tab()` khi đang Simple | tự chuyển Pro; `card_targeting` tồn tại |
| E10 | Đổi mode 10 lần, đo p95 | `<= 120 ms` |

#### F. Pro contract (`test_pro_mode_contract.py`)

| # | Case | Kỳ vọng |
|---|---|---|
| F1 | 5 nav + alias | Combat/Vision/Hardware/Profiles/Telemetry; alias Main Aimbot/Sec Aimbot/Flick V2/RCS/Config/Debug |
| F2 | Sidebar width ≥ 200 | |
| F3 | `runtime_btn` height 38 | |
| F4 | `pill_fps/pill_delay/pill_hardware` | |
| F5 | Combat 4 card + calibration | |
| F6 | Flick V2 card + 7 slider/kênh | |
| F7 | Vision/Hardware/Profiles/Telemetry card | |
| F8 | Theme cycle 6 theme | `_toggle_ui_style` không raise |
| F9 | Language vi/en | `_apply_language` rebuild không raise |
| F10 | Maximize 2 lần | trở về geometry cũ |
| F11 | Profile save/load/export | không đổi hành vi |
| F12 | Clipboard import | không tự nhân bản timer (kết hợp E3) |
| F13 | PID mode tạo canvas + preview | không raise |
| F14 | Binding capture | timeout 10 s, không treo |
| F15 | `config.to_dict()` trước/sau đổi mode | chỉ 4 key UI đổi |

### 13.3. GUI lifecycle test (tích hợp, có Tk thật)

```python
def test_full_lifecycle_simple_pro_hidden(app):
    # 1) Simple
    assert app._ui_mode == "simple"
    w0 = count_widgets(app)
    # 2) Pro
    app._enter_pro_mode()
    app.update_idletasks()
    assert app._ui_mode == "pro"
    assert hasattr(app, "sidebar")
    # 3) về Simple
    app._enter_simple_mode()
    app.update_idletasks()
    assert count_widgets(app) == w0
    # 4) ẩn/hiện
    app._hide_window()
    assert app._ui_hidden
    app._show_window()
    app.update_idletasks()
    assert not app._ui_hidden
    # 5) hotkey giả lập
    app._launcher_queue.put("toggle_ui")
    app._poll_launcher_queue()
    app.update_idletasks()
    assert app._ui_hidden
```

### 13.4. Ma trận QA thủ công

| Chiều | Giá trị |
|---|---|
| Windows | 10 22H2, 11 23H2/24H2 |
| DPI | 100 %, 125 %, 150 % |
| Độ phân giải | 1920×1080, 2560×1440, 1366×768 (Simple vẫn fit?) |
| Mode | Simple, Pro, Simple↔Pro 20 lần |
| Cửa sổ | bình thường, minimize, maximize, ẩn/hiện, đóng khi ẩn (tray Exit) |
| Taskbar | click icon khi minimize; click khi đang mở; unpin/pin; multi-monitor |
| Hotkey | Insert, F8, đổi hotkey trong config, giữ Insert 3 s (không auto-repeat), hotkey trùng game |
| Game | windowed, borderless, exclusive fullscreen; Alt-Tab; game có raw input |
| Instance | chạy `run.bat` lần 2 khi đang ẩn; chạy khi đang Pro; chạy khi đã thoát |
| Runtime | START/STOP ở Simple; START rồi chuyển Pro; đổi profile khi đang chạy |
| Theme/lang | 6 theme, vi/en/zh ở Pro; Simple chỉ tiếng Việt/Anh (label tĩnh) |
| Soak | 30 phút idle ở Simple, 30 phút idle ở Pro, 10 phút ẩn; đo timer/CPU/RAM |

**Tiêu chí QA:**
- Không có khoảng trắng/nháy khi đổi mode.
- Simple không xuất hiện thanh cuộn.
- Minimize → click taskbar → cửa sổ hiện đúng mode, đúng vị trí, không mất icon.
- Insert khi đang ở game borderless → UI hiện/ẩn trong ≤ 150 ms.
- Chạy `run.bat` lần 2 → cửa sổ cũ hiện, không có instance 2 trong Task Manager.
- Sau 30 phút: `len(after info)` không tăng; CPU Simple < 1.5 %.

---

## 14. RỦI RO & GIẢM THIỂU

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| `ShowWindow(SW_MINIMIZE)` không restore đúng trên một số driver/remote desktop | Trung bình | Fallback `iconify()` + hotkey/tray; log; test trên VM |
| `RegisterHotKey` bị game chiếm | Trung bình | Fallback `GetAsyncKeyState` 50 ms; cho đổi phím trong config; hiển thị cảnh báo |
| Tray icon native phức tạp (WNDCLASS/WndProc) | Trung bình | Tách module, test bằng mock; nếu fail → tắt tray, vẫn còn hotkey + single-instance |
| Đổi mode làm mất state runtime | Cao | Invariant I5/I8; test E4; không recreate tracker/capture |
| Simple thiếu tính năng người dùng cần | Trung bình | Có nút Pro 1 click; giữ đủ 6 khối theo yêu cầu; profile load ngay trong Simple |
| Test Tk brittle trên CI/headless | Trung bình | Giữ pattern `SkipTest` như test hiện có; mock user32; không phụ thuộc pixel |
| Pro bị đổi ngoài ý muốn | Cao | Checklist §6.2 + test F + review diff |
| `overrideredirect(True)` + DPI scaling làm lệch vị trí | Thấp | Clamp geometry vào virtual screen; test 125/150 % |
| Đóng app khi thread hotkey đang chờ | Trung bình | Shutdown sequence §8.7; join timeout 1 s; daemon |
| Config schema 4 làm preset cũ mất key | Thấp | `from_dict` chỉ set key có trong data; migration giữ nguyên |
| Người dùng đang quen "Simple = Pro thu nhỏ" | Thấp | Ghi CHANGELOG/README; `ui_compact_layout=False` để quay lại hành vi cũ |

**Rollback:**
1. `ui_compact_layout=False` → Simple quay về hành vi cũ (chỉ collapse section), không cần revert code.
2. `ui_toggle_hotkey=""` + `ui_tray_enabled=False` → tắt launcher mới.
3. `ui_pro_mode=True` → luôn Pro.
4. Revert theo commit C1…C10 (mỗi task một commit).

---

## 15. TIÊU CHÍ HOÀN THÀNH (DoD)

1. **Simple thật**: 560×540, không sidebar, không scrollable, không canvas/tooltip; ≤ 150 widget; build ≤ 60 ms; có đủ 6 khối theo yêu cầu người dùng.
2. **Pro nguyên vẹn**: đủ 5 pillar + sub-nav + Flick V2/Calibration/RCS/Vision/Hardware/Profiles/Telemetry; geometry 980×660; fullscreen hoạt động; test F xanh; không mất attribute nào trong §6.2.
3. **Chuyển mode**: ≤ 120 ms, không nháy, không rò timer/widget sau 20 vòng, giữ state runtime và section.
4. **Persist**: `ui_pro_mode` + 8 key schema 4 roundtrip; config cũ migrate không mất dữ liệu.
5. **Launcher**: Insert ẩn/hiện toàn cục (kể cả game borderless); click taskbar luôn restore; minimize không phá `WS_EX_APPWINDOW`; `run.bat` lần 2 gọi instance cũ; tray Exit đóng sạch.
6. **Hiệu năng**: sau 10 phút, timer ≤ 12 callback/s; CPU idle Simple < 1.5 %; không còn chuỗi clipboard nhân bản.
7. **Chất lượng**: `compileall` sạch; toàn bộ test cũ + mới xanh; Reviewer ký ĐẠT; QA thủ công §13.4 đạt.
8. **Không phá lõi**: không sửa `src/aim_system/**`, `src/capture/**`, `src/utils/mouse/**`; Flick/Calibration vẫn đúng.

---

## 16. PHỤ LỤC

### A. Vì sao `<Map>` bắt được sự kiện của widget con

Tk gán bindtags mặc định:

```
('.!ctkframe.!ctkbutton', 'Button', '.', 'all')
                              ▲
                              └── toplevel path nằm trong bindtags của MỌI widget con
```

`self.bind("<Map>", handler)` đăng ký trên tag `.`, nên handler chạy cho cả Map của `.` **và** của mọi descendant. Đây là lý do một lần rebuild tab (hàng trăm widget) tạo hàng trăm lời gọi `overrideredirect(True)`.

### B. Toán học của rò rỉ timer

Gọi `P(t)` = số chuỗi tại thời điểm `t`. Mỗi 1,2 s scheduler thêm 1 chuỗi:

```
P(t) ≈ t / 1.2
callbacks/giây ≈ P(t) / 1.2 = t / 1.44
t = 60 s   → ~42 callback/s
t = 300 s  → ~208 callback/s
t = 600 s  → ~417 callback/s
```

Mỗi callback còn tạo một `after` mới → số timer P(t) tiếp tục tăng. Đây là **rò rỉ thật**, không phải "Tk chậm".

### C. Bảng VK hotkey đề xuất

| Tên | VK | Ghi chú |
|---|---|---|
| Insert | 0x2D | mặc định |
| Delete | 0x2E | thay thế |
| Home | 0x24 | |
| End | 0x23 | |
| F8 | 0x77 | |
| F9 | 0x78 | |
| Pause | 0x13 | |

`to_vk_code()` đã hỗ trợ các tên này (`src/utils/mouse/keycodes.py:31-106`).

### D. Hợp đồng attribute giữa scheduler và hai layout

| Attribute | Pro | Simple | Nếu vắng |
|---|---|---|---|
| `runtime_btn` | có | có | `_refresh_runtime_button` guard |
| `fps_label` / `decode_delay_label` / `total_delay_label` | có | **không** | `_update_performance_stats` dùng `_safe_text` + pills |
| `pill_fps` / `pill_delay` / `pill_hardware` | có | có | |
| `pill_conn` | không | có | chỉ Simple dùng |
| `status_indicator` | có | có | |
| `sidebar` | có | **không** | test Pro chỉ assert khi Pro |
| `content_frame` | Scrollable | Frame thường | builder riêng |
| `config_option` | có | **không** (dùng `simple_profile_option`) | `_profile_widget()` abstraction |
| `active_profile_label` | có | **không** | không cập nhật định kỳ |
| `debug_log_textbox` | có (Telemetry) | **không** | `_update_debug_log` đã guard |
| `_slider_widgets` | đầy đủ | 6 mục | reset khi teardown |

### E. Checklist review nhanh cho Reviewer

```
[ ] Không có self.bind("<Map>"...) không guard event.widget
[ ] Không còn withdraw()/deiconify() trong _ensure_taskbar_icon
[ ] _on_minimize không gọi overrideredirect
[ ] _taskbar_style_applied không còn là cờ "một lần duy nhất"
[ ] _toggle_pro_mode không clear _collapsible_section_states
[ ] _poll_clipboard_config_import không tự after()
[ ] _ui_tick chỉ một chain; có _scheduler_started
[ ] Mọi update widget dùng safe helper hoặc kiểm tra winfo_exists
[ ] Simple không tạo CTkScrollableFrame/sidebar/tooltip/canvas
[ ] _on_close dọn hotkey/tray/thread/after job
[ ] main.py có single-instance trước khi tạo Tk
[ ] Không sửa file trong src/aim_system, src/capture, src/utils/mouse
[ ] Test mới thực sự fail khi revert bản sửa (mutation check)
```

### F. Quyết định cần chốt trong bước thi công

1. **Simple mặc định hay Pro mặc định cho fresh install?** Kế hoạch chọn **Simple** (`ui_pro_mode=False`) vì yêu cầu "khi ở dạng thu nhỏ không bị giật"; người dùng Pro hiện tại giữ Pro nhờ migration.
2. **Tray mặc định bật?** Kế hoạch chọn **bật trên Windows** (`ui_tray_enabled=True`), vì đây là lối thoát khi cửa sổ withdrawn; nếu implementation native gặp lỗi trên máy test → hạ xuống `False` và dựa vào hotkey + single-instance.
3. **Nút `─` = minimize taskbar hay hide?** Kế hoạch chọn **minimize taskbar** (mặc định), `ui_minimize_to_tray=True` để đổi sang hide.
4. **Có giữ nút maximize ở Simple?** **Không**.
5. **Có bump version?** Không, trừ khi PO yêu cầu; ghi CHANGELOG mục `Unreleased`.

---

*Hết kế hoạch. Trong bước này chỉ file `.bangiao/01-ke-hoach.md` được ghi; không có file mã nguồn nào bị thay đổi.*
