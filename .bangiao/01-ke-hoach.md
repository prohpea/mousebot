# 01 — KẾ HOẠCH TỐI ƯU HỆ THỐNG, HOÀN THIỆN UI FLICK AIM V2 & PHÁT HÀNH v2.1.0

**Mã hiệu:** `PLAN-20261109-FLICK-V2-UI-210`
**Trạng thái:** Chỉ đọc — phân tích — thiết kế — lập kế hoạch. **Không sửa một dòng mã nguồn nào trong bước này.**
**Tài liệu được thay thế:** `.bangiao/01-ke-hoach.md` phiên bản trước (kế hoạch sửa lỗi Flick lệch). Phần lõi Flick V2 của kế hoạch đó **đã được thi công** (`aim_math.py`, `flick_controller.py`, `mode_flick.py`, config migration, test). Kế hoạch này tiếp nhận trạng thái đó và tập trung vào **UI hoàn chỉnh, tối ưu hiệu năng, làm sạch mã, và nâng cấp phiên bản v2.1.0**.
**Phạm vi đọc:** `main.py`; `version.json`; `CHANGELOG.md`; `README.md`; `config.json`; `configs/*.json`; `src/ui.py`; `src/ui_components.py`; `src/ui_tabs/*`; `src/utils/config.py`; `src/utils/i18n.py`; `src/utils/updater.py`; `src/utils/debug_logger.py`; `src/utils/activation.py`; `src/aim_system/aim_math.py`; `flick_controller.py`; `mode_flick.py`; `mode_dispatcher.py`; `normal.py`; `RCS.py`; `MagnetTrigger.py`; `target_smoother.py`; `src/utils/detection.py`; `src/aim_system/anti_smoke_detector.py`; `src/capture/capture_service.py`; toàn bộ `tests/*.py`; `locales/*.json`.

> **Ghi chú môi trường:** trong phiên này shell `pwsh` trả về `0xC0000142` cho mọi lệnh, nên **không thể chạy test/benchmark**. Toàn bộ kết luận dưới đây là phân tích tĩnh có đối chiếu số học và số dòng cụ thể. Các lệnh kiểm chứng được ghi ở mục 12 để chạy trong bước thi công.

---

## 1. KẾT LUẬN ĐIỀU HÀNH

Hệ thống hiện tại **đã có lõi Flick V2 đúng về vật lý**, nhưng **chưa có giao diện Flick V2 hoàn chỉnh**, **chưa có Calibration Valorant thực thụ**, **chưa có nguồn gốc calibration đáng tin**, và **phiên bản 2.0.0 còn nằm rải rác ở 6 điểm**: `version.json`, title bar, badge “v2.0 Pro Engine”, AppUserModelID, `CHANGELOG.md`, `README.md`. Đồng thời tồn tại một số điểm nóng hiệu năng và lỗi đúng đắn trong pipeline di chuyển/UI.

Ba trục công việc:

1. **UI Flick V2 hoàn chỉnh** — thêm `Settle Delay`, chuẩn hoá `Gain / Max Counts / Budget / Iterations / Deadzone / Switch Radius`, tab chuyên dụng `Flick V2`, chẩn đoán trực tiếp, đồng bộ Main + Sec, tách khỏi `ui.py` sang `ui_tabs/`.
2. **Calibration Valorant** — chế độ `Valorant` (0.07°/count tại sens 1.0), `Measured` có nguồn gốc và ràng buộc R²/số mẫu, `Analytic` legacy; lưu `calibration_source`; tính lại theo sens khi ở chế độ Valorant; hiển thị hình học thật (frame/crop/focal).
3. **Tối ưu + làm sạch + v2.1.0** — cắt các vòng lặp UI 500 ms quét toàn bộ widget tree, chặn preview OpenCV theo FPS, cache hình học/calibration, gộp/tách queue theo tag đúng nghĩa, xoá ~450 dòng UI chết, và đưa phiên bản về một nguồn duy nhất.

**Phát hiện nghiêm trọng nhất ngoài phạm vi UI:** `_process_move_queue()` hiện **cộng gộp mọi tag vào một lệnh `controller.move()` duy nhất** (`main.py:217-246`), dù comment khẳng định “Commands are merged ONLY within the same tag”. Hệ quả: xung `flick`, bước `track`, nhịp `rcs` và xung `calib` có thể bị **cộng dồn trong cùng một tick**, làm sai cả hiệu năng lẫn phép đo calibration. Đây là lỗi P0 cần sửa trước khi quảng bá Calibration Valorant.

---

## 2. KIỂM TOÁN HIỆN TRẠNG

### 2.1. Lõi Flick V2 đã có gì

| Thành phần | Hiện trạng | Đánh giá |
|---|---|---|
| `src/aim_system/aim_math.py` | `FrameGeometry`, `Calibration`, `resolve_geometry`, `resolve_calibration`, `px_to_counts`, `fit_calibration`, `counts_per_deg_from_slope` | Đạt; là nguồn chuyển đổi duy nhất |
| `src/aim_system/flick_controller.py` | Vòng kín, gain vật lý, clamp cả vector, residual, budget, settle, rollback, target-switch radius | Đạt về thuật toán; còn lỗi rollback timing và thiếu cấu hình hoá switch radius |
| `src/aim_system/mode_flick.py` | Adapter gọi controller, queue tag `flick`, rollback khi queue từ chối | Đạt; còn resolve geometry/calibration mỗi frame |
| `mode_dispatcher._MODE_CAPS` | Flick `uses_smoother=False`, `uses_budget=True`, `one_shot=True` | Đạt; bypass smoother đúng |
| `main.py` | `_clip_movement` scale giữ hướng, queue có tag, truyền `FrameInfo` thật | Đúng một phần; consumer cộng gộp chéo tag |
| `config.py` | `flick_gain`, `max_counts`, `budget`, `iterations`, `deadzone`, `settle`, `max_speed`, migration | Đạt một phần; thiếu `calibration_source`, `switch_radius`, provenance |
| `config.json` + 6 preset | `counts_per_deg = 62.11`, `flick_gain = 1.0`, `flick_engine = v2` | Số đúng Valorant nhưng **khai báo sai nguồn gốc** (`calibration_samples=0`, `r2=0`) |
| Tests | `test_aim_math.py` 35 test, `test_flick_controller.py` 30 test, cùng các test UI/i18n | Nền tốt; thiếu test version, UI Flick V2, config provenance, queue |

### 2.2. Khoảng trống giao diện Flick V2

| # | Khoảng trống | Bằng chứng | Mức |
|---|---|---|---|
| G1 | **Không có `Settle Delay` trên UI** dù config/controller đã hỗ trợ | `config.py:275,290,730,746,1455-1456`; `flick_controller.py:405-413`; `ui.py` không có `flick_settle_ms` | **P0** |
| G2 | Không có **Calibration Valorant** thực thụ; chỉ có “Flick Calibration” chung với FOV + impulse thủ công | `ui.py:5161-5266` | **P0** |
| G3 | Không có **tab Flick V2 chuyên dụng**; slider Flick nằm rải trong card “Algorithm Tuning” của Main/Sec | `ui.py:5013-5029`, `ui.py:5573-5589` | **P0** |
| G4 | Không hiển thị **nguồn calibration** (Valorant preset / Đo thực / Analytic) và cảnh báo provenance | `_calibration_state_text` chỉ phân biệt `MEASURED`/`ANALYTIC`; `aim_math.Calibration` chỉ có 2 source | P0 |
| G5 | Không có **chẩn đoán Flick trực tiếp** (last reason, iterations, counts, clamp, error) | `FlickState` có dữ liệu nhưng không publish ra UI | P1 |
| G6 | Main và Sec **sao chép gần như nguyên khối** phần Flick (2 × 5 slider + callback trùng lặp) | `ui.py:5013-5029` vs `5573-5589`; callback `9703-9733` vs `10166-10171` | P1 |
| G7 | Không có kiểm tra **`Settle` vs `Budget`**; mặc định 70 ms / 120 ms chỉ cho tối đa 2 bước | `flick_controller.py:385-413`; `config.py:274-275` | **P0** |
| G8 | Không có nút **Reset Flick state / Copy diagnostics / Auto-fix timing** | Không tồn tại | P2 |
| G9 | `Magnet Trigger` UI là file chết; tab chỉ redirect | `ui_tabs/magnet_trigger_tab.py` không được import; `ui.py:5979-5981` | P2 |
| G10 | Nhãn mới chưa có bản dịch `vi/en/zh-CN`; `en.json` rỗng | `locales/en.json:4`; `vi.json` không có Flick/Gain/Calibration | P1 |

### 2.3. Khoảng trống phiên bản v2.1.0

| # | Vị trí | Giá trị hiện tại | Cần đổi |
|---|---|---|---|
| V1 | `version.json:2-4` | `2.0.0`, changelog v2.0.0 | `2.1.0`, codename `Flick V2`, schema 3, changelog mới |
| V2 | `src/ui.py:321` | `self.title("CVM colorBot v2.0 PRO")` | Dùng helper phiên bản, không hard-code |
| V3 | `src/ui.py:526` | `v{current_version} PRO` | Giữ động, nhưng lấy từ một helper duy nhất |
| V4 | `src/ui.py:4981` | badge `"v2.0 Pro Engine"` | `v2.1.0 · Flick V2` động |
| V5 | `main.py:13` | `mycompany.colorbot.v2.0` | **Không nên version hoá AppUserModelID**; đổi về ID ổn định `mycompany.colorbot` (tránh Windows tạo icon taskbar trùng mỗi release) |
| V6 | `CHANGELOG.md:7` | mục mới nhất `v2.0.0` | Thêm mục `[v2.1.0]` lên đầu; giữ lịch sử |
| V7 | `README.md:13` | badge `version-2.0.0--PRO` | `2.1.0--PRO` + mô tả Flick V2/Calibration |
| V8 | Không có test | — | Test chống lệch phiên bản giữa `version.json`, title, badge, changelog |

### 2.4. Điểm nóng hiệu năng

