"""Autorouter for one air wire on one copper layer: a grid search around foreign copper.

Copper of other nets is rasterised, grown by the clearance plus half the track width, and
the shortest grid path (8 directions, a small penalty for bends) joins the two pad centres.
"""

import heapq
from dataclasses import dataclass, replace
from math import hypot

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPathStroker
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

import core

from .connectivity import copper_layers_of, nets
from .export_dialogs import mm_field
from .icons import tool_icon
from .render import geometry

AUTOROUTE_GRID = 0.635  # mm, the original's grid for routing
STEPS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]


@dataclass
class RouteResult:
    points: list[core.Point] | None
    message: str


def _blocked_image(board, layer: int, keep: set[int], grow: float, grid: float) -> QImage:
    """Board area as pixels of one grid cell; foreign copper (grown) is set."""
    width = max(int(board.width / grid) + 1, 2)
    height = max(int(board.height / grid) + 1, 2)
    image = QImage(width, height, QImage.Format.Format_Grayscale8)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    # Pixel (cx, cy) is filled when its centre is covered: put the centre on the grid point.
    painter.translate(0.5, 0.5)
    painter.scale(1 / grid, 1 / grid)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("white"))
    stroker = QPainterPathStroker()
    stroker.setWidth(2 * grow)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    warnings: set[str] = set()
    for index, obj in enumerate(board.elements):
        if index in keep or core.is_hidden_label(obj):
            continue
        if layer not in copper_layers_of(obj, board) and not obj.keepout:
            continue
        if obj.keepout and obj.layer != layer:
            continue
        path = geometry(obj, warnings)
        painter.drawPath(path)
        painter.drawPath(stroker.createStroke(path))
    # A ground plane is no obstacle: it gives way to new tracks with its own clearance.
    painter.end()
    return image


def route(
    board, a: int, b: int, layer: int, width: float, clearance: float, grid: float
) -> RouteResult:
    """A track from pad a to pad b on the layer, or why there is none."""
    numbers = nets(board)
    own = {numbers.get(a), numbers.get(b)} - {None}
    keep = {i for i, n in numbers.items() if n in own} | {a, b}
    image = _blocked_image(board, layer, keep, clearance + width / 2, grid)
    columns, rows = image.width(), image.height()
    data = bytes(image.constBits())
    stride = image.bytesPerLine()

    def free(cx: int, cy: int) -> bool:
        return 0 <= cx < columns and 0 <= cy < rows and data[cy * stride + cx] < 128

    (ax, ay), (bx, by) = core.centre_of(board.elements[a]), core.centre_of(board.elements[b])
    start = (round(ax / grid), round(-ay / grid))
    goal = (round(bx / grid), round(-by / grid))
    if not (0 <= start[0] < columns and 0 <= goal[0] < columns):
        return RouteResult(None, "Площадка вне рабочего поля")
    open_heap: list[tuple[float, float, tuple[int, int], tuple[int, int]]] = []
    came: dict[tuple[int, int], tuple[tuple[int, int], tuple[int, int]]] = {}
    cost: dict[tuple[int, int], float] = {start: 0.0}
    heapq.heappush(open_heap, (0.0, 0.0, start, (0, 0)))
    limit = columns * rows * 4
    while open_heap and limit:
        limit -= 1
        _f, g, cell, direction = heapq.heappop(open_heap)
        if cell == goal:
            break
        if g > cost.get(cell, float("inf")):
            continue
        for dx, dy in STEPS:
            nxt = (cell[0] + dx, cell[1] + dy)
            if nxt != goal and not free(*nxt):
                continue
            step = 1.4142 if dx and dy else 1.0
            bend = 0.3 if direction != (0, 0) and (dx, dy) != direction else 0.0
            new_cost = g + step + bend
            if new_cost < cost.get(nxt, float("inf")):
                cost[nxt] = new_cost
                came[nxt] = (cell, (dx, dy))
                h = hypot(goal[0] - nxt[0], goal[1] - nxt[1])
                heapq.heappush(open_heap, (new_cost + h, new_cost, nxt, (dx, dy)))
    if goal not in came:
        return RouteResult(None, "Путь не найден: мешает медь других цепей")
    cells = [goal]
    while cells[-1] != start:
        cells.append(came[cells[-1]][0])
    cells.reverse()
    # Keep only the corners.
    corners = [cells[0]]
    for prev, here, nxt in zip(cells, cells[1:], cells[2:], strict=False):
        if (here[0] - prev[0], here[1] - prev[1]) != (nxt[0] - here[0], nxt[1] - here[1]):
            corners.append(here)
    corners.append(cells[-1])
    points = [(round(cx * grid, 6), round(-cy * grid, 6)) for cx, cy in corners]
    points[0], points[-1] = (ax, ay), (bx, by)
    return RouteResult(points, "Проложено")


