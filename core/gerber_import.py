"""Importing Gerber layers and Excellon drill files as board objects.

Flashes that sit on a drill hole become through-hole pads; other flashes become SMD pads,
filled circles or polygons; draws become tracks; regions become polygons. Cleared (LPC)
parts cannot be expressed as objects and are counted as skipped.
"""

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from math import cos, hypot, pi, radians, sin

from .gerber_read import GerberFile, Primitive
from .model import Board, Element, Point
from .objects import new_pad, new_smd, new_track
from .shapes import new_circle, new_polygon

Hole = tuple[float, float, float]  # x, y, diameter in mm (file coordinates)
COPPER = (1, 3, 5, 6)
SAME_PLACE = 0.01


class ExcellonError(ValueError):
    pass


def parse_excellon(
    text: str,
    inch: bool | None = None,
    integer: int = 3,
    decimals: int = 3,
    suppress: str | None = None,
) -> list[Hole]:
    """Holes of an Excellon file. Units come from the header unless given; the number
    format (digits before and after the point) is used for numbers without a point, and
    suppress tells which zeros are left out: "none", "leading", "trailing" or None (header).
    """
    tools: dict[int, float] = {}
    holes: list[Hole] = []
    unit_inch = inch
    tool: float | None = None
    leading = True  # leading zeros present (LZ) -> pad on the right is missing
    x = y = 0.0

    def number(value: str) -> float:
        negative = value.startswith("-")
        digits = value.lstrip("+-")
        mode = suppress or ("trailing" if leading else "leading")
        if "." in digits:
            result = float(digits)
        elif mode != "leading":
            result = int(digits.ljust(integer + decimals, "0")) / 10**decimals
        else:
            result = int(digits) / 10**decimals
        result = -result if negative else result
        return result * 25.4 if unit_inch else result

    for raw in text.replace("\r", "").split("\n"):
        line = raw.split(";", 1)[0].strip().upper()
        if not line:
            continue
        if line.startswith(("INCH", "M72")):
            if inch is None:
                unit_inch = True
            leading = "TZ" not in line
            continue
        if line.startswith(("METRIC", "M71")):
            if inch is None:
                unit_inch = False
            leading = "TZ" not in line
            continue
        definition = re.fullmatch(r"T(\d+)(?:F\d+|S\d+)*C([\d.]+).*", line)
        if definition:
            size = float(definition.group(2))
            tools[int(definition.group(1))] = size * 25.4 if unit_inch else size
            continue
        selection = re.fullmatch(r"T(\d+)", line)
        if selection:
            tool = tools.get(int(selection.group(1)))
            continue
        coordinates = dict(re.findall(r"([XY])([+-]?[\d.]+)", line))
        if coordinates and (line.startswith(("X", "Y"))):
            if "X" in coordinates:
                x = number(coordinates["X"])
            if "Y" in coordinates:
                y = number(coordinates["Y"])
            if tool is None:
                raise ExcellonError("Координаты отверстия до выбора сверла")
            holes.append((x, y, tool))
    return holes


@dataclass
class ImportResult:
    elements: list[Element] = field(default_factory=list)
    skipped: int = 0  # cleared parts and shapes that have no object equivalent
    holes_used: int = 0
    plane: bool = False  # the layer starts with a ground plane: switch on its autofill


def _hole_at(holes: Sequence[Hole], x: float, y: float) -> Hole | None:
    for hole in holes:
        if hypot(hole[0] - x, hole[1] - y) <= SAME_PLACE:
            return hole
    return None


def _join(paths: list[tuple[float, list[Point]]]) -> list[tuple[float, list[Point]]]:
    """Join draws of equal width that continue each other into longer tracks."""
    result: list[tuple[float, list[Point]]] = []
    for width, points in paths:
        if result:
            last_width, last = result[-1]
            if (
                last_width == width
                and hypot(last[-1][0] - points[0][0], last[-1][1] - points[0][1]) < 1e-6
            ):
                last.extend(points[1:])
                continue
        result.append((width, list(points)))
    return result


def import_layer(
    board: Board,
    gerber: GerberFile,
    layer: int,
    holes: Sequence[Hole],
    offset: Point,
    pads_done: set[tuple[float, float]],
    join_tracks: bool = True,
) -> ImportResult:
    """Objects for one Gerber layer; offset is added to every Gerber coordinate."""
    dx, dy = offset
    result = ImportResult()
    draws: list[tuple[float, list[Point]]] = []
    primitives = list(gerber.primitives)
    # A dark area followed by cleared parts is how ground planes are written (also by the
    # original program): the board's own autofill recreates it with fresh clearances.
    first_clear = next((i for i, p in enumerate(primitives) if not p.dark), None)
    if first_clear and layer in COPPER and primitives[0].kind == "region":
        result.plane = True
        primitives = primitives[1:first_clear] + [p for p in primitives[first_clear:] if p.dark]
        result.skipped = 0

    def place(p: Point) -> Point:
        return round(p[0] + dx, 6), round(p[1] + dy, 6)

    for item in primitives:
        if not item.dark:
            result.skipped += 1
            continue
        if item.kind == "region":
            result.elements.append(new_polygon(board, layer, [place(p) for p in item.points], 0.0))
        elif item.kind == "draw" and item.aperture is not None:
            width = item.aperture.params[0] if item.aperture.params else 0.1
            draws.append((width, [place(p) for p in item.points]))
        elif item.kind == "flash" and item.aperture is not None:
            _flash(board, item, layer, holes, place, pads_done, result)
    for width, points in _join(draws) if join_tracks else draws:
        result.elements.append(new_track(board, layer, points, width))
    return result


