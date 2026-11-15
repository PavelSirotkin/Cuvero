"""Reading Gerber (RS-274X and X2) files into simple drawing primitives.

Used to import Gerber files and to compare our output with reference files. Supports what
PCB programs write: standard apertures (C, R, O, P), aperture macros with circle, vector
line, centre line, outline and polygon primitives, linear and circular interpolation,
regions, polarity, and the old G54/G70/G71 forms.
"""

import re
from dataclasses import dataclass, field
from math import atan2, cos, hypot, pi, radians, sin

Point = tuple[float, float]


@dataclass
class Aperture:
    shape: str  # C, R, O, P or a macro name
    params: list[float]
    # Outline polygons of a macro aperture around its centre, dark ones first.
    macro: list[tuple[bool, list[Point]]] = field(default_factory=list)


@dataclass
class Primitive:
    """One drawing step: a flash, a stroke along a path, or a filled region."""

    kind: str  # "flash", "draw", "region"
    dark: bool
    points: list[Point]
    aperture: Aperture | None = None
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class GerberFile:
    primitives: list[Primitive] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)
    apertures: dict[int, Aperture] = field(default_factory=dict)
    unit_mm: bool = True


class GerberError(ValueError):
    pass


def _number(text: str) -> float:
    return float(text)


def _arc_points(
    start: Point, end: Point, centre: Point, clockwise: bool, steps_per_turn: int = 72
) -> list[Point]:
    sx, sy = start
    ex, ey = end
    cx, cy = centre
    r = hypot(sx - cx, sy - cy)
    a0 = atan2(sy - cy, sx - cx)
    a1 = atan2(ey - cy, ex - cx)
    if clockwise:
        while a1 >= a0:
            a1 -= 2 * pi
    else:
        while a1 <= a0:
            a1 += 2 * pi
    sweep = a1 - a0
    steps = max(int(abs(sweep) / (2 * pi) * steps_per_turn), 2)
    return [
        (cx + r * cos(a0 + sweep * k / steps), cy + r * sin(a0 + sweep * k / steps))
        for k in range(1, steps + 1)
    ]


def _evaluate(expression: str, variables: dict[int, float]) -> float:
    text = expression.replace("x", "*").replace("X", "*")
    text = re.sub(r"\$(\d+)", lambda m: repr(variables.get(int(m.group(1)), 0.0)), text)
    if not re.fullmatch(r"[0-9.+\-*/() eE]*", text):
        raise GerberError(f"Непонятное выражение в макросе: {expression}")
    return float(eval(text, {"__builtins__": {}}, {}))  # noqa: S307 - digits and operators only


def _rotate(points: list[Point], angle: float) -> list[Point]:
    c, s = cos(radians(angle)), sin(radians(angle))
    return [(x * c - y * s, x * s + y * c) for x, y in points]


def _circle(cx: float, cy: float, d: float, steps: int = 36) -> list[Point]:
    r = d / 2
    return [
        (cx + r * cos(2 * pi * k / steps), cy + r * sin(2 * pi * k / steps)) for k in range(steps)
    ]


def _macro_shapes(body: list[str], params: list[float]) -> list[tuple[bool, list[Point]]]:
    variables = {i + 1: value for i, value in enumerate(params)}
    shapes: list[tuple[bool, list[Point]]] = []
    for statement in body:
        statement = statement.strip()
        if not statement or statement.startswith("0"):
            continue
        if statement.startswith("$"):
            name, value = statement.split("=", 1)
            variables[int(name[1:])] = _evaluate(value, variables)
            continue
        values = [_evaluate(part, variables) for part in statement.split(",")]
        code = int(values[0])
        if code == 1:  # circle: exposure, diameter, x, y[, rotation]
            exposure, d, x, y = values[1:5]
            rotation = values[5] if len(values) > 5 else 0.0
            shapes.append((exposure != 0, _rotate(_circle(x, y, d), rotation)))
        elif code in (2, 20):  # vector line: exposure, width, x1, y1, x2, y2, rotation
            exposure, width, x1, y1, x2, y2, rotation = values[1:8]
            length = hypot(x2 - x1, y2 - y1) or 1e-9
            nx, ny = -(y2 - y1) / length * width / 2, (x2 - x1) / length * width / 2
            outline = [
                (x1 + nx, y1 + ny),
                (x2 + nx, y2 + ny),
                (x2 - nx, y2 - ny),
                (x1 - nx, y1 - ny),
            ]
            shapes.append((exposure != 0, _rotate(outline, rotation)))
        elif code == 21:  # centre line: exposure, width, height, x, y, rotation
            exposure, w, h, x, y, rotation = values[1:7]
            outline = [
                (x - w / 2, y - h / 2),
                (x + w / 2, y - h / 2),
                (x + w / 2, y + h / 2),
                (x - w / 2, y + h / 2),
            ]
            shapes.append((exposure != 0, _rotate(outline, rotation)))
        elif code == 4:  # outline: exposure, n, x0, y0, ..., rotation
            exposure, n = values[1], int(values[2])
            coords = values[3 : 3 + 2 * (n + 1)]
            outline = [(coords[k], coords[k + 1]) for k in range(0, len(coords), 2)]
            rotation = values[3 + 2 * (n + 1)] if len(values) > 3 + 2 * (n + 1) else 0.0
            shapes.append((exposure != 0, _rotate(outline, rotation)))
        elif code == 5:  # polygon: exposure, vertices, x, y, diameter, rotation
            exposure, vertices, x, y, d = values[1:6]
            rotation = values[6] if len(values) > 6 else 0.0
            n = int(vertices)
            corners = [
                (x + d / 2 * cos(2 * pi * k / n), y + d / 2 * sin(2 * pi * k / n)) for k in range(n)
            ]
            shapes.append((exposure != 0, _rotate(corners, rotation)))
        # Moirés (6) and thermals (7) are not written by board programs we read.
    return shapes


