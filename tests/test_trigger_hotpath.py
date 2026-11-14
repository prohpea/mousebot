"""Trigger hot path: mask reuse, monotonic clock, time-based confirm.

Three properties are pinned here, each one a way the "faster trigger" change
could silently change behaviour:

* cutting the shared raw mask must be byte-identical to re-thresholding the ROI
  (otherwise two threshold paths have diverged and the reuse must be dropped),
* the decision clock must be monotonic, so a wall-clock correction cannot fire
  early or hang the cooldown,
* ``trigger_confirm_ms`` must only take effect when the user sets it.
"""
import os
import sys
import time
import unittest
from unittest.mock import patch

import numpy as np
import cv2

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.utils.config import config
from src.aim_system import Triggerbot
from src.aim_system.Triggerbot import (
    process_triggerbot,
    resolve_confirm_frames,
    slice_mask_for_roi,
)


class _FakeFrame:
    def __init__(self, width, height):
        self.xres = width
        self.yres = height


class _FakeController:
    def __init__(self):
        self.presses = 0
        self.releases = 0

    def press(self):
        self.presses += 1

    def release(self):
        self.releases += 1


class _ConfigSandbox:
    # The strafe gate must be off, otherwise a config.json with
    # trigger_strafe_mode="manual_wait" would return STRAFE_WAIT before the
    # decision under test is reached.
    BASE = {"trigger_strafe_mode": "off"}

    def __init__(self, **values):
        self.values = dict(self.BASE)
        self.values.update(values)
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


def _purple_mask(image, model):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, model[0], model[1])


def _load_purple_model():
    """Load the HSV bounds for purple regardless of the user's config.json."""
    from src.utils import detection
    with _ConfigSandbox(color="purple"):
        detection.load_model()
    return detection._model


class TestMaskSlice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = _load_purple_model()
        if cls.model is None:
            raise unittest.SkipTest("HSV model unavailable")

    def setUp(self):
        self.image = np.zeros((200, 240, 3), np.uint8)
        self.image[80:120, 100:140] = (163, 69, 161)
        self.image[10:40, 10:60] = (163, 69, 161)

    def test_full_frame_mask_slice_is_byte_identical_to_inrange(self):
        full_mask = _purple_mask(self.image, self.model)
        x1, y1, x2, y2 = 90, 70, 150, 130

        sliced = slice_mask_for_roi(full_mask, None, x1, y1, x2, y2)
        recomputed = _purple_mask(self.image[y1:y2, x1:x2], self.model)

        self.assertIsNotNone(sliced)
        np.testing.assert_array_equal(sliced, recomputed)

    def test_roi_offset_mask_slice_is_byte_identical_to_inrange(self):
        roi = (60, 40, 200, 180)
        sub_image = self.image[roi[1]:roi[3], roi[0]:roi[2]]
        sub_mask = _purple_mask(sub_image, self.model)

        x1, y1, x2, y2 = 85, 70, 165, 145
        sliced = slice_mask_for_roi(sub_mask, roi, x1, y1, x2, y2)
        recomputed = _purple_mask(self.image[y1:y2, x1:x2], self.model)

        self.assertIsNotNone(sliced)
        np.testing.assert_array_equal(sliced, recomputed)

    def test_mask_that_does_not_cover_the_roi_returns_none(self):
        small_mask = np.zeros((20, 20), np.uint8)
        result = slice_mask_for_roi(small_mask, None, 0, 0, 100, 100)
        self.assertIsNone(result, "an undersized mask must force a real re-threshold")

    def test_none_mask_returns_none(self):
        self.assertIsNone(slice_mask_for_roi(None, None, 0, 0, 10, 10))


