"""Boards from other programs: build a project and draw air wires for unrouted nets."""

from dataclasses import replace
from math import hypot
from pathlib import Path

import core
from core import altium, diptrace, eagle, kicad
from core.foreign import Conversion, ForeignError

from .connectivity import nets as copper_nets

# File name endings that are converted on opening, with their dialog filter.
FOREIGN = {
    ".pcbdoc": "Altium Designer (*.PcbDoc *.pcbdoc *.PCBDOC)",
    ".kicad_pcb": "KiCad (*.kicad_pcb)",
    ".brd": "Eagle (*.brd)",
    ".dip": "DipTrace (*.dip)",
}
CONVERTERS = {
    ".pcbdoc": altium.convert_file,
    ".kicad_pcb": kicad.convert_file,
    ".brd": eagle.convert_file,
    ".dip": diptrace.convert_file,
}


class ForeignFileError(ValueError):
    pass


def is_foreign(path: Path) -> bool:
    return path.suffix.lower() in FOREIGN


def with_air_wires(board: core.Board, pad_nets: dict[int, str]) -> tuple[core.Board, int]:
    """Air wires joining the copper islands of every net, nearest pads first.

    Pads already joined by copper get no wire, so the wires show what is left to route.
    """
    islands = copper_nets(board)
    by_net: dict[str, dict[int, list[int]]] = {}
    for index, net in pad_nets.items():
        island = islands.get(index, -1 - index)
        by_net.setdefault(net, {}).setdefault(island, []).append(index)
    elements = list(board.elements)
    count = 0
    for groups in by_net.values():
        parts = list(groups.values())
        if len(parts) < 2:
            continue
        joined = parts[0]
        rest = parts[1:]
        while rest:
            best = None
            for k, part in enumerate(rest):
                for a in joined:
                    ax, ay = core.centre_of(elements[a])
                    for b in part:
                        bx, by = core.centre_of(elements[b])
                        d = hypot(ax - bx, ay - by)
                        if best is None or d < best[0]:
                            best = (d, k, a, b)
            assert best is not None
            _, k, a, b = best
            current = replace(board, elements=elements)
            for index, obj in core.toggled_wire(current, a, b).items():
                elements[index] = obj
            count += 1
            joined = joined + rest.pop(k)
    return replace(board, elements=elements), count


def board_from_conversion(conversion: Conversion) -> tuple[core.Board, int]:
    board = core.board_from_dialog(
        conversion.name,
        "empty",
        conversion.width,
        conversion.height,
        multilayer=conversion.multilayer,
    )
    for layer in conversion.planes:
        board = core.with_plane(board, layer, True)
    objects = core.import_text(board, conversion.text)
    board = replace(board, elements=objects)
    pad_nets = {
        i: net
        for i, net in enumerate(conversion.nets)
        if net and i < len(objects) and objects[i].kind in (core.THT, core.SMD)
    }
    return with_air_wires(board, pad_nets)


def import_project(path: Path) -> tuple[core.Project, str]:
    """A new project from a foreign board file and a report of what changed on the way."""
    try:
        conversion = CONVERTERS[path.suffix.lower()](path)
        board, wires = board_from_conversion(conversion)
    except (OSError, altium.AltiumError, ForeignError, core.TextIOError) as error:
        raise ForeignFileError(str(error)) from error
    lines = [f"{path.name}: объектов {len(board.elements)}, воздушных линий {wires}."]
    lines += [f"• {text}: {count}" for text, count in conversion.report.items()]
    return core.new_project(board), "\n".join(lines)
