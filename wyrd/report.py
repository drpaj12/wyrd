"""Tables and comparisons over the rows of ``wyrd.db`` (spec sections 3 and 4)."""

from __future__ import annotations

import csv
import io
import json
import math
from decimal import Decimal

_RUN_COLUMNS = frozenset(
    {"key", "design", "arch", "recipe", "params", "status", "started", "ended", "run_dir"}
)


def number(value: object) -> str:
    """Integers as integers; other numbers to 4 significant digits in plain decimal."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return "" if value is None else str(value)
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        return str(value)
    if value.is_integer() or abs(value) >= 1000:
        return str(round(value))
    return format(Decimal(f"{value:.4g}"), "f")


Identity = tuple[str, str, str, str]


def _identity(row: dict[str, object]) -> Identity:
    return (
        str(row["design"]),
        str(row["arch"]),
        str(row.get("recipe") or ""),
        str(row.get("params") or "{}"),
    )


def _param_map(identity: Identity) -> dict[str, object]:
    try:
        loaded = json.loads(identity[3])
    except ValueError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _param_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool | int | float):
        return number(value) if not isinstance(value, bool) else str(value).lower()
    return json.dumps(value)


def latest_per_run(rows: list[dict[str, object]]) -> dict[Identity, dict[str, object]]:
    """The most recently started run for each (design, arch, recipe, params)."""
    cells: dict[Identity, dict[str, object]] = {}
    for row in sorted(rows, key=lambda r: str(r.get("started") or "")):
        cells[_identity(row)] = row
    return cells


def metric_names(rows: list[dict[str, object]]) -> list[str]:
    names = {k for row in rows for k in row if k not in _RUN_COLUMNS}
    return sorted(names)


def _layout(
    identities: list[Identity], rows: list[dict[str, object]]
) -> tuple[bool, list[str]]:
    """Whether to show a recipe column, and the sorted sweep parameter names."""
    show_recipe = len({i[2] for i in identities} | {str(r.get("recipe") or "") for r in rows}) > 1
    names = sorted({n for i in identities for n in _param_map(i)})
    return show_recipe, names


def _id_cells(identity: Identity, show_recipe: bool, params: list[str]) -> list[str]:
    values = _param_map(identity)
    return [
        identity[0],
        identity[1],
        *([identity[2]] if show_recipe else []),
        *(_param_text(values.get(n)) for n in params),
    ]


def _id_header(show_recipe: bool, params: list[str]) -> list[str]:
    return ["design", "arch", *(["recipe"] if show_recipe else []), *params]


def table(
    rows: list[dict[str, object]],
    metrics: list[str] | None = None,
) -> list[list[str]]:
    """Header row then one row per (design, arch, recipe, params), then status and metrics.

    The recipe column appears only when the rows hold more than one recipe.
    """
    cells = latest_per_run(rows)
    show_recipe, params = _layout(list(cells), rows)
    names = metrics if metrics is not None else metric_names(list(cells.values()))
    out = [[*_id_header(show_recipe, params), "status", *names]]
    for ident in sorted(cells):
        row = cells[ident]
        out.append(
            [
                *_id_cells(ident, show_recipe, params),
                str(row["status"]),
                *(number(row.get(n)) for n in names),
            ]
        )
    return out


def compare(
    a: list[dict[str, object]], b: list[dict[str, object]], metrics: list[str] | None = None
) -> list[list[str]]:
    """Header row then one row per matched run and metric: A, B and B/A.

    Runs match on (design, arch, recipe, params). A metric is listed only when at least one
    side of the matched pair has it.
    """
    ca, cb = latest_per_run(a), latest_per_run(b)
    matched = sorted(set(ca) & set(cb))
    show_recipe, params = _layout(matched, a + b)
    names = metrics if metrics is not None else metric_names(list(ca.values()) + list(cb.values()))
    out = [[*_id_header(show_recipe, params), "metric", "A", "B", "B/A"]]
    for ident in matched:
        for name in names:
            va, vb = ca[ident].get(name), cb[ident].get(name)
            if va is None and vb is None:
                continue
            cells = _id_cells(ident, show_recipe, params)
            out.append([*cells, name, number(va), number(vb), _ratio(va, vb)])
    return out


def unmatched(a: list[dict[str, object]], b: list[dict[str, object]]) -> list[str]:
    """Lines "only in A: ..." / "only in B: ..." for runs present in just one project."""
    ca, cb = latest_per_run(a), latest_per_run(b)
    lines: list[str] = []
    for side, mine, other in (("A", ca, cb), ("B", cb, ca)):
        for ident in sorted(set(mine) - set(other)):
            design, arch, recipe, params = ident
            lines.append(f"only in {side}: {design} {arch} {recipe} {params}")
    return lines


def _ratio(a: object, b: object) -> str:
    if isinstance(a, bool) or isinstance(b, bool):
        return ""
    if not isinstance(a, int | float) or not isinstance(b, int | float) or a == 0:
        return ""
    return number(b / a)


def render_md(rows: list[list[str]]) -> str:
    def row(cells: list[str]) -> str:
        return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"

    return "\n".join(
        [row(rows[0]), "|" + "---|" * len(rows[0])] + [row(r) for r in rows[1:]]
    )


def render_csv(rows: list[list[str]]) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue().rstrip("\n")


def render(rows: list[list[str]], fmt: str) -> str:
    return render_csv(rows) if fmt == "csv" else render_md(rows)
