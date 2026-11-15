"""Gerber output (X2 by default, or plain RS-274X) for every layer of a board.

Coordinates are relative to the board origin, like the original program writes them. Copper
layers with an automatic ground plane are written in three passes, as the original does:
the plane area dark, every object grown by its clearance cleared, then the objects (and the
spokes of thermal reliefs) dark again.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from math import atan2, cos, degrees, hypot, pi, radians, sin

from .components import component_id, component_labels, is_hidden_label
from .model import (
    CIRCLE,
    LINE,
    MM,
    POLYGON,
    SEGMENT,
    SMD,
    STROKE_TEXT,
    THT,
    Board,
    Element,
    Point,
)
from .project import has_plane
from .properties import (
    board_origin,
    centre_of,
    has_thermal,
    pad_rotation,
    smd_size,
    spoke_angle,
    thermal_directions,
    thermal_layer_directions,
)

SOFTWARE = ("Cuvero", "Cuvero", "0.1")
COPPER_LAYERS = (1, 3, 5, 6)
PLANE_INDEX = {1: 0, 3: 1, 5: 2, 6: 3}  # thermal direction byte of each copper layer
ARC_STEPS = 72  # segments per full turn where arcs are written as straight pieces


@dataclass
class GerberOptions:
    x2: bool = True
    mirror: bool = False
    frame: bool = False  # a thin frame around the board area on every layer
    holes: str = "none"  # "none", "punch" (0.15 mm centre marks) or "clear" (cut out)
    mask_pads: float | None = 0.3  # solder mask offset of through-hole pads; None: no opening
    mask_smd: float | None = 0.1
    mask_other: float | None = 0.1  # tracks, polygons, circles with a mask opening
    mask_inverted: bool = False
    paste_offset: float = 0.0
    paste_inverted: bool = False
    use_origin: bool = True  # coordinates from the board's origin, else from its corner
    date: datetime | None = None  # creation date written into X2 files; now by default
    plane_only: bool = False  # copper layers: only the ground plane with its spokes


# File name endings of the original program, and the X2 function of each file.
LAYER_FILES: dict[str, tuple[str, str]] = {
    "copper_top": ("Copper,L1,Top", "Positive"),
    "copper_bottom": ("Copper,L{n},Bot", "Positive"),
    "copper_inner1": ("Copper,L2,Inr", "Positive"),
    "copper_inner2": ("Copper,L3,Inr", "Positive"),
    "silkscreen_top": ("Legend,Top", "Positive"),
    "silkscreen_bottom": ("Legend,Bot", "Positive"),
    "outline": ("Profile,NP", "Positive"),
    "soldermask_top": ("Soldermask,Top", "Negative"),
    "soldermask_bottom": ("Soldermask,Bot", "Negative"),
    "smdmask_top": ("Paste,Top", "Positive"),
    "smdmask_bot": ("Paste,Bot", "Positive"),
}
FILE_LAYERS = {
    "copper_top": 1,
    "copper_bottom": 3,
    "copper_inner1": 5,
    "copper_inner2": 6,
    "silkscreen_top": 2,
    "silkscreen_bottom": 4,
    "outline": 7,
}


# --- shapes ------------------------------------------------------------------------------


def _rotated(points: Iterable[Point], angle: float, cx: float, cy: float) -> list[Point]:
    c, s = cos(radians(angle)), sin(radians(angle))
    return [(cx + x * c - y * s, cy + x * s + y * c) for x, y in points]


def tht_geometry(pad: Element, grow: float = 0.0) -> tuple[str, list[float], float]:
    """Basic shape of a through-hole pad: ("C"|"R"|"O"|"OCT"|"OCTLONG", sizes, angle).

    Sizes are full widths along the pad's own axes; angle turns them counter-clockwise.
    """
    r = pad.outer
    shape = pad.shape
    if shape not in range(1, 10) or shape == 1:
        return "C", [2 * (r + grow)], 0.0
    half_x = r * (2 if shape in (4, 5, 6) else 1)
    half_y = r * (2 if shape in (7, 8, 9) else 1)
    angle = pad_rotation(pad)
    sizes = [2 * (half_x + grow), 2 * (half_y + grow)]
    if shape in (4, 7):
        return "O", sizes, angle
    if shape == 2:
        return "OCT", [2 * (r + grow)], angle
    if shape in (5, 8):
        return "OCTLONG", [*sizes, r + grow], angle
    return "R", sizes, angle


def octagon_outline(width: float, height: float, radius: float) -> list[Point]:
    """Octagon with flat sides, its corners cut like a pad of the given radius."""
    cut = radius * (2 - 2**0.5)
    x, y = width / 2, height / 2
    return [
        (-x + cut, -y),
        (x - cut, -y),
        (x, -y + cut),
        (x, y - cut),
        (x - cut, y),
        (-x + cut, y),
        (-x, y - cut),
        (-x, -y + cut),
    ]


def obround_outline(width: float, height: float) -> list[Point]:
    r = min(width, height) / 2
    dx, dy = width / 2 - r, height / 2 - r
    points: list[Point] = []
    centres = [(dx, dy, 0), (-dx, dy, 90), (-dx, -dy, 180), (dx, -dy, 270)]
    for cx, cy, start in centres:
        for k in range(10):
            a = radians(start + 90 * k / 9)
            points.append((cx + r * cos(a), cy + r * sin(a)))
    return points


def tht_outline(pad: Element, grow: float = 0.0) -> list[Point]:
    """The pad's outline as a polygon, centred on the pad."""
    kind, sizes, angle = tht_geometry(pad, grow)
    if kind == "C":
        r = sizes[0] / 2
        outline = [
            (r * cos(2 * pi * k / ARC_STEPS), r * sin(2 * pi * k / ARC_STEPS))
            for k in range(ARC_STEPS)
        ]
    elif kind == "R":
        w, h = sizes
        outline = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    elif kind == "O":
        outline = obround_outline(*sizes)
    elif kind == "OCT":
        outline = octagon_outline(sizes[0], sizes[0], sizes[0] / 2)
    else:
        outline = octagon_outline(sizes[0], sizes[1], sizes[2])
    return _rotated(outline, angle, pad.x, pad.y)


