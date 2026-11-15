"""Project-level data: project information, the active board, and whole-board operations."""

from dataclasses import dataclass, replace
from struct import Struct

from .boards import rename_board
from .editing import units
from .macros import bounds
from .model import COUNT, Board, Project, decode, length_prefixed

# Trailer: active board (uint32), then title, author and company as Pascal strings of
# 100 characters (a length byte and 100 bytes each), then the comment with a length prefix.
ACTIVE = Struct("<I")
FIELD = 101
FIELDS_END = ACTIVE.size + 3 * FIELD
TEXT_LIMIT = 100
COMMENT_LIMIT = 1900
SIZE_OFFSET = 35  # board header: name (31 bytes) and 4 unknown bytes come first
SIZE = Struct("<II")
MULTILAYER_OFFSET = 529


@dataclass(frozen=True)
class ProjectInfo:
    title: str = ""
    author: str = ""
    company: str = ""
    comment: str = ""


def _encode(text: str, limit: int) -> bytes:
    return text.encode("cp1251", "replace")[:limit]


def project_info(project: Project) -> ProjectInfo:
    trailer = project.trailer
    if len(trailer) < FIELDS_END + COUNT.size:
        return ProjectInfo()
    texts = []
    for i in range(3):
        start = ACTIVE.size + i * FIELD
        length = min(trailer[start], TEXT_LIMIT)
        texts.append(decode(trailer[start + 1 : start + 1 + length]))
    (length,) = COUNT.unpack_from(trailer, FIELDS_END)
    comment = decode(trailer[FIELDS_END + COUNT.size : FIELDS_END + COUNT.size + length])
    return ProjectInfo(texts[0], texts[1], texts[2], comment.replace("\r\n", "\n"))


def with_project_info(project: Project, info: ProjectInfo) -> Project:
    """The project with new information; bytes after each text's end are kept."""
    trailer = bytearray(project.trailer[:FIELDS_END].ljust(FIELDS_END, bytes(1)))
    for i, text in enumerate((info.title, info.author, info.company)):
        start = ACTIVE.size + i * FIELD
        raw = _encode(text, TEXT_LIMIT)
        trailer[start] = len(raw)
        trailer[start + 1 : start + 1 + len(raw)] = raw
    comment = _encode(info.comment.replace("\r\n", "\n").replace("\n", "\r\n"), COMMENT_LIMIT)
    return replace(project, trailer=bytes(trailer) + length_prefixed(comment))


def active_board(project: Project) -> int:
    if len(project.trailer) < ACTIVE.size:
        return 0
    (index,) = ACTIVE.unpack_from(project.trailer, 0)
    return index if index < len(project.boards) else 0


def with_active_board(project: Project, index: int) -> Project:
    trailer = bytearray(project.trailer)
    ACTIVE.pack_into(trailer, 0, index)
    return replace(project, trailer=bytes(trailer))


def board_settings(board: Board, name: str, width: float, height: float, multilayer: bool) -> Board:
    """The board with a new name, work-area size and multilayer flag."""
    renamed = rename_board(board, name)
    header = bytearray(renamed.header)
    SIZE.pack_into(header, SIZE_OFFSET, round(width * 10_000), round(height * 10_000))
    header[MULTILAYER_OFFSET] = int(multilayer)
    return replace(renamed, width=width, height=height, multilayer=multilayer, header=bytes(header))


def copied_board(board: Board, name: str) -> Board:
    """An independent copy of a board; objects are immutable and can be shared."""
    return replace(rename_board(board, name), elements=list(board.elements))


def single_board_project(project: Project, index: int) -> Project:
    """A project holding one board, with the original project information."""
    return with_active_board(replace(project, boards=[project.boards[index]]), 0)


def outside_work_area(board: Board) -> list[int]:
    """Indices of units (components, groups, objects) lying entirely outside the work area."""
    result = []
    for unit in units(board.elements, range(len(board.elements))):
        left, bottom, right, top = bounds(board.elements[i] for i in unit)
        # Board Y runs from 0 down to -height.
        outside = right < 0 or left > board.width or top < -board.height or bottom > 0
        if outside:
            result.extend(unit)
    return sorted(result)


PLANES_OFFSET = 43  # board header: one auto ground plane flag per layer C1, S1, C2, S2, I1, I2, O


def has_plane(board: Board, layer: int) -> bool:
    return 1 <= layer <= 7 and bool(board.planes[layer - 1])


def with_plane(board: Board, layer: int, on: bool) -> Board:
    """The board with the auto ground plane of one copper layer switched on or off."""
    header = bytearray(board.header)
    header[PLANES_OFFSET + layer - 1] = int(on)
    planes = bytes(header[PLANES_OFFSET : PLANES_OFFSET + 7])
    return replace(board, header=bytes(header), planes=planes)
