"""DipTrace boards (.dip, binary) converted to Text-IO via the foreign builder.

The layout was read from files only (the user's boards and DipTrace's own examples),
checked field by field against DipTrace's ASCII export of the same boards:
- the file starts with "\\x07DTBOARD" and stores everything big-endian;
- a string is a 2-byte length and UTF-16 characters (an empty string: two zero bytes);
- a small integer takes 3 bytes, offset by 1 000 000 (0x0F4240 is zero);
- a length or coordinate takes 4 bytes, offset by 1 000 000 000, in 1/30 000 mm;
- flags are single bytes.
The fields are read by schema: a run of field types such as "iiLLs". The board outline
follows the schematic file name at the start; components follow, each with its turn in
quarter turns, side, library path, place, pattern name, reference, value and pads (in the
pattern's own coordinates); then the nets with their tracks.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from math import atan2, cos, degrees, radians, sin
from pathlib import Path

from .foreign import Builder, Conversion, ForeignError, arc_through

MAGIC = b"\x07DTBOARD"
UNIT = 1 / 30000  # mm per file unit
SMALL, LONG = 1_000_000, 1_000_000_000


class DipTraceError(ForeignError):
    pass


def _string(data: bytes, pos: int) -> tuple[str, int] | None:
    if pos + 2 > len(data):
        return None
    n = int.from_bytes(data[pos : pos + 2], "big")
    if n == 0:
        return "", pos + 2
    if n > 600 or pos + 2 + 2 * n > len(data):
        return None
    try:
        text = data[pos + 2 : pos + 2 + 2 * n].decode("utf-16-be")
    except UnicodeDecodeError:
        return None
    if not all(c.isprintable() or c in "\r\n\t" for c in text):
        return None
    return text, pos + 2 + 2 * n


def read(data: bytes, pos: int, types: str) -> tuple[list, int] | None:
    """Fields of the given types from pos: b flag (0/1), B any byte, i small integer,
    L length, s string. None when the bytes do not fit."""
    values: list = []
    for kind in types:
        if pos >= len(data):
            return None
        first = data[pos]
        if kind == "b":
            if first > 1:
                return None
            values.append(first)
            pos += 1
        elif kind == "B":
            values.append(first)
            pos += 1
        elif kind == "i":
            if first != 0x0F or pos + 3 > len(data):
                return None
            values.append(int.from_bytes(data[pos : pos + 3], "big") - SMALL)
            pos += 3
        elif kind == "L":
            if not 0x38 <= first <= 0x3E or pos + 4 > len(data):
                return None
            values.append(int.from_bytes(data[pos : pos + 4], "big") - LONG)
            pos += 4
        elif kind == "s":
            got = _string(data, pos)
            if got is None:
                return None
            values.append(got[0])
            pos = got[1]
        else:
            raise ValueError(kind)
    return values, pos


@dataclass
class Pad:
    number: str
    net: int
    x: float
    y: float
    width: float
    height: float
    hole: float
    shape: int = 0
    outline: list[tuple[float, float]] = field(default_factory=list)


def _pad_at(data: bytes, pos: int) -> tuple[list, list[tuple[float, float]], int] | None:
    head = read(data, pos, PAD_HEAD)
    if head is None:
        return None
    values, at = head
    count = values[-1]
    if not 0 <= count < 500:
        return None
    points = []
    for _ in range(count):
        got = read(data, at, "LL")
        if got is None:
            return None
        points.append((got[0][0] * UNIT, got[0][1] * UNIT))
        at = got[1]
    flag = read(data, at, "b")
    if flag is None:
        return None
    at = flag[1]
    for item in ("i", "i", "iiiL"):
        listed = read(data, at, "i")
        if listed is None or not 0 <= listed[0][0] < 64:
            return None
        numbers = read(data, listed[1], item * listed[0][0])
        if numbers is None:
            return None
        at = numbers[1]
    tail = read(data, at, PAD_TAIL)
    if tail is None:
        return None
    return values, points, tail[1]


@dataclass
class Part:
    reference: str
    value: str
    pattern: str
    x: float
    y: float
    quarter_turns: int
    bottom: bool
    pad_shape: int
    kind: int
    surface: bool = False  # surface pads: no holes, whatever hole size they keep
    pads: list[Pad] = field(default_factory=list)
    shapes: list["Shape"] = field(default_factory=list)


@dataclass
class Shape:
    """A drawing of a pattern, in the pattern's own coordinates (mm, DipTrace's y)."""

    kind: int  # 1 line, 2 rectangle, 3 ellipse, 4 filled rectangle, 6 arc, 7 text, 8 polyline
    layer: int  # 0 silkscreen; others are assembly, courtyard and the like
    points: list[tuple[float, float]]
    width: float  # mm; negative: the default
    text: str = ""
    size: int = 0
    turns: int = 0  # a text's own quarter turns


# A pattern shape: type, six lengths, flag, layer, text, font, flag, font size, two lengths,
# two integers, line width, point count; then the points (fractions of the pattern's
# width and height, times 10 000).
SHAPE_HEAD = "iLLLLLLbissbiLLiiLi"


def _shapes_at(data: bytes, pos: int, width: int, height: int) -> tuple[list[Shape], int]:
    """A pattern's drawings and where they end (pos itself when they cannot be read)."""
    got = read(data, pos, "i")
    if got is None or not 0 <= got[0][0] < 2000:
        return [], pos
    count, at = got[0][0], got[1]
    shapes: list[Shape] = []
    for _ in range(count):
        head = read(data, at, SHAPE_HEAD)
        if head is None:
            return shapes, pos
        v, at = head
        n = v[-1]
        if not 0 <= n < 5000:
            return shapes, pos
        pts = read(data, at, "LL" * n)
        if pts is None:
            return shapes, pos
        values, at = pts
        points = [
            (values[k] / 10000 * width * UNIT, values[k + 1] / 10000 * height * UNIT)
            for k in range(0, 2 * n, 2)
        ]
        kind = v[0] // 100 if v[0] >= 100 else v[0]  # texts are stored as 700
        shapes.append(Shape(kind, v[8], points, v[17] * UNIT, v[9], v[12], v[15]))
    return shapes, at