def _flash(
    board: Board,
    item: Primitive,
    layer: int,
    holes: Sequence[Hole],
    place: Callable[[Point], Point],
    pads_done: set[tuple[float, float]],
    result: ImportResult,
) -> None:
    assert item.aperture is not None
    shape, params = item.aperture.shape, item.aperture.params
    x, y = place(item.points[0])
    hole = _hole_at(holes, x, y) if layer in COPPER else None
    if hole is not None:
        # One pad per hole, also when the hole sits a little off the flash.
        key = (round(hole[0], 3), round(hole[1], 3))
        if key in pads_done:
            return  # the same pad on the other copper side
        pads_done.add(key)
        result.holes_used += 1
        drill = hole[2]
        if shape == "C":
            result.elements.append(new_pad(board, layer, x, y, params[0], drill, 1))
        elif shape in ("R", "O") and len(params) >= 2:
            w, h = params[0], params[1]
            if abs(w - h) < 1e-6:
                result.elements.append(
                    new_pad(board, layer, x, y, w, drill, 3 if shape == "R" else 1)
                )
            else:
                pad_shape = (6 if shape == "R" else 4) if w > h else (9 if shape == "R" else 7)
                pad = new_pad(board, layer, x, y, min(w, h), drill, pad_shape)
                result.elements.append(pad)
        else:
            size = params[0] if params else drill * 2
            result.elements.append(
                new_pad(board, layer, x, y, size, drill, 2 if shape == "P" else 1)
            )
        return
    if shape == "R" and len(params) >= 2:
        result.elements.append(new_smd(board, layer, x, y, params[0], params[1]))
    elif shape == "C" and params:
        result.elements.append(
            new_circle(board, layer, x, y, params[0] / 2, params[0] / 2, filled=True)
        )
    elif item.aperture.macro or shape in ("O", "P"):
        outline = _outline(item)
        if outline:
            result.elements.append(
                new_polygon(board, layer, [(x + px, y + py) for px, py in outline], 0.0)
            )
        else:
            result.skipped += 1
    else:
        result.skipped += 1


def _outline(item: Primitive) -> list[Point]:
    """Outline around the flash centre for apertures that have no object equivalent."""
    assert item.aperture is not None
    aperture = item.aperture
    p = aperture.params
    if aperture.shape == "O" and len(p) >= 2:
        w, h = p[0], p[1]
        r = min(w, h) / 2
        ax, ay = w / 2 - r, h / 2 - r
        points: list[Point] = []
        for cx, cy, start in ((ax, ay, 0), (-ax, ay, 90), (-ax, -ay, 180), (ax, -ay, 270)):
            points += [
                (
                    cx + r * cos(radians(start + 90 * k / 8)),
                    cy + r * sin(radians(start + 90 * k / 8)),
                )
                for k in range(9)
            ]
        return points
    if aperture.shape == "P" and len(p) >= 2:
        n = int(p[1])
        rotation = radians(p[2]) if len(p) > 2 else 0.0
        return [
            (p[0] / 2 * cos(rotation + 2 * pi * k / n), p[0] / 2 * sin(rotation + 2 * pi * k / n))
            for k in range(n)
        ]
    dark = [outline for exposure, outline in aperture.macro if exposure]
    return dark[0] if len(dark) == 1 else []


def bare_holes(
    board: Board, holes: Iterable[Hole], used: set[tuple[float, float]]
) -> list[Element]:
    """Holes without a pad: unplated pads exactly as large as the hole."""
    result = []
    for x, y, d in holes:
        key = (round(x, 3), round(y, 3))
        if key in used:
            continue
        used.add(key)
        result.append(replace(new_pad(board, 1, x, y, d, d, 1), plated=False))
    return result


def bounds_of(
    gerbers: Iterable[GerberFile], holes: Iterable[Hole]
) -> tuple[float, float, float, float]:
    """Left, bottom, right, top of everything in the files (Gerber coordinates)."""
    xs: list[float] = []
    ys: list[float] = []
    for gerber in gerbers:
        for item in gerber.primitives:
            size = 0.0
            if item.aperture is not None and item.aperture.params:
                size = max(item.aperture.params[:2]) / 2
            for px, py in item.points:
                xs += [px - size, px + size]
                ys += [py - size, py + size]
    for x, y, d in holes:
        xs += [x - d / 2, x + d / 2]
        ys += [y - d / 2, y + d / 2]
    if not xs:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs), min(ys), max(xs), max(ys)


def detect_excellon(text: str) -> tuple[bool, int, int, str]:
    """Guess units, digits and zero suppression of an Excellon file from its contents."""
    upper = text.upper()
    inch = "INCH" in upper or "M72" in upper
    suppress = "leading" if ",TZ" in upper else "trailing" if ",LZ" in upper else "none"
    integer, decimals = (2, 4) if inch else (3, 3)
    match = re.search(r"FORMAT\s*:?\s*(\d)\.(\d)", upper)
    if match:
        integer, decimals = int(match.group(1)), int(match.group(2))
    return inch, integer, decimals, suppress
