# 01 — KẾ HOẠCH: Phân tích & Kiến trúc sửa lỗi "Flick bị lệch hoàn toàn"

**Trạng thái:** Chỉ đọc – phân tích – lập kế hoạch. **Không sửa một dòng code nào.**
**Phạm vi đọc:** `src/aim_system/normal.py`, `main.py`, `src/utils/config.py`, `config.json`, `src/aim_system/mode_*.py`, `mode_dispatcher.py`, `target_smoother.py`, `activation.py`, `RCS.py`, `MagnetTrigger.py`, `src/capture/capture_service.py`, `CaptureCard.py`, `OBS_UDP.py`, `src/utils/mouse/*`, `src/utils/detection.py`, `src/ui.py` (phần liên quan), `tests/*`.
**Phương pháp:** Phân tích tĩnh + tính toán số học tái lập được. Runtime verification được đưa vào kế hoạch kiểm chứng (mục 8), không thực hiện trong bước này.

> Lưu ý về môi trường: shell (`pwsh`) bị chặn trong phiên này (exit code `0xC0000142`), nên toàn bộ phân tích dựa trên đọc file trực tiếp. Mọi con số dưới đây đều ghi rõ công thức để có thể kiểm chứng lại độc lập.

---

## 1. KẾT LUẬN ĐIỀU TRA (Executive verdict)

> **Flick không hỏng vì "gain chưa đẹp". Flick hỏng vì nó là bộ điều khiển vòng hở (open-loop) đặt trên một tầng quy đổi đơn vị sai, lại bị ba cơ chế chặn ngẫu nhiên (clamp, cooldown, làm mượt EMA) biến mọi sai số thành sai số vĩnh viễn.**

Chuỗi nhân quả:

1. `normal.py` chứa **hai bộ quy đổi pixel→count mâu thuẫn và sai thứ nguyên**: `calculate_movement()` (dùng cho Normal/NCAF/Bezier/WindMouse) và `calculate_exact_counts()` (dùng cho Flick). Hai hàm này lệch nhau **~1.40×** ngay tại tâm màn hình với cùng giả thiết hình học.
2. Flick dùng `calculate_exact_counts()` — nhánh "đúng hình học" hơn — nhưng lại nhân thêm `flick_strength_x = 1.8` / `flick_strength_y = 0.55`, tức **gain vật lý bị thay bằng núm chỉnh cảm giác**. Gain đúng phải là `1.0`.
3. Ngay sau đó `_clip_movement()` cắt cứng ở `max_speed` — một biến **không hề tồn tại trong schema config**, luôn fallback `1000` (`main.py:101`). Với một cú flick 30 px, code yêu cầu ~642 count (đúng) → ×1.8 = ~1155 → **bị cắt còn 1000** → overshoot cố định **1.56×**.
4. Vì overshoot, tâm ngắm vượt qua đầu mục tiêu. `fovsize_sec = 30` → mục tiêu **rơi ra ngoài FOV** → frame sau không còn target → không có hiệu chỉnh.
5. Cơ chế đáng lẽ cứu được (frame kế tiếp) bị `sec_flick_cooldown_ms = 85` **chặn và huỷ** (không phải "hoãn rồi sửa" mà là `return` — bỏ luôn frame). Flick do đó **không thể hội tụ về mặt cấu trúc**.
6. Trước đó, `TargetSmoother` (`ema_alpha=0.35`, `switch_confirm_frames=3`) đã **làm trễ/méo vị trí mục tiêu** trước khi Flick tính cú đánh duy nhất. Flick ngắm vào chỗ mục tiêu *đã ở đó*, không phải chỗ *đang ở đó*.

**Hệ quả:** sai số **có hệ thống, cùng hướng, cùng độ lớn** ở mọi lần flick — đúng như mô tả "lệch hoàn toàn không nhắm vào mục tiêu". Đây là dấu hiệu kinh điển của lỗi **scale/đơn vị**, không phải lỗi "cảm giác".

**Vì sao chỉ Flick hỏng, các mode khác không?**
Normal/PID/NCAF/WindMouse/Bezier đều **vòng kín**: mỗi frame đo lại `(dx, dy)` và tiếp tục đẩy. Sai scale chỉ làm chúng **hội tụ chậm**, không làm **điểm dừng sai**. Flick là **vòng hở**: một xung duy nhất, không đo lại → sai scale trở thành **điểm dừng sai vĩnh viễn**. Đây là lý do kiến trúc, không phải lý do tham số.

---

## 2. BẰNG CHỨNG: HAI BỘ QUY ĐỔI MÂU THUẪN

### 2.1 `calculate_movement()` — sai thứ nguyên (dimensional error)

`src/aim_system/normal.py:123-145`

