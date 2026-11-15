"""Altium Designer boards (.PcbDoc, binary) converted to Text-IO text for a new board.

The file is a compound file (see cfb.py) with one storage per kind of object. Settings,
components, nets and polygons are property lists ("|KEY=value|..."); tracks, arcs, pads,
vias, texts, fills and regions are binary records. Lengths are in 1/10000 mil with Y up.

The result is Text-IO text (the exchange format of the original program, see textio.py),
which builds the objects, components and their labels with the checked import code. What
cannot be represented exactly is counted in the report.
"""

from collections import Counter, defaultdict
from math import cos, hypot, radians, sin
from pathlib import Path
from struct import unpack_from

from .cfb import CfbError, CompoundFile
from .foreign import Conversion

UNIT_MM = 2.54e-6  # one Altium unit (1/10000 mil) in mm
NONE16 = 0xFFFF
# Altium layer numbers (V6) -> our layers: C1 1, S1 2, C2 3, S2 4, I1 5, I2 6, O 7.
TOP, BOTTOM, TOP_OVERLAY, BOTTOM_OVERLAY, MULTI_LAYER = 1, 32, 33, 34, 74
KEEPOUT = 56
SIDE_LAYERS = {TOP: 1, BOTTOM: 3, TOP_OVERLAY: 2, BOTTOM_OVERLAY: 4}
OUTLINE_WIDTH = 0.1  # mm, width of the board contour drawn on layer O
DEFAULT_TEXT_HEIGHT = 1.0
# Capitals of a TrueType text take this part of its height (Arial 1.65 mm: 1.08 mm capitals
# in the Gerber that Altium wrote).
TRUETYPE_CAPS = 0.655


class AltiumError(ValueError):
    pass


def _props(data: bytes) -> list[dict[str, str]]:
    result, pos = [], 0
    while pos + 4 <= len(data):
        length = unpack_from("<I", data, pos)[0] & 0xFFFFFF
        text = data[pos + 4 : pos + 4 + length].rstrip(b"\0").decode("cp1251", "replace")
        pos += 4 + length
        values: dict[str, str] = {}
        for part in text.split("|"):
            if "=" in part:
                key, value = part.split("=", 1)
                values[key.upper()] = value
        result.append(values)
    return result


SUBRECORDS = {2: 6, 5: 2}  # pads and texts have several parts, others one


def _records(data: bytes) -> list[tuple[int, list[bytes]]]:
    result, pos = [], 0
    while pos < len(data):
        kind = data[pos]
        pos += 1
        parts = []
        for _ in range(SUBRECORDS.get(kind, 1)):
            if pos + 4 > len(data):
                raise AltiumError("Обрезанная запись в файле Altium")
            length = unpack_from("<I", data, pos)[0]
            parts.append(data[pos + 4 : pos + 4 + length])
            pos += 4 + length
        result.append((kind, parts))
    return result


def _mil(value: str) -> float:
    """A length property such as "1234.5mil" or "3mm", in mm."""
    value = value.strip().lower()
    if value.endswith("mm"):
        return float(value[:-2])
    if value.endswith("mil"):
        value = value[:-3]
    return float(value) * 0.0254


def _text(data: bytes) -> str:
    if not data:
        return ""
    length = data[0]
    return data[1 : 1 + length].decode("cp1251", "replace")


def _unicode(values: dict[str, str], key: str) -> str:
    """Property text; Altium stores non-ASCII names as UNICODE__KEY=code,code,..."""
    codes = values.get(f"UNICODE__{key}")
    if codes:
        try:
            return "".join(chr(int(c)) for c in codes.split(",") if c)
        except ValueError:
            pass
    return values.get(key, "")


def _name(values: dict[str, str], key: str) -> str:
    """Polygon and similar names stored as character codes "78,79,..." or plain text."""
    value = values.get(key, "")
    if value and all(part.strip().isdigit() for part in value.split(",")):
        return "".join(chr(int(part)) for part in value.split(","))
    return value


