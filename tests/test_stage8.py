"""Stage 8: Text-IO, footprint wizard, copies, autorouter, plugins and general settings."""

import sys
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

import core
from tests.samples import NO_SAMPLES, have_samples
from tests.ui_base import ROOT, WindowTestCase
from ui import style
from ui.drc import Rules, check
from ui.extras_actions import plugin_command, replaced_from_text
from ui.options import OptionsDialog, apply_options
from ui.render import point
from ui.router import route, routed_board

TEXTIO = ROOT / "Samples" / "textio"
# Boards and the Text-IO files the original program exported from them.
REFERENCES = ("tio_156", "tio_ex1_b1", "tio_props")


def blank():
    return core.board_from_dialog("Пустая", "empty", 50, 40)


def reference(name):
    board = core.parse_project((TEXTIO / f"{name}.lay6").read_bytes()).boards[0]
    return board, (TEXTIO / f"{name}.txt").read_bytes()


@unittest.skipUnless(have_samples(), NO_SAMPLES)
class TextIO(unittest.TestCase):
    def test_export_matches_the_original(self):
        for name in REFERENCES:
            with self.subTest(name):
                board, expected = reference(name)
                self.assertEqual(core.export_text(board).encode("cp1251"), expected)

    def test_import_round_trip(self):
        for name in REFERENCES:
            with self.subTest(name):
                board, expected = reference(name)
                again = replaced_from_text(board, expected.decode("cp1251"))
                self.assertEqual(len(again.elements), len(board.elements))
                self.assertEqual(core.export_text(again).encode("cp1251"), expected)

    def test_import_appends_with_new_ids(self):
        board, expected = reference("tio_156")
        added = core.import_text(board, expected.decode("cp1251"))
        old = {core.component_id(obj) for obj in board.elements} - {0}
        new = {core.component_id(obj) for obj in added} - {0}
        self.assertTrue(new)
        self.assertFalse(old & new)

    def test_bad_line(self):
        with self.assertRaises(core.TextIOError):
            core.import_text(blank(), "PAD,POS=abc;\r\n")


class Defaults(unittest.TestCase):
    def test_second_pad_keeps_mask_and_clearance(self):
        # Regression: the second pad on a new board took stale record bytes as defaults.
        board = blank()
        first = core.new_pad(board, 1, 10, -10, 1.6, 0.8)
        board.elements.append(first)
        second = core.new_pad(board, 1, 20, -10, 1.6, 0.8)
        self.assertEqual(second.soldermask, first.soldermask)
        self.assertEqual(second.clearance, first.clearance)


class Arrays(unittest.TestCase):
    def test_footprints(self):
        board = blank()
        dip = core.Footprint(kind=core.DIP, horizontal=7, y=7.62)
        pads = core.footprint(board, dip, 25, -20)
        self.assertEqual(len(pads), 14)
        self.assertEqual(core.footprint_count(dip), 14)
        self.assertEqual(len({tuple(core.group_ids(p)) for p in pads}), 1)
        quad = core.Footprint(kind=core.QUAD, horizontal=4, vertical=3, smd=True, x=10, y=8)
        self.assertEqual(len(core.footprint(board, quad, 25, -20)), 14)
        ring = core.Footprint(kind=core.CIRCLE_ROW, horizontal=6, x=10)
        centres = [core.centre_of(p) for p in core.footprint(board, ring, 25, -20)]
        for x, y in centres:
            self.assertAlmostEqual(((x - 25) ** 2 + (y + 20) ** 2) ** 0.5, 5)

    def test_tiled_and_circled(self):
        board = blank()
        pad = core.new_pad(board, 1, 10, -10, 1.6, 0.8)
        board.elements.append(pad)
        copies = core.tiled(board, [pad], 3, 2, 5, 4)
        self.assertEqual(len(copies), 5)
        self.assertIn((20.0, -14.0), [core.centre_of(c) for c in copies])
        ring = core.circled(board, [pad], (10, -15), 4, 360, False)
        self.assertEqual(len(ring), 3)
        self.assertEqual(
            sorted((round(x, 6), round(y, 6)) for x, y in map(core.centre_of, ring)),
            [(5.0, -15.0), (10.0, -20.0), (15.0, -15.0)],
        )


class Options(unittest.TestCase):
    def test_track_current(self):
        self.assertAlmostEqual(core.track_current(1.0), 3.1266, places=3)
        self.assertGreater(core.track_current(1.0, 70), core.track_current(1.0))
        self.assertGreater(core.track_current(1.0, 35, 40), core.track_current(1.0))

    def test_cam_origin(self):
        if not have_samples():
            self.skipTest(NO_SAMPLES)
        board = core.parse_project((ROOT / "Samples" / "motor ir2101.lay6").read_bytes()).boards[0]
        if core.board_origin(board) == (0.0, 0.0):
            self.skipTest("sample board has no origin")
        with_origin = core.excellon(board)
        without = core.excellon(board, core.DrillOptions(use_origin=False))
        self.assertNotEqual(with_origin, without)

    def test_plugin_command(self):
        self.assertEqual(plugin_command("p", "", "f.txt"), ["p", "f.txt"])
        self.assertEqual(plugin_command("p", "-i $FILE -q", "f.txt"), ["p", "-i", "f.txt", "-q"])


