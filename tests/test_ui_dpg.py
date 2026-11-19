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
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

import dearpygui.dearpygui as dpg

from src.ui_dpg import (
    DpgViewerApp,
    _AIM_TYPE_ITEMS,
    _CAPTURE_MODE_ITEMS,
    _MODE_ITEMS,
    _MOUSE_API_ITEMS,
    _SERIAL_MODE_ITEMS,
)
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


class _ReceiverStub:
    """UDP receiver stub exposing only the performance stats surface."""

    def __init__(self, stats):
        self._stats = stats

    def get_performance_stats(self):
        return self._stats


class _UdpManagerStub:
    def __init__(self, receiver):
        self._receiver = receiver

    def get_receiver(self):
        return self._receiver


class CaptureTelemetryStub:
    """Capture service stub publishing UDP stats and/or frame metadata."""

    def __init__(self, stats=None, meta=None, mode="UDP"):
        self.mode = mode
        self.udp_manager = _UdpManagerStub(_ReceiverStub(stats)) if stats is not None else None
        self._meta = meta
        self.connect_calls = []
        self.disconnect_calls = 0

    def get_frame_meta(self):
        return self._meta

    def set_mode(self, mode):
        self.mode = mode

    def disconnect(self):
        self.disconnect_calls += 1

    def connect_udp(self, ip, port):
        self.connect_calls.append((ip, port))
        return True, None


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
        # The app schedules ``_maybe_auto_start_runtime`` 500 ms after
        # construction. Keep it disarmed so a slow test can never make the HUD
        # open real serial/UDP hardware from the test process.
        config.auto_connect_mouse_api = False
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
        config.mouse_api = "Medius"
        config.selected_mouse_button = 2

        self.assertTrue(self.app._sync_ui_from_config())

        self.assertAlmostEqual(dpg.get_value("cfg_fovsize"), 77.0, places=4)
        self.assertAlmostEqual(dpg.get_value("cfg_normal_x_speed"), 123.0, places=4)
        self.assertFalse(dpg.get_value("cfg_enableaim"))
        self.assertEqual(dpg.get_value("cfg_mode"), "Silent")
        self.assertEqual(dpg.get_value("cfg_color"), "red")
        self.assertEqual(dpg.get_value("cfg_mouse_api"), "Medius")
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

        class _DeferredThread:
            """Records the worker but never runs it: no hardware in tests."""

            started = []

            def __init__(self, target, args=(), **kwargs):
                self._target = target
                self._args = args

            def start(self):
                _DeferredThread.started.append((self._target, self._args))

        with patch("src.ui_dpg.threading.Thread", _DeferredThread):
            self.app._toggle_runtime()
        self.assertEqual(len(_DeferredThread.started), 1)

        with patch("src.utils.mouse.disconnect_all", return_value=None):
            self.app._stop_runtime()
        self.assertFalse(self.app._runtime_active)
        self.assertFalse(self.app._runtime_busy)

    def test_capture_mode_callback(self):
        self.app._cb_capture_mode(None, "UDP")
        self.assertEqual(config.capture_mode, "UDP")

    def test_reconnect_capture_without_crash(self):
        self.app._cb_reconnect_capture()  # must not raise

    # --- (j) combo domains ----------------------------------------------
    def test_combo_domains_match_module_tuples(self):
        self.assertEqual(_MODE_ITEMS, ("Normal", "Flick", "Silent", "NCAF", "WindMouse", "Bezier", "PID"))
        self.assertEqual(_AIM_TYPE_ITEMS, ("head", "body", "nearest"))
        self.assertEqual(_SERIAL_MODE_ITEMS, ("Auto", "Manual"))
        self.assertEqual(len(_MOUSE_API_ITEMS), 12)
        self.assertIn("CaptureCardGStreamer", _CAPTURE_MODE_ITEMS)

        cases = (
            ("mode", "cfg_mode", _MODE_ITEMS),
            ("aim_type", "cfg_aim_type", _AIM_TYPE_ITEMS),
            ("mouse_api", "cfg_mouse_api", _MOUSE_API_ITEMS),
            ("serial_port_mode", "cfg_serial_port_mode", _SERIAL_MODE_ITEMS),
            ("capture_mode", "cfg_capture_mode", _CAPTURE_MODE_ITEMS),
        )
        for key, tag, expected in cases:
            with self.subTest(tag=tag):
                # DPG exposes a combo's items in its configuration dict; the
                # round-trip below also proves the widget really accepts each
                # value instead of silently keeping the previous one.
                configured = (dpg.get_item_configuration(tag) or {}).get("items")
                self.assertIsNotNone(configured, f"{tag} does not expose items")
                self.assertEqual(tuple(configured), tuple(expected))
                for value in expected:
                    setattr(config, key, value)
                    self.app._sync_ui_from_config()
                    self.assertEqual(
                        dpg.get_value(tag),
                        value,
                        f"{value!r} was rejected by {tag}",
                    )

    def test_combo_domains_cover_config_normalisation(self):
        # Every canonical name the engine normalises to must be selectable, so a
        # saved profile never hits the "outside items" skip branch.
        for bogus in ("Makcu", "Kmbox", "kmboxa"):
            with self.subTest(name=bogus):
                self.assertNotIn(bogus, _MOUSE_API_ITEMS)
        self.assertNotIn("COM4", _SERIAL_MODE_ITEMS)
        self.assertNotIn("neck", _AIM_TYPE_ITEMS)

    def test_engine_choices_sync_into_widgets(self):
        cases = (
            ("mode", "PID", "cfg_mode"),
            ("mode", "NCAF", "cfg_mode"),
            ("aim_type", "body", "cfg_aim_type"),
            ("aim_type", "nearest", "cfg_aim_type"),
            ("serial_port_mode", "Manual", "cfg_serial_port_mode"),
            ("mouse_api", "Medius", "cfg_mouse_api"),
            ("capture_mode", "CaptureCardGStreamer", "cfg_capture_mode"),
        )
        for key, value, tag in cases:
            with self.subTest(key=key, value=value):
                setattr(config, key, value)
                self.app._sync_ui_from_config()
                self.assertEqual(dpg.get_value(tag), value)

    def test_serial_port_round_trip(self):
        config.serial_port = "COM7"
        self.app._sync_ui_from_config()
        self.assertEqual(dpg.get_value("cfg_serial_port"), "COM7")

        before = len(self.saver)
        callback = dpg.get_item_callback("cfg_serial_port")
        self.assertIsNotNone(callback)
        callback("cfg_serial_port", "COM12")
        self.assertEqual(config.serial_port, "COM12")
        self.assertEqual(len(self.saver), before + 1)

    def test_serial_port_none_displays_empty_string(self):
        config.serial_port = None
        self.app._sync_ui_from_config()
        value = dpg.get_value("cfg_serial_port")
        # Never the literal "None": an unset port is an empty field.
        self.assertIn(value, ("", None))

    def test_no_hardcoded_telemetry_strings_in_source(self):
        source = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src", "ui_dpg.py")
        with open(source, "r", encoding="utf-8") as handle:
            text = handle.read()
        for stale in ("(AVG 1.8ms)", "144.2 Hz"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, text)

    def test_initial_sync_matches_config(self):
        # setUp built the app with the current config: no INITIALIZING badge
        # and no save during construction.
        self.assertEqual(len(self.saver), 0)
        self.assertAlmostEqual(dpg.get_value("cfg_fovsize"), float(config.fovsize), places=4)
        self.assertEqual(dpg.get_value("cfg_mode"), config.mode)
        self.assertEqual(dpg.get_value("cfg_serial_port"), str(config.serial_port))
        badge = dpg.get_value("txt_status_badge")
        self.assertNotIn("INITIALIZING", badge)
        self.assertTrue(badge.strip())

        before = len(self.saver)
        self.app._sync_ui_from_config()
        self.assertEqual(len(self.saver), before)

    # --- (k) telemetry sources ------------------------------------------
    def _telemetry_with(self, tracker="keep", capture=None):
        app = self._use_collaborators(tracker=tracker, capture=capture)
        app._last_telemetry_time = 0.0
        return app

    def test_telemetry_reads_udp_stats(self):
        capture = CaptureTelemetryStub(
            stats={
                "current_fps": 120.0,
                "receive_delay_ms": 1.5,
                "decode_delay_ms": 2.0,
                "processing_delay_ms": 0.5,
                "last_packet_age_s": 0.01,
            },
            meta={"publish_latency_ms": 9.9},
        )
        app = self._telemetry_with(tracker=None, capture=capture)
        # UDP stats win over the frame meta latency while the stream is alive.
        self.assertEqual(app._read_telemetry_sample(), (120.0, 4.0))
        app._update_telemetry()
        self.assertAlmostEqual(app.plot_latency[-1], 4.0, places=5)
        self.assertAlmostEqual(app.plot_fps[-1], 12.0, places=5)
        self.assertEqual(dpg.get_value("txt_telemetry_avg_lat"), "(AVG 4.0ms)")
        self.assertEqual(dpg.get_value("txt_telemetry_rate"), "120.0 Hz")

    def test_telemetry_falls_back_to_frame_meta_latency(self):
        capture = CaptureTelemetryStub(stats={"current_fps": 0.0}, meta={"publish_latency_ms": 6.5})
        app = self._telemetry_with(tracker=None, capture=capture)
        self.assertEqual(app._read_telemetry_sample(), (0.0, 6.5))

    def test_telemetry_stalled_udp_reports_zero_fps(self):
        capture = CaptureTelemetryStub(
            stats={
                "current_fps": 144.0,
                "receive_delay_ms": 1.0,
                "last_packet_age_s": 5.0,
            }
        )
        app = self._telemetry_with(tracker=None, capture=capture)
        app._update_telemetry()
        self.assertEqual(app.plot_fps[-1], 0.0)
        self.assertEqual(dpg.get_value("txt_telemetry_rate"), "0.0 Hz")

    def test_telemetry_falls_back_to_tracker_without_capture_source(self):
        capture = CaptureTelemetryStub(stats=None, meta={})
        app = self._telemetry_with(capture=capture)
        self.tracker.current_fps = 77.0
        self.tracker.last_latency_ms = 3.25
        self.assertEqual(app._read_telemetry_sample(), (77.0, 3.25))

    def test_telemetry_falls_back_to_tracker_perf(self):
        app = self._telemetry_with(capture=None)
        self.tracker.last_latency_ms = None
        self.tracker.perf = {"publish_to_detect_ms": 2.75}
        self.assertEqual(app._read_telemetry_sample()[1], 2.75)

    def test_telemetry_without_any_source_shows_placeholder(self):
        app = self._telemetry_with(tracker=None, capture=None)
        self.assertEqual(app._read_telemetry_sample(), (None, None))
        app._update_telemetry()
        self.assertEqual(app.plot_latency[-1], 0.0)
        self.assertEqual(app.plot_fps[-1], 0.0)
        self.assertEqual(dpg.get_value("txt_telemetry_avg_lat"), "(AVG --ms)")
        self.assertEqual(dpg.get_value("txt_telemetry_rate"), "-- Hz")

    def test_telemetry_nan_and_bad_stats_do_not_raise(self):
        capture = CaptureTelemetryStub(
            stats={
                "current_fps": float("nan"),
                "receive_delay_ms": float("inf"),
                "decode_delay_ms": "oops",
                "last_packet_age_s": None,
            },
            meta={"publish_latency_ms": float("nan")},
        )
        app = self._telemetry_with(tracker=None, capture=capture)
        app._update_telemetry()
        self.assertTrue(np.isfinite(app.plot_latency[-1]))
        self.assertTrue(np.isfinite(app.plot_fps[-1]))

    def test_telemetry_survives_broken_capture(self):
        capture = MagicMock()
        capture.mode = "UDP"
        capture.udp_manager.get_receiver.side_effect = RuntimeError("receiver gone")
        capture.get_frame_meta.side_effect = RuntimeError("meta gone")
        app = self._telemetry_with(tracker=None, capture=capture)
        app._update_telemetry()  # must not raise
        self.assertTrue(np.isfinite(app.plot_latency[-1]))

    def test_telemetry_avg_uses_measured_samples_only(self):
        app = self._telemetry_with(capture=None)
        self.tracker.last_latency_ms = 10.0
        app._last_telemetry_time = 0.0
        app._update_telemetry()
        self.tracker.last_latency_ms = 20.0
        app._last_telemetry_time = 0.0
        app._update_telemetry()
        self.assertEqual(dpg.get_value("txt_telemetry_avg_lat"), "(AVG 15.0ms)")

    def test_telemetry_after_close_is_silent(self):
        app = self._telemetry_with(capture=None)
        app._on_close()
        app._last_telemetry_time = 0.0
        before = list(app.plot_latency)
        with patch("src.ui_dpg.dpg.set_value") as set_value:
            app._update_telemetry()
            app._process_callbacks()
        set_value.assert_not_called()
        self.assertEqual(app.plot_latency, before)

    # --- (l) thread safety ----------------------------------------------
    def test_start_runtime_worker_never_calls_dpg(self):
        capture = CaptureTelemetryStub(stats={}, meta={})
        app = self._use_collaborators(capture=capture)
        config.capture_mode = "UDP"
        dpg.set_value("input_udp_ip", "10.0.0.5")
        dpg.set_value("input_udp_port", "6001")
        main_thread = threading.current_thread().ident
        read_threads = []
        real_get_value = dpg.get_value

        def _record_thread(tag, *args, **kwargs):
            read_threads.append(threading.current_thread().ident)
            return real_get_value(tag, *args, **kwargs)

        with patch("src.ui_dpg.dpg.get_value", side_effect=_record_thread), patch(
            "src.utils.mouse.switch_backend", return_value=(True, None)
        ):
            app._start_runtime()
            # The worker is a real background thread: wait for it to reach
            # connect_udp, i.e. past every DPG access it might attempt.
            deadline = time.time() + 10.0
            while not capture.connect_calls and time.time() < deadline:
                time.sleep(0.01)

        self.assertEqual(capture.connect_calls, [("10.0.0.5", "6001")])
        # Both widget reads happened, and all of them on the caller's thread.
        self.assertEqual(len(read_threads), 2)
        self.assertEqual(
            set(read_threads),
            {main_thread},
            "dpg.get_value was called from a background thread",
        )

    def test_start_runtime_worker_ignores_config_endpoint_when_ui_has_values(self):
        capture = CaptureTelemetryStub(stats={}, meta={})
        app = self._use_collaborators(capture=capture)
        config.capture_mode = "UDP"
        config.udp_ip = "0.0.0.0"
        config.udp_port = "5000"
        dpg.set_value("input_udp_ip", "192.168.1.9")
        dpg.set_value("input_udp_port", "7000")

        with patch("src.utils.mouse.switch_backend", return_value=(True, None)):
            app._start_runtime_worker("192.168.1.9", "7000")
        self.assertEqual(capture.connect_calls, [("192.168.1.9", "7000")])

    def test_read_udp_endpoint_falls_back_to_config(self):
        app = self._use_collaborators(capture=None)
        config.udp_ip = "1.2.3.4"
        config.udp_port = "4444"
        with patch("src.ui_dpg.dpg.does_item_exist", return_value=False):
            self.assertEqual(app._read_udp_endpoint(), ("1.2.3.4", "4444"))

    def test_start_runtime_after_close_is_noop(self):
        app = self._use_collaborators(capture=CaptureTelemetryStub())
        app._on_close()
        with patch("src.ui_dpg.threading.Thread") as thread_cls:
            app._start_runtime()
        thread_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
