"""Gerber import dialog, laid out like the original: files left, picture right."""

from pathlib import Path

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
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
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from core import gerber_import, gerber_read

from .export_dialogs import swatch
from .gerber_paths import copper_path
from .settings import read_bool, read_str
from .style import LAYERS

IMPORT_LAYERS = (
    (1, "C1 — медь сверху"),
    (2, "S1 — шелкография сверху"),
    (3, "C2 — медь снизу"),
    (4, "S2 — шелкография снизу"),
    (7, "O — контур"),
    (5, "I1 — медь, внутренний слой 1 (многослойная)"),
    (6, "I2 — медь, внутренний слой 2 (многослойная)"),
)
GERBER_FILTER = (
    "Файлы Gerber (*.gbr *.ger *.gtl *.gbl *.gto *.gbo *.gko *.gm1 *.art *.pho);;Все файлы (*)"
)
DRILL_FILTER = "Сверловка (*.drl *.DRL *.txt *.xln *.exc);;Все файлы (*)"
SUPPRESS = (("Нет", "none"), ("Ведущие нули", "leading"), ("Конечные нули", "trailing"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


class Picture(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        self.clicked.emit()


def crossed(size: int) -> QPixmap:
    """The empty picture: black with a white cross, as the original shows it."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor("black"))
    painter = QPainter(pixmap)
    painter.setPen(QPen(QColor("white"), 2))
    painter.drawLine(0, 0, size, size)
    painter.drawLine(size, 0, 0, size)
    painter.end()
    return pixmap


def drill_icon() -> QLabel:
    label = QLabel("⊗")
    font = label.font()
    font.setPointSize(16)
    label.setFont(font)
    return label


class GerberImportDialog(QDialog):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Импорт Gerber")
        outer = QHBoxLayout(self)
        left = QVBoxLayout()
        outer.addLayout(left, 1)

        group = QGroupBox("Gerber (RS-274X, X2)")
        grid = QGridLayout(group)
        self.files: dict[int, QLineEdit] = {}
        for row, (layer, label) in enumerate(IMPORT_LAYERS):
            grid.addWidget(QLabel(label), row * 2, 0, 1, 4)
            grid.addWidget(swatch(layer), row * 2 + 1, 0)
            self.files[layer] = self.file_row(grid, row * 2 + 1, GERBER_FILTER)
        left.addWidget(group)

        group = QGroupBox("Сверловка (Excellon)")
        box = QVBoxLayout(group)
        grid = QGridLayout()
        grid.addWidget(drill_icon(), 0, 0)
        self.drill = self.file_row(grid, 0, DRILL_FILTER)
        box.addLayout(grid)
        line = QHBoxLayout()
        units = QGroupBox("Единицы")
        units_box = QVBoxLayout(units)
        self.unit = QButtonGroup(units)
        for index, label in enumerate(("Дюймы", "мм")):
            radio = QRadioButton(label)
            self.unit.addButton(radio, index)
            units_box.addWidget(radio)
        self.unit.button(0).setChecked(True)
        auto_units = QPushButton("Авто…")
        auto_units.clicked.connect(self.auto_units)
        units_box.addWidget(auto_units, 0, Qt.AlignmentFlag.AlignLeft)
        line.addWidget(units)
        numbers = QGroupBox("Формат чисел")
        numbers_grid = QGridLayout(numbers)
        self.integer = QSpinBox()
        self.integer.setRange(1, 9)
        self.integer.setValue(2)
        self.decimals = QSpinBox()
        self.decimals.setRange(1, 9)
        self.decimals.setValue(4)
        self.sample = QLabel()
        bold = QFont(self.sample.font())
        bold.setBold(True)
        self.sample.setFont(bold)
        self.suppress = QComboBox()
        for label, _ in SUPPRESS:
            self.suppress.addItem(label)
        auto_format = QPushButton("Авто…")
        auto_format.clicked.connect(self.auto_format)
        numbers_grid.addWidget(self.integer, 0, 0)
        numbers_grid.addWidget(self.decimals, 0, 1)
        numbers_grid.addWidget(self.sample, 1, 0, 1, 2)
        numbers_grid.addWidget(self.suppress, 2, 0)
        numbers_grid.addWidget(auto_format, 2, 1)
        for spin in (self.integer, self.decimals):
            spin.valueChanged.connect(self.update_sample)
        line.addWidget(numbers)
        box.addLayout(line)
        left.addWidget(group)

        right = QVBoxLayout()
        outer.addLayout(right, 1)
        hint = QLabel("Щелчок по картинке — увеличить")
        hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(hint)
        self.picture = Picture()
        self.picture.setFixedSize(370, 370)
        self.picture.setPixmap(crossed(370))
        self.picture.clicked.connect(self.zoom)
        right.addWidget(self.picture)
        right.addStretch()
        group = QGroupBox("Создать плату")
        box = QVBoxLayout(group)
        self.new_board = QRadioButton("Новая плата (новая вкладка)")
        self.current = QRadioButton("Текущая плата")
        current = read_bool(settings, "import/current", False)
        (self.current if current else self.new_board).setChecked(True)
        box.addWidget(self.new_board)
        box.addWidget(self.current)
        right.addWidget(group)
        self.vias = QCheckBox("Создавать площадки с отверстиями автоматически")
        self.join = QCheckBox("Соединять продолжающие друг друга дорожки")
        self.vias.setChecked(True)
        self.join.setChecked(True)
        right.addWidget(self.vias)
        right.addWidget(self.join)
        right.addSpacing(10)
        buttons = QHBoxLayout()
        do_import = QPushButton("Импортировать…")
        do_import.clicked.connect(self.accept)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        for push in (do_import, close):
            push.setMinimumWidth(120)
            buttons.addWidget(push)
        right.addLayout(buttons)
        self.update_sample()
        self.image: QImage | None = None

    def file_row(self, grid, row, pattern) -> QLineEdit:
        edit = QLineEdit()
        browse = QPushButton("…")
        browse.setFixedWidth(26)
        clear = QPushButton("×")
        clear.setFixedWidth(26)

        def choose():
            folder = read_str(self.settings, "import/folder", "")
            name, _ = QFileDialog.getOpenFileName(self, "Выбор файла", folder, pattern)
            if name:
                edit.setText(name)
                self.settings.setValue("import/folder", str(Path(name).parent))
                if pattern == DRILL_FILTER:
                    self.auto_format()  # units and number format from the file itself
                self.update_picture()

        browse.clicked.connect(choose)

        def wipe():
            edit.clear()
            self.update_picture()

        clear.clicked.connect(wipe)
        edit.editingFinished.connect(self.update_picture)
        grid.addWidget(edit, row, 1)
        grid.addWidget(browse, row, 2)
        grid.addWidget(clear, row, 3)
        return edit

    # --- values ------------------------------------------------------------------------

    def inch(self) -> bool:
        return self.unit.checkedId() == 0

    def suppression(self) -> str:
        return SUPPRESS[self.suppress.currentIndex()][1]

    def update_sample(self, *_args):
        self.sample.setText("1" * self.integer.value() + ",…")

    def drill_text(self) -> str:
        path = self.drill.text().strip()
        return read_text(Path(path)) if path else ""

    def auto_units(self):
        try:
            inch, _i, _d, _s = gerber_import.detect_excellon(self.drill_text())
        except OSError:
            return
        self.unit.button(0 if inch else 1).setChecked(True)

    def auto_format(self):
        try:
            inch, integer, decimals, suppress = gerber_import.detect_excellon(self.drill_text())
        except OSError:
            return
        self.integer.setValue(integer)
        self.decimals.setValue(decimals)
        self.suppress.setCurrentIndex([key for _, key in SUPPRESS].index(suppress))
        self.unit.button(0 if inch else 1).setChecked(True)

    def layers(self) -> dict[int, gerber_read.GerberFile]:
        return {
            layer: gerber_read.parse(
                Path(edit.text()).read_text(encoding="utf-8", errors="replace")
            )
            for layer, edit in self.files.items()
            if edit.text().strip()
        }

    def holes(self) -> list[gerber_import.Hole]:
        text = self.drill_text()
        if not text:
            return []
        return gerber_import.parse_excellon(
            text, self.inch(), self.integer.value(), self.decimals.value(), self.suppression()
        )

    # --- picture -----------------------------------------------------------------------

    def render_picture(self, size: int) -> QImage | None:
        try:
            layers = self.layers()
            holes = self.holes()
        except (OSError, ValueError):
            return None
        if not layers and not holes:
            return None
        left, bottom, right, top = gerber_import.bounds_of(layers.values(), holes)
        span = max(right - left, top - bottom, 1e-3)
        image = QImage(size, size, QImage.Format.Format_RGB32)
        image.fill(QColor("black"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = (size - 10) / span
        painter.translate(5, size - 5)
        painter.scale(scale, -scale)
        painter.translate(-left, -bottom)
        painter.setPen(Qt.PenStyle.NoPen)
        for layer in (3, 4, 1, 2, 5, 6, 7):
            if layer in layers:
                colour = QColor("white") if layer == 7 else QColor(LAYERS[layer][1])
                painter.setBrush(colour)
                painter.drawPath(copper_path(layers[layer]))
        painter.setBrush(QColor("black"))
        for x, y, d in holes:
            painter.drawEllipse(QPointF(x, y), d / 2, d / 2)
        painter.end()
        return image

    def update_picture(self):
        image = self.render_picture(370)
        self.image = image
        if image is None:
            self.picture.setPixmap(crossed(370))
        else:
            self.picture.setPixmap(QPixmap.fromImage(image))

    def zoom(self):
        image = self.render_picture(800)
        if image is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Импорт Gerber — картинка")
        layout = QVBoxLayout(dialog)
        label = QLabel()
        label.setPixmap(QPixmap.fromImage(image))
        layout.addWidget(label)
        dialog.exec()
