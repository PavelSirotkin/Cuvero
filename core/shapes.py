"""New drawn objects: circles and arcs, rectangles, polygons and the special forms.

Outlines become closed tracks and filled shapes become polygons, as the original makes them.
"""

from collections.abc import Sequence
from dataclasses import replace
from math import atan2, cos, degrees, hypot, pi, radians, sin

from .model import CIRCLE, LINE, POLYGON, SMD, THT, Board, Element, Point
from .objects import _defaults, new_track
from .properties import centre_of
from .texts import new_text, with_text

HATCH_DEFAULT = 1000  # polygons drawn by the original keep 0.5 mm hatching here (1/2000 mm)


def new_circle(
    board: Board,
    layer: int,
    x: float,
    y: float,
    diameter: float,
    line_width: float,
    start: float = 0.0,
    stop: float = 0.0,
    filled: bool = False,
) -> Element:
    """A circle, or an arc from start to stop degrees counter-clockwise (equal: full circle)."""
    record, values = _defaults(board, CIRCLE, layer)
    values.pop("start", None)
    radius = diameter / 2
    return Element(
        CIRCLE,
        x=x,
        y=y,
        outer=radius + line_width / 2,
        inner=max(radius - line_width / 2, 0.0),
        width=(round(stop * 1000) % 360_000) / 10_000,
        start=round(start * 1000) % 360_000,
        layer=layer,
        filled=filled,
        record=record,
        **values,
    )


def new_polygon(board: Board, layer: int, points: Sequence[Point], line_width: float) -> Element:
    """A filled polygon with the given outline (the closing point is added)."""
    record, values = _defaults(board, POLYGON, layer)
    values.pop("start", None)
    ring = list(points)
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return Element(
        POLYGON,
        width=line_width,
        layer=layer,
        mirror_y=True,
        rotation=HATCH_DEFAULT,
        points=ring,
        record=record,
        **values,
    )


def closed_track(board: Board, layer: int, points: Sequence[Point], width: float) -> Element:
    ring = list(points)
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return new_track(board, layer, ring, width)


def rectangle_points(a: Point, b: Point) -> list[Point]:
    (x0, y0), (x1, y1) = a, b
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def new_rectangle(
    board: Board, layer: int, a: Point, b: Point, width: float, filled: bool
) -> Element:
    points = rectangle_points(a, b)
    if filled:
        return new_polygon(board, layer, points, width)
    return closed_track(board, layer, points, width)


def regular_polygon(
    cx: float, cy: float, radius: float, corners: int, offset: float = 0.0
) -> list[Point]:
    """Corners of a regular polygon; offset turns it counter-clockwise, in degrees."""
    corners = max(corners, 3)
    return [
        (
            round(cx + radius * cos(radians(offset) + 2 * pi * k / corners), 6),
            round(cy + radius * sin(radians(offset) + 2 * pi * k / corners), 6),
        )
        for k in range(corners)
    ]


def new_regular_polygon(
    board: Board,
    layer: int,
    cx: float,
    cy: float,
    radius: float,
    corners: int,
    offset: float,
    width: float,
    filled: bool,
) -> Element:
    points = regular_polygon(cx, cy, radius, corners, offset)
    if filled:
        return new_polygon(board, layer, points, width)
    return closed_track(board, layer, points, width)


def new_rays(
    board: Board,
    layer: int,
    cx: float,
    cy: float,
    radius: float,
    count: int,
    offset: float,
    width: float,
) -> list[Element]:
    """Tracks from the centre to the corners of a regular polygon."""
    return [
        new_track(board, layer, [(cx, cy), corner], width)
        for corner in regular_polygon(cx, cy, radius, count, offset)
    ]


def spiral_points(
    cx: float, cy: float, start_radius: float, pitch: float, turns: float, square: bool
) -> list[Point]:
    """A spiral growing by pitch per turn, round or square, as one track."""
    if square:
        points = [(cx + start_radius, cy)]
        radius = start_radius
        for side in range(max(round(turns * 4), 1)):
            # Each side grows by a quarter of the pitch, so a turn adds the whole pitch.
            direction = side % 4
            radius += pitch / 4
            x, y = points[-1]
            if direction == 0:
                y = cy + radius
            elif direction == 1:
                x = cx - radius
            elif direction == 2:
                y = cy - radius
            else:
                x = cx + radius
            points.append((round(x, 6), round(y, 6)))
        return points
    steps = max(round(turns * 36), 2)
    return [
        (
            round(cx + (start_radius + pitch * k / 36) * cos(2 * pi * k / 36), 6),
            round(cy + (start_radius + pitch * k / 36) * sin(2 * pi * k / 36), 6),
        )
        for k in range(steps + 1)
    ]


def spiral_diameter(start_radius: float, pitch: float, turns: float, width: float) -> float:
    return 2 * (start_radius + pitch * turns) + width


def new_spiral(
    board: Board,
    layer: int,
    cx: float,
    cy: float,
    start_radius: float,
    pitch: float,
    turns: float,
    width: float,
    square: bool,
) -> Element:
    return new_track(board, layer, spiral_points(cx, cy, start_radius, pitch, turns, square), width)


# --- track bends ---------------------------------------------------------------------------

FREE, BEND_45, BEND_90 = "free", "45", "90"
BEND_MODES = (BEND_45, BEND_90, FREE)