@dataclass
class BoardShape:
    """A drawing on the board itself (not part of a pattern)."""

    place: int  # 1 top silkscreen, 3 copper (of layer), 4 bottom silkscreen; others unused
    layer: int  # the copper layer's number
    kind: int  # 0 line, 1 arc through 3 points, 2 rectangle, 3 filled rectangle, 6 text,
    # 8 polyline
    points: list[tuple[float, float]]  # mm, DipTrace's y (down)
    width: float  # mm
    text: str = ""
    size: int = 0  # font size in points
    turns: int = 0


# A board shape: orientation, flag, place, layer, kind, font size, an integer, group (-1),
# three colours of three bytes, line width, point count; the points (absolute), then the
# name (a text's text).
BOARD_SHAPE = "ibiiiiii" + "BBB" * 3 + "Li"
# Its start: a small orientation (0..3), a flag, a small place (0..39).
_BOARD_SHAPE_START = re.compile(b"\x0f\x42[\x40-\x43][\x00\x01]\x0f\x42[\x40-\x67]")
DRAWN_PLACES = {1: 2, 4: 4}  # top and bottom silkscreen
COPPER_PLACE = 3


def read_board_shapes(data: bytes) -> list[BoardShape]:
    shapes = []
    for found in _BOARD_SHAPE_START.finditer(data):
        got = read(data, found.start(), BOARD_SHAPE)
        if got is None:
            continue
        v, at = got
        turns, _, place, layer, kind, size, _, group = v[:8]
        width, n = v[-2], v[-1]
        if group != -1 or not (0 <= kind <= 8 and 0 <= size < 200 and 1 <= n < 5000):
            continue
        if not -1 <= layer < 64 or (kind == 6) != (n == 1):
            continue
        pts = read(data, at, "LL" * n)
        if pts is None:
            continue
        values, at = pts
        name = read(data, at, "s")
        if name is None:
            continue
        points = [(values[k] * UNIT, values[k + 1] * UNIT) for k in range(0, 2 * n, 2)]
        text = name[0][0] if kind == 6 else ""
        shapes.append(BoardShape(place, layer, kind, points, width * UNIT, text, size, turns))
    return shapes


