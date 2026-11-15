"""Footprint wizard and the tile / circular arrangement dialog, laid out like the original's."""

from math import cos, radians, sin

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import core

from .export_dialogs import mm_field, ok_cancel, with_unit
from .settings import read_bool, read_float, read_int
from .style import VALUE_STYLE


def count_field(value: int, low: int = 1, high: int = 999) -> QSpinBox:
    box = QSpinBox()
    box.setRange(low, high)
    box.setValue(value)
    box.setAlignment(Qt.AlignmentFlag.AlignRight)
    box.setFixedWidth(60)
    box.setStyleSheet(VALUE_STYLE.replace("QDoubleSpinBox", "QSpinBox"))
    return box


class FootprintPreview(QWidget):
    """Black preview with red pad rings, like the original wizard's lower picture."""

    def __init__(self):
        super().__init__()
        self.points: list[QPointF] = []
        self.smd = False
        self.pad_size = (1.6, 0.8)
        self.setMinimumSize(190, 190)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("black"))
        if not self.points:
            return
        xs = [p.x() for p in self.points]
        ys = [p.y() for p in self.points]
        span = max(max(xs) - min(xs), max(ys) - min(ys)) + max(self.pad_size) * 2
        scale = min(self.width(), self.height()) * 0.85 / max(span, 1e-3)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(scale, -scale)
        painter.translate(-(max(xs) + min(xs)) / 2, -(max(ys) + min(ys)) / 2)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        red = QColor("#ff0000")
        if self.smd:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(red)
            w, h = self.pad_size
            for p in self.points:
                painter.drawRect(QRectF(p.x() - w / 2, p.y() - h / 2, w, h))
        else:
            diameter, drill = self.pad_size
            pen = QPen(red, (diameter - drill) / 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            r = (diameter + drill) / 4
            for p in self.points:
                painter.drawEllipse(p, r, r)


BLUE = QColor("#0000ff")


class DimensionSketch(QWidget):
    """Pale yellow sketch of the chosen arrangement with its d, X and Y measures,
    like the upper picture of the original wizard."""

    def __init__(self):
        super().__init__()
        self.kind = core.SIP
        self.setMinimumSize(190, 130)

    def set_kind(self, kind: int) -> None:
        self.kind = kind
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffe0"))
        painter.setPen(QPen(QColor("#a0a0a0"), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        pad = 9.0
        pads: list[QPointF] = []
        measures: list[tuple[QPointF, QPointF, str]] = []
        if self.kind in (core.SIP, core.DIP):
            step = 16.0
            x0 = cx - 3 * step
            rows = [cy] if self.kind == core.SIP else [cy - 22, cy + 22]
            for y in rows:
                pads += [QPointF(x0 + k * step, y) for k in range(7)]
            top = rows[0]
            measures.append((QPointF(x0, top + 16), QPointF(x0 + step, top + 16), "d"))
            if self.kind == core.DIP:
                right = x0 + 6 * step + 18
                measures.append((QPointF(right, rows[0]), QPointF(right, rows[1]), "Y"))
        elif self.kind == core.QUAD:
            half, step = 34.0, 12.0
            for k in range(-2, 3):
                pads += [
                    QPointF(cx + k * step, cy - half),
                    QPointF(cx + k * step, cy + half),
                    QPointF(cx - half, cy + k * step),
                    QPointF(cx + half, cy + k * step),
                ]
            measures.append((QPointF(cx, cy - half + 13), QPointF(cx + step, cy - half + 13), "d"))
            measures.append(
                (QPointF(cx - half, cy + half + 13), QPointF(cx + half, cy + half + 13), "X")
            )
            measures.append(
                (QPointF(cx + half + 16, cy - half), QPointF(cx + half + 16, cy + half), "Y")
            )
        else:
            rings = [(40.0, 12)]
            if self.kind == core.CIRCLE_TWO:
                rings.append((22.0, 8))
            for radius, count in rings:
                for k in range(count):
                    angle = radians(90 - 360 * k / count)
                    pads.append(QPointF(cx + radius * cos(angle), cy - radius * sin(angle)))
            measures.append((QPointF(cx - 40, cy), QPointF(cx + 40, cy), "X"))
            if self.kind == core.CIRCLE_TWO:
                measures.append((QPointF(cx, cy - 22), QPointF(cx, cy + 22), "Y"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("black"))
        for p in pads:
            painter.drawRect(QRectF(p.x() - pad / 2, p.y() - pad / 2, pad, pad))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        for a, b, label in measures:
            painter.setPen(QPen(BLUE, 1))
            painter.drawLine(a, b)
            vertical = abs(a.x() - b.x()) < abs(a.y() - b.y())
            for end in (a, b):
                if vertical:
                    painter.drawLine(QPointF(end.x() - 4, end.y()), QPointF(end.x() + 4, end.y()))
                else:
                    painter.drawLine(QPointF(end.x(), end.y() - 4), QPointF(end.x(), end.y() + 4))
            middle = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
            offset = QPointF(6, 4) if vertical else QPointF(-4, 14)
            painter.drawText(middle + offset, label)


class FootprintWizard(QDialog):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Мастер посадочных мест")
        layout = QGridLayout(self)
        top = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItems(core.KINDS)
        self.kind.setCurrentIndex(read_int(settings, "wizard/kind", 0))
        default = QPushButton("По умолчанию")
        default.clicked.connect(self.defaults)
        top.addWidget(self.kind, 1)
        top.addWidget(default)
        layout.addLayout(top, 0, 0, 1, 2)
        self.sketch = DimensionSketch()
        layout.addWidget(self.sketch, 1, 0)
        self.preview = FootprintPreview()
        layout.addWidget(self.preview, 2, 0, 2, 1)

        group = QGroupBox("Площадки")
        grid = QGridLayout(group)
        self.pad_type = QButtonGroup(group)
        tht = QRadioButton("С отверстием")
        smd = QRadioButton("SMD")
        self.pad_type.addButton(tht, 0)
        self.pad_type.addButton(smd, 1)
        (smd if read_bool(settings, "wizard/smd", False) else tht).setChecked(True)
        self.diameter = mm_field(read_float(settings, "wizard/diameter", 1.6), 0.1, 20)
        self.drill = mm_field(read_float(settings, "wizard/drill", 0.8), 0.0, 20)
        self.smd_w = mm_field(read_float(settings, "wizard/smd_w", 0.8), 0.05, 20)
        self.smd_h = mm_field(read_float(settings, "wizard/smd_h", 1.6), 0.05, 20)
        grid.addWidget(tht, 0, 0)
        grid.addLayout(with_unit(self.diameter), 0, 1)
        grid.addLayout(with_unit(self.drill), 1, 1)
        grid.addWidget(smd, 2, 0)
        grid.addLayout(with_unit(self.smd_w), 2, 1)
        grid.addLayout(with_unit(self.smd_h), 3, 1)
        layout.addWidget(group, 1, 1)

        group = QGroupBox("Количество площадок")
        grid = QGridLayout(group)
        self.horizontal = count_field(read_int(settings, "wizard/horizontal", 8))
        self.vertical = count_field(read_int(settings, "wizard/vertical", 1))
        self.total = QLabel()
        grid.addWidget(QLabel("По горизонтали:"), 0, 0)
        grid.addWidget(self.horizontal, 0, 1)
        grid.addWidget(QLabel("По вертикали:"), 1, 0)
        grid.addWidget(self.vertical, 1, 1)
        grid.addWidget(QLabel("Всего:"), 2, 0)
        grid.addWidget(self.total, 2, 1)
        layout.addWidget(group, 2, 1)

        group = QGroupBox("Параметры")
        grid = QGridLayout(group)
        self.pitch = mm_field(read_float(settings, "wizard/pitch", 2.54), 0.1, 100)
        self.row_box = mm_field(read_float(settings, "wizard/y", 7.62), 0.1, 200)
        self.side_box = mm_field(read_float(settings, "wizard/x", 7.62), 0.1, 200)
        for row, (caption, box) in enumerate(
            (("d:", self.pitch), ("Y:", self.row_box), ("X:", self.side_box))
        ):
            label = QLabel(caption)
            label.setStyleSheet("color: #000080; font-weight: bold;")
            grid.addWidget(label, row, 0)
            grid.addLayout(with_unit(box), row, 1)
        layout.addWidget(group, 3, 1)
        layout.addWidget(ok_cancel(self), 4, 0, 1, 2)

        for widget in (
            self.diameter,
            self.drill,
            self.smd_w,
            self.smd_h,
            self.pitch,
            self.row_box,
            self.side_box,
        ):
            widget.valueChanged.connect(self.update_preview)
        for counter in (self.horizontal, self.vertical):
            counter.valueChanged.connect(self.update_preview)
        self.kind.currentIndexChanged.connect(self.update_preview)
        self.pad_type.idToggled.connect(self.update_preview)
        self.update_preview()

    def defaults(self):
        values = {
            core.SIP: (8, 1, 2.54, 2.54, 2.54),
            core.DIP: (7, 2, 2.54, 7.62, 7.62),
            core.QUAD: (8, 8, 1.27, 12.0, 12.0),
            core.CIRCLE_ROW: (8, 1, 2.54, 10.0, 10.0),
            core.CIRCLE_TWO: (8, 8, 2.54, 6.0, 10.0),
        }[self.kind.currentIndex()]
        self.horizontal.setValue(values[0])
        self.vertical.setValue(values[1])
        self.pitch.setValue(values[2])
        self.row_box.setValue(values[3])
        self.side_box.setValue(values[4])

    def footprint(self) -> core.Footprint:
        return core.Footprint(
            kind=self.kind.currentIndex(),
            horizontal=self.horizontal.value(),
            vertical=self.vertical.value(),
            pitch=self.pitch.value(),
            y=self.row_box.value(),
            x=self.side_box.value(),
            smd=self.pad_type.checkedId() == 1,
            diameter=self.diameter.value(),
            drill=self.drill.value(),
            smd_width=self.smd_w.value(),
            smd_height=self.smd_h.value(),
        )

    def update_preview(self, *_args):
        fp = self.footprint()
        kind = fp.kind
        self.sketch.set_kind(kind)
        self.vertical.setEnabled(kind in (core.QUAD, core.CIRCLE_TWO))
        self.pitch.setEnabled(kind in (core.SIP, core.DIP, core.QUAD))
        self.row_box.setEnabled(kind in (core.DIP, core.QUAD, core.CIRCLE_TWO))
        self.side_box.setEnabled(kind in (core.QUAD, core.CIRCLE_ROW, core.CIRCLE_TWO))
        for widget in (self.diameter, self.drill):
            widget.setEnabled(not fp.smd)
        for widget in (self.smd_w, self.smd_h):
            widget.setEnabled(fp.smd)
        points = core.footprint_points(fp)
        self.total.setText(str(len(points)))
        self.preview.points = [QPointF(x, y) for (x, y), _ in points]
        self.preview.smd = fp.smd
        self.preview.pad_size = (fp.smd_width, fp.smd_height) if fp.smd else (fp.diameter, fp.drill)
        self.preview.update()

    def remember(self):
        s, fp = self.settings, self.footprint()
        s.setValue("wizard/kind", fp.kind)
        s.setValue("wizard/smd", fp.smd)
        for key, value in (
            ("diameter", fp.diameter),
            ("drill", fp.drill),
            ("smd_w", fp.smd_width),
            ("smd_h", fp.smd_height),
            ("horizontal", fp.horizontal),
            ("vertical", fp.vertical),
            ("pitch", fp.pitch),
            ("y", fp.y),
            ("x", fp.x),
        ):
            s.setValue(f"wizard/{key}", value)


class TileDialog(QDialog):
    """Copies of the selection in a grid or around a centre."""

    def __init__(self, parent, settings):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Размножить")
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        page = QWidget()
        grid = QGridLayout(page)
        self.columns = count_field(read_int(settings, "tile/columns", 2))
        self.rows = count_field(read_int(settings, "tile/rows", 1))
        self.dx = mm_field(read_float(settings, "tile/dx", 2.54), -1000, 1000)
        self.dy = mm_field(read_float(settings, "tile/dy", 2.54), -1000, 1000)
        grid.addWidget(QLabel("Количество"), 0, 1)
        grid.addWidget(QLabel("Шаг"), 0, 2)
        grid.addWidget(QLabel("По горизонтали:"), 1, 0)
        grid.addWidget(self.columns, 1, 1)
        grid.addLayout(with_unit(self.dx), 1, 2)
        grid.addWidget(QLabel("По вертикали:"), 2, 0)
        grid.addWidget(self.rows, 2, 1)
        grid.addLayout(with_unit(self.dy), 2, 2)
        grid.addWidget(QLabel("Не больше 999 копий."), 3, 0, 1, 3)
        grid.setRowStretch(4, 1)
        self.tabs.addTab(page, "Решётка")

        page = QWidget()
        grid = QGridLayout(page)
        self.count = count_field(read_int(settings, "tile/count", 10), 2)
        self.radius = mm_field(read_float(settings, "tile/radius", 15.0), 0.0, 1000)
        self.start = mm_field(read_float(settings, "tile/start", 0.0), -360, 360)
        self.sweep = mm_field(read_float(settings, "tile/sweep", 360.0), -360, 360)
        self.turn = QCheckBox("Поворачивать объекты")
        self.turn.setChecked(read_bool(settings, "tile/turn", True))
        rows = (
            ("Всего копий (с исходной):", self.count, ""),
            ("Радиус:", self.radius, "мм"),
            ("Начальный угол:", self.start, "°"),
            ("Охват:", self.sweep, "°"),
        )
        for row, (caption, box, unit) in enumerate(rows):
            grid.addWidget(QLabel(caption), row, 0)
            grid.addLayout(with_unit(box, unit) if unit else self.centred(box), row, 1)
        grid.addWidget(self.turn, len(rows), 0, 1, 2)
        note = QLabel(
            "Центр окружности — на заданном радиусе от центра выделенного, "
            "под начальным углом; охват 360° — полный круг."
        )
        note.setWordWrap(True)
        grid.addWidget(note, len(rows) + 1, 0, 1, 2)
        self.tabs.addTab(page, "По окружности")
        self.tabs.setCurrentIndex(read_int(settings, "tile/tab", 0))
        layout.addWidget(ok_cancel(self))

    @staticmethod
    def centred(box) -> QHBoxLayout:
        line = QHBoxLayout()
        line.addWidget(box)
        line.addStretch()
        return line

    def remember(self):
        s = self.settings
        s.setValue("tile/tab", self.tabs.currentIndex())
        for key, box in (("columns", self.columns), ("rows", self.rows), ("count", self.count)):
            s.setValue(f"tile/{key}", box.value())
        for key, field in (
            ("dx", self.dx),
            ("dy", self.dy),
            ("radius", self.radius),
            ("start", self.start),
            ("sweep", self.sweep),
        ):
            s.setValue(f"tile/{key}", field.value())
        s.setValue("tile/turn", self.turn.isChecked())

    def copies(self, board, objects) -> list:
        if self.tabs.currentIndex() == 0:
            return core.tiled(
                board,
                objects,
                self.columns.value(),
                self.rows.value(),
                self.dx.value(),
                self.dy.value(),
            )
        left, bottom, right, top = core.bounds(objects)
        ox, oy = (left + right) / 2, (bottom + top) / 2
        a = radians(self.start.value() + 180)
        centre = (ox + self.radius.value() * cos(a), oy + self.radius.value() * sin(a))
        return core.circled(
            board, objects, centre, self.count.value(), self.sweep.value(), self.turn.isChecked()
        )
