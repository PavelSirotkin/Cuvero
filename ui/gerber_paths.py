"""Qt painter paths of Gerber primitives: the exact copper of a layer, for milling."""

from math import cos, pi, radians, sin

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainterPath, QPainterPathStroker, QPolygonF, QTransform

from core import gerber_read


def aperture_path(aperture: gerber_read.Aperture, x: float, y: float) -> QPainterPath:
    """The aperture's shape flashed at (x, y), in Gerber coordinates (y upwards)."""
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    p = aperture.params
    if aperture.shape == "C":
        path.addEllipse(QPointF(x, y), p[0] / 2, p[0] / 2)
    elif aperture.shape == "R":
        path.addRect(QRectF(x - p[0] / 2, y - p[1] / 2, p[0], p[1]))
    elif aperture.shape == "O":
        r = min(p[0], p[1]) / 2
        path.addRoundedRect(QRectF(x - p[0] / 2, y - p[1] / 2, p[0], p[1]), r, r)
    elif aperture.shape == "P":
        n = int(p[1])
        rotation = radians(p[2]) if len(p) > 2 else 0.0
        r = p[0] / 2
        corners = [
            QPointF(x + r * cos(rotation + 2 * pi * k / n), y + r * sin(rotation + 2 * pi * k / n))
            for k in range(n)
        ]
        path.addPolygon(QPolygonF(corners))
        path.closeSubpath()
    else:
        for exposure, outline in aperture.macro:
            part = QPainterPath()
            part.addPolygon(QPolygonF([QPointF(x + px, y + py) for px, py in outline]))
            part.closeSubpath()
            path = path.united(part) if exposure else path.subtracted(part)
    return path


def primitive_path(item: gerber_read.Primitive) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    if item.kind == "region":
        path.addPolygon(QPolygonF([QPointF(*xy) for xy in item.points]))
        path.closeSubpath()
    elif item.kind == "flash" and item.aperture is not None:
        path = aperture_path(item.aperture, *item.points[0])
    elif item.kind == "draw" and item.aperture is not None:
        line = QPainterPath()
        line.moveTo(QPointF(*item.points[0]))
        for xy in item.points[1:]:
            line.lineTo(QPointF(*xy))
        stroker = QPainterPathStroker()
        size = item.aperture.params[0] if item.aperture.params else 0.0
        stroker.setWidth(max(size, 1e-4))
        square = item.aperture.shape == "R"
        stroker.setCapStyle(Qt.PenCapStyle.SquareCap if square else Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        path = stroker.createStroke(line)
    return path


FINE = 5.0  # boolean operations run at 0.2 mm units: Qt flattens arcs too coarsely in mm


def copper_path(gerber: gerber_read.GerberFile) -> QPainterPath:
    """Everything dark in the file, with cleared parts taken out (exact union)."""
    up = QTransform.fromScale(FINE, FINE)
    result = QPainterPath()
    result.setFillRule(Qt.FillRule.WindingFill)
    batch = QPainterPath()
    batch.setFillRule(Qt.FillRule.WindingFill)
    dark = True
    for item in gerber.primitives:
        if item.dark != dark:
            result = result.united(batch) if dark else result.subtracted(batch)
            batch = QPainterPath()
            batch.setFillRule(Qt.FillRule.WindingFill)
            dark = item.dark
        batch.addPath(up.map(primitive_path(item)))
    result = result.united(batch) if dark else result.subtracted(batch)
    return QTransform.fromScale(1 / FINE, 1 / FINE).map(result.simplified())
