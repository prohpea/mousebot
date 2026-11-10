"""Zero-lag UDP receiver for the OBS xUDP MJPEG stream (plan v2.1).

Pipeline (three stages, no backlog anywhere):

    recv thread -> FrameReassembler (5.0 ms deadline) -> LatestFrameSlot (size 1)
                -> decode thread (TurboJPEG, OpenCV fallback) -> get_current_frame()

Wire formats accepted (see plan §11.A):

* single-packet frame: a whole JPEG in one datagram (starts with ``FF D8``);
* fragmented frame: 8-byte header ``<IHH`` = total_size, frag_idx, total_frags
  followed by the JPEG slice for that index (the plugin fragments > 65 000 B).

Nothing else is accepted: a raw byte stream without the 8-byte header is not
supported any more (plan §2.8.4), because it cannot be told apart from a corrupt
fragment and silently produced truncated frames.
"""

try:
    import cv2
except Exception:
    cv2 = None
import socket
import struct
import sys
import threading
import time
import asyncio
try:
    import ctypes
except Exception:
    import types
    class _MockWinDLL:
        def __init__(self, *args, **kwargs):
            pass
        def timeBeginPeriod(self, *args, **kwargs):
            return 1
        def timeEndPeriod(self, *args, **kwargs):
            return 1
        def GetCurrentThread(self, *args, **kwargs):
            return 1
        def SetThreadPriority(self, *args, **kwargs):
            return 1
    ctypes = types.SimpleNamespace(
        WinDLL=_MockWinDLL,
        c_void_p=object,
        c_int=object,
    )
import numpy as np
from typing import Optional, Callable, Tuple, Awaitable
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import logging
import os

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Public defaults (single source of truth: the OBS xUDP plugin sends to 5000)
# --------------------------------------------------------------------------
DEFAULT_UDP_IP = "0.0.0.0"
DEFAULT_UDP_PORT = 5000

# 5.0 ms = 72 % of the 144 FPS frame period (6.944 ms). A stale assembly is
# dropped before the next frame can arrive, so fragments never mix frames.
FRAME_TIMEOUT_SEC = 0.005
# Matches receiver_ultra_fast.py; enough for 1080p at JPEG quality 95.
# Do NOT lower this to the legacy 4 MB buffer: that would drop real frames.
MAX_FRAME_BYTES = 10_000_000
FRAGMENT_HEADER = struct.Struct("<IHH")
FRAGMENT_MIN_TOTAL = 65_000   # the plugin only fragments above this size
MAX_FRAGMENTS = 1000
SOCKET_RCVBUF_BYTES = 8 * 1024 * 1024
SOCKET_RCVBUF_FALLBACK = 4 * 1024 * 1024
RECV_TIMEOUT_SEC = 0.1
SLOT_WAIT_SEC = 0.001

# Optional TurboJPEG for faster CPU JPEG decode
_jpeg = None
try:
    from turbojpeg import TurboJPEG, TJPF_BGR
    dll_candidates = [
        r"C:\libjpeg-turbo64\bin\turbojpeg.dll",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "turbojpeg.dll")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "bin", "64bit", "turbojpeg.dll")),
    ]
    for cand in dll_candidates:
        if os.path.exists(cand):
            try:
                if hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(os.path.dirname(cand))
                _jpeg = TurboJPEG(cand)
                if _jpeg is not None:
                    break
            except Exception:
                continue
    if _jpeg is None:
        _jpeg = TurboJPEG()
except Exception:
    _jpeg = None

_DECODER_BACKEND = "TurboJPEG" if _jpeg is not None else "OpenCV"


# --------------------------------------------------------------------------
# logging -> debug_logger bridge (plan §2.11.1)
# --------------------------------------------------------------------------
class _DebugLoggerBridge(logging.Handler):
    """Forward UDP receiver records into the app's in-UI debug log."""

    def emit(self, record):
        try:
            from src.utils.debug_logger import log_print

            log_print(f"[UDP] {self.format(record)}")
        except Exception:
            pass


def _install_log_bridge_once():
    """Attach exactly one bridge handler to this module's logger."""
    if getattr(logger, "_cvm_bridge_installed", False):
        return
    handler = _DebugLoggerBridge()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # never duplicate into root/stderr
    logger._cvm_bridge_installed = True


# --------------------------------------------------------------------------
# WindowsTimer: process-wide timeBeginPeriod with a refcount (plan §2.3)
# --------------------------------------------------------------------------
_TIMER_LOCK = threading.Lock()
_TIMER_REFCOUNT = 0
_TIMER_ACTIVE = False
_TIMER_WARNED = False