```python
count_per_cm  = dpi / 2.54
deg_per_count = 360.0 / (cm_per_rev * count_per_cm)
ndx = dx * deg_per_count        # ← dx là PIXEL, deg_per_count là ĐỘ/COUNT
ndy = dy * deg_per_count
```

`dx * (độ/count)` cho ra **độ**, nhưng biến được đặt tên `ndx` và được dùng như **count**. Không có focal length, không có `atan`, không có FOV. Đây là lỗi thứ nguyên thuần tuý.

Với `sens=0.23`, `dpi=1100`:
- `cm_per_rev = 54.54 / 0.23 = 237.13 cm`
- `counts_per_cm = 1100 / 2.54 = 433.07`
- `deg_per_count = 360 / (237.13 × 433.07) = 0.003505 °/count`
- `dx = 30 px` → `ndx = 30 × 0.003505 = 0.105` "count"

Tức 30 pixel được hiểu thành 0.105 count. Để bù, Normal phải có `normal_x_speed = 95`, `normalsmooth = 6`:

```python
ndx *= x_speed / smooth     # 0.105 × 95 / 6 = 1.665 count
```

→ ~2 count/frame cho sai số 30 px. **Normal "chạy được" chỉ vì nó lặp hàng trăm frame**, mỗi frame bò 2 count. Mọi núm `x_speed` / `y_speed` / `normalsmooth` trong repo là **hệ số bù cho lỗi thứ nguyên này**, không phải tham số điều khiển thực.

### 2.2 `calculate_exact_counts()` — đúng hình học nhưng hằng số chưa kiểm chứng

`src/aim_system/normal.py:105-120`

```python
fx = (screen_w/2) / tan(radians(fov_deg/2))
deg_x = degrees(atan2(dx, fx))
counts_x = deg_x / deg_per_count
```

Với `screen_w=1920`, `fov_deg=103` (mặc định, **không caller nào override**):
- `fx = 960 / tan(51.5°) = 960 / 1.25717 = 763.62`
- `°/px tại tâm = degrees(1/763.62) = 0.075031`

Nhưng nếu dùng mô hình tuyến tính ngây thơ `103/1920 = 0.053646 °/px`, hai mô hình lệch nhau:

```
0.075031 / 0.053646 = 1.3986  →  ~1.40×
```

**Kết luận 2.2:** trong cùng một file tồn tại **hai mô hình yaw không tương thích**, lệch ~1.40×. Bất kỳ mode nào "trông ổn" đều đang được bù bằng tay.

### 2.3 Hằng số `54.54` và `103.0` là magic number chưa xác thực

- `54.54` (cm/vòng) được hard-code, không có nguồn, không có test, không có UI hiệu chuẩn.
- `103.0` (FOV ngang) được hard-code làm **giá trị mặc định của tham số**, và mọi call-site đều gọi thiếu tham số → luôn dùng 1920/103.

Điểm chí mạng: **hằng số đúng của Valorant cho ra kết quả khác nhiều lần**. Nếu dùng giá trị phổ biến ~`0.07 °/count` tại sens 1.0 (co giãn theo sens → `0.07 × 0.23 = 0.0161 °/count`), thì 2.25° cần `139.8` count, trong khi code tính `641.9` count — **sai 4.59×**. Cộng thêm `strength 1.8` → **~8.3× overshoot**.

Dù chọn hằng số nào, kết luận không đổi: **overshoot rất lớn và có hệ thống**. Kế hoạch này **không** khẳng định một hằng số cụ thể là đúng — nó yêu cầu **đo bằng thực nghiệm** (mục 5.4, 8.3) để loại bỏ hoàn toàn magic number.

### 2.4 Hình học frame thực ≠ hình học giả định

`main.py:509-513` dựng `FrameInfo(w, h)` từ **frame đã crop**, và tâm được tính `frame.xres/2`. Nhưng `calculate_exact_counts()` lại diễn giải các pixel đó như pixel của màn 1920 rộng, FOV 103°.

`capture_service.py:538-595` và `CaptureCard.py:373-402` cho thấy frame bị **crop giữa** với kích thước do người dùng đặt: `udp_fov = 108`, `capture_range_x/y = 256`. Khi crop bật, `°/px` thực thay đổi theo tỉ lệ **FOV_crop / FOV_native**, trong khi code vẫn dùng 1920/103.

→ **Đây là mismatch đơn vị không thể bù bằng bất kỳ một giá trị `strength` cố định nào**, vì nó đổi mỗi khi người dùng đổi capture mode / resolution / crop.

---

## 3. BẰNG CHỨNG: BA CƠ CHẾ BIẾN SAI SỐ THÀNH VĨNH VIỄN

