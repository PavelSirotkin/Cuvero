"""KiCad boards (.kicad_pcb, versions 5 to 9) converted to Text-IO via the foreign builder.

KiCad measures in mm with y downwards. Footprint drawings are stored in the footprint's
own coordinates; pads and texts carry absolute angles, counter-clockwise on screen.
Copper zones are stored together with their fill, which is carried over as it is.
"""

from collections.abc import Callable
from math import atan2, cos, degrees, hypot, radians, sin
from pathlib import Path

from . import sexpr
from .foreign import Builder, Conversion, ForeignError, Point, arc_through

COPPER_LAYERS = {"F.Cu": 1, "B.Cu": 3, "In1.Cu": 5, "In2.Cu": 6}
OTHER_LAYERS = {
    "F.SilkS": 2,
    "F.Silkscreen": 2,
    "B.SilkS": 4,
    "B.Silkscreen": 4,
    "Edge.Cuts": 7,
}
LAYERS = {**COPPER_LAYERS, **OTHER_LAYERS}


class KicadError(ForeignError):
    pass


class _Place:
    """Footprint coordinates to board coordinates (mm, y up)."""

    def __init__(self, x: float = 0.0, y: float = 0.0, angle: float = 0.0):
        self.x, self.y, self.angle = x, y, angle
        a = radians(angle)
        self.c, self.s = cos(a), sin(a)

    def __call__(self, lx: float, ly: float) -> Point:
        # Turn counter-clockwise on screen, then flip y upwards.
        x = lx * self.c + ly * self.s
        y = -lx * self.s + ly * self.c
        return round(self.x + x, 6), round(-(self.y + y), 6)


BOARD = _Place()
NetOf = Callable[[list], str | None]


def _xy(node: list | None) -> tuple[float, float]:
    x, y = sexpr.numbers(node, 2)
    return x, y


def _width(node: list) -> float:
    stroke = sexpr.child(node, "stroke")
    width = sexpr.child(stroke, "width") if stroke else sexpr.child(node, "width")
    return sexpr.numbers(width, 1)[0]


def _layer(node: list) -> str:
    words = sexpr.words(sexpr.child(node, "layer"))
    return words[0] if words else ""


def _filled(node: list) -> bool:
    fill = sexpr.words(sexpr.child(node, "fill"))
    return bool(fill) and fill[0] in ("solid", "yes")


def _hidden(node: list) -> bool:
    if "hide" in [w for w in node[1:] if isinstance(w, str) and not isinstance(w, sexpr.Quoted)]:
        return True
    for holder in (node, sexpr.child(node, "effects")):
        hide = sexpr.child(holder, "hide") if holder else None
        if hide is not None and (sexpr.words(hide) or ["yes"])[0] == "yes":
            return True
    return False


def convert(text: str, name: str = "KiCad") -> Conversion:
    try:
        root = sexpr.parse(text)
    except sexpr.SexprError as error:
        raise KicadError(f"Не файл платы KiCad: {error}") from error
    if sexpr.name(root) != "kicad_pcb":
        raise KicadError("Не файл платы KiCad (.kicad_pcb)")
    b = Builder(name)
    nets = {}
    for net in sexpr.children(root, "net"):
        number, *rest = sexpr.words(net) + [""]
        nets[number] = rest[0]
    used_inner = {_layer(n) for n in root[1:] if isinstance(n, list)} & {"In1.Cu", "In2.Cu"}
    b.multilayer = bool(used_inner)

    def net_of(node: list) -> str | None:
        words = sexpr.words(sexpr.child(node, "net"))
        if not words:
            return None
        named = words[1] if len(words) > 1 else nets.get(words[0], "")
        return named or None

    for node in root[1:]:
        if not isinstance(node, list):
            continue
        kind = sexpr.name(node)
        if kind in ("footprint", "module"):
            _footprint(b, node, net_of)
        elif kind in ("segment", "arc") and sexpr.child(node, "start") and sexpr.child(node, "end"):
            _track(b, node, BOARD, None)
        elif kind == "via":
            x, y = BOARD(*_xy(sexpr.child(node, "at")))
            size = sexpr.numbers(sexpr.child(node, "size"), 1)[0]
            drill = sexpr.numbers(sexpr.child(node, "drill"), 1)[0]
            if {"blind", "micro"} & set(sexpr.words(node)):
                b.report["глухие и микропереходы стали сквозными"] += 1
            b.via(x, y, size, drill, net_of(node))
        elif kind == "zone":
            _zone(b, node)
        elif kind.startswith("gr_"):
            _drawing(b, node, kind[3:], BOARD, None)
    return b.finish()


