"""Move-queue dispatch tests (plan 7.4 / H5 / C1 / C2).

The old consumer grouped items by tag and then ADDED every group into a single
``controller.move()`` call, so a flick impulse could be summed with a tracking
step and a recoil tick. These tests pin the per-tag behaviour.
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import cv2
except Exception:
    import types
    sys.modules['cv2'] = types.ModuleType('cv2')

try:
    import ctypes
except Exception:
    import types
    from unittest.mock import MagicMock
    ctypes_mock = MagicMock()
    sys.modules['_ctypes'] = ctypes_mock
    sys.modules['ctypes'] = ctypes_mock
    sys.modules['ctypes.wintypes'] = ctypes_mock

from unittest.mock import MagicMock
sys.modules['src.capture.capture_service'] = MagicMock()
sys.modules['src.capture.ndi'] = MagicMock()
sys.modules['cyndilib'] = MagicMock()

from main import AimTracker  # noqa: E402


class FakeController:
    """Records every ``move`` call so we can assert the exact dispatch."""

    def __init__(self, reject=False):
        self.calls = []
        self.reject = reject

    def move(self, dx, dy):
        if self.reject:
            raise RuntimeError("backend refused")
        self.calls.append((dx, dy))

    def total(self):
        return (
            sum(call[0] for call in self.calls),
            sum(call[1] for call in self.calls),
        )


def make_queue():
    """An AimTracker instance with only the queue machinery initialised."""
    tracker = AimTracker.__new__(AimTracker)
    tracker.controller = FakeController()
    tracker._move_batch_size = 4
    return tracker


class TestGroupMoveItems(unittest.TestCase):
    def test_groups_preserve_first_seen_order(self):
        groups = AimTracker._group_move_items(
            [
                (1.0, 0.0, 0.0, "track"),
                (2.0, 0.0, 0.0, "flick"),
                (3.0, 0.0, 0.0, "track"),
                (4.0, 0.0, 0.0, "rcs"),
            ]
        )
        self.assertEqual(list(groups.keys()), ["track", "flick", "rcs"])
        self.assertEqual(len(groups["track"]), 2)
        self.assertEqual(len(groups["flick"]), 1)

    def test_group_items_are_float_triples(self):
        groups = AimTracker._group_move_items([("5", "6", "0.1", "track")])
        self.assertEqual(groups["track"], [(5.0, 6.0, 0.1)])

    def test_negative_delay_is_clamped(self):
        groups = AimTracker._group_move_items([(1, 1, -5.0, "track")])
        self.assertEqual(groups["track"][0][2], 0.0)


class TestNoCrossTagSum(unittest.TestCase):
    def test_flick_is_not_summed_with_track(self):
        tracker = make_queue()
        groups = AimTracker._group_move_items(
            [(100.0, 0.0, 0.0, "flick"), (7.0, 0.0, 0.0, "track")]
        )
        tracker._dispatch_groups(groups, max_batch=4)
        # Exactly two commands: the flick impulse intact, then the track step.
        self.assertEqual(tracker.controller.calls, [(100.0, 0.0), (7.0, 0.0)])

    def test_rcs_is_not_summed_with_track(self):
        tracker = make_queue()
        groups = AimTracker._group_move_items(
            [(0.0, 3.0, 0.0, "rcs"), (5.0, 0.0, 0.0, "track")]
        )
        tracker._dispatch_groups(groups, max_batch=4)
        self.assertEqual(tracker.controller.calls, [(0.0, 3.0), (5.0, 0.0)])

    def test_flick_is_dispatched_before_track(self):
        tracker = make_queue()
        # Track first in the queue, flick second: flick must still land first.
        groups = AimTracker._group_move_items(
            [(7.0, 0.0, 0.0, "track"), (100.0, 0.0, 0.0, "flick")]
        )
        tracker._dispatch_groups(groups, max_batch=4)
        self.assertEqual(tracker.controller.calls[0], (100.0, 0.0))
        self.assertEqual(tracker.controller.calls[1], (7.0, 0.0))

    def test_batch_within_tag_sums_inside_only(self):
        tracker = make_queue()
        groups = AimTracker._group_move_items(
            [(1.0, 0.0, 0.0, "track"), (2.0, 0.0, 0.0, "track"), (9.0, 0.0, 0.0, "flick")]
        )
        tracker._dispatch_groups(groups, max_batch=4)
        self.assertEqual(tracker.controller.calls, [(9.0, 0.0), (3.0, 0.0)])

    def test_max_batch_keeps_newest(self):
        tracker = make_queue()
        groups = {
            "track": [(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0)]
        }
        tracker._dispatch_groups(groups, max_batch=2)
        # Only the newest two survive: 2 + 3
        self.assertEqual(tracker.controller.calls, [(5.0, 0.0)])

    def test_flick_impulses_are_never_batched_away(self):
        tracker = make_queue()
        groups = {
            "flick": [(10.0, 0.0, 0.0), (20.0, 0.0, 0.0), (30.0, 0.0, 0.0)]
        }
        tracker._dispatch_groups(groups, max_batch=1)
        # A flick group is never truncated by max_batch; it is sent as one impulse.
        self.assertEqual(tracker.controller.calls, [(60.0, 0.0)])

    def test_pure_zero_move_is_not_sent(self):
        tracker = make_queue()
        tracker._dispatch_groups({"track": [(0.0, 0.0, 0.0)]}, max_batch=4)
        self.assertEqual(tracker.controller.calls, [])


class TestCalibrationExclusive(unittest.TestCase):
    def test_calib_is_sent_alone(self):
        tracker = make_queue()
        groups = AimTracker._group_move_items(
            [
                (0.0, 75.0, 0.0, "calib"),
                (100.0, 0.0, 0.0, "flick"),
                (7.0, 0.0, 0.0, "track"),
            ]
        )
        tracker._dispatch_groups(groups, max_batch=4)
        # Only the calibration impulse; the flick/track items are dropped.
        self.assertEqual(tracker.controller.calls, [(0.0, 75.0)])

    def test_calib_drops_non_calib_items(self):
        tracker = make_queue()
        groups = AimTracker._group_move_items(
            [
                (50.0, 0.0, 0.0, "calib"),
                (100.0, 0.0, 0.0, "flick"),
                (7.0, 0.0, 0.0, "track"),
                (1.0, 0.0, 0.0, "rcs"),
            ]
        )
        tracker._dispatch_groups(groups, max_batch=4)
        self.assertEqual(tracker.controller.calls, [(50.0, 0.0)])

    def test_calib_impulse_is_not_contaminated(self):
        """The measured impulse must be exactly what the user asked for."""
        tracker = make_queue()
        groups = AimTracker._group_move_items([(100.0, 0.0, 0.0, "calib")])
        tracker._dispatch_groups(groups, max_batch=4)
        dx, dy = tracker.controller.calls[0]
        self.assertEqual((dx, dy), (100.0, 0.0))


class TestDelayHandling(unittest.TestCase):
    def test_min_delay_is_returned(self):
        tracker = make_queue()
        groups = {
            "track": [(1.0, 0.0, 0.05)],
            "rcs": [(1.0, 0.0, 0.01)],
        }
        delay = tracker._dispatch_groups(groups, max_batch=4)
        self.assertAlmostEqual(delay, 0.01)

    def test_flick_has_no_delay(self):
        tracker = make_queue()
        groups = {"flick": [(5.0, 0.0, 0.0)]}
        self.assertEqual(tracker._dispatch_groups(groups, max_batch=4), 0.0)

    def test_empty_groups_return_zero(self):
        tracker = make_queue()
        self.assertEqual(tracker._dispatch_groups({}, max_batch=4), 0.0)
        self.assertEqual(tracker.controller.calls, [])


class TestLegacyRollbackPath(unittest.TestCase):
    def test_merge_all_tags_reproduces_old_behaviour(self):
        tracker = make_queue()
        pending = [(1.0, 0.0, 0.0, "track"), (2.0, 0.0, 0.0, "flick")]
        dx, dy, delay = tracker._merge_all_tags(pending, max_batch=4)
        # Deliberately the OLD (incorrect) cross-tag sum: this is the rollback path.
        self.assertEqual((dx, dy), (3.0, 0.0))
        self.assertEqual(delay, 0.0)

    def test_merge_all_tags_batches_inside_tag_only(self):
        tracker = make_queue()
        pending = [(float(i), 0.0, 0.0, "track") for i in range(1, 6)]
        dx, _dy, _delay = tracker._merge_all_tags(pending, max_batch=2)
        # Newest two: 4 + 5
        self.assertEqual(dx, 9.0)


class TestUnpacking(unittest.TestCase):
    def test_three_tuple_defaults_to_track(self):
        self.assertEqual(
            AimTracker._unpack_move_item((1, 2, 0.0)), (1, 2, 0.0, "track")
        )

    def test_four_tuple_preserves_tag(self):
        self.assertEqual(
            AimTracker._unpack_move_item((1, 2, 0.0, "flick")), (1, 2, 0.0, "flick")
        )

    def test_invalid_item_raises(self):
        with self.assertRaises(ValueError):
            AimTracker._unpack_move_item((1, 2))


class TestBackendFailure(unittest.TestCase):
    def test_dispatch_move_swallows_errors(self):
        tracker = make_queue()
        tracker.controller = FakeController(reject=True)
        self.assertFalse(tracker._dispatch_move(5.0, 5.0))

    def test_zero_move_is_not_sent(self):
        tracker = make_queue()
        tracker._dispatch_move(0.0, 0.0)
        self.assertEqual(tracker.controller.calls, [])


if __name__ == "__main__":
    unittest.main()