| # | Vị trí | Vấn đề | Ảnh hưởng | Mức |
|---|---|---|---|---|
| H1 | `ui.py:9529-9558` → `8831-8832` → `995-998` | Mỗi 500 ms gọi `_refresh_capture_entry_card()` → `_apply_runtime_settings_lock()` → **đệ quy duyệt toàn bộ widget tree** của 3 frame phần cứng **khi tab Hardware đang mở**; khi tab khác, vẫn gọi `winfo_exists()` trên widget đã destroy | 2-10 ms mỗi 500 ms khi đang ở Hardware; giật khi kéo slider | **P0** |
| H2 | `ui.py:10620-10674` | `_update_debug_log()` chạy 10 Hz, luôn lấy 500 log, format toàn bộ chuỗi, rồi so sánh với toàn bộ textbox; sau khi rời tab, widget đã bị destroy nhưng attribute vẫn còn nên vẫn format rồi mới ném exception | ~5.000 phép format/giây + exception 10 Hz | **P0** |
| H3 | `main.py:595-598`, `714-738` | Khi bật preview: `bgr_img.copy()` mỗi frame, `display_img = bgr_img.copy()`, 3 cửa sổ `imshow` + `waitKey` mỗi frame | 144 FPS → 432 lời gọi GUI/s; copy 720p ~0.3-1 ms/frame | **P0** |
| H4 | `main.py:510-528` | Anti-smoke: với mỗi target, `min()` trên toàn bộ `target_bboxes`; `is_bbox_plausible()` chạy `findContours + convexHull` trên ROI; hàm được gọi **hai lần** (Main + Sec), mỗi lần lặp lại toàn bộ | O(n²) + 2× contour cho mỗi target/frame | **P0** khi bật anti-smoke |
| H5 | `main.py:217-246` | Gom nhóm tag bằng list comprehension lồng nhau; sau đó **cộng tất cả tag** vào `merged_dx/dy` | Sai đúng đắn + O(n²) nhỏ | **P0** |
| H6 | `mode_flick.py:43-65` | Mỗi frame gọi `resolve_geometry()` + `resolve_calibration()` + `configure()` dù cấu hình/hình học không đổi | Dataclass + trig + getattr mỗi frame | P1 |
| H7 | `aim_math.py:300-409` | `resolve_geometry()` đọc hàng chục config key, dựng `CropInfo`, `FrameGeometry` mỗi lần gọi | 20-50 µs/frame; tăng khi nhiều mode v2 | P1 |
| H8 | `normal.py:950-972` | `_dispatch_aimbot` gọi `get_mode_caps()` (copy dict) mỗi lần; `process_normal_mode` gọi thêm 2 lần cho RCS/Y-release | 3 copy dict/frame không cần thiết | P1 |
| H9 | `main.py:955-1020` | `_estimate_head_positions()` luôn `cv2.rectangle()` vẽ ROI **kể cả khi preview tắt**, và `np.where` + `np.median` trên upper mask cho từng detection | Vẽ vô ích + cấp phát mảng mỗi target | P1 |
| H10 | `ui.py:9560-9631` | Cập nhật 3 label mỗi 500 ms dù chuỗi không đổi; nhánh `NDI`/`CaptureCard` ghi `~target_fps` | String churn nhỏ, nhưng cộng dồn với H1 | P2 |
| H11 | `ui.py:454-461` | 6 timer `after()` độc lập (50/100/200/300/500/1200 ms) | Tk event queue chịu tải; khó tạm dừng khi minimize | P1 |
| H12 | `main.py:1134`, `1154` | `config.load_from_file()` được gọi **hai lần**; lần đầu sau khi `AimTracker` đã khởi tạo, nên tracker giữ default đến khi `_sync_config_to_tracker()` chạy | Trạng thái không nhất quán lúc startup | P1 |
| H13 | `debug_logger.py:194-205` | `log_move()` ghi deque cho **mọi bước aim** ở 144-200 FPS, hai kênh | 300-400 entry/giây; hữu ích khi debug, lãng phí khi chạy thật | P1 |
| H14 | `main.py:584-598`, `1018` | Nhiều `getattr(config, ...)` trong vòng lặp detection; `config` là global mutable | Chậm nhẹ + không thread-safe | P2 |
| H15 | `ui.py:10116-10134` | Đổi mode → `_show_aimbot_tab()` phá và dựng lại toàn bộ tab (4 card, hàng chục widget) | Giật 50-150 ms mỗi lần đổi mode | P2 |

### 2.5. Lỗi đúng đắn / nợ kỹ thuật phát hiện thêm

| # | Lỗi | Bằng chứng | Hệ quả |
|---|---|---|---|
| C1 | **Cộng gộp chéo tag trong move queue** | `main.py:217-246`: `merged_dx += item[0]` cho mọi `item_tag`; comment `195-197` nói ngược lại | Flick + track + RCS + calib có thể cộng dồn; xung flick bị bóp méo; phép đo calibration sai |
| C2 | **Xung calibration không độc quyền** | `ui.py:5328` đẩy tag `calib`; consumer cộng với mọi lệnh khác | “Send impulse” có thể kèm bước aim → sai số đo |
| C3 | **`rollback_step()` không hoàn tác timing** | `flick_controller.py:313-325` chỉ giảm `iterations`, phục hồi `residual`; không phục hồi `_last_step_time`, `last_sent`, `total_sent`, `clamped_steps` | Khi queue từ chối xung, controller tưởng đã gửi → chờ `settle_ms` vô ích; budget bị tiêu sai |
| C4 | **Khai báo provenance calibration sai** | `config.json:222-225`: `counts_per_deg=62.11`, `calibration_r2=0`, `samples=0`; `_calibration_state_text` hiển thị `MEASURED` | Người dùng tin là đã đo thực; thực chất là preset Valorant |
| C5 | **`resolve_calibration` bỏ qua nguồn, không tính lại theo sens** | `aim_math.py:525-537`: chỉ đọc `counts_per_deg_x/y` nếu > 0 | Đổi sens từ 0.23 → 0.40 vẫn dùng 62.11 c/deg → flick thiếu 42% |
| C6 | **Settle/Budget không được kiểm tra** | `flick_controller.py:385-413`; default 70/120 | Chỉ 2 bước; UI không cảnh báo; người dùng tưởng 4 iterations có tác dụng |
| C7 | **Vẽ ROI vô điều kiện** | `main.py:1018` nằm ngoài mọi điều kiện `show_detection` | Tốn CPU + có thể vẽ lên ảnh trigger source |
| C8 | **Widget debug đã destroy nhưng vẫn được dùng** | `ui.py:1476-1488` không xoá `debug_log_textbox`; `10620-10674` vẫn format rồi mới lỗi | Lãng phí + log exception |
| C9 | **Hai lần load config** | `main.py:1134`, `1154` | Startup chậm, tracker/UI lệch trạng thái |
| C10 | **Fit calibration một trục vẫn được chấp nhận** | `ui.py:5377-5386` ngoại suy trục còn lại bằng tỉ lệ focal; `record_sample` dùng `abs()` | Có thể lưu scale méo; mất dấu phép đo |
| C11 | **`flick_max_step_counts` ma trong legacy path** | `normal.py:513` default 999, không có schema | Chỉ ảnh hưởng `flick_engine=legacy`; cần khai tử cùng legacy |
| C12 | **`max_speed` clamp lần hai** | `main.py:271-296`; legacy flick gọi `tracker._clip_movement`, controller V2 thì không | Hai nguồn giới hạn khác nghĩa; dễ gây hiểu nhầm khi tuning |
| C13 | **`ui_pro_mode` không được persist** | `ui.py:359,1375` đọc/ghi `config.ui_pro_mode`; `config.py` không khai báo key này và `to_dict()` không chứa nó | Mỗi lần mở app, chế độ Pro/Simple reset về Simple ngoài ý muốn |
| C14 | **`configure()` không truyền `settle_ms`** | `mode_flick.py:52-64` truyền `gain/max_counts/max_iterations/budget/deadzone` nhưng thiếu `settle_ms` (và sẽ thiếu `switch_radius_px`) | Đổi Settle trên UI **không có tác dụng** cho tới khi controller bị tạo lại (đổi mode/restart) — đúng lỗi sẽ lộ ra ngay khi thêm slider Settle |

---

## 3. KIẾN TRÚC ĐÍCH

### 3.1. Nguyên tắc

1. **Một nguồn cho phiên bản:** `version.json` → `src/version.py` → title/badge/changelog/updater. Không hard-code chuỗi phiên bản ở UI/main.
2. **Một nguồn cho calibration:** `calibration_source` quyết định công thức; `Valorant` tính động theo sens; `Measured` bất biến theo sens và có provenance; `Analytic` là legacy có cảnh báo.
3. **Một nguồn cho hình học:** `resolve_geometry()` + cache theo signature; UI chỉ hiển thị, không tự tính.
4. **UI là lớp trình bày:** `ui.py` giữ orchestration; các panel Flick/Calibration nằm trong `src/ui_tabs/`, dùng chung spec để Main/Sec không lệch.
5. **Hot path không cấp phát:** snapshot cấu hình một lần mỗi frame; controller chỉ `configure()` khi signature đổi.
6. **Queue đúng ngữ nghĩa tag:** không bao giờ cộng chéo tag; `calib` độc quyền; `flick` nguyên xung.
7. **Mọi giới hạn có tên, có schema, có log, có test.**
8. **Xoá code chết có bằng chứng grep; giữ shim public trong một release.**

### 3.2. Sơ đồ module đích

```
version.json ──► src/version.py ──► ui.title / badge / UpdateDialog / updater / main print
                                      │
config.json ──► src/utils/config.py ──┤ schema 3, calibration_source, settle, switch_radius
                                      ▼
                         src/aim_system/tuning.py (MỚI)
                         FlickTuning (immutable) + signature()
                                      │
main.track_once ──► process_normal_mode ──► mode_dispatcher ──► mode_flick
                                      │                         │
                                      │                         ├─ FlickController.step
                                      │                         ├─ aim_math cache
                                      │                         └─ tracker.flick_status
                                      ▼
                         move_queue (tag: calib | flick | track | rcs)
                                      │
                         _process_move_queue: dispatch THEO TAG
                                      │
UI scheduler (100/250 ms, chỉ tab hiện tại) ◄── tracker.flick_status + config snapshot
        │
        ├─ src/ui_tabs/flick_tab.py        (tab Flick V2 + card inline)
        ├─ src/ui_tabs/calibration_tab.py  (Calibration Valorant)
        └─ src/ui_tabs/common.py           (spec slider, helper, format)
```

