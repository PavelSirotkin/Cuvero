"""Stage 1 in the window: selection, clipboard, groups, sides, alignment and track nodes."""

import unittest

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

import core
from tests.ui_base import DIP, WindowTestCase
from ui.render import point


class EditingTest(WindowTestCase):
    def loose(self, kind=None):
        """Objects that a click selects alone, optionally of one kind."""
        elements = self.board.elements
        return [
            i
            for i, obj in enumerate(elements)
            if (kind is None or obj.kind == kind) and len(core.unit_of(elements, i)) == 1
        ]

    def view_pos(self, x, y):
        return self.window.view.mapFromScene(point(x, y))

    def test_band_selects_objects_fully_inside(self):
        w = self.window
        w.add_element("pad", [(3.0, -3.0)])
        w.add_element("pad", [(6.0, -3.0)])
        pads = [len(self.board.elements) - 2, len(self.board.elements) - 1]
        w.view.select(None)
        viewport = w.view.viewport()
        # Start just above the board, clear of the rulers, where nothing can be hit.
        start, end = self.view_pos(0.5, 0.8), self.view_pos(7.5, -4.5)
        self.assertIsNone(w.view.item_at(start))
        self.assertGreater(min(start.x(), start.y()), 25)
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewport, end)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
        self.assertTrue(set(pads) <= set(w.view.members))
        self.assertIsNone(w.view.band_item)

    def test_shift_click_toggles_units(self):
        w = self.window
        first, second = self.loose(core.THT)[:2]
        w.view.select(first)
        w.view.select(second, add=True)
        self.assertEqual(w.view.members, sorted([first, second]))
        w.view.select(first, add=True)
        self.assertEqual(w.view.members, [second])
        self.assertTrue(w.group_action.isEnabled())

    def test_copy_paste_and_duplicate(self):
        w = self.window
        w.view.select(0)  # the SOT-89 component
        members = len(w.view.members)
        self.assertTrue(w.copy_selection())
        w.paste()
        self.assertEqual(len(self.board.elements), self.count + members)
        pasted = self.board.elements[self.count :]
        self.assertEqual({core.component_id(o) for o in pasted}, {2})
        self.assertEqual(len(w.view.members), members)
        w.duplicate_action.trigger()
        self.assertEqual(len(self.board.elements), self.count + 2 * members)
        self.assertEqual(
            {core.component_id(o) for o in self.board.elements[self.count + members :]}, {3}
        )
        self.assertEqual(len(self.saved()), len(self.board.elements))
        w.undo.undo()
        w.undo.undo()
        self.assertEqual(len(self.board.elements), self.count)

    def test_cut_removes_and_paste_restores(self):
        w = self.window
        track = self.loose(core.LINE)[0]
        points = self.board.elements[track].points
        w.view.select(track)
        w.cut_action.trigger()
        self.assertEqual(len(self.board.elements), self.count - 1)
        self.assertIn("Вырезание", w.undo.undoText())
        w.paste()  # the cursor is outside the view: same place
        self.assertEqual(self.board.elements[-1].points, points)

    def test_group_then_click_selects_group(self):
        w = self.window
        chosen = self.loose(core.THT)[:3]
        w.view.set_selection(chosen)
        w.group_action.trigger()
        w.view.select(chosen[1])
        self.assertEqual(w.view.members, sorted(chosen))
        w.ungroup_action.trigger()
        w.view.select(chosen[1])
        self.assertEqual(w.view.members, [chosen[1]])

    def test_other_side_and_layer(self):
        w = self.window
        w.view.select(0)
        layers = [self.board.elements[i].layer for i in w.view.members]
        w.side_action.trigger()
        flipped = [self.board.elements[i].layer for i in w.view.members]
        self.assertEqual(flipped, [{1: 3, 2: 4}.get(layer, layer) for layer in layers])
        track = self.loose(core.LINE)[0]
        w.view.select(track)
        w.layer_selection(4)
        self.assertEqual(self.board.elements[track].layer, 4)

    def test_snap_and_align(self):
        w = self.window
        w.view.grid = 0.1
        w.add_element("pad", [(3.03, -3.0)])
        w.add_element("pad", [(6.0, -4.07)])
        a, b = len(self.board.elements) - 2, len(self.board.elements) - 1
        moved = core.transformed(self.board.elements[a], 0.033, 0)
        w.edit_element(a, moved)
        w.view.set_selection([a])
        w.snap_action.trigger()
        self.assertAlmostEqual(self.board.elements[a].x, 3.1, places=6)
        w.view.set_selection([a, b])
        w.align_selection("bottom")
        self.assertAlmostEqual(self.board.elements[a].y, self.board.elements[b].y, places=6)

    def test_split_and_join_track(self):
        w = self.window
        w.add_element("track", [(1.0, -1.0), (4.0, -1.0), (4.0, -3.0)])
        track = len(self.board.elements) - 1
        w.split_at(track, 1)
        self.assertEqual(len(self.board.elements), self.count + 2)
        self.assertEqual(self.board.elements[track].points, [(1.0, -1.0), (4.0, -1.0)])
        w.view.set_selection([track, track + 1])
        w.join_selected()
        self.assertEqual(len(self.board.elements), self.count + 1)
        self.assertEqual(self.board.elements[track].points, [(1.0, -1.0), (4.0, -1.0), (4.0, -3.0)])
        w.undo.undo()  # one step undoes the whole join
        self.assertEqual(len(self.board.elements), self.count + 2)

    def test_node_menu_operations(self):
        w = self.window
        w.add_element("track", [(1.0, -1.0), (4.0, -1.0), (4.0, -3.0)])
        track = len(self.board.elements) - 1
        w.add_node(track, (2.52, -1.0))
        self.assertEqual(len(self.board.elements[track].points), 4)
        self.assertEqual(self.board.elements[track].points[1], (2.5, -1.0))
        w.remove_node(track, 1)
        self.assertEqual(len(self.board.elements[track].points), 3)

    @unittest.skipUnless(DIP.exists(), "no macro library in MAKROS")
    def test_drag_moves_several_units(self):
        w = self.window
        w.macros.as_component.setChecked(True)
        w.place_macro("top", str(DIP), (20.0, -12.0))
        component = list(w.view.members)
        track = self.loose(core.LINE)[0]
        w.view.set_selection([*component, track])
        pad = next(i for i in component if self.board.elements[i].kind == core.THT)
        x0, track_x0 = self.board.elements[pad].x, self.board.elements[track].points[0][0]
        obj = self.board.elements[pad]
        viewport = w.view.viewport()
        start = w.view.mapFromScene(QPointF(obj.x, -obj.y))
        end = w.view.mapFromScene(QPointF(obj.x + 2, -obj.y))
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewport, end)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
        self.assertAlmostEqual(self.board.elements[pad].x - x0, 2.0, places=3)
        self.assertAlmostEqual(self.board.elements[track].points[0][0] - track_x0, 2.0, places=3)


if __name__ == "__main__":
    unittest.main()
