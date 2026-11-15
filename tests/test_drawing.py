"""Stage 4 core: stroke font and texts, drawn shapes, bends, snapping, rubber band, components."""

import unittest
from math import hypot
from pathlib import Path

import core
from core import font
from tests.samples import require_samples

require_samples()

ROOT = Path(__file__).resolve().parent.parent
HLDI = ROOT / "Samples" / "HLDI_ALL_PCB.lay6"


def blank():
    return core.board_from_dialog("Пустая", "empty", 80, 60)


def reread(board):
    return core.parse_project(core.serialize(core.new_project(board))).boards[0]


def extent(obj):
    xs = [x - obj.x for child in obj.children for x, _ in child.points]
    ys = [y - obj.y for child in obj.children for _, y in child.points]
    return min(xs), max(xs), min(ys), max(ys)


class Font(unittest.TestCase):
    def test_latin_digits_and_cyrillic(self):
        for char in "AZaz09-+.,ЖжЁёЯяЩщЪъ№µΩ°":
            with self.subTest(char=char):
                self.assertTrue(font.supported(char))
                self.assertTrue(font.glyph(char)[2])

    def test_unknown_characters_are_reported(self):
        self.assertEqual(core.unsupported_characters("R1 Ä€"), "Ä€")


class Texts(unittest.TestCase):
    def test_strokes_match_the_original_layout(self):
        # Texts saved by the original: our strokes take the same direction, height and
        # stroke width, and nearly the same length.
        board = core.parse_project(HLDI.read_bytes()).boards[0]
        checked = 0
        for obj in board.elements:
            if obj.kind != core.STROKE_TEXT or not obj.text or obj.shape:
                continue
            ours = core.with_strokes(obj)
            for theirs_value, ours_value in zip(extent(obj), extent(ours), strict=True):
                if abs(theirs_value) <= obj.outer * 1.2:
                    # Across the text: the height and baseline must agree.
                    self.assertAlmostEqual(ours_value, theirs_value, delta=obj.outer * 0.6)
                else:
                    # Along the text: same direction; letter widths differ between fonts.
                    self.assertGreater(ours_value * theirs_value, 0)
                    self.assertAlmostEqual(ours_value, theirs_value, delta=abs(theirs_value) * 0.4)
            self.assertAlmostEqual(ours.children[0].width, obj.children[0].width, places=3)
            checked += 1
        self.assertGreater(checked, 10)

    def test_new_text_round_trip(self):
        board = blank()
        text = core.new_text(board, 2, 10, -10, "Плата 1", 2.0, core.BOLD, 2, 90, True)
        board.elements.append(text)
        again = reread(board).elements[-1]
        self.assertEqual(again.text, "Плата 1")
        self.assertEqual((again.outer, again.rotation), (2.0, 90))
        self.assertEqual((core.text_weight(again), core.text_spacing(again)), (core.BOLD, 2))
        self.assertTrue(again.mirror_x)
        self.assertEqual(len(again.children), len(text.children))
        self.assertAlmostEqual(again.children[0].width, 2.0 / 6.3, places=4)

    def test_cap_height_and_baseline(self):
        text = core.new_text(blank(), 2, 0, 0, "HE", 1.8)
        _, _, low, high = extent(text)
        self.assertAlmostEqual(low, 0)
        self.assertAlmostEqual(high, 1.6)  # 8/9 of the height, as the original

    def test_editing_rebuilds_strokes(self):
        text = core.new_text(blank(), 2, 0, 0, "A")
        longer = core.with_text(text, text="AAAA", height=3.0)
        self.assertGreater(extent(longer)[1], extent(text)[1] * 4)
        empty = core.with_text(text, text="")
        self.assertEqual(len(empty.children), 1)  # the original's tiny rectangle

    def test_numbering(self):
        self.assertEqual(core.numbered("R", 12), "R12")


