import unittest

from src.aim_system.Bezier import (
    BezierMovement,
    calculate_bezier_movement_deltas,
    calculate_bezier_point,
    generate_bezier_points,
)


class BezierPointTests(unittest.TestCase):
    def test_endpoints_are_control_endpoints(self):
        p0, p1, p2, p3 = (1.0, 2.0), (3.0, 4.0), (5.0, 6.0), (7.0, 8.0)
        self.assertEqual(calculate_bezier_point(0.0, p0, p1, p2, p3), p0)
        self.assertEqual(calculate_bezier_point(1.0, p0, p1, p2, p3), p3)

    def test_midpoint_matches_symmetric_curve(self):
        point = calculate_bezier_point(0.5, (0, 0), (0, 0), (10, 10), (10, 10))
        self.assertAlmostEqual(point[0], 5.0)
        self.assertAlmostEqual(point[1], 5.0)


class BezierPathTests(unittest.TestCase):
    def test_non_positive_segments_returns_destination(self):
        self.assertEqual(generate_bezier_points(0, 0, 10, 20, 1, 1, 0), [(10, 20)])
        self.assertEqual(
            calculate_bezier_movement_deltas(10, 20, 1, 1, -1), [(10, 20)]
        )

    def test_generated_path_starts_and_ends_on_target(self):
        points = generate_bezier_points(1, 2, 11, 22, 3, -4, 6)
        self.assertEqual(len(points), 7)
        self.assertEqual(points[0], (1.0, 2.0))
        self.assertEqual(points[-1], (11.0, 22.0))

    def test_deltas_sum_to_requested_movement(self):
        deltas = calculate_bezier_movement_deltas(100, -40, 10, -5, 8)
        self.assertAlmostEqual(sum(dx for dx, _ in deltas), 100.0)
        self.assertAlmostEqual(sum(dy for _, dy in deltas), -40.0)


class BezierMovementTests(unittest.TestCase):
    def test_command_uses_truncated_integer_arguments(self):
        movement = BezierMovement(segments=8, ctrl_x=16.5, ctrl_y=2.0)
        self.assertEqual(
            movement.generate_movement_command(10.9, -4.2), "km.move(10,-4,8,16,2)"
        )

    def test_negative_segments_are_clamped(self):
        movement = BezierMovement(segments=4)
        movement.update_parameters(segments=-5)
        self.assertEqual(movement.segments, 0)


if __name__ == "__main__":
    unittest.main()
