"""Board model and the .lay6 file format: reading and byte-exact writing."""

import re
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from struct import Struct

SEGMENT, THT, OUTLINE_TEXT, POLYGON, CIRCLE, LINE, STROKE_TEXT, SMD = range(1, 9)
MM = 10_000

Point = tuple[float, float]
MAGIC = b"\x06\x33\xaa\xff"

# Field layout reference: KiCad's sprint_layout_parser.cpp, parseObject.
OBJECT = Struct("<Bffffi x BB 7x i 5x B i 5x BBB i BB 18x")
POINT = Struct("<ff")
COUNT = Struct("<I")
EDITABLE = (THT, SMD, LINE, SEGMENT)
WITH_POINTS = (THT, POLYGON, LINE, SMD)
PADS = (THT, SMD)


def _field_spans(fmt: str) -> list[tuple[int, int]]:
    """Byte ranges of the non-padding fields of a little-endian struct format."""
    spans, offset = [], 0
    for count, code in re.findall(r"(\d*)([a-zA-Z])", fmt):
        size = int(count or 1) * (1 if code in "xBb" else 4)
        if code != "x":
            spans.append((offset, offset + size))
        offset += size
    return spans


FIELD_SPANS = _field_spans(OBJECT.format[1:])
FLAGS = {9, 11, 12, 13, 15, 16}  # filled, mirror_x, mirror_y, keepout, plated, soldermask
# Byte offsets of the component identifier and the selection flag in OBJECT.
COMPONENT_ID = slice(28, 31)


class LayoutError(ValueError):
    pass


@dataclass
class Element:
    kind: int
    x: float = 0.0
    y: float = 0.0
    outer: float = 0.0
    inner: float = 0.0
    width: float = 0.0
    layer: int = 1
    shape: int = 0
    start: int = 0
    filled: bool = False
    clearance: float = 0.0
    mirror_x: bool = False
    mirror_y: bool = False
    keepout: bool = False
    rotation: int = 0
    plated: bool = False
    soldermask: bool = False
    text: str = ""
    points: list[Point] = field(default_factory=list)
    children: list["Element"] = field(default_factory=list)
    # Bytes kept verbatim so that unknown fields survive a save.
    record: bytes = b""
    raw_text: bytes = b""
    identifier: bytes = b""
    groups: bytes = b""
    component: bytes = b""
    connections: bytes = b""
    record_offset: int = 0
    points_offset: int = 0


@dataclass
class Board:
    name: str
    width: float
    height: float
    planes: bytes
    multilayer: bool
    elements: list[Element]
    header: bytes = b""


@dataclass
class Project:
    boards: list[Board]
    trailer: bytes


class Reader:
    def __init__(self, data: bytes):
        self.data = memoryview(data)
        self.offset = 0

    def take(self, size: int) -> memoryview:
        end = self.offset + size
        if end > len(self.data):
            raise LayoutError(f"Неожиданный конец файла (позиция {self.offset:#x})")
        result = self.data[self.offset : end]
        self.offset = end
        return result

    def integer(self) -> int:
        return int.from_bytes(self.take(4), "little")

    def count(self, record_size: int) -> int:
        count = self.integer()
        if count * record_size > len(self.data) - self.offset:
            raise LayoutError(f"Недопустимое число записей (позиция {self.offset - 4:#x})")
        return count

    def block(self, record_size: int) -> bytes:
        """Return a counted block, including its count, as raw bytes."""
        start = self.offset
        self.take(self.count(record_size) * record_size)
        return bytes(self.data[start : self.offset])

    def element(self, child: bool = False) -> Element:
        offset = self.offset
        record = bytes(self.take(OBJECT.size))
        (
            kind,
            x,
            y,
            outer,
            inner,
            width,
            layer,
            shape,
            start,
            filled,
            clearance,
            mirror_x,
            mirror_y,
            keepout,
            rotation,
            plated,
            soldermask,
        ) = OBJECT.unpack(record)
        if kind not in range(1, 9) or (child and kind == STROKE_TEXT):
            raise LayoutError(f"Тип объекта {kind}, слой {layer}, позиция {offset:#x}")
        if not all(isfinite(v) for v in (x, y, outer, inner)):
            raise LayoutError(f"Некорректная геометрия на слое {layer}, позиция {offset:#x}")
        obj = Element(
            kind,
            x / MM,
            y / MM,
            outer / MM,
            inner / MM,
            width / MM,
            layer,
            shape,
            start,
            bool(filled),
            clearance / MM,
            bool(mirror_x),
            bool(mirror_y),
            bool(keepout),
            rotation,
            bool(plated),
            bool(soldermask),
            record=record,
            record_offset=offset,
        )
        if not child:
            obj.raw_text = bytes(self.take(self.integer()))
            obj.text = decode(obj.raw_text)
            obj.identifier = bytes(self.take(self.integer()))
            obj.groups = self.block(4)
        if kind in WITH_POINTS:
            count = self.count(POINT.size)
            obj.points_offset = self.offset
            for _ in range(count):
                px, py = POINT.unpack(self.take(POINT.size))
                if not isfinite(px) or not isfinite(py):
                    raise LayoutError(f"Некорректная точка на слое {layer}, позиция {offset:#x}")
                obj.points.append((px / MM, py / MM))
        if kind == STROKE_TEXT:
            obj.children = [self.element(child=True) for _ in range(self.count(OBJECT.size))]
            if shape == 1:
                start = self.offset
                self.take(17)  # Component centre, centre mode and angle
                self.take(self.integer())  # Package
                self.take(self.integer())  # Comment
                self.take(1)
                obj.component = bytes(self.data[start : self.offset])
        return obj

    def board(self, index: int) -> Board:
        start = self.offset
        name_field = self.take(31)
        name = decode(name_field[1 : 1 + min(name_field[0], 30)])
        self.take(4)
        width, height = self.integer() / MM, self.integer() / MM
        planes = bytes(self.take(7))
        header_tail = self.take(480)
        header = bytes(self.data[start : self.offset])
        elements = [self.element() for _ in range(self.count(OBJECT.size))]
        for obj in elements:
            if obj.kind in PADS:
                obj.connections = self.block(4)
        return Board(
            name or f"Плата {index}", width, height, planes, bool(header_tail[-1]), elements, header
        )


