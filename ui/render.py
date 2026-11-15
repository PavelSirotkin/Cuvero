"""Conversion of board objects to Qt painter paths and scene items."""

from math import cos, hypot, radians, sin

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
    QTransform,
)

import core
from core import gerber_read

from .gerber_paths import copper_path
from .style import (
    COPPER,
    HOLE_COLOR,
    LAYERS,
    OPTIONS,
    PLANE_SHADE,
    THROUGH,
    THROUGH_COLOR,
    WIRE_COLOR,
)


def point(x, y):
    return QPointF(x, -y)


def ellipse(center, radius):
    path = QPainterPath()
    path.addEllipse(center, radius, radius)
    return path


def polyline(points, closed=False):
    path = QPainterPath()
    if points:
        path.moveTo(point(*points[0]))
        for xy in points[1:]:
            path.lineTo(point(*xy))
        if closed:
            path.closeSubpath()
    return path


def stroke(path, width):
    stroker = QPainterPathStroker()
    stroker.setWidth(width)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return stroker.createStroke(path)


def tht_shape(obj):
    r = obj.outer
    center = point(obj.x, obj.y)
    if obj.shape == 1:
        return ellipse(center, r)
    if core.has_corners(obj):
        # Rectangular pads that keep their four corners, like SMD pads.
        return polyline(obj.points[:4], closed=True)

    half_x = r * (2 if obj.shape in (4, 5, 6) else 1)
    half_y = r * (2 if obj.shape in (7, 8, 9) else 1)
    rect = QRectF(-half_x, -half_y, half_x * 2, half_y * 2)
    path = QPainterPath()
    if obj.shape in (4, 7):
        path.addRoundedRect(rect, r, r)
    elif obj.shape in (2, 5, 8):
        cut = r * (2 - 2**0.5)
        x, y = half_x, half_y
        path = polyline(
            [
                (-x + cut, -y),
                (x - cut, -y),
                (x, -y + cut),
                (x, y - cut),
                (x - cut, y),
                (-x + cut, y),
                (-x, y - cut),
                (-x, -y + cut),
            ],
            closed=True,
        )
    else:
        path.addRect(rect)
    transform = QTransform.fromTranslate(center.x(), center.y())
    transform.rotate(-core.pad_rotation(obj))
    return transform.map(path)


def geometry(obj, warnings):
    center = point(obj.x, obj.y)
    if obj.kind == core.THT:
        if obj.shape not in range(1, 10):
            warnings.add(f"Неизвестная форма площадки на слое {obj.layer}")
            return ellipse(center, abs(obj.outer))
        return tht_shape(obj)
    if obj.kind == core.SMD:
        if len(obj.points) >= 3:
            return polyline(obj.points, closed=True)
        path = QPainterPath()
        path.addRect(
            QRectF(center.x() - obj.outer / 2, center.y() - obj.inner / 2, obj.outer, obj.inner)
        )
        warnings.add(f"SMD без контура на слое {obj.layer}")
        return path
    if obj.kind == core.SEGMENT:
        return stroke(polyline([(obj.x, obj.y), (obj.outer, obj.inner)]), max(obj.width, 0.02))
    if obj.kind in (core.LINE, core.POLYGON):
        closed = obj.kind == core.POLYGON
        path = polyline(obj.points, closed)
        if closed and len(obj.points) >= 3 and obj.layer != 7:
            return path
        return stroke(path, max(obj.width, 0.02))
    if obj.kind == core.CIRCLE:
        radius = (obj.outer + obj.inner) / 2
        start, end = obj.start, round(obj.width * core.MM)
        if max(abs(start), abs(end)) > 1000:
            start, end = start / 1000, end / 1000
        if end == start or abs(end - start) >= 360:
            path = ellipse(center, radius)
            if obj.filled:
                return ellipse(center, obj.outer)
        else:
            path = QPainterPath()
            rect = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
            path.arcMoveTo(rect, start)
            path.arcTo(rect, start, (end - start) % 360)
        return stroke(path, max(obj.outer - obj.inner, 0.02))

    if obj.kind == core.STROKE_TEXT and obj.children:
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        for child in obj.children:
            path.addPath(geometry(child, warnings))
        return path

    path = QPainterPath()
    if obj.text:
        warnings.add(f"Текст заменён системным шрифтом на слое {obj.layer}")
        font = QFont("Sans Serif")
        font.setPixelSize(100)
        path.addText(QPointF(), font, obj.text)
        height = path.boundingRect().height()
        if height:
            scale = max(obj.outer, 0.1) / height
            transform = QTransform.fromTranslate(center.x(), center.y())
            transform.rotate(-obj.rotation % 360)
            transform.scale(-scale if obj.mirror_x else scale, -scale if obj.mirror_y else scale)
            path = transform.map(path)
    return path


