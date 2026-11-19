import cv2
import socket
import struct
import threading
import time
import asyncio
import ctypes
import numpy as np
from typing import Optional, Callable, Tuple, Awaitable
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import logging

logger = logging.getLogger(__name__)

# OBS xUDP plugin fragments frames larger than 65 000 B, prefixing every
# datagram with an 8-byte header: <IHH = total_size, frag_idx, total_frags.
# Splicing those headers into a raw byte stream injects binary garbage into the
# JPEG payload every MTU, which decodes as banding/garbage rather than failing
# outright, so the damage is invisible to a "did it decode?" check.
FRAGMENT_HEADER = struct.Struct("<IHH")
FRAGMENT_MIN_TOTAL = 65_000     # smaller frames are sent whole, without a header
FRAGMENT_MAX_TOTAL = 10_000_000  # sanity bound; above this it cannot be a fragment
FRAGMENT_MAX_COUNT = 1000

# Default reassembly deadline. The plugin sends every fragment of one frame back
# to back, so 8 ms is already generous at 144 Hz (6.94 ms/frame); a partial
# assembly older than this belongs to a frame that will never complete.
FRAGMENT_TIMEOUT_MS_DEFAULT = 8.0
RCVBUF_MB_DEFAULT = 8

# A partial JPEG cannot survive this long: MJPEG frames are sent back to back,
# so a start marker older than a second belongs to a datagram lost while the
# sender kept going. Left in place, its timestamp would be glued to the next
# complete frame and every latency/measurement downstream would be wrong.
MJPEG_BUFFER_MAX_AGE_S = 1.0

# Socket rebind backoff after a hard socket error while the stream is supposed
# to be live (Windows WSAECONNRESET on a socket that was never connected is the
# everyday case). Capped so a port squatted by another instance is retried
# forever without burning a core.
SOCKET_REBIND_DELAYS = (0.1, 0.2, 0.5, 1.0)

# The config object is resolved once: the fragment path runs per datagram, and a
# fresh ``import`` on every packet is measurable at 100+ fragments per frame.
_CONFIG = None


def _config():
    global _CONFIG
    if _CONFIG is None:
        try:
            from src.utils.config import config as _cfg
            _CONFIG = _cfg
        except Exception:
            _CONFIG = False
    return _CONFIG or None


def _read_int_config(name, default):
    cfg = _config()
    try:
        value = getattr(cfg, name, None)
        return int(default if value is None else value)
    except Exception:
        return int(default)


def _read_float_config(name, default):
    cfg = _config()
    try:
        value = getattr(cfg, name, None)
        return float(default if value is None else value)
    except Exception:
        return float(default)


def _read_bool_config(name, default):
    cfg = _config()
    try:
        value = getattr(cfg, name, None)
        return bool(default if value is None else value)
    except Exception:
        return bool(default)


def _try_set_thread_high_priority():
    """Best-effort HIGHEST priority for a real-time thread; Windows only.

    Deliberately not REALTIME_PRIORITY: that can starve the UI thread and the
    tracking thread this receiver feeds. Returns True when the call succeeded.
    """
    if not hasattr(ctypes, "windll"):
        return False
    try:
        handle = ctypes.windll.kernel32.GetCurrentThread()
        # THREAD_PRIORITY_HIGHEST == 2
        return bool(ctypes.windll.kernel32.SetThreadPriority(handle, 2))
    except Exception:
        return False

# Optional TurboJPEG for faster CPU JPEG decode
_jpeg = None
try:
    import os
    from turbojpeg import TurboJPEG, TJPF_BGR
    dll_candidates = [
        r"C:\libjpeg-turbo64\bin\turbojpeg.dll",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "turbojpeg.dll")),
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


