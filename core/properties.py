"""Reading and changing object properties shown in the properties panel.

Only fields confirmed against the original program are edited here. Thermal reliefs are
left alone: their storage could not be confirmed (see ROADMAP.md).
"""

from dataclasses import replace
from math import atan2, degrees, hypot
from struct import Struct

from .macros import transformed
from .model import CIRCLE, LINE, MM, POLYGON, SEGMENT, SMD, THT, Board, Element, Point
from .objects import resized_smd

ORIGIN = Struct("<ii")
ORIGIN_OFFSET = 521  # board header: origin x and y in 1/10000 mm, right before the layer flag
COPPER_UM = 35.0
TEMPERATURE_RISE = 20.0


# --- Coordinate origin -------------------------------------------------------


def board_origin(board: Board) -> Point:
    """Point the original program measures displayed coordinates from (file units, Y up)."""
    if len(board.header) < ORIGIN_OFFSET + ORIGIN.size:
        return 0.0, 0.0
    x, y = ORIGIN.unpack_from(board.header, ORIGIN_OFFSET)
    return x / MM, y / MM


def with_origin(board: Board, x: float, y: float) -> Board:
    header = bytearray(board.header)
    ORIGIN.pack_into(header, ORIGIN_OFFSET, round(x * MM), round(y * MM))
    return replace(board, header=bytes(header))


# --- Positions ---------------------------------------------------------------


def centre_of(obj: Element) -> Point:
    """Reference point of an object as the properties panel shows it."""
    if obj.kind == SMD and obj.points:
        xs = [x for x, _ in obj.points]
        ys = [y for _, y in obj.points]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    if obj.kind in (LINE, POLYGON) and obj.points:
        xs = [x for x, _ in obj.points]
        ys = [y for _, y in obj.points]
        return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    return obj.x, obj.y


def moved_to(obj: Element, x: float, y: float) -> Element:
    cx, cy = centre_of(obj)
    return transformed(obj, x - cx, y - cy)


# --- Pads --------------------------------------------------------------------


def with_pad_shape(pad: Element, shape: int) -> Element:
    """A through-hole pad of another shape, keeping its place, size and turn."""
    from .objects import pad_points

    angle = pad_rotation(pad)
    changed = replace(pad, shape=shape)
    return replace(changed, points=pad_points(pad.x, pad.y, pad.outer, shape, angle))


def with_pad_size(pad: Element, diameter: float, drill: float) -> Element:
    """A through-hole pad with a new outer diameter and drill, keeping its orientation."""
    radius = diameter / 2
    points = pad.points
    if len(points) in (4, 8):
        from .objects import pad_points

        points = pad_points(pad.x, pad.y, radius, pad.shape, pad_rotation(pad))
    elif len(points) == 2 and pad.outer > 0:
        # The two points span the pad along its orientation; scale them with the pad.
        (x0, y0), (x1, y1) = points
        factor = radius / pad.outer
        points = [
            (pad.x + (x0 - pad.x) * factor, pad.y + (y0 - pad.y) * factor),
            (pad.x + (x1 - pad.x) * factor, pad.y + (y1 - pad.y) * factor),
        ]
    resized = replace(pad, outer=radius, inner=drill / 2, points=points)
    if has_thermal(resized):
        resized = replace(resized, width=thermal_width(resized))
    return resized


def smd_size(pad: Element) -> tuple[float, float]:
    if len(pad.points) == 4:
        (x0, y0), (x1, y1), _, (x3, y3) = pad.points
        return hypot(x1 - x0, y1 - y0), hypot(x3 - x0, y3 - y0)
    return pad.outer, pad.inner


def smd_angle(pad: Element) -> float:
    """Direction of the pad's width edge in degrees, counter-clockwise."""
    if len(pad.points) != 4:
        return 0.0
    (x0, y0), (x1, y1) = pad.points[0], pad.points[1]
    return degrees(atan2(y1 - y0, x1 - x0)) % 360


def with_smd_size(pad: Element, width: float, height: float) -> Element:
    resized = resized_smd(pad, width, height)
    if has_thermal(resized):
        resized = replace(resized, width=thermal_width(resized))
    return resized


# --- Tracks ------------------------------------------------------------------


