"""Editing operations on sets of objects: units, groups, clipboard, layers, alignment, nodes.

A *unit* is what one click selects: a whole component, else the outermost group of an
object, else the object alone. Each object stores its groups as a list of ids in the
order they were made, so the last id is the outermost group.
"""

from collections.abc import Iterable, Sequence
from dataclasses import replace
from math import hypot

from .components import component_id, with_component_id
from .macros import bounds, transformed
from .model import (
    COUNT,
    LINE,
    OBJECT,
    PADS,
    SEGMENT,
    SMD,
    Element,
    LayoutError,
    Point,
    Reader,
    write_element,
)
from .transform import mirror_all

COPPER_SIDES = {1: 3, 3: 1, 2: 4, 4: 2}
PAD_LAYERS = (1, 3)


# --- Units and groups -------------------------------------------------------


def group_ids(obj: Element) -> list[int]:
    if len(obj.groups) < 4:
        return []
    count = int.from_bytes(obj.groups[:4], "little")
    return [int.from_bytes(obj.groups[4 + 4 * i : 8 + 4 * i], "little") for i in range(count)]


def with_group_ids(obj: Element, ids: Sequence[int]) -> Element:
    data = COUNT.pack(len(ids)) + b"".join(i.to_bytes(4, "little") for i in ids)
    return replace(obj, groups=data)


def outer_group(obj: Element) -> int | None:
    ids = group_ids(obj)
    return ids[-1] if ids else None


def unit_of(elements: Sequence[Element], index: int) -> list[int]:
    """Indices selected together with the object at index."""
    return unit_closure(elements, [index])


def unit_closure(elements: Sequence[Element], indices: Iterable[int]) -> list[int]:
    """Indices extended by whole components and outermost groups, until nothing is added."""
    chosen = set(indices)
    while True:
        cids = {component_id(elements[i]) for i in chosen} - {0}
        groups = {outer_group(elements[i]) for i in chosen} - {None}
        grown = {
            i
            for i, obj in enumerate(elements)
            if component_id(obj) in cids or outer_group(obj) in groups
        }
        if grown <= chosen:
            return sorted(chosen)
        chosen |= grown


def units(elements: Sequence[Element], indices: Iterable[int]) -> list[list[int]]:
    """Split a selection into units that move and align as one.

    Objects sharing a component or an outermost group belong to one unit, transitively;
    one pass with a union-find keeps this fast on boards with thousands of objects.
    """
    chosen = sorted(set(indices))
    parent = {i: i for i in chosen}

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first_with: dict[tuple[str, int], int] = {}
    for i in chosen:
        obj = elements[i]
        keys = [("c", component_id(obj))] if component_id(obj) else []
        group = outer_group(obj)
        if group is not None:
            keys.append(("g", group))
        for key in keys:
            if key in first_with:
                parent[root(i)] = root(first_with[key])
            else:
                first_with[key] = i
    result: dict[int, list[int]] = {}
    for i in chosen:
        result.setdefault(root(i), []).append(i)
    return sorted(result.values())


def next_group_id(elements: Iterable[Element]) -> int:
    return max((max(group_ids(obj), default=0) for obj in elements), default=0) + 1


def grouped(elements: Sequence[Element], indices: Iterable[int]) -> dict[int, Element]:
    """Put the objects into one new group around their current groups."""
    gid = next_group_id(elements)
    return {i: with_group_ids(elements[i], [*group_ids(elements[i]), gid]) for i in indices}


def ungrouped(elements: Sequence[Element], indices: Iterable[int]) -> dict[int, Element]:
    """Dissolve the outermost group of each selected object, keeping inner groups."""
    chosen = list(indices)
    outer = {outer_group(elements[i]) for i in chosen} - {None}
    return {
        i: with_group_ids(elements[i], group_ids(elements[i])[:-1])
        for i in chosen
        if outer_group(elements[i]) in outer
    }


# --- Clipboard --------------------------------------------------------------

CLIPBOARD_MAGIC = b"L6OB"


