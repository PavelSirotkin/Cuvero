"""The macro library panel with preview and drag and drop."""

from pathlib import Path

from PySide6.QtCore import QDir, QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFileSystemModel,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSplitter,
    QStyle,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

import core

from .icons import tool_icon
from .render import ellipse, geometry, point
from .settings import read_bool, read_str
from .style import BACKGROUND, LAYERS, MACRO_MIME
from .widgets import PanelTitle


class MacroPreview(QGraphicsView):
    """Black preview of the selected macro; dragging it onto the board places it."""

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(BACKGROUND)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setToolTip("Предпросмотр макроса. Перетащите его на плату.")
        self.path = None
        self.side = "top"
        self.turns = 0  # quarter turns clockwise
        self.elements = []
        self.label = QLabel("Перетащите на плату", self)
        self.label.setStyleSheet("color: #c0c0c0; background: transparent;")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.label.adjustSize()
        self.label.move(
            self.width() - self.label.width() - 6, self.height() - self.label.height() - 4
        )
        self.fit()

    def fit(self):
        rect = self.scene().itemsBoundingRect()
        if not rect.isEmpty():
            margin = max(rect.width(), rect.height()) * 0.1
            self.fitInView(
                rect.adjusted(-margin, -margin, margin, margin), Qt.AspectRatioMode.KeepAspectRatio
            )

    def show_macro(self, path, elements):
        self.path, self.elements = path, elements
        self.redraw()

    def redraw(self):
        scene = self.scene()
        scene.clear()
        if not self.elements:
            return
        placed = core.strip_labels(core.place_macro(self.elements, 0, 0, self.side))
        if self.turns:
            placed = core.rotate_all(placed, -90 * self.turns)
        warnings: set[str] = set()
        for layer in (3, 4, 1, 2, 7):
            for obj in placed:
                if obj.layer != layer and not (obj.kind == core.THT and obj.plated and layer == 3):
                    continue
                path = geometry(obj, warnings)
                scene.addPath(path, QPen(Qt.PenStyle.NoPen), QColor(LAYERS[layer][1]))
                if obj.kind == core.THT and obj.inner > 0:
                    scene.addPath(
                        ellipse(point(obj.x, obj.y), obj.inner), QPen(Qt.PenStyle.NoPen), BACKGROUND
                    )
        self.fit()

    def mouseMoveEvent(self, event):
        if self.path and event.buttons() & Qt.MouseButton.LeftButton:
            data = QMimeData()
            data.setData(MACRO_MIME, f"{self.side}\n{self.turns}\n{self.path}".encode())
            drag = QDrag(self)
            drag.setMimeData(data)
            drag.exec(Qt.DropAction.CopyAction)
            return
        super().mouseMoveEvent(event)


class MacroPanel(QWidget):
    """Library of macros (.lmk) from a chosen folder, with preview and board side."""

    hidden = Signal()
    message = Signal(str)
    save_requested = Signal()

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(PanelTitle("Макросы", self.close_panel))
        self.model = QFileSystemModel(self)
        self.model.setNameFilters(["*.lmk", "*.LMK"])
        self.model.setNameFilterDisables(False)
        self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setHeaderHidden(True)
        for column in range(1, 4):
            self.tree.hideColumn(column)
        self.tree.selectionModel().currentChanged.connect(self.current_changed)
        self.empty = QLabel("Выберите папку\nс макросами (.lmk)")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        splitter = QSplitter(Qt.Orientation.Vertical)
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(self.tree)
        top_layout.addWidget(self.empty)
        splitter.addWidget(top)
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(2, 2, 2, 0)
        bottom_layout.setSpacing(2)
        self.as_component = QCheckBox("Как компонент")
        self.as_component.setToolTip(
            "Поставить макрос как компонент: его объекты перемещаются вместе"
        )
        self.as_component.setChecked(read_bool(settings, "macro/component", True))
        self.as_component.toggled.connect(lambda on: settings.setValue("macro/component", on))
        bottom_layout.addWidget(self.as_component)
        buttons = QHBoxLayout()
        buttons.setSpacing(1)
        standard = self.style().standardIcon

        def button(icon, tip, slot=None):
            tool = QToolButton()
            tool.setIcon(icon)
            tool.setIconSize(QSize(20, 20))
            tool.setToolTip(tip)
            tool.setAutoRaise(True)
            if slot is None:
                tool.setEnabled(False)
            else:
                tool.clicked.connect(slot)
            buttons.addWidget(tool)
            return tool

        button(tool_icon("folder"), "Папка с макросами…", self.choose_folder)
        button(
            standard(QStyle.StandardPixmap.SP_DialogSaveButton),
            "Сохранить выделенное как макрос…",
            self.save_requested.emit,
        )
        button(
            standard(QStyle.StandardPixmap.SP_TrashIcon),
            "Удалить выбранный макрос…",
            self.delete_macro,
        )
        button(tool_icon("rotate"), "Повернуть макрос на 90° по часовой стрелке", self.rotate)
        button(tool_icon("via"), "Переходные отверстия — пока не реализовано")
        buttons.addStretch()
        self.side_button = QToolButton()
        self.side_button.setIcon(tool_icon("macro_side"))
        self.side_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.side_button.setToolTip("Сторона платы для макроса: верх или низ (зеркально)")
        self.side_button.setAutoRaise(True)
        self.side_button.setMinimumWidth(64)
        self.side_button.clicked.connect(self.toggle_side)
        buttons.addWidget(self.side_button)
        bottom_layout.addLayout(buttons)
        self.preview = MacroPreview()
        bottom_layout.addWidget(self.preview, 1)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)
        self.set_side(read_str(settings, "macro/side", "top"))
        self.set_folder(read_str(settings, "macro/folder"))

    def close_panel(self):
        self.hide()
        self.hidden.emit()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Папка с макросами", read_str(self.settings, "macro/folder")
        )
        if folder:
            self.set_folder(folder)

    def set_folder(self, folder):
        folder = str(folder or "")
        valid = bool(folder) and Path(folder).is_dir()
        self.tree.setVisible(valid)
        self.empty.setVisible(not valid)
        if valid:
            self.settings.setValue("macro/folder", folder)
            self.tree.setRootIndex(self.model.setRootPath(folder))

    def set_side(self, side):
        self.preview.side = side if side in ("top", "bottom") else "top"
        self.side_button.setText("ВЕРХ" if self.preview.side == "top" else "НИЗ")
        self.settings.setValue("macro/side", self.preview.side)
        self.preview.redraw()

    def rotate(self):
        self.preview.turns = (self.preview.turns + 1) % 4
        self.preview.redraw()

    def folder(self):
        return read_str(self.settings, "macro/folder")

    def delete_macro(self):
        path = self.preview.path
        if path is None:
            self.message.emit("Выберите макрос в списке")
            return
        answer = QMessageBox.question(
            self, "Удалить макрос", f"Удалить файл макроса «{Path(path).name}»?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            Path(path).unlink()
        except OSError as error:
            QMessageBox.warning(self, "Не удалось удалить макрос", str(error))
            return
        self.preview.show_macro(None, [])

    def toggle_side(self):
        self.set_side("bottom" if self.preview.side == "top" else "top")

    def current_changed(self, index):
        path = Path(self.model.filePath(index))
        if not path.is_file():
            self.preview.show_macro(None, [])
            return
        try:
            elements = core.load_macro(path)
        except (OSError, core.LayoutError) as error:
            self.preview.show_macro(None, [])
            self.message.emit(f"{path.name}: {error}")
            return
        self.preview.show_macro(path, elements)
