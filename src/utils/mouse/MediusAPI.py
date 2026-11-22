"""
Medius box mouse/keyboard backend (Universal Auto-Protocol Edition).

Supports:
1. Official `medius` Python SDK when installed and its protocol matches the box.
2. Built-in pure-Python Medius Binary Protocol over pyserial (6 Mbaud, with 4 Mbaud
   fallback for pre-3.4.0 boxes), automatically handling ANY firmware/protocol
   version (proto 4..10+) even if the box firmware differs from the pip `medius`
   package or `medius` is not installed.

Protocol reference: https://medius.k4tech.net/native/frame
"""
from __future__ import annotations

import math
import struct
import threading
import time

import serial
from serial.tools import list_ports as serial_list_ports

from src.utils.debug_logger import log_print

from . import state
from .keycodes import to_hid_code

_medius_device = None
_active_stream = None
_native_client = None
_active_transport = ""  # "sdk" | "native"
_active_port_info = ""
_active_fw_info = ""
_medius_lock = threading.Lock()
_listener_stop = threading.Event()
_held_keys = set()
_held_keys_lock = threading.Lock()
_button_press_seq = {i: 0 for i in range(5)}
_key_press_seq = {}
_press_seq_lock = threading.Lock()

# Cache lock states to avoid flooding the control port every frame.
_axis_lock_lock = threading.Lock()
_cached_lock_x = None
_cached_lock_y = None
_cached_locked_buttons: set[int] = set()
_locks_dirty = True

_BUTTON_IDX_TO_SLOT = {
    0: 0,  # Button.LEFT
    1: 1,  # Button.RIGHT
    2: 2,  # Button.MIDDLE
    3: 3,  # Button.SIDE1
    4: 4,  # Button.SIDE2
}

# Native Medius framing & opcodes (https://medius.k4tech.net/native/frame)
_SOF = 0xA5
_OP_MOVE = 0x01
_OP_INJECT = 0x03
_OP_RESET = 0x04
_OP_QUERY = 0x05
_OP_RESP = 0x06
_OP_LOCK = 0x0A
_OP_CATCH = 0x0B
_OP_USAGE_EVENT = 0x0F

_QUERY_VERSION = 0x00
_QUERY_HEALTH = 0x01
_QUERY_DEVICE_INFO = 0x02
_QUERY_STATS = 0x05

_CLS_BUTTON = 0
_CLS_KEY = 1
_CLS_AXIS = 3

_ACT_SOFT_RELEASE = 0
_ACT_PRESS = 1

_MEDIUS_BAUD_RATES = (6_000_000, 4_000_000)
_CH34X_VID_PIDS = (
    (0x1A86, 0x55D3),  # CH343 (Medius / MAKCU primary)
    (0x1A86, 0x5523),  # CH343 variant
    (0x1A86, 0x7523),  # CH340
    (0x1A86, 0x5740),  # CH347
)


def _crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc


def _encode_frame(op: int, seq: int, payload: bytes = b"") -> bytes:
    body = bytes((op & 0xFF, seq & 0xFF)) + len(payload).to_bytes(2, "little") + payload
    crc = _crc16_ccitt(body)
    return bytes((_SOF,)) + body + crc.to_bytes(2, "little")