def objects_to_bytes(objects: Sequence[Element]) -> bytes:
    """Objects in the file's own record format, for the clipboard."""
    out = bytearray(CLIPBOARD_MAGIC)
    out += COUNT.pack(len(objects))
    for obj in objects:
        write_element(out, obj)
        if obj.kind in PADS:
            out += COUNT.pack(0)
    return bytes(out)


def objects_from_bytes(data: bytes) -> list[Element]:
    reader = Reader(data)
    if bytes(reader.take(4)) != CLIPBOARD_MAGIC:
        raise LayoutError("В буфере обмена нет объектов платы")
    objects = []
    for _ in range(reader.count(OBJECT.size)):
        obj = reader.element()
        if obj.kind in PADS:
            reader.take(reader.count(4) * 4)
        objects.append(obj)
    return objects


def fresh_copies(
    objects: Sequence[Element], existing: Sequence[Element], dx: float = 0.0, dy: float = 0.0
) -> list[Element]:
    """Copies moved by (dx, dy) with new group and component ids, so they stand apart."""
    first_group = next_group_id(existing)
    old_groups = sorted({g for obj in objects for g in group_ids(obj)})
    group_map = {g: first_group + n for n, g in enumerate(old_groups)}
    first_cid = max((component_id(obj) for obj in existing), default=0) + 1
    old_cids = sorted({component_id(obj) for obj in objects} - {0})
    cid_map = {c: first_cid + n for n, c in enumerate(old_cids)}
    if cid_map and max(cid_map.values()) > 0xFFFF:
        raise LayoutError("На плате слишком много компонентов")
    result = []
    for obj in objects:
        copy = moved(obj, dx, dy)
        copy = with_group_ids(copy, [group_map[g] for g in group_ids(obj)])
        if component_id(obj):
            copy = with_component_id(copy, cid_map[component_id(obj)])
        result.append(replace(copy, connections=b""))
    return result


def moved(obj: Element, dx: float, dy: float) -> Element:
    return transformed(obj, dx, dy)


# --- Layers and sides -------------------------------------------------------


def on_layer(obj: Element, layer: int) -> Element:
    """The object moved to another layer; pads only move between the copper sides."""
    if obj.kind in PADS and layer not in PAD_LAYERS:
        return obj
    if obj.children:
        children = [replace(child, layer=layer) for child in obj.children]
        return replace(obj, layer=layer, children=children)
    return replace(obj, layer=layer)


def to_other_side(objects: Sequence[Element]) -> list[Element]:
    """Flip objects to the other board side: mirrored left-right, top and bottom layers swapped."""
    flipped = mirror_all(objects, "x")
    return [
        on_layer(obj, COPPER_SIDES[obj.layer]) if obj.layer in COPPER_SIDES else obj
        for obj in flipped
    ]


# --- Alignment --------------------------------------------------------------


def _snap(value: float, grid: float) -> float:
    return round(round(value / grid) * grid, 6)


def anchor(objects: Sequence[Element]) -> Point:
    """Reference point of a unit: its first pad, else the centre of its outline."""
    for obj in objects:
        if obj.kind == SMD and obj.points:
            xs = [x for x, _ in obj.points]
            ys = [y for _, y in obj.points]
            return sum(xs) / len(xs), sum(ys) / len(ys)
        if obj.kind in PADS:
            return obj.x, obj.y
    left, bottom, right, top = bounds(objects)
    return (left + right) / 2, (bottom + top) / 2


def snapped_to_grid(
    elements: Sequence[Element], indices: Iterable[int], grid: float
) -> dict[int, Element]:
    """Move each unit so its anchor lies on the grid; loose tracks snap every node."""
    result: dict[int, Element] = {}
    for unit in units(elements, indices):
        objects = [elements[i] for i in unit]
        if len(unit) == 1 and objects[0].kind == LINE:
            obj = objects[0]
            points = [(_snap(x, grid), _snap(y, grid)) for x, y in obj.points]
            result[unit[0]] = replace(obj, points=points)
            continue
        if len(unit) == 1 and objects[0].kind == SEGMENT:
            obj = objects[0]
            result[unit[0]] = replace(
                obj,
                x=_snap(obj.x, grid),
                y=_snap(obj.y, grid),
                outer=_snap(obj.outer, grid),
                inner=_snap(obj.inner, grid),
            )
            continue
        x, y = anchor(objects)
        dx, dy = _snap(x, grid) - x, _snap(y, grid) - y
        for i, obj in zip(unit, objects, strict=True):
            result[i] = moved(obj, dx, dy)
    return result


