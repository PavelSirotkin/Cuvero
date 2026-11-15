"""Selector and Components side panels, and the component list export, like the original's."""

from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import core

from .settings import read_bool, read_int, read_str
from .widgets import PanelTitle

SELECTOR_COLOR = "#e9d1e9"  # measured on the original's selector panel
SELECTOR_LIST = "#f7eef7"
KINDS = ("Все площадки", "Переходные отверстия", "SMD-площадки", "Дорожки", "Тексты")
SORTS = {
    0: ("Отверстие", "Размер", "Форма"),
    1: ("Отверстие", "Размер"),
    2: ("Размер",),
    3: ("Ширина",),
    4: ("Высота",),
}
LAYER_FILTERS = ("Только медь", "Только шелкография и контур", "Все слои")
SHAPE_NAMES = {1: "круглые", 2: "восьмиугольные", 3: "квадратные"}


def mm_text(value: float) -> str:
    return f"{value:.2f} мм".replace(".", ",")


def selector_groups(board, kind: int, sort: int, layers: int) -> dict[str, list[int]]:
    """Objects of a kind grouped by the chosen property: {caption: [indices]}."""
    copper = {1, 3, 5, 6}
    groups: dict[str, list[int]] = defaultdict(list)
    for index, obj in enumerate(board.elements):
        if core.is_hidden_label(obj):
            continue
        on_copper = obj.layer in copper
        if (layers == 0 and not on_copper) or (layers == 1 and on_copper):
            continue
        sort_name = SORTS[kind][min(sort, len(SORTS[kind]) - 1)]
        if kind in (0, 1) and obj.kind == core.THT:
            if kind == 1 and (core.component_id(obj) or not obj.plated):
                continue
            if sort_name == "Отверстие":
                key = mm_text(2 * obj.inner)
            elif sort_name == "Размер":
                key = mm_text(2 * obj.outer)
            else:
                key = SHAPE_NAMES.get(obj.shape, "продолговатые")
        elif kind == 2 and obj.kind == core.SMD:
            width, height = core.smd_size(obj)
            key = f"{width:.2f} × {height:.2f} мм".replace(".", ",")
        elif kind == 3 and obj.kind == core.LINE:
            key = mm_text(obj.width)
        elif kind == 4 and obj.kind == core.STROKE_TEXT:
            key = mm_text(obj.outer)
        else:
            continue
        groups[key].append(index)
    return dict(sorted(groups.items(), key=lambda item: _number(item[0])))


def _number(text: str) -> tuple[float, str]:
    try:
        return float(text.split()[0].replace(",", ".")), text
    except ValueError:
        return 0.0, text


