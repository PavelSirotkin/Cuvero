"""Stroke texts: building their strokes with our font, text settings and component labels.

The file keeps every text twice: as its characters and as ready line strokes (children).
The original program draws the strokes, so a text is only complete with fresh strokes.
Text fields: outer is the height, inner the stroke weight (0 thin, 1 normal, 2 bold),
width the letter spacing (0 narrow, 1 normal, 2 wide), all as small integers in 1/10000.
"""

from dataclasses import replace
from math import cos, radians, sin

from . import font
from .model import LINE, MM, STROKE_TEXT, Board, Element, Point

THIN, NORMAL, BOLD = 0, 1, 2
NARROW, WIDE = 0, 2
# Stroke width as a part of the text height, as measured in the original's files.
WEIGHTS = {THIN: 0.06, NORMAL: 1 / 9, BOLD: 1 / 6.3}
CAP_HEIGHT = 8 / 9  # the capitals' strokes span this part of the text height
SPACING_STEP = 0.135  # extra room per letter for "wide" (and less for "narrow"), by height
TIGHTEN = 3.0  # font units taken off between letters to match the original's text widths
HEIGHT_RANGE = (0.1, 50.0)
FREE_TEXT = 0  # shape code of a free text; 1 and 2 are component labels


def text_weight(obj: Element) -> int:
    return min(max(round(obj.inner * MM), THIN), BOLD)


def text_spacing(obj: Element) -> int:
    return min(max(round(obj.width * MM), NARROW), WIDE)


def stroke_width(height: float, weight: int) -> float:
    return round(height * WEIGHTS.get(weight, WEIGHTS[NORMAL]), 4)


def text_points(
    text: str,
    height: float,
    spacing: int = 1,
    rotation: float = 0,
    mirror_x: bool = False,
    mirror_y: bool = False,
) -> list[list[Point]]:
    """Strokes relative to the text origin (left end of the baseline), y upwards."""
    scale = height * CAP_HEIGHT / (font.BASE - font.CAP)
    extra = (spacing - 1) * SPACING_STEP * height / scale - TIGHTEN
    strokes, _ = font.layout(text, max(extra, -8.0))
    ink = [x for s in strokes for x, _ in s]
    left = min(ink, default=0.0)
    angle = radians(rotation)
    c, s_ = cos(angle), sin(angle)
    result = []
    for stroke in strokes:
        points = []
        for gx, gy in stroke:
            x, y = (gx - left) * scale, (font.BASE - gy) * scale
            if mirror_x:
                x = -x
            if mirror_y:
                y = -y
            # Text angles turn clockwise, as the original stores them.
            points.append((round(x * c + y * s_, 6), round(-x * s_ + y * c, 6)))
        result.append(points)
    return result


def empty_stroke(x: float, y: float, height: float) -> list[Point]:
    """The tiny rectangle the original stores as the only stroke of an empty text."""
    w, d = height * 0.0444, height * 0.0533
    return [(x, y + d), (x, y), (x - w, y), (x - w, y + d), (x, y + d), (x, y)]


def with_strokes(obj: Element) -> Element:
    """obj with its line strokes rebuilt from its characters and settings."""
    if obj.kind != STROKE_TEXT:
        return obj
    height = obj.outer
    width = stroke_width(height, text_weight(obj))
    template = obj.children[0] if obj.children else Element(LINE)
    if obj.text:
        strokes = [
            [(obj.x + x, obj.y + y) for x, y in stroke]
            for stroke in text_points(
                obj.text, height, text_spacing(obj), obj.rotation, obj.mirror_x, obj.mirror_y
            )
        ]
    else:
        strokes = [empty_stroke(obj.x, obj.y, height)]
    children = [
        replace(template, layer=obj.layer, width=width, points=points, x=0.0, y=0.0)
        for points in strokes
    ]
    return replace(obj, children=children)


def new_text(
    board: Board,
    layer: int,
    x: float,
    y: float,
    text: str,
    height: float = 2.0,
    weight: int = NORMAL,
    spacing: int = 1,
    rotation: int = 0,
    mirror_x: bool = False,
    mirror_y: bool = False,
) -> Element:
    templates = [
        obj for obj in board.elements if obj.kind == STROKE_TEXT and obj.shape == FREE_TEXT
    ]
    record = templates[-1].record if templates else b""
    if record:
        record = record[:28] + bytes(3) + record[31:]  # no component, not selected
    obj = Element(
        STROKE_TEXT,
        x=x,
        y=y,
        outer=height,
        inner=weight / MM,
        width=spacing / MM,
        layer=layer,
        filled=True,
        clearance=0.4,
        mirror_x=mirror_x,
        mirror_y=mirror_y,
        rotation=rotation % 360,
        text=text,
        record=record,
    )
    return with_strokes(obj)


def with_text(
    obj: Element,
    text: str | None = None,
    height: float | None = None,
    weight: int | None = None,
    spacing: int | None = None,
    rotation: int | None = None,
    mirror_x: bool | None = None,
    mirror_y: bool | None = None,
    layer: int | None = None,
) -> Element:
    """A text with some settings changed and its strokes rebuilt."""
    if obj.kind != STROKE_TEXT:
        return obj
    changes: dict[str, object] = {}
    if text is not None:
        changes["text"] = text
    if height is not None:
        low, high = HEIGHT_RANGE
        changes["outer"] = min(max(height, low), high)
    if weight is not None:
        changes["inner"] = weight / MM
    if spacing is not None:
        changes["width"] = spacing / MM
    if rotation is not None:
        changes["rotation"] = round(rotation) % 360
    if mirror_x is not None:
        changes["mirror_x"] = mirror_x
    if mirror_y is not None:
        changes["mirror_y"] = mirror_y
    if layer is not None:
        changes["layer"] = layer
    return with_strokes(replace(obj, **changes))  # type: ignore[arg-type]


def numbered(text: str, number: int) -> str:
    """Text with a running number appended, for automatic numbering of placed texts."""
    return f"{text}{number}"


def unsupported_characters(text: str) -> str:
    """Characters our font cannot draw (they come out as '?')."""
    return "".join(sorted({char for char in text if not font.supported(char)}))