### 3.1 Clamp `max_speed` — cắt cụt cú flick (nghiêm trọng nhất)

`main.py:101` → `self.max_speed = float(getattr(config, "max_speed", 1000.0))`
`grep` xác nhận **`max_speed` không tồn tại trong `config.py`** → luôn = `1000`.

`main.py:230-242`:
```python
clipped_dx = np.clip(dx, -abs(self.max_speed), abs(self.max_speed))
```

`normal.py:467`: `ddx, ddy = tracker._clip_movement(out_x, out_y)`

Tính toán cụ thể (giả thiết hình học như code, `sens=0.23`, `dpi=1100`, lỗi 30 px):

| Bước | Giá trị |
|---|---|
| `fx` | 763.62 |
| góc cần xoay | `atan2(30, 763.62)` = **2.2502°** |
| `deg_per_count` | 0.0035053 |
| count vật lý đúng | **641.9** |
| × `flick_strength_x` 1.8 | **1155.4** |
| sau `_clip_movement` (±1000) | **1000.0** |
| **overshoot** | **1000 / 641.9 = 1.558×** |

Với lỗi 30 px, tâm ngắm vượt mục tiêu `30 × 1.558 ≈ 47 px`. `fovsize_sec = 30` → **47 > 30 → mục tiêu ra khỏi FOV** → frame sau `targets_sec` rỗng → **không có hiệu chỉnh**. Đây chính là "vòng xoáy tử thần" khớp 100% với triệu chứng.

Đồng thời `normal.py:456`: `flick_max_step_counts` mặc định `999.0` và **cũng không có trong schema** → limiter "max step" thực chất **vô hiệu**, chỉ còn clamp 1000 của `max_speed` hoạt động.

### 3.2 Cooldown — bỏ frame thay vì hoãn rồi sửa

`normal.py:415-420`:
```python
if (now - last_flick_time) < cooldown_sec:
    return          # ← HUỶ frame, không lên lịch lại
```

Docstring tự nhận "matching the 71ms video pipeline latency", nhưng hành vi là **chặn mọi hiệu chỉnh trong 85 ms**. Trong 85 ms đó, các frame chứa **thông tin sửa sai** bị vứt. Open-loop + blind = không thể hội tụ.

Bất đối xứng: **nhánh Main không có cooldown**, chỉ nhánh Sec có (`normal.py:416-420`). Trong khi `config.json` đặt `mode_sec = "Flick"` → **đúng nhánh bị cooldown là nhánh đang dùng**.

### 3.3 `TargetSmoother` — làm trễ mục tiêu trước cú đánh duy nhất

`main.py:613-618`: smoother được áp **trước khi** tách main/sec:
```python
targets_all = self._target_smoother.stabilize(targets_all, ...)
targets_main = list(targets_all)
targets_sec  = list(targets_all)
```

`target_smoother.py:73-77`:
```python
smooth_x = last_x + alpha * (desired_x - last_x)   # alpha = 0.35
```
và `target_smoother.py:61-65`: khi đổi mục tiêu, trả về **vị trí cũ** cho tới khi đủ `switch_confirm_frames = 3`.

Với mode vòng kín, đây là "ổn định". Với Flick — nơi vị trí chỉ được đọc **một lần** — đây là **ngắm vào quá khứ**. Sai lệch ≈ `0.65 × |Δ|` mỗi frame trễ, cộng tối đa 3 frame giữ vị trí cũ.

### 3.4 Mất độ chính xác dưới 1 count ở nhánh Sec

`normal.py:432-433` (nhánh sec):
```python
qdx = int(round(ddx))
qdy = int(round(ddy))
```
**Không** dùng `_quantize_with_residual()` (chỉ nhánh main dùng, `normal.py:468`), và **không** có bước "nudge tối thiểu 1 count" (chỉ nhánh main có, `normal.py:469-473`).

→ Mọi sai số < 0.5 count bị **nuốt vĩnh viễn**, không bao giờ cộng dồn thành bước đi. Nhánh Sec/Flick **không bao giờ** sửa được sai số nhỏ.

### 3.5 Queue làm mất xung flick

`main.py:199-210` với `move_queue_merge_batch = 1` (config.json):
```python
if len(pending) > max_batch:
    pending = pending[-max_batch:]      # chỉ giữ 1 lệnh mới nhất
merged_dx = sum(...)                    # rồi cộng
```
Xung Flick có thể bị **lệnh khác (RCS/normal) ghi đè** trước khi được gửi. Thêm nữa `RCS._rcs_pull_loop` gọi `controller.move()` **trực tiếp**, bỏ qua queue → RCS và Flick có thể **đánh nhau** trên cùng trục Y.