def _draw_board_shape(
    b: Builder, shape: BoardShape, copper: dict[int, int], silk: float = 0.25
) -> None:
    if shape.place == COPPER_PLACE:
        layer = copper.get(shape.layer)
    else:
        layer = DRAWN_PLACES.get(shape.place)
    if layer is None:
        if shape.place != COPPER_PLACE:
            b.report["графика платы вне шелкографии и меди пропущена"] += 1
        return
    pts = [(x, -y) for x, y in shape.points]
    width = shape.width if shape.width > 0 else silk
    if shape.kind == 6 and shape.text:
        # The text's top left corner as seen from the top (a mirrored one runs leftwards).
        bottom = layer in (3, 4)
        ink = max(shape.size, 1) * TEXT_HEIGHT
        x, y = pts[0]
        justify = (1.0 if bottom else 0.0, 1.0)
        b.text(layer, x, y, shape.text, ink, 90 * shape.turns, bottom, justify)
    elif shape.kind in (0, 8) and len(pts) >= 2:
        b.track(layer, pts if shape.kind == 8 else pts[:2], width)
    elif shape.kind in (2, 3) and len(pts) >= 2:
        (x0, y0), (x1, y1) = pts[:2]
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        if shape.kind == 3:
            b.zone(layer, corners)
        else:
            b.track(layer, [*corners, corners[0]], width)
    elif shape.kind == 1 and len(pts) >= 3:
        try:
            centre, radius, start, end = arc_through(pts[0], pts[1], pts[2])
        except ForeignError:
            return
        b.arc(layer, centre, radius, width, start, end)
    else:
        b.report["графика платы: эллипсы и прочие фигуры пропущены"] += 1


@dataclass
class Track:
    layer: int  # of the last segment
    points: list[tuple[float, float]]
    widths: list[float]
    layers: list[int] = field(default_factory=list)  # of the segment up to each point
    # Vias where the track changes layer: x, y, diameter, hole (mm).
    vias: list[tuple[float, float, float, float]] = field(default_factory=list)


@dataclass
class Layer:
    number: int
    name: str
    plane: bool  # a plane layer (type 1) poured with one net


FLAG = bytes([1])
# The copper layers: count, then each one: flag, number, colour (3 bytes), name, type
# (0 signal, 1 plane), hole type, net, a length, flag.
LAYER = "biBBBsiiiLb"


def read_layers(data: bytes) -> list[Layer]:
    """The board's copper layers from top to bottom (their numbers are what tracks, pads
    and pours refer to)."""
    zero = SMALL.to_bytes(3, "big")
    pos = data.find(FLAG + zero)
    while 0 <= pos < 4096:
        count = read(data, pos - 3, "i")
        if count is not None and 1 <= count[0][0] <= 32:
            layers, at = [], pos
            for k in range(count[0][0]):
                got = read(data, at, LAYER)
                if got is None or got[0][1] != k:
                    break
                v, at = got
                layers.append(Layer(k, v[5], v[6] == 1))
            if len(layers) == count[0][0]:
                return layers
        pos = data.find(FLAG + zero, pos + 1)
    return []


def layer_map(layers: list[Layer], use: Counter[int] | None = None) -> dict[int, int]:
    """DipTrace layer numbers to Sprint-Layout copper layers: the first is the top, the
    last the bottom; of those between them the two with the most copper (use: objects
    per layer number) become the inner layers I1 and I2, in their order."""
    if len(layers) < 2:
        return dict(LAYERS)
    inner = layers[1:-1]
    if len(inner) > len(INNER):
        use = use or Counter()
        busiest = sorted(inner, key=lambda layer: -use[layer.number])[: len(INNER)]
        inner = [layer for layer in inner if layer in busiest]
    result = {layers[0].number: 1, layers[-1].number: 3}
    result.update({layer.number: to for layer, to in zip(inner, INNER, strict=False)})
    return result


