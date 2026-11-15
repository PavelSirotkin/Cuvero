"""The board canvas: zoom, rulers, grid, selection, dragging, drawing, drops."""

from dataclasses import replace
from math import ceil, floor, hypot

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import (
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
)

import core

from .render import geometry, point
from .style import (
    BACKGROUND,
    CREATE_MODES,
    DRAFT_MODES,
    EDIT_MODES,
    GRID_COLOR,
    MACRO_MIME,
    TEST_COLOR,
    WIRE_COLOR,
)
from .units import Units


class BoardView(QGraphicsView):
    selected = Signal(object)
    moved = Signal(object)
    created = Signal(str, object)
    macro_dropped = Signal(str, str, object, int)  # side, path, position, quarter turns
    units_clicked = Signal()
    context_requested = Signal(object, object)  # board point, track node index or None
    mask_clicked = Signal(int)
    picked = Signal(str, object)  # tool mode, object index or None
    route_clicked = Signal(QPointF)  # scene point of a click in the autorouter tool
    route_pads = Signal(int, int)  # pads joined by dragging in the autorouter tool
    placed = Signal(object)  # objects carried on the cursor, put down by a click
    view_changed = Signal()  # zoom or scroll
    activated = Signal(int)  # double click on an object
    bend_changed = Signal(str)

    def __init__(self, coordinate_label, hint_label):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.coordinate_label = coordinate_label
        self.hint_label = hint_label
        self.show_grid = True
        self.setAcceptDrops(True)
        self.setBackgroundBrush(BACKGROUND)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMouseTracking(True)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.bounds = QRectF()
        self.measuring = False
        self.measure_start: QPointF | None = None
        self.measure_line: QGraphicsLineItem | None = None
        self.measure_distance: float | None = None
        self.board: core.Board | None = None
        self.mode = "edit"
        self.active_layer = 1
        self.selection: int | None = None
        self.drag_origin: QPointF | None = None
        self.drag_node: int | None = None
        self.overlay: QGraphicsPathItem | None = None
        self.preview_element: core.Element | None = None
        self.grid = 0.1
        self.draft: list[core.Point] | None = None
        self.members: list[int] = []
        self.track_width = 0.4
        self.units = Units()
        self.origin: core.Point = (0.0, 0.0)
        self.band_origin: QPointF | None = None
        self.band_item: QGraphicsRectItem | None = None
        self.draft_kind = "track"
        self.bend_mode = core.BEND_45
        self.snap_nodes = False
        self.rubber = False
        self.rect_filled = False
        self.history: list[tuple[QTransform, QPointF]] = []
        self.marks: list = []
        self.rings: list = []
        # A dashed line from a pad to the cursor while a connection is being drawn.
        self.wire_from: QPointF | None = None
        self.wire_line: QGraphicsLineItem | None = None
        self.pick_press: int | None = None  # pad pressed in the connections tool
        self.route_start: int | None = None  # pad pressed in the autorouter tool
        self.route_press: QPointF | None = None
        # Objects carried on the cursor (Text-IO import) until a click puts them down.
        self.placing: list[core.Element] | None = None
        self.placing_centre: core.Point = (0.0, 0.0)

    @property
    def elements(self) -> list[core.Element]:
        """Objects of the shown board, or an empty list before a board is shown."""
        return self.board.elements if self.board is not None else []

    def fit_board(self):
        if not self.bounds.isEmpty():
            self.fitInView(self.bounds, Qt.AspectRatioMode.KeepAspectRatio)
            self.view_changed.emit()

    def remember_view(self) -> None:
        centre = self.mapToScene(self.viewport().rect().center())
        self.history.append((self.transform(), centre))
        del self.history[:-20]

    def zoom_to(self, rect: QRectF) -> None:
        """Show a scene rectangle, remembering the current view for "previous zoom"."""
        if rect.isEmpty():
            rect = rect.adjusted(-1, -1, 1, 1)
        self.remember_view()
        margin = max(rect.width(), rect.height()) * 0.05
        self.fitInView(
            rect.adjusted(-margin, -margin, margin, margin), Qt.AspectRatioMode.KeepAspectRatio
        )
        self.view_changed.emit()

    def zoom_previous(self) -> bool:
        if not self.history:
            return False
        transform, centre = self.history.pop()
        self.setTransform(transform)
        self.centerOn(centre)
        self.view_changed.emit()
        return True

    def objects_rect(self, indices=None) -> QRectF:
        """Scene rectangle around objects (all visible ones, or the given indices)."""
        rect = QRectF()
        for item in self.scene().items():
            index = item.data(0)
            if index is None or not item.isVisible():
                continue
            if indices is None or index in indices:
                rect = rect.united(item.sceneBoundingRect())
        return rect

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        # Qt shifts the drawn picture and repaints only the uncovered strip; the rulers,
        # drawn over the board, would move with it and leave traces.
        self.viewport().update()
        self.view_changed.emit()

    def wheelEvent(self, event):
        factor = 1.25 ** (event.angleDelta().y() / 120)
        if 0.1 <= abs(self.transform().m11()) * factor <= 2500:
            self.scale(factor, factor)
            self.view_changed.emit()
        event.accept()

    def set_measure(self, enabled):
        self.measuring = enabled
        self.measure_start = None
        self.measure_distance = None
        if self.measure_line is not None:
            self.scene().removeItem(self.measure_line)
            self.measure_line = None
        self.coordinate_label.clear()

    def highlight(self, indices) -> None:
        """Mark objects in the test mode's colour; an empty list removes the marks."""
        for item in self.marks:
            self.scene().removeItem(item)
        self.marks = []
        if not indices or self.board is None:
            return
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        for index in indices:
            path.addPath(geometry(self.elements[index], set()))
        item = self.scene().addPath(path, QPen(Qt.PenStyle.NoPen), QColor(TEST_COLOR))
        item.setZValue(30)
        self.marks.append(item)

    def mark_points(self, points) -> None:
        """Red rings at DRC violations; an empty list removes them."""
        for item in self.rings:
            self.scene().removeItem(item)
        self.rings = []
        pen = QPen(QColor("#ff0000"), 2)
        pen.setCosmetic(True)
        for position in points:
            ring = self.scene().addEllipse(
                QRectF(position.x() - 0.6, position.y() - 0.6, 1.2, 1.2), pen
            )
            ring.setZValue(31)
            self.rings.append(ring)

    def forget_scene_items(self) -> None:
        """The scene was cleared: drop references to marks and lines that were in it."""
        self.marks, self.rings, self.wire_line = [], [], None
        if self.wire_from is not None:
            self.set_wire_from(self.wire_from)

    def set_wire_from(self, start: QPointF | None) -> None:
        """Start (a scene point) or end (None) the dashed connection line to the cursor."""
        self.wire_from = start
        if start is None:
            if self.wire_line is not None:
                self.scene().removeItem(self.wire_line)
                self.wire_line = None
            return
        if self.wire_line is None:
            pen = QPen(QColor(WIRE_COLOR), 0, Qt.PenStyle.DashLine)
            self.wire_line = self.scene().addLine(QLineF(start, start), pen)
            self.wire_line.setZValue(31)
        cursor = self.mapToScene(self.viewport().mapFromGlobal(QCursor.pos()))
        self.wire_line.setLine(QLineF(start, cursor))

    def start_placing(self, objects: list[core.Element]) -> None:
        """Carry the objects on the cursor; a left click puts them down, Esc cancels."""
        self.select(None)
        self.placing = list(objects)
        self.placing_centre = core.centre(objects)
        cursor = self.viewport().mapFromGlobal(QCursor.pos())
        if not self.viewport().rect().contains(cursor):
            cursor = self.viewport().rect().center()
        self.show_placing(self.mapToScene(cursor), Qt.KeyboardModifier.NoModifier)

    def placing_moved(self, end: QPointF, modifiers) -> list[core.Element]:
        assert self.placing is not None
        cx, cy = self.placing_centre
        dx, dy = end.x() - cx, -end.y() - cy
        if self.grid and not modifiers & Qt.KeyboardModifier.ControlModifier:
            dx, dy = (round(value / self.grid) * self.grid for value in (dx, dy))
        return [core.moved(obj, dx, dy) for obj in self.placing]

    def show_placing(self, end: QPointF, modifiers) -> None:
        moved = self.placing_moved(end, modifiers)
        visible = [obj for obj in moved if not core.is_hidden_label(obj)] or moved
        self.preview(visible[0], visible[1:])
        self.viewport().update()

    def cancel_placing(self) -> None:
        if self.placing is not None:
            self.placing = None
            self.select(None)

    def set_mode(self, mode):
        self.cancel_placing()
        self.set_wire_from(None)
        self.pick_press = self.route_start = None
        self.highlight([])
        self.set_measure(mode == "measure")
        self.mode = mode
        self.setDragMode(self.DragMode.ScrollHandDrag if mode == "zoom" else self.DragMode.NoDrag)
        self.select(None)

    def select(self, index: int | None, add: bool = False) -> None:
        """Select the unit at index; with add, toggle it within the current selection."""
        if index is None:
            self.set_selection([])
            return
        unit = core.unit_of(self.elements, index)
        if not add or not self.members:
            self.set_selection(unit, index)
        elif index in self.members:
            rest = [i for i in self.members if i not in unit]
            self.set_selection(rest, rest[0] if rest else None)
        else:
            self.set_selection([*self.members, *unit], self.selection)

    def set_selection(self, indices, primary: int | None = None) -> None:
        """Select objects together with their whole units; primary is the clicked one."""
        self.draft = None
        self.drag_origin = None
        self.preview_element = None
        members = core.unit_closure(self.elements, indices) if indices else []
        if primary not in members:
            primary = members[0] if members else None
        self.selection, self.members = primary, members
        if self.overlay is not None:
            self.scene().removeItem(self.overlay)
            self.overlay = None
        if primary is not None:
            self.preview(
                self.elements[primary],
                [self.elements[i] for i in members if i != primary],
            )
        self.selected.emit(primary)
        self.viewport().update()

    def item_at(self, pos, kinds=None) -> int | None:
        """Index of the object under a viewport position, preferring the active layer."""
        items = [
            item
            for item in self.items(pos)
            if item.data(0) is not None
            and (kinds is None or self.elements[item.data(0)].kind in kinds)
        ]
        items.sort(key=lambda item: item.data(1) != self.active_layer)
        return items[0].data(0) if items else None

    def node_at(self, pos) -> int | None:
        """Node of the single selected track under a viewport position."""
        if self.selection is None or len(self.members) != 1:
            return None
        obj = self.elements[self.selection]
        for index, xy in enumerate(track_nodes(obj)):
            if (self.mapFromScene(point(*xy)) - pos).manhattanLength() <= 10:
                return index
        return None

    def preview(self, obj, others=()):
        self.preview_element = obj
        path = geometry(obj, set())
        for other in others:
            if not core.is_hidden_label(other):
                path.addPath(geometry(other, set()))
        if self.overlay is None:
            self.overlay = self.scene().addPath(path, QPen(QColor("#ffffff"), 0))
            self.overlay.setZValue(21)
        else:
            self.overlay.setPath(path)

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        if self.board is None or self.grid <= 0 or not self.show_grid:
            return
        step = self.grid
        while step * abs(self.transform().m11()) < 8:
            step *= 2
        rect = rect.intersected(QRectF(0, 0, self.board.width, self.board.height))
        painter.setPen(QPen(GRID_COLOR, 0))
        for i in range(ceil(rect.left() / step), floor(rect.right() / step) + 1):
            painter.drawLine(QLineF(i * step, rect.top(), i * step, rect.bottom()))
        for i in range(ceil(rect.top() / step), floor(rect.bottom() / step) + 1):
            painter.drawLine(QLineF(rect.left(), i * step, rect.right(), i * step))

    def drawForeground(self, painter, rect):
        painter.save()
        painter.resetTransform()
        painter.setPen(QPen(QColor("#202020")))
        width, height = self.viewport().width(), self.viewport().height()
        ruler = QColor("#efefef")
        painter.fillRect(0, 0, width, 19, ruler)
        painter.fillRect(0, 0, 21, height, ruler)
        painter.drawText(2, 13, self.units.suffix)
        if self.board is not None:
            units, (ox, oy) = self.units, self.origin
            top_left = self.mapToScene(0, 0)
            bottom_right = self.mapToScene(width, height)
            # Ruler steps are round numbers in display units, counted from the origin.
            step = 1.0
            scale = abs(self.transform().m11()) * units.from_display(1.0)
            while step * scale < 48:
                step *= 2
            while step * scale > 125:
                step /= 2
            left = units.to_display(top_left.x() - ox)
            right = units.to_display(bottom_right.x() - ox)
            for i in range(ceil(left / step), floor(right / step) + 1):
                x = self.mapFromScene(units.from_display(i * step) + ox, 0).x()
                if x > 23:
                    painter.drawLine(x, 15, x, 19)
                    painter.drawText(x + 2, 12, f"{i * step:g}")
            top = units.to_display(-top_left.y() - oy)
            bottom = units.to_display(-bottom_right.y() - oy)
            for i in range(ceil(bottom / step), floor(top / step) + 1):
                y = self.mapFromScene(0, -(units.from_display(i * step) + oy)).y()
                if y > 28:
                    painter.drawLine(17, y, 21, y)
                    painter.save()
                    painter.translate(12, y - 2)
                    painter.rotate(-90)
                    painter.drawText(0, 0, f"{i * step:g}")
                    painter.restore()
            if self.selection is not None and len(self.members) == 1:
                obj = self.preview_element
                for x, y in track_nodes(obj):
                    marker = self.mapFromScene(point(x, y))
                    painter.fillRect(marker.x() - 3, marker.y() - 3, 7, 7, Qt.GlobalColor.white)
        painter.restore()

    def edit_press(self, event, end):
        pos = event.position().toPoint()
        if pos.x() < 21 and pos.y() < 19:
            self.units_clicked.emit()
            return
        if pos.x() < 21 or pos.y() < 19:
            return
        if self.mode == "mask":
            hit = self.item_at(pos)
            if hit is not None:
                self.mask_clicked.emit(hit)
            return
        if self.mode == "autoroute":
            # From a pad: drag to another pad; elsewhere: a click on an air wire.
            self.route_press = self.mapToScene(pos)
            self.route_start = self.item_at(pos, (core.THT, core.SMD))
            if self.route_start is not None:
                self.set_wire_from(point(*core.centre_of(self.elements[self.route_start])))
            else:
                self.route_clicked.emit(self.route_press)
            return
        if self.mode in ("connect", "test"):
            hit = self.item_at(pos, EDIT_MODES[self.mode])
            self.pick_press = hit if self.mode == "connect" else None
            self.picked.emit(self.mode, hit)
            return
        node = self.node_at(pos)
        if node is not None:
            self.drag_origin, self.drag_node = end, node
            return
        hit = self.item_at(pos, EDIT_MODES[self.mode])
        toggle = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if hit is not None:
            if toggle:
                self.select(hit, add=True)
                return
            if hit in self.members:
                self.selection = hit
            else:
                self.select(hit)
            self.drag_origin, self.drag_node = end, None
            return
        if self.mode == "edit":
            if not toggle:
                self.select(None)
            self.band_origin = end
            return
        self.select(None)
        if self.mode in DRAFT_MODES:
            start = self.snap(end, event.modifiers())
            self.draft_kind = self.mode
            self.draft = [start, start]
            self.show_draft()
        elif self.mode in CREATE_MODES:
            self.created.emit(self.mode, [self.snap(end, event.modifiers())])

    def snap(self, end, modifiers):
        x, y = end.x(), -end.y()
        if self.snap_nodes and self.board is not None:
            reach = 10 / max(abs(self.transform().m11()), 1e-9)
            found = core.nearest(core.snap_points(self.board), x, y, reach)
            if found is not None:
                return found
        if self.grid and not modifiers & Qt.KeyboardModifier.ControlModifier:
            x, y = (round(value / self.grid) * self.grid for value in (x, y))
        return round(x, 6), round(y, 6)

    def draft_points(self) -> list[core.Point]:
        """Fixed points of the draft plus the bend towards the cursor."""
        assert self.draft is not None
        if len(self.draft) < 2:
            return list(self.draft)
        return self.draft[:-1] + core.bend(self.draft[-2], self.draft[-1], self.bend_mode)

    def draft_element(self) -> core.Element:
        assert self.draft is not None
        kind, width = self.draft_kind, self.track_width
        if kind == "circle":
            (cx, cy), (x, y) = self.draft[0], self.draft[-1]
            radius = hypot(x - cx, y - cy)
            return core.Element(
                core.CIRCLE, x=cx, y=cy, outer=radius + width / 2, inner=max(radius - width / 2, 0)
            )
        if kind == "rect":
            ring = core.rectangle_points(self.draft[0], self.draft[-1])
            if self.rect_filled:
                return core.Element(core.POLYGON, width=width, points=[*ring, ring[0]])
            return core.Element(core.LINE, width=width, points=[*ring, ring[0]])
        points = self.draft_points()
        if kind == "zone" and len(points) >= 3:
            return core.Element(core.POLYGON, width=width, points=[*points, points[0]])
        return core.Element(core.LINE, width=width, points=points)

    def show_draft(self):
        if self.draft is None:
            return
        self.preview(self.draft_element())
        self.viewport().update()

    def finish_draft(self):
        if self.draft is None:
            return
        kind = self.draft_kind
        points: list[core.Point] = []
        for xy in self.draft[:-1]:
            if not points or points[-1] != xy:
                points.append(xy)
        self.select(None)
        if kind == "track" and len(points) >= 2:
            self.created.emit("track", points)
        elif kind == "zone":
            if len(points) > 2 and points[0] == points[-1]:
                points.pop()
            if len(points) >= 3:
                self.created.emit("zone", points)

    def keyPressEvent(self, event):
        if (
            event.key() == Qt.Key.Key_Space
            and self.draft is not None
            and self.draft_kind in ("track", "zone")
        ):
            modes = core.BEND_MODES
            self.bend_mode = modes[(modes.index(self.bend_mode) + 1) % len(modes)]
            self.bend_changed.emit(self.bend_mode)
            self.show_draft()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.placing is not None:
            self.cancel_placing()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.draft is not None:
            self.select(None)
            event.accept()
            return
        super().keyPressEvent(event)

    def drag_result(self, end: QPointF, modifiers) -> dict[int, core.Element]:
        """Moved copies of the dragged objects, by index; empty when nothing is dragged."""
        if self.drag_origin is None or self.selection is None:
            return {}
        delta = end - self.drag_origin
        dx, dy = delta.x(), -delta.y()
        if self.grid and not modifiers & Qt.KeyboardModifier.ControlModifier:
            dx, dy = (round(value / self.grid) * self.grid for value in (dx, dy))
        if self.drag_node is not None:
            obj = self.elements[self.selection]
            return {self.selection: move_geometry(obj, dx, dy, self.drag_node)}
        moved = {i: core.transformed(self.elements[i], dx, dy) for i in self.members}
        if self.rubber and self.board is not None:
            moved.update(core.rubber_band(self.board, moved))
        return moved

    def mousePressEvent(self, event):
        if self.placing is not None:
            if event.button() == Qt.MouseButton.LeftButton:
                end = self.mapToScene(event.position().toPoint())
                objects = self.placing_moved(end, event.modifiers())
                self.placing = None
                self.select(None)
                self.placed.emit(objects)
            else:
                self.cancel_placing()
            event.accept()
            return
        if self.draft is not None:
            cursor = self.snap(self.mapToScene(event.position().toPoint()), event.modifiers())
            if event.button() == Qt.MouseButton.LeftButton:
                if self.draft_kind in ("circle", "rect"):
                    first = self.draft[0]
                    kind = self.draft_kind
                    self.select(None)
                    if cursor != first:
                        self.created.emit(kind, [first, cursor])
                else:
                    self.draft[-1] = cursor
                    self.draft = self.draft_points()
                    self.draft.append(self.draft[-1])
                    self.show_draft()
            elif event.button() == Qt.MouseButton.RightButton:
                if self.draft_kind in ("circle", "rect"):
                    self.select(None)
                else:
                    self.finish_draft()
            event.accept()
            return
        if (
            not self.measuring
            and self.mode in EDIT_MODES
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.edit_press(event, self.mapToScene(event.position().toPoint()))
            event.accept()
            return
        if not self.measuring or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        end = self.mapToScene(event.position().toPoint())
        if self.measure_start is None:
            self.set_measure(True)
            self.measure_start = end
        else:
            self.measure_distance = self.update_measure(end).line().length()
            self.measure_start = None
        self.update_coordinates(end)
        event.accept()

    def mouseMoveEvent(self, event):
        end = self.mapToScene(event.position().toPoint())
        if self.measure_start is not None:
            self.update_measure(end)
        self.update_coordinates(end)
        if self.wire_from is not None and self.wire_line is not None:
            self.wire_line.setLine(QLineF(self.wire_from, end))
        if self.placing is not None:
            self.show_placing(end, event.modifiers())
            event.accept()
            return
        if self.draft is not None:
            self.draft[-1] = self.snap(end, event.modifiers())
            self.show_draft()
            event.accept()
            return
        if self.band_origin is not None:
            rect = QRectF(self.band_origin, end).normalized()
            if self.band_item is None:
                pen = QPen(QColor("#ffffff"), 0, Qt.PenStyle.DashLine)
                self.band_item = self.scene().addRect(rect, pen)
                self.band_item.setZValue(22)
            else:
                self.band_item.setRect(rect)
            event.accept()
            return
        if self.drag_origin is not None:
            moved = self.drag_result(end, event.modifiers())
            if self.selection in moved:
                others = [obj for i, obj in moved.items() if i != self.selection]
                self.preview(moved[self.selection], others)
            self.viewport().update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and (
            self.pick_press is not None or self.route_start is not None
        ):
            pos = event.position().toPoint()
            target = self.item_at(pos, (core.THT, core.SMD))
            if self.pick_press is not None:
                # Dragged from one pad to another in the connections tool.
                if target is not None and target != self.pick_press:
                    self.picked.emit("connect", target)
                self.pick_press = None
            else:
                start, self.route_start = self.route_start, None
                self.set_wire_from(None)
                if target is not None and target != start:
                    self.route_pads.emit(start, target)
                elif self.route_press is not None:
                    self.route_clicked.emit(self.route_press)
            event.accept()
            return
        if self.band_origin is not None and event.button() == Qt.MouseButton.LeftButton:
            rect = QRectF(self.band_origin, self.mapToScene(event.position().toPoint()))
            self.band_origin = None
            if self.band_item is not None:
                self.scene().removeItem(self.band_item)
                self.band_item = None
            inside = {
                item.data(0)
                for item in self.scene().items(
                    rect.normalized(), Qt.ItemSelectionMode.ContainsItemShape
                )
                if item.data(0) is not None and item.isVisible()
            }
            if inside:
                self.set_selection(sorted(set(self.members) | inside), self.selection)
            event.accept()
            return
        if self.drag_origin is not None and event.button() == Qt.MouseButton.LeftButton:
            edited = self.drag_result(
                self.mapToScene(event.position().toPoint()), event.modifiers()
            )
            self.drag_origin = None
            if edited:
                self.moved.emit(edited)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        if self.draft is not None or self.mode not in EDIT_MODES or self.board is None:
            return
        pos = event.pos()
        node = self.node_at(pos)
        if node is None:
            hit = self.item_at(pos)
            if hit is not None and hit not in self.members:
                self.select(hit)
        end = self.mapToScene(pos)
        self.context_requested.emit((end.x(), -end.y()), node)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if self.draft is not None and event.button() == Qt.MouseButton.LeftButton:
            self.finish_draft()
            event.accept()
            return
        if self.mode in ("edit", "text") and event.button() == Qt.MouseButton.LeftButton:
            hit = self.item_at(event.position().toPoint(), EDIT_MODES[self.mode])
            if hit is not None:
                self.drag_origin = None
                self.activated.emit(hit)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def update_coordinates(self, end):
        units, (ox, oy) = self.units, self.origin
        self.coordinate_label.setText(
            f"X: {units.with_suffix(end.x() - ox)}\nY: {units.with_suffix(-end.y() - oy)}"
        )
        distance = self.measure_distance
        if self.measure_start is not None:
            start = self.measure_start
            distance = hypot(end.x() - start.x(), end.y() - start.y())
            dx, dy = end.x() - start.x(), start.y() - end.y()
            self.hint_label.setText(
                f"dX: {units.with_suffix(dx)}   dY: {units.with_suffix(dy)}   "
                f"Расстояние: {units.with_suffix(distance)}"
            )
        elif distance is not None and self.measuring:
            self.hint_label.setText(f"Расстояние: {units.with_suffix(distance)}")

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MACRO_MIME) and self.board is not None:
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MACRO_MIME):
            event.acceptProposedAction()
            self.update_coordinates(self.mapToScene(event.position().toPoint()))
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(MACRO_MIME):
            super().dropEvent(event)
            return
        side, turns, path = bytes(event.mimeData().data(MACRO_MIME)).decode("utf-8").split("\n", 2)
        position = self.snap(self.mapToScene(event.position().toPoint()), event.modifiers())
        event.acceptProposedAction()
        self.macro_dropped.emit(side, path, position, int(turns))

    def update_measure(self, end: QPointF) -> QGraphicsLineItem:
        start = self.measure_start if self.measure_start is not None else end
        line = QLineF(start, end)
        if self.measure_line is None:
            self.measure_line = self.scene().addLine(line, QPen(QColor("#ffffff"), 0))
            self.measure_line.setZValue(20)
        else:
            self.measure_line.setLine(line)
        return self.measure_line


def track_nodes(obj):
    if obj.kind == core.SEGMENT:
        return [(obj.x, obj.y), (obj.outer, obj.inner)]
    return obj.points if obj.kind == core.LINE else []


def move_geometry(obj, dx, dy, node=None):
    if obj.kind == core.SEGMENT:
        return replace(
            obj,
            x=obj.x + (dx if node != 1 else 0),
            y=obj.y + (dy if node != 1 else 0),
            outer=obj.outer + (dx if node != 0 else 0),
            inner=obj.inner + (dy if node != 0 else 0),
        )
    points = [
        (x + dx, y + dy) if node is None or i == node else (x, y)
        for i, (x, y) in enumerate(obj.points)
    ]
    if obj.kind == core.THT or (obj.kind == core.SMD and not points):
        return replace(obj, x=obj.x + dx, y=obj.y + dy, points=points)
    return replace(obj, points=points)