def corner_outline(pad: Element, grow: float = 0.0) -> list[Point]:
    """The pad's four stored corners, moved outwards by grow along the rectangle's axes."""
    if len(pad.points) < 4:
        w, h = pad.outer / 2 + grow, pad.inner / 2 + grow
        x, y = centre_of(pad)
        return [(x - w, y - h), (x + w, y - h), (x + w, y + h), (x - w, y + h)]
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = pad.points[:4]
    if not grow:
        return [(x0, y0), (x1, y1), (x2, y2), (x3, y3)]
    ux, uy = x1 - x0, y1 - y0
    vx, vy = x3 - x0, y3 - y0
    lu, lv = hypot(ux, uy) or 1, hypot(vx, vy) or 1
    ux, uy, vx, vy = ux / lu * grow, uy / lu * grow, vx / lv * grow, vy / lv * grow
    return [
        (x0 - ux - vx, y0 - uy - vy),
        (x1 + ux - vx, y1 + uy - vy),
        (x2 + ux + vx, y2 + uy + vy),
        (x3 - ux + vx, y3 - uy + vy),
    ]


def has_corners(pad: Element) -> bool:
    """Rectangular pads that store their four corners (SMD, and some through-hole pads)."""
    return pad.kind == SMD or (pad.kind == THT and pad.shape in (3, 6, 9) and len(pad.points) == 4)


def _axis_angle(pad: Element) -> float | None:
    """Rotation of an SMD pad's rectangle if it is a multiple of 90 degrees, else None."""
    if len(pad.points) < 2:
        return 0.0
    (x0, y0), (x1, y1) = pad.points[0], pad.points[1]
    angle = degrees(atan2(y1 - y0, x1 - x0)) % 90
    return 0.0 if min(angle, 90 - angle) < 1e-6 else None


def circle_path(obj: Element) -> tuple[float, float, float, float, float]:
    """Centre, radius, start and sweep angle (degrees, counter-clockwise) of a circle or arc."""
    radius = (obj.outer + obj.inner) / 2
    start, end = float(obj.start), float(round(obj.width * MM))
    if max(abs(start), abs(end)) > 1000:
        start, end = start / 1000, end / 1000
    sweep = (end - start) % 360
    if end == start:
        sweep = 360.0
    return obj.x, obj.y, radius, float(start), float(sweep)


# --- writer ------------------------------------------------------------------------------


