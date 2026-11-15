"""Smoke tests of the main window, run without a visible screen."""

import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

import core
from tests.ui_base import DIP, WindowTestCase
from ui.commands import AddBoard
from ui.main_window import MainWindow
from ui.new_board_dialog import NewBoardDialog
from ui.render import point
from version import VERSION


class MainWindowTest(WindowTestCase):
    def test_program_icon(self):
        icon = self.window.windowIcon()
        self.assertFalse(icon.isNull())
        self.assertIn(256, [size.width() for size in icon.availableSizes()])

    def test_add_objects_undo_and_save(self):
        w = self.window
        w.add_element("pad", [(5.0, -5.0)])
        w.add_element("smd", [(8.0, -5.0)])
        w.add_element("track", [(1.0, -1.0), (4.0, -1.0)])
        self.assertEqual(len(self.board.elements), self.count + 3)
        w.undo.undo()
        self.assertEqual(len(self.board.elements), self.count + 2)
        w.undo.redo()
        kinds = [obj.kind for obj in self.saved()[self.count :]]
        self.assertEqual(kinds, [core.THT, core.SMD, core.LINE])

    def test_size_change_applies_to_selected_track(self):
        w = self.window
        track = next(i for i, obj in enumerate(self.board.elements) if obj.kind == core.LINE)
        w.view.select(track)
        w.track_size.set_values((1.2,), emit=True)
        self.assertAlmostEqual(self.board.elements[track].width, 1.2)

    def test_plane_switch_in_the_status_bar(self):
        w = self.window
        w.set_active_layer(1)
        before = core.has_plane(self.board, 1)
        w.plane_button.click()
        self.assertEqual(core.has_plane(w.boards[w.current_board_index()], 1), not before)
        w.undo.undo()
        self.assertEqual(core.has_plane(w.boards[w.current_board_index()], 1), before)
        self.assertEqual(w.plane_button.isChecked(), before)
        w.set_active_layer(2)
        self.assertFalse(w.plane_button.isEnabled())

    def test_clearance_for_new_and_selected_objects(self):
        w = self.window
        w.clearance_box.setValue(0.75)
        w.add_element("pad", [(5.0, -5.0)])
        pad = len(w.view.elements) - 1
        self.assertAlmostEqual(w.view.elements[pad].clearance, 0.75)
        w.view.select(pad)
        w.clearance_box.setValue(0.3)
        self.assertAlmostEqual(w.view.elements[pad].clearance, 0.3)

    @unittest.skipUnless(DIP.exists(), "no macro library in MAKROS")
    def test_turned_macro_and_saving_a_macro(self):
        w = self.window
        w.macros.as_component.setChecked(False)
        w.place_macro("top", str(DIP), (20.0, -12.0), turns=1)
        new = range(self.count, len(w.view.elements))
        xs = [w.view.elements[i].x for i in new if w.view.elements[i].kind == core.THT]
        ys = [w.view.elements[i].y for i in new if w.view.elements[i].kind == core.THT]
        # 14DIP300 is wide and low; a quarter turn makes it tall and narrow.
        self.assertGreater(max(ys) - min(ys), max(xs) - min(xs))
        elements = [w.view.elements[i] for i in new]
        again = core.parse_macro(core.macro_bytes(elements))
        self.assertEqual([e.kind for e in again], [e.kind for e in elements])

    @unittest.skipUnless(DIP.exists(), "no macro library in MAKROS")
    def test_component_is_dragged_as_a_whole(self):
        w = self.window
        w.macros.as_component.setChecked(True)
        w.place_macro("top", str(DIP), (20.0, -12.0))
        new = range(self.count, len(self.board.elements))
        self.assertEqual(len(w.view.members), len(new))
        pads = [i for i in new if self.board.elements[i].kind == core.THT]
        before = [self.board.elements[i].x for i in pads]
        pad = self.board.elements[pads[0]]
        viewport = w.view.viewport()
        start = w.view.mapFromScene(point(pad.x, pad.y))
        end = w.view.mapFromScene(point(pad.x + 5, pad.y))
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(viewport, end)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
        after = [self.board.elements[i].x for i in pads]
        for old, moved in zip(before, after, strict=True):
            self.assertAlmostEqual(moved - old, 5.0, places=3)
        w.undo.undo()
        self.assertEqual([self.board.elements[i].x for i in pads], before)
        cid = core.component_id(self.board.elements[pads[0]])
        self.assertEqual(core.component_package(self.saved(), cid), "14DIP300")

    def test_delete_track_and_undo(self):
        w = self.window
        track = next(
            i
            for i, obj in enumerate(self.board.elements)
            if obj.kind == core.LINE and len(core.unit_of(self.board.elements, i)) == 1
        )
        removed = self.board.elements[track]
        w.view.select(track)
        self.assertTrue(w.delete_action.isEnabled())
        w.delete_action.trigger()
        self.assertEqual(len(self.board.elements), self.count - 1)
        self.assertNotIn(removed, self.board.elements[track : track + 1])
        self.assertFalse(w.delete_action.isEnabled())
        self.assertEqual(len(self.saved()), self.count - 1)
        w.undo.undo()
        self.assertIs(self.board.elements[track], removed)
        self.assertEqual(w.view.selection, track)

    @unittest.skipUnless(DIP.exists(), "no macro library in MAKROS")
    def test_delete_whole_component(self):
        w = self.window
        w.macros.as_component.setChecked(True)
        w.place_macro("top", str(DIP), (20.0, -12.0))
        self.assertGreater(len(self.board.elements), self.count)
        w.delete_action.trigger()
        self.assertEqual(len(self.board.elements), self.count)
        self.assertEqual(w.undo.undoText(), "Удаление компонента 14DIP300")
        w.undo.undo()
        self.assertEqual(len(w.view.members), len(self.board.elements) - self.count)

    @unittest.skipUnless(DIP.exists(), "no macro library in MAKROS")
    def test_rotate_and_mirror_component(self):
        w = self.window
        w.macros.as_component.setChecked(True)
        w.place_macro("top", str(DIP), (20.0, -12.0))
        members = list(w.view.members)
        pads = [i for i in members if self.board.elements[i].kind == core.THT]

        def spread():
            xs = [self.board.elements[i].x for i in pads]
            ys = [self.board.elements[i].y for i in pads]
            return max(xs) - min(xs), max(ys) - min(ys)

        wide, high = spread()
        self.assertGreater(wide, high)  # a DIP lies horizontally in the library
        w.set_rotation_step(90)
        self.assertTrue(w.rotate_action.isEnabled())
        w.rotate_action.trigger()
        turned = spread()
        self.assertAlmostEqual(turned[0], high, places=3)
        self.assertAlmostEqual(turned[1], wide, places=3)
        self.assertEqual(w.view.members, members)
        w.undo.undo()
        self.assertAlmostEqual(spread()[0], wide, places=3)
        before = [self.board.elements[i].x for i in pads]
        cx, _ = core.centre([self.board.elements[i] for i in members])
        w.mirror_h_action.trigger()
        after = [self.board.elements[i].x for i in pads]
        for old, new in zip(before, after, strict=True):
            self.assertAlmostEqual(new, 2 * cx - old, places=5)
        self.assertEqual(len(self.saved()), len(self.board.elements))

    def test_standard_buttons_are_russian(self):
        buttons = QMessageBox.StandardButton
        box = QMessageBox(QMessageBox.Icon.Question, "Проверка", "Проверка")
        box.setStandardButtons(buttons.Discard | buttons.Cancel | buttons.Yes | buttons.No)
        for button in (buttons.Discard, buttons.Cancel, buttons.Yes, buttons.No):
            with self.subTest(button):
                text = box.button(button).text().replace("&", "")
                self.assertRegex(text, "[А-Яа-яЁё]", text)

    def test_broken_settings_fall_back_to_defaults(self):
        settings = self.window.settings
        broken = {
            "grid": "abc",
            "pad/shape": "",
            "grid/visible": "maybe",
            "size/pad": "1.6",
            "favourites/smd": "1;2;3|x",
        }
        for key, value in broken.items():
            settings.setValue(key, value)
        try:
            window = MainWindow()
            self.assertEqual(window.view.grid, 0.1)
            self.assertEqual(window.pad_shape, 1)
            self.assertEqual(len(window.pad_size.boxes), 2)
            self.assertEqual(window.smd_size.favourites[0], (0.3, 0.3))
            window.close()
        finally:
            for key in broken:
                settings.remove(key)

    def test_new_project_add_and_rename_board(self):
        w = self.window
        dialog = NewBoardDialog(w, w.settings)
        dialog.kinds.button(1).setChecked(True)
        dialog.rect_w.setValue(50)
        dialog.rect_h.setValue(30)
        dialog.rect_margin.setValue(5)
        w.start_project(core.new_project(dialog.board()), None)
        self.assertEqual(w.windowTitle(), f"Cuvero {VERSION} — Новый проект")
        self.assertEqual((w.boards[0].width, w.boards[0].height), (60, 40))
        dialog.kinds.button(2).setChecked(True)
        dialog.name.setText("Круглая")
        w.undo.push(AddBoard(w, dialog.board()))
        self.assertEqual(w.board_select.count(), 2)
        self.assertEqual(w.board_select.currentIndex(), 1)
        w.undo.undo()
        self.assertEqual(len(w.boards), 1)
        w.undo.redo()
        path = Path(self.temp.name) / "new.lay6"
        w.save_copy(path)
        self.assertEqual(w.path, path)
        boards = core.parse_project(path.read_bytes()).boards
        self.assertEqual([b.name for b in boards], ["Новая плата", "Круглая"])


if __name__ == "__main__":
    unittest.main()
