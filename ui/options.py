"""General settings, laid out like the original's: a list of pages on the left.

Values live in the user's INI file under "options/" and in style.OPTIONS while running;
colours are changed in place in the style module so every view picks them up.
"""

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import style
from .export_dialogs import ok_cancel
from .settings import read_bool, read_float, read_int, read_str

# (key, label, default) of the general options with a check box
GENERAL = (
    ("show_overview", "Показывать окно обзора платы", True),
    ("darken_planes", "Автозаливку показывать темнее", True),
    ("all_planes", "Автозаливку всех слоёв показывать одновременно", True),
    ("wires_in_test", "Учитывать воздушные линии в режиме «Проверка»", False),
    ("blink_test", "Мигающая подсветка в режиме «Проверка»", True),
    ("double_click_sizes", "Двойной щелчок берёт размеры объекта", True),
    ("limit_text", "Ограничить высоту текста (линия не тоньше 0,15 мм)", False),
    ("readable_labels", "Обозначение и номинал читаемы после поворота", True),
    ("optimize_nodes", "Автоматически убирать лишние узлы дорожек", True),
    ("cam_origin", "Начало координат в выводе (Gerber, Excellon, HPGL)", True),
)
# Options that already change something; the rest are shown greyed out, as placeholders.
WORKING = {"show_overview", "darken_planes", "wires_in_test", "cam_origin"}
HOLES = ("Цвет фона", "Белые", "Чёрные")
CROSSHAIRS = ("Нет", "Малое перекрестие", "Перекрестие на всё поле")
DEFAULT_COLORS = {
    "1": "#1e6af9",
    "2": "#ff0000",
    "3": "#00ba00",
    "4": "#e1d704",
    "5": "#c27c14",
    "6": "#eeb662",
    "7": "#ffffff",
    "background": "#000000",
    "grid": "#2d2d2d",
    "through": "#51e3fd",
    "wire": "#d7d7d7",
}
COLOR_NAMES = (
    ("background", "Фон"),
    ("grid", "Сетка"),
    ("1", "C1 (медь сверху)"),
    ("2", "S1 (маркировка сверху)"),
    ("3", "C2 (медь снизу)"),
    ("4", "S2 (маркировка снизу)"),
    ("5", "I1 (медь внутри 1)"),
    ("6", "I2 (медь внутри 2)"),
    ("7", "O (контур)"),
    ("through", "Сквозные площадки"),
    ("wire", "Воздушные линии"),
)
SCHEMES = ("Стандарт", "Своя 1", "Своя 2", "Своя 3")


def scheme_key(scheme: int, key: str) -> str:
    return f"options/colors{scheme}/{key}"


def apply_options(settings) -> None:
    """Load the options into style.OPTIONS and the colours into the style module."""
    options = style.OPTIONS
    for key, _label, default in GENERAL:
        options[key] = read_bool(settings, f"options/{key}", default)
    options["holes"] = read_int(settings, "options/holes", 0)
    options["crosshair"] = read_int(settings, "options/crosshair", 0)
    options["copper_um"] = read_float(settings, "options/copper_um", 35.0)
    options["rise"] = read_float(settings, "options/rise", 20.0)
    options["undo_limit"] = read_int(settings, "options/undo_limit", 50)
    scheme = read_int(settings, "options/scheme", 0)
    colors = {
        key: read_str(settings, scheme_key(scheme, key), default)
        for key, default in DEFAULT_COLORS.items()
    }
    for layer in (1, 2, 3, 4, 5, 6, 7):
        name = style.LAYERS[layer][0]
        style.LAYERS[layer] = (name, colors[str(layer)])
    style.BACKGROUND.setRgba(QColor(colors["background"]).rgba())
    style.GRID_COLOR.setRgba(QColor(colors["grid"]).rgba())
    style.THROUGH_COLOR.setRgba(QColor(colors["through"]).rgba())
    style.WIRE_COLOR.setRgba(QColor(colors["wire"]).rgba())
    hole = (colors["background"], "#ffffff", "#000000")[options["holes"]]
    style.HOLE_COLOR.setRgba(QColor(hole).rgba())


class ColorBox(QToolButton):
    def __init__(self, colour: str):
        super().__init__()
        self.setFixedSize(46, 18)
        self.set_colour(colour)
        self.clicked.connect(self.choose)

    def set_colour(self, colour: str):
        self.colour = colour
        self.setStyleSheet(f"QToolButton {{ background: {colour}; border: 1px solid #404040; }}")

    def choose(self):
        colour = QColorDialog.getColor(QColor(self.colour), self, "Цвет")
        if colour.isValid():
            self.set_colour(colour.name())