class _NativeMediusClient:
    """Pure-Python pyserial Medius binary client compatible across protocol versions."""

    def __init__(self, port_path: str, baudrate: int = 6_000_000):
        self.port_path = port_path
        self.baudrate = baudrate
        self.ser = serial.Serial(
            port=port_path,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05,
            write_timeout=0.25,
        )
        self._tx_lock = threading.Lock()
        self._seq = 1
        self._stop = threading.Event()
        self._rx_thread = None
        self._resp_lock = threading.Lock()
        self._resp_cond = threading.Condition(self._resp_lock)
        self._pending_resps = {}  # (what, seq) -> payload; plus ("hello", 0)
        self._last_tx_time = time.monotonic()

        self.proto_ver = 0
        self.fw_major = 0
        self.fw_minor = 0
        self.fw_patch = 0
        self.mac = b""
        self.name = ""

    def _next_seq(self) -> int:
        s = self._seq
        self._seq = 1 if self._seq >= 255 else self._seq + 1
        return s

    def start(self):
        self._stop.clear()
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True, name="MediusNativeRX")
        self._rx_thread.start()

    def close(self):
        self._stop.set()
        if self._rx_thread is not None and self._rx_thread.is_alive() and self._rx_thread is not threading.current_thread():
            try:
                self._rx_thread.join(timeout=0.4)
            except Exception:
                pass
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass

    def send_frame(self, op: int, payload: bytes = b"", seq: int | None = None) -> int:
        with self._tx_lock:
            use_seq = self._next_seq() if seq is None else (seq & 0xFF)
            pkt = _encode_frame(op, use_seq, payload)
            self.ser.write(pkt)
            self.ser.flush()
            self._last_tx_time = time.monotonic()
            return use_seq

    def query(self, what: int, timeout: float = 0.35, retries: int = 3) -> bytes | None:
        for _ in range(max(1, retries)):
            seq = self.send_frame(_OP_QUERY, bytes((what & 0xFF,)))
            deadline = time.monotonic() + timeout
            with self._resp_cond:
                while not self._stop.is_set():
                    key = (what & 0xFF, seq)
                    if key in self._pending_resps:
                        return self._pending_resps.pop(key)
                    if what == _QUERY_VERSION and (_QUERY_VERSION, 0) in self._pending_resps:
                        return self._pending_resps.pop((_QUERY_VERSION, 0))
                    rem = deadline - time.monotonic()
                    if rem <= 0:
                        break
                    self._resp_cond.wait(timeout=rem)
        return None

    def handshake(self) -> bool:
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass
        resp = self.query(_QUERY_VERSION, timeout=0.25, retries=4)
        if not resp or len(resp) < 11 or resp[0] != _QUERY_VERSION:
            return False
        self.proto_ver = resp[1]
        self.fw_major = resp[2]
        self.fw_minor = resp[3]
        self.fw_patch = resp[4]
        self.mac = bytes(resp[5:11])
        self.name = resp[11:].decode("ascii", errors="ignore").strip("\x00 ")
        return True

    def query_health(self):
        resp = self.query(_QUERY_HEALTH, timeout=0.25, retries=2)
        if not resp or len(resp) < 3 or resp[0] != _QUERY_HEALTH:
            return None
        flags = int.from_bytes(resp[1:3], "little")
        return {
            "link_up": bool(flags & 0x01),
            "mouse_attached": bool(flags & 0x02),
            "clone_ok": bool(flags & 0x04),
            "kbd_attached": bool(flags & 0x80),
        }

    def query_device_info(self):
        resp = self.query(_QUERY_DEVICE_INFO, timeout=0.25, retries=2)
        if not resp or len(resp) < 7 or resp[0] != _QUERY_DEVICE_INFO:
            return None
        kind = resp[5] if len(resp) > 5 else 0
        product = resp[7:].decode("utf-8", errors="ignore").strip("\x00 ") if len(resp) > 7 else ""
        return {"kind": kind, "product": product}

    def subscribe_input(self):
        # Subscribe to sparse button (class 0) and key (class 1) snapshots.
        self.send_frame(_OP_CATCH, struct.pack("<BHBBB", _CLS_BUTTON, 0xFFFF, 0, 1, 0))
        self.send_frame(_OP_CATCH, struct.pack("<BHBBB", _CLS_KEY, 0xFFFF, 0, 1, 0))

    def move_rel(self, dx: int, dy: int, immediate: bool = True):
        flags = 1 if (immediate and self.proto_ver >= 5) else 0
        self.send_frame(_OP_MOVE, struct.pack("<BhhB", 0, dx, dy, flags))

    def wheel(self, dz: int):
        self.send_frame(_OP_MOVE, struct.pack("<BhB", 1, dz, 0))

    def inject(self, cls: int, uid: int, action: int):
        self.send_frame(_OP_INJECT, struct.pack("<BHB", cls & 0xFF, uid & 0xFFFF, action & 0xFF))

    def lock(self, cls: int, uid: int, direction: int, locked: bool):
        if self.proto_ver <= 4:
            scale = 1 if locked else 0
        else:
            scale = 0 if locked else 100
        self.send_frame(_OP_LOCK, struct.pack("<BHBh", cls & 0xFF, uid & 0xFFFF, direction & 0xFF, scale))

    def reset(self):
        self.send_frame(_OP_RESET, b"\x00")

    def _handle_frame(self, op: int, seq: int, payload: bytes):
        if op == _OP_RESP and len(payload) >= 1:
            what = payload[0]
            with self._resp_cond:
                self._pending_resps[(what, seq)] = payload
                self._resp_cond.notify_all()
        elif op == _OP_USAGE_EVENT and len(payload) >= 8:
            # Payload: ts_us(u32), clk(u8), cls(u8), dir(u8), n(u8), n * (u8 cls, u16 id)
            snap_cls = payload[5]
            count = payload[7]
            ids = set()
            pos = 8
            for _ in range(count):
                if pos + 3 > len(payload):
                    break
                u_cls = payload[pos]
                u_id = int.from_bytes(payload[pos + 1 : pos + 3], "little")
                pos += 3
                if u_cls == snap_cls:
                    ids.add(u_id)

            if snap_cls == _CLS_BUTTON:
                with state.button_states_lock:
                    newly_pressed = []
                    for idx in range(5):
                        was_held = bool(state.button_states.get(idx, False))
                        now_held = idx in ids
                        state.button_states[idx] = now_held
                        if now_held and not was_held:
                            newly_pressed.append(idx)
                if newly_pressed:
                    with _press_seq_lock:
                        for idx in newly_pressed:
                            _button_press_seq[idx] = _button_press_seq.get(idx, 0) + 1
            elif snap_cls == _CLS_KEY:
                with _held_keys_lock:
                    newly_pressed_keys = [kid for kid in ids if kid not in _held_keys]
                    _held_keys.clear()
                    _held_keys.update(ids)
                if newly_pressed_keys:
                    with _press_seq_lock:
                        for kid in newly_pressed_keys:
                            _key_press_seq[kid] = _key_press_seq.get(kid, 0) + 1

    def _rx_loop(self):
        buf = bytearray()
        last_keepalive = time.monotonic()
        while not self._stop.is_set():
            try:
                now = time.monotonic()
                if (now - self._last_tx_time) >= 0.40 and (now - last_keepalive) >= 0.40:
                    last_keepalive = now
                    try:
                        self.send_frame(_OP_QUERY, bytes((_QUERY_STATS,)))
                    except Exception:
                        break

                waiting = self.ser.in_waiting
                chunk = self.ser.read(waiting if waiting > 0 else 1)
                if chunk:
                    buf.extend(chunk)
                    while len(buf) >= 7:
                        sof_idx = buf.find(bytes((_SOF,)))
                        if sof_idx < 0:
                            buf.clear()
                            break
                        if sof_idx > 0:
                            del buf[:sof_idx]
                        if len(buf) < 7:
                            break
                        op = buf[1]
                        seq = buf[2]
                        plen = int.from_bytes(buf[3:5], "little")
                        if plen > 512:
                            del buf[0]
                            continue
                        total_len = 5 + plen + 2
                        if len(buf) < total_len:
                            break
                        body = bytes(buf[1 : 5 + plen])
                        rx_crc = int.from_bytes(buf[5 + plen : total_len], "little")
                        del buf[:total_len]
                        if _crc16_ccitt(body) == rx_crc:
                            self._handle_frame(op, seq, body[4:])
            except Exception:
                if self._stop.is_set():
                    break
                time.sleep(0.01)


