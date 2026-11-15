"""Eagle boards (.brd, XML, version 6 and newer) converted to Text-IO via the foreign builder.

Eagle measures in mm with y upwards. Parts are library packages placed by element (x, y,
rotation "R90", mirrored "MR90" for the bottom side). Eagle keeps only the outlines of its
copper polygons and pours them when it shows the board; the poured result is not in the
file. A ground polygon that covers the board becomes our automatic ground plane on its
layer: its pads get thermal relief, its tracks and vias touch the plane.
"""

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from math import atan2, cos, degrees, hypot, radians, sin
from pathlib import Path

from .foreign import OUTLINE_WIDTH, Builder, Conversion, ForeignError, Point

COPPER = {"1": 1, "16": 3}
LAYERS = {
    "1": 1,
    "16": 3,
    "21": 2,  # tPlace
    "25": 2,  # tNames
    "22": 4,  # bPlace
    "26": 4,  # bNames
    "20": 7,  # Dimension
    "46": 7,  # Milling
}
# Layers that change places when a part is mirrored to the bottom side.
FLIPPED = {
    "1": "16", "16": "1", "21": "22", "22": "21", "25": "26", "26": "25",
    "27": "28", "28": "27", "29": "30", "30": "29", "31": "32", "32": "31",
    "35": "36", "36": "35", "39": "40", "40": "39", "41": "42", "42": "41",
    "51": "52", "52": "51",
}  # fmt: skip
PLANE_SHARE = 0.5  # a polygon covering at least this part of the board becomes a plane


class EagleError(ForeignError):
    pass


def _length(value: str | None, default: float = 0.0) -> float:
    """A design rule length such as "10mil", "0.15mm" or "0.3" (mm)."""
    if not value:
        return default
    match = re.fullmatch(r"\s*([-+0-9.eE]+)\s*(mm|mil|in|inch|mic)?\s*", value)
    if not match:
        return default
    number = float(match.group(1))
    unit = match.group(2) or "mm"
    return number * {"mm": 1.0, "mil": 0.0254, "in": 25.4, "inch": 25.4, "mic": 0.001}[unit]


def _f(element: ET.Element, key: str, default: float = 0.0) -> float:
    try:
        return float(element.get(key, default))
    except ValueError:
        return default


@dataclass
class _Rotation:
    """Eagle's rot attribute: "R90", "MR180", "SR45" (spin: no turning for readability)."""

    angle: float = 0.0
    mirror: bool = False
    spin: bool = False

    @classmethod
    def parse(cls, text: str | None) -> "_Rotation":
        text = text or "R0"
        number = re.search(r"[-0-9.]+", text)
        return cls(float(number.group()) if number else 0.0, "M" in text, "S" in text)


class _Place:
    """Package coordinates to board coordinates."""

    def __init__(self, x: float = 0.0, y: float = 0.0, rot: _Rotation | None = None):
        self.x, self.y = x, y
        self.rot = rot or _Rotation()
        a = radians(self.rot.angle)
        self.c, self.s = cos(a), sin(a)

    def __call__(self, lx: float, ly: float) -> Point:
        if self.rot.mirror:
            lx = -lx
        return (
            round(self.x + lx * self.c - ly * self.s, 6),
            round(self.y + lx * self.s + ly * self.c, 6),
        )

    def angle(self, local: float) -> float:
        """A local angle on the board (mirroring turns it the other way)."""
        return (self.rot.angle + (-local if self.rot.mirror else local)) % 360

    def layer(self, layer: str) -> str:
        return FLIPPED.get(layer, layer) if self.rot.mirror else layer


BOARD = _Place()


def _arc(p1: Point, p2: Point, curve: float) -> tuple[Point, float, float, float]:
    """Centre, radius, start and end angle (counter-clockwise) of an Eagle curved wire."""
    (x1, y1), (x2, y2) = p1, p2
    chord = hypot(x2 - x1, y2 - y1)
    theta = radians(curve)
    radius = chord / (2 * sin(abs(theta) / 2))
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    # The centre lies left of the chord for a counter-clockwise arc.
    distance = radius * cos(theta / 2) * (1 if curve > 0 else -1)
    nx, ny = -(y2 - y1) / chord, (x2 - x1) / chord
    cx, cy = mx + nx * distance, my + ny * distance
    a1 = degrees(atan2(y1 - cy, x1 - cx))
    a2 = degrees(atan2(y2 - cy, x2 - cx))
    start, end = (a1, a2) if curve > 0 else (a2, a1)
    return (cx, cy), radius, start, end