### 3.6 (Tiềm ẩn) Zero hoá `dy` trong `process_normal_mode`

`normal.py:1001-1004`:
```python
if rcs_active: dy = 0
if check_y_release(): dy = 0
```
Hiện `enablercs = false`, `rcs_release_y_enabled = false` → chưa kích hoạt. Nhưng nếu bật, với Flick (một xung duy nhất), `dy = 0` = **lệch dọc chắc chắn**, và cooldown chặn luôn cơ hội sửa. Phải xử lý như một phần của kiến trúc, không để lại bẫy.

### 3.7 (Tiềm ẩn) Hai tầng offset chồng nhau

`_estimate_head_positions` cộng `offsetX/offsetY` (`main.py:896-899`, `923-924`), rồi `process_normal_mode` cộng tiếp `aim_offsetX_sec/aim_offsetY_sec` (`normal.py:992-993`). Hai stage độc lập, dễ double-apply. Hiện cả 4 giá trị = 0 nên trung tính, nhưng là nợ kiến trúc.

---

## 4. BẢNG KHUYẾT ĐIỂM & MỨC ĐỘ

| # | Khuyết điểm | Vị trí | Mức | Ảnh hưởng trực tiếp tới Flick |
|---|---|---|---|---|
| D1 | `calculate_movement` sai thứ nguyên (pixel × °/count) | `normal.py:123-145` | **P0** | Nền tảng sai; mọi "speed" là fudge |
| D2 | Hai mô hình yaw lệch ~1.40× trong cùng file | `normal.py:105-145` | **P0** | Không có chuẩn duy nhất |
| D3 | `54.54` / `103.0` hard-code, chưa xác thực | `normal.py:105-120` | **P0** | Sai scale nhiều lần |
| D4 | `strength` dùng như gain chính (1.8 / 0.55) | `normal.py:454-465`, `config.json:213-214` | **P0** | Overshoot cố định |
| D5 | Clamp `max_speed=1000` không có trong schema | `normal.py:467`, `main.py:101` | **P0** | Cắt cụt → overshoot 1.56× |
| D6 | Cooldown 85 ms `return` thay vì sửa | `normal.py:415-420` | **P0** | Không thể hội tụ |
| D7 | Smoother EMA áp trước Flick (open-loop) | `main.py:613-618`, `target_smoother.py` | **P0** | Ngắm vào vị trí cũ |
| D8 | `fovsize_sec=30` + overshoot → mất target | `config.json:224` | **P0** | Vòng xoáy không hiệu chỉnh |
| D9 | Nhánh Sec mất residual & nudge | `normal.py:432-433` | P1 | Sai số nhỏ vĩnh viễn |
| D10 | `flick_max_step_counts` default 999, không persist | `normal.py:456` | P1 | Limiter vô hiệu |
| D11 | Queue gộp `batch=1` có thể ghi đè xung | `main.py:199-210` | P1 | Mất lệnh |
| D12 | RCS move trực tiếp, bỏ queue | `RCS.py:30-58` | P1 | Tranh chấp trục |
| D13 | `dy=0` khi RCS/y-release | `normal.py:1001-1004` | P1 (latent) | Lệch dọc chắc chắn |
| D14 | Hai tầng offset | `main.py:896`, `normal.py:992` | P2 (latent) | Double-apply |
| D15 | `mode_*.py` chỉ là shim 4 dòng | `mode_*.py` | P2 | Không có ranh giới kiến trúc |
| D16 | Geometry hard-code 1920/103, bỏ qua crop | `normal.py:105` | **P0** | Sai khi crop/res đổi |

---

## 5. KIẾN TRÚC GIẢI PHÁP

### 5.1 Nguyên tắc thiết kế

1. **Một nguồn chân lý duy nhất cho quy đổi đơn vị.** Không mode nào được tự nhân hệ số bí mật.
2. **Gain vật lý = 1.0.** `strength` bị khai tử, thay bằng `gain` với ý nghĩa rõ ràng và mặc định 1.0 (đúng vật lý), không phải "cảm giác".
3. **Flick phải là vòng kín có ngân sách.** Vẫn "flick" (nhanh, dứt khoát) nhưng **tự sửa** trong `N` bước / `T` ms, thay vì một xung mù.
4. **Hình học lấy từ frame thật**, không hard-code.
5. **Không có cơ chế nào âm thầm cắt cụt hoặc huỷ lệnh.** Mọi giới hạn phải cấu hình được, có tên, có log.
6. **Tách "mode" thành module thật**, `normal.py` chỉ còn orchestration.

### 5.2 Sơ đồ luồng mới

