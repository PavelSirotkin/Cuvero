"""Components: objects bound by a component id with name and value labels."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from struct import Struct

from .macros import bounds
from .model import (
    LINE,
    MM,
    OBJECT,
    POINT,
    SMD,
    STROKE_TEXT,
    THT,
    Board,
    Element,
    LayoutError,
    Reader,
    decode,
    length_prefixed,
)

COMPONENT_REF, COMPONENT_VALUE = 1, 2  # STROKE_TEXT shape codes of the two labels
TEXT_HEIGHT = 1.3


def component_id(obj: Element) -> int:
    return int.from_bytes(obj.record[28:30], "little") if len(obj.record) >= 30 else 0


def with_component_id(obj: Element, cid: int) -> Element:
    record = bytearray(obj.record or bytes(OBJECT.size))
    record[28:30] = cid.to_bytes(2, "little")
    record[30] = 0  # not selected
    return replace(obj, record=bytes(record))


def is_hidden_label(obj: Element) -> bool:
    """Component name and value texts are hidden unless their visibility flag is set."""
    return (
        obj.kind == STROKE_TEXT
        and obj.shape in (COMPONENT_REF, COMPONENT_VALUE)
        and component_id(obj) > 0
        and not obj.filled
    )


def component_block(
    package: str, comment: str = "", rotation: float = 0.0, pick_place: bool = True
) -> bytes:
    def text(value: str) -> bytes:
        return length_prefixed(value.encode("cp1251", "replace"))

    return (
        POINT.pack(0, 0)
        + bytes([0])
        + Struct("<d").pack(rotation)
        + text(package)
        + text(comment)
        + bytes([1 if pick_place else 0])
    )


def empty_label(
    board: Board,
    shape: int,
    x: float,
    y: float,
    layer: int,
    cid: int,
    identifier: bytes,
    package: str = "",
) -> Element:
    """Hidden, empty component label as the original program stores it.

    An empty text still carries one stroke: a tiny rectangle at the text origin.
    """
    templates = [
        obj
        for obj in board.elements
        if obj.kind == STROKE_TEXT and obj.shape == shape and component_id(obj)
    ]
    record = templates[-1].record if templates else b""
    h = TEXT_HEIGHT
    w, d = h * 0.0444, h * 0.0533
    stroke = [(x, y + d), (x, y), (x - w, y), (x - w, y + d), (x, y + d), (x, y)]
    child = Element(LINE, layer=1, width=h * 0.1587, points=stroke)
    label = Element(
        STROKE_TEXT,
        x=x,
        y=y,
        outer=h,
        inner=2 / MM,
        width=1 / MM,
        layer=layer,
        shape=shape,
        clearance=0.4,
        record=record,
        identifier=identifier,
        children=[child],
        component=component_block(package) if shape == COMPONENT_REF else b"",
    )
    return with_component_id(label, cid)


def make_component(
    board: Board, elements: Sequence[Element], package: str, side: str = "top"
) -> list[Element]:
    """Bind placed macro objects into one component with hidden name and value labels."""
    cid = max((component_id(obj) for obj in board.elements), default=0) + 1
    if cid > 0xFFFF:
        raise LayoutError("На плате слишком много компонентов")
    result = [with_component_id(obj, cid) for obj in elements]
    shapes = {obj.shape for obj in result if is_label(obj)}
    if {COMPONENT_REF, COMPONENT_VALUE} <= shapes:
        # Library macros often carry their own name and value labels: reuse them.
        return [
            with_package(obj, package) if is_label(obj) and obj.shape == COMPONENT_REF else obj
            for obj in result
        ]
    result = strip_labels(result)
    identifier = next((obj.identifier for obj in elements if obj.identifier), b"")
    left, bottom, right, top = bounds(result)
    layer = 2 if side == "top" else 4
    x, y = (left + right) / 2, (bottom + top) / 2
    result.append(empty_label(board, COMPONENT_REF, x, y, layer, cid, identifier, package))
    result.append(
        empty_label(board, COMPONENT_VALUE, x + TEXT_HEIGHT * 1.5, y, layer, cid, identifier)
    )
    return result


def is_label(obj: Element) -> bool:
    return obj.kind == STROKE_TEXT and obj.shape in (COMPONENT_REF, COMPONENT_VALUE)


def strip_labels(elements: Iterable[Element]) -> list[Element]:
    """Objects without component name/value labels, for placing a macro as loose objects."""
    return [obj for obj in elements if not is_label(obj)]


def with_package(label: Element, package: str) -> Element:
    """Set the package name in a name label's component block, keeping its other fields."""
    block = label.component
    if len(block) < 26:
        return replace(label, component=component_block(package))
    reader = Reader(block)
    head = bytes(reader.take(17))
    old = bytes(reader.take(reader.integer()))
    rest = bytes(block[reader.offset :])
    if old.split(b"\x00", 1)[0]:
        return label
    return replace(
        label, component=head + length_prefixed(package.encode("cp1251", "replace")) + rest
    )


