"""Stage 4 in the window: drawing tools, track bends, mask tool, texts and components."""

import unittest
from unittest import mock

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsPathItem

import core
from tests.ui_base import DIP, WindowTestCase
from ui.component_dialog import ComponentDialog
from ui.draw_dialogs import SpecialFormDialog, TextDialog
from ui.render import MASK_COLOR, point


class DrawingTest(WindowTestCase):
    def click(self, x, y, button=Qt.MouseButton.LeftButton):
        QApplication.processEvents()  # let a changed hint resize the status bar first
        pos = self.window.view.mapFromScene(point(x, y))
        viewport = self.window.view.viewport()
        QTest.mouseMove(viewport, pos)
        QTest.mouseClick(viewport, button, pos=pos)

    def mask_drawn(self):
        return any(
            isinstance(item, QGraphicsPathItem) and item.brush().color() == MASK_COLOR
            for item in self.window.view.scene().items()
        )

    def new(self):
        return self.board.elements[self.count :]

    def test_circle_rectangle_and_polygon(self):
        w = self.window
        w.mode_actions["circle"].trigger()
        self.click(43, -10)
        self.click(45, -10)
        (circle,) = self.new()
        self.assertEqual(circle.kind, core.CIRCLE)
        self.assertAlmostEqual(core.circle_diameter(circle), 4.0, places=3)
        w.set_rect_filled(True)
        self.click(41, -12)
        self.click(46, -15)
        self.assertEqual(self.new()[-1].kind, core.POLYGON)
        w.mode_actions["zone"].trigger()
        for xy in ((41, -16), (46, -16), (46, -20)):
            self.click(*xy)
        self.click(41, -20, Qt.MouseButton.RightButton)
        zone = self.new()[-1]
        self.assertEqual(zone.kind, core.POLYGON)
        self.assertEqual(len(zone.points), 4)  # three corners and the closing point
        kinds = [obj.kind for obj in self.saved()[self.count :]]
        self.assertEqual(kinds, [core.CIRCLE, core.POLYGON, core.POLYGON])

    def test_track_bends_and_space(self):
        w = self.window
        w.mode_actions["track"].trigger()
        w.view.bend_mode = core.BEND_90
        self.click(41, -5)
        self.click(45, -8)
        self.click(45, -8, Qt.MouseButton.RightButton)
        (track,) = self.new()
        self.assertEqual(track.points, [(41, -5), (45, -5), (45, -8)])
        self.click(41, -10)
        QTest.keyClick(w.view, Qt.Key.Key_Space)
        self.assertEqual(w.view.bend_mode, core.FREE)
        self.click(45, -13)
        self.click(45, -13, Qt.MouseButton.RightButton)
        self.assertEqual(self.new()[-1].points, [(41, -10), (45, -13)])

    def test_mask_tool_toggles_the_opening(self):
        w = self.window
        w.add_element("pad", [(43.0, -6.0)])
        index = len(self.board.elements) - 1
        before = self.board.elements[index].soldermask
        self.assertFalse(self.mask_drawn())
        w.mode_actions["mask"].trigger()
        self.assertTrue(self.mask_drawn())
        self.click(43, -6)
        self.assertEqual(self.board.elements[index].soldermask, not before)
        w.undo.undo()
        self.assertEqual(self.board.elements[index].soldermask, before)
        w.mode_actions["edit"].trigger()
        self.assertFalse(self.mask_drawn())

    def test_text_tool_with_numbering(self):
        w = self.window
        w.settings.setValue("text/text", "X")
        w.settings.setValue("text/numbering", True)
        w.settings.setValue("text/number", 3)
        with mock.patch.object(TextDialog, "exec", return_value=1):
            w.set_active_layer(2)
            w.add_element("text", [(42.0, -5.0)])
            w.add_element("text", [(42.0, -8.0)])
        texts = [obj.text for obj in self.new()]
        self.assertEqual(texts, ["X3", "X4"])
        self.assertTrue(all(obj.children for obj in self.new()))
        saved = self.saved()[self.count :]
        self.assertEqual([obj.text for obj in saved], ["X3", "X4"])

    def test_properties_panel_edits_text(self):
        w = self.window
        with mock.patch.object(TextDialog, "exec", return_value=1):
            w.add_element("text", [(42.0, -5.0)])
        index = len(self.board.elements) - 1
        w.view.select(index)
        panel = w.properties
        panel.text_value.setText("Новый")
        panel.text_changed()
        self.assertEqual(self.board.elements[index].text, "Новый")
        panel.text_weight.setCurrentIndex(core.BOLD)
        self.assertEqual(core.text_weight(self.board.elements[index]), core.BOLD)

    def test_special_form(self):
        w = self.window
        w.settings.setValue("special/tab", 0)
        w.settings.setValue("special/rays", False)
        w.settings.setValue("special/filled", False)
        w.settings.setValue("special/corners", 5)
        with mock.patch.object(SpecialFormDialog, "exec", return_value=1):
            w.add_element("special", [(45.0, -10.0)])
        (shape,) = self.new()
        self.assertEqual(shape.kind, core.LINE)
        self.assertEqual(len(shape.points), 6)

    @unittest.skipUnless(DIP.exists(), "no macro library in MAKROS")
    def test_component_dialog(self):
        w = self.window
        w.macros.as_component.setChecked(True)
        w.place_macro("top", str(DIP), (45.0, -12.0))
        pad = next(i for i, obj in enumerate(self.new()) if obj.kind == core.THT) + self.count
        w.view.select(pad)

        def fill(dialog):
            dialog.ref_text.setText("IC7")
            dialog.ref_visible.setChecked(True)
            dialog.comment.setText("логика")
            return 1

        with mock.patch.object(ComponentDialog, "exec", fill):
            w.edit_component()
        cid = core.component_id(self.board.elements[pad])
        ref, _ = core.component_labels(self.board.elements, cid)
        assert ref is not None
        label = self.board.elements[ref]
        self.assertEqual(label.text, "IC7")
        self.assertTrue(label.filled)
        self.assertEqual(core.component_comment(label), "логика")
        self.assertEqual(core.component_package(self.board.elements, cid), "14DIP300")
        with mock.patch.object(ComponentDialog, "exec", return_value=ComponentDialog.DISSOLVE):
            w.edit_component()
        self.assertFalse(any(core.component_id(obj) == cid for obj in w.view.elements))
        w.undo.undo()
        self.assertTrue(any(core.component_id(obj) == cid for obj in w.view.elements))


if __name__ == "__main__":
    unittest.main()
