# 01 — KẾ HOẠCH ĐỒNG BỘ & NÂNG CẤP OBS xUDP + UDP RECEIVER LÊN CHUẨN v2.1 (144 FPS / ZERO-LAG)

**Mã hiệu:** `PLAN-20261112-UDP-V21-ZERO-LAG`
**Vai trò:** Lead Software Architect & Planner (Dây chuyền 4 Agent `/ship`)
**Trạng thái:** Đã khảo sát tĩnh — thiết kế — lập kế hoạch. **Không sửa một dòng mã sản phẩm nào.**
**Tài liệu được thay thế:** `.bangiao/01-ke-hoach.md` phiên bản `PLAN-20261111-UI-SIMPLE-PRO-LAUNCHER`. Toàn bộ hạ tầng Simple/Pro, launcher, `win32_window.py`, `global_hotkey.py`, `single_instance.py`, schema 4 và 264 test hiện có được coi là **baseline bất biến**, không được phá vỡ trong đợt này.
**Phạm vi đọc:** `.bangiao/task_prompt.md`; `src/capture/OBS_UDP.py`; `src/capture/capture_service.py`; `src/utils/config.py`; `src/utils/network_feedback.py`; `src/utils/activation.py`; `src/ui.py` (các vùng UDP/Audio Feedback/port); `main.py`; `tests/test_udp_receiver_latency.py`; `tests/test_ui_launcher.py`; `tests/test_flick_config.py`; `config.json`; `config.burst_spray.json`; `configs/*.json`; `../OBS-xUDP-Plugin/receiver_ultra_fast.py`; `../OBS-xUDP-Plugin/test_receiver_ultra_fast.py`; `../OBS-xUDP-Plugin/install.ps1`; `../OBS-xUDP-Plugin/install.bat`; `../OBS-xUDP-Plugin/run_receiver.bat`; `../OBS-xUDP-Plugin/config.json`; `../OBS-xUDP-Plugin/cvm_config_optimized.json`; `../OBS-xUDP-Plugin/HUONG_DAN_SU_DUNG.txt`; `../HUONG_DAN_CAI_DAT.txt`; `../OBS-xUDP-Plugin/udp_receiver_test.py`; `../OBS-xUDP-Plugin/udp_receiver_test_legacy.py`; `CHANGELOG.md`.

> **Ghi chú môi trường (bắt buộc đọc):** phiên Planner này **không chạy bất kỳ lệnh shell/subprocess nào** (môi trường Windows sandbox trả `0xC0000142`). Mọi kết luận là **phân tích tĩnh**, mọi con số độ trễ trong tài liệu là **ngân sách thiết kế / ngưỡng nghiệm thu**, không phải số đo thực tế. Coder và Tester phải tự chạy các lệnh ở §6.7 để tạo bằng chứng.

---

## 0. KẾT LUẬN ĐIỀU HÀNH

Bài toán có **hai lỗi P0 độc lập** và **một nợ kỹ thuật P1**:

1. **P0 — Lệch cổng làm hệ thống "kết nối thành công nhưng không có frame":**
   Plugin OBS gửi stream tới **UDP 5000** (`HUONG_DAN_SU_DUNG.txt:50`, `run_receiver.bat:12-14`, `receiver_ultra_fast.py:745`), nhưng bot bind **UDP 3110** (`src/utils/config.py:518`, `config.json:368`, toàn bộ `configs/*.json`). `capture_service.connect_udp()` chỉ bind socket nên **luôn trả `True`** dù không nhận được gói nào. UI hiện "UDP connected", FPS = 0, người dùng tưởng hỏng plugin.
   Đồng thời `OBS_UDP.py` mặc định `port=1234`, `capture_service.py` mặc định `_port=1234`, `ui.py` fallback `"1234"` — tức có **ba giá trị mặc định khác nhau** trong cùng một sản phẩm.

2. **P0 — Receiver của bot không hiểu định dạng fragment của plugin:**
   `OBS-xUDP-Plugin` gửi frame > 65 000 byte dưới dạng nhiều gói, mỗi gói có **header 8 byte `[total_size:uint32][frag_idx:uint16][total_frags:uint16]`** (`receiver_ultra_fast.py:291-302`). `OBS_UDP.py` hiện chỉ nối byte vào `bytearray` và tìm `FFD8…FFD9` (`OBS_UDP.py:400-458`). Khi frame bị chia mảnh, 8 byte header của **mọi mảnh sau mảnh 0** nằm giữa dữ liệu JPEG → JPEG hỏng → `imdecode` thất bại. Với frame 320×320 chất lượng 80 (~7–8 KB) lỗi này không lộ; với 640×640/1080p hoặc JPEG quality cao, **gần như 100 % frame bị mất**. Đây là lý do phải có `FrameReassembler` thật, không chỉ tăng buffer.

3. **P1 — Thiếu deadline và thiếu timer/priority:**
   Receiver hiện không có khái niệm "frame quá hạn". Nếu một mảnh rơi, các mảnh còn lại nằm trong buffer tới khi frame kế tiếp tràn vào; buffer có thể tích tụ và làm frame mới bị cắt sai. Không có `timeBeginPeriod(1)`, không nâng priority luồng nhận/giải mã, `recvfrom` timeout 1.0 s làm `disconnect()` có thể treo UI tới 1 giây.

**Giải pháp tổng thể:** đưa toàn hệ thống về **một cổng stream duy nhất 5000**; port beep **4455** tách biệt và cấu hình được; thay lõi nhận của bot bằng **pipeline 3 tầng** `FrameReassembler (5.0 ms deadline) → LatestFrameSlot (size-1) → DecodeWorker (TurboJPEG/OpenCV)`; bọc `WindowsTimer(1ms)` + `THREAD_PRIORITY_HIGHEST`; giữ **100 % hợp đồng API** với `capture_service.py`, `ui.py` và test cũ; đồng bộ `install.ps1`, tài liệu và toàn bộ config mẫu.

---

## 1. HIỆN TRẠNG & KIẾN TRÚC TỔNG THỂ

### 1.1. Luồng dữ liệu hai máy