def bend(a: Point, b: Point, mode: str, flip: bool = False) -> list[Point]:
    """Points from a to b with the corner the bend mode asks for (b is the last point)."""
    (x0, y0), (x1, y1) = a, b
    dx, dy = x1 - x0, y1 - y0
    if mode == FREE or dx == 0 or dy == 0:
        return [b]
    if mode == BEND_90:
        corner = (x1, y0) if not flip else (x0, y1)
        return [corner, b]
    # 45 degrees: a straight part along an axis, then a diagonal (or the other way round).
    d = min(abs(dx), abs(dy))
    sx, sy = (1 if dx > 0 else -1), (1 if dy > 0 else -1)
    if abs(dx) > abs(dy):
        corner = (x1 - sx * d, y0) if not flip else (x0 + sx * d, y1)
    else:
        corner = (x0, y1 - sy * d) if not flip else (x1, y0 + sy * d)
    if corner in (a, b):
        return [b]
    return [(round(corner[0], 6), round(corner[1], 6)), b]


# --- snapping and rubber banding -------------------------------------------------------------


def snap_points(board: Board, skip: Sequence[int] = ()) -> list[Point]:
    """Pad centres and track nodes that drawing snaps to."""
    skipped = set(skip)
    result: list[Point] = []
    for i, obj in enumerate(board.elements):
        if i in skipped:
            continue
        if obj.kind in (THT, SMD):
            result.append(centre_of(obj))
        elif obj.kind == LINE:
            result.extend(obj.points)
    return result


def nearest(points: Sequence[Point], x: float, y: float, reach: float) -> Point | None:
    best, best_distance = None, reach
    for px, py in points:
        distance = hypot(px - x, py - y)
        if distance <= best_distance:
            best, best_distance = (px, py), distance
    return best


def rubber_band(
    board: Board, moved: dict[int, Element], tolerance: float = 1e-3
) -> dict[int, Element]:
    """Tracks whose ends sat on moved pads, with those ends following the pads.

    Returns the changed tracks by index (tracks that move themselves are left alone).
    """
    shifts = []
    for index, obj in moved.items():
        old = board.elements[index]
        if old.kind in (THT, SMD):
            (ox, oy), (nx, ny) = centre_of(old), centre_of(obj)
            if (ox, oy) != (nx, ny):
                shifts.append((ox, oy, nx - ox, ny - oy))
    if not shifts:
        return {}
    result: dict[int, Element] = {}
    for index, obj in enumerate(board.elements):
        if obj.kind != LINE or index in moved or len(obj.points) < 2:
            continue
        points = list(obj.points)
        changed = False
        for end in (0, len(points) - 1):
            x, y = points[end]
            for ox, oy, dx, dy in shifts:
                if hypot(x - ox, y - oy) <= tolerance:
                    points[end] = (round(x + dx, 6), round(y + dy, 6))
                    changed = True
                    break
        if changed:
            result[index] = replace(obj, points=points)
    return result


def angle_of(a: Point, b: Point) -> float:
    return degrees(atan2(b[1] - a[1], b[0] - a[0])) % 360


FRAME_MARGIN = 5.0  # mm between the outer and inner border of a drawing frame
FRAME_LINE = 0.3
FRAME_TEXT = 2.5


def _label(index: int, letters: bool) -> str:
    if not letters:
        return str(index + 1)
    return chr(ord("A") + index) if index < 26 else str(index + 1)


def new_frame(
    board: Board,
    layer: int,
    x: float,
    y: float,
    width: float,
    height: float,
    columns: int,
    rows: int,
    column_sides: int = 0,
    row_sides: int = 0,
    column_letters: bool = True,
    row_letters: bool = False,
) -> list[Element]:
    """A drawing frame from (x, y): outer and inner border, column and row marks with labels.

    *_sides: 0 both sides, 1 top (left) only, 2 bottom (right) only, 3 none.
    """
    m = FRAME_MARGIN
    line = FRAME_LINE
    result = [
        closed_track(board, layer, rectangle_points((x, y), (x + width, y + height)), line),
        closed_track(
            board, layer, rectangle_points((x + m, y + m), (x + width - m, y + height - m)), line
        ),
    ]
    inner_w, inner_h = width - 2 * m, height - 2 * m
    text_h = min(FRAME_TEXT, m * 0.6)

    def label(text: str, cx: float, cy: float) -> Element:
        obj = new_text(board, layer, 0, 0, text, text_h)
        xs = [px for child in obj.children for px, _ in child.points]
        ys = [py for child in obj.children for _, py in child.points]
        dx = cx - (min(xs) + max(xs)) / 2
        dy = cy - (min(ys) + max(ys)) / 2
        return with_text(replace(obj, x=dx, y=dy))

    top, bottom = column_sides in (0, 1), column_sides in (0, 2)
    for k in range(columns):
        left = x + m + inner_w * k / columns
        if k:
            if top:
                result.append(
                    new_track(board, layer, [(left, y + height), (left, y + height - m)], line)
                )
            if bottom:
                result.append(new_track(board, layer, [(left, y), (left, y + m)], line))
        centre = left + inner_w / columns / 2
        if top:
            result.append(label(_label(k, column_letters), centre, y + height - m / 2))
        if bottom:
            result.append(label(_label(k, column_letters), centre, y + m / 2))
    left_side, right_side = row_sides in (0, 1), row_sides in (0, 2)
    for k in range(rows):
        upper = y + height - m - inner_h * k / rows
        if k:
            if left_side:
                result.append(new_track(board, layer, [(x, upper), (x + m, upper)], line))
            if right_side:
                result.append(
                    new_track(board, layer, [(x + width - m, upper), (x + width, upper)], line)
                )
        centre = upper - inner_h / rows / 2
        if left_side:
            result.append(label(_label(k, row_letters), x + m / 2, centre))
        if right_side:
            result.append(label(_label(k, row_letters), x + width - m / 2, centre))
    return result
