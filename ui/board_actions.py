"""Board and project commands: add, copy, delete, reorder, settings, import, export, info.

A mixin of the main window, built on the file actions.
"""

from pathlib import Path

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMenu, QMessageBox

import core

from .commands import (
    DeleteElements,
    InsertBoard,
    MoveBoard,
    RemoveBoard,
    RenameBoard,
    ReplaceBoard,
    SetProjectInfo,
)
from .file_actions import FILTER, FileActions
from .new_board_dialog import NewBoardDialog
from .project_dialogs import BoardPickDialog, BoardSettingsDialog, ProjectInfoDialog

NAME_LIMIT = 30


def copy_name(name: str, names: list[str]) -> str:
    """'Плата (копия)', then 'Плата (копия 2)' and so on, within the 30-character limit."""
    for number in range(1, 1000):
        suffix = " (копия)" if number == 1 else f" (копия {number})"
        candidate = name[: NAME_LIMIT - len(suffix)] + suffix
        if candidate not in names:
            return candidate
    return name


class BoardActions(FileActions):
    def build_board_actions(self) -> None:
        window = self.widget()

        def make(text: str, slot, tip: str = "") -> QAction:
            action = QAction(text, window)
            action.triggered.connect(lambda _=False: slot())
            if tip:
                action.setToolTip(tip)
            return action

        self.add_board_action = make("Новая плата…", self.add_board, "Добавить в проект плату")
        self.board_settings_action = make(
            "Настройка платы…", self.edit_board_settings, "Имя, размер рабочего поля, слои"
        )
        self.rename_board_action = make("Переименовать плату…", self.rename_board)
        self.copy_board_action = make("Копировать плату", self.copy_board)
        self.delete_board_action = make("Удалить плату…", self.delete_board)
        self.move_first_action = make("Переместить в начало", lambda: self.move_board("first"))
        self.move_left_action = make("Переместить влево", lambda: self.move_board("left"))
        self.move_right_action = make("Переместить вправо", lambda: self.move_board("right"))
        self.move_last_action = make("Переместить в конец", lambda: self.move_board("last"))
        self.load_boards_action = make("Загрузить платы из файла…", self.load_boards)
        self.save_board_action = make("Сохранить плату в отдельный файл…", self.save_board)
        self.project_info_action = make("Сведения о проекте…", self.edit_project_info)
        self.delete_outside_action = make(
            "Удалить объекты за пределами платы",
            self.delete_outside,
            "Удалить всё, что целиком лежит за пределами рабочего поля",
        )

    def board_actions(self) -> list[QAction | None]:
        """Board commands in menu order; None marks a separator."""
        return [
            self.add_board_action,
            self.board_settings_action,
            self.rename_board_action,
            None,
            self.copy_board_action,
            self.delete_board_action,
            None,
            self.load_boards_action,
            self.save_board_action,
            None,
            self.move_first_action,
            self.move_left_action,
            self.move_right_action,
            self.move_last_action,
        ]

    def fill_board_menu(self, menu: QMenu) -> None:
        for action in self.board_actions():
            if action is None:
                menu.addSeparator()
            else:
                menu.addAction(action)

    def update_board_actions(self) -> None:
        index, count = self.current_board_index(), len(self.boards)
        self.delete_board_action.setEnabled(count > 1)
        for action in (self.move_first_action, self.move_left_action):
            action.setEnabled(index > 0)
        for action in (self.move_right_action, self.move_last_action):
            action.setEnabled(index < count - 1)

    # --- boards -----------------------------------------------------------------

    def add_board(self) -> None:
        dialog = NewBoardDialog(
            self.widget(),
            self.settings,
            "Новая плата",
            f"Плата {len(self.boards) + 1}",
            ask_position=True,
        )
        if dialog.exec():
            index = (
                self.current_board_index() + 1
                if dialog.after_current.isChecked()
                else len(self.boards)
            )
            self.undo.push(InsertBoard(self, index, dialog.board(self.view.grid)))

    def copy_board(self) -> None:
        index = self.current_board_index()
        board = self.boards[index]
        name = copy_name(board.name, [b.name for b in self.boards])
        self.undo.push(
            InsertBoard(self, index + 1, core.copied_board(board, name), f"Копия платы «{name}»")
        )

    def delete_board(self) -> None:
        if len(self.boards) < 2:
            self.hint.setText("В проекте должна остаться хотя бы одна плата")
            return
        index = self.current_board_index()
        answer = QMessageBox.question(
            self.widget(),
            "Удаление платы",
            f"Удалить плату «{self.boards[index].name}» со всеми объектами?\n"
            "Удаление можно отменить (Ctrl+Z).",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.undo.push(RemoveBoard(self, index))

    def move_board(self, where: str) -> None:
        index, last = self.current_board_index(), len(self.boards) - 1
        target = {"first": 0, "left": index - 1, "right": index + 1, "last": last}[where]
        target = min(max(target, 0), last)
        if target != index:
            self.undo.push(MoveBoard(self, index, target))

    def rename_board(self) -> None:
        index = self.current_board_index()
        old = self.boards[index]
        name, ok = QInputDialog.getText(
            self.widget(), "Переименовать плату", "Имя платы:", text=old.name
        )
        name = name.strip()[:NAME_LIMIT]
        if ok and name and name != old.name:
            self.undo.push(RenameBoard(self, index, old, core.rename_board(old, name)))

    def edit_board_settings(self) -> None:
        index = self.current_board_index()
        old = self.boards[index]
        dialog = BoardSettingsDialog(self.widget(), old)
        if dialog.exec():
            new = dialog.board(old)
            if (new.name, new.width, new.height, new.multilayer) != (
                old.name,
                old.width,
                old.height,
                old.multilayer,
            ):
                self.undo.push(ReplaceBoard(self, index, old, new, "Настройка платы"))

    def load_boards(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self.widget(), "Загрузить платы из файла", self.last_folder(), FILTER
        )
        if not filename:
            return
        path = Path(filename)
        try:
            boards = core.parse_project(path.read_bytes()).boards
        except (OSError, core.LayoutError) as error:
            QMessageBox.warning(self.widget(), "Не удалось открыть файл", f"{path.name}\n{error}")
            return
        chosen = list(range(len(boards)))
        if len(boards) > 1:
            dialog = BoardPickDialog(self.widget(), path.name, boards)
            if not dialog.exec():
                return
            chosen = dialog.chosen()
        self.insert_boards([boards[i] for i in chosen], f"Платы из «{path.name}»")

    def insert_boards(self, boards: list[core.Board], description: str) -> None:
        if not boards:
            return
        self.undo.beginMacro(description)
        for board in boards:
            self.undo.push(InsertBoard(self, len(self.boards), board))
        self.undo.endMacro()

    def save_board(self) -> None:
        index = self.current_board_index()
        board = self.boards[index]
        folder = Path(self.last_folder())
        name, _ = QFileDialog.getSaveFileName(
            self.widget(), "Сохранить плату в файл", str(folder / f"{board.name}.lay6"), FILTER
        )
        if not name:
            return
        path = Path(name)
        if path.suffix.lower() != ".lay6":
            path = path.with_name(path.name + ".lay6")
        if self.path is not None and path.exists() and path.samefile(self.path):
            QMessageBox.warning(
                self.widget(), "Сохранение платы", "Выберите другой файл: этот открыт сейчас"
            )
            return
        try:
            self.write_project(path, core.single_board_project(self.project, index))
        except (OSError, core.LayoutError, OverflowError) as error:
            QMessageBox.warning(self.widget(), "Ошибка сохранения", f"{path.name}\n{error}")
            return
        self.hint.setText(f"Плата «{board.name}» сохранена в {path.name}")

    # --- project ------------------------------------------------------------------

    def edit_project_info(self) -> None:
        old = core.project_info(self.project)
        dialog = ProjectInfoDialog(self.widget(), old)
        if dialog.exec() and dialog.info() != old:
            self.undo.push(SetProjectInfo(self, dialog.info()))

    def delete_outside(self) -> None:
        board = self.boards[self.current_board_index()]
        indices = core.outside_work_area(board)
        if not indices:
            self.hint.setText("За пределами рабочего поля объектов нет")
            return
        self.undo.push(
            DeleteElements(
                self,
                self.current_board_index(),
                indices,
                f"Удаление за пределами платы: объектов {len(indices)}",
            )
        )
