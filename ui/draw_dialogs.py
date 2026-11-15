"""Dialogs of the drawing tools: text settings and the special forms."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import core

from .settings import read_bool, read_float, read_int, read_str


def spin(value, low, high, step=0.1, decimals=2, suffix=" мм"):
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setValue(value)
    box.setSuffix(suffix)
    return box


def radio_group(parent_layout, title, labels, checked):
    group = QGroupBox(title)
    layout = QVBoxLayout(group)
    buttons = QButtonGroup(group)
    for index, label in enumerate(labels):
        button = QRadioButton(label)
        buttons.addButton(button, index)
        layout.addWidget(button)
    (buttons.button(checked) or buttons.button(0)).setChecked(True)
    parent_layout.addWidget(group)
    return buttons


class TextDialog(QDialog):
    """Text, height, stroke weight, letter spacing, angle, mirroring and running numbers."""

    def __init__(self, parent, settings, text_obj=None, numbering=True):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Свойства текста")
        layout = QVBoxLayout(self)
        self.text = QLineEdit(
            text_obj.text if text_obj else read_str(settings, "text/text", "Текст")
        )
        self.text.textChanged.connect(self.check_text)
        box = QGroupBox("Текст")
        QVBoxLayout(box).addWidget(self.text)
        layout.addWidget(box)
        self.warning = QLabel()
        self.warning.setStyleSheet("color: #a00000;")
        layout.addWidget(self.warning)

        row = QHBoxLayout()
        height = text_obj.outer if text_obj else read_float(settings, "text/height", 2.0)
        self.height_box = spin(height, *core.HEIGHT_RANGE)
        group = QGroupBox("Высота")
        QVBoxLayout(group).addWidget(self.height_box)
        row.addWidget(group)
        weight = core.text_weight(text_obj) if text_obj else read_int(settings, "text/weight", 1)
        self.weight = radio_group(row, "Толщина", ["Тонкий", "Обычный", "Жирный"], weight)
        spacing = core.text_spacing(text_obj) if text_obj else read_int(settings, "text/spacing", 1)
        self.spacing = radio_group(row, "Интервал", ["Узкий", "Обычный", "Широкий"], spacing)
        layout.addLayout(row)

        row = QHBoxLayout()
        group = QGroupBox("Угол")
        angle_layout = QGridLayout(group)
        self.angle = QSpinBox()
        self.angle.setRange(0, 359)
        self.angle.setSuffix("°")
        self.angle.setValue(
            text_obj.rotation if text_obj else read_int(settings, "text/rotation", 0)
        )
        for column, value in enumerate((0, 90, 180, 270)):
            button = QPushButton(f"{value}°")
            button.setFixedWidth(44)
            button.clicked.connect(lambda _=False, value=value: self.angle.setValue(value))
            angle_layout.addWidget(button, 0, column)
        angle_layout.addWidget(self.angle, 1, 0, 1, 4)
        row.addWidget(group)
        group = QGroupBox("Зеркально")
        mirror_layout = QVBoxLayout(group)
        self.mirror_x = QCheckBox("По горизонтали")
        self.mirror_y = QCheckBox("По вертикали")
        self.mirror_x.setChecked(
            text_obj.mirror_x if text_obj else read_bool(settings, "text/mirror_x", False)
        )
        self.mirror_y.setChecked(
            text_obj.mirror_y if text_obj else read_bool(settings, "text/mirror_y", False)
        )
        mirror_layout.addWidget(self.mirror_x)
        mirror_layout.addWidget(self.mirror_y)
        row.addWidget(group)
        layout.addLayout(row)

        self.numbering = QCheckBox("Добавлять к тексту номер, начиная с")
        self.number = QSpinBox()
        self.number.setRange(0, 9999)
        self.number.setValue(read_int(settings, "text/number", 1))
        self.numbering.setChecked(read_bool(settings, "text/numbering", False))
        if numbering:
            group = QGroupBox("Автоматически")
            auto = QHBoxLayout(group)
            auto.addWidget(self.numbering)
            auto.addWidget(self.number)
            auto.addStretch()
            layout.addWidget(group)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.check_text()

    def check_text(self):
        missing = core.unsupported_characters(self.text.text())
        self.warning.setText(f"Нет в шрифте, будет «?»: {missing}" if missing else "")
        self.warning.setVisible(bool(missing))

    def values(self):
        return {
            "text": self.text.text(),
            "height": self.height_box.value(),
            "weight": self.weight.checkedId(),
            "spacing": self.spacing.checkedId(),
            "rotation": self.angle.value(),
            "mirror_x": self.mirror_x.isChecked(),
            "mirror_y": self.mirror_y.isChecked(),
        }

    def remember(self):
        for key, value in self.values().items():
            self.settings.setValue(f"text/{key}", value)
        self.settings.setValue("text/numbering", self.numbering.isChecked())
        self.settings.setValue("text/number", self.number.value())


FRAME_SIDES = ("Сверху и снизу", "Только сверху", "Только снизу", "Нет")
ROW_SIDES = ("Слева и справа", "Только слева", "Только справа", "Нет")
LABEL_KINDS = ("A, B, …", "1, 2, …")


class SpecialFormDialog(QDialog):
    """Regular polygon or rays, spiral, or a drawing frame with column and row marks."""

    def __init__(self, parent, settings, line_width):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Спецформы")
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        page = QWidget()
        form = QFormLayout(page)
        self.corners = QSpinBox()
        self.corners.setRange(3, 360)
        self.corners.setValue(read_int(settings, "special/corners", 6))
        self.radius = spin(read_float(settings, "special/radius", 12.0), 0.1, 500)
        self.offset = spin(read_float(settings, "special/offset", 0.0), -360, 360, 1, 1, "°")
        self.line_width_box = spin(
            read_float(settings, "special/width", line_width), 0.01, 50, 0.05
        )
        self.filled = QCheckBox("Залитый (полигон)")
        self.filled.setChecked(read_bool(settings, "special/filled", False))
        self.rays = QCheckBox("Лучи из центра")
        self.rays.setChecked(read_bool(settings, "special/rays", False))
        self.rays.toggled.connect(lambda on: self.filled.setEnabled(not on))
        self.filled.setEnabled(not self.rays.isChecked())
        form.addRow("Число углов:", self.corners)
        form.addRow("Радиус:", self.radius)
        form.addRow("Поворот:", self.offset)
        form.addRow("Ширина линии:", self.line_width_box)
        form.addRow(self.filled)
        form.addRow(self.rays)
        self.tabs.addTab(page, "Многоугольник")

        page = QWidget()
        form = QFormLayout(page)
        self.start_radius = spin(read_float(settings, "special/start_radius", 2.0), 0, 500)
        self.pitch = spin(read_float(settings, "special/pitch", 2.0), 0.01, 100)
        self.turns = spin(read_float(settings, "special/turns", 6.0), 0.25, 200, 0.25, 2, "")
        self.spiral_width = spin(
            read_float(settings, "special/spiral_width", line_width), 0.01, 50, 0.05
        )
        self.round = QRadioButton("Круглая")
        self.square = QRadioButton("Квадратная")
        (self.square if read_bool(settings, "special/square", False) else self.round).setChecked(
            True
        )
        self.diameter = QLabel()
        form.addRow("Начальный радиус:", self.start_radius)
        form.addRow("Шаг витка:", self.pitch)
        form.addRow("Витков:", self.turns)
        form.addRow("Ширина линии:", self.spiral_width)
        shape = QHBoxLayout()
        shape.addWidget(self.round)
        shape.addWidget(self.square)
        form.addRow("Форма:", shape)
        form.addRow("Диаметр:", self.diameter)
        for box in (self.start_radius, self.pitch, self.turns, self.spiral_width):
            box.valueChanged.connect(self.update_diameter)
        self.update_diameter()
        self.tabs.addTab(page, "Спираль")

        page = QWidget()
        form = QFormLayout(page)
        self.columns = QSpinBox()
        self.columns.setRange(1, 26)
        self.columns.setValue(read_int(settings, "special/columns", 8))
        self.column_sides = QComboBox()
        self.column_sides.addItems(FRAME_SIDES)
        self.column_sides.setCurrentIndex(read_int(settings, "special/column_sides", 0))
        self.column_kind = QComboBox()
        self.column_kind.addItems(LABEL_KINDS)
        self.column_kind.setCurrentIndex(read_int(settings, "special/column_kind", 0))
        self.rows = QSpinBox()
        self.rows.setRange(1, 99)
        self.rows.setValue(read_int(settings, "special/rows", 8))
        self.row_sides = QComboBox()
        self.row_sides.addItems(ROW_SIDES)
        self.row_sides.setCurrentIndex(read_int(settings, "special/row_sides", 0))
        self.row_kind = QComboBox()
        self.row_kind.addItems(LABEL_KINDS)
        self.row_kind.setCurrentIndex(read_int(settings, "special/row_kind", 1))
        self.frame_width = spin(read_float(settings, "special/frame_width", 90.0), 10, 2000, 1)
        self.frame_height = spin(read_float(settings, "special/frame_height", 50.0), 10, 2000, 1)
        columns = QHBoxLayout()
        for widget in (self.columns, self.column_sides, self.column_kind):
            columns.addWidget(widget)
        rows = QHBoxLayout()
        for widget in (self.rows, self.row_sides, self.row_kind):
            rows.addWidget(widget)
        form.addRow("Столбцы:", columns)
        form.addRow("Строки:", rows)
        form.addRow("Ширина:", self.frame_width)
        form.addRow("Высота:", self.frame_height)
        self.tabs.addTab(page, "Рамка")
        self.tabs.setCurrentIndex(read_int(settings, "special/tab", 0))

        hint = QLabel(
            "После «ОК» фигура ставится центром (рамка — левым нижним углом) в точку щелчка."
        )
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def update_diameter(self):
        value = core.spiral_diameter(
            self.start_radius.value(),
            self.pitch.value(),
            self.turns.value(),
            self.spiral_width.value(),
        )
        self.diameter.setText(f"{value:.2f} мм".replace(".", ","))

    def remember(self):
        s = self.settings
        s.setValue("special/tab", self.tabs.currentIndex())
        for key, box in (
            ("corners", self.corners),
            ("radius", self.radius),
            ("offset", self.offset),
            ("width", self.line_width_box),
            ("start_radius", self.start_radius),
            ("pitch", self.pitch),
            ("turns", self.turns),
            ("spiral_width", self.spiral_width),
            ("columns", self.columns),
            ("rows", self.rows),
            ("frame_width", self.frame_width),
            ("frame_height", self.frame_height),
        ):
            s.setValue(f"special/{key}", box.value())
        for key, check in (
            ("filled", self.filled),
            ("rays", self.rays),
            ("square", self.square),
        ):
            s.setValue(f"special/{key}", check.isChecked())
        for key, combo in (
            ("column_sides", self.column_sides),
            ("column_kind", self.column_kind),
            ("row_sides", self.row_sides),
            ("row_kind", self.row_kind),
        ):
            s.setValue(f"special/{key}", combo.currentIndex())

    def build(self, board, layer, x, y):
        """The objects of the chosen form placed at (x, y)."""
        tab = self.tabs.currentIndex()
        if tab == 0:
            if self.rays.isChecked():
                return core.new_rays(
                    board,
                    layer,
                    x,
                    y,
                    self.radius.value(),
                    self.corners.value(),
                    self.offset.value(),
                    self.line_width_box.value(),
                )
            return [
                core.new_regular_polygon(
                    board,
                    layer,
                    x,
                    y,
                    self.radius.value(),
                    self.corners.value(),
                    self.offset.value(),
                    self.line_width_box.value(),
                    self.filled.isChecked(),
                )
            ]
        if tab == 1:
            return [
                core.new_spiral(
                    board,
                    layer,
                    x,
                    y,
                    self.start_radius.value(),
                    self.pitch.value(),
                    self.turns.value(),
                    self.spiral_width.value(),
                    self.square.isChecked(),
                )
            ]
        return core.new_frame(
            board,
            layer,
            x,
            y,
            self.frame_width.value(),
            self.frame_height.value(),
            self.columns.value(),
            self.rows.value(),
            self.column_sides.currentIndex(),
            self.row_sides.currentIndex(),
            self.column_kind.currentIndex() == 0,
            self.row_kind.currentIndex() == 0,
        )
