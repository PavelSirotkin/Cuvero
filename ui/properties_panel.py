"""The properties panel: shows and changes the selected objects, or the board itself.

Its pages and look follow the original program: board, pad, SMD pad, track, polygon,
circle or arc, text and a summary for several objects. Every change is sent to the
window as an undoable edit; the panel never changes data itself.
"""

from collections import Counter
from dataclasses import replace
from math import cos, hypot, radians, sin

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QRadioButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import core

from .icons import pad_shape_icon, tool_icon
from .style import OPTIONS, PAD_SHAPES, VALUE_STYLE
from .units import Units
from .widgets import PanelTitle

PANEL_BACKGROUND = "#d0d3e1"
THERMAL_BACKGROUND = "#a9afcd"
SHAPE_NAMES = {item[1]: item[0] for item in PAD_SHAPES if item}


class UnitBox(QDoubleSpinBox):
    """A value field holding millimetres and showing the current display units."""

    def __init__(self, units: Units, minimum: float = 0.0, maximum: float = 2000.0):
        super().__init__()
        self.units = units
        self.minimum_mm, self.maximum_mm = minimum, maximum
        self.setKeyboardTracking(False)
        self.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.setStyleSheet(VALUE_STYLE)
        self.setFixedWidth(76)
        self.exact = 0.0  # the value last shown, in mm, without display rounding
        self.apply_units()

    def apply_units(self) -> None:
        self.blockSignals(True)
        self.setDecimals(self.units.decimals)
        self.setRange(
            self.units.to_display(self.minimum_mm), self.units.to_display(self.maximum_mm)
        )
        self.setValue(self.units.to_display(self.exact))
        self.blockSignals(False)

    def mm(self) -> float:
        """The value in mm; unchanged values keep their exact size despite display rounding.

        Without this, showing 1 mm as 39.4 mil and reading it back would quietly turn it
        into 1.00076 mm whenever another field of the same object is edited.
        """
        shown = self.units.to_display(self.exact)
        if abs(shown - self.value()) <= 0.5 * 10 ** -self.decimals():
            return self.exact
        return round(self.units.from_display(self.value()), 6)

    def set_mm(self, value: float) -> None:
        self.exact = value
        self.blockSignals(True)
        self.setValue(self.units.to_display(value))
        self.blockSignals(False)


class AngleBox(QDoubleSpinBox):
    def __init__(self):
        super().__init__()
        self.setKeyboardTracking(False)
        self.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.setStyleSheet(VALUE_STYLE)
        self.setDecimals(2)
        self.setRange(0.0, 359.99)
        self.setFixedWidth(76)

    def set_quietly(self, value: float) -> None:
        self.blockSignals(True)
        self.setValue(value % 360)
        self.blockSignals(False)


def quiet_check(box, value: bool) -> None:
    box.blockSignals(True)
    box.setChecked(value)
    box.blockSignals(False)


def caption(text: str, bold: bool = False) -> QLabel:
    label = QLabel(text)
    if bold:
        label.setStyleSheet("font-weight: bold;")
    return label


def note(text: str, color: str = "#404040") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {color};")
    return label


class SpokeSelector(QWidget):
    """The pad with its eight spoke positions, as in the original: click a square to switch.

    Squares sit where the spokes point on screen, so they follow the pad's rotation.
    """

    toggled = Signal(int)  # direction bit

    SIZE = 88
    RADIUS = 30
    SQUARE = 11

    def __init__(self):
        super().__init__()
        self.setFixedSize(self.SIZE, self.SIZE)
        self.pad: core.Element | None = None
        self.bits = 0
        self.setToolTip("Щёлкните по квадрату, чтобы добавить или убрать перемычку")

    def show_pad(self, pad: core.Element, bits: int) -> None:
        self.pad, self.bits = pad, bits
        self.update()

    def centre_of(self, bit: int) -> QPointF:
        assert self.pad is not None
        angle = radians(core.spoke_angle(self.pad, bit))
        c = self.SIZE / 2
        return QPointF(c + self.RADIUS * cos(angle), c - self.RADIUS * sin(angle))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.SIZE / 2
        if self.pad is not None:
            for bit in range(8):
                if self.bits >> bit & 1:
                    p.setPen(QPen(QColor("#000000"), 3))
                    p.drawLine(QPointF(c, c), self.centre_of(bit))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#000000"))
        p.drawEllipse(QPointF(c, c), 15, 15)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(c, c), 9, 9)
        p.setBrush(QColor("#000000"))
        p.drawEllipse(QPointF(c, c), 4, 4)
        if self.pad is None:
            return
        half = self.SQUARE / 2
        for bit in range(8):
            centre = self.centre_of(bit)
            p.setPen(QPen(QColor("#606060"), 1))
            p.setBrush(QColor("#000000") if self.bits >> bit & 1 else QColor("#ffffff"))
            p.drawRect(QRectF(centre.x() - half, centre.y() - half, self.SQUARE, self.SQUARE))

    def mousePressEvent(self, event):
        if self.pad is None or event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()

        def distance(bit: int) -> float:
            centre = self.centre_of(bit)
            return hypot(centre.x() - pos.x(), centre.y() - pos.y())

        bit = min(range(8), key=distance)
        if distance(bit) <= self.SQUARE:
            self.toggled.emit(bit)


