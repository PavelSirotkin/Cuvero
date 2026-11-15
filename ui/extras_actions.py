"""Stage 8 actions of the main window: footprint wizard, copies in a grid or a circle,
Text-IO import and export, external programs (plugins), autorouting, general settings
and the Ctrl+1..9 grid keys.
"""

import contextlib
import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCursor, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import core

from .export_dialogs import ok_cancel
from .options import OptionsDialog, apply_options
from .router import RouteBar, route, routed_board, wire_at
from .settings import read_float, read_str
from .style import COPPER, OPTIONS
from .wizards import FootprintWizard, TileDialog

ENCODING = "cp1251"
PLUGIN_COUNT = 10
HOTKEY_GRIDS = (0.05, 0.1, 0.25, 0.5, 0.635, 1.0, 1.27, 2.54, 5.08)


def text_bytes(board: core.Board) -> bytes:
    return core.export_text(board).encode(ENCODING, errors="replace")


def replaced_from_text(board: core.Board, text: str) -> core.Board:
    """The board whose objects are all replaced by those in the Text-IO text."""
    empty = replace(board, elements=[])
    return replace(board, elements=core.import_text(empty, text))


class PluginDialog(QDialog):
    """List of external programs started with the board as a Text-IO file."""

    def __init__(self, parent, settings):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Внешние программы")
        self.entries = plugins(settings)
        layout = QVBoxLayout(self)
        body = QHBoxLayout()
        layout.addLayout(body)
        self.list = QListWidget()
        self.list.setFixedWidth(180)
        body.addWidget(self.list)
        form = QFormLayout()
        body.addLayout(form, 1)
        self.name = QLineEdit()
        self.program = QLineEdit()
        browse = QPushButton("…")
        browse.setFixedWidth(28)
        browse.clicked.connect(self.browse)
        line = QHBoxLayout()
        line.addWidget(self.program, 1)
        line.addWidget(browse)
        self.arguments = QLineEdit()
        self.arguments.setPlaceholderText("$FILE")
        self.arguments.setToolTip(
            "$FILE заменяется именем файла Text-IO; без него имя файла добавляется в конец"
        )
        form.addRow("Название:", self.name)
        form.addRow("Программа:", line)
        form.addRow("Параметры:", self.arguments)
        for k in range(PLUGIN_COUNT):
            self.list.addItem(self.entries[k][0] or f"{k + 1}: (пусто)")
        self.list.currentRowChanged.connect(self.show_entry)
        for field in (self.name, self.program, self.arguments):
            field.textEdited.connect(self.store_entry)
        self.list.setCurrentRow(0)
        layout.addWidget(ok_cancel(self))
        self.resize(560, 260)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Программа", self.program.text())
        if path:
            self.program.setText(path)
            self.store_entry()

    def show_entry(self, row: int):
        name, program, arguments = self.entries[row]
        self.name.setText(name)
        self.program.setText(program)
        self.arguments.setText(arguments)

    def store_entry(self, *_args):
        row = self.list.currentRow()
        self.entries[row] = (self.name.text(), self.program.text(), self.arguments.text())
        self.list.item(row).setText(self.name.text() or f"{row + 1}: (пусто)")

    def remember(self):
        for k, (name, program, arguments) in enumerate(self.entries):
            self.settings.setValue(f"plugins/{k}/name", name)
            self.settings.setValue(f"plugins/{k}/program", program)
            self.settings.setValue(f"plugins/{k}/arguments", arguments)


def plugins(settings) -> list[tuple[str, str, str]]:
    return [
        (
            read_str(settings, f"plugins/{k}/name", ""),
            read_str(settings, f"plugins/{k}/program", ""),
            read_str(settings, f"plugins/{k}/arguments", ""),
        )
        for k in range(PLUGIN_COUNT)
    ]


def plugin_command(program: str, arguments: str, path: str) -> list[str]:
    words = arguments.split() if arguments.strip() else []
    if any("$FILE" in word for word in words):
        words = [word.replace("$FILE", path) for word in words]
    else:
        words.append(path)
    return [program, *words]


