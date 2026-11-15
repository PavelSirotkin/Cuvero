"""Background template: a scanned picture of a board under the layout, to trace it.

Each board side has its own picture with resolution, offset and colour, as in the original.
The bottom side's picture is mirrored, as it is scanned from below. The picture of the active
side is shown under the board.
"""

import json
from dataclasses import asdict, dataclass
from hashlib import sha1
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPixmap, QTransform
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QFileDialog,
    QGraphicsPixmapItem,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

IMAGES = "Изображения (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff);;Все файлы (*)"


@dataclass
class Template:
    path: str = ""
    dpi: int = 600
    dx: int = 0  # 1/10 mm
    dy: int = 0  # 1/10 mm
    visible: bool = True
    colour: str = "#ffffff"


def settings_key(project: Path | None, board_name: str) -> str:
    name = f"{project or ''}|{board_name}"
    return "template/" + sha1(name.encode("utf-8")).hexdigest()[:16]


def load_templates(settings, key: str) -> dict[int, Template]:
    try:
        data = json.loads(str(settings.value(key, "{}")))
        return {int(side): Template(**values) for side, values in data.items()}
    except (ValueError, TypeError):
        return {}


def save_templates(settings, key: str, templates: dict[int, Template]) -> None:
    data = {str(side): asdict(t) for side, t in templates.items() if t.path}
    settings.setValue(key, json.dumps(data))


_CACHE: dict[tuple[str, str, float], QImage] = {}


def tinted(path: str, colour: str) -> QImage | None:
    """The picture's dark lines in the chosen colour on a transparent background."""
    try:
        stamp = Path(path).stat().st_mtime
    except OSError:
        return None
    key = (path, colour, stamp)
    if key in _CACHE:
        return _CACHE[key]
    image = QImage(path)
    if image.isNull():
        return None
    grey = image.convertToFormat(QImage.Format.Format_Grayscale8)
    alpha = grey.copy()
    alpha.invertPixels()
    result = QImage(grey.size(), QImage.Format.Format_ARGB32)
    result.fill(QColor(colour))
    result.setAlphaChannel(alpha)
    _CACHE.clear()  # keep one picture in memory
    _CACHE[key] = result
    return result


def template_item(template: Template, side: int, board_height: float) -> QGraphicsPixmapItem | None:
    """A scene item with the picture in place: top left at the board's top left corner."""
    if not template.path or not template.visible:
        return None
    image = tinted(template.path, template.colour)
    if image is None:
        return None
    if side == 2:
        image = image.mirrored(True, False)
    item = QGraphicsPixmapItem(QPixmap.fromImage(image))
    scale = 25.4 / max(template.dpi, 1)
    item.setTransform(QTransform.fromScale(scale, scale))
    item.setPos(QPointF(template.dx / 10, -template.dy / 10))
    item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
    item.setZValue(-10)
    return item


class SideNumber(QLabel):
    def __init__(self, number: int):
        super().__init__(str(number))
        self.setFixedSize(56, 56)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont(self.font())
        font.setPointSize(30)
        font.setBold(True)
        self.setFont(font)
        self.setStyleSheet("background: black; color: #1e6af9;")


class SidePage(QWidget):
    def __init__(self, number: int, template: Template):
        super().__init__()
        self.template = template
        layout = QGridLayout(self)
        buttons = QVBoxLayout()
        self.load = QPushButton("Загрузить изображение…")
        self.load.clicked.connect(self.choose)
        self.remove = QPushButton("Удалить изображение")
        self.remove.clicked.connect(self.clear)
        buttons.addWidget(self.load)
        buttons.addWidget(self.remove)
        layout.addLayout(buttons, 0, 0, 1, 3)
        layout.addWidget(SideNumber(number), 0, 3, Qt.AlignmentFlag.AlignRight)
        self.name = QLabel()
        self.name.setStyleSheet("color: #0000a0;")
        layout.addWidget(self.name, 1, 0, 1, 4)
        self.show_box = QCheckBox("Показывать изображение")
        self.show_box.setChecked(template.visible)
        layout.addWidget(self.show_box, 2, 0, 1, 4)
        self.dpi = self.spin(20, 2400, template.dpi)
        self.dx = self.spin(-3000, 3000, template.dx)
        self.dy = self.spin(-3000, 3000, template.dy)
        for row, (caption, box, unit) in enumerate(
            (
                ("Разрешение:", self.dpi, "[dpi]"),
                ("Смещение по X:", self.dx, "[1/10 мм]"),
                ("Смещение по Y:", self.dy, "[1/10 мм]"),
            ),
            3,
        ):
            layout.addWidget(QLabel(caption), row, 0)
            layout.addWidget(box, row, 1)
            layout.addWidget(QLabel(unit), row, 2)
        layout.addWidget(QLabel("Цвет:"), 6, 0)
        self.colour = QToolButton()
        self.colour.setFixedSize(40, 18)
        self.colour.clicked.connect(self.choose_colour)
        layout.addWidget(self.colour, 6, 1)
        layout.setRowStretch(7, 1)
        self.colour_value = template.colour
        self.update_states()

    @staticmethod
    def spin(low, high, value):
        box = QSpinBox()
        box.setRange(low, high)
        box.setValue(value)
        return box

    def choose(self):
        start = str(Path(self.template.path).parent) if self.template.path else ""
        name, _ = QFileDialog.getOpenFileName(self, "Изображение для обрисовки", start, IMAGES)
        if name:
            self.template.path = name
            image = QImage(name)
            if not image.isNull() and image.dotsPerMeterX() > 0:
                self.dpi.setValue(round(image.dotsPerMeterX() * 0.0254))
            self.show_box.setChecked(True)
            self.update_states()

    def clear(self):
        self.template.path = ""
        self.update_states()

    def choose_colour(self):
        colour = QColorDialog.getColor(QColor(self.colour_value), self, "Цвет изображения")
        if colour.isValid():
            self.colour_value = colour.name()
            self.update_states()

    def update_states(self):
        has = bool(self.template.path)
        self.name.setText(Path(self.template.path).name if has else "Изображение не загружено")
        for widget in (self.remove, self.show_box, self.dpi, self.dx, self.dy, self.colour):
            widget.setEnabled(has)
        self.colour.setStyleSheet(
            f"QToolButton {{ background: {self.colour_value}; border: 1px solid #404040; }}"
        )

    def value(self) -> Template:
        return Template(
            path=self.template.path,
            dpi=self.dpi.value(),
            dx=self.dx.value(),
            dy=self.dy.value(),
            visible=self.show_box.isChecked(),
            colour=self.colour_value,
        )


class TemplateDialog(QDialog):
    def __init__(self, parent, templates: dict[int, Template]):
        super().__init__(parent)
        self.setWindowTitle("Подложка-шаблон")
        layout = QVBoxLayout(self)
        note = QLabel("Загружает изображение (скан платы) в фон, чтобы обрисовать его.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #0000a0;")
        layout.addWidget(note)
        tabs = QTabWidget()
        self.pages = {}
        for side, caption in ((1, "Сторона 1 (верх)"), (2, "Сторона 2 (низ)")):
            page = SidePage(side, templates.get(side, Template()))
            tabs.addTab(page, caption)
            self.pages[side] = page
        layout.addWidget(tabs)
        line = QHBoxLayout()
        line.addStretch()
        ok = QPushButton("ОК")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        line.addWidget(ok)
        layout.addLayout(line)

    def templates(self) -> dict[int, Template]:
        return {side: page.value() for side, page in self.pages.items()}
