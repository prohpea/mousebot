import unittest
from unittest import mock

from src.aim_system import normal
from src.utils import activation
from src.utils.config import config
from src.utils.mouse import state as mouse_state


class DummyFrame:
    def __init__(self, xres=320, yres=320):
        self.xres = xres
        self.yres = yres


class DummyTracker:
    def __init__(self):
        self.controller = mock.MagicMock()
        self.model = None
        self.rcs_pull_speed = 0
        self.rcs_activation_delay = 100
        self.rcs_rapid_click_threshold = 200
        self.fovsize = 62.0
        self.fovsize_sec = 150.0
        self.aim_offsetX = 0.0
        self.aim_offsetY = 0.0
        self.aim_offsetX_sec = 0.0
        self.aim_offsetY_sec = 0.0
        self.tbdelay_min = 0.08
        self.tbdelay_max = 0.15
        self.tbhold_min = 40.0
        self.tbhold_max = 60.0
        self.tbcooldown_min = 0.0
        self.tbcooldown_max = 0.0
        self.tbburst_count_min = 1
        self.tbburst_count_max = 1
        self.tbburst_interval_min = 0.0
        self.tbburst_interval_max = 0.0
        self._was_main_aimbot_active = False


class ActivationToggleTests(unittest.TestCase):
    def setUp(self):
        activation.reset_activation_state(is_sec=False)
        activation.reset_activation_state(is_sec=True)
        self._saved_cfg = {}
        for key in (
            "enableaim",
            "selected_mouse_button",
            "aimbot_activation_type",
            "fovsize",
            "ads_fov_enabled",
            "deadzone_fov_enabled",
            "mode",
            "aim_type",
            "aim_offsetX",
            "aim_offsetY",
            "enableaim_sec",
            "selected_mouse_button_sec",
            "aimbot_activation_type_sec",
            "fovsize_sec",
            "ads_fov_enabled_sec",
            "deadzone_fov_enabled_sec",
            "mode_sec",
            "aim_type_sec",
            "aim_offsetX_sec",
            "aim_offsetY_sec",
            "enable_magnet_trigger",
            "enabletb",
        ):
            self._saved_cfg[key] = getattr(config, key, None)

        config.enableaim = True
        config.selected_mouse_button = 4  # Side Mouse 5
        config.aimbot_activation_type = "toggle"
        config.fovsize = 62.0
        config.ads_fov_enabled = False
        config.deadzone_fov_enabled = False
        config.mode = "ABCurves"
        config.aim_type = "head"
        config.aim_offsetX = 0.0
        config.aim_offsetY = 0.0
        config.enableaim_sec = False
        config.selected_mouse_button_sec = 3
        config.aimbot_activation_type_sec = "toggle"
        config.fovsize_sec = 80.0
        config.ads_fov_enabled_sec = False
        config.deadzone_fov_enabled_sec = False
        config.mode_sec = "Normal"
        config.aim_type_sec = "head"
        config.aim_offsetX_sec = 0.0
        config.aim_offsetY_sec = 0.0
        config.enable_magnet_trigger = False
        config.enabletb = False

    def tearDown(self):
        for key, value in self._saved_cfg.items():
            setattr(config, key, value)
        activation.reset_activation_state(is_sec=False)
        activation.reset_activation_state(is_sec=True)

    def _run_frame(self, tracker, targets_main, targets_sec=None):
        frame = DummyFrame(320, 320)
        with (
            mock.patch.object(normal, "process_rcs", return_value=False),
            mock.patch.object(normal, "check_y_release", return_value=False),
            mock.patch.object(normal, "process_triggerbot", return_value="DISABLED"),
            mock.patch.object(normal.mode_abcurves, "reset"),
            mock.patch.object(normal, "_dispatch_aimbot") as dispatch_mock,
        ):
            normal.process_normal_mode(
                targets_main=targets_main,
                frame=frame,
                img=None,
                tracker=tracker,
                targets_sec=targets_sec,
            )
            return dispatch_mock

    def test_mouse5_toggles_on_without_targets_and_aims_when_target_enters_fov(self):
        tracker = DummyTracker()
        pressed = {"val": False}

        with (
            mock.patch.object(activation, "is_button_pressed", side_effect=lambda idx: pressed["val"] if idx == 4 else False),
            mock.patch.object(activation, "get_button_press_seq", return_value=0),
        ):
            # Initial frame: no target, button not pressed -> toggle OFF
            dispatch = self._run_frame(tracker, [])
            self.assertFalse(activation.get_aimbot_toggle_state())
            dispatch.assert_not_called()

            # Press Mouse 5 while NO target is on screen -> toggle turns ON immediately
            pressed["val"] = True
            dispatch = self._run_frame(tracker, [])
            self.assertTrue(activation.get_aimbot_toggle_state())
            dispatch.assert_not_called()

            # Release Mouse 5 while still no target -> toggle stays ON
            pressed["val"] = False
            dispatch = self._run_frame(tracker, [])
            self.assertTrue(activation.get_aimbot_toggle_state())
            dispatch.assert_not_called()

            # Target enters 62px FOV (center is 160, 160 -> target at 180, 160 is 20px away)
            target = (180.0, 160.0, 20.0, None, None)
            dispatch = self._run_frame(tracker, [target])
            self.assertTrue(activation.get_aimbot_toggle_state())
            dispatch.assert_called_once()

            # Press Mouse 5 again while target is outside FOV -> toggle turns OFF
            far_target = (280.0, 160.0, 120.0, None, None)
            pressed["val"] = True
            dispatch = self._run_frame(tracker, [far_target])
            self.assertFalse(activation.get_aimbot_toggle_state())
            dispatch.assert_not_called()

            # Target re-enters FOV -> aim does NOT fire while toggle is OFF
            pressed["val"] = False
            dispatch = self._run_frame(tracker, [target])
            self.assertFalse(activation.get_aimbot_toggle_state())
            dispatch.assert_not_called()

    def test_sec_aimbot_toggle_updates_without_target(self):
        config.enableaim = False
        config.enableaim_sec = True
        config.selected_mouse_button_sec = 4
        config.aimbot_activation_type_sec = "toggle"
        tracker = DummyTracker()
        pressed = {"val": False}

        with (
            mock.patch.object(activation, "is_button_pressed", side_effect=lambda idx: pressed["val"] if idx == 4 else False),
            mock.patch.object(activation, "get_button_press_seq", return_value=0),
        ):
            self._run_frame(tracker, [])
            pressed["val"] = True
            self._run_frame(tracker, [])
            pressed["val"] = False

            target = (175.0, 160.0, 15.0, None, None)
            dispatch = self._run_frame(tracker, [target])
            dispatch.assert_called_once()

    def test_fast_click_caught_by_press_seq_without_double_toggle(self):
        pressed = {"val": False}
        seq = {"val": 0}

        with (
            mock.patch.object(activation, "is_button_pressed", side_effect=lambda idx: pressed["val"] if idx == 4 else False),
            mock.patch.object(activation, "get_button_press_seq", side_effect=lambda idx: seq["val"] if idx == 4 else 0),
        ):
            # Baseline idle frame
            self.assertFalse(activation.check_aimbot_activation(4, "toggle", is_sec=False))

            # Fast click happens entirely between two frames: pressed returns False, but seq incremented
            seq["val"] = 1
            pressed["val"] = False
            self.assertTrue(activation.check_aimbot_activation(4, "toggle", is_sec=False))
            self.assertTrue(activation.get_aimbot_toggle_state())

            # Interleaving check: if button is observed still held on the next frame with same seq, do NOT double toggle
            pressed["val"] = True
            self.assertTrue(activation.check_aimbot_activation(4, "toggle", is_sec=False))
            self.assertTrue(activation.get_aimbot_toggle_state())

            # Release -> still ON
            pressed["val"] = False
            self.assertTrue(activation.check_aimbot_activation(4, "toggle", is_sec=False))

            # Second press (seq=2) -> toggles OFF
            seq["val"] = 2
            pressed["val"] = True
            self.assertFalse(activation.check_aimbot_activation(4, "toggle", is_sec=False))
            self.assertFalse(activation.get_aimbot_toggle_state())

    def test_stale_press_seq_before_first_poll_does_not_false_toggle(self):
        # E.g., user pressed Mouse 5 during keybind capture (seq=3), then released before tracking starts
        with (
            mock.patch.object(activation, "is_button_pressed", return_value=False),
            mock.patch.object(activation, "get_button_press_seq", return_value=3),
        ):
            self.assertFalse(activation.check_aimbot_activation(4, "toggle", is_sec=False))
            self.assertFalse(activation.get_aimbot_toggle_state())

        # Next real press (seq=4) toggles ON cleanly
        with (
            mock.patch.object(activation, "is_button_pressed", return_value=True),
            mock.patch.object(activation, "get_button_press_seq", return_value=4),
        ):
            self.assertTrue(activation.check_aimbot_activation(4, "toggle", is_sec=False))
            self.assertTrue(activation.get_aimbot_toggle_state())

    def test_mouse_state_serial_press_seq_exposed(self):
        from src.utils import mouse as mouse_mod

        prev_connected = mouse_state.is_connected
        prev_backend = mouse_state.active_backend
        prev_seq = mouse_state.button_press_seq.get(4, 0)
        try:
            mouse_state.set_connected(True, "Serial")
            with mouse_state.button_states_lock:
                mouse_state.button_press_seq[4] = prev_seq + 2
            self.assertEqual(mouse_mod.get_button_press_seq(4), prev_seq + 2)
        finally:
            with mouse_state.button_states_lock:
                mouse_state.button_press_seq[4] = prev_seq
            mouse_state.set_connected(prev_connected, prev_backend)


if __name__ == "__main__":
    unittest.main()