### 3.3. Điều hướng UI đích

```
Combat
 ├─ Main Aimbot
 ├─ Sec Aimbot
 ├─ Flick V2          ← MỚI: tab chuyên dụng, 2 cột Main/Sec + Calibration + Diagnostics
 └─ Recoil & RCS

Main Aimbot / Sec Aimbot
 └─ Card "Algorithm Tuning"
      ├─ (mode Normal/WindMouse/...) như cũ
      └─ (mode Flick) card compact:
           Gain · Settle · Max Counts · Budget · Deadzone
           [Open Flick V2]  [Calibrate]
```

Lý do giữ cả hai: người dùng đang ở tab Main/Sec có ngữ cảnh mode; người dùng muốn tinh chỉnh sâu có tab riêng. **Cùng một builder**, không sao chép.

### 3.4. Bố cục tab Flick V2 (wireframe)

```
┌ Flick V2 ─────────────────────────────────────────────────────────────────────┐
│ [Engine v2] [Calibration: VALORANT · 62.11 c/deg] [Frame 640×360 · crop]      │
│ [Effective steps: 2 / 4] [Last: aim · 139.8 counts · 30.0 px]                 │
├───────────────────────────────┬───────────────────────────────────────────────┤
│ MAIN CHANNEL                  │ SECONDARY CHANNEL                             │
│ ┌ Ballistics ───────────────┐ │ ┌ Ballistics ───────────────────────────────┐ │
│ │ Gain           [1.00]     │ │ │ Gain           [1.00]                     │ │
│ │ Settle Delay   [70 ms]    │ │ │ Settle Delay   [70 ms]                    │ │
│ │ Max Counts     [6000]     │ │ │ Max Counts     [6000]                     │ │
│ │ Budget         [240 ms]   │ │ │ Budget         [240 ms]                   │ │
│ │ Iterations     [4]        │ │ │ Iterations     [4]                        │ │
│ │ Deadzone       [1.5 px]   │ │ │ Deadzone       [2.0 px]                   │ │
│ │ [Advanced ▸] Switch 64 px │ │ │ [Advanced ▸] Switch 64 px                 │ │
│ │ [Calibrate] [Reset state] │ │ │ [Calibrate] [Reset state]                 │ │
│ └───────────────────────────┘ │ └───────────────────────────────────────────┘ │
├───────────────────────────────┴───────────────────────────────────────────────┤
│ CALIBRATION — VALORANT                                                        │
│ [Valorant] [Measured] [Analytic]        Sens [0.230]  DPI [1100]              │
│ → 62.11 counts/deg · 51.63 cm/360 · source = VALORANT preset                  │
│ Geometry: 1920×1080 · hFOV 103.0° · focal 763.6 px · 0.0750°/px · native     │
│ [Apply Valorant scale] [Send test impulse] [Record sample] [Fit & save]       │
│ Samples x=0 y=0 · R²=-- · Updated: --                                         │
├───────────────────────────────────────────────────────────────────────────────┤
│ ▸ Diagnostics (collapsed)                                                     │
│   last_reason=aim · iterations=1/4 · counts=(139.8, 0.0) · residual=(0.2,0.0) │
│   geometry_source=crop · calibration_source=valorant · clamped=0              │
└───────────────────────────────────────────────────────────────────────────────┘
```

### 3.5. Luồng dữ liệu & quyền sở hữu trạng thái

- **Config** là nguồn duy nhất cho tham số; UI callback ghi scalar + gọi `config.touch()` (revision++).
- **`FlickTuning`** là snapshot bất biến được tạo ở đầu `process_normal_mode` (hoặc khi signature đổi), truyền vào `FlickController`. Không đọc global config trong vòng lặp step.
- **`FlickStatus`** là dict nhỏ, gán atomic vào `tracker.flick_status[channel]`; UI đọc 250 ms/lần. Không lock trong hot path.
- **`aim_math` cache** giữ `FrameGeometry`/`Calibration` theo signature; UI gọi cùng API với `refresh=False` để hiển thị.
- **Move queue** nhận tag; consumer dispatch theo tag; calibration có cờ `calibration_session` để pipeline aim tự bỏ qua.

### 3.6. Mô hình threading / scheduler UI

- Một scheduler duy nhất `_ui_tick()` mỗi 100 ms, phân nhánh theo `elapsed`:
  - 100 ms: source updates (chỉ NDI), debug log (chỉ tab Telemetry + dirty).
  - 250 ms: performance stats, Flick status, calibration readout (chỉ tab liên quan).
  - 500 ms: connection/hardware status (chỉ khi trạng thái đổi).
  - 1200 ms: clipboard poll (chỉ tab Profiles).
- Tạm dừng tick nặng khi `self.state() == "iconic"` hoặc tab không hiện.
- Mọi cập nhật widget từ worker phải qua `self.after(0, ...)` (giữ nguyên quy ước hiện có).

---

## 4. ĐẶC TẢ UI FLICK V2

### 4.1. Bảng điều khiển (Main & Sec dùng chung spec)

| Key | Nhãn UI | Khoảng | Bước | Mặc định Main | Mặc định Sec | Handler | Ghi chú |
|---|---|---|---|---|---|---|---|
| `flick_gain` | Gain (1.0 = physical) | 0.10 – 3.00 | 0.01 | 1.00 | 1.00 | `_on_flick_gain_changed` | Không phải “feel knob”; tooltip |
| `flick_settle_ms` | Settle Delay (ms) | 0 – 300 | 5 | 70 | 70 | `_on_flick_settle_ms_changed` | **MỚI**; chờ pipeline camera |
| `flick_max_counts` | Max Counts / Step | 100 – 20000 | 50 | 6000 | 6000 | `_on_flick_max_counts_changed` | Budget vector, giữ hướng |
| `flick_budget_ms` | Convergence Budget (ms) | 40 – 1000 | 10 | **240** (fresh) | **240** (fresh) | `_on_flick_budget_ms_changed` | Giữ 120 khi migrate |
| `flick_max_iterations` | Max Iterations | 1 – 10 | 1 | 4 | 4 | `_on_flick_max_iterations_changed` | |
| `flick_deadzone_px` | Deadzone (px) | 0 – 20 | 0.1 | 1.5 | 2.0 | `_on_flick_deadzone_px_changed` | |
| `flick_switch_radius_px` | Target Switch Radius (px) | 16 – 256 | 4 | 64 | 64 | `_on_flick_switch_radius_px_changed` | **MỚI**; advanced |
| `flick_engine` | Engine | `v2` / `legacy` | — | v2 | v2 | `_on_flick_engine_changed` | Advanced; legacy chỉ A/B |
| `flick_telemetry_enabled` | Publish diagnostics | bool | — | False | False | switch | Tránh log spam |

**Quy tắc hiển thị:**
- `Settle Delay` có tooltip: “Thời gian chờ frame mới sau mỗi xung. Nên ≥ độ trễ pipeline (≈70 ms) + 1 frame.”
- Dòng derived ngay dưới Budget:
  - `effective_steps = min(max_iterations, floor(budget_ms / max(settle_ms, 1)) + 1)`
  - `estimated_max_travel = max_counts * effective_steps` (counts)
  - Với `settle=70`, `budget=120` → `floor(1.71)+1 = 2` bước: **UI hiện tại hứa 4 iterations nhưng thực tế chỉ có 2**. Đây là lý do fresh default được đặt `budget=240` (`floor(3.43)+1 = 4`) để tôn trọng đúng `max_iterations=4`; config cũ giữ 120 và hiện cảnh báo thay vì âm thầm sửa.
  - Nếu `effective_steps < 2`: badge vàng **“Settle ≥ Budget: chỉ 1 bước”** + nút `Auto-fix` đặt `budget = settle + 50`.
  - Nếu `settle_ms == 0`: badge xám “Không chờ pipeline; có thể đo frame cũ”.
- `Gain` hiển thị thêm `counts/deg` hiện tại và `counts cho 30 px` (đọc từ `aim_math`, cache).
- Nút `Calibrate` chuyển sang tab Flick V2 (hoặc scroll tới card Calibration) và focus mode `Valorant`.
- Nút `Reset state` gọi `reset_aim_state(tracker, is_sec=...)`, log, cập nhật status.

### 4.2. Thành phần & tái sử dụng

Tạo `src/ui_tabs/common.py`:

```python
FLICK_SLIDER_SPECS = (
    # key, label, min, max, step, default_main, default_sec, is_float, advanced
    ("flick_gain", "Gain (1.0 = physical)", 0.1, 3.0, 0.01, 1.0, 1.0, True, False),
    ("flick_settle_ms", "Settle Delay (ms)", 0.0, 300.0, 5.0, 70.0, 70.0, True, False),
    ("flick_max_counts", "Max Counts / Step", 100, 20000, 50, 6000, 6000, False, False),
    ("flick_budget_ms", "Convergence Budget (ms)", 40, 1000, 10, 240, 240, True, False),
    ("flick_max_iterations", "Max Iterations", 1, 10, 1, 4, 4, False, False),
    ("flick_deadzone_px", "Deadzone (px)", 0.0, 20.0, 0.1, 1.5, 2.0, True, False),
    ("flick_switch_radius_px", "Target Switch Radius (px)", 16, 256, 4, 64, 64, False, True),
)
```

- `ui.py:_add_slider_in_frame` mở rộng tham số `steps=None`, `suffix=""`, `tooltip=None`, `help_text=None`, `advanced=False`; vẫn đăng ký `_slider_widgets` để `_apply_settings` cập nhật được.
- `flick_tab.build_flick_panel(app, parent, is_sec)` dùng spec; gắn `app.flick_sliders_main/sec` để test.
- `flick_tab.build_flick_v2_tab(app)` dựng tab đầy đủ (2 cột + Calibration + Diagnostics).
- `ui.py` chỉ còn:
  - `_show_flick_v2_tab()` → `build_flick_v2_tab(self)`;
  - trong `_show_aimbot_tab`/`_show_sec_aimbot_tab`, nhánh `Flick` → `build_flick_panel(self, card.content, is_sec=...)`;
  - các proxy `_build_calibration_card` → `build_flick_calibration_card(self, grid_container)`.