def routed_board(board, a: int, b: int, layer: int, points, width: float):
    """The board with the new track added and the routed air wire removed."""
    elements = list(board.elements)
    if b in core.wired_to(board.elements[a]):
        for index, obj in core.toggled_wire(board, a, b).items():
            elements[index] = obj
    elements.append(core.new_track(board, layer, points, width))
    return replace(board, elements=elements)


def wire_at(board, point: QPointF, reach: float) -> tuple[int, int] | None:
    """The air wire nearest to a scene point, within reach."""
    best, best_distance = None, reach
    for a, b in core.air_wires(board):
        (ax, ay), (bx, by) = core.centre_of(board.elements[a]), core.centre_of(board.elements[b])
        p1, p2 = QPointF(ax, -ay), QPointF(bx, -by)
        dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
        length = dx * dx + dy * dy
        t = 0.0 if not length else ((point.x() - p1.x()) * dx + (point.y() - p1.y()) * dy) / length
        t = min(max(t, 0.0), 1.0)
        nearest = QPointF(p1.x() + t * dx, p1.y() + t * dy)
        distance = hypot(point.x() - nearest.x(), point.y() - nearest.y())
        if distance <= best_distance:
            best, best_distance = (a, b), distance
    return best


class RouteBar(QWidget):
    """Autorouter options above the board, as in the original."""

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.setObjectName("routebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("QWidget#routebar { background: #ffffff; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        icon = QLabel()
        icon.setPixmap(tool_icon("autoroute").pixmap(32, 32))
        layout.addWidget(icon)
        layout.addSpacing(12)
        grid = QGridLayout()
        self.width_box = mm_field(float(settings.value("route/width", 0.4)), 0.05, 10)
        self.clearance_box = mm_field(float(settings.value("route/clearance", 0.2)), 0.05, 10)
        grid.addWidget(QLabel("Ширина дорожки:"), 0, 0)
        grid.addWidget(self.width_box, 0, 1)
        grid.addWidget(QLabel("мм"), 0, 2)
        grid.addWidget(QLabel("Мин. зазор:"), 1, 0)
        grid.addWidget(self.clearance_box, 1, 1)
        grid.addWidget(QLabel("мм"), 1, 2)
        layout.addLayout(grid)
        column = QGridLayout()
        self.on_grid = QCheckBox("По текущей сетке")
        self.on_grid.setChecked(str(settings.value("route/on_grid", "true")).lower() == "true")
        self.grid_label = QLabel()
        column.addWidget(self.on_grid, 0, 0)
        column.addWidget(self.grid_label, 1, 0)
        layout.addSpacing(16)
        layout.addLayout(column)
        status = QGridLayout()
        status.addWidget(QLabel("Состояние:"), 0, 0)
        self.status = QLineEdit("Готов")
        self.status.setReadOnly(True)
        self.status.setMinimumWidth(260)
        status.addWidget(self.status, 1, 0)
        layout.addSpacing(16)
        layout.addLayout(status)
        layout.addStretch()
        self.current_grid = AUTOROUTE_GRID
        self.on_grid.toggled.connect(self.update_grid)
        self.update_grid()

    def grid(self) -> float:
        return self.current_grid if self.on_grid.isChecked() else AUTOROUTE_GRID

    def update_grid(self, *_args):
        # As in the original: the autorouter's own grid, greyed out while the current
        # grid is used instead.
        self.grid_label.setText(f"Сетка трассировки: {AUTOROUTE_GRID:g} мм".replace(".", ","))
        self.grid_label.setEnabled(not self.on_grid.isChecked())
        self.settings.setValue("route/on_grid", self.on_grid.isChecked())

    def remember(self):
        self.settings.setValue("route/width", self.width_box.value())
        self.settings.setValue("route/clearance", self.clearance_box.value())