def component_package(elements: Iterable[Element], cid: int) -> str:
    """Package name stored with the component's name label, or an empty string."""
    for obj in elements:
        if (
            obj.kind == STROKE_TEXT
            and obj.shape == COMPONENT_REF
            and component_id(obj) == cid
            and len(obj.component) >= 21
        ):
            reader = Reader(obj.component)
            reader.take(17)
            return decode(reader.take(reader.integer()))
    return ""


BLOCK_HEAD = 17  # offset (two floats), centre mode, rotation (double)


def component_labels(elements: Sequence[Element], cid: int) -> tuple[int | None, int | None]:
    """Indices of the component's name and value labels."""
    found: dict[int, int] = {}
    for index, obj in enumerate(elements):
        if is_label(obj) and component_id(obj) == cid and obj.shape not in found:
            found[obj.shape] = index
    return found.get(COMPONENT_REF), found.get(COMPONENT_VALUE)


def component_comment(label: Element) -> str:
    block = label.component
    if len(block) < BLOCK_HEAD + 8:
        return ""
    reader = Reader(block)
    reader.take(BLOCK_HEAD)
    reader.take(reader.integer())
    return decode(reader.take(reader.integer()))


def component_rotation(label: Element) -> float:
    if len(label.component) < BLOCK_HEAD:
        return 0.0
    return float(Struct("<d").unpack(bytes(label.component[9:17]))[0])


def with_component_details(label: Element, package: str, comment: str) -> Element:
    """A name label with a new package name and comment, keeping the other block fields."""
    block = label.component
    if len(block) < BLOCK_HEAD + 8:
        return replace(label, component=component_block(package, comment))
    reader = Reader(block)
    head = bytes(reader.take(BLOCK_HEAD))
    reader.take(reader.integer())
    reader.take(reader.integer())
    rest = bytes(block[reader.offset :])

    def text(value: str) -> bytes:
        return length_prefixed(value.encode("cp1251", "replace"))

    return replace(label, component=head + text(package) + text(comment) + rest)


def dissolved(elements: Sequence[Element], cid: int) -> tuple[dict[int, Element], list[int]]:
    """Free the component's objects: changed objects by index and the labels to delete."""
    changed: dict[int, Element] = {}
    labels: list[int] = []
    for index, obj in enumerate(elements):
        if component_id(obj) != cid:
            continue
        if is_label(obj):
            labels.append(index)
        else:
            changed[index] = with_component_id(obj, 0)
    return changed, labels


@dataclass
class ComponentInfo:
    cid: int
    name: str
    value: str
    top: bool
    x: float  # centre of the component's pads (or objects), board coordinates
    y: float
    rotation: float
    package: str
    comment: str
    smd: bool  # only SMD pads
    indices: list[int]


def components_of(board: Board) -> list[ComponentInfo]:
    """Every component of a board with its labels, place and package, in board order."""
    members: dict[int, list[int]] = {}
    for index, obj in enumerate(board.elements):
        cid = component_id(obj)
        if cid:
            members.setdefault(cid, []).append(index)
    result = []
    for cid, indices in members.items():
        ref, value = component_labels(board.elements, cid)
        objects = [board.elements[i] for i in indices]
        pads = [obj for obj in objects if obj.kind in (THT, SMD)]
        shapes = [obj for obj in (pads or objects) if not is_label(obj)] or objects
        left, bottom, right, top = bounds(shapes)
        label = board.elements[ref] if ref is not None else None
        result.append(
            ComponentInfo(
                cid=cid,
                name=label.text if label else "",
                value=board.elements[value].text if value is not None else "",
                top=all(obj.layer not in (3, 4) for obj in pads) if pads else True,
                x=(left + right) / 2,
                y=(bottom + top) / 2,
                rotation=component_rotation(label) if label else 0.0,
                package=component_package(board.elements, cid),
                comment=component_comment(label) if label else "",
                smd=bool(pads) and all(obj.kind == SMD for obj in pads),
                indices=indices,
            )
        )
    return result