class _Frame:
    """Altium units to Text-IO numbers: 1/10000 mm from the top left corner, y down."""

    def __init__(self, left: float, top: float):
        self.left, self.top = left, top

    def x(self, value: float) -> int:
        return round((value * UNIT_MM - self.left) * 10000)

    def y(self, value: float) -> int:
        return round((self.top - value * UNIT_MM) * 10000)

    def pos(self, x: float, y: float) -> str:
        return f"{self.x(x)}/{self.y(y)}"


def _n(mm: float) -> int:
    return round(mm * 10000)


def _angle_cw(degrees_ccw: float) -> int:
    """Pad rotation of Text-IO: 1/100 degree clockwise."""
    return round((-degrees_ccw) % 360 * 100) % 36000


def _outline(board: dict[str, str]) -> list[tuple[str, tuple]]:
    """Board contour from Board6: ("line", (x1, y1, x2, y2)) and ("arc", ...) in mm, y up."""
    count = 0
    while f"VX{count}" in board:
        count += 1
    pieces: list[tuple[str, tuple]] = []
    for i in range(count - 1):
        x1, y1 = _mil(board[f"VX{i}"]), _mil(board[f"VY{i}"])
        x2, y2 = _mil(board[f"VX{i + 1}"]), _mil(board[f"VY{i + 1}"])
        if board.get(f"KIND{i}") == "1":
            cx, cy = _mil(board[f"CX{i}"]), _mil(board[f"CY{i}"])
            r = _mil(board[f"R{i}"])
            sa, ea = float(board[f"SA{i}"]), float(board[f"EA{i}"])
            pieces.append(("arc", (cx, cy, r, sa, ea)))
        elif hypot(x2 - x1, y2 - y1) > 1e-6:
            pieces.append(("line", (x1, y1, x2, y2)))
    return pieces


def _keyhole(
    outer: list[tuple[float, float]], holes: list[list[tuple[float, float]]]
) -> list[tuple[float, float]]:
    """One contour with the holes joined to the outline by zero-width cuts."""
    ring = list(outer)
    for hole in sorted(holes, key=lambda h: min(x for x, _ in h)):
        if len(hole) < 3:
            continue
        best = None
        for hi, (hx, hy) in enumerate(hole):
            for ri, (rx, ry) in enumerate(ring):
                d = (hx - rx) ** 2 + (hy - ry) ** 2
                if best is None or d < best[0]:
                    best = (d, hi, ri)
        assert best is not None
        _, hi, ri = best
        turned = hole[hi:] + hole[:hi]
        ring = ring[: ri + 1] + turned + [turned[0], ring[ri]] + ring[ri + 1 :]
    return ring


def _chains(segments: list[tuple[tuple, tuple]]) -> list[list[tuple]]:
    """Join track segments that meet end to end into polylines."""
    ends: dict[tuple, list[int]] = defaultdict(list)
    for i, (a, b) in enumerate(segments):
        ends[a].append(i)
        ends[b].append(i)
    used = [False] * len(segments)
    result = []
    for i in range(len(segments)):
        if used[i]:
            continue
        used[i] = True
        a, b = segments[i]
        line = [a, b]
        for forward in (True, False):
            while True:
                tip = line[-1] if forward else line[0]
                nxt = next((j for j in ends[tip] if not used[j]), None)
                if nxt is None or len(ends[tip]) != 2:
                    break
                used[nxt] = True
                p, q = segments[nxt]
                other = q if p == tip else p
                if forward:
                    line.append(other)
                else:
                    line.insert(0, other)
        result.append(line)
    return result


