"""Design rule check: distances between copper of different nets and between holes,
minimum and maximum sizes, and print or mask problems; a side panel like the original's."""

from collections import defaultdict
from dataclasses import dataclass, field
from math import floor, hypot

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QPainterPath, QPainterPathStroker
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import core

from .connectivity import copper_layers_of, nets
from .export_dialogs import mm_field
from .render import geometry
from .settings import read_bool, read_float
from .style import LAYERS
from .widgets import PanelTitle

PANEL_COLOR = "#eacfbb"  # measured on the original's DRC panel
CELL = 4.0

# (key, label, default) of every value check
DISTANCES = (("copper", "Медь:", 0.15), ("holes", "Отверстия:", 0.50))
LIMITS = (
    ("hole_min", "Отверстие мин.:", 0.30),
    ("hole_max", "Отверстие макс.:", 8.00),
    ("track_min", "Дорожка мин.:", 0.20),
    ("ring_min", "Поясок мин.:", 0.20),
    ("silk_min", "Шелкография мин.:", 0.15),
)
DISTANCE_KEYS = {key for key, _label, _default in DISTANCES}
OTHERS = (
    ("silk_pads", "Шелкография на площадках"),
    ("smd_holes", "Отверстия в SMD-площадках"),
    ("no_mask", "Площадки без окна в маске"),
    ("mask_off_pads", "Окна маски вне площадок"),
)


@dataclass
class Rules:
    distances: dict[str, float | None] = field(default_factory=dict)
    limits: dict[str, float | None] = field(default_factory=dict)
    others: set[str] = field(default_factory=set)


@dataclass
class Violation:
    text: str
    position: QPointF  # scene coordinates
    objects: list[int]


def _grown(path: QPainterPath, distance: float) -> QPainterPath:
    stroker = QPainterPathStroker()
    stroker.setWidth(2 * distance)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    return path.united(stroker.createStroke(path))


def _cells(rect: QRectF):
    for gx in range(floor(rect.left() / CELL), floor(rect.right() / CELL) + 1):
        for gy in range(floor(rect.top() / CELL), floor(rect.bottom() / CELL) + 1):
            yield gx, gy