# Byte of the thermal direction mask that belongs to each copper layer.
PLANE_LAYER_INDEX = {1: 0, 3: 1, 5: 2, 6: 3}
MASK_COLOR = QColor(0, 150, 70, 110)


def thermal_spokes(obj, layer: int) -> QPainterPath | None:
    """Spokes of a thermal relief on one copper layer, as filled bars from the pad centre.

    They are cut out of the clearance ring, so the auto ground plane stays connected to the
    pad along each spoke, like in the original program.
    """
    if not core.has_thermal(obj):
        return None
    if obj.kind == core.THT:
        bits = core.thermal_layer_directions(obj, PLANE_LAYER_INDEX.get(layer, 0))
        size = obj.outer * (2 if obj.shape in range(4, 10) else 1)
    else:
        bits = core.thermal_directions(obj)
        size = hypot(*core.smd_size(obj)) / 2
    if not bits or obj.width <= 0:
        return None
    reach = size + obj.clearance + 0.1
    half = obj.width / 2
    cx, cy = core.centre_of(obj)
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    for bit in range(8):
        if not bits >> bit & 1:
            continue
        angle = radians(core.spoke_angle(obj, bit))
        dx, dy = cos(angle), sin(angle)
        nx, ny = -dy * half, dx * half
        corners = [
            (cx + nx, cy + ny),
            (cx + dx * reach + nx, cy + dy * reach + ny),
            (cx + dx * reach - nx, cy + dy * reach - ny),
            (cx - nx, cy - ny),
        ]
        path.addPolygon(QPolygonF([point(x, y) for x, y in corners]))
        path.closeSubpath()
    return path


def soldermask_overlay(board, side: int = 1) -> QPainterPath:
    """The solder mask of one side over the board, with the openings cut out exactly as the
    Gerber output makes them (with the usual offsets of the original)."""
    ending = "soldermask_top" if side == 1 else "soldermask_bottom"
    text = core.layer_gerber(board, ending, core.GerberOptions(x2=False))
    openings = copper_path(gerber_read.parse(text))
    ox, oy = core.board_origin(board)
    openings = QTransform(1, 0, 0, -1, ox, -oy).map(openings)
    mask = QPainterPath()
    mask.addRect(QRectF(0, 0, board.width, board.height))
    return mask.subtracted(openings)


PLANE_FILES = {1: "copper_top", 3: "copper_bottom", 5: "copper_inner1", 6: "copper_inner2"}


def plane_path(board, layer: int) -> QPainterPath:
    """The exact automatic ground plane of a copper layer, as written to Gerber.

    The board area, with every object's clearance cut out and thermal spokes added back,
    in scene coordinates.
    """
    options = core.GerberOptions(x2=False, plane_only=True)
    text = core.layer_gerber(board, PLANE_FILES[layer], options)
    path = copper_path(gerber_read.parse(text))
    ox, oy = core.board_origin(board)
    # Gerber coordinates are relative to the board origin with y upwards.
    return QTransform(1, 0, 0, -1, ox, -oy).map(path)


def on_copper(obj, layer: int, board) -> bool:
    """Plated through-hole pads have copper on every copper layer, other objects on theirs."""
    if obj.kind == core.THT and obj.plated and obj.inner > 0:
        return layer in (1, 3) or board.multilayer
    return obj.layer == layer


def bare_hole_mark(obj) -> QPainterPath:
    r = obj.inner * 0.45
    centre = point(obj.x, obj.y)
    path = ellipse(centre, r)
    d = r * 0.7
    path.moveTo(centre + QPointF(-d, -d))
    path.lineTo(centre + QPointF(d, d))
    path.moveTo(centre + QPointF(-d, d))
    path.lineTo(centre + QPointF(d, -d))
    return path


