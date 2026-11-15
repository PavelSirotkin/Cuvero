"""Text-IO: the original program's plain text exchange of board objects.

One object per line, "KIND,KEY=value,...;". Lengths are in 1/10000 mm from the board's
top left corner with y pointing down; pad and SMD angles in 1/100 degree clockwise, text,
arc and circle angles in 1/1000 degree. Groups are enclosed in GROUP; ... END_GROUP; and
components in BEGIN_COMPONENT,...; ... END_COMPONENT;. Files are Windows-1251 with CRLF.
Learnt from files the original program exported.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import replace
from math import cos, radians, sin

from .components import (
    COMPONENT_REF,
    COMPONENT_VALUE,
    component_block,
    component_comment,
    component_id,
    component_package,
    is_label,
    with_component_id,
)
from .editing import group_ids, next_group_id, with_group_ids
from .model import CIRCLE, LINE, MM, POLYGON, SMD, STROKE_TEXT, THT, Board, Element, Point
from .nets import wired_to, with_wires
from .objects import new_pad, new_smd, new_track
from .properties import (
    centre_of,
    circle_angles,
    has_thermal,
    is_hatched,
    pad_rotation,
    smd_angle,
    smd_size,
    thermal_layers_equal,
    with_circle,
    with_hatching,
    with_thermal,
    with_thermal_percent,
)
from .shapes import new_circle, new_polygon
from .texts import new_text, text_spacing, text_weight

DEFAULT_CLEARANCE = 4000  # 0.4 mm: not written


class TextIOError(ValueError):
    pass


def _n(value: float) -> int:
    return round(value * MM)


def _xy(point: Point) -> str:
    x, y = point
    return f"{_n(x)}/{_n(-y)}"


def _points(points: Iterable[Point]) -> list[str]:
    return [f"P{k}={_xy(p)}" for k, p in enumerate(points)]


def _common(obj: Element, mask_default: bool) -> list[str]:
    parts = [f"LAYER={obj.layer}"]
    clearance = _n(obj.clearance)
    if clearance != DEFAULT_CLEARANCE:
        parts.append(f"CLEAR={clearance}")
    if obj.keepout:
        parts.append("CUTOUT=true")
    if obj.soldermask != mask_default:
        parts.append(f"SOLDERMASK={'true' if obj.soldermask else 'false'}")
    return parts


def _thermal(obj: Element) -> list[str]:
    if not has_thermal(obj):
        return []
    individual = "false" if thermal_layers_equal(obj) else "true"
    tracks = obj.start & (0xFFFFFFFF if obj.kind == THT else 0xFF)
    percent = obj.rotation if obj.rotation > 0 else 100
    return [
        "THERMAL=true",
        f"THERMAL_TRACKS_INDIVIDUAL={individual}",
        f"THERMAL_TRACKS={tracks}",
        f"THERMAL_TRACKS_WIDTH={percent}",
    ]


def _angle(degrees_ccw: float) -> int:
    return round((-degrees_ccw) % 360 * 100) % 36000


def object_line(obj: Element, index: int, wired: bool) -> str | None:
    """The Text-IO line of one object (without indentation), or None if not exchanged."""
    if obj.kind == THT:
        parts = ["PAD", *_common(obj, True)]
        parts += [f"POS={_xy((obj.x, obj.y))}", f"FORM={obj.shape}"]
        parts += [f"SIZE={_n(2 * obj.outer)}", f"DRILL={_n(2 * obj.inner)}"]
        if obj.plated:
            parts.append("VIA=true")
        angle = _angle(pad_rotation(obj))
        if angle:
            parts.append(f"ROTATION={angle}")
        parts += _thermal(obj)
        if wired:
            parts.append(f"PAD_ID={index}")
            parts += [f"CON{k}={t}" for k, t in enumerate(wired_to(obj))]
    elif obj.kind == SMD:
        width, height = smd_size(obj)
        parts = ["SMDPAD", *_common(obj, True), f"POS={_xy(centre_of(obj))}"]
        parts += [f"SIZE_X={_n(width)}", f"SIZE_Y={_n(height)}"]
        angle = _angle(smd_angle(obj))
        if angle:
            parts.append(f"ROTATION={angle}")
        parts += _thermal(obj)
        if wired:
            parts.append(f"PAD_ID={index}")
            parts += [f"CON{k}={t}" for k, t in enumerate(wired_to(obj))]
    elif obj.kind == LINE:
        parts = ["TRACK", *_common(obj, False), f"WIDTH={_n(obj.width)}", *_points(obj.points)]
    elif obj.kind == POLYGON:
        parts = ["ZONE", *_common(obj, False), f"WIDTH={_n(obj.width)}"]
        if is_hatched(obj):
            parts.append("HATCH=true")
        parts += _points(obj.points)
    elif obj.kind == CIRCLE:
        start, stop = circle_angles(obj)
        parts = ["CIRCLE", *_common(obj, False), f"CENTER={_xy((obj.x, obj.y))}"]
        parts += [f"RADIUS={_n((obj.outer + obj.inner) / 2)}", f"WIDTH={_n(obj.outer - obj.inner)}"]
        if start:
            parts.append(f"START={round(start * 1000)}")
        if stop:
            parts.append(f"STOP={round(stop * 1000)}")
        if obj.filled:
            parts.append("FILL=true")
    elif obj.kind == STROKE_TEXT:
        kind = "TEXT"
        if is_label(obj):
            kind = "ID_TEXT" if obj.shape == COMPONENT_REF else "VALUE_TEXT"
        parts = [kind]
        if is_label(obj) and not obj.filled:
            parts.append("VISIBLE=false")
        parts += [*_common(obj, False), f"POS={_xy((obj.x, obj.y))}"]
        parts.append(f"HEIGHT={_n(obj.outer)}")
        if text_weight(obj) != 1:
            parts.append(f"THICKNESS={text_weight(obj)}")
        if text_spacing(obj) != 1:
            parts.append(f"STYLE={text_spacing(obj)}")
        if obj.mirror_x:
            parts.append("MIRROR_HORZ=true")
        if obj.mirror_y:
            parts.append("MIRROR_VERT=true")
        if obj.rotation:
            parts.append(f"ROTATION={round(obj.rotation * 1000)}")
        parts.append(f"TEXT=|{obj.text}|")
    else:
        return None
    return ",".join(parts) + ";"


def export_text(board: Board) -> str:
    """The board's objects as Text-IO text (to be written in Windows-1251 with CRLF)."""
    elements = board.elements
    wired = {i for i, obj in enumerate(elements) if wired_to(obj)}
    loose: list[str] = []
    components: dict[int, list[int]] = {}
    groups: dict[int, list[int]] = {}
    for index, obj in enumerate(elements):
        cid = component_id(obj)
        if cid:
            components.setdefault(cid, []).append(index)
            continue
        ids = group_ids(obj)
        if ids:
            groups.setdefault(ids[-1], []).append(index)
            continue
        line = object_line(obj, index, index in wired)
        if line:
            loose.append(line)
    lines = list(loose)
    for members in groups.values():
        lines.append("GROUP;")
        body = [object_line(elements[i], i, i in wired) for i in members]
        lines += ["   " + line for line in body if line]
        lines.append("END_GROUP;")
    for cid, members in components.items():
        label = next(
            (elements[i] for i in members if is_label(elements[i]) and elements[i].shape == 1),
            None,
        )
        head = ["BEGIN_COMPONENT"]
        comment = component_comment(label) if label is not None else ""
        if comment:
            head.append(f"COMMENT=|{comment}|")
        if label is not None and label.component and label.component[-1]:
            head.append("USE_PICKPLACE=true")
        package = component_package(elements, cid)
        if package:
            head.append(f"PACKAGE=|{package}|")
        lines.append(",".join(head) + ";")
        body = [object_line(elements[i], i, i in wired) for i in members]
        lines += ["   " + line for line in body if line]
        lines.append("END_COMPONENT;")
    return "\r\n".join(lines) + ("\r\n" if lines else "")


