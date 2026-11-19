"""End-to-end workflow over the Tactical HUD shell.

Covers the language switch, the Pro/Simple disclosure toggle, the two HUD width
modes, all five pages, the header telemetry pills, the ENGINE dock button and the
footer controls. The old ``runtime_btn.height == 38`` assertion is replaced by the
stricter HUD contract: the dock is 20px tall, its fill flips to the danger colour
while running, and the footer state reports RUNNING.
"""
import unittest
import sys
import os
from unittest.mock import MagicMock, patch
import customtkinter as ctk

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# Fence real game hardware and the user's real config.json before building the app.
from ui_test_support import fence_game_hardware

fence_game_hardware()

from src.ui import ViewerApp
from src.utils.config import config
from src.utils.i18n import i18n


class _ConfigSandbox:
    """Pin config values for one test and always restore them."""

    def __init__(self, **values):
        self.values = values
        self.previous = {}

    def __enter__(self):
        for key, value in self.values.items():
            self.previous[key] = getattr(config, key, "__missing__")
            setattr(config, key, value)
        return self

    def __exit__(self, *exc_info):
        for key, value in self.previous.items():
            if value == "__missing__":
                try:
                    delattr(config, key)
                except AttributeError:
                    pass
            else:
                setattr(config, key, value)
        return False


class TestE2EUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("Dark")

    @staticmethod
    def _hud_width(app):
        """Allocated width, falling back to the requested geometry for withdrawn windows."""
        width = int(app.winfo_width())
        if width > 1:
            return width
        try:
            return int(str(app.geometry()).split("x", 1)[0])
        except Exception:
            return width

    def test_e2e_ui_workflow(self):
        tracker_mock = MagicMock()
        capture_mock = MagicMock()
        # Start from a known language so the intermediate assertions are stable.
        config.language = i18n.set_language("en")
        app = ViewerApp(tracker=tracker_mock, capture_service=capture_mock)
        app.deiconify()
        app.update()

        # 1. Test language switch to Vietnamese, then back to English
        app._on_language_changed("Tiếng Việt")
        self.assertEqual(i18n.language, "vi", "i18n language should be set to 'vi'")
        self.assertIn("Tiếng Việt", app.lang_btn.cget("text"))

        app._on_language_changed("English")
        self.assertEqual(i18n.language, "en", "i18n language should be set to 'en'")
        self.assertIn("English", app.lang_btn.cget("text"))

        # 2. Test Pro/Simple disclosure toggle (independent of the HUD width mode)
        initial_mode = app._ui_pro_mode
        app._toggle_pro_mode()
        self.assertNotEqual(app._ui_pro_mode, initial_mode, "Pro mode should be toggled")
        app._toggle_pro_mode()
        self.assertEqual(app._ui_pro_mode, initial_mode, "Pro mode should be restored")

        # 3. HUD width modes: both must keep the shell above its minimum width
        original_hud_mode = getattr(config, "ui_hud_mode", "simple")
        try:
            app._apply_hud_mode("simple")
            app.update_idletasks()
            self.assertGreaterEqual(self._hud_width(app), 780)
            app._apply_hud_mode("wide")
            app.update_idletasks()
            self.assertGreaterEqual(self._hud_width(app), 1040)
        finally:
            app._apply_hud_mode(original_hud_mode)

        # 4. Test 5-Pillar Navigation across all tabs
        app._show_aimbot_tab()
        self.assertEqual(app._active_tab_name, "Main Aimbot")
        self.assertTrue(hasattr(app, "card_targeting"))

        app._show_sec_aimbot_tab()
        self.assertEqual(app._active_tab_name, "Sec Aimbot")
        self.assertTrue(hasattr(app, "card_targeting_sec"))

        app._show_vision_tab()
        self.assertEqual(app._active_tab_name, "Vision")
        self.assertTrue(hasattr(app, "card_color_preset"))
        self.assertTrue(hasattr(app, "card_hsv_tuning"))
        self.assertTrue(hasattr(app, "_toggle_inline_hsv_preview"))
        self.assertTrue(callable(app._open_hsv_preview), "HsvPreviewWindow hook must survive")

        app._show_general_tab()
        self.assertEqual(app._active_tab_name, "Hardware")
        self.assertTrue(hasattr(app, "card_mouse_api"))
        self.assertTrue(hasattr(app, "card_capture_service"))

        app._show_config_tab()
        self.assertEqual(app._active_tab_name, "Profiles")
        self.assertTrue(hasattr(app, "card_profile_manager"))

        app._show_debug_tab()
        self.assertEqual(app._active_tab_name, "Telemetry")
        self.assertTrue(hasattr(app, "card_mouse_monitor"))
        self.assertTrue(hasattr(app, "card_system_logs"))

        # 5. Test Status Pills
        self.assertTrue(hasattr(app, "pill_fps"))
        self.assertTrue(hasattr(app, "pill_delay"))
        self.assertTrue(hasattr(app, "pill_hardware"))

        # 6. Master Runtime Engine dock button (HUD proportions + real binding)
        self.assertTrue(hasattr(app, "runtime_btn"))
        self.assertEqual(app.runtime_btn.cget("height"), 20)
        self.assertIn("START ENGINE", app.runtime_btn.cget("text"))

        called = []
        original_toggle = app._toggle_runtime
        app._toggle_runtime = lambda: called.append(True)
        app.runtime_btn.invoke()
        app._toggle_runtime = original_toggle
        self.assertTrue(called, "The dock ENGINE button must call the real _toggle_runtime")

        app._runtime_active = True
        app._runtime_busy = False
        app._refresh_runtime_button()
        self.assertIn("STOP ENGINE", app.runtime_btn.cget("text"))
        self.assertIn("RUNNING", app.footer_state_label.cget("text"))
        app._runtime_active = False
        app._refresh_runtime_button()

        # 7. Footer + shell controls are present and wired
        self.assertTrue(hasattr(app, "footer_bar"))
        for attr in ("lang_btn", "theme_btn", "accent_btn", "hud_mode_btn", "settings_btn"):
            self.assertTrue(hasattr(app, attr), f"missing HUD control: {attr}")

        # 8. Profile list reflects the real configs/ directory
        app._show_config_tab()
        app.update_idletasks()
        self.assertGreaterEqual(len(app.config_option.cget("values")), 1)

        app.destroy()


