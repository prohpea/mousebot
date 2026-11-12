"""The stall detector must distinguish "flowing" from "bound but silent".

Writing it is trivial; the value is that a wrong threshold or an inverted
comparison would silently reintroduce the exact bug it exists to prevent
(a healthy-looking UI on a dead stream).
"""
import unittest
from unittest.mock import MagicMock

from src.ui import ViewerApp


def _app_with(mode="UDP", connected=True, packets=0, age=None):
    app = ViewerApp.__new__(ViewerApp)  # bypass Tk construction
    app.capture = MagicMock()
    app.capture.mode = mode
    app.capture.is_connected.return_value = connected
    if packets is None:
        app.capture.udp_manager = None
    else:
        receiver = MagicMock()
        receiver.packet_count = packets
        receiver.get_performance_stats.return_value = {"last_packet_age_s": age}
        app.capture.udp_manager.get_receiver.return_value = receiver
    return app


class TestUdpStreamStarved(unittest.TestCase):
    def test_no_packets_is_starved(self):
        self.assertTrue(_app_with(packets=0)._udp_stream_starved())

    def test_packets_flowing_is_not_starved(self):
        self.assertFalse(_app_with(packets=5000, age=0.006)._udp_stream_starved())

    def test_stale_packets_is_starved(self):
        """Packets exist historically but nothing arrived for >2 s."""
        self.assertTrue(_app_with(packets=5000, age=3.5)._udp_stream_starved())

    def test_non_udp_mode_is_never_starved(self):
        self.assertFalse(_app_with(mode="NDI", packets=0)._udp_stream_starved())

    def test_disconnected_is_never_starved(self):
        self.assertFalse(
            _app_with(connected=False, packets=0)._udp_stream_starved()
        )

    def test_missing_receiver_is_not_starved(self):
        self.assertFalse(_app_with(packets=None)._udp_stream_starved())

    def test_missing_age_is_not_starved(self):
        self.assertFalse(_app_with(packets=10, age=None)._udp_stream_starved())


if __name__ == "__main__":
    unittest.main()
