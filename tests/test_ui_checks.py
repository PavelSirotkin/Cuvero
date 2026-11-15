"""Stage 7: air wires, connections tool, test mode, DRC, selector and components."""

import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QGraphicsLineItem

import core
from tests.ui_base import DIP, WindowTestCase
from ui.connectivity import net_of, nets
from ui.drc import Rules, check
from ui.lists import ComponentExportDialog, selector_groups

EXAMPLE = Path("D:/My/ZProgs/Sprint-Layout/Example1.lay6")


def blank():
    return core.board_from_dialog("Пустая", "empty", 50, 40)


class AirWires(unittest.TestCase):
    def test_lists_round_trip(self):
        board = blank()
        board.elements += [core.new_pad(board, 1, x, -10, 1.6, 0.8) for x in (5, 10, 15)]
        changed = core.toggled_wire(board, 0, 2)
        for index, obj in changed.items():
            board.elements[index] = obj
        self.assertEqual(core.air_wires(board), [(0, 2)])
        again = core.parse_project(core.serialize(core.new_project(board))).boards[0]
        self.assertEqual(core.wired_to(again.elements[0]), [2])
        self.assertEqual(core.wired_to(again.elements[2]), [0])
        changed = core.toggled_wire(again, 2, 0)  # the same wire again removes it
        self.assertEqual([core.wired_to(obj) for obj in changed.values()], [[], []])

    def test_renumbering_on_delete(self):
        board = blank()
        board.elements += [core.new_pad(board, 1, x, -10, 1.6, 0.8) for x in (5, 10, 15, 20)]
        for a, b in ((0, 3), (1, 3)):
            for index, obj in core.toggled_wire(board, a, b).items():
                board.elements[index] = obj
        changed = core.renumbered(board, [1])
        self.assertEqual(core.wired_to(changed[0]), [2])  # pad 3 becomes pad 2
        self.assertEqual(core.wired_to(changed[3]), [0])  # the wire to pad 1 is gone

    @unittest.skipUnless(EXAMPLE.exists(), "no example board of the full original")
    def test_example_board(self):
        board = core.parse_project(EXAMPLE.read_bytes()).boards[0]
        self.assertEqual(len(core.air_wires(board)), 4)


