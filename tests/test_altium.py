"""Stage 9: Altium Designer boards (.PcbDoc) opened as new projects."""

import unittest
import unittest.mock
from collections import Counter
from pathlib import Path

import core
from core.altium import AltiumError, Conversion, convert, convert_file
from core.cfb import CfbError, CompoundFile
from tests.ui_base import ROOT, WindowTestCase
from ui.importers import board_from_conversion

ALTIUM = ROOT / "Samples" / "Altium"
CARRIAGE = ALTIUM / "Carriage_LAS_DRV_NOflip_LasPointer.PcbDoc"
BOARD = ALTIUM / "Board.PcbDoc"
SAMPLES = sorted(ALTIUM.glob("*.PcbDoc")) if ALTIUM.exists() else []


class Container(unittest.TestCase):
    def test_not_a_compound_file(self):
        with self.assertRaises(CfbError):
            CompoundFile(b"PK\x03\x04 not ole")
        with self.assertRaises(AltiumError):
            convert(b"nothing at all")

    @unittest.skipUnless(SAMPLES, "no Altium samples")
    def test_streams(self):
        cfb = CompoundFile(SAMPLES[0].read_bytes())
        for name in ("Board6/Data", "Pads6/Data", "Tracks6/Data", "Components6/Data"):
            self.assertTrue(cfb.has(name), name)
        self.assertEqual(len(cfb.stream("Pads6/Header")), 4)


@unittest.skipUnless(CARRIAGE.exists(), "no Altium sample")
class Carriage(unittest.TestCase):
    conversion: Conversion
    board: core.Board
    wires: int

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        QApplication.instance() or QApplication([])
        cls.conversion = convert_file(CARRIAGE)
        cls.board, cls.wires = board_from_conversion(cls.conversion)

    def test_size_and_contour(self):
        self.assertAlmostEqual(self.conversion.width, 54.0, delta=0.5)
        self.assertAlmostEqual(self.conversion.height, 74.1, delta=0.5)
        self.assertTrue(any(obj.layer == 7 for obj in self.board.elements))

    def test_objects(self):
        kinds = Counter(obj.kind for obj in self.board.elements)
        self.assertGreater(kinds[core.SMD], 100)
        self.assertGreater(kinds[core.THT], 70)  # pads and vias
        self.assertGreater(kinds[core.LINE], 50)
        self.assertGreater(kinds[core.POLYGON], 5)  # poured copper
        self.assertEqual(len(self.conversion.nets), len(self.board.elements))

    def test_components_and_labels(self):
        infos = core.components_of(self.board)
        names = {info.name for info in infos}
        self.assertIn("R16", names)
        self.assertGreater(len(infos), 30)
        packages = {info.package for info in infos}
        self.assertIn("R0603", packages)

    def test_routed_board_has_no_air_wires(self):
        self.assertEqual(self.wires, 0)

    def test_report(self):
        self.assertTrue(any("SMD" in text for text in self.conversion.report))

    def test_saves_as_lay6(self):
        data = core.serialize(core.new_project(self.board))
        again = core.parse_project(data).boards[0]
        self.assertEqual(len(again.elements), len(self.board.elements))


@unittest.skipUnless(BOARD.exists(), "no Altium sample")
class SingleSided(unittest.TestCase):
    def test_bottom_only_pads(self):
        from PySide6.QtWidgets import QApplication

        QApplication.instance() or QApplication([])
        conversion = convert_file(BOARD)
        board, wires = board_from_conversion(conversion)
        bottom = [o for o in board.elements if o.kind == core.THT and o.layer == 3]
        self.assertGreater(len(bottom), 50)
        self.assertLess(wires, 10)


@unittest.skipUnless(CARRIAGE.exists(), "no Altium sample")
class Opening(WindowTestCase):
    def test_open_as_new_project(self):
        w = self.window
        self.assertTrue(w.open_path(CARRIAGE))
        w.import_report.close()
        self.assertIsNone(w.path)
        self.assertTrue(w.is_modified())
        self.assertIn("импорт", w.windowTitle())
        self.assertEqual(w.boards[0].name, CARRIAGE.stem)
        saved = Path(self.temp.name) / "carriage.lay6"
        w.save_to(saved)
        self.assertEqual(w.path, saved)
        self.assertFalse(w.is_modified())
        self.assertNotIn("импорт", w.windowTitle())
        self.assertEqual(
            len(core.parse_project(saved.read_bytes()).boards[0].elements),
            len(w.boards[0].elements),
        )

    def test_broken_file(self):
        w = self.window
        bad = Path(self.temp.name) / "broken.PcbDoc"
        bad.write_bytes(b"not a board")
        with unittest.mock.patch("ui.file_actions.QMessageBox.warning") as warned:
            self.assertFalse(w.open_path(bad))
        warned.assert_called_once()