class TestProcessTriggerbotUsesSharedMask(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = _load_purple_model()
        if cls.model is None:
            raise unittest.SkipTest("HSV model unavailable")

    def setUp(self):
        self._reset_state()
        self.image = np.zeros((160, 160, 3), np.uint8)
        cv2.circle(self.image, (80, 80), 12, (163, 69, 161), -1)
        self.frame = _FakeFrame(160, 160)

    def _reset_state(self):
        Triggerbot._triggerbot_state.update({
            "burst_state": None,
            "burst_thread": None,
            "enter_range_time": None,
            "random_delay": None,
            "confirm_count": 0,
            "last_trigger_time": 0.0,
            "current_cooldown": 0.0,
            "active_trigger_type": "current",
            "activation_last_pressed": False,
            "activation_toggle_state": False,
            "deactivation_release_sent": False,
            "strafe_manual_neutral_since": None,
        })

    def _call(self, source_mask=None, source_mask_roi=None, targets=None):
        return process_triggerbot(
            self.frame, self.image, self.model, _FakeController(),
            0.0, 0.0, 40.0, 60.0, 0.0, 0.0, 1, 1, 0.0, 0.0,
            targets=targets if targets is not None else [(80.0, 80.0, 0.0, None, None)],
            source_img=self.image,
            source_mask=source_mask,
            source_mask_roi=source_mask_roi,
        )

    def test_shared_mask_does_not_change_the_detection_decision(self):
        full_mask = _purple_mask(self.image, self.model)

        with _ConfigSandbox(enabletb=True, trigger_confirm_frames=1, trigger_confirm_ms=0.0,
                            selected_tb_btn=1, selected_2_tb=2,
                            trigger_activation_type="hold_enable", tbfovsize=40,
                            trigger_min_pixels=1, trigger_min_ratio=0.0,
                            show_opencv_windows=False):
            with patch.object(Triggerbot, "_safe_binding_pressed", return_value=True):
                without = self._call()
                self._reset_state()  # reset trigger state
                with_mask = self._call(source_mask=full_mask)

        self.assertEqual(
            without.split(" ")[0], with_mask.split(" ")[0],
            f"decision changed by mask reuse: {without!r} vs {with_mask!r}",
        )
        # And the shared-mask path must not fall back to thresholding.
        self.assertNotEqual(without, "INVALID_ROI")
        self.assertNotEqual(without, "OUT_OF_FOV")
        self.assertNotEqual(without, "ERROR", without)

    def test_mask_reuse_skips_the_second_inrange(self):
        full_mask = _purple_mask(self.image, self.model)

        with _ConfigSandbox(enabletb=True, trigger_confirm_frames=1, trigger_confirm_ms=0.0,
                            selected_tb_btn=1, selected_2_tb=2,
                            trigger_activation_type="hold_enable", tbfovsize=40,
                            trigger_min_pixels=1, trigger_min_ratio=0.0,
                            show_opencv_windows=False):
            with patch.object(Triggerbot, "_safe_binding_pressed", return_value=True):
                with patch.object(cv2, "inRange", wraps=cv2.inRange) as mocked:
                    self._call(source_mask=full_mask)
                self.assertEqual(
                    mocked.call_count, 0,
                    "cv2.inRange was still called even though a mask was supplied",
                )

    def test_without_a_mask_it_still_thresholds(self):
        with _ConfigSandbox(enabletb=True, trigger_confirm_frames=1, trigger_confirm_ms=0.0,
                            selected_tb_btn=1, selected_2_tb=2,
                            trigger_activation_type="hold_enable", tbfovsize=40,
                            trigger_min_pixels=1, trigger_min_ratio=0.0,
                            show_opencv_windows=False):
            with patch.object(Triggerbot, "_safe_binding_pressed", return_value=True):
                with patch.object(cv2, "inRange", wraps=cv2.inRange) as mocked:
                    self._call(source_mask=None)
                self.assertGreaterEqual(mocked.call_count, 1)


class TestMonotonicClock(unittest.TestCase):
    """A wall-clock jump must not fire early or stall the decision path."""

    @classmethod
    def setUpClass(cls):
        cls.model = _load_purple_model()
        if cls.model is None:
            raise unittest.SkipTest("HSV model unavailable")

    def setUp(self):
        Triggerbot._triggerbot_state.update({
            "burst_state": None,
            "burst_thread": None,
            "enter_range_time": None,
            "random_delay": None,
            "confirm_count": 0,
            "last_trigger_time": 0.0,
            "current_cooldown": 0.0,
            "active_trigger_type": "current",
            "activation_last_pressed": False,
            "activation_toggle_state": False,
            "deactivation_release_sent": False,
            "strafe_manual_neutral_since": None,
        })
        self.image = np.zeros((160, 160, 3), np.uint8)
        cv2.circle(self.image, (80, 80), 12, (163, 69, 161), -1)
        self.frame = _FakeFrame(160, 160)

    def test_wall_clock_going_backwards_does_not_fire_early(self):
        """A wall-clock correction must not shorten the cooldown.

        All trigger timestamps use perf_counter, so the patch on time.time is
        only a distraction for the code under test: if any part of the decision
        path still read time.time(), the cooldown would collapse and a second
        burst would start immediately.
        """
        controller = _FakeController()
        targets = [(80.0, 80.0, 0.0, None, None)]

        with _ConfigSandbox(enabletb=True, trigger_confirm_frames=1, trigger_confirm_ms=0.0,
                            selected_tb_btn=1, selected_2_tb=2,
                            trigger_activation_type="hold_enable", tbfovsize=40,
                            trigger_min_pixels=1, trigger_min_ratio=0.0,
                            show_opencv_windows=False,
                            tbburst_count_min=1, tbburst_count_max=1,
                            tbburst_interval_min=0.0, tbburst_interval_max=0.0,
                            tbcooldown_min=1.0, tbcooldown_max=1.0):
            with patch.object(Triggerbot, "_safe_binding_pressed", return_value=True):
                first = process_triggerbot(
                    self.frame, self.image, self.model, controller,
                    0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1, 1, 0.0, 0.0,
                    targets=targets, source_img=self.image,
                )
                self.assertTrue(first.startswith("BURST_STARTED"), first)
                # Let the (single, zero-hold) burst thread finish so the next
                # call is evaluated instead of returning BURSTING.
                deadline = time.perf_counter() + 2.0
                while time.perf_counter() < deadline:
                    if Triggerbot._triggerbot_state.get("burst_state") is None:
                        break
                    time.sleep(0.005)

                # Wall clock jumps back 10 s. With time.time() this used to look
                # like "cooldown finished long ago" and fire again immediately.
                real_time = time.time
                with patch.object(time, "time", lambda: real_time() - 10.0):
                    second = process_triggerbot(
                        self.frame, self.image, self.model, controller,
                        0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1, 1, 0.0, 0.0,
                        targets=targets, source_img=self.image,
                    )

        self.assertFalse(
            second.startswith("BURST_STARTED"),
            f"trigger fired inside its cooldown after the clock jumped back: {second!r}",
        )
        self.assertTrue(
            second.startswith("COOLDOWN"),
            f"expected the cooldown to hold, got {second!r}",
        )

    def test_no_time_time_call_in_the_decision_path(self):
        targets = [(80.0, 80.0, 0.0, None, None)]
        with _ConfigSandbox(enabletb=True, trigger_confirm_frames=1, trigger_confirm_ms=0.0,
                            selected_tb_btn=1, selected_2_tb=2,
                            trigger_activation_type="hold_enable", tbfovsize=40,
                            trigger_min_pixels=1, trigger_min_ratio=0.0,
                            show_opencv_windows=False):
            with patch.object(Triggerbot, "_safe_binding_pressed", return_value=True):
                with patch.object(time, "time", side_effect=AssertionError("time.time() used")):
                    status = process_triggerbot(
                        self.frame, self.image, self.model, _FakeController(),
                        0.0, 0.0, 10.0, 10.0, 0.0, 0.0, 1, 1, 0.0, 0.0,
                        targets=targets, source_img=self.image,
                    )
        self.assertIsInstance(status, str)


class TestConfirmMs(unittest.TestCase):
    def setUp(self):
        self._saved_frames = getattr(config, "trigger_confirm_frames", 2)
        self._saved_ms = getattr(config, "trigger_confirm_ms", 0.0)

    def tearDown(self):
        config.trigger_confirm_frames = self._saved_frames
        config.trigger_confirm_ms = self._saved_ms

    def test_zero_ms_keeps_the_frame_counter(self):
        config.trigger_confirm_frames = 3
        config.trigger_confirm_ms = 0.0
        self.assertEqual(resolve_confirm_frames(1.0 / 144.0), 3)

    def test_one_frame_budget_at_144hz(self):
        config.trigger_confirm_ms = 1000.0 / 144.0
        self.assertEqual(resolve_confirm_frames(1.0 / 144.0), 1)

    def test_two_frame_budget_at_144hz(self):
        config.trigger_confirm_ms = 2 * 1000.0 / 144.0
        self.assertEqual(resolve_confirm_frames(1.0 / 144.0), 2)

    def test_confirm_ms_never_returns_zero_frames(self):
        config.trigger_confirm_ms = 0.1
        self.assertGreaterEqual(resolve_confirm_frames(1.0 / 144.0), 1)

    def test_sub_millisecond_budget_rounds_up_to_one_frame(self):
        config.trigger_confirm_ms = 2.0
        self.assertEqual(resolve_confirm_frames(1.0 / 30.0), 1)


if __name__ == "__main__":
    unittest.main()
