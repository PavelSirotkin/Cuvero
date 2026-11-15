"""HPGL output for milling machines: by default 1 unit = 1/40 mm, one pen per tool."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .model import Point

UNITS_PER_MM = 40


@dataclass
class Job:
    """One milling or drilling job, done with one pen (tool)."""

    name: str
    pen: int
    paths: list[list[Point]] = field(default_factory=list)  # tool centre lines
    drills: list[Point] = field(default_factory=list)  # plunges (PD at one point)
    circles: list[tuple[Point, float]] = field(default_factory=list)  # centre, radius (CI)
    mirror_width: float | None = None  # mirror x about this width (milling from below)
    slow: bool = False  # drill with the lowest feed (VS1)
    side: str = ""  # shown in the job list


def _xy(point: Point, job: Job, units: float) -> str:
    x, y = point
    if job.mirror_width is not None:
        x = job.mirror_width - x
    return f"{round(x * units)},{round(y * units)}"


def hpgl_text(jobs: Iterable[Job], units: float = UNITS_PER_MM) -> str:
    """HPGL text for the jobs in order; units is the number of HPGL units per mm."""
    lines = ["IN;", "PA;"]
    for job in jobs:
        lines.append(f"SP{job.pen};")
        if job.slow and (job.drills or job.circles):
            lines.append("VS1;")
        for path in job.paths:
            if len(path) < 2:
                continue
            lines.append(f"PU{_xy(path[0], job, units)};")
            lines.append("PD" + ",".join(_xy(p, job, units) for p in path[1:]) + ";")
        for point in job.drills:
            lines.append(f"PU{_xy(point, job, units)};PD;PU;")
        for centre, radius in job.circles:
            lines.append(f"PU{_xy(centre, job, units)};CI{round(radius * units)};")
    lines += ["PU;", "SP0;"]
    return "\n".join(lines) + "\n"


def register_holes(
    left: float, bottom: float, right: float, top: float, distance: float, count: int
) -> list[Point]:
    """Holes outside the board for turning it over exactly: 2 at the sides, 4 at corners."""
    if count <= 0:
        return []
    middle = (bottom + top) / 2
    if count == 2:
        return [(left - distance, middle), (right + distance, middle)]
    return [
        (left - distance, top + distance),
        (right + distance, top + distance),
        (left - distance, bottom - distance),
        (right + distance, bottom - distance),
    ]


def job_list(jobs: Sequence[Job]) -> str:
    """A short text describing the jobs, for the machine operator."""
    rows = [f"Перо {job.pen}: {job.name}" + (f" ({job.side})" if job.side else "") for job in jobs]
    return "\n".join(rows) + "\n"