def _track(b: Builder, node: list, place: _Place, part: str | None) -> None:
    layer = LAYERS.get(_layer(node))
    if layer is None:
        b.report["дорожки и линии на слоях без соответствия"] += 1
        return
    start = place(*_xy(sexpr.child(node, "start")))
    end = place(*_xy(sexpr.child(node, "end")))
    width = _width(node)
    mid_node = sexpr.child(node, "mid")
    if mid_node is not None:
        try:
            centre, radius, a0, a1 = arc_through(start, place(*_xy(mid_node)), end)
        except ForeignError:
            b.track(layer, [start, end], width, part)
            return
        b.arc(layer, centre, radius, width, a0, a1, part)
        return
    b.track(layer, [start, end], width, part)


def _drawing(b: Builder, node: list, kind: str, place: _Place, part: str | None) -> None:
    """gr_* and fp_* drawings: line, arc, circle, rect, poly, text."""
    if kind == "text":
        _text(b, node, place, part, None)
        return
    if kind in ("line", "arc") and sexpr.child(node, "mid") is not None:
        _track(b, node, place, part)
        return
    layer = LAYERS.get(_layer(node))
    if layer is None:
        if _layer(node).endswith(".Mask"):
            b.report["окна в маске без меди (рисунки на слое маски) не переносятся"] += 1
        elif kind not in ("text_box",):
            b.report["рисунки на слоях без соответствия (Fab, CrtYd, User…)"] += 1
        return
    width = max(_width(node), 0.1 if layer == 7 else 0.0)
    if kind == "line":
        b.track(
            layer,
            [place(*_xy(sexpr.child(node, "start"))), place(*_xy(sexpr.child(node, "end")))],
            width,
            part,
        )
    elif kind == "arc":
        # KiCad 5: start is the centre, end the arc's start, angle clockwise on screen.
        centre = place(*_xy(sexpr.child(node, "start")))
        first = place(*_xy(sexpr.child(node, "end")))
        sweep = sexpr.numbers(sexpr.child(node, "angle"), 1)[0]
        radius = hypot(first[0] - centre[0], first[1] - centre[1])
        a0 = degrees(atan2(first[1] - centre[1], first[0] - centre[0]))
        # Clockwise on screen is counter-clockwise once y points up.
        start, end = (a0, a0 + sweep) if sweep >= 0 else (a0 + sweep, a0)
        b.arc(layer, centre, radius, width, start, end, part)
    elif kind == "circle":
        centre = place(*_xy(sexpr.child(node, "center")))
        edge = place(*_xy(sexpr.child(node, "end")))
        radius = hypot(edge[0] - centre[0], edge[1] - centre[1])
        if _filled(node) and layer != 7:
            b.disc(layer, centre, radius + width / 2, part)
        else:
            b.arc(layer, centre, radius, width, 0.0, 0.0, part)
    elif kind == "rect":
        (x0, y0), (x1, y1) = _xy(sexpr.child(node, "start")), _xy(sexpr.child(node, "end"))
        corners = [place(x0, y0), place(x1, y0), place(x1, y1), place(x0, y1)]
        if _filled(node) and layer != 7:
            b.zone(layer, corners, part=part)
        else:
            b.track(layer, [*corners, corners[0]], width, part)
    elif kind == "poly":
        points = [
            place(*sexpr.numbers(p, 2))
            for p in sexpr.children(sexpr.child(node, "pts") or [], "xy")
        ]
        if len(points) < 2:
            return
        if (_filled(node) or sexpr.child(node, "fill") is None and kind == "poly") and layer != 7:
            b.zone(layer, points, part=part)
        else:
            b.track(layer, [*points, points[0]], width, part)
    elif kind == "curve":
        b.report["кривые Безье пропущены"] += 1


def _effects(node: list) -> tuple[float, tuple[float, float], bool, float]:
    """Letter height with strokes (mm), justification shares, mirrored, font size."""
    effects = sexpr.child(node, "effects") or []
    font = sexpr.child(effects, "font") if effects else None
    height = sexpr.numbers(sexpr.child(font, "size") if font else None, 1, 1.0)[0]
    thickness = sexpr.numbers(sexpr.child(font, "thickness") if font else None, 1, height * 0.15)[0]
    justify = sexpr.words(sexpr.child(effects, "justify")) if effects else []
    kx = 0.0 if "left" in justify else (1.0 if "right" in justify else 0.5)
    ky = 0.0 if "bottom" in justify else (1.0 if "top" in justify else 0.5)
    return height + thickness, (kx, ky), "mirror" in justify, height


