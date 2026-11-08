import cv2
import socket
import threading
import time
import asyncio
import numpy as np
from typing import Optional, Callable, Tuple, Awaitable
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import logging

logger = logging.getLogger(__name__)

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
    
    def __init__(self, ip: str = "192.168.0.1", port: int = 1234, target_fps: int = 60, max_workers: int = None):
        """
        Initialize OBS UDP receiver
        
        Args:
            ip: IP address to receive UDP stream from
            port: Port number to receive UDP stream on
            target_fps: Target FPS for processing (deprecated, kept for compatibility)
            max_workers: Maximum number of worker threads for frame processing (None = auto)
        """
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
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Increase receive buffer size to 4MB for high FPS streams and zero packet drop
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            self.socket.settimeout(1.0)  # 1 second timeout
            
            # Bind to receive UDP packets
            self.socket.bind((self.ip, self.port))
            
            self.is_connected = True
            self.stop_event.clear()
            self._frame_ready_event.clear()
            
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
        listen = await loop.create_datagram_endpoint(
            lambda: OBS_UDP_Receiver._UDPProtocol(self),
            local_addr=(self.ip, self.port),
        )
        self._transport, self._protocol = listen
        self.is_connected = True
        self.is_receiving = True
        self.stop_event.clear()
        
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
            
            # Clear current frame
            with self.frame_lock:
                self.current_frame = None
            
            logger.info("Disconnected from UDP stream")
            
        except Exception as e:
            logger.error(f"Error during disconnect: {e}", exc_info=True)
    
    def _receive_loop(self):
        """Main receiving loop for UDP packets"""
        self.is_receiving = True
        logger.info("Started UDP receive loop")
        
        while not self.stop_event.is_set() and self.is_connected:
            try:
                # Receive UDP packet
                data, addr = self.socket.recvfrom(65536)  # Max UDP packet size
                receive_time = time.perf_counter()
                
                # Process MJPEG data
                self._process_mjpeg_data(data, receive_time)
                
            except socket.timeout:
                continue
            except OSError as e:
                if self.is_connected:
                    logger.error(f"Socket error in receive loop: {e}")
                break
            except Exception as e:
                if self.is_connected:
                    logger.error(f"Error in receive loop: {e}", exc_info=True)
                break
        
        self.is_receiving = False
        logger.info("UDP receive loop ended")
    
    def _decode_worker_loop(self):
        """Ultra-low-latency dedicated frame decoder loop (Single-slot, Zero backlog)"""
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
                frame = self._decode_jpeg_frame_raw(jpeg_data)
                t_decode_end = time.perf_counter()
                
                if frame is not None:
                    # 100% REAL MEASUREMENTS (no fake values, no artificial clamps):
                    # decode_delay: Exact milliseconds TurboJPEG spent decompressing this frame
                    self.decode_delay = (t_decode_end - t_decode_start) * 1000.0
                    # receive_delay: Exact milliseconds from first UDP packet arrival of this frame until decoding began
                    self.receive_delay = max(0.0, (t_decode_start - frame_start_time) * 1000.0)
                    self._update_frame(frame)
            except Exception as e:
                if self.is_connected:
                    logger.error(f"Error in frame decoder loop: {e}", exc_info=True)
                continue
        
        logger.info("Frame decoder loop ended")

    def _frame_processing_loop(self):
        """Backward-compatible alias for the decode loop"""
        return self._decode_worker_loop()
    
    def _process_mjpeg_data(self, data: bytes, receive_time: float):
        """
        Process incoming MJPEG data with in-place bytearray searching and automatic stale frame dropping.
        """
        try:
            with self.buffer_lock:
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
                    
                    with self._slot_lock:
                        self._latest_jpeg_slot = (jpeg_data, frame_start)
                    self._frame_ready_event.set()
                    break
        except Exception as e:
            logger.error(f"Error processing MJPEG data: {e}", exc_info=True)
            with self.buffer_lock:
                self.mjpeg_buffer.clear()
                self._frame_start_time = None
    
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
    
    def _update_frame(self, frame: np.ndarray, receive_time: float = 0.0):
        """Update current frame and trigger processing"""
        try:
            with self.frame_lock:
                self.current_frame = frame
            
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
            'buffer_size_bytes': buffer_size,
            'queue_size': 0,
            'max_workers': self.max_workers
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
