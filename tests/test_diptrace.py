"""Stage 9: DipTrace boards (.dip, binary) opened as new projects."""

import unittest
from collections import Counter
from pathlib import Path

import core
from core import diptrace
from tests.ui_base import ROOT
from ui.importers import board_from_conversion

DIPTRACE = ROOT / "Samples" / "DipTrace"
CARRIAGE = DIPTRACE / "LPP_Carriage_Module_Gen_1 Ver_2.dip"
MAINBOARD = DIPTRACE / "LPP_MainBoard_Gen_1_Ver_5.dip"
GERBERS = DIPTRACE / "gerber"


def qt():
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])


class Fields(unittest.TestCase):
    def test_read(self):
        data = (
            (0x3B9ACA00 + 30000).to_bytes(4, "big")
            + (1_000_000 - 1).to_bytes(3, "big")
            + b"\x00\x02\x00A\x04\x12"
            + b"\x01"
            + b"\x00\x00"
        )
        got = diptrace.read(data, 0, "Lisbs")
        assert got is not None
        values, end = got
        self.assertEqual(values, [30000, -1, "AВ", 1, ""])
        self.assertEqual(end, len(data))
        self.assertIsNone(diptrace.read(data, 0, "i"))

    def test_not_a_board(self):
        with self.assertRaises(diptrace.DipTraceError):
            diptrace.convert(b"PK\x03\x04")


@unittest.skipUnless(CARRIAGE.exists(), "no DipTrace sample")
class Carriage(unittest.TestCase):
    def test_outline_and_parts(self):
        data = CARRIAGE.read_bytes()
        outline = diptrace.read_outline(data)
        self.assertEqual(
            [(round(x), round(y)) for x, y in outline], [(0, -30), (70, -30), (70, 0), (0, 0)]
        )
        parts = {p.reference: p for p in diptrace.read_parts(data)}
        self.assertEqual(len(parts), 15)  # as many as DipTrace's own ASCII export lists
        r1 = parts["R1"]
        self.assertEqual((r1.quarter_turns, r1.bottom), (11, True))  # 5.5π in the export
        self.assertAlmostEqual(r1.x, 60.295, places=3)
        self.assertEqual(len(parts["C3"].pads), 2)

    def test_board(self):
        qt()
        board, _ = board_from_conversion(diptrace.convert_file(CARRIAGE))
        kinds = Counter(obj.kind for obj in board.elements)
        self.assertGreater(kinds[core.LINE], 30)
        self.assertGreater(kinds[core.THT], 20)
        names = {info.name for info in core.components_of(board)}
        self.assertTrue({"C3", "D1", "R1", "Q1"} <= names)

    def test_nets_texts_and_shapes(self):
        data = CARRIAGE.read_bytes()
        nets = diptrace.read_nets(data)
        self.assertEqual(len(nets), 17)  # as in the ASCII export
        self.assertEqual(nets[6], "Сеть 12")  # pads refer to the net number
        board_shapes = diptrace.read_board_shapes(data)
        (text,) = [shape for shape in board_shapes if shape.kind == 6]
        self.assertEqual(
            (text.text, text.place, text.layer, text.size),
            ("LPP Carriage Module Gen 1 Ver 2", 3, 1, 5),
        )
        self.assertEqual([(round(x, 2), round(y, 2)) for x, y in text.points], [(27.35, -3.0)])
        q1 = next(p for p in diptrace.read_parts(data) if p.reference == "Q1")
        kinds = Counter(shape.kind for shape in q1.shapes if shape.layer == 0)
        self.assertEqual(kinds[8], 2)  # body drawn as two polylines
        self.assertIn("Q1", [shape.text for shape in q1.shapes if shape.kind == 7])

    def test_converted_texts(self):
        conversion = diptrace.convert_file(CARRIAGE)
        self.assertIn("LPP Carriage Module Gen 1 Ver 2", conversion.text)
        self.assertIn("Сеть 12", conversion.nets)


@unittest.skipUnless(MAINBOARD.exists(), "no DipTrace sample")
class MainBoard(unittest.TestCase):
    def test_parts_and_pours(self):
        data = MAINBOARD.read_bytes()
        self.assertEqual(len(diptrace.read_parts(data)), 143)
        pours = diptrace.read_pours(data)
        self.assertEqual(sorted(p.layer for p in pours), [0, 1])
        # Thermal spokes, as many as DipTrace's ASCII export lists for each pour
        self.assertEqual(sorted(len(p.spokes) for p in pours), [43, 49])
        self.assertEqual(len(diptrace.read_nets(data)), 45)

    def test_bottom_part_mirrors_top_to_bottom(self):
        # U3 is on the bottom side turned by 180°: DipTrace puts its heat tab (pattern
        # x -4.16 mm) to the right of the part, and its pins to the left.
        u3 = next(p for p in diptrace.read_parts(MAINBOARD.read_bytes()) if p.reference == "U3")
        tab = max(u3.pads, key=lambda pad: pad.width * pad.height)
        pins = [pad for pad in u3.pads if pad is not tab and pad.width > 0]
        self.assertGreater(diptrace.pad_position(u3, tab)[0], u3.x + 3)
        self.assertTrue(all(diptrace.pad_position(u3, pin)[0] < u3.x - 4 for pin in pins))


def _bounds(g):
    xs = [x for p in g.primitives for x, _ in p.points]
    ys = [y for p in g.primitives for _, y in p.points]
    return min(xs), min(ys), max(xs), max(ys)