class TestVisionObsUdpCard(unittest.TestCase):
    """The AI-only OBS UDP Stream card and the F5 engine sync hook."""

    @classmethod
    def setUpClass(cls):
        ctk.set_appearance_mode("Dark")

    def setUp(self):
        self._saved_engine = getattr(config, "detection_engine", "colorbot")
        self._saved_enabled = getattr(config, "ai_detection_enabled", False)
        self._saved_udp = (getattr(config, "udp_ip", "0.0.0.0"),
                           getattr(config, "udp_port", "3110"))
        self._saved_capture_mode = getattr(config, "capture_mode", "NDI")
        self._saved_stream_intent = getattr(config, "ai_udp_stream_enabled", False)
        self._saved_color = getattr(config, "color", "yellow")
        self._saved_outline_filter = getattr(config, "ai_enemy_outline_filter", "auto")
        self._saved_outline_px = getattr(config, "ai_enemy_outline_min_pixels", 4)
        self.app = ViewerApp(tracker=MagicMock(), capture_service=MagicMock())

    def tearDown(self):
        config.detection_engine = self._saved_engine
        config.ai_detection_enabled = self._saved_enabled
        config.udp_ip, config.udp_port = self._saved_udp
        config.capture_mode = self._saved_capture_mode
        config.ai_udp_stream_enabled = self._saved_stream_intent
        config.color = self._saved_color
        config.ai_enemy_outline_filter = self._saved_outline_filter
        config.ai_enemy_outline_min_pixels = self._saved_outline_px
        # The colour handler reloads the HSV model, which captures the band in
        # module globals: restore them under the restored colour so the next
        # suite does not inherit this test's band.
        try:
            from src.utils.detection import reload_model

            reload_model()
        except Exception:
            pass
        try:
            self.app._stop_obs_udp_telemetry()
            self.app.destroy()
        except Exception:
            pass

    def _set_engine(self, engine):
        config.detection_engine = engine
        config.ai_detection_enabled = engine == "ai_detection"

    def _vision(self):
        """Build the Vision page; widgets only map once the window is pumped."""
        self.app.deiconify()
        self.app._show_vision_tab()
        self.app.update()

    def test_vision_ai_card_shows_anti_teammate_filter(self):
        """The guard mode is visible, writable, and synced without writing config."""
        self._set_engine("ai_detection")
        with _ConfigSandbox(ai_enemy_outline_filter="auto"):
            self._vision()
            option = self.app.ai_enemy_filter_option
            self.assertEqual(
                list(option.cget("values")),
                ["Auto (No Teammate Class)", "Always On", "Off"],
            )
            self.assertTrue(option.winfo_ismapped(), "the filter dropdown is not shown")
            self.assertEqual(option.get(), "Auto (No Teammate Class)")

            # Choosing "Always On" writes the config value.
            option.set("Always On")
            self.app._on_ai_enemy_filter_selected("Always On")
            self.assertEqual(config.ai_enemy_outline_filter, "on")

            # A hotkey-style change from outside is mirrored, never written back.
            config.ai_enemy_outline_filter = "off"
            self.assertTrue(self.app._sync_engine_ui_from_config())
            self.assertEqual(option.get(), "Off")
            config.ai_enemy_outline_filter = "bogus"
            self.app._sync_engine_ui_from_config()
            self.assertEqual(option.get(), "Auto (No Teammate Class)")
            self.assertEqual(config.ai_enemy_outline_filter, "bogus")

    def test_vision_ai_card_shows_model_class_capability(self):
        """The card must say whether the selected model has a 'teammate' class."""
        self._set_engine("ai_detection")
        self._vision()

        label = getattr(self.app, "ai_teammate_status_label", None)
        self.assertIsNotNone(label, "missing ai_teammate_status_label")
        self.assertTrue(label.winfo_ismapped())
        text = label.cget("text")
        self.assertTrue(
            "teammate" in text or "Enemy Outline Guard" in text,
            f"the capability label says nothing useful: {text!r}",
        )

        # A player-only detector must advertise the guard requirement.
        class _PlayerOnly:
            class_names = ["head", "body", "body", "body"]

            @staticmethod
            def is_ready():
                return True

            @staticmethod
            def teammate_capability_summary():
                return (
                    "Player-only (no 'teammate' class): 4 classes (head, body); "
                    "Enemy Outline Guard required"
                )

        with patch("src.utils.ai_detection.get_ai_detector", return_value=_PlayerOnly()):
            self.app._refresh_teammate_status_label()
        text = self.app.ai_teammate_status_label.cget("text")
        self.assertIn("Player-only", text)
        self.assertIn("Enemy Outline Guard required", text)

        # Native teammate support must be determined from supports_teammate_class(),
        # not by substring-matching the summary prose.
        class _NativeCustomLabel:
            @staticmethod
            def supports_teammate_class():
                return True

            @staticmethod
            def teammate_capability_summary():
                return "5 classes exported (custom wording)"

        with _ConfigSandbox(ai_enemy_outline_filter="auto"), patch(
            "src.utils.ai_detection.get_ai_detector", return_value=_NativeCustomLabel()
        ):
            self.app._refresh_teammate_status_label()
        text = self.app.ai_teammate_status_label.cget("text")
        self.assertIn("Auto: guard idle for this model", text)

    def test_vision_ai_card_warns_when_the_outline_band_is_unusable(self):
        """A reversed custom band makes the guard verify nothing; the card must say so."""
        self._set_engine("ai_detection")
        with _ConfigSandbox(
            ai_enemy_outline_filter="on",
            color="custom",
            custom_hsv_min_h=170, custom_hsv_min_s=255, custom_hsv_min_v=255,
            custom_hsv_max_h=10, custom_hsv_max_s=10, custom_hsv_max_v=10,
        ):
            self._vision()
            text = self.app.ai_teammate_status_label.cget("text")
            self.assertIn("unusable", text)
            self.assertNotIn("Always On: guard runs for every model", text)

            # Fixing the band restores the normal "Always On" description.
            config.custom_hsv_max_h = 179
            config.custom_hsv_max_s = 255
            config.custom_hsv_max_v = 255
            self.assertTrue(self.app._sync_engine_ui_from_config())
            self.assertIn("Always On: guard runs for every model",
                          self.app.ai_teammate_status_label.cget("text"))

    def test_vision_ai_card_outline_colour_quick_selector(self):
        """Changing the outline colour must update config, swatch and hex at once."""
        self._set_engine("ai_detection")
        with _ConfigSandbox(color="purple"):
            self._vision()
            option = getattr(self.app, "enemy_outline_color_option", None)
            swatch = getattr(self.app, "enemy_outline_swatch", None)
            hex_label = getattr(self.app, "enemy_outline_hex_label", None)
            for widget, name in (
                (option, "enemy_outline_color_option"),
                (swatch, "enemy_outline_swatch"),
                (hex_label, "enemy_outline_hex_label"),
            ):
                self.assertIsNotNone(widget, f"missing {name}")
                self.assertTrue(widget.winfo_ismapped(), f"{name} is not shown")

            self.assertEqual(option.get(), "purple")
            purple_hex = hex_label.cget("text")
            self.assertRegex(purple_hex, r"^#[0-9A-F]{6}$")
            self.assertEqual(swatch.cget("fg_color"), purple_hex)

            option.set("red")
            self.app._on_enemy_outline_color_selected("red")
            self.assertEqual(config.color, "red")
            red_hex = hex_label.cget("text")
            self.assertRegex(red_hex, r"^#[0-9A-F]{6}$")
            self.assertNotEqual(red_hex, purple_hex, "the swatch did not follow the colour")
            self.assertEqual(swatch.cget("fg_color"), red_hex)

            # A config change from outside is reflected by the sync.
            config.color = "yellow"
            self.assertTrue(self.app._sync_engine_ui_from_config())
            self.assertEqual(option.get(), "yellow")
            self.assertEqual(hex_label.cget("text"), self.app._enemy_outline_color_hex())

    def test_vision_ai_engine_shows_obs_udp_stream_card(self):
        self._set_engine("ai_detection")
        self._vision()

        for attr in (
            "card_obs_udp_stream",
            "var_ai_udp_stream",
            "var_ai_udp_bypass",
            "obs_udp_plugin_label",
            "obs_udp_telemetry_label",
            "obs_udp_crop_label",
            "obs_udp_ip_entry",
            "obs_udp_port_entry",
        ):
            self.assertTrue(hasattr(self.app, attr), f"missing card widget: {attr}")
        for method in (
            "_build_obs_udp_stream_card",
            "_apply_ai_udp_stream",
            "_copy_ai_obs_preset",
            "_check_or_install_obs_plugin",
            "_refresh_obs_udp_telemetry",
        ):
            self.assertTrue(callable(getattr(self.app, method, None)), f"missing: {method}")

        self.assertTrue(self.app.card_obs_udp_stream.winfo_ismapped())
        self.assertEqual(
            self.app.obs_udp_ip_entry.get(), str(getattr(config, "udp_ip", "0.0.0.0"))
        )
        self.assertEqual(
            self.app.obs_udp_port_entry.get(), str(getattr(config, "udp_port", "3110"))
        )
        # The telemetry job is scheduled while the page is open.
        self.assertIsNotNone(getattr(self.app, "_obs_udp_telemetry_job", None))
        self.assertIn("OBS plugin", self.app.obs_udp_plugin_label.cget("text"))
        self.assertIn("AI UDP crop", self.app.obs_udp_crop_label.cget("text"))

        # Colorbot hides the card again, without destroying it.
        self._set_engine("colorbot")
        self.app._update_engine_cards_visibility()
        self.app.update()
        self.assertFalse(self.app.card_obs_udp_stream.winfo_ismapped())
        self.assertEqual(self.app.card_obs_udp_stream.winfo_manager(), "")

    def test_sync_engine_ui_from_config_follows_config_both_ways(self):
        self._set_engine("colorbot")
        self._vision()
        self.assertEqual(self.app.engine_option.get(), "Colorbot (HSV)")

        # Simulate the F5 hotkey in main.py: config changes behind the UI's back.
        self._set_engine("ai_detection")
        self.assertTrue(self.app._sync_engine_ui_from_config())
        self.app.update()
        self.assertEqual(self.app.engine_option.get(), "AI Detection (DirectML ONNX)")
        self.assertTrue(self.app.card_obs_udp_stream.winfo_ismapped())

        self._set_engine("colorbot")
        self.assertTrue(self.app._sync_engine_ui_from_config())
        self.app.update()
        self.assertEqual(self.app.engine_option.get(), "Colorbot (HSV)")
        self.assertFalse(self.app.card_obs_udp_stream.winfo_ismapped())

        # Config must never be written by a display sync.
        self._set_engine("ai_detection")
        self.app._sync_engine_ui_from_config()
        self.assertEqual(config.detection_engine, "ai_detection")

    def test_apply_ai_udp_stream_updates_config_and_footer(self):
        self._set_engine("ai_detection")
        self._vision()

        capture = self.app.capture
        capture.mode = "NDI"
        capture.connect_udp.return_value = (True, None)
        self.app.obs_udp_ip_entry.delete(0, "end")
        self.app.obs_udp_ip_entry.insert(0, "0.0.0.0")
        self.app.obs_udp_port_entry.delete(0, "end")
        self.app.obs_udp_port_entry.insert(0, "5000")

        self.assertTrue(self.app._apply_ai_udp_stream())
        capture.set_mode.assert_any_call("UDP")
        capture.connect_udp.assert_called_with("0.0.0.0", 5000)
        self.assertEqual(config.udp_port, "5000")
        self.assertEqual(config.capture_mode, "UDP")
        self.assertIn("5000", self.app.footer_udp_label.cget("text"))
        # The switch reflects the real stream, and the mode to return to is the
        # one that was active before Apply, not a lost value.
        self.assertTrue(self.app.var_ai_udp_stream.get())
        self.assertEqual(self.app._ai_udp_previous_mode, "NDI")

    def test_apply_ai_udp_stream_rejects_invalid_port(self):
        self._set_engine("ai_detection")
        self._vision()
        self.app.obs_udp_port_entry.delete(0, "end")
        self.app.obs_udp_port_entry.insert(0, "99999")

        self.assertFalse(self.app._apply_ai_udp_stream())
        self.app.capture.connect_udp.assert_not_called()

    def test_copy_ai_obs_preset_uses_selected_model(self):
        self._set_engine("ai_detection")
        with _ConfigSandbox(ai_model_path="models/my_yolo_model_640.onnx"):
            self._vision()
            text = self.app._copy_ai_obs_preset()
        self.assertIn("640x640", text)
        self.assertIn("Contrast Crush: 0.00", text)

    def test_telemetry_tick_survives_mock_capture_and_reschedules(self):
        self._set_engine("ai_detection")
        self._vision()
        self.app._stop_obs_udp_telemetry()
        self.app._refresh_obs_udp_telemetry()
        self.app.update()
        self.assertTrue(self.app.obs_udp_telemetry_label.cget("text"))
        self.assertIsNotNone(getattr(self.app, "_obs_udp_telemetry_job", None))

    def test_deferred_initial_config_refreshes_the_open_page(self):
        """The delayed first-config pass must not navigate away from Vision.

        Regression: ``_load_initial_config`` hard-coded a jump to Combat, so any
        page opened during the first 200 ms (the Vision OBS UDP card included)
        was destroyed and every widget reference was reset to ``None``.
        """
        self._set_engine("ai_detection")
        self._vision()

        self.app._load_initial_config()
        self.app.update()

        self.assertEqual(self.app._active_tab_name, "Vision")
        self.assertIsNotNone(self.app.card_obs_udp_stream)
        self.assertTrue(self.app.card_obs_udp_stream.winfo_exists())
        self.assertTrue(self.app.obs_udp_port_entry.winfo_exists())
        self.assertTrue(self.app._sync_engine_ui_from_config())

    def test_vision_columns_stay_even_in_ai_mode_with_custom_colour(self):
        """AI mode must not force-collapse the right column on its own.

        The engine branch used to call ``_set_second_column_active(..., False)``
        unconditionally, which fought the layout contract (an even split while
        the HSV card is shown) and left Vision lopsided with the shipped
        ``detection_engine = "ai_detection"`` + ``color = "custom"`` config.
        """
        self._set_engine("ai_detection")
        with _ConfigSandbox(color="custom"):
            self._vision()
            host = self.app._vision_cols
            left = host.grid_slaves(row=0, column=0)[0]
            right = host.grid_slaves(row=0, column=1)[0]
            self.assertAlmostEqual(left.winfo_width(), right.winfo_width(), delta=2)
            self.assertTrue(right.winfo_ismapped())
            self.assertTrue(self.app.card_hsv_tuning.winfo_ismapped())

        # Same rule with the HSV card hidden: the column gives its width back,
        # whatever engine is active.
        with _ConfigSandbox(color="yellow"):
            self.app._update_custom_hsv_visibility()
            self.app.update_idletasks()
            self.assertFalse(right.winfo_ismapped())

    def test_udp_stream_switch_off_disconnects_and_restores_mode(self):
        """The switch is a control, not a dead flag: OFF must stop the stream."""
        self._set_engine("ai_detection")
        with _ConfigSandbox(capture_mode="NDI"):
            self._vision()
            capture = self.app.capture
            capture.mode = "UDP"
            self.app._ai_udp_previous_mode = "NDI"
            self.app.var_ai_udp_stream.set(False)

            self.app._on_ai_udp_stream_toggled()

            self.assertFalse(config.ai_udp_stream_enabled)
            capture.set_mode.assert_called_with("NDI")
            self.assertEqual(config.capture_mode, "NDI")

    def test_udp_stream_switch_on_connects_through_the_apply_path(self):
        self._set_engine("ai_detection")
        with _ConfigSandbox(ai_udp_stream_enabled=False):
            self._vision()
            capture = self.app.capture
            capture.mode = "NDI"
            capture.connect_udp.return_value = (True, None)
            self.app.obs_udp_ip_entry.delete(0, "end")
            self.app.obs_udp_ip_entry.insert(0, "0.0.0.0")
            self.app.obs_udp_port_entry.delete(0, "end")
            self.app.obs_udp_port_entry.insert(0, "5000")
            self.app.var_ai_udp_stream.set(True)

            self.app._on_ai_udp_stream_toggled()

            capture.connect_udp.assert_called_with("0.0.0.0", 5000)
            self.assertTrue(config.ai_udp_stream_enabled)
            self.assertTrue(self.app.var_ai_udp_stream.get())

    def test_failed_apply_clears_the_switch_and_the_intent(self):
        self._set_engine("ai_detection")
        with _ConfigSandbox(ai_udp_stream_enabled=False):
            self._vision()
            self.app.capture.mode = "NDI"
            self.app.capture.connect_udp.return_value = (False, "port in use")
            self.app.obs_udp_ip_entry.delete(0, "end")
            self.app.obs_udp_ip_entry.insert(0, "0.0.0.0")
            self.app.obs_udp_port_entry.delete(0, "end")
            self.app.obs_udp_port_entry.insert(0, "5000")

            self.assertFalse(self.app._apply_ai_udp_stream())

            self.assertFalse(self.app.var_ai_udp_stream.get())
            self.assertFalse(config.ai_udp_stream_enabled)

    def test_install_completion_never_claims_success_it_cannot_prove(self):
        """``Start-Process -RunAs`` returns before the copy: no premature "done"."""
        self._set_engine("ai_detection")
        self._vision()
        not_installed = {
            "installed": False,
            "bundle_available": True,
            "missing": ["obs-plugins/64bit/obs-color-correction.dll"],
        }
        with patch("src.utils.obs_udp_plugin.check_plugin_status", return_value=not_installed):
            self.app._on_obs_plugin_install_done(
                False, "installer launched but the plugin DLLs are not in place"
            )

        status = self.app.status_indicator.cget("text")
        self.assertIn("not installed", status.lower())
        self.assertNotIn("finished", status.lower())
        self.assertIn("NOT installed", self.app.obs_udp_plugin_label.cget("text"))


if __name__ == "__main__":
    unittest.main()
