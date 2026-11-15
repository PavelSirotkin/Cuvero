"""Common builder for boards from other programs (KiCad, Eagle).

Converters call it with lengths in mm and y upwards; it writes Text-IO text (see
textio.py), which builds the objects, components and their labels with the checked import
code. Text-IO measures from the board's top left corner in 1/10000 mm with y downwards.
"""

from bisect import bisect_left
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from math import atan2, cos, degrees, hypot, radians, sin

from .texts import text_points

Point = tuple[float, float]
COPPER = (1, 3, 5, 6)
OUTLINE_WIDTH = 0.1  # mm, the board contour on layer O
MARGIN = 2.0  # mm of work area around the board
INK = 1.05  # our letters with their strokes stand this many text heights tall


class ForeignError(ValueError):
    pass


@dataclass
class Conversion:
    """Text-IO text of the board and what could not be carried over."""

    name: str
    width: float  # mm
    height: float
    text: str
    multilayer: bool
    nets: list[str | None]  # net name of every object line, in text order (pads only)
    report: Counter = field(default_factory=Counter)
    planes: dict[int, float] = field(default_factory=dict)  # layer -> clearance in mm


def n(mm: float) -> int:
    return round(mm * 10000)


def angle_cw(degrees_ccw: float) -> int:
    """Rotation of Text-IO pads: 1/100 degree clockwise."""
    return round((-degrees_ccw) % 360 * 100) % 36000


def distinct(points: Sequence[Point], closed: bool = False) -> list[Point]:
    """Points at the Text-IO step (1/10000 mm) without repeats in a row (and, closed,
    without a last point equal to the first): zero-length edges upset the original."""
    result: list[Point] = []
    for x, y in points:
        point = (round(x, 4), round(y, 4))
        if not result or result[-1] != point:
            result.append(point)
    if closed:
        while len(result) > 1 and result[-1] == result[0]:
            result.pop()
    return result


def _closest_pair(hole: Sequence[Point], ring: Sequence[Point]) -> tuple[int, int]:
    """Indices of the closest hole and ring points (the first such pair in hole order, then
    ring order), found by walking outward from each hole point along the ring sorted by x."""
    order = sorted(range(len(ring)), key=lambda i: ring[i][0])
    xs = [ring[i][0] for i in order]
    best: tuple[float, int, int] | None = None
    for hi, (hx, hy) in enumerate(hole):
        start = bisect_left(xs, hx)
        for step in (-1, 1):
            k = start if step == 1 else start - 1
            while 0 <= k < len(order):
                dx = xs[k] - hx
                if best is not None and dx * dx > best[0]:
                    break
                ri = order[k]
                d = dx * dx + (ring[ri][1] - hy) ** 2
                if best is None or (d, hi, ri) < best:
                    best = (d, hi, ri)
                k += step
    assert best is not None
    return best[1], best[2]


def keyhole(outer: Sequence[Point], holes: Sequence[Sequence[Point]]) -> list[Point]:
    """One contour with the holes joined to the outline by zero-width cuts."""
    ring = list(outer)
    for hole in sorted(holes, key=lambda h: min(x for x, _ in h)):
        if len(hole) < 3:
            continue
        hi, ri = _closest_pair(hole, ring)
        turned = list(hole[hi:]) + list(hole[:hi])
        ring = ring[: ri + 1] + turned + [turned[0], ring[ri]] + ring[ri + 1 :]
    return ring


def chains(segments: list[tuple[tuple, tuple]]) -> list[list[tuple]]:
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


def arc_through(start: Point, mid: Point, end: Point) -> tuple[Point, float, float, float]:
    """Centre, radius and counter-clockwise start and end angle of the arc through 3 points."""
    (ax, ay), (bx, by), (cx, cy) = start, mid, end
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        raise ForeignError("Дуга по трём точкам на одной прямой")
    sa, sb, sc = ax**2 + ay**2, bx**2 + by**2, cx**2 + cy**2
    ux = (sa * (by - cy) + sb * (cy - ay) + sc * (ay - by)) / d
    uy = (sa * (cx - bx) + sb * (ax - cx) + sc * (bx - ax)) / d
    r = hypot(ax - ux, ay - uy)
    a0 = degrees(atan2(ay - uy, ax - ux)) % 360
    a1 = degrees(atan2(by - uy, bx - ux)) % 360
    a2 = degrees(atan2(cy - uy, cx - ux)) % 360
    # Counter-clockwise from a0 through a1 to a2, or else the other way round.
    if (a1 - a0) % 360 <= (a2 - a0) % 360:
        return (ux, uy), r, a0, a2
    return (ux, uy), r, a2, a0