def _mm(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def _centre(obj) -> QPointF:
    x, y = core.centre_of(obj)
    return QPointF(x, -y)


def check(board, rules: Rules, area: QRectF | None = None) -> list[Violation]:
    """All violations on a board; with area, only those inside it (scene coordinates)."""
    elements = board.elements
    result: list[Violation] = []
    warnings: set[str] = set()

    def add(text, position, objects):
        if area is None or area.contains(position):
            result.append(Violation(text, position, list(objects)))

    copper_gap = rules.distances.get("copper")
    if copper_gap:
        numbers = nets(board)
        shapes = []
        for index, obj in enumerate(elements):
            if index not in numbers:
                continue
            path = geometry(obj, warnings)
            for layer in copper_layers_of(obj, board):
                shapes.append((index, layer, path, path.boundingRect()))
        grid: dict[tuple[int, int, int], list[int]] = defaultdict(list)
        for number, (_i, layer, _p, rect) in enumerate(shapes):
            for gx, gy in _cells(rect.adjusted(-copper_gap, -copper_gap, copper_gap, copper_gap)):
                grid[(layer, gx, gy)].append(number)
        grown: dict[int, QPainterPath] = {}
        seen: set[tuple[int, int]] = set()
        for members in grid.values():
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    a, b = members[i], members[j]
                    ia, la, pa, ra = shapes[a]
                    ib, _lb, pb, rb = shapes[b]
                    pair = (min(ia, ib), max(ia, ib))
                    if ia == ib or pair in seen or numbers[ia] == numbers[ib]:
                        continue
                    near = ra.adjusted(-copper_gap, -copper_gap, copper_gap, copper_gap)
                    if not near.intersects(rb):
                        continue
                    if a not in grown:
                        grown[a] = _grown(pa, copper_gap)
                    if grown[a].intersects(pb):
                        seen.add(pair)
                        touch = grown[a].intersected(pb).boundingRect().center()
                        add(
                            f"Зазор меди меньше {_mm(copper_gap)} мм ({LAYERS[la][0]})", touch, pair
                        )

    holes = [(i, obj) for i, obj in enumerate(elements) if obj.kind == core.THT and obj.inner > 0]
    hole_gap = rules.distances.get("holes")
    if hole_gap:
        for k, (ia, a) in enumerate(holes):
            for ib, b in holes[k + 1 :]:
                edge = hypot(a.x - b.x, a.y - b.y) - a.inner - b.inner
                if edge < hole_gap:
                    middle = QPointF((a.x + b.x) / 2, -(a.y + b.y) / 2)
                    add(f"Отверстия ближе {_mm(hole_gap)} мм", middle, (ia, ib))
    limits = rules.limits
    eps = 1e-9

    def below(value: float, key: str) -> bool:
        limit = limits.get(key)
        return limit is not None and value < limit - eps

    def above(value: float, key: str) -> bool:
        limit = limits.get(key)
        return limit is not None and value > limit + eps

    for index, obj in holes:
        diameter = 2 * obj.inner
        if below(diameter, "hole_min"):
            add(f"Отверстие {_mm(diameter)} мм меньше минимума", _centre(obj), [index])
        if above(diameter, "hole_max"):
            add(f"Отверстие {_mm(diameter)} мм больше максимума", _centre(obj), [index])
        ring = obj.outer - obj.inner
        if not core.is_bare_hole(obj) and below(ring, "ring_min"):
            add(f"Поясок {_mm(round(ring, 3))} мм меньше минимума", _centre(obj), [index])
    for index, obj in enumerate(elements):
        if core.is_hidden_label(obj):
            continue
        if obj.kind == core.LINE and obj.layer in (1, 3, 5, 6) and below(obj.width, "track_min"):
            add(f"Дорожка {_mm(obj.width)} мм уже минимума", _centre(obj), [index])
        if obj.layer in (2, 4) and obj.kind in (core.LINE, core.STROKE_TEXT):
            widths = (
                [c.width for c in obj.children] if obj.kind == core.STROKE_TEXT else [obj.width]
            )
            thinnest = min(widths, default=1.0)
            if below(thinnest, "silk_min"):
                add(f"Линия шелкографии {_mm(thinnest)} мм тоньше минимума", _centre(obj), [index])

    others = rules.others
    pads = [(i, obj) for i, obj in enumerate(elements) if obj.kind in core.PADS]
    if "no_mask" in others:
        for index, obj in pads:
            if not obj.soldermask and not core.is_bare_hole(obj):
                add("Площадка без окна в маске", _centre(obj), [index])
    if "mask_off_pads" in others:
        for index, obj in enumerate(elements):
            if obj.soldermask and obj.kind not in core.PADS and not core.is_hidden_label(obj):
                add("Окно в маске не на площадке", _centre(obj), [index])
    if "smd_holes" in others:
        for ih, hole in holes:
            for ip, pad in pads:
                same_side = pad.kind == core.SMD and pad.layer in copper_layers_of(hole, board)
                if same_side and geometry(pad, warnings).contains(QPointF(hole.x, -hole.y)):
                    add("Отверстие в SMD-площадке", _centre(hole), (ih, ip))
    if "silk_pads" in others:
        sides = {2: 1, 4: 3}
        pad_shapes = {
            side: [
                (i, geometry(obj, warnings))
                for i, obj in pads
                if side in copper_layers_of(obj, board)
            ]
            for side in (1, 3)
        }
        for index, obj in enumerate(elements):
            if obj.layer not in sides or core.is_hidden_label(obj):
                continue
            path = geometry(obj, warnings)
            rect = path.boundingRect()
            for ip, pad_path in pad_shapes[sides[obj.layer]]:
                if rect.intersects(pad_path.boundingRect()) and path.intersects(pad_path):
                    spot = path.intersected(pad_path).boundingRect().center()
                    add("Шелкография на площадке", spot, (index, ip))
    return result


class DrcPanel(QWidget):
    """The DRC side panel: rules, the check buttons and the list of violations."""

    hidden = Signal()
    run_requested = Signal(bool)  # True: only the visible window
    chosen = Signal(object)  # Violation
    mark_all = Signal()

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.violations: list[Violation] = []
        self.setObjectName("drcpanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#drcpanel {{ background: {PANEL_COLOR}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(PanelTitle("DRC", self.close_panel, color="#ffffff"))
        body = QVBoxLayout()
        body.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(body, 1)
        self.values: dict[str, tuple[QCheckBox, QDoubleSpinBox]] = {}
        for title, rows in (("Минимальный зазор", DISTANCES), ("Мин./макс.", LIMITS)):
            group = QGroupBox(title)
            grid = QGridLayout(group)
            for row, (key, label, default) in enumerate(rows):
                check = QCheckBox(label)
                check.setChecked(read_bool(settings, f"drc/{key}_on", True))
                field_box = mm_field(read_float(settings, f"drc/{key}", default), 0, 50)
                grid.addWidget(check, row, 0)
                grid.addWidget(field_box, row, 1)
                grid.addWidget(QLabel("мм"), row, 2)
                self.values[key] = (check, field_box)
            body.addWidget(group)
        group = QGroupBox("Прочее")
        box = QVBoxLayout(group)
        self.others: dict[str, QCheckBox] = {}
        for key, label in OTHERS:
            check = QCheckBox(label)
            check.setChecked(read_bool(settings, f"drc/{key}", True))
            box.addWidget(check)
            self.others[key] = check
        body.addWidget(group)
        body.addSpacing(10)
        line = QHBoxLayout()
        complete = QPushButton("▷ Вся плата…")
        complete.clicked.connect(lambda: self.run_requested.emit(False))
        window = QPushButton("▷ Окно…")
        window.clicked.connect(lambda: self.run_requested.emit(True))
        line.addWidget(complete)
        line.addWidget(window)
        body.addLayout(line)
        self.select_all = QPushButton("Отметить все")
        self.select_all.setEnabled(False)
        self.select_all.clicked.connect(self.mark_all.emit)
        body.addWidget(self.select_all)
        self.count = QLabel()
        body.addWidget(self.count)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.row_chosen)
        body.addWidget(self.list, 1)

    def close_panel(self):
        self.hide()
        self.hidden.emit()

    def rules(self) -> Rules:
        rules = Rules()
        for key, (check, box) in self.values.items():
            value = box.value() if check.isChecked() else None
            target = rules.distances if key in DISTANCE_KEYS else rules.limits
            target[key] = value
            self.settings.setValue(f"drc/{key}_on", check.isChecked())
            self.settings.setValue(f"drc/{key}", box.value())
        for key, check in self.others.items():
            if check.isChecked():
                rules.others.add(key)
            self.settings.setValue(f"drc/{key}", check.isChecked())
        return rules

    def show_violations(self, violations: list[Violation]) -> None:
        self.violations = violations
        self.list.clear()
        for number, violation in enumerate(violations, 1):
            QListWidgetItem(f"{number}. {violation.text}", self.list)
        self.count.setText(
            f"Нарушений: {len(violations)}" if violations else "Нарушений не найдено"
        )
        self.select_all.setEnabled(bool(violations))

    def row_chosen(self, row: int) -> None:
        if 0 <= row < len(self.violations):
            self.chosen.emit(self.violations[row])