def read_outline(data: bytes) -> list[tuple[float, float]]:
    head = read(data, len(MAGIC), "iLiis")
    if head is None:
        raise DipTraceError("Нет заголовка платы DipTrace")
    got = read(data, head[1], "bLLLLi")
    if got is None:
        return []
    count = got[0][5]
    pos = got[1]
    points = []
    for _ in range(count):
        point = read(data, pos, "LLb")
        if point is None:
            break
        points.append((point[0][0] * UNIT, point[0][1] * UNIT))
        pos = point[1]
    return points


# A part record: Type, Number1, Number2, quarter turns, Group, Number, PadShape, SurfacePad,
# four integers, four lengths, BottomSide, ConnectedLayer, Flipped, HiddenId, origin x and
# y, two flags and the count of user fields (each: name, value, integer).
PART_HEAD = "iiiiiiib" + "iiii" + "LLLL" + "bibi" + "LL" + "bb" + "i"
# After the user fields: two integers, a length, a flag, the library path, an integer and
# a count of points (x, y each; read apart), four flags, x, y, two lengths, flag, length,
# two flags, two integers, the pattern name, width, height, pad width, pad height, hole,
# hole height, two integers, and four strings: name, reference, value and one more; then
# the pad count.
PART_PLACE = "iiLbs" + "ii" + "bbbbLL" + "LLbLbbii" + "s" + "LLLLLLii" + "ssss" + "i"
_PLACE_POINTS = 7  # fields of PART_PLACE before the points
# A pad: flag, index, net, x, y, number, name, width, height, hole, hole height, an
# integer, flag, the pad's shape, flag, the count of its outline points (then the points,
# x and y each), a flag, three lists (a count, then the items): hidden layers and blind
# layers (layer numbers), custom spokes (layer, type, spoke count, width); and the rest.
PAD_HEAD = "biiLLssLLLLibibi"
PAD_TAIL = "bbbbbLLb"


def _part_at(data: bytes, pos: int) -> tuple[Part, int] | None:
    head = read(data, pos, PART_HEAD)
    if head is None:
        return None
    values, at = head
    kind, quarter, pad_shape, surface, bottom, fields = (
        values[0],
        values[3],
        values[6],
        values[7],
        values[16],
        values[-1],
    )
    if not (0 <= kind < 40 and 0 <= fields < 60 and -1 <= pad_shape < 20):
        return None
    for _ in range(fields):
        got = read(data, at, "ssi")
        if got is None:
            return None
        at = got[1]
    before = read(data, at, PART_PLACE[:_PLACE_POINTS])
    if before is None or not 0 <= before[0][-1] < 1000:
        return None
    points = read(data, before[1], "LL" * before[0][-1])
    if points is None:
        return None
    after = read(data, points[1], PART_PLACE[_PLACE_POINTS:])
    if after is None:
        return None
    v, at = before[0] + after[0], after[1]
    x, y = v[11], v[12]
    pattern = v[21]
    default_w, default_h, default_hole = v[24], v[25], v[26]
    name, reference, value = v[30], v[31], v[32]
    pad_count = v[34]
    if not 0 <= pad_count < 2000:
        return None
    part = Part(
        reference=reference,
        value=value,
        pattern=pattern or name,
        x=x * UNIT,
        y=y * UNIT,
        quarter_turns=quarter,
        bottom=bottom == 1,
        pad_shape=pad_shape,
        kind=kind,
        surface=surface == 1,
    )
    for _ in range(pad_count):
        pad_read = _pad_at(data, at)
        if pad_read is None:
            return None
        p, outline, at = pad_read
        if p[1] <= 0:
            continue  # a template pad of the pattern (numbered -1 or 0)
        w, h, hole = p[7], p[8], p[9]
        part.pads.append(
            Pad(
                number=p[5],
                net=p[2],
                x=p[3] * UNIT,
                y=p[4] * UNIT,
                width=(w if w > 0 else default_w) * UNIT,
                height=(h if h > 0 else default_h) * UNIT,
                hole=(hole if hole >= 0 else default_hole) * UNIT,
                shape=p[13],
                outline=outline,
            )
        )
    # The pattern's size as drawn (stored turned by odd quarter turns).
    width, height = (v[23], v[22]) if quarter % 2 else (v[22], v[23])
    part.shapes, at = _shapes_at(data, at, width, height)
    return part, at