@dataclass
class _Writer:
    origin: Point
    mirror_width: float | None
    x2: bool
    apertures: dict[tuple, int] = field(default_factory=dict)
    definitions: list[str] = field(default_factory=list)
    body: list[str] = field(default_factory=list)
    current: int | None = None
    dark: bool = True
    function: str | None = None
    component: str | None = None
    defined_function: str | None = None  # aperture function in force while defining

    def xy(self, point: Point) -> str:
        x, y = point[0] - self.origin[0], point[1] - self.origin[1]
        if self.mirror_width is not None:
            x = self.mirror_width - x
        return f"X{round(x * 1e6)}Y{round(y * 1e6)}"

    def aperture(self, shape: str, params: Iterable[float], function: str | None) -> int:
        values = tuple(round(v, 4) for v in params)
        key = (shape, values, function if self.x2 else None)
        if key not in self.apertures:
            number = 10 + len(self.apertures)
            self.apertures[key] = number
            text = "X".join(f"{v:g}" for v in values)
            if self.x2 and function != self.defined_function:
                if function:
                    self.definitions.append(f"%TA.AperFunction,{function}*%")
                else:
                    self.definitions.append("%TD.AperFunction*%")
                self.defined_function = function
            self.definitions.append(f"%ADD{number}{shape},{text}*%")
        return self.apertures[key]

    def select(self, number: int) -> None:
        if number != self.current:
            self.body.append(f"D{number}*")
            self.current = number

    def polarity(self, dark: bool) -> None:
        if dark != self.dark:
            self.body.append("%LPD*%" if dark else "%LPC*%")
            self.dark = dark

    def owner(self, name: str | None) -> None:
        if not self.x2 or name == self.component:
            return
        if name:
            safe = name.replace(",", "_").replace("*", "_").replace("%", "_")
            self.body.append(f"%TO.C,{safe}*%")
        else:
            self.body.append("%TD.C*%")
        self.component = name

    def flash(self, shape: str, params: Iterable[float], at: Point, function: str | None) -> None:
        self.select(self.aperture(shape, params, function))
        self.body.append(f"{self.xy(at)}D03*")

    def line(self, points: list[Point], width: float, function: str | None) -> None:
        if len(points) < 2:
            if points:
                self.flash("C", [max(width, 0.001)], points[0], function)
            return
        self.select(self.aperture("C", [max(width, 0.001)], function))
        self.body.append(f"{self.xy(points[0])}D02*")
        self.body.extend(f"{self.xy(p)}D01*" for p in points[1:])

    def region(self, points: list[Point], function: str | None) -> None:
        if len(points) < 3:
            return
        if self.x2 and function:
            self.body.append(f"%TA.AperFunction,{function}*%")
        self.body.append("G36*")
        self.body.append(f"{self.xy(points[0])}D02*")
        self.body.extend(f"{self.xy(p)}D01*" for p in points[1:])
        if points[0] != points[-1]:
            self.body.append(f"{self.xy(points[0])}D01*")
        self.body.append("G37*")
        if self.x2 and function:
            self.body.append("%TD.AperFunction*%")


def _arc_points(cx: float, cy: float, r: float, start: float, sweep: float) -> list[Point]:
    steps = max(int(ARC_STEPS * sweep / 360), 2)
    return [
        (
            cx + r * cos(radians(start + sweep * k / steps)),
            cy + r * sin(radians(start + sweep * k / steps)),
        )
        for k in range(steps + 1)
    ]


def _on_copper(obj: Element, layer: int, board: Board) -> bool:
    if is_hidden_label(obj):
        return False
    if obj.kind == THT and obj.plated and obj.inner > 0:
        # Plated through-hole pads have copper on every copper layer of the board.
        return layer in (1, 3) or board.multilayer
    return obj.layer == layer


def is_bare_hole(obj: Element) -> bool:
    """A through-hole pad no larger than its hole: a hole without copper."""
    return obj.kind == THT and obj.inner > 0 and obj.outer <= obj.inner


def _component_names(board: Board) -> dict[int, str]:
    names: dict[int, str] = {}
    for obj in board.elements:
        cid = component_id(obj)
        if cid and cid not in names:
            ref, _ = component_labels(board.elements, cid)
            if ref is not None and board.elements[ref].text:
                names[cid] = board.elements[ref].text
    return names