def parse(text: str) -> GerberFile:
    """Primitives of a Gerber file, in file order, in millimetres."""
    result = GerberFile()
    macros: dict[str, list[str]] = {}
    integer, decimal = 3, 4
    scale = 1.0
    x = y = 0.0
    aperture: Aperture | None = None
    dark = True
    linear, clockwise = True, False
    region: list[list[Point]] | None = None
    path: list[Point] = []
    attributes: dict[str, str] = {}

    def flush() -> None:
        nonlocal path
        if len(path) > 1 and region is None:
            result.primitives.append(Primitive("draw", dark, path, aperture, dict(attributes)))
        path = []

    def coordinate(value: str | None, old: float) -> float:
        if value is None:
            return old
        negative = value.startswith("-")
        digits = value.lstrip("+-")
        if "." in digits:
            number = float(digits)
        else:
            digits = digits.rjust(integer + decimal, "0")
            number = int(digits) / 10**decimal
        return (-number if negative else number) * scale

    # Split into extended commands (%...%) and word commands ending with "*".
    tokens = re.findall(r"%[^%]*%|[^%*]+\*", text.replace("\r", "").replace("\n", ""))
    for token in tokens:
        if token.startswith("%"):
            body = token[1:-1]
            for command in [c for c in body.split("*") if c]:
                head = command[:2]
                if head == "FS":
                    match = re.search(r"X(\d)(\d)", command)
                    if match:
                        integer, decimal = int(match.group(1)), int(match.group(2))
                elif head == "MO":
                    result.unit_mm = command[2:4] == "MM"
                    scale = 1.0 if result.unit_mm else 25.4
                elif head == "AD":
                    match = re.fullmatch(r"ADD(\d+)([A-Za-z_$.][\w.$]*),?(.*)", command)
                    if not match:
                        raise GerberError(f"Непонятная апертура: {command}")
                    number, shape, args = int(match.group(1)), match.group(2), match.group(3)
                    params = [float(v) for v in args.split("X") if v]
                    new = Aperture(shape, params)
                    if shape not in ("C", "R", "O", "P"):
                        if shape not in macros:
                            raise GerberError(f"Нет макроса {shape}")
                        new.macro = _macro_shapes(macros[shape], params)
                    if scale != 1.0:
                        new.params = [
                            v * scale if i != 1 or shape != "P" else v
                            for i, v in enumerate(new.params)
                        ]
                        new.macro = [
                            (e, [(px * scale, py * scale) for px, py in pts])
                            for e, pts in new.macro
                        ]
                    result.apertures[number] = new
                elif head == "AM":
                    # The rest of this block is the macro body.
                    macros[command[2:]] = [c for c in body.split("*")[1:] if c]
                    break
                elif head == "LP":
                    flush()
                    dark = command[2] == "D"
                elif head == "TF":
                    key, _, value = command[2:].partition(",")
                    result.attributes[key] = value
                elif head in ("TA", "TO"):
                    key, _, value = command[2:].partition(",")
                    attributes[key] = value
                elif head == "TD":
                    key = command[2:]
                    if key:
                        attributes.pop(key, None)
                    else:
                        attributes.clear()
            continue
        word = token[:-1]
        if not word:
            continue
        for code in re.findall(r"G0*(\d+)", word.split("X")[0].split("Y")[0].split("D")[0]):
            g = int(code)
            if g == 1:
                linear = True
            elif g in (2, 3):
                linear, clockwise = False, g == 2
            elif g == 36:
                flush()
                region = [[]]
            elif g == 37:
                if region is not None:
                    for contour in region:
                        if len(contour) >= 3:
                            result.primitives.append(
                                Primitive("region", dark, contour, None, dict(attributes))
                            )
                region = None
            elif g == 70:
                scale = 25.4
            elif g == 71:
                scale = 1.0
            elif g == 54:
                pass
        select = re.search(r"(?:G54)?D(\d+)$", word)
        if select and int(select.group(1)) >= 10 and not re.search(r"[XYIJ]", word):
            flush()
            aperture = result.apertures.get(int(select.group(1)))
            continue
        if word.startswith("M0"):
            flush()
            break
        coords = dict(re.findall(r"([XYIJ])([+-]?[\d.]+)", word))
        operation = re.search(r"D0*([123])$", word)
        nx = coordinate(coords.get("X"), x)
        ny = coordinate(coords.get("Y"), y)
        if operation is None:
            if coords:
                x, y = nx, ny
            continue
        op = int(operation.group(1))
        if op == 2:
            flush()
            if region is not None:
                region.append([(nx, ny)])
            x, y = nx, ny
        elif op == 1:
            if linear:
                new_points = [(nx, ny)]
            else:
                i = coordinate(coords.get("I"), 0.0) if "I" in coords else 0.0
                j = coordinate(coords.get("J"), 0.0) if "J" in coords else 0.0
                new_points = _arc_points((x, y), (nx, ny), (x + i, y + j), clockwise)
            if region is not None:
                if not region[-1]:
                    region[-1].append((x, y))
                region[-1].extend(new_points)
            else:
                if not path:
                    path = [(x, y)]
                path.extend(new_points)
            x, y = nx, ny
        else:  # D03 flash
            flush()
            x, y = nx, ny
            result.primitives.append(Primitive("flash", dark, [(x, y)], aperture, dict(attributes)))
    flush()
    return result