# --- import --------------------------------------------------------------------------------

TEXT_FIELD = re.compile(r"(\w+)=(\|[^|]*\||[^,;]*)")


def _parse_line(line: str) -> tuple[str, dict[str, str]]:
    text = line.strip().rstrip(";")
    kind, _, rest = text.partition(",")
    values = {
        key: value.strip("|") if value.startswith("|") else value
        for key, value in TEXT_FIELD.findall(rest)
    }
    return kind.strip(), values


def _point(value: str) -> Point:
    try:
        x, y = value.split("/")
        return int(x) / MM, -int(y) / MM
    except ValueError as error:
        raise TextIOError(f"Непонятная точка: {value}") from error


def _mm(values: dict[str, str], key: str, default: float = 0.0) -> float:
    return int(values[key]) / MM if key in values else default


def _flag(values: dict[str, str], key: str, default: bool) -> bool:
    return values[key].lower() == "true" if key in values else default


def _rotated_about(points: Sequence[Point], angle_ccw: float, cx: float, cy: float) -> list[Point]:
    c, s = cos(radians(angle_ccw)), sin(radians(angle_ccw))
    return [
        (round(cx + (x - cx) * c - (y - cy) * s, 6), round(cy + (x - cx) * s + (y - cy) * c, 6))
        for x, y in points
    ]


