"""Stage 2 in the window: saving, recent files, autosave, boards and project information."""

import shutil
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QMessageBox

import core
from tests.ui_base import ROOT, WindowTestCase
from ui.commands import InsertBoard, ReplaceBoard, SetProjectInfo
from ui.file_actions import autosave_file, backup_file
from ui.main_window import MainWindow

HLDI = ROOT / "Samples" / "HLDI_ALL_PCB.lay6"
YES = QMessageBox.StandardButton.Yes


class ProjectTest(WindowTestCase):
    def working_copy(self, source: Path = HLDI) -> Path:
        """A copy of a sample in the temporary folder, opened in the window."""
        path = Path(self.temp.name) / f"work_{self._testMethodName}.lay6"
        shutil.copy2(source, path)
        backup_file(path).unlink(missing_ok=True)
        self.assertTrue(self.window.open_path(path))
        self.board = self.window.boards[0]
        return path

    def add_pad(self):
        self.window.add_element("pad", [(3.0, -3.0)])

    def test_title_marks_unsaved_changes(self):
        w = self.window
        self.working_copy()
        self.assertNotIn("*", w.windowTitle())
        self.add_pad()
        self.assertIn("— *", w.windowTitle())
        w.undo.undo()
        self.assertNotIn("*", w.windowTitle())

    def test_save_keeps_a_backup(self):
        w = self.window
        path = self.working_copy()
        original = path.read_bytes()
        self.add_pad()
        self.assertTrue(w.save())
        self.assertEqual(backup_file(path).read_bytes(), original)
        saved = core.parse_project(path.read_bytes())
        self.assertEqual(len(saved.boards[0].elements), len(self.board.elements))
        self.assertTrue(w.undo.isClean())

    def test_save_to_switches_file_and_remembers_it(self):
        w = self.window
        self.working_copy()
        other = Path(self.temp.name) / "renamed.lay6"
        self.assertTrue(w.save_to(other))
        self.assertEqual(w.path, other)
        self.assertEqual(w.recent_files()[0], str(other.resolve()))
        self.assertIn("renamed.lay6", w.windowTitle())

    def test_active_board_is_saved_and_restored(self):
        w = self.window
        path = self.working_copy()
        w.board_select.setCurrentIndex(2)
        self.add_pad()
        w.save()
        self.assertEqual(core.active_board(core.parse_project(path.read_bytes())), 2)
        again = MainWindow()
        again.open_path(path)
        self.assertEqual(again.board_select.currentIndex(), 2)
        again.close()

    def test_recent_files_order_and_limit(self):
        w = self.window
        w.settings.setValue("recent", [])
        paths = [Path(self.temp.name) / f"r{i}.lay6" for i in range(10)]
        for path in paths:
            w.remember_recent(path)
        recent = w.recent_files()
        self.assertEqual(len(recent), 8)
        self.assertEqual(recent[0], str(paths[-1].resolve()))
        w.remember_recent(paths[5])
        self.assertEqual(w.recent_files()[0], str(paths[5].resolve()))

    def test_autosave_and_recovery(self):
        w = self.window
        path = self.working_copy()
        self.add_pad()
        count = len(self.board.elements)
        self.assertTrue(w.autosave_now())
        copy = autosave_file(path)
        self.assertTrue(copy.exists())
        self.assertNotEqual(copy.parent, path.parent)  # never next to the user's file
        w.undo.setClean()  # simulate a crash: the file itself was not saved
        again = MainWindow()
        with mock.patch.object(QMessageBox, "question", return_value=YES):
            again.open_path(path)
        self.assertTrue(again.recovered)
        self.assertTrue(again.is_modified())
        self.assertEqual(len(again.boards[0].elements), count)
        self.assertTrue(again.save())
        self.assertFalse(copy.exists())
        again.close()

    def test_declined_recovery_removes_the_copy(self):
        w = self.window
        path = self.working_copy()
        self.add_pad()
        w.autosave_now()
        w.undo.setClean()
        again = MainWindow()
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            again.open_path(path)
        self.assertFalse(again.recovered)
        self.assertFalse(autosave_file(path).exists())
        again.close()

    def test_board_copy_move_delete_and_undo(self):
        w = self.window
        self.working_copy()
        names = [b.name for b in w.boards]
        w.board_select.setCurrentIndex(1)
        w.copy_board()
        self.assertEqual(w.boards[2].name, f"{names[1]} (копия)")
        self.assertEqual(len(w.boards[2].elements), len(w.boards[1].elements))
        w.move_board("first")
        self.assertEqual(w.boards[0].name, f"{names[1]} (копия)")
        self.assertEqual(w.board_select.currentIndex(), 0)
        with mock.patch.object(QMessageBox, "question", return_value=YES):
            w.delete_board()
        self.assertEqual([b.name for b in w.boards], names)
        for _ in range(3):
            w.undo.undo()
        self.assertEqual([b.name for b in w.boards], names)
        self.assertEqual(w.board_select.count(), len(names))

    def test_insert_board_after_current(self):
        w = self.window
        self.working_copy()
        w.board_select.setCurrentIndex(0)
        board = core.board_from_dialog("Вставка", "empty", 50, 40)
        w.undo.push(InsertBoard(w, 1, board))
        self.assertEqual(w.boards[1].name, "Вставка")
        self.assertEqual(w.board_select.tabText(1), "Вставка")
        self.assertEqual(w.board_select.currentIndex(), 1)

    def test_board_settings_and_multilayer(self):
        w = self.window
        path = self.working_copy()
        old = w.boards[0]
        new = core.board_settings(old, "Основная", 90, 85, True)
        w.undo.push(ReplaceBoard(w, 0, old, new, "Настройка платы"))
        self.assertFalse(w.layer_bar.checks[5].isHidden())  # I1 is offered now
        self.assertEqual(w.board_select.tabText(0), "Основная")
        w.save()
        board = core.parse_project(path.read_bytes()).boards[0]
        self.assertEqual(
            (board.name, board.width, board.height, board.multilayer), ("Основная", 90, 85, True)
        )

    def test_project_info_is_saved_and_undoable(self):
        w = self.window
        path = self.working_copy()
        info = core.ProjectInfo("Проект", "Автор", "Фирма", "Первая строка\nВторая")
        w.undo.push(SetProjectInfo(w, info))
        w.save()
        self.assertEqual(core.project_info(core.parse_project(path.read_bytes())), info)
        w.undo.undo()
        self.assertEqual(core.project_info(w.project), core.ProjectInfo())

    def test_delete_objects_outside_the_board(self):
        w = self.window
        self.working_copy()
        board = w.boards[0]
        count = len(board.elements)
        w.add_element("pad", [(board.width + 20, -5.0)])
        w.delete_outside()
        self.assertEqual(len(board.elements), count)
        w.undo.undo()
        self.assertEqual(len(board.elements), count + 1)

    def test_load_boards_and_save_one_board(self):
        w = self.window
        self.working_copy(ROOT / "Samples" / "motor ir2101.lay6")
        others = core.parse_project(HLDI.read_bytes()).boards
        w.insert_boards(others[1:3], "Платы из файла")
        self.assertEqual(len(w.boards), 3)
        w.undo.undo()  # one step for the whole import
        self.assertEqual(len(w.boards), 1)
        w.undo.redo()
        target = Path(self.temp.name) / "one_board.lay6"
        w.board_select.setCurrentIndex(2)
        with mock.patch(
            "ui.board_actions.QFileDialog.getSaveFileName", return_value=(str(target), "")
        ):
            w.save_board()
        saved = core.parse_project(target.read_bytes())
        self.assertEqual([b.name for b in saved.boards], [others[2].name])


if __name__ == "__main__":
    unittest.main()