class ThermalBox(QWidget):
    """Thermal relief of a pad: switch, spoke width slider, spoke directions, layers."""

    changed = Signal(bool, int, object)  # enabled, direction bits, layer index or None
    percent_changed = Signal(int)

    def __init__(self, units: Units, with_layers: bool):
        super().__init__()
        self.units = units
        self.pad: core.Element | None = None
        self.with_layers = with_layers
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.enabled = QCheckBox("Термобарьер")
        self.enabled.toggled.connect(self.emit_change)
        layout.addWidget(self.enabled)
        self.frame = QFrame()
        self.frame.setObjectName("thermal")
        self.frame.setStyleSheet(
            f"QFrame#thermal {{ background: {THERMAL_BACKGROUND}; border: 1px solid #7a80a0; }}"
        )
        inner = QVBoxLayout(self.frame)
        inner.setContentsMargins(6, 4, 6, 6)
        self.width_label = QLabel()
        inner.addWidget(self.width_label)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(*core.THERMAL_PERCENT_RANGE)
        self.slider.setToolTip("Ширина перемычек: 50…300 % от трети размера площадки")
        self.slider.valueChanged.connect(self.slider_moved)
        self.slider.sliderReleased.connect(lambda: self.percent_changed.emit(self.slider.value()))
        inner.addWidget(self.slider)
        title = caption("Перемычки:", bold=True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(title)
        self.spokes = SpokeSelector()
        self.spokes.toggled.connect(self.spoke_toggled)
        inner.addWidget(self.spokes, 0, Qt.AlignmentFlag.AlignHCenter)
        self.all_layers = QRadioButton("Все слои одинаково")
        self.single_layer = QRadioButton("Слои по отдельности")
        self.layer = QComboBox()
        self.layer.addItems(core.THERMAL_LAYERS)
        self.layer.setToolTip("Медный слой, перемычки которого показаны и меняются")
        group = QButtonGroup(self)
        group.addButton(self.all_layers)
        group.addButton(self.single_layer)
        self.all_layers.setChecked(True)
        self.all_layers.toggled.connect(self.layers_mode_changed)
        self.layer.currentIndexChanged.connect(self.refresh_spokes)
        for widget in (self.all_layers, self.single_layer, self.layer):
            inner.addWidget(widget)
            widget.setVisible(with_layers)
        layout.addWidget(self.frame)

    def layer_index(self) -> int | None:
        if self.with_layers and self.single_layer.isChecked():
            return self.layer.currentIndex()
        return None

    def show_pad(self, pad: core.Element) -> None:
        self.pad = pad
        widgets = (self.enabled, self.slider, self.all_layers, self.single_layer, self.layer)
        for widget in widgets:
            widget.blockSignals(True)
        on = core.has_thermal(pad)
        self.enabled.setChecked(on)
        self.frame.setVisible(on)
        self.slider.setValue(core.thermal_percent(pad))
        if not core.thermal_layers_equal(pad):
            self.single_layer.setChecked(True)
        self.layer.setVisible(self.with_layers and self.single_layer.isChecked())
        for widget in widgets:
            widget.blockSignals(False)
        self.update_width_label(core.thermal_percent(pad))
        self.refresh_spokes()

    def current_bits(self) -> int:
        if self.pad is None:
            return 0
        index = self.layer_index()
        if index is None:
            return core.thermal_directions(self.pad)
        return core.thermal_layer_directions(self.pad, index)

    def refresh_spokes(self) -> None:
        if self.pad is not None:
            self.spokes.show_pad(self.pad, self.current_bits())

    def update_width_label(self, percent: int) -> None:
        if self.pad is None:
            return
        width = core.thermal_width(replace(self.pad, rotation=percent))
        self.width_label.setText(f"Ширина: {self.units.with_suffix(width, 2)}")

    def slider_moved(self, percent: int) -> None:
        self.update_width_label(percent)
        if not self.slider.isSliderDown():
            self.percent_changed.emit(percent)

    def spoke_toggled(self, bit: int) -> None:
        bits = self.current_bits() ^ (1 << bit)
        self.changed.emit(True, bits, self.layer_index())

    def layers_mode_changed(self) -> None:
        self.layer.setVisible(self.with_layers and self.single_layer.isChecked())
        self.refresh_spokes()

    def emit_change(self) -> None:
        self.frame.setVisible(self.enabled.isChecked())
        self.changed.emit(self.enabled.isChecked(), self.current_bits(), None)


class AngleDiagram(QWidget):
    """The little circle explaining arc angles, as drawn in the original panel."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(110, 100)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre = QPointF(55, 50)
        p.setPen(QPen(QColor("#202060"), 1))
        p.drawEllipse(centre, 38, 38)
        p.drawLine(QPointF(15, 50), QPointF(95, 50))
        p.drawLine(QPointF(55, 10), QPointF(55, 90))
        p.drawArc(QRectF(43, 38, 24, 24), 0, 300 * 16)
        font = QFont()
        font.setPixelSize(10)
        p.setFont(font)
        p.drawText(QPointF(72, 46), "0°")
        p.drawText(QPointF(40, 22), "90°")
        p.drawText(QPointF(17, 46), "180°")
        p.drawText(QPointF(58, 86), "270°")


class PropertiesPanel(QWidget):
    edited = Signal(object, str)  # {index: new object}, undo description
    component_requested = Signal()
    board_edited = Signal(object, str)  # new board, undo description
    hidden = Signal()

    def __init__(self, units: Units):
        super().__init__()
        self.units = units
        self.board: core.Board | None = None
        self.index: int | None = None
        self.members: list[int] = []
        self.unit_boxes: list[UnitBox] = []
        self.unit_labels: list[QLabel] = []
        self.setObjectName("properties")
        self.setStyleSheet(
            f"QWidget#properties, QWidget#page, QScrollArea, QStackedWidget"
            f" {{ background: {PANEL_BACKGROUND}; }}"
        )
        self.setAutoFillBackground(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(PanelTitle("Свойства", self.close_panel, color="#ffffff"))
        self.heading = QLabel()
        self.heading.setStyleSheet(
            "font-weight: bold; padding: 8px 4px 4px 4px; border-bottom: 1px solid #a0a4b8;"
        )
        layout.addWidget(self.heading)
        self.pages = QStackedWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.pages)
        layout.addWidget(scroll, 1)
        self.build_board_page()
        self.build_pad_page()
        self.build_smd_page()
        self.build_track_page()
        self.build_polygon_page()
        self.build_circle_page()
        self.build_text_page()
        self.build_multi_page()

    # --- helpers ----------------------------------------------------------------

    def close_panel(self) -> None:
        self.hide()
        self.hidden.emit()

    def page(self) -> tuple[QWidget, QGridLayout]:
        widget = QWidget()
        widget.setObjectName("page")
        grid = QGridLayout(widget)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(3)
        grid.setColumnStretch(3, 1)
        grid.setRowStretch(99, 1)
        self.pages.addWidget(widget)
        return widget, grid

    def box(self, minimum: float = 0.0, maximum: float = 2000.0) -> UnitBox:
        box = UnitBox(self.units, minimum, maximum)
        self.unit_boxes.append(box)
        return box

    def unit_label(self) -> QLabel:
        label = QLabel(self.units.suffix)
        self.unit_labels.append(label)
        return label

    def value_row(self, grid: QGridLayout, row: int, text: str, box: QWidget, unit=True) -> None:
        """'X:  [value]  мм' as in the original: label, black field, unit after it."""
        if text:
            grid.addWidget(QLabel(text), row, 0)
        grid.addWidget(box, row, 1)
        if unit:
            grid.addWidget(self.unit_label(), row, 2)

    def origin(self) -> core.Point:
        return core.board_origin(self.board) if self.board else (0.0, 0.0)

    def element(self) -> core.Element:
        assert self.board is not None and self.index is not None
        return self.board.elements[self.index]

    def edit(self, obj: core.Element, description: str) -> None:
        if self.index is not None and obj != self.element():
            self.edited.emit({self.index: obj}, description)

    def apply_units(self) -> None:
        for box in self.unit_boxes:
            box.apply_units()
        for label in self.unit_labels:
            label.setText(self.units.suffix)
        self.refresh()

    def centre_rows(self, grid: QGridLayout, row: int, slot) -> tuple[UnitBox, UnitBox]:
        x, y = self.box(-2000.0), self.box(-2000.0)
        x.valueChanged.connect(slot)
        y.valueChanged.connect(slot)
        grid.addWidget(QLabel("Центр:"), row, 0, 1, 3)
        self.value_row(grid, row + 1, "X:", x)
        self.value_row(grid, row + 2, "Y:", y)
        return x, y

    def size_block(self, grid: QGridLayout, row: int, icon: str, first: UnitBox, second: UnitBox):
        """Two stacked size fields with the pictogram of what they measure, on the left."""
        picture = QLabel()
        picture.setPixmap(tool_icon(icon, 24).pixmap(24, 24))
        picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(picture, row, 0, 2, 1)
        grid.addWidget(first, row, 1)
        grid.addWidget(self.unit_label(), row, 2)
        grid.addWidget(second, row + 1, 1)
        grid.addWidget(self.unit_label(), row + 1, 2)

    # --- board ------------------------------------------------------------------

    def build_board_page(self) -> None:
        self.board_page, grid = self.page()
        self.board_width = self.box(1.0)
        self.board_height = self.box(1.0)
        self.board_width.valueChanged.connect(self.board_changed)
        self.board_height.valueChanged.connect(self.board_changed)
        grid.addWidget(QLabel("Ширина:"), 0, 0, 1, 3)
        self.value_row(grid, 1, "", self.board_width)
        grid.addWidget(QLabel("Высота:"), 2, 0, 1, 3)
        self.value_row(grid, 3, "", self.board_height)
        self.board_area = QLabel()
        self.board_area.setStyleSheet("color: #202080;")
        grid.addWidget(QLabel("Площадь:"), 4, 0)
        grid.addWidget(self.board_area, 4, 1, 1, 2)
        grid.addWidget(QLabel("Имя:"), 5, 0, 1, 3)
        self.board_name = QLineEdit()
        self.board_name.setMaxLength(30)
        self.board_name.editingFinished.connect(self.board_changed)
        grid.addWidget(self.board_name, 6, 0, 1, 4)
        self.board_multilayer = QCheckBox("Многослойная (I1, I2)")
        self.board_multilayer.toggled.connect(self.board_changed)
        grid.addWidget(self.board_multilayer, 7, 0, 1, 4)

    def board_changed(self) -> None:
        if self.board is None:
            return
        name = self.board_name.text().strip() or self.board.name
        new = core.board_settings(
            self.board,
            name,
            self.board_width.mm(),
            self.board_height.mm(),
            self.board_multilayer.isChecked(),
        )
        if (new.name, new.width, new.height, new.multilayer) != (
            self.board.name,
            self.board.width,
            self.board.height,
            self.board.multilayer,
        ):
            self.board_edited.emit(new, "Настройка платы")

    # --- pads -------------------------------------------------------------------

    def build_pad_page(self) -> None:
        self.pad_page, grid = self.page()
        self.pad_x, self.pad_y = self.centre_rows(grid, 0, self.pad_moved)
        grid.addWidget(QLabel("Форма:"), 3, 0, 1, 3)
        self.pad_shape = QToolButton()
        self.pad_shape.setIconSize(QSize(24, 24))
        self.pad_shape.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.pad_shape.setStyleSheet("QToolButton { background: #ffffff; padding: 1px 4px; }")
        menu = QMenu(self.pad_shape)
        for item in PAD_SHAPES:
            if item is None:
                menu.addSeparator()
                continue
            label, shape = item
            menu.addAction(pad_shape_icon(shape), label).triggered.connect(
                lambda _=False, shape=shape: self.pad_shape_chosen(shape)
            )
        self.pad_shape.setMenu(menu)
        grid.addWidget(self.pad_shape, 4, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
        self.pad_diameter = self.box(0.01)
        self.pad_drill = self.box(0.0)
        self.pad_diameter.setToolTip("Диаметр площадки")
        self.pad_drill.setToolTip("Диаметр отверстия")
        self.pad_diameter.valueChanged.connect(self.pad_changed)
        self.pad_drill.valueChanged.connect(self.pad_changed)
        self.size_block(grid, 5, "padsize", self.pad_diameter, self.pad_drill)
        self.pad_plated = QCheckBox("Металлизация")
        self.pad_plated.setToolTip("Металлизированное (сквозное) отверстие")
        self.pad_plated.toggled.connect(self.pad_changed)
        grid.addWidget(self.pad_plated, 7, 0, 1, 4)
        self.pad_thermal = ThermalBox(self.units, with_layers=True)
        self.pad_thermal.changed.connect(self.thermal_changed)
        self.pad_thermal.percent_changed.connect(self.thermal_percent_changed)
        grid.addWidget(self.pad_thermal, 8, 0, 1, 4)
        self.pad_mask = QCheckBox("Окно в паяльной маске")
        self.pad_mask.toggled.connect(self.pad_changed)
        grid.addWidget(self.pad_mask, 9, 0, 1, 4)
        self.pad_clearance = self.box(0.0, 20.0)
        self.pad_clearance.valueChanged.connect(self.pad_changed)
        grid.addWidget(QLabel("Зазор до заливки:"), 10, 0, 1, 3)
        self.value_row(grid, 11, "", self.pad_clearance)

    def pad_shape_chosen(self, shape: int) -> None:
        self.edit(core.with_pad_shape(self.element(), shape), "Форма площадки")

    def pad_moved(self) -> None:
        ox, oy = self.origin()
        self.edit(
            core.moved_to(self.element(), self.pad_x.mm() + ox, self.pad_y.mm() + oy),
            "Перемещение площадки",
        )

    def pad_changed(self) -> None:
        obj = self.element()
        diameter, drill = self.pad_diameter.mm(), self.pad_drill.mm()
        if drill >= diameter:
            self.refresh()
            return
        new = core.with_pad_size(obj, diameter, drill)
        new = replace(
            new,
            plated=self.pad_plated.isChecked(),
            soldermask=self.pad_mask.isChecked(),
            clearance=self.pad_clearance.mm(),
        )
        self.edit(new, "Свойства площадки")

    def thermal_changed(self, enabled: bool, bits: int, layer) -> None:
        obj = self.element()
        if enabled and not core.has_thermal(obj) and bits == 0:
            bits = core.STRAIGHT_SPOKES
        self.edit(core.with_thermal(obj, enabled, bits, layer), "Термобарьер")

    def thermal_percent_changed(self, percent: int) -> None:
        self.edit(core.with_thermal_percent(self.element(), percent), "Ширина перемычек")

    def build_smd_page(self) -> None:
        self.smd_page, grid = self.page()
        self.smd_x, self.smd_y = self.centre_rows(grid, 0, self.smd_moved)
        self.smd_width = self.box(0.01)
        self.smd_height = self.box(0.01)
        self.smd_width.setToolTip("Ширина SMD-площадки")
        self.smd_height.setToolTip("Высота SMD-площадки")
        self.smd_width.valueChanged.connect(self.smd_changed)
        self.smd_height.valueChanged.connect(self.smd_changed)
        self.size_block(grid, 3, "smdsize", self.smd_width, self.smd_height)
        self.smd_angle = QLabel()
        grid.addWidget(QLabel("Поворот:"), 5, 0)
        grid.addWidget(self.smd_angle, 5, 1, 1, 2)
        self.smd_thermal = ThermalBox(self.units, with_layers=False)
        self.smd_thermal.changed.connect(self.thermal_changed)
        self.smd_thermal.percent_changed.connect(self.thermal_percent_changed)
        grid.addWidget(self.smd_thermal, 6, 0, 1, 4)
        self.smd_mask = QCheckBox("Окно в паяльной маске")
        self.smd_mask.toggled.connect(self.smd_changed)
        grid.addWidget(self.smd_mask, 7, 0, 1, 4)
        self.smd_clearance = self.box(0.0, 20.0)
        self.smd_clearance.valueChanged.connect(self.smd_changed)
        grid.addWidget(QLabel("Зазор до заливки:"), 8, 0, 1, 3)
        self.value_row(grid, 9, "", self.smd_clearance)

    def smd_moved(self) -> None:
        ox, oy = self.origin()
        self.edit(
            core.moved_to(self.element(), self.smd_x.mm() + ox, self.smd_y.mm() + oy),
            "Перемещение SMD-площадки",
        )

    def smd_changed(self) -> None:
        new = core.with_smd_size(self.element(), self.smd_width.mm(), self.smd_height.mm())
        new = replace(new, soldermask=self.smd_mask.isChecked(), clearance=self.smd_clearance.mm())
        self.edit(new, "Свойства SMD-площадки")

    # --- tracks -----------------------------------------------------------------

    def build_track_page(self) -> None:
        self.track_page, grid = self.page()
        self.track_width = self.box(0.01, 50.0)
        self.track_width.valueChanged.connect(self.track_changed)
        grid.addWidget(QLabel("Ширина:"), 0, 0, 1, 3)
        self.value_row(grid, 1, "", self.track_width)
        self.track_length = QLabel()
        self.track_nodes = QLabel()
        self.track_current = QLabel()
        grid.addWidget(QLabel("Длина:"), 2, 0)
        grid.addWidget(self.track_length, 2, 1, 1, 3)
        grid.addWidget(QLabel("Узлов:"), 3, 0)
        grid.addWidget(self.track_nodes, 3, 1, 1, 3)
        grid.addWidget(QLabel("Ток*:"), 4, 0)
        grid.addWidget(self.track_current, 4, 1, 1, 3)
        grid.addWidget(note("* (35 мкм / 20 °C)", "#a00000"), 5, 0, 1, 4)
        self.track_keepout = QCheckBox("Запретная зона")
        self.track_keepout.toggled.connect(self.track_changed)
        grid.addWidget(self.track_keepout, 6, 0, 1, 4)
        self.track_clearance = self.box(0.0, 20.0)
        self.track_clearance.valueChanged.connect(self.track_changed)
        grid.addWidget(QLabel("Зазор до заливки:"), 7, 0, 1, 3)
        self.value_row(grid, 8, "", self.track_clearance)

    def track_changed(self) -> None:
        new = replace(
            self.element(),
            width=self.track_width.mm(),
            keepout=self.track_keepout.isChecked(),
            clearance=self.track_clearance.mm(),
        )
        self.edit(new, "Свойства дорожки")

    # --- polygons ---------------------------------------------------------------

    def build_polygon_page(self) -> None:
        self.polygon_page, grid = self.page()
        self.polygon_width = self.box(0.0, 50.0)
        self.polygon_width.valueChanged.connect(self.polygon_changed)
        grid.addWidget(QLabel("Контур:"), 0, 0, 1, 3)
        self.value_row(grid, 1, "", self.polygon_width)
        self.polygon_hatched = QCheckBox("Штриховка")
        self.polygon_hatched.toggled.connect(self.polygon_changed)
        grid.addWidget(self.polygon_hatched, 2, 0, 1, 4)
        self.hatch_outline = QRadioButton("Как контур")
        self.hatch_own = QRadioButton("Своя ширина:")
        group = QButtonGroup(self)
        group.addButton(self.hatch_outline)
        group.addButton(self.hatch_own)
        self.hatch_outline.toggled.connect(self.polygon_changed)
        grid.addWidget(self.hatch_outline, 3, 0, 1, 4)
        grid.addWidget(self.hatch_own, 4, 0, 1, 4)
        self.hatch_width = self.box(0.01, 50.0)
        self.hatch_width.valueChanged.connect(self.polygon_changed)
        self.value_row(grid, 5, "", self.hatch_width)
        self.polygon_nodes = QLabel()
        grid.addWidget(QLabel("Узлов:"), 6, 0)
        grid.addWidget(self.polygon_nodes, 6, 1, 1, 3)
        self.polygon_keepout = QCheckBox("Запретная зона")
        self.polygon_keepout.setToolTip("Вырез в автозаливке")
        self.polygon_keepout.toggled.connect(self.polygon_changed)
        grid.addWidget(self.polygon_keepout, 7, 0, 1, 4)
        self.polygon_mask = QCheckBox("Вырез в паяльной маске")
        self.polygon_mask.toggled.connect(self.polygon_changed)
        grid.addWidget(self.polygon_mask, 8, 0, 1, 4)

    def polygon_changed(self) -> None:
        hatched = self.polygon_hatched.isChecked()
        new = core.with_hatching(self.element(), hatched)
        if hatched:
            new = core.with_hatch_style(new, self.hatch_outline.isChecked(), self.hatch_width.mm())
        new = replace(
            new,
            width=self.polygon_width.mm(),
            keepout=self.polygon_keepout.isChecked(),
            soldermask=self.polygon_mask.isChecked(),
        )
        self.edit(new, "Свойства полигона")

    # --- circles ----------------------------------------------------------------

    def build_circle_page(self) -> None:
        self.circle_page, grid = self.page()
        self.circle_x, self.circle_y = self.centre_rows(grid, 0, self.circle_moved)
        self.circle_line = self.box(0.0, 50.0)
        self.circle_start = AngleBox()
        self.circle_stop = AngleBox()
        self.circle_diameter = self.box(0.01)
        grid.addWidget(QLabel("Толщина линии:"), 3, 0, 1, 3)
        self.value_row(grid, 4, "", self.circle_line)
        grid.addWidget(QLabel("Начальный угол:"), 5, 0, 1, 3)
        self.value_row(grid, 6, "", self.circle_start, unit=False)
        grid.addWidget(QLabel("Конечный угол:"), 7, 0, 1, 3)
        self.value_row(grid, 8, "", self.circle_stop, unit=False)
        grid.addWidget(QLabel("Диаметр:"), 9, 0, 1, 3)
        self.value_row(grid, 10, "", self.circle_diameter)
        for widget in (self.circle_diameter, self.circle_line, self.circle_start, self.circle_stop):
            widget.valueChanged.connect(self.circle_changed)
        self.circle_keepout = QCheckBox("Запретная зона")
        self.circle_filled = QCheckBox("Заливка")
        self.circle_keepout.toggled.connect(self.circle_changed)
        self.circle_filled.toggled.connect(self.circle_changed)
        grid.addWidget(self.circle_keepout, 11, 0, 1, 4)
        grid.addWidget(self.circle_filled, 12, 0, 1, 4)
        grid.addWidget(AngleDiagram(), 13, 0, 1, 4, Qt.AlignmentFlag.AlignHCenter)
        grid.addWidget(
            note("Дуга идёт от начального угла к конечному против часовой стрелки."), 14, 0, 1, 4
        )

    def circle_moved(self) -> None:
        ox, oy = self.origin()
        self.edit(
            core.moved_to(self.element(), self.circle_x.mm() + ox, self.circle_y.mm() + oy),
            "Перемещение окружности",
        )

    def circle_changed(self) -> None:
        line = self.circle_line.mm()
        if line > self.circle_diameter.mm():
            self.refresh()
            return
        new = core.with_circle(
            self.element(),
            self.circle_diameter.mm(),
            line,
            self.circle_start.value(),
            self.circle_stop.value(),
            self.circle_filled.isChecked(),
        )
        self.edit(replace(new, keepout=self.circle_keepout.isChecked()), "Свойства окружности")

    # --- texts ------------------------------------------------------------------

    def build_text_page(self) -> None:
        self.text_page, grid = self.page()
        self.text_value = QLineEdit()
        self.text_value.editingFinished.connect(self.text_changed)
        grid.addWidget(QLabel("Текст:"), 0, 0, 1, 3)
        grid.addWidget(self.text_value, 1, 0, 1, 4)
        self.text_height = self.box(core.HEIGHT_RANGE[0], core.HEIGHT_RANGE[1])
        self.text_height.valueChanged.connect(self.text_changed)
        self.value_row(grid, 2, "Высота:", self.text_height)
        self.text_weight = QComboBox()
        self.text_weight.addItems(["Тонкий", "Обычный", "Жирный"])
        self.text_spacing = QComboBox()
        self.text_spacing.addItems(["Узкий", "Обычный", "Широкий"])
        grid.addWidget(QLabel("Толщина:"), 3, 0)
        grid.addWidget(self.text_weight, 3, 1, 1, 3)
        grid.addWidget(QLabel("Интервал:"), 4, 0)
        grid.addWidget(self.text_spacing, 4, 1, 1, 3)
        self.text_angle = AngleBox()
        self.text_angle.setDecimals(0)
        self.value_row(grid, 5, "Угол:", self.text_angle, unit=False)
        self.text_mirror_x = QCheckBox("Зеркально по горизонтали")
        self.text_mirror_y = QCheckBox("Зеркально по вертикали")
        grid.addWidget(self.text_mirror_x, 6, 0, 1, 4)
        grid.addWidget(self.text_mirror_y, 7, 0, 1, 4)
        self.text_keepout = QCheckBox("Запретная зона")
        grid.addWidget(self.text_keepout, 8, 0, 1, 4)
        for combo in (self.text_weight, self.text_spacing):
            combo.currentIndexChanged.connect(self.text_changed)
        self.text_angle.valueChanged.connect(self.text_changed)
        for check in (self.text_mirror_x, self.text_mirror_y, self.text_keepout):
            check.toggled.connect(self.text_changed)
        self.text_component = QToolButton()
        self.text_component.setText("Компонент…")
        self.text_component.setToolTip("Обозначение, номинал, корпус и комментарий компонента")
        self.text_component.clicked.connect(lambda: self.component_requested.emit())
        grid.addWidget(self.text_component, 9, 0, 1, 4)

    def text_changed(self, *_args) -> None:
        if self.index is None or self.board is None:
            return
        obj = self.element()
        if obj.kind != core.STROKE_TEXT:
            return
        new = core.with_text(
            obj,
            text=self.text_value.text(),
            height=self.text_height.mm(),
            weight=self.text_weight.currentIndex(),
            spacing=self.text_spacing.currentIndex(),
            rotation=round(self.text_angle.value()),
            mirror_x=self.text_mirror_x.isChecked(),
            mirror_y=self.text_mirror_y.isChecked(),
        )
        self.edit(replace(new, keepout=self.text_keepout.isChecked()), "Свойства текста")

    # --- several objects --------------------------------------------------------

    def build_multi_page(self) -> None:
        self.multi_page, grid = self.page()
        self.multi_list = QLabel()
        self.multi_list.setWordWrap(True)
        self.multi_list.setStyleSheet("background: #ffffff; padding: 3px;")
        grid.addWidget(self.multi_list, 0, 0, 1, 4)
        self.multi_track_width = self.box(0.01, 50.0)
        self.multi_track_width.valueChanged.connect(self.multi_tracks_changed)
        self.multi_track_label = QLabel("Ширина дорожек:")
        grid.addWidget(self.multi_track_label, 1, 0, 1, 3)
        self.value_row(grid, 2, "", self.multi_track_width)
        self.multi_pad_diameter = self.box(0.01)
        self.multi_pad_drill = self.box(0.0)
        self.multi_pad_diameter.valueChanged.connect(self.multi_pads_changed)
        self.multi_pad_drill.valueChanged.connect(self.multi_pads_changed)
        self.multi_pad_label = QLabel("Площадки:")
        grid.addWidget(self.multi_pad_label, 3, 0, 1, 3)
        self.size_block(grid, 4, "padsize", self.multi_pad_diameter, self.multi_pad_drill)
        self.multi_clearance = self.box(0.0, 20.0)
        self.multi_clearance.valueChanged.connect(self.multi_clearance_changed)
        grid.addWidget(QLabel("Зазор до заливки:"), 6, 0, 1, 3)
        self.value_row(grid, 7, "", self.multi_clearance)
        grid.addWidget(
            note("Значения применяются ко всем выделенным объектам этого вида."), 8, 0, 1, 4
        )

    def selected_of(self, kinds) -> list[int]:
        assert self.board is not None
        return [i for i in self.members if self.board.elements[i].kind in kinds]

    def multi_tracks_changed(self) -> None:
        assert self.board is not None
        width = self.multi_track_width.mm()
        edits = {
            i: replace(self.board.elements[i], width=width)
            for i in self.selected_of((core.LINE, core.SEGMENT))
        }
        self.edited.emit(edits, "Ширина дорожек")

    def multi_pads_changed(self) -> None:
        assert self.board is not None
        diameter, drill = self.multi_pad_diameter.mm(), self.multi_pad_drill.mm()
        if drill >= diameter:
            self.refresh()
            return
        edits = {
            i: core.with_pad_size(self.board.elements[i], diameter, drill)
            for i in self.selected_of((core.THT,))
        }
        self.edited.emit(edits, "Размер площадок")

    def multi_clearance_changed(self) -> None:
        assert self.board is not None
        clearance = self.multi_clearance.mm()
        edits = {
            i: replace(self.board.elements[i], clearance=clearance)
            for i in self.members
            if not core.is_hidden_label(self.board.elements[i])
        }
        self.edited.emit(edits, "Зазор до заливки")

    # --- showing ----------------------------------------------------------------

    def show_selection(self, board: core.Board | None, members: list[int], index: int | None):
        self.board, self.members, self.index = board, list(members), index
        self.refresh()

    def refresh(self) -> None:
        board = self.board
        if board is None:
            self.heading.setText("")
            return
        parts = core.units(board.elements, self.members) if self.members else []
        if len(parts) > 1:
            self.show_multi(board)
        elif self.index is None:
            self.show_board()
        else:
            self.show_object(self.element())

    def show_board(self) -> None:
        assert self.board is not None
        board = self.board
        self.heading.setText("Плата")
        self.board_name.blockSignals(True)
        self.board_name.setText(board.name)
        self.board_name.blockSignals(False)
        self.board_width.set_mm(board.width)
        self.board_height.set_mm(board.height)
        area = board.width * board.height / 100
        self.board_area.setText(f"{area:.1f} см²".replace(".", ","))
        quiet_check(self.board_multilayer, board.multilayer)
        self.pages.setCurrentWidget(self.board_page)

    def show_object(self, obj: core.Element) -> None:
        ox, oy = self.origin()
        x, y = core.centre_of(obj)
        name = core.KIND_NAMES.get(obj.kind, "Текст")
        cid = core.component_id(obj)
        if cid and self.board is not None:
            package = core.component_package(self.board.elements, cid)
            name += f" ({package})" if package else " (компонент)"
        self.heading.setText(name)
        if obj.kind == core.THT:
            self.pad_x.set_mm(x - ox)
            self.pad_y.set_mm(y - oy)
            self.pad_shape.setIcon(pad_shape_icon(obj.shape))
            self.pad_shape.setToolTip(SHAPE_NAMES.get(obj.shape, "Форма площадки"))
            self.pad_diameter.set_mm(obj.outer * 2)
            self.pad_drill.set_mm(obj.inner * 2)
            quiet_check(self.pad_plated, obj.plated)
            quiet_check(self.pad_mask, obj.soldermask)
            self.pad_clearance.set_mm(obj.clearance)
            self.pad_thermal.show_pad(obj)
            self.pages.setCurrentWidget(self.pad_page)
        elif obj.kind == core.SMD:
            width, height = core.smd_size(obj)
            self.smd_x.set_mm(x - ox)
            self.smd_y.set_mm(y - oy)
            self.smd_width.set_mm(width)
            self.smd_height.set_mm(height)
            self.smd_angle.setText(f"{core.smd_angle(obj):.1f}°".replace(".", ","))
            quiet_check(self.smd_mask, obj.soldermask)
            self.smd_clearance.set_mm(obj.clearance)
            self.smd_thermal.show_pad(obj)
            self.pages.setCurrentWidget(self.smd_page)
        elif obj.kind in (core.LINE, core.SEGMENT):
            self.track_width.set_mm(obj.width)
            self.track_length.setText(self.units.with_suffix(core.track_length(obj)))
            nodes = 2 if obj.kind == core.SEGMENT else len(obj.points)
            self.track_nodes.setText(str(nodes))
            current = core.track_current(obj.width, OPTIONS["copper_um"], OPTIONS["rise"])
            self.track_current.setText(f"{current:.3g} А".replace(".", ","))
            quiet_check(self.track_keepout, obj.keepout)
            self.track_clearance.set_mm(obj.clearance)
            self.pages.setCurrentWidget(self.track_page)
        elif obj.kind == core.POLYGON:
            hatched = core.is_hatched(obj)
            self.polygon_width.set_mm(obj.width)
            self.polygon_nodes.setText(str(len(obj.points)))
            quiet_check(self.polygon_hatched, hatched)
            quiet_check(self.hatch_outline, core.hatch_uses_outline(obj))
            quiet_check(self.hatch_own, not core.hatch_uses_outline(obj))
            self.hatch_width.set_mm(core.hatch_width(obj))
            for widget in (self.hatch_outline, self.hatch_own, self.hatch_width):
                widget.setEnabled(hatched)
            quiet_check(self.polygon_keepout, obj.keepout)
            quiet_check(self.polygon_mask, obj.soldermask)
            self.pages.setCurrentWidget(self.polygon_page)
        elif obj.kind == core.CIRCLE:
            start, stop = core.circle_angles(obj)
            self.circle_x.set_mm(x - ox)
            self.circle_y.set_mm(y - oy)
            self.circle_diameter.set_mm(core.circle_diameter(obj))
            self.circle_line.set_mm(core.circle_line_width(obj))
            self.circle_start.set_quietly(start)
            self.circle_stop.set_quietly(stop)
            quiet_check(self.circle_filled, obj.filled)
            quiet_check(self.circle_keepout, obj.keepout)
            self.pages.setCurrentWidget(self.circle_page)
        else:
            widgets: tuple[QWidget, ...] = (
                self.text_value,
                self.text_weight,
                self.text_spacing,
                self.text_mirror_x,
                self.text_mirror_y,
            )
            for text_widget in widgets:
                text_widget.blockSignals(True)
            self.text_value.setText(obj.text)
            self.text_weight.setCurrentIndex(core.text_weight(obj))
            self.text_spacing.setCurrentIndex(core.text_spacing(obj))
            self.text_mirror_x.setChecked(obj.mirror_x)
            self.text_mirror_y.setChecked(obj.mirror_y)
            for text_widget in widgets:
                text_widget.blockSignals(False)
            self.text_height.set_mm(obj.outer)
            self.text_angle.set_quietly(obj.rotation)
            quiet_check(self.text_keepout, obj.keepout)
            self.text_component.setVisible(bool(core.component_id(obj)))
            self.pages.setCurrentWidget(self.text_page)

    def show_multi(self, board: core.Board) -> None:
        elements = [board.elements[i] for i in self.members]
        visible = [obj for obj in elements if not core.is_hidden_label(obj)]
        counts = Counter(core.KIND_NAMES.get(obj.kind, "Текст") for obj in visible)
        self.heading.setText(f"Выделено объектов: {len(visible)}")
        self.multi_list.setText("\n".join(f"{name}: {n}" for name, n in sorted(counts.items())))
        tracks = [obj for obj in elements if obj.kind in (core.LINE, core.SEGMENT)]
        pads = [obj for obj in elements if obj.kind == core.THT]
        for widget in (self.multi_track_label, self.multi_track_width):
            widget.setVisible(bool(tracks))
        for widget in (self.multi_pad_label, self.multi_pad_diameter, self.multi_pad_drill):
            widget.setVisible(bool(pads))
        if tracks:
            self.multi_track_width.set_mm(tracks[0].width)
        if pads:
            self.multi_pad_diameter.set_mm(pads[0].outer * 2)
            self.multi_pad_drill.set_mm(pads[0].inner * 2)
        if visible:
            self.multi_clearance.set_mm(visible[0].clearance)
        self.pages.setCurrentWidget(self.multi_page)