@unittest.skipUnless(GERBERS.exists(), "no Gerber output of DipTrace")
class AgainstDipTraceGerber(unittest.TestCase):
    """Our Gerber of each converted board against the Gerber DipTrace wrote for it."""

    def test_copper(self):
        qt()
        from core import gerber, gerber_read
        from tests.gerber_image import render

        for folder in sorted(p for p in GERBERS.iterdir() if p.is_dir()):
            source = next(DIPTRACE.glob(f"{folder.name}*.dip"), None)
            if source is None:
                continue
            board, _ = board_from_conversion(diptrace.convert_file(source))

            def layer(name, folder=folder):
                return gerber_read.parse((folder / f"{name}.gbr").read_text(encoding="cp1251"))

            tb = _bounds(layer("BoardOutline"))
            ob = _bounds(gerber_read.parse(gerber.layer_gerber(board, "outline")))
            dx, dy = ob[0] - tb[0], ob[1] - tb[1]
            area = (tb[0] - 1, tb[1] - 1, tb[2] - tb[0] + 2, tb[3] - tb[1] + 2)
            for ending, name, missing in (
                ("copper_top", "1 - Верхний", 0.03),
                ("copper_bottom", "2 - Нижний", 0.05),
            ):
                with self.subTest(board=folder.name, layer=ending):
                    a = render(layer(name), *area, 8)
                    ours = gerber_read.parse(gerber.layer_gerber(board, ending))
                    b = render(ours, area[0] + dx, area[1] + dy, area[2], area[3], 8)
                    da, db = bytes(a.constBits()), bytes(b.constBits())
                    dark = sum(1 for p in da if p > 127)
                    only_theirs = sum(1 for p, q in zip(da, db, strict=True) if p > 127 >= q)
                    only_ours = sum(1 for p, q in zip(da, db, strict=True) if q > 127 >= p)
                    self.assertLess(only_theirs / dark, missing)
                    self.assertLess(only_ours / dark, 0.05)


class PadCorners(unittest.TestCase):
    """Rectangular and octagonal pads keep their corners, as in the original's files."""

    def test_like_the_original(self):
        # Points of an octagonal pad (radius 1.3) and a tall one (radius 1) in Example1.lay6
        octagon = core.pad_points(0, 0, 1.3, 2)
        self.assertEqual(
            [(round(x, 4), round(y, 4)) for x, y in octagon],
            [
                (-1.3, 0.5395),
                (-0.5395, 1.3),
                (0.5395, 1.3),
                (1.3, 0.5395),
                (1.3, -0.5395),
                (0.5395, -1.3),
                (-0.5395, -1.3),
                (-1.3, -0.5395),
            ],
        )
        tall = core.pad_points(0, 0, 1.0, 8)
        self.assertEqual((round(tall[1][0], 4), round(tall[1][1], 4)), (-0.415, 2.0))
        square = core.pad_points(0, 0, 1.0, 3)
        self.assertEqual(square, [(-1.0, 1.0), (1.0, 1.0), (1.0, -1.0), (-1.0, -1.0)])

    def test_new_pad_and_shape_change(self):
        board = core.board_from_dialog("t", "empty", 20, 20)
        pad = core.new_pad(board, 1, 5, -5, 2.0, 0.8, 2)
        self.assertEqual(len(pad.points), 8)
        self.assertEqual(core.pad_rotation(pad), 0.0)
        square = core.with_pad_shape(pad, 3)
        self.assertEqual((square.shape, len(square.points)), (3, 4))
        bigger = core.with_pad_size(square, 3.0, 0.8)
        self.assertEqual(bigger.points[1], (6.5, -3.5))


EXAMPLES = Path(r"C:\Program Files\DipTrace\Examples")


def example(name: str) -> bytes:
    return (EXAMPLES / f"{name}.dip").read_bytes()


@unittest.skipUnless((EXAMPLES / "PCB_6.dip").exists(), "DipTrace's examples not installed")
class DipTraceExamples(unittest.TestCase):
    """DipTrace's own example boards, checked against its ASCII export of them."""

    def test_layers(self):
        layers = diptrace.read_layers(example("PCB_6"))
        self.assertEqual(
            [(layer.name, layer.plane) for layer in layers],
            [("Top", False), ("Gnd", True), ("Pwr", True), ("Bottom", False)],
        )
        self.assertEqual(diptrace.layer_map(layers), {0: 1, 3: 3, 1: 5, 2: 6})

    def test_all_parts(self):
        # Vias with hidden layers, pads with custom spokes and parts with outline points
        for name, count in (("Banana_Pi", 764), ("BeagleBone_Black", 1241), ("PCB_4", 67)):
            with self.subTest(board=name):
                self.assertEqual(len(diptrace.read_parts(example(name))), count)

    def test_surface_parts(self):
        parts = {p.reference: p for p in diptrace.read_parts(example("Banana_Pi"))}
        self.assertTrue(parts["U1"].surface)  # a BGA: its pads keep a hole size
        self.assertFalse(parts["StaticVia26"].surface)

    def test_tracks_change_layer_at_vias(self):
        tracks = diptrace.read_tracks(example("PCB_4"))
        changing = [t for t in tracks if len(set(t.layers[1:])) > 1]
        self.assertTrue(changing)
        self.assertTrue(all(t.vias for t in changing))
        x, y, diameter, hole = changing[0].vias[0]
        self.assertAlmostEqual(diameter, 1.016, places=3)

    def test_board_shapes_and_silk_width(self):
        shapes = diptrace.read_board_shapes(example("Banana_Pi"))
        kinds = Counter((s.place, s.kind) for s in shapes)
        self.assertEqual((kinds[(1, 0)], kinds[(1, 1)], kinds[(1, 6)]), (608, 2, 11))
        width = diptrace.read_silk_width(example("BeagleBone_Black"))
        self.assertAlmostEqual(width, 0.1524, places=4)
