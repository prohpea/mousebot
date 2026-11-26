import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.ui as ui_module
from src.utils.config import config
from src.utils import detection
from src.utils.i18n import i18n


def _make_stub_tracker():
    tracker = MagicMock()
    tracker._frame_count = 0
    tracker._target_fps = 144
    tracker.model = None
    tracker.class_names = {}
    return tracker


def _make_stub_capture():
    capture = MagicMock()
    capture.mode = "UDP"
    capture.is_connected.return_value = False
    capture.udp_manager = MagicMock()
    capture.udp_manager.get_receiver.return_value = None
    capture.teleport_manager = None
    capture.mss_capture = None
    capture.get_ndi_sources.return_value = []
    capture.get_capture_card_devices.return_value = []
    capture.set_mode.side_effect = lambda m: setattr(capture, "mode", m)
    return capture


class TestBentoDashboardUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_ui_style = getattr(config, "ui_style", None)
        cls._orig_legacy = getattr(config, "legacy_ui_mode", True)
        cls._orig_simple = getattr(config, "ui_simple_mode", False)
        cls._orig_lang = getattr(config, "language", "en")
        cls._orig_act_type = getattr(config, "aimbot_activation_type", "hold_enable")
        cls._orig_enableaim = getattr(config, "enableaim", True)
        cls._orig_gpu = getattr(config, "gpu_opencl_enabled", True)

        config.ui_style = "hud"
        config.ui_simple_mode = False
        config.language = "en"

        cls.tracker = _make_stub_tracker()
        cls.capture = _make_stub_capture()

        cls._save_patcher = patch.object(config, "save_to_file", lambda *a, **kw: True)
        cls._save_patcher.start()

        with patch.object(ui_module.ViewerApp, "_maybe_auto_start_runtime", lambda self: None), \
             patch.object(ui_module.ViewerApp, "_load_initial_config", lambda self: None), \
             patch.object(ui_module.ViewerApp, "_poll_clipboard_config_import", lambda self: None), \
             patch.object(ui_module.ViewerApp, "_process_source_updates", lambda self: None):
            cls.app = ui_module.ViewerApp(cls.tracker, cls.capture)
            cls.app.withdraw()
            cls.app.update_idletasks()

    @classmethod
    def tearDownClass(cls):
        try:
            for after_id in cls.app.tk.call("after", "info"):
                try:
                    cls.app.after_cancel(after_id)
                except Exception:
                    pass
            cls.app.destroy()
        except Exception:
            pass
        try:
            cls._save_patcher.stop()
        except Exception:
            pass
        if cls._orig_ui_style is not None:
            config.ui_style = cls._orig_ui_style
        elif hasattr(config, "ui_style"):
            delattr(config, "ui_style")
        config.legacy_ui_mode = cls._orig_legacy
        config.ui_simple_mode = cls._orig_simple
        config.language = cls._orig_lang
        config.aimbot_activation_type = cls._orig_act_type
        config.enableaim = cls._orig_enableaim
        config.gpu_opencl_enabled = cls._orig_gpu
        i18n.set_language(cls._orig_lang)

    def test_minimal_hud_is_default_without_rcs_trigger_magnet(self):
        self.assertEqual(self.app._ui_style, "hud")
        self.assertTrue(self.app._is_hud_mode())
        self.assertIn("hud", ui_module.THEME_PRESETS)
        self.assertEqual(ui_module.COLOR_BG, "#06080B")
        self.assertEqual(ui_module.COLOR_ACCENT, "#00F0FF")
        self.assertIsNotNone(self.app.hud_nav_bar)
        self.assertIsNotNone(self.app.hud_quick_bar)
        self.assertIsNotNone(self.app.hud_status_box)
        self.assertIsNone(self.app.hud_fps_canvas)
        self.assertEqual(
            list(self.app.nav_buttons.keys()),
            ["General", "Main Aimbot", "Config", "Debug"],
        )
        self.assertEqual(ui_module.AIM_MODE_OPTIONS, ["ABCurves", "Normal", "WindMouse"])
        self.assertFalse(config.enabletb)
        self.assertFalse(config.enable_magnet_trigger)
        self.assertFalse(config.enablercs)
        self.assertFalse(config.enableaim_sec)
        self.assertFalse(config.anti_smoke_enabled)
        self.assertTrue(len(self.app._quick_profile_buttons) >= 1)

    def test_all_minimal_tabs_render_in_hud_pro_and_lite(self):
        tabs = [
            ("General", self.app._show_general_tab),
            ("Main Aimbot", self.app._show_aimbot_tab),
            ("Config", self.app._show_config_tab),
            ("Debug", self.app._show_debug_tab),
        ]
        for simple_mode in (False, True):
            self.app._set_ui_simple_mode(simple_mode)
            for name, fn in tabs:
                self.app._handle_nav_click(name, fn)
                self.app.update_idletasks()
                self.assertEqual(self.app._active_tab_name, name)
        self.app._set_ui_simple_mode(False)

    def test_lite_mode_hides_pro_controls_and_pro_restores_them(self):
        self.app._set_ui_simple_mode(False)
        self.app._handle_nav_click("Main Aimbot", self.app._show_aimbot_tab)
        self.assertIn("aim_offsetX", self.app._slider_widgets)

        self.app._set_ui_simple_mode(True)
        self.assertNotIn("aim_offsetX", self.app._slider_widgets)

        self.app._set_ui_simple_mode(False)
        self.assertIn("aim_offsetX", self.app._slider_widgets)

    def test_hud_toggle_banner_reflects_activation_state_readonly(self):
        from src.utils import activation

        config.enableaim = True
        config.aimbot_activation_type = "toggle"
        orig_toggle = activation._activation_states["main"]["toggle_state"]
        try:
            activation._activation_states["main"]["toggle_state"] = True
            self.app._update_header_status_pills()
            self.assertIn("TOGGLE ON", self.app.hud_status_title.cget("text"))
            self.assertIn("ON", self.app.hud_toggle_metric.cget("text"))

            activation._activation_states["main"]["toggle_state"] = False
            self.app._update_header_status_pills()
            self.assertIn("TOGGLE OFF", self.app.hud_status_title.cget("text"))
            self.assertIn("OFF", self.app.hud_toggle_metric.cget("text"))

            config.aimbot_activation_type = "hold_enable"
            self.app._update_header_status_pills()
            self.assertIn("HOLD MODE", self.app.hud_status_title.cget("text"))
        finally:
            activation._activation_states["main"]["toggle_state"] = orig_toggle

    def test_quick_profile_click_loads_aim_only_and_preserves_hsv_and_hardware(self):
        names = list(self.app._quick_profile_buttons.keys())
        self.assertTrue(len(names) >= 1)
        target = names[0]
        captured = {}

        def _capture_apply(data, config_name=None):
            captured.update(data)

        with patch.object(self.app, "_apply_settings", side_effect=_capture_apply):
            self.app._quick_load_profile(target)
            self.assertTrue(len(captured) > 0)
            self.assertEqual(self.app._active_quick_profile.lower(), target.lower())
            # Must NEVER touch HSV or Hardware/Capture settings
            for forbidden in ("color", "custom_hsv_min_h", "custom_hsv_max_h", "udp_ip", "mouse_api", "capture_mode"):
                self.assertNotIn(forbidden, captured)

    def test_config_persists_gpu_ui_style_and_target_fps(self):
        d = config.to_dict()
        for key in ("gpu_opencl_enabled", "ui_style", "ui_simple_mode", "target_fps", "update_skipped_version", "never_update"):
            self.assertIn(key, d)

    def test_gpu_opencl_mask_matches_cpu_mask_identically(self):
        # Synthetic 320x320 BGR frame with a bright purple vertical outline
        img = np.zeros((320, 320, 3), dtype=np.uint8)
        # BGR magenta/purple -> HSV H~150, S=255, V=255
        img[110:190, 145:175] = (230, 20, 230)
        img[125:175, 152:168] = (20, 20, 20)
        model = detection.XUDP_HSV_PRESETS["purple"][0]

        raw_cpu, mask_cpu = detection._build_masks_cpu(img, model, "legacy")
        info = detection.get_compute_backend_info()
        if info["gpu_available"]:
            raw_gpu, mask_gpu = detection._build_masks_gpu_opencl(img, model, "legacy")
            self.assertTrue(np.array_equal(raw_cpu, raw_gpu))
            self.assertTrue(np.array_equal(mask_cpu, mask_gpu))

        orig = getattr(config, "gpu_opencl_enabled", True)
        try:
            config.gpu_opencl_enabled = False
            self.assertEqual(detection.get_compute_backend_info()["active_backend"], "CPU")
            config.gpu_opencl_enabled = True
            expected = "GPU" if info["gpu_available"] else "CPU"
            self.assertEqual(detection.get_compute_backend_info()["active_backend"], expected)
        finally:
            config.gpu_opencl_enabled = orig

    def test_ui_style_cycles_hud_bento_classic_neon_hud(self):
        self.assertEqual(self.app._ui_style, "hud")
        self.app._toggle_ui_style()
        self.assertEqual(self.app._ui_style, "bento")
        self.assertTrue(self.app._is_bento_mode())
        self.assertNotIn("RCS", self.app.nav_buttons)
        self.assertNotIn("Trigger", self.app.nav_buttons)
        self.assertNotIn("Magnet Trigger", self.app.nav_buttons)
        self.app._toggle_ui_style()
        self.assertEqual(self.app._ui_style, "classic")
        self.assertNotIn("RCS", self.app.nav_buttons)
        self.app._toggle_ui_style()
        self.assertEqual(self.app._ui_style, "neon")
        self.assertNotIn("Trigger", self.app.nav_buttons)
        self.app._toggle_ui_style()
        self.assertEqual(self.app._ui_style, "hud")
        self.assertTrue(self.app._is_hud_mode())

    def test_vietnamese_locale_in_hud_mode(self):
        i18n.set_language("vi")
        self.app._apply_language()
        self.app.update_idletasks()
        self.assertIn("HUD", self.app.ui_style_btn.cget("text"))
        i18n.set_language("en")
        self.app._apply_language()
        self.app.update_idletasks()


if __name__ == "__main__":
    unittest.main()
