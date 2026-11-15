"""Stroke font for board texts: Hershey simplex Latin plus Cyrillic drawn in the same style.

Glyph coordinates follow the Hershey grid: x to the right, y downwards, capitals from
y = -12 to the baseline y = 9, small letters from y = -5, descenders down to y = 16.
"""

from collections.abc import Iterable

from .font_data import SIMPLEX

Stroke = list[tuple[float, float]]
Glyph = tuple[float, float, list[Stroke]]  # left bound, right bound, strokes

CAP, BASE, X_HEIGHT = -12, 9, -5


def _decode(data: str) -> Glyph:
    left, right = ord(data[0]) - 82, ord(data[1]) - 82
    strokes: list[Stroke] = [[]]
    for k in range(2, len(data) - 1, 2):
        if data[k : k + 2] == " R":
            strokes.append([])
        else:
            strokes[-1].append((ord(data[k]) - 82, ord(data[k + 1]) - 82))
    return left, right, [s for s in strokes if s]


GLYPHS: dict[str, Glyph] = {chr(32 + i): _decode(data) for i, data in enumerate(SIMPLEX)}


def _bowl(top: float, bottom: float, left: float, right: float) -> Stroke:
    """The rounded right-hand bowl used by Б, Ь, Ъ, Ы: from (left, top) to (left, bottom)."""
    h = bottom - top
    return [
        (left, top),
        (right - 5, top),
        (right - 2, top + h * 0.09),
        (right - 1, top + h * 0.18),
        (right, top + h * 0.36),
        (right, top + h * 0.64),
        (right - 1, top + h * 0.82),
        (right - 2, top + h * 0.91),
        (right - 5, bottom),
        (left, bottom),
    ]


def _shifted(strokes: Iterable[Stroke], dx: float = 0, sx: float = 1) -> list[Stroke]:
    return [[(x * sx + dx, y) for x, y in s] for s in strokes]


def _cyrillic_capitals() -> dict[str, Glyph]:
    g = GLYPHS
    o = g["O"][2][0]
    c = g["C"][2][0]
    caps: dict[str, Glyph] = {
        "А": g["A"],
        "В": g["B"],
        "Е": g["E"],
        "З": g["3"],
        "К": g["K"],
        "М": g["M"],
        "Н": g["H"],
        "О": g["O"],
        "Р": g["P"],
        "С": g["C"],
        "Т": g["T"],
        "Х": g["X"],
        "Б": (-11, 10, [[(7, -12), (-7, -12)], _bowl(-2, 9, -7, 7), [(-7, -12), (-7, 9)]]),
        "Г": (-10, 8, [[(-6, 9), (-6, -12), (7, -12)]]),
        "Д": (
            -11,
            11,
            [[(-9, 13), (-9, 9), (9, 9), (9, 13)], [(-6, 9), (-4, 2), (-3, -12), (6, -12), (6, 9)]],
        ),
        "Ж": (
            -12,
            12,
            [[(0, -12), (0, 9)], [(-8, -12), (0, -2), (8, -12)], [(-8, 9), (0, -2), (8, 9)]],
        ),
        "И": (-11, 11, [[(-7, -12), (-7, 9), (7, -12), (7, 9)]]),
        "Л": (-11, 11, [[(-8, 9), (-6, 8), (-5, 5), (-3, -12), (7, -12), (7, 9)]]),
        "П": (-11, 11, [[(-7, 9), (-7, -12), (7, -12), (7, 9)]]),
        "У": (-9, 9, [[(-8, -12), (0, 4)], [(8, -12), (-1, 6), (-3, 8), (-5, 9), (-7, 9)]]),
        "Ф": (
            -12,
            12,
            [
                [(0, -12), (0, 9)],
                [
                    (0, -8),
                    (-4, -8),
                    (-7, -6),
                    (-8, -3),
                    (-7, 0),
                    (-4, 2),
                    (4, 2),
                    (7, 0),
                    (8, -3),
                    (7, -6),
                    (4, -8),
                    (0, -8),
                ],
            ],
        ),
        "Ц": (-11, 12, [[(-7, -12), (-7, 9), (9, 9), (9, 13)], [(7, -12), (7, 9)]]),
        "Ч": (-10, 10, [[(-6, -12), (-6, -5), (-5, -3), (-3, -2), (6, -2)], [(6, -12), (6, 9)]]),
        "Ш": (-13, 13, [[(-9, -12), (-9, 9), (9, 9), (9, -12)], [(0, -12), (0, 9)]]),
        "Щ": (
            -13,
            14,
            [[(-9, -12), (-9, 9), (11, 9), (11, 13)], [(9, -12), (9, 9)], [(0, -12), (0, 9)]],
        ),
        "Ъ": (-12, 10, [[(-10, -12), (-6, -12), (-6, 9)], _bowl(-2, 9, -6, 7)]),
        "Ы": (-12, 13, [[(-8, -12), (-8, 9)], _bowl(-2, 9, -8, 4), [(9, -12), (9, 9)]]),
        "Ь": (-11, 10, [[(-7, -12), (-7, 9)], _bowl(-2, 9, -7, 7)]),
        "Э": (-11, 10, [[(-x, y) for x, y in c], [(-3, -2), (7, -2)]]),
        "Ю": (
            -13,
            13,
            [[(-10, -12), (-10, 9)], [(-10, -2), (-5, -2)], *_shifted([o], dx=4, sx=0.6)],
        ),
        "Я": (
            -10,
            11,
            [
                [
                    (7, 9),
                    (7, -12),
                    (-2, -12),
                    (-5, -11),
                    (-6, -10),
                    (-7, -8),
                    (-7, -5),
                    (-6, -3),
                    (-5, -2),
                    (-2, -1),
                    (7, -1),
                ],
                [(0, -1), (-7, 9)],
            ],
        ),
    }
    breve: Stroke = [(-4, -16), (-2, -14), (2, -14), (4, -16)]
    caps["Й"] = (-11, 11, caps["И"][2] + [breve])
    caps["Ё"] = (-10, 9, g["E"][2] + [[(-3, -15), (-2, -15)], [(3, -15), (4, -15)]])
    return caps


