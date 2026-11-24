"""
Network Feedback Module for CVM-colorBot.
Dispatches toggle state signals to OBS xUDP Plugin on PC 1 via UDP or ZeroMQ.

Modes:
- 'udp': sends UDP datagram to port 4455 (default).
- 'zmq': sends TCP PUSH message to port 5555 via ZeroMQ.
  (Automatically falls back to UDP if ZMQ fails or is unavailable).
"""

import socket
from .config import config

FEEDBACK_PORT = 4455
_feedback_socket = None


def _get_udp_socket():
    global _feedback_socket
    if _feedback_socket is None:
        try:
            _feedback_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            _feedback_socket.setblocking(False)
        except Exception as e:
            print(f"[NetworkFeedback] Failed to create UDP socket: {e}")
            _feedback_socket = None
    return _feedback_socket


def _send_udp(is_active: bool):
    """Fallback / Default UDP sender."""
    try:
        sock = _get_udp_socket()
        if not sock:
            return
        target_ip = getattr(config, "audio_feedback_ip", "192.168.10.3")
        if not target_ip or target_ip == "0.0.0.0":
            target_ip = "127.0.0.1"

        payload = b'1' if is_active else b'0'
        sock.sendto(payload, (target_ip, FEEDBACK_PORT))
    except Exception:
        # Non-fatal: networking warning should not break aimbot execution
        pass


def send_toggle_feedback(is_active: bool):
    """
    Send toggle state byte to OBS plugin on PC 1.
    Respects 'toggle_feedback_method': 'zmq' or 'udp'.
    Safely falls back to UDP if ZMQ encounters any error.
    """
    if not getattr(config, "audio_feedback_enabled", True):
        return

    method = str(getattr(config, "toggle_feedback_method", "udp")).strip().lower()

    if method == "zmq":
        try:
            from .network_feedback_zmq import send_toggle_feedback_zmq
            if send_toggle_feedback_zmq(is_active):
                return
        except Exception:
            pass
        # Fallback to UDP if ZMQ failed or raised exception
        _send_udp(is_active)
    else:
        _send_udp(is_active)