def read_parts(data: bytes, start: int = 0, end: int | None = None) -> list[Part]:
    parts = []
    pos, end = start, len(data) if end is None else end
    while pos < end:
        if data[pos] == 0x0F:
            got = _part_at(data, pos)
            if got is not None:
                parts.append(got[0])
                pos = got[1]
                continue
        pos += 1
    return parts


# A track vertex: x, y, the layer of the segment up to it, kind, width, via diameter, flag,
# integer, flag, integer, via hole, the via's first and last layer, flag.
VERTEX = "LLiiLLbibiLiib"


def read_tracks(data: bytes, start: int = 0, end: int | None = None) -> list[Track]:
    """Tracks: integer -1, track number, vertex count, then the vertices."""
    tracks: list[Track] = []
    pos, end = start, len(data) if end is None else end
    minus_one = (SMALL - 1).to_bytes(3, "big")
    while pos < end:
        pos = data.find(minus_one, pos, end)
        if pos < 0:
            break
        got = read(data, pos + 3, "ii")
        if got is None or not 2 <= got[0][1] < 5000:
            pos += 1
            continue
        count, at = got[0][1], got[1]
        points, layers, widths, sizes = [], [], [], []
        for _ in range(count):
            vertex = read(data, at, VERTEX)
            if vertex is None:
                break
            v, at = vertex
            points.append((v[0] * UNIT, v[1] * UNIT))
            layers.append(v[2])
            widths.append(v[4] * UNIT)
            sizes.append((v[5] * UNIT, v[10] * UNIT))
        if len(points) == count:
            vias = [
                (points[k][0], points[k][1], via[0], via[1])
                for k, via in enumerate(sizes)
                if 0 < k < count - 1 and layers[k] != layers[k + 1]
            ]
            tracks.append(Track(layers[-1], points, widths, layers, vias))
            pos = at
        else:
            pos += 1
    return tracks


# A net record ends its head with: a flag, active point, active line, two integers,
# the net number (what pads refer to), route mode, width, clearance; then the name,
# via size and via ring.
NET_HEAD = "iiiiiLL"
NET_NAME = "sLL"


def read_nets(data: bytes) -> dict[int, str]:
    """Net names by net number."""
    names: dict[int, str] = {}
    head = 3 * 5 + 4 * 2
    for pos in range(head, len(data) - 10):
        got = read(data, pos, NET_NAME)
        if got is None or not got[0][0]:
            continue
        before = read(data, pos - head, NET_HEAD)
        if before is None or before[1] != pos:
            continue
        _, active_line, _, number, mode, width, clearance = before[0]
        (name, via, ring), _ = got
        if not (0 < width < 1_000_000 and 0 <= clearance < 1_000_000 and 0 < via < 1_000_000):
            continue
        if 0 <= number < 100_000 and 0 <= mode < 10 and active_line >= -1:
            names.setdefault(number, name)
    return names


@dataclass
class Pour:
    layer: int
    net: int
    width: float  # mm: the fill is drawn with lines of this width
    regions: list[list[tuple[float, float]]]  # poured copper outlines (holes included)
    ids: list[int]
    spokes: list[tuple[float, float, float, float, float]] = field(default_factory=list)