class OptionsDialog(QDialog):
    PAGES = (
        "Общие настройки",
        "Цвета",
        "Рабочие папки",
        "Папка макросов",
        "Глубина отмены",
        "Imax",
        "Клавиши сетки",
        "Перекрестие",
        "Автосохранение",
    )

    def __init__(self, parent, settings):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Общие настройки")
        layout = QVBoxLayout(self)
        body = QHBoxLayout()
        layout.addLayout(body, 1)
        self.list = QListWidget()
        self.list.addItems(self.PAGES)
        self.list.setFixedWidth(150)
        body.addWidget(self.list)
        right = QVBoxLayout()
        body.addLayout(right, 1)
        self.caption = QLabel()
        self.caption.setStyleSheet(
            "background: #505050; color: white; font-weight: bold; padding: 3px 6px;"
        )
        right.addWidget(self.caption)
        self.pages = QStackedWidget()
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        framed = QVBoxLayout(frame)
        framed.setContentsMargins(4, 4, 4, 4)
        framed.addWidget(self.pages)
        right.addWidget(frame, 1)
        for build in (
            self.general_page,
            self.colors_page,
            self.folders_page,
            self.macro_page,
            self.undo_page,
            self.imax_page,
            self.hotkeys_page,
            self.crosshair_page,
            self.autosave_page,
        ):
            self.pages.addWidget(build())
        self.list.currentRowChanged.connect(self.show_page)
        self.list.setCurrentRow(0)
        layout.addWidget(ok_cancel(self))
        self.resize(600, 380)

    def show_page(self, row: int):
        self.pages.setCurrentIndex(row)
        self.caption.setText(self.PAGES[row])

    # --- pages -----------------------------------------------------------------------

    def general_page(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        grid = QGridLayout()
        self.unit = QComboBox()
        self.unit.addItems(["мм", "mil (1/1000 дюйма)"])
        self.unit.setCurrentIndex(1 if read_bool(self.settings, "units/mil", False) else 0)
        self.holes = QComboBox()
        self.holes.addItems(HOLES)
        self.holes.setCurrentIndex(read_int(self.settings, "options/holes", 0))
        grid.addWidget(QLabel("Единицы:"), 0, 0)
        grid.addWidget(self.unit, 0, 1)
        grid.addWidget(QLabel("Отверстия:"), 0, 2)
        grid.addWidget(self.holes, 0, 3)
        box.addLayout(grid)
        box.addSpacing(8)
        self.general: dict[str, QCheckBox] = {}
        box.setSpacing(2)
        for key, label, default in GENERAL:
            if key == "cam_origin":
                top_left = QCheckBox("Начало координат слева вверху (а не слева внизу)")
                top_left.setEnabled(False)
                top_left.setToolTip("Пока не поддерживается: координаты считаются снизу вверх")
                box.addWidget(top_left)
            check = QCheckBox(label)
            check.setChecked(read_bool(self.settings, f"options/{key}", default))
            if key not in WORKING:
                check.setEnabled(False)
                check.setToolTip("Пока не поддерживается")
            box.addWidget(check)
            self.general[key] = check
        box.addStretch()
        return page

    def colors_page(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        line = QHBoxLayout()
        line.addWidget(QLabel("Цветовая схема:"))
        self.scheme = QComboBox()
        self.scheme.addItems(SCHEMES)
        self.scheme.setCurrentIndex(read_int(self.settings, "options/scheme", 0))
        self.scheme.currentIndexChanged.connect(self.load_scheme)
        line.addWidget(self.scheme)
        defaults = QPushButton("Стандартные цвета…")
        defaults.clicked.connect(self.default_colors)
        line.addWidget(defaults)
        line.addStretch()
        box.addLayout(line)
        grid = QGridLayout()
        self.colors: dict[str, ColorBox] = {}
        for row, (key, label) in enumerate(COLOR_NAMES):
            grid.addWidget(QLabel(label), row % 6, (row // 6) * 2)
            colour_box = ColorBox(DEFAULT_COLORS[key])
            grid.addWidget(colour_box, row % 6, (row // 6) * 2 + 1)
            self.colors[key] = colour_box
        box.addLayout(grid)
        box.addStretch()
        self.load_scheme()
        return page

    def load_scheme(self, *_args):
        scheme = self.scheme.currentIndex()
        for key, colour_box in self.colors.items():
            colour_box.set_colour(
                read_str(self.settings, scheme_key(scheme, key), DEFAULT_COLORS[key])
            )

    def default_colors(self):
        for key, colour_box in self.colors.items():
            colour_box.set_colour(DEFAULT_COLORS[key])

    def folders_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.folders: dict[str, QLineEdit] = {}
        for key, label in (("projects", "Проекты:"), ("export", "Вывод (Gerber и другие):")):
            self.folders[key] = self.folder_row(form, label, f"folders/{key}")
        return page

    def folder_row(self, form, label, key) -> QLineEdit:
        edit = QLineEdit(read_str(self.settings, key, ""))
        browse = QPushButton("…")
        browse.setFixedWidth(28)
        browse.clicked.connect(
            lambda: edit.setText(
                QFileDialog.getExistingDirectory(self, label, edit.text()) or edit.text()
            )
        )
        line = QHBoxLayout()
        line.addWidget(edit, 1)
        line.addWidget(browse)
        form.addRow(label, line)
        return edit

    def macro_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.macro_folder = self.folder_row(form, "Папка с макросами:", "macro/folder")
        return page

    def undo_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.undo_limit = QSpinBox()
        self.undo_limit.setRange(1, 200)
        self.undo_limit.setValue(read_int(self.settings, "options/undo_limit", 50))
        form.addRow("Количество отменяемых действий:", self.undo_limit)
        note = QLabel(
            "Если на больших платах программа замедляется, это число можно уменьшить. "
            "Новое значение действует с открытия следующего проекта."
        )
        note.setWordWrap(True)
        form.addRow(note)
        return page

    def imax_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.copper = QDoubleSpinBox()
        self.copper.setRange(5, 400)
        self.copper.setSuffix(" мкм")
        self.copper.setValue(read_float(self.settings, "options/copper_um", 35.0))
        self.rise = QDoubleSpinBox()
        self.rise.setRange(1, 100)
        self.rise.setSuffix(" °C")
        self.rise.setValue(read_float(self.settings, "options/rise", 20.0))
        form.addRow("Толщина меди:", self.copper)
        form.addRow("Допустимый нагрев:", self.rise)
        note = QLabel(
            "Для допустимого тока дорожки на панели свойств. При 35 мкм и 20 °C значения "
            "совпадают с оригиналом; остальное пересчитывается по формуле IPC-2221."
        )
        note.setWordWrap(True)
        form.addRow(note)
        return page

    def hotkeys_page(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.addWidget(QLabel("Клавиши"), 0, 0)
        grid.addWidget(QLabel("Шаг сетки, мм"), 0, 1)
        self.hotkeys: list[QDoubleSpinBox] = []
        defaults = (0.05, 0.1, 0.25, 0.5, 0.635, 1.0, 1.27, 2.54, 5.08)
        for k in range(9):
            grid.addWidget(QLabel(f"Ctrl+{k + 1}"), k + 1, 0)
            spin = QDoubleSpinBox()
            spin.setRange(0.001, 50)
            spin.setDecimals(4)
            spin.setValue(read_float(self.settings, f"options/hotkey{k + 1}", defaults[k]))
            grid.addWidget(spin, k + 1, 1)
            self.hotkeys.append(spin)
        grid.setRowStretch(10, 1)
        return page

    def crosshair_page(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        self.crosshair = QButtonGroup(page)
        for index, label in enumerate(CROSSHAIRS):
            radio = QRadioButton(label)
            self.crosshair.addButton(radio, index)
            box.addWidget(radio)
        chosen = self.crosshair.button(read_int(self.settings, "options/crosshair", 0))
        (chosen or self.crosshair.button(0)).setChecked(True)
        box.addStretch()
        return page

    def autosave_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.autosave = QSpinBox()
        self.autosave.setRange(0, 120)
        self.autosave.setSuffix(" мин")
        self.autosave.setSpecialValueText("выключено")
        enabled = read_bool(self.settings, "autosave/enabled", True)
        self.autosave.setValue(read_int(self.settings, "autosave/minutes", 5) if enabled else 0)
        form.addRow("Автосохранение каждые:", self.autosave)
        return page

    def remember(self):
        s = self.settings
        s.setValue("units/mil", self.unit.currentIndex() == 1)
        s.setValue("options/holes", self.holes.currentIndex())
        for key, check in self.general.items():
            s.setValue(f"options/{key}", check.isChecked())
        scheme = self.scheme.currentIndex()
        s.setValue("options/scheme", scheme)
        for key, colour_box in self.colors.items():
            s.setValue(scheme_key(scheme, key), colour_box.colour)
        for key, edit in self.folders.items():
            s.setValue(f"folders/{key}", edit.text())
        s.setValue("macro/folder", self.macro_folder.text())
        s.setValue("options/undo_limit", self.undo_limit.value())
        s.setValue("options/copper_um", self.copper.value())
        s.setValue("options/rise", self.rise.value())
        for k, spin in enumerate(self.hotkeys):
            s.setValue(f"options/hotkey{k + 1}", spin.value())
        s.setValue("options/crosshair", self.crosshair.checkedId())
        s.setValue("autosave/enabled", self.autosave.value() > 0)
        if self.autosave.value() > 0:
            s.setValue("autosave/minutes", self.autosave.value())
