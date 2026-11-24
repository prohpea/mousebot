import unittest

import numpy as np

from ABCurves.abcurves.smoothing import (
    SmoothingSpec,
    parse_smoothing_spec,
    smooth_dxdy,
)


class SmoothingSpecTests(unittest.TestCase):
    def test_defaults_and_window_parsing(self):
        self.assertEqual(parse_smoothing_spec(None), SmoothingSpec())
        self.assertEqual(
            parse_smoothing_spec("triangular_moving_average_path:window=7").window, 7
        )

    def test_invalid_specs_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_smoothing_spec("other_method")
        with self.assertRaises(ValueError):
            parse_smoothing_spec("triangular_moving_average_path:window=0")
        with self.assertRaises(ValueError):
            parse_smoothing_spec("triangular_moving_average_path:unknown=1")


class SmoothDxDyTests(unittest.TestCase):
    def test_empty_input_returns_zeros(self):
        result = smooth_dxdy(np.zeros((0, 2), dtype=np.float32))
        self.assertEqual(result.shape, (0, 2))

    def test_constant_velocity_is_preserved_in_interior(self):
        deltas = np.tile(np.array([[1.0, 2.0]], dtype=np.float32), (20, 1))
        result = smooth_dxdy(deltas)
        np.testing.assert_allclose(result[6:-6], deltas[6:-6], atol=1e-5)

    def test_mask_limits_valid_prefix(self):
        deltas = np.ones((6, 2), dtype=np.float32)
        mask = np.array([True, True, True, False, False, False])
        result = smooth_dxdy(deltas, mask=mask)
        np.testing.assert_array_equal(result[3:], np.zeros((3, 2), dtype=np.float32))

    def test_bad_shape_is_rejected(self):
        with self.assertRaises(ValueError):
            smooth_dxdy(np.zeros((3, 3), dtype=np.float32))


if __name__ == "__main__":
    unittest.main()
