"""Tables and comparisons over the rows of ``wyrd.db`` (spec sections 3 and 4)."""

from __future__ import annotations

import csv
import io

_RUN_COLUMNS = frozenset(
    {"key", "design", "arch", "recipe", "params", "status", "started", "ended", "run_dir"}
)


def number(value: object) -> str:
    """Integers when integral, else up to 4 significant digits; empty for a missing value."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return "" if value is None else str(value)
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.4g}"


def latest_per_cell(rows: list[dict[str, object]]) -> dict[tuple[str, str], dict[str, object]]:
    """The most recently started run for each (design, arch)."""
    cells: dict[tuple[str, str], dict[str, object]] = {}
    for row in sorted(rows, key=lambda r: str(r.get("started") or "")):
        cells[(str(row["design"]), str(row["arch"]))] = row
    return cells


def metric_names(rows: list[dict[str, object]]) -> list[str]:
    names = {k for row in rows for k in row if k not in _RUN_COLUMNS}
    return sorted(names)


def table(
    rows: list[dict[str, object]], metrics: list[str] | None = None
) -> list[list[str]]:
    """Header row then one row per design x arch: design, arch, status, then the metrics."""
    cells = latest_per_cell(rows)
    names = metrics if metrics is not None else metric_names(list(cells.values()))
    out = [["design", "arch", "status", *names]]
    for design, arch in sorted(cells):
        row = cells[(design, arch)]
        out.append([design, arch, str(row["status"]), *(number(row.get(n)) for n in names)])
    return out


def compare(
    a: list[dict[str, object]], b: list[dict[str, object]], metrics: list[str] | None = None
) -> list[list[str]]:
    """Header row then one row per matched design x arch x metric: A, B and B/A."""
    ca, cb = latest_per_cell(a), latest_per_cell(b)
    names = metrics if metrics is not None else metric_names(list(ca.values()) + list(cb.values()))
    out = [["design", "arch", "metric", "A", "B", "B/A"]]
    for design, arch in sorted(set(ca) & set(cb)):
        for name in names:
            va, vb = ca[(design, arch)].get(name), cb[(design, arch)].get(name)
            out.append([design, arch, name, number(va), number(vb), _ratio(va, vb)])
    return out


def _ratio(a: object, b: object) -> str:
    if isinstance(a, bool) or isinstance(b, bool):
        return ""
    if not isinstance(a, int | float) or not isinstance(b, int | float) or a == 0:
        return ""
    return number(b / a)


def render_md(rows: list[list[str]]) -> str:
    return "\n".join(
        ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
        + ["| " + " | ".join(r) + " |" for r in rows[1:]]
    )


def render_csv(rows: list[list[str]]) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue().rstrip("\n")


def render(rows: list[list[str]], fmt: str) -> str:
    return render_csv(rows) if fmt == "csv" else render_md(rows)