class WindowsTimer:
    """Reference-counted ``timeBeginPeriod(1)`` wrapper.

    ``timeBeginPeriod`` is process-wide, so two receivers must not turn the
    timer off for each other: the last ``disable()`` wins.
    """

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
                logger.warning(
                    "[UDP] timeBeginPeriod(%d) unavailable; timing falls back to OS default",
                    self.period_ms,
                )
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

    def __enter__(self):
        self.enable()
        return self

    def __exit__(self, *exc):
        self.disable()


def set_high_thread_priority() -> bool:
    """Raise the calling thread to THREAD_PRIORITY_HIGHEST. Never raises."""
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


# --------------------------------------------------------------------------
# FrameReassembler (plan §2.5)
# --------------------------------------------------------------------------
class FrameReassembler:
    """Turn UDP datagrams into complete JPEG frames, or drop them fast.

    Classification order matters and is deliberate: the 8-byte header is
    examined BEFORE the JPEG SOI check. A valid fragment whose ``total_size``
    is e.g. 121 087 starts with ``FF D8 01 00`` (SOI!), so checking SOI first
    would misclassify it as a single packet and lose the whole frame.
    A real single-packet JPEG always has ``total_size >= 0xC0FFD8FF`` (~3.2 B)
    because its 4th byte is a JPEG marker, so it always takes the
    ``total_size >= max_frame_bytes`` branch and then correctly falls through
    to the SOI branch.
    """

    def __init__(self, timeout_sec: float = FRAME_TIMEOUT_SEC,
                 max_frame_bytes: int = MAX_FRAME_BYTES):
        self.timeout_sec = float(timeout_sec)
        self.max_frame_bytes = int(max_frame_bytes)
        self._lock = threading.RLock()

        self._fragments: dict = {}
        self._cur_total_size = 0
        self._cur_total_frags = 0
        self._started_at = 0.0
        self._buffered_bytes = 0
        self._last_frame_ts = 0.0

        # Counters (written under the lock, read directly: int reads under the
        # GIL are atomic and a one-frame skew in telemetry is irrelevant).
        self.completed_frames = 0
        self.dropped_frames = 0
        self.timeout_drops = 0
        self.restart_drops = 0
        self.invalid_packets = 0
        self.oversize_packets = 0
        self.bad_frames = 0

    # -- internal helpers (caller must hold the lock) ----------------------
    def _reset_locked(self):
        self._fragments.clear()
        self._cur_total_size = 0
        self._cur_total_frags = 0
        self._started_at = 0.0
        self._buffered_bytes = 0
        # NOTE: _last_frame_ts is intentionally kept so the caller can still
        # read the timestamp of the frame that was just completed.

    def _drop_locked(self, reason: str):
        if self._fragments:
            self.dropped_frames += 1
            if reason == "timeout":
                self.timeout_drops += 1
            elif reason == "restart":
                self.restart_drops += 1
        self._reset_locked()

    # -- public API --------------------------------------------------------
    def process_packet(self, data: bytes, now: Optional[float] = None) -> Optional[bytes]:
        """Feed one datagram. Returns complete JPEG bytes, or None."""
        if not data or len(data) < 2:
            with self._lock:
                self.invalid_packets += 1
            return None
        now = time.perf_counter() if now is None else float(now)

        with self._lock:
            # (A) Deadline first: any packet arriving checks the open assembly.
            if self._fragments and (now - self._started_at) > self.timeout_sec:
                self._drop_locked("timeout")

            # (B) Header before SOI (safe, see class docstring).
            if len(data) >= 8:
                total_size, frag_idx, total_frags = FRAGMENT_HEADER.unpack_from(data)

                if total_size >= self.max_frame_bytes:
                    # Cannot be a real fragment. Might still be a single JPEG
                    # (its first 4 bytes read as a huge size) -> fall through.
                    if not data.startswith(b"\xff\xd8"):
                        self.oversize_packets += 1
                        self.invalid_packets += 1
                        return None

                elif (FRAGMENT_MIN_TOTAL < total_size
                      and 1 < total_frags <= MAX_FRAGMENTS
                      and frag_idx < total_frags):
                    # ---- valid fragment ----
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

            # (C) Single packet
            if data[:2] == b"\xff\xd8":
                if self._fragments:
                    self._drop_locked("restart")
                self._last_frame_ts = now
                self.completed_frames += 1
                return data

            # (D) Junk
            self.invalid_packets += 1
            return None

    def expire(self, now: Optional[float] = None) -> bool:
        """Drop a stale open assembly. Called by the decode worker when idle."""
        now = time.perf_counter() if now is None else float(now)
        with self._lock:
            if self._fragments and (now - self._started_at) > self.timeout_sec:
                self._drop_locked("timeout")
                return True
        return False

    def reset(self, mark_dropped: bool = False) -> None:
        with self._lock:
            if mark_dropped and self._fragments:
                self.dropped_frames += 1
            self._reset_locked()
            self._last_frame_ts = 0.0

    # Plugin-compatible alias.
    reset_assembly = reset

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