def _text(
    b: Builder,
    node: list,
    place: _Place,
    part: str | None,
    label: str | None,
    upright: bool = False,
) -> None:
    """gr_text / fp_text / property; label "ID_TEXT" or "VALUE_TEXT" for component labels."""
    words = sexpr.words(node)
    layer_name = _layer(node)
    layer = OTHER_LAYERS.get(layer_name) or COPPER_LAYERS.get(layer_name)
    at = sexpr.numbers(sexpr.child(node, "at"), 3)
    x, y = place(at[0], at[1])
    angle = at[2]
    ink, justify, mirrored, size = _effects(node)
    if upright:
        # KiCad keeps footprint texts readable: never upside down.
        angle %= 360
        if 90 < angle <= 270:
            angle -= 180
            justify = (1 - justify[0], 1 - justify[1])
    if label is not None:
        visible = layer in (2, 4) and not _hidden(node)
        side = layer if layer in (2, 4) else (4 if layer_name.startswith("B.") else 2)
        b.label(part or "", label, side, x, y, ink, angle, mirrored, visible, justify)
        return
    if layer is None or _hidden(node):
        if layer is None and not _hidden(node):
            b.report["тексты на слоях без соответствия"] += 1
        return
    text = next((w for w in words if isinstance(w, sexpr.Quoted)), words[-1] if words else "")
    if "${" in text:
        return  # a field reference such as ${REFERENCE} on a drawing layer
    # KiCad ignores empty lines at the end and spaces lines 1.62 font sizes apart.
    lines = text.rstrip("\n").split("\n")
    step = size * 1.62
    for k, line in enumerate(lines):
        # Lines go down the page; the block keeps its justification as a whole.
        shift = ((len(lines) - 1) * (1 - justify[1]) - k) * step
        a = radians(angle)
        lx, ly = x - shift * sin(a), y + shift * cos(a)
        b.text(layer, lx, ly, line, ink, angle, mirrored, justify, part)


def _footprint(b: Builder, node: list, net_of: NetOf) -> None:
    words = sexpr.words(node)
    package = words[0].split(":")[-1] if words else ""
    at = sexpr.numbers(sexpr.child(node, "at"), 3)
    place = _Place(at[0], at[1], at[2])
    top = not _layer(node).startswith("B.")
    reference = value = ""
    for prop in sexpr.children(node, "property"):
        key, *rest = sexpr.words(prop) + [""]
        if key == "Reference":
            reference = rest[0]
        elif key == "Value":
            value = rest[0]
    for item in sexpr.children(node, "fp_text"):
        kind, *rest = sexpr.words(item) + [""]
        if kind == "reference":
            reference = rest[0]
        elif kind == "value":
            value = rest[0]
    key = f"{reference}#{id(node)}"
    b.component(key, reference, value, package, top)
    for prop in sexpr.children(node, "property"):
        name = (sexpr.words(prop) or [""])[0]
        if name in ("Reference", "Value"):
            _text(b, prop, place, key, "ID_TEXT" if name == "Reference" else "VALUE_TEXT", True)
    for item in node[1:]:
        if not isinstance(item, list):
            continue
        kind = sexpr.name(item)
        if kind == "fp_text":
            role = (sexpr.words(item) or [""])[0]
            if role == "reference":
                _text(b, item, place, key, "ID_TEXT", True)
            elif role == "value":
                _text(b, item, place, key, "VALUE_TEXT", True)
            else:
                _text(b, item, place, key, None, True)
        elif kind.startswith("fp_"):
            _drawing(b, item, kind[3:], place, key)
        elif kind == "pad":
            _pad(b, item, place, key, net_of)
        elif kind == "zone":
            _zone(b, item)