def _try_import_medius():
    try:
        import medius
        from medius import (
            Button,
            CatchEventKind,
            CatchFilter,
            Class,
            Device,
            Direction,
            DisconnectedError,
            LockTarget,
            MediusError,
            NotFoundError,
            Usage,
        )
        return {
            "medius": medius,
            "BadProtoVerError": getattr(medius, "BadProtoVerError", None),
            "Blanket": getattr(medius, "Blanket", None),
            "Button": Button,
            "CatchEventKind": CatchEventKind,
            "CatchFilter": CatchFilter,
            "Class": Class,
            "Device": Device,
            "Direction": Direction,
            "DisconnectedError": DisconnectedError,
            "LockTarget": LockTarget,
            "MediusError": MediusError,
            "NotFoundError": NotFoundError,
            "PortBusyError": getattr(medius, "PortBusyError", None),
            "Usage": Usage,
        }
    except ImportError:
        return None


def _normalize_serial_port_name(port_value: str) -> str:
    raw = str(port_value or "").strip()
    if not raw:
        return ""
    if raw.upper().startswith("COM"):
        return raw.upper()
    if raw.isdigit():
        return f"COM{raw}"
    return raw


def _looks_like_serial_path(value: str) -> bool:
    upper = value.upper()
    return (
        upper.startswith("COM")
        or value.startswith("/")
        or value.startswith("\\\\.\\")
        or value.isdigit()
    )


def _find_serial_candidate_ports() -> list[dict]:
    candidates = []
    for p in serial_list_ports.comports():
        vid = p.vid
        pid = p.pid
        hwid = (p.hwid or "").upper()
        desc = (p.description or "").upper()
        matched = False
        if vid is not None and pid is not None and (vid, pid) in _CH34X_VID_PIDS:
            matched = True
        elif any(tag in hwid or tag in desc for tag in ("1A86:55D3", "CH343", "MEDIUS")):
            matched = True
        if matched:
            candidates.append(
                {
                    "path": str(p.device or ""),
                    "vid": int(vid or 0),
                    "pid": int(pid or 0),
                    "serial": str(getattr(p, "serial_number", "") or ""),
                    "id": "",
                    "product": str(p.description or ""),
                    "proto_ver": 0,
                }
            )
    return candidates


