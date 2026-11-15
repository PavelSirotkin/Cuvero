"""Isolation milling (HPGL), laid out like the original: options left, ordered jobs right."""

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import core
from core import gerber, gerber_read, hpgl

from .export_dialogs import mm_field, swatch, with_unit
from .gerber_paths import copper_path
from .settings import read_bool, read_float, read_int
from .style import VALUE_STYLE

NO_OUTPUT = "✗  Не выводить"
SCALES = (
    ("1 единица HPGL = 0,025 мм (1/40 мм)", 40.0),
    ("1 единица HPGL = 0,01 мм (1/100 мм)", 100.0),
)
REGISTER = "Отверстия для переворота"


def polylines(path: QPainterPath) -> list[list[core.Point]]:
    result = []
    for polygon in path.toSubpathPolygons():
        points = [(polygon.at(i).x(), polygon.at(i).y()) for i in range(polygon.size())]
        if len(points) >= 2:
            if points[0] != points[-1]:
                points.append(points[0])
            result.append(points)
    return result


def isolation(
    copper: QPainterPath, tool: float, passes: int, overlap: float
) -> list[list[core.Point]]:
    """Tool centre lines around the copper: each pass a further step outwards."""
    result = []
    for k in range(max(passes, 1)):
        offset = tool / 2 + k * tool * (1 - overlap)
        stroker = QPainterPathStroker()
        stroker.setWidth(2 * offset)
        grown = copper.united(stroker.createStroke(copper)).simplified()
        result += polylines(grown)
    return result


def copper_of(board: core.Board, ending: str) -> QPainterPath:
    text = gerber.layer_gerber(board, ending, gerber.GerberOptions(x2=False))
    return copper_path(gerber_read.parse(text))


def contour_lines(board: core.Board) -> list[list[core.Point]]:
    """Centre lines of everything on the outline layer, relative to the board origin."""
    text = gerber.layer_gerber(board, "outline", gerber.GerberOptions(x2=False))
    parsed = gerber_read.parse(text)
    return [list(item.points) for item in parsed.primitives if item.kind == "draw"]


def text_strokes(board: core.Board, layer: int) -> list[list[core.Point]]:
    """Centre lines of the texts on a copper layer, relative to the board origin."""
    ox, oy = core.board_origin(board)
    return [
        [(x - ox, y - oy) for x, y in child.points]
        for obj in board.elements
        if obj.kind == core.STROKE_TEXT and obj.layer == layer and not core.is_hidden_label(obj)
        for child in obj.children
    ]


class RegisterPicture(QWidget):
    """The board with its reference holes, as in the original's dialog."""

    def __init__(self):
        super().__init__()
        self.count = 0
        self.setFixedSize(96, 64)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("white"))
        board = QRectF(18, 16, 60, 32)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#c0c0c0"))
        for dot_x in (6, 48, 90):
            for dot_y in (6, 58):
                painter.drawEllipse(QPointF(dot_x, dot_y), 1.2, 1.2)
        painter.setBrush(QColor("#606060"))
        points = core.register_holes(
            board.left(), board.top(), board.right(), board.bottom(), 9, self.count
        )
        for x, y in points:
            painter.drawEllipse(QPointF(x, y), 2.5, 2.5)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#d00000"), 2))
        painter.drawRect(board)


def int_field(value: int, low: int, high: int) -> QSpinBox:
    box = QSpinBox()
    box.setRange(low, high)
    box.setValue(value)
    box.setAlignment(Qt.AlignmentFlag.AlignRight)
    box.setFixedWidth(52)
    box.setStyleSheet(VALUE_STYLE.replace("QDoubleSpinBox", "QSpinBox"))
    return box


def checked(group: QButtonGroup, index: int, fallback: int) -> None:
    (group.button(index) or group.button(fallback)).setChecked(True)