class OBS_UDP_Receiver:
    """
    OBS UDP receiver for MJPEG stream from OBS Studio
    Supports receiving Motion JPEG stream over UDP protocol
    """
    
    def __init__(self, ip: str = "192.168.0.1", port: int = 1234, target_fps: int = 60, max_workers: int = None,
                 bind_ip: Optional[str] = None):
        """
        Initialize OBS UDP receiver
        
        Args:
            ip: IP address to receive UDP stream from (the sender, for reference/logging)
            port: Port number to receive UDP stream on
            target_fps: Target FPS for processing (deprecated, kept for compatibility)
            max_workers: Maximum number of worker threads for frame processing (None = auto)
            bind_ip: Local address to bind. None/"0.0.0.0" listens on every interface,
                which is almost always what a receiver wants.
        """
        self.ip = ip
        self.port = port
        self.bind_ip = bind_ip
        self.target_fps = target_fps  # Kept for compatibility, not used for limiting
        self.frame_interval = 1.0 / target_fps if target_fps > 0 else 0  # Not enforced
        
        # Connection state
        self.socket = None
        self.is_connected = False
        self.is_receiving = False
        # A successful bind only proves the port was free; it says nothing about
        # whether packets ever arrive. Track arrivals so a silent black stream can
        # be reported instead of looking like a healthy connection.
        self.packet_count = 0
        self.last_packet_time = 0.0
        self._bind_addr = None
        
        # Threading / Async
        self.receive_thread = None
        self.processing_thread = None
        self.stop_event = threading.Event()
        self._loop = None  # asyncio loop (background thread)
        self._loop_thread = None
        self._transport = None  # asyncio.DatagramTransport
        self._protocol = None   # protocol instance
        
        # Single-slot dedicated real-time frame decoder (Zero backlog)
        self._slot_lock = threading.Lock()
        self._latest_jpeg_slot = None
        self._frame_ready_event = threading.Event()
        self._frame_start_time = None

        # Multi-threaded frame processing (kept for compatibility)
        self.max_workers = max_workers if max_workers is not None else min(8, (threading.active_count() or 1) + 4)
        self.executor = None
        self.frame_queue = Queue(maxsize=10)
        self.processing_lock = threading.Lock()
        
        # Frame processing
        self.current_frame = None
        self.frame_lock = threading.Lock()
        # Published-frame counter + condition on the same lock. Consumers wait
        # for "a frame newer than seq N" instead of polling get_current_frame(),
        # and because publish and wait share frame_lock a wakeup can be missed
        # only if the frame was published before the read, never in between.
        self._frame_cond = threading.Condition(self.frame_lock)
        self._frame_seq = 0
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
        
        # MJPEG buffer - use bytearray for zero-copy in-place slicing
        self.mjpeg_buffer = bytearray()
        self.buffer_lock = threading.Lock()
        self.mjpeg_start_marker = b'\xff\xd8'
        self.mjpeg_end_marker = b'\xff\xd9'
        self.max_buffer_size = 4 * 1024 * 1024  # 4MB limit

        # OBS xUDP fragment reassembly state (see _try_reassemble_fragment)
        self._frag_parts = {}
        self._frag_total_size = 0
        self._frag_total_count = 0
        self._frag_started_at = 0.0
        self._frag_bytes = 0
        self.fragment_drops = 0

        # Latency metadata for the most recently published frame. Kept in its
        # own lock so readers never touch frame_lock (consumers block there).
        self._frame_meta_lock = threading.Lock()
        self._last_frame_meta = {}

        # Socket tuning, captured at connect() so stats can report what the OS
        # actually granted rather than what was requested.
        self.rcvbuf_requested_bytes = 0
        self.rcvbuf_actual_bytes = 0

        # Seam for tests: a decoder that can be blocked or replaced without
        # touching the real TurboJPEG path.
        self._decode_fn = self._decode_jpeg_frame_raw
        self._priority_threads = set()
        
        logger.info(f"OBS_UDP_Receiver initialized: {ip}:{port}, max_workers={self.max_workers}")
    
    def set_frame_callback(self, callback: Callable[[np.ndarray], None]):
        """
        Set callback function for frame processing
        
        Args:
            callback: Function to call with each received frame
        """
        self.frame_callback = callback
    
    def set_frame_callback_async(self, callback: Callable[[np.ndarray], Awaitable[None]]):
        """
        Set async callback function for frame processing.
        The coroutine will be scheduled on the internal asyncio loop thread.
        """
        self.frame_callback_async = callback
    
    def _reset_stream_state(self):
        """Drop partial frames/buffers so a reconnect starts from a clean slate."""
        with self.buffer_lock:
            self.mjpeg_buffer.clear()
        self._frame_start_time = None
        self._frag_parts = {}
        self._frag_total_size = 0
        self._frag_total_count = 0
        self._frag_started_at = 0.0
        self._frag_bytes = 0
        with self._slot_lock:
            self._latest_jpeg_slot = None
        with self._frame_meta_lock:
            self._last_frame_meta = {}

    def _configure_socket(self, sock) -> int:
        """Apply receive-buffer sizing and return the size the OS actually granted.

        Windows silently clamps SO_RCVBUF, so the requested value is worthless as
        evidence: only a getsockopt read-back tells whether the kernel really
        reserved the buffer (the sender is asked for 8 MB for the same reason).
        """
        requested_mb = _read_int_config("receiver_rcvbuf_mb", RCVBUF_MB_DEFAULT)
        requested_mb = max(1, min(64, int(requested_mb)))
        requested = requested_mb * 1024 * 1024
        self.rcvbuf_requested_bytes = requested
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, requested)
        except OSError as exc:
            logger.warning(f"Could not set SO_RCVBUF to {requested} bytes: {exc}")
        actual = 0
        try:
            actual = int(sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF))
        except OSError:
            actual = 0
        self.rcvbuf_actual_bytes = actual
        logger.info(
            f"SO_RCVBUF requested {requested / (1024 * 1024):.1f} MB, "
            f"actual {actual / (1024 * 1024):.1f} MB"
        )
        return actual

    def connect(self) -> bool:
        """
        Connect to UDP stream
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            if self.is_connected:
                self.disconnect()
            
            # Create UDP socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Deliberately NO SO_REUSEADDR. On Windows it lets a second process
            # bind the same UDP port successfully while the first one keeps
            # receiving, so a stale bot instance silently swallows the stream:
            # the new instance reports "connected" and shows black forever.
            # Without it, a duplicate bind fails loudly with WinError 10048.
            # Increase receive buffer size for high FPS streams and zero packet
            # drop. Windows clamps this value, so _configure_socket() reads it
            # back and the granted number is what stats report.
            self._configure_socket(self.socket)
            self.socket.settimeout(1.0)  # 1 second timeout

            # Bind to the wildcard address, not to self.ip. self.ip is the
            # SENDER's address used for logging; binding the receiver to it means
            # packets arriving on any other interface (loopback, second NIC,
            # VPN) are dropped by the kernel before this process ever sees them.
            # For a receiver the correct bind is INADDR_ANY on the port.
            bind_addr = (self.bind_ip or "0.0.0.0", self.port)
            self.socket.bind(bind_addr)
            self._bind_addr = bind_addr
            self.packet_count = 0
            self.last_packet_time = 0.0
            
            self.is_connected = True
            self.stop_event.clear()
            self._frame_ready_event.clear()
            self._reset_stream_state()

            # Start receiving thread
            self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.receive_thread.start()
            
            # Start dedicated ultra-low-latency decoding worker
            self.processing_thread = threading.Thread(target=self._decode_worker_loop, daemon=True)
            self.processing_thread.start()
            
            logger.info(f"Connected to UDP stream at {self.ip}:{self.port}")
            return True
            
        except OSError as e:
            logger.error(f"Failed to connect to UDP stream: {e}")
            self.is_connected = False
            return False
        except Exception as e:
            logger.error(f"Unexpected error connecting to UDP stream: {e}")
            self.is_connected = False
            return False

    # -------------------- Async version --------------------
    class _UDPProtocol(asyncio.DatagramProtocol):
        """Asyncio protocol to receive UDP datagrams and forward to receiver."""
        def __init__(self, receiver: "OBS_UDP_Receiver"):
            self.receiver = receiver

        def datagram_received(self, data: bytes, addr):
            receive_time = time.perf_counter()
            self.receiver.packet_count += 1
            self.receiver.last_packet_time = receive_time
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
        loop = asyncio.get_running_loop()
        # Same reasoning as the threaded connect(): a receiver binds the port on
        # every interface, never on the sender's IP.
        bind_addr = (self.bind_ip or "0.0.0.0", self.port)
        listen = await loop.create_datagram_endpoint(
            lambda: OBS_UDP_Receiver._UDPProtocol(self),
            local_addr=bind_addr,
        )
        self._bind_addr = bind_addr
        self.packet_count = 0
        self.last_packet_time = 0.0
        self._transport, self._protocol = listen
        self.is_connected = True
        self.is_receiving = True
        self.stop_event.clear()
        self._reset_stream_state()
        
        # Start frame processing thread
        if not hasattr(self, 'processing_thread') or self.processing_thread is None or not self.processing_thread.is_alive():
            self.processing_thread = threading.Thread(target=self._decode_worker_loop, daemon=True)
            self.processing_thread.start()
        
        logger.info(f"[async] Connected to UDP stream at {self.ip}:{self.port}")
        return True

    async def _disconnect_asyncio(self):
        try:
            self.is_receiving = False
            self.is_connected = False
            self.stop_event.set()
            
            if self.executor:
                self.executor.shutdown(wait=False, cancel_futures=True)
                self.executor = None
            
            # Clear frame queue
            while not self.frame_queue.empty():
                try:
                    self.frame_queue.get_nowait()
                except Exception:
                    break
            
            if self._transport is not None:
                self._transport.close()
                await asyncio.sleep(0.1)  # Give transport time to close
                self._transport = None
            self._protocol = None
            
            # Clean up loop if no longer needed
            if self._loop and self._loop_thread and self._loop_thread.is_alive():
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._loop_thread.join(timeout=2.0)
                self._loop = None
                self._loop_thread = None
            
            logger.info("[async] Disconnected from UDP stream")
        except Exception as e:
            logger.error(f"[async] Error during disconnect: {e}", exc_info=True)

    def connect_async(self) -> bool:
        """
        Start asyncio-based UDP receiving in a background event loop thread.
        Returns True if scheduling succeeded.
        """
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
        """Stop asyncio-based UDP receiving and close transport."""
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
        """Disconnect from UDP stream"""
        try:
            self.is_connected = False
            self.is_receiving = False
            self.stop_event.set()
            self._frame_ready_event.set()
            
            if self.receive_thread and self.receive_thread.is_alive():
                self.receive_thread.join(timeout=1.0)
            
            if hasattr(self, 'processing_thread') and self.processing_thread and self.processing_thread.is_alive():
                self.processing_thread.join(timeout=1.0)
            
            if self.executor:
                self.executor.shutdown(wait=False, cancel_futures=True)
                self.executor = None
            
            # Clear frame queue
            while not self.frame_queue.empty():
                try:
                    self.frame_queue.get_nowait()
                except Exception:
                    break
            
            if self.socket:
                try:
                    self.socket.close()
                except Exception:
                    pass
                self.socket = None
            
            # Clear buffer
            with self.buffer_lock:
                self.mjpeg_buffer.clear()
            
            with self._slot_lock:
                self._latest_jpeg_slot = None
            
            # Clear current frame. Bumping the sequence and waking waiters means
            # a consumer blocked in wait_for_new_frame() returns immediately
            # instead of sitting until its timeout after a disconnect.
            with self._frame_cond:
                self.current_frame = None
                self._frame_seq += 1
                self._frame_cond.notify_all()
            
            logger.info("Disconnected from UDP stream")
            
        except Exception as e:
            logger.error(f"Error during disconnect: {e}", exc_info=True)
    
    def _maybe_raise_thread_priority(self):
        """Boost the calling (receive/decode) thread once, if configured.

        SetThreadPriority acts on the calling thread, so each worker opts in for
        itself; ``_priority_threads`` remembers which idents were already done.
        Best-effort and opt-in: on non-Windows, or when the call is refused, the
        receiver keeps working exactly as before.
        """
        ident = threading.get_ident()
        if ident in self._priority_threads:
            return True
        if not _read_bool_config("receiver_high_priority", False):
            return False
        applied = _try_set_thread_high_priority()
        # Remember the attempt either way: retrying every loop iteration on a
        # platform that refuses would just be syscall noise.
        self._priority_threads.add(ident)
        if applied:
            logger.info("Receiver thread priority raised to HIGHEST")
        return applied

    def _receive_loop(self):
        """Main receiving loop for UDP packets"""
        self.is_receiving = True
        self._maybe_raise_thread_priority()
        logger.info("Started UDP receive loop")

        # Transient errors are not evidence of a broken socket: Windows reports
        # WSAECONNRESET (ConnectionResetError) for a datagram the peer's ICMP
        # port-unreachable raced, and a non-blocking socket raises
        # BlockingIOError on an empty queue. Treating those as fatal killed the
        # receiver while ``is_connected`` stayed True, so the UI looked healthy
        # on a permanently black frame.
        transient_errors = (ConnectionResetError, BlockingIOError, InterruptedError)
        rebind_attempt = 0

        while not self.stop_event.is_set() and self.is_connected:
            if self.socket is None:
                # A previous rebind failed (port still held): keep retrying with
                # backoff instead of dereferencing a dead socket.
                delay = SOCKET_REBIND_DELAYS[
                    min(rebind_attempt, len(SOCKET_REBIND_DELAYS) - 1)
                ]
                rebind_attempt += 1
                self._recover_socket(delay)
                continue

            try:
                # Receive UDP packet
                data, addr = self.socket.recvfrom(65536)  # Max UDP packet size
                receive_time = time.perf_counter()
                self.packet_count += 1
                self.last_packet_time = receive_time

                # Process MJPEG data
                self._process_mjpeg_data(data, receive_time)
                rebind_attempt = 0

            except socket.timeout:
                continue
            except transient_errors as e:
                logger.debug(f"Transient UDP receive error (ignored): {e}")
                continue
            except OSError as e:
                if not self.is_connected or self.stop_event.is_set():
                    break
                logger.error(f"Socket error in receive loop: {e}; rebinding socket")
                delay = SOCKET_REBIND_DELAYS[
                    min(rebind_attempt, len(SOCKET_REBIND_DELAYS) - 1)
                ]
                rebind_attempt += 1
                self._recover_socket(delay)
            except Exception as e:
                if not self.is_connected or self.stop_event.is_set():
                    break
                logger.error(f"Error in receive loop: {e}", exc_info=True)
                time.sleep(0.01)

        self.is_receiving = False
        logger.info("UDP receive loop ended")

    def _recover_socket(self, delay: float = 0.0):
        """Close, recreate, reconfigure and rebind the UDP socket.

        A hard ``OSError`` on the receive socket leaves it unusable, but the
        receiver is still logically connected. Reporting it as connected while
        the socket is dead is the worst of both worlds, so the socket is rebuilt
        in place and the partial stream state discarded. A failed rebind (port
        held by another instance) is retried with backoff instead of flipping
        ``is_connected`` to False: the UI then shows "bound, no data" thanks to
        ``_udp_stream_starved()`` rather than pretending to be healthy.
        """
        if delay > 0:
            deadline = time.perf_counter() + delay
            while time.perf_counter() < deadline:
                if self.stop_event.is_set():
                    return
                time.sleep(min(0.05, max(0.0, deadline - time.perf_counter())))

        old_socket = self.socket
        self.socket = None
        try:
            if old_socket is not None:
                old_socket.close()
        except Exception:
            pass

        if self.stop_event.is_set() or not self.is_connected:
            return

        bind_addr = self._bind_addr or (self.bind_ip or "0.0.0.0", self.port)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                self._configure_socket(sock)
                sock.settimeout(1.0)
                sock.bind(bind_addr)
            except Exception:
                try:
                    sock.close()
                except Exception:
                    pass
                raise
            self.socket = sock
            self._bind_addr = bind_addr
            self._reset_stream_state()
            logger.info(f"UDP socket rebound on {bind_addr[0]}:{bind_addr[1]}")
        except Exception as e:
            # Keep is_connected True: the stream is meant to be live, and the
            # caller retries with a longer backoff on the next OSError/timeout
            # iteration. Lost packets are already visible as starvation.
            self.socket = None
            logger.error(f"UDP socket rebind failed on {bind_addr}: {e}")

    def _decode_worker_loop(self):
        """Ultra-low-latency dedicated frame decoder loop (Single-slot, Zero backlog)"""
        self._maybe_raise_thread_priority()
        logger.info("Started ultra-low-latency frame decoder loop")
        
        while not self.stop_event.is_set() and self.is_connected:
            try:
                if not self._frame_ready_event.wait(timeout=0.05):
                    continue
                self._frame_ready_event.clear()
                
                with self._slot_lock:
                    if self._latest_jpeg_slot is None:
                        continue
                    jpeg_data, frame_start_time = self._latest_jpeg_slot
                    self._latest_jpeg_slot = None
                
                # Fast TurboJPEG decode (Measured in real-time)
                t_decode_start = time.perf_counter()
                frame = self._decode_fn(jpeg_data)
                t_decode_end = time.perf_counter()
                
                if frame is not None:
                    # 100% REAL MEASUREMENTS (no fake values, no artificial clamps):
                    # decode_delay: Exact milliseconds TurboJPEG spent decompressing this frame
                    self.decode_delay = (t_decode_end - t_decode_start) * 1000.0
                    # receive_delay: Exact milliseconds from first UDP packet arrival of this frame until decoding began
                    self.receive_delay = max(0.0, (t_decode_start - frame_start_time) * 1000.0)
                    self._update_frame(frame, t_published=t_decode_end, t_frame_start=frame_start_time)
            except Exception as e:
                if self.is_connected:
                    logger.error(f"Error in frame decoder loop: {e}", exc_info=True)
                continue
        
        logger.info("Frame decoder loop ended")

    def _frame_processing_loop(self):
        """Backward-compatible alias for the decode loop"""
        return self._decode_worker_loop()
    
    def _deliver_jpeg(self, jpeg_data: bytes, frame_start: float):
        """Publish a complete JPEG to the single-slot decoder."""
        if len(jpeg_data) < 100:
            return
        with self._slot_lock:
            self._latest_jpeg_slot = (jpeg_data, frame_start)
        self._frame_ready_event.set()

    def _try_reassemble_fragment(self, data: bytes, receive_time: float):
        """Strip the plugin's 8-byte fragment header and reassemble a frame.

        Returns True when the datagram was consumed as a fragment (complete or
        not), and False when it is not a fragment so the caller can treat it as
        a raw stream.

        The header must be examined BEFORE the JPEG SOI check: a valid fragment
        whose total_size is e.g. 121087 begins FF D8 01 00, which looks like SOI.
        A genuine single-packet JPEG always reads a huge total_size (its 4th byte
        is a JPEG marker), so it fails the is-a-fragment test and falls through.
        """
        if len(data) < 8:
            return False

        total_size, frag_idx, total_frags = FRAGMENT_HEADER.unpack_from(data)

        is_fragment = (
            FRAGMENT_MIN_TOTAL < total_size <= FRAGMENT_MAX_TOTAL
            and 1 < total_frags <= FRAGMENT_MAX_COUNT
            and frag_idx < total_frags
        )
        if not is_fragment:
            return False

        payload = data[8:]
        if not payload:
            return True

        timeout_ms = _read_float_config("receiver_fragment_timeout_ms", FRAGMENT_TIMEOUT_MS_DEFAULT)
        timeout_s = max(0.001, float(timeout_ms) / 1000.0)

        # Drop a half-assembled frame that can no longer complete. Without this,
        # losing fragment 0 of frame N leaves the old parts sitting in the dict,
        # frame N+1's fragment 0 does not collide with any index, and b"".join()
        # splices two different frames into one "valid" JPEG.
        if self._frag_parts and (receive_time - self._frag_started_at) > timeout_s:
            self._frag_parts = {}
            self._frag_bytes = 0
            self.fragment_drops += 1

        # A frame that lost a fragment must not be spliced onto the next one:
        # restart on size/count change or a repeated index.
        if self._frag_parts and (
            total_size != self._frag_total_size
            or total_frags != self._frag_total_count
            or frag_idx in self._frag_parts
        ):
            self._frag_parts = {}
            self._frag_bytes = 0

        if not self._frag_parts:
            self._frag_total_size = total_size
            self._frag_total_count = total_frags
            self._frag_started_at = receive_time

        self._frag_parts[frag_idx] = payload
        self._frag_bytes += len(payload)

        if len(self._frag_parts) == self._frag_total_count:
            jpeg_data = b"".join(
                self._frag_parts[i] for i in range(self._frag_total_count)
            )
            frame_start = self._frag_started_at or receive_time
            self._frag_parts = {}
            self._frag_bytes = 0
            self._frag_started_at = 0.0
            self._deliver_jpeg(jpeg_data, frame_start)
        return True

    def _process_mjpeg_data(self, data: bytes, receive_time: float):
        """
        Process incoming MJPEG data with in-place bytearray searching and automatic stale frame dropping.

        Called from a single thread (the receive thread, or the asyncio loop), so
        the fragment assembly state below needs no extra lock.
        """
        try:
            if self._try_reassemble_fragment(data, receive_time):
                return

            with self.buffer_lock:
                # Drop a half-received JPEG that can no longer complete: its
                # start-marker timestamp would otherwise be attached to the next
                # complete frame, and the latency numbers derived from it would
                # describe a frame that never existed.
                if (
                    self._frame_start_time is not None
                    and (receive_time - self._frame_start_time) > MJPEG_BUFFER_MAX_AGE_S
                ):
                    self.mjpeg_buffer.clear()
                    self._frame_start_time = None

                self.mjpeg_buffer.extend(data)
                
                # Record frame start timestamp when start marker arrives
                if self._frame_start_time is None and self.mjpeg_start_marker in self.mjpeg_buffer:
                    self._frame_start_time = receive_time
                
                # Prevent buffer from growing too large
                if len(self.mjpeg_buffer) > self.max_buffer_size:
                    self.mjpeg_buffer.clear()
                    self._frame_start_time = None
                    return
                
                # In-place search for complete JPEG frames
                while True:
                    start_pos = self.mjpeg_buffer.find(self.mjpeg_start_marker)
                    if start_pos == -1:
                        if len(self.mjpeg_buffer) > 2048:
                            del self.mjpeg_buffer[:-1024]
                        break
                    
                    if start_pos > 0:
                        del self.mjpeg_buffer[:start_pos]
                    
                    end_pos = self.mjpeg_buffer.find(self.mjpeg_end_marker, 2)
                    if end_pos == -1:
                        # Waiting for remaining packets of this frame
                        break
                    
                    jpeg_data = bytes(self.mjpeg_buffer[:end_pos + 2])
                    del self.mjpeg_buffer[:end_pos + 2]
                    
                    frame_start = self._frame_start_time or receive_time
                    self._frame_start_time = None  # Reset for next incoming frame
                    
                    if len(jpeg_data) < 100:
                        continue
                    
                    # If another complete JPEG frame is already waiting in buffer, skip current!
                    next_start = self.mjpeg_buffer.find(self.mjpeg_start_marker)
                    if next_start != -1:
                        next_end = self.mjpeg_buffer.find(self.mjpeg_end_marker, next_start + 2)
                        if next_end != -1:
                            continue
                    
                    self._deliver_jpeg(jpeg_data, frame_start)
                    break
        except Exception as e:
            logger.error(f"Error processing MJPEG data: {e}", exc_info=True)
            with self.buffer_lock:
                self.mjpeg_buffer.clear()
                self._frame_start_time = None
            self._frag_parts = {}
            self._frag_bytes = 0
    
    def _decode_jpeg_frame_raw(self, jpeg_data: bytes) -> Optional[np.ndarray]:
        """Decode JPEG with TurboJPEG or OpenCV fallback"""
        try:
            if len(jpeg_data) < 100:
                return None
            if not (jpeg_data.startswith(b'\xff\xd8') and jpeg_data.endswith(b'\xff\xd9')):
                return None
            
            if _jpeg is not None:
                try:
                    return _jpeg.decode(jpeg_data, pixel_format=TJPF_BGR)
                except Exception:
                    pass
            
            nparr = np.frombuffer(jpeg_data, np.uint8)
            try:
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if frame is not None and frame.size > 0:
                    return frame
            except cv2.error:
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
                frame[h//2, w//2]
            ]
            if len(set(tuple(sample) for sample in sample_points)) == 1:
                return True
            if all(np.all(sample == 0) for sample in sample_points):
                return True
            return False
        except Exception:
            return True
    
    def _update_frame(self, frame: np.ndarray, receive_time: float = 0.0,
                      t_published: Optional[float] = None,
                      t_frame_start: Optional[float] = None):
        """Update current frame and trigger processing.

        ``t_published``/``t_frame_start`` carry the perf_counter stamps of the
        decode worker for this specific frame, so latency metadata describes the
        frame that was just published instead of whatever ran last.
        """
        try:
            published_at = time.perf_counter() if t_published is None else float(t_published)

            # Frame, sequence and metadata are published under the same lock as
            # the notify: a consumer that wakes up and immediately calls
            # get_last_frame_meta() must see the timing of the frame it just
            # received, never the previous one.
            with self._frame_cond:
                self.current_frame = frame
                self._frame_seq += 1
                seq = self._frame_seq
                latency_ms = (
                    max(0.0, (published_at - float(t_frame_start)) * 1000.0)
                    if t_frame_start is not None
                    else float(self.receive_delay)
                )
                with self._frame_meta_lock:
                    self._last_frame_meta = {
                        "frame_seq": seq,
                        "published_at": published_at,
                        "frame_start_time": t_frame_start,
                        "decode_ms": float(self.decode_delay),
                        "receive_ms": latency_ms,
                        "publish_latency_ms": latency_ms,
                    }
                self._frame_cond.notify_all()

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
                        logger.error(f"Error scheduling async frame callback: {e}")
                if self.frame_callback:
                    try:
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
            else:
                self.processing_delay = 0.0
        except Exception as e:
            logger.error(f"Error updating frame: {e}", exc_info=True)
    
    def _update_fps_counters(self):
        """Update FPS counters for monitoring"""
        current_time = time.time()
        self.fps_counter += 1
        
        if current_time - self.last_fps_time >= 1.0:
            self.current_fps = self.fps_counter / (current_time - self.last_fps_time)
            self.fps_counter = 0
            self.last_fps_time = current_time
    
    def get_current_frame(self) -> Optional[np.ndarray]:
        """
        Get current frame (Zero-copy read)
        
        Returns:
            Current frame or None if no frame available
        """
        with self.frame_lock:
            return self.current_frame

    def get_current_frame_with_seq(self) -> Tuple[Optional[np.ndarray], int]:
        """Return the current frame together with its publish sequence number.

        The sequence increases on every publish (and on disconnect), so a caller
        holding a previous value can tell "same frame as last time" apart from
        "a new frame arrived" without comparing image contents.
        """
        with self.frame_lock:
            return self.current_frame, self._frame_seq

    def wait_for_new_frame(self, after_seq: Optional[int] = None,
                           timeout: float = 0.0) -> Tuple[Optional[np.ndarray], int]:
        """Block until a frame newer than ``after_seq`` is published, or timeout.

        Returns ``(frame, seq)``. On timeout ``seq`` is unchanged from the last
        publish (equal to ``after_seq`` when nothing arrived), so the caller can
        use ``seq == after_seq`` as the "nothing new" test. ``after_seq=None``
        means "whatever is current", returning immediately when ``timeout`` is 0.
        """
        with self._frame_cond:
            target = self._frame_seq if after_seq is None else int(after_seq)
            deadline = time.perf_counter() + max(0.0, float(timeout or 0.0))
            while self._frame_seq <= target:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    break
                self._frame_cond.wait(remaining)
            return self.current_frame, self._frame_seq
    
    def get_last_frame_meta(self) -> dict:
        """Latency metadata of the most recently published frame.

        Returns ``{}`` before the first frame. Keys: ``frame_seq``,
        ``published_at``, ``frame_start_time``, ``decode_ms``, ``receive_ms`` and
        ``publish_latency_ms`` (``published_at - frame_start_time``), all in
        ``perf_counter`` seconds / milliseconds.
        """
        with self._frame_meta_lock:
            return dict(self._last_frame_meta)

    def get_performance_stats(self) -> dict:
        """
        Get performance statistics
        
        Returns:
            Dictionary with performance metrics
        """
        with self.buffer_lock:
            buffer_size = len(self.mjpeg_buffer)
        
        with self.processing_lock:
            processing_fps = self.processing_fps
            processing_delay = self.processing_delay
            decoding_fps = self.decoding_fps

        with self.frame_lock:
            frame_seq = self._frame_seq
        
        return {
            'current_fps': self.current_fps,
            'processing_fps': processing_fps,
            'decoding_fps': decoding_fps,
            'target_fps': self.target_fps,
            'receive_delay_ms': self.receive_delay,
            'decode_delay_ms': self.decode_delay,
            'processing_delay_ms': processing_delay,
            'is_connected': self.is_connected,
            'is_receiving': self.is_receiving,
            'packet_count': self.packet_count,
            'last_packet_age_s': (
                round(time.perf_counter() - self.last_packet_time, 3)
                if self.last_packet_time else None
            ),
            'bind_addr': self._bind_addr,
            'buffer_size_bytes': buffer_size,
            'queue_size': 0,
            'max_workers': self.max_workers,
            'frame_seq': frame_seq,
            'fragment_drops': self.fragment_drops,
            'rcvbuf_requested_bytes': self.rcvbuf_requested_bytes,
            'rcvbuf_actual_bytes': self.rcvbuf_actual_bytes,
        }
    
    def set_target_fps(self, fps: int):
        """
        Set target FPS (deprecated, kept for compatibility - no longer enforced)
        
        Args:
            fps: Target FPS value (for monitoring only)
        """
        self.target_fps = max(1, fps)  # No upper limit, just for monitoring
        self.frame_interval = 1.0 / self.target_fps if self.target_fps > 0 else 0
        logger.info(f"Target FPS set to {self.target_fps} (monitoring only, no limit enforced)")
    
    def update_connection_params(self, ip: str, port: int):
        """
        Update connection parameters
        
        Args:
            ip: New IP address
            port: New port number
        """
        self.ip = ip
        self.port = port
        logger.info(f"Connection parameters updated: {ip}:{port}")


class OBS_UDP_Manager:
    """
    Manager class for OBS UDP connections
    Provides high-level interface for UDP stream management
    """
    
    def __init__(self):
        self.receiver = None
        self.is_connected = False
        
    def create_receiver(self, ip: str, port: int, target_fps: int = 60) -> OBS_UDP_Receiver:
        """
        Create new UDP receiver
        
        Args:
            ip: IP address
            port: Port number
            target_fps: Target FPS
            
        Returns:
            OBS_UDP_Receiver instance
        """
        self.receiver = OBS_UDP_Receiver(ip, port, target_fps)
        return self.receiver
    
    def connect(self, ip: str, port: int, target_fps: int = 60) -> bool:
        """
        Connect to UDP stream
        
        Args:
            ip: IP address
            port: Port number
            target_fps: Target FPS
            
        Returns:
            True if connection successful
        """
        if self.receiver:
            self.receiver.disconnect()
        
        self.receiver = OBS_UDP_Receiver(ip, port, target_fps)
        success = self.receiver.connect()
        self.is_connected = success
        return success

    # -------------------- Async helpers --------------------
    def connect_async(self, ip: str, port: int, target_fps: int = 60) -> bool:
        """Connect using asyncio-based receiver running in background loop thread."""
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
        return self.is_connected and self.receiver and self.receiver.is_receiving
