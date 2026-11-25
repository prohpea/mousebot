import asyncio
import ctypes
import logging
import os
import socket
import struct
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from typing import Awaitable, Callable, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def _set_high_thread_priority() -> bool:
    """Boost current thread priority to THREAD_PRIORITY_HIGHEST on Windows."""
    if sys.platform == "win32":
        try:
            k32 = ctypes.windll.kernel32
            k32.GetCurrentThread.restype = ctypes.c_void_p
            k32.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
            k32.SetThreadPriority.restype = ctypes.c_int
            return bool(k32.SetThreadPriority(k32.GetCurrentThread(), 2))
        except Exception:
            pass
    return False


def _find_turbojpeg_dll() -> Optional[str]:
    """Locate bundled or system turbojpeg.dll without requiring PyTurboJPEG."""
    candidates = []
    try:
        from src.utils.app_paths import get_bundle_dir
        candidates.append(get_bundle_dir() / "turbojpeg.dll")
    except Exception:
        pass
    repo_root = Path(__file__).resolve().parents[2]
    candidates.extend([
        repo_root / "turbojpeg.dll",
        repo_root / "bin" / "64bit" / "turbojpeg.dll",
        Path(r"C:\libjpeg-turbo64\bin\turbojpeg.dll"),
        Path(r"C:\Program Files\obs-studio\bin\64bit\turbojpeg.dll"),
    ])
    for cand in candidates:
        try:
            if cand.is_file():
                return str(cand)
        except Exception:
            continue
    return None


class _CtypesTurboJPEG:
    """Zero-dependency ctypes binding to turbojpeg.dll (BGR output)."""

    TJPF_BGR = 1

    def __init__(self, dll_path: str):
        self.dll_path = dll_path
        self._lock = threading.Lock()
        self._dll = ctypes.CDLL(dll_path)

        self._dll.tjInitDecompress.restype = ctypes.c_void_p
        self._dll.tjInitDecompress.argtypes = []

        self._dll.tjDecompressHeader3.restype = ctypes.c_int
        self._dll.tjDecompressHeader3.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]

        self._dll.tjDecompress2.restype = ctypes.c_int
        self._dll.tjDecompress2.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ]

        self._dll.tjDestroy.restype = ctypes.c_int
        self._dll.tjDestroy.argtypes = [ctypes.c_void_p]

        self._handle = self._dll.tjInitDecompress()
        if not self._handle:
            raise RuntimeError("tjInitDecompress returned null handle")

    def decode(self, jpeg_bytes: bytes) -> Optional[np.ndarray]:
        with self._lock:
            if not self._handle:
                return None
            w = ctypes.c_int()
            h = ctypes.c_int()
            subsamp = ctypes.c_int()
            colorspace = ctypes.c_int()
            buf_len = len(jpeg_bytes)
            res = self._dll.tjDecompressHeader3(
                self._handle,
                jpeg_bytes,
                buf_len,
                ctypes.byref(w),
                ctypes.byref(h),
                ctypes.byref(subsamp),
                ctypes.byref(colorspace),
            )
            if res != 0 or w.value <= 0 or h.value <= 0 or w.value > 10000 or h.value > 10000:
                return None
            out = np.empty((h.value, w.value, 3), dtype=np.uint8)
            ret = self._dll.tjDecompress2(
                self._handle,
                jpeg_bytes,
                buf_len,
                out.ctypes.data,
                w.value,
                0,
                h.value,
                self.TJPF_BGR,
                0,
            )
            return out if ret == 0 else None

    def close(self):
        with self._lock:
            if self._handle and self._dll:
                try:
                    self._dll.tjDestroy(self._handle)
                except Exception:
                    pass
                self._handle = None

    def __del__(self):
        self.close()