def convert(data: bytes, name: str = "Altium") -> Conversion:
    try:
        cfb = CompoundFile(data)
    except CfbError as error:
        raise AltiumError(f"Не файл Altium Designer: {error}") from error
    if not cfb.has("Board6/Data"):
        raise AltiumError("Нет данных платы (Board6): это не двоичный .PcbDoc")
    report: Counter = Counter()

    def stream(path: str) -> bytes:
        return cfb.stream(path) if cfb.has(path) else b""

    board = (_props(stream("Board6/Data")) or [{}])[0]
    components = _props(stream("Components6/Data"))
    nets = [values.get("NAME", "") for values in _props(stream("Nets6/Data"))]
    polygons = _props(stream("Polygons6/Data"))

    def net_name(index: int) -> str | None:
        return nets[index] if index < len(nets) else None

    # Mid layers in use become I1 and I2.
    used_mid: set[int] = set()
    raw: dict[str, list] = {}
    for key in ("Tracks6", "Arcs6", "Pads6", "Vias6", "Texts6", "Fills6", "Regions6"):
        raw[key] = _records(stream(f"{key}/Data"))
        for kind, parts in raw[key]:
            body = parts[4] if kind == 2 and len(parts) > 4 else parts[0]
            if body and 2 <= body[0] <= 31:
                used_mid.add(body[0])
    mid = sorted(used_mid)
    layers = dict(SIDE_LAYERS)
    for altium_layer, ours in zip(mid, (5, 6), strict=False):
        layers[altium_layer] = ours
    if len(mid) > 2:
        report[f"внутренние слои сверх двух ({len(mid) - 2}) пропущены"] += 1

    # Board frame: the contour, else everything.
    contour = _outline(board)
    xs: list[float] = []
    ys: list[float] = []
    for kind, geo in contour:
        if kind == "line":
            xs += [geo[0], geo[2]]
            ys += [geo[1], geo[3]]
        else:
            cx, cy, r = geo[:3]
            xs += [cx - r, cx + r]
            ys += [cy - r, cy + r]
    if not xs:
        for kind, parts in raw["Pads6"] + raw["Tracks6"]:
            body = parts[4] if kind == 2 else parts[0]
            x, y = unpack_from("<2i", body, 13)
            xs.append(x * UNIT_MM)
            ys.append(y * UNIT_MM)
    if not xs:
        raise AltiumError("На плате нет объектов")
    margin = 2.0
    left, right = min(xs) - margin, max(xs) + margin
    bottom, top = min(ys) - margin, max(ys) + margin
    frame = _Frame(left, top)

    def mm_pos(x: float, y: float) -> str:
        return f"{_n(x - left)}/{_n(top - y)}"

    loose: list[tuple[str, str | None]] = []
    by_component: dict[int, list[tuple[str, str | None]]] = defaultdict(list)
    labels: dict[int, dict[str, str]] = defaultdict(dict)

    def put(line: str, component: int, net: str | None = None) -> None:
        if component != NONE16 and component < len(components):
            by_component[component].append((line, net))
        else:
            loose.append((line, net))

    def layer_of(altium: int, what: str) -> int | None:
        ours = layers.get(altium)
        if ours is None:
            report[f"{what} на слоях без соответствия (механические, запретные и т. п.)"] += 1
        return ours

    # Contour on layer O.
    for kind, geo in contour:
        if kind == "line":
            x1, y1, x2, y2 = geo
            loose.append(
                (
                    f"TRACK,LAYER=7,WIDTH={_n(OUTLINE_WIDTH)},P0={mm_pos(x1, y1)},"
                    f"P1={mm_pos(x2, y2)};",
                    None,
                )
            )
        else:
            cx, cy, r, sa, ea = geo
            loose.append((_circle_line(7, mm_pos(cx, cy), r, OUTLINE_WIDTH, sa, ea), None))

    # Tracks, joined into polylines where they meet.
    groups: dict[tuple, list] = defaultdict(list)
    for _, parts in raw["Tracks6"]:
        s = parts[0]
        net, _polygon, component = unpack_from("<3H", s, 3)
        x1, y1, x2, y2, width = unpack_from("<5i", s, 13)
        if s[2] == 2 or s[0] == KEEPOUT:
            report["запретные дорожки (keepout) пропущены"] += 1
            continue
        layer = layer_of(s[0], "дорожки")
        if layer is None:
            continue
        groups[(layer, width, component, net)].append(((x1, y1), (x2, y2)))
    for (layer, width, component, _net), segments in groups.items():
        for chain in _chains(segments):
            points = ",".join(f"P{k}={frame.pos(*p)}" for k, p in enumerate(chain))
            put(f"TRACK,LAYER={layer},WIDTH={_n(width * UNIT_MM)},{points};", component)

    # Arcs.
    for _, parts in raw["Arcs6"]:
        s = parts[0]
        component = unpack_from("<H", s, 7)[0]
        cx, cy, r = unpack_from("<3i", s, 13)
        sa, ea = unpack_from("<2d", s, 25)
        width = unpack_from("<i", s, 41)[0]
        if s[2] == 2 or s[0] == KEEPOUT:
            report["запретные дуги (keepout) пропущены"] += 1
            continue
        layer = layer_of(s[0], "дуги")
        if layer is None:
            continue
        put(
            _circle_line(layer, frame.pos(cx, cy), r * UNIT_MM, width * UNIT_MM, sa, ea),
            component,
        )

    # Pads.
    for _, parts in raw["Pads6"]:
        if len(parts) < 5 or len(parts[4]) < 63:
            report["площадки неизвестного вида пропущены"] += 1
            continue
        s, extra = parts[4], parts[5] if len(parts) > 5 else b""
        net, component = unpack_from("<H", s, 3)[0], unpack_from("<H", s, 7)[0]
        x, y, tx, ty = unpack_from("<4i", s, 13)
        hole = unpack_from("<i", s, 45)[0] * UNIT_MM
        shape, direction, plated = s[49], unpack_from("<d", s, 52)[0], s[60]
        w, h = tx * UNIT_MM, ty * UNIT_MM
        pad_net = net_name(net) if net != NONE16 else None
        if hole > 0:
            if not (tx and ty) and s[102] == 2 and unpack_from("<i", s, 90)[0] > 0:
                report["окна маски вокруг отверстий без меди не переносятся"] += 1
            if len(extra) > 262 and extra[262] == 2:
                report["пазы (продолговатые отверстия) заменены круглыми"] += 1
            bx, by = unpack_from("<2i", s, 37)
            side = 1
            if s[62] != 0 and (tx, ty) != (bx, by):
                if not (tx and ty) and bx and by:
                    side, w, h = 3, bx * UNIT_MM, by * UNIT_MM  # copper on the bottom only
                elif tx and ty and not (bx and by):
                    pass  # copper on the top only
                else:
                    report["площадки с разной медью сверху и снизу взяты по верхней"] += 1
                    side = 0
                if side:
                    report["односторонние площадки (медь только на одной стороне)"] += 1
            else:
                side = 0
            put_lines = _tht_pad(
                frame.pos(x, y), w, h, hole, shape, direction, plated, report, side
            )
            for k, line in enumerate(put_lines):
                put(line, component, pad_net if k == 0 else None)
            continue
        layer = layers.get(s[0]) if s[0] in (TOP, BOTTOM) else None
        if layer is None:
            report["SMD-площадки не на медных слоях пропущены"] += 1
            continue
        if shape != 2:
            report["круглые и скруглённые SMD-площадки стали прямоугольными"] += 1
        line = (
            f"SMDPAD,LAYER={layer},POS={frame.pos(x, y)},SIZE_X={_n(w)},SIZE_Y={_n(h)}"
            + (f",ROTATION={_angle_cw(direction)}" if _angle_cw(direction) else "")
            + ";"
        )
        put(line, component, pad_net)

    # Vias: plated pads.
    for _, parts in raw["Vias6"]:
        s = parts[0]
        net = unpack_from("<H", s, 3)[0]
        x, y, diameter, hole = unpack_from("<4i", s, 13)
        if (s[29], s[30]) not in ((TOP, BOTTOM), (BOTTOM, TOP)):
            report["глухие и скрытые переходы стали сквозными"] += 1
        # Flags 0x20 and 0x40: the via is covered by the solder mask on top and bottom.
        if diameter <= hole:
            report["переходы без медного пояска стали отверстиями без металлизации"] += 1
        tented = s[1] & 0x60 == 0x60
        mask = ",SOLDERMASK=false" if tented else ""
        loose.append(
            (
                f"PAD,LAYER=1,POS={frame.pos(x, y)},FORM=1,SIZE={_n(diameter * UNIT_MM)},"
                f"DRILL={_n(hole * UNIT_MM)},VIA=true{mask};",
                net_name(net) if net != NONE16 else None,
            )
        )

    # Fills: filled rectangles.
    for _, parts in raw["Fills6"]:
        s = parts[0]
        component = unpack_from("<H", s, 7)[0]
        x1, y1, x2, y2 = unpack_from("<4i", s, 13)
        rotation = unpack_from("<d", s, 29)[0] if len(s) >= 37 else 0.0
        layer = layer_of(s[0], "заливки")
        if layer is None:
            continue
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        hw, hh = abs(x2 - x1) / 2, abs(y2 - y1) / 2
        c, sn = cos(radians(rotation)), sin(radians(rotation))
        corners = [
            (cx + dx * c - dy * sn, cy + dx * sn + dy * c)
            for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))
        ]
        points = ",".join(f"P{k}={frame.pos(*p)}" for k, p in enumerate(corners))
        put(f"ZONE,LAYER={layer},WIDTH=0,{points};", component)

    # Regions: copper areas and poured polygons (holes joined by cuts), board cut-outs.
    for _, parts in raw["Regions6"]:
        s = parts[0]
        component = unpack_from("<H", s, 7)[0]
        holes = unpack_from("<H", s, 14)[0]
        length = unpack_from("<I", s, 18)[0]
        values = {}
        for part in s[22 : 22 + length].rstrip(b"\0").decode("cp1251", "replace").split("|"):
            if "=" in part:
                key, value = part.split("=", 1)
                values[key.upper()] = value
        pos = 22 + length
        count = unpack_from("<I", s, pos)[0]
        pos += 4
        outer = [unpack_from("<2d", s, pos + 16 * i) for i in range(count)]
        pos += 16 * count
        cutouts = []
        for _ in range(holes):
            n = unpack_from("<I", s, pos)[0]
            pos += 4
            cutouts.append([unpack_from("<2d", s, pos + 16 * i) for i in range(n)])
            pos += 16 * n
        if values.get("ISBOARDCUTOUT", "").upper() == "TRUE":
            ring = [*outer, outer[0]]
            points = ",".join(f"P{k}={frame.pos(*p)}" for k, p in enumerate(ring))
            loose.append((f"TRACK,LAYER=7,WIDTH={_n(OUTLINE_WIDTH)},{points};", None))
            continue
        if values.get("KIND", "0") != "0" or s[0] == KEEPOUT or s[2] == 2:
            report["запретные области и вырезы полигонов пропущены"] += 1
            continue
        layer = layer_of(s[0], "области")
        if layer is None or len(outer) < 3:
            continue
        ring = _keyhole(outer, cutouts)
        points = ",".join(f"P{k}={frame.pos(*p)}" for k, p in enumerate(ring))
        put(f"ZONE,LAYER={layer},WIDTH=0,{points};", component)
    if polygons:
        report["полигоны перенесены залитыми, как в Altium (без перезаливки)"] += len(polygons)

    # Texts.
    for _, parts in raw["Texts6"]:
        s = parts[0]
        component = unpack_from("<H", s, 7)[0]
        x, y, height = unpack_from("<3i", s, 13)
        rotation = unpack_from("<d", s, 27)[0]
        mirrored, stroke = s[35], unpack_from("<i", s, 36)[0]
        is_comment, is_designator = len(s) > 41 and s[40], len(s) > 41 and s[41]
        truetype = len(s) > 43 and s[43] == 1
        text = _text(parts[1]).replace("|", "/")
        layer = layers.get(s[0])
        in_component = component != NONE16 and component < len(components)
        if in_component and (is_designator or is_comment):
            if layer is None:
                continue
            key = "ID_TEXT" if is_designator else "VALUE_TEXT"
            if key == "ID_TEXT":
                text = _unicode(components[component], "SOURCEDESIGNATOR") or text
            labels[component][key] = _text_line(
                key,
                layer,
                frame.pos(x, y),
                height * UNIT_MM,
                stroke * UNIT_MM,
                rotation,
                bool(mirrored),
                text,
                truetype,
            )
            if key == "VALUE_TEXT":
                labels[component]["comment"] = text
            continue
        if layer is None:
            report["тексты на слоях без соответствия"] += 1
            continue
        if text.startswith(".") and in_component:
            report["служебные тексты (.Designator и т. п.) пропущены"] += 1
            continue
        if truetype:
            report["тексты шрифтом TrueType переданы штриховым шрифтом"] += 1
        put(
            _text_line(
                "TEXT",
                layer,
                frame.pos(x, y),
                height * UNIT_MM,
                stroke * UNIT_MM,
                rotation,
                bool(mirrored),
                text,
                truetype,
            ),
            component,
        )

    # Text-IO: loose objects, then components with their labels.
    lines: list[str] = []
    line_nets: list[str | None] = []
    for line, net in loose:
        lines.append(line)
        line_nets.append(net)
    for index, values in enumerate(components):
        members = by_component.get(index, [])
        if not members:
            continue
        side = 4 if values.get("LAYER", "TOP").upper() == "BOTTOM" else 2
        own = labels.get(index, {})
        comment = own.get("comment", "")
        package = _unicode(values, "PATTERN")
        head = "BEGIN_COMPONENT"
        if comment:
            head += f",COMMENT=|{comment}|"
        if package:
            head += f",PACKAGE=|{package}|"
        lines.append(head + ";")
        line_nets.append(None)
        for line, net in members:
            lines.append("   " + line)
            line_nets.append(net)
        cx, cy = _mil(values.get("X", "0")), _mil(values.get("Y", "0"))
        designator = _unicode(values, "SOURCEDESIGNATOR")
        id_line = own.get("ID_TEXT") or _hidden_label("ID_TEXT", side, mm_pos(cx, cy), designator)
        value_line = own.get("VALUE_TEXT") or _hidden_label("VALUE_TEXT", side, mm_pos(cx, cy), "")
        if values.get("NAMEON", "TRUE").upper() != "TRUE":
            id_line = id_line.replace("ID_TEXT,", "ID_TEXT,VISIBLE=false,", 1)
        if values.get("COMMENTON", "FALSE").upper() != "TRUE":
            value_line = value_line.replace("VALUE_TEXT,", "VALUE_TEXT,VISIBLE=false,", 1)
        for line in (id_line, value_line):
            lines.append("   " + line)
            line_nets.append(None)
        lines.append("END_COMPONENT;")
        line_nets.append(None)
    # Only object lines produce objects; keep nets for them alone.
    object_nets = [
        net
        for line, net in zip(lines, line_nets, strict=True)
        if not line.strip().startswith(("BEGIN_COMPONENT", "END_COMPONENT"))
    ]
    return Conversion(
        name=name,
        width=round(right - left, 4),
        height=round(top - bottom, 4),
        text="\r\n".join(lines) + "\r\n",
        multilayer=bool(mid),
        nets=object_nets,
        report=+report,
    )


