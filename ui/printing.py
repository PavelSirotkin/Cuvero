"""Printing, laid out like the original: layers and options on the left, the sheet on the right.

The sheet preview shows the page in millimetres; the board can be dragged on it. Layers are
drawn from the exact output geometry (the same as in Gerber), so planes are exact too.
"""

from dataclasses import dataclass, field
from datetime import datetime
from math import ceil, floor

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QPageLayout,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtPrintSupport import QPageSetupDialog, QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import core
from core import gerber, gerber_read

from .export_dialogs import ok_cancel
from .gerber_paths import copper_path
from .settings import read_bool, read_float, read_int, read_str

# (key, label, Gerber file ending, default colour, side: 1 top, 2 bottom, 0 both)
PRINT_LAYERS = (
    ("C1", "C1", "copper_top", "#000000", 1),
    ("S1", "S1", "silkscreen_top", "#ff0000", 1),
    ("C2", "C2", "copper_bottom", "#000000", 2),
    ("S2", "S2", "silkscreen_bottom", "#c0a000", 2),
    ("I1", "I1", "copper_inner1", "#000000", 0),
    ("I2", "I2", "copper_inner2", "#000000", 0),
    ("O", "O", "outline", "#00c000", 0),
)
SPECIAL_LAYERS = (
    ("M1", "Маска 1", "soldermask_top", "#000000", 1),
    ("M2", "Маска 2", "soldermask_bottom", "#000000", 2),
    ("D", "Отверстия", "", "#000000", 0),
)
MODES = ("1 над 2", "2 над 1", "1 и 2 друг под другом", "1 и 2 рядом")
MARK = 5.0  # mm: register crosses and their distance from the board
INFO = 4.0  # mm below the board for the info line
GAP = 5.0  # mm between the two sides when printed apart