def track_length(obj: Element) -> float:
    if obj.kind == SEGMENT:
        return hypot(obj.outer - obj.x, obj.inner - obj.y)
    return sum(
        hypot(x1 - x0, y1 - y0)
        for (x0, y0), (x1, y1) in zip(obj.points, obj.points[1:], strict=False)
    )


def track_current(width: float, copper_um: float = 35.0, rise: float = 20.0) -> float:
    """Allowed current in amperes, by default for 35 um copper and 20 degrees of heating.

    The original program shows 0.667 A, 1.59 A, 3.13 A and 6.2 A for tracks of 0.2, 0.5,
    1 and 2 mm; this straight line reproduces all four within their shown precision.
    Other copper and heating scale it as the IPC-2221 formula does.
    """
    base = 3.0733 * width + 0.0533
    return base * (copper_um / 35.0) ** 0.725 * (rise / 20.0) ** 0.44


# --- Circles and arcs --------------------------------------------------------


def _angle_scale(obj: Element) -> int:
    start, end = obj.start, round(obj.width * MM)
    return 1000 if max(abs(start), abs(end)) > 1000 else 1


def circle_angles(obj: Element) -> tuple[float, float]:
    """Start and stop angle in degrees, counter-clockwise; equal angles mean a full circle."""
    scale = _angle_scale(obj)
    return obj.start / scale, round(obj.width * MM) / scale


def circle_diameter(obj: Element) -> float:
    return obj.outer + obj.inner


def circle_line_width(obj: Element) -> float:
    return obj.outer - obj.inner


def with_circle(
    obj: Element, diameter: float, line_width: float, start: float, stop: float, filled: bool
) -> Element:
    """A circle or arc with new size and angles; angles are stored in 1/1000 degree."""
    radius = diameter / 2
    return replace(
        obj,
        outer=radius + line_width / 2,
        inner=radius - line_width / 2,
        start=round(start * 1000) % 360_000,
        width=(round(stop * 1000) % 360_000) / MM,
        filled=filled,
    )


# --- Polygons ----------------------------------------------------------------


def is_hatched(obj: Element) -> bool:
    """Polygons keep the hatching flag where other objects keep their mirror flag."""
    return obj.kind == POLYGON and obj.mirror_x


def with_hatching(obj: Element, hatched: bool) -> Element:
    return replace(obj, mirror_x=hatched) if obj.kind == POLYGON else obj


KIND_NAMES = {
    THT: "Площадка",
    SMD: "SMD-площадка",
    LINE: "Дорожка",
    SEGMENT: "Дорожка",
    POLYGON: "Полигон",
    CIRCLE: "Окружность",
}


# --- Thermal reliefs ---------------------------------------------------------
#
# Confirmed with the original program and files saved by it:
# - the relief is on when the byte that other objects use as "mirror X" is set;
# - the spoke width lives in the width field, by default a third of the pad diameter;
# - spoke directions are bits of the start-angle field, one byte per copper layer
#   (C1, C2, I1, I2): bit k points at phi + 90 - 45 * k degrees, where phi is the
#   direction from the pad's first orientation point to its second; 0x55 means the
#   four straight spokes, 0xAA the four diagonal ones;
# - the original draws spokes only when the record carries the marker 123456789 at
#   bytes 62..65, which every pad it writes has.

THERMAL_MARKER = bytes.fromhex("15cd5b07")
THERMAL_MARKER_OFFSET = 62
STRAIGHT_SPOKES = 0x55


def has_thermal(pad: Element) -> bool:
    return pad.kind in (THT, SMD) and pad.mirror_x


def thermal_directions(pad: Element) -> int:
    """Direction bits of the first copper layer's byte."""
    return pad.start & 0xFF


def pad_orientation(pad: Element) -> float:
    """Angle in degrees from the pad's first orientation point to its second."""
    if len(pad.points) >= 2:
        (x0, y0), (x1, y1) = pad.points[0], pad.points[1]
        if (x0, y0) != (x1, y1):
            return degrees(atan2(y1 - y0, x1 - x0))
    return 0.0


