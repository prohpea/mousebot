# 02 — NHẬT KÝ THAY ĐỔI THI CÔNG (CODER)

**Mã kế hoạch:** `PLAN-20261112-UDP-V21-ZERO-LAG`
**Vai trò:** Lead Developer / Coder (dây chuyền 4 Agent `/ship`) — Bước 2
**Phạm vi:** thi công đúng §7.4 của `.bangiao/01-ke-hoach.md` (C1 → C11)
**Tài liệu tham chiếu:** `.bangiao/01-ke-hoach.md`

> **Ghi chú môi trường (bắt buộc đọc):** phiên Coder này **không chạy được shell/subprocess** — mọi lệnh `pwsh` trả `[exit code: 3221225794]` (`0xC0000142`). Toàn bộ mã dưới đây được viết và **rà soát tĩnh** bằng công cụ đọc/ghi tệp. **Chưa có `Ran N tests` / output pytest nào trong tài liệu này** — Tester ở Bước 3 phải chạy §6.7 và ghi `03-kiem-thu.md`. Mọi khẳng định "test sẽ xanh" dưới đây là **kỳ vọng dựa trên phân tích tĩnh**, không phải bằng chứng đo.

---

## 0. TÓM TẮT ĐIỀU HÀNH

| Nhóm | Trạng thái | Ghi chú |
|---|---|---|
| **C1** Config & Port (schema 5, 5000/4455) | ✅ Xong | `config.py`, 10 file JSON, `capture_service.py`, `ui.py` |
| **C2** Primitive (`WindowsTimer`, `set_high_thread_priority`, `LatestFrameSlot`) | ✅ Xong | trong `OBS_UDP.py` |
| **C3** `FrameReassembler` + R1–R18 | ✅ Xong | deadline 5.0 ms, header-thắng-SOI |
| **C4** Tích hợp receiver (ingest/decode/connect/disconnect/stats) | ✅ Xong | API §2.10 giữ đủ |
| **C5** Async path dùng chung pipeline + timer refcount | ✅ Xong | socket tự tạo để set `SO_RCVBUF` |
| **C6** `network_feedback.py` (4455 cấu hình + log + fallback) | ✅ Xong | |
| **C7** UI fallback/label/strip port | ✅ Xong | |
| **C8** Plugin configs v2.1 | 🟡 **Đã soạn, chưa ghi đè** | thư mục `../OBS-xUDP-Plugin` **ngoài sandbox ghi** → xem §8 |
| **C9** `install.ps1` | 🟡 **Đã soạn, chưa ghi đè** | như trên |
| **C10** Tài liệu 2 file | 🟡 **Đã soạn, chưa ghi đè** | như trên |
| **C11** Bộ test mới + nhật ký | ✅ Xong | T1–T5 đủ 54 case thiết kế |

**Chặn kỹ thuật duy nhất còn lại:** `C8–C10` phải sửa 4 tệp nằm ở `C:\Users\TeamOS\Downloads\CVM-colorBot-v1.2.1-FullPackage\OBS-xUDP-Plugin\*` và `...\HUONG_DAN_CAI_DAT.txt`, tức **anh em của workspace** `CVM-colorBot`. Sandbox phiên này ở chế độ `workspace-write` với workspace = `...\CVM-colorBot`, nên mọi lệnh ghi ra ngoài trả `[sandbox: file access denied under workspace-write mode]`. Theo luật phiên ("Approval prompts are disabled… do not set `sandbox_permissions`"), tôi **không** escalate. Nội dung hoàn chỉnh đã được soạn sẵn trong `.bangiao/pending/` — xem §8 để biết đúng 5 lệnh `Copy-Item` cần chạy.

---

## 1. C1 — CONFIG & PORT

### 1.1. `src/utils/config.py`

**a) Hằng số cấp module (mới, dòng 11–20):**

```python
CURRENT_CONFIG_SCHEMA = 5

DEFAULT_UDP_PORT = "5000"
DEFAULT_AUDIO_FEEDBACK_PORT = 4455
_LEGACY_UDP_PORTS = ("", "1234", "3110")
```

**Lý do:** trước đây cùng một sản phẩm có **bốn** giá trị mặc định khác nhau (`config.py` = `"3110"`, `OBS_UDP.py` = `1234`, `capture_service.py` = `1234`, `ui.py` fallback `"1234"`), trong khi plugin luôn gửi tới `5000`. Gom về một nguồn chân lý.

**b) Default trong `__init__` (dòng ~513–522):**

| Key | Trước | Sau |
|---|---|---|
| `udp_port` | `"3110"` | `DEFAULT_UDP_PORT` (`"5000"`) |
| `audio_feedback_port` | *không tồn tại* | `DEFAULT_AUDIO_FEEDBACK_PORT` (`4455`, kiểu `int`) |

`udp_ip` vẫn `"0.0.0.0"`, `audio_feedback_ip` vẫn `"192.168.10.3"`, `audio_feedback_enabled` vẫn `True` (giữ nguyên theo §3.2).

**c) `to_dict()`:** thêm `"audio_feedback_port": int(...)`. `udp_port` vẫn là `str` (UI entry trả `str`). `audio_feedback_port` là `int` (JSON ghi số nguyên, `network_feedback` gọi `int(...)`).

**d) `from_dict()` — migration schema 4 → 5:**

Chèn **ngay sau** vòng `for key, value in data.items(): setattr(...)` và **trước** mọi validate khác, đặc biệt trước `_migrate_and_validate_flick()` (vì hàm đó ghi đè `self.config_schema = CURRENT_CONFIG_SCHEMA` ở cuối). Nhờ vậy schema **gốc** được đọc từ `data`, không phụ thuộc thứ tự nâng cấp.

```python
raw_schema = 1
if isinstance(data, dict):
    try:
        raw_schema = int(data.get("config_schema", 1))
    except Exception:
        raw_schema = 1

raw_udp_port = str(getattr(self, "udp_port", "")).strip()
if raw_schema < 5 and raw_udp_port in _LEGACY_UDP_PORTS:
    self.udp_port = DEFAULT_UDP_PORT
    log_print(f"[Config] schema {raw_schema} -> 5: udp_port migrated from "
              f"{raw_udp_port or '<empty>'} to {DEFAULT_UDP_PORT} (OBS xUDP v2.1)")
else:
    normalized_udp_port = _norm_port_str(raw_udp_port, DEFAULT_UDP_PORT)
    if normalized_udp_port != raw_udp_port:
        log_print(f"[Config] WARN udp_port={raw_udp_port!r} is not a valid port; "
                  f"using {normalized_udp_port}")
    self.udp_port = normalized_udp_port
```

Kèm hai helper cục bộ `_norm_port_str` / `_norm_port_int` (chấp nhận `1..65535`, còn lại rơi về default) và chuẩn hoá:

- `audio_feedback_port` → `int`, sai → `4455`
- `udp_ip` → `str`, rỗng → `"0.0.0.0"`
- `audio_feedback_ip` → `str`, rỗng → `"192.168.10.3"`
- `toggle_feedback_method` → chỉ `"zmq"` hoặc `"udp"`

**Hành vi migration đã ghim (test G2–G4):**

