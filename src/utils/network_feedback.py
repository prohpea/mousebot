"""
Network Feedback Module for CVM-colorBot.
Dispatches toggle state signals to OBS xUDP Plugin on PC 1 via UDP or ZeroMQ.

Modes:
- 'udp': sends a UDP datagram to ``config.audio_feedback_port`` (default 4455).
- 'zmq': sends a TCP PUSH message to port 5555 via ZeroMQ.
  (Automatically falls back to UDP if ZMQ fails or is unavailable.)

The feedback port is configurable (schema 5). Every failure is logged once
instead of being swallowed, so "the beep does not work" is diagnosable.
"""

import socket
from .config import config
from .debug_logger import log_print

# Kept for backwards compatibility: callers that import the constant directly.
FEEDBACK_PORT = 4455
_DEFAULT_PORT = 4455

_feedback_socket = None
_last_target = None
_warned = set()
_sent_ok = 0
_sent_fail = 0


def _get_udp_socket():
    global _feedback_socket
    if _feedback_socket is None:
        try:
            _feedback_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            _feedback_socket.setblocking(False)
        except Exception as e:
            _feedback_socket = None
            _log_once("socket_fail", f"[NetworkFeedback] Failed to create UDP socket: {e}")
    return _feedback_socket


def _target():
    """Return the ``(ip, port)`` the beep datagram must be sent to."""
    ip = str(getattr(config, "audio_feedback_ip", "") or "").strip()
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
    if key in _warned:
        return
    _warned.add(key)
    log_print(message)


def _send_udp(is_active: bool) -> bool:
    """Default / fallback UDP sender. Never raises."""
    global _last_target, _sent_ok, _sent_fail
    try:
        sock = _get_udp_socket()
        if not sock:
            return False

        ip, port = _target()
        if _last_target != (ip, port):
            _last_target = (ip, port)
            log_print(f"[NetworkFeedback] UDP beep target -> {ip}:{port}")
            _warned.discard("send_fail")  # a new target deserves a fresh log line

        payload = b"1" if is_active else b"0"
        sock.sendto(payload, (ip, port))
        _sent_ok += 1
        return True
    except Exception as exc:
        _sent_fail += 1
        _log_once(
            "send_fail",
            f"[NetworkFeedback] UDP beep failed: {exc} "
            "(check PC1 IP and inbound UDP 4455 firewall rule)",
        )
        return False


def send_toggle_feedback(is_active: bool):
    """
    Send toggle state byte to OBS plugin on PC 1.

    Respects ``toggle_feedback_method`` ('zmq' or 'udp'), returns whether a
    datagram was actually handed to the OS, and never raises.
    """
    if not getattr(config, "audio_feedback_enabled", True):
        return False

    method = str(getattr(config, "toggle_feedback_method", "udp")).strip().lower()

    if method == "zmq":
        try:
            from .network_feedback_zmq import send_toggle_feedback_zmq

            if send_toggle_feedback_zmq(is_active):
                return True
            _log_once(
                "zmq_fallback",
                "[NetworkFeedback] ZMQ send returned falsy, fallback UDP 4455",
            )
        except Exception as exc:
            _log_once(
                "zmq_fallback",
                f"[NetworkFeedback] ZMQ unavailable ({exc}), fallback UDP 4455",
            )
        # Fallback to UDP if ZMQ failed or raised exception
        return _send_udp(is_active)

    return _send_udp(is_active)