```
track_once()  [main.py]
  ├─ detect → targets (pixel, frame thật)
  ├─ TargetSmoother  ── CHỈ áp cho mode khai báo closed_loop_tracking
  │                      (Flick: BYPASS)
  ├─ process_normal_mode()  [normal.py — orchestration only]
  │    ├─ activation (activation.py)
  │    ├─ chọn target + offset (một tầng duy nhất)
  │    ├─ resolve_geometry(frame)  ──► FrameGeometry
  │    └─ dispatch(mode)  [mode_dispatcher.py]
  │         └─ FlickController.step(error_px, geometry, state)
  │              ├─ px_to_counts()  [aim_math.py — DUY NHẤT]
  │              ├─ gain (1.0) × error → counts
  │              ├─ clamp theo ngân sách CẤU HÌNH ĐƯỢC
  │              ├─ residual carry (cả main & sec)
  │              └─ lặp tới khi |error| ≤ deadzone HOẶC hết budget
  └─ move_queue  (tag: "flick" | "track" | "rcs", không gộp chéo)
```

### 5.3 Module mới

#### `src/aim_system/aim_math.py` (MỚI — nguồn chân lý)

```python
@dataclass(frozen=True)
class FrameGeometry:
    frame_w: int
    frame_h: int
    hfov_deg: float          # FOV ngang của VÙNG ĐANG THẤY
    vfov_deg: float          # suy ra từ aspect, hoặc cấu hình riêng
    @property focal_x -> float      # (frame_w/2)/tan(hfov/2)
    @property focal_y -> float
    def px_to_deg(dx, dy) -> (fx_deg, fy_deg)     # atan2 chuẩn
    def deg_to_counts(dx_deg, dy_deg, sens, dpi) -> (cx, cy)

@dataclass
class Calibration:
    counts_per_deg_x: float
    counts_per_deg_y: float
    source: str              # "analytic" | "measured"
    def px_to_counts(geometry, dx, dy) -> (float, float)

def resolve_geometry(tracker, frame) -> FrameGeometry
def px_to_counts(...) -> (float, float)      # API DUY NHẤT cho toàn repo
```

- `resolve_geometry` đọc **kích thước frame thật** + FOV cấu hình + trạng thái crop (`capture_mode`, `udp_fov_enabled`, `capture_range_*`) để tính `hfov` của vùng nhìn thấy.
- `Calibration` ưu tiên `measured` (từ hiệu chuẩn) hơn `analytic`. Khi `measured` có mặt, `54.54` và `103.0` **không còn được dùng**.
- Xoá bỏ hoàn toàn `calculate_movement`; `calculate_exact_counts` giữ làm wrapper deprecated gọi `px_to_counts` (back-compat cho `MagnetTrigger`/test cũ).

#### `src/aim_system/flick_controller.py` (MỚI — thay `mode_flick.py`)

Trạng thái:
```python
armed: bool          # đang trong một cú flick
target_id: hash      # để phát hiện đổi mục tiêu
iterations: int
t0: float
residual: (fx, fy)
```

Thuật toán mỗi frame:
```
1. Nếu không có target hoặc |error| ≤ deadzone_px  → reset(armed=False); return
2. Nếu đổi target                                → reset, armed=True
3. Nếu iterations ≥ flick_max_iterations
      hoặc (now - t0) > flick_budget_ms          → reset(armed=False); return
4. counts = calib.px_to_counts(geometry, dx, dy) * flick_gain     # gain mặc định 1.0
5. counts += residual
6. Gộp vector; nếu |counts| > flick_max_counts → scale GIỮ HƯỚNG, KHÔNG cắt trục
7. residual = counts - round(counts)
8. enqueue(tag="flick", drop_oldest=False)     # ưu tiên xung flick
9. iterations += 1
```

Điểm mấu chốt so với hiện tại:
- **Không cooldown mù.** `flick_budget_ms` là ngân sách *hội tụ*, không phải *cấm đoán*. Hết budget → nhả ra, để frame sau bắt đầu cú mới.
- **Clamp giữ hướng** (`scale` cả vector) thay vì cắt từng trục → không làm méo hướng ngắm.
- **Residual cho cả main và sec.**
- **`deadzone_px` tính theo góc**, không theo pixel thô (pixel ở frame 256 khác nghĩa pixel ở frame 1920).
- **Bypass `TargetSmoother`** (xem 5.4).

### 5.4 Sửa `TargetSmoother` — opt-in theo mode

`mode_dispatcher.py` bổ sung metadata:

```python
_MODE_CAPS = {
    "Flick":     {"closed_loop": False, "uses_smoother": False},
    "Normal":    {"closed_loop": True,  "uses_smoother": True},
    "PID":       {"closed_loop": True,  "uses_smoother": True},
    "NCAF":      {"closed_loop": True,  "uses_smoother": True},
    "WindMouse": {"closed_loop": True,  "uses_smoother": True},
    "Bezier":    {"closed_loop": True,  "uses_smoother": True},
    "Silent":    {"closed_loop": False, "uses_smoother": False},
}
```

