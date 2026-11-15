"""Rasterising Gerber primitives with Qt, to compare our output with reference files."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPainterPathStroker, QPolygonF

from core import gerber_read
from ui.gerber_paths import aperture_path

WHITE, BLACK = QColor("white"), QColor("black")


def render(
    gerber: gerber_read.GerberFile,
    left: float,
    bottom: float,
    width: float,
    height: float,
    dpmm: float = 20,
) -> QImage:
    """Black image with dark parts white, for the area from (left, bottom), y upwards."""
    image = QImage(int(width * dpmm), int(height * dpmm), QImage.Format.Format_Grayscale8)
    image.fill(BLACK)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.translate(0, image.height())
    painter.scale(dpmm, -dpmm)
    painter.translate(-left, -bottom)
    painter.setPen(Qt.PenStyle.NoPen)
    for item in gerber.primitives:
        painter.setBrush(WHITE if item.dark else BLACK)
        if item.kind == "region":
            painter.drawPolygon(QPolygonF([QPointF(*xy) for xy in item.points]))
        elif item.kind == "flash" and item.aperture is not None:
            painter.drawPath(aperture_path(item.aperture, *item.points[0]))
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
            painter.drawPath(stroker.createStroke(line))
    painter.end()
    return image


def difference(a: QImage, b: QImage) -> float:
    """Share of pixels that differ between two images of the same size."""
    assert a.size() == b.size()
    da = bytes(a.constBits())
    db = bytes(b.constBits())
    differ = sum(1 for p, q in zip(da, db, strict=True) if (p > 127) != (q > 127))
    return differ / len(da)
