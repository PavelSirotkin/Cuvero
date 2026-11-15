"""Footprint wizard (rows and rings of pads) and copies of objects in a grid or a circle."""

from collections.abc import Sequence
from dataclasses import dataclass
from math import cos, pi, radians, sin

from .editing import fresh_copies, next_group_id, with_group_ids
from .macros import bounds
from .model import Board, Element, Point
from .objects import new_pad, new_smd
from .transform import rotate_all

SIP, DIP, QUAD, CIRCLE_ROW, CIRCLE_TWO = range(5)
KINDS = ("Один ряд (SIP)", "Два ряда (DIP)", "Квадрат (QUAD)", "По окружности", "Две окружности")


@dataclass
class Footprint:
    kind: int = SIP
    horizontal: int = 8
    vertical: int = 1
    pitch: float = 2.54  # d: distance between neighbouring pads
    y: float = 2.54  # row distance (DIP), side distance (QUAD), inner diameter (two rings)
    x: float = 2.54  # side distance (QUAD), diameter (rings)
    smd: bool = False
    diameter: float = 1.6
    drill: float = 0.8
    smd_width: float = 0.8
    smd_height: float = 1.6


def footprint_points(fp: Footprint) -> list[tuple[Point, float]]:
    """Pad centres around (0, 0) and the turn of each pad (for SMD on the sides)."""
    n, m, d = max(fp.horizontal, 1), max(fp.vertical, 1), fp.pitch
    row = [((k - (n - 1) / 2) * d, 0.0) for k in range(n)]
    if fp.kind == SIP:
        return [(p, 0.0) for p in row]
    if fp.kind == DIP:
        half = fp.y / 2
        lower = [((x, -half), 0.0) for x, _ in row]
        upper = [((x, half), 0.0) for x, _ in reversed(row)]
        return lower + upper
    if fp.kind == QUAD:
        column = [(0.0, (k - (m - 1) / 2) * d) for k in range(m)]
        hx, hy = fp.x / 2, fp.y / 2
        result: list[tuple[Point, float]] = []
        result += [((-hx, -y), 90.0) for _, y in column]
        result += [((x, -hy), 0.0) for x, _ in row]
        result += [((hx, y), 90.0) for _, y in column]
        result += [((-x, hy), 0.0) for x, _ in row]
        return result
    rings = [(fp.x / 2, n)]
    if fp.kind == CIRCLE_TWO:
        rings.append((fp.y / 2, m))
    result = []
    for radius, count in rings:
        for k in range(count):
            a = pi / 2 - 2 * pi * k / count
            result.append(((radius * cos(a), radius * sin(a)), -360 * k / count))
    return result


def footprint(board: Board, fp: Footprint, x: float, y: float, layer: int = 1) -> list[Element]:
    """The wizard's pads placed around (x, y), joined into one group."""
    pads = []
    for (px, py), turn in footprint_points(fp):
        if fp.smd:
            pad = new_smd(board, layer, x + px, y + py, fp.smd_width, fp.smd_height)
            if turn:
                (pad,) = rotate_all([pad], turn)
        else:
            pad = new_pad(board, layer, x + px, y + py, fp.diameter, fp.drill)
        pads.append(pad)
    group = next_group_id(board.elements)
    return [with_group_ids(pad, [group]) for pad in pads]


def footprint_count(fp: Footprint) -> int:
    return len(footprint_points(fp))


def tiled(
    board: Board, objects: Sequence[Element], columns: int, rows: int, dx: float, dy: float
) -> list[Element]:
    """Copies of the objects in a grid (the originals are the first cell)."""
    result: list[Element] = []
    existing = list(board.elements)
    for row in range(max(rows, 1)):
        for column in range(max(columns, 1)):
            if row == 0 and column == 0:
                continue
            copies = fresh_copies(objects, existing + result, column * dx, -row * dy)
            result += copies
    return result


def circled(
    board: Board,
    objects: Sequence[Element],
    centre: Point,
    count: int,
    sweep: float,
    turn_objects: bool,
) -> list[Element]:
    """Copies around a centre: count places over sweep degrees (360: a full ring)."""
    count = max(count, 2)
    step = sweep / count if abs(sweep) >= 360 else sweep / (count - 1)
    left, bottom, right, top = bounds(objects)
    ox, oy = (left + right) / 2, (bottom + top) / 2
    cx, cy = centre
    result: list[Element] = []
    existing = list(board.elements)
    for k in range(1, count):
        angle = radians(step * k)
        rx, ry = ox - cx, oy - cy
        nx = cx + rx * cos(angle) - ry * sin(angle)
        ny = cy + rx * sin(angle) + ry * cos(angle)
        copies = fresh_copies(objects, existing + result, nx - ox, ny - oy)
        if turn_objects:
            copies = rotate_all(copies, step * k)
        result += copies
    return result