`main.py` chỉ gọi `stabilize()` khi **mode đang hoạt động** cần smoother. Với Flick: dùng **vị trí detect thô** của frame hiện tại — đúng bản chất one-shot.

### 5.5 Ngân sách thay cho clamp ma

| Cũ | Mới | Ghi chú |
|---|---|---|
| `max_speed` (không có schema, =1000) | `flick_max_counts` (có schema, mặc định suy ra từ cấu hình, ví dụ 6000) | Đặt tên đúng đơn vị: **counts** |
| `flick_max_step_counts` (default 999, vô hiệu) | bỏ, gộp vào `flick_max_counts` | Một giới hạn, một nghĩa |
| `sec_flick_cooldown_ms = 85` | `flick_budget_ms` (mặc định 120) + `flick_max_iterations` (mặc định 4) | Ngân sách hội tụ, không cấm đoán |
| `flick_strength_x/y` | `flick_gain` (mặc định **1.0**) | Gain vật lý, không phải cảm giác |

---

## 6. PHÂN RÃ FILE CẦN SỬA

### 6.1 Tạo mới

| File | Nội dung | Ưu tiên |
|---|---|---|
| `src/aim_system/aim_math.py` | `FrameGeometry`, `Calibration`, `resolve_geometry`, `px_to_counts` | P0 |
| `src/aim_system/flick_controller.py` | `FlickController` vòng kín có ngân sách | P0 |
| `tests/test_aim_math.py` | Test thuần toán: hình học, crop, aspect, counts | P0 |
| `tests/test_flick_controller.py` | Mô phỏng hội tụ, overshoot, budget, residual | P0 |

### 6.2 Sửa

| File | Hành động cụ thể | Ưu tiên |
|---|---|---|
| `src/aim_system/normal.py` | **Giảm còn orchestration.** Xoá `calculate_movement` (D1). `calculate_exact_counts` → wrapper deprecated gọi `aim_math`. Xoá toàn bộ `_apply_flick_aim` (chuyển sang `flick_controller`). Giữ `_apply_normal_aim` / `_apply_pid_aim` / `_apply_ncaf_aim` / `_apply_windmouse_aim` / `_apply_bezier_aim` / `_apply_silent_aim` nhưng chuyển dần sang `px_to_counts`. Gộp hai tầng offset về một (D14). | P0 |
| `src/aim_system/mode_flick.py` | Thay shim 4 dòng bằng `apply()` gọi `FlickController.step(...)` | P0 |
| `src/aim_system/mode_dispatcher.py` | Thêm `_MODE_CAPS`; expose `get_mode_caps(mode)`; `reset()` mở rộng cho flick state | P0 |
| `main.py` | (a) `_clip_movement` dùng `flick_max_counts`/`max_speed` có schema, **scale giữ hướng**; (b) `_process_move_queue` tôn trọng tag, không gộp chéo `flick`/`rcs`; (c) truyền `FrameInfo` thật vào pipeline; (d) smoother theo `_MODE_CAPS`; (e) `max_speed` có default suy ra, không 1000 ma | P0 |
| `src/utils/config.py` | Thêm schema + clamp cho: `flick_gain`, `flick_gain_sec`, `flick_max_counts`, `flick_max_counts_sec`, `flick_max_iterations`, `flick_budget_ms`, `flick_deadzone_px`, `hfov_deg`, `vfov_deg`, `counts_per_deg_x/y` (measured), `max_speed`; **persist trong `to_dict()`/`from_dict()`**; migration: `strength → gain` với map `1.8 → 1.0` + log cảnh báo | P0 |
| `config.json` | Chuẩn hoá giá trị; `flick_gain = 1.0`; `flick_max_counts` hợp lý; bỏ phụ thuộc `sec_flick_cooldown_ms` cũ (giữ key để back-compat, đọc vào `flick_budget_ms`) | P0 |
| `src/utils/config.py` (`from_dict`) | Thêm validate: `gain ∈ [0.1, 3.0]`, `max_counts ∈ [1, 20000]`, `iterations ∈ [1, 10]`, `budget ∈ [20, 1000]`, `deadzone ∈ [0, 20]`, `hfov ∈ [40, 140]` | P1 |
| `src/ui.py` | Thay slider "Strength X/Y" bằng **Gain / Max counts / Iterations / Budget**; thêm panel **Calibration** (đo `counts_per_deg`); cập nhật `_sync_config_to_tracker` | P1 |
| `src/aim_system/RCS.py` | Đưa `controller.move` vào queue có tag `"rcs"` thay vì gọi trực tiếp (D12) | P1 |
| `src/aim_system/MagnetTrigger.py` | Cập nhật `_magnet_mode_context` theo key mới (`flick_gain` thay `flick_strength_*`) | P1 |
| `src/aim_system/target_smoother.py` | Thêm `enabled` / bypass rõ ràng; không đổi thuật toán | P2 |
| `tests/test_toggle_activation.py` | Cập nhật nếu chữ ký đổi (dự kiến không đổi public API) | P2 |