def list_ports():
    """Return [{path, vid, pid, serial, id, product, proto_ver}, ...] for connected Medius boxes."""
    results = []
    seen_paths = set()

    mods = _try_import_medius()
    if mods is not None:
        medius_mod = mods["medius"]
        list_boxes = getattr(medius_mod, "list_boxes", None)
        if callable(list_boxes):
            try:
                for box in list_boxes():
                    port_info = getattr(box, "port", None)
                    path = str(getattr(port_info, "path", "") or "")
                    if path:
                        seen_paths.add(path.upper())
                    dev_info = getattr(box, "device", None)
                    ver_info = getattr(box, "version", None)
                    results.append(
                        {
                            "path": path,
                            "vid": int(getattr(port_info, "vid", 0) or 0),
                            "pid": int(getattr(port_info, "pid", 0) or 0),
                            "serial": str(getattr(box, "serial", "") or getattr(port_info, "serial", "") or ""),
                            "id": str(getattr(box, "id", "") or ""),
                            "product": str(getattr(dev_info, "product", "") or ""),
                            "proto_ver": int(getattr(ver_info, "proto_ver", 0) or 0),
                        }
                    )
            except Exception as e:
                log_print(f"[Medius] list_boxes failed, falling back: {e}")

        try:
            for info in medius_mod.find_ports():
                path = str(getattr(info, "path", "") or "")
                if path and path.upper() in seen_paths:
                    continue
                if path:
                    seen_paths.add(path.upper())
                results.append(
                    {
                        "path": path,
                        "vid": int(getattr(info, "vid", 0) or 0),
                        "pid": int(getattr(info, "pid", 0) or 0),
                        "serial": str(getattr(info, "serial", "") or ""),
                        "id": "",
                        "product": "",
                        "proto_ver": 0,
                    }
                )
        except Exception:
            pass

    for cand in _find_serial_candidate_ports():
        path = cand["path"]
        if path and path.upper() not in seen_paths:
            seen_paths.add(path.upper())
            results.append(cand)

    return results


def _button_usage(mods, idx: int):
    button = mods["Button"]
    usage = mods["Usage"]
    slot = _BUTTON_IDX_TO_SLOT.get(int(idx))
    if slot is None:
        return None
    mapping = {
        0: button.LEFT,
        1: button.RIGHT,
        2: button.MIDDLE,
        3: button.SIDE1,
        4: button.SIDE2,
    }
    member = mapping.get(slot)
    if member is None:
        return None
    return usage.button(member)


def _apply_catch_usage_snapshot(mods, snap) -> None:
    """Update cached button/key states and press counters from a CatchEvent USAGES snapshot."""
    cls_enum = mods["Class"]
    snap_cls = getattr(snap, "cls", None)
    usages = getattr(snap, "usages", None) or []

    if snap_cls == cls_enum.BUTTON:
        ids = {int(u.id) for u in usages if getattr(u, "kind", None) == cls_enum.BUTTON}
        with state.button_states_lock:
            newly_pressed = []
            for idx in range(5):
                was_held = bool(state.button_states.get(idx, False))
                now_held = idx in ids
                state.button_states[idx] = now_held
                if now_held and not was_held:
                    newly_pressed.append(idx)
        if newly_pressed:
            with _press_seq_lock:
                for idx in newly_pressed:
                    _button_press_seq[idx] = _button_press_seq.get(idx, 0) + 1
        return

    if snap_cls == cls_enum.KEY:
        ids = {int(u.id) for u in usages if getattr(u, "kind", None) == cls_enum.KEY}
        with _held_keys_lock:
            newly_pressed_keys = [kid for kid in ids if kid not in _held_keys]
            _held_keys.clear()
            _held_keys.update(ids)
        if newly_pressed_keys:
            with _press_seq_lock:
                for kid in newly_pressed_keys:
                    _key_press_seq[kid] = _key_press_seq.get(kid, 0) + 1


def _listener_loop(device, mods):
    global _active_stream
    stream = None
    catch_filter = mods["CatchFilter"]
    catch_kind = mods["CatchEventKind"]
    cls_enum = mods["Class"]
    disconnected_err = mods["DisconnectedError"]

    try:
        filters = [
            catch_filter.watch_class(cls_enum.BUTTON),
            catch_filter.watch_class(cls_enum.KEY),
        ]
        stream = device.catch_events(filters)
        with _medius_lock:
            _active_stream = stream
    except Exception as e:
        log_print(f"[Medius] Failed to subscribe catch events: {e}")
        return

    log_print("[Medius] Input listener started (catch USAGES stream).")
    try:
        while not _listener_stop.is_set() and state.is_connected and state.active_backend == "Medius":
            try:
                event = stream.recv_timeout(80)
            except disconnected_err:
                if not _listener_stop.is_set():
                    log_print("[Medius] Input stream disconnected.")
                break
            except Exception as e:
                if _listener_stop.is_set():
                    break
                log_print(f"[Medius] Input stream error: {e}")
                time.sleep(0.05)
                continue

            if event is None:
                if hasattr(stream, "is_connected") and not stream.is_connected:
                    if not _listener_stop.is_set():
                        log_print("[Medius] Medius link dropped.")
                    break
                continue

            try:
                if getattr(event, "kind", None) == catch_kind.USAGES and getattr(event, "usages", None) is not None:
                    _apply_catch_usage_snapshot(mods, event.usages)
                while hasattr(stream, "try_recv"):
                    extra = stream.try_recv()
                    if extra is None:
                        break
                    if getattr(extra, "kind", None) == catch_kind.USAGES and getattr(extra, "usages", None) is not None:
                        _apply_catch_usage_snapshot(mods, extra.usages)
            except Exception:
                continue
    finally:
        with _medius_lock:
            if _active_stream is stream:
                _active_stream = None
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass
        log_print("[Medius] Input listener stopped.")