def _pad(b: Builder, node: list, place: _Place, part: str, net_of: NetOf) -> None:
    words = sexpr.words(node)
    kind = words[1] if len(words) > 1 else ""
    shape = words[2] if len(words) > 2 else "circle"
    at = sexpr.numbers(sexpr.child(node, "at"), 3)
    x, y = place(at[0], at[1])
    angle = at[2]
    w, h = sexpr.numbers(sexpr.child(node, "size"), 2)
    layers = sexpr.words(sexpr.child(node, "layers"))
    net = net_of(node)
    if kind in ("thru_hole", "np_thru_hole"):
        drill_node = sexpr.child(node, "drill")
        drill_words = sexpr.words(drill_node)
        if drill_words and drill_words[0] == "oval":
            dw, dh = sexpr.numbers(drill_node, 2)
            drill = min(dw, dh) if dh else dw
            b.report["пазы (продолговатые отверстия) заменены круглыми"] += 1
        else:
            drill = sexpr.numbers(drill_node, 1)[0]
        if kind == "np_thru_hole":
            copper = [layer for layer in layers if layer.endswith(".Cu")]
            if not copper or max(w, h) <= drill:
                b.tht(x, y, 0, 0, drill, "round", 0, False, part, None)
                return
        rr = sexpr.numbers(sexpr.child(node, "roundrect_rratio"), 1, 0.25)[0]
        kind_shape = {"rect": "rect", "roundrect": "rect" if rr < 0.3 else "round"}.get(
            shape, "round"
        )
        if shape in ("custom", "trapezoid"):
            b.report["площадки сложной формы заменены простыми"] += 1
        b.tht(x, y, w, h, drill, kind_shape, angle, kind == "thru_hole", part, net)
        return
    if kind in ("smd", "connect"):
        sides = [COPPER_LAYERS[n] for n in layers if n in COPPER_LAYERS]
        if not sides:
            return
        if shape == "trapezoid":
            b.report["площадки сложной формы заменены простыми"] += 1
        elif shape in ("circle", "oval"):
            b.report["круглые и овальные SMD-площадки стали прямоугольными"] += 1
        b.smd(sides[0], x, y, w, h, angle, part, net)
        if shape == "custom":
            # The anchor pad above carries the connections; the drawn shape is copper
            # with an opening in the solder mask around it.
            _primitives(b, node, _Place(x, -y, angle), sides[0], part)
            b.report["площадки произвольной формы: якорь и медь их формы"] += 1


def _primitives(b: Builder, pad: list, place: _Place, layer: int, part: str) -> None:
    for item in (sexpr.child(pad, "primitives") or [])[1:]:
        if not isinstance(item, list):
            continue
        kind = sexpr.name(item)
        width = _width(item)
        if kind == "gr_poly":
            nodes = sexpr.children(sexpr.child(item, "pts") or [], "xy")
            points = [place(*sexpr.numbers(p, 2)) for p in nodes]
            b.zone(layer, points, part=part, mask=True)
            if width > 0:
                b.track(layer, [*points, points[0]], width, part)
        elif kind == "gr_circle":
            centre = place(*_xy(sexpr.child(item, "center")))
            edge = place(*_xy(sexpr.child(item, "end")))
            radius = hypot(edge[0] - centre[0], edge[1] - centre[1])
            b.disc(layer, centre, radius + width / 2, part, mask=True)
        elif kind == "gr_rect":
            (x0, y0), (x1, y1) = _xy(sexpr.child(item, "start")), _xy(sexpr.child(item, "end"))
            corners = [place(x0, y0), place(x1, y0), place(x1, y1), place(x0, y1)]
            b.zone(layer, corners, part=part, mask=True)
        elif kind == "gr_line":
            start = place(*_xy(sexpr.child(item, "start")))
            end = place(*_xy(sexpr.child(item, "end")))
            b.track(layer, [start, end], width, part)


def _zone(b: Builder, node: list) -> None:
    if sexpr.child(node, "keepout") is not None and not sexpr.children(node, "filled_polygon"):
        return
    for poly in sexpr.children(node, "filled_polygon"):
        layer = COPPER_LAYERS.get(_layer(poly)) or LAYERS.get(_layer(node))
        if layer is None:
            continue
        points = [
            BOARD(*sexpr.numbers(p, 2))
            for p in sexpr.children(sexpr.child(poly, "pts") or [], "xy")
        ]
        b.zone(layer, points)
    if sexpr.children(node, "filled_polygon"):
        b.report["зоны перенесены залитыми, как в KiCad (без перезаливки)"] += 1


def convert_file(path: Path) -> Conversion:
    return convert(path.read_text(encoding="utf-8", errors="replace"), path.stem)
