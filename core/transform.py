"""Rotating and mirroring objects about a point, including texts, arcs and components.

Angles follow the file: arcs and component rotations count counter-clockwise (Y up),
text rotations count clockwise. Pads are oriented by their points; their rotation and
mirror fields hold thermal settings and are left untouched.
"""

from collections.abc import Iterable, Sequence
from dataclasses import replace
from math import cos, isclose, radians, sin
from struct import Struct
from typing import Any

from .macros import bounds
from .model import CIRCLE, MM, OUTLINE_TEXT, SEGMENT, SMD, STROKE_TEXT, THT, Element, Point

ROTATION = Struct("<d")
ROTATION_OFFSET = 9  # component block: offset x, offset y (floats), centre mode (byte), rotation
TEXTS = (OUTLINE_TEXT, STROKE_TEXT)


def centre(elements: Iterable[Element]) -> Point:
    left, bottom, right, top = bounds(elements)
    return (left + right) / 2, (bottom + top) / 2


def _arc_scale(obj: Element) -> tuple[int, int, int]:
    """Start, end and units per degree of an arc: angles are in degrees or 1/1000 degree."""
    start, end = obj.start, round(obj.width * MM)
    scale = 1000 if max(abs(start), abs(end)) > 1000 else 1
    return start, end, scale


def _full_circle(obj: Element) -> bool:
    start, end, scale = _arc_scale(obj)
    return start == end or abs(end - start) >= 360 * scale


def _with_component_rotation(obj: Element, change: Any) -> Element:
    """Apply change(degrees) -> degrees to the rotation stored in a component block."""
    block = obj.component
    if len(block) < ROTATION_OFFSET + ROTATION.size:
        return obj
    (angle,) = ROTATION.unpack_from(block, ROTATION_OFFSET)
    new = change(angle) % 360
    if isclose(new, 360) or isclose(new, 0, abs_tol=1e-9):
        new = 0.0
    data = bytearray(block)
    ROTATION.pack_into(data, ROTATION_OFFSET, new)
    return replace(obj, component=bytes(data))


def _move_points(obj: Element, f: Any, changes: dict[str, Any]) -> None:
    changes["points"] = [f(x, y) for x, y in obj.points]
    if (
        obj.kind in (THT, CIRCLE, SEGMENT)
        or obj.kind in TEXTS
        or (obj.kind == SMD and not obj.points)
    ):
        changes["x"], changes["y"] = f(obj.x, obj.y)
    if obj.kind == SEGMENT:
        changes["outer"], changes["inner"] = f(obj.outer, obj.inner)


def rotated(obj: Element, angle: float, cx: float, cy: float) -> Element:
    """obj rotated counter-clockwise by angle degrees about (cx, cy)."""
    c, s = cos(radians(angle)), sin(radians(angle))

    def f(x: float, y: float) -> Point:
        dx, dy = x - cx, y - cy
        return cx + dx * c - dy * s, cy + dx * s + dy * c

    changes: dict[str, Any] = {}
    _move_points(obj, f, changes)
    if obj.kind == CIRCLE and not _full_circle(obj):
        start, end, scale = _arc_scale(obj)
        step = round(angle * scale)
        full = 360 * scale
        changes["start"] = (start + step) % full
        changes["width"] = ((end + step) % full) / MM
    if obj.kind in TEXTS:
        changes["rotation"] = round(obj.rotation - angle) % 360
    if obj.children:
        changes["children"] = [rotated(child, angle, cx, cy) for child in obj.children]
    result = replace(obj, **changes)
    if obj.component:
        result = _with_component_rotation(result, lambda a: a + angle)
    return result


def mirrored(obj: Element, axis: str, at: float) -> Element:
    """obj mirrored left-right (axis 'x', about x = at) or top-bottom (axis 'y', y = at)."""

    def f(x: float, y: float) -> Point:
        return (2 * at - x, y) if axis == "x" else (x, 2 * at - y)

    changes: dict[str, Any] = {}
    _move_points(obj, f, changes)
    if obj.kind == CIRCLE and not _full_circle(obj):
        start, end, scale = _arc_scale(obj)
        full = 360 * scale
        base = 180 * scale if axis == "x" else 0
        # Mirroring reverses the sweep, so the old end becomes the new start.
        changes["start"] = (base - end) % full
        changes["width"] = ((base - start) % full) / MM
    if obj.kind in TEXTS:
        flag = "mirror_x" if axis == "x" else "mirror_y"
        changes[flag] = not getattr(obj, flag)
        changes["rotation"] = (-obj.rotation) % 360
    if obj.children:
        changes["children"] = [mirrored(child, axis, at) for child in obj.children]
    result = replace(obj, **changes)
    if obj.component:
        result = _with_component_rotation(
            result, (lambda a: 180 - a) if axis == "x" else (lambda a: -a)
        )
    return result


def rotate_all(elements: Sequence[Element], angle: float) -> list[Element]:
    """Objects rotated together about the centre of their common bounding box."""
    cx, cy = centre(elements)
    return [rotated(obj, angle, cx, cy) for obj in elements]


def mirror_all(elements: Sequence[Element], axis: str) -> list[Element]:
    """Objects mirrored together about the centre line of their common bounding box."""
    cx, cy = centre(elements)
    at = cx if axis == "x" else cy
    return [mirrored(obj, axis, at) for obj in elements]