def _circle_line(layer: int, centre: str, radius: float, width: float, sa: float, ea: float) -> str:
    line = f"CIRCLE,LAYER={layer},CENTER={centre},RADIUS={_n(radius)},WIDTH={_n(width)}"
    if (ea - sa) % 360 > 1e-6:
        line += f",START={round((sa % 360) * 1000)},STOP={round((ea % 360) * 1000)}"
    return line + ";"


def _tht_pad(
    pos: str,
    w: float,
    h: float,
    hole: float,
    shape: int,
    direction: float,
    plated: int,
    report: Counter,
    side: int = 0,
) -> list[str]:
    """A through-hole pad; long pads of another proportion than 2:1 get copper tracks.

    side 0: copper on both sides; 1 or 3: copper on that side only (an unplated pad).
    """
    via = ",VIA=true" if plated and not side else ""
    pad_layer = side or 1
    if w <= 0 or h <= 0:
        return [f"PAD,LAYER={pad_layer},POS={pos},FORM=1,SIZE={_n(hole)},DRILL={_n(hole)};"]
    angle = direction
    if h > w:
        w, h, angle = h, w, direction + 90
    ratio = w / h
    rotation = _angle_cw(angle)
    rot = f",ROTATION={rotation}" if rotation else ""
    if ratio < 1.05 and not plated and not side and w > hole:
        # An unplated hole with copper on both sides: our unplated pads have copper on
        # their own side only, so the other side gets a copper ring of the same size.
        report["неметаллизированные отверстия с медью с двух сторон: кольцо на C2"] += 1
        form = {1: 1, 2: 3, 3: 2}.get(shape, 1)
        x, y = (int(v) for v in pos.split("/"))
        return [
            f"PAD,LAYER=1,POS={pos},FORM={form},SIZE={_n(w)},DRILL={_n(hole)}{rot};",
            f"CIRCLE,LAYER=3,SOLDERMASK=true,CENTER={pos},RADIUS={_n((w + hole) / 4)},"
            f"WIDTH={_n((w - hole) / 2)};",
        ]
    if ratio < 1.05:
        form = {1: 1, 2: 3, 3: 2}.get(shape, 1)
        return [
            f"PAD,LAYER={pad_layer},POS={pos},FORM={form},SIZE={_n(w)},DRILL={_n(hole)}{via}{rot};"
        ]
    if abs(ratio - 2) < 0.2:
        form = {1: 4, 2: 6, 3: 5}.get(shape, 4)
        return [
            f"PAD,LAYER={pad_layer},POS={pos},FORM={form},SIZE={_n(h)},DRILL={_n(hole)}{via}{rot};"
        ]
    # Another proportion: a round (or square) pad of the small size, and the long copper
    # as a track of the pad's width on both sides, with an opening in the solder mask.
    report["продолговатые площадки дополнены дорожками (пропорция не 2:1)"] += 1
    form = 3 if shape == 2 else 1
    lines = [
        f"PAD,LAYER={pad_layer},POS={pos},FORM={form},SIZE={_n(h)},DRILL={_n(hole)}{via}{rot};"
    ]
    x, y = (int(v) for v in pos.split("/"))
    half = (w - h) / 2 * 10000
    a = radians(angle)
    dx, dy = round(half * cos(a)), round(-half * sin(a))  # Text-IO y points down
    for layer in (side,) if side else (1, 3):
        lines.append(
            f"TRACK,LAYER={layer},SOLDERMASK=true,WIDTH={_n(h)},"
            f"P0={x - dx}/{y - dy},P1={x + dx}/{y + dy};"
        )
    return lines