Line = Callable[["Frame"], str]


class Frame:
    def __init__(self, left: float, top: float):
        self.left, self.top = left, top

    def pos(self, x: float, y: float) -> str:
        return f"{n(x - self.left)}/{n(self.top - y)}"


@dataclass
class _Item:
    line: Line
    net: str | None = None
    points: list[Point] = field(default_factory=list)  # for the board extent


class Builder:
    """Objects of a foreign board, collected in mm with y up, written as Text-IO."""

    def __init__(self, name: str):
        self.name = name
        self.loose: list[_Item] = []
        self.parts: dict[str, list[_Item]] = defaultdict(list)
        self.part_info: dict[str, dict] = {}
        self.outline: list[Point] = []
        self.report: Counter = Counter()
        self.multilayer = False
        self.planes: dict[int, float] = {}
        self.segments: dict[tuple, list[tuple[Point, Point]]] = defaultdict(list)

    # --- collecting -----------------------------------------------------------------

    def _put(self, item: _Item, part: str | None) -> None:
        if part is not None and part in self.part_info:
            self.parts[part].append(item)
        else:
            self.loose.append(item)

    @staticmethod
    def _extras(clear: float | None, mask: bool | None, thermal: bool = False) -> str:
        text = ""
        if clear is not None:
            text += f",CLEAR={n(clear)}"
        if mask is not None:
            text += f",SOLDERMASK={'true' if mask else 'false'}"
        if thermal:
            text += ",THERMAL=true"
        return text

    def component(self, key: str, designator: str, value: str, package: str, top: bool) -> None:
        self.part_info[key] = {
            "designator": designator,
            "value": value,
            "package": package,
            "side": 2 if top else 4,
            "labels": {},
        }

    def label(
        self,
        part: str,
        kind: str,
        layer: int,
        x: float,
        y: float,
        ink: float,
        angle: float,
        mirrored: bool,
        visible: bool,
        justify: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        """The designator (ID_TEXT) or value (VALUE_TEXT) label of a component."""
        info = self.part_info.get(part)
        if info is None:
            return
        text = info["designator"] if kind == "ID_TEXT" else info["value"]
        line = self._text_line(kind, layer, x, y, text, ink, angle, mirrored, justify, 1)
        if not visible:

            def hidden(f: Frame, base: Line = line, k: str = kind) -> str:
                return base(f).replace(f"{k},", f"{k},VISIBLE=false,", 1)

            self.part_info[part]["labels"][kind] = hidden
        else:
            self.part_info[part]["labels"][kind] = line

    def track(
        self,
        layer: int,
        points: Sequence[Point],
        width: float,
        part: str | None = None,
        clear: float | None = None,
    ) -> None:
        pts = distinct(points)
        if len(pts) < 2:
            return  # a zero-length track
        if len(pts) == 2 and part is None and clear is None:
            # Single segments are joined into polylines when the board is written.
            self.segments[(layer, round(width, 5))].append((pts[0], pts[1]))
            return
        self._track_item(layer, pts, width, part, clear)

    def _track_item(
        self,
        layer: int,
        pts: list[Point],
        width: float,
        part: str | None,
        clear: float | None,
    ) -> None:
        def line(f: Frame, pts: list[Point] = pts) -> str:
            points = ",".join(f"P{k}={f.pos(*p)}" for k, p in enumerate(pts))
            return f"TRACK,LAYER={layer}{self._extras(clear, None)},WIDTH={n(width)},{points};"

        self._put(_Item(line, points=list(pts)), part)
        if layer == 7:
            self.outline += list(pts)

    def arc(
        self,
        layer: int,
        centre: Point,
        radius: float,
        width: float,
        start: float,
        end: float,
        part: str | None = None,
    ) -> None:
        """An arc counter-clockwise from start to end degrees (equal: a full circle)."""
        cx, cy = centre

        def line(f: Frame) -> str:
            text = (
                f"CIRCLE,LAYER={layer},CENTER={f.pos(cx, cy)},RADIUS={n(radius)},WIDTH={n(width)}"
            )
            if (end - start) % 360 > 1e-6:
                text += f",START={round((start % 360) * 1000)},STOP={round((end % 360) * 1000)}"
            return text + ";"

        box = [(cx - radius, cy - radius), (cx + radius, cy + radius)]
        self._put(_Item(line, points=box), part)
        if layer == 7:
            self.outline += box

    def disc(
        self,
        layer: int,
        centre: Point,
        radius: float,
        part: str | None = None,
        mask: bool | None = None,
    ) -> None:
        """A filled circle."""
        cx, cy = centre

        def line(f: Frame) -> str:
            return (
                f"CIRCLE,LAYER={layer}{self._extras(None, mask)},CENTER={f.pos(cx, cy)},"
                f"RADIUS={n(radius / 2)},WIDTH={n(radius)},FILL=true;"
            )

        self._put(
            _Item(line, points=[(cx - radius, cy - radius), (cx + radius, cy + radius)]), part
        )

    def zone(
        self,
        layer: int,
        outer: Sequence[Point],
        holes: Sequence[Sequence[Point]] = (),
        part: str | None = None,
        mask: bool | None = None,
        width: float = 0.0,
    ) -> None:
        """A filled area; width draws its outline as a line of that width (on its centre)."""
        outer = distinct(outer, closed=True)
        holes = [h for h in (distinct(hole, closed=True) for hole in holes) if len(h) >= 3]
        if len(outer) < 3:
            return
        ring = distinct(keyhole(outer, holes) if holes else outer, closed=True)

        def line(f: Frame) -> str:
            points = ",".join(f"P{k}={f.pos(*p)}" for k, p in enumerate(ring))
            return f"ZONE,LAYER={layer}{self._extras(None, mask)},WIDTH={n(width)},{points};"

        self._put(_Item(line, points=list(outer)), part)

    def smd(
        self,
        layer: int,
        x: float,
        y: float,
        w: float,
        h: float,
        angle: float,
        part: str | None,
        net: str | None,
        clear: float | None = None,
        thermal: bool = False,
    ) -> None:
        rotation = angle_cw(angle)

        def line(f: Frame) -> str:
            return (
                f"SMDPAD,LAYER={layer}{self._extras(clear, None, thermal)},POS={f.pos(x, y)},"
                f"SIZE_X={n(w)},SIZE_Y={n(h)}" + (f",ROTATION={rotation}" if rotation else "") + ";"
            )

        self._put(_Item(line, net, [(x, y)]), part)

    def tht(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        drill: float,
        shape: str,
        angle: float,
        plated: bool,
        part: str | None,
        net: str | None,
        clear: float | None = None,
        thermal: bool = False,
        mask: bool | None = None,
    ) -> None:
        """A through-hole pad: shape "round", "rect", "octagon" (oval when w != h)."""
        if w <= 0 or h <= 0 or max(w, h) <= drill:
            # No copper ring: a plain hole.
            self._pad_line(x, y, 1, drill, drill, 0, False, part, None, clear, False, None)
            return
        if h > w:
            w, h, angle = h, w, angle + 90
        ratio = w / h
        if ratio < 1.05:
            form = {"rect": 3, "octagon": 2}.get(shape, 1)
            self._pad_line(x, y, form, w, drill, angle, plated, part, net, clear, thermal, mask)
            return
        if abs(ratio - 2) < 0.2:
            form = {"rect": 6, "octagon": 5}.get(shape, 4)
            self._pad_line(x, y, form, h, drill, angle, plated, part, net, clear, thermal, mask)
            return
        # Another proportion: a pad of the small size plus a track of its width on both
        # sides, with an opening in the solder mask.
        self.report["продолговатые площадки дополнены дорожками (пропорция не 2:1)"] += 1
        form = 3 if shape == "rect" else 1
        self._pad_line(x, y, form, h, drill, angle, plated, part, net, clear, thermal, mask)
        half = (w - h) / 2
        a = radians(angle)
        dx, dy = half * cos(a), half * sin(a)
        for layer in (1, 3):
            pts = [(x - dx, y - dy), (x + dx, y + dy)]

            def line(f: Frame, layer: int = layer, pts: list[Point] = pts) -> str:
                return (
                    f"TRACK,LAYER={layer}{self._extras(clear, True)},WIDTH={n(h)},"
                    f"P0={f.pos(*pts[0])},P1={f.pos(*pts[1])};"
                )

            self._put(_Item(line, points=pts), part)

    def _pad_line(
        self,
        x: float,
        y: float,
        form: int,
        size: float,
        drill: float,
        angle: float,
        plated: bool,
        part: str | None,
        net: str | None,
        clear: float | None,
        thermal: bool,
        mask: bool | None,
    ) -> None:
        rotation = angle_cw(angle)

        def line(f: Frame) -> str:
            return (
                f"PAD,LAYER=1{self._extras(clear, mask, thermal)},POS={f.pos(x, y)},FORM={form},"
                f"SIZE={n(size)},DRILL={n(drill)}"
                + (",VIA=true" if plated else "")
                + (f",ROTATION={rotation}" if rotation else "")
                + ";"
            )

        self._put(_Item(line, net, [(x, y)]), part)

    def via(
        self,
        x: float,
        y: float,
        diameter: float,
        drill: float,
        net: str | None,
        tented: bool = True,
        clear: float | None = None,
        thermal: bool = False,
    ) -> None:
        if diameter <= drill:
            self.report["переходы без медного пояска стали отверстиями без металлизации"] += 1
        self._pad_line(
            x, y, 1, diameter, drill, 0, True, None, net, clear, thermal, False if tented else None
        )

    def text(
        self,
        layer: int,
        x: float,
        y: float,
        text: str,
        ink: float,
        angle: float,
        mirrored: bool,
        justify: tuple[float, float] = (0.0, 0.0),
        part: str | None = None,
        spacing: int = 1,
    ) -> None:
        if not text.strip():
            return
        line = self._text_line("TEXT", layer, x, y, text, ink, angle, mirrored, justify, spacing)
        self._put(_Item(line, points=[(x, y)]), part)

    def _text_line(
        self,
        kind: str,
        layer: int,
        x: float,
        y: float,
        text: str,
        ink: float,
        angle: float,
        mirrored: bool,
        justify: tuple[float, float],
        spacing: int,
    ) -> Line:
        """A text whose letters stand ink mm tall, placed by its anchor and justification.

        justify: (horizontal, vertical) share of the text box left of and below the anchor:
        (0, 0) anchor at the bottom left, (0.5, 0.5) at the centre, (1, 1) top right.
        """
        height = max(ink / INK, 0.1)
        text = text.replace("|", "/")
        strokes = text_points(text, height, spacing) if text else []
        width = max((px for s in strokes for px, _ in s), default=0.0)
        kx, ky = justify
        # Our text starts at the left end of its baseline; mirrored, it runs to the left.
        dx = width * kx if mirrored else -width * kx
        dy = -ink * ky
        a = radians(angle)
        ox = x + dx * cos(a) - dy * sin(a)
        oy = y + dx * sin(a) + dy * cos(a)
        turn = round(((-angle) % 360) * 1000) % 360000
        extra = ""
        if spacing != 1:
            extra += f",STYLE={spacing}"
        if mirrored:
            extra += ",MIRROR_HORZ=true"
        if turn:
            extra += f",ROTATION={turn}"

        def line(f: Frame) -> str:
            return (
                f"{kind},LAYER={layer},POS={f.pos(ox, oy)},HEIGHT={n(height)}{extra},TEXT=|{text}|;"
            )

        return line

    # --- writing --------------------------------------------------------------------

    def finish(self, margin: float = MARGIN) -> Conversion:
        for (layer, width), segments in self.segments.items():
            for chain in chains(segments):
                self._track_item(layer, chain, width, None, None)
        self.segments.clear()
        items = self.loose + [item for members in self.parts.values() for item in members]
        everything = self.outline or [p for item in items for p in item.points]
        if not everything:
            raise ForeignError("На плате нет объектов")
        xs = [x for x, _ in everything]
        ys = [y for _, y in everything]
        left, right = min(xs) - margin, max(xs) + margin
        bottom, top = min(ys) - margin, max(ys) + margin
        frame = Frame(left, top)
        lines: list[str] = []
        nets: list[str | None] = []
        for item in self.loose:
            lines.append(item.line(frame))
            nets.append(item.net)
        for key, info in self.part_info.items():
            members = self.parts.get(key, [])
            if not members:
                continue
            head = "BEGIN_COMPONENT"
            if info["value"]:
                head += f",COMMENT=|{info['value'].replace('|', '/')}|"
            if info["package"]:
                head += f",PACKAGE=|{info['package'].replace('|', '/')}|"
            lines.append(head + ";")
            for item in members:
                lines.append("   " + item.line(frame))
                nets.append(item.net)
            px = sum(p[0] for m in members for p in m.points[:1]) / len(members)
            py = sum(p[1] for m in members for p in m.points[:1]) / len(members)
            for kind in ("ID_TEXT", "VALUE_TEXT"):
                label = info["labels"].get(kind)
                if label is None:
                    text = info["designator"] if kind == "ID_TEXT" else info["value"]
                    line = (
                        f"{kind},VISIBLE=false,LAYER={info['side']},POS={frame.pos(px, py)},"
                        f"HEIGHT={n(1.0)},TEXT=|{text.replace('|', '/')}|;"
                    )
                else:
                    line = label(frame)
                lines.append("   " + line)
                nets.append(None)
            lines.append("END_COMPONENT;")
        return Conversion(
            name=self.name,
            width=round(right - left, 4),
            height=round(top - bottom, 4),
            text="\r\n".join(lines) + "\r\n",
            multilayer=self.multilayer,
            nets=nets,
            report=+self.report,
            planes=dict(self.planes),
        )