# A copper pour: line width, clearance, minimum area, group, layer, net, the outline
# (count, points), the fill as lines (count; x1 y1 x2 y2 and an integer each) and the
# fill as polygons (count; each: point count, points, island number).
POUR_HEAD = "LLLiiii"


def _pour_at(data: bytes, pos: int) -> tuple[Pour, int] | None:
    head = read(data, pos, POUR_HEAD)
    if head is None:
        return None
    (width, clearance, area, group, layer, net, count), at = head
    if not (0 < width < 3_000_000 and 0 <= clearance < 3_000_000 and 0 <= layer < 32):
        return None
    if not 3 <= count < 5000:
        return None
    got = read(data, at, "LL" * count + "i")
    if got is None:
        return None
    lines, at = got[0][-1], got[1]
    if not 0 <= lines < 200_000:
        return None
    for _ in range(lines):
        line = read(data, at, "LLLLi")
        if line is None:
            return None
        at = line[1]
    got = read(data, at, "i")
    if got is None or not 0 <= got[0][0] < 100_000:
        return None
    regions, ids = [], []
    at = got[1]
    for _ in range(got[0][0]):
        size = read(data, at, "i")
        if size is None or not 0 <= size[0][0] < 200_000:
            return None
        n = size[0][0]
        poly = read(data, size[1], "LL" * n + "i")
        if poly is None:
            return None
        values, at = poly
        regions.append([(values[k] * UNIT, values[k + 1] * UNIT) for k in range(0, 2 * n, 2)])
        ids.append(values[-1])
    # Thermal relief: type, spoke count, line spacing, spoke width, then the spokes as
    # lines (x1, y1, x2, y2, width, number).
    spokes = []
    relief = read(data, at, "iiLLi")
    if relief is not None and 0 <= relief[0][-1] < 50_000:
        tail = relief[1]
        for _ in range(relief[0][-1]):
            spoke = read(data, tail, "LLLLLi")
            if spoke is None:
                break
            (x1, y1, x2, y2, w, _number), tail = spoke
            spokes.append((x1 * UNIT, y1 * UNIT, x2 * UNIT, y2 * UNIT, w * UNIT))
        else:
            at = tail
    return Pour(layer, net, width * UNIT, regions, ids, spokes), at


def read_pours(data: bytes) -> list[Pour]:
    pours = []
    pos = 0
    while pos < len(data):
        if 0x38 <= data[pos] <= 0x3E:
            got = _pour_at(data, pos)
            if got is not None:
                pours.append(got[0])
                pos = got[1]
                continue
        pos += 1
    return pours


def _area(points: list[tuple[float, float]]) -> float:
    return (
        abs(
            sum(
                points[k][0] * points[(k + 1) % len(points)][1]
                - points[(k + 1) % len(points)][0] * points[k][1]
                for k in range(len(points))
            )
        )
        / 2
    )


def _inside(point: tuple[float, float], ring: list[tuple[float, float]]) -> bool:
    x, y = point
    hit = False
    for k in range(len(ring)):
        (x1, y1), (x2, y2) = ring[k], ring[(k + 1) % len(ring)]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def pour_islands(pour: Pour) -> list[tuple[list, list[list]]]:
    """Outer outlines with their holes: a region inside a larger one of the same island
    number is a hole in it."""
    order = sorted(range(len(pour.regions)), key=lambda k: -_area(pour.regions[k]))
    islands: list[tuple[list, list[list]]] = []
    owner: dict[int, int] = {}
    for k in order:
        ring = pour.regions[k]
        if len(ring) < 3:
            continue
        parent = next(
            (
                n
                for n, (outer, _) in enumerate(islands)
                if owner.get(n) == pour.ids[k] and _inside(ring[0], outer)
            ),
            None,
        )
        if parent is None:
            owner[len(islands)] = pour.ids[k]
            islands.append((ring, []))
        else:
            islands[parent][1].append(ring)
    return islands