class MillingDialog(QDialog):
    def __init__(self, parent, settings, board):
        super().__init__(parent)
        self.settings, self.board = settings, board
        self.setWindowTitle("Фрезеровка изоляции")
        outer = QHBoxLayout(self)
        left = QVBoxLayout()
        outer.addLayout(left, 3)

        line = QHBoxLayout()
        group = QGroupBox("Фрезеровка изоляции")
        grid = QGridLayout(group)
        width_label = QLabel("●  Ширина фрезы:")
        width_label.setStyleSheet("font-weight: bold;")
        self.tool = mm_field(read_float(settings, "milling/tool", 0.2), 0.01, 10)
        grid.addWidget(width_label, 0, 0, 1, 2)
        grid.addLayout(with_unit(self.tool), 0, 2)
        self.sides = {}
        rows = (("top", "C1 — верх", 1, 0), ("bottom", "C2 — низ", 3, 1))
        for row, (key, label, colour, mirror) in enumerate(rows, 1):
            check = QCheckBox(label)
            check.setChecked(read_bool(settings, f"milling/{key}", key == "top"))
            combo = QComboBox()
            combo.addItems(["Без зеркала", "Зеркально по горизонтали"])
            combo.setCurrentIndex(read_int(settings, f"milling/{key}_mirror", mirror))
            punch = QCheckBox("Метки центров (отверстия)")
            punch.setChecked(read_bool(settings, f"milling/{key}_punch", False))
            grid.addWidget(check, row, 0)
            grid.addWidget(swatch(colour), row, 1)
            grid.addWidget(combo, row, 2)
            grid.addWidget(punch, row, 3)
            self.sides[key] = (check, combo, punch)
        line.addWidget(group, 1)
        group = QGroupBox("Проходы")
        grid = QGridLayout(group)
        self.passes = int_field(read_int(settings, "milling/passes", 1), 1, 20)
        self.overlap = int_field(read_int(settings, "milling/overlap", 25), 0, 90)
        grid.addWidget(QLabel("Количество:"), 0, 0)
        grid.addWidget(self.passes, 1, 0)
        grid.addWidget(QLabel("Перекрытие:"), 2, 0)
        grid.addLayout(with_unit(self.overlap, "%"), 3, 0)
        line.addWidget(group)
        left.addLayout(line)

        group = QGroupBox("Отверстия")
        grid = QGridLayout(group)
        self.drill_output = QComboBox()
        self.drill_output.addItems([NO_OUTPUT, "Сверлить на C1", "Сверлить на C2"])
        self.drill_output.setCurrentIndex(read_int(settings, "milling/drill_side", 0))
        grid.addWidget(self.drill_output, 0, 0)
        self.drill_mode = QButtonGroup(group)
        modes = (
            "Все отверстия фрезой (команда CI)",
            "Сверлить (команда PD) — все отверстия одним сверлом (пером)",
            "Сверлить (команда PD) — каждому диаметру своё сверло (перо)",
        )
        for index, label in enumerate(modes):
            radio = QRadioButton(label)
            self.drill_mode.addButton(radio, index)
            grid.addWidget(radio, index + 1, 0)
        checked(self.drill_mode, read_int(settings, "milling/drill_mode2", 1), 1)
        self.drill_tool = mm_field(read_float(settings, "milling/drill_tool", 0.8), 0.01, 10)
        cutter = QHBoxLayout()
        cutter.addWidget(QLabel("Ширина фрезы:"))
        cutter.addWidget(self.drill_tool)
        cutter.addWidget(QLabel("мм"))
        grid.addLayout(cutter, 1, 1)
        if not core.holes(board):
            grid.addWidget(QLabel("На плате нет отверстий"), 0, 1)
        left.addWidget(group)

        group = QGroupBox("Фрезеровка контура")
        grid = QGridLayout(group)
        self.contour_output = QComboBox()
        self.contour_output.addItems([NO_OUTPUT, "Фрезеровать на C1", "Фрезеровать на C2"])
        self.contour_output.setCurrentIndex(read_int(settings, "milling/contour_side", 0))
        grid.addWidget(self.contour_output, 0, 0)
        grid.addWidget(swatch(7), 0, 1)
        has_contour = any(obj.layer == 7 for obj in board.elements)
        caption = "Слой O (по линиям)" if has_contour else "На слое O нет контура платы"
        grid.addWidget(QLabel(caption), 0, 2)
        grid.setColumnStretch(3, 1)
        left.addWidget(group)

        line = QHBoxLayout()
        group = QGroupBox("Отверстия для переворота (точно перевернуть плату)")
        grid = QGridLayout(group)
        self.picture = RegisterPicture()
        grid.addWidget(self.picture, 0, 0, 3, 1)
        self.register_count = QComboBox()
        self.register_count.addItems(["0", "2", "4"])
        self.register_count.setCurrentIndex(read_int(settings, "milling/register", 0))
        self.register_distance = mm_field(
            read_float(settings, "milling/register_distance", 5.0), 0, 100
        )
        count_line = QHBoxLayout()
        count_line.addWidget(QLabel("Количество:"))
        count_line.addWidget(self.register_count)
        count_line.addStretch()
        grid.addLayout(count_line, 0, 1)
        grid.addWidget(QLabel("Расстояние от края платы:"), 1, 1)
        grid.addLayout(with_unit(self.register_distance), 2, 1)
        line.addWidget(group, 3)
        group = QGroupBox("Текст")
        grid = QGridLayout(group)
        self.text_mode = QButtonGroup(group)
        grid.addWidget(QLabel("Обычный:"), 0, 0)
        for index, label in enumerate(("Контур", "По линиям")):
            radio = QRadioButton(label)
            self.text_mode.addButton(radio, index)
            grid.addWidget(radio, 0, index + 1)
        checked(self.text_mode, read_int(settings, "milling/text", 0), 0)
        selected = QLabel("Выделенный:")
        selected.setEnabled(False)
        grid.addWidget(selected, 1, 0)
        for index, label in enumerate(("Контур", "По линиям")):
            radio = QRadioButton(label)
            radio.setAutoExclusive(False)
            radio.setChecked(index == 0)
            radio.setEnabled(False)
            grid.addWidget(radio, 1, index + 1)
        line.addWidget(group, 2)
        left.addLayout(line)

        group = QGroupBox("Параметры")
        grid = QGridLayout(group)
        only_selected = QCheckBox("Фрезеровать только выделенное")
        only_selected.setEnabled(False)
        self.scale = QComboBox()
        for label, _ in SCALES:
            self.scale.addItem(label)
        self.scale.setCurrentIndex(read_int(settings, "milling/scale", 0))
        self.slow = QCheckBox("Сверлить с минимальной подачей")
        self.slow.setChecked(read_bool(settings, "milling/slow", False))
        grid.addWidget(only_selected, 0, 0)
        grid.addWidget(QLabel("Масштаб:"), 0, 1)
        grid.addWidget(self.scale, 0, 2)
        grid.addWidget(self.slow, 1, 0)
        left.addWidget(group)

        right = QVBoxLayout()
        outer.addLayout(right, 2)
        title = QLabel("Порядок заданий — перетаскиванием")
        title.setStyleSheet("color: #e00000; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(title)
        self.jobs_view = QTreeWidget()
        self.jobs_view.setHeaderLabels(["Перо", "Задание", "Сторона"])
        self.jobs_view.setRootIsDecorated(False)
        self.jobs_view.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.jobs_view.model().rowsMoved.connect(self.renumber)
        self.jobs_view.setColumnWidth(0, 40)
        self.jobs_view.setColumnWidth(1, 180)
        right.addWidget(self.jobs_view, 1)
        self.save_list = QCheckBox("Сохранить список заданий в текстовый файл")
        self.separate = QCheckBox("Отдельный файл на каждое задание")
        self.register_each = QCheckBox("Отверстия для переворота в каждый файл (нулевая точка)")
        for key, check in (
            ("save_list", self.save_list),
            ("separate", self.separate),
            ("register_each", self.register_each),
        ):
            check.setChecked(read_bool(settings, f"milling/{key}", False))
            right.addWidget(check)
        self.separate.toggled.connect(self.update_states)
        right.addSpacing(16)
        self.create_button = QPushButton("Создать…")
        self.create_button.clicked.connect(self.accept)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        for push in (self.create_button, cancel):
            push.setMinimumWidth(110)
            right.addWidget(push, 0, Qt.AlignmentFlag.AlignRight)

        for check, combo, punch in self.sides.values():
            check.toggled.connect(self.refresh_jobs)
            combo.currentIndexChanged.connect(self.refresh_jobs)
            punch.toggled.connect(self.refresh_jobs)
        for widget in (self.drill_output, self.contour_output, self.register_count):
            widget.currentIndexChanged.connect(self.refresh_jobs)
        self.tool.valueChanged.connect(self.refresh_jobs)
        self.drill_tool.valueChanged.connect(self.refresh_jobs)
        self.drill_mode.idToggled.connect(self.refresh_jobs)
        self.refresh_jobs()

    # --- job list ----------------------------------------------------------------------

    def planned(self) -> list[tuple[str, str, str]]:
        """(key, name, side) of every job the options ask for."""
        result = []
        holes = core.holes(self.board)
        for key, (check, _combo, punch) in self.sides.items():
            if check.isChecked():
                side = "C1" if key == "top" else "C2"
                result.append((f"iso_{key}", f"Изоляция, фреза {self.tool.value():g} мм", side))
                if punch.isChecked() and holes:
                    result.append((f"punch_{key}", "Метки центров отверстий", side))
        drill_side = self.drill_output.currentIndex()
        if drill_side and holes:
            side = "C1" if drill_side == 1 else "C2"
            mode = self.drill_mode.checkedId()
            if mode == 0:
                name = f"Фрезеровка отверстий {self.drill_tool.value():g} мм"
                result.append(("drill_ci", name, side))
            elif mode == 1:
                result.append(("drill_all", "Сверловка (одно сверло)", side))
            else:
                for diameter in sorted({d for d, _ in holes}):
                    result.append((f"drill_{diameter}", f"Сверло {diameter:g} мм", side))
        contour_side = self.contour_output.currentIndex()
        if contour_side and any(obj.layer == 7 for obj in self.board.elements):
            result.append(("contour", "Контур платы", "C1" if contour_side == 1 else "C2"))
        if self.register_count.currentIndex():
            result.append(("register", REGISTER, "C1"))
        return result

    def refresh_jobs(self, *_args):
        self.picture.count = (0, 2, 4)[self.register_count.currentIndex()]
        self.picture.update()
        planned = {key: (name, side) for key, name, side in self.planned()}
        kept = [key for key in self.current_order() if key in planned]
        order = kept + [key for key in planned if key not in kept]
        self.jobs_view.clear()
        for number, key in enumerate(order, 1):
            name, side = planned[key]
            item = QTreeWidgetItem([str(number), name, side])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
            self.jobs_view.addTopLevelItem(item)
        self.create_button.setEnabled(bool(order))
        self.update_states()

    def current_order(self) -> list[str]:
        if not hasattr(self, "jobs_view"):
            return []
        return [
            self.jobs_view.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
            for i in range(self.jobs_view.topLevelItemCount())
        ]

    def renumber(self, *_args):
        for i in range(self.jobs_view.topLevelItemCount()):
            self.jobs_view.topLevelItem(i).setText(0, str(i + 1))

    def update_states(self, *_args):
        registers = self.register_count.currentIndex() > 0
        self.register_each.setEnabled(self.separate.isChecked() and registers)

    def remember(self):
        s = self.settings
        for key, (check, combo, punch) in self.sides.items():
            s.setValue(f"milling/{key}", check.isChecked())
            s.setValue(f"milling/{key}_mirror", combo.currentIndex())
            s.setValue(f"milling/{key}_punch", punch.isChecked())
        s.setValue("milling/tool", self.tool.value())
        s.setValue("milling/passes", self.passes.value())
        s.setValue("milling/overlap", self.overlap.value())
        s.setValue("milling/drill_side", self.drill_output.currentIndex())
        s.setValue("milling/drill_mode2", self.drill_mode.checkedId())
        s.setValue("milling/drill_tool", self.drill_tool.value())
        s.setValue("milling/contour_side", self.contour_output.currentIndex())
        s.setValue("milling/register", self.register_count.currentIndex())
        s.setValue("milling/register_distance", self.register_distance.value())
        s.setValue("milling/text", self.text_mode.checkedId())
        s.setValue("milling/scale", self.scale.currentIndex())
        s.setValue("milling/slow", self.slow.isChecked())
        for key, check in (
            ("save_list", self.save_list),
            ("separate", self.separate),
            ("register_each", self.register_each),
        ):
            s.setValue(f"milling/{key}", check.isChecked())

    # --- geometry ----------------------------------------------------------------------

    def mirror_for(self, side: str) -> float | None:
        board = self.board
        key = "top" if side == "C1" else "bottom"
        if self.sides[key][1].currentIndex() != 1:
            return None
        return board.width - 2 * core.board_origin(board)[0]

    def build(self, key: str, name: str, side: str, pen: int) -> hpgl.Job:
        board = self.board
        ox, oy = core.board_origin(board)
        job = hpgl.Job(name, pen, side=side, mirror_width=self.mirror_for(side))
        holes = [(pad.x - ox, pad.y - oy, d) for d, pad in core.holes(board)]
        slow = self.slow.isChecked()
        if key.startswith("iso_"):
            layer = 1 if key == "iso_top" else 3
            singleline = self.text_mode.checkedId() == 1
            source = board
            if singleline:
                # Texts are milled along their strokes instead of around their outline.
                kept = [
                    obj
                    for obj in board.elements
                    if not (obj.kind == core.STROKE_TEXT and obj.layer == layer)
                ]
                source = replace(board, elements=kept)
            copper = copper_of(source, "copper_top" if layer == 1 else "copper_bottom")
            job.paths = isolation(
                copper, self.tool.value(), self.passes.value(), self.overlap.value() / 100
            )
            if singleline:
                job.paths += text_strokes(board, layer)
        elif key.startswith("punch_") or key == "drill_all":
            job.drills = [(x, y) for x, y, _ in holes]
            job.slow = slow
        elif key == "drill_ci":
            tool = self.drill_tool.value()
            job.circles = [((x, y), (d - tool) / 2) for x, y, d in holes if d > tool]
            job.drills = [(x, y) for x, y, d in holes if d <= tool]
            job.slow = slow
        elif key.startswith("drill_"):
            diameter = float(key.split("_", 1)[1])
            job.drills = [(x, y) for x, y, d in holes if d == diameter]
            job.slow = slow
        elif key == "contour":
            job.paths = contour_lines(board)
        elif key == "register":
            count = (0, 2, 4)[self.register_count.currentIndex()]
            area = (-ox, -board.height - oy, board.width - ox, -oy)
            job.drills = hpgl.register_holes(*area, self.register_distance.value(), count)
        return job

    def jobs(self) -> list[hpgl.Job]:
        planned = {key: (name, side) for key, name, side in self.planned()}
        return [
            self.build(key, *planned[key], pen) for pen, key in enumerate(self.current_order(), 1)
        ]

    def write(self, path: Path) -> list[Path]:
        jobs = self.jobs()
        units = SCALES[self.scale.currentIndex()][1]
        written = []
        if self.separate.isChecked():
            register = [job for job in jobs if job.name == REGISTER]
            for number, job in enumerate(jobs, 1):
                selected = [job]
                if self.register_each.isChecked() and register and job not in register:
                    selected = register + selected
                target = path.with_name(f"{path.stem}_{number}{path.suffix or '.plt'}")
                target.write_text(hpgl.hpgl_text(selected, units), encoding="ascii")
                written.append(target)
        else:
            path.write_text(hpgl.hpgl_text(jobs, units), encoding="ascii")
            written.append(path)
        if self.save_list.isChecked():
            listing = path.with_suffix(".txt")
            listing.write_text(hpgl.job_list(jobs), encoding="utf-8")
            written.append(listing)
        return written