- `magnet_trigger_tab._build_flick_params` cập nhật để dùng cùng spec (nếu giữ file) hoặc xoá file chết.

### 4.3. Callback & đồng bộ

Thêm vào `ViewerApp`:

| Callback | Hành vi |
|---|---|
| `_on_flick_settle_ms_changed(val)` | `config.flick_settle_ms = float(val)`; `config.touch()`; refresh derived; reset controller để áp dụng ngay |
| `_on_flick_settle_ms_sec_changed(val)` | Tương tự với `_sec` |
| `_on_flick_switch_radius_px_changed(val)` | Ghi config; controller.configure(switch_radius) |
| `_on_flick_engine_changed(val)` | Ghi `flick_engine`; reset cả 2 controller; rebuild panel |
| `_on_flick_telemetry_changed(val)` | Ghi bool; bật/tắt publish |
| `_refresh_flick_readouts()` | Cập nhật derived + status; chỉ chạy khi tab Flick V2/Main/Sec hiện hành |
| `_copy_flick_diagnostics()` | Copy JSON nhỏ vào clipboard (helper sẵn có) |

Tất cả callback phải:
1. Chuẩn hoá/clampe giá trị.
2. Ghi config.
3. `config.touch()`.
4. Nếu là tham số ảnh hưởng controller: `mode_flick.reset(self.tracker, is_sec=...)`.
5. Cập nhật readout (không rebuild cả tab).

**Bắt buộc sửa kèm (C14):** `mode_flick._get_controller()` phải truyền **đầy đủ** `settle_ms` và `switch_radius_px` trong `controller.configure(...)`; nếu không, slider Settle/Switch trên UI sẽ ghi config nhưng controller cũ vẫn giữ giá trị cũ cho tới khi bị tạo lại. Thêm test `test_configure_propagates_settle_and_switch_radius` để chặn hồi quy.

`_sync_config_to_tracker()` bổ sung:
```python
self.tracker.flick_status = getattr(self.tracker, "flick_status", {})
self.tracker.flick_engine = config.flick_engine
self.tracker.flick_settle_ms = config.flick_settle_ms
self.tracker.flick_settle_ms_sec = config.flick_settle_ms_sec
# ... các key mới
```
(không bắt buộc cho controller nếu dùng snapshot, nhưng giữ cho test/mock và debug.)

### 4.4. Chẩn đoán trực tiếp

`FlickController` đã có `FlickState`. Bổ sung publish trong `mode_flick.apply`:

```python
tracker.flick_status = {
    "main": {
        "reason": step.reason,
        "iterations": step.iterations,
        "counts": step.counts,
        "error_px": step.error_px,
        "residual": step.residual,
        "clamped": step.clamped,
        "armed": step.armed,
        "calibration": controller.calibration.source if controller.calibration else "none",
        "gain": controller.gain,
    },
    "sec": {...},
}
```
Chỉ publish khi `config.flick_telemetry_enabled` hoặc tab Flick V2 đang mở (tránh cấp phát dict mỗi frame khi không cần). UI đọc 250 ms/lần.

### 4.5. i18n, theme, accessibility

- Thêm key vào `locales/vi.json`, `locales/zh-CN.json`, `locales/en.json` (en có thể để rỗng vì fallback = key):
  `Flick V2`, `Settle Delay (ms)`, `Convergence Budget (ms)`, `Target Switch Radius (px)`, `Calibration — Valorant`, `Valorant preset`, `Measured`, `Analytic`, `Apply Valorant scale`, `Send test impulse`, `Fit & save`, `Effective steps`, `Settle ≥ Budget`.
- Màu: dùng token hiện có (`COLOR_ACCENT`, `COLOR_WARNING`, `COLOR_DANGER`); badge xanh cho `VALORANT`, cyan cho `MEASURED`, xám cho `ANALYTIC`.
- Không dùng emoji mới ngoài bộ hiện có; giữ font `Segoe UI`/`Consolas`.
- Tooltip dùng `_create_tooltip` sẵn có; không tạo cửa sổ mới mỗi hover (đã có).
- Tab phải hoạt động ở cả `Simple` và `Pro`; advanced section mặc định đóng ở Simple.

---

## 5. ĐẶC TẢ CALIBRATION VALORANT

### 5.1. Ba nguồn, một thứ tự ưu tiên

| Source | Công thức | Khi dùng | Persist |
|---|---|---|---|
| `valorant` | `counts_per_deg = 1 / (0.07 × sens)` | Người chơi Valorant, chưa đo; preset chuẩn | `valorant_deg_per_count`, `calibration_source`, `valorant_sens_at_calibration` |
| `measured` | `counts_per_deg = slope_px_to_counts / deg_per_px` | Người dùng đo bằng impulse + shift | `counts_per_deg_x/y`, `calibration_r2`, `calibration_samples`, `calibration_sens_at_measurement` |
| `analytic` | `1 / deg_per_count` từ `cm_per_rev`, `dpi`, `sens` | Legacy / game khác; có cảnh báo “54.54 chưa xác thực” | `cm_per_rev`, `sens`, `dpi` |

**Quy tắc:**
- `calibration_source` là **tường minh**; không suy đoán mỗi lần resolve.
- `valorant` **tính động** theo `in_game_sens`: đổi sens → scale đổi ngay, không cần restart.
- `measured` **không** tự đổi theo sens; nếu sens hiện tại lệch sens lúc đo > 2% → banner vàng “Sens đã đổi, hãy đo lại”.
- `analytic` dùng `cm_per_rev` (54.54) và bị đánh dấu `LEGACY` trong UI; không được quảng bá là “chuẩn”.
- Khi `measured` có đủ cặp và R² ≥ 0.99 và samples ≥ 5 → được ưu tiên nếu người dùng chọn; không tự ghi đè preset.

### 5.2. Công thức & ví dụ số

Với Valorant, góc yaw trên mỗi count tại sens 1.0 là `0.07°`:

```
deg_per_count(sens) = 0.07 × sens
counts_per_deg(sens) = 1 / (0.07 × sens)
```

| Sens | counts/deg | cm/360 @ DPI 1100 |
|---|---|---|
| 0.10 | 142.857 | 118.75 cm |
| 0.23 | **62.112** | **51.63 cm** |
| 0.235 | 60.790 | 50.53 cm |
| 0.40 | 35.714 | 29.69 cm |

Kiểm tra chéo cm/360:

```
counts_360 = cm_360 × dpi / 2.54
counts_per_deg = counts_360 / 360
cm_360 = 360 / (0.07 × sens) / (dpi / 2.54)
```

Tại sens 0.23, DPI 1100: `counts_360 = 22 360.25`, `cm_360 = 51.63 cm`.
**Đối chiếu:** hằng số legacy `54.54 cm/rev` cho ra `285.28 counts/deg` — lệch `4.594×` so với preset Valorant. Đây là lý do calibration phải có nguồn gốc, không được trộn hai mô hình.

Ví dụ hình học 1920×1080, hFOV 103°:

```
focal_x = 960 / tan(51.5°) = 763.62 px
góc của 30 px = atan(30 / 763.62) = 2.2502°
counts = 2.2502 × 62.112 = 139.77 counts
```

So với legacy: `2.2502 × 285.28 = 642.0 counts` → `4.594×`. Đây là con số phải hiển thị trong tooltip “30 px ≈ 139.8 counts” để người dùng tự thấy preset hoạt động đúng.

### 5.3. Bố cục card Calibration