class Shapes(unittest.TestCase):
    def test_circle(self):
        circle = core.new_circle(blank(), 1, 5, -5, 4.0, 0.4)
        self.assertAlmostEqual(core.circle_diameter(circle), 4.0)
        self.assertAlmostEqual(core.circle_line_width(circle), 0.4)
        self.assertEqual(core.circle_angles(circle), (0, 0))

    def test_rectangle_outline_and_fill(self):
        board = blank()
        outline = core.new_rectangle(board, 1, (0, 0), (10, -5), 0.3, False)
        self.assertEqual(outline.kind, core.LINE)
        self.assertEqual(outline.points[0], outline.points[-1])
        self.assertEqual(len(outline.points), 5)
        filled = core.new_rectangle(board, 1, (0, 0), (10, -5), 0.3, True)
        self.assertEqual(filled.kind, core.POLYGON)
        board.elements += [outline, filled]
        again = reread(board)
        self.assertEqual(again.elements[-1].points, filled.points)

    def test_regular_polygon_and_rays(self):
        corners = core.regular_polygon(0, 0, 10, 6)
        self.assertEqual(len(corners), 6)
        for x, y in corners:
            self.assertAlmostEqual(hypot(x, y), 10, places=4)
        rays = core.new_rays(blank(), 1, 0, 0, 10, 8, 0, 0.3)
        self.assertEqual(len(rays), 8)

    def test_spiral(self):
        points = core.spiral_points(0, 0, 2, 2, 6, False)
        self.assertAlmostEqual(hypot(*points[-1]), 2 + 2 * 6, places=4)
        square = core.spiral_points(0, 0, 2, 2, 6, True)
        self.assertEqual(len(square), 25)
        self.assertAlmostEqual(core.spiral_diameter(2, 2, 6, 0.4), 28.4)

    def test_frame(self):
        parts = core.new_frame(blank(), 7, 0, -60, 90, 50, 8, 4)
        labels = sorted(obj.text for obj in parts if obj.kind == core.STROKE_TEXT)
        self.assertEqual(labels.count("A"), 2)
        self.assertEqual(labels.count("4"), 2)


class Bends(unittest.TestCase):
    def test_modes(self):
        self.assertEqual(core.bend((0, 0), (10, 4), core.FREE), [(10, 4)])
        self.assertEqual(core.bend((0, 0), (10, 4), core.BEND_90), [(10, 0), (10, 4)])
        self.assertEqual(core.bend((0, 0), (10, 4), core.BEND_45), [(6, 0), (10, 4)])
        self.assertEqual(core.bend((0, 0), (3, 3), core.BEND_45), [(3, 3)])


class SnapAndRubber(unittest.TestCase):
    def test_snap_to_pad_centre(self):
        board = blank()
        board.elements.append(core.new_pad(board, 1, 5, -5, 1.6, 0.8))
        found = core.nearest(core.snap_points(board), 5.2, -5.1, 0.5)
        self.assertEqual(found, (5, -5))
        self.assertIsNone(core.nearest(core.snap_points(board), 7, -5, 0.5))

    def test_tracks_follow_moved_pads(self):
        board = blank()
        board.elements.append(core.new_pad(board, 1, 5, -5, 1.6, 0.8))
        board.elements.append(core.new_track(board, 1, [(5, -5), (10, -5)], 0.4))
        moved = {0: core.transformed(board.elements[0], 2, 1)}
        followed = core.rubber_band(board, moved)
        self.assertEqual(followed[1].points, [(7, -4), (10, -5)])


class Components(unittest.TestCase):
    def test_labels_details_and_dissolving(self):
        board = blank()
        pads = [core.new_pad(board, 1, x, -5, 1.6, 0.8) for x in (0, 2.54)]
        parts = core.make_component(board, pads, "R0207", "top")
        board.elements.extend(parts)
        cid = core.component_id(parts[0])
        ref, value = core.component_labels(board.elements, cid)
        assert ref is not None and value is not None
        label = core.with_text(board.elements[ref], text="R7")
        label = core.with_component_details(label, "R0207", "1 %")
        board.elements[ref] = label
        again = reread(board)
        self.assertEqual(again.elements[ref].text, "R7")
        self.assertEqual(core.component_package(again.elements, cid), "R0207")
        self.assertEqual(core.component_comment(again.elements[ref]), "1 %")
        changed, labels = core.dissolved(again.elements, cid)
        self.assertEqual(sorted(labels), sorted([ref, value]))
        self.assertTrue(all(core.component_id(obj) == 0 for obj in changed.values()))


if __name__ == "__main__":
    unittest.main()
