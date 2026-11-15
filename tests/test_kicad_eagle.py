"""Stage 9: KiCad (.kicad_pcb) and Eagle (.brd) boards opened as new projects."""

import unittest
from collections import Counter
from math import isclose

import core
from core import eagle, kicad, sexpr
from core.foreign import Builder, arc_through
from tests.ui_base import ROOT, WindowTestCase
from ui.importers import board_from_conversion

KICAD = ROOT / "Samples" / "KiCAD"
EAGLE = ROOT / "Samples" / "Eagle"
K555 = KICAD / "555.kicad_pcb"
COUNTER = KICAD / "Counter.kicad_pcb"
SLICE = EAGLE / "R016 - Slice of Radio v1.1.brd"


def qt():
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])


class Sexpr(unittest.TestCase):
    def test_parse(self):
        tree = sexpr.parse('(a 1 "two words" (b 2.5 -3) (c "x\\"y") hide)')
        self.assertEqual(sexpr.name(tree), "a")
        self.assertEqual(sexpr.numbers(sexpr.child(tree, "b"), 2), [2.5, -3.0])
        self.assertEqual(sexpr.words(sexpr.child(tree, "c")), ['x"y'])
        self.assertIsInstance(tree[2], sexpr.Quoted)
        self.assertIn("hide", sexpr.words(tree))

    def test_errors(self):
        with self.assertRaises(sexpr.SexprError):
            sexpr.parse("(a (b 1)")
        with self.assertRaises(kicad.KicadError):
            kicad.convert("(not_a_board)")
        with self.assertRaises(eagle.EagleError):
            eagle.convert(b"<eagle><drawing><schematic/></drawing></eagle>")
        with self.assertRaises(eagle.EagleError):
            eagle.convert(b"\x10\x80binary old eagle")


class Geometry(unittest.TestCase):
    def test_arc_through_three_points(self):
        (cx, cy), r, a0, a1 = arc_through((1, 0), (0, 1), (-1, 0))
        self.assertTrue(isclose(cx, 0, abs_tol=1e-9) and isclose(cy, 0, abs_tol=1e-9))
        self.assertAlmostEqual(r, 1)
        self.assertEqual((round(a0), round(a1)), (0, 180))
        # The same points the other way round: still the upper half.
        _, _, a0, a1 = arc_through((-1, 0), (0, 1), (1, 0))
        self.assertEqual((round(a0), round(a1)), (0, 180))

    def test_eagle_curve(self):
        (cx, cy), r, a0, a1 = eagle._arc((1, 0), (-1, 0), 180)
        self.assertAlmostEqual(r, 1)
        self.assertAlmostEqual(cy, 0, places=9)
        self.assertEqual((round(a0) % 360, round(a1) % 360), (0, 180))

    def test_eagle_mirrored_part(self):
        place = eagle._Place(10, 20, eagle._Rotation.parse("MR90"))
        self.assertEqual(place(1, 0), (10, 19))  # mirrored to (-1, 0), turned to (0, -1)
        self.assertEqual(place.layer("1"), "16")
        self.assertEqual(place.layer("21"), "22")

    def test_text_justification(self):
        b = Builder("t")
        b.text(2, 10, 10, "ABC", 1.05, 0, False, (0.5, 0.5))
        b.text(2, 10, 10, "ABC", 1.05, 0, False, (0.0, 0.0))
        conversion = b.finish(0)
        centred, plain = conversion.text.splitlines()[:2]
        cx = int(centred.split("POS=")[1].split("/")[0])
        px = int(plain.split("POS=")[1].split("/")[0])
        self.assertLess(cx, px)  # centred text starts left of its anchor


@unittest.skipUnless(K555.exists(), "no KiCad sample")
class Kicad(unittest.TestCase):
    def test_555(self):
        qt()
        conversion = kicad.convert_file(K555)
        board, wires = board_from_conversion(conversion)
        kinds = Counter(obj.kind for obj in board.elements)
        self.assertEqual(kinds[core.THT], 29)  # every through-hole pad, no vias
        self.assertGreater(kinds[core.LINE], 20)
        self.assertTrue(any(obj.layer == 7 for obj in board.elements))
        names = {info.name for info in core.components_of(board)}
        self.assertTrue({"U1", "R1", "C1", "Q1"} <= names)
        self.assertEqual(wires, 0)  # a routed board

    @unittest.skipUnless(COUNTER.exists(), "no KiCad sample")
    def test_bottom_side_parts(self):
        qt()
        board, _ = board_from_conversion(kicad.convert_file(COUNTER))
        bottom = [obj for obj in board.elements if obj.kind == core.SMD and obj.layer == 3]
        self.assertGreater(len(bottom), 50)
        data = core.serialize(core.new_project(board))
        self.assertEqual(len(core.parse_project(data).boards[0].elements), len(board.elements))