def _object(board: Board, kind: str, v: dict[str, str]) -> Element | None:
    layer = int(v.get("LAYER", "1"))
    if kind == "PAD":
        x, y = _point(v["POS"])
        size, drill = _mm(v, "SIZE", 1.6), _mm(v, "DRILL", 0.8)
        obj = new_pad(board, layer, x, y, size, drill, int(v.get("FORM", "1")))
        obj = replace(obj, plated=_flag(v, "VIA", False))
        angle = -int(v.get("ROTATION", "0")) / 100
        if angle:
            obj = replace(obj, points=_rotated_about(obj.points, angle, x, y))
    elif kind == "SMDPAD":
        x, y = _point(v["POS"])
        obj = new_smd(board, layer, x, y, _mm(v, "SIZE_X", 1.0), _mm(v, "SIZE_Y", 1.0))
        angle = -int(v.get("ROTATION", "0")) / 100
        if angle:
            obj = replace(obj, points=_rotated_about(obj.points, angle, x, y))
    elif kind in ("TRACK", "ZONE"):
        points = [_point(v[f"P{k}"]) for k in range(len(v)) if f"P{k}" in v]
        if kind == "TRACK":
            obj = new_track(board, layer, points, _mm(v, "WIDTH", 0.4))
        else:
            obj = new_polygon(board, layer, points, _mm(v, "WIDTH", 0.0))
            obj = replace(obj, points=points)  # as written: closed or not
            obj = with_hatching(obj, _flag(v, "HATCH", False))
    elif kind == "CIRCLE":
        x, y = _point(v["CENTER"])
        width = _mm(v, "WIDTH", 0.4)
        obj = new_circle(board, layer, x, y, 2 * _mm(v, "RADIUS", 1.0), width)
        obj = with_circle(
            obj,
            2 * _mm(v, "RADIUS", 1.0),
            width,
            int(v.get("START", "0")) / 1000,
            int(v.get("STOP", "0")) / 1000,
            _flag(v, "FILL", False),
        )
    elif kind in ("TEXT", "ID_TEXT", "VALUE_TEXT"):
        x, y = _point(v["POS"])
        obj = new_text(
            board,
            layer,
            x,
            y,
            v.get("TEXT", ""),
            _mm(v, "HEIGHT", 2.0),
            int(v.get("THICKNESS", "1")),
            int(v.get("STYLE", "1")),
            round(int(v.get("ROTATION", "0")) / 1000),
            _flag(v, "MIRROR_HORZ", False),
            _flag(v, "MIRROR_VERT", False),
        )
        if kind != "TEXT":
            shape = COMPONENT_REF if kind == "ID_TEXT" else COMPONENT_VALUE
            obj = replace(obj, shape=shape, filled=_flag(v, "VISIBLE", True))
    else:
        return None
    obj = replace(
        obj,
        clearance=int(v["CLEAR"]) / MM if "CLEAR" in v else DEFAULT_CLEARANCE / MM,
        keepout=_flag(v, "CUTOUT", False),
        soldermask=_flag(v, "SOLDERMASK", obj.kind in (THT, SMD)),
    )
    if _flag(v, "THERMAL", False):
        obj = with_thermal(obj, True, int(v.get("THERMAL_TRACKS", "85")) & 0xFF)
        tracks = int(v.get("THERMAL_TRACKS", "1431655765"))
        obj = replace(obj, start=tracks if obj.kind == THT else tracks & 0xFF)
        obj = with_thermal_percent(obj, int(v.get("THERMAL_TRACKS_WIDTH", "100")))
    return obj


def import_text(board: Board, text: str) -> list[Element]:
    """New objects read from Text-IO text, to be appended to the board."""
    result: list[Element] = []
    pad_ids: dict[int, int] = {}  # PAD_ID in the file -> position in result
    wires: list[tuple[int, list[int]]] = []
    group: list[int] | None = None
    component: list[int] | None = None
    component_head: dict[str, str] = {}
    next_group = next_group_id(board.elements)
    next_cid = max((component_id(obj) for obj in board.elements), default=0) + 1
    for number, raw in enumerate(text.replace("\r", "").split("\n"), 1):
        line = raw.strip()
        if not line:
            continue
        kind, values = _parse_line(line)
        if kind == "GROUP":
            group = []
            continue
        if kind == "END_GROUP":
            for i in group or []:
                result[i] = with_group_ids(result[i], [*group_ids(result[i]), next_group])
            next_group += 1
            group = None
            continue
        if kind == "BEGIN_COMPONENT":
            component, component_head = [], values
            continue
        if kind == "END_COMPONENT":
            for i in component or []:
                obj = with_component_id(result[i], next_cid)
                if obj.kind == STROKE_TEXT and obj.shape == COMPONENT_REF:
                    obj = replace(
                        obj,
                        component=component_block(
                            component_head.get("PACKAGE", ""),
                            component_head.get("COMMENT", ""),
                            pick_place=_flag(component_head, "USE_PICKPLACE", False),
                        ),
                    )
                result[i] = obj
            next_cid += 1
            component = None
            continue
        try:
            made = _object(board, kind, values)
        except (KeyError, ValueError) as error:
            raise TextIOError(f"Строка {number}: {line}") from error
        if made is None:
            continue
        position = len(result)
        result.append(made)
        if group is not None:
            group.append(position)
        if component is not None:
            component.append(position)
        if "PAD_ID" in values:
            pad_ids[int(values["PAD_ID"])] = position
            targets = [int(values[f"CON{k}"]) for k in range(64) if f"CON{k}" in values]
            wires.append((position, targets))
    base = len(board.elements)
    for position, targets in wires:
        mapped = [base + pad_ids[t] for t in targets if t in pad_ids]
        result[position] = with_wires(result[position], mapped)
    return result
