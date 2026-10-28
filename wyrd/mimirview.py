"""Headless model of the Mimir browser: read-only queries on a Mimir v4 SQLite store.

Spec: docs/specs/2026-10-28-mimir-browser.md. Standard library only; the `mimir` package is never
needed for data. The store is opened with `mode=ro`, a fresh connection per query, so the model is
safe on a worker thread and while another process writes the store.
"""

from __future__ import annotations

import csv
import importlib
import io
import math
import shutil
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_VERSION = "4"
DEFAULT_LIMIT = 500
SCATTER_LIMIT = 20000
PARAM_CONFS = ("given", "default", "default-unrecorded", "unknown")
TABLES = (
    "records", "design", "design_source", "design_meta", "design_lineage", "flow_config",
    "flow_param", "run", "run_artifact", "structure", "structure_mapping", "structure_member",
    "partition", "analysis_result",
)  # fmt: skip
Row = tuple[object, ...]


class MimirError(Exception):
    """A store cannot be read: not a store, another schema version, or a query failed."""


@dataclass(frozen=True)
class Table:
    """A result table: column names, rows, and whether the limit cut more rows off."""

    title: str
    columns: tuple[str, ...]
    rows: list[Row]
    more: bool = False


@dataclass(frozen=True)
class Summary:
    version: str
    size_bytes: int
    counts: dict[str, int]
    sources: Table
    levels: list[str]
    n_metrics: int


@dataclass(frozen=True)
class DesignInfo:
    name: str
    sources: list[str]
    metrics: Table
    runs: Table
    meta: Table
    lineage: Table
    structures: Table


@dataclass(frozen=True)
class RunInfo:
    run_id: str
    header: dict[str, object]
    config: dict[str, object]
    params: Table
    artifacts: Table


@dataclass(frozen=True)
class CompareRow:
    label: str
    n: int
    ratio: float | None  # geometric mean of value / base value; None when no design is shared


@dataclass(frozen=True)
class Compare:
    metric: str
    base: str
    rows: list[CompareRow] = field(default_factory=list)

    def as_table(self) -> Table:
        cols = ("config", "n designs", f"geomean {self.metric} / {self.base}")
        rows: list[Row] = [
            (r.label, r.n, "" if r.ratio is None else f"{r.ratio:.4f}") for r in self.rows
        ]
        return Table("compare", cols, rows)


@dataclass(frozen=True)
class Point:
    label: str
    x: float
    y: float


def prefix_range(prefix: str) -> tuple[str, str]:
    """[low, high) bounds of the strings that start with `prefix` (uses the index, unlike LIKE)."""
    return prefix, prefix + "\U0010ffff"


def config_label(source: str, arm: str) -> str:
    return f"{source}/{arm}" if arm else source


def geomean_ratio(values: dict[str, float], base: dict[str, float]) -> tuple[int, float | None]:
    """(n, geometric mean of values/base) over the keys both have with both values > 0."""
    logs = [math.log(v / base[k]) for k, v in values.items() if k in base and v > 0 and base[k] > 0]
    if not logs:
        return 0, None
    return len(logs), math.exp(sum(logs) / len(logs))


def mimir_on_path() -> str | None:
    """Path of the `mimir` command, or None."""
    return shutil.which("mimir")


def fetch_argv(run_id: str, db: Path, out: Path) -> list[str]:
    """Argument list for `mimir fetch --run RUN_ID --db DB --out DIR` (run it without a shell)."""
    return ["mimir", "fetch", "--run", run_id, "--db", str(db), "--out", str(out)]


def metric_registry() -> dict[str, str]:
    """Metric key to description, from `mimir.registry` when importable; else empty."""
    try:
        mod = importlib.import_module("mimir.registry")
        reg = mod.load_registry()
        return {str(k): str(m.description) for k, m in reg.items()}
    except Exception:  # the package is optional and any failure just means no descriptions
        return {}


def _mean(pairs: Sequence[tuple[str, float]]) -> dict[str, float]:
    sums: dict[str, list[float]] = {}
    for key, v in pairs:
        sums.setdefault(key, []).append(v)
    return {k: sum(v) / len(v) for k, v in sums.items()}


