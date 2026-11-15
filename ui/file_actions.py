"""Opening and saving projects: save with backup, save as, recent files and autosave.

A mixin of the main window; it relies on the window's settings, undo stack, tabs and view.
"""

import hashlib
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDir, QIODevice, QSaveFile, QSettings, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QUndoStack
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QStyle,
    QTabBar,
    QWidget,
)

import core

from .board_view import BoardView
from .importers import FOREIGN, ForeignFileError, import_project, is_foreign
from .new_board_dialog import NewBoardDialog
from .project_dialogs import AutosaveDialog
from .settings import read_bool, read_int, read_str
from .style import APP_TITLE, OPTIONS

FILTER = "Платы .lay6 (*.lay6);;Все файлы (*)"
# Opening also converts boards of other programs (see importers.py).
OPEN_FILTER = (
    "Все платы (*.lay6 *.PcbDoc *.pcbdoc *.PCBDOC *.kicad_pcb *.brd *.dip);;Платы .lay6 (*.lay6);;"
    + ";;".join(FOREIGN.values())
    + ";;Все файлы (*)"
)
RECENT_LIMIT = 8
NEW_PROJECT_AUTOSAVE = "новый_проект.lay6"


def autosave_folder() -> Path:
    folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    return folder / "autosave"


def autosave_file(path: Path | None) -> Path:
    """Where the autosave copy of a project lives; one file per project path."""
    if path is None:
        return autosave_folder() / NEW_PROJECT_AUTOSAVE
    key = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:10]
    return autosave_folder() / f"{key}_{path.name}"


def backup_file(path: Path) -> Path:
    return path.with_name(path.name + ".bak")


def write_atomically(path: Path, data: bytes) -> None:
    output = QSaveFile(str(path))
    if not output.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(output.errorString())
    if output.write(data) != len(data):
        output.cancelWriting()
        raise OSError(output.errorString())
    if not output.commit():
        raise OSError(output.errorString())