def _small(glyph: Glyph) -> Glyph:
    """A capital squeezed to the height of small letters, for Cyrillic small letters."""
    left, right, strokes = glyph
    k = (BASE - X_HEIGHT) / (BASE - CAP)
    sx = 0.8
    return (
        left * sx,
        right * sx,
        [[(x * sx, BASE - (BASE - y) * k) for x, y in s] for s in strokes],
    )


def _cyrillic() -> dict[str, Glyph]:
    caps = _cyrillic_capitals()
    glyphs = dict(caps)
    latin_small = {"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x"}
    for capital in caps:
        small = capital.lower()
        glyphs[small] = (
            GLYPHS[latin_small[small]] if small in latin_small else _small(caps[capital])
        )
    e = GLYPHS["e"]
    glyphs["ё"] = (e[0], e[1], e[2] + [[(-3, -8), (-2, -8)], [(3, -8), (4, -8)]])
    glyphs["№"] = (
        -13,
        15,
        GLYPHS["N"][2]
        + [[(10, -5), (12, -4), (13, -2), (12, 0), (10, 1), (8, 0), (7, -2)]]
        + [[(7, -2), (8, -4), (10, -5)], [(7, 4), (13, 4)]],
    )
    return glyphs


GLYPHS.update(_cyrillic())
GLYPHS["°"] = (-5, 5, [[(0, -12), (-2, -11), (-2, -9), (0, -8), (2, -9), (2, -11), (0, -12)]])
GLYPHS["µ"] = (
    -10,
    10,
    [[(-5, -5), (-5, 16)], [(-5, 5), (-4, 8), (-2, 9), (1, 9), (3, 8), (6, 5)], [(6, -5), (6, 9)]],
)
GLYPHS["Ω"] = (
    -11,
    11,
    [
        [
            (-8, 9),
            (-4, 9),
            (-4, 7),
            (-6, 5),
            (-8, 1),
            (-8, -4),
            (-7, -8),
            (-5, -11),
            (-2, -12),
            (2, -12),
            (5, -11),
            (7, -8),
            (8, -4),
            (8, 1),
            (6, 5),
            (4, 7),
            (4, 9),
            (8, 9),
        ]
    ],
)
MISSING = "?"


def glyph(char: str) -> Glyph:
    return GLYPHS.get(char) or GLYPHS[MISSING]


def supported(char: str) -> bool:
    return char in GLYPHS


def layout(text: str, spacing: float = 0.0) -> tuple[list[Stroke], float]:
    """Strokes of a line of text in font units, starting at x = 0, and its advance.

    spacing is extra room between letters, in font units.
    """
    strokes: list[Stroke] = []
    pen = 0.0
    for i, char in enumerate(text):
        left, right, parts = glyph(char)
        strokes.extend([[(pen + x - left, y) for x, y in s] for s in parts])
        pen += right - left
        if i < len(text) - 1:
            pen += spacing
    return strokes, pen