```
┌ Calibration — Valorant ──────────────────────────────────────────────────────┐
│ Nguồn:  (•) Valorant preset   ( ) Đo thực   ( ) Analytic (legacy)            │
│                                                                              │
│ [Valorant]                                                                    │
│   In-game Sens [0.230]   DPI [1100]   Yaw chuẩn [0.070 °/count @ sens 1.0]   │
│   → 62.112 counts/deg · 51.63 cm/360 · 30 px ≈ 139.8 counts                  │
│   [Apply Valorant scale]                                                     │
│                                                                              │
│ [Measured]                                                                    │
│   Impulse counts [100]  Axis [X ▾]  [Send test impulse]                      │
│   Measured shift (px, signed) [12.4]  [Record sample]                        │
│   Samples: x=0/5  y=0/5   R²: --   [Fit & save]  [Clear]                     │
│                                                                              │
│ [Analytic legacy]                                                             │
│   hFOV [103.0]  cm/rev [54.54]  Sens [0.230]  DPI [1100]                     │
│   ⚠ 54.54 cm/rev chưa được xác thực; chỉ dùng khi không có preset/đo.        │
│                                                                              │
│ Geometry: 1920×1080 · hFOV 103.00° · focal 763.62 px · 0.0750°/px · native   │
│ Source=VALORANT · Updated=-- · Samples=0 · R²=--                             │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 5.4. Quy trình đo thực (Measured)

1. Chọn `Measured`; tạm khoá aimbot (cờ `calibration_session`) để không có lệnh `track`/`flick` chen vào.
2. Chọn trục X hoặc Y; nhập số counts (ví dụ 100); bấm `Send test impulse`.
3. Đo dịch chuyển tâm ngắm trên frame hiện tại **có dấu** (phải = +, trái = −); nhập `Measured shift (px, signed)`.
4. Lặp tối thiểu **5 điểm/trục**, trải đều 4 hướng; bấm `Record sample`.
5. `Fit & save`:
   - Fit riêng từng trục bằng `fit_calibration(samples, min_r2=0.99)`.
   - **Bắt buộc cả X và Y**; không ngoại suy trục thiếu.
   - Nếu R² < 0.99 hoặc < 5 mẫu/trục → từ chối, hiện lý do, không ghi config.
   - Ghi `counts_per_deg_x/y`, `calibration_r2 = min(r2_x, r2_y)`, `calibration_samples = tổng`, `calibration_source="measured"`, `calibration_sens_at_measurement = sens`.
6. Sau khi lưu: reset `FlickController` cả 2 kênh; refresh readout; log tóm tắt.

**Sửa lỗi hiện tại:** `record_sample` dùng `abs()` (`ui.py:5337`) làm mất dấu; đổi sang signed. `_on_calibration_fit` (`ui.py:5377-5386`) đang ngoại suy trục thiếu; bỏ.

### 5.5. Preset Valorant

- Nút `Apply Valorant scale`:
  - Đọc `in_game_sens` (0.05–5.0), `mouse_dpi` (1–32000), `valorant_deg_per_count` (0.01–0.2).
  - Tính `cpd = 1/(0.07*sens)`.
  - Ghi `counts_per_deg_x = counts_per_deg_y = cpd`, `calibration_source="valorant"`, `calibration_r2=0.0`, `calibration_samples=0`, `valorant_sens_at_calibration=sens`, `calibration_updated_at=ISO8601`.
  - Reset controller; refresh; log `[Calibration] Valorant preset applied: 62.112 c/deg @ sens 0.230`.
- Khi người dùng đổi sens và source=valorant:
  - `resolve_calibration` tự tính lại (không cần bấm lại).
  - UI hiển thị “Preset tự động cập nhật theo sens”; nếu muốn cố định, chuyển sang `Measured`.
- Cảnh báo nếu `abs(cpd_measured / cpd_valorant - 1) > 0.20` khi đang measured: “Lệch >20% so với preset Valorant; kiểm tra lại phép đo.”

### 5.6. Hình học hiển thị

`resolve_geometry()` trả `FrameGeometry`; UI hiển thị:
- `frame_w × frame_h` (frame thật đưa vào detector).
- `hfov_deg`, `vfov_deg` (sau crop).
- `focal_x`, `focal_y`.
- `deg_per_px_at_center()`.
- `source` (`native` / `crop`) + crop info nếu có (`udp_fov`, `ndi_fov`, `capture_range_*`).

Mục đích: người dùng thấy ngay “tôi đang crop 216×216 từ 1920×1080” và hiểu vì sao `°/px` lớn hơn. Không cần mở config.

### 5.7. Migration của `counts_per_deg = 62.11` hiện tại

Config hiện tại có `62.11` nhưng `samples=0`, `r2=0`. Khi nâng schema 3:

```
if both counts > 0:
    valorant = 1 / (0.07 * sens)
    if abs(counts / valorant - 1) <= 0.01:
        source = "valorant"
        # giữ counts, samples=0, r2=0; UI hiển thị PRESET, không MEASURED
    elif samples >= 5 and r2 >= 0.99:
        source = "measured"
    else:
        source = "analytic"
        counts = 0  # quay về analytic, WARN rõ
elif ...
    source = "analytic" (config cũ) hoặc "valorant" (fresh default)
```

Với `62.11` @ sens 0.23 → khớp preset trong 0.01% → `valorant`. Với config legacy `285.28`, samples=0 → `analytic` + WARN “giá trị cũ không có nguồn gốc; hãy chạy calibration”. Không âm thầm coi là measured.

---

## 6. PHIÊN BẢN v2.1.0 — THIẾT KẾ MỘT NGUỒN

### 6.1. `src/version.py` (MỚI)

API thuần stdlib, không import UI/network:

```python
VERSION_FALLBACK = "2.1.0"
CODENAME_FALLBACK = "Flick V2"

@dataclass(frozen=True)
class VersionInfo:
    version: str
    release_date: str
    codename: str
    schema: int
    changelog: str

def load_version_info(refresh: bool = False) -> VersionInfo: ...
def get_version() -> str: ...
def get_version_label() -> str:          # "v2.1.0 PRO"
def get_engine_badge() -> str:           # "v2.1.0 · Flick V2"
def get_changelog() -> str: ...
```

- Đọc `version.json` tại project root; cache theo `(mtime, size)`; lỗi parse → fallback + `log_print` một lần.
- Validate semver bằng regex; `schema` int; `codename` string.
- `updater.py` dùng `load_version_info().version` thay vì tự mở file; giữ `get_current_version()` để không vỡ API.
- Không để `version.py` import `src.ui` hoặc `customtkinter`.

### 6.2. `version.json` đích

```json
{
    "version": "2.1.0",
    "release_date": "2026-11-09",
    "codename": "Flick V2",
    "schema": 3,
    "changelog": "v2.1.0 — Flick V2 Complete UI & Valorant Calibration\n\n- Flick V2 tab: Gain, Settle Delay, Max Counts, Budget, Iterations, Deadzone, Switch Radius for Main and Sec.\n- Valorant calibration: 0.07 deg/count preset, cm/360 cross-check, measured fit with provenance (source, samples, R2).\n- Performance: preview throttling, anti-smoke cache, UI scheduler gating, debug log incremental, geometry/calibration cache, per-tag move queue dispatch.\n- Fixes: calibration impulse isolation, flick rollback timing, duplicate config load, stale debug widget, settle/budget validation.\n- Cleanup: removed dead Magnet Trigger UI and unused UI builders; unified version across title, badge, README and changelog."
}
```

`release_date` chốt tại thời điểm phát hành; `changelog` có thể dùng `\n` để `UpdateDialog` format.

### 6.3. Các điểm gắn phiên bản

| File | Thay đổi |
|---|---|
| `src/ui.py:321` | `self.title(f"CVM colorBot {get_version_label()}")`; gọi sau khi import helper, trước `_build_layout` |
| `src/ui.py:523-530` | `self.version_lbl` dùng `get_version_label()` |
| `src/ui.py:4981` | `badge_text=get_engine_badge()` |
| `src/ui.py` (tab Telemetry/Profiles) | Thêm dòng `Version: v2.1.0 · Flick V2` + nút `Changelog` mở `UpdateDialog` với `get_changelog()` (P2) |
| `main.py:13` | `myappid = "mycompany.colorbot"` (ID ổn định, không version) |
| `main.py:1162` | In `v{get_version()} ({codename})` |
| `src/utils/updater.py:35-47` | Dùng `load_version_info()`; fallback giữ nguyên |
| `README.md:13` | `version-2.1.0--PRO`; thêm mục Flick V2/Calibration |
| `CHANGELOG.md` | Thêm `## [v2.1.0] - 2026-11-09 ("Flick V2 UI & Valorant Calibration")` lên đầu |
| `tests/test_version.py` | Assert đồng bộ tất cả điểm trên |

**Không đổi:** các mục lịch sử `v2.0.0`, `v1.2.1` trong CHANGELOG; badge README lịch sử nếu có.

### 6.4. Nội dung CHANGELOG v2.1.0 (dàn ý)

- **Flick V2 UI**: tab riêng; đủ 7 tham số/kênh; derived effective steps; diagnostics; reset state.
- **Calibration Valorant**: preset 0.07°/count; cm/360; measured fit 5 điểm/trục, R² ≥ 0.99; provenance; auto-recalc theo sens.
- **Hiệu năng**: preview ≤ 30 FPS; anti-smoke cache; UI scheduler; debug log incremental; geometry/calibration cache; queue theo tag.
- **Sửa lỗi**: calibration impulse độc quyền; rollback timing; settle/budget warning; load config một lần; widget debug stale; draw ROI vô điều kiện.
- **Dọn dẹp**: ~450 dòng UI chết; import thừa; `Magnet Trigger` UI chết; hằng số không dùng.
- **Nâng cấp**: schema 3; migration `calibration_source`; preset profiles cập nhật.

---

## 7. KẾ HOẠCH TỐI ƯU HIỆU NĂNG CHI TIẾT

### 7.1. Mục tiêu đo được

| Chỉ số | Hiện tại (ước tính tĩnh) | Mục tiêu |
|---|---|---|
| `track_once` p95 @ 640×360 | 3–6 ms | ≤ 4.5 ms |
| `track_once` p95 @ 1280×720 | 6–12 ms | ≤ 8 ms |
| Callback UI dài nhất | 2–10 ms (H1) | ≤ 3 ms |
| CPU UI khi idle | 3–8% | < 2% |
| Queue latency p95 | 1–5 ms | ≤ 3 ms |
| Tăng trưởng bộ nhớ 10 phút | chưa đo | < 5% |
| Số lệnh `controller.move`/frame | 1 (gộp sai) | 1–3 theo tag, không cộng chéo |

Đo bằng `tools/bench_track_once.py` (MỚI): frame tổng hợp 640×360/1280×720, capture giả, detection thật, 500 vòng, xuất p50/p95/p99; chạy trên máy đích, không chạy trong CI.

### 7.2. Bảng hành động

