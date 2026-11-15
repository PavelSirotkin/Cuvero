"""Dialog for a new board: empty work area, rectangular or round board with a margin."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import core

from .settings import read_float, read_int
from .style import mm

KINDS = (
    ("empty", "Пустое рабочее поле\nбез контура платы"),
    ("rect", "Рабочее поле\nс прямоугольным\nконтуром платы"),
    ("round", "Рабочее поле\nс круглым\nконтуром платы"),
)


def kind_icon(kind):
    pixmap = QPixmap(64, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#606060"), 1))
    p.setBrush(QColor("#000000"))
    p.drawRect(QRectF(2, 2, 60, 44))
    p.setPen(QPen(QColor("#ffff00"), 2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "rect":
        p.drawRect(QRectF(12, 10, 40, 28))
    elif kind == "round":
        p.drawEllipse(QPointF(32, 24), 15, 15)
    p.end()
    return QIcon(pixmap)


def size_box(value, maximum=2000.0):
    box = QDoubleSpinBox()
    box.setDecimals(2)
    box.setRange(1.0, maximum)
    box.setSuffix(" мм")
    box.setValue(value)
    box.setMinimumWidth(110)
    return box


class NewBoardDialog(QDialog):
    def __init__(
        self, parent, settings, title="Новая плата", name="Новая плата", ask_position=False
    ):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(title)
        layout = QGridLayout(self)

        self.kinds = QButtonGroup(self)
        choices = QVBoxLayout()
        for row, (kind, text) in enumerate(KINDS):
            button = QToolButton()
            button.setCheckable(True)
            button.setIcon(kind_icon(kind))
            button.setIconSize(QSize(64, 48))
            button.setText(text)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setMinimumWidth(230)
            button.setStyleSheet(
                "QToolButton { padding: 4px; border: 1px solid transparent; }"
                " QToolButton:checked { background: #cfe3ff; border: 1px solid #3a78d8;"
                " color: #000000; font-weight: bold; }"
            )
            self.kinds.addButton(button, row)
            choices.addWidget(button)
        choices.addStretch()
        layout.addLayout(choices, 0, 0, 2, 1)

        self.pages = QStackedWidget()
        self.empty_w, self.empty_h = size_box(160), size_box(100)
        self.rect_w, self.rect_h, self.rect_margin = size_box(160), size_box(100), size_box(20)
        self.round_d, self.round_margin = size_box(100), size_box(20)
        self.rect_margin.setMinimum(0)
        self.round_margin.setMinimum(0)
        self.rect_result, self.round_result = QLabel(), QLabel()
        self.pages.addWidget(
            self.page(
                "Размер рабочего поля:", [("Ширина:", self.empty_w), ("Высота:", self.empty_h)]
            )
        )
        self.pages.addWidget(
            self.page(
                "Прямоугольный контур платы:",
                [
                    ("Ширина:", self.rect_w),
                    ("Высота:", self.rect_h),
                    ("Отступ до края поля:", self.rect_margin),
                ],
                self.rect_result,
            )
        )
        self.pages.addWidget(
            self.page(
                "Круглый контур платы:",
                [("Диаметр:", self.round_d), ("Отступ до края поля:", self.round_margin)],
                self.round_result,
            )
        )
        layout.addWidget(self.pages, 0, 1)

        name_row = QFormLayout()
        self.name = QLineEdit(name)
        self.name.setMaxLength(30)
        name_row.addRow("Имя:", self.name)
        self.after_current = QRadioButton("После текущей платы")
        self.at_end = QRadioButton("Последней")
        self.at_end.setChecked(True)
        if ask_position:
            position = QHBoxLayout()
            position.addWidget(self.after_current)
            position.addWidget(self.at_end)
            name_row.addRow("Вставить:", position)
        layout.addLayout(name_row, 1, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, 2, 0, 1, 2)

        for box in (self.rect_w, self.rect_h, self.rect_margin, self.round_d, self.round_margin):
            box.valueChanged.connect(self.update_results)
        self.kinds.idToggled.connect(self.kind_toggled)
        self.restore()
        self.update_results()

    def kind_toggled(self, index: int, on: bool) -> None:
        if on:
            self.pages.setCurrentIndex(index)

    @staticmethod
    def page(caption, rows, result=None):
        page = QWidget()
        form = QFormLayout(page)
        form.addRow(QLabel(f"<b>{caption}</b>"))
        for label, box in rows:
            form.addRow(label, box)
        if result is not None:
            form.addRow(QLabel("Итоговое рабочее поле:"))
            form.addRow(result)
        return page

    def update_results(self):
        margin = 2 * self.rect_margin.value()
        self.rect_result.setText(
            f"{mm(self.rect_w.value() + margin)} x {mm(self.rect_h.value() + margin)} мм"
        )
        size = self.round_d.value() + 2 * self.round_margin.value()
        self.round_result.setText(f"{mm(size)} x {mm(size)} мм")

    def boxes(self):
        return {
            "empty_w": self.empty_w,
            "empty_h": self.empty_h,
            "rect_w": self.rect_w,
            "rect_h": self.rect_h,
            "rect_margin": self.rect_margin,
            "round_d": self.round_d,
            "round_margin": self.round_margin,
        }

    def restore(self):
        for key, box in self.boxes().items():
            box.setValue(read_float(self.settings, f"new_board/{key}", box.value()))
        index = read_int(self.settings, "new_board/kind", 0)
        self.kinds.button(index if 0 <= index < len(KINDS) else 0).setChecked(True)

    def accept(self):
        if not self.name.text().strip():
            self.name.setFocus()
            return
        for key, box in self.boxes().items():
            self.settings.setValue(f"new_board/{key}", box.value())
        self.settings.setValue("new_board/kind", self.kinds.checkedId())
        super().accept()

    def board(self, grid=0.1):
        kind = KINDS[self.kinds.checkedId()][0]
        name = self.name.text().strip()
        if kind == "empty":
            return core.board_from_dialog(
                name, kind, self.empty_w.value(), self.empty_h.value(), grid=grid
            )
        if kind == "rect":
            return core.board_from_dialog(
                name,
                kind,
                self.rect_w.value(),
                self.rect_h.value(),
                self.rect_margin.value(),
                grid=grid,
            )
        return core.board_from_dialog(
            name,
            kind,
            self.round_d.value(),
            self.round_d.value(),
            self.round_margin.value(),
            grid=grid,
        )
