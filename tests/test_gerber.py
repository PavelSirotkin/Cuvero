"""Gerber and drill output, compared with the files the original program wrote."""

import os
import unittest
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import core  # noqa: E402
from core import drill, gerber, gerber_read  # noqa: E402
from tests.gerber_image import difference, render  # noqa: E402
from tests.samples import require_samples

require_samples()

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "Samples"
MOTOR = SAMPLES / "motor ir2101.lay6"
HLDI = SAMPLES / "HLDI_ALL_PCB.lay6"

# (board file, board, file ending, reference)
REFERENCES = [
    (MOTOR, 0, "copper_top", "motor ir2101_copper_top.gbr"),
    (MOTOR, 0, "copper_bottom", "motor ir2101_copper_bottom.gbr"),
    (HLDI, 0, "copper_top", "HLDI_ALL_PCB-[HLDI Main]_copper_top.gbr"),
    (HLDI, 0, "copper_bottom", "HLDI_ALL_PCB-[HLDI Main]_copper_bottom.gbr"),
    (HLDI, 0, "soldermask_top", "HLDI_ALL_PCB-[HLDI Main]_soldermask_top.gbr"),
    (HLDI, 0, "soldermask_bottom", "HLDI_ALL_PCB-[HLDI Main]_soldermask_bottom.gbr"),
]


def width(primitive):
    assert primitive.aperture is not None
    return primitive.aperture.params[0]


def board(path, index=0):
    return core.parse_project(path.read_bytes()).boards[index]


class GerberImages(unittest.TestCase):
    app: object

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_layers_match_the_original(self):
        for path, index, ending, reference in REFERENCES:
            with self.subTest(reference=reference):
                b = board(path, index)
                ours = gerber_read.parse(gerber.layer_gerber(b, ending))
                theirs = gerber_read.parse((SAMPLES / reference).read_text())
                ox, oy = core.board_origin(b)
                area = (-1.0, -b.height - oy - 1.0, b.width + 2, b.height + 2)
                share = difference(render(ours, *area, 10), render(theirs, *area, 10))
                # Only single pixels along slanted edges may differ.
                self.assertLess(share, 0.0005)


class GerberText(unittest.TestCase):
    def test_x2_attributes(self):
        when = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
        text = gerber.layer_gerber(board(HLDI), "copper_top", gerber.GerberOptions(date=when))
        self.assertIn("%TF.FileFunction,Copper,L1,Top*%", text)
        self.assertIn("%TF.FilePolarity,Positive*%", text)
        self.assertIn("%TF.CreationDate,2026-11-12T10:00:00+00:00*%", text)
        self.assertIn("%TA.AperFunction,SMDPad,CuDef*%", text)
        self.assertIn("%TA.AperFunction,ComponentPad*%", text)
        self.assertIn("%TA.AperFunction,Conductor*%", text)
        self.assertTrue(text.rstrip().endswith("M02*"))
        mask = gerber.layer_gerber(board(HLDI), "soldermask_top")
        self.assertIn("%TF.FileFunction,Soldermask,Top*%", mask)
        self.assertIn("%TF.FilePolarity,Negative*%", mask)

    def test_component_names_on_pads(self):
        b = core.board_from_dialog("Пустая", "empty", 30, 20)
        pads = [core.new_pad(b, 1, x, -10, 1.6, 0.8) for x in (5, 7.54)]
        parts = core.make_component(b, pads, "R0207")
        b.elements.extend(parts)
        ref, _ = core.component_labels(b.elements, core.component_id(parts[0]))
        assert ref is not None
        b.elements[ref] = core.with_text(b.elements[ref], text="R7")
        text = gerber.layer_gerber(b, "copper_top")
        self.assertEqual(text.count("%TO.C,R7*%"), 1)
        self.assertIn("%TD.C*%", text)

    def test_plain_rs274x(self):
        text = gerber.layer_gerber(board(MOTOR), "copper_top", gerber.GerberOptions(x2=False))
        self.assertNotIn("%T", text)
        self.assertTrue(text.startswith("%FSLAX46Y46*%"))

    def test_file_names_like_the_original(self):
        self.assertEqual(
            gerber.file_name("HLDI_ALL_PCB", "HLDI Main", "copper_top", 4),
            "HLDI_ALL_PCB-[HLDI Main]_copper_top.gbr",
        )
        self.assertEqual(
            gerber.file_name("motor ir2101", "x", "copper_top", 1), "motor ir2101_copper_top.gbr"
        )

    def test_thermal_spokes_and_holes(self):
        b = core.board_from_dialog("Пустая", "empty", 30, 20)
        b = core.with_plane(b, 1, True)
        pad = core.with_thermal(core.new_pad(b, 1, 10, -10, 2.0, 1.0), True)
        b.elements.append(pad)
        text = gerber.layer_gerber(b, "copper_top", gerber.GerberOptions(holes="clear"))
        parsed = gerber_read.parse(text)
        spokes = [p for p in parsed.primitives if p.kind == "draw" and p.dark]
        self.assertEqual(len(spokes), 4)  # straight spokes, a third of the pad wide
        self.assertAlmostEqual(width(spokes[0]), 2.0 / 3, places=3)
        cleared = [p for p in parsed.primitives if not p.dark and p.kind == "flash"]
        self.assertEqual([width(p) for p in cleared], [2.8, 1.0])


class Drill(unittest.TestCase):
    def test_excellon_is_byte_identical(self):
        for path, fmt, reference in (
            (MOTOR, "3.3", "motor ir2101.DRL"),
            (HLDI, "3.2", "HLDI_ALL_PCB-[HLDI Main].DRL"),
        ):
            with self.subTest(reference=reference):
                ours = drill.excellon(board(path), drill.DrillOptions(format=fmt))
                self.assertEqual(ours.encode(), (SAMPLES / reference).read_bytes())

    def test_options(self):
        text = drill.excellon(
            board(MOTOR),
            drill.DrillOptions(inch=True, m71=True, comments=False, decimal_point=False),
        )
        self.assertTrue(text.startswith("M48\r\nM72\r\n"))
        self.assertNotIn(".", text.split("%")[1])

    def test_hole_table(self):
        table = drill.hole_table(board(HLDI))
        self.assertEqual([d for d, _, _ in table][:3], [0.3, 0.4, 0.5])
        self.assertEqual(sum(p + s for _, p, s in table), len(drill.holes(board(HLDI))))


if __name__ == "__main__":
    unittest.main()