def _start_listener(device, mods):
    _listener_stop.clear()
    thread = threading.Thread(target=_listener_loop, args=(device, mods), daemon=True, name="MediusListener")
    state.listener_thread = thread
    thread.start()


def _reset_cached_locks():
    global _cached_lock_x, _cached_lock_y, _locks_dirty
    with _axis_lock_lock:
        _cached_lock_x = None
        _cached_lock_y = None
        _cached_locked_buttons.clear()
        _locks_dirty = True


def _connect_via_native_protocol(port_candidates: list[str]) -> tuple[bool, str]:
    global _native_client, _active_transport, _active_port_info, _active_fw_info
    last_err = "No Medius box found on serial ports."
    busy_ports = []

    for port_path in port_candidates:
        for baud in _MEDIUS_BAUD_RATES:
            client = None
            try:
                client = _NativeMediusClient(port_path, baudrate=baud)
                client.start()
                if client.handshake():
                    with _medius_lock:
                        _native_client = client
                        _active_transport = "native"
                        _active_port_info = f"{port_path} @ {baud // 1_000_000}M"
                        _active_fw_info = (
                            f"fw {client.fw_major}.{client.fw_minor}.{client.fw_patch}, "
                            f"proto {client.proto_ver}, name='{client.name}'"
                        )

                    state.reset_button_states()
                    with _held_keys_lock:
                        _held_keys.clear()
                    _reset_cached_locks()
                    state.set_connected(True, "Medius")
                    client.subscribe_input()

                    log_print(f"[Medius] Connected (Universal Native {baud // 1_000_000}M on {port_path}): {_active_fw_info}")
                    health = client.query_health()
                    if health:
                        log_print(
                            f"[Medius] Health: link_up={health['link_up']}, "
                            f"clone_ok={health['clone_ok']}, mouse_attached={health['mouse_attached']}"
                        )
                    info = client.query_device_info()
                    if info:
                        log_print(f"[Medius] Cloned device: kind={info['kind']}, product='{info['product']}'")
                    return True, ""
                client.close()
                last_err = f"Port {port_path} did not respond to Medius handshake."
            except serial.SerialException as e:
                if client is not None:
                    client.close()
                msg = str(e)
                if "Access is denied" in msg or "PermissionError" in msg or "busy" in msg.lower():
                    busy_ports.append(port_path)
                    last_err = f"Medius serial port {port_path} is busy (close Medius Dashboard or other apps)."
                    break
                last_err = msg
            except Exception as e:
                if client is not None:
                    client.close()
                last_err = str(e)

    if busy_ports and "busy" not in last_err.lower():
        last_err = f"Medius serial port {', '.join(busy_ports)} is busy (close Medius Dashboard or other apps)."
    return False, last_err


def get_runtime_status_info() -> dict:
    return {
        "transport": _active_transport or "none",
        "port": _active_port_info,
        "firmware": _active_fw_info,
    }