```
┌──────────────────────────── MÁY 1 (PC chơi game / OBS) ────────────────────────────┐
│                                                                                     │
│  Game / màn hình                                                                    │
│      │                                                                              │
│      ▼                                                                              │
│  OBS Studio 64-bit                                                                  │
│   ├─ Game Capture ──► Filter "Color Correction" (obs-color-correction.dll)          │
│   │                        │                                                        │
│   │                        ├─ JPEG encode 320×320, Q80–85, 144 FPS                  │
│   │                        ├─ Nếu JPEG ≤ 65 000 B: 1 datagram = [FFD8 … FFD9]       │
│   │                        └─ Nếu JPEG > 65 000 B: N datagram, mỗi gói:             │
│   │                              [total_size u32 LE][frag_idx u16 LE][total_frags u16 LE][payload] │
│   │                                     │                                           │
│   │                                     ▼ UDP, đích = IP_PC2:5000                   │
│   └─ Audio Feedback listener ◄──── UDP 4455 ◄──── bot gửi b'1' / b'0' khi toggle     │
│                                                                                     │
└──────────────────────────────────────┬──────────────────────────────────────────────┘
                                       │ LAN / Ethernet / Wi-Fi
                                       ▼
┌──────────────────────────── MÁY 2 (CVM-colorBot) ──────────────────────────────────┐
│                                                                                     │
│  src/capture/OBS_UDP.py                                                             │
│   socket bind 0.0.0.0:5000, SO_RCVBUF 8 MB                                          │
│      │                                                                              │
│      ▼  receive thread (THREAD_PRIORITY_HIGHEST)                                    │
│   FrameReassembler(timeout=5.0 ms)                                                  │
│      │  frame JPEG hoàn chỉnh + recv_ts                                             │
│      ▼                                                                              │
│   LatestFrameSlot (size-1, ghi đè frame chưa kịp giải mã)                           │
│      │                                                                              │
│      ▼  decode thread (THREAD_PRIORITY_HIGHEST, WindowsTimer 1 ms)                  │
│   TurboJPEG (ưu tiên) → OpenCV imdecode (fallback)                                  │
│      │  ndarray BGR                                                                 │
│      ▼                                                                              │
│   get_current_frame()  ◄── CaptureService.read_frame() ◄── AimTracker / UI          │
│                                                                                     │
│  src/utils/network_feedback.py ── UDP b'1'/b'0' ──► IP_PC1:4455                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

**Hai kênh hoàn toàn độc lập:**

| Kênh | Chiều | Giao thức | Cổng | Ai bind | Ai gửi |
|---|---|---|---|---|---|
| Video stream | PC1 → PC2 | UDP | **5000** | Bot (`OBS_UDP_Receiver`) | `obs-color-correction.dll` |
| Toggle beep | PC2 → PC1 | UDP | **4455** | `obs-color-correction.dll` | `network_feedback.py` |
| (không thuộc phạm vi) OBS WebSocket | — | **TCP** | 4455 | OBS built-in | browser/tool |
| (không thuộc phạm vi) DHZ mouse box | PC2 → box | UDP | 5000 (remote) | box | `DHZAPI.py` (ephemeral source) |

> **Cảnh báo quan trọng:** UDP 4455 của plugin **không phải** OBS WebSocket TCP 4455. Hai giao thức khác nhau nên cùng số cổng vẫn chạy song song, nhưng tài liệu và rule firewall phải ghi rõ `UDP` để người dùng không mở nhầm TCP. Tương tự, `dhz_port = "5000"` là cổng **đích trên box DHZ**, không phải cổng bind của bot; chỉ có thể trùng nếu box DHZ chạy trên chính PC2 — khi đó phải đổi `dhz_port` sang 5001.

### 1.2. Bằng chứng hiện trạng (đọc trực tiếp từ mã)

| # | Vị trí | Nội dung | Hệ quả |
|---|---|---|---|
| E1 | `src/utils/config.py:518` | `self.udp_port = "3110"` | Default bot lệch plugin |
| E2 | `config.json:368`; `config.burst_spray.json:344`; 8 file `configs/*.json` | `"udp_port": "3110"` | Mọi profile đều kéo bot về 3110 |
| E3 | `src/capture/OBS_UDP.py:45` | `port: int = 1234` | Default thứ hai |
| E4 | `src/capture/capture_service.py:151` | `self._port = 1234` | Default thứ ba |
| E5 | `src/ui.py:437, 1848, 1907` | fallback `"1234"` | Default thứ tư |
| E6 | `../OBS-xUDP-Plugin/receiver_ultra_fast.py:745-747` | CLI default `--port 5000` | Nguồn chân lý của plugin |
| E7 | `../OBS-xUDP-Plugin/HUONG_DAN_SU_DUNG.txt:50` | `Target Port: 5000` | Tài liệu đã đúng 5000 |
| E8 | `../OBS-xUDP-Plugin/config.json:345`; `cvm_config_optimized.json:345` | `"udp_port": "3110"` | Config mẫu tự mâu thuẫn với tài liệu |
| E9 | `OBS_UDP.py:400-458` | buffer byte + `find(b'\xff\xd8')` / `find(b'\xff\xd9')` | Không hiểu header 8 byte; frame phân mảnh hỏng |
| E10 | `OBS_UDP.py:341` | `recvfrom(65536)` | Đúng kích thước tối đa datagram |
| E11 | `OBS_UDP.py:146` | `SO_RCVBUF = 4 MB` | Thấp hơn chuẩn 8 MB của plugin |
| E12 | `OBS_UDP.py:144` | `SO_REUSEADDR = 1` | Cho phép hai tiến trình cùng bind 5000 → lỗi im lặng |
| E13 | `OBS_UDP.py:147` | `settimeout(1.0)` | `disconnect()` có thể chờ 1 s |
| E14 | `OBS_UDP.py:367` | decode worker `wait(0.05)` | Nhịp thức tối đa 50 ms; không phù hợp deadline 5 ms |
| E15 | `src/capture/capture_service.py:239` | `udp_manager.connect(..., target_fps=0)` | Không có decode-rate limit; đúng ý zero-lag |
| E16 | `OBS_UDP.py:574-602` | stats trả `receive_delay_ms`, `decode_delay_ms`, `processing_delay_ms`, `current_fps`, `queue_size` | UI đang phụ thuộc; phải giữ |
| E17 | `src/ui.py:10825-10851` | UI đọc đúng các key trên | Không được đổi tên/kiểu |
| E18 | `src/utils/network_feedback.py:41` | gửi cứng `FEEDBACK_PORT = 4455` | Không cấu hình được; lỗi gửi bị nuốt im lặng |
| E19 | `src/utils/network_feedback.py:58-66` | `from .network_feedback_zmq import ...` nhưng **file không tồn tại** | Mọi lần chọn ZMQ đều fallback UDP, không log |
| E20 | `src/utils/config.py:519` | `audio_feedback_ip = "192.168.10.3"` | Lệch với `config.json` (`192.168.100.1`) |
| E21 | `../OBS-xUDP-Plugin/install.ps1:5-10` | Hard-code `C:\Program Files\obs-studio`, không firewall, không VC++ | Cài đặt thất bại trên máy cài ổ D/E/Steam |
| E22 | `../OBS-xUDP-Plugin/install.ps1:2` | Banner "240 FPS" | Sai chuẩn v2.1 (144 FPS) |
| E23 | `../OBS-xUDP-Plugin/install.ps1:12-13` | `Stop-Process -Force obs64` | Có thể giết OBS đang stream mà không cảnh báo |
| E24 | `tests/test_udp_receiver_latency.py` | Chỉ 1 test, skip toàn class nếu thiếu `turbojpeg`, bind port 13110 | Không kiểm thử reassembler/timeout/zero-backlog |
| E25 | `../OBS-xUDP-Plugin/config.json:43-44` | `in_game_sens 0.235`, `mouse_dpi 1100` | Lệch chuẩn 0.23 |
| E26 | `../OBS-xUDP-Plugin/cvm_config_optimized.json:43-44` | `sens 0.235`, `dpi 800` | Lệch chuẩn 0.23 / 1100 |
| E27 | hai config mẫu `:95` | `mode_sec: WindMouse` | Lệch chuẩn "Flick sec" |
| E28 | `../OBS-xUDP-Plugin/config.json` | Thiếu `config_schema`, `flick_*`, `audio_feedback_port`, `toggle_feedback_method` | Nạp vào bot sẽ rơi về default rải rác, khó tái lập |
| E29 | `../OBS-xUDP-Plugin/udp_receiver_test.py:34-41` | Bỏ 8 byte header nhưng **không ghép mảnh** | Công cụ debug cũng sai với frame phân mảnh |
| E30 | `../OBS-xUDP-Plugin/receiver_ultra_fast.py:257` | `FrameReassembler(timeout_sec=0.005)` nhưng `UltraFastReceiver` default `0.010` (`:422`) | CLI truyền 0.005 nên đúng; API default lệch — chỉ ghi nhận, **không sửa** file này |
| E31 | `OBS_UDP.py:10-12` + toàn repo | `logging.getLogger(__name__)` nhưng **không** có `basicConfig`/handler; `debug_logger` là module riêng không bridge | `logger.info(...)` bị nuốt; `logger.error(...)` chỉ ra stderr qua `lastResort`. Người dùng **không thấy** log kết nối/lỗi trong Telemetry tab. Yêu cầu "thông báo log rõ ràng" hiện **không đạt** |

### 1.3. Xung đột cổng 5000 vs 3110 — chuỗi nhân quả

```
OBS plugin gửi tới PC2:5000
        │
        ▼
PC2 không có process nào bind 5000
        │
        ├─► kernel PC2 gửi ICMP port unreachable (nếu firewall cho phép)
        │       └─► plugin không quan tâm (UDP fire-and-forget) → mất 100% frame
        │
        └─► bot bind 0.0.0.0:3110 thành công
                └─► connect_udp() trả True (bind là đủ)
                        └─► UI "UDP connected", FPS 0, Delay 0
                                └─► người dùng kết luận "plugin hỏng"
```

**Giải pháp đồng bộ (ba lớp, không chỉ đổi một chỗ):**

1. **Lớp default:** đổi mọi default runtime về `5000` (config, receiver, service, UI fallback).
2. **Lớp migration:** bump `CURRENT_CONFIG_SCHEMA` 4 → 5; khi nạp config schema < 5 có `udp_port` thuộc `{"", "1234", "3110"}` thì ghi đè `"5000"` **một lần**, log rõ. Config schema ≥ 5 giữ nguyên giá trị người dùng (kể cả 3110 nếu họ cố ý).
3. **Lớp chẩn đoán:** bind lỗi phải trả `False` + thông điệp nêu đích danh cổng và tiến trình có thể đang chiếm; nhận được gói từ IP lạ vẫn log sender (rate-limited) để đối chiếu.

> **Không** đổi cổng beep 4455. **Không** đổi cổng DHZ/Ferrum 5000 (remote box). **Không** đổi OBS WebSocket.

### 1.4. Khoảng trống so với chuẩn v2.1

| Hạng mục v2.1 | `receiver_ultra_fast.py` (plugin) | `OBS_UDP.py` (bot) | Kết luận |
|---|---|---|---|
| Single-packet SOI | Có | Có (buffer scan) | Bot giữ, thay bằng path rõ ràng |
| Fragment 8-byte header | Có | **Không** | Thiếu P0 |
| Deadline 5.0 ms | Có | **Không** | Thiếu P0 |
| Out-of-order | Có | Không (phụ thuộc thứ tự byte) | Thiếu |
| Duplicate/interleave drop | Có | Không | Thiếu |
| Size-1 latest slot | Có (`LatestFrameQueue`) | Có một phần (`_latest_jpeg_slot`) | Chuẩn hoá, thêm counter |
| SO_RCVBUF 8 MB | Có | 4 MB | Nâng |
| WindowsTimer 1 ms | Có (CLI) | **Không** | Thiếu |
| Thread priority | Có | **Không** | Thiếu |
| TurboJPEG | ctypes tự viết | Python binding có sẵn | Giữ binding của bot (ổn định hơn) |
| OpenCV fallback | Có | Có | Giữ |
| Stats đo thật | Có | Có | Giữ + mở rộng additive |
| API tương thích UI | Không liên quan | **Bắt buộc** | Ràng buộc cứng |

**Quyết định kiến trúc:** **không import** `receiver_ultra_fast.py` từ bot. Hai thư mục được triển khai độc lập (PC1 vs PC2), đường dẫn tương đối `../OBS-xUDP-Plugin` không tồn tại trên máy đích. Giải thuật được **port có kiểm soát** vào `OBS_UDP.py`, kèm test đối chiếu hành vi. Chấp nhận trùng lặp ~120 dòng; đổi lại bot không có dependency chéo và có thể đóng gói riêng.

---

## 2. THIẾT KẾ CHI TIẾT `src/capture/OBS_UDP.py`

### 2.1. Bất biến thiết kế (invariants)

| ID | Bất biến | Cách đảm bảo |
|---|---|---|
| U1 | Frame trả về `get_current_frame()` luôn là **frame mới nhất đã giải mã xong**, không bao giờ là frame cũ hơn frame đã trả trước đó | slot size-1 + decode tuần tự một worker |
| U2 | Bộ nhớ chờ frame **tối đa 1 frame JPEG** | `LatestFrameSlot` ghi đè, không queue |
| U3 | Không giữ mảnh dở quá **5.0 ms** kể từ mảnh đầu | `process_packet()` + `expire()` kiểm tra mọi lần |
| U4 | Mọi datagram rác không làm crash/không làm phình bộ nhớ | validate độ dài, `max_frame_bytes`, counter |
| U5 | `connect()` chỉ trả `True` khi **bind thành công**; không hứa có frame | giữ nguyên semantics cũ (UI dựa vào) |
| U6 | `disconnect()` kết thúc nhanh, không treo UI | đóng socket trước (giải phóng `recvfrom`) → thread thoát trong ~1 chu kỳ 0.1 s; join tối đa 0.5 s/thread. **Thực tế thường < 150 ms; trần lý thuyết 1.0 s** nếu một thread bị OS treo. Không join vô hạn. |
| U7 | API công khai không đổi tên/không đổi kiểu trả về | bảng §2.10 |
| U8 | Stats cũ vẫn đủ key, chỉ **thêm** key mới | bảng §2.9 |
| U9 | Timer 1 ms được bật/tắt đúng cặp, nhiều receiver không tắt sớm của nhau | refcount module-level |
| U10 | Luồng nhận không bao giờ giải mã JPEG | tách thread, chỉ đẩy slot |
| U11 | Luồng giải mã không bao giờ block chờ mạng | chỉ chờ slot tối đa 1 ms/lần |
| U12 | Không dùng `SO_REUSEADDR` để tránh bind trùng im lặng | bỏ option, log lỗi rõ |

### 2.2. Cấu trúc module & hằng số

Giữ nguyên tên file/class; thêm các thành phần nội bộ **trước** `OBS_UDP_Receiver`:

```python
# ---- Hằng số cấp module ----
DEFAULT_UDP_IP = "0.0.0.0"
DEFAULT_UDP_PORT = 5000
FRAME_TIMEOUT_SEC = 0.005          # 5.0 ms = 72% chu kỳ 144 FPS (6.944 ms)
MAX_FRAME_BYTES = 10_000_000       # khớp receiver_ultra_fast.py; đủ cho 1080p Q95
FRAGMENT_HEADER = struct.Struct("<IHH")
FRAGMENT_MIN_TOTAL = 65_000        # plugin chỉ phân mảnh khi > 65 kB
MAX_FRAGMENTS = 1000
SOCKET_RCVBUF_BYTES = 8 * 1024 * 1024
SOCKET_RCVBUF_FALLBACK = 4 * 1024 * 1024
RECV_TIMEOUT_SEC = 0.1
SLOT_WAIT_SEC = 0.001
```

Thứ tự trong file:

```
imports                                   # thêm: ctypes, struct, sys (đã có: cv2, socket,
                                          # threading, time, asyncio, numpy, typing,
                                          # concurrent.futures, queue, logging, os)
_jpeg (TurboJPEG) import block            # giữ nguyên, bổ sung _DECODER_BACKEND
_DebugLoggerBridge + _install_log_bridge_once   # §2.11.1, phải đứng trước class
WindowsTimer
set_high_thread_priority
FrameReassembler
LatestFrameSlot
OBS_UDP_Receiver
OBS_UDP_Manager
```

> **Bắt buộc thêm import:** `ctypes` (Win32 timer/priority), `struct` (header `<IHH`), `sys` (platform guard). Không dùng `ctypes.windll` trực tiếp ở cấp module; chỉ trong hàm và trong `try/except`.
>
> Không đặt `timeBeginPeriod` ở import-time. Không gọi API Win32 ở cấp module ngoài `try/except`.

#### 2.2.1. Thuộc tính mới trong `OBS_UDP_Receiver.__init__`

Giữ nguyên toàn bộ attribute cũ; **thêm** (tất cả khởi tạo trước khi start thread):

```python
_install_log_bridge_once()      # xem §2.11.1

# --- v2.1 zero-lag pipeline ---
self.reassembly_timeout = float(reassembly_timeout)      # keyword-only, default 0.005
self._force_opencv = bool(force_opencv)
self._timer = WindowsTimer(1)
self._timer_active = False
self._reassembler = FrameReassembler(self.reassembly_timeout)
self._slot = LatestFrameSlot()
self._stats_lock = threading.Lock()

self._receive_priority_ok = False
self._decode_priority_ok = False
self.rcvbuf_bytes = 0
self._last_addr = None
self._last_warn_ts = 0.0
self._warn_interval = 5.0

# counters mới (không trùng tên cũ)
self.packets_received = 0
self.bytes_received = 0
self.frames_received = 0
self.frames_decoded = 0
self.decode_errors = 0
self.last_frame_id = 0
```

Chữ ký constructor:

```python
def __init__(self, ip: str = DEFAULT_UDP_IP, port: int = DEFAULT_UDP_PORT,
             target_fps: int = 60, max_workers: int = None, *,
             reassembly_timeout: float = FRAME_TIMEOUT_SEC,
             force_opencv: bool = False):
```

- `force_opencv` chỉ dùng cho test L4 và QA; mặc định `False` (dùng `_jpeg` nếu có).
- `target_fps` vẫn chỉ để monitoring, không giới hạn.
- `max_workers`, `executor`, `frame_queue` giữ nguyên để không vỡ ai đang chạm (dù nội bộ không dùng).

#### 2.2.2. Chọn decoder & `_DECODER_BACKEND`

Giữ nguyên khối import TurboJPEG hiện có (`OBS_UDP.py:14-36`), bổ sung biến cấp module:

```python
_DECODER_BACKEND = "TurboJPEG" if _jpeg is not None else "OpenCV"
```

- `_decode_jpeg_frame_raw(jpeg)` giữ chữ ký; thêm nhánh `self._force_opencv` để test L4 bỏ qua TurboJPEG dù DLL có mặt.
- **Không** đổi thứ tự thử DLL (`C:\libjpeg-turbo64\bin\turbojpeg.dll` → `<root>/turbojpeg.dll`); thêm candidate `os.path.join(os.path.dirname(__file__), "..", "..", "bin", "64bit", "turbojpeg.dll")` để bản đóng gói có DLL trong `bin/64bit` vẫn tìm thấy.
- Nếu TurboJPEG decode ném exception → fallback OpenCV cho **frame đó**; chỉ tăng `decode_errors` khi **cả hai** trả `None`. Lỗi TurboJPEG trên một frame hỏng không phải lỗi backend.
- Ghi `decoder_backend` vào stats từ `_DECODER_BACKEND` (hoặc `"OpenCV (forced)"` khi `force_opencv=True`).
- **Kiểm tra SOI/EOI trước khi gọi decoder:** `_decode_jpeg_frame_raw` giữ guard hiện tại (`len >= 100`, bắt đầu `FFD8`, kết thúc `FFD9`). Đây là guard rẻ và đã có; **không** nới lỏng nó, vì reassembler đã đảm bảo SOI nhưng chưa đảm bảo EOI.

#### 2.2.3. Kỷ luật lock (bắt buộc, tránh deadlock)

| Lock | Bảo vệ | Không bao giờ được lấy khi đang giữ |
|---|---|---|
| `FrameReassembler._lock` | `_fragments`, `_cur_*`, `_started_at`, `_buffered_bytes`, counters reassembler | bất kỳ lock nào khác |
| `LatestFrameSlot._lock` | `_item`, counters slot | bất kỳ lock nào khác |
| `_stats_lock` | counters receiver + `receive_delay`/`decode_delay`/FPS | `frame_lock`, `processing_lock` |
| `frame_lock` | `current_frame` | bất kỳ lock nào khác |
| `buffer_lock` (giữ tên cũ) | giữ làm lock bảo vệ `mjpeg_buffer` rỗng (legacy attribute, không dùng để ghép frame nữa) | bất kỳ lock nào khác |
| `processing_lock` (giữ tên cũ) | `processing_delay`, `processing_counter`, `processing_fps`, `decoding_fps` | bất kỳ lock nào khác |

**Legacy attributes phải còn (để code/test cũ không `AttributeError`):** `mjpeg_buffer` (`bytearray()` luôn rỗng), `mjpeg_start_marker`, `mjpeg_end_marker`, `max_buffer_size`, `buffer_lock`, `_frame_start_time`, `frame_queue` (`Queue(maxsize=10)` không dùng), `executor` (`None`), `processing_lock`, `frame_lock`, `_frame_ready_event`. Coder **không** xoá chúng; chỉ thêm comment `# legacy, unused by v2.1 pipeline`.

> `max_buffer_size` (4 MB) chỉ còn là thuộc tính legacy; **không** dùng để chặn frame nữa. Giới hạn thật là `MAX_FRAME_BYTES = 10 000 000` trong `FrameReassembler`, khớp `receiver_ultra_fast.py`. Đừng "đồng bộ hoá" hai con số này bằng cách hạ `MAX_FRAME_BYTES` về 4 MB — sẽ làm rớt frame 1080p chất lượng cao.
>
> `get_performance_stats()` trả `buffer_size_bytes` từ reassembler (không từ `len(mjpeg_buffer)`), nên buffer rỗng không làm sai số liệu.

**Quy tắc vàng: KHÔNG BAO GIỜ giữ lock này trong khi lấy lock khác.** Mọi khối `with` trong pipeline đều ngắn và kết thúc trước khi sang lock kế tiếp. Cụ thể:
- `_update_frame`: `with frame_lock:` (gán `current_frame`) **kết thúc**, rồi `with processing_lock:` (đếm/đo) **kết thúc**, rồi mới gọi callback (không giữ lock nào).
- `get_performance_stats`: `with processing_lock:` **kết thúc**, rồi `with _stats_lock:` — tuần tự, không lồng.
- `FrameReassembler` và `LatestFrameSlot` tự quản lock riêng; receiver **không** gọi method của chúng khi đang giữ `_stats_lock`/`frame_lock`/`processing_lock`.
- Property `buffered_bytes`/`depth`/`pending` tự lấy lock của chúng; gọi **trước** khi vào `_stats_lock`.

Nhờ vậy không có chu trình chờ (deadlock) nào có thể hình thành, kể cả khi thêm nhánh mới.

### 2.3. `WindowsTimer` — refcount toàn process

`timeBeginPeriod` là **process-wide**, không phải per-thread. Nếu hai receiver (sync + async) cùng bật rồi một cái tắt, timer có thể bị hạ trước khi receiver còn lại dừng. Thiết kế:

```python
_TIMER_LOCK = threading.Lock()
_TIMER_REFCOUNT = 0
_TIMER_ACTIVE = False
_TIMER_WARNED = False

class WindowsTimer:
    def __init__(self, period_ms: int = 1):
        self.period_ms = int(period_ms)
        self._acquired = False

    def enable(self) -> bool:
        global _TIMER_REFCOUNT, _TIMER_ACTIVE, _TIMER_WARNED
        if sys.platform != "win32":
            return False
        with _TIMER_LOCK:
            if self._acquired:
                return True
            if _TIMER_ACTIVE:
                _TIMER_REFCOUNT += 1
                self._acquired = True
                return True
            try:
                winmm = ctypes.WinDLL("winmm")
                if winmm.timeBeginPeriod(self.period_ms) == 0:
                    _TIMER_ACTIVE = True
                    _TIMER_REFCOUNT = 1
                    self._acquired = True
                    return True
            except Exception:
                pass
            if not _TIMER_WARNED:
                _TIMER_WARNED = True
                logger.warning("[UDP] timeBeginPeriod(%d) unavailable; timing falls back to OS default",
                               self.period_ms)
        return False

    def disable(self) -> None:
        global _TIMER_REFCOUNT, _TIMER_ACTIVE
        with _TIMER_LOCK:
            if not self._acquired:
                return
            self._acquired = False
            if _TIMER_REFCOUNT > 0:
                _TIMER_REFCOUNT -= 1
            if _TIMER_REFCOUNT == 0 and _TIMER_ACTIVE:
                try:
                    ctypes.WinDLL("winmm").timeEndPeriod(self.period_ms)
                except Exception:
                    pass
                _TIMER_ACTIVE = False

    def __enter__(self): self.enable(); return self
    def __exit__(self, *exc): self.disable()
```

Quy tắc:
- Chỉ `enable()` trong `connect()` / `connect_async()`; chỉ `disable()` trong `disconnect()` / `disconnect_async()` và trong nhánh lỗi sau khi đã enable.
- `disable()` idempotent (`_acquired` guard **bên trong** lock — kiểm tra ngoài lock là race).
- `disable()` **không** được gọi khi `_acquired == False`, kể cả khi `_TIMER_ACTIVE` True do instance khác giữ.
- Không đổi `period_ms` giữa chừng; nếu cần period khác, tạo instance mới sau khi instance cũ đã disable.
- Test phải patch `sys.platform`/`ctypes.WinDLL`; trên non-Windows `enable()` trả `False` và không raise.
- Ghi log **một lần** khi timer bật thất bại (`_TIMER_WARNED`); không spam mỗi connect.

### 2.4. `set_high_thread_priority()`

Giữ đúng chữ ký của plugin, trả `bool`:

```python
def set_high_thread_priority() -> bool:
    if sys.platform != "win32":
        return False
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentThread.restype = ctypes.c_void_p
        k32.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
        k32.SetThreadPriority.restype = ctypes.c_int
        return k32.SetThreadPriority(k32.GetCurrentThread(), 2) != 0  # HIGHEST
    except Exception:
        return False
```

Gọi ở **dòng đầu** của `_receive_loop()` và `_decode_worker_loop()`. Không gọi trong `__init__` (thread chưa tồn tại). Kết quả lưu vào `self._receive_priority_ok`, `self._decode_priority_ok` để stats.

> **Đánh đổi:** `THREAD_PRIORITY_HIGHEST` cho decode có thể cạnh tranh với vòng aim 144 Hz. Vì decode TurboJPEG chỉ ~0,5 ms/frame và chỉ chạy khi có frame mới, rủi ro thấp. Nếu QA đo thấy aim loop bị starvation trên máy yếu, hạ decode xuống `THREAD_PRIORITY_ABOVE_NORMAL (1)` — ghi rõ trong `02-thay-doi.md`; **không hạ luồng nhận**.

### 2.5. `FrameReassembler` — đặc tả đầy đủ

#### 2.5.1. Trạng thái

```python
class FrameReassembler:
    def __init__(self, timeout_sec: float = FRAME_TIMEOUT_SEC,
                 max_frame_bytes: int = MAX_FRAME_BYTES):
        self.timeout_sec = float(timeout_sec)
        self.max_frame_bytes = int(max_frame_bytes)
        self._lock = threading.RLock()

        self._fragments: dict[int, bytes] = {}
        self._cur_total_size = 0
        self._cur_total_frags = 0
        self._started_at = 0.0
        self._buffered_bytes = 0
        self._last_frame_ts = 0.0     # recv_ts của mảnh đầu / single packet

        # counters (đọc không cần lock trong stats; ghi dưới lock)
        self.completed_frames = 0
        self.dropped_frames = 0
        self.timeout_drops = 0
        self.restart_drops = 0
        self.invalid_packets = 0
        self.oversize_packets = 0
        self.bad_frames = 0
```

`_last_frame_ts` là mốc để tính `receive_delay_ms` (từ gói đầu tiên của frame tới lúc decode bắt đầu).

#### 2.5.2. Phân loại gói — thứ tự quyết định

Thứ tự kiểm tra **giống** reference (`receiver_ultra_fast.py:291-306`), và đây là lựa chọn **có chủ đích sau khi đã cân nhắc ngược lại**:

1. `len(data) < 2` → `invalid_packets += 1`, `None`.
2. Nếu `len(data) >= 8`: parse header `<IHH`.
3. Nếu header `total_size >= max_frame_bytes`:
   - Nếu `data` **không** bắt đầu bằng `FF D8` → `oversize_packets += 1`, `invalid_packets += 1`, `None`.
   - Nếu **có** SOI → rơi xuống bước 5 (coi là single-packet; xem lý do ở §11.A).
4. Nếu header thoả `FRAGMENT_MIN_TOTAL < total_size` **và** `1 < total_frags <= MAX_FRAGMENTS` **và** `frag_idx < total_frags` → **fragment hợp lệ**, đi nhánh ghép mảnh.
5. Nếu `data[:2] == b"\xff\xd8"` → **single-packet frame**.
6. Còn lại → `invalid_packets += 1`, `None`.

**Vì sao KHÔNG kiểm tra SOI trước (đính chính quan trọng):** một fragment hợp lệ có `total_size = 0x0001D8FF = 121 087` byte sẽ có 4 byte đầu `FF D8 01 00`, tức **bắt đầu bằng SOI**. Nếu kiểm tra SOI trước, gói này bị phân loại nhầm là single-packet: toàn bộ header + mảnh 0 bị đưa vào decoder (hỏng), và các mảnh còn lại của frame mất mảnh 0 → frame 121 KB bị mất hoàn toàn. Đây là lỗi hiếm nhưng tất định (cùng kích thước frame luôn lỗi), nên không thể bỏ qua. (Xem bảng giá trị 4 byte đầu ở §11.A.)

> **Ghi chú về reference:** `receiver_ultra_fast.py:295-312` kiểm tra `is_fragment` (header) **trước** rồi mới tới `data.startswith(b"\xff\xd8")`. Thiết kế này giữ đúng thứ tự đó. Điểm khác duy nhất là cách xử lý khi `total_size` vượt ngưỡng: reference trả `None` ngay; ta kiểm tra thêm SOI để một JPEG single-packet không bị đếm nhầm `oversize`. Với JPEG thật, `total_size` ≥ 3,23 tỷ nên **luôn** rơi vào nhánh này; nếu không kiểm tra SOI, **mọi** frame single-packet sẽ bị vứt — đây là lỗi nghiêm trọng hơn nhiều so với việc "khác reference một dòng".

**Vì sao kiểm tra header trước lại an toàn cho single-packet JPEG:** 4 byte đầu của mọi JPEG là `FF D8 FF <marker>`, với `<marker>` ∈ `C0..FE`. Do đó `total_size` đọc little-endian luôn ≥ `0xC0FFD8FF` ≈ 3,23 tỷ, **luôn** ≥ `max_frame_bytes = 10 000 000`. Ở nhánh đó, `data.startswith(b"\xff\xd8")` đúng → nhảy xuống nhánh single-packet. Điều kiện `total_size >= max_frame_bytes` kết hợp kiểm tra SOI chính là hàng rào bảo đảm cả hai chiều.

> **Hệ quả cho test:** R2 (junk 2 byte) vẫn invalid; R1 single JPEG vẫn đúng; **thêm** test biên `total_size = 0x0001D8FF` (121 087) để ghim hành vi "header thắng SOI". Nếu thiếu test này, một refactor "tối ưu" sau có thể đảo thứ tự và tái tạo lỗi.

#### 2.5.3. Thuật toán `process_packet`

```python
def process_packet(self, data: bytes, now: float | None = None) -> bytes | None:
    if not data or len(data) < 2:
        with self._lock:
            self.invalid_packets += 1
        return None
    now = time.perf_counter() if now is None else float(now)

    with self._lock:
        # (A) Deadline: mọi gói đến đều kiểm tra assembly đang dở
        if self._fragments and (now - self._started_at) > self.timeout_sec:
            self._drop_locked("timeout")

        # (B) Thử parse header TRƯỚC (an toàn: JPEG SOI cho total_size > 3 tỷ)
        if len(data) >= 8:
            total_size, frag_idx, total_frags = FRAGMENT_HEADER.unpack_from(data)

            if total_size >= self.max_frame_bytes:
                # Không phải fragment hợp lệ. Có thể là single JPEG (total_size
                # khổng lồ do FF D8 FF xx) → rơi xuống nhánh SOI bên dưới.
                if not data.startswith(b"\xff\xd8"):
                    self.oversize_packets += 1
                    self.invalid_packets += 1
                    return None

            elif (FRAGMENT_MIN_TOTAL < total_size
                  and 1 < total_frags <= MAX_FRAGMENTS
                  and frag_idx < total_frags):
                # ---- Fragment hợp lệ ----
                payload = data[8:]
                if not payload:
                    self.invalid_packets += 1
                    return None

                if self._fragments and (
                    total_size != self._cur_total_size
                    or total_frags != self._cur_total_frags
                    or frag_idx in self._fragments
                ):
                    self._drop_locked("restart")

                if not self._fragments:
                    self._cur_total_size = total_size
                    self._cur_total_frags = total_frags
                    self._started_at = now
                    self._last_frame_ts = now

                self._fragments[frag_idx] = payload
                self._buffered_bytes += len(payload)

                if len(self._fragments) == self._cur_total_frags:
                    frame = b"".join(
                        self._fragments[i] for i in range(self._cur_total_frags)
                    )
                    self._reset_locked()
                    if len(frame) == total_size and frame[:2] == b"\xff\xd8":
                        self.completed_frames += 1
                        return frame
                    self.bad_frames += 1
                    self.dropped_frames += 1
                    return None
                return None

            # total_size nằm trong (0, 65000] hoặc total_frags/frag_idx sai:
            # không phải fragment. Nếu không phải SOI → rác.

        # (C) Single packet
        if data[:2] == b"\xff\xd8":
            if self._fragments:
                self._drop_locked("restart")   # frame mới thay frame dở
            self._last_frame_ts = now
            self.completed_frames += 1
            return data

        # (D) Rác
        self.invalid_packets += 1
        return None
```

> Ghi chú: nhánh `total_size >= max_frame_bytes` chỉ tăng `oversize_packets` khi **không** bắt đầu bằng SOI. Nhờ vậy một JPEG single-packet không bị đếm nhầm là "oversize". Test R13 dùng payload **không** bắt đầu SOI để khẳng định counter này.

`_drop_locked(reason)`:

```python
if self._fragments:
    self.dropped_frames += 1
    if reason == "timeout": self.timeout_drops += 1
    elif reason == "restart": self.restart_drops += 1
self._reset_locked()
```

`_reset_locked()` xóa `_fragments`, `_cur_*`, `_started_at`, `_buffered_bytes = 0`; **không** đụng counters; **không** reset `_last_frame_ts` (frame vừa xong vẫn cần mốc cho `_ingest_datagram` đọc ngay sau đó). `reset(mark_dropped)` là API công khai dùng khi connect/disconnect: gọi `_reset_locked()` rồi **đặt** `_last_frame_ts = 0.0`.

```python
def reset(self, mark_dropped: bool = False) -> None:
    with self._lock:
        if mark_dropped and self._fragments:
            self.dropped_frames += 1
        self._reset_locked()
        self._last_frame_ts = 0.0
```

**API công khai tối thiểu của `FrameReassembler` (chốt tên, dùng thống nhất trong toàn bộ kế hoạch):**

| Thành viên | Kiểu | Ghi chú |
|---|---|---|
| `process_packet(data, now=None)` | `bytes \| None` | §2.5.3 |
| `expire(now=None)` | `bool` | §2.5.4 |
| `reset(mark_dropped=False)` | `None` | Xoá assembly + `_last_frame_ts = 0.0`. Nếu `mark_dropped` và đang có mảnh dở thì `dropped_frames += 1`. Dùng khi `connect()`/`disconnect()`. **Đặt tên `reset`**; nếu muốn tương thích plugin có thể thêm alias `reset_assembly = reset`. |
| `last_frame_ts` | `float` (property) | Đọc dưới lock; `recv_ts` của gói đầu frame gần nhất; dùng cho `receive_delay_ms` |
| `buffered_bytes` | `int` (property) | Đọc dưới lock; dùng cho `buffer_size_bytes` |
| `pending` | `bool` (property) | Đang có assembly dở |
| counters | `int` | Đọc trực tiếp trong `get_performance_stats()`; CPython đọc `int` là atomic dưới GIL nên **không cần** lấy lock reassembler (chấp nhận lệch tối đa 1 frame). Nếu Coder muốn tuyệt đối nhất quán, thêm `snapshot() -> dict` lấy `_lock` một lần; **không** gọi `snapshot()` từ trong `process_packet`/`expire`. |

`_ingest_datagram` dùng `self._reassembler.last_frame_ts` **sau** khi `process_packet` trả frame — property này phải còn giữ mốc của frame vừa hoàn tất, nên `_reset_locked()` không được xoá nó (đúng như trên).

Các property (đọc dưới lock):

```python
@property
def last_frame_ts(self) -> float:
    with self._lock:
        return self._last_frame_ts

@property
def buffered_bytes(self) -> int:
    with self._lock:
        return self._buffered_bytes

@property
def pending(self) -> bool:
    with self._lock:
        return bool(self._fragments)
```

#### 2.5.4. `expire()` — dọn assembly khi stream im lặng

Nếu mảnh cuối bị rơi và **không có gói nào đến nữa**, `process_packet` không bao giờ chạy, assembly giữ bộ nhớ vô hạn (tới frame sau). Decode worker gọi mỗi lần thức:

```python
def expire(self, now: float | None = None) -> bool:
    now = time.perf_counter() if now is None else float(now)
    with self._lock:
        if self._fragments and (now - self._started_at) > self.timeout_sec:
            self._drop_locked("timeout")
            return True
    return False
```

Worker chờ slot tối đa `SLOT_WAIT_SEC = 1 ms`; nếu hết 1 ms không có frame → `expire()`. Vậy assembly dở được dọn trong khoảng **5–6 ms** kể cả khi mạng chết hẳn.

#### 2.5.5. Bảng hành vi biên (dùng làm test oracle)

| Tình huống | `completed` | `dropped` | `timeout` | `restart` | `invalid` | `oversize` | `bad` | Trả về |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Single packet hợp lệ | +1 | 0 | 0 | 0 | 0 | 0 | 0 | data |
| Junk 2 byte không SOI, < 8 byte | 0 | 0 | 0 | 0 | +1 | 0 | 0 | None |
| Header hợp lệ mảnh 0/2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | None |
| Đủ 2 mảnh đúng thứ tự | +1 | 0 | 0 | 0 | 0 | 0 | 0 | frame |
| Đủ 2 mảnh ngược thứ tự | +1 | 0 | 0 | 0 | 0 | 0 | 0 | frame |
| Mảnh trùng `frag_idx` | 0 | +1 | 0 | +1 | 0 | 0 | 0 | None (bắt đầu assembly mới) |
| `total_size`/`total_frags` đổi giữa chừng | 0 | +1 | 0 | +1 | 0 | 0 | 0 | None |
| `frag1` đến sau `5.0001 ms` (mảnh 0 đã bị hủy) | 0 | +1 | +1 | 0 | 0 | 0 | 0 | None — frame mất, `frag1` thành assembly mới chờ mảnh 0 |
| Gói mới đến đúng `5.0000 ms` | — | 0 | 0 | 0 | 0 | 0 | 0 | xử lý bình thường (`>` là strict) |
| Single packet chen khi đang ghép | +1 | +1 | 0 | +1 | 0 | 0 | 0 | single data |
| Ghép đủ nhưng `len != total_size` | 0 | +1 | 0 | 0 | 0 | 0 | +1 | None |
| Ghép đủ nhưng không bắt đầu SOI | 0 | +1 | 0 | 0 | 0 | 0 | +1 | None |
| `total_size >= 10 000 000` **và không phải SOI** | 0 | 0 | 0 | 0 | +1 | +1 | 0 | None |
| Fragment header hợp lệ nhưng 4 byte đầu cũng là `FF D8` | — | — | — | — | 0 | 0 | 0 | ghép frame bình thường (header thắng) |
| Fragment có payload rỗng | 0 | 0 | 0 | 0 | +1 | 0 | 0 | None |

> Lưu ý test trùng mảnh: sau khi drop, mảnh vừa đến **trở thành mảnh 0 của assembly mới**. Nếu test gửi lần lượt `frag0, frag0, frag1` thì kết quả cuối là frame hoàn chỉnh và `dropped == 1`, khớp test cũ của plugin (`test_receiver_ultra_fast.py:135-144`).

#### 2.5.6. Vì sao 5.0 ms là đúng cho 144 FPS

```
Chu kỳ 144 FPS          = 1000 / 144 = 6.9444 ms
Deadline reassembly     = 5.0 ms      = 72.0% chu kỳ
Dư cho decode + slot    = 1.9444 ms
Ngân sách decode Turbo  = ~0.5 ms
Ngân sách callback/UI   = ~0.2–0.4 ms
```

Nếu deadline = 10 ms (default cũ của `UltraFastReceiver`), một frame rơi mảnh sẽ sống **qua 1.44 chu kỳ**, tức có thể ghép nhầm mảnh của frame N với mảnh của frame N+1 nếu header trùng `total_size/total_frags` — đây chính là "buffer bloat" mà yêu cầu nêu. 5 ms đảm bảo assembly luôn kết thúc **trước** khi frame kế tiếp tới (6.94 ms), nên frame lỗi bị hủy trước khi có cơ hội nhiễm frame sau.

> Nếu người dùng đổi OBS sang 240 FPS, chu kỳ 4.17 ms < 5 ms → deadline dài hơn chu kỳ. Tài liệu phải khuyến cáo **giữ 144 FPS**; constructor vẫn cho phép `reassembly_timeout=0.004` cho ai cố tình dùng 240. Không tự động suy ra từ `target_fps` vì `target_fps=0` (không giới hạn) là giá trị hợp lệ.

**Giới hạn còn lại của định dạng (phải ghi nhận, không thể sửa từ phía bot):** header 8 byte **không có frame-id/sequence number**. Nếu hai frame liên tiếp có **cùng `total_size` và cùng `total_frags`** và các gói của chúng bị hoán vị trên mạng, reassembler không có cách phân biệt mảnh của frame N với frame N+1; nó chỉ có thể dựa vào deadline để cắt. Với 144 FPS + JPEG VBR, xác suất hai frame liên tiếp trùng cả hai giá trị là thấp nhưng **không bằng 0**. Giảm thiểu:
1. Deadline 5 ms < chu kỳ 6.94 ms → cửa sổ chồng lấn bị đóng trước frame sau.
2. `bad_frames` + `completed_frames` được đưa vào stats để QA phát hiện bất thường.
3. QA thủ công M2 (JPEG Q95/640×640) kiểm tra ảnh không bị "xé" chéo frame.
4. Nếu cần triệt để: đề xuất **plugin** thêm `uint32 frame_id` (header 12 byte) ở phiên bản sau — **ngoài phạm vi đợt này**, ghi vào backlog.

### 2.6. `LatestFrameSlot` — size-1, zero backlog

```python
class LatestFrameSlot:
    def __init__(self):
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._item = None            # (jpeg: bytes, recv_ts: float, frame_id: int)
        self.enqueued = 0
        self.dropped_unconsumed = 0

    def put(self, item) -> None:
        with self._lock:
            if self._item is not None:
                self.dropped_unconsumed += 1
            self._item = item
            self.enqueued += 1
            self._event.set()        # set trong lock

    def get_nowait(self):
        with self._lock:
            item, self._item = self._item, None
            self._event.clear()      # clear trong cùng lock với put() → không mất tín hiệu
            return item

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)

    def clear(self) -> None:
        with self._lock:
            self._item = None
            self._event.clear()

    def wake(self) -> None:
        """Đánh thức consumer đang wait() mà không đẩy frame (dùng khi shutdown)."""
        self._event.set()

    @property
    def pending(self) -> bool:
        with self._lock:
            return self._item is not None

    @property
    def depth(self) -> int:
        with self._lock:
            return 1 if self._item is not None else 0

    @property
    def drops(self) -> int:
        with self._lock:
            return self.dropped_unconsumed
```

**Vì sao không dùng `queue.Queue(maxsize=1)`:** `Queue.put()` block khi đầy, buộc producer phải chờ consumer — đúng thứ gây lag. `put_nowait()` + `get_nowait()` có thể làm mất frame **mới** nếu consumer lấy sai thời điểm. Ghi đè trực tiếp dưới lock đảm bảo **frame mới luôn thắng**.

**Tương thích:** thay hoàn toàn `self._latest_jpeg_slot` (tuple 2 phần tử) + `self._frame_ready_event` bằng `self._slot`. Đã kiểm tra toàn repo: **không** file nào ngoài `OBS_UDP.py` đọc `_latest_jpeg_slot`/`_frame_ready_event` (grep chỉ ra chính file này). Vì vậy **không** cần property tương thích phức tạp; chỉ cần giữ hai attribute legacy ở dạng vô hại (`_frame_ready_event = threading.Event()` không dùng) để tránh `AttributeError` nếu có script ngoài repo chạm vào.

Quy ước nội bộ:

```python
def _publish_frame(self, jpeg_data: bytes, recv_ts: float) -> None:
    with self._stats_lock:
        self.frames_received += 1
        frame_id = self.frames_received
    self._slot.put((jpeg_data, recv_ts, frame_id))
```

`frame_id` là `frames_received` (đơn điệu tăng, bắt đầu từ 1); dùng cho `last_frame_id` trong stats và để QA đối chiếu log.

### 2.7. Luồng nhận & luồng giải mã

#### 2.7.1. Nhận

```python
def _receive_loop(self):
    self.is_receiving = True
    self._receive_priority_ok = set_high_thread_priority()
    logger.info("[UDP] receive loop started (priority=%s)", self._receive_priority_ok)
    sock = self.socket                 # giữ tham chiếu cục bộ: disconnect() sẽ set self.socket = None
    if sock is None:
        self.is_receiving = False
        return
    try:
        while not self.stop_event.is_set() and self.is_connected:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError as exc:
                if self.is_connected and not self.stop_event.is_set():
                    logger.error("[UDP] socket error: %s", exc)
                break
            recv_ts = time.perf_counter()
            if addr != self._last_addr:
                self._last_addr = addr
                logger.info("[UDP] stream source: %s:%d", addr[0], addr[1])
            self._ingest_datagram(data, recv_ts)
    finally:
        self.is_receiving = False
        logger.info("[UDP] receive loop ended")
```

`_ingest_datagram`:

```python
def _ingest_datagram(self, data: bytes, recv_ts: float):
    """Receive thread / asyncio protocol only. Never decodes."""
    # Đếm ở đây (không đếm trong receive loop) để async path cũng có số liệu.
    with self._stats_lock:
        self.packets_received += 1
        self.bytes_received += len(data)

    frame = self._reassembler.process_packet(data, now=recv_ts)
    if frame is None:
        return
    first_ts = self._reassembler.last_frame_ts or recv_ts
    self._publish_frame(frame, first_ts)
```

`_publish_frame` (định nghĩa ở §2.6) tăng `frames_received`, dùng nó làm `frame_id`, và `put()` vào slot. Tách hàm để async path và test dùng chung đúng một đường.

`_process_mjpeg_data(data, receive_time)` trở thành alias mỏng:

```python
def _process_mjpeg_data(self, data: bytes, receive_time: float):
    """Backward-compatible ingest entry (async protocol + legacy tests)."""
    self._ingest_datagram(data, receive_time)
```

> Đây là điểm quan trọng để test cũ `test_udp_receiver_latency.py:40` vẫn chạy: nó gọi `_process_mjpeg_data(jpeg_bytes, now)` với **single packet**, không cần socket.

#### 2.7.2. Giải mã

```python
def _decode_worker_loop(self):
    self._decode_priority_ok = set_high_thread_priority()
    consecutive_errors = 0
    while not self.stop_event.is_set() and self.is_connected:
        try:
            item = self._slot.get_nowait()
            if item is None:
                if not self._slot.wait(SLOT_WAIT_SEC):
                    self._reassembler.expire()
                continue

            jpeg_data, recv_ts, frame_id = item
            t0 = time.perf_counter()
            frame = self._decode_jpeg_frame_raw(jpeg_data)
            t1 = time.perf_counter()

            if frame is None:
                with self._stats_lock:
                    self.decode_errors += 1
                consecutive_errors = 0      # decode trả None là hợp lệ, không phải lỗi vòng lặp
                continue

            with self._stats_lock:
                self.decode_delay = (t1 - t0) * 1000.0
                self.receive_delay = max(0.0, (t0 - recv_ts) * 1000.0)
                self.last_frame_id = frame_id
                self.frames_decoded += 1

            consecutive_errors = 0
            self._update_frame(frame)

        except Exception as exc:
            # Không dùng logger.exception mỗi vòng: nếu lỗi lặp ở 144 Hz sẽ
            # tự tạo lag + làm ngập debug log.
            consecutive_errors += 1
            if consecutive_errors == 1 or consecutive_errors % 720 == 0:
                logger.error("[UDP] decode worker error (x%d): %s",
                             consecutive_errors, exc, exc_info=True)
            continue

    logger.info("[UDP] decode loop ended")
```

- `consecutive_errors % 720` ≈ 1 lần/5 giây ở 144 Hz.
- `logger.exception` chỉ dùng cho lỗi khởi tạo (connect), không dùng trong vòng lặp nóng.

**Vì sao `get_nowait()` trước rồi mới `wait()`:** tránh race "producer set event đúng lúc consumer clear" làm mất tín hiệu. Nếu slot có hàng, lấy ngay; nếu rỗng, chờ tối đa 1 ms; hết 1 ms thì dọn assembly quá hạn.

> **`Event.wait(0.001)` không cần timer 1 ms để đúng:** khi có frame mới, `put()` gọi `set()` và đánh thức worker **ngay**, không phụ thuộc timeout. Con số 1 ms chỉ là **nhịp dọn rác** khi stream im lặng; nếu `timeBeginPeriod` không bật được, nhịp này có thể thành ~15,6 ms — assembly dở vẫn được dọn, chỉ chậm hơn, và **không** thêm latency cho frame đang chạy. Đây là lý do thiết kế không đặt `wait(0.0001)` (sẽ quay CPU vô ích) và không đặt `wait(0.05)` như bản cũ (expire quá muộn).

**Thứ tự ưu tiên frame:** nếu trong 1 ms có 3 frame tới, slot chỉ giữ frame cuối; `dropped_unconsumed` tăng 2. Đây là **zero backlog chủ đích**, không phải lỗi.

#### 2.7.3. Callback & `_update_frame`

Giữ nguyên hành vi hiện tại (`frame.copy()` cho callback, đo `processing_delay_ms`, cập nhật `decoding_fps`). Bổ sung:
- Bọc phần đọc/ghi counter `processing_delay`/`processing_counter`/`processing_fps`/`decoding_*` bằng `self.processing_lock` (không phải `_stats_lock`).
- Nếu cả `frame_callback` và `frame_callback_async` đều None, `processing_delay = 0.0` (giữ như cũ).
- Không gọi callback trên receive thread.

#### 2.7.4. Ghi `current_fps` dưới lock

`_update_fps_counters()` hiện tăng `fps_counter` và gán `current_fps` **không lock**. Với pipeline mới, `get_performance_stats()` đọc `current_fps` dưới `_stats_lock`; để tránh torn read/race về ngữ nghĩa, chuyển thân hàm vào `with self._stats_lock:`. Hàm này chỉ chạy 1 lần/frame (~144 Hz), lock ngắn, không ảnh hưởng throughput.

Tương tự, `decoding_counter`/`decoding_fps`/`last_decoding_time` giữ dưới `processing_lock` (như bản cũ) — **không** chuyển sang `_stats_lock`, để tránh hai nguồn ghi.

> Nếu Coder thấy việc `_update_frame` lấy `processing_lock` hai lần (một cho decoding FPS, một cho processing FPS) là thừa, có thể gộp thành **một** khối `with processing_lock:` bao cả hai phần đếm; vẫn phải kết thúc khối trước khi gọi callback.

### 2.8. `connect` / `disconnect` / async

#### 2.8.1. `connect()`

```python
def connect(self) -> bool:
    try:
        if self.is_connected:
            self.disconnect()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket = sock          # gán NGAY: nếu bind lỗi, helper đóng được
        # KHÔNG set SO_REUSEADDR: bind trùng phải fail rõ ràng.
        actual_rcvbuf = 0
        for size in (SOCKET_RCVBUF_BYTES, SOCKET_RCVBUF_FALLBACK):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, size)
                actual_rcvbuf = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
                break
            except OSError:
                continue
        sock.settimeout(RECV_TIMEOUT_SEC)
        sock.bind((self.ip, int(self.port)))
        self.rcvbuf_bytes = actual_rcvbuf

        self._timer_active = self._timer.enable()
        self._reassembler.reset(mark_dropped=False)
        self._slot.clear()
        self._last_addr = None
        self.stop_event.clear()
        self.is_connected = True
        # Đặt TRƯỚC khi start thread: UI gọi is_stream_active() ngay sau connect()
        # sẽ thấy True, không phải chờ thread kịp chạy (race cũ).
        self.is_receiving = True

        self.receive_thread = threading.Thread(
            target=self._receive_loop, name="UDPReceiveWorker", daemon=True)
        self.receive_thread.start()
        self.processing_thread = threading.Thread(
            target=self._decode_worker_loop, name="UDPDecodeWorker", daemon=True)
        self.processing_thread.start()

        logger.info("[UDP] listening on %s:%d rcvbuf=%d timer=%s decoder=%s",
                    self.ip, self.port, actual_rcvbuf, self._timer_active, _DECODER_BACKEND)
        return True
    except OSError as exc:
        logger.error("[UDP] bind %s:%d failed: %s. Port 5000 co the dang bi chiem boi "
                     "receiver_ultra_fast.py hoac mot instance CVM-colorBot khac. "
                     "Dong tien trinh do, hoac doi Port o ca OBS va bot.",
                     self.ip, self.port, exc)
        self._abort_connect()
        return False
    except Exception as exc:
        logger.error("[UDP] unexpected connect error on %s:%d: %s",
                     self.ip, self.port, exc, exc_info=True)
        self._abort_connect()
        return False
```

`_abort_connect()` (dọn mọi thứ dở dang, idempotent):

```python
def _abort_connect(self):
    self.is_connected = False
    self.is_receiving = False
    self.stop_event.set()
    self._close_socket_quietly()
    self._timer_active = False
    self._timer.disable()
    self._slot.clear()
    self._reassembler.reset(mark_dropped=False)
    self.receive_thread = None
    self.processing_thread = None
```

`_close_socket_quietly()` là helper nội bộ:

```python
def _close_socket_quietly(self):
    sock, self.socket = self.socket, None
    if sock is not None:
        try:
            sock.close()
        except OSError:
            pass
```

Chi tiết:
- **Bỏ `SO_REUSEADDR`.** UDP không có `TIME_WAIT`; không cần. Bind trùng phải lỗi rõ thay vì chia gói ngẫu nhiên giữa hai process.
- `SO_RCVBUF` thử 8 MB → 4 MB; log giá trị **thực** (`getsockopt`) vì Windows có thể cap.
- `settimeout(0.1)` thay 1.0 để `disconnect()` nhanh; 0.1 s không ảnh hưởng throughput vì `recvfrom` thức ngay khi có gói.
- Timer bật **sau** bind thành công, tránh bật rồi phải tắt khi lỗi.
- Reset reassembler + slot trước khi start thread.
- `target_fps`: giữ nguyên, không dùng để giới hạn. `frame_interval = 1/fps if fps > 0 else 0`.
- `is_receiving = True` đặt **trước** khi start thread, để `capture_service.is_connected()`/`is_stream_active()` không trả `False` trong khoảng race ngắn ngay sau `connect()`. Nếu receive thread chết vì lỗi socket, `finally` đặt lại `False`.

#### 2.8.2. `disconnect()`

Thứ tự bắt buộc:

```
1. is_connected = False; is_receiving = False
2. stop_event.set(); slot.wake() (đánh thức worker đang chờ 1 ms)
3. đóng socket TRƯỚC (giải phóng recvfrom)
4. join receive_thread 0.5 s
5. join processing_thread 0.5 s
6. reassembler.reset(mark_dropped=True)  (nếu còn mảnh dở)
7. slot.clear(); current_frame = None
8. timer.disable()
9. log
```

- Không join vô hạn; nếu thread không chết sau 1 s, log warning và để daemon thread tự kết thúc (không treo UI).
- `processing_thread` có thể là `None` (test) → guard.
- `disconnect()` gọi nhiều lần phải an toàn.
- `self.socket is None` (test chưa từng `connect()`) → bỏ qua bước đóng, vẫn reset state + timer.disable() (idempotent).

#### 2.8.3. Tương thích với test cũ đang tồn tại

`tests/test_udp_receiver_latency.py` hiện tại (sẽ được viết lại ở T2, nhưng **trong lúc Coder làm C2–C4 nó vẫn phải xanh**) làm như sau:

```python
self.receiver = OBS_UDP_Receiver(ip="127.0.0.1", port=13110, target_fps=144)
...
self.receiver.is_connected = True
self.receiver.processing_thread = threading.Thread(target=self.receiver._decode_worker_loop, daemon=True)
self.receiver.processing_thread.start()
self.receiver._process_mjpeg_data(self.jpeg_bytes, now)
```

Do đó:
- `__init__` **không** được yêu cầu socket/timer/thread để tạo `_slot`/`_reassembler`/`_stats_lock`.
- `_decode_worker_loop` chỉ phụ thuộc `stop_event`, `is_connected`, `_slot`, `_reassembler`, `_stats_lock`, `_update_frame` — tất cả có sẵn từ `__init__`.
- `_process_mjpeg_data` phải hoạt động **không cần** `connect()`.
- `disconnect()` phải chịu được `socket is None`, `receive_thread is None`, `processing_thread` là thread do test tạo.
- `tearDown` gọi `disconnect()`; nếu thread test còn chạy, `stop_event.set()` + join 0.5 s là đủ.

> Coder **không được** để test cũ đỏ trong suốt quá trình C2–C4. Nếu buộc phải thay đổi hành vi, cập nhật test **cùng lúc** và ghi rõ trong `02-thay-doi.md`.

#### 2.8.4. Chấm dứt hỗ trợ "raw byte-stream" không header (quyết định có chủ đích)

Bản cũ ghép JPEG bằng cách nối byte và tìm `FFD8…FFD9`, nên **có thể** nhận được một luồng MJPEG bị chia nhỏ tuỳ ý **không có header 8 byte** (ví dụ một sender tự viết). Bản v2.1 **không** hỗ trợ dạng đó nữa vì:

1. Yêu cầu chỉ định nghĩa đúng 2 dạng: single-packet SOI và fragment 8-byte.
2. Duy trì cả hai cơ chế làm tăng nhánh mã, tăng nguy cơ ghép nhầm và làm mờ nguyên nhân lỗi.
3. `obs-color-correction.dll` (nguồn duy nhất trong hệ thống) không bao giờ gửi dạng thứ ba.

**Giảm thiểu:** ghi rõ trong `HUONG_DAN_SU_DUNG.txt` ("Receiver v2.1 chỉ chấp nhận single-packet hoặc fragment 8-byte của plugin"); log DEBUG rate-limited khi gặp datagram không SOI và không qua validate header (`invalid_packets` tăng). Nếu tương lai cần, thêm `legacy_stream_mode=False` bằng keyword-only, **không** bật mặc định.

#### 2.8.5. Async path

- `_UDPProtocol.datagram_received` → `receiver._ingest_datagram(data, time.perf_counter())`.
- `_connect_asyncio`: tạo endpoint, bật timer, start decode worker (nếu chưa), set `is_connected/is_receiving`; nếu lỗi → timer.disable, trả `False`.
- `_disconnect_asyncio`: stop worker, đóng transport, timer.disable, clear slot, reset reassembler. Giữ nguyên logic stop thread/loop.
- **Không** chạy decode trên event-loop thread. Chỉ ingest.
- Async path dùng cùng `FrameReassembler`/`LatestFrameSlot`; không có đường code thứ hai.

**Vấn đề cần xử lý tường minh — `create_datagram_endpoint` không cho set `SO_RCVBUF` sau khi bind:**
`asyncio.loop.create_datagram_endpoint()` tạo socket nội bộ với buffer mặc định của OS (~64 KB), **không** phải 8 MB. Ở 144 FPS với frame 7–8 KB thì 64 KB chỉ đủ ~8 frame (~55 ms) — chấp nhận được cho burst ngắn nhưng không đạt chuẩn v2.1. Thiết kế: tạo socket **trước**, set option, rồi truyền vào endpoint.

```python
async def _connect_asyncio(self):
    if self.is_connected:
        await self._disconnect_asyncio()

    loop = asyncio.get_running_loop()

    # Tạo socket thủ công để set SO_RCVBUF/không REUSEADDR trước khi bind.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for size in (SOCKET_RCVBUF_BYTES, SOCKET_RCVBUF_FALLBACK):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, size)
                self.rcvbuf_bytes = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
                break
            except OSError:
                continue
        sock.setblocking(False)
        sock.bind((self.ip, int(self.port)))
    except OSError as exc:
        sock.close()
        logger.error("[UDP][async] bind %s:%d failed: %s", self.ip, self.port, exc)
        return False

    try:
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: OBS_UDP_Receiver._UDPProtocol(self),
            sock=sock,            # truyền socket đã cấu hình, KHÔNG truyền local_addr
        )
    except Exception as exc:
        sock.close()
        logger.error("[UDP][async] endpoint failed: %s", exc, exc_info=True)
        return False

    self._transport, self._protocol = transport, protocol
    self._timer_active = self._timer.enable()
    self._reassembler.reset(mark_dropped=False)
    self._slot.clear()
    self.stop_event.clear()
    self.is_connected = True
    self.is_receiving = True

    if not self.processing_thread or not self.processing_thread.is_alive():
        self.processing_thread = threading.Thread(
            target=self._decode_worker_loop, name="UDPDecodeWorker", daemon=True)
        self.processing_thread.start()

    logger.info("[UDP][async] listening on %s:%d rcvbuf=%d timer=%s",
                self.ip, self.port, self.rcvbuf_bytes, self._timer_active)
    return True
```

Quy tắc:
- Khi truyền `sock=`, **không** truyền `local_addr` (asyncio sẽ raise nếu cả hai). Socket đã bind thủ công.
- `sock.setblocking(False)` là bắt buộc trước khi giao cho asyncio.
- `rcvbuf_bytes` được ghi từ async path để stats phản ánh đúng.
- Nếu endpoint fail, đóng `sock` (asyncio không nhận ownership khi raise trước khi tạo transport).
- `_disconnect_asyncio` phải `self._transport.close()` rồi chờ ngắn; socket do transport sở hữu sẽ được đóng theo, **không** đóng lần hai.
- Test L1 không chạm async path; nếu Tester muốn phủ, thêm test riêng kiểm tra `rcvbuf_bytes > 0` sau `connect_async()` — **không bắt buộc** trong bộ 15 case.

### 2.9. Hợp đồng `get_performance_stats()`

**Key cũ — giữ nguyên tên, kiểu, ý nghĩa:**

| Key | Kiểu | Ý nghĩa | Nguồn |
|---|---|---|---|
| `current_fps` | float | FPS frame giải mã xong trong cửa sổ 1 s | `_update_fps_counters` |
| `processing_fps` | float | FPS callback xử lý | `_update_frame` |
| `decoding_fps` | float | FPS decode | `_update_frame` |
| `target_fps` | int | giá trị cấu hình, chỉ monitoring | `self.target_fps` |
| `receive_delay_ms` | float | từ gói đầu tiên của frame → bắt đầu decode (gồm thời gian chờ slot) | decode worker |
| `decode_delay_ms` | float | thời gian TurboJPEG/OpenCV cho frame gần nhất | decode worker |
| `processing_delay_ms` | float | thời gian callback frame gần nhất | `_update_frame` |
| `is_connected` | bool | đã bind + start thread | state |
| `is_receiving` | bool | receive loop đang chạy | state |
| `buffer_size_bytes` | int | byte JPEG đang giữ trong assembly dở (0 khi rảnh) | reassembler |
| `queue_size` | int | **0 hoặc 1** — độ sâu slot | slot |
| `max_workers` | int | giữ nguyên | constructor |

**Key mới — additive, UI cũ bỏ qua an toàn:**

| Key | Kiểu | Ý nghĩa |
|---|---|---|
| `queue_drops` | int | số frame bị ghi đè trong slot |
| `reassembly_drops` | int | tổng frame dở bị hủy |
| `timeout_drops` | int | hủy do quá 5 ms |
| `restart_drops` | int | hủy do frame mới/mảnh trùng |
| `invalid_packets` | int | datagram không hợp lệ |
| `oversize_packets` | int | header khai báo `>= 10 000 000` **và** datagram không phải SOI |
| `bad_frames` | int | ghép đủ nhưng sai kích thước/SOI |
| `frames_received` | int | frame hoàn chỉnh đẩy vào slot |
| `frames_decoded` | int | frame decode thành công |
| `decode_errors` | int | decode thất bại |
| `packets_received` | int | datagram nhận |
| `bytes_received` | int | byte nhận |
| `decoder_backend` | str | `"TurboJPEG"` / `"OpenCV"` |
| `timer_active` | bool | `timeBeginPeriod(1)` đang giữ |
| `rcvbuf_bytes` | int | SO_RCVBUF thực |
| `receive_priority_ok` | bool | đặt priority luồng nhận |
| `decode_priority_ok` | bool | đặt priority luồng decode |
| `last_frame_id` | int | id frame gần nhất |

Tất cả key của receiver đọc trong `with self._stats_lock:` để tránh torn read; riêng `buffer_size_bytes` lấy từ `reassembler.buffered_bytes` (property tự lock) và `queue_size` lấy từ `slot.depth` (property tự lock) — **không** lấy `_stats_lock` lồng với hai lock đó. Không đổi `current_fps` sang int; UI format `:.1f`.

Khung triển khai (thứ tự lock đúng, không lồng ngược):

```python
def get_performance_stats(self) -> dict:
    # 1) Hai property tự lock, lấy TRƯỚC _stats_lock để không lồng lock.
    buffered = self._reassembler.buffered_bytes
    queue_size = self._slot.depth
    queue_drops = self._slot.drops

    # 2) processing_* + decoding_fps đọc dưới processing_lock (giữ nguyên như bản cũ).
    with self.processing_lock:
        processing_fps = self.processing_fps
        processing_delay = self.processing_delay
        decoding_fps = self.decoding_fps

    # 3) counters/FPS/delay của receiver.
    with self._stats_lock:
        return {
            # --- key cũ, giữ nguyên ---
            "current_fps": self.current_fps,
            "processing_fps": processing_fps,
            "decoding_fps": decoding_fps,
            "target_fps": self.target_fps,
            "receive_delay_ms": self.receive_delay,
            "decode_delay_ms": self.decode_delay,
            "processing_delay_ms": processing_delay,
            "is_connected": self.is_connected,
            "is_receiving": self.is_receiving,
            "buffer_size_bytes": buffered,
            "queue_size": queue_size,
            "max_workers": self.max_workers,
            # --- key mới ---
            "queue_drops": queue_drops,
            "reassembly_drops": self._reassembler.dropped_frames,
            "timeout_drops": self._reassembler.timeout_drops,
            "restart_drops": self._reassembler.restart_drops,
            "invalid_packets": self._reassembler.invalid_packets,
            "oversize_packets": self._reassembler.oversize_packets,
            "bad_frames": self._reassembler.bad_frames,
            "frames_received": self.frames_received,
            "frames_decoded": self.frames_decoded,
            "decode_errors": self.decode_errors,
            "packets_received": self.packets_received,
            "bytes_received": self.bytes_received,
            "decoder_backend": ("OpenCV (forced)" if self._force_opencv else _DECODER_BACKEND),
            "timer_active": self._timer_active,
            "rcvbuf_bytes": self.rcvbuf_bytes,
            "receive_priority_ok": self._receive_priority_ok,
            "decode_priority_ok": self._decode_priority_ok,
            "last_frame_id": self.last_frame_id,
        }
```

> `current_fps`, `receive_delay`, `decode_delay` được ghi dưới `_stats_lock` ở decode worker; `get_performance_stats` chỉ đọc. `processing_fps`/`processing_delay`/`decoding_fps` giữ dưới `processing_lock` như bản cũ — **không** đổi nơi ghi, tránh làm lệch ngữ nghĩa `_update_frame`. Thứ tự lấy lock trong hàm này là `processing_lock` → `_stats_lock`; **không** lồng ngược ở bất kỳ chỗ nào khác.

### 2.10. Bảng tương thích API (hợp đồng cứng)

| API / attribute | Ai dùng | Yêu cầu |
|---|---|---|
| `OBS_UDP_Receiver(ip, port, target_fps, max_workers=None)` | `OBS_UDP_Manager`, test | Giữ 4 tham số cũ; **thêm keyword-only** `reassembly_timeout=0.005`, `force_opencv=False` |
| `.ip`, `.port`, `.target_fps` | UI, manager | Giữ |
| `.is_connected`, `.is_receiving` | `capture_service.is_connected`, `is_stream_active` | Giữ bool |
| `.connect() -> bool` | manager | Giữ |
| `.disconnect() -> None` | manager, cleanup | Giữ, idempotent |
| `.connect_async() -> bool` | manager | Giữ |
| `.disconnect_async() -> None` | manager | Giữ |
| `.get_current_frame() -> np.ndarray|None` | `capture_service.read_frame`, `get_frame_dimensions` | **Zero-copy**, không copy |
| `.get_performance_stats() -> dict` | `ui._update_performance_stats` | Đủ key bảng §2.9 |
| `.set_target_fps(int)` | UI cũ | Giữ, không giới hạn |
| `.update_connection_params(ip, port)` | UI cũ | Giữ |
| `.set_frame_callback(cb)` | ngoài | Giữ |
| `.set_frame_callback_async(cb)` | ngoài | Giữ |
| `._process_mjpeg_data(data, ts)` | async protocol, test cũ | Giữ làm alias ingest |
| `._decode_worker_loop()` | test cũ | Giữ tên |
| `._frame_processing_loop()` | tương thích | Alias `_decode_worker_loop` |
| `._decode_jpeg_frame(jpeg, ts)` | test/tương thích | Giữ, cập nhật stats |
| `._decode_jpeg_frame_raw(jpeg)` | nội bộ/test | Giữ |
| `._is_frame_corrupted(frame)` | nội bộ | Giữ staticmethod |
| `._update_frame(frame, receive_time=0.0)` | nội bộ | Giữ |
| `._latest_jpeg_slot` | không ai trong repo dùng | **Không** cần property; giữ `_frame_ready_event` legacy. Nếu Coder thấy an toàn có thể thêm property read-only trả `(jpeg, ts)` hoặc `None`; không bắt buộc. |
| `OBS_UDP_Manager()` | `capture_service` | Giữ |
| `.create_receiver(ip, port, target_fps=60)` | ngoài | Giữ; default port đổi 5000 |
| `.connect(ip, port, target_fps=60)` | `capture_service` | Giữ |
| `.connect_async(...)` | ngoài | Giữ |
| `.disconnect()`, `.disconnect_async()` | `capture_service` | Giữ |
| `.get_receiver()` | `capture_service`, UI | Giữ |
| `.is_stream_active()` | `capture_service` | Giữ |
| `.is_connected` (manager) | `capture_service.cleanup` | Giữ |

> **Không** đổi `get_current_frame()` sang trả bản copy. UI đọc mỗi frame; copy 320×320×3 (~300 KB) ở 144 Hz là ~43 MB/s vô ích. Chỉ callback mới copy (như hiện tại).

### 2.11. Xử lý lỗi & logging

| Tình huống | Hành vi | Log |
|---|---|---|
| Bind lỗi `WSAEADDRINUSE` | trả `False`, đóng socket, tắt timer | ERROR nêu port + gợi ý đóng process khác |
| Bind lỗi `WSAEADDRNOTAVAIL` | trả `False` | ERROR: IP không thuộc máy, dùng 0.0.0.0 |
| `recvfrom` OSError khi đang connected | dừng loop, set `is_receiving=False` | ERROR |
| Datagram rác | bỏ qua, tăng counter | DEBUG rate-limited (1/5 s) |
| Frame quá hạn | hủy, tăng `timeout_drops` | DEBUG rate-limited |
| Decode lỗi | bỏ frame, tăng `decode_errors` | WARNING rate-limited (1/5 s) |
| Timer không bật được | vẫn chạy, `timer_active=False` | WARNING một lần |
| Priority không đặt được | vẫn chạy | WARNING một lần |
| `disconnect` thread không join | tiếp tục, không treo | WARNING |

**Rate limiting:** dùng `self._last_warn_ts` + `_warn_interval = 5.0`; tuyệt đối không log mỗi gói ở 144 FPS (sẽ tự tạo lag).

#### 2.11.1. Cầu nối `logging` → `debug_logger` (bắt buộc để "log rõ ràng" là thật)

Hiện `OBS_UDP.py` dùng `logging.getLogger(__name__)` nhưng **không có handler nào**; `src/utils/debug_logger.py` là module độc lập (deque + Telemetry tab). Vì vậy mọi `logger.info("[UDP] listening on 0.0.0.0:5000")` sẽ **không** xuất hiện ở đâu người dùng thấy. Để yêu cầu "thông báo log rõ ràng" có giá trị thực, thêm **một** bridge tối thiểu ngay trong `OBS_UDP.py` (không sửa `debug_logger.py`, không đụng module khác):

```python
class _DebugLoggerBridge(logging.Handler):
    """Forward UDP receiver records into the app's in-UI debug log."""

    def emit(self, record):
        try:
            from src.utils.debug_logger import log_print
            msg = self.format(record)
            log_print(f"[UDP] {msg}")
        except Exception:
            pass


def _install_log_bridge_once():
    if getattr(logger, "_cvm_bridge_installed", False):
        return
    handler = _DebugLoggerBridge()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False          # tránh nhân đôi ra root/stderr
    logger._cvm_bridge_installed = True
```

- Gọi `_install_log_bridge_once()` **một lần** ở đầu `OBS_UDP_Receiver.__init__` (không ở import-time, để tránh side-effect khi test chỉ import module).
- Chỉ bridge mức `INFO` trở lên → không có log per-packet (mọi log per-packet đều là `DEBUG` và bị lọc).
- Nếu `debug_logger` import lỗi (chạy test độc lập) → handler nuốt exception, receiver vẫn chạy.
- `propagate = False` ngăn record xuất hiện hai lần nếu app sau này gọi `logging.basicConfig`.
- **Không** log đối tượng `addr` thô mỗi gói; chỉ log khi sender **đổi** (1 lần/phiên) và khi bind/lỗi/timer.
- Test L15 kiểm tra: sau `connect()` thất bại, `debug_logger.get_recent_logs()` có chứa chuỗi `"bind"` (chứng minh bridge hoạt động). Nếu môi trường test không có `debug_logger`, skip assertion đó với lý do rõ.

> **Vì sao không sửa `debug_logger.py`:** đó là hạ tầng UI/Telemetry đã ổn định, có test riêng (`test_ui_perf.py`). Thêm bridge cục bộ giữ ranh giới thay đổi nhỏ và có thể revert độc lập.

### 2.12. Ngân sách hiệu năng (mục tiêu, không phải số đo)

| Công đoạn | Ngân sách | Ghi chú |
|---|---|---|
| `recvfrom` + classify + reassembler (single packet) | ≤ 30 µs | 1 lần lock, 1 so sánh SOI |
| Reassembler 2 mảnh | ≤ 80 µs | join 2 bytes object ~7 KB |
| Slot put/get | ≤ 5 µs | lock ngắn |
| TurboJPEG 320×320 | ~0.3–0.6 ms | tùy CPU |
| OpenCV fallback | ~0.8–2.0 ms | chỉ khi thiếu TurboJPEG |
| `receive_delay` mục tiêu | < 1.0 ms | gồm chờ slot |
| `decode_delay` mục tiêu | < 1.5 ms | test §6.3 (L2/L3) |
| Tổng pipeline mục tiêu | < 3.0 ms | UI đổi màu pill khi < 3 ms (`ui.py:10848`) |
| Bộ nhớ tối đa cho frame | ≤ 10 MB + 1 slot | không tích lũy |

### 2.13. Những gì bị xoá / thay thế trong `OBS_UDP.py` (để diff rõ ràng)

| Hạng mục cũ | Dòng | Hành động | Thay bằng |
|---|---|---|---|
| `socket.setsockopt(SO_REUSEADDR, 1)` | `:144` | **Xoá** | không có; bind trùng phải lỗi |
| `SO_RCVBUF = 4 MB` | `:146` | Thay | 8 MB → fallback 4 MB, log thực tế |
| `settimeout(1.0)` | `:147` | Thay | `RECV_TIMEOUT_SEC = 0.1` |
| `bind((self.ip, self.port))` không bọc lỗi | `:150` | Thay | try/except + `_abort_connect()` + log chẩn đoán |
| Thân `_process_mjpeg_data` (buffer + find FFD8/FFD9) | `:400-458` | **Xoá toàn bộ thân** | `_ingest_datagram` + `FrameReassembler` |
| `_frame_start_time` logic | `:78, 409-437` | Xoá logic | `reassembler.last_frame_ts` |
| `_latest_jpeg_slot` tuple | `:76, 450-452` | Thay | `LatestFrameSlot` |
| `_frame_ready_event` dùng thật | `:77, 367, 452` | Ngừng dùng | `slot.wait()` / `slot.wake()`; giữ attribute rỗng để tương thích |
| `wait(timeout=0.05)` | `:367` | Thay | `SLOT_WAIT_SEC = 0.001` + `expire()` |
| `_frame_processing_loop` alias | `:396-398` | **Giữ** | vẫn alias `_decode_worker_loop` |
| `_decode_jpeg_frame_raw` | `:460-483` | Giữ + nhánh `force_opencv` | — |
| `_is_frame_corrupted` | `:496-511` | Giữ nguyên (không dùng trong hot path) | — |
| `_update_frame` | `:513-552` | Giữ + lock đúng | — |
| `get_performance_stats` | `:574-602` | Giữ key cũ + thêm key mới | §2.9 |
| `_update_fps_counters` | `:554-562` | Giữ + bọc `_stats_lock` | §2.7.4 |
| Async `_UDPProtocol` | `:177-190` | Giữ, đổi sang `_ingest_datagram` | §2.8.5 |
| `_connect_asyncio` tạo endpoint bằng `local_addr` | `:202-221` | Thay | tạo socket thủ công + `sock=` |
| `connect_async`/`disconnect_async` | `:257-283` | Giữ chữ ký | — |
| `OBS_UDP_Manager` | `:628-705` | Giữ | chỉ đổi default port |

> **Nguyên tắc diff:** mọi method công khai trong bảng §2.10 phải còn; mọi thứ chỉ phục vụ cơ chế buffer byte cũ phải biến mất. Nếu Reviewer thấy `mjpeg_buffer.find(` còn trong `_process_mjpeg_data`, đó là thi công chưa xong.

---

## 3. `capture_service.py`, `config.py`, `ui.py`, `network_feedback.py`

### 3.1. `src/capture/capture_service.py`

| Dòng hiện tại | Thay đổi | Lý do |
|---|---|---|
| `:151` `self._port = 1234` | `5000` | đồng bộ default |
| `:150` `self._ip = "127.0.0.1"` | `"0.0.0.0"` | bind mọi interface; UI luôn truyền giá trị thật |
| `:226-246` `connect_udp` | chuẩn hoá `ip.strip()`, `int(port)` 1..65535; lỗi trả `(False, msg)`; log `[Capture] UDP listen ip:port` | chặn port rỗng/chữ; thông điệp rõ |
| `:239` `target_fps=0` | giữ | zero-lag |
| `:243` message | bổ sung "Port phải khớp Target Port trong OBS (mặc định 5000)" | chẩn đoán |
| `:136` manager | giữ | không đổi API |
| `:183-196` `get_frame_dimensions` | giữ | dùng `get_current_frame` |
| `:628-655` `read_frame` | giữ | không copy thêm |

`connect_udp` mới (pseudocode):

```python
def connect_udp(self, ip, port):
    ip = str(ip or "").strip() or "0.0.0.0"
    try:
        port_int = int(str(port).strip())
    except (TypeError, ValueError):
        return False, f"Invalid UDP port: {port!r}"
    if not (1 <= port_int <= 65535):
        return False, f"UDP port out of range: {port_int}"

    if not HAS_UDP:
        return False, "UDP module not loaded (OBS_UDP.py missing)"
    if not self.udp_manager:
        return False, "UDP manager not initialized"

    # Chỉ đổi mode SAU khi tham số hợp lệ: nếu port rác, capture.mode giữ nguyên
    # để UI không hiển thị "UDP" trong khi thực tế chưa hề bind.
    self._ip, self._port = ip, port_int
    try:
        if not self.udp_manager.connect(self._ip, self._port, target_fps=0):
            return False, (f"Cannot bind UDP {self._ip}:{self._port}. "
                           "Port may be in use, or the IP is not local. "
                           "OBS Target Port must match (default 5000).")
        self.mode = "UDP"
        log_print(f"[Capture] UDP listening on {self._ip}:{self._port} (OBS target port must match)")
        return True, None
    except Exception as exc:
        log_print(f"[Capture] UDP connection exception: {exc}")
        return False, str(exc)
```

> **Không** tự động fallback sang 3110. Fallback im lặng sẽ tái tạo đúng lỗi đang sửa. Nếu bind 5000 lỗi, trả lỗi để người dùng xử lý.

### 3.2. `src/utils/config.py` — schema 5 & cổng

1. `CURRENT_CONFIG_SCHEMA = 5`.
2. Default:
   - `self.udp_ip = "0.0.0.0"` (giữ)
   - `self.udp_port = "5000"`
   - `self.audio_feedback_ip = "192.168.10.3"` (giữ default trung tính; config.json thật đã có IP riêng)
   - `self.audio_feedback_port = 4455` **(mới)**
   - `self.audio_feedback_enabled = True` (giữ)
3. `to_dict()`: thêm `"audio_feedback_port": int(self.audio_feedback_port)`.
4. `from_dict()`: sau vòng `setattr`, thêm khối migration **trước** các validate khác:

```python
# --- Schema 4 -> 5: đồng bộ cổng stream v2.1 ---
# CHÈN NGAY SAU vòng `for key, value in data.items(): setattr(...)` (config.py:1066-1068),
# TRƯỚC mọi validate khác và TRƯỚC _migrate_and_validate_flick() (dòng 1325),
# vì hàm đó set self.config_schema = CURRENT ở cuối. Ta đọc schema GỐC từ `data`.
raw_schema = 1
if isinstance(data, dict):
    try:
        raw_schema = int(data.get("config_schema", 1))
    except Exception:
        raw_schema = 1

def _norm_port_str(value, default):
    try:
        p = int(str(value).strip())
    except Exception:
        return str(default)
    return str(p) if 1 <= p <= 65535 else str(default)

def _norm_port_int(value, default):
    try:
        p = int(str(value).strip())
    except Exception:
        return int(default)
    return p if 1 <= p <= 65535 else int(default)

raw_udp_port = str(getattr(self, "udp_port", "")).strip()
if raw_schema < 5 and raw_udp_port in ("", "1234", "3110"):
    self.udp_port = "5000"
    log_print("[Config] schema 4 -> 5: udp_port migrated to 5000 (OBS xUDP v2.1)")
else:
    self.udp_port = _norm_port_str(raw_udp_port, "5000")

self.audio_feedback_port = _norm_port_int(
    getattr(self, "audio_feedback_port", 4455), 4455
)
self.udp_ip = str(getattr(self, "udp_ip", "0.0.0.0")).strip() or "0.0.0.0"
self.audio_feedback_ip = (
    str(getattr(self, "audio_feedback_ip", "192.168.10.3")).strip()
    or "192.168.10.3"
)
self.toggle_feedback_method = (
    "zmq" if str(getattr(self, "toggle_feedback_method", "udp")).strip().lower() == "zmq"
    else "udp"
)
```

- `udp_port` giữ **kiểu `str`** (đúng như hiện tại: UI entry trả str, config lưu str).
- `audio_feedback_port` giữ **kiểu `int`** (network_feedback gọi `int(...)`; JSON ghi số nguyên).
- Nếu `data` không phải dict (không nên xảy ra vì `load_from_file` đọc JSON object) → coi như schema 1 và **vẫn** chuẩn hoá cổng; không raise.
- **Không** đặt `self.config_schema = 5` trong khối này; để cuối `from_dict()`/`_migrate_and_validate_flick()` làm như hiện có, tránh hai nguồn chân lý.

5. `config_schema` được set `CURRENT_CONFIG_SCHEMA` ở cuối `_migrate_and_validate_flick()` (`:1833`) và trong `from_dict()` (`:1499-1500`). Khối migration cổng chạy **trước** các chỗ đó, dùng `raw_schema` từ `data`, nên không phụ thuộc thứ tự nâng schema.
6. `load_from_file()`: giữ; log thêm `udp_port`/`audio_feedback_port` sau khi nạp để dễ chẩn đoán.
7. `config.json`, `config.burst_spray.json`, 8 file `configs/*.json`: đổi `"udp_port": "5000"`, thêm `"audio_feedback_port": 4455` nếu thiếu, `"config_schema": 5`.

**Vì sao phải migration thay vì chỉ sửa default:** người dùng đã có `config.json` với `"udp_port": "3110"` sẽ không bao giờ nhận default mới. Migration một lần + sửa file ship sẵn + thông điệp lỗi rõ là bộ ba bắt buộc.

### 3.3. `src/ui.py`

| Vị trí | Thay đổi |
|---|---|
| `:437` `getattr(config, "udp_port", "1234")` | fallback `"5000"` |
| `:1848`, `:1907` | fallback `"5000"` |
| `:4523-4532` khối Port | thêm label phụ nhỏ: `"Stream UDP 5000 · Beep UDP 4455"` (dùng text tĩnh, không i18n mới để tránh đụng test i18n) |
| `:4945-4952` `_on_udp_port_changed` | giữ lưu chuỗi; **không** chặn khi đang gõ |
| `:10169-10187` `_connect_udp` | `port = self.udp_port_entry.get().strip()`; nếu rỗng → dùng `config.udp_port`; log lỗi bind từ service |
| `:5773-5781` Audio Feedback | đổi mô tả thành `"Beep qua UDP 4455 tới PC1 (OBS plugin)"`; nếu thêm entry port thì phải có `_on_audio_feedback_port_changed` — **khuyến nghị không thêm entry** trong đợt này để giữ UI ổn định, chỉ dùng config/JSON |
| `:10825-10851` stats | không đổi; có thể hiển thị thêm `queue_drops` ở tooltip (tùy chọn, không bắt buộc) |

> **Ranh giới:** không tái cấu trúc UI, không đổi layout Simple/Pro, không đổi scheduler. Chỉ sửa default/port/label.

### 3.4. `src/utils/network_feedback.py` — 4455 cấu hình được & có log

Thiết kế mới:

```python
from .config import config
from .debug_logger import log_print   # BẮT BUỘC thêm: file hiện chưa import log_print

FEEDBACK_PORT = 4455          # giữ hằng số cũ cho ai import
_DEFAULT_PORT = 4455
_feedback_socket = None
_last_target = None
_warned = set()
_sent_ok = 0
_sent_fail = 0

def _target():
    ip = str(getattr(config, "audio_feedback_ip", "")).strip()
    if not ip or ip == "0.0.0.0":
        ip = "127.0.0.1"
    try:
        port = int(getattr(config, "audio_feedback_port", _DEFAULT_PORT))
    except Exception:
        port = _DEFAULT_PORT
    if not (1 <= port <= 65535):
        port = _DEFAULT_PORT
    return ip, port

def _log_once(key, message):
    if key in _warned: return
    _warned.add(key)
    log_print(message)

def _send_udp(is_active: bool) -> bool:
    global _feedback_socket, _last_target, _sent_ok, _sent_fail
    try:
        sock = _get_udp_socket()
        if not sock: return False
        ip, port = _target()
        if _last_target != (ip, port):
            _last_target = (ip, port)
            log_print(f"[NetworkFeedback] UDP beep target -> {ip}:{port}")
            _warned.discard("send_fail")   # target mới được log lỗi lại
        sock.sendto(b"1" if is_active else b"0", (ip, port))
        _sent_ok += 1
        return True
    except Exception as exc:
        _sent_fail += 1
        _log_once("send_fail", f"[NetworkFeedback] UDP beep failed: {exc} "
                               "(kiem tra IP PC1, firewall UDP 4455)")
        return False
```

`send_toggle_feedback`:
- Nếu `audio_feedback_enabled` False → `return False` (không gửi).
- `method == "zmq"`: thử import module; nếu `ImportError` hoặc trả falsy → log **một lần** `"ZMQ unavailable/failed, fallback UDP 4455"` rồi `_send_udp`.
- Trả `bool` (tương thích ngược: caller cũ bỏ qua return).
- Không raise.

**Vì sao không tạo `network_feedback_zmq.py`:** ngoài phạm vi yêu cầu; thêm dependency ZMQ làm nặng gói. Chỉ cần fallback đúng và **không im lặng**.

---

## 4. `OBS-xUDP-Plugin/install.ps1` & TÀI LIỆU

### 4.1. Mục tiêu script

1. Chạy được trên máy cài OBS ở bất kỳ ổ nào (C/D/E/Steam), không hard-code.
2. Cấu hình firewall đúng chiều, idempotent, không tạo rule trùng.
3. Cảnh báo VC++ 2015–2022 x64 nếu thiếu.
4. Thông điệp chuẩn **144 FPS / Purple v2.1**, không còn "240 FPS".
5. Không giết OBS đang chạy mà không hỏi; không copy khi thiếu file nguồn.
6. Thoát với mã lỗi rõ ràng (`exit 1`) để `install.bat` dừng.

### 4.2. Khung script

```powershell
#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ObsPath = "",
    [switch]$SkipFirewall,
    [switch]$ForceCloseObs,
    [switch]$SkipLocalReceiverRule
)
$ErrorActionPreference = "Stop"
$script:ExitCode = 0
```

> `-SkipLocalReceiverRule` cho phép **không** mở UDP 5000 Inbound trên máy đang chạy script. Mặc định **có** tạo rule này (theo yêu cầu "Outbound/Inbound 5000") vì nó cần cho kịch bản bot chạy cùng máy hoặc khi người dùng đổi vai trò hai máy; tài liệu ghi rõ nó chỉ có tác dụng khi máy này thực sự nhận stream.

#### 4.2.1. Kiểm tra quyền admin

```powershell
function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}
if (-not (Test-IsAdmin)) {
    Write-Host "[ERROR] Can quyen Administrator de copy plugin + tao firewall rule." -ForegroundColor Red
    Write-Host "Chuot phai install.bat -> Run as administrator." -ForegroundColor Yellow
    exit 1
}
```

#### 4.2.2. Auto-detect OBS

Thứ tự dò **tất định**, trả về đường dẫn đầu tiên hợp lệ (có `bin\64bit\obs64.exe`):

```powershell
function Resolve-ObsCandidate([string]$path) {
    if ([string]::IsNullOrWhiteSpace($path)) { return $null }
    $p = $path.Trim().Trim('"')
    if (-not (Test-Path $p)) { return $null }
    $item = Get-Item $p -ErrorAction SilentlyContinue
    if ($null -eq $item) { return $null }

    # Người dùng có thể trỏ tới: thư mục gốc, obs64.exe, hoặc bin\64bit\obs64.exe
    if ($item.PSIsContainer) { $dir = $item.FullName }
    else { $dir = Split-Path $item.FullName -Parent }

    # Nếu đang ở ...\bin\64bit thì lùi 2 cấp về gốc OBS
    if ($dir -match '(?i)\\bin\\64bit$') {
        $dir = Split-Path (Split-Path $dir -Parent) -Parent
    }

    if (Test-Path (Join-Path $dir "bin\64bit\obs64.exe")) {
        return (Resolve-Path $dir).Path
    }
    return $null
}

function Find-ObsStudio {
    # 1) Registry (theo yeu cau HKLM:\SOFTWARE\OBS Studio). Luu y: khong phai
    #    moi ban OBS deu ghi key nay; day la MOT trong cac nguon, khong phai
    #    nguon duy nhat. Luon fallback tiep neu khong thay.
    $regKeys = @(
        "HKLM:\SOFTWARE\OBS Studio",
        "HKLM:\SOFTWARE\WOW6432Node\OBS Studio",
        "HKCU:\SOFTWARE\OBS Studio"
    )
    foreach ($key in $regKeys) {
        if (Test-Path $key) {
            $props = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
            if ($null -ne $props) {
                foreach ($name in @("InstallLocation", "InstallDir", "Path")) {
                    $cand = Resolve-ObsCandidate ([string]$props.$name)
                    if ($cand) { return $cand }
                }
            }
        }
    }

    # 2) Uninstall entry (DisplayIcon / InstallLocation)
    $uninstallRoots = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    )
    foreach ($root in $uninstallRoots) {
        if (-not (Test-Path $root)) { continue }
        # foreach (không dùng ForEach-Object) để `return` thoát khỏi FUNCTION,
        # không chỉ thoát khỏi script block của pipeline.
        $entries = @(Get-ChildItem $root -ErrorAction SilentlyContinue)
        foreach ($entry in $entries) {
            $p = Get-ItemProperty $entry.PSPath -ErrorAction SilentlyContinue
            if ($null -eq $p -or [string]$p.DisplayName -notmatch "OBS Studio") { continue }
            $icon = [string]$p.DisplayIcon
            if ($icon) {
                $exe = ($icon -split ",")[0].Trim('"')
                $cand = Resolve-ObsCandidate (Split-Path $exe -Parent)
                if ($cand) { return $cand }
            }
            $cand = Resolve-ObsCandidate ([string]$p.InstallLocation)
            if ($cand) { return $cand }
        }
    }

    # 3) Steam library
    $steamKeys = @("HKCU:\SOFTWARE\Valve\Steam", "HKLM:\SOFTWARE\WOW6432Node\Valve\Steam")
    foreach ($key in $steamKeys) {
        if (-not (Test-Path $key)) { continue }
        $steamProps = Get-ItemProperty $key -ErrorAction SilentlyContinue
        $steamPath = if ($null -ne $steamProps) { [string]$steamProps.SteamPath } else { "" }
        if (-not $steamPath) { continue }
        $steamPath = $steamPath -replace "/", "\"
        $vdf = Join-Path $steamPath "steamapps\libraryfolders.vdf"
        $libraries = @($steamPath)
        if (Test-Path $vdf) {
            $content = Get-Content $vdf -Raw
            foreach ($m in [regex]::Matches($content, '"path"\s+"([^"]+)"')) {
                $libraries += ($m.Groups[1].Value -replace "\\\\", "\")
            }
        }
        foreach ($lib in ($libraries | Select-Object -Unique)) {
            $cand = Resolve-ObsCandidate (Join-Path $lib "steamapps\common\OBS Studio")
            if ($cand) { return $cand }
        }
    }

    # 4) Fallback ổ đĩa (bỏ qua biến môi trường rỗng để Join-Path không ném lỗi)
    $fallbacks = @()
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ($base) { $fallbacks += (Join-Path $base "obs-studio") }
    }
    $fallbacks += @(
        "C:\Program Files\obs-studio",
        "D:\Program Files\obs-studio",
        "E:\Program Files\obs-studio",
        "D:\obs-studio",
        "E:\obs-studio"
    )
    foreach ($path in $fallbacks) {
        $cand = Resolve-ObsCandidate $path
        if ($cand) { return $cand }
    }
    return $null
}
```

Nếu `-ObsPath` được truyền → validate trước, không dò. Nếu không tìm thấy → prompt tối đa 3 lần:

```powershell
$obsDir = $null
for ($attempt = 1; $attempt -le 3; $attempt++) {
    # KHÔNG dùng $input: đây là automatic variable của PowerShell.
    $userPath = Read-Host "Nhap duong dan OBS Studio (thu muc chua bin\64bit\obs64.exe)"
    $cand = Resolve-ObsCandidate $userPath
    if ($cand) { $obsDir = $cand; break }
    Write-Host "[!] Khong hop le: $userPath" -ForegroundColor Yellow
}
if (-not $obsDir) {
    Write-Host "[ERROR] Khong tim thay OBS Studio. Cai OBS 64-bit hoac chay: .\install.ps1 -ObsPath 'D:\obs-studio'" -ForegroundColor Red
    exit 1
}
```

#### 4.2.3. Kiểm tra file nguồn trước khi copy

```powershell
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$required = @(
    "obs-plugins\64bit\obs-color-correction.dll",
    "bin\64bit\turbojpeg.dll"
)
foreach ($rel in $required) {
    if (-not (Test-Path (Join-Path $scriptDir $rel))) {
        Write-Host "[ERROR] Thieu file nguon: $rel" -ForegroundColor Red
        exit 1
    }
}
```

#### 4.2.4. Đóng OBS an toàn

```powershell
$obs = Get-Process -Name "obs64" -ErrorAction SilentlyContinue
if ($obs) {
    if (-not $ForceCloseObs) {
        $answer = Read-Host "OBS dang chay. Dong OBS de cai plugin? (Y/N)"
        if ($answer -notmatch "^(y|yes)$") {
            Write-Host "[!] Huy cai dat. Hay dong OBS roi chay lai." -ForegroundColor Yellow
            exit 1
        }
    }
    $obs | Stop-Process -Force
    Start-Sleep -Milliseconds 800
}
```

> Nếu người dùng chọn Y, **cảnh báo rõ** rằng OBS đang stream/ghi hình sẽ bị ngắt và bản ghi có thể hỏng. Không có cách "cài nóng" DLL đang được nạp; đóng là bắt buộc.

#### 4.2.5. Copy & xác minh

```powershell
Copy-Item "$scriptDir\obs-plugins\64bit\*" "$obsDir\obs-plugins\64bit\" -Force -Recurse
Copy-Item "$scriptDir\bin\64bit\*" "$obsDir\bin\64bit\" -Force -Recurse

$turboDir = "C:\libjpeg-turbo64\bin"
New-Item -ItemType Directory -Path $turboDir -Force | Out-Null
Copy-Item "$scriptDir\bin\64bit\turbojpeg.dll" "$turboDir\turbojpeg.dll" -Force

$installedDll = Join-Path $obsDir "obs-plugins\64bit\obs-color-correction.dll"
if (-not (Test-Path $installedDll)) {
    Write-Host "[ERROR] Copy that bai: $installedDll" -ForegroundColor Red
    exit 1
}
```

#### 4.2.6. Firewall — đúng chiều, idempotent

```powershell
$obsExe = Join-Path $obsDir "bin\64bit\obs64.exe"
if (-not (Test-Path $obsExe)) {
    Write-Host "[ERROR] Khong tim thay obs64.exe: $obsExe" -ForegroundColor Red
    exit 1
}

function Set-CvmFirewallRule {
    param(
        [string]$Name,
        [string]$Direction,      # Inbound | Outbound
        [string]$Protocol = "UDP",
        [int]$LocalPort = 0,
        [int]$RemotePort = 0,
        [string]$Program = "",
        [string]$Description = ""
    )
    Get-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue
    $params = @{
        DisplayName = $Name
        Direction   = $Direction
        Protocol    = $Protocol
        Action      = "Allow"
        Profile     = "Any"
        Description = $Description
        Enabled     = "True"
    }
    if ($LocalPort -gt 0)  { $params.LocalPort  = $LocalPort }
    if ($RemotePort -gt 0) { $params.RemotePort = $RemotePort }
    if ($Program)          { $params.Program    = $Program }
    New-NetFirewallRule @params | Out-Null
}
```

Các rule bắt buộc:

| Rule | Direction | Protocol | Điều kiện | Máy đúng |
|---|---|---|---|---|
| `CVM xUDP - OBS Studio UDP In` | Inbound | UDP | `-Program $obsExe` | PC1 |
| `CVM xUDP - OBS Studio UDP Out` | Outbound | UDP | `-Program $obsExe` | PC1 |
| `CVM xUDP - Beep 4455 In` | Inbound | UDP | `-LocalPort 4455` | PC1 |
| `CVM xUDP - Stream 5000 Out` | Outbound | UDP | `-RemotePort 5000` | PC1 |
| `CVM xUDP - Stream 5000 In` | Inbound | UDP | `-LocalPort 5000` | PC2 (hoặc PC1 nếu chạy receiver cùng máy) |

**Điểm kỹ thuật quan trọng:** OBS gửi stream từ **source port ephemeral** tới PC2:5000. Vì vậy rule outbound phải dùng `-RemotePort 5000`, **không phải** `-LocalPort 5000`. Rule `-LocalPort 5000` chỉ có nghĩa trên máy **nhận**. Script chạy trên PC1 nên tạo 4 rule PC1 (+1 rule inbound 5000 nếu không `-SkipLocalReceiverRule`):

```powershell
if (-not $SkipFirewall) {
    try {
        Set-CvmFirewallRule -Name "CVM xUDP - OBS Studio UDP In" `
            -Direction Inbound -Protocol UDP -Program $obsExe `
            -Description "OBS Studio nhan UDP (plugin/websocket/beep)"
        Set-CvmFirewallRule -Name "CVM xUDP - OBS Studio UDP Out" `
            -Direction Outbound -Protocol UDP -Program $obsExe `
            -Description "OBS Studio gui stream xUDP toi may 2"
        Set-CvmFirewallRule -Name "CVM xUDP - Beep 4455 In" `
            -Direction Inbound -Protocol UDP -LocalPort 4455 `
            -Description "Nhan tin hieu toggle tu bot (UDP 4455, khong phai TCP)"
        Set-CvmFirewallRule -Name "CVM xUDP - Stream 5000 Out" `
            -Direction Outbound -Protocol UDP -RemotePort 5000 `
            -Description "Gui stream toi may 2 cong 5000"

        if (-not $SkipLocalReceiverRule) {
            Set-CvmFirewallRule -Name "CVM xUDP - Stream 5000 In" `
                -Direction Inbound -Protocol UDP -LocalPort 5000 `
                -Description "Nhan stream tren may nay (can khi bot chay cung may)"
        }
    } catch {
        Write-Host "[!] Khong tao duoc firewall rule: $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "    Chay PowerShell as Administrator hoac tu tao rule theo HUONG_DAN_SU_DUNG.txt" -ForegroundColor Yellow
        $script:ExitCode = 2
    }
} else {
    Write-Host "[i] Bo qua firewall (-SkipFirewall). Lenh thu cong:" -ForegroundColor Gray
    Write-Host "    New-NetFirewallRule -DisplayName 'CVM xUDP - Stream 5000 In' -Direction Inbound -Protocol UDP -LocalPort 5000 -Action Allow"
}
```

- Rule `Stream 5000 In` được tạo mặc định (theo yêu cầu mở "Outbound/Inbound 5000"), trừ khi chạy với `-SkipLocalReceiverRule`. Trên PC2, rule này là **bắt buộc**; chạy lệnh:

```powershell
New-NetFirewallRule -DisplayName "CVM xUDP - Stream 5000 In" -Direction Inbound `
  -Protocol UDP -LocalPort 5000 -Action Allow -Profile Any
```

> Rule inbound 5000 **rộng hơn** mức tối thiểu cần cho PC1 (máy chơi game không cần nhận stream). Script vẫn tạo vì: (a) yêu cầu nghiệm thu nêu rõ "UDP Outbound/Inbound 5000"; (b) người dùng thường đổi vai trò hai máy hoặc chạy bot cùng máy; (c) rule chỉ mở khi có ứng dụng bind cổng. Nếu muốn giảm bề mặt tấn công, thêm `-SkipLocalReceiverRule`; tài liệu phải nêu rõ lựa chọn này.

Nếu `-SkipFirewall` → in danh sách lệnh để người dùng tự chạy. Nếu `New-NetFirewallRule` lỗi (policy domain chặn) → cảnh báo, **không** fail toàn bộ cài đặt plugin; đặt `$script:ExitCode = 2` và in hướng dẫn.

#### 4.2.7. VC++ 2015–2022 x64

```powershell
function Test-VCRedistX64 {
    $keys = @(
        "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
    )
    foreach ($key in $keys) {
        if (Test-Path $key) {
            $p = Get-ItemProperty $key -ErrorAction SilentlyContinue
            if ($p.Installed -eq 1) { return $true }
        }
    }
    return $false
}
```

Thiếu → cảnh báo đỏ + link `https://aka.ms/vs/17/release/vc_redist.x64.exe`; **không tự tải** (máy có thể offline). Ghi vào phần "CANH BAO" cuối script, không chặn copy.

#### 4.2.8. Thông điệp kết thúc

```
================================================================
  CVM xUDP / VeloNet OBS Plugin v2.1 — 144 FPS · Purple
================================================================
[OK] OBS Studio : <đường dẫn>
[OK] Plugin     : obs-color-correction.dll
[OK] Decoder    : turbojpeg.dll (C:\libjpeg-turbo64\bin)
[OK] Firewall   : UDP 4455 In · UDP 5000 Out (RemotePort)
[!]  VC++ 2015-2022 x64: <OK/THIEU>
----------------------------------------------------------------
Buoc tiep theo:
 1. Mo OBS -> Settings -> Video: FPS = 144
 2. Filter Color Correction: 320x320, JPEG 80-85,
    Target IP = IP cua may 2, Target Port = 5000
 3. Tren may 2: chay CVM-colorBot, Capture = UDP,
    IP = 0.0.0.0, Port = 5000
 4. Bat/tat aim de nghe beep (UDP 4455) tren tai nghe PC1.
================================================================
```

`exit $script:ExitCode` (0 = thành công; 2 = đã cài nhưng có cảnh báo firewall hoặc VC++; 1 = lỗi không cài được). `install.bat` chỉ `pause` để người dùng đọc, không che exit code.

> **Ghi chú văn bản:** toàn bộ thông điệp script/tài liệu hiện dùng ASCII không dấu (tiếng Việt không dấu) vì console mặc định `cp437/cp1258` có thể hiển thị sai. Giữ nhất quán như vậy thay vì trộn Unicode — trừ tên thương hiệu "CVM xUDP / VeloNet" và "Purple". Nếu Coder muốn dùng Unicode tiếng Việt, phải đặt `[Console]::OutputEncoding = [Text.Encoding]::UTF8` và `chcp 65001`, **không** làm nửa vời.

### 4.3. `HUONG_DAN_SU_DUNG.txt` — nội dung bắt buộc

Cập nhật các mục:

1. **Bảng cổng:**

```
| Kênh                | Giao thức | Cổng | Máy bind | Máy gửi |
|---------------------|-----------|------|----------|---------|
| Video stream        | UDP       | 5000 | Máy 2    | Máy 1   |
| Toggle beep         | UDP       | 4455 | Máy 1    | Máy 2   |
| OBS WebSocket       | TCP       | 4455 | Máy 1    | tool    |
```

2. **Cấu hình IP hai máy:** PC1 (OBS) Target IP = IP LAN của PC2; PC2 (bot) `udp_ip = 0.0.0.0` (bind mọi card), `udp_port = 5000`. Beep: PC2 `audio_feedback_ip` = IP LAN của PC1, `audio_feedback_port = 4455`.
3. **Firewall:** rule nào tạo trên máy nào; lệnh PowerShell cho PC2; cảnh báo UDP 4455 ≠ TCP 4455.
4. **144 FPS:** giải thích 6.94 ms, deadline 5 ms, vì sao không nên đặt 240 FPS khi receiver dùng deadline 5 ms.
5. **Purple v2.1:** HSV H `[120,160]`, S ≥ 188, V ≥ 115; nhấn mạnh đây là giá trị bot dùng, plugin chỉ biến đổi màu.
6. **Chẩn đoán nhanh:** FPS = 0 → kiểm tra port; có frame nhưng méo → kiểm tra fragment/TurboJPEG; beep không kêu → firewall UDP 4455/IP PC1.
7. **Lệnh receiver độc lập:** `python receiver_ultra_fast.py --port 5000 --timeout 0.005` (chỉ để test, **không** chạy đồng thời với bot vì sẽ tranh cổng 5000).

### 4.4. `../HUONG_DAN_CAI_DAT.txt` — nội dung bắt buộc

- Bước 1: chạy `install.bat` as admin; script tự dò OBS (Registry/Steam/D/E) hoặc hỏi đường dẫn; tự tạo firewall; cảnh báo VC++.
- Bước 2: cấu hình OBS 144 FPS, 320×320, JPEG 80–85, Target IP/Port 5000.
- Bước 3: bot `config.json` chuẩn v2.1: Sens 0.23, DPI 1100, WindMouse main, Flick sec, `udp_ip 0.0.0.0`, `udp_port 5000`, `audio_feedback_ip` = IP PC1.
- Bước 4: kiểm tra kết nối (FPS > 0, Delay < 3 ms), beep 4455.
- Bảng lỗi thường gặp: bind 5000 fail, firewall, sai IP, TurboJPEG thiếu.
- Xóa mô tả cũ "X Speed 100 / Y 70 / Gravity 4.5" nếu không khớp config ship (hiện `normal_x_speed 95`, `wm_gravity 5.5`). **Không** bịa số mới; chỉ mô tả đúng file `config.json`.

---

## 5. ĐỒNG BỘ CONFIG MẪU `OBS-xUDP-Plugin`

### 5.1. Bộ chuẩn v2.1 bắt buộc

| Key | Giá trị chuẩn | `config.json` hiện | `cvm_config_optimized.json` hiện |
|---|---|---|---|
| `in_game_sens` | **0.23** | 0.235 | 0.235 |
| `mouse_dpi` | **1100** | 1100 | **800** |
| `mode` | **WindMouse** | WindMouse | WindMouse |
| `mode_sec` | **Flick** | WindMouse | WindMouse |
| `udp_ip` | **0.0.0.0** | 192.168.100.2 | 192.168.10.25 |
| `udp_port` | **5000** | 3110 | 3110 |
| `audio_feedback_port` | **4455** | thiếu | thiếu |
| `audio_feedback_ip` | IP PC1 (mẫu `192.168.100.1`) | thiếu | thiếu |
| `toggle_feedback_method` | `udp` | thiếu | thiếu |
| `config_schema` | **5** | thiếu | thiếu |
| `capture_mode` | `UDP` | UDP | UDP |
| `target_fps` | 144 | 144 | 144 |
| `capture_fps` | 144.0 | 144.0 | 144.0 |
| `aim_engine` | `legacy` | thiếu | thiếu |
| `flick_engine` | `v2` | thiếu | thiếu |
| `flick_gain` / `flick_gain_sec` | 1.0 | thiếu | thiếu |
| `flick_max_counts` / `_sec` | 6000.0 | thiếu | thiếu |
| `flick_budget_ms` | 120.0 | thiếu | thiếu |
| `flick_budget_ms_sec` | 240.0 | thiếu | thiếu |
| `flick_settle_ms` / `_sec` | 70.0 | thiếu | thiếu |
| `flick_deadzone_px` / `_sec` | 1.5 / 2.0 | thiếu | thiếu |
| `flick_switch_radius_px` / `_sec` | 64 | thiếu | thiếu |

> **Không** đổi các giá trị tuning khác (`fovsize`, `normal_x_speed`, `wm_*`, HSV, RCS…) trừ khi chúng mâu thuẫn trực tiếp với bộ chuẩn. Mục tiêu là **cùng một baseline tái lập được**, không phải "làm mới" toàn bộ config.

### 5.2. Cách thực hiện an toàn

1. Sửa **tay từng key** bằng `edit`/`write`, không sinh JSON bằng script (tránh mất thứ tự/comment).
2. Giữ nguyên `_comment` nhưng đổi thành:
   `"CVM Colorbot Config - v2.1 (144 FPS) - Sens 0.23 / DPI 1100 / WindMouse main / Flick sec / UDP 5000"`.
3. Validate JSON bằng mắt + test `json.load` (§6.6 O1–O3).
4. `config.json` và `cvm_config_optimized.json` phải **cùng bộ key v2.1**; khác nhau chỉ ở các giá trị tuning được phép (nếu có). Tốt nhất làm chúng **giống hệt** để người dùng không chọn nhầm bản cũ.
5. Sao chép cùng bộ key sang `config.json` gốc của bot? **Không** — config gốc đã có nhiều key UI/launcher mới hơn. Chỉ đồng bộ các key cổng/chuẩn v2.1 đã liệt kê.

### 5.3. `config.json` gốc của bot & profiles

| File | Thay đổi tối thiểu |
|---|---|
| `CVM-colorBot/config.json` | `udp_port: "5000"`, `audio_feedback_port: 4455`, `config_schema: 5` |
| `CVM-colorBot/config.burst_spray.json` | như trên |
| `CVM-colorBot/configs/*.json` (8 file) | `udp_port: "5000"`, thêm `audio_feedback_port`, `config_schema: 5` nếu thiếu |
| `OBS-xUDP-Plugin/config.json` | §5.1 |
| `OBS-xUDP-Plugin/cvm_config_optimized.json` | §5.1 |

> **Không** đổi `dhz_port`, `ferrum_dhz_port`, `keyboard_ferrum_dhz_port` (remote box 5000). Ghi chú trong tài liệu để tránh nhầm.

---

## 6. THIẾT KẾ KIỂM THỬ (TEST MATRIX CHO TESTER)

### 6.1. Nguyên tắc

- Test **không được bind cổng 5000 thật** trong CI (có thể đang có bot chạy). Dùng `127.0.0.1` + cổng ephemeral (`bind(("127.0.0.1", 0))` lấy port), hoặc chỉ test unit không socket.
- Test reassembler **không phụ thuộc TurboJPEG**; chỉ test receiver decode mới cần.
- Đo latency: warm-up 5 frame, đo 30 frame, assert **median (p50) < 1.5 ms**, **p95 < 3.0 ms**; skip nếu `turbojpeg` không có hoặc `sys.platform != "win32"`. Không assert max (máy CI có thể bị preempt).
- Mọi test phải dọn tài nguyên trong `tearDown`/`addCleanup`: `disconnect()`, đóng socket, `WindowsTimer.disable()`.
- Không dùng `time.sleep` dài; tối đa 50 ms cho đồng bộ thread, và luôn có timeout.

### 6.2. T1 — `tests/test_udp_frame_reassembler.py` (mới, 18 case)

| ID | Tên test | Thao tác | Assert |
|---|---|---|---|
| R1 | `test_single_packet_returns_same_bytes` | `process_packet(jpeg)` | `== jpeg`; `completed==1`; `dropped==0` |
| R2 | `test_single_packet_rejects_short_junk` | `b"\x00\x01"` | `None`; `invalid==1` |
| R3 | `test_two_fragments_in_order` | frag0, frag1 | frame; `completed==1` |
| R4 | `test_two_fragments_out_of_order` | frag1, frag0 | frame; `completed==1`; `dropped==0` |
| R5 | `test_three_fragments_2_0_1` | frag2, frag0, frag1 | frame; `completed==1` |
| R6 | `test_duplicate_fragment_restarts` | frag0, frag0, frag1 | frame; `dropped==1`; `restart==1` |
| R7 | `test_different_total_size_restarts` | frag0(A), frag0(B) | `None`; `dropped==1`; `restart==1` |
| R8 | `test_timeout_discards_before_new_frame` | frag0 @ t=1000.000; single @ t=1000.006 | single; `timeout==1`; `dropped==1` |
| R9 | `test_timeout_boundary_is_strict` | frag0 @ t=0; frag1 @ t=0.005 | frame; `timeout==0` (dùng `>` không `>=`) |
| R10 | `test_single_frame_supersedes_partial` | frag0; single | single; `dropped==1`; `restart==1` |
| R11 | `test_length_mismatch_is_bad_frame` | header `total_size=70000`, 2 mảnh thiếu byte | `None`; `bad==1`; `dropped==1` |
| R12 | `test_reassembled_payload_must_start_soi` | 2 mảnh payload bắt đầu `b"XX"` | `None`; `bad==1`; `dropped==1` |
| R13 | `test_oversize_header_rejected` | payload **không** bắt đầu SOI, `total_size = 10_000_001` | `None`; `oversize==1`; `invalid==1`; không lưu mảnh |
| R14 | `test_empty_fragment_payload_rejected` | header hợp lệ + `b""` | `None`; `invalid==1` |
| R15 | `test_expire_drops_stale_assembly` | frag0 @ t=0; `expire(t=0.006)` | `True`; `timeout==1`; `buffered_bytes==0` |
| R16 | `test_reset_clears_state` | frag0; `reset(mark_dropped=True)` | `dropped==1`; `buffered==0`; `process_packet(single)` OK |
| R17 | `test_fragment_with_soi_looking_header_wins` | `total_size=0x0001D8FF` (121 087) → 4 byte đầu `FF D8 01 00`; gửi 2 mảnh | **phải** ghép thành frame; `completed==1`; `invalid==0`. Nếu code kiểm tra SOI trước header, test này đỏ ngay. |
| R18 | `test_real_single_jpeg_not_counted_oversize` | JPEG thật `FF D8 FF E0 … FF D9`, 128×128 | trả data; `oversize==0`; `invalid==0`; `completed==1` |

> R17/R18 ghim thứ tự phân loại §2.5.2 — đây là chỗ dễ bị "tối ưu" sai nhất khi review.

Test data:
- JPEG giả tối thiểu: `b"\xff\xd8" + b"F"*69998` (như plugin test) cho frame 2 mảnh.
- Header: `struct.pack("<IHH", total_size, idx, total_frags)`.
- Chia mảnh: 64 992 byte cho mảnh 0 (khớp plugin test) hoặc 50 000 byte; test không cần đúng kích thước OBS, chỉ cần > 65 000 tổng.

### 6.3. T2 — `tests/test_udp_receiver_latency.py` (viết lại, 15 case)

Giữ tên file để `unittest discover` và thói quen CI không đổi.

| ID | Tên test | Điều kiện | Assert |
|---|---|---|---|
| L1 | `test_default_port_is_5000` | không cần turbojpeg | `OBS_UDP_Receiver().port == 5000`; `ip == "0.0.0.0"` |
| L2 | `test_single_packet_decode_latency_p50` | turbojpeg + win32 | encode 128×128; `_process_mjpeg_data`; chờ decode; p50 `decode_delay_ms < 1.5`; frame shape đúng |
| L3 | `test_decode_latency_p95` | như trên | p95 `< 3.0` (không assert max) |
| L4 | `test_opencv_fallback_decodes` | luôn | `force_opencv=True`; decode ảnh; shape đúng; backend chứa "OpenCV" |
| L5 | `test_slot_depth_never_exceeds_one` | luôn | **không** start decode thread; đẩy 5 frame liên tiếp vào `_slot` qua `_process_mjpeg_data`; `stats["queue_size"] == 1`; `queue_drops == 4` |
| L6 | `test_zero_backlog_keeps_latest_frame` | turbojpeg/opencv | gửi frame đỏ rồi xanh; sau decode, pixel trung tâm là xanh (frame mới nhất) |
| L7 | `test_receive_delay_non_negative` | turbojpeg | `receive_delay_ms >= 0`; `decode_delay_ms >= 0` |
| L8 | `test_stats_contract_keys` | luôn | đủ key cũ §2.9; kiểu số; `queue_size` int |
| L9 | `test_corrupt_jpeg_returns_none` | luôn | `_decode_jpeg_frame_raw(b"not a jpeg") is None`; `decode_errors` tăng sau worker (hoặc gọi trực tiếp) |
| L10 | `test_windows_timer_idempotent` | patch `sys.platform`/`ctypes.WinDLL` | `enable()` 2 lần không tăng refcount sai; `disable()` 2 lần không raise; non-Windows trả `False` |
| L11 | `test_high_thread_priority_never_raises` | luôn | trả bool; không exception |
| L12 | `test_disconnect_clears_frame_and_slot` | luôn | sau `disconnect()`: `get_current_frame() is None`; `queue_size == 0` |
| L13 | `test_connect_busy_port_returns_false` | luôn | bind một socket tạm vào `127.0.0.1:0`, lấy port, rồi `receiver.connect()` cùng port → `False`; không raise; log có "bind" |
| L14 | `test_legacy_api_surface` | luôn | `set_target_fps`, `update_connection_params`, `set_frame_callback`, `_frame_processing_loop` tồn tại; `get_performance_stats` không raise |
| L15 | `test_log_bridge_reaches_debug_logger` | luôn | sau `connect()` lỗi (cổng bận), `debug_logger.get_recent_logs()` chứa chuỗi `"bind"`; handler chỉ cài **một lần** dù tạo 3 receiver |

> L2/L3 cần decode thật. Nếu máy Tester không có `turbojpeg`, **skip riêng 2 test này**, không skip cả class (khác test cũ). Ghi rõ lý do skip trong báo cáo.

### 6.4. T3 — `tests/test_config_ports.py` (mới, 8 case)

> Dùng tiền tố `G` (config) để **không** trùng với mã task Coder `C1–C11` ở §7.4.

| ID | Test | Assert |
|---|---|---|
| G1 | default mới | `Config().udp_port == "5000"`; `audio_feedback_port == 4455` |
| G2 | migration schema 4 + 3110 | `from_dict({"config_schema":4,"udp_port":"3110"})` → `"5000"`; schema 5 |
| G3 | migration schema 4 + 1234/rỗng | → `"5000"` |
| G4 | schema 5 giữ 3110 | `from_dict({"config_schema":5,"udp_port":"3110"})` → `"3110"` (tôn trọng người dùng) |
| G5 | port rác | `"abc"`, `"70000"`, `"-1"` → `"5000"` |
| G6 | audio port rác | `"abc"` → `4455` |
| G7 | round-trip `to_dict` | có `udp_port`, `audio_feedback_port`; `json.dumps` được |
| G8 | load file thật | đọc `config.json` (nếu tồn tại) → `udp_port == "5000"` |

### 6.5. T4 — `tests/test_network_feedback.py` (mới, 6 case)

| ID | Test | Assert |
|---|---|---|
| N1 | disabled | `audio_feedback_enabled=False` → không gọi `sendto`; trả `False` |
| N2 | payload đúng | patch socket; active → `b"1"`, inactive → `b"0"` |
| N3 | target từ config | `audio_feedback_ip/port` được dùng đúng |
| N4 | lỗi gửi | `sendto` raise → trả `False`; không raise; log một lần (patch `log_print`) |
| N5 | zmq fallback | `toggle_feedback_method="zmq"`, module không tồn tại → vẫn gửi UDP; log fallback |
| N6 | `FEEDBACK_PORT` compat | hằng số vẫn `== 4455` |

### 6.6. T5 — `tests/test_obs_config_sync.py` (mới, 7 case, static)

| ID | Test | Assert |
|---|---|---|
| O1 | plugin config JSON hợp lệ | `json.load` không lỗi |
| O2 | bộ chuẩn v2.1 | `in_game_sens == 0.23`, `mouse_dpi == 1100`, `mode == "WindMouse"`, `mode_sec == "Flick"`, `udp_port == "5000"` |
| O3 | `cvm_config_optimized` | như O2 (đặc biệt `mouse_dpi == 1100`, không còn 800) |
| O4 | config bot & profiles | mọi `config*.json` + `configs/*.json` có `udp_port == "5000"` |
| O5 | `audio_feedback_port` | config bot & plugin mẫu có 4455 |
| O6 | `install.ps1` có thành phần bắt buộc | chứa `HKLM:\SOFTWARE\OBS Studio`, `New-NetFirewallRule`, `4455`, `5000`, `VC\Runtimes\x64`, `144 FPS`; **không** chứa `240 FPS` |
| O7 | tài liệu | `HUONG_DAN_SU_DUNG.txt` và `HUONG_DAN_CAI_DAT.txt` chứa `5000`, `4455`, `144` |

> O6/O7 là test tĩnh, không chạy PowerShell. Nó ngăn tài liệu/script bị revert về bản cũ.
>
> **Ràng buộc văn bản cho Coder:** `install.ps1` **không được chứa chuỗi `"240 FPS"`** (kể cả trong câu cảnh báo). Nếu cần nói về 240, viết "240" tách khỏi "FPS", hoặc chỉ nói "chi giu 144 FPS". Tương tự, `HUONG_DAN_SU_DUNG.txt` được phép giải thích 240 (O7 chỉ yêu cầu chứa `5000`, `4455`, `144`), nhưng **không** được mô tả 240 là chuẩn khuyến nghị.

### 6.7. T6 — Hồi quy toàn bộ

```powershell
cd C:\Users\TeamOS\Downloads\CVM-colorBot-v1.2.1-FullPackage\CVM-colorBot
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Kỳ vọng:
- `0 errors`, `0 failures`.
- Số test tăng so với baseline 264 (theo `03-kiem-thu.md`), không giảm.
- Skip chỉ được phép do: thiếu Tk/display (class-level), thiếu `turbojpeg` (L2/L3), hoặc test GUI thật.
- Chạy riêng các file mới:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_udp_frame_reassembler -v
.\venv\Scripts\python.exe -m unittest tests.test_udp_receiver_latency -v
.\venv\Scripts\python.exe -m unittest tests.test_config_ports -v
.\venv\Scripts\python.exe -m unittest tests.test_network_feedback -v
.\venv\Scripts\python.exe -m unittest tests.test_obs_config_sync -v
```

- Chạy bộ test tham chiếu của plugin (không bắt buộc trong CI bot, nhưng phải xanh trên máy có đủ DLL):

```powershell
cd ..\OBS-xUDP-Plugin
..\CVM-colorBot\venv\Scripts\python.exe test_receiver_ultra_fast.py
```

### 6.8. QA thủ công (không thể tự động hóa)

| ID | Kịch bản | Kỳ vọng |
|---|---|---|
| M1 | PC1 OBS 144 FPS, 320×320 Q80 → PC2 bot UDP 5000 | FPS ≈ 144, Delay < 3 ms, không giật |
| M2 | Đổi OBS Q95 / 640×640 để buộc phân mảnh | Vẫn có frame; `reassembly_drops` tăng chậm; không có frame xanh/đen |
| M3 | Rút dây mạng 2 s rồi cắm lại | Bot không crash; frame tự phục hồi; `timeout_drops` tăng |
| M4 | Chạy đồng thời `receiver_ultra_fast.py` và bot trên PC2 | Một trong hai bind fail rõ ràng; không chia gói im lặng |
| M5 | Bật/tắt aim toggle | Beep PC1 kêu; log `NetworkFeedback` đúng IP:4455 |
| M6 | Chặn firewall UDP 4455 | Beep không kêu; log lỗi một lần, không spam; bot vẫn chạy |
| M7 | Cài OBS ở `D:\obs-studio`, chạy `install.bat` | Tự dò đúng; copy đúng; rule firewall tạo đúng |
| M8 | Chạy `install.ps1` lần 2 | Không tạo rule trùng; không lỗi; thông điệp 144 FPS/Purple |
| M9 | Máy thiếu VC++ | Cảnh báo rõ, vẫn cài plugin |
| M10 | `disconnect()` qua UI khi đang nhận 144 FPS | UI không đứng > 0.5 s; không lỗi rò rỉ thread |
| M11 | Đổi `udp_port` trong UI sang `3110` rồi bấm Connect khi OBS vẫn gửi 5000 | Bot bind 3110 **thành công** (bind là đủ) nhưng FPS = 0; log/tài liệu phải đủ rõ để người dùng tự nhận ra. Đây là **hành vi đúng** của thiết kế (không fallback ngầm), không phải lỗi. |
| M12 | Chạy bot trên máy có `config.json` cũ (`schema 4`, port 3110) | Log có `schema 4 -> 5: udp_port migrated to 5000`; UI hiển thị 5000; file sau khi lưu có `config_schema: 5`. |

---

## 7. DANH SÁCH TỆP TÁC ĐỘNG & RANH GIỚI AN TOÀN

### 7.1. Tạo mới

| Tệp | Mục đích | Ghi chú |
|---|---|---|
| `tests/test_udp_frame_reassembler.py` | Unit test reassembler | Không phụ thuộc turbojpeg/Tk |
| `tests/test_config_ports.py` | Migration/validate cổng | Dùng `tempfile` như `test_flick_config.py` |
| `tests/test_network_feedback.py` | Test 4455/fallback/log | Patch socket |
| `tests/test_obs_config_sync.py` | Test tĩnh config + script + docs | Chỉ đọc file |

### 7.2. Sửa

| Tệp | Mức độ | Nội dung |
|---|---|---|
| `src/capture/OBS_UDP.py` | **Lớn** | Thêm `WindowsTimer`, `set_high_thread_priority`, `FrameReassembler`, `LatestFrameSlot`; viết lại ingest/decode/connect/disconnect; giữ API |
| `src/capture/capture_service.py` | Nhỏ | default 5000, validate port, log, thông điệp lỗi |
| `src/utils/config.py` | Vừa | schema 5, default 5000, `audio_feedback_port`, migration, validate |
| `src/utils/network_feedback.py` | Vừa | port cấu hình, log, return bool, fallback ZMQ rõ |
| `src/ui.py` | Nhỏ | fallback 5000, label phụ, strip port khi connect |
| `config.json` | Nhỏ | `udp_port 5000`, `audio_feedback_port 4455`, `config_schema 5` |
| `config.burst_spray.json` | Nhỏ | như trên |
| `configs/*.json` (8 file) | Nhỏ | như trên |
| `../OBS-xUDP-Plugin/config.json` | Vừa | bộ chuẩn v2.1 §5.1 |
| `../OBS-xUDP-Plugin/cvm_config_optimized.json` | Vừa | bộ chuẩn v2.1 §5.1 |
| `../OBS-xUDP-Plugin/install.ps1` | **Lớn** | auto-detect, firewall, VC++, thông điệp, an toàn |
| `../OBS-xUDP-Plugin/HUONG_DAN_SU_DUNG.txt` | Vừa | bảng cổng, IP, firewall, 144 FPS, chẩn đoán |
| `../HUONG_DAN_CAI_DAT.txt` | Vừa | quy trình cài, cấu hình, lỗi thường gặp |
| `tests/test_udp_receiver_latency.py` | **Lớn** | viết lại theo T2 |

### 7.3. Không sửa (ranh giới cứng)

| Tệp/Thành phần | Lý do |
|---|---|
| `../OBS-xUDP-Plugin/receiver_ultra_fast.py` | Là nguồn tham chiếu; sửa sẽ làm lệch test đối chiếu |
| `../OBS-xUDP-Plugin/test_receiver_ultra_fast.py` | Bộ test chuẩn của plugin |
| `../OBS-xUDP-Plugin/obs-plugins/64bit/obs-color-correction.dll` | Binary; không có source trong repo |
| `../OBS-xUDP-Plugin/bin/64bit/turbojpeg.dll` | Binary |
| `../OBS-xUDP-Plugin/install.bat`, `run_receiver.bat` | Chỉ cần giữ tương thích; không đổi logic |
| `src/ui_modes/simple_dashboard.py`, `src/utils/win32_window.py`, `global_hotkey.py`, `single_instance.py` | Baseline UI/launcher vừa chốt |
| `src/aim_system/*`, `main.py` (logic aim) | Ngoài phạm vi |
| `version.json` | Schema app ≠ schema config; không bump |
| `locales/*.json` | Không thêm key mới; label phụ dùng tiếng Việt tĩnh |

### 7.4. Thứ tự thi công bắt buộc (Coder)

1. **C1 — Config & port:** `config.py` schema 5 + default; `config.json` + profiles; `capture_service` default/validate; `ui.py` fallback. Chạy `test_config_ports` + toàn bộ test cũ (phải xanh trước khi đụng receiver).
2. **C2 — Primitive:** `WindowsTimer`, `set_high_thread_priority`, `LatestFrameSlot` trong `OBS_UDP.py`. Chưa đổi receiver.
3. **C3 — `FrameReassembler`:** thêm class + unit test R1–R18. Chạy test riêng.
4. **C4 — Tích hợp receiver:** thay `_process_mjpeg_data`, `_receive_loop`, `_decode_worker_loop`, `connect/disconnect`, stats. Chạy T2 + test cũ.
5. **C5 — Async path:** đảm bảo dùng chung ingest/slot; timer refcount.
6. **C6 — `network_feedback`:** port + log + fallback; test N1–N6.
7. **C7 — UI:** chỉ fallback/label; chạy test UI hiện có (skip Tk nếu headless).
8. **C8 — Plugin configs:** §5; test O1–O5.
9. **C9 — `install.ps1`:** §4; kiểm tra cú pháp bằng `powershell -NoProfile -Command "[scriptblock]::Create((Get-Content -Raw .\install.ps1)) | Out-Null"` (Tester/QA chạy, không phải Planner).
10. **C10 — Tài liệu:** §4.3/§4.4; test O7.
11. **C11 — Chạy full suite + ghi `02-thay-doi.md`.**

> Nếu bất kỳ bước nào làm đỏ test cũ, **dừng và sửa ngay**, không tích lũy.

---

## 8. TIÊU CHÍ HOÀN THÀNH (DoD)

### 8.1. Chức năng

- [ ] Bot bind `0.0.0.0:5000`; OBS Target Port 5000; nhận frame ở 144 FPS.
- [ ] Single-packet JPEG hoạt động; frame > 65 000 byte phân mảnh hoạt động; out-of-order hoạt động.
- [ ] Mảnh rơi/quá 5 ms bị hủy; không có frame ghép sai; `timeout_drops` tăng đúng.
- [ ] Slot không bao giờ sâu > 1; frame trả về là mới nhất.
- [ ] `disconnect()` trả về trong < 300 ms ở điều kiện bình thường (đo bằng QA M10); connect lại được sau disconnect.
- [ ] Bind trùng cổng trả `False` + thông điệp rõ, không treo.
- [ ] Beep 4455 gửi đúng IP/port; lỗi được log một lần, không spam; fallback ZMQ → UDP có log.
- [ ] `install.ps1` dò đúng OBS ở Registry/Steam/D/E; tạo rule firewall đúng chiều; cảnh báo VC++; thông điệp 144 FPS/Purple.
- [ ] Config mẫu plugin đúng Sens 0.23 / DPI 1100 / WindMouse / Flick / 5000 / schema 5.
- [ ] Tài liệu khớp cổng, IP, firewall, 144 FPS.

### 8.2. Kỹ thuật

- [ ] `python -m unittest discover -s tests` → 0 errors, 0 failures; số test ≥ baseline + 40.
- [ ] 5 file test mới xanh độc lập và khi discover (T1: 18, T2: 15, T3: 8, T4: 6, T5: 7 = 54 case). **Lưu ý đếm:** `unittest` chỉ `startTest()` các method không bị skip ở cấp class; nếu T2 bị skip toàn class vì thiếu TurboJPEG thì con số `Ran` sẽ thấp hơn — Tester phải giải thích, **không** được giả vờ đủ 54.
- [ ] `decode_delay_ms` p50 < 1.5 ms (TurboJPEG, máy Tester); p95 < 3.0 ms.
- [ ] `receive_delay_ms` p50 < 1.0 ms trong điều kiện LAN (QA thủ công).
- [ ] Không còn chuỗi `"3110"` trong default/runtime config (trừ test migration/history).
- [ ] Không còn `"1234"` trong default runtime (trừ test).
- [ ] `install.ps1` parse thành công bằng `[scriptblock]::Create`; chạy 2 lần không tạo rule trùng.
- [ ] Không thêm dependency Python mới; không import chéo `OBS-xUDP-Plugin`.
- [ ] API surface §2.10 không đổi; UI Pro/Simple không hồi quy.
- [ ] Không log mỗi packet/frame ở 144 FPS.

### 8.3. Bằng chứng bắt buộc trong `03-kiem-thu.md`

1. Lệnh + output **nguyên văn** của full suite (không cắt).
2. Lệnh + output riêng từng file test mới.
3. Bảng pass/fail theo R1–R18, L1–L15, G1–G8, N1–N6, O1–O7.
4. Số đo p50/p95 decode (nếu máy có TurboJPEG); nếu skip phải nêu lý do.
5. Kết quả QA thủ công M1–M12 (ai chạy, máy nào, ảnh/log nếu có).
6. Xác nhận `install.ps1` chạy trên ít nhất một máy có OBS thật (hoặc lý do không thể).

---

## 9. RỦI RO & GIẢM THIỂU

| ID | Rủi ro | Khả năng | Tác động | Giảm thiểu |
|---|---|---|---|---|
| P1 | Đổi default 3110 → 5000 làm người dùng cũ mất kết nối | Cao | Trung bình | Migration schema 5 + sửa file ship + thông điệp lỗi + tài liệu |
| P2 | Deadline 5 ms quá ngắn trên Wi-Fi chập chờn → rớt nhiều frame phân mảnh | Trung bình | Trung bình | Khuyến cáo LAN; cho phép `reassembly_timeout` qua constructor; log `timeout_drops` |
| P3 | `timeBeginPeriod` ảnh hưởng toàn process (tăng tiêu thụ điện) | Chắc chắn | Thấp | Refcount + chỉ bật khi connected + tắt khi disconnect |
| P4 | `THREAD_PRIORITY_HIGHEST` làm đói aim loop trên CPU yếu | Thấp | Trung bình | Đo QA; hạ decode xuống ABOVE_NORMAL nếu cần; không hạ receive |
| P5 | Bỏ `SO_REUSEADDR` làm test/QA không bind lại ngay được | Thấp | Thấp | UDP không có TIME_WAIT; dùng cổng khác cho test; đóng socket đúng |
| P6 | `SO_RCVBUF` 8 MB bị Windows cap | Trung bình | Thấp | Log giá trị thực; fallback 4 MB |
| P7 | Test latency 1.5 ms flaky trên CI | Cao | Thấp | p50/p95, warm-up, skip có lý do; không assert max |
| P8 | `install.ps1` bị policy chặn `New-NetFirewallRule` | Trung bình | Trung bình | Không fail cài plugin; in lệnh thủ công; exit code 2 |
| P9 | Registry OBS không tồn tại (bản portable/MSIX) | Trung bình | Trung bình | Fallback ổ đĩa + Steam + prompt |
| P10 | Nhầm UDP 4455 với OBS WebSocket TCP 4455 | Cao | Thấp | Bảng cổng trong 2 tài liệu; ghi rõ giao thức |
| P11 | Nhầm `dhz_port = 5000` với stream 5000 | Trung bình | Thấp | Ghi chú; không đổi key DHZ |
| P12 | Thay đổi `config.json` mẫu làm lệch tuning người dùng | Trung bình | Trung bình | Chỉ đổi 5 key chuẩn + thêm key thiếu; giữ nguyên còn lại |
| P13 | Hai receiver (bot + `receiver_ultra_fast.py`) chạy cùng lúc | Trung bình | Cao | Bỏ REUSEADDR + thông điệp lỗi + tài liệu |
| P14 | Test cũ `test_udp_receiver_latency` bị viết lại làm mất coverage | Thấp | Trung bình | Giữ tên file; test mới bao phủ rộng hơn; không xóa case cũ |
| P15 | `network_feedback_zmq.py` không tồn tại | Chắc chắn | Thấp | Fallback có log; không thêm dependency |
| P16 | Nhầm mã test `Gx` với mã task Coder `Cx` khi đối chiếu báo cáo | Trung bình | Thấp | §6.4 dùng tiền tố `G`; §7.4/§10.1 dùng `C1–C11` |
| P17 | `install.ps1` vô tình chứa chuỗi "240 FPS" trong câu cảnh báo → test O6 đỏ | Trung bình | Thấp | Ghi rõ ràng buộc văn bản ở §6.6; test O6 là chốt chặn |

### 9.1. Quyết định cần chốt (đã chốt trong kế hoạch)

| ID | Câu hỏi | Quyết định |
|---|---|---|
| D1 | Deadline cố định 5 ms hay adaptive theo FPS? | **Cố định 5 ms** theo yêu cầu; cho phép override qua constructor; tài liệu khuyến cáo 144 FPS |
| D2 | Có giữ `SO_REUSEADDR`? | **Bỏ** để bind trùng fail rõ |
| D3 | Có bump config schema? | **Có, lên 5**, migration một lần |
| D4 | Có thêm `audio_feedback_port`? | **Có**, default 4455, validate |
| D5 | Có sửa `receiver_ultra_fast.py`? | **Không** |
| D6 | Có import chéo plugin → bot? | **Không** |
| D7 | Có thêm entry UI cho beep port? | **Không** trong đợt này; dùng config/JSON |
| D8 | Có đổi `dhz_port`? | **Không**; chỉ ghi chú |
| D9 | Firewall inbound 5000 tạo trên PC1? | **Có mặc định** (theo yêu cầu "Outbound/Inbound 5000"); có switch `-SkipLocalReceiverRule` để tắt; in lệnh cho PC2 |
| D10 | Latency test assert gì? | **p50 < 1.5 ms, p95 < 3.0 ms**, skip nếu thiếu TurboJPEG/không phải Windows |

---

## 10. PHÂN RÃ CÔNG VIỆC / BÀN GIAO

### 10.1. Coder (11 task — mã `C1`…`C11` tách biệt với mã test `G1`…`G8`, theo đúng thứ tự §7.4)

| Task | Tệp | Đầu ra |
|---|---|---|
| C1 | `config.py`, `config*.json`, `configs/*.json`, `capture_service.py`, `ui.py` | Port 5000 + schema 5 + validate; test cũ xanh |
| C2 | `OBS_UDP.py` | `WindowsTimer`, `set_high_thread_priority`, `LatestFrameSlot` |
| C3 | `OBS_UDP.py` | `FrameReassembler` + test R1–R18 |
| C4 | `OBS_UDP.py` | Ingest/decode/connect/disconnect/stats mới |
| C5 | `OBS_UDP.py` | Async dùng chung pipeline; timer refcount |
| C6 | `network_feedback.py` | 4455 cấu hình + log + fallback |
| C7 | `ui.py` | Fallback/label/strip port |
| C8 | `OBS-xUDP-Plugin/config.json`, `cvm_config_optimized.json` | Bộ chuẩn v2.1 |
| C9 | `install.ps1` | Auto-detect + firewall + VC++ + 144 FPS |
| C10 | 2 tài liệu | Bảng cổng/IP/firewall/chẩn đoán |
| C11 | tất cả | Full suite + `02-thay-doi.md` |

### 10.2. Tester

1. Đọc kế hoạch này + `02-thay-doi.md`.
2. Viết/hoàn thiện T1–T5 theo §6; không sửa code sản phẩm.
3. Chạy T6 full suite; chạy riêng từng file; ghi output nguyên văn.
4. Chạy QA thủ công M1–M12 nếu có môi trường 2 máy; nếu không, ghi rõ giới hạn.
5. Đối chiếu DoD §8; lập bảng thiếu/đủ.
6. Ghi `03-kiem-thu.md` với bằng chứng, không tóm tắt thay output.

### 10.3. Reviewer

1. Kiểm tra API contract §2.10 bằng grep/đọc mã.
2. Kiểm tra không có `SO_REUSEADDR`, không còn default 3110/1234 trong runtime.
3. Kiểm tra `install.ps1` dùng `-RemotePort 5000` cho outbound (không phải `-LocalPort`).
4. Kiểm tra firewall 4455 ghi rõ UDP, không nhầm TCP.
5. Kiểm tra test latency không assert max; có skip hợp lý.
6. Kiểm tra config mẫu đúng 5 key chuẩn + schema 5.
7. Kiểm tra không sửa file trong §7.3.
8. Ký `04-danh-gia.md` với 1 trong 3 phán quyết.

---

## 11. PHỤ LỤC

### A. Định dạng gói tin (chốt)

**Single-packet:**

```
byte 0..1 : FF D8 (SOI)
byte 2..n : JPEG payload
byte n-1..n : FF D9 (EOI)   # không bắt buộc validate ở reassembler
```

**Fragmented:**

```
offset 0 : total_size   uint32 little-endian
offset 4 : frag_idx     uint16 little-endian
offset 6 : total_frags  uint16 little-endian
offset 8 : payload      (mảnh thứ frag_idx)
```

Ví dụ Python:

```python
import struct
header = struct.pack("<IHH", len(jpeg), idx, total)
packet = header + jpeg[start:end]
```

**Bảng giá trị 4 byte đầu và cách phân loại (ghim §2.5.2):**

| Trường hợp | 4 byte đầu | `total_size` LE | Kết luận |
|---|---|---|---|
| Single JPEG | `FF D8 FF E0` | ~3,77 tỷ | `>= 10 MB` + SOI đúng → single-packet |
| Single JPEG (marker khác) | `FF D8 FF DB`/`FF D8 FF C0`/`FF D8 FF C4` | ≥ 3,23 tỷ | như trên |
| Fragment frame 121 087 B | `FF D8 01 00` | 121 087 | `< 10 MB`, `1 < frags`, `idx < frags` → **fragment** (header thắng SOI) |
| Fragment frame 80 000 B | `80 38 01 00` | 80 000 | `< 10 MB`, không SOI → fragment |
| Fragment frame 186 623 B | `FF D8 02 00` | 186 623 | `< 10 MB` → fragment (header thắng SOI) |
| Fragment > 10 MB, không SOI | bất kỳ | ≥ 10 MB | `oversize_packets += 1`, `invalid += 1`, bỏ |
| Rác ngắn (< 8 B, không SOI) | bất kỳ | — | `invalid_packets += 1`, bỏ |

> **Về dòng "> 10 MB mà vẫn bắt đầu bằng `FF D8`":** điều này chỉ xảy ra khi `total_size ≥ 0xFFD80000` ≈ 4,29 tỷ byte (> 4 GB) — bất khả thi với JPEG từ OBS. Nếu có kẻ gửi dữ liệu độc hại như vậy, nó rơi xuống nhánh single-packet, `_decode_jpeg_frame_raw` từ chối (không phải JPEG hợp lệ, hoặc quá lớn để cấp phát), `decode_errors` tăng. Không có rủi ro cấp phát bộ nhớ vì decoder chỉ nhận `bytes` đã có sẵn trong datagram ≤ 65 535 byte. Không cần thêm nhánh đặc biệt.

### B. Toán thời gian

```
144 FPS: T = 6.9444 ms
Deadline: 5.0 ms
Margin: 1.9444 ms
Nếu decode 0.5 ms + callback 0.3 ms → còn 1.14 ms dự phòng
Nếu mảnh rơi ở 4.9 ms → frame bị hủy ở gói kế tiếp (≤ 5.1 ms), trước frame sau (6.94 ms)
Nếu mảnh rơi và không có gói kế tiếp → expire() hủy trong 5–6 ms
```

### C. Checklist chẩn đoán nhanh cho người dùng

1. **FPS = 0, Delay = 0:**
   - OBS Target Port có đúng 5000?
   - Bot `udp_port` có 5000? (UI Capture → UDP)
   - `netstat -ano | findstr :5000` trên PC2 có process bot không?
   - Firewall PC2 có cho UDP 5000?
   - PC1 và PC2 cùng subnet? Ping được?
2. **Có frame nhưng méo/xanh:**
   - `decode_errors` / `bad_frames` trong stats?
   - TurboJPEG DLL có đúng 64-bit? (`C:\libjpeg-turbo64\bin\turbojpeg.dll`)
   - OBS JPEG quality quá cao → frame > 65 KB → kiểm tra fragment (log `oversize`, `bad_frames`).
3. **Beep không kêu:**
   - `audio_feedback_enabled` true?
   - `audio_feedback_ip` = IP PC1?
   - Firewall PC1 UDP 4455 In?
   - `toggle_feedback_method` = `udp` (hoặc ZMQ fallback có log)?
4. **Bind fail:**
   - Đóng `receiver_ultra_fast.py`/bot instance khác.
   - Đổi port ở **cả** OBS và bot nếu buộc phải dùng port khác.
5. **Cài plugin fail:**
   - Chạy admin?
   - OBS 64-bit?
   - VC++ 2015–2022 x64?
   - Đường dẫn OBS có `bin\64bit\obs64.exe`?

### D. Bảng đối chiếu yêu cầu → mục kế hoạch

| Yêu cầu `task_prompt.md` | Mục |
|---|---|
| 1. Đồng bộ cổng 5000 toàn hệ thống | §1.3, §3.1–3.3, §5.3 |
| 1. Fallback & cấu hình IP/Port Audio Feedback 4455, log rõ | §3.4 |
| 2. `FrameReassembler` + deadline 5 ms | §2.5 |
| 2. Single + 8-byte fragment | §2.5.2–2.5.3, §11.A |
| 2. `WindowsTimer(1ms)` + priority | §2.3–2.4 |
| 2. TurboJPEG + OpenCV fallback, slot size-1 | §2.6–2.7 |
| 2. Giữ 100% API | §2.10 |
| 3. Auto-detect OBS Registry/fallback/custom | §4.2.2 |
| 3. Firewall OBS/UDP 4455/5000 | §4.2.6 |
| 3. VC++ 2015–2022 x64 | §4.2.7 |
| 3. Thông điệp 144 FPS & Purple v2.1 | §4.2.8, §4.3 |
| 4. Đồng bộ config mẫu v2.1 | §5.1–5.2 |
| 5. Test reassembler/receiver/regression | §6 |
| 6. Danh sách file + DoD | §7, §8 |

### E. Checklist review nhanh (Reviewer)

- [ ] `FrameReassembler` kiểm tra timeout **trước** khi xử lý gói mới.
- [ ] Header được kiểm tra **trước** SOI, và nhánh `total_size >= max_frame_bytes` chỉ coi là single-packet khi `data` **thực sự** bắt đầu bằng `FF D8` (tránh cả false-positive lẫn false-negative — xem §2.5.2).
- [ ] `total_size >= max_frame_bytes` bị chặn trước khi lưu mảnh (trừ khi là single JPEG hợp lệ).
- [ ] `expire()` được gọi từ decode worker, không chỉ từ packet arrival.
- [ ] Slot ghi đè, không block producer.
- [ ] `get_performance_stats()` giữ đủ key cũ.
- [ ] `_process_mjpeg_data` vẫn tồn tại và nhận single packet.
- [ ] `connect()` trả `False` khi bind lỗi; không `SO_REUSEADDR`.
- [ ] `disconnect()` đóng socket trước khi join; timer disable đúng.
- [ ] Không log per-packet; log bridge `_install_log_bridge_once` chỉ cài một handler và `propagate = False`.
- [ ] `MAX_FRAME_BYTES = 10_000_000` khớp plugin, **không** bị hạ về 4 MB.
- [ ] Không còn vòng lặp nóng nào gọi `logger.exception` mỗi frame.
- [ ] `install.ps1` outbound dùng `-RemotePort 5000`.
- [ ] Firewall 4455 ghi `UDP`, không `TCP`.
- [ ] Config mẫu `mouse_dpi == 1100` ở **cả hai** file.
- [ ] Không sửa `receiver_ultra_fast.py`.
- [ ] Test latency dùng p50/p95, có skip.
- [ ] Không còn `"3110"`/`"1234"` trong default runtime.
- [ ] Test cũ `test_udp_receiver_latency.py` **không bị xoá trắng**; các case cũ (single-slot decode, decode_delay < 1.5 ms, frame shape) vẫn hiện diện dưới dạng L2/L3/… sau khi viết lại.

---

**KẾT THÚC KẾ HOẠCH.** Coder thi công theo §7.4; Tester nghiệm thu theo §6/§8; Reviewer đối chiếu §11.E và ký `04-danh-gia.md`.