def _draw_object(
    w: _Writer, obj: Element, grow: float, functions: bool, names: dict[int, str]
) -> None:
    """One object as dark or clear Gerber, grown by grow on every side."""
    w.owner(names.get(component_id(obj)) if functions and obj.kind in (THT, SMD) else None)
    if has_corners(obj):
        function = None
        if functions:
            function = "SMDPad,CuDef" if obj.kind == SMD else "ComponentPad"
        if _axis_angle(obj) is not None and len(obj.points) >= 4:
            xs = [x for x, _ in obj.points[:4]]
            ys = [y for _, y in obj.points[:4]]
            size = [max(xs) - min(xs) + 2 * grow, max(ys) - min(ys) + 2 * grow]
            w.flash("R", size, ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2), function)
        else:
            w.region(corner_outline(obj, grow), function)
        return
    if obj.kind == THT:
        kind, sizes, angle = tht_geometry(obj, grow)
        function = "ComponentPad" if functions else None
        upright = abs(angle % 90) < 1e-6 or abs(angle % 90 - 90) < 1e-6
        if kind == "C":
            w.flash("C", sizes, (obj.x, obj.y), function)
        elif kind in ("R", "O") and upright:
            if round(angle) % 180 == 90:
                sizes = sizes[::-1]
            w.flash(kind, sizes, (obj.x, obj.y), function)
        elif kind == "OCT":
            diameter = sizes[0] / cos(radians(22.5))
            w.flash("P", [diameter, 8, (angle + 22.5) % 360], (obj.x, obj.y), function)
        else:
            w.region(tht_outline(obj, grow), function)
        return
    function = "Conductor" if functions else None
    if obj.kind == LINE:
        w.line(list(obj.points), obj.width + 2 * grow, function)
    elif obj.kind == SEGMENT:
        w.line([(obj.x, obj.y), (obj.outer, obj.inner)], obj.width + 2 * grow, function)
    elif obj.kind == POLYGON and len(obj.points) >= 3:
        w.region(list(obj.points), function)
        if obj.width > 0 or grow:
            ring = list(obj.points)
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            w.line(ring, obj.width + 2 * grow, function)
    elif obj.kind == CIRCLE:
        cx, cy, r, start, sweep = circle_path(obj)
        line_width = obj.outer - obj.inner
        if obj.filled and sweep >= 360:
            w.flash("C", [2 * (obj.outer + grow)], (cx, cy), function)
        else:
            w.line(_arc_points(cx, cy, r, start, sweep), line_width + 2 * grow, function)
    elif obj.kind == STROKE_TEXT:
        text_function = "NonConductor" if functions else None
        for child in obj.children:
            w.line(list(child.points), child.width + 2 * grow, text_function)


def _spokes(w: _Writer, pad: Element, layer: int, functions: bool) -> None:
    if not has_thermal(pad) or pad.width <= 0:
        return
    if pad.kind == THT:
        bits = thermal_layer_directions(pad, PLANE_INDEX.get(layer, 0))
        kind, sizes, _ = tht_geometry(pad)
        size = max(sizes) / 2
    else:
        bits = thermal_directions(pad)
        size = hypot(*smd_size(pad)) / 2
    reach = size + pad.clearance + 0.1
    cx, cy = centre_of(pad)
    for bit in range(8):
        if bits >> bit & 1:
            a = radians(spoke_angle(pad, bit))
            end = (cx + cos(a) * reach, cy + sin(a) * reach)
            w.line([(cx, cy), end], pad.width, "Conductor" if functions else None)


def _header(
    w: _Writer, function: str, polarity: str, options: GerberOptions, board: Board
) -> list[str]:
    lines = ["%FSLAX46Y46*%", "%MOMM*%"]
    if w.x2:
        date = (options.date or datetime.now().astimezone()).isoformat(timespec="seconds")
        name, vendor, version = SOFTWARE
        lines = [
            f"%TF.GenerationSoftware,{vendor},{name},{version}*%",
            f"%TF.CreationDate,{date}*%",
            f"%TF.SameCoordinates,{_safe(board.name) or 'board'}*%",
            f"%TF.FileFunction,{function}*%",
            f"%TF.FilePolarity,{polarity}*%",
            "%TF.Part,Single*%",
            *lines,
        ]
    return lines


def _safe(text: str) -> str:
    return "".join(ch if ch not in ",*%\\" else "_" for ch in text)


def _frame(w: _Writer, board: Board) -> None:
    ox, oy = 0.0, 0.0
    corners = [
        (ox, oy),
        (ox + board.width, oy),
        (ox + board.width, oy - board.height),
        (ox, oy - board.height),
        (ox, oy),
    ]
    w.polarity(True)
    w.line(corners, 0.1, "Profile" if w.x2 else None)