ALIGN_MODES = ("left", "right", "top", "bottom", "hcenter", "vcenter")


def aligned(elements: Sequence[Element], indices: Iterable[int], mode: str) -> dict[int, Element]:
    """Align units by their outlines: to the outermost edge, or to the common centre line."""
    if mode not in ALIGN_MODES:
        raise ValueError(mode)
    groups = units(elements, indices)
    boxes = [bounds([elements[i] for i in unit]) for unit in groups]
    if len(groups) < 2:
        return {}
    if mode == "left":
        target = min(b[0] for b in boxes)
    elif mode == "right":
        target = max(b[2] for b in boxes)
    elif mode == "bottom":
        target = min(b[1] for b in boxes)
    elif mode == "top":
        target = max(b[3] for b in boxes)
    elif mode == "hcenter":
        target = sum((b[1] + b[3]) / 2 for b in boxes) / len(boxes)
    else:
        target = sum((b[0] + b[2]) / 2 for b in boxes) / len(boxes)
    result: dict[int, Element] = {}
    for unit, (left, bottom, right, top) in zip(groups, boxes, strict=True):
        dx = dy = 0.0
        if mode == "left":
            dx = target - left
        elif mode == "right":
            dx = target - right
        elif mode == "bottom":
            dy = target - bottom
        elif mode == "top":
            dy = target - top
        elif mode == "hcenter":
            dy = target - (bottom + top) / 2
        else:
            dx = target - (left + right) / 2
        for i in unit:
            result[i] = moved(elements[i], dx, dy)
    return result


# --- Track nodes ------------------------------------------------------------


def without_node(track: Element, node: int) -> Element | None:
    """The track with one node removed; None when only two nodes are left."""
    if track.kind != LINE or len(track.points) <= 2 or not 0 <= node < len(track.points):
        return None
    return replace(track, points=track.points[:node] + track.points[node + 1 :])


def nearest_segment(track: Element, point: Point) -> tuple[int, float]:
    """Index of the segment closest to point (segment i joins nodes i and i + 1), distance."""
    px, py = point
    best = (0, float("inf"))
    for i, ((x0, y0), (x1, y1)) in enumerate(zip(track.points, track.points[1:], strict=False)):
        dx, dy = x1 - x0, y1 - y0
        length = dx * dx + dy * dy
        t = 0.0 if length == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / length))
        distance = hypot(px - (x0 + t * dx), py - (y0 + t * dy))
        if distance < best[1]:
            best = (i, distance)
    return best


def with_node(track: Element, point: Point) -> Element:
    """The track with a new node at point, inserted into the closest segment."""
    segment, _ = nearest_segment(track, point)
    points = list(track.points)
    points.insert(segment + 1, point)
    return replace(track, points=points)


def split_track(track: Element, node: int) -> tuple[Element, Element] | None:
    """Two tracks meeting at an inner node; None at the ends."""
    if track.kind != LINE or not 0 < node < len(track.points) - 1:
        return None
    return replace(track, points=track.points[: node + 1]), replace(
        track, points=track.points[node:]
    )


def joined_tracks(first: Element, second: Element, tolerance: float = 1e-4) -> Element | None:
    """One track from two tracks on the same layer that share an end node."""
    if first.kind != LINE or second.kind != LINE or first.layer != second.layer:
        return None
    a, b = list(first.points), list(second.points)
    if len(a) < 2 or len(b) < 2:
        return None

    def same(p: Point, q: Point) -> bool:
        return hypot(p[0] - q[0], p[1] - q[1]) <= tolerance

    for left, right in ((a, b), (a, b[::-1]), (a[::-1], b), (a[::-1], b[::-1])):
        if same(left[-1], right[0]):
            return replace(first, points=left + right[1:])
    return None