class ExtrasActions:
    """Mixed into the main window."""

    # Provided by the main window.
    settings: Any
    view: Any
    hint: Any
    undo: Any
    boards: list
    overview: Any
    current_board: Callable[[], core.Board]
    current_board_index: Callable[[], int]
    selection_objects: Callable[[], list]
    add_objects: Callable[[list, str], None]
    replace_current_board: Callable[[core.Board, str], None]
    show_board: Callable[..., None]
    set_grid: Callable[[float], None]
    set_units: Callable[[bool], None]
    apply_autosave_settings: Callable[[], None]
    addAction: Callable[[QAction], None]
    widget: Callable[[], QWidget]

    def build_extras_actions(self) -> None:
        self.wizard_action = QAction("Мастер посадочных мест…", self.widget())
        self.wizard_action.setToolTip("Ряды и окружности площадок по заданному шагу")
        self.wizard_action.triggered.connect(self.footprint_wizard)
        self.tile_action = QAction("Размножить…", self.widget())
        self.tile_action.setToolTip("Копии выделенного решёткой или по окружности")
        self.tile_action.triggered.connect(self.tile_selection)
        self.textio_import_action = QAction("Text-IO: импорт объектов…", self.widget())
        self.textio_import_action.triggered.connect(self.textio_import)
        self.textio_export_action = QAction("Text-IO: экспорт объектов…", self.widget())
        self.textio_export_action.triggered.connect(self.textio_export)
        self.plugins_action = QAction("Настроить внешние программы…", self.widget())
        self.plugins_action.triggered.connect(self.configure_plugins)
        self.options_action = QAction("Общие настройки…", self.widget())
        self.options_action.triggered.connect(self.general_settings)
        self.grid_key_actions = []
        for k in range(9):
            action = QAction(self.widget())
            action.setShortcut(QKeySequence(f"Ctrl+{k + 1}"))
            action.triggered.connect(lambda _=False, k=k: self.grid_hotkey(k))
            self.addAction(action)
            self.grid_key_actions.append(action)
        self.route_bar = RouteBar(self.settings)
        self.route_bar.hide()

    def fill_plugin_menu(self, menu) -> None:
        menu.clear()
        for k, (name, program, _arguments) in enumerate(plugins(self.settings)):
            if program:
                action = menu.addAction(name or Path(program).name)
                action.triggered.connect(lambda _=False, k=k: self.run_plugin(k))
        if menu.actions():
            menu.addSeparator()
        menu.addAction(self.plugins_action)

    # --- wizard and copies -----------------------------------------------------------

    def placement_point(self) -> tuple[float, float]:
        """Under the cursor when it is over the board view, else the view centre."""
        cursor = self.view.viewport().mapFromGlobal(QCursor.pos())
        if not self.view.viewport().rect().contains(cursor):
            cursor = self.view.viewport().rect().center()
        target = self.view.mapToScene(cursor)
        x, y = target.x(), -target.y()
        if self.view.grid:
            x = round(x / self.view.grid) * self.view.grid
            y = round(y / self.view.grid) * self.view.grid
        return x, y

    def footprint_wizard(self) -> None:
        if not self.boards:
            return
        dialog = FootprintWizard(self.widget(), self.settings)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        dialog.remember()
        fp = dialog.footprint()
        layer = self.view.active_layer
        if fp.smd and layer not in (1, 3):
            layer = 1
        x, y = self.placement_point()
        pads = core.footprint(self.current_board(), fp, x, y, layer if fp.smd else 3)
        self.add_objects(pads, f"Мастер: площадок {len(pads)}")

    def tile_selection(self) -> None:
        objects = self.selection_objects()
        if not objects:
            self.hint.setText("Сначала выделите, что размножить")
            return
        dialog = TileDialog(self.widget(), self.settings)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        dialog.remember()
        copies = dialog.copies(self.current_board(), objects)
        if copies:
            self.add_objects(copies, f"Размножение: объектов {len(copies)}")

    # --- Text-IO -----------------------------------------------------------------------

    def textio_export(self) -> None:
        if not self.boards:
            return
        folder = read_str(self.settings, "textio/folder", "")
        path, _ = QFileDialog.getSaveFileName(
            self.widget(), "Text-IO: экспорт", folder, "Text-IO (*.txt);;Все файлы (*)"
        )
        if not path:
            return
        Path(path).write_bytes(text_bytes(self.current_board()))
        self.settings.setValue("textio/folder", str(Path(path).parent))
        self.hint.setText(f"Объекты платы записаны в {Path(path).name}")

    def textio_import(self) -> None:
        if not self.boards:
            return
        folder = read_str(self.settings, "textio/folder", "")
        path, _ = QFileDialog.getOpenFileName(
            self.widget(), "Text-IO: импорт", folder, "Text-IO (*.txt);;Все файлы (*)"
        )
        if not path:
            return
        self.settings.setValue("textio/folder", str(Path(path).parent))
        try:
            text = Path(path).read_bytes().decode(ENCODING, errors="replace")
            objects = core.import_text(self.current_board(), text)
        except (OSError, core.TextIOError) as error:
            QMessageBox.warning(self.widget(), "Text-IO", str(error))
            return
        if not objects:
            self.hint.setText("В файле нет объектов")
            return
        self.view.start_placing(objects)
        self.hint.setText(
            f"Text-IO: объектов {len(objects)} — щелчок кладёт их на плату, Esc — отмена"
        )

    def put_down(self, objects) -> None:
        """Objects carried on the cursor were put down by a click."""
        self.add_objects(objects, f"Text-IO: объектов {len(objects)}")

    # --- plugins -----------------------------------------------------------------------

    def configure_plugins(self) -> None:
        dialog = PluginDialog(self.widget(), self.settings)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dialog.remember()

    def run_plugin(self, k: int) -> None:
        if not self.boards:
            return
        name, program, arguments = plugins(self.settings)[k]
        board = self.current_board()
        original = text_bytes(board)
        handle, path = tempfile.mkstemp(prefix="cuvero_", suffix=".txt")
        try:
            with os.fdopen(handle, "wb") as file:
                file.write(original)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                subprocess.run(plugin_command(program, arguments, path), check=False)
            finally:
                QApplication.restoreOverrideCursor()
            changed = Path(path).read_bytes()
        except OSError as error:
            QMessageBox.warning(self.widget(), name or "Внешняя программа", str(error))
            return
        finally:
            with contextlib.suppress(OSError):
                os.remove(path)
        if changed == original:
            self.hint.setText(f"{name or program}: плата не изменена")
            return
        try:
            new = replaced_from_text(board, changed.decode(ENCODING, errors="replace"))
        except core.TextIOError as error:
            QMessageBox.warning(self.widget(), name or "Внешняя программа", str(error))
            return
        self.replace_current_board(new, name or "Внешняя программа")
        self.hint.setText(f"{name or program}: плата обновлена (Ctrl+Z отменяет)")

    # --- autorouter --------------------------------------------------------------------

    def route_click(self, position) -> None:
        board = self.view.board
        if board is None:
            return
        reach = 6 / max(abs(self.view.transform().m11()), 1e-9)
        wire = wire_at(board, position, reach)
        if wire is None:
            self.route_bar.status.setText("Щёлкните по воздушной линии")
            return
        self.route_between(*wire)

    def route_pads(self, a: int, b: int) -> None:
        """Pads joined by dragging in the autorouter tool."""
        self.route_between(a, b)

    def route_between(self, a: int, b: int) -> None:
        board = self.view.board
        wire = (a, b)
        layer = self.view.active_layer if self.view.active_layer in COPPER else 3
        width = self.route_bar.width_box.value()
        self.route_bar.current_grid = self.view.grid or self.route_bar.current_grid
        self.route_bar.remember()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = route(
                board,
                *wire,
                layer,
                width,
                self.route_bar.clearance_box.value(),
                self.route_bar.grid(),
            )
        finally:
            QApplication.restoreOverrideCursor()
        self.route_bar.status.setText(result.message)
        if result.points is None:
            return
        new = routed_board(board, *wire, layer, result.points, width)
        self.replace_current_board(new, "Автотрассировка")

    def show_route_bar(self, mode: str) -> None:
        self.route_bar.setVisible(mode == "autoroute")
        if mode == "autoroute":
            self.route_bar.current_grid = self.view.grid or self.route_bar.current_grid
            self.route_bar.update_grid()
            self.route_bar.status.setText("Готов: щёлкните по воздушной линии")

    # --- settings ----------------------------------------------------------------------

    def general_settings(self) -> None:
        dialog = OptionsDialog(self.widget(), self.settings)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        dialog.remember()
        apply_options(self.settings)
        self.set_units(dialog.unit.currentIndex() == 1)
        self.apply_undo_limit()
        self.overview.setVisible(OPTIONS.get("show_overview", True))
        self.apply_autosave_settings()
        if self.boards:
            self.show_board(self.current_board_index(), refit=False)

    def apply_undo_limit(self) -> None:
        """QUndoStack takes a new limit only while it is empty."""
        if self.undo.count() == 0:
            self.undo.setUndoLimit(max(int(OPTIONS.get("undo_limit", 50)), 1))

    def grid_hotkey(self, k: int) -> None:
        value = read_float(self.settings, f"options/hotkey{k + 1}", HOTKEY_GRIDS[k])
        self.set_grid(value)
        self.hint.setText(f"Сетка {value:g} мм (Ctrl+{k + 1})".replace(".", ","))