class SelectorPanel(QWidget):
    hidden = Signal()
    select = Signal(object)  # list of object indices

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.board = None
        self.setObjectName("selector")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QWidget#selector {{ background: {SELECTOR_COLOR}; }}"
            f" QTreeWidget {{ background: {SELECTOR_LIST}; border: none; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(PanelTitle("Селектор", self.close_panel, color="#ffffff"))
        form = QVBoxLayout()
        form.setContentsMargins(4, 2, 4, 2)
        self.kind = QComboBox()
        self.kind.addItems(KINDS)
        self.sort = QComboBox()
        self.layers = QComboBox()
        self.layers.addItems(LAYER_FILTERS)
        for caption, combo in (
            ("Объекты:", self.kind),
            ("Сортировка:", self.sort),
            ("Слой:", self.layers),
        ):
            form.addWidget(QLabel(caption))
            form.addWidget(combo)
        layout.addLayout(form)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self.clicked)
        layout.addWidget(self.tree, 1)
        self.count = QLabel()
        self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count.setStyleSheet("font-weight: bold; padding: 3px;")
        layout.addWidget(self.count)
        self.kind.setCurrentIndex(read_int(settings, "selector/kind", 0))
        self.fill_sorts()
        self.sort.setCurrentIndex(read_int(settings, "selector/sort", 0))
        self.layers.setCurrentIndex(read_int(settings, "selector/layers", 0))
        self.kind.currentIndexChanged.connect(self.kind_changed)
        self.sort.currentIndexChanged.connect(self.refresh)
        self.layers.currentIndexChanged.connect(self.refresh)

    def close_panel(self):
        self.hide()
        self.hidden.emit()

    def fill_sorts(self):
        self.sort.blockSignals(True)
        self.sort.clear()
        self.sort.addItems(SORTS[self.kind.currentIndex()])
        self.sort.blockSignals(False)

    def kind_changed(self, *_args):
        self.fill_sorts()
        self.refresh()

    def show_board(self, board) -> None:
        self.board = board
        self.refresh()

    def refresh(self, *_args):
        self.settings.setValue("selector/kind", self.kind.currentIndex())
        self.settings.setValue("selector/sort", self.sort.currentIndex())
        self.settings.setValue("selector/layers", self.layers.currentIndex())
        self.tree.clear()
        if self.board is None:
            self.count.setText("")
            return
        groups = selector_groups(
            self.board,
            self.kind.currentIndex(),
            self.sort.currentIndex(),
            self.layers.currentIndex(),
        )
        total = 0
        for caption, indices in groups.items():
            item = QTreeWidgetItem([f"{caption}   × {len(indices)}"])
            item.setData(0, Qt.ItemDataRole.UserRole, indices)
            for index in indices:
                x, y = core.centre_of(self.board.elements[index])
                child = QTreeWidgetItem([f"X {x:.2f}  Y {y:.2f}".replace(".", ",")])
                child.setData(0, Qt.ItemDataRole.UserRole, [index])
                item.addChild(child)
            self.tree.addTopLevelItem(item)
            total += len(indices)
        self.count.setText(f"Объектов: {total}")

    def clicked(self, item, _column):
        indices = item.data(0, Qt.ItemDataRole.UserRole)
        if indices:
            self.select.emit(list(indices))


# --- components ---------------------------------------------------------------------------

COLUMNS = (
    ("number", "№"),
    ("name", "Обозначение"),
    ("value", "Номинал"),
    ("layer", "Слой"),
    ("rotation", "Поворот"),
    ("package", "Корпус"),
    ("comment", "Комментарий"),
)
OPTIONAL = ("number", "layer", "rotation", "package", "comment")


class ComponentsPanel(QWidget):
    hidden = Signal()
    select = Signal(object)  # component indices
    renamed = Signal(int, str, str)  # component id, field ("name" or "value"), new text
    export_requested = Signal()

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.items: list[core.ComponentInfo] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(PanelTitle("Компоненты", self.close_panel, color="#ffffff"))
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([title for _, title in COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.table.itemSelectionChanged.connect(self.row_chosen)
        self.table.itemChanged.connect(self.cell_changed)
        layout.addWidget(self.table, 1)
        group = QWidget()
        box = QVBoxLayout(group)
        box.setContentsMargins(6, 2, 6, 6)
        caption = QLabel("<u>Показать:</u>")
        box.addWidget(caption)
        self.shown: dict[str, QCheckBox] = {}
        for key, title in COLUMNS:
            if key not in OPTIONAL:
                continue
            check = QCheckBox("Номер" if key == "number" else title)
            check.setChecked(read_bool(settings, f"components/{key}", True))
            check.toggled.connect(self.apply_columns)
            box.addWidget(check)
            self.shown[key] = check
        export = QPushButton("Экспорт…")
        export.clicked.connect(self.export_requested.emit)
        box.addWidget(export)
        layout.addWidget(group)
        self.apply_columns()

    def close_panel(self):
        self.hide()
        self.hidden.emit()

    def apply_columns(self, *_args):
        for column, (key, _title) in enumerate(COLUMNS):
            if key in self.shown:
                visible = self.shown[key].isChecked()
                self.table.setColumnHidden(column, not visible)
                self.settings.setValue(f"components/{key}", visible)

    def show_board(self, board) -> None:
        self.items = core.components_of(board) if board is not None else []
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.items))
        for row, info in enumerate(self.items):
            values = (
                str(row + 1),
                info.name,
                info.value,
                "Верх" if info.top else "Низ",
                f"{info.rotation:g}°",
                info.package,
                info.comment,
            )
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if COLUMNS[column][0] not in ("name", "value"):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.table.blockSignals(False)

    def row_chosen(self):
        rows = {index.row() for index in self.table.selectedIndexes()}
        indices = [i for row in sorted(rows) for i in self.items[row].indices]
        if indices:
            self.select.emit(indices)

    def cell_changed(self, item):
        key = COLUMNS[item.column()][0]
        if key in ("name", "value") and 0 <= item.row() < len(self.items):
            self.renamed.emit(self.items[item.row()].cid, key, item.text())