class MimirView:
    """Read-only access to one Mimir store. Opening checks the file and its schema version."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.version = self._check()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        try:
            yield con
        finally:
            con.close()

    def _query(self, sql: str, args: Sequence[object] = ()) -> list[Row]:
        try:
            with self._conn() as con:
                return [tuple(r) for r in con.execute(sql, args).fetchall()]
        except sqlite3.Error as e:
            raise MimirError(f"{self.path}: {e}") from e

    def _check(self) -> str:
        if not self.path.is_file():
            raise MimirError(f"{self.path}: no such file")
        try:
            rows = self._query("SELECT value FROM meta WHERE key = 'schema_version'")
        except MimirError as e:
            raise MimirError(f"{self.path}: not a Mimir store ({e})") from e
        if not rows:
            raise MimirError(f"{self.path}: not a Mimir store (no schema_version in meta)")
        version = str(rows[0][0])
        if version != SUPPORTED_VERSION:
            raise MimirError(
                f"{self.path}: schema version {version}; "
                f"this Wyrd reads version {SUPPORTED_VERSION}"
            )
        return version

    def _table(
        self,
        title: str,
        columns: tuple[str, ...],
        sql: str,
        args: Sequence[object],
        limit: int,
        offset: int = 0,
    ) -> Table:
        rows = self._query(f"{sql} LIMIT ? OFFSET ?", (*args, limit + 1, offset))
        return Table(title, columns, rows[:limit], len(rows) > limit)

    def _count(self, sql: str) -> int:
        return _n(self._query(sql)[0][0])

    def _existing_tables(self) -> set[str]:
        return {str(r[0]) for r in self._query("SELECT name FROM sqlite_master WHERE type='table'")}

    # ---- summary ----

    def summary(self) -> Summary:
        have = self._existing_tables()
        counts = {t: self._count(f"SELECT COUNT(*) FROM {t}") for t in TABLES if t in have}
        rec = self._query("SELECT source, COUNT(*) FROM records GROUP BY source")
        runs = {
            str(a): _n(b)
            for a, b in self._query("SELECT source, COUNT(*) FROM run GROUP BY source")
        }
        src_rows: list[Row] = [
            (s, n, runs.get(str(s), 0)) for s, n in sorted(rec, key=lambda r: str(r[0]))
        ]
        for s in sorted(set(runs) - {str(r[0]) for r in rec}):
            src_rows.append((s, 0, runs[s]))
        levels = [
            str(r[0]) for r in self._query("SELECT DISTINCT level FROM records ORDER BY level")
        ]
        n_metrics = self._count("SELECT COUNT(*) FROM (SELECT DISTINCT metric FROM records)")
        return Summary(
            self.version,
            self.path.stat().st_size,
            counts,
            Table("sources", ("source", "records", "runs"), src_rows),
            levels,
            n_metrics,
        )

    def sources(self) -> list[str]:
        """Sources that have designs listed (design_source or run)."""
        rows = self._query(
            "SELECT source FROM design_source UNION SELECT source FROM run ORDER BY 1"
        )
        return [str(r[0]) for r in rows]

    # ---- design list ----

    def designs(
        self, source: str | None = None, text: str = "", limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> Table:
        where, args = ["1=1"], []
        if source:
            where.append("a.source = ?")
            args.append(source)
        if text:
            where.append("(LOWER(a.name) LIKE ? OR LOWER(COALESCE(a.slug, '')) LIKE ?)")
            args += [f"%{text.lower()}%"] * 2
        sql = (
            "SELECT a.source, a.name, COALESCE(a.slug, ''), COALESCE(d.suite, ''), "
            "(SELECT COUNT(*) FROM run r WHERE r.source = a.source AND r.design = a.name) "
            "FROM (SELECT source, name, slug FROM design_source UNION "
            "SELECT source, design, slug FROM run) a LEFT JOIN design d ON d.slug = a.slug "
            f"WHERE {' AND '.join(where)} ORDER BY a.source, a.name"
        )
        return self._table(
            "designs", ("source", "name", "slug", "suite", "runs"), sql, args, limit, offset
        )

    # ---- one design ----

    def design(
        self, name: str, source: str | None = None, limit: int = DEFAULT_LIMIT
    ) -> DesignInfo:
        pairs = self._design_pairs(name, source)
        if not pairs:
            raise MimirError(f"no design {name!r}" + (f" in source {source!r}" if source else ""))
        srcs = [s for s, _ in pairs]
        slugs = sorted({slug for _, slug in pairs if slug})
        return DesignInfo(
            name,
            srcs,
            self._metrics(name, srcs, limit),
            self._design_runs(name, srcs, limit),
            self._meta(slugs, limit),
            self._lineage(slugs, limit),
            self._structures(slugs),
        )

    def _design_pairs(self, name: str, source: str | None) -> list[tuple[str, str]]:
        args: list[object] = [name]
        extra = ""
        if source:
            extra = " AND source = ?"
            args.append(source)
        rows = self._query(
            "SELECT source, COALESCE(slug, '') FROM design_source WHERE name = ?"
            + extra
            + " UNION SELECT source, slug FROM run WHERE design = ?"
            + extra
            + " ORDER BY 1",
            [*args, *args],
        )
        return [(str(s), str(g)) for s, g in rows]

    def _in(self, values: Sequence[str]) -> str:
        return ", ".join("?" for _ in values) or "NULL"

    def _metrics(self, name: str, srcs: list[str], limit: int) -> Table:
        sql = (
            "SELECT source, level, metric, value, unit, measurer, origin, arch, arm, seed, bin, "
            f"tool_commit FROM records WHERE design = ? AND source IN ({self._in(srcs)}) "
            "ORDER BY level, metric, source, arm, arch, seed"
        )
        cols = ("source", "level", "metric", "value", "unit", "measurer", "origin", "arch", "arm",
                "seed", "bin", "tool_commit")  # fmt: skip
        return self._table("metrics", cols, sql, [name, *srcs], limit)

    def _design_runs(self, name: str, srcs: list[str], limit: int) -> Table:
        sql = (
            "SELECT run_id, source, arch, arm, seed, family, tool_commits, time_s, peak_rss_mib, "
            f"COALESCE(host, '') FROM run WHERE design = ? AND source IN ({self._in(srcs)}) "
            "ORDER BY source, arm, arch, seed"
        )
        cols = ("run_id", "source", "arch", "arm", "seed", "family", "tool_commits", "time_s",
                "peak_rss_mib", "host")  # fmt: skip
        return self._table("runs", cols, sql, [name, *srcs], limit)

    def _meta(self, slugs: list[str], limit: int) -> Table:
        sql = (
            f"SELECT field, value, source, conf FROM design_meta WHERE slug IN ({self._in(slugs)}) "
            "ORDER BY slug, field"
        )
        return self._table("design_meta", ("field", "value", "source", "conf"), sql, slugs, limit)

    def _lineage(self, slugs: list[str], limit: int) -> Table:
        sql = (
            "SELECT step_no, tool, script, parent_hash, source, conf FROM design_lineage "
            f"WHERE slug IN ({self._in(slugs)}) ORDER BY slug, step_no"
        )
        cols = ("step", "tool", "script", "parent_hash", "source", "conf")
        return self._table("design_lineage", cols, sql, slugs, limit)

    def _structures(self, slugs: list[str]) -> Table:
        sql = (
            f"SELECT kind, COUNT(*) FROM structure WHERE design IN ({self._in(slugs)}) "
            "GROUP BY kind ORDER BY kind"
        )
        return self._table("structures", ("kind", "count"), sql, slugs, DEFAULT_LIMIT)

    # ---- one run ----

    def run(self, run_id: str) -> RunInfo:
        cols = (
            *("run_id", "slug", "config_hash", "source", "design", "arch", "seed", "arm"),
            *("family", "tool_commits", "time_s", "peak_rss_mib", "host", "origin", "tool_commit"),
        )
        rows = self._query(f"SELECT {', '.join(cols)} FROM run WHERE run_id = ?", [run_id])
        if not rows:
            raise MimirError(f"no run {run_id!r}")
        header = dict(zip(cols, rows[0], strict=True))
        cfg_hash = str(header["config_hash"])
        ccols = ("config_hash", "name", "status", "text_kind", "origin")
        crow = self._query(
            f"SELECT {', '.join(ccols)} FROM flow_config WHERE config_hash = ?", [cfg_hash]
        )
        config = dict(zip(ccols, crow[0], strict=True)) if crow else {}
        params = self._table(
            "flow_param",
            ("step", "key", "value", "conf", "source"),
            "SELECT step, key, value, conf, source FROM flow_param WHERE config_hash = ? "
            "ORDER BY step, key",
            [cfg_hash],
            10000,
        )
        art = self._table(
            "artifacts",
            ("kind", "blob_sha256"),
            "SELECT kind, blob_sha256 FROM run_artifact WHERE run_id = ? ORDER BY kind",
            [run_id],
            10000,
        )
        return RunInfo(run_id, header, config, params, art)

    # ---- compare and scatter ----

    def config_labels(self, prefix: str) -> list[str]:
        lo, hi = prefix_range(prefix)
        rows = self._query(
            "SELECT DISTINCT source, arm FROM records WHERE source >= ? AND source < ?"
            " ORDER BY source, arm",
            [lo, hi],
        )
        return [config_label(str(s), str(a)) for s, a in rows]

    def metric_names(self, prefix: str = "") -> list[str]:
        lo, hi = prefix_range(prefix)
        rows = self._query(
            "SELECT DISTINCT metric FROM records WHERE source >= ? AND source < ? ORDER BY metric",
            [lo, hi],
        )
        return [str(r[0]) for r in rows]

    def compare(self, prefix: str, base: str, metric: str, level: str | None = None) -> Compare:
        lo, hi = prefix_range(prefix)
        sql = (
            "SELECT source, arm, design, value FROM records WHERE source >= ? AND source < ? "
            "AND metric = ?"
        )
        args: list[object] = [lo, hi, metric]
        if level:
            sql += " AND level = ?"
            args.append(level)
        per: dict[str, list[tuple[str, float]]] = {}
        for s, a, d, v in self._query(sql, args):
            per.setdefault(config_label(str(s), str(a)), []).append((f"{s}\x00{d}", _f(v)))
        if base not in per:
            raise MimirError(
                f"base config {base!r} has no {metric!r} values under prefix {prefix!r}"
            )
        means = {label: _mean(pairs) for label, pairs in per.items()}
        out = Compare(metric, base)
        for label in sorted(means):
            n, r = geomean_ratio(_strip(means[label]), _strip(means[base]))
            out.rows.append(CompareRow(label, n, r))
        return out

    def scatter(self, x_metric: str, y_metric: str, source: str | None = None) -> list[Point]:
        xs = self._per_design(x_metric, source)
        ys = self._per_design(y_metric, source)
        pts = [Point(k, xs[k], ys[k]) for k in sorted(xs) if k in ys]
        return pts[:SCATTER_LIMIT]

    def _per_design(self, metric: str, source: str | None) -> dict[str, float]:
        sql = "SELECT source, design, value FROM records WHERE metric = ?"
        args: list[object] = [metric]
        if source:
            sql += " AND source = ?"
            args.append(source)
        pairs = [(f"{s}/{d}", _f(v)) for s, d, v in self._query(sql, args)]
        return _mean(pairs)


def _n(x: object) -> int:
    return x if isinstance(x, int) else 0


def _f(x: object) -> float:
    return float(x) if isinstance(x, (int, float)) else math.nan


def _strip(d: dict[str, float]) -> dict[str, float]:
    """Keys "source\\x00design" to the design name, so configs of different sources match."""
    return {k.split("\x00", 1)[1]: v for k, v in d.items()}


def cell_text(x: object) -> str:
    if isinstance(x, float):
        return f"{x:.6g}"
    return "" if x is None else str(x)


def render_csv(t: Table) -> str:
    """The table as CSV text (header row first)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(t.columns)
    w.writerows([[cell_text(c) for c in r] for r in t.rows])
    return buf.getvalue()


def render_tsv(t: Table) -> str:
    """The table as tab-separated text, for the clipboard."""
    lines = ["\t".join(t.columns)]
    lines += ["\t".join(cell_text(c) for c in r) for r in t.rows]
    return "\n".join(lines) + "\n"


def render_text(t: Table) -> str:
    """The table as aligned plain text; a final line says when the limit cut rows off."""
    cells = [[cell_text(c) for c in r] for r in t.rows]
    widths = [len(c) for c in t.columns]
    for r in cells:
        widths = [max(w, len(c)) for w, c in zip(widths, r, strict=True)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    lines = [fmt.format(*t.columns).rstrip(), "  ".join("-" * w for w in widths)]
    lines += [fmt.format(*r).rstrip() for r in cells]
    if t.more:
        lines.append(f"... more rows (limit {len(t.rows)}); use --limit")
    return "\n".join(lines)
