"""Small widgets: value fields, size favourites, panel caption, layer bar."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QRadioButton,
    QToolButton,
    QWidget,
)

from .icons import tool_icon
from .style import FAVOURITES, LAYER_HINTS, LAYERS, VALUE_STYLE, mm


def value_box(value, minimum=0.01, maximum=100.0):
    box = QDoubleSpinBox()
    box.setDecimals(2)
    box.setRange(minimum, maximum)
    box.setSingleStep(0.05)
    box.setValue(value)
    box.setKeyboardTracking(False)
    box.setFixedWidth(48)
    box.setAlignment(Qt.AlignmentFlag.AlignRight)
    box.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
    box.setStyleSheet(VALUE_STYLE)
    return box


def separator():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line


def parse_values(text):
    """Sizes stored as "1.6;0.8"; None when the text is missing or malformed."""
    if not text:
        return None
    try:
        return tuple(float(value) for value in str(text).split(";"))
    except ValueError:
        return None


class SizeRow(QWidget):
    """Size fields with a favourites list, like the left panel of classic layout editors."""

    changed = Signal()

    def __init__(self, key, icon, hints, settings):
        super().__init__()
        self.key, self.settings = key, settings
        self.boxes = []
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(2)
        layout.setVerticalSpacing(1)
        self.button = QToolButton()
        self.button.setIcon(tool_icon(icon))
        self.button.setIconSize(QSize(20, 20))
        self.button.setText("▾")
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setStyleSheet(
            "QToolButton { color: #2050d0; } QToolButton::menu-indicator { image: none; }"
        )
        self.button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.button.setToolTip("Избранные размеры")
        self.button.setAutoRaise(True)
        self.menu = QMenu(self)
        self.menu.aboutToShow.connect(self.fill_menu)
        self.button.setMenu(self.menu)
        layout.addWidget(self.button, 0, 0, len(hints), 1, Qt.AlignmentFlag.AlignVCenter)
        default = FAVOURITES[key][3 if key == "track" else 4]
        values = default if isinstance(default, tuple) else (default,)
        stored = parse_values(settings.value(f"size/{key}"))
        if stored is not None and len(stored) == len(hints):
            values = stored
        for row, (hint, value) in enumerate(zip(hints, values, strict=True)):
            box = value_box(value, 0.0 if key == "pad" and row == 1 else 0.01)
            box.setToolTip(hint)
            box.valueChanged.connect(self.value_changed)
            layout.addWidget(box, row, 1)
            self.boxes.append(box)
        stored = settings.value(f"favourites/{key}")
        self.favourites = list(FAVOURITES[key])
        if stored:
            items = [parse_values(item) for item in str(stored).split("|") if item]
            if items and all(item is not None and len(item) == len(hints) for item in items):
                self.favourites = [item[0] if len(item) == 1 else item for item in items]

    def values(self):
        return tuple(box.value() for box in self.boxes)

    def current(self):
        values = self.values()
        return values[0] if len(values) == 1 else values

    def set_values(self, values, emit=False):
        for box, value in zip(self.boxes, values, strict=True):
            box.blockSignals(not emit)
            box.setValue(value)
            box.blockSignals(False)
        self.save()

    def label(self, item):
        values = item if isinstance(item, tuple) else (item,)
        return " x ".join(mm(v) for v in values) + " мм"

    def fill_menu(self):
        self.menu.clear()
        current = self.current()
        for item in self.favourites:
            action = self.menu.addAction(self.label(item))
            action.setCheckable(True)
            action.setChecked(item == current)
            values = item if isinstance(item, tuple) else (item,)
            action.triggered.connect(
                lambda _=False, values=values: self.set_values(values, emit=True)
            )
        self.menu.addSeparator()
        add = self.menu.addAction("+  " + self.label(current))
        add.setToolTip("Добавить текущий размер в избранное")
        add.setEnabled(current not in self.favourites)
        add.triggered.connect(self.add_current)
        remove = self.menu.addMenu("Удалить")
        remove.setEnabled(bool(self.favourites))
        for item in self.favourites:
            remove.addAction(self.label(item)).triggered.connect(
                lambda _=False, item=item: self.remove(item)
            )

    def add_current(self):
        self.favourites.append(self.current())
        self.favourites.sort()
        self.save()

    def remove(self, item):
        self.favourites.remove(item)
        self.save()

    def value_changed(self):
        self.save()
        self.changed.emit()

    def save(self):
        self.settings.setValue(f"size/{self.key}", ";".join(f"{v:g}" for v in self.values()))
        self.settings.setValue(
            f"favourites/{self.key}",
            "|".join(
                ";".join(f"{v:g}" for v in (item if isinstance(item, tuple) else (item,)))
                for item in self.favourites
            ),
        )


class PanelTitle(QWidget):
    """Dark caption bar of a side panel with a close button."""

    def __init__(self, title, on_close, color="#ff4040"):
        super().__init__()
        # A plain QWidget paints a style-sheet background only with this attribute;
        # without it the caption takes the colour of a styled parent panel.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("paneltitle")
        self.setStyleSheet("QWidget#paneltitle { background: #000000; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 1, 1)
        label = QLabel(title)
        label.setStyleSheet(f"color: {color}; font-weight: bold; background: transparent;")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label, 1)
        close = QToolButton()
        close.setText("✕")
        close.setToolTip("Скрыть панель")
        close.setAutoRaise(True)
        close.setStyleSheet("color: #ffffff; background: #000000;")
        close.clicked.connect(on_close)
        layout.addWidget(close)


class LayerBar(QWidget):
    """Visible / active layer switches of the status bar."""

    visibility = Signal(int, bool)
    activated = Signal(int)

    ORDER = (1, 2, 3, 4, 5, 6, 7)

    def __init__(self):
        super().__init__()
        self.setObjectName("layerbar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget#layerbar { border: 1px solid #a0a0a0; }"
            " QWidget#layerbar > QLabel { border-right: 1px solid #a0a0a0; padding: 0 4px; }"
        )
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 2, 0)
        layout.setHorizontalSpacing(2)
        layout.setVerticalSpacing(0)
        layout.addWidget(QLabel("видимый"), 0, 0)
        layout.addWidget(QLabel("активный"), 1, 0)
        self.checks, self.radios = {}, {}
        group = QButtonGroup(self)
        for column, layer in enumerate(self.ORDER, 1):
            name, color = LAYERS[layer]
            check = QToolButton()
            check.setText(name)
            check.setCheckable(True)
            check.setChecked(True)
            check.setToolTip(LAYER_HINTS[layer])
            check.setStyleSheet(
                f"QToolButton {{ color: {color}; background: #000000; font-weight: bold;"
                f" border: 1px solid #000000; padding: 0 2px; }}"
                f" QToolButton:!checked {{ color: #505050; }}"
            )
            check.toggled.connect(lambda visible, layer=layer: self.visibility.emit(layer, visible))
            radio = QRadioButton()
            radio.setToolTip(LAYER_HINTS[layer])
            group.addButton(radio, layer)
            layout.addWidget(check, 0, column)
            layout.addWidget(radio, 1, column, Qt.AlignmentFlag.AlignHCenter)
            self.checks[layer], self.radios[layer] = check, radio
        group.idClicked.connect(self.activated.emit)

    def set_available(self, layer, available):
        self.checks[layer].setVisible(available)
        self.radios[layer].setVisible(available)

    def set_active(self, layer):
        self.radios[layer].setChecked(True)
        self.checks[layer].setChecked(True)