EXPORT_FIELDS = (
    ("number", "Порядковый номер"),
    ("name", "Обозначение"),
    ("value", "Номинал"),
    ("layer", "Слой"),
    ("position", "Позиция"),
    ("rotation", "Поворот"),
    ("package", "Корпус"),
    ("comment", "Комментарий"),
)
SEPARATORS = ((",", "Запятая"), (";", "Точка с запятой"), ("\t", "Табуляция"))


class ComponentExportDialog(QDialog):
    """Pick-and-place / parts list export, with the original's choices."""

    def __init__(self, parent, settings, board):
        super().__init__(parent)
        self.settings, self.board = settings, board
        self.setWindowTitle("Экспорт данных компонентов")
        layout = QHBoxLayout(self)
        left = QVBoxLayout()
        layout.addLayout(left)
        group = QGroupBox("Данные для экспорта")
        box = QVBoxLayout(group)
        box.addWidget(QLabel("Порядок — перетаскиванием"))
        self.fields = QListWidget()
        self.fields.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        order = read_str(settings, "export/fields", ",".join(key for key, _ in EXPORT_FIELDS))
        titles = dict(EXPORT_FIELDS)
        keys = [k for k in order.split(",") if k in titles]
        keys += [k for k, _ in EXPORT_FIELDS if k not in keys]
        for key in keys:
            item = QListWidgetItem(titles[key])
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = read_bool(settings, f"export/use_{key}", True)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.fields.addItem(item)
        box.addWidget(self.fields)
        left.addWidget(group)
        group = QGroupBox("Разделитель")
        box = QVBoxLayout(group)
        self.separator = QButtonGroup(group)
        for index, (_char, label) in enumerate(SEPARATORS):
            radio = QRadioButton(label)
            self.separator.addButton(radio, index)
            box.addWidget(radio)
        chosen = self.separator.button(read_int(settings, "export/separator", 0))
        (chosen or self.separator.button(0)).setChecked(True)
        left.addWidget(group)

        right = QVBoxLayout()
        layout.addLayout(right, 1)
        group = QGroupBox("Позиция X/Y")
        grid = QGridLayout(group)
        self.unit = QComboBox()
        self.unit.addItems(["мм", "mil"])
        self.unit.setCurrentIndex(read_int(settings, "export/unit", 0))
        self.decimals = QSpinBox()
        self.decimals.setRange(0, 4)
        self.decimals.setValue(read_int(settings, "export/decimals", 3))
        self.strip = QCheckBox("Убирать нули")
        self.strip.setChecked(read_bool(settings, "export/strip", False))
        grid.addWidget(QLabel("Единицы:"), 0, 0)
        grid.addWidget(self.unit, 0, 1)
        grid.addWidget(QLabel("Знаков после запятой:"), 1, 0)
        grid.addWidget(self.decimals, 1, 1)
        grid.addWidget(self.strip, 2, 0, 1, 2)
        right.addWidget(group)
        group = QGroupBox("Названия сторон")
        grid = QGridLayout(group)
        self.top_text = QLineEdit(read_str(settings, "export/top", "Top"))
        self.bottom_text = QLineEdit(read_str(settings, "export/bottom", "Bottom"))
        grid.addWidget(QLabel("Верх:"), 0, 0)
        grid.addWidget(self.top_text, 0, 1)
        grid.addWidget(QLabel("Низ:"), 1, 0)
        grid.addWidget(self.bottom_text, 1, 1)
        right.addWidget(group)
        self.prefix = QCheckBox("Поворот с префиксом «R»")
        self.prefix.setChecked(read_bool(settings, "export/prefix", False))
        right.addWidget(self.prefix)
        group = QGroupBox("Фильтр")
        grid = QGridLayout(group)
        self.filters = {}
        for row, (key, label) in enumerate(
            (
                ("smd", "SMD-компоненты"),
                ("tht", "Выводные компоненты"),
                ("top", "Верх"),
                ("bottom", "Низ"),
            )
        ):
            check = QCheckBox(label)
            check.setChecked(read_bool(settings, f"export/{key}", True))
            grid.addWidget(check, row // 2, row % 2)
            self.filters[key] = check
        right.addWidget(group)
        right.addWidget(QLabel("Просмотр:"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        right.addWidget(self.preview, 1)
        buttons = QHBoxLayout()
        export = QPushButton("Экспорт…")
        export.clicked.connect(self.export)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(export)
        buttons.addWidget(close)
        right.addLayout(buttons)
        for signal in (
            self.fields.itemChanged,
            self.fields.model().rowsMoved,
            self.separator.idToggled,
            self.unit.currentIndexChanged,
            self.decimals.valueChanged,
            self.strip.toggled,
            self.top_text.textChanged,
            self.bottom_text.textChanged,
            self.prefix.toggled,
        ):
            signal.connect(self.update_preview)
        for check in self.filters.values():
            check.toggled.connect(self.update_preview)
        self.resize(760, 520)
        self.update_preview()

    def chosen_fields(self) -> list[str]:
        result = []
        for row in range(self.fields.count()):
            item = self.fields.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(item.data(Qt.ItemDataRole.UserRole))
        return result

    def number(self, value: float) -> str:
        if self.unit.currentIndex() == 1:
            value /= 0.0254
        text = f"{value:.{self.decimals.value()}f}"
        if self.strip.isChecked() and "." in text:
            text = text.rstrip("0").rstrip(".")
        return text

    def text(self) -> str:
        separator = SEPARATORS[self.separator.checkedId()][0]
        fields = self.chosen_fields()
        ox, oy = core.board_origin(self.board)
        rows = []
        number = 0
        for info in core.components_of(self.board):
            if info.smd and not self.filters["smd"].isChecked():
                continue
            if not info.smd and not self.filters["tht"].isChecked():
                continue
            if info.top and not self.filters["top"].isChecked():
                continue
            if not info.top and not self.filters["bottom"].isChecked():
                continue
            number += 1
            values = {
                "number": str(number),
                "name": info.name,
                "value": info.value,
                "layer": self.top_text.text() if info.top else self.bottom_text.text(),
                "position": f"{self.number(info.x - ox)}{separator}{self.number(info.y - oy)}",
                "rotation": ("R" if self.prefix.isChecked() else "") + f"{info.rotation:g}",
                "package": info.package,
                "comment": info.comment,
            }
            rows.append(separator.join(values[key] for key in fields))
        return "\n".join(rows) + ("\n" if rows else "")

    def update_preview(self, *_args):
        self.preview.setPlainText(self.text())

    def remember(self):
        s = self.settings
        order = [
            self.fields.item(r).data(Qt.ItemDataRole.UserRole) for r in range(self.fields.count())
        ]
        s.setValue("export/fields", ",".join(order))
        for row in range(self.fields.count()):
            item = self.fields.item(row)
            s.setValue(
                f"export/use_{item.data(Qt.ItemDataRole.UserRole)}",
                item.checkState() == Qt.CheckState.Checked,
            )
        s.setValue("export/separator", self.separator.checkedId())
        s.setValue("export/unit", self.unit.currentIndex())
        s.setValue("export/decimals", self.decimals.value())
        s.setValue("export/strip", self.strip.isChecked())
        s.setValue("export/top", self.top_text.text())
        s.setValue("export/bottom", self.bottom_text.text())
        s.setValue("export/prefix", self.prefix.isChecked())
        for key, check in self.filters.items():
            s.setValue(f"export/{key}", check.isChecked())

    def export(self):
        self.remember()
        start = read_str(self.settings, "export/folder", str(Path.home()))
        name, _ = QFileDialog.getSaveFileName(
            self, "Экспорт компонентов", start, "Текст (*.txt *.csv);;Все файлы (*)"
        )
        if name:
            Path(name).write_text(self.text(), encoding="utf-8")
            self.settings.setValue("export/folder", str(Path(name).parent))