def connect(port=None, mode: str = "Auto") -> bool:
    global _medius_device, _active_transport, _active_port_info, _active_fw_info
    state.last_connect_error = ""
    disconnect()

    mode_norm = str(mode or "Auto").strip().lower()
    raw_target = "" if mode_norm == "auto" else str(port or "").strip()

    mods = _try_import_medius()
    fallback_to_native = mods is None
    sdk_err = ""

    if mods is not None:
        Device = mods["Device"]
        NotFoundError = mods["NotFoundError"]
        BadProtoVerError = mods["BadProtoVerError"] or ()
        PortBusyError = mods["PortBusyError"] or ()

        try:
            if raw_target:
                if _looks_like_serial_path(raw_target):
                    norm_port = _normalize_serial_port_name(raw_target)
                    device = Device.open(norm_port)
                    _active_port_info = norm_port
                else:
                    open_by_id = getattr(Device, "open_by_id", None)
                    if callable(open_by_id):
                        try:
                            device = open_by_id(raw_target)
                        except NotFoundError:
                            device = Device.open(raw_target)
                    else:
                        device = Device.open(raw_target)
                    _active_port_info = raw_target
            else:
                finder = getattr(Device, "find_mouse_box", None)
                if callable(finder):
                    try:
                        device = finder()
                    except NotFoundError:
                        device = Device.find()
                else:
                    device = Device.find()
                _active_port_info = "auto"

            with _medius_lock:
                _medius_device = device
                _active_transport = "sdk"

            state.reset_button_states()
            with _held_keys_lock:
                _held_keys.clear()
            _reset_cached_locks()
            state.set_connected(True, "Medius")
            _start_listener(device, mods)

            try:
                version = device.query_version()
                _active_fw_info = (
                    f"fw {version.fw_major}.{version.fw_minor}.{version.fw_patch}, "
                    f"proto {version.proto_ver}, name='{getattr(version, 'name', '')}'"
                )
                log_print(f"[Medius] Connected (SDK): {_active_fw_info}")
            except Exception:
                _active_fw_info = "connected"
                log_print("[Medius] Connected (SDK).")

            try:
                health = device.query_health()
                clone_ok = getattr(health, "clone_up", getattr(health, "clone_configured", "?"))
                dev_ok = getattr(health, "device_attached", getattr(health, "mouse_attached", "?"))
                log_print(
                    f"[Medius] Health: link_up={getattr(health, 'link_up', '?')}, "
                    f"clone_ok={clone_ok}, device_attached={dev_ok}"
                )
            except Exception:
                pass

            try:
                info = device.device_info()
                log_print(
                    f"[Medius] Cloned device: kind={getattr(info, 'kind', '?')}, "
                    f"product='{getattr(info, 'product', '')}'"
                )
            except Exception:
                pass

            return True

        except Exception as e:
            if BadProtoVerError and isinstance(e, BadProtoVerError):
                log_print(f"[Medius] SDK protocol mismatch ({e}); switching to Universal Native Binary mode...")
                fallback_to_native = True
            elif NotFoundError and isinstance(e, NotFoundError):
                # Older pre-3.4 firmware or non-matching proto boxes may be skipped by SDK find(); try native scan.
                fallback_to_native = True
                sdk_err = "No Medius box found. Check the control-port cable."
            elif PortBusyError and isinstance(e, PortBusyError):
                sdk_err = f"Medius serial port is busy (close Medius Dashboard or other apps): {e}"
                fallback_to_native = False
            elif "Access is denied" in str(e) or "os error 5" in str(e).lower():
                sdk_err = f"Medius serial port is busy (close Medius Dashboard or other apps): {e}"
                fallback_to_native = False
            else:
                log_print(f"[Medius] SDK connect failed ({e}); trying Universal Native Binary fallback...")
                fallback_to_native = True
                sdk_err = str(e)

    if fallback_to_native:
        if raw_target and _looks_like_serial_path(raw_target):
            candidates = [_normalize_serial_port_name(raw_target)]
        else:
            discovered = [item["path"] for item in list_ports() if item.get("path")]
            # Preserve order while deduplicating.
            candidates = list(dict.fromkeys(discovered))

        if candidates:
            ok, native_err = _connect_via_native_protocol(candidates)
            if ok:
                return True
            state.last_connect_error = native_err or sdk_err or "Medius connect failed."
        else:
            state.last_connect_error = sdk_err or "No Medius box found. Check the control-port cable."
    else:
        state.last_connect_error = sdk_err or "Medius connect failed."

    state.set_connected(False, "Medius")
    log_print(f"[Medius] {state.last_connect_error}")
    return False


def disconnect():
    global _medius_device, _active_stream, _native_client, _active_transport, _active_port_info, _active_fw_info
    _listener_stop.set()
    with _medius_lock:
        stream = _active_stream
        _active_stream = None
        device = _medius_device
        _medius_device = None
        native = _native_client
        _native_client = None
        _active_transport = ""
        _active_port_info = ""
        _active_fw_info = ""

    if stream is not None:
        try:
            stream.close()
        except Exception:
            pass

    listener = getattr(state, "listener_thread", None)
    if listener is not None and listener.is_alive() and listener is not threading.current_thread():
        try:
            listener.join(timeout=0.5)
        except Exception:
            pass

    if device is not None:
        try:
            device.reset()
        except Exception:
            pass
        try:
            device.close()
        except Exception:
            pass
        time.sleep(0.05)

    if native is not None:
        try:
            native.reset()
        except Exception:
            pass
        try:
            native.close()
        except Exception:
            pass
        time.sleep(0.05)

    if state.active_backend == "Medius":
        state.set_connected(False, "Medius")
    state.reset_button_states()
    with _held_keys_lock:
        _held_keys.clear()
    _reset_cached_locks()
    state.mask_applied_idx = None


def _get_backend():
    if not state.is_connected or state.active_backend != "Medius":
        return None, None
    with _medius_lock:
        return _medius_device, _native_client


def is_button_pressed(idx: int) -> bool:
    try:
        idx = int(idx)
    except Exception:
        return False
    with state.button_states_lock:
        return bool(state.button_states.get(idx, False))


def is_key_pressed(key) -> bool:
    hid = to_hid_code(key)
    if hid is None:
        return False
    with _held_keys_lock:
        return int(hid) in _held_keys


def get_button_press_seq(idx: int) -> int:
    try:
        idx = int(idx)
    except Exception:
        return 0
    with _press_seq_lock:
        return int(_button_press_seq.get(idx, 0))


def get_key_press_seq(key) -> int:
    hid = to_hid_code(key)
    if hid is None:
        return 0
    with _press_seq_lock:
        return int(_key_press_seq.get(int(hid), 0))


def move(x: float, y: float):
    device, native = _get_backend()
    if device is None and native is None:
        return
    try:
        dx = max(-32768, min(32767, int(round(float(x)))))
        dy = max(-32768, min(32767, int(round(float(y)))))
        if dx == 0 and dy == 0:
            return
        if device is not None:
            move_now = getattr(device, "move_rel_now", None)
            if callable(move_now):
                move_now(dx, dy)
            else:
                device.move_rel(dx, dy)
        else:
            native.move_rel(dx, dy, immediate=True)
    except Exception as e:
        log_print(f"[Medius] move failed: {e}")


