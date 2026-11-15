"""Drill data: Excellon files like the original's, and the list of holes by diameter."""

from collections.abc import Iterable
from dataclasses import dataclass
from math import hypot
from struct import Struct

from .model import MM, THT, Board, Element, Point
from .properties import board_origin

FLOAT32 = Struct("<f")
FORMATS = {"3.3": (3, 3), "2.4": (2, 4), "3.2": (3, 2)}


@dataclass
class DrillOptions:
    format: str = "3.3"  # digits before and after the decimal point, in mm (or inch)
    inch: bool = False
    leading_zeros: bool = True
    decimal_point: bool = True
    plated: bool = True  # through-plated holes
    unplated: bool = True  # simple holes
    side: str = "top"  # "top", "bottom_gerber" (mirrored in x), "bottom_hpgl"
    sort: bool = True  # order the holes of each tool for a short path, as the original
    use_origin: bool = True  # coordinates from the board's origin, else from its corner
    m71: bool = False  # M71/M72 instead of METRIC/INCH
    comments: bool = True
    g90: bool = True


def holes(board: Board, plated: bool = True, unplated: bool = True) -> list[tuple[float, Element]]:
    """(diameter, pad) of every hole, in board order."""
    result = []
    for obj in board.elements:
        if obj.kind == THT and obj.inner > 0 and (plated if obj.plated else unplated):
            result.append((round(2 * obj.inner, 4), obj))
    return result


def hole_table(board: Board) -> list[tuple[float, int, int]]:
    """(diameter, plated count, simple count) per diameter, smallest first."""
    counts: dict[float, list[int]] = {}
    for diameter, pad in holes(board):
        counts.setdefault(diameter, [0, 0])[0 if pad.plated else 1] += 1
    return [(d, counts[d][0], counts[d][1]) for d in sorted(counts)]


def _grid(value: float, base: float) -> float:
    """value - base on the 0.01 mm grid, rounding exact halves to even as the original."""
    units = round(value * MM) - round(base * MM)  # positions are exact in 1/10000 mm
    hundredths, rest = divmod(units, 100)
    if rest > 50 or (rest == 50 and hundredths % 2):
        hundredths += 1
    return hundredths / 100


def _f32(value: float) -> float:
    return float(FLOAT32.unpack(FLOAT32.pack(value))[0])


def _short_path(holes: list[tuple[Point, Point]], start: Point) -> list[tuple[Point, Point]]:
    """Nearest-neighbour order by the first point of each pair; ties go to the earlier hole."""
    rest = list(holes)
    path: list[tuple[Point, Point]] = []
    x, y = start
    while rest:
        index = min(range(len(rest)), key=lambda i: hypot(rest[i][0][0] - x, rest[i][0][1] - y))
        path.append(rest.pop(index))
        x, y = path[-1][0]
    return path


def _number(value: float, integer: int, decimals: int, options: DrillOptions) -> str:
    negative = value < 0
    value = abs(value)
    if options.decimal_point:
        text = f"{value:0{integer + decimals + 1}.{decimals}f}"
        if not options.leading_zeros:
            text = text.lstrip("0") or "0"
            if text.startswith("."):
                text = "0" + text
    else:
        text = f"{round(value * 10**decimals):0{integer + decimals}d}"
        if not options.leading_zeros:
            text = text.lstrip("0") or "0"
    return ("-" if negative else "") + text


def excellon(board: Board, options: DrillOptions | None = None) -> str:
    """Excellon drill file text with CRLF line ends, as the original writes it."""
    options = options or DrillOptions()
    integer, decimals = FORMATS.get(options.format, (3, 3))
    scale = 1 / 25.4 if options.inch else 1.0
    ox, oy = board_origin(board) if options.use_origin else (0.0, 0.0)
    selected = holes(board, options.plated, options.unplated)
    tools = sorted({d for d, _ in selected})
    lines: list[str] = []
    if options.comments:
        sample = "0" * integer + "." + "0" * decimals
        lines += ["; Drill file", f"; Format: {integer}.{decimals} ({sample})"]
    lines.append("M48")
    if options.m71:
        lines.append("M72" if options.inch else "M71")
    else:
        lines.append("INCH" if options.inch else "METRIC")
    for number, diameter in enumerate(tools, 1):
        size = f"{diameter * scale:g}"
        lines.append(f"T{number:02d}C{size if '.' in size else size + '.0'}")
    lines += ["%", "G05"]
    if options.g90:
        lines.append("G90")
    for number, diameter in enumerate(tools, 1):
        stored: list[tuple[Point, Point]] = []  # (position as stored, output position)
        for d, pad in selected:
            if d != diameter:
                continue
            x, y = _grid(pad.x, ox), _grid(pad.y, oy)
            if options.side != "top":
                x = board.width - x
            stored.append(((_f32(pad.x * MM), _f32(pad.y * MM)), (x, y)))
        if options.sort:
            # From the lower left corner, always to the nearest hole. Distances use the
            # positions as stored (single precision, 1/10000 mm), so that equal distances
            # are decided exactly as by the original.
            corner = (board.width * MM if options.side != "top" else 0.0, -board.height * MM)
            stored = _short_path(stored, corner)
        points = [output for _, output in stored]
        lines.append(f"T{number:02d}")
        lines += [
            f"X{_number(x * scale, integer, decimals, options)}"
            f"Y{_number(y * scale, integer, decimals, options)}"
            for x, y in points
        ]
    lines.append("M30")
    return "\r\n".join(lines) + "\r\n"


def drill_file_name(project_name: str, board_name: str, boards: int) -> str:
    return f"{project_name}-[{board_name}].DRL" if boards > 1 else f"{project_name}.DRL"


def pad_list(elements: Iterable[Element]) -> list[Element]:
    return [obj for obj in elements if obj.kind == THT]