def decode(data: bytes | memoryview) -> str:
    raw = bytes(data).split(b"\x00", 1)[0]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1251", errors="replace")


def load(path: Path) -> list[Board]:
    return parse(path.read_bytes())


def parse(data: bytes) -> list[Board]:
    return parse_project(data).boards


def parse_project(data: bytes) -> Project:
    reader = Reader(data)
    if reader.take(4) != MAGIC:
        raise LayoutError("Ожидался файл платы .lay6")
    count = reader.count(534)
    if not count:
        raise LayoutError("В проекте нет плат")
    boards: list[Board] = []
    for index in range(1, count + 1):
        try:
            boards.append(reader.board(index))
        except LayoutError as error:
            raise LayoutError(f"Плата {index}: {error}") from error
    trailer = reader.offset
    reader.take(307)  # Active board and fixed project metadata
    reader.take(reader.integer())  # Project comment
    return Project(boards, bytes(reader.data[trailer:]))


def length_prefixed(data: bytes) -> bytes:
    return COUNT.pack(len(data)) + data


def write_element(out: bytearray, obj: Element, child: bool = False) -> None:
    record = bytearray(obj.record or bytes(OBJECT.size))
    # Integer fields were divided by MM on reading; rounding restores them exactly.
    values = (
        obj.kind,
        obj.x * MM,
        obj.y * MM,
        obj.outer * MM,
        obj.inner * MM,
        round(obj.width * MM),
        obj.layer,
        obj.shape,
        obj.start,
        int(obj.filled),
        round(obj.clearance * MM),
        int(obj.mirror_x),
        int(obj.mirror_y),
        int(obj.keepout),
        obj.rotation,
        int(obj.plated),
        int(obj.soldermask),
    )
    # Flag bytes may hold values other than 0 and 1; keep them while the meaning is unchanged.
    original = OBJECT.unpack(record)
    merged = tuple(
        old if index in FLAGS and bool(old) == bool(new) else new
        for index, (old, new) in enumerate(zip(original, values, strict=True))
    )
    try:
        packed = OBJECT.pack(*merged)
    except Exception as error:
        raise LayoutError(f"Значение вне диапазона на слое {obj.layer}: {error}") from error
    # Copy only the known fields: padding bytes keep their original contents.
    for start, end in FIELD_SPANS:
        record[start:end] = packed[start:end]
    out += record
    if not child:
        text = (
            obj.raw_text
            if decode(obj.raw_text) == obj.text
            else obj.text.encode("cp1251", "replace")
        )
        out += length_prefixed(text)
        out += length_prefixed(obj.identifier)
        out += obj.groups or COUNT.pack(0)
    if obj.kind in WITH_POINTS:
        out += COUNT.pack(len(obj.points))
        for x, y in obj.points:
            out += POINT.pack(x * MM, y * MM)
    if obj.kind == STROKE_TEXT:
        out += COUNT.pack(len(obj.children))
        for item in obj.children:
            write_element(out, item, child=True)
        if obj.shape == 1:
            out += obj.component or bytes(17) + COUNT.pack(0) * 2 + bytes(1)


def serialize(project: Project) -> bytes:
    out = bytearray(MAGIC)
    out += COUNT.pack(len(project.boards))
    for board in project.boards:
        out += board.header
        out += COUNT.pack(len(board.elements))
        for obj in board.elements:
            write_element(out, obj)
        for obj in board.elements:
            if obj.kind in PADS:
                out += obj.connections or COUNT.pack(0)
    out += project.trailer
    return bytes(out)
