"""File menu output and import: Gerber, drill data, milling, images, printing, hole list."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QAction, QColor, QPainter
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import (
    QFileDialog,
    QGraphicsScene,
    QMenu,
    QMessageBox,
)

import core
from core import drill, gerber_import

from .commands import InsertBoard, ReplaceBoard
from .export_dialogs import (
    DrillDialog,
    GerberDialog,
    HoleListDialog,
    ImageDialog,
    save_message,
    scene_image,
)
from .file_actions import FileActions
from .import_dialog import GerberImportDialog
from .milling import MillingDialog
from .printing import PrintDialog
from .render import draw_board
from .style import BACKGROUND


class OutputActions(FileActions):
    """Mixed into the main window: actions of the export and import menu items."""

    # Provided by the main window.
    current_board_index: Callable[[], int]
    mask_shown: Callable[[], bool]
    mask_side: Callable[[], int | None]
    transparent_action: QAction
    groups: dict

    def build_output_actions(self):
        def action(text, slot, tip=""):
            item = QAction(text, self.widget())
            item.triggered.connect(slot)
            if tip:
                item.setStatusTip(tip)
            return item

        self.gerber_action = action(
            "Экспорт &Gerber…", self.export_gerber, "Файлы Gerber X2 для производства"
        )
        self.drill_action = action("Данные сверловки (&Excellon)…", self.export_drill)
        self.milling_action = action("&Фрезеровка изоляции (HPGL, *.plt)…", self.export_milling)
        self.image_actions = [
            action(
                f"{name} (*.{suffix})…", lambda _=False, suffix=suffix: self.export_image(suffix)
            )
            for name, suffix in (("BMP", "bmp"), ("JPG", "jpg"), ("PNG", "png"), ("SVG", "svg"))
        ]
        self.printer_setup_action = action("Настройка &принтера…", self.printer_setup)
        self.print_action = action("&Печать…", self.print_board)
        self.print_action.setShortcut("Ctrl+P")
        self.import_gerber_action = action("Импорт &Gerber…", self.import_gerber)
        self.holes_action = action("Список &отверстий…", self.show_holes)

    def fill_output_menu(self, menu: QMenu) -> None:
        menu.addAction(self.import_gerber_action)
        export = menu.addMenu("&Экспорт")
        export.addActions([self.gerber_action, self.drill_action])
        export.addSeparator()
        export.addAction(self.milling_action)
        export.addSeparator()
        export.addActions(self.image_actions)
        menu.addSeparator()
        menu.addActions([self.printer_setup_action, self.print_action])

    # --- helpers ---------------------------------------------------------------------

    def project_name(self) -> str:
        return self.path.stem if self.path else "Новый проект"

    def output_folder(self) -> Path:
        return self.path.parent if self.path else Path.home()

    def current_board(self) -> core.Board:
        return self.boards[self.current_board_index()]

    # --- export ----------------------------------------------------------------------

    def export_gerber(self):
        dialog = GerberDialog(
            self.widget(),
            self.settings,
            self.current_board(),
            self.project_name(),
            len(self.boards),
            self.output_folder(),
        )
        dialog.exec()
        dialog.remember()

    def export_drill(self):
        board = self.current_board()
        if not core.holes(board):
            QMessageBox.information(self.widget(), "Сверловка", "На плате нет отверстий.")
            return
        dialog = DrillDialog(self.widget(), self.settings)
        if not dialog.exec():
            return
        dialog.remember()
        name = drill.drill_file_name(self.project_name(), board.name, len(self.boards))
        start = str(self.output_folder() / name)
        path, _ = QFileDialog.getSaveFileName(
            self.widget(), "Сохранить сверловку", start, "Excellon (*.DRL *.drl);;Все файлы (*)"
        )
        if not path:
            return
        try:
            Path(path).write_bytes(drill.excellon(board, dialog.options()).encode("ascii"))
        except OSError as error:
            QMessageBox.warning(self.widget(), "Не удалось записать файл", str(error))
            return
        save_message(self, [path])

    def export_milling(self):
        board = self.current_board()
        dialog = MillingDialog(self.widget(), self.settings, board)
        if not dialog.exec():
            return
        dialog.remember()
        start = str(self.output_folder() / f"{self.project_name()}.plt")
        path, _ = QFileDialog.getSaveFileName(
            self.widget(), "Сохранить фрезеровку", start, "HPGL (*.plt);;Все файлы (*)"
        )
        if not path:
            return
        try:
            written = dialog.write(Path(path))
        except OSError as error:
            QMessageBox.warning(self.widget(), "Не удалось записать файлы", str(error))
            return
        save_message(self, written)

    def board_scene(self) -> tuple[QGraphicsScene, QRectF]:
        """A scene of the current board with the layers visible on screen."""
        board = self.current_board()
        scene = QGraphicsScene()
        groups, _ = draw_board(scene, board, self.mask_side(), self.transparent_action.isChecked())
        for layer, group in groups.items():
            shown = self.groups.get(layer)
            group.setVisible(shown.isVisible() if shown is not None else True)
        return scene, QRectF(0, 0, board.width, board.height)

    def printer_setup(self):
        from PySide6.QtPrintSupport import QPageSetupDialog

        QPageSetupDialog(self.printer(), self.widget()).exec()

    def printer(self):
        if getattr(self, "_printer", None) is None:
            from PySide6.QtPrintSupport import QPrinter

            self._printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        return self._printer

    def export_image(self, suffix="png"):
        board = self.current_board()
        dialog = ImageDialog(self.widget(), self.settings, board.width, board.height)
        if not dialog.exec():
            return
        dialog.remember()
        start = str(self.output_folder() / f"{self.project_name()}.{suffix}")
        path, _ = QFileDialog.getSaveFileName(
            self.widget(), "Сохранить изображение", start, f"{suffix.upper()} (*.{suffix})"
        )
        if not path:
            return
        scene, source = self.board_scene()
        size = dialog.image_size()
        if path.lower().endswith(".svg"):
            generator = QSvgGenerator()
            generator.setFileName(path)
            generator.setSize(QSize(round(board.width * 10), round(board.height * 10)))
            generator.setViewBox(QRectF(0, 0, board.width * 10, board.height * 10))
            generator.setTitle(board.name)
            painter = QPainter(generator)
            painter.fillRect(QRectF(0, 0, board.width * 10, board.height * 10), BACKGROUND)
            scene.render(painter, QRectF(0, 0, board.width * 10, board.height * 10), source)
            painter.end()
        else:
            image = scene_image(scene, source, size, dialog.mono.isChecked(), QColor(BACKGROUND))
            image.setDotsPerMeterX(round(dialog.dpi() / 0.0254))
            image.setDotsPerMeterY(round(dialog.dpi() / 0.0254))
            if not image.save(path):
                QMessageBox.warning(self.widget(), "Не удалось сохранить", path)
                return
        save_message(self, [path])

    def print_board(self):
        dialog = PrintDialog(
            self.widget(), self.settings, self.current_board(), self.project_name()
        )
        dialog.exec()
        dialog.remember()

    def show_holes(self):
        HoleListDialog(self.widget(), self.current_board()).exec()

    # --- import ----------------------------------------------------------------------

    def import_gerber(self):
        dialog = GerberImportDialog(self.widget(), self.settings)
        if not dialog.exec():
            return
        self.settings.setValue("import/current", dialog.current.isChecked())
        try:
            layers = dialog.layers()
            holes = dialog.holes()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self.widget(), "Не удалось прочитать файлы", str(error))
            return
        if not layers and not holes:
            return
        if dialog.current.isChecked():
            index = self.current_board_index()
            board = self.current_board()
            ox, oy = core.board_origin(board)
        else:
            left, bottom, right, top = gerber_import.bounds_of(layers.values(), holes)
            margin = 2.0
            width, height = right - left + 2 * margin, top - bottom + 2 * margin
            board = core.board_from_dialog("Импорт Gerber", "empty", max(width, 5), max(height, 5))
            # Keep the Gerber coordinates as displayed coordinates of the new board.
            ox, oy = margin - left, -height + margin - bottom
            board = core.with_origin(board, ox, oy)
            index = None
        shifted = [(x + ox, y + oy, d) for x, y, d in holes]
        pad_holes = shifted if dialog.vias.isChecked() else []
        done: set[tuple[float, float]] = set()
        elements: list[core.Element] = []
        skipped = 0
        planes = []
        for layer, parsed in layers.items():
            result = gerber_import.import_layer(
                board, parsed, layer, pad_holes, (ox, oy), done, dialog.join.isChecked()
            )
            elements += result.elements
            skipped += result.skipped
            if result.plane:
                planes.append(layer)
        elements += gerber_import.bare_holes(board, shifted, done)
        new = replace(board, elements=list(board.elements) + elements)
        for layer in planes:
            new = core.with_plane(new, layer, True)
        if index is None:
            self.undo.push(InsertBoard(self, len(self.boards), new, "Импорт Gerber"))
        else:
            self.undo.push(ReplaceBoard(self, index, board, new, "Импорт Gerber"))
        note = f"Импортировано объектов: {len(elements)}."
        if planes:
            note += (
                " Автозаливка включена на слоях: "
                + ", ".join({1: "C1", 3: "C2", 5: "I1", 6: "I2"}[p] for p in planes)
                + "."
            )
        if skipped:
            note += f" Пропущено частей без аналога среди объектов: {skipped}."
        QMessageBox.information(self.widget(), "Импорт Gerber", note)
