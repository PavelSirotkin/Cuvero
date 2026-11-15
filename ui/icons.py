"""Tool icons drawn in code, so the program ships no foreign artwork."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF


def round_pen(color, width):
    result = QPen(color, width)
    result.setCapStyle(Qt.PenCapStyle.RoundCap)
    return result


def tool_icon(name, size=20):
    """Simple line-art icons drawn in code so the program ships no foreign artwork."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    ink = QColor("#202020")
    p.setPen(QPen(ink, 1.6))
    s = size
    if name == "edit":
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon(
            QPolygonF(
                [
                    QPointF(5, 2),
                    QPointF(5, 16),
                    QPointF(8.5, 12.5),
                    QPointF(11, 18),
                    QPointF(13, 17),
                    QPointF(10.5, 11.5),
                    QPointF(15, 11.5),
                ]
            )
        )
    elif name == "zoom":
        p.drawEllipse(QRectF(3, 3, 10, 10))
        p.setPen(QPen(ink, 3))
        p.drawLine(QPointF(12, 12), QPointF(17, 17))
    elif name == "track":
        p.setPen(round_pen(ink, 3))
        p.drawLine(QPointF(3, 16), QPointF(9, 10))
        p.drawLine(QPointF(9, 10), QPointF(17, 10))
    elif name == "pad":
        p.setBrush(ink)
        p.drawEllipse(QRectF(3, 3, 14, 14))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(7.5, 7.5, 5, 5))
    elif name == "smd":
        p.setBrush(ink)
        p.drawRect(QRectF(7, 2, 6, 16))
    elif name == "circle":
        p.drawEllipse(QRectF(3, 3, 14, 14))
    elif name == "rect":
        p.drawRect(QRectF(3, 5, 14, 10))
    elif name == "zone":
        p.setBrush(ink)
        p.drawPolygon(QPolygonF([QPointF(3, 16), QPointF(6, 4), QPointF(17, 7), QPointF(14, 16)]))
    elif name == "special":
        p.drawEllipse(QRectF(2, 2, 8, 8))
        p.drawRect(QRectF(10, 10, 8, 8))
    elif name == "text":
        font = QFont()
        font.setPixelSize(12)
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, "ab")
    elif name == "mask":
        p.setPen(QPen(QColor("#d00000"), 1.6))
        p.setBrush(QColor("#ff3030"))
        p.drawEllipse(QRectF(5, 5, 10, 10))
    elif name == "connect":
        p.setBrush(ink)
        p.drawEllipse(QRectF(2, 3, 4, 4))
        p.drawEllipse(QRectF(14, 13, 4, 4))
        p.setPen(QPen(ink, 1, Qt.PenStyle.DotLine))
        p.drawLine(QPointF(5, 6), QPointF(15, 14))
    elif name == "autoroute":
        font = QFont()
        font.setPixelSize(15)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor("#3060c0"))
        p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, "A")
    elif name == "test":
        p.setPen(round_pen(ink, 2.5))
        p.drawLine(QPointF(4, 4), QPointF(14, 14))
        p.setPen(QPen(ink, 1.2))
        p.drawLine(QPointF(14, 14), QPointF(17, 17))
    elif name == "measure":
        p.drawLine(QPointF(2, 13), QPointF(18, 13))
        for x in range(3, 18, 3):
            p.drawLine(QPointF(x, 13), QPointF(x, 10 if x % 6 == 0 else 11.5))
    elif name == "photo":
        p.setBrush(QColor("#808080"))
        p.drawRoundedRect(QRectF(2, 6, 16, 11), 2, 2)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(7, 8, 7, 7))
    elif name == "grid":
        p.setPen(QPen(ink, 1))
        for i in range(2, s, 4):
            p.drawLine(QPointF(i, 2), QPointF(i, s - 2))
            p.drawLine(QPointF(2, i), QPointF(s - 2, i))
    elif name == "width":
        p.setBrush(ink)
        p.drawRect(QRectF(2, 8, 16, 4))
        p.drawLine(QPointF(10, 2), QPointF(10, 7))
        p.drawLine(QPointF(10, 13), QPointF(10, 18))
    elif name == "padsize":
        p.setBrush(ink)
        p.drawEllipse(QRectF(4, 2, 12, 12))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(8, 6, 4, 4))
        p.drawLine(QPointF(3, 17), QPointF(17, 17))
    elif name == "smdsize":
        p.setBrush(ink)
        p.drawRect(QRectF(5, 4, 8, 14))
        p.drawLine(QPointF(16, 3), QPointF(16, 18))
    elif name == "fit":
        p.drawRect(QRectF(3, 3, 14, 14))
        p.drawEllipse(QRectF(7, 7, 6, 6))
    elif name == "rotate":
        p.drawArc(QRectF(4, 4, 12, 12), 30 * 16, 300 * 16)
        p.setBrush(ink)
        p.drawPolygon(QPolygonF([QPointF(15, 2), QPointF(17, 8), QPointF(11, 7)]))
    elif name == "folder":
        p.setBrush(QColor("#e8c060"))
        p.drawPolygon(
            QPolygonF(
                [
                    QPointF(2, 5),
                    QPointF(8, 5),
                    QPointF(10, 7),
                    QPointF(18, 7),
                    QPointF(18, 16),
                    QPointF(2, 16),
                ]
            )
        )
    elif name == "swap":
        p.drawLine(QPointF(3, 7), QPointF(17, 7))
        p.drawLine(QPointF(3, 13), QPointF(17, 13))
        p.drawLine(QPointF(14, 4), QPointF(17, 7))
        p.drawLine(QPointF(6, 16), QPointF(3, 13))
    elif name == "cut":
        p.drawEllipse(QRectF(2, 12, 6, 6))
        p.drawEllipse(QRectF(12, 12, 6, 6))
        p.drawLine(QPointF(7, 13), QPointF(14, 2))
        p.drawLine(QPointF(13, 13), QPointF(6, 2))
    elif name in ("copy", "duplicate"):
        p.setBrush(QColor("#ffffff"))
        p.drawRect(QRectF(2, 2, 10, 12))
        p.drawRect(QRectF(7, 6, 10, 12))
        if name == "duplicate":
            p.drawLine(QPointF(12, 9), QPointF(12, 15))
            p.drawLine(QPointF(9, 12), QPointF(15, 12))
    elif name == "paste":
        p.setBrush(QColor("#e8c060"))
        p.drawRect(QRectF(3, 3, 14, 15))
        p.setBrush(QColor("#ffffff"))
        p.drawRect(QRectF(7, 1, 6, 4))
        p.drawRect(QRectF(6, 8, 8, 8))
    elif name in ("group", "ungroup"):
        p.setBrush(ink)
        p.drawRect(QRectF(4, 4, 5, 5))
        p.drawEllipse(QRectF(11, 11, 5, 5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(ink, 1, Qt.PenStyle.DashLine if name == "ungroup" else Qt.PenStyle.SolidLine))
        p.drawRect(QRectF(1.5, 1.5, 17, 17))
    elif name == "align":
        p.drawLine(QPointF(3, 2), QPointF(3, 18))
        p.setBrush(ink)
        p.drawRect(QRectF(5, 4, 12, 4))
        p.drawRect(QRectF(5, 12, 7, 4))
    elif name == "snap":
        p.setPen(QPen(ink, 1))
        for i in (4, 10, 16):
            p.drawLine(QPointF(i, 2), QPointF(i, 18))
            p.drawLine(QPointF(2, i), QPointF(18, i))
        p.setBrush(QColor("#d00000"))
        p.setPen(QPen(QColor("#d00000"), 1))
        p.drawEllipse(QPointF(10, 10), 3, 3)
    elif name == "macro_side":
        p.setBrush(QColor("#507ff5"))
        p.drawRect(QRectF(2, 3, 16, 6))
        p.setBrush(QColor("#33d253"))
        p.drawRect(QRectF(2, 11, 16, 6))
    elif name == "selector":
        p.setPen(QPen(QColor("#c03070"), 2))
        p.setBrush(QColor("#ffb0d0"))
        p.drawEllipse(QPointF(10, 10), 7, 7)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(10, 10), 3, 3)
    elif name in ("components", "drc", "macros", "properties"):
        colours = {
            "components": "#000000",
            "drc": "#006000",
            "macros": "#a00000",
            "properties": "#202080",
        }
        texts = {"components": "R1", "drc": "DRC", "macros": "M", "properties": "≡"}
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(colours[name]))
        p.drawRoundedRect(QRectF(1, 2, 18, 16), 2, 2)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(13 if name in ("macros", "properties") else 8)
        p.setFont(font)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(1, 2, 18, 16), Qt.AlignmentFlag.AlignCenter, texts[name])
    elif name == "transparent":
        p.setPen(Qt.PenStyle.NoPen)
        blue = QColor("#1e6af9")
        green = QColor("#00ba00")
        green.setAlpha(150)
        p.setBrush(blue)
        p.drawRect(QRectF(2, 2, 11, 11))
        p.setBrush(green)
        p.drawRect(QRectF(7, 7, 11, 11))
    elif name == "plane":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1a3a8a"))
        p.drawRect(QRectF(1, 1, 18, 18))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(8, 8), 4, 4)
        p.setBrush(QColor("#5080f0"))
        p.drawEllipse(QPointF(8, 8), 2.5, 2.5)
        p.setPen(QPen(QColor("#5080f0"), 2))
        p.drawLine(QPointF(8, 8), QPointF(17, 17))
    elif name == "node_snap":
        p.setPen(QPen(QColor("#c00000"), 2))
        p.drawEllipse(QPointF(10, 10), 6, 6)
        p.setPen(QPen(ink, 1.2))
        p.drawLine(QPointF(10, 1), QPointF(10, 19))
        p.drawLine(QPointF(1, 10), QPointF(19, 10))
    elif name == "rubber":
        p.setPen(QPen(QColor("#2050c0"), 2))
        p.drawLine(QPointF(3, 15), QPointF(10, 8))
        p.drawLine(QPointF(10, 8), QPointF(17, 12))
        p.setPen(QPen(QColor("#d00000"), 2))
        p.drawLine(QPointF(3, 3), QPointF(17, 17))
    elif name == "via":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#000000"))
        p.drawEllipse(QPointF(10, 10), 7, 7)
        p.setBrush(QColor("#e00000"))
        p.drawEllipse(QPointF(10, 10), 3.5, 3.5)
    elif name == "side":
        p.setPen(QPen(ink, 1.5))
        p.drawLine(QPointF(3, 16), QPointF(17, 16))
        p.drawLine(QPointF(10, 3), QPointF(10, 12))
        p.drawLine(QPointF(6, 8), QPointF(10, 12))
        p.drawLine(QPointF(14, 8), QPointF(10, 12))
    elif name in ("mirror_h", "mirror_v"):
        if name == "mirror_v":
            p.translate(s / 2, s / 2)
            p.rotate(90)
            p.translate(-s / 2, -s / 2)
        p.setPen(QPen(ink, 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(10, 1), QPointF(10, 19))
        p.setPen(QPen(ink, 1.2))
        p.setBrush(ink)
        p.drawPolygon(QPolygonF([QPointF(8, 4), QPointF(8, 16), QPointF(2, 16)]))
        p.setBrush(QColor("#ffffff"))
        p.drawPolygon(QPolygonF([QPointF(12, 4), QPointF(12, 16), QPointF(18, 16)]))
    p.end()
    return QIcon(pixmap)


def pad_shape_icon(shape: int, size: int = 24) -> QIcon:
    """Pictogram of a pad shape code 1..9: round, octagon, square, then wide and tall ones."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    ink = QColor("#000000")
    p.setPen(QPen(ink, 1))
    p.setBrush(ink)
    c = size / 2
    r = size * 0.27
    half_x = r * (2 if shape in (4, 5, 6) else 1)
    half_y = r * (2 if shape in (7, 8, 9) else 1)
    half_x, half_y = min(half_x, c - 1), min(half_y, c - 1)
    rect = QRectF(c - half_x, c - half_y, 2 * half_x, 2 * half_y)
    if shape == 1:
        p.drawEllipse(QPointF(c, c), r, r)
    elif shape in (4, 7):
        p.drawRoundedRect(rect, min(half_x, half_y), min(half_x, half_y))
    elif shape in (2, 5, 8):
        cut = min(half_x, half_y) * 0.6
        x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
        p.drawPolygon(
            QPolygonF(
                [
                    QPointF(x0 + cut, y0),
                    QPointF(x1 - cut, y0),
                    QPointF(x1, y0 + cut),
                    QPointF(x1, y1 - cut),
                    QPointF(x1 - cut, y1),
                    QPointF(x0 + cut, y1),
                    QPointF(x0, y1 - cut),
                    QPointF(x0, y0 + cut),
                ]
            )
        )
    else:
        p.drawRect(rect)
    p.setBrush(QColor("#ffffff"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(c, c), r * 0.4, r * 0.4)
    p.end()
    return QIcon(pixmap)