def wheel(delta: int):
    device, native = _get_backend()
    if device is None and native is None:
        return
    try:
        dz = max(-32768, min(32767, int(round(float(delta)))))
        if dz == 0:
            return
        if device is not None:
            device.wheel(dz)
        else:
            native.wheel(dz)
    except Exception as e:
        log_print(f"[Medius] wheel failed: {e}")


def move_bezier(x: float, y: float, segments: int, ctrl_x: float, ctrl_y: float):
    steps = max(1, int(segments or 1))
    if steps <= 1:
        move(x, y)
        return

    total_x = float(x)
    total_y = float(y)
    if math.hypot(total_x, total_y) < 1e-6:
        return

    p0 = (0.0, 0.0)
    p1 = (total_x * 0.25 + float(ctrl_x) * 0.5, total_y * 0.25 + float(ctrl_y) * 0.5)
    p2 = (total_x * 0.75 + float(ctrl_x) * 0.25, total_y * 0.75 + float(ctrl_y) * 0.25)
    p3 = (total_x, total_y)

    sent_x = 0.0
    sent_y = 0.0
    for i in range(1, steps + 1):
        t = i / steps
        u = 1.0 - t
        bx = (u ** 3) * p0[0] + 3 * (u ** 2) * t * p1[0] + 3 * u * (t ** 2) * p2[0] + (t ** 3) * p3[0]
        by = (u ** 3) * p0[1] + 3 * (u ** 2) * t * p1[1] + 3 * u * (t ** 2) * p2[1] + (t ** 3) * p3[1]
        step_x = int(round(bx - sent_x))
        step_y = int(round(by - sent_y))
        if step_x != 0 or step_y != 0:
            move(step_x, step_y)
            sent_x += step_x
            sent_y += step_y
        if i < steps:
            time.sleep(0.001)


def _inject_button(idx: int, isdown: int):
    device, native = _get_backend()
    if device is None and native is None:
        return
    slot = _BUTTON_IDX_TO_SLOT.get(int(idx))
    if slot is None:
        return
    try:
        if device is not None:
            mods = _try_import_medius()
            if mods is None:
                return
            usage = _button_usage(mods, idx)
            if usage is None:
                return
            if int(isdown):
                device.press(usage)
            else:
                device.soft_release(usage)
        else:
            native.inject(_CLS_BUTTON, slot, _ACT_PRESS if int(isdown) else _ACT_SOFT_RELEASE)
    except Exception as e:
        log_print(f"[Medius] button({idx}) failed: {e}")


def left(isdown: int):
    _inject_button(0, isdown)


def right(isdown: int):
    _inject_button(1, isdown)


def middle(isdown: int):
    _inject_button(2, isdown)


def key_down(key):
    device, native = _get_backend()
    hid = to_hid_code(key)
    if (device is None and native is None) or hid is None:
        return
    try:
        if device is not None:
            mods = _try_import_medius()
            if mods is None:
                return
            device.press(mods["Usage"].key(int(hid)))
        else:
            native.inject(_CLS_KEY, int(hid), _ACT_PRESS)
        with _held_keys_lock:
            _held_keys.add(int(hid))
    except Exception as e:
        log_print(f"[Medius] key_down failed: {e}")


def key_up(key):
    device, native = _get_backend()
    hid = to_hid_code(key)
    if (device is None and native is None) or hid is None:
        return
    try:
        if device is not None:
            mods = _try_import_medius()
            if mods is None:
                return
            device.soft_release(mods["Usage"].key(int(hid)))
        else:
            native.inject(_CLS_KEY, int(hid), _ACT_SOFT_RELEASE)
        with _held_keys_lock:
            _held_keys.discard(int(hid))
    except Exception as e:
        log_print(f"[Medius] key_up failed: {e}")


def key_press(key):
    key_down(key)
    time.sleep(0.012)
    key_up(key)


def lock_button_idx(idx: int):
    global _locks_dirty
    device, native = _get_backend()
    if device is None and native is None:
        return
    slot = _BUTTON_IDX_TO_SLOT.get(int(idx))
    if slot is None:
        return
    try:
        if device is not None:
            mods = _try_import_medius()
            if mods is None:
                return
            usage = _button_usage(mods, idx)
            if usage is None:
                return
            device.lock(mods["LockTarget"].usage(usage), mods["Direction"].BOTH)
        else:
            native.lock(_CLS_BUTTON, slot, 0, True)
        with _axis_lock_lock:
            _cached_locked_buttons.add(slot)
            _locks_dirty = True
    except Exception as e:
        log_print(f"[Medius] lock_button failed: {e}")