def _text_line(
    kind: str,
    layer: int,
    pos: str,
    height: float,
    stroke: float,
    rotation: float,
    mirrored: bool,
    text: str,
    truetype: bool = False,
) -> str:
    """A text with letters of the same size as Altium's on the board.

    Altium's stroke text height runs between the stroke centres, so its letters stand
    height + stroke tall; ours stand exactly the text height tall (with their stroke). A
    TrueType height is the font's whole line: its capitals take TRUETYPE_CAPS of it.
    """
    height = height or DEFAULT_TEXT_HEIGHT
    spacing = 1
    if truetype:
        height *= TRUETYPE_CAPS
        weight = 1
        spacing = 2  # TrueType letters are wider than ours: wide spacing comes closest
    else:
        ratio = stroke / height if height else 0.11
        weight = 0 if ratio < 0.085 else (1 if ratio < 0.135 else 2)
        # Our letters with their strokes stand about 5 % above the text height.
        height = (height + stroke) / 1.05
    line = f"{kind},LAYER={layer},POS={pos},HEIGHT={_n(height)}"
    if weight != 1:
        line += f",THICKNESS={weight}"
    if spacing != 1:
        line += f",STYLE={spacing}"
    if mirrored:
        line += ",MIRROR_HORZ=true"
    turn = round(((-rotation) % 360) * 1000) % 360000
    if turn:
        line += f",ROTATION={turn}"
    return line + f",TEXT=|{text}|;"


def _hidden_label(kind: str, layer: int, pos: str, text: str) -> str:
    return f"{kind},VISIBLE=false,LAYER={layer},POS={pos},HEIGHT={_n(1.0)},TEXT=|{text}|;"


def convert_file(path: Path) -> Conversion:
    return convert(path.read_bytes(), path.stem)