class Router(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication

        QApplication.instance() or QApplication([])

    def test_route_around_an_obstacle(self):
        board = blank()
        board.elements += [
            core.new_pad(board, 1, 10, -20, 1.6, 0.8),
            core.new_pad(board, 1, 40, -20, 1.6, 0.8),
            core.new_track(board, 3, [(25, -5), (25, -30)], 1.0),
        ]
        for index, obj in core.toggled_wire(board, 0, 1).items():
            board.elements[index] = obj
        result = route(board, 0, 1, 3, 0.4, 0.3, 0.25)
        self.assertIsNotNone(result.points)
        routed = routed_board(board, 0, 1, 3, result.points, 0.4)
        self.assertEqual(core.air_wires(routed), [])
        self.assertEqual(len(routed.elements), 4)
        self.assertEqual(check(routed, Rules(distances={"copper": 0.3})), [])

    def test_no_way_through(self):
        board = blank()
        board.elements += [
            core.new_pad(board, 1, 10, -20, 1.6, 0.8),
            core.new_pad(board, 1, 40, -20, 1.6, 0.8),
            core.new_track(board, 3, [(25, 1), (25, -41)], 1.0),
        ]
        result = route(board, 0, 1, 3, 0.4, 0.3, 0.25)
        self.assertIsNone(result.points)


PLUGIN = textwrap.dedent(
    """
    import sys
    path = sys.argv[1]
    lines = open(path, encoding="cp1251").read().splitlines()
    pads = [line for line in lines if line.startswith("PAD,")]
    open(path, "w", encoding="cp1251", newline="\\r\\n").write("\\n".join(pads[:2]) + "\\n")
    """
)


class Window(WindowTestCase):
    def test_wizard_and_tile(self):
        w = self.window
        with mock.patch("ui.extras_actions.FootprintWizard.exec", return_value=1):
            w.footprint_wizard()
        added = w.boards[0].elements[self.count :]
        self.assertTrue(added)
        self.assertTrue(all(obj.kind in (core.THT, core.SMD) for obj in added))
        w.view.select(len(w.boards[0].elements) - 1)
        before = len(w.boards[0].elements)
        members = len(w.view.members)
        with mock.patch("ui.wizards.TileDialog.exec", return_value=1):
            w.tile_selection()
        self.assertGreater(len(w.boards[0].elements), before)
        self.assertEqual((len(w.boards[0].elements) - before) % members, 0)
        w.undo.undo()
        self.assertEqual(len(w.boards[0].elements), before)

    def test_textio_export_import(self):
        w = self.window
        path = Path(self.temp.name) / "objects.txt"
        with mock.patch(
            "ui.extras_actions.QFileDialog.getSaveFileName", return_value=(str(path), "")
        ):
            w.textio_export()
        self.assertEqual(path.read_bytes(), core.export_text(self.board).encode("cp1251"))
        with mock.patch(
            "ui.extras_actions.QFileDialog.getOpenFileName", return_value=(str(path), "")
        ):
            w.textio_import()
        # The objects are carried on the cursor until a click puts them down.
        self.assertEqual(len(w.boards[0].elements), self.count)
        self.assertIsNotNone(w.view.placing)
        target = w.view.mapFromScene(QPointF(20, 12))
        QTest.mouseMove(w.view.viewport(), target)
        QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, pos=target)
        self.assertIsNone(w.view.placing)
        self.assertEqual(len(w.boards[0].elements), 2 * self.count)
        clicked = w.view.mapToScene(target)
        cx, cy = core.centre(w.boards[0].elements[self.count :])
        step = w.view.grid or 0.01
        self.assertAlmostEqual(cx, clicked.x(), delta=step)
        self.assertAlmostEqual(cy, -clicked.y(), delta=step)
        w.undo.undo()
        self.assertEqual(len(w.boards[0].elements), self.count)

    def test_placing_cancelled(self):
        w = self.window
        w.view.start_placing(list(self.board.elements[:3]))
        QTest.keyClick(w.view, Qt.Key.Key_Escape)
        self.assertIsNone(w.view.placing)
        self.assertEqual(len(w.boards[0].elements), self.count)

    def test_connection_drag_shows_dashed_line(self):
        w = self.window
        board = w.boards[0]
        pads = [i for i, e in enumerate(board.elements) if e.kind == core.THT]
        a, b = pads[0], pads[2]
        w.mode_actions["connect"].trigger()
        start = w.view.mapFromScene(point(*core.centre_of(board.elements[a])))
        end = w.view.mapFromScene(point(*core.centre_of(board.elements[b])))
        viewport = w.view.viewport()
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
        self.assertIsNotNone(w.view.wire_line)
        QTest.mouseMove(viewport, end)
        line = w.view.wire_line
        assert line is not None
        self.assertEqual(line.pen().style(), Qt.PenStyle.DashLine)
        self.assertGreater(line.line().length(), 0)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
        self.assertIsNone(w.view.wire_line)
        self.assertIn((min(a, b), max(a, b)), core.air_wires(w.boards[0]))

    def test_plugin(self):
        w = self.window
        script = Path(self.temp.name) / "plugin.py"
        script.write_text(PLUGIN, encoding="utf-8")
        w.settings.setValue("plugins/0/name", "Две площадки")
        w.settings.setValue("plugins/0/program", sys.executable)
        w.settings.setValue("plugins/0/arguments", f"{script} $FILE")
        w.run_plugin(0)
        self.assertEqual(len(w.boards[0].elements), 2)
        self.assertIn("обновлена", w.hint.text())
        w.undo.undo()
        self.assertEqual(len(w.boards[0].elements), self.count)

    def test_autoroute_click(self):
        w = self.window
        board = w.boards[0]
        pads = [i for i, e in enumerate(board.elements) if e.kind == core.THT]
        a, b = pads[0], pads[-1]
        for index, obj in core.toggled_wire(board, a, b).items():
            board.elements[index] = obj
        w.mode_actions["autoroute"].trigger()
        self.assertTrue(w.route_bar.isVisibleTo(w))
        (ax, ay), (bx, by) = core.centre_of(board.elements[a]), core.centre_of(board.elements[b])
        w.route_click(QPointF((ax + bx) / 2, -(ay + by) / 2))
        status = w.route_bar.status.text()
        if w.boards[0] is board:
            self.assertIn("не найден", status)
        else:
            self.assertEqual(len(w.boards[0].elements), self.count + 1)
            self.assertNotIn((a, b), core.air_wires(w.boards[0]))
        w.route_click(QPointF(-1000, 1000))
        self.assertIn("воздушной", w.route_bar.status.text())

    def test_autoroute_keeps_zoom_and_routes_a_drag(self):
        w = self.window
        board = blank()
        board.elements += [
            core.new_pad(board, 1, 10, -20, 1.6, 0.8),
            core.new_pad(board, 1, 40, -20, 1.6, 0.8),
        ]
        w.boards[0] = board
        w.rebuild_tabs(0)
        w.mode_actions["autoroute"].trigger()
        w.view.scale(1.2, 1.2)
        zoom = w.view.transform().m11()
        viewport = w.view.viewport()
        start = w.view.mapFromScene(QPointF(10, 20))
        end = w.view.mapFromScene(QPointF(40, 20))
        self.assertTrue(viewport.rect().contains(start) and viewport.rect().contains(end))
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
        self.assertIsNotNone(w.view.wire_line)
        QTest.mouseMove(viewport, end)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(len(w.boards[0].elements), 3)
        self.assertEqual(w.boards[0].elements[2].kind, core.LINE)
        self.assertEqual(core.air_wires(w.boards[0]), [])
        self.assertAlmostEqual(w.view.transform().m11(), zoom)

    def test_settings_dialog(self):
        w = self.window
        dialog = OptionsDialog(w, w.settings)
        dialog.colors["grid"].set_colour("#123456")
        dialog.holes.setCurrentIndex(1)
        dialog.general["darken_planes"].setChecked(False)
        dialog.undo_limit.setValue(7)
        dialog.hotkeys[2].setValue(0.3)
        dialog.remember()
        apply_options(w.settings)
        try:
            self.assertEqual(style.GRID_COLOR.name(), "#123456")
            self.assertEqual(style.HOLE_COLOR.name(), "#ffffff")
            self.assertFalse(style.OPTIONS["darken_planes"])
            self.assertEqual(style.OPTIONS["undo_limit"], 7)
            w.grid_hotkey(2)
            self.assertAlmostEqual(w.view.grid, 0.3)
            for page in range(len(OptionsDialog.PAGES)):
                dialog.list.setCurrentRow(page)
                self.assertEqual(dialog.caption.text(), OptionsDialog.PAGES[page])
        finally:
            w.settings.remove("options")
            apply_options(w.settings)
        self.assertEqual(style.GRID_COLOR.name(), "#2d2d2d")
        with mock.patch(
            "ui.extras_actions.OptionsDialog.exec", return_value=QDialog.DialogCode.Rejected
        ):
            w.general_settings()

    def test_component_dialog_after_macro_drop(self):
        from tests.ui_base import DIP

        if not DIP.exists():
            self.skipTest("no macro library in MAKROS")
        w = self.window
        w.component_dialog_on_drop = True
        w.macros.as_component.setChecked(True)
        with mock.patch("ui.main_window.ComponentDialog.exec", return_value=0) as shown:
            w.place_macro("top", str(DIP), (20.0, -12.0))
            QApplication.processEvents()
        shown.assert_called_once()
        self.assertGreater(len(w.boards[0].elements), self.count)