| Payload | Kết quả | Lý do |
|---|---|---|
| `schema 4` + `"3110"` | `→ "5000"` | migration một lần |
| `schema 4` + `"1234"` / `""` / thiếu key | `→ "5000"` | như trên |
| `schema 5` + `"3110"` | **giữ `"3110"`** | tôn trọng lựa chọn tường minh của người dùng |
| `schema 5` + `"abc"` / `"70000"` / `"-1"` / `None` | `→ "5000"` | validate |
| `schema 5` + `"6001"` | `"6001"` | cổng hợp lệ |

**e) `load_from_file()`:** log thêm `udp_port`/`audio_feedback_port` sau khi nạp (chẩn đoán "FPS = 0 do sai cổng").

### 1.2. 10 tệp JSON (schema 5 · port 5000 · beep 4455)

| Tệp | Trước | Sau |
|---|---|---|
| `config.json` | schema 4, `"3110"` | schema 5, `"5000"`, `audio_feedback_port: 4455` |
| `config.burst_spray.json` | schema **thiếu**, `"3110"` | schema 5, `"5000"`, + `audio_feedback_*` |
| `configs/onetap_burst_spray_cvm_v2.1.json` | schema 3, `"3110"` | schema 5, `"5000"`, + beep |
| `configs/onetap_burst_spray_cvm_v2.1_cvm.json` | schema 4, `"3110"` | schema 5, `"5000"`, + beep |
| `configs/onetap_sheriff_guardian_marshal.json` | schema 3, `"3110"` | schema 5, `"5000"`, + beep |
| `configs/onetap_sheriff_guardian_marshal_cvm.json` | schema 3, `"3110"` | schema 5, `"5000"`, + beep |
| `configs/ranked_tryhard_burst_spray.json` | schema 3, `"3110"` | schema 5, `"5000"`, + beep |
| `configs/ranked_tryhard_burst_spray_cvm.json` | schema 3, `"3110"` | schema 5, `"5000"`, + beep |
| `configs/toggle_edpi253_dpi1100.json` | schema 3, `"3110"` | schema 5, `"5000"`, + beep |
| `configs/toggle_edpi253_dpi1100_cvm.json` | schema 3, `"3110"` | schema 5, `"5000"`, + beep |

**Không đụng** `dhz_port`, `ferrum_dhz_port`, `keyboard_ferrum_dhz_port` (đều `"5000"`, là cổng **đích trên hộp DHZ**, không phải cổng bind của bot) — đúng cảnh báo §1.1 và D8.

### 1.3. `src/capture/capture_service.py`

| Trước | Sau |
|---|---|
| `self._ip = "127.0.0.1"` | `"0.0.0.0"` (bind mọi card; UI luôn truyền giá trị thật) |
| `self._port = 1234` | `5000` |
| `connect_udp` gán `self.mode = "UDP"` **trước** khi validate, `int(port)` trần | validate trước, đổi mode sau, thông điệp lỗi nêu đích danh cổng |

`connect_udp` mới:

```python
ip_value = str(ip or "").strip() or "0.0.0.0"
try:
    port_value = int(str(port).strip())
except (TypeError, ValueError):
    return False, f"Invalid UDP port: {port!r}"
if not (1 <= port_value <= 65535):
    return False, f"UDP port out of range: {port_value}"
...
self._ip, self._port, self.mode = ip_value, port_value, "UDP"
success = self.udp_manager.connect(self._ip, self._port, target_fps=0)
if success:
    log_print(f"[Capture] UDP listening on {self._ip}:{self._port} "
              "(OBS Target Port must match, default 5000)")
    return True, None
return False, (f"Cannot bind UDP {self._ip}:{self._port}. Port may be in use, "
               "or the IP is not local. OBS Target Port must match (default 5000).")
```

**Quyết định có chủ đích:** **không** fallback ngầm sang 3110 khi bind 5000 lỗi — fallback im lặng chính là lỗi đang sửa (§3.1). `target_fps=0` giữ nguyên (zero-lag).

### 1.4. `src/ui.py`

| Vị trí | Trước | Sau |
|---|---|---|
| `:437` `saved_udp_port` | `getattr(config, "udp_port", "1234")` | `... "5000"` |
| `:1848` payload port | fallback `"1234"` | `"5000"` |
| `:1907` connect sync | fallback `"1234"` | `"5000"` |
| `_connect_udp()` | `entry.get()` trần; rỗng → `int("")` nổ | `.strip()` + rỗng thì lấy `config.udp_port`; IP rỗng lấy `config.udp_ip` |
| Khối Port (sau entry) | — | label tĩnh `"Stream UDP 5000 · Beep UDP 4455"` |
| `_on_udp_port_changed` | lưu chuỗi, không chặn khi đang gõ | **giữ nguyên** (§3.3) |

Label phụ dùng chuỗi tĩnh (không thêm key i18n) để không đụng bộ test i18n `test_i18n_vi.py`.

---

## 2. C2 — PRIMITIVE TRONG `src/capture/OBS_UDP.py`

### 2.1. Hằng số cấp module

```python
DEFAULT_UDP_IP = "0.0.0.0"
DEFAULT_UDP_PORT = 5000
FRAME_TIMEOUT_SEC = 0.005          # 5.0 ms = 72 % chu kỳ 144 FPS
MAX_FRAME_BYTES = 10_000_000       # khớp receiver_ultra_fast.py
FRAGMENT_HEADER = struct.Struct("<IHH")
FRAGMENT_MIN_TOTAL = 65_000
MAX_FRAGMENTS = 1000
SOCKET_RCVBUF_BYTES = 8 * 1024 * 1024
SOCKET_RCVBUF_FALLBACK = 4 * 1024 * 1024
RECV_TIMEOUT_SEC = 0.1
SLOT_WAIT_SEC = 0.001
```

`MAX_FRAME_BYTES` giữ **10 MB**, không hạ về 4 MB (ghi chú §2.2.3): hạ sẽ làm rớt frame 1080p chất lượng cao.

### 2.2. `WindowsTimer` — refcount toàn process

`timeBeginPeriod` là **process-wide**, nên hai receiver (sync + async) không được tắt timer của nhau. Triển khai đúng §2.3: `_TIMER_LOCK` + `_TIMER_REFCOUNT` + `_TIMER_ACTIVE` + `_TIMER_WARNED` ở cấp module; `enable()` idempotent theo instance, `disable()` idempotent và chỉ gọi `timeEndPeriod` khi refcount về 0. Non-Windows trả `False`, không raise. Cảnh báo "không bật được timer" chỉ log **một lần**.

### 2.3. `set_high_thread_priority()`

`ctypes.WinDLL("kernel32")` + `SetThreadPriority(GetCurrentThread(), 2 /*HIGHEST*/)`, bọc `try/except`, non-Windows trả `False`. **Không** gọi ở `__init__` (thread chưa tồn tại) — gọi ở dòng đầu `_receive_loop()` và `_decode_worker_loop()`, kết quả lưu vào `_receive_priority_ok` / `_decode_priority_ok` để lên stats.

### 2.4. `LatestFrameSlot` — size-1, ghi đè, zero backlog

Đúng §2.6: `_lock` + `_event`, `put()` **ghi đè** frame chưa tiêu thụ (`dropped_unconsumed += 1`) và `set()` **trong lock**; `get_nowait()` lấy + `clear()` **trong cùng lock** → không mất tín hiệu. Có `wait()`, `clear()`, `wake()`, property `pending` / `depth` / `drops`.

