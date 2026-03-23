import unittest

from logic import (
    GRID_CELLS,
    PointHistory,
    compute_step,
    grid_to_screen,
    screen_to_grid,
    validate_coord,
)


class LogicTests(unittest.TestCase):
    def test_compute_step_has_minimum(self):
        step = compute_step(120, 120, GRID_CELLS, min_px=30)
        self.assertGreaterEqual(step, 30)

    def test_grid_screen_round_trip(self):
        cx, cy, step = 300, 200, 40
        gx, gy = -4, 6
        sx, sy = grid_to_screen(gx, gy, cx, cy, step)
        rx, ry = screen_to_grid(sx, sy, cx, cy, step, GRID_CELLS)
        self.assertEqual((rx, ry), (gx, gy))

    def test_validate_coord_range(self):
        ok, _ = validate_coord(3, -2, GRID_CELLS)
        self.assertTrue(ok)
        ok2, _ = validate_coord(GRID_CELLS + 1, 0, GRID_CELLS)
        self.assertFalse(ok2)

    def test_point_history(self):
        h = PointHistory()
        h.add(1, 2)
        h.add(3, 4)
        self.assertEqual(h.as_list(), [(1, 2), (3, 4)])
        h.undo()
        self.assertEqual(h.as_list(), [(1, 2)])
        h.clear()
        self.assertEqual(h.as_list(), [])


if __name__ == "__main__":
    unittest.main()