def plane_colour(layer: int) -> QColor:
    colour = QColor(LAYERS[layer][1])
    shade = PLANE_SHADE if OPTIONS.get("darken_planes", True) else 1.0
    # Truncated like the original: C1 #1e6af9 gives #123f95, C2 #00ba00 gives #006f00.
    return QColor(
        int(colour.red() * shade),
        int(colour.green() * shade),
        int(colour.blue() * shade),
    )


TRANSPARENT_OPACITY = 0.6  # layers in the transparent view

PLANE = 100  # group key of a layer's ground plane: PLANE + layer

# Drawing order from the bottom: the ground planes of all layers under every object, as in
# the original; through-hole pads above C1, holes on top of everything.
WIRES = 9  # group key of the air wires, drawn on top
DRAW_ORDER = (PLANE + 3, PLANE + 6, PLANE + 5, PLANE + 1, 3, 6, 5, 1, THROUGH, 4, 2, 7, 0, WIRES)


def draw_board(scene, board, soldermask: int | None = None, transparent: bool = False):
    """Build one scene group per layer, plus the board boundary.

    soldermask is the side (1 or 3) whose mask is laid over the board, or None.
    """
    boundary = QRectF(0, 0, board.width, board.height)
    scene.addRect(boundary, QPen(QColor("#66737b"), 0)).setZValue(-1)
    groups = {layer: scene.createItemGroup([]) for layer in DRAW_ORDER}
    warnings: set[str] = set()
    no_pen = QPen(Qt.PenStyle.NoPen)
    copper_layers = COPPER if board.multilayer else (1, 3)
    for index, obj in enumerate(board.elements):
        if core.is_hidden_label(obj):
            continue
        if obj.layer not in groups or obj.layer == 0:
            warnings.add(f"Неизвестный слой {obj.layer}")
            continue
        path = geometry(obj, warnings)
        layers: tuple[int, ...] = (obj.layer,)
        if obj.kind == core.THT and obj.layer in COPPER:
            layers = tuple(layer for layer in copper_layers if on_copper(obj, layer, board))
        bare = core.is_bare_hole(obj)
        for layer in layers:
            if not obj.keepout and not bare and not path.isEmpty():
                item = scene.addPath(path, no_pen, QColor(LAYERS[layer][1]))
                item.setData(0, index)
                item.setData(1, layer)
                groups[layer].addToGroup(item)
        if len(layers) > 1 and not bare and not path.isEmpty():
            # Shown instead of the separate sides while both copper sides are visible.
            item = scene.addPath(path, no_pen, QColor(THROUGH_COLOR))
            item.setData(0, index)
            item.setData(1, obj.layer)
            groups[THROUGH].addToGroup(item)
        if obj.kind == core.THT and obj.inner > 0:
            hole = ellipse(point(obj.x, obj.y), obj.inner)
            item = scene.addPath(hole, no_pen, HOLE_COLOR)
            groups[0].addToGroup(item)
            if bare:
                item.setData(0, index)
                item.setData(1, obj.layer)
                # A hole without copper carries the original's mark: a crossed circle.
                mark = scene.addPath(bare_hole_mark(obj), QPen(QColor("#ffffff"), 0))
                groups[0].addToGroup(mark)
    for layer in COPPER:
        if not core.has_plane(board, layer) or (layer in (5, 6) and not board.multilayer):
            continue
        item = scene.addPath(plane_path(board, layer), no_pen, plane_colour(layer))
        groups[PLANE + layer].addToGroup(item)
    for z, group in enumerate(groups.values()):
        group.setZValue(z)
    wire_pen = QPen(QColor(WIRE_COLOR), 2)
    wire_pen.setCosmetic(True)
    for a, b in core.air_wires(board):
        (ax, ay), (bx, by) = core.centre_of(board.elements[a]), core.centre_of(board.elements[b])
        line = scene.addLine(QLineF(point(ax, ay), point(bx, by)), wire_pen)
        groups[WIRES].addToGroup(line)
    if transparent:
        for layer, group in groups.items():
            if layer:
                group.setOpacity(TRANSPARENT_OPACITY)
    if soldermask:
        overlay = scene.addPath(soldermask_overlay(board, soldermask), no_pen, MASK_COLOR)
        overlay.setZValue(len(groups) + 1)
    return groups, warnings