### 6.3 Không sửa (nhưng phải biết)

- `src/utils/detection.py` — toạ độ bbox đã đúng hệ frame, không phải nguồn lỗi.
- `src/capture/*` — chỉ **đọc** để lấy hình học; không sửa.
- `src/utils/mouse/SerialAPI.py` — `int(x), int(y)` là hành vi hợp lệ; không phải nguồn lỗi.

---

## 7. THAY ĐỔI CONFIG ĐỀ XUẤT (migration)

```jsonc
// THÊM
"hfov_deg": 103.0,              // FOV ngang của nguồn (hiệu chỉnh được)
"vfov_deg": 70.5,               // suy ra từ aspect nếu null
"flick_gain": 1.0,              // 1.0 = đúng vật lý
"flick_gain_sec": 1.0,
"flick_max_counts": 6000,       // ngân sách mỗi xung (count)
"flick_max_counts_sec": 6000,
"flick_max_iterations": 4,      // số bước hiệu chỉnh tối đa
"flick_budget_ms": 120.0,       // tổng thời gian hội tụ
"flick_deadzone_px": 1.5,       // dưới ngưỡng → coi như trúng
"flick_deadzone_px_sec": 2.0,
"counts_per_deg_x": null,       // đo được → ưu tiên hơn analytic
"counts_per_deg_y": null,
"max_speed": 6000,              // có schema, không còn 1000 ma

// GIỮ để back-compat, đọc map sang mới
"flick_strength_x": 1.0,        // was 1.8  → nay = gain
"flick_strength_y": 1.0,        // was 0.55
"sec_flick_cooldown_ms": 120.0, // was 85  → nay = budget
"sec_aim_deadzone": 2.0
```

**Migration trong `from_dict`:**
```
nếu file có flick_strength_x và KHÔNG có flick_gain:
    flick_gain = 1.0
    log WARN: "flick_strength_x=<cũ> đã bị bỏ; gain đặt 1.0.
               Chạy Calibration để có counts_per_deg chính xác."
```

---

## 8. KẾ HOẠCH KIỂM CHỨNG

### 8.1 Unit test thuần toán (`tests/test_aim_math.py`)

| Test | Kỳ vọng |
|---|---|
| `px_to_deg` tại tâm, dx=30, fx=763.62 | `≈2.2502°` |
| `deg_to_counts` với `counts_per_deg` đo được | khớp tuyến tính ±0.1% |
| `resolve_geometry` frame 1920×1080 | `hfov` đúng cấu hình |
| `resolve_geometry` frame 256×256 (crop vuông) | `°/px` **lớn hơn** frame 1920, đúng tỉ lệ FOV |
| aspect 1:1 vs 16:9 | `vfov` suy ra đúng, `focal_y == focal_x` khi cùng aspect |
| `px_to_counts` **đối xứng dấu** | `f(-dx) = -f(dx)` |

### 8.2 Mô phỏng hội tụ (`tests/test_flick_controller.py`)

Kịch bản: mục tiêu đứng yên, khởi tạo lệch `d ∈ {5, 15, 30, 60, 120} px`.

Tiêu chí **bắt buộc**:
- `|error_final| ≤ deadzone` trong `≤ flick_max_iterations` bước.
- **Overshoot ≤ 10%** ở mọi `d` (đây là test bắt D4/D5).
- Không có bước nào vượt `flick_max_counts`.
- Residual: tổng các bước = `counts` lý thuyết ±0.5.
- Đổi mục tiêu giữa chừng → reset sạch, không mang residual cũ.
- Hết budget → nhả `armed=False`, không kẹt.

### 8.3 Hiệu chuẩn thực nghiệm (bắt buộc trước khi tuyên bố "đã sửa")

Đây là bước **loại bỏ magic number** `54.54` / `103.0`:

1. Bật Calibration panel.
2. Đặt mục tiêu tại offset biết trước `(dx, dy)` so với tâm (dùng lưới test).
3. Ra lệnh **một** xung `counts = C` cố định (ví dụ 100 count).
4. Đo dịch chuyển pixel thực tế của tâm ngắm `Δpx`.
5. Lặp cho `C ∈ {25, 50, 100, 200, 400}` và 4 hướng.
6. Fit tuyến tính → `counts_per_px = C / Δpx`; suy `counts_per_deg`.
7. Ghi `counts_per_deg_x/y` vào config → `Calibration.source = "measured"`.