# --------------------------------------------------------------------------
# LatestFrameSlot: size-1, overwrite-on-write, zero backlog (plan §2.6)
# --------------------------------------------------------------------------
class LatestFrameSlot:
    """Single-slot container: the newest frame always wins, producers never block."""

    def __init__(self):
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._item = None  # (jpeg: bytes, recv_ts: float, frame_id: int)
        self.enqueued = 0
        self.dropped_unconsumed = 0

    def put(self, item) -> None:
        with self._lock:
            if self._item is not None:
                self.dropped_unconsumed += 1
            self._item = item
            self.enqueued += 1
            self._event.set()  # set inside the lock

    def get_nowait(self):
        with self._lock:
            item, self._item = self._item, None
            self._event.clear()  # cleared in the same lock as put()
            return item

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)

    def clear(self) -> None:
        with self._lock:
            self._item = None
            self._event.clear()

    def wake(self) -> None:
        """Wake a waiting consumer without pushing a frame (used on shutdown)."""
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


# --------------------------------------------------------------------------
# Receiver
# --------------------------------------------------------------------------
class OBS_UDP_Receiver:
    """
    OBS UDP receiver for the MJPEG stream from OBS Studio (xUDP plugin).

    Public API is unchanged from the pre-v2.1 receiver (plan §2.10): only
    keyword-only ``reassembly_timeout`` and ``force_opencv`` were added.
    """

    def __init__(self, ip: str = DEFAULT_UDP_IP, port: int = DEFAULT_UDP_PORT,
                 target_fps: int = 60, max_workers: int = None, *,
                 reassembly_timeout: float = FRAME_TIMEOUT_SEC,
                 force_opencv: bool = False):
        """
        Args:
            ip: local interface to bind (0.0.0.0 = every interface)
            port: UDP port to bind; must match the OBS Target Port (5000)
            target_fps: monitoring only, never rate limits the pipeline
            max_workers: kept for compatibility, unused by the v2.1 pipeline
            reassembly_timeout: fragment deadline in seconds (default 5.0 ms)
            force_opencv: skip TurboJPEG even when the DLL is present (tests/QA)
        """
        _install_log_bridge_once()

        self.ip = ip
        self.port = port
        self.target_fps = target_fps  # Kept for compatibility, not used for limiting
        self.frame_interval = 1.0 / target_fps if target_fps > 0 else 0  # Not enforced

        # Connection state
        self.socket = None
        self.is_connected = False
        self.is_receiving = False

        # Threading / Async
        self.receive_thread = None
        self.processing_thread = None
        self.stop_event = threading.Event()
        self._loop = None  # asyncio loop (background thread)
        self._loop_thread = None
        self._transport = None  # asyncio.DatagramTransport
        self._protocol = None   # protocol instance

        # --- v2.1 zero-lag pipeline ---
        self.reassembly_timeout = float(reassembly_timeout)
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

        # Counters (additive; none of the old names collide)
        self.packets_received = 0
        self.bytes_received = 0
        self.frames_received = 0
        self.frames_decoded = 0
        self.decode_errors = 0
        self.last_frame_id = 0

        # Legacy single-slot attributes kept so external scripts do not break.
        # They are not used by the v2.1 pipeline.
        self._slot_lock = threading.Lock()
        self._latest_jpeg_slot = None   # legacy, unused by v2.1 pipeline
        self._frame_ready_event = threading.Event()  # legacy, unused
        self._frame_start_time = None   # legacy, unused

        # Multi-threaded frame processing (kept for compatibility)
        self.max_workers = max_workers if max_workers is not None else min(8, (threading.active_count() or 1) + 4)
        self.executor = None
        self.frame_queue = Queue(maxsize=10)  # legacy, unused by v2.1 pipeline
        self.processing_lock = threading.Lock()

        # Frame processing
        self.current_frame = None
        self.frame_lock = threading.Lock()
        self.frame_callback = None
        self.frame_callback_async: Optional[Callable[[np.ndarray], Awaitable[None]]] = None

        # Performance monitoring
        self.fps_counter = 0
        self.last_fps_time = time.time()
        self.current_fps = 0.0
        self.processing_fps = 0.0
        self.last_processing_time = time.time()
        self.processing_counter = 0
        self.receive_delay = 0.0
        self.decode_delay = 0.0
        self.processing_delay = 0.0
        self.decoding_fps = 0.0
        self.decoding_counter = 0
        self.last_decoding_time = time.time()

        # Legacy MJPEG buffer (always empty now; the reassembler owns assembly).
        self.mjpeg_buffer = bytearray()  # legacy, unused by v2.1 pipeline
        self.buffer_lock = threading.Lock()
        self.mjpeg_start_marker = b'\xff\xd8'
        self.mjpeg_end_marker = b'\xff\xd9'
        self.max_buffer_size = 4 * 1024 * 1024  # legacy limit only

        logger.info(
            "OBS_UDP_Receiver initialized: %s:%s, max_workers=%d, timeout=%.4fs, decoder=%s",
            ip, port, self.max_workers, self.reassembly_timeout,
            "OpenCV (forced)" if self._force_opencv else _DECODER_BACKEND,
        )

    # ------------------------------------------------------------------
    # callbacks
    # ------------------------------------------------------------------
    def set_frame_callback(self, callback: Callable[[np.ndarray], None]):
        """Set the sync callback invoked (with a copy) for every decoded frame."""
        self.frame_callback = callback

    def set_frame_callback_async(self, callback: Callable[[np.ndarray], Awaitable[None]]):
        """Set the async callback; scheduled on the internal asyncio loop."""
        self.frame_callback_async = callback

    # ------------------------------------------------------------------
    # connect / disconnect
    # ------------------------------------------------------------------
    def connect(self) -> bool:
        """Bind the UDP port and start the receive + decode threads."""
        try:
            if self.is_connected:
                self.disconnect()

            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket = sock  # assign now so _abort_connect() can close it
            # Deliberately NO SO_REUSEADDR: a duplicate bind must fail loudly
            # instead of silently splitting datagrams between two processes.
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
            # Set BEFORE starting the threads: the UI calls is_stream_active()
            # right after connect() and must not observe a False race window.
            self.is_receiving = True

            self.receive_thread = threading.Thread(
                target=self._receive_loop, name="UDPReceiveWorker", daemon=True)
            self.receive_thread.start()
            self.processing_thread = threading.Thread(
                target=self._decode_worker_loop, name="UDPDecodeWorker", daemon=True)
            self.processing_thread.start()

            logger.info(
                "[UDP] listening on %s:%s rcvbuf=%d timer=%s decoder=%s",
                self.ip, self.port, actual_rcvbuf, self._timer_active, _DECODER_BACKEND)
            return True
        except OSError as exc:
            logger.error(
                "[UDP] bind %s:%s failed: %s. Port %s may be in use by "
                "receiver_ultra_fast.py or another CVM-colorBot instance. "
                "Close that process, or change the port in BOTH OBS and the bot.",
                self.ip, self.port, exc, self.port)
            self._abort_connect()
            return False
        except Exception as exc:
            logger.error("[UDP] unexpected connect error on %s:%s: %s",
                         self.ip, self.port, exc, exc_info=True)
            self._abort_connect()
            return False

    def _close_socket_quietly(self):
        sock, self.socket = self.socket, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _abort_connect(self):
        """Undo a partially completed connect(). Idempotent."""
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

    def disconnect(self):
        """Stop both threads and release the socket without hanging the UI."""
        try:
            self.is_connected = False
            self.is_receiving = False
            self.stop_event.set()
            self._slot.wake()  # release a worker parked in wait(1 ms)

            # Close the socket BEFORE joining: that is what releases recvfrom().
            self._close_socket_quietly()

            receive_thread = self.receive_thread
            if receive_thread and receive_thread.is_alive():
                receive_thread.join(timeout=0.5)
                if receive_thread.is_alive():
                    logger.warning("[UDP] receive thread did not stop within 0.5s")

            self.receive_thread = None

            processing_thread = self.processing_thread
            if processing_thread and processing_thread.is_alive():
                processing_thread.join(timeout=0.5)
                if processing_thread.is_alive():
                    logger.warning("[UDP] decode thread did not stop within 0.5s")

            self.processing_thread = None

            if self.executor:
                self.executor.shutdown(wait=False, cancel_futures=True)
                self.executor = None

            # Drain the legacy queue if anything ever put something in it.
            while not self.frame_queue.empty():
                try:
                    self.frame_queue.get_nowait()
                except Exception:
                    break

            self._reassembler.reset(mark_dropped=True)
            self._slot.clear()

            with self.frame_lock:
                self.current_frame = None

            self._timer_active = False
            self._timer.disable()

            logger.info("[UDP] disconnected from %s:%s", self.ip, self.port)
        except Exception as exc:
            logger.error("[UDP] error during disconnect: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Async version
    # ------------------------------------------------------------------
    class _UDPProtocol(asyncio.DatagramProtocol):
        """Asyncio protocol: datagrams go straight into the shared ingest path."""

        def __init__(self, receiver: "OBS_UDP_Receiver"):
            self.receiver = receiver

        def datagram_received(self, data: bytes, addr):
            try:
                # Ingest only: never decode on the event loop thread.
                self.receiver._ingest_datagram(data, time.perf_counter())
            except Exception as exc:
                logger.error("[UDP][async] protocol datagram error: %s", exc, exc_info=True)

        def error_received(self, exc):
            logger.error("[UDP][async] socket error: %s", exc)

    def _ensure_loop_thread(self):
        if self._loop and self._loop_thread and self._loop_thread.is_alive():
            return

        self._loop = asyncio.new_event_loop()

        def run_loop(loop: asyncio.AbstractEventLoop):
            asyncio.set_event_loop(loop)
            loop.run_forever()

        self._loop_thread = threading.Thread(target=run_loop, args=(self._loop,), daemon=True)
        self._loop_thread.start()

    async def _connect_asyncio(self):
        if self.is_connected:
            await self._disconnect_asyncio()

        loop = asyncio.get_running_loop()

        # Build the socket by hand: create_datagram_endpoint(local_addr=...)
        # cannot raise SO_RCVBUF above the OS default (~64 KB), which is far
        # below the v2.1 8 MB requirement.
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
            logger.error("[UDP][async] bind %s:%s failed: %s", self.ip, self.port, exc)
            return False

        try:
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: OBS_UDP_Receiver._UDPProtocol(self),
                sock=sock,  # pre-bound socket; never pass local_addr as well
            )
        except Exception as exc:
            sock.close()  # asyncio did not take ownership
            logger.error("[UDP][async] endpoint failed: %s", exc, exc_info=True)
            return False

        self._transport, self._protocol = transport, protocol
        self._timer_active = self._timer.enable()
        self._reassembler.reset(mark_dropped=False)
        self._slot.clear()
        self.stop_event.clear()
        self.is_connected = True
        self.is_receiving = True

        # Decode off the event loop, same worker as the sync path.
        if not self.processing_thread or not self.processing_thread.is_alive():
            self.processing_thread = threading.Thread(
                target=self._decode_worker_loop, name="UDPDecodeWorker", daemon=True)
            self.processing_thread.start()

        logger.info("[UDP][async] listening on %s:%s rcvbuf=%d timer=%s",
                    self.ip, self.port, self.rcvbuf_bytes, self._timer_active)
        return True

    async def _disconnect_asyncio(self):
        try:
            self.is_receiving = False
            self.is_connected = False
            self.stop_event.set()
            self._slot.wake()

            if self.executor:
                self.executor.shutdown(wait=False, cancel_futures=True)
                self.executor = None

            while not self.frame_queue.empty():
                try:
                    self.frame_queue.get_nowait()
                except Exception:
                    break

            if self._transport is not None:
                self._transport.close()
                await asyncio.sleep(0.05)  # let ownership close the socket
                self._transport = None
            self._protocol = None

            processing_thread = self.processing_thread
            if processing_thread and processing_thread.is_alive():
                processing_thread.join(timeout=0.5)
            self.processing_thread = None

            self._reassembler.reset(mark_dropped=True)
            self._slot.clear()
            with self.frame_lock:
                self.current_frame = None
            self._timer_active = False
            self._timer.disable()

            if self._loop and self._loop_thread and self._loop_thread.is_alive():
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._loop_thread.join(timeout=2.0)
                self._loop = None
                self._loop_thread = None

            logger.info("[UDP][async] disconnected")
        except Exception as exc:
            logger.error("[UDP][async] error during disconnect: %s", exc, exc_info=True)

    def connect_async(self) -> bool:
        """Start the asyncio receiver in a background loop thread."""
        try:
            self._ensure_loop_thread()
            fut = asyncio.run_coroutine_threadsafe(self._connect_asyncio(), self._loop)
            return bool(fut.result(timeout=5.0))
        except asyncio.TimeoutError:
            logger.error("[UDP][async] connect timeout")
            return False
        except Exception as exc:
            logger.error("[UDP][async] failed to start receiver: %s", exc, exc_info=True)
            return False

    def disconnect_async(self):
        """Stop the asyncio receiver and close the transport."""
        try:
            if self._loop:
                fut = asyncio.run_coroutine_threadsafe(self._disconnect_asyncio(), self._loop)
                try:
                    fut.result(timeout=3.0)
                except (asyncio.TimeoutError, Exception):
                    pass
        except Exception as exc:
            logger.error("[UDP][async] error scheduling disconnect: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # receive path
    # ------------------------------------------------------------------
    def _receive_loop(self):
        """Receive thread: read datagrams, hand them to the reassembler."""
        self.is_receiving = True
        self._receive_priority_ok = set_high_thread_priority()
        logger.info("[UDP] receive loop started (priority=%s)", self._receive_priority_ok)

        sock = self.socket  # local ref: disconnect() will set self.socket = None
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
                try:
                    self._ingest_datagram(data, recv_ts)
                except Exception as exc:
                    self._warn_rate_limited("[UDP] ingest error", exc)
        finally:
            self.is_receiving = False
            logger.info("[UDP] receive loop ended")

    def _warn_rate_limited(self, prefix: str, exc):
        """Log a hot-path error at most once per ``_warn_interval`` seconds."""
        now = time.perf_counter()
        if (now - self._last_warn_ts) >= self._warn_interval:
            self._last_warn_ts = now
            logger.warning("%s: %s", prefix, exc)

    def _publish_frame(self, jpeg_data: bytes, recv_ts: float) -> None:
        """Count a complete frame and hand it to the size-1 slot."""
        with self._stats_lock:
            self.frames_received += 1
            frame_id = self.frames_received
        self._slot.put((jpeg_data, recv_ts, frame_id))

    def _ingest_datagram(self, data: bytes, recv_ts: float):
        """Receive thread / asyncio protocol only. Never decodes."""
        with self._stats_lock:
            self.packets_received += 1
            self.bytes_received += len(data)

        frame = self._reassembler.process_packet(data, now=recv_ts)
        if frame is None:
            return
        # last_frame_ts still holds the timestamp of the frame just completed.
        first_ts = self._reassembler.last_frame_ts or recv_ts
        self._publish_frame(frame, first_ts)

    def _process_mjpeg_data(self, data: bytes, receive_time: float):
        """Backward-compatible ingest entry (async protocol + legacy tests)."""
        self._ingest_datagram(data, receive_time)

    # ------------------------------------------------------------------
    # decode path
    # ------------------------------------------------------------------
    def _decode_worker_loop(self):
        """Decode thread: newest slot frame -> TurboJPEG/OpenCV -> current_frame."""
        self._decode_priority_ok = set_high_thread_priority()
        logger.info("[UDP] decode loop started (priority=%s, backend=%s)",
                    self._decode_priority_ok,
                    "OpenCV (forced)" if self._force_opencv else _DECODER_BACKEND)
        consecutive_errors = 0

        while not self.stop_event.is_set() and self.is_connected:
            try:
                item = self._slot.get_nowait()
                if item is None:
                    # Wait up to 1 ms, then re-check the slot. get_nowait()
                    # clears the event under the same lock as put(), so a
                    # stray wake() cannot turn this into a busy spin.
                    if self._slot.wait(SLOT_WAIT_SEC):
                        item = self._slot.get_nowait()
                    if item is None:
                        # No frame for 1 ms: reclaim a half-reassembled frame
                        # so a dead stream cannot pin memory.
                        self._reassembler.expire()
                        continue

                jpeg_data, recv_ts, frame_id = item
                t0 = time.perf_counter()
                frame = self._decode_jpeg_frame_raw(jpeg_data)
                t1 = time.perf_counter()

                if frame is None:
                    with self._stats_lock:
                        self.decode_errors += 1
                    consecutive_errors = 0
                    continue

                with self._stats_lock:
                    self.decode_delay = (t1 - t0) * 1000.0
                    self.receive_delay = max(0.0, (t0 - recv_ts) * 1000.0)
                    self.last_frame_id = frame_id
                    self.frames_decoded += 1

                consecutive_errors = 0
                self._update_frame(frame)

            except Exception as exc:
                # Never log per-frame at 144 Hz: that would be the lag.
                consecutive_errors += 1
                if consecutive_errors == 1 or consecutive_errors % 720 == 0:
                    logger.error("[UDP] decode worker error (x%d): %s",
                                 consecutive_errors, exc, exc_info=True)
                continue

        logger.info("[UDP] decode loop ended")

    def _frame_processing_loop(self):
        """Backward-compatible alias for the decode loop"""
        return self._decode_worker_loop()

    def _decode_jpeg_frame_raw(self, jpeg_data: bytes) -> Optional[np.ndarray]:
        """Decode a JPEG with TurboJPEG, falling back to OpenCV."""
        try:
            if len(jpeg_data) < 100:
                return None
            # Cheap guard. The reassembler guarantees SOI but not EOI, so keep
            # both checks instead of relaxing them.
            if not (jpeg_data.startswith(b'\xff\xd8') and jpeg_data.endswith(b'\xff\xd9')):
                return None

            if _jpeg is not None and not self._force_opencv:
                try:
                    return _jpeg.decode(jpeg_data, pixel_format=TJPF_BGR)
                except Exception:
                    # A corrupt frame is not a backend failure: try OpenCV for
                    # THIS frame only, and keep TurboJPEG for the next ones.
                    pass

            if cv2 is not None:
                nparr = np.frombuffer(jpeg_data, np.uint8)
                try:
                    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    if frame is not None and frame.size > 0:
                        return frame
                except Exception:
                    return None
        except Exception:
            return None
        return None

    def _decode_jpeg_frame(self, jpeg_data: bytes, receive_time: float) -> Optional[np.ndarray]:
        """Legacy helper for testing and backward compatibility"""
        t0 = time.perf_counter()
        frame = self._decode_jpeg_frame_raw(jpeg_data)
        t1 = time.perf_counter()
        if frame is not None:
            self.decode_delay = (t1 - t0) * 1000.0
            self.receive_delay = max(0.0, (t0 - receive_time) * 1000.0)
            self._update_frame(frame)
        return frame

    @staticmethod
    def _is_frame_corrupted(frame: np.ndarray) -> bool:
        """Fast corruption check using sampling instead of full array scan"""
        try:
            h, w = frame.shape[:2]
            sample_points = [
                frame[0, 0], frame[0, -1], frame[-1, 0], frame[-1, -1],
                frame[h // 2, w // 2]
            ]
            if len(set(tuple(sample) for sample in sample_points)) == 1:
                return True
            if all(np.all(sample == 0) for sample in sample_points):
                return True
            return False
        except Exception:
            return True

    def _update_frame(self, frame: np.ndarray, receive_time: float = 0.0):
        """Publish the decoded frame, then run callbacks with copies."""
        try:
            with self.frame_lock:
                self.current_frame = frame

            # decoding FPS + processing counters share processing_lock; the
            # block ends before any callback runs (no lock while calling out).
            with self.processing_lock:
                self.decoding_counter += 1
                current_time = time.time()
                if current_time - self.last_decoding_time >= 1.0:
                    self.decoding_fps = self.decoding_counter / (current_time - self.last_decoding_time)
                    self.decoding_counter = 0
                    self.last_decoding_time = current_time

            self._update_fps_counters()

            if self.frame_callback or (self.frame_callback_async and self._loop):
                processing_start = time.perf_counter()
                if self.frame_callback_async and self._loop:
                    try:
                        asyncio.run_coroutine_threadsafe(self.frame_callback_async(frame.copy()), self._loop)
                    except Exception as e:
                        logger.error("[UDP] error scheduling async frame callback: %s", e)
                if self.frame_callback:
                    try:
                        self.frame_callback(frame.copy())
                    except Exception as e:
                        logger.error("[UDP] frame callback error: %s", e, exc_info=True)
                processing_end = time.perf_counter()
                with self.processing_lock:
                    self.processing_delay = (processing_end - processing_start) * 1000.0
                    self.processing_counter += 1
                    if processing_end - self.last_processing_time >= 1.0:
                        self.processing_fps = self.processing_counter / (processing_end - self.last_processing_time)
                        self.processing_counter = 0
                        self.last_processing_time = processing_end
            else:
                self.processing_delay = 0.0
        except Exception as e:
            logger.error("[UDP] error updating frame: %s", e, exc_info=True)

    def _update_fps_counters(self):
        """Update decoded-frame FPS. Called once per frame, so the lock is cheap."""
        with self._stats_lock:
            current_time = time.time()
            self.fps_counter += 1

            if current_time - self.last_fps_time >= 1.0:
                self.current_fps = self.fps_counter / (current_time - self.last_fps_time)
                self.fps_counter = 0
                self.last_fps_time = current_time

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    def get_current_frame(self) -> Optional[np.ndarray]:
        """Return the newest decoded frame (zero-copy)."""
        with self.frame_lock:
            return self.current_frame

    def get_performance_stats(self) -> dict:
        """Performance telemetry. Every legacy key is preserved verbatim."""
        # 1) slot/reassembler expose their own locks: read them BEFORE _stats_lock.
        buffered = self._reassembler.buffered_bytes
        queue_size = self._slot.depth
        queue_drops = self._slot.drops

        # 2) processing_* / decoding_fps keep living under processing_lock.
        with self.processing_lock:
            processing_fps = self.processing_fps
            processing_delay = self.processing_delay
            decoding_fps = self.decoding_fps

        # 3) receiver counters.
        with self._stats_lock:
            return {
                # --- legacy keys, unchanged ---
                'current_fps': self.current_fps,
                'processing_fps': processing_fps,
                'decoding_fps': decoding_fps,
                'target_fps': self.target_fps,
                'receive_delay_ms': self.receive_delay,
                'decode_delay_ms': self.decode_delay,
                'processing_delay_ms': processing_delay,
                'is_connected': self.is_connected,
                'is_receiving': self.is_receiving,
                'buffer_size_bytes': buffered,
                'queue_size': queue_size,
                'max_workers': self.max_workers,
                # --- v2.1 additive keys ---
                'queue_drops': queue_drops,
                'reassembly_drops': self._reassembler.dropped_frames,
                'timeout_drops': self._reassembler.timeout_drops,
                'restart_drops': self._reassembler.restart_drops,
                'invalid_packets': self._reassembler.invalid_packets,
                'oversize_packets': self._reassembler.oversize_packets,
                'bad_frames': self._reassembler.bad_frames,
                'frames_received': self.frames_received,
                'frames_decoded': self.frames_decoded,
                'decode_errors': self.decode_errors,
                'packets_received': self.packets_received,
                'bytes_received': self.bytes_received,
                'decoder_backend': ('OpenCV (forced)' if self._force_opencv else _DECODER_BACKEND),
                'timer_active': self._timer_active,
                'rcvbuf_bytes': self.rcvbuf_bytes,
                'receive_priority_ok': self._receive_priority_ok,
                'decode_priority_ok': self._decode_priority_ok,
                'last_frame_id': self.last_frame_id,
            }

    def set_target_fps(self, fps: int):
        """Set target FPS (monitoring only, no limit enforced)."""
        self.target_fps = max(1, fps)
        self.frame_interval = 1.0 / self.target_fps if self.target_fps > 0 else 0
        logger.info("[UDP] target FPS set to %d (monitoring only, no limit enforced)",
                    self.target_fps)

    def update_connection_params(self, ip: str, port: int):
        """Update connection parameters (takes effect on the next connect())."""
        self.ip = ip
        self.port = port
        logger.info("[UDP] connection parameters updated: %s:%s", ip, port)


class OBS_UDP_Manager:
    """
    Manager class for OBS UDP connections
    Provides high-level interface for UDP stream management
    """

    def __init__(self):
        self.receiver = None
        self.is_connected = False

    def create_receiver(self, ip: str, port: int = DEFAULT_UDP_PORT,
                        target_fps: int = 60) -> OBS_UDP_Receiver:
        """Create a new UDP receiver (default port is the plugin's 5000)."""
        self.receiver = OBS_UDP_Receiver(ip, port, target_fps)
        return self.receiver

    def connect(self, ip: str, port: int = DEFAULT_UDP_PORT, target_fps: int = 60) -> bool:
        """Connect to the UDP stream, replacing any current receiver."""
        if self.receiver:
            self.receiver.disconnect()

        self.receiver = OBS_UDP_Receiver(ip, port, target_fps)
        success = self.receiver.connect()
        self.is_connected = success
        return success

    # -------------------- Async helpers --------------------
    def connect_async(self, ip: str, port: int = DEFAULT_UDP_PORT, target_fps: int = 60) -> bool:
        """Connect using the asyncio-based receiver in a background loop."""
        if self.receiver:
            try:
                self.receiver.disconnect_async()
            except Exception:
                pass
        self.receiver = OBS_UDP_Receiver(ip, port, target_fps)
        success = self.receiver.connect_async()
        self.is_connected = success
        return success

    def disconnect_async(self):
        if self.receiver:
            self.receiver.disconnect_async()
            self.receiver = None
        self.is_connected = False

    def disconnect(self):
        """Disconnect from UDP stream"""
        if self.receiver:
            self.receiver.disconnect()
            self.receiver = None
        self.is_connected = False

    def get_receiver(self) -> Optional[OBS_UDP_Receiver]:
        """Get current receiver instance"""
        return self.receiver

    def is_stream_active(self) -> bool:
        """Check if stream is active"""
        return bool(self.is_connected and self.receiver and self.receiver.is_receiving)
