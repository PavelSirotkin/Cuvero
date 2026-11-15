"""Electrical connectivity: which copper objects touch, through layers and ground planes.

Shapes come from the same geometry as the screen; ground planes from the exact output
geometry, split into separate islands. Plated through-hole pads join all copper layers.
"""

from collections import defaultdict
from math import floor

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainterPath, QPolygonF

import core

from .render import geometry, plane_path

COPPER = (1, 3, 5, 6)
CELL = 4.0  # mm, size of the grid used to find neighbours quickly


class Groups:
    """Union-find over node numbers."""

    def __init__(self):
        self.parent: dict[int, int] = {}

    def find(self, node: int) -> int:
        root = self.parent.setdefault(node, node)
        while root != self.parent[root]:
            root = self.parent[root]
        while node != root:
            node, self.parent[node] = self.parent[node], root
        return root

    def join(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def islands(path: QPainterPath) -> list[QPainterPath]:
    """Separate pieces of a filled area, each with its own holes (even-odd filled)."""
    polygons = [p for p in path.toSubpathPolygons() if p.size() >= 3]
    bounds = [p.boundingRect() for p in polygons]
    rule = path.fillRule()
    depth = []
    for i, polygon in enumerate(polygons):
        point = polygon.at(0)
        depth.append(
            sum(
                1
                for j, other in enumerate(polygons)
                if j != i and bounds[j].contains(point) and other.containsPoint(point, rule)
            )
        )
    result = []
    for i, polygon in enumerate(polygons):
        if depth[i] % 2:
            continue
        piece = QPainterPath()
        piece.setFillRule(Qt.FillRule.OddEvenFill)
        piece.addPolygon(polygon)
        piece.closeSubpath()
        for j, hole in enumerate(polygons):
            if (
                depth[j] == depth[i] + 1
                and bounds[i].contains(hole.at(0))
                and polygon.containsPoint(hole.at(0), rule)
            ):
                piece.addPolygon(QPolygonF(hole))
                piece.closeSubpath()
        result.append(piece)
    return result


def _cells(rect: QRectF):
    for gx in range(floor(rect.left() / CELL), floor(rect.right() / CELL) + 1):
        for gy in range(floor(rect.top() / CELL), floor(rect.bottom() / CELL) + 1):
            yield gx, gy


def copper_layers_of(obj, board) -> tuple[int, ...]:
    if obj.kind == core.THT and obj.plated and obj.inner > 0:
        return COPPER if board.multilayer else (1, 3)
    return (obj.layer,) if obj.layer in COPPER else ()


def nets(board) -> dict[int, int]:
    """Net number of every copper object, by object index (connected objects share it)."""
    groups = Groups()
    shapes: list[tuple[int, int, QPainterPath, QRectF]] = []  # node, layer, path, bounds
    warnings: set[str] = set()
    for index, obj in enumerate(board.elements):
        if obj.keepout or core.is_hidden_label(obj) or core.is_bare_hole(obj):
            continue
        layers = copper_layers_of(obj, board)
        if not layers:
            continue
        path = geometry(obj, warnings)
        if obj.kind == core.STROKE_TEXT and path.isEmpty():
            continue
        groups.find(index)
        for layer in layers:
            shapes.append((index, layer, path, path.boundingRect()))
    node = len(board.elements)
    for layer in COPPER:
        if not core.has_plane(board, layer) or (layer in (5, 6) and not board.multilayer):
            continue
        for piece in islands(plane_path(board, layer)):
            groups.find(node)
            shapes.append((node, layer, piece, piece.boundingRect()))
            node += 1
    grid: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for number, (_node, layer, _path, rect) in enumerate(shapes):
        for gx, gy in _cells(rect):
            grid[(layer, gx, gy)].append(number)
    checked: set[tuple[int, int]] = set()
    for cell_items in grid.values():
        for i in range(len(cell_items)):
            for j in range(i + 1, len(cell_items)):
                a, b = cell_items[i], cell_items[j]
                pair = (a, b) if a < b else (b, a)
                if pair in checked:
                    continue
                checked.add(pair)
                na, _la, pa, ra = shapes[a]
                nb, _lb, pb, rb = shapes[b]
                if groups.find(na) == groups.find(nb) or not ra.intersects(rb):
                    continue
                if pa.intersects(pb):
                    groups.join(na, nb)
    return {
        index: groups.find(index) for index in range(len(board.elements)) if index in groups.parent
    }


def net_of(board, index: int, wires: bool = False) -> list[int]:
    """All objects electrically connected with the object at index (itself included).

    With wires, air wires count as connections too.
    """
    numbers = nets(board)
    if index not in numbers:
        return [index]
    if wires:
        joined = Groups()
        for a, b in core.air_wires(board):
            if a in numbers and b in numbers:
                joined.join(numbers[a], numbers[b])
        numbers = {i: joined.find(n) for i, n in numbers.items()}
    net = numbers[index]
    return sorted(i for i, n in numbers.items() if n == net)


def point(x: float, y: float) -> QPointF:
    return QPointF(x, -y)
