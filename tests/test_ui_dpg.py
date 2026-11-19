import unittest
import dearpygui.dearpygui as dpg
from src.ui_dpg import DpgViewerApp
from src.utils.config import config


class MockTracker:
    def __init__(self):
        self.normal_x_speed = 0.0
        self.normal_y_speed = 0.0
        self.normalsmooth = 0.0
        self.fovsize = 0.0
        self.mouse_dpi = 0
        self.current_fps = 144.0
        self.last_latency_ms = 1.8


class TestDpgUI(unittest.TestCase):
    def test_dpg_viewer_app_lifecycle(self):
        tracker = MockTracker()
        app = DpgViewerApp(tracker=tracker, capture_service=None)

        # Test sync
        app._sync_config_to_tracker()
        self.assertEqual(tracker.normal_x_speed, getattr(config, "normal_x_speed", 100.0))
        self.assertEqual(tracker.fovsize, getattr(config, "fovsize", 28.0))

        # Test after callback queue
        executed = []
        app.after(0, lambda: executed.append(True))
        app._process_callbacks()
        self.assertEqual(executed, [True])

        # Test cleanup
        app._on_close()
        self.assertFalse(app._running)


if __name__ == "__main__":
    unittest.main()
