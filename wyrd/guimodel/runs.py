"""Run list, summary rows and step directories read from ``wyrd.db`` and run folders."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from wyrd import report
from wyrd.store import Store

_STEP_DIR = re.compile(r"^(\d+)-(.*)$")
_HARD = "hard_blocks."


@dataclass(frozen=True)
class StepDir:
    n: int
    name: str
    path: Path


@dataclass(frozen=True)
class RunInfo:
    label: str
    key: str
    status: str
    run_dir: Path
    row: dict[str, object]


def load_rows(root: Path) -> list[dict[str, object]] | None:
    """Rows of ``root/wyrd.db``, or None when there is no database file."""
    db = root / "wyrd.db"
    if not db.is_file():
        return None
    return Store.open_readonly(db).rows()


def _label(row: dict[str, object], many_recipes: bool) -> str:
    label = f"{row['design']} / {row['arch']}"
    if many_recipes:
        label += f" / {row.get('recipe') or ''}"
    params = str(row.get("params") or "{}")
    if params != "{}":
        label += f" {params}"
    return label


def run_infos(rows: list[dict[str, object]]) -> list[RunInfo]:
    """The latest run of each identity, sorted by label."""
    many = len({str(r.get("recipe") or "") for r in rows}) > 1
    infos = [
        RunInfo(_label(r, many), str(r["key"]), str(r["status"]), Path(str(r["run_dir"])), r)
        for r in report.latest_per_run(rows).values()
    ]
    return sorted(infos, key=lambda i: i.label)


def fmax_mhz(crit_path_ns: object) -> float | None:
    if isinstance(crit_path_ns, bool) or not isinstance(crit_path_ns, int | float):
        return None
    if not math.isfinite(crit_path_ns) or crit_path_ns <= 0:
        return None
    return 1000.0 / crit_path_ns


def _show(value: object) -> str:
    return "n/a" if value is None else report.number(value)


def _hard_rows(row: dict[str, object]) -> list[tuple[str, str]]:
    names = sorted(k for k in row if k.startswith(_HARD))
    if not names:
        return [("Hard blocks", "none")]
    return [(k[len(_HARD) :], _show(row[k])) for k in names]


def summary_rows(row: dict[str, object]) -> list[tuple[str, str]]:
    """Label and value pairs of a run's Summary page (spec section 7)."""
    fmax = fmax_mhz(row.get("crit_path_ns"))
    return [
        ("Status", str(row.get("status", ""))),
        ("LUTs", _show(row.get("luts"))),
        ("CLBs", _show(row.get("clbs"))),
        *_hard_rows(row),
        ("Fmax (MHz)", "n/a" if fmax is None else report.number(fmax)),
        ("Min channel width", _show(row.get("min_chan_width"))),
        ("Critical path (ns)", _show(row.get("crit_path_ns"))),
        ("Run directory", str(row.get("run_dir", ""))),
        ("Run key", str(row.get("key", ""))),
    ]


def step_dirs(run_dir: Path) -> list[StepDir]:
    """Step directories ``<n>-<name>`` of a run, in step order."""
    found: list[StepDir] = []
    try:
        children = list(run_dir.iterdir())
    except OSError:
        return []
    for child in children:
        m = _STEP_DIR.match(child.name)
        if m and child.is_dir():
            found.append(StepDir(int(m.group(1)), m.group(2), child))
    return sorted(found, key=lambda s: (s.n, s.name))


def log_files(step_dir: Path) -> list[Path]:
    try:
        return sorted(step_dir.rglob("*.log"))
    except OSError:
        return []