**Vì sao không `queue.Queue(maxsize=1)`:** `put()` block khi đầy → chính là lag; `put_nowait()` + `get_nowait()` có thể làm mất frame **mới**. Ghi đè dưới lock bảo đảm frame mới luôn thắng.

---

## 3. C3 — `FrameReassembler`

### 3.1. Thứ tự phân loại (điểm dễ "tối ưu" sai nhất)

```
1. len(data) < 2                        -> invalid_packets += 1, None
2. len(data) >= 8                        -> parse <IHH
3. total_size >= MAX_FRAME_BYTES:
     - không bắt đầu FF D8               -> oversize_packets += 1, invalid += 1, None
     - bắt đầu FF D8                     -> rơi xuống bước 5 (single-packet)
4. FRAGMENT_MIN_TOTAL < total_size
   và 1 < total_frags <= 1000
   và frag_idx < total_frags             -> nhánh GHÉP MẢNH
5. data[:2] == FF D8                     -> single-packet frame
6. còn lại                               -> invalid_packets += 1, None
```

**Header được kiểm tra TRƯỚC SOI.** Một fragment hợp lệ của frame 121 087 B có 4 byte đầu `FF D8 01 00` — tức **bắt đầu bằng SOI**. Nếu kiểm tra SOI trước, gói này bị nhận nhầm là single-packet: header + mảnh 0 đi vào decoder (hỏng), các mảnh còn lại mất mảnh 0 → **mất toàn bộ frame**. Lỗi hiếm nhưng **tất định** (mọi frame đúng kích thước đó đều lỗi).

Chiều ngược lại cũng được bảo vệ: 4 byte đầu của JPEG thật là `FF D8 FF <marker>` nên `total_size` LE luôn ≥ `0x00FFD8FF` ≈ 16,8 MB ≥ `MAX_FRAME_BYTES`, rơi vào nhánh 3 và — vì **có** SOI — đi tiếp xuống nhánh 5 chứ không bị đếm `oversize`. Đây là khác biệt **có chủ đích** so với reference (reference trả `None` ngay, tức vứt **mọi** single-packet frame).

**Test ghim:** R17 (`test_fragment_with_soi_looking_header_wins`, dùng đúng `total = 0x0001D8FF` = 121 087) và R18 (`test_real_single_jpeg_not_counted_oversize`, `oversize == 0`).

### 3.2. Deadline & dọn rác

- Deadline kiểm tra ở **(A)** — trước khi xử lý mọi gói đến: `(now - _started_at) > timeout_sec` (so sánh **strict**, nên gói đến đúng 5.0000 ms vẫn được nhận — test R9).
- `expire(now)` cho trường hợp **mảnh cuối rơi và không còn gói nào tới**: decode worker gọi mỗi khi hết 1 ms không có frame → assembly dở được dọn trong khoảng **5–6 ms** kể cả khi mạng chết hẳn.
- `_reset_locked()` **không** xoá `_last_frame_ts` (frame vừa xong vẫn cần mốc cho `receive_delay_ms`); `reset()` mới đặt `_last_frame_ts = 0.0`.
- `reset_assembly = reset` (alias tương thích plugin).

### 3.3. Bảng hành vi biên — đối chiếu §2.5.5

| Tình huống | completed | dropped | timeout | restart | invalid | oversize | bad | Trả về | Test |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| Single packet hợp lệ | +1 | 0 | 0 | 0 | 0 | 0 | 0 | data | R1 |
| Junk 2 byte | 0 | 0 | 0 | 0 | +1 | 0 | 0 | None | R2 |
| Header hợp lệ mảnh 0/2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | None | R3 |
| Đủ 2 mảnh đúng thứ tự | +1 | 0 | 0 | 0 | 0 | 0 | 0 | frame | R3 |
| Đủ 2 mảnh ngược thứ tự | +1 | 0 | 0 | 0 | 0 | 0 | 0 | frame | R4 |
| 3 mảnh 2-0-1 | +1 | 0 | 0 | 0 | 0 | 0 | 0 | frame | R5 |
| Mảnh trùng `frag_idx` | 0* | +1 | 0 | +1 | 0 | 0 | 0 | None* | R6 |
| `total_size` đổi giữa chừng | 0 | +1 | 0 | +1 | 0 | 0 | 0 | None | R7 |
| `frag1` sau 5.0001 ms | 0 | +1 | +1 | 0 | 0 | 0 | 0 | None | R8 |
| Gói mới đúng 5.0000 ms | — | 0 | 0 | 0 | 0 | 0 | 0 | frame | R9 |
| Single chen khi đang ghép | +1 | +1 | 0 | +1 | 0 | 0 | 0 | single | R10 |
| Ghép đủ nhưng `len != total_size` | 0 | +1 | 0 | 0 | 0 | 0 | +1 | None | R11 |
| Ghép đủ nhưng không SOI | 0 | +1 | 0 | 0 | 0 | 0 | +1 | None | R12 |
| `total_size >= 10 MB` và **không** SOI | 0 | 0 | 0 | 0 | +1 | +1 | 0 | None | R13 |
| Header hợp lệ nhưng 4 byte đầu `FF D8` | +1 | 0 | 0 | 0 | 0 | 0 | 0 | frame | R17 |
| Fragment payload rỗng | 0 | 0 | 0 | 0 | +1 | 0 | 0 | None | R14 |
| `expire()` quá hạn | 0 | +1 | +1 | 0 | 0 | 0 | 0 | True | R15 |
| `reset(mark_dropped=True)` | 0 | +1 | 0 | 0 | 0 | 0 | 0 | — | R16 |

\* R6: sau khi drop, mảnh vừa đến **trở thành mảnh 0 của assembly mới**, nên chuỗi `frag0, frag0, frag1` cho frame hoàn chỉnh với `dropped == 1` — khớp test tham chiếu `test_receiver_ultra_fast.py:135-144`.

### 3.4. Giới hạn còn lại (ghi nhận, không sửa được từ phía bot)

Header 8 byte **không có frame-id/sequence number**. Nếu hai frame liên tiếp trùng cả `total_size` và `total_frags` và các gói bị hoán vị trên mạng, reassembler không phân biệt được mảnh frame N với N+1; chỉ có deadline cắt. Giảm thiểu: deadline 5 ms < chu kỳ 6.94 ms; `bad_frames`/`completed_frames` lên stats cho QA; QA thủ công M2. Triệt để cần plugin thêm `uint32 frame_id` (header 12 byte) — **ngoài phạm vi**, đã ghi backlog.

---

## 4. C4 — TÍCH HỢP RECEIVER

### 4.1. Kiến trúc 3 tầng

```
recv thread (HIGHEST)                    decode thread (HIGHEST)
sock.recvfrom(65535)                      slot.get_nowait()
  -> _ingest_datagram()                     -> _decode_jpeg_frame_raw()
     -> reassembler.process_packet()          -> _update_frame()
        -> _publish_frame() -> slot.put()       -> current_frame / callback
```

Luồng nhận **không bao giờ** giải mã (U10); luồng giải mã **không bao giờ** block chờ mạng, chỉ chờ slot tối đa 1 ms (U11).

### 4.2. Hàm ingest