@unittest.skipUnless(SLICE.exists(), "no Eagle sample")
class Eagle(unittest.TestCase):
    def test_ground_planes(self):
        qt()
        conversion = eagle.convert_file(SLICE)
        self.assertEqual(set(conversion.planes), {1, 3})
        board, wires = board_from_conversion(conversion)
        self.assertTrue(core.has_plane(board, 1) and core.has_plane(board, 3))
        thermal = [
            obj
            for obj in board.elements
            if obj.kind in (core.THT, core.SMD) and core.thermal_directions(obj)
        ]
        self.assertTrue(thermal)  # GND pads are tied to the plane
        self.assertEqual(wires, 0)
        names = {info.name for info in core.components_of(board)}
        self.assertIn("R1", names)
        outline = [obj for obj in board.elements if obj.layer == 7]
        self.assertTrue(outline)
        self.assertTrue(all(obj.width <= 0.11 for obj in outline if obj.kind == core.LINE))

    def test_all_samples_convert(self):
        qt()
        for path in sorted(EAGLE.glob("*.brd")):
            with self.subTest(path.name):
                board, _ = board_from_conversion(eagle.convert_file(path))
                self.assertGreater(len(board.elements), 100)


@unittest.skipUnless(K555.exists() and SLICE.exists(), "no samples")
class Opening(WindowTestCase):
    def test_open_kicad_and_eagle(self):
        w = self.window
        for path in (K555, SLICE):
            with self.subTest(path.name):
                self.assertTrue(w.open_path(path))
                w.import_report.close()
                self.assertIsNone(w.path)
                self.assertIn("импорт", w.windowTitle())
                w.recovered = False


GERBERS = KICAD / "gerber"


def _bounds(g):
    xs = [x for p in g.primitives for x, _ in p.points]
    ys = [y for p in g.primitives for _, y in p.points]
    return min(xs), min(ys), max(xs), max(ys)


@unittest.skipUnless(GERBERS.exists(), "no Gerber output of KiCad (kicad-cli)")
class AgainstKicadGerber(unittest.TestCase):
    """Our Gerber of each converted board against the Gerber kicad-cli wrote for it."""

    def test_copper(self):
        qt()
        from core import gerber, gerber_read
        from tests.gerber_image import render

        for folder in sorted(p for p in GERBERS.iterdir() if p.is_dir()):
            source = KICAD / f"{folder.name}.kicad_pcb"
            if not source.exists():
                continue
            board, _ = board_from_conversion(kicad.convert_file(source))

            def layer(suffix, folder=folder):
                path = next(p for p in folder.iterdir() if p.stem.endswith("-" + suffix))
                return gerber_read.parse(path.read_text())

            tb = _bounds(layer("Edge_Cuts"))
            ob = _bounds(gerber_read.parse(gerber.layer_gerber(board, "outline")))
            dx, dy = ob[0] - tb[0], ob[1] - tb[1]
            area = (tb[0] - 1, tb[1] - 1, tb[2] - tb[0] + 2, tb[3] - tb[1] + 2)
            for ending, suffix in (("copper_top", "F_Cu"), ("copper_bottom", "B_Cu")):
                with self.subTest(board=folder.name, layer=ending):
                    a = render(layer(suffix), *area, 8)
                    ours = gerber_read.parse(gerber.layer_gerber(board, ending))
                    b = render(ours, area[0] + dx, area[1] + dy, area[2], area[3], 8)
                    da, db = bytes(a.constBits()), bytes(b.constBits())
                    dark = sum(1 for p in da if p > 127)
                    only_theirs = sum(1 for p, q in zip(da, db, strict=True) if p > 127 >= q)
                    only_ours = sum(1 for p, q in zip(da, db, strict=True) if q > 127 >= p)
                    self.assertLess(only_theirs / dark, 0.01)
                    self.assertLess(only_ours / dark, 0.01)


class TextLines(unittest.TestCase):
    def test_trailing_newline_is_no_line(self):
        text = (
            '(kicad_pcb (gr_line (start 0 0) (end 10 0) (layer "Edge.Cuts") (width 0.1))'
            ' (gr_text "WAKE\n" (at 5 5) (layer "F.SilkS")'
            " (effects (font (size 2 2) (thickness 0.3)) (justify left bottom))))"
        )
        conversion = kicad.convert(text)
        texts = [line for line in conversion.text.splitlines() if line.startswith("TEXT")]
        self.assertEqual(len(texts), 1)