def layer_gerber(board: Board, name: str, options: GerberOptions | None = None) -> str:
    """The Gerber text of one output file, named by its original file name ending."""
    options = options or GerberOptions()
    function, polarity = LAYER_FILES[name]
    copper_count = 4 if board.multilayer else 2
    function = function.replace("{n}", str(copper_count))
    if board.multilayer and name == "copper_inner2":
        function = "Copper,L3,Inr"
    if (name.startswith("soldermask") and options.mask_inverted) or (
        name.startswith("smdmask") and options.paste_inverted
    ):
        polarity = "Negative" if polarity == "Positive" else "Positive"
    mirror = board.width if options.mirror else None
    origin = board_origin(board) if options.use_origin else (0.0, 0.0)
    w = _Writer(origin, mirror, options.x2)
    names = _component_names(board) if options.x2 else {}
    if name in FILE_LAYERS:
        layer = FILE_LAYERS[name]
        if layer in COPPER_LAYERS:
            _copper(w, board, layer, options, names)
        else:
            for obj in board.elements:
                if obj.layer == layer and not is_hidden_label(obj) and not obj.keepout:
                    _draw_object(w, obj, 0.0, False, names)
            if name == "outline" and w.x2:
                pass
    elif name.startswith("soldermask"):
        _mask(w, board, name.endswith("top"), options)
    else:
        _paste(w, board, name.endswith("top"), options)
    if options.frame and name != "outline":
        _frame(w, board)
    w.owner(None)
    lines = _header(w, function, polarity, options, board)
    lines += w.definitions
    lines.append("G01*")  # linear interpolation for every draw; arcs are written as lines
    lines += ["%LPD*%"] + w.body + ["M02*"]
    return "\n".join(lines) + "\n"


def _copper(
    w: _Writer, board: Board, layer: int, options: GerberOptions, names: dict[int, str]
) -> None:
    objects = [obj for obj in board.elements if _on_copper(obj, layer, board)]
    if has_plane(board, layer):
        ox, oy = 0.0, 0.0
        area = [
            (ox, oy),
            (ox + board.width, oy),
            (ox + board.width, oy - board.height),
            (ox, oy - board.height),
        ]
        w.region(area, "Conductor" if options.x2 else None)
        w.polarity(False)
        for obj in objects:
            if obj.clearance > 0 or obj.keepout:
                _draw_object(w, obj, 0.0 if obj.keepout else obj.clearance, False, names)
        w.polarity(True)
        for obj in objects:
            if obj.keepout or is_bare_hole(obj):
                continue
            if not options.plane_only:
                _draw_object(w, obj, 0.0, options.x2, names)
            if obj.kind in (THT, SMD):
                _spokes(w, obj, layer, options.x2)
    elif not options.plane_only:
        for obj in objects:
            if not obj.keepout and not is_bare_hole(obj):
                _draw_object(w, obj, 0.0, options.x2, names)
    if options.holes != "none":
        w.polarity(False)
        w.owner(None)
        for obj in board.elements:
            if obj.kind == THT and obj.inner > 0:
                size = 0.15 if options.holes == "punch" else 2 * obj.inner
                w.flash("C", [size], (obj.x, obj.y), None)
        w.polarity(True)


def _board_area(board: Board) -> list[Point]:
    return [(0.0, 0.0), (board.width, 0.0), (board.width, -board.height), (0.0, -board.height)]


def _mask(w: _Writer, board: Board, top: bool, options: GerberOptions) -> None:
    side = 1 if top else 3
    if options.mask_inverted:
        w.region(_board_area(board), None)
        w.polarity(False)
    for obj in board.elements:
        if not obj.soldermask or is_hidden_label(obj):
            continue
        if obj.kind == THT and _on_copper(obj, side, board):
            # A pad no larger than its hole is a bare hole: the mask covers it.
            if options.mask_pads is not None and not is_bare_hole(obj):
                _draw_object(w, obj, options.mask_pads, False, {})
        elif obj.layer != side:
            continue
        elif obj.kind == SMD:
            if options.mask_smd is not None:
                _draw_object(w, obj, options.mask_smd, False, {})
        elif options.mask_other is not None:
            _draw_object(w, obj, options.mask_other, False, {})


def _paste(w: _Writer, board: Board, top: bool, options: GerberOptions) -> None:
    side = 1 if top else 3
    if options.paste_inverted:
        w.region(_board_area(board), None)
        w.polarity(False)
    for obj in board.elements:
        if obj.kind == SMD and obj.layer == side and not is_hidden_label(obj):
            _draw_object(w, obj, options.paste_offset, False, {})


def output_names(board: Board) -> list[str]:
    """The files worth writing for a board: copper, silk, outline, masks, paste."""
    names = ["copper_top", "copper_bottom"]
    if board.multilayer:
        names += ["copper_inner1", "copper_inner2"]
    names += ["silkscreen_top", "silkscreen_bottom", "outline"]
    names += ["soldermask_top", "soldermask_bottom", "smdmask_top", "smdmask_bot"]
    return names


def file_name(project_name: str, board_name: str, ending: str, boards: int) -> str:
    """Like the original: "<project>_<ending>.gbr", or "<project>-[<board>]_<ending>.gbr"."""
    if boards > 1:
        return f"{project_name}-[{board_name}]_{ending}.gbr"
    return f"{project_name}_{ending}.gbr"