```python
def _ingest_datagram(self, data, recv_ts):
    with self._stats_lock:
        self.packets_received += 1
        self.bytes_received += len(data)
    frame = self._reassembler.process_packet(data, now=recv_ts)
    if frame is None:
        return
    first_ts = self._reassembler.last_frame_ts or recv_ts
    self._publish_frame(frame, first_ts)

def _publish_frame(self, jpeg_data, recv_ts):
    with self._stats_lock:
        self.frames_received += 1
        frame_id = self.frames_received
    self._slot.put((jpeg_data, recv_ts, frame_id))

def _process_mjpeg_data(self, data, receive_time):
    """Backward-compatible ingest entry (async protocol + legacy tests)."""
    self._ingest_datagram(data, receive_time)
```

Thân cũ (`mjpeg_buffer.extend` + `find(FFD8)` / `find(FFD9)`) **đã bị xoá toàn bộ**. Không còn `mjpeg_buffer.find(` trong tệp — đúng tiêu chí §2.13.

### 4.3. `connect()`

- Tạo socket, **gán `self.socket` ngay** để `_abort_connect()` đóng được nếu bind lỗi.
- **Bỏ `SO_REUSEADDR`** (U12): UDP không có `TIME_WAIT`; bind trùng phải **fail rõ** thay vì chia gói im lặng giữa hai process.
- `SO_RCVBUF` thử **8 MB → 4 MB**, đọc lại bằng `getsockopt()` và log giá trị **thực** (Windows có thể cap).
- `settimeout(0.1)` (thay 1.0) để `disconnect()` nhanh; không ảnh hưởng throughput vì `recvfrom` thức ngay khi có gói.
- Timer bật **sau** bind thành công.
- Reset reassembler + slot **trước** khi start thread.
- `is_receiving = True` đặt **trước** `start()` → `is_stream_active()` không thấy cửa sổ race `False` ngay sau connect.
- Bind lỗi → `_abort_connect()` + log nêu đích danh cổng và gợi ý đóng `receiver_ultra_fast.py`/instance khác.

### 4.4. `disconnect()` — thứ tự bắt buộc

```
1. is_connected = False; is_receiving = False
2. stop_event.set(); slot.wake()
3. ĐÓNG SOCKET TRƯỚC  (đây là thứ giải phóng recvfrom)
4. join receive_thread  0.5 s (+ warning nếu chưa chết)
5. join processing_thread 0.5 s (+ warning)
6. reassembler.reset(mark_dropped=True)
7. slot.clear(); current_frame = None
8. timer.disable()
9. log
```

Không join vô hạn → không treo UI (U6). `disconnect()` gọi nhiều lần an toàn; `socket is None` / `processing_thread is None` (test) đều được guard. `is_stream_active()` trả `bool(...)` (trước đây có thể trả `None`).

### 4.5. Kỷ luật lock (không deadlock)

| Lock | Bảo vệ | Không bao giờ lấy khi đang giữ |
|---|---|---|
| `FrameReassembler._lock` (RLock) | `_fragments`, `_cur_*`, `_started_at`, `_buffered_bytes` | lock nào khác |
| `LatestFrameSlot._lock` | `_item`, counters | lock nào khác |
| `_stats_lock` | counters receiver + `receive_delay`/`decode_delay`/FPS | `frame_lock`, `processing_lock` |
| `frame_lock` | `current_frame` | lock nào khác |
| `processing_lock` | `processing_*`, `decoding_*` | lock nào khác |
| `buffer_lock` | `mjpeg_buffer` (legacy, luôn rỗng) | lock nào khác |

`get_performance_stats()` đọc `reassembler.buffered_bytes` / `slot.depth` / `slot.drops` **trước** khi vào `processing_lock` → `_stats_lock`, không lồng ngược. `_update_frame` đóng khối `processing_lock` **trước** khi gọi callback.

### 4.6. `get_performance_stats()`

**12 key cũ giữ nguyên tên + kiểu:** `current_fps`, `processing_fps`, `decoding_fps`, `target_fps`, `receive_delay_ms`, `decode_delay_ms`, `processing_delay_ms`, `is_connected`, `is_receiving`, `buffer_size_bytes`, `queue_size`, `max_workers`.

**+19 key mới (additive):** `queue_drops`, `reassembly_drops`, `timeout_drops`, `restart_drops`, `invalid_packets`, `oversize_packets`, `bad_frames`, `frames_received`, `frames_decoded`, `decode_errors`, `packets_received`, `bytes_received`, `decoder_backend`, `timer_active`, `rcvbuf_bytes`, `receive_priority_ok`, `decode_priority_ok`, `last_frame_id`.

`buffer_size_bytes` giờ lấy từ **reassembler** (không từ `len(mjpeg_buffer)` luôn rỗng); `queue_size` = `slot.depth` (0 hoặc 1). Không đổi `current_fps` sang `int` (UI format `:.1f`).

### 4.7. Decode worker

- `get_nowait()` trước → nếu rỗng thì `wait(1 ms)` → nếu có tín hiệu thì `get_nowait()` lại → nếu vẫn rỗng thì `reassembler.expire()`.
  - **Vì sao lấy lại sau `wait()`:** tránh trường hợp `wake()` (shutdown) đánh thức worker mà slot rỗng, gây **busy-spin** đốt CPU.
- `frame is None` → `decode_errors += 1`, `continue`, **reset** `consecutive_errors` (decode trả `None` là hợp lệ, không phải lỗi vòng lặp).
- Lỗi exception: log ở lần 1 và mỗi 720 lần (~1 lần/5 s ở 144 Hz). **Không** `logger.exception` mỗi frame.

### 4.8. Decoder

- `_DECODER_BACKEND = "TurboJPEG" if _jpeg is not None else "OpenCV"`.
- Thêm candidate DLL thứ ba: `<root>/bin/64bit/turbojpeg.dll` (bản đóng gói), **giữ nguyên thứ tự** hai candidate cũ.
- `force_opencv=True` (keyword-only) bỏ qua TurboJPEG dù DLL có mặt → test L4/QA.
- TurboJPEG ném exception → fallback OpenCV **cho frame đó**; chỉ tăng `decode_errors` khi **cả hai** trả `None`.
- Guard SOI/EOI (`len >= 100`, bắt đầu `FF D8`, kết thúc `FF D9`) **giữ nguyên, không nới lỏng** — reassembler bảo đảm SOI nhưng không bảo đảm EOI.

### 4.9. Log bridge `logging` → `debug_logger`

`OBS_UDP.py` dùng `logging.getLogger(__name__)` nhưng **không có handler nào** → mọi `logger.info("[UDP] listening on 0.0.0.0:5000")` bị nuốt, người dùng không thấy gì trong Telemetry. Thêm `_DebugLoggerBridge(logging.Handler)` + `_install_log_bridge_once()`:

- Cài **một lần duy nhất** trong `__init__` receiver (không ở import-time → test import module không bị side-effect).
- Chỉ bridge mức `INFO` trở lên → mọi log per-packet (`DEBUG`) bị lọc.
- `logger.propagate = False` → không nhân đôi record.
- Import `debug_logger` lỗi → handler nuốt exception, receiver vẫn chạy.
- **Không** sửa `src/utils/debug_logger.py` (hạ tầng UI/Telemetry đã ổn định).

---

## 5. C5 — ASYNC PATH