LAYERS = {0: 1, 1: 3}  # signal layers of a two-layer board: top, bottom
INNER = (5, 6)  # Sprint-Layout's inner layers I1, I2
SILK_WIDTH = 0.25  # mm: DipTrace default (SilkLineWidth 0.75 in its ASCII thirds of a mm)
# The board's line widths: jumper layer, display mode, a flag, then silkscreen, table,
# titles and board outline widths.
_WIDTHS = re.compile(
    b"\x0f\x42[\x40-\x4f]\x0f\x42[\x40-\x4f][\x00\x01](?:\x3b[\x9a\x9b]..){4}[\x00\x01]", re.S
)


def read_silk_width(data: bytes) -> float:
    """The default width of silkscreen lines (mm)."""
    for found in _WIDTHS.finditer(data):
        got = read(data, found.start(), "iibLLLL")
        if got is not None and all(0 < v < 30000 for v in got[0][3:]):
            return got[0][3] * UNIT
    return SILK_WIDTH


TEXT_HEIGHT = 0.3528  # mm of letter height per unit of DipTrace's font size (points)


def _draw_shapes(b: Builder, part: "Part", key: str, turn: float, silk: float = SILK_WIDTH) -> None:
    """Silkscreen drawings of a pattern. A part on the bottom side keeps them already
    mirrored, as seen from the top, so every part places them like a top one."""
    a = radians(turn)
    layer = 4 if part.bottom else 2

    def place(px: float, py: float) -> tuple[float, float]:
        lx, ly = px, -py
        return part.x + lx * cos(a) - ly * sin(a), -part.y + lx * sin(a) + ly * cos(a)

    for shape in part.shapes:
        if shape.layer != 0 or not shape.points:
            continue
        width = shape.width if shape.width > 0 else silk
        pts = [place(px, py) for px, py in shape.points]
        if shape.kind == 1 and len(pts) >= 2:
            b.track(layer, pts[:2], width, key)
        elif shape.kind in (2, 4) and len(pts) >= 2:
            (x0, y0), (x1, y1) = shape.points[:2]
            corners = [place(x0, y0), place(x1, y0), place(x1, y1), place(x0, y1)]
            if shape.kind == 4:
                b.zone(layer, corners, part=key)
            else:
                b.track(layer, [*corners, corners[0]], width, key)
        elif shape.kind in (3, 5) and len(pts) >= 2:
            (x0, y0), (x1, y1) = pts[:2]
            centre = ((x0 + x1) / 2, (y0 + y1) / 2)
            radius = (abs(x1 - x0) + abs(y1 - y0)) / 4
            if shape.kind == 5:
                b.disc(layer, centre, radius, key)
            else:
                b.arc(layer, centre, radius, width, 0.0, 0.0, key)
        elif shape.kind == 6 and len(pts) >= 3:
            try:
                centre, radius, start, end = arc_through(pts[0], pts[1], pts[2])
            except ForeignError:
                continue
            b.arc(layer, centre, radius, width, start, end, key)
        elif shape.kind == 8 and len(pts) >= 2:
            b.track(layer, pts, width, key)
        elif shape.kind == 7 and shape.text:
            # The text runs along its own turn in the pattern (DipTrace's y points down),
            # turned and mirrored with the part; it is centred along its baseline, which
            # passes through its point.
            px, py = shape.points[0]
            t = radians(90 * shape.turns)
            x, y = place(px, py)
            ex, ey = place(px + cos(t), py - sin(t))
            angle = degrees(atan2(ey - y, ex - x))
            ink = max(shape.size, 1) * TEXT_HEIGHT
            justify = (0.5, 0.0)
            if shape.text == part.reference:
                b.label(key, "ID_TEXT", layer, x, y, ink, angle, part.bottom, True, justify)
            else:
                b.text(layer, x, y, shape.text, ink, angle, part.bottom, justify, key)


MOUNTING_HOLE = 15  # part type of a plain mounting hole


