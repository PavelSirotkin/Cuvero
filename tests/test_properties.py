"""Object properties: origin, positions, pad sizes, tracks, arcs and polygons."""

import unittest
from pathlib import Path

import core
from tests.samples import require_samples

require_samples()

ROOT = Path(__file__).resolve().parent.parent
MOTOR = ROOT / "Samples" / "motor ir2101.lay6"
HLDI = ROOT / "Samples" / "HLDI_ALL_PCB.lay6"
# A board saved by the full original program with thermal reliefs (outside the repository).
THERMAL = Path("D:/My/ZProgs/Sprint-Layout/comp156_Plata-TDA1524A.lay6")


def motor():
    return core.parse_project(MOTOR.read_bytes())


def reread(project):
    return core.parse_project(core.serialize(project))


class Origin(unittest.TestCase):
    def test_displayed_coordinates_match_the_original(self):
        # The original program shows this pad at X 27.130, Y 97.440 with 1.00 / 0.50 mm.
        board = motor().boards[0]
        pad = next(e for e in board.elements if e.kind == core.THT and abs(e.x - 27.13) < 0.01)
        (x, y), (ox, oy) = core.centre_of(pad), core.board_origin(board)
        self.assertAlmostEqual(x - ox, 27.13, places=3)
        self.assertAlmostEqual(y - oy, 97.44, places=3)

    def test_origin_round_trip(self):
        project = motor()
        project.boards[0] = core.with_origin(project.boards[0], 5.5, -24.5)
        self.assertEqual(core.board_origin(reread(project).boards[0]), (5.5, -24.5))


class Pads(unittest.TestCase):
    def test_move_pad_and_smd_to_a_point(self):
        board = motor().boards[0]
        pad = core.new_pad(board, 1, 3, -3, 1.6, 0.8)
        self.assertEqual(core.centre_of(core.moved_to(pad, 10, -7)), (10, -7))
        smd = core.new_smd(board, 1, 3, -3, 1.0, 2.0)
        x, y = core.centre_of(core.moved_to(smd, 10, -7))
        self.assertAlmostEqual(x, 10)
        self.assertAlmostEqual(y, -7)

    def test_pad_size_keeps_orientation(self):
        board = motor().boards[0]
        (pad,) = core.rotate_all([core.new_pad(board, 1, 0, 0, 2.0, 0.8, shape=4)], 30)
        bigger = core.with_pad_size(pad, 3.0, 1.0)
        self.assertAlmostEqual(bigger.outer, 1.5)
        self.assertAlmostEqual(bigger.inner, 0.5)
        (x0, y0), (x1, y1) = bigger.points
        self.assertAlmostEqual(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5, 3.0)

    def test_smd_size_and_angle(self):
        board = motor().boards[0]
        (smd,) = core.rotate_all([core.new_smd(board, 1, 0, 0, 2.0, 1.0)], 30)
        width, height = core.smd_size(smd)
        self.assertAlmostEqual(width, 2.0)
        self.assertAlmostEqual(height, 1.0)
        self.assertAlmostEqual(core.smd_angle(smd), 30)


class Tracks(unittest.TestCase):
    def test_length(self):
        track = core.new_track(motor().boards[0], 1, [(0, 0), (3, 0), (3, 4)], 0.4)
        self.assertAlmostEqual(core.track_length(track), 7)

    def test_current_matches_the_original(self):
        # Values the original program shows for 35 um copper and 20 degrees.
        for width, shown in ((0.2, 0.667), (0.5, 1.59), (1.0, 3.13), (2.0, 6.2)):
            with self.subTest(width=width):
                self.assertAlmostEqual(core.track_current(width), shown, delta=shown * 0.005)


class Circles(unittest.TestCase):
    def test_board_outline_circle(self):
        board = core.parse_project(HLDI.read_bytes()).boards[3]
        circle = next(e for e in board.elements if e.kind == core.CIRCLE and e.layer == 7)
        self.assertAlmostEqual(core.circle_diameter(circle), 27.94, places=4)
        self.assertAlmostEqual(core.circle_line_width(circle), 0.1, places=4)
        self.assertEqual(core.circle_angles(circle), (0, 0))

    def test_arc_angles_and_round_trip(self):
        project = core.parse_project(HLDI.read_bytes())
        board = project.boards[0]
        index = next(
            i
            for i, e in enumerate(board.elements)
            if e.kind == core.CIRCLE and e.start != round(e.width * core.MM)
        )
        self.assertEqual(core.circle_angles(board.elements[index]), (270, 0))
        board.elements[index] = core.with_circle(board.elements[index], 5, 0.3, 45, 135, False)
        again = reread(project).boards[0].elements[index]
        self.assertEqual(core.circle_angles(again), (45, 135))
        self.assertAlmostEqual(core.circle_diameter(again), 5, places=4)
        self.assertAlmostEqual(core.circle_line_width(again), 0.3, places=4)