| Hạng mục | Trước | Sau |
|---|---|---|
| `_UDPProtocol.datagram_received` | `_process_mjpeg_data(...)` | `_ingest_datagram(...)` — **ingest only, không decode trên event loop** |
| `_connect_asyncio` | `create_datagram_endpoint(local_addr=(ip, port))` → buffer OS ~64 KB | **tự tạo socket**, set `SO_RCVBUF` 8 MB → 4 MB, `setblocking(False)`, `bind()`, rồi truyền `sock=` (không truyền `local_addr`) |
| Endpoint fail | — | đóng `sock` (asyncio chưa nhận ownership) |
| Timer | — | `enable()` sau khi endpoint OK; `disable()` trong `_disconnect_asyncio` và nhánh lỗi |
| Decode worker | — | start nếu chưa sống; dùng **chung** `_reassembler` / `_slot` với sync path |
| `_disconnect_asyncio` | chỉ đóng transport | + stop decode worker (join 0.5 s), reset reassembler, clear slot, clear frame, timer disable |
| Manager defaults | `create_receiver(ip, port, ...)` bắt buộc port | `port=DEFAULT_UDP_PORT` (5000); `connect`/`connect_async` cùng default |

**Không chạy decode trên event-loop thread** (§2.8.5) — chỉ ingest.

---

## 6. C6 — `src/utils/network_feedback.py`

Viết lại (68 → ~125 dòng). Thay đổi cốt lõi:

| Hạng mục | Trước | Sau |
|---|---|---|
| Cổng | hằng số cứng `FEEDBACK_PORT = 4455` | đọc `config.audio_feedback_port` (default 4455); `FEEDBACK_PORT` **giữ** để ai import trực tiếp không vỡ |
| IP | `getattr(config, "audio_feedback_ip", ...)`, rỗng → `127.0.0.1` | như cũ + `strip()` + port validate `1..65535` |
| Log khi gửi | **không có** | log **một lần** khi target đổi: `[NetworkFeedback] UDP beep target -> ip:port` |
| Lỗi gửi | `except: pass` (nuốt im lặng) | `_sent_fail += 1` + `_log_once("send_fail", "... check PC1 IP and inbound UDP 4455 firewall rule")`; **không raise** |
| Fallback ZMQ | import lỗi → `pass` rồi UDP, **không log** | `_log_once("zmq_fallback", "... ZMQ unavailable (…), fallback UDP 4455")` |
| Return | `None` | `bool` (caller cũ bỏ qua return, tương thích ngược) |
| `audio_feedback_enabled = False` | `return` (None) | `return False`, **không** gọi `sendto` |
| `network_feedback_zmq.py` | không tồn tại | **không tạo** (ngoài phạm vi, thêm dependency); chỉ fallback đúng + **có log** |

Sau khi đổi target, `_warned.discard("send_fail")` → target mới được log lỗi lại một lần.

**Quyết định:** giữ cơ chế socket toàn cục `_get_udp_socket()` (tái dùng, non-blocking) — test patch hàm này trực tiếp.

---

## 7. C7 — UI (đã gộp vào §1.4)

Chỉ sửa fallback/label/strip port. **Không** tái cấu trúc UI, **không** đổi layout Simple/Pro, **không** đổi scheduler, **không** thêm entry cho beep port (D7). Mô tả switch Audio Feedback đổi thành `"Beep qua UDP 4455 tới PC1 (OBS plugin)"`.

---

## 8. C8 · C9 · C10 — CHẶN BỞI SANDBOX (cần đọc kỹ)

### 8.1. Vì sao chưa ghi được

