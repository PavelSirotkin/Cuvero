"""The small overview of the whole board with the visible part, below the tool panel."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class Overview(QWidget):
    """Whole board in miniature; the green box is the visible part. Click or drag to move."""

    def __init__(self, view):
        super().__init__()
        self.view = view
        self.setFixedHeight(64)
        self.setToolTip("Обзор платы: щелчок или перетаскивание показывает это место")
        view.view_changed.connect(self.update)

    def frame(self) -> tuple[QRectF, float, QPointF]:
        """Board area, scale and offset of the miniature."""
        board = self.view.board
        area = QRectF(0, 0, board.width, board.height) if board else QRectF(0, 0, 1, 1)
        scale = min((self.width() - 6) / area.width(), (self.height() - 6) / area.height())
        offset = QPointF(
            (self.width() - area.width() * scale) / 2, (self.height() - area.height() * scale) / 2
        )
        return area, scale, offset

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        if self.view.board is None:
            return
        area, scale, offset = self.frame()
        painter.setPen(QPen(QColor("#808080"), 1))
        painter.setBrush(QColor("#000000"))
        painter.drawRect(QRectF(offset, area.size() * scale))
        visible = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        visible = visible.intersected(area)
        if not visible.isEmpty():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#00ff00"))
            painter.drawRect(QRectF(offset + visible.topLeft() * scale, visible.size() * scale))

    def move_to(self, position) -> None:
        _area, scale, offset = self.frame()
        self.view.centerOn((position - offset) / scale)

    def mousePressEvent(self, event):
        self.move_to(event.position())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move_to(event.position())
