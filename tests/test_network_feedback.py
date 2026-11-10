"""N1-N6: beep feedback port, payload, logging and ZMQ fallback (plan §6.5).

Before this change the beep port was a hard-coded constant, send failures were
swallowed with a bare ``except: pass`` and the ZMQ fallback was invisible. These
tests pin: the configured target is honoured, the payload is b"1"/b"0", failures
return False and log once, and a missing ZMQ module still beeps over UDP.
"""

import os
import sys
import unittest
from unittest import mock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils import network_feedback  # noqa: E402
from src.utils.config import config  # noqa: E402


class TestNetworkFeedback(unittest.TestCase):
    def setUp(self):
        # Snapshot + restore every config knob this module reads.
        self._saved = {
            "audio_feedback_enabled": getattr(config, "audio_feedback_enabled", True),
            "audio_feedback_ip": getattr(config, "audio_feedback_ip", ""),
            "audio_feedback_port": getattr(config, "audio_feedback_port", 4455),
            "toggle_feedback_method": getattr(config, "toggle_feedback_method", "udp"),
        }
        config.audio_feedback_enabled = True
        config.audio_feedback_ip = "192.168.100.1"
        config.audio_feedback_port = 4455
        config.toggle_feedback_method = "udp"

        network_feedback._warned.clear()
        network_feedback._last_target = None
        network_feedback._sent_ok = 0
        network_feedback._sent_fail = 0

        fake_socket = mock.MagicMock()
        self.sock = fake_socket
        patcher = mock.patch.object(network_feedback, "_get_udp_socket", return_value=fake_socket)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._restore)

    def _restore(self):
        for key, value in self._saved.items():
            setattr(config, key, value)
        network_feedback._warned.clear()
        network_feedback._last_target = None

    # -- N1 ---------------------------------------------------------------
    def test_disabled_sends_nothing(self):
        config.audio_feedback_enabled = False
        self.assertFalse(network_feedback.send_toggle_feedback(True))
        self.sock.sendto.assert_not_called()

    # -- N2 ---------------------------------------------------------------
    def test_payload_bytes(self):
        self.assertTrue(network_feedback.send_toggle_feedback(True))
        self.sock.sendto.assert_called_once_with(b"1", ("192.168.100.1", 4455))

        self.sock.reset_mock()
        self.assertTrue(network_feedback.send_toggle_feedback(False))
        self.sock.sendto.assert_called_once_with(b"0", ("192.168.100.1", 4455))

    # -- N3 ---------------------------------------------------------------
    def test_target_comes_from_config(self):
        config.audio_feedback_ip = "10.20.30.40"
        config.audio_feedback_port = 5001
        self.assertTrue(network_feedback.send_toggle_feedback(True))
        self.sock.sendto.assert_called_once_with(b"1", ("10.20.30.40", 5001))

        # Port garbage falls back to the documented default.
        config.audio_feedback_port = "not-a-port"
        self.sock.reset_mock()
        self.assertTrue(network_feedback.send_toggle_feedback(True))
        self.sock.sendto.assert_called_once_with(b"1", ("10.20.30.40", 4455))

    # -- N4 ---------------------------------------------------------------
    def test_send_failure_is_logged_once(self):
        self.sock.sendto.side_effect = OSError("network unreachable")
        with mock.patch.object(network_feedback, "log_print") as fake_log:
            self.assertFalse(network_feedback.send_toggle_feedback(True))
            self.assertFalse(network_feedback.send_toggle_feedback(False))

        failure_logs = [
            call for call in fake_log.call_args_list
            if "failed" in str(call.args[0]).lower()
        ]
        self.assertEqual(len(failure_logs), 1, "the failure must be logged once, not per call")
        self.assertIn("4455", str(failure_logs[0].args[0]))
        self.assertEqual(network_feedback._sent_fail, 2)

    # -- N5 ---------------------------------------------------------------
    def test_zmq_falls_back_to_udp(self):
        config.toggle_feedback_method = "zmq"
        with mock.patch.object(network_feedback, "log_print") as fake_log:
            # src.utils.network_feedback_zmq does not exist -> ImportError.
            self.assertTrue(network_feedback.send_toggle_feedback(True))

        self.sock.sendto.assert_called_once_with(b"1", ("192.168.100.1", 4455))
        messages = " ".join(str(call.args[0]) for call in fake_log.call_args_list)
        self.assertIn("ZMQ", messages)
        self.assertIn("4455", messages)

    # -- N6 ---------------------------------------------------------------
    def test_feedback_port_constant_compat(self):
        self.assertEqual(network_feedback.FEEDBACK_PORT, 4455)


if __name__ == "__main__":
    unittest.main()