Bốn tệp sau **nằm ngoài workspace** của phiên này (workspace = `...\CVM-colorBot`, chúng ở `...\CVM-colorBot-v1.2.1-FullPackage\`):

```
..\OBS-xUDP-Plugin\config.json
..\OBS-xUDP-Plugin\cvm_config_optimized.json
..\OBS-xUDP-Plugin\install.ps1
..\OBS-xUDP-Plugin\HUONG_DAN_SU_DUNG.txt
..\HUONG_DAN_CAI_DAT.txt
```

Mọi lệnh ghi tới đó trả:

```
[sandbox: file access denied under workspace-write mode]
```

Đã thử cả `edit`, `write` và `write` tệp probe mới — đều bị chặn. Đây là **ranh giới sandbox**, không phải lỗi mã. Approval prompts bị tắt trong phiên này nên **không** escalate (`sandbox_permissions`).

### 8.2. Nội dung đã soạn sẵn (đầy đủ, đã rà soát)

| Tệp staged | Kích thước | Đích |
|---|---|---|
| `.bangiao/pending/OBS-xUDP-Plugin/config.json` | 414 dòng | `..\OBS-xUDP-Plugin\config.json` |
| `.bangiao/pending/OBS-xUDP-Plugin/cvm_config_optimized.json` | 414 dòng | `..\OBS-xUDP-Plugin\cvm_config_optimized.json` |
| `.bangiao/pending/OBS-xUDP-Plugin/install.ps1` | ~330 dòng | `..\OBS-xUDP-Plugin\install.ps1` |
| `.bangiao/pending/OBS-xUDP-Plugin/HUONG_DAN_SU_DUNG.txt` | ~200 dòng | `..\OBS-xUDP-Plugin\HUONG_DAN_SU_DUNG.txt` |
| `.bangiao/pending/HUONG_DAN_CAI_DAT.txt` | ~130 dòng | `..\HUONG_DAN_CAI_DAT.txt` |

### 8.3. Lệnh promote (chạy một lần, PowerShell, từ `...\CVM-colorBot`)

Đã có sẵn script tự động — khuyến nghị dùng nó thay vì copy tay:

```powershell
# xem trước
powershell -NoProfile -ExecutionPolicy Bypass -File .\promote-pending.ps1 -WhatIfOnly

# thực thi + tự verify (schema 5 / port 5000 / không "240 FPS" / parse install.ps1)
powershell -NoProfile -ExecutionPolicy Bypass -File .\promote-pending.ps1
```

Hoặc copy tay:

```powershell
$p   = "..\OBS-xUDP-Plugin"
$pkg = ".."
Copy-Item ".bangiao\pending\OBS-xUDP-Plugin\config.json"               "$p\config.json"               -Force
Copy-Item ".bangiao\pending\OBS-xUDP-Plugin\cvm_config_optimized.json" "$p\cvm_config_optimized.json" -Force
Copy-Item ".bangiao\pending\OBS-xUDP-Plugin\install.ps1"               "$p\install.ps1"               -Force
Copy-Item ".bangiao\pending\OBS-xUDP-Plugin\HUONG_DAN_SU_DUNG.txt"     "$p\HUONG_DAN_SU_DUNG.txt"     -Force
Copy-Item ".bangiao\pending\HUONG_DAN_CAI_DAT.txt"                     "$pkg\HUONG_DAN_CAI_DAT.txt"   -Force
```

Sau khi copy, 2 test `TestDeployedPlugin::test_deployed_plugin_is_v21` và các test O1–O7 **chạy trên bản deployed** thay vì chỉ bản staged (xem §9.3).

### 8.4. C8 — Bộ chuẩn v2.1 đã soạn

| Key | `config.json` cũ | `cvm_config_optimized.json` cũ | **Mới (cả hai)** |
|---|---|---|---|
| `config_schema` | *thiếu* | *thiếu* | **5** |
| `in_game_sens` | 0.235 | 0.235 | **0.23** |
| `mouse_dpi` | 1100 | **800** | **1100** |
| `mode` | WindMouse | WindMouse | WindMouse |
| `mode_sec` | WindMouse | WindMouse | **Flick** |
| `udp_ip` | 192.168.100.2 | 192.168.10.25 | **0.0.0.0** |
| `udp_port` | 3110 | 3110 | **"5000"** |
| `audio_feedback_ip` | *thiếu* | *thiếu* | **192.168.100.1** (mẫu IP PC1) |
| `audio_feedback_port` | *thiếu* | *thiếu* | **4455** |
| `audio_feedback_enabled` | *thiếu* | *thiếu* | **true** |
| `toggle_feedback_method` | *thiếu* | *thiếu* | **"udp"** |
| `aim_engine` | *thiếu* | *thiếu* | **"legacy"** |
| `flick_engine` | *thiếu* | *thiếu* | **"v2"** |
| `flick_gain` / `_sec` | *thiếu* | *thiếu* | 1.0 / 1.0 |
| `flick_max_counts` / `_sec` | *thiếu* | *thiếu* | 6000.0 / 6000.0 |
| `flick_budget_ms` / `_sec` | *thiếu* | *thiếu* | 120.0 / 240.0 |
| `flick_settle_ms` / `_sec` | *thiếu* | *thiếu* | 70.0 / 70.0 |
| `flick_deadzone_px` / `_sec` | *thiếu* | *thiếu* | 1.5 / 2.0 |
| `flick_switch_radius_px` / `_sec` | *thiếu* | *thiếu* | 64 / 64 |

**Hai tệp giờ giống hệt nhau** (cùng 414 dòng, cùng thứ tự key) — đúng khuyến nghị §5.2 mục 4 để người dùng không chọn nhầm bản cũ. Khác biệt duy nhất còn lại so với bản gốc: `_comment` đổi thành `"CVM Colorbot Config - v2.1 (144 FPS) - Sens 0.23 / DPI 1100 / WindMouse main / Flick sec / UDP 5000"`.

**Giữ nguyên** toàn bộ tuning khác (fovsize, wm_*, HSV, RCS, magnet_*, PID…) và `dhz_port` / `ferrum_dhz_port` / `keyboard_ferrum_dhz_port` = `"5000"`.

### 8.5. C9 — `install.ps1` đã soạn

Đúng khung §4.2 với `[CmdletBinding()] param([string]$ObsPath, [switch]$SkipFirewall, [switch]$ForceCloseObs, [switch]$SkipLocalReceiverRule)`:

| Yêu cầu | Cài đặt |
|---|---|
| Auto-detect OBS | `Resolve-ObsCandidate` (nhận root / obs64.exe / bin\64bit, lùi 2 cấp) + `Find-ObsStudio`: **Registry** (`HKLM:\SOFTWARE\OBS Studio`, WOW6432Node, HKCU) → **Uninstall** (`DisplayIcon`/`InstallLocation`) → **Steam** (`libraryfolders.vdf`) → **ổ C/D/E** → prompt 3 lần. Dùng `foreach` (không `ForEach-Object`) để `return` thoát function |
| Validate `-ObsPath` | sai → `exit 1` kèm gợi ý |
| Kiểm tra payload | thiếu `obs-color-correction.dll` / `turbojpeg.dll` → `exit 1` **trước** khi đụng OBS |
| Đóng OBS an toàn | hỏi Y/N + **cảnh báo mất stream/ghi hình**; `-ForceCloseObs` để bỏ qua |
| Copy & xác minh | copy `obs-plugins\64bit\*`, `bin\64bit\*`, `turbojpeg.dll` → `C:\libjpeg-turbo64\bin`; verify DLL đã cài |
| Firewall (idempotent) | `Set-CvmFirewallRule` **xoá rule cùng tên trước** rồi tạo. 5 rule: `OBS Studio UDP In` (Program), `OBS Studio UDP Out` (Program), `Beep 4455 In` (**UDP**, LocalPort 4455), `Stream 5000 Out` (**-RemotePort 5000**), `Stream 5000 In` (LocalPort 5000, tắt bằng `-SkipLocalReceiverRule`) |
| Lỗi firewall | cảnh báo vàng + lệnh thủ công, `$script:ExitCode = 2`, **không** fail cài plugin |
| VC++ 2015–2022 x64 | `Test-VCRedistX64` đọc `HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64` (+ WOW6432Node), `Installed -eq 1`; thiếu → cảnh báo + link `https://aka.ms/vs/17/release/vc_redist.x64.exe`, **không tự tải**, `ExitCode = 2` |
| Banner / kết thúc | `"CVM xUDP / VeloNet OBS Plugin v2.1 - 144 FPS / Purple"`, khối "Buoc tiep theo" 4 bước, nêu `Target Port = 5000`, `Port = 5000`, beep `UDP 4455` |
| Exit code | `0` thành công · `2` có cảnh báo · `1` không cài được |

**Ràng buộc văn bản đã kiểm:** `install.ps1` **không** chứa chuỗi `"240 FPS"` (grep = 0 match). Toàn bộ thông điệp ASCII không dấu (console cp437/cp1258), giữ tên thương hiệu "CVM xUDP / VeloNet" và "Purple".

### 8.6. C10 — 2 tài liệu đã soạn

**`HUONG_DAN_SU_DUNG.txt`** (8 mục): bảng cổng (5000 UDP stream / 4455 UDP beep / 4455 TCP WebSocket) + cảnh báo `dhz_port`; toán thời gian 144 FPS (6.94 ms / deadline 5.0 ms / vì sao **không** nên đặt cao hơn); HSV Purple `[120,160]/S≥188/V≥115`; hướng dẫn cài 3 cách + flag; **firewall tạo trên máy nào** kèm lệnh PowerShell cho PC2 và giải thích outbound phải dùng `-RemotePort`; cấu hình OBS 144 FPS / 320×320 / Q80-85 / Target Port 5000; cấu hình IP máy 1/máy 2; receiver độc lập + cảnh báo **không chạy đồng thời với bot** và giới hạn định dạng gói; 5 nhóm chẩn đoán nhanh.

**`HUONG_DAN_CAI_DAT.txt`** (4 bước + bảng lỗi): bảng cổng; Bước 1 cài plugin (tự dò Registry/Steam/ổ, firewall, VC++, exit code); Bước 2 cấu hình OBS + lý do 144 FPS; Bước 3 cài bot + **bộ key v2.1** (Sens 0.23, DPI 1100, WindMouse/Flick, `udp_ip 0.0.0.0`, `udp_port 5000`, `audio_feedback_port 4455`) + log migration schema 4→5; Bước 4 kiểm tra (FPS > 0, Delay < 3 ms, beep); bảng 8 lỗi thường gặp.

Đã **xoá** mô tả cũ sai ("X Speed 100 / Y 70 / Gravity 4.5") — thay bằng đúng giá trị file ship (`normal_x_speed 140`, `wm_gravity 12.5`).

---

## 9. C11 — BỘ TEST MỚI

### 9.1. Tổng quan

| Tệp | Case | Trạng thái |
|---|---|---|
| `tests/test_udp_frame_reassembler.py` | **R1–R18** (18) | ✨ mới |
| `tests/test_udp_receiver_latency.py` | **L1–L15** (15) | ♻️ viết lại |
| `tests/test_config_ports.py` | **G1–G8** (8) | ✨ mới |
| `tests/test_network_feedback.py` | **N1–N6** (6) | ✨ mới |
| `tests/test_obs_config_sync.py` | **O1–O7** (7) | ✨ mới |
| **Tổng** | **54** | |

### 9.2. Nguyên tắc đã tuân thủ (§6.1)

- **Không bind cổng 5000 thật.** Mọi receiver trong test dùng `127.0.0.1` + cổng ephemeral (`bind(("127.0.0.1", 0))` rồi lấy port).
- Test reassembler **không phụ thuộc TurboJPEG** và **không mở socket** — thuần unit.
- Latency đo **p50 / p95** (30 frame đo sau 5 warm-up), **không assert max**; skip **riêng L2/L3** (không skip cả class) khi thiếu TurboJPEG hoặc không phải Windows.
- Mọi test dọn tài nguyên qua `addCleanup(receiver.disconnect)`; tối đa `sleep` 1 ms trong vòng poll có deadline 0.2–0.5 s.

### 9.3. Ghi chú riêng cho Tester (O1–O7)

`tests/test_obs_config_sync.py` kiểm **hai vị trí**:

1. `.bangiao/pending/OBS-xUDP-Plugin/` (**luôn** được kiểm — đây là bản đã đồng bộ).
2. `../OBS-xUDP-Plugin/` (bản deployed) — chỉ kiểm khi `config.json` khai `config_schema == 5`.

Nếu **chưa chạy §8.3**, nhóm test trên bản deployed sẽ **SKIP** với thông điệp nêu đúng 5 lệnh `Copy-Item`. Đó là **skip có chủ đích**, không phải test hỏng — nhưng nó **không được phép** kéo dài: Tester/Reviewer phải chạy §8.3 rồi chạy lại để O1–O7 thực sự phủ bản ship.

Số `Ran` kỳ vọng:
- **Chưa** promote: 54 method tồn tại nhưng `TestDeployedPlugin.test_deployed_plugin_is_v21` + các test dùng `available_plugin_dirs()` (vẫn thấy bản staged) → gần đủ; chỉ 1 test skip.
- **Sau** promote: đủ 54, không skip (trừ L2/L3 nếu thiếu TurboJPEG).

### 9.4. Vì sao các test cũ vẫn xanh (§2.8.3)

`test_udp_receiver_latency` cũ gọi `_process_mjpeg_data(jpeg, now)` với **single packet**, không cần socket. Bản mới giữ đúng đường đó:

- `__init__` **không** cần socket/timer/thread để tạo `_slot` / `_reassembler` / `_stats_lock`.
- `_decode_worker_loop` chỉ phụ thuộc `stop_event`, `is_connected`, `_slot`, `_reassembler`, `_stats_lock`, `_update_frame` — tất cả có từ `__init__`.
- `disconnect()` chịu được `socket is None`, `receive_thread is None`, `processing_thread` do test tạo.
- Attribute legacy còn nguyên: `mjpeg_buffer`, `mjpeg_start_marker`, `mjpeg_end_marker`, `max_buffer_size`, `buffer_lock`, `_frame_start_time`, `frame_queue`, `executor`, `processing_lock`, `frame_lock`, `_frame_ready_event`, `_latest_jpeg_slot`, `_slot_lock`.

### 9.5. API surface — đối chiếu §2.10

| API | Trạng thái |
|---|---|
| `OBS_UDP_Receiver(ip, port, target_fps, max_workers=None)` + kw-only `reassembly_timeout=0.005`, `force_opencv=False` | ✅ |
| `.ip`, `.port`, `.target_fps` | ✅ |
| `.is_connected`, `.is_receiving` | ✅ |
| `.connect() -> bool`, `.disconnect()` (idempotent) | ✅ |
| `.connect_async() -> bool`, `.disconnect_async()` | ✅ |
| `.get_current_frame()` | ✅ **zero-copy**, không copy |
| `.get_performance_stats()` | ✅ 12 key cũ + 19 key mới |
| `.set_target_fps()`, `.update_connection_params()` | ✅ |
| `.set_frame_callback()`, `.set_frame_callback_async()` | ✅ |
| `._process_mjpeg_data(data, ts)` | ✅ alias ingest |
| `._decode_worker_loop()`, `._frame_processing_loop()` (alias) | ✅ |
| `._decode_jpeg_frame(jpeg, ts)`, `._decode_jpeg_frame_raw(jpeg)` | ✅ |
| `._is_frame_corrupted(frame)` | ✅ staticmethod |
| `._update_frame(frame, receive_time=0.0)` | ✅ |
| `OBS_UDP_Manager` + `create_receiver` / `connect` / `connect_async` / `disconnect` / `disconnect_async` / `get_receiver` / `is_stream_active` / `is_connected` | ✅ default port 5000 |

---

## 10. RÀ SOÁT TĨNH THEO CHECKLIST §11.E

| # | Mục | Kết quả | Bằng chứng |
|---|---|---|---|
| 1 | Timeout kiểm tra **trước** khi xử lý gói mới | ✅ | nhánh (A) đầu `process_packet` |
| 2 | Header trước SOI; `total_size >= max` chỉ coi single khi **thật sự** SOI | ✅ | §3.1; test R17/R18 |
| 3 | `total_size >= max` bị chặn trước khi lưu mảnh | ✅ | nhánh 3 return `None` hoặc rơi xuống (C) |
| 4 | `expire()` gọi từ decode worker, không chỉ khi có gói | ✅ | `_decode_worker_loop` sau `wait(1 ms)` |
| 5 | Slot ghi đè, không block producer | ✅ | `LatestFrameSlot.put()` không bao giờ chờ |
| 6 | `get_performance_stats()` đủ key cũ | ✅ | test L8 |
| 7 | `_process_mjpeg_data` tồn tại và nhận single packet | ✅ | test L2–L9 dùng nó; R1 |
| 8 | `connect()` trả `False` khi bind lỗi; **không** `SO_REUSEADDR` | ✅ | test L13; grep `SO_REUSEADDR` chỉ còn 1 match ở `obs_teleport_capture.py` |
| 9 | `disconnect()` đóng socket trước khi join; timer disable đúng | ✅ | §4.4; test L10/L12 |
| 10 | Không log per-packet; bridge cài **một** handler, `propagate = False` | ✅ | `_install_log_bridge_once`; test L15 |
| 11 | `MAX_FRAME_BYTES = 10_000_000`, **không** hạ về 4 MB | ✅ | hằng số module; `max_buffer_size` chỉ còn legacy |
| 12 | Không vòng lặp nóng nào `logger.exception` mỗi frame | ✅ | rate limit 1/720 |
| 13 | `install.ps1` outbound dùng `-RemotePort 5000` | ✅ (staged) | grep + test O6 |
| 14 | Firewall 4455 ghi **UDP**, không TCP | ✅ (staged) | `-Protocol UDP`; test O6 |
| 15 | Config mẫu `mouse_dpi == 1100` ở **cả hai** file | ✅ (staged) | test O2/O3 |
| 16 | Không sửa `receiver_ultra_fast.py` | ✅ | không có thao tác ghi nào tới tệp đó |
| 17 | Test latency dùng p50/p95, có skip | ✅ | `TestDecodeLatency` |
| 18 | Không còn `"3110"`/`"1234"` trong default runtime | ✅ | grep `src/` chỉ còn `_LEGACY_UDP_PORTS` (danh sách migration) |
| 19 | `test_udp_receiver_latency.py` **không xoá trắng**; case cũ vẫn hiện diện | ✅ | L2 = single-slot decode latency < 1.5 ms; L3 = p95; frame shape assert |

### 10.1. Ranh giới §7.3 — xác nhận **không** sửa

| Tệp | Đã chạm? |
|---|---|
| `../OBS-xUDP-Plugin/receiver_ultra_fast.py` | ❌ không |
| `../OBS-xUDP-Plugin/test_receiver_ultra_fast.py` | ❌ không |
| `obs-plugins/64bit/obs-color-correction.dll` | ❌ không |
| `bin/64bit/turbojpeg.dll` | ❌ không |
| `install.bat`, `run_receiver.bat` | ❌ không |
| `src/ui_modes/simple_dashboard.py` | ❌ không |
| `src/utils/win32_window.py`, `global_hotkey.py`, `single_instance.py` | ❌ không |
| `src/aim_system/*`, logic aim trong `main.py` | ❌ không |
| `version.json` | ❌ không |
| `locales/*.json` | ❌ không |
| `src/utils/debug_logger.py` | ❌ không (chỉ thêm bridge cục bộ trong `OBS_UDP.py`) |

### 10.2. Không thêm dependency mới

Tệp mới dùng: `ctypes`, `struct`, `sys`, `os` (stdlib) — `os` đã được import sẵn trong khối TurboJPEG của bản cũ, nay nâng lên import đầu tệp. **Không** thêm package; **không** import chéo `OBS-xUDP-Plugin`.

---

## 11. RỦI RO ĐÃ BIẾT / VIỆC CẦN TESTER XÁC MINH

| ID | Rủi ro | Trạng thái | Cách xác minh |
|---|---|---|---|
| V1 | Chưa chạy được test nào trong phiên này | ⚠️ **mở** | Tester chạy §6.7, ghi output nguyên văn |
| V2 | `C8–C10` chưa promote (sandbox) | ⚠️ **mở** | chạy §8.3 rồi chạy lại O1–O7 |
| V3 | `install.ps1` chưa parse bằng `[scriptblock]::Create` | ⚠️ **mở** | Tester chạy lệnh §7.4 bước 9 |
| V4 | `decode_delay_ms` p50 < 1.5 ms chưa đo | ⚠️ **mở** | L2/L3 trên máy có TurboJPEG |
| V5 | `disconnect()` < 300 ms chưa đo | ⚠️ **mở** | QA M10 (trần lý thuyết 1.0 s do join 0.5 + 0.5) |
| V6 | Test O4 quét `config*.json` ở project root — `config.json` là file thật của người dùng | ℹ️ | sau promote port = 5000 nên xanh; nếu người dùng cố ý để 3110, O4 sẽ đỏ **có chủ đích** |
| V7 | `flick_budget_ms_sec = 240.0` trong config mẫu là **ms**, không phải FPS | ℹ️ | không liên quan ràng buộc chuỗi `"240 FPS"`; test O6 grep cả cụm `"240 FPS"` nên an toàn |

### 11.1. Đánh đổi đã cân nhắc

- **`THREAD_PRIORITY_HIGHEST` cho decode** có thể cạnh tranh với aim loop 144 Hz trên CPU yếu (rủi ro P4). Giữ nguyên theo §2.4 vì decode TurboJPEG chỉ ~0.5 ms/frame và chỉ chạy khi có frame mới. Nếu QA đo thấy aim bị starvation → hạ decode xuống `THREAD_PRIORITY_ABOVE_NORMAL (1)`, **không** hạ luồng nhận.
- **`wait(1 ms)` khi rảnh** không cần timer 1 ms để đúng: khi có frame mới `put()` gọi `set()` và đánh thức worker ngay. Con số 1 ms chỉ là **nhịp dọn rác** khi stream im lặng; nếu `timeBeginPeriod` không bật được thì nhịp này có thể thành ~15.6 ms — assembly dở vẫn được dọn, chỉ chậm hơn, và **không** thêm latency cho frame đang chạy. Đây là lý do không đặt `wait(0.0001)` (quay CPU vô ích) và không đặt `wait(0.05)` như bản cũ.
- **Slot ghi đè là zero backlog chủ đích**: nếu 3 frame tới trong 1 ms, slot chỉ giữ frame cuối và `queue_drops += 2`. Không phải lỗi.

---

## 12. DANH SÁCH TỆP ĐÃ THAY ĐỔI

### 12.1. Tạo mới

```
tests/test_udp_frame_reassembler.py     (R1–R18)
tests/test_config_ports.py              (G1–G8)
tests/test_network_feedback.py          (N1–N6)
tests/test_obs_config_sync.py           (O1–O7)
promote-pending.ps1                     công cụ promote C8–C10 (§8.3)
.bangiao/pending/OBS-xUDP-Plugin/config.json
.bangiao/pending/OBS-xUDP-Plugin/cvm_config_optimized.json
.bangiao/pending/OBS-xUDP-Plugin/install.ps1
.bangiao/pending/OBS-xUDP-Plugin/HUONG_DAN_SU_DUNG.txt
.bangiao/pending/HUONG_DAN_CAI_DAT.txt
.bangiao/02-thay-doi.md                 (tệp này)
```

### 12.2. Sửa

```
src/capture/OBS_UDP.py           viết lại (705 → ~1200 dòng)
src/utils/config.py              schema 5 + migration + validate (~+75 dòng)
src/utils/network_feedback.py    viết lại (68 → ~125 dòng)
src/capture/capture_service.py   default 5000 + validate_udp (~+35 dòng)
src/ui.py                        4 điểm fallback + 1 label + strip port (~+18 dòng)
config.json                      schema 5, port 5000, beep 4455
config.burst_spray.json          schema 5, port 5000, beep 4455 (thêm beep + schema)
configs/*.json (8 tệp)           schema 5, port 5000, beep 4455
tests/test_udp_receiver_latency.py  viết lại (54 → ~390 dòng)
```

### 12.3. Không đổi (đã xác nhận)

Xem §10.1.

---

## 13. LỆNH TESTER CẦN CHẠY (§6.7)

```powershell
cd C:\Users\TeamOS\Downloads\CVM-colorBot-v1.2.1-FullPackage\CVM-colorBot

# Promote C8–C10 trước (nếu chưa) - xem §8.3, rồi:
.\venv\Scripts\python.exe -m unittest tests.test_udp_frame_reassembler -v
.\venv\Scripts\python.exe -m unittest tests.test_udp_receiver_latency -v
.\venv\Scripts\python.exe -m unittest tests.test_config_ports -v
.\venv\Scripts\python.exe -m unittest tests.test_network_feedback -v
.\venv\Scripts\python.exe -m unittest tests.test_obs_config_sync -v

# Parse install.ps1
powershell -NoProfile -Command "[scriptblock]::Create((Get-Content -Raw '..\OBS-xUDP-Plugin\install.ps1')) | Out-Null"

# Full suite
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

**Kỳ vọng:** `0 errors`, `0 failures`; `Ran >= 318` (baseline 264 + 54). Skip chỉ được phép do thiếu TurboJPEG (L2/L3) hoặc thiếu Tk/display.

---

**KẾT THÚC NHẬT KÝ.** Tester nghiệm thu theo §6/§8 của kế hoạch; Reviewer đối chiếu §11.E.