| ID | File / dòng | Thay đổi thiết kế | Kỳ vọng | Rủi ro | Test |
|---|---|---|---|---|---|
| H1 | `ui.py:9529-9558`, `8831-8832`, `995-998` | Cache `_last_runtime_lock_state`; chỉ gọi `_apply_runtime_settings_lock()` khi trạng thái đổi; `_refresh_capture_entry_card()` chỉ cập nhật nhãn, không đệ quy | Bỏ 2-10 ms/500 ms | Thấp | UI test: gọi 2 lần, đếm số lần duyệt widget = 1 |
| H2 | `ui.py:1476-1488`, `10620-10674` | Xoá attribute widget khi `_clear_content`; `_update_debug_log` kiểm tra `winfo_exists` + tab + `get_log_version()`; chỉ format khi version đổi; chèn incremental thay vì rebuild toàn bộ | Giảm ~90% công việc 10 Hz | Thấp | Test: rời tab, không format; log mới chỉ append |
| H3 | `main.py:591-598`, `714-738` | `PreviewScheduler`: tối đa `ui_preview_max_fps` (30); chỉ copy khi cần vẽ; một `cv2.waitKey(1)`/frame; tái sử dụng buffer; tắt hẳn khi `show_opencv_windows=False` | Giảm 60-80% chi phí preview | Trung bình (thay đổi hình ảnh) | Manual + đếm call qua mock |
| H4 | `main.py:510-528` | Tính `nearest_bbox` một lần/frame; cache kết quả `is_bbox_plausible` theo `(bbox, detector_version, mask_version)`; nếu cả 2 detector tắt → bỏ qua ngay; dùng lưới ô để tìm nearest | Giảm 2-4× khi bật | Trung bình | Unit test với mock detector đếm call |
| H5 | `main.py:180-256` | Tách `_group_move_items(pending)` thuần; dispatch từng tag; `calib` độc quyền; không cộng chéo; delay lấy min trong tag; sleep một lần cuối tick | Đúng đắn + ít cấp phát | **Cao** (ảnh hưởng mọi mode) | `tests/test_move_queue.py` |
| H6 | `mode_flick.py:43-65` | `FlickTuning.signature()`; chỉ `configure()` khi signature đổi; geometry/calibration lấy từ cache | Bỏ 20-50 µs/frame | Thấp | Test configure call count |
| H7 | `aim_math.py:300-409`, `506-537` | `@lru_cache`/dict cache theo signature `(frame_w, frame_h, hfov, vfov, crop..., sens, dpi, source, counts)`; `resolve_calibration` tôn trọng `calibration_source`; `valorant` tính động | Bỏ trig/dataclass lặp | Thấp | `tests/test_aim_math_cache.py` |
| H8 | `normal.py:950-972` | `get_mode_caps` một lần/frame cho mỗi kênh; truyền caps vào nhánh; cache theo `(mode,)` | Nhỏ nhưng sạch | Thấp | Existing tests |
| H9 | `main.py:955-1020` | Chỉ vẽ ROI khi `show_detection`; thay `np.where + median` bằng histogram cột (`np.count_nonzero` theo trục) hoặc `cv2.reduce`; giới hạn ROI upper 35% | 0.1-0.5 ms/target | Trung bình (sai lệch median) | So sánh output với thuật toán cũ trên ảnh mẫu |
| H10 | `ui.py:9560-9631` | Cache chuỗi label; chỉ `configure` khi khác; gộp nhánh NDI/CaptureCard | Nhỏ | Thấp | UI test |
| H11 | `ui.py:454-461` | Một `_ui_tick` thay 6 timer; tạm dừng khi minimize; khoảng 100/250/500/1200 ms | Giảm tải Tk | Trung bình | Manual + test scheduler |
| H12 | `main.py:1134`, `1154` | Load config **một lần** trước `AimTracker`; bỏ lần thứ hai; `ViewerApp` chỉ `_sync_config_to_tracker()` | Startup nhanh, nhất quán | Thấp | Startup test |
| H13 | `debug_logger.py:194-205` | `log_move` chỉ ghi khi `flick_telemetry_enabled` hoặc `debug_move_logging`; thêm `log_version` tăng mỗi entry | Giảm 300-400 entry/s | Thấp | Test counter |
| H14 | `main.py:620-730` | Snapshot `config` một lần/frame (`DetectionTuning`) thay `getattr` rải rác | Nhỏ | Thấp | Existing tests |
| H15 | `ui.py:10116-10134` | Chỉ rebuild card Tuning thay vì cả tab; hoặc giữ rebuild nhưng hoãn bằng `after_idle` | Giảm giật 50-150 ms | Trung bình | UI test |

### 7.3. Thiết kế cache hình học/calibration

```python
# src/aim_system/aim_math.py
_GEOMETRY_CACHE: dict[tuple, FrameGeometry] = {}
_CALIB_CACHE: dict[tuple, Calibration] = {}

def geometry_signature(frame_w, frame_h, cfg, capture) -> tuple: ...
def resolve_geometry_cached(...) -> FrameGeometry: ...
def resolve_calibration_cached(cfg) -> Calibration: ...
```

- Key gồm mọi input ảnh hưởng: frame size, `hfov_deg`, `vfov_deg`, `capture_mode`, cờ FOV + giá trị, `capture_range_*`, `capture_width/height`.
- Calibration key: `calibration_source`, `counts_per_deg_x/y`, `sens`, `dpi`, `cm_per_rev`, `valorant_deg_per_count`.
- Giới hạn cache 32 entry (LRU) để tránh rò rỉ khi người dùng kéo slider liên tục.
- Public API `resolve_geometry()` giữ nguyên; thêm `cached=True` mặc định; test tắt cache khi cần.

### 7.4. Thiết kế queue theo tag

```python
def _group_move_items(pending):
    groups = {}  # tag -> [items], giữ thứ tự xuất hiện
    for item in pending:
        dx, dy, delay, tag = item
        groups.setdefault(tag, []).append((dx, dy, delay))
    return groups

def _dispatch_groups(groups, max_batch):
    # 1. calib: độc quyền, gửi đúng một lần, không cộng gì khác
    # 2. flick: giữ nguyên từng xung, không cắt, không gộp với track
    # 3. track: gộp trong tag, giữ tối đa max_batch
    # 4. rcs: giữ nhịp, tối đa max_batch
    # Mỗi nhóm gọi controller.move(riêng); delay = min trong nhóm; sleep một lần cuối
```

Quy tắc:
- `calib` có mặt → **chỉ gửi `calib`**. Vì các item đã bị pop khỏi `queue.Queue`, không thể “đẩy lại đầu hàng”; do đó:
  - Bật cờ `calibration_session` **trước khi** gửi impulse để pipeline aim không sinh lệnh mới;
  - Các item không phải `calib` bị **drop có log** (`[MoveQueue] dropped N non-calib items during calibration`);
  - Tắt cờ sau khi người dùng `Record sample` hoặc `Cancel`, không tự hết hạn ngầm.
- `flick` có mặt → gửi flick trước, track sau; không cộng.
- `rcs` không bao giờ gộp vào flick/track.
- Thêm cờ rollback `move_queue_per_tag_dispatch` (mặc định True) để quay lại hành vi cũ nếu cần.

### 7.5. UI scheduler

```python
def _ui_tick(self):
    now = perf_counter()
    if not self._is_ui_visible():          # iconic / withdrawn
        self.after(500, self._ui_tick); return
    if now - self._last_source_tick >= 0.10: ...
    if now - self._last_telemetry_tick >= 0.25: ...
    if now - self._last_status_tick >= 0.50: ...
    if now - self._last_clipboard_tick >= 1.20: ...
    self.after(100, self._ui_tick)
```

Chỉ tick phần đang hiển thị; không format log khi tab Telemetry không mở.

---

## 8. KẾ HOẠCH LÀM SẠCH MÃ

### 8.1. Ứng viên xoá (đã grep xác nhận không có call-site)

| Vị trí | Nội dung | Bằng chứng | Hành động |
|---|---|---|---|
| `ui.py:17` | `from functools import partial` | Không dùng `partial` trong file | Xoá import |
| `ui.py:27` | `ModernSlider` trong import | Chỉ test `ui_components` dùng; `ui.py` không | Bỏ khỏi import |
| `ui.py:157` | `COLOR_HARDWARE_PANEL` | Chỉ định nghĩa; bản `_BORDER` mới được dùng | Xoá hằng |
| `ui.py:373` | `self.current_frame = None` | Không đọc | Xoá |
| `ui.py:5624-5977` | Hàm `_show_tb_tab`: 2 dòng đầu redirect rồi `return`; toàn bộ thân sau **không bao giờ chạy** | `5626-5627` return ngay; các callback `_on_trigger_*` chỉ còn được gọi từ block chết | Xoá ~350 dòng chết; giữ hàm redirect; rà lại các callback mồ côi (`_on_enabletb_changed`, `_on_trigger_type_selected`, `_on_trigger_activation_type_selected`, `_on_trigger_strafe_mode_selected`) |
| `ui.py:6338-6339` | `_add_subtitle` | Không call-site | Xoá |
| `ui.py:6597-6598` | `_add_spacer` | Không call-site | Xoá |
| `ui.py:6600-6614` | `_add_switch` (ViewerApp) | Không call-site; `_add_switch_in_frame` mới được dùng | Xoá |
| `ui.py:6616-6662` | `_add_slider` | Không call-site | Xoá |
| `ui.py:6677-6688` | `_add_range_slider` | Không call-site; `_add_range_slider_in_frame` dùng `_to_parent` | Xoá wrapper |
| `ui.py:6957-6971` | `_add_option_row` | Không call-site | Xoá |
| `main.py:133` | `_move_batch_small_step` | Không đọc | Xoá |
| `flick_controller.py:59` | `MIN_STEP_COUNTS` | Không dùng | Xoá |
| `flick_controller.py:156-157` | `FlickStep.as_tuple` | Không call-site | Xoá |
| `normal.py:229-236` | `_flush_move_queue` | Không call-site | Xoá |
| `ui_tabs/magnet_trigger_tab.py` | Toàn bộ file | Không import; tab redirect | Xoá file; giữ backend `MagnetTrigger.py` |
| `ui.py:883`, `913`, `1536` | Mục nav + alias + refresh map `Magnet Trigger` | Tab không tồn tại | Bỏ khỏi legacy nav + refresh map; giữ shim `_show_magnet_trigger_tab` 1 release |

**Giữ lại có chủ đích:**
- `_create_nav_btn_legacy` (dùng cho theme `classic`).
- `_toggle_theme`, `_toggle_ui_style` (dùng ở sidebar).
- `calculate_exact_counts`, `calculate_movement`, `flick_strength_*`, `sec_flick_cooldown_ms` (shim migration; xoá ở v2.2/v3).
- `mode_*.py` shim (ranh giới dispatcher).
- `ModernSlider` trong `ui_components.py` (public component, test dùng).

### 8.2. Chuẩn hoá nhỏ

- `ui.py:321` title; `:4981` badge; `:5013-5029`/`:5573-5589` thay bằng builder.
- Gộp `on_flick_*` trùng lặp thành helper `_bind_flick_channel(is_sec)`.
- `ui_tabs/__init__.py` export `build_flick_v2_tab`, `build_flick_panel`, `build_flick_calibration_card`.
- Không mass-reencode các chuỗi mojibake hiện có; chỉ sửa block được chạm.

---

## 9. PHÂN RÃ FILE CẦN SỬA / TẠO / XOÁ

### 9.1. Tạo mới

