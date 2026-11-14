"""Plain-text table of a mux cost report document."""

from __future__ import annotations


def _cell(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _where(row: dict[str, object]) -> str:
    return f"{row['file']}:{row['line']}" if row["file"] else "(no source)"


def _table(header: list[str], body: list[list[str]]) -> list[str]:
    widths = [
        max(len(h), *(len(r[i]) for r in body)) if body else len(h) for i, h in enumerate(header)
    ]
    lines = ["  ".join(h.ljust(w) for h, w in zip(header, widths, strict=True)).rstrip()]
    lines += ["  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip() for r in body]
    return lines


def _pct(row: dict[str, object]) -> str:
    return f"{float(str(row['share'])) * 100:.1f}%"


def _mux_table(rows: list[dict[str, object]], timing: bool) -> list[str]:
    header = [
        "where",
        "construct",
        "kind",
        "width",
        "arms",
        "const",
        "dup",
        "rel",
        "sel",
        "mux_bits",
        "share",
        "luts",
        "shared",
        "lut_lb",
    ]
    if timing:
        header += ["sel_crit", "data_crit", "late"]
    body = []
    for r in rows:
        line = [
            _where(r),
            str(r["construct"]),
            str(r["kind"]),
            *(
                _cell(r[k])
                for k in (
                    "width",
                    "arms",
                    "const_arms",
                    "dup_arms",
                    "related_arms",
                    "select_width",
                    "mux_bits",
                )
            ),
            _pct(r),
            *(_cell(r[k]) for k in ("luts", "luts_shared", "lut_lower_bound")),
        ]
        if timing:
            line += [_cell(r[k]) for k in ("sel_crit", "data_crit", "late")]
        body.append(line)
    return _table(header, body)


def _construct_table(rows: list[dict[str, object]], timing: bool) -> list[str]:
    header = [
        "where",
        "construct",
        "muxes",
        "arms",
        "mux_bits",
        "share",
        "luts",
        "shared",
        "lut_lb",
    ]
    if timing:
        header.append("late")
    body = []
    for r in rows:
        line = [
            _where(r),
            str(r["construct"]),
            *(_cell(r[k]) for k in ("muxes", "arms", "mux_bits")),
            _pct(r),
            *(_cell(r[k]) for k in ("luts", "luts_shared", "lut_lower_bound")),
        ]
        if timing:
            line.append(_cell(r["late"]))
        body.append(line)
    return _table(header, body)


def render(doc: dict[str, object]) -> str:
    totals = doc["totals"]
    design = doc["design"]
    assert isinstance(totals, dict) and isinstance(design, dict)
    cuts = totals["cuts"]
    timing = bool(doc["timing"])
    muxes, cons = doc["muxes"], doc["constructs"]
    assert isinstance(muxes, list) and isinstance(cons, list)
    head = [
        f"Mux cost of {design['top']} (K={design['lut_k']}): "
        f"{totals['logical_muxes']} logical muxes, "
        f"{totals['mux_cells']} mux cells, {totals['mux_bits']} mux bits (2:1 equivalents)",
        f"LUTs {totals['luts']}: exact cut {cuts['exact']}, approximate {cuts['approx']}, "
        f"drive a named net {cuts['named']}, no cut {cuts['none']}; "
        f"attributed to a word cell {totals['luts_attributed']}",
        f"Sorted by {doc['sort']}.",
        "",
        "Per HDL construct",
        *_construct_table(cons, timing),
        "",
        "Per logical mux",
        *_mux_table(muxes, timing),
    ]
    if not timing:
        head += ["", "No routed timing report given: no select lateness column (see --net-timing)."]
    return "\n".join(head)