# Optional PyTurboJPEG fallback if ctypes DLL load fails
_pyturbojpeg = None
_PYTURBO_TJPF_BGR = 1
try:
    from turbojpeg import TJPF_BGR as _PYTURBO_TJPF_BGR
    from turbojpeg import TurboJPEG as _PyTurboJPEGClass

    _dll_cand = _find_turbojpeg_dll()
    _pyturbojpeg = _PyTurboJPEGClass(_dll_cand) if _dll_cand else _PyTurboJPEGClass()
except Exception:
    _pyturbojpeg = None


def _create_fast_decoder() -> Tuple[Optional[object], str]:
    """Create the fastest available JPEG decoder and return (decoder, backend_label)."""
    dll_path = _find_turbojpeg_dll()
    if dll_path:
        try:
            return _CtypesTurboJPEG(dll_path), f"TurboJPEG (ctypes: {Path(dll_path).name})"
        except Exception as e:
            logger.warning(f"[UDP] ctypes TurboJPEG init failed ({dll_path}): {e}")
    if _pyturbojpeg is not None:
        return _pyturbojpeg, "TurboJPEG (PyTurboJPEG)"
    return None, "OpenCV (imdecode)"


class OBS_UDP_Receiver:
    """
    Ultra-low-latency OBS xUDP / MJPEG receiver:
      - Direct single-packet JPEG fast path (zero buffer copy/scan).
      - Hardened xUDP 8-byte fragment reassembly (<IHH) with 5ms timeout & size validation.
      - Thread-safe size-1 latest-frame slot (zero FIFO queue lag).
      - Zero-dependency ctypes TurboJPEG decoder with explicit backend telemetry.
      - 8MB SO_RCVBUF, 0.2s socket timeout, non-blocking disconnect, 0.0.0.0 bind fallback.
    """

    def __init__(self, ip: str = "0.0.0.0", port: int = 5000, target_fps: int = 144, max_workers: int = None):
        self.ip = ip
        self.port = int(port)
        self.target_fps = target_fps
        self.frame_interval = 1.0 / target_fps if target_fps > 0 else 0

        # Connection state
        self.socket = None
        self.is_connected = False
        self.is_receiving = False
        self.bound_address: Optional[Tuple[str, int]] = None

        # Threading / Async
        self.receive_thread = None
        self.processing_thread = None
        self.stop_event = threading.Event()
        self._loop = None
        self._loop_thread = None
        self._transport = None
        self._protocol = None

        # Legacy-compatible attributes (kept for external callers/callbacks)
        self.max_workers = max_workers if max_workers is not None else 1
        self.executor = None
        self.frame_queue = Queue(maxsize=1)
        self.processing_lock = threading.Lock()

        # Size-1 latest raw JPEG slot (eliminates 100-frame FIFO lag)
        self._latest_cond = threading.Condition()
        self._pending_raw: Optional[Tuple[bytes, float]] = None

        # Dedicated fast JPEG decoder
        self._decoder, self.decoder_backend = _create_fast_decoder()

        # Decoded frame state + monotonic sequence counter for dedup
        self.current_frame = None
        self.frame_seq = 0
        self.frame_lock = threading.Lock()
        self._frame_seq_cond = threading.Condition(self.frame_lock)
        self.frame_callback = None
        self.frame_callback_async: Optional[Callable[[np.ndarray], Awaitable[None]]] = None

        # Performance monitoring
        self._stats_start_time = time.perf_counter()
        self.fps_counter = 0
        self.last_fps_time = time.perf_counter()
        self.current_fps = 0.0
        self.processing_fps = 0.0
        self.last_processing_time = time.perf_counter()
        self.processing_counter = 0
        self.receive_delay = 0.0
        self.decode_time_ms = 0.0
        self.processing_delay = 0.0
        self.decoding_fps = 0.0
        self.decoding_counter = 0
        self.last_decoding_time = time.perf_counter()
        self.packets_received = 0
        self.bytes_received = 0
        self.reassembly_drops = 0
        self.queue_drops = 0
        self.decode_errors = 0

        # Fallback MJPEG stream buffer (only used for non-xUDP chunked MJPEG streams)
        self.mjpeg_buffer = bytearray()
        self.buffer_lock = threading.Lock()
        self.mjpeg_start_marker = b"\xff\xd8"
        self.mjpeg_end_marker = b"\xff\xd9"
        self.max_buffer_size = 2 * 1024 * 1024

        # xUDP fragmented-frame reassembly state (<IHH: total_size, frag_idx, total_frags)
        self._frag_timeout_sec = 0.005  # 5ms deadline tuned for 144 FPS (6.94ms budget)
        self._frag_total_size = 0
        self._frag_total_count = 0
        self._frag_chunks = {}
        self._frag_started_at = 0.0

        logger.info(
            f"OBS_UDP_Receiver initialized: {ip}:{port}, backend={self.decoder_backend}"
        )

    def set_frame_callback(self, callback: Callable[[np.ndarray], None]):
        self.frame_callback = callback

    def set_frame_callback_async(self, callback: Callable[[np.ndarray], Awaitable[None]]):
        self.frame_callback_async = callback

    def _bind_udp_socket(self, sock: socket.socket) -> Tuple[str, int]:
        bind_ip = str(self.ip or "0.0.0.0").strip() or "0.0.0.0"
        try:
            sock.bind((bind_ip, self.port))
            return (bind_ip, self.port)
        except OSError as e:
            if bind_ip not in ("0.0.0.0", "127.0.0.1"):
                logger.warning(
                    f"[UDP] Bind to {bind_ip}:{self.port} failed ({e}); falling back to 0.0.0.0:{self.port}"
                )
                sock.bind(("0.0.0.0", self.port))
                return ("0.0.0.0", self.port)
            raise

    def connect(self) -> bool:
        """Connect to UDP stream with 8MB SO_RCVBUF and size-1 latest-frame decoding."""
        try:
            if self.is_connected:
                self.disconnect()

            if self._decoder is None:
                self._decoder, self.decoder_backend = _create_fast_decoder()

            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                try:
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                except Exception:
                    pass
            else:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SIO_UDP_CONNRESET"):
                try:
                    self.socket.ioctl(socket.SIO_UDP_CONNRESET, False)
                except Exception:
                    pass
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
            except Exception as e:
                logger.warning(f"[UDP] Failed to set 8MB SO_RCVBUF: {e}")
            self.socket.settimeout(0.2)

            self.bound_address = self._bind_udp_socket(self.socket)

            self._stats_start_time = time.perf_counter()
            self.is_connected = True
            self.stop_event.clear()

            if self.frame_callback is not None:
                self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="UDPCallback")

            self.receive_thread = threading.Thread(
                target=self._receive_loop, name="UDPIngestionWorker", daemon=True
            )
            self.receive_thread.start()

            self.processing_thread = threading.Thread(
                target=self._frame_processing_loop, name="UDPDecodeWorker", daemon=True
            )
            self.processing_thread.start()

            logger.info(
                f"[UDP] Connected at {self.bound_address[0]}:{self.bound_address[1]} "
                f"| Decoder: {self.decoder_backend} | SO_RCVBUF: 8MB | Timeout: {self._frag_timeout_sec * 1000:.1f}ms"
            )
            return True

        except OSError as e:
            logger.error(f"Failed to connect to UDP stream: {e}")
            if self.socket:
                try:
                    self.socket.close()
                except Exception:
                    pass
                self.socket = None
            self.is_connected = False
            return False
        except Exception as e:
            logger.error(f"Unexpected error connecting to UDP stream: {e}")
            self.is_connected = False
            return False

    # -------------------- Async version --------------------
    class _UDPProtocol(asyncio.DatagramProtocol):
        def __init__(self, receiver: "OBS_UDP_Receiver"):
            self.receiver = receiver

        def datagram_received(self, data: bytes, addr):
            receive_time = time.perf_counter()
            try:
                self.receiver._process_mjpeg_data(data, receive_time)
            except Exception as e:
                logger.error(f"Protocol datagram handling error: {e}", exc_info=True)

        def error_received(self, exc):
            logger.error(f"UDP error received: {exc}")

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
        if self._decoder is None:
            self._decoder, self.decoder_backend = _create_fast_decoder()
        loop = asyncio.get_running_loop()
        bind_ip = str(self.ip or "0.0.0.0").strip() or "0.0.0.0"
        try:
            listen = await loop.create_datagram_endpoint(
                lambda: OBS_UDP_Receiver._UDPProtocol(self),
                local_addr=(bind_ip, self.port),
            )
        except OSError:
            listen = await loop.create_datagram_endpoint(
                lambda: OBS_UDP_Receiver._UDPProtocol(self),
                local_addr=("0.0.0.0", self.port),
            )
        self._transport, self._protocol = listen
        self.is_connected = True
        self.is_receiving = True
        self.stop_event.clear()

        if self.frame_callback is not None and self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="UDPCallback")

        if self.processing_thread is None or not self.processing_thread.is_alive():
            self.processing_thread = threading.Thread(
                target=self._frame_processing_loop, name="UDPDecodeWorker", daemon=True
            )
            self.processing_thread.start()

        logger.info(f"[async] Connected to UDP stream at {self.ip}:{self.port} | Decoder: {self.decoder_backend}")
        return True

    async def _disconnect_asyncio(self):
        try:
            self.is_receiving = False
            self.is_connected = False
            self.stop_event.set()

            with self._latest_cond:
                self._pending_raw = None
                self._latest_cond.notify_all()

            if self.executor:
                self.executor.shutdown(wait=False, cancel_futures=True)
                self.executor = None

            if self._transport is not None:
                self._transport.close()
                await asyncio.sleep(0.05)
                self._transport = None
            self._protocol = None

            if self._loop and self._loop_thread and self._loop_thread.is_alive():
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._loop_thread.join(timeout=1.0)
                self._loop = None
                self._loop_thread = None

            logger.info("[async] Disconnected from UDP stream")
        except Exception as e:
            logger.error(f"[async] Error during disconnect: {e}", exc_info=True)

    def connect_async(self) -> bool:
        try:
            self._ensure_loop_thread()
            fut = asyncio.run_coroutine_threadsafe(self._connect_asyncio(), self._loop)
            return bool(fut.result(timeout=5.0))
        except asyncio.TimeoutError:
            logger.error("Async connect timeout")
            return False
        except Exception as e:
            logger.error(f"Failed to start async UDP receiver: {e}", exc_info=True)
            return False

    def disconnect_async(self):
        try:
            if self._loop:
                fut = asyncio.run_coroutine_threadsafe(self._disconnect_asyncio(), self._loop)
                try:
                    fut.result(timeout=3.0)
                except (asyncio.TimeoutError, Exception):
                    pass
        except Exception as e:
            logger.error(f"Error scheduling async disconnect: {e}", exc_info=True)

    def disconnect(self):
        """Disconnect cleanly without blocking UI (close socket BEFORE joining thread)."""
        try:
            self.is_connected = False
            self.is_receiving = False
            self.stop_event.set()

            # Close socket FIRST so blocking recvfrom() unblocks immediately
            sock = self.socket
            self.socket = None
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

            # Wake decoder & any frame_seq waiter immediately
            with self._latest_cond:
                self._pending_raw = None
                self._latest_cond.notify_all()
            with self._frame_seq_cond:
                self._frame_seq_cond.notify_all()

            if self.receive_thread and self.receive_thread.is_alive():
                self.receive_thread.join(timeout=1.0)
            self.receive_thread = None

            if self.processing_thread and self.processing_thread.is_alive():
                self.processing_thread.join(timeout=1.0)
            self.processing_thread = None

            if self.executor:
                self.executor.shutdown(wait=False, cancel_futures=True)
                self.executor = None

            with self.buffer_lock:
                self.mjpeg_buffer.clear()
            self._reset_fragment_assembly(mark_dropped=False)

            with self.frame_lock:
                self.current_frame = None

            if isinstance(self._decoder, _CtypesTurboJPEG):
                self._decoder.close()
                self._decoder = None

            logger.info("Disconnected from UDP stream")

        except Exception as e:
            logger.error(f"Error during disconnect: {e}", exc_info=True)

    def _receive_loop(self):
        """High-priority UDP ingestion loop."""
        _set_high_thread_priority()
        self.is_receiving = True
        logger.info("Started UDP receive loop")

        while not self.stop_event.is_set() and self.is_connected:
            sock = self.socket
            if sock is None:
                break
            try:
                data, _addr = sock.recvfrom(65536)
                if not data:
                    continue
                receive_time = time.perf_counter()
                self.packets_received += 1
                self.bytes_received += len(data)
                self._process_mjpeg_data(data, receive_time)
            except socket.timeout:
                continue
            except OSError as e:
                if not self.is_connected or self.stop_event.is_set() or self.socket is None:
                    break
                logger.warning(f"Transient UDP socket error in receive loop: {e}")
                time.sleep(0.005)
                continue
            except Exception as e:
                if self.is_connected:
                    logger.error(f"Error in receive loop: {e}", exc_info=True)
                break

        self.is_receiving = False
        logger.info("UDP receive loop ended")

    def _frame_processing_loop(self):
        """Dedicated size-1 latest-frame decoder thread (zero stale frame buildup)."""
        logger.info("Started frame processing loop")

        while not self.stop_event.is_set() and self.is_connected:
            try:
                with self._latest_cond:
                    if self._pending_raw is None:
                        self._latest_cond.wait(timeout=0.1)
                    if self._pending_raw is None:
                        continue
                    jpeg_data, receive_time = self._pending_raw
                    self._pending_raw = None

                t0 = time.perf_counter()
                frame = self._decode_jpeg_frame(jpeg_data, receive_time)
                self.decode_time_ms = (time.perf_counter() - t0) * 1000.0
                if frame is not None:
                    self._update_frame(frame, receive_time)
                else:
                    self.decode_errors += 1
            except Exception as e:
                if self.is_connected:
                    logger.error(f"Error in frame processing loop: {e}", exc_info=True)
                continue

        logger.info("Frame processing loop ended")

    def _reset_fragment_assembly(self, mark_dropped: bool = False):
        if mark_dropped and self._frag_chunks:
            self.reassembly_drops += 1
        self._frag_chunks.clear()
        self._frag_total_size = 0
        self._frag_total_count = 0
        self._frag_started_at = 0.0

    def _submit_jpeg_frame(self, jpeg_data: bytes, receive_time: float) -> bool:
        if len(jpeg_data) < 100 or len(jpeg_data) > 10 * 1024 * 1024:
            return False
        if self.stop_event.is_set():
            return False
        with self._latest_cond:
            if self._pending_raw is not None:
                self.queue_drops += 1
            self._pending_raw = (jpeg_data, receive_time)
            self._latest_cond.notify()
        return True

    def _try_reassemble_xudp_fragment(
        self, data: bytes, receive_time: float
    ) -> Tuple[bool, Optional[bytes]]:
        """Handle xUDP 8-byte fragmented packets (<IHH: total_size, frag_idx, total_frags)."""
        if not data or len(data) < 8:
            return False, None
        total_size, frag_idx, total_frags = struct.unpack_from("<IHH", data)
        if not (65000 < total_size < 10_000_000 and 1 < total_frags <= 1000 and frag_idx < total_frags):
            return False, None

        now = time.perf_counter()
        if self._frag_chunks and (now - self._frag_started_at > self._frag_timeout_sec):
            self._reset_fragment_assembly(mark_dropped=True)

        if self._frag_chunks and (
            self._frag_total_size != total_size
            or self._frag_total_count != total_frags
            or frag_idx in self._frag_chunks
        ):
            self._reset_fragment_assembly(mark_dropped=True)

        payload = data[8:]
        if not payload or len(payload) > total_size:
            self.reassembly_drops += 1
            return True, None

        if not self._frag_chunks:
            self._frag_total_size = total_size
            self._frag_total_count = total_frags
            self._frag_started_at = now
            self._frag_bytes_buffered = 0

        if getattr(self, "_frag_bytes_buffered", 0) + len(payload) > total_size:
            self._reset_fragment_assembly(mark_dropped=True)
            return True, None

        self._frag_chunks[frag_idx] = payload
        self._frag_bytes_buffered = getattr(self, "_frag_bytes_buffered", 0) + len(payload)

        if len(self._frag_chunks) == self._frag_total_count:
            assembled = b"".join(self._frag_chunks[i] for i in range(self._frag_total_count))
            self._reset_fragment_assembly(mark_dropped=False)
            if len(assembled) == total_size and assembled.startswith(b"\xff\xd8"):
                return True, assembled
            self.reassembly_drops += 1
            return True, None

        return True, None

    def _process_mjpeg_data(self, data: bytes, receive_time: float):
        """Process incoming UDP datagram with zero-copy single-packet xUDP fast path."""
        try:
            # 1. Handle xUDP fragmented packets (>65KB)
            is_frag, assembled = self._try_reassemble_xudp_fragment(data, receive_time)
            if is_frag:
                if assembled is not None:
                    self._submit_jpeg_frame(assembled, receive_time)
                return

            # 2. Fast path: complete single-packet JPEG frame (standard xUDP 320x320 ~7-15KB)
            if data.startswith(self.mjpeg_start_marker) and data.endswith(self.mjpeg_end_marker):
                if self._frag_chunks:
                    self._reset_fragment_assembly(mark_dropped=True)
                if self.mjpeg_buffer:
                    with self.buffer_lock:
                        self.mjpeg_buffer.clear()
                self._submit_jpeg_frame(data, receive_time)
                return

            # 3. Fallback: stream-buffered MJPEG (for legacy/chunked MJPEG senders)
            with self.buffer_lock:
                self.mjpeg_buffer.extend(data)
                buffer_len = len(self.mjpeg_buffer)
                if buffer_len > self.max_buffer_size:
                    logger.debug(f"MJPEG buffer too large ({buffer_len} bytes), clearing")
                    self.mjpeg_buffer.clear()
                    return
                buffer = bytes(self.mjpeg_buffer)

            frames_processed = 0
            max_frames_per_packet = 5
            bytes_removed_from_start = 0

            while frames_processed < max_frames_per_packet:
                start_pos = buffer.find(self.mjpeg_start_marker)
                if start_pos == -1:
                    if len(buffer) > 2048:
                        with self.buffer_lock:
                            if len(self.mjpeg_buffer) > 1024:
                                self.mjpeg_buffer = self.mjpeg_buffer[-1024:]
                    break

                if start_pos > 0:
                    bytes_removed_from_start += start_pos
                    buffer = buffer[start_pos:]

                end_pos = buffer.find(self.mjpeg_end_marker, 2)
                if end_pos == -1:
                    break

                frame_end_pos = end_pos + 2
                jpeg_data = buffer[:frame_end_pos]
                bytes_removed_from_start += frame_end_pos
                buffer = buffer[frame_end_pos:]

                if 100 <= len(jpeg_data) <= 10 * 1024 * 1024:
                    self._submit_jpeg_frame(jpeg_data, receive_time)
                    frames_processed += 1

            if bytes_removed_from_start > 0:
                with self.buffer_lock:
                    if bytes_removed_from_start <= len(self.mjpeg_buffer):
                        self.mjpeg_buffer = self.mjpeg_buffer[bytes_removed_from_start:]

        except Exception as e:
            logger.error(f"Error processing MJPEG data: {e}", exc_info=True)
            with self.buffer_lock:
                self.mjpeg_buffer.clear()

    def _decode_jpeg_frame(self, jpeg_data: bytes, receive_time: float) -> Optional[np.ndarray]:
        """Decode JPEG bytes into a BGR numpy image via TurboJPEG or OpenCV fallback."""
        try:
            if len(jpeg_data) < 100:
                return None
            if not (jpeg_data.startswith(b"\xff\xd8") and jpeg_data.endswith(b"\xff\xd9")):
                return None

            frame = None
            decoder = self._decoder
            if isinstance(decoder, _CtypesTurboJPEG):
                try:
                    frame = decoder.decode(jpeg_data)
                except Exception:
                    frame = None
            elif decoder is not None:
                try:
                    frame = decoder.decode(jpeg_data, pixel_format=_PYTURBO_TJPF_BGR)
                except Exception:
                    frame = None

            if frame is None:
                nparr = np.frombuffer(jpeg_data, np.uint8)
                try:
                    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                except cv2.error:
                    try:
                        frame = cv2.imdecode(nparr, cv2.IMREAD_ANYCOLOR)
                    except cv2.error:
                        return None

            if frame is None or frame.size == 0:
                return None
            if len(frame.shape) < 2 or frame.shape[0] <= 0 or frame.shape[1] <= 0:
                return None

            height, width = frame.shape[:2]
            if height < 10 or width < 10 or height > 10000 or width > 10000:
                return None

            if self._is_frame_corrupted(frame):
                return None

            self.receive_delay = max(0.0, (time.perf_counter() - receive_time) * 1000.0)
            return frame

        except cv2.error:
            pass
        except Exception:
            pass
        return None

    @staticmethod
    def _is_frame_corrupted(frame: np.ndarray) -> bool:
        """
        Validate basic frame structure without rejecting valid dark / contrast-crushed
        xUDP frames (where corners and center can legitimately be pure black).
        """
        try:
            if frame is None or frame.size == 0 or frame.ndim < 2:
                return True
            h, w = frame.shape[:2]
            return h < 10 or w < 10
        except Exception:
            return True

    def _update_frame(self, frame: np.ndarray, receive_time: float):
        """Publish newly decoded frame, bump frame_seq, and notify waiters/callbacks."""
        try:
            with self._frame_seq_cond:
                self.current_frame = frame
                self.frame_seq += 1
                self._frame_seq_cond.notify_all()

            now = time.perf_counter()
            with self.processing_lock:
                self.decoding_counter += 1
                if now - self.last_decoding_time >= 1.0:
                    self.decoding_fps = self.decoding_counter / (now - self.last_decoding_time)
                    self.decoding_counter = 0
                    self.last_decoding_time = now

            self._update_fps_counters()

            processing_start = time.perf_counter()
            if self.frame_callback_async and self._loop:
                try:
                    asyncio.run_coroutine_threadsafe(self.frame_callback_async(frame.copy()), self._loop)
                except Exception as e:
                    logger.error(f"Error scheduling async frame callback: {e}")
            if self.frame_callback:
                try:
                    if self.executor:
                        self.executor.submit(self.frame_callback, frame.copy())
                    else:
                        self.frame_callback(frame.copy())
                except Exception as e:
                    logger.error(f"Frame callback error: {e}", exc_info=True)
            processing_end = time.perf_counter()

            with self.processing_lock:
                self.processing_delay = (processing_end - processing_start) * 1000.0
                self.processing_counter += 1
                if processing_end - self.last_processing_time >= 1.0:
                    self.processing_fps = self.processing_counter / (processing_end - self.last_processing_time)
                    self.processing_counter = 0
                    self.last_processing_time = processing_end

        except Exception as e:
            logger.error(f"Error updating frame: {e}", exc_info=True)

    def _update_fps_counters(self):
        current_time = time.perf_counter()
        self.fps_counter += 1
        if current_time - self.last_fps_time >= 1.0:
            self.current_fps = self.fps_counter / (current_time - self.last_fps_time)
            self.fps_counter = 0
            self.last_fps_time = current_time

    def get_current_frame(self) -> Optional[np.ndarray]:
        with self.frame_lock:
            return self.current_frame.copy() if self.current_frame is not None else None

    def get_current_frame_with_seq(self) -> Tuple[Optional[np.ndarray], int]:
        """Return (frame_copy_or_None, frame_seq) atomically."""
        with self.frame_lock:
            frame = self.current_frame.copy() if self.current_frame is not None else None
            return frame, self.frame_seq

    def wait_for_new_frame(self, last_seq: int, timeout: float = 0.015) -> Tuple[Optional[np.ndarray], int]:
        """Wait up to `timeout` seconds for a frame with frame_seq > last_seq."""
        with self._frame_seq_cond:
            if self.frame_seq <= last_seq and self.is_connected and not self.stop_event.is_set():
                self._frame_seq_cond.wait(timeout=timeout)
            if self.frame_seq <= last_seq or self.current_frame is None:
                return None, self.frame_seq
            return self.current_frame.copy(), self.frame_seq

    def get_performance_stats(self) -> dict:
        with self.buffer_lock:
            buffer_size = len(self.mjpeg_buffer)
        with self.processing_lock:
            processing_fps = self.processing_fps
            processing_delay = self.processing_delay
            decoding_fps = self.decoding_fps
        with self._latest_cond:
            q_size = 1 if self._pending_raw is not None else 0
        elapsed = max(0.001, time.perf_counter() - self._stats_start_time)
        bitrate_mbps = (self.bytes_received * 8.0) / (elapsed * 1_000_000.0)

        return {
            "current_fps": self.current_fps,
            "processing_fps": processing_fps,
            "decoding_fps": decoding_fps,
            "target_fps": self.target_fps,
            "receive_delay_ms": self.receive_delay,
            "decode_time_ms": self.decode_time_ms,
            "processing_delay_ms": processing_delay,
            "is_connected": self.is_connected,
            "is_receiving": self.is_receiving,
            "buffer_size_bytes": buffer_size,
            "queue_size": q_size,
            "max_workers": self.max_workers,
            "decoder_backend": self.decoder_backend,
            "frame_seq": self.frame_seq,
            "packets_received": self.packets_received,
            "reassembly_drops": self.reassembly_drops,
            "queue_drops": self.queue_drops,
            "decode_errors": self.decode_errors,
            "bitrate_mbps": bitrate_mbps,
        }

    def set_target_fps(self, fps: int):
        self.target_fps = max(1, fps)
        self.frame_interval = 1.0 / self.target_fps if self.target_fps > 0 else 0
        logger.info(f"Target FPS set to {self.target_fps} (monitoring only, no limit enforced)")

    def update_connection_params(self, ip: str, port: int):
        self.ip = ip
        self.port = int(port)
        logger.info(f"Connection parameters updated: {ip}:{port}")


class OBS_UDP_Manager:
    """High-level manager for OBS UDP stream connections."""

    def __init__(self):
        self.receiver = None
        self.is_connected = False

    def create_receiver(self, ip: str, port: int, target_fps: int = 144) -> OBS_UDP_Receiver:
        self.receiver = OBS_UDP_Receiver(ip, port, target_fps)
        return self.receiver

    def connect(self, ip: str, port: int, target_fps: int = 144) -> bool:
        if self.receiver:
            self.receiver.disconnect()

        self.receiver = OBS_UDP_Receiver(ip, port, target_fps)
        success = self.receiver.connect()
        self.is_connected = success
        return success

    def connect_async(self, ip: str, port: int, target_fps: int = 144) -> bool:
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
        if self.receiver:
            self.receiver.disconnect()
            self.receiver = None
        self.is_connected = False

    def get_receiver(self) -> Optional[OBS_UDP_Receiver]:
        return self.receiver

    def is_stream_active(self) -> bool:
        return bool(self.is_connected and self.receiver and self.receiver.is_receiving)