GERBERS = ALTIUM / "gerber"
# (sample, Gerber folder, [(our layer, Altium layer, largest missed share of Altium's area)])
COMPARED = [
    (
        BOARD,
        "Board",
        [
            ("copper_top", "Copper_Signal_Top", 0.005),
            ("copper_bottom", "Copper_Signal_Bot", 0.005),
            ("soldermask_bottom", "Soldermask_Bot", 0.12),  # bare holes' openings
        ],
    ),
    (
        CARRIAGE,
        "Carriage",
        [
            ("copper_top", "Copper_Signal_Top", 0.01),
            ("copper_bottom", "Copper_Signal_Bot", 0.015),  # vias without a ring
        ],
    ),
    (
        ALTIUM / "HLDI_G431RxT6_CH334R_EXT_Ldrw.PcbDoc",
        "HLDI",
        [
            ("copper_top", "Copper_Signal_Top", 0.005),
            ("copper_bottom", "Copper_Signal_Bot", 0.005),
        ],
    ),
]


def _bounds(g):
    xs = [x for p in g.primitives for x, _ in p.points]
    ys = [y for p in g.primitives for _, y in p.points]
    return min(xs), min(ys), max(xs), max(ys)


@unittest.skipUnless(GERBERS.exists(), "no Gerber output of Altium")
class AgainstAltiumGerber(unittest.TestCase):
    """Our Gerber of each converted board against the Gerber Altium wrote for it."""

    def test_copper_and_mask(self):
        from PySide6.QtWidgets import QApplication

        from core import gerber, gerber_read
        from tests.gerber_image import render

        QApplication.instance() or QApplication([])
        options = gerber.GerberOptions(mask_pads=0.1016, mask_smd=0.1016, mask_other=0.1016)
        for source, folder_name, layers in COMPARED:
            folder = GERBERS / folder_name
            if not (source.exists() and folder.exists()):
                continue
            board, _ = board_from_conversion(convert_file(source))
            # Line both up by the board contour, or by the top copper without one.
            profile = list(folder.glob("*_Profile.gbr"))
            if profile:
                theirs = gerber_read.parse(profile[0].read_text())
                ours = gerber_read.parse(gerber.layer_gerber(board, "outline", options))
            else:
                theirs = gerber_read.parse(next(folder.glob("*_Copper_Signal_Top.gbr")).read_text())
                ours = gerber_read.parse(gerber.layer_gerber(board, "copper_top", options))
            tb, ob = _bounds(theirs), _bounds(ours)
            dx, dy = ob[0] - tb[0], ob[1] - tb[1]
            area = (tb[0] - 1, tb[1] - 1, tb[2] - tb[0] + 2, tb[3] - tb[1] + 2)
            for ending, name, missing in layers:
                with self.subTest(board=folder_name, layer=ending):
                    text = next(folder.glob(f"*_{name}.gbr")).read_text()
                    a = render(gerber_read.parse(text), *area, 8)
                    layer = gerber_read.parse(gerber.layer_gerber(board, ending, options))
                    b = render(layer, area[0] + dx, area[1] + dy, area[2], area[3], 8)
                    da, db = bytes(a.constBits()), bytes(b.constBits())
                    dark = sum(1 for p in da if p > 127)
                    only_theirs = sum(1 for p, q in zip(da, db, strict=True) if p > 127 >= q)
                    only_ours = sum(1 for p, q in zip(da, db, strict=True) if q > 127 >= p)
                    self.assertLess(only_theirs / dark, missing)
                    self.assertLess(only_ours / dark, 0.01)

    @unittest.skipUnless(BOARD.exists(), "no Altium sample")
    def test_vias_are_tented(self):
        from PySide6.QtWidgets import QApplication

        QApplication.instance() or QApplication([])
        board, _ = board_from_conversion(convert_file(BOARD))
        vias = [o for o in board.elements if o.kind == core.THT and o.plated and o.layer == 1]
        self.assertTrue(vias)
        self.assertFalse(any(o.soldermask for o in vias if o.inner < 0.5))


class TextSizes(unittest.TestCase):
    """Letters as tall as Altium's (measured on the Gerber that Altium wrote)."""

    @staticmethod
    def height(line: str) -> float:
        return int(line.split("HEIGHT=")[1].split(",")[0]) / 10000

    def test_stroke_text(self):
        from core.altium import _text_line

        # Altium: 1.52 mm text with 0.25 mm strokes has 1.77 mm tall letters.
        line = _text_line("TEXT", 2, "0/0", 1.52, 0.25, 0.0, False, "MD3")
        self.assertAlmostEqual(self.height(line) * 1.05, 1.77, places=2)
        self.assertNotIn("STYLE", line)

    def test_truetype_text(self):
        from core.altium import _text_line

        # Altium: capitals of a 1.65 mm TrueType text are 1.08 mm tall.
        line = _text_line("TEXT", 2, "0/0", 1.65, 0.25, 0.0, False, "ABC", truetype=True)
        self.assertAlmostEqual(self.height(line), 1.08, places=2)
        self.assertIn("STYLE=2", line)
