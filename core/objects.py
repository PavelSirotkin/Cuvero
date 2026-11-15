"""New tracks and pads, and size changes of existing pads."""

from collections.abc import Iterable, Sequence
from dataclasses import replace
from math import cos, radians, sin
from typing import Any

from .model import COMPONENT_ID, LINE, OBJECT, PADS, SMD, THT, Board, Element, Point


def similar(board: Board, kind: int, layer: int) -> Element | None:
    """The last object of the same kind, preferably on the same layer."""
    candidates = [obj for obj in board.elements if obj.kind == kind and obj.record]
    if not candidates:
        return None
    same_layer = [obj for obj in candidates if obj.layer == layer]
    return (same_layer or candidates)[-1]


def template(board: Board, kind: int, layer: int) -> bytes:
    """Unknown record fields for a new object, copied from a similar existing one."""
    model = similar(board, kind, layer)
    if model is None:
        return b""
    record = bytearray(model.record)
    record[COMPONENT_ID] = bytes(3)  # New objects belong to no component and are unselected
    return bytes(record)


def _defaults(board: Board, kind: int, layer: int) -> tuple[bytes, dict[str, Any]]:
    """Clearance, thermal style and solder-mask settings of a similar object.

    The values come from the similar object's fields, not from its record: a record is
    only refreshed when the board is written, so a freshly drawn object's record still
    holds the bytes it was created from.
    """
    model = similar(board, kind, layer)
    if model is None and kind in PADS:
        # The defaults every pad written by the original program carries: the marker
        # 123456789 at bytes 62..65 (thermal reliefs need it), straight spoke directions
        # on all copper layers (one byte for SMD pads) and a 100 % spoke width.
        blank = bytearray(OBJECT.size)
        blank[62:66] = bytes.fromhex("15cd5b07")
        start = 0x55555555 if kind == THT else 0x55
        return bytes(blank), {"clearance": 0.4, "soldermask": True, "start": start, "rotation": 100}
    if model is None:
        return b"", {"clearance": 0.4, "soldermask": kind in PADS}
    values: dict[str, Any] = {
        "clearance": model.clearance,
        "soldermask": model.soldermask,
        "start": model.start,
    }
    if kind in PADS:
        values["rotation"] = model.rotation if model.rotation > 0 else 100
    return template(board, kind, layer), values


def new_track(board: Board, layer: int, points: Iterable[Point], width: float) -> Element:
    record, values = _defaults(board, LINE, layer)
    values.pop("start", None)
    return Element(LINE, layer=layer, width=width, points=list(points), record=record, **values)


OCTAGON_CUT = 0.585  # an octagonal pad's corner cut, as a part of its radius (original files)


def pad_points(x: float, y: float, radius: float, shape: int, angle: float = 0.0) -> list[Point]:
    """The points a through-hole pad keeps, turned counter-clockwise by angle degrees.

    As the original stores them: round and rounded pads (1, 4, 7) two orientation points
    across the pad (running downwards for the tall kind 7); rectangles (3, 6, 9) their
    four corners from the top left, clockwise; octagons (2, 5, 8) their eight corners,
    starting on the left side at the top, clockwise.
    """
    r = radius
    hx = r * (2 if shape in (4, 5, 6) else 1)
    hy = r * (2 if shape in (7, 8, 9) else 1)
    if shape in (3, 6, 9):
        local = [(-hx, hy), (hx, hy), (hx, -hy), (-hx, -hy)]
    elif shape in (2, 5, 8):
        a = r * OCTAGON_CUT
        local = [
            (-hx, hy - a),
            (-hx + a, hy),
            (hx - a, hy),
            (hx, hy - a),
            (hx, -hy + a),
            (hx - a, -hy),
            (-hx + a, -hy),
            (-hx, -hy + a),
        ]
    elif shape == 7:
        local = [(0.0, r), (0.0, -r)]
    else:
        local = [(-r, 0.0), (r, 0.0)]
    c, s = cos(radians(angle)), sin(radians(angle))
    return [(round(x + px * c - py * s, 6), round(y + px * s + py * c, 6)) for px, py in local]


def new_pad(
    board: Board, layer: int, x: float, y: float, diameter: float, drill: float, shape: int = 1
) -> Element:
    record, values = _defaults(board, THT, layer)
    radius = diameter / 2
    return Element(
        THT,
        x=x,
        y=y,
        outer=radius,
        inner=drill / 2,
        layer=layer,
        shape=shape,
        plated=True,
        points=pad_points(x, y, radius, shape),
        record=record,
        **values,
    )


def new_smd(board: Board, layer: int, x: float, y: float, width: float, height: float) -> Element:
    record, values = _defaults(board, SMD, layer)
    w, h = width / 2, height / 2
    points = [(x - w, y + h), (x + w, y + h), (x + w, y - h), (x - w, y - h)]
    return Element(
        SMD, outer=width, inner=height, layer=layer, points=points, record=record, **values
    )


def resized_smd(obj: Element, width: float, height: float) -> Element:
    """Resize an SMD pad around its centre, keeping its orientation."""
    if len(obj.points) != 4:
        return replace(obj, outer=width, inner=height)
    (x0, y0), (x1, y1), _, (x3, y3) = obj.points
    cx = sum(x for x, _ in obj.points) / 4
    cy = sum(y for _, y in obj.points) / 4
    ux, uy = x1 - x0, y1 - y0
    vx, vy = x3 - x0, y3 - y0
    lu, lv = (ux * ux + uy * uy) ** 0.5 or 1, (vx * vx + vy * vy) ** 0.5 or 1
    ux, uy, vx, vy = (
        ux / lu * width / 2,
        uy / lu * width / 2,
        vx / lv * height / 2,
        vy / lv * height / 2,
    )
    points = [
        (cx - ux - vx, cy - uy - vy),
        (cx + ux - vx, cy + uy - vy),
        (cx + ux + vx, cy + uy + vy),
        (cx - ux + vx, cy - uy + vy),
    ]
    return replace(obj, outer=width, inner=height, points=points)


def has_connections(board: Board) -> bool:
    """True if any pad stores air-wire connections, which may refer to object positions."""
    return any(
        obj.kind in PADS and obj.connections not in (b"", bytes(4)) for obj in board.elements
    )


def without_connections(obj: Element) -> Element:
    return replace(obj, connections=b"") if obj.kind in PADS else obj


def delete_elements(board: Board, indices: Iterable[int]) -> list[tuple[int, Element]]:
    """Remove objects by index; returns [(index, object)] in ascending order for restoring."""
    removed = [(index, board.elements[index]) for index in sorted(set(indices))]
    for index, _ in reversed(removed):
        del board.elements[index]
    return removed


def restore_elements(board: Board, removed: Sequence[tuple[int, Element]]) -> None:
    """Put objects returned by delete_elements back at their old positions."""
    for index, obj in removed:
        board.elements.insert(index, obj)
