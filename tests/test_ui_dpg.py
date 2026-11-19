"""Interaction tests for the DearPyGui HUD in ``src/ui_dpg.py``.

The suite builds a real DPG context per test (never shown, never rendered) and
exercises every user-facing interaction: widget tags, config <-> UI sync in
both directions, profile load/save, the timer queue, telemetry and the video
preview frame normalisation.

Two hazards are fenced here:

* ``config.save_to_file`` would write the user's real ``config.json``, so it is
  replaced by a counting recorder for the whole class and restored afterwards.
* ``config`` is a process-wide singleton, so it is snapshotted once and
  restored after every test to keep the tests independent.

Only one DPG context may be alive at a time, so exactly one context is built per
test (in ``setUp``); tests that need a different tracker or capture service swap
the collaborators on the existing app instead of building a second context.
"""

import copy
import os
import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

import dearpygui.dearpygui as dpg

from src.ui_dpg import DpgViewerApp
from src.utils.config import config
from src.utils.debug_logger import log_print


class MockTracker:
    def __init__(self):
        self.normal_x_speed = 0.0
        self.normal_y_speed = 0.0
        self.normalsmooth = 0.0
        self.normalsmoothfov = 0.0
        self.fovsize = 0.0
        self.mouse_dpi = 0
        self.ads_fov_enabled = False
        self.ads_fovsize = 0.0
        self.ads_key = ""
        self.tbfovsize = 0.0
        self.trigger_ads_fov_enabled = False
        self.trigger_ads_fovsize = 0.0
        self.trigger_ads_key = ""
        self.trigger_ads_key_type = ""
        self.selected_tb_btn = 0
        self.current_fps = 144.0
        self.last_latency_ms = 1.8
        self.mouse_api = MagicMock()


class MockCapture:
    def __init__(self, frame=None, error=None):
        self._frame = frame
        self._error = error
        self.calls = 0

    def get_last_frame(self):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._frame


class _CountingSaver:
    """Stands in for ``config.save_to_file`` so tests never touch disk."""

    def __init__(self):
        self.calls = []

    def __call__(self, filename="config.json"):
        self.calls.append(filename)
        return None

    def __len__(self):
        return len(self.calls)


class TestDpgUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._config_snapshot = copy.deepcopy(config.to_dict())
        cls._real_save = config.save_to_file
        cls.saver = _CountingSaver()
        config.save_to_file = cls.saver

    @classmethod
    def tearDownClass(cls):
        config.save_to_file = cls._real_save
        config.from_dict(copy.deepcopy(cls._config_snapshot))

    def setUp(self):
        config.from_dict(copy.deepcopy(self._config_snapshot))
        self.saver.calls.clear()
        self.tracker = MockTracker()
        self.app = DpgViewerApp(tracker=self.tracker, capture_service=None)

    def tearDown(self):
        if getattr(self, "app", None) is not None:
            self.app._on_close()
        config.from_dict(copy.deepcopy(self._config_snapshot))

    def _use_collaborators(self, tracker="keep", capture=None, preview_enabled=False):
        """Point the existing app at different collaborators.

        No second DPG context is created: the app is rebuilt only by setUp, so
        the suite never depends on repeated context creation being stable.
        """
        if tracker != "keep":
            self.app.tracker = tracker
        self.app.capture = capture
        self.app.capture_service = capture
        self.app.preview_enabled = preview_enabled
        return self.app

    # --- (a) widget tags -------------------------------------------------
    def test_config_widget_tags_exist(self):
        self.assertTrue(DpgViewerApp._CONFIG_WIDGETS)
        keys = [key for key, _ in DpgViewerApp._CONFIG_WIDGETS]
        self.assertEqual(len(keys), len(set(keys)), "duplicate keys in _CONFIG_WIDGETS")
        for key in keys:
            tag = self.app._cfg_tag(key)
            self.assertEqual(tag, f"cfg_{key}")
            self.assertTrue(dpg.does_item_exist(tag), f"missing widget tag {tag}")

    def test_non_config_widget_tags_exist(self):
        for tag in (
            "chk_preview",
            "btn_load_profile",
            "btn_save_profile",
            "btn_reconnect_serial",
            "combo_preset_profile",
            "txt_status_badge",
            "txt_log_console",
        ):
            self.assertTrue(dpg.does_item_exist(tag), f"missing widget tag {tag}")

    def test_config_widgets_are_readable(self):
        # A tag on a decorative item would be silently accepted by the tag test
        # above but could never be synced; every entry must have a readable value.
        for key, _type_fn in DpgViewerApp._CONFIG_WIDGETS:
            tag = self.app._cfg_tag(key)
            self.assertIsInstance(dpg.get_item_configuration(tag), dict)
            self.assertIsNotNone(dpg.get_value(tag), f"{tag} has no readable value")
            self.assertIsNotNone(dpg.get_item_callback(tag), f"{tag} has no callback")

    # --- (b) config -> UI ------------------------------------------------
    def test_sync_ui_from_config_updates_widgets(self):
        config.fovsize = 77.0
        config.normal_x_speed = 123.0
        config.enableaim = False
        config.mode = "Silent"
        config.color = "red"
        config.mouse_api = "Makcu"
        config.selected_mouse_button = 2

        self.assertTrue(self.app._sync_ui_from_config())

        self.assertAlmostEqual(dpg.get_value("cfg_fovsize"), 77.0, places=4)
        self.assertAlmostEqual(dpg.get_value("cfg_normal_x_speed"), 123.0, places=4)
        self.assertFalse(dpg.get_value("cfg_enableaim"))
        self.assertEqual(dpg.get_value("cfg_mode"), "Silent")
        self.assertEqual(dpg.get_value("cfg_color"), "red")
        self.assertEqual(dpg.get_value("cfg_mouse_api"), "Makcu")
        self.assertEqual(dpg.get_value("cfg_selected_mouse_button"), "Right Mouse")

    def test_sync_ui_from_config_is_idempotent(self):
        config.fovsize = 61.0
        config.mouse_dpi = 1600
        self.assertTrue(self.app._sync_ui_from_config())
        first = {
            key: dpg.get_value(self.app._cfg_tag(key))
            for key, _ in DpgViewerApp._CONFIG_WIDGETS
        }
        self.assertTrue(self.app._sync_ui_from_config())
        second = {
            key: dpg.get_value(self.app._cfg_tag(key))
            for key, _ in DpgViewerApp._CONFIG_WIDGETS
        }
        self.assertEqual(first, second)

    def test_sync_ui_from_config_clamps_display_but_keeps_config(self):
        # Out-of-domain profile values must never be written back to config.
        config.fovsize = 999.0
        config.normal_x_speed_sec = 2.0  # below the slider's 10.0 floor
        real_config = dpg.get_item_configuration

        def _config_with_bounds(tag, **kwargs):
            item = dict(real_config(tag, **kwargs) or {})
            if tag == "cfg_fovsize":
                item["min_value"], item["max_value"] = 5.0, 120.0
            if tag == "cfg_normal_x_speed_sec":
                item["min_value"], item["max_value"] = 10.0, 250.0
            return item

        with patch("src.ui_dpg.dpg.get_item_configuration", side_effect=_config_with_bounds):
            self.assertTrue(self.app._sync_ui_from_config())

        self.assertAlmostEqual(dpg.get_value("cfg_fovsize"), 120.0, places=4)
        self.assertAlmostEqual(dpg.get_value("cfg_normal_x_speed_sec"), 10.0, places=4)
        # Display-only clamp: the stored config keeps the profile value.
        self.assertEqual(config.fovsize, 999.0)
        self.assertEqual(config.normal_x_speed_sec, 2.0)

    def test_sync_ui_from_config_skips_combo_value_outside_items(self):
        # A profile may name an engine/bone the combo does not offer; the old
        # display must survive instead of an invented item appearing.
        config.aim_type = "body"
        real_config = dpg.get_item_configuration

        def _config_with_items(tag, **kwargs):
            item = dict(real_config(tag, **kwargs) or {})
            if tag == "cfg_aim_type":
                item["items"] = ["head", "neck", "chest"]
            return item

        dpg.set_value("cfg_aim_type", "head")
        with patch("src.ui_dpg.dpg.get_item_configuration", side_effect=_config_with_items):
            self.app._sync_ui_from_config()

        self.assertEqual(dpg.get_value("cfg_aim_type"), "head")

    def test_sync_ui_from_config_does_not_save_config(self):
        before = len(self.saver)
        config.fovsize = 44.0
        self.app._sync_ui_from_config()
        self.assertEqual(len(self.saver), before)

    def test_sync_ui_from_config_status_badge(self):
        config.ai_detection_enabled = False
        config.detection_engine = "colorbot"
        self.app._sync_ui_from_config()
        self.assertEqual(dpg.get_value("txt_status_badge"), "STATUS: ONLINE")

        config.ai_detection_enabled = True
        config.detection_engine = "ai_detection"
        self.app._sync_ui_from_config()
        self.assertEqual(dpg.get_value("txt_status_badge"), "STATUS: AI DETECTION")

    def test_sync_ui_from_config_returns_false_after_close(self):
        self.app._on_close()
        self.assertFalse(self.app._sync_ui_from_config())
        self.assertFalse(self.app._sync_engine_ui_from_config())

    # --- (c) UI -> config ------------------------------------------------
    def test_checkbox_callback_writes_config_and_saves(self):
        callback = dpg.get_item_callback("cfg_enableaim")
        self.assertIsNotNone(callback)
        callback("cfg_enableaim", False)
        self.assertFalse(config.enableaim)
        self.assertEqual(len(self.saver), 1)

        callback("cfg_enableaim", True)
        self.assertTrue(config.enableaim)
        self.assertEqual(len(self.saver), 2)

    def test_slider_callback_writes_config_and_tracker(self):
        callback = dpg.get_item_callback("cfg_fovsize")
        self.assertIsNotNone(callback)
        callback("cfg_fovsize", 88.5)
        self.assertAlmostEqual(config.fovsize, 88.5, places=5)
        self.assertAlmostEqual(self.tracker.fovsize, 88.5, places=5)

        dpi_cb = dpg.get_item_callback("cfg_mouse_dpi")
        dpi_cb("cfg_mouse_dpi", 3200)
        self.assertEqual(config.mouse_dpi, 3200)
        self.assertEqual(self.tracker.mouse_dpi, 3200)

    def test_combo_callback_writes_config(self):
        callback = dpg.get_item_callback("cfg_mode")
        self.assertIsNotNone(callback)
        callback("cfg_mode", "Bezier")
        self.assertEqual(config.mode, "Bezier")

        color_cb = dpg.get_item_callback("cfg_color")
        color_cb("cfg_color", "yellow")
        self.assertEqual(config.color, "yellow")

    def test_aim_button_callback_writes_config(self):
        callback = dpg.get_item_callback("cfg_selected_mouse_button")
        self.assertIsNotNone(callback)
        callback("cfg_selected_mouse_button", "Left Mouse")
        self.assertEqual(config.selected_mouse_button, 1)
        callback("cfg_selected_mouse_button", "Side Mouse 5")
        self.assertEqual(config.selected_mouse_button, 5)
        callback("cfg_selected_mouse_button", "Right Mouse")
        self.assertEqual(config.selected_mouse_button, 2)

    def test_toggle_preview_callback(self):
        callback = dpg.get_item_callback("chk_preview")
        self.assertIsNotNone(callback)
        callback("chk_preview", True)
        self.assertTrue(self.app.preview_enabled)
        callback("chk_preview", False)
        self.assertFalse(self.app.preview_enabled)

    # --- (d) profile load / save ----------------------------------------
    def _load_with(self, choice, load_stub):
        dpg.set_value("combo_preset_profile", choice)
        with patch("src.ui_dpg.os.path.exists", return_value=True), patch.object(
            config, "load_from_file", side_effect=load_stub
        ) as loader:
            self.app._cb_load_profile()
        return loader

    def test_load_profile_updates_ui_tracker_and_badge(self):
        def _stub(filename):
            config.fovsize = 33.0
            config.mode = "Flick"
            config.ai_detection_enabled = True
            config.detection_engine = "ai_detection"

        loader = self._load_with("config.json (Default)", _stub)
        loader.assert_called_once_with("config.json")

        self.assertAlmostEqual(dpg.get_value("cfg_fovsize"), 33.0, places=4)
        self.assertEqual(dpg.get_value("cfg_mode"), "Flick")
        self.assertEqual(dpg.get_value("txt_status_badge"), "STATUS: AI DETECTION")
        self.assertAlmostEqual(self.tracker.fovsize, 33.0, places=4)

    def test_load_profile_picks_file_per_combo_branch(self):
        cases = {
            "config.json (Default)": "config.json",
            "config.burst_spray.json": "config.burst_spray.json",
            "udp_144hz_fast_cvm.json": os.path.join("configs", "udp_144hz_fast_cvm.json"),
            "2aim_cvm.json": os.path.join("configs", "2aim_cvm.json"),
        }
        for choice, expected in cases.items():
            with self.subTest(choice=choice):
                loader = self._load_with(choice, lambda filename: None)
                loader.assert_called_once_with(expected)

    def test_load_profile_missing_file_is_noop(self):
        dpg.set_value("combo_preset_profile", "2aim_cvm.json")
        with patch("src.ui_dpg.os.path.exists", return_value=False), patch.object(
            config, "load_from_file"
        ) as loader:
            self.app._cb_load_profile()
        loader.assert_not_called()

    def test_save_profile_calls_save(self):
        dpg.get_item_callback("btn_save_profile")("btn_save_profile", None)
        self.assertEqual(len(self.saver), 1)

    def test_reconnect_serial_success_and_failure(self):
        self.app._cb_reconnect_serial()
        self.tracker.mouse_api.disconnect.assert_called_once()
        self.tracker.mouse_api.connect.assert_called_once()

        self.tracker.mouse_api.disconnect.side_effect = RuntimeError("boom")
        self.app._cb_reconnect_serial()  # must not raise

    def test_reconnect_serial_without_mouse_api(self):
        self.tracker.mouse_api = None
        self.app._cb_reconnect_serial()  # must not raise

    # --- (e) timer queue -------------------------------------------------
    def test_after_runs_due_callback_once(self):
        calls = []
        self.app.after(0, lambda: calls.append(1))
        self.app._process_callbacks()
        self.assertEqual(calls, [1])
        self.app._process_callbacks()
        self.assertEqual(calls, [1])

    def test_after_passes_positional_args(self):
        calls = []
        self.app.after(0, lambda a, b: calls.append((a, b)), 1, 2)
        self.app._process_callbacks()
        self.assertEqual(calls, [(1, 2)])

    def test_after_does_not_run_early(self):
        calls = []
        self.app.after(150, lambda: calls.append(1))
        self.app._process_callbacks()
        self.assertEqual(calls, [])
        time.sleep(0.2)
        self.app._process_callbacks()
        self.assertEqual(calls, [1])

    def test_failing_callback_does_not_block_others(self):
        calls = []

        def _boom():
            raise RuntimeError("callback exploded")

        self.app.after(0, _boom)
        self.app.after(0, lambda: calls.append("ok"))
        self.app._process_callbacks()
        self.assertEqual(calls, ["ok"])
        # The failed callback is dropped, not retried forever.
        self.app._process_callbacks()
        self.assertEqual(calls, ["ok"])

    def test_protocol_register_and_close_handler(self):
        calls = []
        self.app.protocol("WM_DELETE_WINDOW", lambda: calls.append(1))
        self.app._on_close()
        self.assertEqual(calls, [1])

    # --- (f) hotkey compatibility path -----------------------------------
    def test_sync_engine_ui_from_config_is_reachable_from_main(self):
        self.assertTrue(hasattr(self.app, "_sync_engine_ui_from_config"))
        config.ai_detection_enabled = True
        config.detection_engine = "ai_detection"
        self.app.after(0, self.app._sync_engine_ui_from_config)
        self.app._process_callbacks()
        self.assertEqual(dpg.get_value("txt_status_badge"), "STATUS: AI DETECTION")

        config.ai_detection_enabled = False
        config.detection_engine = "colorbot"
        self.app.after(0, self.app._sync_engine_ui_from_config)
        self.app._process_callbacks()
        self.assertEqual(dpg.get_value("txt_status_badge"), "STATUS: ONLINE")

    # --- (g) telemetry ---------------------------------------------------
    def test_telemetry_window_and_console(self):
        message = "telemetry-probe-%d" % time.time_ns()
        log_print(message)
        self.app._last_telemetry_time = 0.0
        before = list(self.app.plot_latency)

        self.tracker.last_latency_ms = 4.2
        self.tracker.current_fps = 60.0
        self.app._update_telemetry()

        self.assertEqual(len(self.app.plot_latency), self.app.max_plot_pts)
        self.assertEqual(self.app.plot_latency[-1], 4.2)
        self.assertEqual(self.app.plot_fps[-1], 6.0)
        self.assertEqual(self.app.plot_latency[:-1], before[1:])

        console = dpg.get_value("txt_log_console")
        self.assertIsInstance(console, str)
        self.assertIn(message, console)

    def test_telemetry_pushes_plot_series(self):
        self.app._last_telemetry_time = 0.0
        self.tracker.last_latency_ms = 7.5
        self.tracker.current_fps = 90.0
        with patch("src.ui_dpg.dpg.set_value") as set_value:
            self.app._update_telemetry()

        payloads = {call.args[0]: call.args[1] for call in set_value.call_args_list}
        self.assertIn(self.app.series_latency, payloads)
        self.assertIn(self.app.series_fps, payloads)
        xs, ys = payloads[self.app.series_latency]
        self.assertEqual(xs, self.app.plot_x)
        self.assertAlmostEqual(ys[-1], 7.5, places=5)
        self.assertAlmostEqual(payloads[self.app.series_fps][1][-1], 9.0, places=5)

    def test_telemetry_tolerates_none_and_nan(self):
        for bad in (None, float("nan"), float("inf"), "not-a-number"):
            with self.subTest(value=bad):
                self.tracker.last_latency_ms = bad
                self.tracker.current_fps = bad
                self.app._last_telemetry_time = 0.0
                self.app._update_telemetry()
                self.assertTrue(np.isfinite(self.app.plot_latency[-1]))
                self.assertTrue(np.isfinite(self.app.plot_fps[-1]))

    def test_telemetry_without_tracker(self):
        app = self._use_collaborators(tracker=None)
        app._last_telemetry_time = 0.0
        app._update_telemetry()
        self.assertEqual(len(app.plot_latency), app.max_plot_pts)
        self.assertTrue(np.isfinite(app.plot_latency[-1]))

    # --- (h) video preview ----------------------------------------------
    def _preview_app(self, frame=None, error=None, enabled=True):
        capture = MockCapture(frame=frame, error=error)
        return self._use_collaborators(capture=capture, preview_enabled=enabled), capture

    def _assert_flat_buffer(self, buffer):
        self.assertIsInstance(buffer, np.ndarray)
        self.assertEqual(buffer.ndim, 1)
        self.assertEqual(buffer.dtype, np.float32)
        self.assertEqual(buffer.size, self.app.preview_w * self.app.preview_h * 4)
        self.assertGreaterEqual(float(buffer.min()), 0.0)
        self.assertLessEqual(float(buffer.max()), 1.0)

    def test_preview_none_frame(self):
        app, _capture = self._preview_app(frame=None)
        self.assertFalse(app._update_video_preview())

    def test_preview_empty_frames(self):
        for frame in (
            np.array([], dtype=np.uint8),
            np.zeros((0, 0, 3), dtype=np.uint8),
            np.zeros((0, 10), dtype=np.uint8),
            "not-a-frame",
        ):
            with self.subTest(shape=getattr(frame, "shape", type(frame))):
                app, _capture = self._preview_app(frame=frame)
                self.assertFalse(app._update_video_preview())
                self.assertEqual(app._preview_error_count, 0)

    def test_preview_publishes_flat_float32_buffer(self):
        cases = {
            "bgr": np.zeros((48, 64, 3), dtype=np.uint8),
            "bgra": np.full((48, 64, 4), 255, dtype=np.uint8),
            "gray2d": np.zeros((48, 64), dtype=np.uint8),
            "mask1ch": np.zeros((48, 64, 1), dtype=np.uint8),
            "float01": np.zeros((48, 64, 3), dtype=np.float32),
            "bgr_float255": np.full((48, 64, 3), 255.0, dtype=np.float32),
        }
        for name, frame in cases.items():
            with self.subTest(kind=name):
                app, _capture = self._preview_app(frame=frame)
                published = []
                with patch(
                    "src.ui_dpg.dpg.set_value",
                    side_effect=lambda tag, val: published.append(val),
                ):
                    self.assertTrue(app._update_video_preview())
                self.assertEqual(len(published), 1)
                self._assert_flat_buffer(published[0])

    def test_preview_resizes_odd_frames(self):
        app, _capture = self._preview_app(frame=np.zeros((1, 7), dtype=np.uint8))
        buffer = app._prepare_preview_rgba(np.zeros((1, 7), dtype=np.uint8))
        self._assert_flat_buffer(buffer)

    def test_preview_rejects_unsupported_channel_counts(self):
        for frame in (
            np.zeros((16, 16, 2), dtype=np.uint8),
            np.zeros((16, 16, 5), dtype=np.uint8),
            np.zeros((16, 16, 3, 2), dtype=np.uint8),
        ):
            with self.subTest(shape=frame.shape):
                app, _capture = self._preview_app(frame=frame)
                self.assertFalse(app._update_video_preview())

    def test_preview_capture_error_is_swallowed_and_counted(self):
        app, _capture = self._preview_app(error=RuntimeError("grab failed"))
        self.assertFalse(app._update_video_preview())
        self.assertEqual(app._preview_error_count, 1)
        # Second failure is counted but not logged again.
        self.assertFalse(app._update_video_preview())
        self.assertEqual(app._preview_error_count, 2)

    def test_preview_disabled_does_not_read_capture(self):
        app, capture = self._preview_app(
            frame=np.zeros((8, 8, 3), dtype=np.uint8), enabled=False
        )
        self.assertFalse(app._update_video_preview())
        self.assertEqual(capture.calls, 0)

    def test_preview_publishes_into_real_texture(self):
        # No patch: proves DPG itself accepts the published buffer format
        # (a rejected buffer would be caught and turn the return value False).
        frame = np.full((40, 40, 3), 200, dtype=np.uint8)
        app, _capture = self._preview_app(frame=frame)
        self.assertTrue(app._update_video_preview())
        self.assertEqual(app._preview_error_count, 0)

    def test_preview_after_close_returns_false(self):
        app, _capture = self._preview_app(frame=np.zeros((8, 8, 3), dtype=np.uint8))
        app._on_close()
        self.assertFalse(app._update_video_preview())

    # --- (i) lifecycle ---------------------------------------------------
    def test_close_is_idempotent(self):
        self.app._on_close()
        self.assertFalse(self.app._running)
        self.app._on_close()  # second close must not raise
        self.assertFalse(self.app._running)

    def test_sync_config_to_tracker_without_tracker_still_syncs_ui(self):
        app = self._use_collaborators(tracker=None)
        config.fovsize = 55.0
        config.mouse_dpi = 2400
        app._sync_config_to_tracker()
        self.assertAlmostEqual(dpg.get_value("cfg_fovsize"), 55.0, places=4)
        self.assertEqual(dpg.get_value("cfg_mouse_dpi"), 2400)

    def test_ui_to_config_to_ui_round_trip_converges(self):
        # UI -> config -> tracker -> UI must settle on the widget's own value.
        dpg.get_item_callback("cfg_normal_y_speed")("cfg_normal_y_speed", 142.5)
        self.assertAlmostEqual(config.normal_y_speed, 142.5, places=5)
        self.assertAlmostEqual(self.tracker.normal_y_speed, 142.5, places=5)
        self.assertAlmostEqual(dpg.get_value("cfg_normal_y_speed"), 142.5, places=4)

    def test_runtime_toggle_and_start_stop(self):
        self.assertFalse(self.app._runtime_active)
        self.app._toggle_runtime()
        # Toggle triggers start worker
        self.app._stop_runtime()
        self.assertFalse(self.app._runtime_active)

    def test_capture_mode_callback(self):
        self.app._cb_capture_mode(None, "UDP")
        self.assertEqual(config.capture_mode, "UDP")

    def test_reconnect_capture_without_crash(self):
        self.app._cb_reconnect_capture()  # must not raise


if __name__ == "__main__":
    unittest.main()
