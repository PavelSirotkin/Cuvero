"""Photo view: the board as it comes from the factory, drawn from the exact output geometry.

Colours were measured on the original program's photo view: the mask is bright over
copper and darker over the bare board, the other side's copper shows darker still through
the board (X-ray); exposed pads gold, print white, holes black.
"""

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

import core
from core import gerber, gerber_read

from .gerber_paths import copper_path

# (name, mask over the bare board, mask over copper, the other side's copper seen through)
BOARD_COLOURS = (
    ("Зелёная", "#00a500", "#00be00", "#167516"),
    ("Синяя", "#1a43b4", "#2458e0", "#18337a"),
    ("Без маски", "#c9b48a", "#c87533", "#9c8460"),
)
FINISHES = (("Золото", "#dcaa14"), ("Серебро", "#c8c8c8"), ("Медь", "#c87533"))
PRINT = "#ffffff"
HOLE = "#000000"


@dataclass
class PhotoOptions:
    top: bool = True
    silkscreen: bool = True
    xray: bool = True
    board: int = 0
    finish: int = 0


def _path(board: core.Board, ending: str) -> QPainterPath:
    text = gerber.layer_gerber(board, ending, gerber.GerberOptions(x2=False, mask_other=0.0))
    path = copper_path(gerber_read.parse(text))
    ox, oy = core.board_origin(board)
    return QTransform(1, 0, 0, -1, ox, -oy).map(path)


def draw_photo(scene, board: core.Board, options: PhotoOptions) -> None:
    """Fill a scene with the photo view of one side of the board (bottom mirrored)."""
    no_pen = QPen(Qt.PenStyle.NoPen)
    _name, bare, over_copper, through = BOARD_COLOURS[options.board]
    finish = FINISHES[options.finish][1]
    side = "top" if options.top else "bottom"
    other = "bottom" if options.top else "top"
    area = QPainterPath()
    area.addRect(QRectF(0, 0, board.width, board.height))
    copper = _path(board, f"copper_{side}")
    openings = _path(board, f"soldermask_{side}")
    items = []
    items.append(scene.addPath(area, no_pen, QColor(bare)))
    items.append(scene.addPath(copper, no_pen, QColor(over_copper)))
    if options.xray:
        # The original shows the other side's copper through everything under the mask.
        items.append(scene.addPath(_path(board, f"copper_{other}"), no_pen, QColor(through)))
    # Without a mask all copper gets the finish.
    exposed = copper if options.board == 2 else copper.intersected(openings)
    items.append(scene.addPath(exposed, no_pen, QColor(finish)))
    if options.silkscreen:
        silk = _path(board, "silkscreen_top" if options.top else "silkscreen_bottom")
        # Print does not stick on exposed pads.
        items.append(scene.addPath(silk.subtracted(exposed), no_pen, QColor(PRINT)))
    holes = QPainterPath()
    for diameter, pad in core.holes(board):
        holes.addEllipse(QPointF(pad.x, -pad.y), diameter / 2, diameter / 2)
    items.append(scene.addPath(holes, no_pen, QColor(HOLE)))
    outline = scene.addRect(QRectF(0, 0, board.width, board.height), QPen(QColor("#202020"), 0))
    items.append(outline)
    if not options.top:
        # Seen from below: mirrored left to right about the board's middle.
        mirror = QTransform(-1, 0, 0, 1, board.width, 0)
        for item in items:
            item.setTransform(mirror)
    for z, item in enumerate(items):
        item.setZValue(z)


class PhotoBar(QWidget):
    """Options of the photo view, shown above the board while the view is active."""

    def __init__(self, settings, changed):
        super().__init__()
        self.settings = settings
        self.setObjectName("photobar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("QWidget#photobar { background: #fffff0; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        sides = QVBoxLayout()
        self.side = QButtonGroup(self)
        for index, label in enumerate(("Сторона C1/S1", "Сторона C2/S2 (зеркально)")):
            radio = QRadioButton(label)
            self.side.addButton(radio, index)
            sides.addWidget(radio)
        (self.side.button(int(settings.value("photo/side", 0))) or self.side.button(0)).setChecked(
            True
        )
        layout.addLayout(sides)
        checks = QVBoxLayout()
        self.silkscreen = QCheckBox("С шелкографией")
        self.xray = QCheckBox("На просвет")
        for key, check in (("silkscreen", self.silkscreen), ("xray", self.xray)):
            check.setChecked(str(settings.value(f"photo/{key}", "true")).lower() == "true")
            checks.addWidget(check)
        layout.addSpacing(20)
        layout.addLayout(checks)
        self.board = QComboBox()
        self.board.addItems([row[0] for row in BOARD_COLOURS])
        self.finish = QComboBox()
        self.finish.addItems([row[0] for row in FINISHES])
        for key, combo in (("board", self.board), ("finish", self.finish)):
            combo.setCurrentIndex(int(settings.value(f"photo/{key}", 0)))
        for caption, combo in (("Плата:", self.board), ("Покрытие:", self.finish)):
            column = QVBoxLayout()
            column.addWidget(QLabel(caption))
            column.addWidget(combo)
            layout.addSpacing(20)
            layout.addLayout(column)
        layout.addStretch()
        self.side.idToggled.connect(lambda *_: changed())
        for check in (self.silkscreen, self.xray):
            check.toggled.connect(lambda *_: changed())
        for combo in (self.board, self.finish):
            combo.currentIndexChanged.connect(lambda *_: changed())

    def options(self) -> PhotoOptions:
        options = PhotoOptions(
            top=self.side.checkedId() == 0,
            silkscreen=self.silkscreen.isChecked(),
            xray=self.xray.isChecked(),
            board=self.board.currentIndex(),
            finish=self.finish.currentIndex(),
        )
        s = self.settings
        s.setValue("photo/side", self.side.checkedId())
        s.setValue("photo/silkscreen", options.silkscreen)
        s.setValue("photo/xray", options.xray)
        s.setValue("photo/board", options.board)
        s.setValue("photo/finish", options.finish)
        return options