| File | Nội dung | Ưu tiên |
|---|---|---|
| `src/version.py` | `VersionInfo`, `load_version_info`, `get_version_label`, `get_engine_badge`, `get_changelog`; cache theo mtime | P0 |
| `src/aim_system/tuning.py` | `FlickTuning` immutable, `snapshot_flick_tuning(config, is_sec)`, `signature()` | P1 |
| `src/ui_tabs/common.py` | `FLICK_SLIDER_SPECS`, helper format/validation, base builder | P0 |
| `src/ui_tabs/flick_tab.py` | `build_flick_panel(app, parent, is_sec)`, `build_flick_v2_tab(app)`, diagnostics | P0 |
| `src/ui_tabs/calibration_tab.py` | `build_flick_calibration_card(app, parent)`, 3 mode, preset Valorant, measured workflow | P0 |
| `tools/bench_track_once.py` | Benchmark p50/p95/p99 cho `track_once` | P2 |
| `tests/test_version.py` | Đồng bộ phiên bản | P0 |
| `tests/test_flick_ui.py` | Sự hiện diện control, callback, validation, calibration preset | P0 |
| `tests/test_flick_config.py` | Schema/migration/provenance/clamp/roundtrip | P0 |
| `tests/test_move_queue.py` | Nhóm tag, calib độc quyền, không cộng chéo | P0 |
| `tests/test_aim_math_cache.py` | Cache & source-aware calibration | P1 |

### 9.2. Sửa

| File | Hành động cụ thể | Ưu tiên |
|---|---|---|
| `version.json` | 2.1.0, codename, schema 3, changelog mới | P0 |
| `CHANGELOG.md` | Thêm mục v2.1.0 lên đầu | P0 |
| `README.md` | Badge 2.1.0; mục Flick V2/Calibration; không sửa lịch sử | P1 |
| `main.py` | Title/version print; AppUserModelID ổn định; load config một lần; preview throttle; anti-smoke cache; `_group_move_items`; bỏ draw ROI vô điều kiện; bỏ `_move_batch_small_step` | P0 |
| `src/ui.py` | Title/badge động; gọi builder Flick/Calibration; thêm callback settle/switch/source; scheduler hợp nhất; xoá dead code; sửa stale debug widget; cache lock state | P0 |
| `src/ui_tabs/__init__.py` | Export builder mới; bỏ export/file magnet nếu xoá | P1 |
| `src/ui_tabs/magnet_trigger_tab.py` | **Xoá** (hoặc cập nhật nếu quyết định giữ tab; mặc định xoá) | P2 |
| `src/utils/config.py` | `calibration_source`, `valorant_deg_per_count`, `switch_radius`, `valorant_sens_at_calibration`, `calibration_updated_at`, `config_schema`, `ui_preview_max_fps`, `flick_telemetry_enabled`, `move_queue_per_tag_dispatch`; migration schema 3; validation; `touch()`/revision; `to_dict/from_dict` | P0 |
| `src/utils/updater.py` | Dùng `src.version`; giữ API | P1 |
| `src/aim_system/aim_math.py` | Cache geometry/calibration; `Calibration.source` thêm `valorant`; `resolve_calibration` tôn trọng source & tính động; `describe` rõ nguồn; giữ API cũ | P0 |
| `src/aim_system/flick_controller.py` | `switch_radius_px` từ config; rollback phục hồi timing/clamp; expose status; validate settle/budget; dọn unused | P0 |
| `src/aim_system/mode_flick.py` | Dùng `FlickTuning`; chỉ configure khi signature đổi; **truyền đủ `settle_ms` + `switch_radius_px`** (C14); publish status; reset đúng | P0 |
| `src/aim_system/normal.py` | `_dispatch_aimbot` nhận caps/snapshot; bỏ `_flush_move_queue`; legacy path đánh dấu deprecated; giữ shim | P1 |
| `src/aim_system/RCS.py` | Đảm bảo tag `rcs` không bị gộp; thêm telemetry nhịp | P2 |
| `src/aim_system/MagnetTrigger.py` | Cập nhật key Flick mới (`settle`, `switch_radius`) nếu tab được giữ; nếu xoá UI, vẫn đảm bảo context không lỗi | P2 |
| `src/aim_system/mode_dispatcher.py` | Thêm `get_mode_caps` cache; (tuỳ chọn) cap `uses_settle` | P2 |
| `src/utils/debug_logger.py` | `log_version`, gate `log_move` | P1 |
| `src/utils/detection.py` | (Tuỳ chọn P2) tránh `raw_mask.copy()` khi không cần; giữ hành vi | P2 |
| `src/capture/capture_service.py` | Chỉ đọc; thêm getter metadata crop/frame để UI hiển thị (không đổi logic) | P2 |
| `locales/vi.json`, `zh-CN.json`, `en.json` | Key mới | P1 |
| `tests/test_combat_tab.py` | Assert tab Flick V2/control mới; giữ test cũ | P1 |
| `tests/test_flick_controller.py` | Thêm rollback timing, settle, switch radius | P1 |
| `configs/*.json`, `config.json` | Thêm `calibration_source`, `settle`, `switch_radius`; cập nhật budget fresh; giữ giá trị người dùng | P1 |

### 9.3. Không sửa

- `src/capture/*` logic (chỉ đọc metadata).
- `src/utils/mouse/*` backend.
- `src/utils/detection.py` thuật toán HSV (trừ tối ưu copy nếu được duyệt).
- Lịch sử CHANGELOG cũ.
- `docs/superpowers/*` (tài liệu thiết kế cũ).

---

## 10. SCHEMA CONFIG & MIGRATION

### 10.1. Key mới/đổi

| Key | Kiểu | Mặc định | Clamp | Ghi chú |
|---|---|---|---|---|
| `config_schema` | int | 3 | — | Version schema, không phải app version |
| `calibration_source` | str | `"valorant"` (fresh) | enum | `valorant|measured|analytic` |
| `valorant_deg_per_count` | float | 0.07 | 0.01–0.2 | Yaw tại sens 1.0 |
| `valorant_sens_at_calibration` | float | 0.0 | 0–10 | Sens lúc áp preset |
| `calibration_updated_at` | str | `""` | — | ISO8601 |
| `flick_settle_ms` | float | 70 | 0–500 | Đã có, thêm UI |
| `flick_settle_ms_sec` | float | 70 | 0–500 | Đã có, thêm UI |
| `flick_switch_radius_px` | int | 64 | 16–256 | Mới |
| `flick_switch_radius_px_sec` | int | 64 | 16–256 | Mới |
| `flick_budget_ms` | float | 240 (fresh) | 40–1000 | Migrate giữ 120 |
| `flick_budget_ms_sec` | float | 240 (fresh) | 40–1000 | Migrate giữ 120 |
| `flick_telemetry_enabled` | bool | False | — | Publish status |
| `ui_preview_max_fps` | int | 30 | 1–144 | Throttle preview |
| `ui_pro_mode` | bool | False | — | Persist Pro/Simple (hiện bị thiếu trong schema) |
| `move_queue_per_tag_dispatch` | bool | True | — | Rollback flag |
| `calibration_samples` | int | 0 | 0–10000 | Đã có |
| `calibration_r2` | float | 0.0 | 0–1 | Đã có |

### 10.2. Migration schema 2 → 3

1. Nếu `calibration_source` thiếu:
   - Nếu cả `counts_per_deg_x/y` > 0:
     - `valorant = 1/(0.07*sens)`; nếu lệch ≤ 1% → `"valorant"`, giữ counts, **không** đổi `samples/r2`.
     - elif `samples ≥ 5` và `r2 ≥ 0.99` → `"measured"`.
     - else → `"analytic"`, đặt counts về 0, WARN.
   - Nếu không có counts → `"analytic"` cho config cũ; fresh default `"valorant"`.
2. Nếu `flick_settle_ms` thiếu → 70; `_sec` → 70.
3. Nếu `flick_budget_ms` thiếu:
   - Có `sec_flick_cooldown_ms` → map sang `flick_budget_ms_sec`.
   - Còn lại → 120 (giữ hành vi cũ), UI cảnh báo effective steps.
4. Nếu `flick_switch_radius_px` thiếu → 64.
5. `flick_engine` giữ `v2`; `aim_engine` giữ `legacy` (closed-loop A/B) trừ khi người dùng chọn.
6. Mirror alias `flick_strength_*`, `sec_flick_cooldown_ms` sau clamp.
7. Thêm `ui_pro_mode` vào `__init__`/`to_dict()` (mặc định False), sửa lỗi C13.
8. `config_schema = 3`.
9. Ghi log tóm tắt migration một lần, không spam mỗi frame.

### 10.3. `resolve_calibration` hành vi mới

```python
source = getattr(cfg, "calibration_source", "analytic")
if source == "valorant":
    cpd = 1.0 / (valorant_deg_per_count * sens)
    return Calibration(cpd, cpd, source="valorant", ...)
if source == "measured" and measured_pair_valid:
    return Calibration(measured_x, measured_y, source="measured", ...)
# analytic
return Calibration(sens=sens, dpi=dpi, cm_per_rev=cm_per_rev, source="analytic")
```

- `Calibration.is_measured` chỉ true với `source=="measured"`.
- `needs_recalibration_warning()`:
  - measured: sens lệch >2% hoặc R² <0.99.
  - valorant: sens ngoài 0.05–5.
  - analytic: luôn cảnh báo legacy.
- Test hiện tại `test_measured_wins_over_analytic` vẫn pass nếu cả pair được cung cấp; cập nhật test cho source.

---

## 11. THỨ TỰ THI CÔNG & ROLLBACK