@dataclass
class Sheet:
    """Everything needed to draw the printout on a page, in millimetres."""

    board: core.Board
    title: str
    layers: list[tuple[str, QPainterPath, QColor, int]] = field(default_factory=list)
    holes: list[tuple[float, float, float]] = field(default_factory=list)
    hole_colour: QColor = field(default_factory=lambda: QColor("black"))
    mode: int = 0
    mirror: bool = False
    marks: bool = False
    frame: bool = False
    negative: bool = False
    grid: bool = False
    info: bool = True
    scale_x: float = 1.0
    scale_y: float = 1.0
    offset: QPointF = field(default_factory=lambda: QPointF(10, 10))  # board corner on the page

    def board_size(self) -> QSizeF:
        return QSizeF(self.board.width * self.scale_x, self.board.height * self.scale_y)

    def parts(self) -> list[tuple[int, QPointF]]:
        """(side, top-left corner) of each copy of the board: one, or two side by side."""
        size = self.board_size()
        if self.mode == 2:
            below = QPointF(self.offset.x(), self.offset.y() + size.height() + GAP + INFO)
            return [(1, self.offset), (2, below)]
        if self.mode == 3:
            beside = QPointF(self.offset.x() + size.width() + GAP, self.offset.y())
            return [(1, self.offset), (2, beside)]
        return [(0, self.offset)]

    def extent(self) -> QRectF:
        """Area on the page taken by the printout, with marks and info line."""
        rect = QRectF()
        size = self.board_size()
        for _side, corner in self.parts():
            rect = rect.united(QRectF(corner, size))
        margin = MARK * 1.5 if self.marks else 0.0
        return rect.adjusted(-margin, -margin, margin, margin + (INFO if self.info else 0))

    def draw(self, painter: QPainter) -> None:
        """Draw onto a painter whose units are millimetres from the page's top left."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ox, oy = core.board_origin(self.board)
        area = QRectF(-ox, -oy - self.board.height, self.board.width, self.board.height)
        size = self.board_size()
        for side, corner in self.parts():
            painter.save()
            painter.translate(corner)
            frame = QRectF(QPointF(0, 0), size)
            if self.negative:
                painter.fillRect(frame, QColor("black"))
            painter.save()
            if self.mirror:
                painter.translate(size.width(), 0)
                painter.scale(-self.scale_x, self.scale_y)
            else:
                painter.scale(self.scale_x, self.scale_y)
            painter.translate(-area.left(), area.bottom())
            painter.scale(1, -1)
            painter.setPen(Qt.PenStyle.NoPen)
            layers = [item for item in self.layers if side == 0 or item[3] in (0, side)]
            if self.mode == 1:
                layers = sorted(layers, key=lambda item: item[3] != 2)
            elif self.mode == 0:
                layers = sorted(layers, key=lambda item: item[3] != 1)
                layers.reverse()
            for _key, path, colour, _layer_side in layers:
                painter.setBrush(QColor("white") if self.negative else colour)
                painter.drawPath(path)
            if self.holes:
                painter.setBrush(self.hole_colour if not self.negative else QColor("black"))
                for x, y, d in self.holes:
                    painter.drawEllipse(QPointF(x, y), d / 2, d / 2)
            painter.restore()
            pen = QPen(QColor("black"), 0.15)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if self.frame:
                painter.drawRect(frame)
            if self.marks:
                for cx, cy in (
                    (-MARK, -MARK),
                    (size.width() + MARK, -MARK),
                    (-MARK, size.height() + MARK),
                    (size.width() + MARK, size.height() + MARK),
                ):
                    painter.drawLine(QPointF(cx - MARK / 2, cy), QPointF(cx + MARK / 2, cy))
                    painter.drawLine(QPointF(cx, cy - MARK / 2), QPointF(cx, cy + MARK / 2))
                    painter.drawEllipse(QPointF(cx, cy), MARK / 4, MARK / 4)
            if self.info:
                font = painter.font()
                font.setPixelSize(2)
                painter.setFont(font)
                painter.setPen(QColor("#0000a0"))
                chosen = ", ".join(
                    key for key, _p, _c, s in self.layers if side in (0, s) or s == 0
                )
                text = (
                    f"{self.title} [{self.board.name}] — {chosen} — {round(self.scale_x * 100)} %"
                )
                if self.mirror:
                    text += " — зеркально"
                painter.drawText(QPointF(0, size.height() + 3), text)
                stamp = datetime.now().strftime("%d.%m.%Y %H:%M")
                width = painter.fontMetrics().horizontalAdvance(stamp)
                painter.drawText(QPointF(size.width() - width, size.height() + 3), stamp)
            painter.restore()


class SheetPreview(QWidget):
    """The page with rulers, its printable area, a 50 mm grid and the board on it."""

    moved = Signal()

    def __init__(self):
        super().__init__()
        self.sheet: Sheet | None = None
        self.page = QRectF(0, 0, 210, 297)
        self.printable = QRectF(5, 5, 200, 287)
        self.drag: QPointF | None = None
        self.setMinimumSize(520, 560)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def scale(self) -> float:
        return min(
            (self.width() - 40) / self.page.width(), (self.height() - 40) / self.page.height()
        )

    def to_page(self, point) -> QPointF:
        s = self.scale()
        return QPointF((point.x() - 30) / s, (point.y() - 30) / s)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#eeeeee"))
        s = self.scale()
        painter.translate(30, 30)
        # Rulers in millimetres.
        painter.setPen(QColor("#202020"))
        font = painter.font()
        font.setPointSize(7)
        painter.setFont(font)
        for mm in range(0, int(self.page.width()) + 1, 10):
            x = mm * s
            painter.drawLine(QPointF(x, -6 if mm % 50 == 0 else -3), QPointF(x, 0))
            if mm % 50 == 0:
                painter.drawText(QPointF(x + 2, -8), str(mm))
        for mm in range(0, int(self.page.height()) + 1, 10):
            y = mm * s
            painter.drawLine(QPointF(-6 if mm % 50 == 0 else -3, y), QPointF(0, y))
            if mm % 50 == 0:
                painter.save()
                painter.translate(-9, y + 2)
                painter.rotate(-90)
                painter.drawText(QPointF(-14, 0), str(mm))
                painter.restore()
        page = QRectF(0, 0, self.page.width() * s, self.page.height() * s)
        painter.fillRect(page.translated(3, 3), QColor("#808080"))
        painter.fillRect(page, QColor("white"))
        painter.setPen(QPen(QColor("#d0d0d0"), 1))
        for mm in range(50, int(self.page.width()), 50):
            painter.drawLine(QPointF(mm * s, 0), QPointF(mm * s, page.height()))
        for mm in range(50, int(self.page.height()), 50):
            painter.drawLine(QPointF(0, mm * s), QPointF(page.width(), mm * s))
        painter.setPen(QPen(QColor("#e00000"), 1, Qt.PenStyle.DashLine))
        p = self.printable
        painter.drawRect(QRectF(p.left() * s, p.top() * s, p.width() * s, p.height() * s))
        if self.sheet is not None:
            painter.save()
            painter.setClipRect(page)
            painter.scale(s, s)
            self.sheet.draw(painter)
            painter.restore()

    def mousePressEvent(self, event):
        if self.sheet is not None and event.button() == Qt.MouseButton.LeftButton:
            self.drag = self.to_page(event.position()) - self.sheet.offset
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.drag is not None and self.sheet is not None:
            point = self.to_page(event.position()) - self.drag
            self.sheet.offset = QPointF(round(point.x()), round(point.y()))
            self.update()

    def mouseReleaseEvent(self, event):
        if self.drag is not None:
            self.drag = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.moved.emit()


class ColourBox(QToolButton):
    """A small colour box; a click chooses the printing colour of the layer."""

    def __init__(self, colour: str):
        super().__init__()
        self.colour = QColor(colour)
        self.setFixedSize(16, 14)
        self.clicked.connect(self.choose)
        self.paint()

    def paint(self):
        self.setStyleSheet(
            f"QToolButton {{ background: {self.colour.name()}; border: 1px solid #404040; }}"
        )

    def choose(self):
        colour = QColorDialog.getColor(self.colour, self, "Цвет при печати")
        if colour.isValid():
            self.colour = colour
            self.paint()


class CalibrationDialog(QDialog):
    def __init__(self, parent, x: float, y: float):
        super().__init__(parent)
        self.setWindowTitle("Калибровка принтера")
        form = QFormLayout(self)
        form.addRow(QLabel("Поправка масштаба, если принтер растягивает или сжимает отпечаток:"))
        self.x_box, self.y_box = QDoubleSpinBox(), QDoubleSpinBox()
        for box, value in ((self.x_box, x), (self.y_box, y)):
            box.setRange(50, 150)
            box.setDecimals(2)
            box.setSuffix(" %")
            box.setValue(value)
        form.addRow("По горизонтали (X):", self.x_box)
        form.addRow("По вертикали (Y):", self.y_box)
        form.addRow(ok_cancel(self))


class DrillMarksDialog(QDialog):
    def __init__(self, parent, real: bool, size: float):
        super().__init__(parent)
        self.setWindowTitle("Отверстия при печати")
        form = QFormLayout(self)
        self.real = QRadioButton("Настоящий диаметр отверстия")
        self.mark = QRadioButton("Метка для сверления диаметром:")
        (self.real if real else self.mark).setChecked(True)
        self.size_box = QDoubleSpinBox()
        self.size_box.setRange(0.05, 3)
        self.size_box.setDecimals(2)
        self.size_box.setSuffix(" мм")
        self.size_box.setValue(size)
        form.addRow(self.real)
        form.addRow(self.mark, self.size_box)
        form.addRow(ok_cancel(self))


class PrintDialog(QDialog):
    def __init__(self, parent, settings, board, title, printer=None):
        super().__init__(parent)
        self.settings, self.board, self.title = settings, board, title
        self.printer = printer or QPrinter(QPrinter.PrinterMode.HighResolution)
        self.setWindowTitle(f"Печать — {self.printer.printerName() or 'принтер'}")
        self.correct_x = read_float(settings, "print/correct_x", 100.0)
        self.correct_y = read_float(settings, "print/correct_y", 100.0)
        self.real_holes = read_bool(settings, "print/real_holes", False)
        self.hole_mark = read_float(settings, "print/hole_mark", 0.4)
        self.paths: dict[str, QPainterPath] = {}
        outer = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        outer.addLayout(toolbar)
        for text, slot in (
            ("По центру", self.center),
            ("В буфер обмена", self.copy),
            ("Разбивка…", self.tiles),
            ("Калибровка…", self.calibrate),
            ("Настройка…", self.page_setup),
            ("Печать", self.print_now),
            ("Отмена", self.reject),
        ):
            push = QPushButton(text)
            push.clicked.connect(slot)
            toolbar.addWidget(push)
        toolbar.addStretch()
        body = QHBoxLayout()
        outer.addLayout(body, 1)
        left = QVBoxLayout()
        body.addLayout(left)
        self.preview = SheetPreview()
        self.preview.moved.connect(self.remember_offset)
        body.addWidget(self.preview, 1)

        group = QGroupBox("Слои")
        box = QVBoxLayout(group)
        self.layer_checks: dict[str, tuple[QCheckBox, ColourBox]] = {}
        for key, label, _ending, colour, _side in PRINT_LAYERS:
            self.layer_checks[key] = self.layer_row(box, key, label, colour)
            if key in ("I1", "I2") and not board.multilayer:
                self.layer_checks[key][0].setChecked(False)
                self.layer_checks[key][0].setEnabled(False)
        modes = QHBoxLayout()
        self.mode = QButtonGroup(group)
        for index, text in enumerate(("1/2", "2/1", "1\n2", "1 2")):
            button = QToolButton()
            button.setText(text)
            button.setToolTip(MODES[index])
            button.setCheckable(True)
            button.setFixedSize(30, 30)
            self.mode.addButton(button, index)
            modes.addWidget(button)
        (self.mode.button(read_int(settings, "print/mode", 0)) or self.mode.button(0)).setChecked(
            True
        )
        box.addLayout(modes)
        left.addWidget(group)

        group = QGroupBox("Особые слои")
        box = QVBoxLayout(group)
        for key, label, _ending, colour, _side in SPECIAL_LAYERS:
            self.layer_checks[key] = self.layer_row(box, key, label, colour)
        drill_options = QPushButton("Параметры…")
        drill_options.clicked.connect(self.drill_options)
        box.addWidget(drill_options)
        left.addWidget(group)

        group = QGroupBox("Параметры")
        box = QVBoxLayout(group)
        self.options: dict[str, QCheckBox] = {}
        for key, label, default in (
            ("mono", "Чёрно-белая", False),
            ("mirror", "Зеркально", False),
            ("marks", "Метки совмещения", False),
            ("frame", "Контур платы", False),
            ("template", "Шаблон (подложка)", False),
            ("negative", "Инвертировать", False),
            ("grid", "Сетка", True),
            ("info", "Строка сведений", True),
        ):
            check = QCheckBox(label)
            check.setChecked(read_bool(settings, f"print/{key}", default))
            check.toggled.connect(self.refresh)
            box.addWidget(check)
            self.options[key] = check
        self.options["template"].setEnabled(False)
        self.options["template"].setToolTip("Подложка-шаблон появится на этапе 6")
        left.addWidget(group)

        group = QGroupBox("Масштаб")
        box = QVBoxLayout(group)
        self.one_to_one = QRadioButton("1:1")
        self.free = QRadioButton("Масштаб:")
        self.percent = QLabel()
        self.percent.setAlignment(Qt.AlignmentFlag.AlignRight)
        free_line = QHBoxLayout()
        free_line.addWidget(self.free)
        free_line.addWidget(self.percent)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(10, 500)
        self.slider.setValue(round(read_float(settings, "print/scale", 100.0)))
        (self.free if read_int(settings, "print/scale_mode", 0) else self.one_to_one).setChecked(
            True
        )
        box.addWidget(self.one_to_one)
        box.addLayout(free_line)
        box.addWidget(self.slider)
        left.addWidget(group)

        group = QGroupBox("Ориентация")
        box = QVBoxLayout(group)
        self.portrait = QRadioButton("Книжная")
        self.landscape = QRadioButton("Альбомная")
        landscape = read_str(settings, "print/orientation", "portrait") == "landscape"
        (self.landscape if landscape else self.portrait).setChecked(True)
        box.addWidget(self.portrait)
        box.addWidget(self.landscape)
        left.addWidget(group)
        left.addStretch()

        for widget in (self.one_to_one, self.free, self.portrait, self.landscape):
            widget.toggled.connect(self.refresh)
        self.slider.valueChanged.connect(self.refresh)
        self.mode.idToggled.connect(self.refresh)
        offset = QPointF(
            read_float(settings, "print/offset_x", -1), read_float(settings, "print/offset_y", -1)
        )
        self.offset = offset
        self.resize(980, 760)
        self.refresh()
        if offset.x() < 0:
            self.center()

    def layer_row(self, box, key, label, colour) -> tuple[QCheckBox, ColourBox]:
        line = QHBoxLayout()
        check = QCheckBox(label)
        check.setChecked(read_bool(self.settings, f"print/{key}", key in ("C1", "O")))
        check.toggled.connect(self.refresh)
        swatch = ColourBox(read_str(self.settings, f"print/colour_{key}", colour))
        swatch.clicked.connect(self.refresh)
        line.addWidget(check)
        line.addStretch()
        line.addWidget(swatch)
        box.addLayout(line)
        return check, swatch

    # --- state -----------------------------------------------------------------------

    def path(self, ending: str) -> QPainterPath:
        if ending not in self.paths:
            text = gerber.layer_gerber(self.board, ending, gerber.GerberOptions(x2=False))
            self.paths[ending] = copper_path(gerber_read.parse(text))
        return self.paths[ending]

    def sheet(self) -> Sheet:
        mono = self.options["mono"].isChecked()
        factor = self.slider.value() / 100 if self.free.isChecked() else 1.0
        sheet = Sheet(
            self.board,
            self.title,
            mode=self.mode.checkedId(),
            mirror=self.options["mirror"].isChecked(),
            marks=self.options["marks"].isChecked(),
            frame=self.options["frame"].isChecked(),
            negative=self.options["negative"].isChecked(),
            grid=self.options["grid"].isChecked(),
            info=self.options["info"].isChecked(),
            scale_x=factor * self.correct_x / 100,
            scale_y=factor * self.correct_y / 100,
            offset=QPointF(self.offset),
        )
        for key, _label, ending, _colour, side in PRINT_LAYERS + SPECIAL_LAYERS:
            check, swatch = self.layer_checks[key]
            if not check.isChecked() or not check.isEnabled():
                continue
            colour = QColor("black") if mono else swatch.colour
            if key == "D":
                ox, oy = core.board_origin(self.board)
                sheet.holes = [
                    (pad.x - ox, pad.y - oy, d if self.real_holes else self.hole_mark)
                    for d, pad in core.holes(self.board)
                ]
                # Holes show as white dots in the copper, as for drilling by hand.
                sheet.hole_colour = QColor("white")
                continue
            sheet.layers.append((key, self.path(ending), colour, side))
        return sheet

    def apply_orientation(self):
        orientation = (
            QPageLayout.Orientation.Landscape
            if self.landscape.isChecked()
            else QPageLayout.Orientation.Portrait
        )
        self.printer.setPageOrientation(orientation)
        layout = self.printer.pageLayout()
        self.preview.page = layout.fullRect(QPageLayout.Unit.Millimeter)
        full = layout.fullRect(QPageLayout.Unit.Millimeter)
        paint = layout.paintRect(QPageLayout.Unit.Millimeter)
        self.preview.printable = paint.translated(-full.left(), -full.top())

    def refresh(self, *_args):
        self.percent.setText(f"{self.slider.value()} %")
        self.slider.setEnabled(self.free.isChecked())
        self.apply_orientation()
        self.preview.sheet = self.sheet()
        self.preview.update()

    def remember_offset(self):
        if self.preview.sheet is not None:
            self.offset = QPointF(self.preview.sheet.offset)

    def center(self):
        sheet = self.sheet()
        extent = sheet.extent()
        page = self.preview.page
        self.offset = QPointF(
            round(self.offset.x() + (page.width() - extent.width()) / 2 - extent.left()),
            round(self.offset.y() + (page.height() - extent.height()) / 2 - extent.top()),
        )
        self.refresh()

    def remember(self):
        s = self.settings
        for key, (check, swatch) in self.layer_checks.items():
            if check.isEnabled():
                s.setValue(f"print/{key}", check.isChecked())
            s.setValue(f"print/colour_{key}", swatch.colour.name())
        for key, check in self.options.items():
            s.setValue(f"print/{key}", check.isChecked())
        s.setValue("print/mode", self.mode.checkedId())
        s.setValue("print/scale_mode", int(self.free.isChecked()))
        s.setValue("print/scale", self.slider.value())
        s.setValue("print/correct_x", self.correct_x)
        s.setValue("print/correct_y", self.correct_y)
        s.setValue("print/orientation", "landscape" if self.landscape.isChecked() else "portrait")
        s.setValue("print/offset_x", self.offset.x())
        s.setValue("print/offset_y", self.offset.y())
        s.setValue("print/real_holes", self.real_holes)
        s.setValue("print/hole_mark", self.hole_mark)

    # --- buttons ---------------------------------------------------------------------

    def calibrate(self):
        dialog = CalibrationDialog(self, self.correct_x, self.correct_y)
        if dialog.exec():
            self.correct_x, self.correct_y = dialog.x_box.value(), dialog.y_box.value()
            self.refresh()

    def drill_options(self):
        dialog = DrillMarksDialog(self, self.real_holes, self.hole_mark)
        if dialog.exec():
            self.real_holes = dialog.real.isChecked()
            self.hole_mark = dialog.size_box.value()
            self.refresh()

    def tiles(self):
        columns, rows = self.page_count()
        QMessageBox.information(
            self,
            "Разбивка на листы",
            f"Отпечаток займёт листов: {columns * rows} ({columns} × {rows}).\n"
            "Если плата не помещается на лист, она печатается по частям; передвиньте её"
            " на листе, чтобы выбрать, где пройдут границы.",
        )

    def page_count(self) -> tuple[int, int]:
        extent = self.sheet().extent()
        page = self.preview.printable
        columns = max(1, ceil((extent.right() - page.left()) / page.width()))
        rows = max(1, ceil((extent.bottom() - page.top()) / page.height()))
        first_column = max(0, floor((extent.left() - page.left()) / page.width()))
        first_row = max(0, floor((extent.top() - page.top()) / page.height()))
        return columns - first_column, rows - first_row

    def page_setup(self):
        QPageSetupDialog(self.printer, self).exec()
        self.refresh()

    def copy(self):
        sheet = self.sheet()
        extent = sheet.extent()
        dots = 20  # per mm, about 500 dpi
        image = QImage(
            max(1, round(extent.width() * dots)),
            max(1, round(extent.height() * dots)),
            QImage.Format.Format_RGB32,
        )
        image.fill(QColor("white"))
        painter = QPainter(image)
        painter.scale(dots, dots)
        painter.translate(-extent.left(), -extent.top())
        sheet.draw(painter)
        painter.end()
        QGuiApplication.clipboard().setImage(image)

    def print_now(self):
        self.remember()
        if QPrintDialog(self.printer, self).exec():
            self.paint(self.printer)
            self.accept()

    def paint(self, printer):
        sheet = self.sheet()
        layout = printer.pageLayout()
        full = layout.fullRect(QPageLayout.Unit.Millimeter)
        paint = layout.paintRect(QPageLayout.Unit.Millimeter)
        painter = QPainter(printer)
        if not painter.isActive():
            return
        to_device = painter.device().width() / paint.width()
        extent = sheet.extent()
        printable = paint.translated(-full.left(), -full.top())
        columns = max(1, ceil((extent.right() - printable.left()) / printable.width()))
        rows = max(1, ceil((extent.bottom() - printable.top()) / printable.height()))
        first = True
        for row in range(rows):
            for column in range(columns):
                tile = QRectF(
                    printable.left() + column * printable.width(),
                    printable.top() + row * printable.height(),
                    printable.width(),
                    printable.height(),
                )
                if not tile.intersects(extent):
                    continue
                if not first:
                    printer.newPage()
                first = False
                painter.save()
                painter.scale(to_device, to_device)
                # Device origin is the printable area's corner.
                painter.translate(-tile.left(), -tile.top())
                sheet.draw(painter)
                painter.restore()
        painter.end()
