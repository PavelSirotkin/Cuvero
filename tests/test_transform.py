"""Rotation and mirroring of objects, texts, arcs and components."""

import struct
import unittest
from pathlib import Path

import core
from tests.samples import require_samples

require_samples()

ROOT = Path(__file__).resolve().parent.parent
MOTOR = ROOT / "Samples" / "motor ir2101.lay6"
HLDI = ROOT / "Samples" / "HLDI_ALL_PCB.lay6"


def component(cid=1):
    """The SOT-89 component of the sample board: pads, tracks and two labels."""
    elements = core.parse_project(MOTOR.read_bytes()).boards[0].elements
    return [obj for obj in elements if core.component_id(obj) == cid]


def arcs():
    board = core.parse_project(HLDI.read_bytes()).boards[0]
    return [
        obj
        for obj in board.elements
        if obj.kind == core.CIRCLE and obj.start != round(obj.width * core.MM)
    ]


def component_rotation(elements):
    label = next(obj for obj in elements if obj.component)
    return struct.unpack_from("<d", label.component, 9)[0]


class Transform(unittest.TestCase):
    def assertSameGeometry(self, before, after):
        for old, new in zip(before, after, strict=True):
            for name in ("x", "y", "outer", "inner", "width"):
                self.assertAlmostEqual(getattr(old, name), getattr(new, name), places=6)
            for (x0, y0), (x1, y1) in zip(old.points, new.points, strict=True):
                self.assertAlmostEqual(x0, x1, places=6)
                self.assertAlmostEqual(y0, y1, places=6)
            for name in ("start", "rotation", "mirror_x", "mirror_y", "layer", "kind", "record"):
                self.assertEqual(getattr(old, name), getattr(new, name), name)
            self.assertSameGeometry(old.children, new.children)

    def test_four_quarter_turns_restore_everything(self):
        original = component()
        turned = original
        for _ in range(4):
            turned = core.rotate_all(turned, 90)
        self.assertSameGeometry(original, turned)
        self.assertEqual(component_rotation(turned), component_rotation(original))

    def test_mirroring_twice_restores_everything(self):
        original = component()
        for axis in ("x", "y"):
            with self.subTest(axis):
                twice = core.mirror_all(core.mirror_all(original, axis), axis)
                self.assertSameGeometry(original, twice)

    def test_quarter_turn_keeps_the_centre(self):
        original = component()
        turned = core.rotate_all(original, 90)
        for a, b in zip(core.centre(original), core.centre(turned), strict=True):
            self.assertAlmostEqual(a, b, places=6)

    def test_quarter_turn_of_a_pad(self):
        board = core.parse_project(MOTOR.read_bytes()).boards[0]
        pad = core.new_smd(board, 1, 10, -10, 2.0, 1.0)
        (turned,) = core.rotate_all([pad], -90)
        xs = [x for x, _ in turned.points]
        ys = [y for _, y in turned.points]
        self.assertAlmostEqual(max(xs) - min(xs), 1.0)
        self.assertAlmostEqual(max(ys) - min(ys), 2.0)

    def test_pad_thermal_fields_are_not_changed(self):
        pads = [obj for obj in component() if obj.kind in core.PADS]
        for obj in core.mirror_all(core.rotate_all(pads, 90), "x"):
            original = next(p for p in pads if p.record == obj.record)
            self.assertEqual(
                (obj.rotation, obj.mirror_x, obj.mirror_y, obj.start),
                (original.rotation, original.mirror_x, original.mirror_y, original.start),
            )

    def test_component_and_label_angles(self):
        original = component()
        self.assertEqual(component_rotation(original), 90)
        turned = core.rotate_all(original, 90)
        self.assertEqual(component_rotation(turned), 180)
        self.assertEqual({obj.rotation for obj in turned if obj.kind == core.STROKE_TEXT}, {180})
        self.assertEqual(component_rotation(core.mirror_all(original, "x")), 90)
        self.assertEqual(component_rotation(core.mirror_all(original, "y")), 270)

    def test_arcs(self):
        sample = arcs()
        self.assertTrue(sample)
        arc = sample[0]
        self.assertEqual((arc.start, round(arc.width * core.MM)), (270000, 0))
        (turned,) = core.rotate_all([arc], 90)
        self.assertEqual((turned.start, round(turned.width * core.MM)), (0, 90000))
        (flipped,) = core.mirror_all([arc], "x")
        self.assertEqual((flipped.start, round(flipped.width * core.MM)), (180000, 270000))

    def test_transformed_board_saves(self):
        project = core.parse_project(MOTOR.read_bytes())
        board = project.boards[0]
        indices = [i for i, obj in enumerate(board.elements) if core.component_id(obj) == 1]
        moved = core.mirror_all(core.rotate_all([board.elements[i] for i in indices], 45), "y")
        for index, obj in zip(indices, moved, strict=True):
            board.elements[index] = obj
        again = core.parse_project(core.serialize(project)).boards[0].elements
        # 90 + 45 = 135 degrees, mirrored top-bottom: -135 = 225 degrees.
        self.assertEqual(component_rotation([again[i] for i in indices]), 225)


if __name__ == "__main__":
    unittest.main()