class Polygons(unittest.TestCase):
    def test_hatching_flag(self):
        project = core.parse_project(HLDI.read_bytes())
        board = project.boards[0]
        index = next(i for i, e in enumerate(board.elements) if e.kind == core.POLYGON)
        self.assertFalse(core.is_hatched(board.elements[index]))
        board.elements[index] = core.with_hatching(board.elements[index], True)
        self.assertTrue(core.is_hatched(reread(project).boards[0].elements[index]))
        pad = core.new_pad(board, 1, 0, 0, 1.6, 0.8)
        self.assertIs(core.with_hatching(pad, True), pad)


class Thermal(unittest.TestCase):
    def test_new_pads_carry_the_original_defaults(self):
        board = core.board_from_dialog("Пустая", "empty", 50, 40)
        pad = core.new_pad(board, 1, 5, -5, 1.8, 0.8)
        self.assertEqual(pad.record[62:66], core.THERMAL_MARKER)
        self.assertEqual(pad.start, 0x55555555)
        self.assertEqual(pad.rotation, 100)
        self.assertEqual(core.new_smd(board, 1, 5, -5, 1, 2).start, 0x55)

    def test_switching_on_and_off(self):
        board = core.board_from_dialog("Пустая", "empty", 50, 40)
        pad = core.new_pad(board, 1, 5, -5, 1.8, 0.8)
        on = core.with_thermal(pad, True)
        self.assertTrue(core.has_thermal(on))
        self.assertAlmostEqual(on.width, 0.6)  # a third of the diameter, as the original
        self.assertEqual(core.thermal_directions(on), 0x55)
        bigger = core.with_pad_size(on, 3.0, 1.0)
        self.assertAlmostEqual(bigger.width, 1.0)
        fewer = core.with_thermal(on, True, 0x51)
        self.assertEqual(fewer.start & 0xFFFFFFFF, 0x51515151)
        self.assertFalse(core.has_thermal(core.with_thermal(fewer, False)))

    def test_spoke_width_percentage(self):
        board = core.board_from_dialog("Пустая", "empty", 50, 40)
        pad = core.with_thermal(core.new_pad(board, 1, 5, -5, 1.0, 0.5), True)
        self.assertEqual(core.thermal_percent(pad), 100)
        wide = core.with_thermal_percent(pad, 200)  # the original shows 0.67 mm here
        self.assertAlmostEqual(wide.width, 2 / 3)
        self.assertEqual(core.with_thermal_percent(pad, 1000).rotation, 300)
        self.assertEqual(core.with_thermal_percent(pad, 10).rotation, 50)
        smd = core.with_thermal(core.new_smd(board, 1, 5, -5, 1.5, 3.0), True)
        self.assertAlmostEqual(smd.width, 0.5)  # a third of the shorter side

    def test_directions_per_layer(self):
        board = core.board_from_dialog("Пустая", "empty", 50, 40)
        pad = core.with_thermal(core.new_pad(board, 1, 5, -5, 1.0, 0.5), True)
        only_c2 = core.with_thermal(pad, True, 0x05, layer_index=1)
        self.assertEqual(only_c2.start & 0xFFFFFFFF, 0x55550555)
        self.assertFalse(core.thermal_layers_equal(only_c2))
        self.assertEqual(core.thermal_layer_directions(only_c2, 1), 0x05)

    def test_spoke_directions_follow_the_pad(self):
        board = core.board_from_dialog("Пустая", "empty", 50, 40)
        pad = core.new_pad(board, 1, 0, 0, 1.8, 0.8)  # points run left to right
        self.assertEqual([core.spoke_angle(pad, bit) for bit in (0, 2, 4, 6)], [90, 0, 270, 180])
        (turned,) = core.rotate_all([pad], 90)
        self.assertAlmostEqual(core.spoke_angle(turned, 2), 90)

    @unittest.skipUnless(THERMAL.exists(), "no board from the full original program")
    def test_board_saved_by_the_original(self):
        board = core.parse_project(THERMAL.read_bytes()).boards[0]
        pads = [e for e in board.elements if core.has_thermal(e)]
        self.assertEqual(len(pads), 16)
        for pad in pads:
            self.assertAlmostEqual(pad.width, core.thermal_width(pad), places=4)
            self.assertEqual(pad.record[62:66], core.THERMAL_MARKER)
        odd = next(p for p in pads if core.thermal_directions(p) == 0x51)
        # The original draws this pad without its left spoke: bit 2 points left.
        self.assertAlmostEqual(core.spoke_angle(odd, 2), 180)


if __name__ == "__main__":
    unittest.main()