class FileActions:
    # Provided by the main window.
    settings: QSettings
    undo: QUndoStack
    path: Path | None
    project: core.Project
    boards: list[core.Board]
    board_select: QTabBar
    hint: QLabel
    view: BoardView
    show_board: Callable[..., None]

    def build_file_actions(self) -> None:
        window = self.widget()
        style = window.style()
        self.recovered = False
        self.new_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_FileIcon), "Новый проект…", window
        )
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.setToolTip("Начать новый проект с новой платой (Ctrl+N)")
        self.new_action.triggered.connect(self.new_file)
        self.open_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton), "Открыть…", window
        )
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.setToolTip("Открыть файл платы (Ctrl+O)")
        self.open_action.triggered.connect(self.open_dialog)
        self.save_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), "Сохранить", window
        )
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.setToolTip(
            "Сохранить проект (Ctrl+S); прежняя версия файла остаётся в .bak"
        )
        self.save_action.triggered.connect(self.save)
        self.save_as_action = QAction("Сохранить как…", window)
        self.save_as_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.save_as_action.triggered.connect(self.save_as)
        self.autosave_action = QAction("Автосохранение…", window)
        self.autosave_action.triggered.connect(self.configure_autosave)
        self.recent_menu = QMenu("Последние файлы", window)
        self.recent_menu.aboutToShow.connect(self.fill_recent_menu)
        self.autosave_timer = QTimer(window)
        self.autosave_timer.timeout.connect(self.autosave_now)
        self.apply_autosave_settings()
        self.undo.cleanChanged.connect(lambda _clean: self.update_title())

    def widget(self) -> QWidget:
        assert isinstance(self, QWidget)
        return self

    def fill_file_menu(
        self, menu: QMenu, quit_action: QAction, extra: Callable[[QMenu], None] | None = None
    ) -> None:
        menu.addActions([self.new_action, self.open_action])
        menu.addMenu(self.recent_menu)
        menu.addSeparator()
        menu.addActions([self.save_action, self.save_as_action])
        menu.addSeparator()
        menu.addAction(self.autosave_action)
        menu.addSeparator()
        if extra is not None:
            extra(menu)
            menu.addSeparator()
        menu.addAction(quit_action)

    # --- state ------------------------------------------------------------------

    def is_modified(self) -> bool:
        return self.recovered or not self.undo.isClean()

    def update_title(self) -> None:
        name = self.path.name if self.path else "Новый проект"
        if self.path is None and getattr(self, "imported_name", None):
            name = f"{self.imported_name} (импорт, не сохранено в .lay6)"
        mark = "*" if self.is_modified() else ""
        self.widget().setWindowTitle(f"{APP_TITLE} — {mark}{name}")

    def can_discard(self) -> bool:
        if not self.is_modified():
            return True
        buttons = QMessageBox.StandardButton
        box = QMessageBox(
            QMessageBox.Icon.Question,
            "Несохранённые изменения",
            "Сохранить изменения в проекте?",
            buttons.Save | buttons.Discard | buttons.Cancel,
            self.widget(),
        )
        # Qt's own translation says "Отклонить", which does not fit this question.
        box.button(buttons.Discard).setText("Не сохранять")
        box.setDefaultButton(buttons.Save)
        answer = box.exec()
        if answer == buttons.Save:
            return self.save()
        if answer == buttons.Discard:
            self.remove_autosave()
            return True
        return False

    def start_project(self, project: core.Project, path: Path | None) -> None:
        self.path = path
        self.project = project
        self.boards = project.boards
        self.recovered = False
        self.imported_name: str | None = None
        self.undo.clear()
        self.undo.setUndoLimit(max(int(OPTIONS.get("undo_limit", 50)), 1))
        self.update_title()
        self.rebuild_tabs(core.active_board(project))

    def rebuild_tabs(self, current: int) -> None:
        """Recreate the board tabs after boards were added, removed or reordered."""
        tabs = self.board_select
        tabs.blockSignals(True)
        while tabs.count():
            tabs.removeTab(0)
        for board in self.boards:
            tabs.addTab(board.name)
        current = min(max(current, 0), len(self.boards) - 1)
        tabs.setCurrentIndex(current)
        tabs.blockSignals(False)
        self.show_board(current)

    # --- opening ----------------------------------------------------------------

    def last_folder(self) -> str:
        return str(self.path.parent) if self.path else read_str(self.settings, "last_folder")

    def new_file(self) -> None:
        if not self.can_discard():
            return
        dialog = NewBoardDialog(self.widget(), self.settings, "Новый проект")
        if dialog.exec():
            self.start_project(core.new_project(dialog.board(self.view.grid)), None)

    def open_dialog(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self.widget(), "Открыть плату", self.last_folder(), OPEN_FILTER
        )
        if filename:
            self.open_path(Path(filename))

    def open_path(self, path: Path) -> bool:
        if not self.can_discard():
            return False
        if is_foreign(path):
            return self.open_foreign(path)
        try:
            project = core.parse_project(path.read_bytes())
        except (OSError, core.LayoutError) as error:
            QMessageBox.warning(self.widget(), "Не удалось открыть плату", f"{path.name}\n{error}")
            self.forget_recent(path)
            return False
        self.start_project(project, path)
        self.remember_recent(path)
        self.offer_recovery(path)
        return True

    def open_foreign(self, path: Path) -> bool:
        """Convert a board of another program into a new, unsaved project."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            project, report = import_project(path)
        except ForeignFileError as error:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self.widget(), "Не удалось открыть плату", f"{path.name}\n{error}")
            return False
        QApplication.restoreOverrideCursor()
        self.start_project(project, None)
        # Unsaved until written as .lay6: closing asks to save it.
        self.recovered = True
        self.imported_name = path.name
        self.settings.setValue("last_folder", str(path.parent))
        self.update_title()
        self.remember_recent(path)
        self.import_report = QMessageBox(
            QMessageBox.Icon.Information, "Импорт платы", report, parent=self.widget()
        )
        self.import_report.setInformativeText(
            "Плата открыта как новый проект. Сохраните её в формате .lay6 (Ctrl+S)."
        )
        self.import_report.open()
        return True

    # --- recent files -----------------------------------------------------------

    def recent_files(self) -> list[str]:
        value = self.settings.value("recent", [])
        # INI files store a single-item list as a plain string.
        if isinstance(value, str):
            items = [value]
        elif isinstance(value, (list, tuple)):
            items = list(value)
        else:
            items = []
        return [str(item) for item in items if item][:RECENT_LIMIT]

    def remember_recent(self, path: Path) -> None:
        text = str(path.resolve())
        items = [text] + [item for item in self.recent_files() if item != text]
        self.settings.setValue("recent", items[:RECENT_LIMIT])
        self.settings.setValue("last_folder", str(path.parent))

    def forget_recent(self, path: Path) -> None:
        text = str(path.resolve())
        self.settings.setValue("recent", [item for item in self.recent_files() if item != text])

    def fill_recent_menu(self) -> None:
        self.recent_menu.clear()
        items = self.recent_files()
        if not items:
            self.recent_menu.addAction("Список пуст").setEnabled(False)
            return
        for number, item in enumerate(items, 1):
            path = Path(item)
            action = self.recent_menu.addAction(f"&{number}  {path.name}")
            action.setToolTip(QDir.toNativeSeparators(item))
            action.setStatusTip(QDir.toNativeSeparators(item))
            action.triggered.connect(lambda _=False, path=path: self.open_path(path))
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("Очистить список").triggered.connect(
            lambda: self.settings.setValue("recent", [])
        )

    # --- saving -----------------------------------------------------------------

    def current_board_index(self) -> int:
        return max(self.board_select.currentIndex(), 0)

    def write_project(self, path: Path, project: core.Project, backup: bool = True) -> None:
        """Write a project file; the previous version of that file is kept as .bak."""
        data = core.serialize(project)
        if backup and path.exists():
            shutil.copy2(path, backup_file(path))
        write_atomically(path, data)

    def save(self) -> bool:
        if self.path is None:
            return self.save_as()
        return self.save_to(self.path)

    def save_as(self) -> bool:
        suggested = (
            self.path
            if self.path is not None
            else Path(read_str(self.settings, "last_folder")) / f"{self.boards[0].name}.lay6"
        )
        name, _ = QFileDialog.getSaveFileName(
            self.widget(), "Сохранить как", str(suggested), FILTER
        )
        if not name:
            return False
        path = Path(name)
        if path.suffix.lower() != ".lay6":
            path = path.with_name(path.name + ".lay6")
        return self.save_to(path)

    def save_to(self, path: Path) -> bool:
        """Save the project as path and keep working on that file."""
        self.project.trailer = core.with_active_board(
            self.project, self.current_board_index()
        ).trailer
        old_autosave = autosave_file(self.path)
        try:
            self.write_project(path, self.project)
        except (OSError, core.LayoutError, OverflowError) as error:
            QMessageBox.warning(self.widget(), "Ошибка сохранения", f"{path.name}\n{error}")
            return False
        old_autosave.unlink(missing_ok=True)
        self.path = path
        self.recovered = False
        self.undo.setClean()
        self.update_title()
        self.remember_recent(path)
        self.hint.setText(f"Сохранено: {path.name}")
        return True

    def save_copy(self, path: Path) -> None:
        """Write the project to another file without switching to it (used by tests)."""
        if self.path is not None and (
            path.resolve() == self.path.resolve() or (path.exists() and path.samefile(self.path))
        ):
            raise core.LayoutError("Укажите новое имя для копии проекта")
        self.write_project(path, self.project, backup=False)
        if self.path is None:
            self.path = path
        self.recovered = False
        self.undo.setClean()
        self.update_title()
        self.hint.setText(f"Сохранено: {path.name}")

    # --- autosave ---------------------------------------------------------------

    def apply_autosave_settings(self) -> None:
        if read_bool(self.settings, "autosave/enabled", True):
            self.autosave_timer.start(read_int(self.settings, "autosave/minutes", 5) * 60_000)
        else:
            self.autosave_timer.stop()

    def configure_autosave(self) -> None:
        dialog = AutosaveDialog(
            self.widget(),
            read_bool(self.settings, "autosave/enabled", True),
            read_int(self.settings, "autosave/minutes", 5),
        )
        if dialog.exec():
            self.settings.setValue("autosave/enabled", dialog.enabled.isChecked())
            self.settings.setValue("autosave/minutes", dialog.minutes.value())
            self.apply_autosave_settings()

    def autosave_now(self) -> bool:
        """Write a recovery copy of a modified project; True when one was written."""
        if not self.is_modified():
            return False
        target = autosave_file(self.path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            write_atomically(target, core.serialize(self.project))
        except (OSError, core.LayoutError, OverflowError) as error:
            self.hint.setText(f"Автосохранение не удалось: {error}")
            return False
        self.hint.setText(f"Автосохранение: {datetime.now():%H:%M}")
        return True

    def remove_autosave(self) -> None:
        autosave_file(self.path).unlink(missing_ok=True)

    def offer_recovery(self, path: Path | None) -> bool:
        """Offer an autosave copy that is newer than the project file; True if restored."""
        copy = autosave_file(path)
        if not copy.exists():
            return False
        if path is not None and path.exists() and copy.stat().st_mtime <= path.stat().st_mtime:
            copy.unlink(missing_ok=True)
            return False
        when = datetime.fromtimestamp(copy.stat().st_mtime)
        name = path.name if path else "нового проекта"
        answer = QMessageBox.question(
            self.widget(),
            "Восстановление",
            f"Найдена автосохранённая копия {name} от {when:%d.%m.%Y %H:%M}, "
            "новее сохранённого файла.\nВосстановить несохранённые изменения?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            copy.unlink(missing_ok=True)
            return False
        try:
            project = core.parse_project(copy.read_bytes())
        except (OSError, core.LayoutError) as error:
            QMessageBox.warning(self.widget(), "Не удалось восстановить", str(error))
            return False
        self.start_project(project, path)
        self.recovered = True
        self.update_title()
        self.hint.setText("Восстановлены несохранённые изменения. Сохраните проект (Ctrl+S)")
        return True