def unlock_button_idx(idx: int):
    device, native = _get_backend()
    if device is None and native is None:
        return
    slot = _BUTTON_IDX_TO_SLOT.get(int(idx))
    if slot is None:
        return
    try:
        if device is not None:
            mods = _try_import_medius()
            if mods is None:
                return
            usage = _button_usage(mods, idx)
            if usage is None:
                return
            device.unlock(mods["LockTarget"].usage(usage), mods["Direction"].BOTH)
        else:
            native.lock(_CLS_BUTTON, slot, 0, False)
        with _axis_lock_lock:
            _cached_locked_buttons.discard(slot)
    except Exception as e:
        log_print(f"[Medius] unlock_button failed: {e}")


def unlock_all_locks():
    """Unlock all button and axis locks without resetting active CATCH subscriptions."""
    global _cached_lock_x, _cached_lock_y, _locks_dirty
    device, native = _get_backend()
    if device is None and native is None:
        return
    with _axis_lock_lock:
        if (
            not _locks_dirty
            and not _cached_locked_buttons
            and _cached_lock_x is False
            and _cached_lock_y is False
        ):
            return
    try:
        if device is not None:
            mods = _try_import_medius()
            if mods is None:
                return
            Direction = mods["Direction"]
            Blanket = mods.get("Blanket")
            if Blanket is not None:
                # Only clear locks; Device.reset() also tears down CATCH subscriptions.
                device.unlock_all(Blanket.BUTTONS, Direction.BOTH)
                device.unlock_all(Blanket.AIM, Direction.BOTH)
            else:
                LockTarget = mods["LockTarget"]
                for btn_idx in _BUTTON_IDX_TO_SLOT:
                    usage = _button_usage(mods, btn_idx)
                    if usage is not None:
                        device.unlock(LockTarget.usage(usage), Direction.BOTH)
                device.unlock(LockTarget.x(), Direction.BOTH)
                device.unlock(LockTarget.y(), Direction.BOTH)
        else:
            for slot in _BUTTON_IDX_TO_SLOT.values():
                native.lock(_CLS_BUTTON, slot, 0, False)
            native.lock(_CLS_AXIS, 0, 0, False)
            native.lock(_CLS_AXIS, 1, 0, False)
        with _axis_lock_lock:
            _cached_lock_x = False
            _cached_lock_y = False
            _cached_locked_buttons.clear()
            _locks_dirty = False
    except Exception as e:
        log_print(f"[Medius] unlock_all failed: {e}")


def lock_movement_x(lock: bool = True, skip_lock: bool = False):
    del skip_lock
    global _cached_lock_x, _locks_dirty
    desired = bool(lock)
    device, native = _get_backend()
    if device is None and native is None:
        return
    with _axis_lock_lock:
        if _cached_lock_x is desired:
            return
    try:
        if device is not None:
            mods = _try_import_medius()
            if mods is None:
                return
            target = mods["LockTarget"].x()
            if desired:
                device.lock(target, mods["Direction"].BOTH)
            else:
                device.unlock(target, mods["Direction"].BOTH)
        else:
            native.lock(_CLS_AXIS, 0, 0, desired)
        with _axis_lock_lock:
            _cached_lock_x = desired
            if desired:
                _locks_dirty = True
    except Exception as e:
        log_print(f"[Medius] lock_movement_x failed: {e}")


def lock_movement_y(lock: bool = True, skip_lock: bool = False):
    del skip_lock
    global _cached_lock_y, _locks_dirty
    desired = bool(lock)
    device, native = _get_backend()
    if device is None and native is None:
        return
    with _axis_lock_lock:
        if _cached_lock_y is desired:
            return
    try:
        if device is not None:
            mods = _try_import_medius()
            if mods is None:
                return
            target = mods["LockTarget"].y()
            if desired:
                device.lock(target, mods["Direction"].BOTH)
            else:
                device.unlock(target, mods["Direction"].BOTH)
        else:
            native.lock(_CLS_AXIS, 1, 0, desired)
        with _axis_lock_lock:
            _cached_lock_y = desired
            if desired:
                _locks_dirty = True
    except Exception as e:
        log_print(f"[Medius] lock_movement_y failed: {e}")


def update_movement_lock(lock_x: bool, lock_y: bool, is_main: bool = True):
    del is_main
    lock_movement_x(bool(lock_x))
    lock_movement_y(bool(lock_y))


def tick_movement_lock_manager():
    return


def mask_manager_tick(selected_idx: int, aimbot_running: bool):
    if not state.is_connected or state.active_backend != "Medius":
        return
    try:
        from src.utils.config import config

        if not bool(getattr(config, "button_mask_enabled", False)):
            if state.mask_applied_idx is not None:
                unlock_button_idx(state.mask_applied_idx)
                state.mask_applied_idx = None
            return
    except Exception:
        return

    if aimbot_running:
        if state.mask_applied_idx != selected_idx:
            if state.mask_applied_idx is not None:
                unlock_button_idx(state.mask_applied_idx)
            lock_button_idx(selected_idx)
            state.mask_applied_idx = selected_idx
    elif state.mask_applied_idx is not None:
        unlock_button_idx(state.mask_applied_idx)
        state.mask_applied_idx = None


def test_move():
    move(100, 100)