def pad_rotation(pad: Element) -> float:
    """Counter-clockwise turn of a through-hole pad's shape from its upright position.

    Pads keep two orientation points (round and rounded shapes), their four corners
    (rectangles) or their eight corners (octagons); for the corner forms the top edge
    gives the turn. Rounded and octagonal pads of the "tall" kinds (7, 8) stand upright
    when their two points run downwards.
    """
    points = pad.points
    if len(points) == 8:
        (x0, y0), (x1, y1) = points[1], points[2]
    elif len(points) == 4:
        (x0, y0), (x1, y1) = points[0], points[1]
    elif len(points) == 2:
        return (pad_orientation(pad) + (90 if pad.shape in (7, 8, 9) else 0)) % 360
    else:
        return 0.0
    if (x0, y0) == (x1, y1):
        return 0.0
    return degrees(atan2(y1 - y0, x1 - x0)) % 360


def spoke_angle(pad: Element, bit: int) -> float:
    return (pad_orientation(pad) + 90 - 45 * bit) % 360


def thermal_width(pad: Element) -> float:
    """Default spoke width of a pad: a third of its size, scaled by the stored percentage."""
    size = pad.outer * 2 if pad.kind == THT else min(smd_size(pad))
    percent = pad.rotation if pad.rotation > 0 else 100
    return size / 3 * percent / 100


def with_marker(pad: Element) -> Element:
    record = bytearray(pad.record or bytes(77))
    start = THERMAL_MARKER_OFFSET
    if bytes(record[start : start + 4]) == THERMAL_MARKER:
        return pad
    record[start : start + 4] = THERMAL_MARKER
    return replace(pad, record=bytes(record))


THERMAL_LAYERS = ("C1", "C2", "I1", "I2")  # one direction byte each, in this order


def thermal_layer_directions(pad: Element, layer_index: int) -> int:
    return (pad.start & 0xFFFFFFFF) >> (8 * layer_index) & 0xFF


def thermal_layers_equal(pad: Element) -> bool:
    if pad.kind != THT:
        return True
    return len({thermal_layer_directions(pad, i) for i in range(4)}) == 1


def with_thermal(
    pad: Element, enabled: bool, directions: int | None = None, layer_index: int | None = None
) -> Element:
    """Switch a pad's thermal relief and set its spoke directions.

    Without layer_index the directions apply to every copper layer (SMD pads have one);
    with it only that layer's byte changes, like "Layer individual" in the original.
    """
    if pad.kind not in (THT, SMD):
        return pad
    bits = (thermal_directions(pad) or STRAIGHT_SPOKES) if directions is None else directions
    bits &= 0xFF
    current = pad.start & 0xFFFFFFFF
    if pad.kind == SMD:
        mask = (current & 0xFFFFFF00) | bits
    elif layer_index is None:
        mask = bits * 0x01010101
    else:
        shift = 8 * layer_index
        mask = (current & ~(0xFF << shift) & 0xFFFFFFFF) | bits << shift
    signed = mask - (1 << 32) if mask >= 1 << 31 else mask
    changed = replace(
        pad, mirror_x=enabled, start=signed, rotation=pad.rotation if pad.rotation > 0 else 100
    )
    if enabled:
        changed = replace(with_marker(changed), width=thermal_width(changed))
    return changed


THERMAL_PERCENT_RANGE = (50, 300)


def thermal_percent(pad: Element) -> int:
    return pad.rotation if pad.rotation > 0 else 100


def with_thermal_percent(pad: Element, percent: int) -> Element:
    """Spoke width as a percentage of the default (a third of the pad), 50..300 %."""
    low, high = THERMAL_PERCENT_RANGE
    changed = replace(pad, rotation=min(max(int(percent), low), high))
    return replace(changed, width=thermal_width(changed)) if has_thermal(changed) else changed


# --- Polygon hatching --------------------------------------------------------
# A hatched polygon draws its grid lines either with the outline width or with its own
# width; the original keeps that choice in the "mirror Y" byte (set: outline width) and
# the own width in the rotation field, in 1/2000 mm (1000 shows as 0.50 mm).

HATCH_UNITS = 2000


def hatch_uses_outline(obj: Element) -> bool:
    return obj.mirror_y


def hatch_width(obj: Element) -> float:
    return obj.rotation / HATCH_UNITS


def with_hatch_style(obj: Element, uses_outline: bool, width: float) -> Element:
    if obj.kind != POLYGON:
        return obj
    return replace(obj, mirror_y=uses_outline, rotation=round(width * HATCH_UNITS))