Sau bước này, Flick **không còn phụ thuộc** `54.54`/`103.0`. Nếu `measured` lệch `analytic` > 20%, log WARN vĩnh viễn nhắc hiệu chuẩn lại.

### 8.4 Kiểm chứng hồi quy

- `pytest tests/` phải xanh (đặc biệt `test_toggle_activation.py`, `test_windmouse_predictive.py`).
- A/B trên sân tập: Flick mới vs cũ, đo **thời gian tới đích** và **tỉ lệ trúng** ở 5 khoảng cách.
- Kiểm tra không hồi quy Normal/PID/NCAF/WindMouse (chúng dùng chung `aim_math` sau khi refactor).

---

## 9. THỨ TỰ THI CÔNG ĐỀ XUẤT

| Bước | Nội dung | Phụ thuộc |
|---|---|---|
| 1 | Tạo `aim_math.py` + test (không đụng code cũ) | — |
| 2 | Thêm schema config mới + migration, giữ key cũ | — |
| 3 | Tạo `flick_controller.py` + test mô phỏng | 1, 2 |
| 4 | Nối `mode_flick.py` → controller mới; **giữ code cũ sau flag** `flick_engine = "legacy"/"v2"` | 3 |
| 5 | Bypass smoother cho Flick (`_MODE_CAPS`) | 2 |
| 6 | Sửa `main.py`: queue tag, clamp giữ hướng, geometry thật | 1 |
| 7 | UI: Gain/Max/Iterations/Budget + Calibration panel | 2, 3 |
| 8 | Refactor `normal.py` → orchestration; xoá `calculate_movement` | 1, 4 |
| 9 | Calibration thực nghiệm, ghi `counts_per_deg` | 7 |
| 10 | Xoá flag legacy sau khi A/B đạt | 4, 9 |

**Nguyên tắc rollback:** mọi bước 4–8 giữ được đường lui qua flag; không xoá code cũ cho tới bước 10.

---

## 10. RỦI RO & GIẢM THIỂU

| Rủi ro | Giảm thiểu |
|---|---|
| `px_to_counts` mới làm Normal/PID chậm/khác | Giữ `calculate_movement` + flag trong giai đoạn chuyển; A/B từng mode |
| Người dùng có config cũ với `strength` lớn | Migration map về `gain=1.0`, log WARN rõ ràng; không âm thầm nhân |
| `measured` calibration sai do nhiễu | Yêu cầu ≥5 điểm × 4 hướng, fit R² ≥ 0.99, nếu không → fallback analytic + WARN |
| Bỏ cooldown gây rung | `flick_max_iterations` + `deadzone` + ngân sách thời gian chặn rung; test overshoot ≤10% |
| Clamp giữ hướng làm chậm cú lớn | `flick_max_counts` đủ lớn (6000) + nhiều bước trong budget |
| Refactor `normal.py` vỡ import | Giữ alias public (`calculate_exact_counts`, các `_apply_*`) trong giai đoạn chuyển |

---

## 11. TÓM TẮT MỘT ĐOẠN

Flick lệch hoàn toàn **không phải** vì thiếu tinh chỉnh, mà vì nó là **bộ điều khiển vòng hở** đặt trên **hai bộ quy đổi pixel→count mâu thuẫn và sai thứ nguyên** (`calculate_movement` sai đơn vị; `calculate_exact_counts` dùng magic number `54.54`/`103.0` chưa xác thực, lệch nhau ~1.40×). Cú đánh duy nhất bị nhân bởi `strength 1.8`, rồi bị `max_speed=1000` (biến không có trong schema) **cắt cụt**, tạo overshoot cố định ~1.56× (hoặc lớn hơn nếu hằng số yaw sai) — đủ để đẩy mục tiêu ra ngoài `fovsize_sec=30`, sau đó `sec_flick_cooldown_ms=85` **huỷ** các frame chứa thông tin sửa sai, và `TargetSmoother` đã **làm trễ** vị trí ngay từ đầu. Kiến trúc đúng là: **một module quy đổi duy nhất lấy hình học từ frame thật + hiệu chuẩn đo được**, **gain vật lý 1.0**, **Flick vòng kín có ngân sách hội tụ** thay cho một xung mù, **bypass smoother cho mode one-shot**, và **mọi giới hạn phải có tên, có schema, có log**.

---

*Hết kế hoạch. Không có file mã nguồn nào bị thay đổi trong bước này.*