| Bước | Nội dung | Phụ thuộc | Rollback |
|---|---|---|---|
| 0 | Tag/backup baseline; chạy test hiện có (khi shell hoạt động) | — | — |
| 1 | `src/version.py` + `version.json` 2.1.0 + `tests/test_version.py`; title/badge/README/CHANGELOG | — | Revert version files |
| 2 | Config schema 3 + migration + `calibration_source` + tests | 1 | Giữ key cũ; flag |
| 3 | `aim_math` cache + source-aware calibration + tests | 2 | Tắt cache bằng tham số |
| 4 | `flick_controller` rollback/settle/switch radius + tests | 2 | Giữ default cũ |
| 5 | `tuning.py` + `mode_flick` signature-based configure + status publish | 2,3,4 | `flick_engine=legacy` |
| 6 | `ui_tabs/flick_tab.py`, `calibration_tab.py`, `common.py`; wire `ui.py`; tests UI | 2,4,5 | Ẩn tab bằng `ui_flick_v2_enabled` |
| 7 | Queue per-tag dispatch + tests | 4 | `move_queue_per_tag_dispatch=False` |
| 8 | Hiệu năng UI (H1,H2,H11), preview (H3), anti-smoke (H4), head estimate (H9) | 6 | Từng patch độc lập |
| 9 | Dọn code chết; i18n; docs; cập nhật presets | 1,6 | Revert file |
| 10 | Full regression + benchmark + manual QA + release | tất cả | Tag rollback |

**Nguyên tắc:** mỗi bước có test riêng; không gộp bước 7 (queue) với bước 6 (UI) trong cùng commit để dễ khoanh vùng lỗi.

---

## 12. KẾ HOẠCH KIỂM CHỨNG

### 12.1. Lệnh (chạy khi shell hoạt động)

```powershell
.\venv\Scripts\python.exe -m compileall -q src main.py
.\venv\Scripts\python.exe -m unittest discover -s tests -v
.\venv\Scripts\python.exe -m unittest tests.test_version tests.test_flick_ui tests.test_flick_config tests.test_move_queue tests.test_aim_math tests.test_flick_controller -v
.\venv\Scripts\python.exe tools\bench_track_once.py --frames 500 --size 640x360
```

### 12.2. Test mới

| Test | Nội dung | Tiêu chí |
|---|---|---|
| `test_version.py` | `version.json` == title/badge/updater/changelog | Không còn `v2.0` trong code hiện hành |
| `test_flick_ui.py` | Tab Flick V2 tồn tại; đủ 7 slider/kênh; `flick_settle_ms` có mặt; callback ghi config; validation effective steps; preset Valorant cập nhật counts + source | Widget tồn tại, config đúng, không rebuild |
| `test_flick_config.py` | Fresh defaults; migrate 62.11 → valorant; migrate 285.28 → analytic + zero; measured cần samples/r2; settle clamp; roundtrip to_dict/from_dict | Tất cả assert |
| `test_move_queue.py` | `_group_move_items`; calib độc quyền; flick không cộng track; rcs giữ nhịp; max_batch | Không cross-tag sum |
| `test_aim_math_cache.py` | Cache hit/miss; đổi sens → valorant cpd đổi; measured không đổi; geometry crop | ±1e-9 |
| `test_flick_controller.py` (bổ sung) | Rollback phục hồi `_last_step_time`, `last_sent`, `total_sent`; settle chặn step; switch radius từ config; `configure(settle_ms=...)` có hiệu lực ngay | Pass |
| `test_ui_perf.py` (tuỳ chọn) | Gọi `_apply_runtime_settings_lock` 2 lần; đếm traversal | 1 lần |
| `test_head_estimate.py` (tuỳ chọn) | Preview tắt → không gọi `cv2.rectangle`; kết quả X/Y khớp thuật toán cũ trên fixture | Mock call count = 0 |

### 12.3. Ma trận QA thủ công

| Chiều | Giá trị |
|---|---|
| Độ phân giải | 1920×1080, 1280×720, 640×360, crop 216×216, crop 512×512 |
| Sens | 0.10, 0.23, 0.235, 0.40 |
| DPI | 400, 800, 1100, 1600 |
| Khoảng cách flick | 5, 15, 30, 60, 120 px |
| Settle | 0, 35, 70, 120 ms |
| Budget | 120, 240, 500 ms |
| Calibration | Valorant preset, measured 5×4, analytic legacy |
| Mode | Flick Main + Flick Sec; Flick + Normal; Flick + RCS |
| UI | Simple/Pro; theme nord/emerald/classic; language vi/en/zh |
| Runtime | start/stop; đổi mode khi chạy; đổi capture; minimize |
| Config | save/load/import/export; config cũ 2.0.0; preset 6 file |

**Tiêu chí Flick:**
- 30 px → ~139.8 counts @ sens 0.23, preset Valorant.
- Sau bước 1, overshoot ≤ 10%; hội tụ trong deadzone với ≤ 4 bước khi budget đủ.
- Settle 70 ms: không gửi bước 2 trước 70 ms.
- Đổi sens khi source=valorant: counts đổi ngay, không restart.
- Calib impulse: không có lệnh track/flick chen vào.

### 12.4. Benchmark

- `tools/bench_track_once.py` xuất CSV: frame size, p50/p95/p99, detection, draw, anti-smoke, total.
- So sánh trước/sau trên cùng máy; lưu `docs/perf/2026-11-09-v2.1.0.csv` (tạo trong bước thi công, không phải bây giờ).
- Không đưa benchmark vào CI (flaky); chỉ regression ngưỡng mềm.

---

## 13. RỦI RO & GIẢM THIỂU

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Queue per-tag làm thay đổi cảm giác aim mọi mode | Cao | Flag `move_queue_per_tag_dispatch`; test; A/B 1 ngày; rollback |
| Preset Valorant 0.07 sai với game/version khác | Trung bình | Chỉ áp khi người dùng chọn; measured luôn thắng; hiển thị nguồn |
| Tự tính lại theo sens làm người dùng bất ngờ | Trung bình | Chỉ với source=valorant; banner giải thích; measured bất biến |
| Settle cao làm giảm nhịp flick | Trung bình | Cảnh báo effective steps; mặc định 70; auto-fix |
| Xoá code chết làm vỡ script ngoài | Thấp | Giữ shim public 1 release; grep trước khi xoá |
| Đổi AppUserModelID gây icon taskbar trùng | Thấp | Dùng ID ổn định `mycompany.colorbot`; ghi chú Windows cache |
| UI test Tkinter brittle | Trung bình | Builder thuần + attribute ổn định; test không phụ thuộc pixel |
| Cache geometry stale khi đổi crop | Trung bình | Signature đầy đủ; test invalidate; giới hạn LRU |
| Thread safety config | Trung bình | Snapshot immutable/frame; UI chỉ ghi scalar; không lock hot path |
| Mojibake khi sửa UI | Thấp | Chỉ sửa block chạm; không mass re-encode |

---

## 14. TIÊU CHÍ HOÀN THÀNH (Definition of Done)

1. `version.json` = 2.1.0; title, badge, README, CHANGELOG, updater cùng 2.1.0; test version xanh.
2. Tab `Flick V2` tồn tại; Main/Sec đều có `Gain`, `Settle Delay`, `Max Counts`, `Budget`, `Iterations`, `Deadzone`; advanced `Switch Radius`; giá trị persist qua save/load.
3. Calibration có 3 nguồn; preset Valorant tính đúng 62.112 @ 0.23; measured bắt buộc 5 mẫu/trục + R² ≥ 0.99; provenance hiển thị đúng; đổi sens auto-update khi preset.
4. `Settle`/`Budget` có cảnh báo effective steps; không còn trường hợp UI hứa 4 bước nhưng budget chỉ cho 2 mà không nói.
5. Move queue không cộng chéo tag; calibration impulse độc quyền; test queue xanh.
6. Rollback flick phục hồi đúng timing/residual; `configure()` áp Settle/Switch ngay; test xanh.
7. Các điểm nóng H1–H5 được xử lý; benchmark p95 đạt mục tiêu; UI idle < 2% CPU (đo trên máy đích).
8. Dead code đã xoá; `compileall` sạch; không import thừa; `ui.py` giảm ≥ 400 dòng.
9. Toàn bộ test cũ + mới xanh; QA thủ công theo ma trận đạt.
10. Không thay đổi hành vi Normal/PID/NCAF/WindMouse/Bezier ngoài phạm vi đã nêu; RCS vẫn hoạt động.

---

## 15. PHỤ LỤC

### A. Công thức & hằng số

```
Valorant: deg_per_count = 0.07 * sens
          counts_per_deg = 1 / (0.07 * sens)
          cm_360 = 360 / (0.07 * sens) / (dpi / 2.54)
Analytic legacy: deg_per_count = 360 / ((54.54/sens) * (dpi/2.54))
Geometry: focal_x = (w/2) / tan(hfov/2)
          deg_x = atan2(dx, focal_x)
          counts_x = deg_x * counts_per_deg_x
```

### B. Đối chiếu nhanh

| Sens | Valorant c/deg | Legacy c/deg | Tỉ lệ |
|---|---|---|---|
| 0.23 | 62.112 | 285.28 | 4.594× |
| 0.235 | 60.790 | 279.20 | 4.593× |
| 0.40 | 35.714 | 164.04 | 4.593× |

### C. Quyết định cần chốt trong bước thi công

1. `flick_budget_ms` fresh default: **240 ms** (đề xuất) hay giữ 120 ms để không đổi cảm giác? Kế hoạch chọn 240 cho fresh, migrate giữ 120 + cảnh báo.
2. `calibration_source` fresh default: **valorant** (đề xuất) hay analytic? Kế hoạch chọn valorant vì sản phẩm nhắm Valorant; analytic vẫn chọn được.
3. Có giữ tab `Magnet Trigger` không? Kế hoạch chọn **không** (xoá UI chết), giữ backend.
4. Có giữ `flick_engine=legacy` trên UI advanced không? Kế hoạch chọn **có**, mặc định v2, để A/B và rollback.
5. AppUserModelID: **ổn định** `mycompany.colorbot`, không version.

### D. Liên hệ với kế hoạch trước

Kế hoạch trước đã xác lập: hai bộ quy đổi mâu thuẫn, gain 1.8, clamp 1000, cooldown 85 ms, smoother làm trễ, và kiến trúc `aim_math` + `FlickController`. Các điểm đó **đã được xử lý trong mã hiện tại**. Kế hoạch này không mở lại root cause; nó giải quyết lớp giao diện/phiên bản/hiệu năng còn thiếu và các lỗi đúng đắn mới phát hiện (C1–C14).

---

*Hết kế hoạch. Không có file mã nguồn nào bị thay đổi trong bước này; chỉ tài liệu kế hoạch được ghi.*
