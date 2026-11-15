"""Colours, layer names, tool list, grid and size presets."""

from PySide6.QtGui import QColor

import core
from version import VERSION

APP_NAME = "Cuvero"
APP_TITLE = f"{APP_NAME} {VERSION}"  # the name with the version, as in the title
BACKGROUND = QColor("#000000")
LAYERS = {
    3: ("C2", "#00ba00"),
    6: ("I2", "#eeb662"),
    5: ("I1", "#c27c14"),
    1: ("C1", "#1e6af9"),
    4: ("S2", "#e1d704"),
    2: ("S1", "#ff0000"),
    7: ("O", "#ffffff"),
    0: ("Отв.", "#000000"),
}
# Colours measured on the original program's screen: through-hole pads on both copper
# sides are drawn in their own colour, ground planes at 60 % of their layer's colour.
THROUGH = 8
THROUGH_COLOR = QColor("#51e3fd")
PLANE_SHADE = 0.6
GRID_COLOR = QColor("#2d2d2d")
HOLE_COLOR = QColor("#000000")  # drill holes: background, white or black (settings)
# Runtime options from the settings dialog (ui/options.py fills it at start).
OPTIONS: dict = {
    "darken_planes": True,
    "all_planes": True,
    "wires_in_test": False,
    "blink_test": True,
    "readable_labels": True,
    "optimize_nodes": True,
    "cam_origin": True,
    "copper_um": 35.0,
    "rise": 20.0,
    "undo_limit": 50,
}
LAYER_HINTS = {
    1: "C1 — медь, верхняя сторона",
    2: "S1 — маркировка, верхняя сторона",
    3: "C2 — медь, нижняя сторона",
    4: "S2 — маркировка, нижняя сторона",
    5: "I1 — внутренний слой меди 1",
    6: "I2 — внутренний слой меди 2",
    7: "O — контур платы",
}
COPPER = (1, 3, 5, 6)
EDIT_MODES = {
    "edit": None,
    "track": (core.LINE, core.SEGMENT),
    "pad": (core.THT,),
    "smd": (core.SMD,),
    "circle": (core.CIRCLE,),
    "rect": (),
    "zone": (core.POLYGON,),
    "special": (),
    "text": (core.STROKE_TEXT,),
    "mask": None,
    "connect": (core.THT, core.SMD),
    "test": None,
    "autoroute": None,
}
TEST_COLOR = "#cc88cc"  # highlight of connected copper, as in the original's test mode
WIRE_COLOR = QColor("#d7d7d7")  # air wires
CREATE_MODES = ("track", "pad", "smd", "circle", "rect", "zone", "special", "text")
DRAFT_MODES = ("track", "zone", "circle", "rect")  # drawn with several clicks
# The pad shape menu in the order of the shape codes stored in the file.
PAD_SHAPES = (
    ("Круглая", 1),
    ("Восьмиугольная", 2),
    ("Квадратная", 3),
    None,
    ("Скруглённая, поперёк", 4),
    ("Восьмиугольная, поперёк", 5),
    ("Прямоугольная, поперёк", 6),
    None,
    ("Скруглённая, вдоль", 7),
    ("Восьмиугольная, вдоль", 8),
    ("Прямоугольная, вдоль", 9),
)
# (icon, caption, mode or None when not implemented yet, shortcut, status bar hint)
TOOLS = (
    ("edit", "Правка", "edit", "Esc", "Правка: выделение и перемещение объектов, узлы дорожек"),
    (
        "zoom",
        "Масштаб",
        "zoom",
        "Z",
        "Масштаб: колесо мыши меняет масштаб, перетаскивание двигает плату",
    ),
    (
        "track",
        "Дорожка",
        "track",
        "L",
        "Дорожка: щелчок ставит узел, правая кнопка или двойной щелчок завершает",
    ),
    (
        "pad",
        "Площадка",
        "pad",
        "P",
        "Площадка: щелчок по пустому месту ставит площадку, форма — по стрелке",
    ),
    ("smd", "SMD-площадка", "smd", "S", "SMD-площадка: щелчок по пустому месту ставит площадку"),
    (
        "circle",
        "Окружность",
        "circle",
        "C",
        "Окружность: щелчок — центр, второй щелчок — радиус; ширина линии как у дорожки",
    ),
    (
        "rect",
        "Прямоугольник",
        "rect",
        "R",
        "Прямоугольник: два щелчка по углам; контур или заливка — по стрелке",
    ),
    (
        "zone",
        "Полигон",
        "zone",
        "F",
        "Полигон: щелчки ставят углы, правая кнопка или двойной щелчок замыкает",
    ),
    (
        "special",
        "Спецформа",
        "special",
        "Q",
        "Спецформа: многоугольник, лучи, спираль или рамка — щелчок ставит фигуру",
    ),
    ("text", "Текст", "text", "T", "Текст: щелчок ставит текст, свойства — в диалоге"),
    (
        "mask",
        "Маска",
        "mask",
        "O",
        "Маска: плата накрыта маской; щелчок по объекту открывает или закрывает в ней окно",
    ),
    (
        "connect",
        "Связи",
        "connect",
        "N",
        "Связи: щёлкните две площадки, чтобы протянуть или убрать воздушную линию",
    ),
    (
        "autoroute",
        "Автотрассировка",
        "autoroute",
        "A",
        "Автотрассировка: щелчок по воздушной линии прокладывает дорожку на активном слое",
    ),
    (
        "test",
        "Проверка",
        "test",
        "K",
        "Проверка: щелчок по меди подсвечивает всё, что с ней электрически связано",
    ),
    ("measure", "Измерение", "measure", "M", "Измерение: укажите две точки"),
    (
        "photo",
        "Фотовид",
        "photo",
        "V",
        "Фотовид: плата такой, какой её изготовят; параметры — над платой",
    ),
)
GRID_STANDARD = (
    (0.0396875, "39,6875 мкм (1/64 шага)"),
    (0.079375, "79,375 мкм (1/32 шага)"),
    (0.15875, "0,15875 мм (1/16 шага)"),
    (0.3175, "0,3175 мм (1/8 шага)"),
    (0.635, "0,635 мм (1/4 шага)"),
    (1.27, "1,27 мм (1/2 шага)"),
    (2.54, "2,54 мм (шаг)"),
    (5.08, "5,08 мм (2 шага)"),
)
GRID_METRIC = (0.01, 0.02, 0.025, 0.05, 0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 2.5)
# Default favourites, as shipped lists of common sizes in millimetres.
Size = float | tuple[float, ...]
FAVOURITES: dict[str, list[Size]] = {
    "track": [0.15, 0.2, 0.3, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4],
    "pad": [
        (0.8, 0.4),
        (1.0, 0.5),
        (1.4, 0.8),
        (1.4, 1.0),
        (1.6, 0.8),
        (1.6, 1.0),
        (2.0, 0.8),
        (2.0, 1.0),
        (2.4, 1.2),
        (3.0, 1.4),
    ],
    "smd": [
        (0.3, 0.3),
        (0.5, 0.6),
        (0.6, 0.9),
        (0.8, 0.9),
        (0.9, 1.6),
        (1.0, 1.2),
        (1.2, 1.7),
        (1.2, 2.7),
        (1.2, 3.2),
    ],
}
ROTATION_STEPS = (90.0, 45.0, 15.0, 5.0)
MACRO_MIME = "application/x-lay6-macro"
VALUE_STYLE = (
    "QDoubleSpinBox { background: #000000; color: #ffff00; border: 1px solid #606060;"
    " font-weight: bold; } QDoubleSpinBox:disabled { color: #808000; }"
)


def mm(value, digits=2):
    """Russian number format: decimal comma."""
    return f"{value:.{digits}f}".replace(".", ",")