def _outline(vertices: list[ET.Element], place: _Place) -> list[Point]:
    """Polygon vertices, curved edges split into short segments."""
    points: list[Point] = []
    for k, vertex in enumerate(vertices):
        p1 = place(_f(vertex, "x"), _f(vertex, "y"))
        points.append(p1)
        curve = _f(vertex, "curve")
        if curve:
            if place.rot.mirror:
                curve = -curve
            nxt = vertices[(k + 1) % len(vertices)]
            p2 = place(_f(nxt, "x"), _f(nxt, "y"))
            (cx, cy), r, a0, a1 = _arc(p1, p2, curve)
            steps = max(int(abs(curve) / 10), 2)
            sweep = (a1 - a0) % 360
            angles = [a0 + sweep * i / steps for i in range(1, steps)]
            if curve < 0:
                angles.reverse()
            points += [(cx + r * cos(radians(a)), cy + r * sin(radians(a))) for a in angles]
    return points


def _area(points: list[Point]) -> float:
    return (
        abs(
            sum(
                points[i][0] * points[(i + 1) % len(points)][1]
                - points[(i + 1) % len(points)][0] * points[i][1]
                for i in range(len(points))
            )
        )
        / 2
    )


class _Converter:
    def __init__(self, root: ET.Element, name: str):
        self.b = Builder(name)
        board = root.find("drawing/board")
        if board is None:
            raise EagleError("В файле нет платы (это схема или библиотека Eagle?)")
        self.board = board
        rules = {p.get("name"): p.get("value") for p in board.findall("designrules/param")}
        self.rules = rules
        self.packages: dict[tuple[str, str], ET.Element] = {}
        for library in board.findall("libraries/library"):
            for package in library.findall("packages/package"):
                self.packages[(library.get("name", ""), package.get("name", ""))] = package
        self.pad_nets: dict[tuple[str, str], str] = {}
        for signal in board.findall("signals/signal"):
            for ref in signal.findall("contactref"):
                self.pad_nets[(ref.get("element", ""), ref.get("pad", ""))] = signal.get("name", "")
        self.clearance = _length(rules.get("mdWireWire"), 0.2)
        self.plane_nets: dict[str, str] = {}  # our layer number (as text) -> signal
        self.thermals: dict[str, bool] = {}

    # --- planes ---------------------------------------------------------------------

    def choose_planes(self) -> None:
        """Each copper layer's largest polygon covering most of the board becomes a plane."""
        outline = [p for w in self._outline_wires() for p in w]
        if outline:
            xs = [x for x, _ in outline]
            ys = [y for _, y in outline]
            board_area = (max(xs) - min(xs)) * (max(ys) - min(ys))
        else:
            board_area = 0.0
        best: dict[str, tuple[float, ET.Element, str]] = {}
        for signal in self.board.findall("signals/signal"):
            for polygon in signal.findall("polygon"):
                layer = polygon.get("layer", "")
                if layer not in COPPER:
                    continue
                area = _area(_outline(polygon.findall("vertex"), BOARD))
                if layer not in best or area > best[layer][0]:
                    best[layer] = (area, polygon, signal.get("name", ""))
        for signal in self.board.findall("signals/signal"):
            for polygon in signal.findall("polygon"):
                layer = polygon.get("layer", "")
                if layer not in COPPER:
                    continue
                area, chosen, net = best[layer]
                if polygon is not chosen:
                    self.b.report[
                        "полигоны других цепей на слое с автозаливкой пропущены (видны связями)"
                    ] += 1
                    continue
                if board_area and area < PLANE_SHARE * board_area:
                    self.b.report["небольшие полигоны стали автозаливкой всего слоя"] += 1
                isolate = _length(polygon.get("isolate"), 0.0) or self.clearance
                self.b.planes[COPPER[layer]] = isolate
                self.plane_nets[layer] = net
                self.thermals[layer] = polygon.get("thermals", "yes") != "no"
        if self.b.planes:
            self.b.report["полигоны Eagle стали автозаливкой слоя (её зазоры — по полигону)"] += 1

    def _plane_terms(self, net: str | None, layers: tuple[str, ...]) -> tuple[float | None, bool]:
        """Clearance and thermal flag of a copper object on layers ("1", "16")."""
        on_plane = [layer for layer in layers if layer in self.plane_nets]
        if not on_plane:
            return None, False
        if net is not None and any(self.plane_nets[layer] == net for layer in on_plane):
            return 0.0, any(self.thermals[layer] for layer in on_plane)
        return max(self.b.planes[COPPER[layer]] for layer in on_plane), False

    # --- objects --------------------------------------------------------------------

    def _outline_wires(self) -> Iterator[list[Point]]:
        for wire in self.board.findall("plain/wire"):
            if wire.get("layer") in ("20", "46"):
                yield [(_f(wire, "x1"), _f(wire, "y1")), (_f(wire, "x2"), _f(wire, "y2"))]
        for element in self.board.findall("elements/element"):
            package = self._package(element)
            if package is None:
                continue
            place = self._place(element)
            for wire in package.findall("wire"):
                if wire.get("layer") in ("20", "46"):
                    yield [
                        place(_f(wire, "x1"), _f(wire, "y1")),
                        place(_f(wire, "x2"), _f(wire, "y2")),
                    ]

    def _package(self, element: ET.Element) -> ET.Element | None:
        return self.packages.get((element.get("library", ""), element.get("package", "")))

    @staticmethod
    def _place(element: ET.Element) -> _Place:
        return _Place(_f(element, "x"), _f(element, "y"), _Rotation.parse(element.get("rot")))

    def wire(
        self, wire: ET.Element, place: _Place, part: str | None, net: str | None = None
    ) -> None:
        layer_name = place.layer(wire.get("layer", ""))
        layer = LAYERS.get(layer_name)
        if layer is None:
            if layer_name != "19":  # unrouted connections: drawn by us as air wires
                self.b.report["линии на слоях без соответствия (Docu, tStop, Keepout…)"] += 1
            return
        if layer == 7:
            part = None  # the board contour belongs to the board, not to a part
        p1 = place(_f(wire, "x1"), _f(wire, "y1"))
        p2 = place(_f(wire, "x2"), _f(wire, "y2"))
        # The board contour is the centre line of the cut: drawn thin, whatever the tool.
        width = OUTLINE_WIDTH if layer == 7 else _f(wire, "width")
        curve = _f(wire, "curve")
        if curve:
            if place.rot.mirror:
                curve = -curve
            centre, radius, a0, a1 = _arc(p1, p2, curve)
            self.b.arc(layer, centre, radius, width, a0, a1, part)
            return
        clear = None
        if layer in (1, 3):
            clear, _ = self._plane_terms(net, (layer_name,))
        self.b.track(layer, [p1, p2], width, part, clear)

    def shapes(self, holder: ET.Element, place: _Place, part: str | None) -> None:
        """Drawings of the board (plain) or of a package: wires, circles, rectangles,
        polygons, holes."""
        for wire in holder.findall("wire"):
            self.wire(wire, place, part)
        for circle in holder.findall("circle"):
            layer = LAYERS.get(place.layer(circle.get("layer", "")))
            if layer is None:
                continue
            centre = place(_f(circle, "x"), _f(circle, "y"))
            radius, width = _f(circle, "radius"), _f(circle, "width")
            if layer == 7:
                width = OUTLINE_WIDTH
            if width == 0:
                self.b.disc(layer, centre, radius, part)
            else:
                self.b.arc(layer, centre, radius, width, 0.0, 0.0, None if layer == 7 else part)
        for rect in holder.findall("rectangle"):
            layer = LAYERS.get(place.layer(rect.get("layer", "")))
            if layer is None:
                continue
            x1, y1, x2, y2 = (_f(rect, k) for k in ("x1", "y1", "x2", "y2"))
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            turn = _Rotation.parse(rect.get("rot"))
            a = radians(turn.angle)
            corners = []
            for dx, dy in (
                (x1 - cx, y1 - cy),
                (x2 - cx, y1 - cy),
                (x2 - cx, y2 - cy),
                (x1 - cx, y2 - cy),
            ):
                rx, ry = dx * cos(a) - dy * sin(a), dx * sin(a) + dy * cos(a)
                corners.append(place(cx + rx, cy + ry))
            self.b.zone(layer, corners, part=part)
        for polygon in holder.findall("polygon"):
            layer = LAYERS.get(place.layer(polygon.get("layer", "")))
            if layer is None or layer in (1, 3) and holder.tag == "signal":
                continue
            points = _outline(polygon.findall("vertex"), place)
            if layer == 7:
                self.b.track(7, [*points, points[0]], OUTLINE_WIDTH)
            else:
                self.b.zone(layer, points, part=part)
        for hole in holder.findall("hole"):
            x, y = place(_f(hole, "x"), _f(hole, "y"))
            self.b.tht(x, y, 0, 0, _f(hole, "drill"), "round", 0, False, part, None)

    def text(
        self,
        text: ET.Element,
        place: _Place,
        part: str | None,
        content: str,
        label: str | None = None,
        layer_name: str | None = None,
    ) -> None:
        layer_name = layer_name or place.layer(text.get("layer", ""))
        layer = LAYERS.get(layer_name)
        if label is None and layer is None:
            self.b.report["тексты на слоях без соответствия"] += 1
            return
        x, y = place(_f(text, "x"), _f(text, "y"))
        own = _Rotation.parse(text.get("rot"))
        angle = place.angle(own.angle)
        mirrored = place.rot.mirror != own.mirror
        size = _f(text, "size", 1.27)
        align = text.get("align", "bottom-left")
        vertical, _, horizontal = align.partition("-") if "-" in align else ("center", "", align)
        if align == "center":
            vertical, horizontal = "center", "center"
        kx = {"left": 0.0, "center": 0.5, "right": 1.0}.get(horizontal, 0.0)
        ky = {"bottom": 0.0, "center": 0.5, "top": 1.0}.get(vertical, 0.0)
        if not own.spin and 90 < angle <= 270:
            # Eagle keeps texts readable from the bottom or the right side.
            angle -= 180
            kx, ky = 1 - kx, 1 - ky
        if label is not None:
            side = 4 if layer_name in ("26", "28", "22") else 2
            visible = layer is not None and layer_name in ("25", "26", "21", "22")
            self.b.label(part or "", label, side, x, y, size, angle, mirrored, visible, (kx, ky))
            return
        assert layer is not None
        for k, line in enumerate(content.split("\n")):
            a = radians(angle)
            shift = k * size * 1.6
            self.b.text(
                layer,
                x + shift * sin(a),
                y - shift * cos(a),
                line,
                size,
                angle,
                mirrored,
                (kx, ky),
                part,
            )

    def pad_size(self, drill: float, given: float, restring: str, low: str, high: str) -> float:
        ring = min(
            max(_f_rule(self.rules, restring, 0.25) * drill, _length(self.rules.get(low), 0.254)),
            _length(self.rules.get(high), 0.508),
        )
        return max(given, drill + 2 * ring)

    def element(self, element: ET.Element) -> None:
        package = self._package(element)
        name = element.get("name", "")
        if package is None:
            self.b.report["элементы без корпуса в библиотеке файла пропущены"] += 1
            return
        place = self._place(element)
        key = f"{name}#{id(element)}"
        self.b.component(
            key, name, element.get("value", ""), package.get("name", ""), not place.rot.mirror
        )
        self.shapes(package, place, key)
        for pad in package.findall("pad"):
            x, y = place(_f(pad, "x"), _f(pad, "y"))
            drill = _f(pad, "drill")
            d = self.pad_size(drill, _f(pad, "diameter"), "rvPadTop", "rlMinPadTop", "rlMaxPadTop")
            shape = pad.get("shape", "round")
            angle = place.angle(_Rotation.parse(pad.get("rot")).angle)
            w = h = d
            if shape in ("long", "offset"):
                share = (
                    _f_rule(
                        self.rules,
                        "psElongationLong" if shape == "long" else "psElongationOffset",
                        100,
                    )
                    / 100
                )
                w = d * (1 + share)
            net = self.pad_nets.get((name, pad.get("name", "")))
            clear, thermal = self._plane_terms(net, ("1", "16"))
            kind = {"square": "rect", "octagon": "octagon"}.get(shape, "round")
            self.b.tht(x, y, w, h, drill, kind, angle, True, key, net, clear, thermal)
        for smd in package.findall("smd"):
            x, y = place(_f(smd, "x"), _f(smd, "y"))
            layer_name = place.layer(smd.get("layer", "1"))
            layer = COPPER.get(layer_name)
            if layer is None:
                continue
            angle = place.angle(_Rotation.parse(smd.get("rot")).angle)
            if _f(smd, "roundness") > 0:
                self.b.report["скруглённые SMD-площадки стали прямоугольными"] += 1
            net = self.pad_nets.get((name, smd.get("name", "")))
            clear, thermal = self._plane_terms(net, (layer_name,))
            self.b.smd(layer, x, y, _f(smd, "dx"), _f(smd, "dy"), angle, key, net, clear, thermal)
        # Names and values: placed attributes of a smashed part, else the package's texts.
        attributes = {a.get("name"): a for a in element.findall("attribute")}
        for role, label in (("NAME", "ID_TEXT"), ("VALUE", "VALUE_TEXT")):
            attribute = attributes.get(role)
            if attribute is not None and attribute.get("x") is not None:
                hidden = attribute.get("display") == "off"
                layer_name = attribute.get("layer", "25" if role == "NAME" else "27")
                if hidden:
                    layer_name = "0"
                self.text(attribute, BOARD, key, "", label, layer_name)
                continue
            for text in package.findall("text"):
                if (text.text or "").strip().upper() == f">{role}":
                    self.text(text, place, key, "", label)
                    break
        for text in package.findall("text"):
            content = (text.text or "").strip()
            if content.startswith(">"):
                continue
            self.text(text, place, key, content)

    def signals(self) -> None:
        for signal in self.board.findall("signals/signal"):
            net = signal.get("name", "")
            for wire in signal.findall("wire"):
                self.wire(wire, BOARD, None, net)
            for via in signal.findall("via"):
                x, y = _f(via, "x"), _f(via, "y")
                drill = _f(via, "drill")
                d = self.pad_size(
                    drill, _f(via, "diameter"), "rvViaOuter", "rlMinViaOuter", "rlMaxViaOuter"
                )
                if via.get("extent", "1-16") != "1-16":
                    self.b.report["глухие и скрытые переходы стали сквозными"] += 1
                clear, thermal = self._plane_terms(net, ("1", "16"))
                self.b.via(x, y, d, drill, net, True, clear, False)

    def run(self) -> Conversion:
        self.choose_planes()
        plain = self.board.find("plain")
        if plain is not None:
            self.shapes(plain, BOARD, None)
            for text in plain.findall("text"):
                self.text(text, BOARD, None, (text.text or "").strip())
        for element in self.board.findall("elements/element"):
            self.element(element)
        self.signals()
        return self.b.finish(0.0 if self.b.planes else 2.0)


def _f_rule(rules: dict, key: str, default: float) -> float:
    try:
        return float(rules.get(key, default))
    except (TypeError, ValueError):
        return default


def convert(data: bytes, name: str = "Eagle") -> Conversion:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise EagleError(f"Не файл Eagle (XML): {error}") from error
    if root.tag != "eagle":
        raise EagleError("Не файл Eagle: это двоичный .brd старых версий или другой XML")
    return _Converter(root, name).run()


def convert_file(path: Path) -> Conversion:
    return convert(path.read_bytes(), path.stem)
