"""Macro (.lmk) files and placing their objects on a board."""

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from .model import (
    CIRCLE,
    COMPONENT_ID,
    COUNT,
    MAGIC,
    MM,
    OBJECT,
    OUTLINE_TEXT,
    PADS,
    SEGMENT,
    SMD,
    STROKE_TEXT,
    THT,
    Element,
    LayoutError,
    Point,
    Reader,
    write_element,
)

MACRO_LAYERS = {"top": {5: 3, 6: 2}, "bottom": {5: 1, 6: 4}}
SIDE_SWAP = {1: 3, 3: 1, 2: 4, 4: 2}


def parse_macro(data: bytes) -> list[Element]:
    """A macro (.lmk) is a file header (version 5 or 6) followed by one object list.

    Library macros are drawn for the top side on layers C1-S2; the per-pad
    connection lists and the fixed 102-byte trailer after the objects are not needed.
    """
    reader = Reader(data)
    header = bytes(reader.take(4))
    if header[0] not in (5, 6) or header[1:] != MAGIC[1:]:
        raise LayoutError("Ожидался файл макроса .lmk")
    return [reader.element() for _ in range(reader.count(OBJECT.size))]


def load_macro(path: Path) -> list[Element]:
    return parse_macro(path.read_bytes())


def bounds(elements: Iterable[Element]) -> tuple[float, float, float, float]:
    xs, ys = [], []
    for obj in elements:
        for x, y in _anchor_points(obj):
            xs.append(x)
            ys.append(y)
    if not xs:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs), min(ys), max(xs), max(ys)


def _anchor_points(obj: Element) -> Iterator[Point]:
    if obj.kind == STROKE_TEXT and obj.children:
        for child in obj.children:
            yield from _anchor_points(child)
        return
    if obj.points:
        yield from obj.points
    if obj.kind in (THT, CIRCLE, OUTLINE_TEXT, SEGMENT) or (obj.kind == SMD and not obj.points):
        yield obj.x, obj.y
    if obj.kind == SEGMENT:
        yield obj.outer, obj.inner


def transformed(
    obj: Element,
    dx: float,
    dy: float,
    mirror_at: float | None = None,
    layers: dict[int, int] | None = None,
) -> Element:
    """Copy of obj moved by (dx, dy), optionally mirrored at x = mirror_at first."""

    def fx(x: float) -> float:
        return (2 * mirror_at - x if mirror_at is not None else x) + dx

    def fy(y: float) -> float:
        return y + dy

    changes: dict[str, Any] = {"points": [(fx(x), fy(y)) for x, y in obj.points]}
    if obj.kind in (THT, CIRCLE, OUTLINE_TEXT, SEGMENT, STROKE_TEXT) or (
        obj.kind == SMD and not obj.points
    ):
        changes.update(x=fx(obj.x), y=fy(obj.y))
    if obj.kind == SEGMENT:
        changes.update(outer=fx(obj.outer), inner=fy(obj.inner))
    if mirror_at is not None:
        if obj.kind == CIRCLE:
            start, end = obj.start, round(obj.width * MM)
            half = 180_000 if max(abs(start), abs(end)) > 1000 else 180
            changes.update(
                start=(half - end) % (2 * half), width=((half - start) % (2 * half)) / MM
            )
        if obj.kind in (OUTLINE_TEXT, STROKE_TEXT):
            changes.update(mirror_x=not obj.mirror_x)
    if obj.children:
        changes["children"] = [
            transformed(child, dx, dy, mirror_at, layers) for child in obj.children
        ]
    if layers:
        changes["layer"] = layers.get(obj.layer, obj.layer)
    return replace(obj, **changes)


def place_macro(
    elements: Sequence[Element], x: float, y: float, side: str = "top"
) -> list[Element]:
    """Macro objects centred at (x, y) on the chosen board side, without group links."""
    left, bottom, right, top = bounds(elements)
    cx, cy = (left + right) / 2, (bottom + top) / 2
    layers = dict(MACRO_LAYERS[side])
    mirror_at: float | None = None
    if side == "bottom":
        mirror_at = cx
        layers.update(SIDE_SWAP)
        layers.update(MACRO_LAYERS["bottom"])
    placed = []
    for obj in elements:
        moved = transformed(obj, x - cx, y - cy, mirror_at, layers)
        record = bytearray(moved.record)
        if record:
            record[COMPONENT_ID] = bytes(3)
        placed.append(replace(moved, groups=b"", record=bytes(record), connections=b""))
    return placed


MACRO_TRAILER = 102  # bytes after the pad connection lists; zero in macros of version 5


def macro_bytes(elements: Sequence[Element]) -> bytes:
    """A macro file (.lmk) holding the objects, without group links or components."""
    out = bytearray(MAGIC)
    out += COUNT.pack(len(elements))
    for obj in elements:
        write_element(out, obj)
    for obj in elements:
        if obj.kind in PADS:
            out += COUNT.pack(0)
    out += bytes(MACRO_TRAILER)
    return bytes(out)
