"""Air wires (rubber bands): the pad connection lists stored in the file.

Every pad keeps the list of board object indices it is wired to; the original writes each
wire into both pads' lists. Because the lists hold indices, they must be renumbered when
objects are deleted.
"""

from collections.abc import Iterable, Sequence
from dataclasses import replace
from struct import Struct

from .model import COUNT, PADS, Board, Element

INDEX = Struct("<I")


def wired_to(obj: Element) -> list[int]:
    """Indices of the objects a pad is wired to."""
    data = obj.connections
    if obj.kind not in PADS or len(data) < 4:
        return []
    count = COUNT.unpack(data[:4])[0]
    return [INDEX.unpack(data[4 + 4 * k : 8 + 4 * k])[0] for k in range(count)]


def with_wires(obj: Element, targets: Iterable[int]) -> Element:
    unique = list(dict.fromkeys(targets))
    data = COUNT.pack(len(unique)) + b"".join(INDEX.pack(t) for t in unique)
    return replace(obj, connections=data if unique else COUNT.pack(0))


def air_wires(board: Board) -> list[tuple[int, int]]:
    """Each wire once, as (smaller index, larger index), between existing pads."""
    count = len(board.elements)
    wires = set()
    for index, obj in enumerate(board.elements):
        for target in wired_to(obj):
            if target != index and 0 <= target < count and board.elements[target].kind in PADS:
                wires.add((min(index, target), max(index, target)))
    return sorted(wires)


def toggled_wire(board: Board, a: int, b: int) -> dict[int, Element]:
    """Changed pads after adding the wire a–b, or removing it if it exists."""
    elements = board.elements
    first, second = wired_to(elements[a]), wired_to(elements[b])
    if b in first or a in second:
        return {
            a: with_wires(elements[a], [t for t in first if t != b]),
            b: with_wires(elements[b], [t for t in second if t != a]),
        }
    return {a: with_wires(elements[a], [*first, b]), b: with_wires(elements[b], [*second, a])}


def without_wires_of(board: Board, indices: Iterable[int]) -> dict[int, Element]:
    """Changed pads after removing every wire touching the given objects."""
    chosen = set(indices)
    changed: dict[int, Element] = {}
    for index, obj in enumerate(board.elements):
        targets = wired_to(obj)
        if not targets:
            continue
        kept = [] if index in chosen else [t for t in targets if t not in chosen]
        if kept != targets:
            changed[index] = with_wires(obj, kept)
    return changed


def renumbered(board: Board, deleted: Sequence[int]) -> dict[int, Element]:
    """Changed pads (by their current index) once the given objects are deleted:
    wires to deleted objects go, the other targets move down."""
    gone = sorted(set(deleted))
    gone_set = set(gone)

    def new_index(old: int) -> int:
        # How many deleted objects lie before this one.
        low, high = 0, len(gone)
        while low < high:
            mid = (low + high) // 2
            if gone[mid] < old:
                low = mid + 1
            else:
                high = mid
        return old - low

    changed: dict[int, Element] = {}
    for index, obj in enumerate(board.elements):
        if index in gone_set:
            continue
        targets = wired_to(obj)
        if not targets:
            continue
        moved = [new_index(t) for t in targets if t not in gone_set]
        if moved != targets:
            changed[index] = with_wires(obj, moved)
    return changed
