"""New projects and boards, with optional contour on the outline layer."""

from collections.abc import Iterable
from dataclasses import replace
from struct import Struct

from .model import CIRCLE, COUNT, LINE, MM, Board, Element, Project

BOARD_HEADER = Struct("<B30s4xII7sddiiI7sBBB200sB200s6i2iiiB")
TRAILER_SIZE = 307
OUTLINE = 7
OUTLINE_WIDTH = 0.1


def board_header(
    name: str, width: float, height: float, multilayer: bool = False, grid: float = 0.1
) -> bytes:
    """A board header with the settings the original program writes for a fresh board."""
    raw = name.encode("cp1251", "replace")[:30]
    return BOARD_HEADER.pack(
        len(raw),
        raw,
        round(width * MM),
        round(height * MM),
        bytes(7),
        grid * MM,
        0.003,
        0,
        0,
        1,
        bytes([1] * 7),
        0,
        0,
        0,
        bytes(200),
        0,
        bytes(200),
        600,
        600,
        0,
        0,
        0,
        0,
        0xFF00,
        0xFF00,
        0,
        -1_000_000,
        int(multilayer),
    )


def new_board(
    name: str,
    width: float,
    height: float,
    outline: Iterable[Element] = (),
    multilayer: bool = False,
    grid: float = 0.1,
) -> Board:
    header = board_header(name, width, height, multilayer, grid)
    return Board(name, width, height, bytes(7), multilayer, list(outline), header)


def new_project(board: Board) -> Project:
    return Project([board], bytes(TRAILER_SIZE) + COUNT.pack(0))


def rectangle_outline(left: float, top: float, width: float, height: float) -> Element:
    """Closed board contour on the outline layer; top-left corner in board units (Y up)."""
    x0, y0, x1, y1 = left, -top, left + width, -(top + height)
    points = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    return Element(LINE, layer=OUTLINE, width=OUTLINE_WIDTH, points=points, clearance=0.4)


def round_outline(cx: float, cy: float, diameter: float) -> Element:
    radius = diameter / 2
    return Element(
        CIRCLE,
        x=cx,
        y=-cy,
        outer=radius + OUTLINE_WIDTH / 2,
        inner=radius - OUTLINE_WIDTH / 2,
        layer=OUTLINE,
        clearance=0.4,
    )


def board_from_dialog(
    name: str,
    kind: str,
    width: float,
    height: float,
    margin: float = 0.0,
    multilayer: bool = False,
    grid: float = 0.1,
) -> Board:
    """kind: 'empty' (work area only), 'rect' or 'round' (contour plus margin on every side)."""
    if kind == "empty":
        return new_board(name, width, height, (), multilayer, grid)
    if kind == "rect":
        return new_board(
            name,
            width + 2 * margin,
            height + 2 * margin,
            [rectangle_outline(margin, margin, width, height)],
            multilayer,
            grid,
        )
    size = width + 2 * margin
    return new_board(name, size, size, [round_outline(size / 2, size / 2, width)], multilayer, grid)


def rename_board(board: Board, name: str) -> Board:
    raw = name.encode("cp1251", "replace")[:30]
    header = bytearray(board.header)
    header[0] = len(raw)
    header[1:31] = raw.ljust(30, bytes(1))
    return replace(board, name=name, header=bytes(header))