class Checks(WindowTestCase):
    def test_wires_drawn_and_kept_on_delete(self):
        w = self.window
        pads = [i for i, e in enumerate(self.board.elements) if e.kind == core.THT][:3]
        w.mode_actions["connect"].trigger()
        w.picked("connect", pads[0])
        w.picked("connect", pads[2])
        self.assertEqual(core.air_wires(self.board), [(pads[0], pads[2])])
        lines = [i for i in w.view.scene().items() if isinstance(i, QGraphicsLineItem)]
        self.assertTrue(lines)
        ends = {core.centre_of(self.board.elements[i]) for i in (pads[0], pads[2])}
        w.mode_actions["edit"].trigger()
        w.view.select(pads[1])
        w.delete_selection()  # removes objects before the wire's second pad
        ((a, b),) = core.air_wires(self.board)
        # The wire still joins the same two pads under their new numbers.
        self.assertEqual({core.centre_of(self.board.elements[i]) for i in (a, b)}, ends)
        w.undo.undo()
        self.assertEqual(core.air_wires(self.board), [(pads[0], pads[2])])

    def test_test_mode_highlights_the_net(self):
        w = self.window
        numbers = nets(self.board)
        largest = max(set(numbers.values()), key=list(numbers.values()).count)
        track = next(
            i
            for i, n in numbers.items()
            if n == largest and self.board.elements[i].kind == core.LINE
        )
        w.mode_actions["test"].trigger()
        w.picked("test", track)
        net = net_of(self.board, track)
        self.assertGreater(len(net), 1)
        self.assertIn(str(len(net)), w.hint.text())
        self.assertEqual(len(w.view.marks), 1)
        w.mode_actions["edit"].trigger()
        self.assertEqual(w.view.marks, [])

    def test_touching_tracks_share_a_net(self):
        board = blank()
        board.elements.append(core.new_track(board, 1, [(5, -5), (15, -5)], 0.4))
        board.elements.append(core.new_track(board, 1, [(15, -5), (15, -15)], 0.4))
        board.elements.append(core.new_track(board, 3, [(5, -5), (15, -5)], 0.4))
        numbers = nets(board)
        self.assertEqual(numbers[0], numbers[1])
        self.assertNotEqual(numbers[0], numbers[2])  # other side, no through pad
        board.elements.append(core.new_pad(board, 1, 5, -5, 1.6, 0.8))
        numbers = nets(board)
        self.assertEqual(numbers[0], numbers[2])

    def test_drc(self):
        board = blank()
        board.elements.append(core.new_track(board, 1, [(5, -5), (25, -5)], 0.4))
        board.elements.append(core.new_track(board, 1, [(5, -5.5), (25, -5.5)], 0.4))  # 0.1 gap
        board.elements.append(core.new_track(board, 1, [(5, -20), (25, -20)], 0.1))
        board.elements.append(core.new_pad(board, 1, 30, -30, 1.6, 0.8))
        board.elements.append(core.new_pad(board, 1, 31, -30, 1.6, 0.8))  # holes 0.2 apart
        rules = Rules(
            distances={"copper": 0.15, "holes": 0.5},
            limits={"track_min": 0.2, "hole_min": 1.0},
            others=set(),
        )
        texts = [v.text for v in check(board, rules)]
        self.assertTrue(any(t.startswith("Зазор меди") for t in texts))
        self.assertTrue(any(t.startswith("Отверстия ближе") for t in texts))
        self.assertTrue(any(t.startswith("Дорожка 0,1") for t in texts))
        self.assertEqual(sum(t.startswith("Отверстие 0,8") for t in texts), 2)

    def test_drc_panel(self):
        w = self.window
        w.drc_action.setChecked(True)
        w.run_drc(False)
        self.assertEqual(w.drc.list.count(), len(w.drc.violations))
        self.assertEqual(len(w.view.rings), len(w.drc.violations))
        if w.drc.violations:
            w.drc.list.setCurrentRow(0)
            self.assertTrue(w.view.marks)
        w.drc_action.setChecked(False)

    def test_selector(self):
        groups = selector_groups(self.board, 0, 0, 0)
        total = sum(len(v) for v in groups.values())
        pads = [e for e in self.board.elements if e.kind == core.THT and e.layer in (1, 3)]
        self.assertEqual(total, len(pads))
        w = self.window
        w.selector_action.setChecked(True)
        self.assertEqual(w.selector.tree.topLevelItemCount(), len(groups))
        first = w.selector.tree.topLevelItem(0)
        w.selector.clicked(first, 0)
        # A pad of a component brings the whole component along.
        self.assertLessEqual(set(groups[next(iter(groups))]), set(w.view.members))
        w.selector_action.setChecked(False)

    @unittest.skipUnless(DIP.exists(), "no macro library in MAKROS")
    def test_components_panel_and_export(self):
        w = self.window
        w.macros.as_component.setChecked(True)
        w.place_macro("top", str(DIP), (20.0, -12.0))
        w.components_action.setChecked(True)
        table = w.components.table
        self.assertEqual(table.rowCount(), len(core.components_of(self.board)))
        row = table.rowCount() - 1
        self.assertEqual(table.item(row, 5).text(), "14DIP300")
        table.item(row, 1).setText("IC9")
        info = core.components_of(self.board)[-1]
        self.assertEqual(info.name, "IC9")
        dialog = ComponentExportDialog(w, w.settings, self.board)
        self.assertIn("IC9", dialog.text())
        self.assertIn("14DIP300", dialog.text())
        with mock.patch.object(ComponentExportDialog, "exec", return_value=1):
            w.export_components()
        w.components_action.setChecked(False)