def pad_position(part: Part, pad: Pad) -> tuple[float, float]:
    """A pad's place on the board, in mm with y up. Pattern coordinates get y up
    (DipTrace's y points down), then are turned; a part on the bottom side keeps y as it
    is, which mirrors it top to bottom, and turns the other way."""
    a = radians(90 * part.quarter_turns * (-1 if part.bottom else 1))
    lx, ly = pad.x, (pad.y if part.bottom else -pad.y)
    return part.x + lx * cos(a) - ly * sin(a), -part.y + lx * sin(a) + ly * cos(a)


def convert(data: bytes, name: str = "DipTrace") -> Conversion:
    if not data.startswith(MAGIC):
        raise DipTraceError("Не файл платы DipTrace (.dip)")
    outline = read_outline(data)
    parts = read_parts(data)
    tracks = read_tracks(data)
    nets = read_nets(data)
    pours = read_pours(data)
    layers = read_layers(data)
    silk = read_silk_width(data)
    use = Counter(layer for track in tracks for layer in track.layers[1:])
    use += Counter(pour.layer for pour in pours)
    copper = layer_map(layers, use)
    b = Builder(name)
    b.multilayer = len(layers) > 2
    for layer in layers:
        if layer.number not in copper:
            b.report[f"слой «{layer.name}» пропущен: внутренних слоёв больше двух"] += 1
        elif layer.plane and not use[layer.number]:
            b.report[f"слой-плоскость «{layer.name}» без заливки не перенесён"] += 1
    # DipTrace's y axis points down the screen; ours points up.
    outline = [(x, -y) for x, y in outline]
    if len(outline) >= 3:
        b.track(7, [*outline, outline[0]], 0.1)
    for n, part in enumerate(parts):
        key = f"{part.reference}#{n}"
        b.component(key, part.reference, part.value, part.pattern, not part.bottom)
        a = radians(90 * part.quarter_turns * (-1 if part.bottom else 1))
        _draw_shapes(b, part, key, 90 * part.quarter_turns, silk)
        for pad in part.pads:
            x, y = pad_position(part, pad)
            net = nets.get(pad.net, f"net{pad.net}") if pad.net >= 0 else None
            if part.kind == MOUNTING_HOLE:
                b.tht(x, y, 0, 0, pad.hole or pad.width, "round", 0, False, key, None)
                continue
            # The pad's own shape, else the part's: 1 round or oval, 2 rectangle; an
            # outline of 8 points is an octagon.
            code = pad.shape or part.pad_shape
            shape = "rect" if code == 2 else "round"
            if len(pad.outline) == 8:
                shape = "octagon"
            if pad.hole > 0 and not part.surface:
                b.tht(x, y, pad.width, pad.height, pad.hole, shape, degrees(a), True, key, net)
            else:
                b.smd(3 if part.bottom else 1, x, y, pad.width, pad.height, degrees(a), key, net)
    for track in tracks:
        points = [(x, -y) for x, y in track.points]
        for k in range(len(points) - 1):
            signal = copper.get(track.layers[k + 1] if track.layers else track.layer)
            if signal is not None:
                b.track(signal, points[k : k + 2], track.widths[k] or 0.25)
        for x, y, diameter, hole in track.vias:
            b.via(x, -y, diameter, hole, None)
    for pour in pours:
        poured = copper.get(pour.layer)
        if poured is None:
            continue
        for outer, holes in pour_islands(pour):
            flip = [(x, -y) for x, y in outer]
            holes_up = [[(x, -y) for x, y in hole] for hole in holes]
            b.zone(poured, flip, holes_up, width=pour.width)
        for x1, y1, x2, y2, w in pour.spokes:
            b.track(poured, [(x1, -y1), (x2, -y2)], w)
        b.report["заливки перенесены залитыми, как в DipTrace (без перезаливки)"] += 1
    for drawing in read_board_shapes(data):
        _draw_board_shape(b, drawing, copper, silk)
    b.report["графика корпусов: только шелкография (сборочные слои и контуры пропущены)"] += 1
    return b.finish()


def convert_file(path: Path) -> Conversion:
    return convert(path.read_bytes(), path.stem)
