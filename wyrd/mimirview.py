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

SUPPORTED_VERSIONS = ("4", "5")  # 5 is additive on 4: timing_run, timing_path_hist, timing_object
DEFAULT_LIMIT = 500
SCATTER_LIMIT = 20000
NO_LIMIT = 2**62
RUN_METRICS = {
    "run.time_s": "wall time of the run in seconds (run table)",
    "run.peak_rss_mib": "peak resident memory of the run in MiB (run table)",
}
RUNS_ONLY_NOTE = "this store has runs but no metric records"
PARAM_CONFS = ("given", "default", "default-unrecorded", "unknown")
TABLES = (
    "records", "design", "design_source", "design_meta", "design_lineage", "flow_config",
    "flow_param", "run", "run_artifact", "structure", "structure_mapping", "structure_member",
    "partition", "analysis_result", "timing_run", "timing_path_hist", "timing_object",
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
    note: str = ""


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
class Point:
    label: str
    x: float
    y: float
    source: str = ""  # set on per-design points (Plot tab); compared exactly, never parsed
    design: str = ""


@dataclass(frozen=True)
class CompareRow:
    label: str
    level: str  # "" for run-table metrics
    n: int  # designs in the ratio
    ratio: float | None  # geometric mean of value / base value; None when no design is shared
    dropped: int = 0  # non-numeric rows plus shared designs with a value <= 0
    duplicates: int = 0  # records rows merged because they repeat (arch, seed, design, level)
    commits: int = 0  # distinct tool_commit among the rows used
    configs: int = 0  # distinct run.config_hash for this (source, arm); 0 when no run rows

    @property
    def mixed(self) -> bool:
        return self.commits > 1 or self.configs > 1


COMPARE_COLUMNS = (
    "config", "level", "n designs", "geomean {metric} / {base}", "dropped (<=0 or non-numeric)",
    "duplicate rows merged", "tool commits", "configs", "mixed",
)  # fmt: skip


@dataclass(frozen=True)
class Compare:
    metric: str
    base: str
    rows: list[CompareRow] = field(default_factory=list)

    @property
    def multi_level(self) -> bool:
        return len({r.level for r in self.rows}) > 1

    def as_table(self) -> Table:
        cols = tuple(c.format(metric=self.metric, base=self.base) for c in COMPARE_COLUMNS)
        rows: list[Row] = [
            (
                r.label, r.level, r.n, "" if r.ratio is None else f"{r.ratio:.4f}", r.dropped,
                r.duplicates, r.commits, r.configs, "MIXED" if r.mixed else "",
            )
            for r in self.rows
        ]  # fmt: skip
        return Table("compare", cols, rows)


@dataclass(frozen=True)
class Scatter:
    points: list[Point]
    total: int  # points before the cap

    @property
    def capped(self) -> bool:
        return self.total > len(self.points)

    @property
    def note(self) -> str:
        n = len(self.points)
        return f"{n} designs" + (f" (capped at {n} of {self.total})" if self.capped else "")


def prefix_range(prefix: str) -> tuple[str, str]:
    """[low, high) bounds of the strings that start with `prefix` (uses the index, unlike LIKE)."""
    return prefix, prefix + "\U0010ffff"


def like_escape(text: str) -> str:
    """`text` with the LIKE wildcards % and _ (and the escape character) taken literally."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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


def metric_descriptions() -> dict[str, str]:
    """Tooltip text per metric key: the Mimir registry when importable, plus the run.* metrics."""
    return {**metric_registry(), **RUN_METRICS}


STRUCT_COLUMNS = (
    "structure_id", "kind", "level", "n_luts", "n_clbs", "bbox", "spread", "crit_share",
    "joined_with", "lost_at_pass",
)  # fmt: skip
HIST_BINS = 20
TIMING_OBJECT_COLUMNS = (
    "kind", "object", "crit_max", "n_paths", "n >= 0.90", "n >= 0.95", "n >= 0.99",
    "delay share 0.90", "via", "bits (MSB first, crit)",
)  # fmt: skip
STRIP_MAX = 12
BIT_CHUNK = 400
TIMING_RUN_COLUMNS = (
    "cpd_ns", "worst_slack_ns", "paths_requested", "paths_in_report", "paths_used", "max_req_ns",
    "dmax_source", "req_spread_ns", "pairs", "pairs_skipped", "last_crit", "trunc_090",
    "trunc_095", "trunc_099", "n_endpoints_090", "n_endpoints_095", "n_endpoints_099",
    "source_kind", "analysis_n",
)  # fmt: skip


@dataclass(frozen=True)
class TimingRunInfo:
    run_id: str
    label: str
    summary: dict[str, object]
    hist: list[int]  # HIST_BINS counts
    missing: tuple[str, ...] = ()  # optional timing_run columns this store lacks


def _bbox(row: Row) -> str:
    x0, y0, x1, y1 = row
    return "" if x0 is None else f"({x0},{y0})-({x1},{y1})"


def bit_strip(rows: Sequence[tuple[int, float]], limit: int = STRIP_MAX) -> str:
    """``bit:crit`` pairs, MSB first, the hottest ``limit`` bits when there are more."""
    top = sorted(rows, key=lambda r: (-r[1], -r[0]))[:limit]
    return " ".join(f"{b}:{c:.3f}" for b, c in sorted(top, reverse=True))


class _ExploreMixin:
    """Queries of the Structures and Timing tabs (spec 2026-10-28-heat-explore.md section 4)."""

    version: str

    def _query(self, sql: str, args: Sequence[object] = ()) -> list[Row]:
        raise NotImplementedError

    def _existing_tables(self) -> set[str]:
        raise NotImplementedError

    def has_timing(self) -> bool:
        have = self._existing_tables()
        return {"timing_run", "timing_path_hist", "timing_object"} <= have

    def structure_designs(self) -> list[str]:
        rows = self._query("SELECT DISTINCT design FROM structure_mapping ORDER BY design")
        return [str(r[0]) for r in rows]

    def structure_design_sources(self) -> dict[str, set[str]]:
        """For each structure_mapping design key (suite/design), the sources of its runs."""
        rows = self._query(
            "SELECT DISTINCT m.design, r.source FROM structure_mapping m "
            "JOIN run r ON r.run_id = m.run_id"
        )
        out: dict[str, set[str]] = {}
        for d, s in rows:
            out.setdefault(str(d), set()).add(str(s))
        return out

    def structure_runs(self, design: str) -> list[str]:
        rows = self._query(
            "SELECT DISTINCT run_id FROM structure_mapping WHERE design = ? ORDER BY run_id",
            [design],
        )
        return [str(r[0]) for r in rows]

    def structure_filters(self, design: str) -> tuple[list[str], list[str]]:
        """(levels, kinds) present for the design."""
        lv = self._query(
            "SELECT DISTINCT level FROM structure_mapping WHERE design = ? ORDER BY level", [design]
        )
        kd = self._query(
            "SELECT DISTINCT s.kind FROM structure s WHERE s.design = ? ORDER BY s.kind", [design]
        )
        return [str(r[0]) for r in lv], [str(r[0]) for r in kd]

    def _struct_where(
        self, design: str, run: str, level: str, kind: str
    ) -> tuple[str, list[object]]:
        where = ["m.design = ?"]
        args: list[object] = [design]
        for col, val in (("m.run_id", run), ("m.level", level), ("s.kind", kind)):
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        return " AND ".join(where), args

    def structure_rows(
        self, design: str, run: str = "", level: str = "", kind: str = "",
        limit: int = DEFAULT_LIMIT,
    ) -> Table:  # fmt: skip
        """The structure_mapping rows of a design (optionally one run, level, kind)."""
        where, args = self._struct_where(design, run, level, kind)
        sql = (
            "SELECT m.structure_id, COALESCE(s.kind, ''), m.level, m.n_luts, m.n_clbs, "
            "m.bbox_x0, m.bbox_y0, m.bbox_x1, m.bbox_y1, m.spread, m.crit_share, "
            "m.joined_with, m.lost_at_pass FROM structure_mapping m LEFT JOIN structure s "
            "ON s.design = m.design AND s.structure_id = m.structure_id "
            f"WHERE {where} ORDER BY m.level, m.structure_id LIMIT ?"
        )
        limit = limit if limit > 0 else NO_LIMIT
        rows = self._query(sql, [*args, limit + 1])
        out: list[Row] = [(*r[:5], _bbox(r[5:9]), *r[9:]) for r in rows[:limit]]
        return Table("structure_mapping", STRUCT_COLUMNS, out, len(rows) > limit)

    def structure_scatter(
        self, design: str, run: str = "", level: str = "", kind: str = ""
    ) -> Scatter:
        """Placement spread (x) against critical share (y), rows that have both."""
        where, args = self._struct_where(design, run, level, kind)
        sql = (
            "SELECT m.structure_id, m.run_id, m.spread, m.crit_share FROM structure_mapping m "
            "LEFT JOIN structure s ON s.design = m.design AND s.structure_id = m.structure_id "
            f"WHERE {where} AND m.spread IS NOT NULL AND m.crit_share IS NOT NULL LIMIT ?"
        )
        rows = self._query(sql, [*args, SCATTER_LIMIT + 1])
        pts = [Point(f"{r[0]} ({str(r[1])[:6]})", _f(r[2]), _f(r[3])) for r in rows[:SCATTER_LIMIT]]
        return Scatter(pts, len(rows))

    def timing_runs(self) -> list[tuple[str, str]]:
        """(run_id, label) of every run with a timing_run row."""
        if not self.has_timing():
            return []
        rows = self._query(
            "SELECT t.run_id, r.design, r.arm, r.seed, r.source FROM timing_run t "
            "LEFT JOIN run r ON r.run_id = t.run_id ORDER BY r.design, r.arm, r.seed, t.run_id"
        )
        return [(str(r[0]), f"{r[1]} / {r[4]} / {r[2]} / seed {r[3]}  [{str(r[0])[:8]}]")
                for r in rows]  # fmt: skip

    def timing_design_sources(self) -> set[tuple[str, str]]:
        """(source, design) of every run that has a timing_run row."""
        if not self.has_timing():
            return set()
        rows = self._query(
            "SELECT DISTINCT r.source, r.design FROM timing_run t JOIN run r ON r.run_id = t.run_id"
        )
        return {(str(a), str(b)) for a, b in rows}

    def timing_run(self, run_id: str) -> TimingRunInfo:
        have = {str(r[1]) for r in self._query("PRAGMA table_info(timing_run)")}
        cols = tuple(c for c in TIMING_RUN_COLUMNS if c in have)
        missing = tuple(c for c in TIMING_RUN_COLUMNS if c not in have)
        rows = self._query(f"SELECT {', '.join(cols)} FROM timing_run WHERE run_id = ?", [run_id])
        if not rows:
            raise MimirError(f"no timing for run {run_id!r}")
        info = dict(zip(cols, rows[0], strict=True))
        near = self._query(
            "SELECT metric, value FROM records r JOIN record_run u ON u.record_rowid = r.rowid "
            "WHERE u.run_id = ? AND r.metric LIKE 'timing.nc_paths_%' ORDER BY metric",
            [run_id],
        )
        info.update({str(m): v for m, v in near})
        hist = [0] * HIST_BINS
        for b, n in self._query("SELECT bin, n FROM timing_path_hist WHERE run_id = ?", [run_id]):
            if 0 <= _n(b) < HIST_BINS:
                hist[_n(b)] = _n(n)
        label = dict(self.timing_runs()).get(run_id, run_id)
        return TimingRunInfo(run_id, label, info, hist, missing)

    def _word_bits(self, run_id: str, keys: Sequence[str]) -> dict[str, list[tuple[int, float]]]:
        """Bit rows of the given word objects only (in chunks, under SQLite's variable limit)."""
        bits: dict[str, list[tuple[int, float]]] = {}
        for i in range(0, len(keys), BIT_CHUNK):
            chunk = list(keys[i : i + BIT_CHUNK])
            marks = ", ".join("?" * len(chunk))
            for key, bit, crit in self._query(
                "SELECT object_key, bit, crit_max FROM timing_object WHERE run_id = ? "
                f"AND kind = 'word' AND bit >= 0 AND object_key IN ({marks})", [run_id, *chunk]
            ):  # fmt: skip
                bits.setdefault(str(key), []).append((_n(bit), _f(crit)))
        return bits

    def timing_top_objects(self, run_id: str, kind: str = "word", limit: int = 100) -> Table:
        """Objects of one kind by crit_max; a word row carries its bit strip."""
        sql = (
            "SELECT kind, object_key, crit_max, n_paths, n_paths_090, n_paths_095, n_paths_099, "
            "delay_share_090, via FROM timing_object WHERE run_id = ? AND kind = ? AND bit = -1 "
            "ORDER BY crit_max DESC, n_paths DESC, object_key LIMIT ?"
        )
        limit = limit if limit > 0 else NO_LIMIT
        rows = self._query(sql, [run_id, kind, limit + 1])
        shown = rows[:limit]
        bits = self._word_bits(run_id, [str(r[1]) for r in shown]) if kind == "word" else {}
        out: list[Row] = [(*r, bit_strip(bits.get(str(r[1]), ()))) for r in shown]
        return Table("timing_object", TIMING_OBJECT_COLUMNS, out, len(rows) > limit)

    def design_origin(self, run_id: str) -> str:
        """The recorded origin (source path, may contain ``$VTR_ROOT``) of the run's design."""
        rows = self._query(
            "SELECT d.origin FROM run r JOIN design d ON d.slug = r.slug WHERE r.run_id = ?",
            [run_id],
        )
        return str(rows[0][0]) if rows else ""

    def timing_object_rows(self, run_id: str) -> list[Row]:
        """(kind, key, bit, via, crit_max) of the span and word rows, for the hot/cold view."""
        return self._query(
            "SELECT kind, object_key, bit, via, crit_max FROM timing_object "
            "WHERE run_id = ? AND kind IN ('span', 'word')", [run_id]
        )  # fmt: skip

    def run_scatter(self, x_metric: str, y_metric: str) -> Scatter:
        """One point per run that has both metrics (through the record_run view)."""

        def per_run(metric: str) -> dict[str, float]:
            rows = self._query(
                "SELECT u.run_id, r.value FROM records r JOIN record_run u "
                "ON u.record_rowid = r.rowid WHERE r.metric = ?",
                [metric],
            )
            return {str(a): _f(b) for a, b in rows}

        xs, ys = per_run(x_metric), per_run(y_metric)
        names = dict(self.timing_runs()) if self.has_timing() else {}
        keys = sorted(xs.keys() & ys.keys())
        pts = [Point(names.get(k, k), xs[k], ys[k]) for k in keys]
        return Scatter(pts[:SCATTER_LIMIT], len(pts))


class MimirView(_ExploreMixin):
    """Read-only access to one Mimir store. Opening checks the file and its schema version."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.version = self._check()

    def uri(self) -> str:
        """SQLite read-only URI; the path is percent-encoded, so `#`, `?` and `%` are safe."""
        return self.path.resolve().as_uri() + "?mode=ro"

    @property
    def wal_present(self) -> bool:
        """True when a `-wal` file sits beside the store (another process may have it open)."""
        return Path(f"{self.path}-wal").exists()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.uri(), uri=True)
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
        if version not in SUPPORTED_VERSIONS:
            raise MimirError(
                f"{self.path}: schema version {version}; "
                f"this Wyrd reads versions {' and '.join(SUPPORTED_VERSIONS)}"
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
        limit = limit if limit > 0 else NO_LIMIT  # 0 or less: no cap
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
        runs_only = counts.get("records", 0) == 0 and counts.get("run", 0) > 0
        return Summary(
            self.version,
            self.path.stat().st_size,
            counts,
            Table("sources", ("source", "records", "runs"), src_rows),
            levels,
            n_metrics,
            RUNS_ONLY_NOTE if runs_only else "",
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
            where.append(
                "(a.name LIKE ? ESCAPE '\\' OR COALESCE(a.slug, '') LIKE ? ESCAPE '\\')"
            )  # LIKE folds ASCII case only, the same for both sides
            args += [f"%{like_escape(text)}%"] * 2
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
        self,
        name: str,
        source: str | None = None,
        limit: int = DEFAULT_LIMIT,
        level: str | None = None,
    ) -> DesignInfo:
        pairs = self._design_pairs(name, source)
        if not pairs:
            raise MimirError(f"no design {name!r}" + (f" in source {source!r}" if source else ""))
        srcs = [s for s, _ in pairs]
        slugs = sorted({slug for _, slug in pairs if slug})
        return DesignInfo(
            name,
            srcs,
            self._metrics(name, srcs, limit, level),
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

    def _metrics(self, name: str, srcs: list[str], limit: int, level: str | None = None) -> Table:
        lvl = " AND level = ?" if level else ""
        sql = (
            "SELECT source, level, metric, value, unit, measurer, origin, arch, arm, seed, bin, "
            f"tool_commit FROM records WHERE design = ? AND source IN ({self._in(srcs)}){lvl} "
            "ORDER BY level, metric, source, arm, arch, seed"
        )
        cols = ("source", "level", "metric", "value", "unit", "measurer", "origin", "arch", "arm",
                "seed", "bin", "tool_commit")  # fmt: skip
        return self._table("metrics", cols, sql, [name, *srcs, *([level] if level else [])], limit)

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
            "SELECT source, arm FROM (SELECT DISTINCT source, arm FROM records UNION "
            "SELECT DISTINCT source, arm FROM run) WHERE source >= ? AND source < ? "
            "ORDER BY source, arm",
            [lo, hi],
        )
        return [config_label(str(s), str(a)) for s, a in rows]

    def metric_names(self, prefix: str = "") -> list[str]:
        """Record metrics under the source prefix, then `run.*` metrics when run rows exist."""
        lo, hi = prefix_range(prefix)
        rows = self._query(
            "SELECT DISTINCT metric FROM records WHERE source >= ? AND source < ? ORDER BY metric",
            [lo, hi],
        )
        names = [str(r[0]) for r in rows]
        have_run = self._query(
            "SELECT 1 FROM run WHERE source >= ? AND source < ? LIMIT 1", [lo, hi]
        )
        return names + (list(RUN_METRICS) if have_run else [])

    def _compare_rows(self, lo: str, hi: str, metric: str, level: str | None) -> list[Row]:
        """Rows of source, arm, level, design, arch, seed, tool_commit, value."""
        if metric in RUN_METRICS:
            col = metric.split(".", 1)[1]
            return self._query(
                f"SELECT source, arm, '', design, arch, seed, tool_commit, {col} FROM run "
                "WHERE source >= ? AND source < ?",
                [lo, hi],
            )
        sql = (
            "SELECT source, arm, level, design, arch, seed, tool_commit, value FROM records "
            "WHERE source >= ? AND source < ? AND metric = ?"
        )
        args: list[object] = [lo, hi, metric]
        if level:
            sql += " AND level = ?"
            args.append(level)
        return self._query(sql, args)

    def _config_counts(self, lo: str, hi: str) -> dict[str, int]:
        rows = self._query(
            "SELECT source, arm, COUNT(DISTINCT config_hash) FROM run "
            "WHERE source >= ? AND source < ? GROUP BY source, arm",
            [lo, hi],
        )
        return {config_label(str(s), str(a)): _n(n) for s, a, n in rows}

    def compare(self, prefix: str, base: str, metric: str, level: str | None = None) -> Compare:
        """Geomean of value / base value per (config, level); see the spec for the averaging."""
        lo, hi = prefix_range(prefix)
        groups: dict[tuple[str, str], _Group] = {}
        for s, a, lvl, d, arch, seed, commit, v in self._compare_rows(lo, hi, metric, level):
            g = groups.setdefault((config_label(str(s), str(a)), str(lvl)), _Group())
            g.add(str(d), str(arch), _n(seed), str(commit), v)
        if not any(label == base for label, _ in groups):
            raise MimirError(
                f"base config {base!r} has no {metric!r} values under prefix {prefix!r}"
            )
        cfgs = self._config_counts(lo, hi)
        out = Compare(metric, base)
        for label, lvl in sorted(groups):
            g, b = groups[(label, lvl)], groups.get((base, lvl), _Group())
            n, r, dropped = ratio_stats(g.design_means(), b.design_means())
            out.rows.append(
                CompareRow(
                    label,
                    lvl,
                    n,
                    r,
                    g.nonnumeric + dropped,
                    g.duplicates,
                    len(g.commits),
                    cfgs.get(label, 0),
                )  # fmt: skip
            )
        return out

    def scatter(self, x_metric: str, y_metric: str, source: str | None = None) -> Scatter:
        """Per (source, design) the mean of each metric over the arms that have both."""
        xs = self._per_arm(x_metric, source)
        ys = self._per_arm(y_metric, source)
        per: dict[tuple[str, str], list[tuple[float, float]]] = {}
        for key in xs.keys() & ys.keys():
            s, _arm, d = key
            per.setdefault((s, d), []).append((xs[key], ys[key]))
        pts = [
            Point(f"{s}/{d}", sum(x for x, _ in v) / len(v), sum(y for _, y in v) / len(v), s, d)
            for (s, d), v in sorted(per.items())
        ]
        return Scatter(pts[:SCATTER_LIMIT], len(pts))

    def _per_arm(self, metric: str, source: str | None) -> dict[tuple[str, str, str], float]:
        sql = "SELECT source, arm, design, value FROM records WHERE metric = ?"
        args: list[object] = [metric]
        if source:
            sql += " AND source = ?"
            args.append(source)
        acc: dict[tuple[str, str, str], list[float]] = {}
        for s, a, d, v in self._query(sql, args):
            x = _f(v)
            if not math.isnan(x):
                acc.setdefault((str(s), str(a), str(d)), []).append(x)
        return {k: sum(v) / len(v) for k, v in acc.items()}


class _Group:
    """Values of one (config, level): deduplicated per (design, arch, seed), then averaged."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str, int], list[float]] = {}
        self.commits: set[str] = set()
        self.nonnumeric = 0

    @property
    def duplicates(self) -> int:
        return sum(len(v) - 1 for v in self.values.values())

    def add(self, design: str, arch: str, seed: int, commit: str, value: object) -> None:
        self.commits.add(commit)
        x = _f(value)
        if math.isnan(x):
            self.nonnumeric += 1
        else:
            self.values.setdefault((design, arch, seed), []).append(x)

    def design_means(self) -> dict[str, float]:
        """One value per (design, arch, seed), mean over seeds per arch, then over archs."""
        per_arch: dict[tuple[str, str], list[float]] = {}
        for (d, arch, _seed), v in self.values.items():
            per_arch.setdefault((d, arch), []).append(sum(v) / len(v))
        per_design: dict[str, list[float]] = {}
        for (d, _arch), v in per_arch.items():
            per_design.setdefault(d, []).append(sum(v) / len(v))
        return {d: sum(v) / len(v) for d, v in per_design.items()}


def ratio_stats(values: dict[str, float], base: dict[str, float]) -> tuple[int, float | None, int]:
    """(n, geomean of values/base, shared designs left out because a value is <= 0)."""
    shared = [k for k in values if k in base]
    n, r = geomean_ratio(values, base)
    return n, r, len(shared) - n


def _n(x: object) -> int:
    return x if isinstance(x, int) else 0


def _f(x: object) -> float:
    return float(x) if isinstance(x, (int, float)) else math.nan


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
    if t.more:
        buf.write(f"# truncated at {len(t.rows)} rows\n")
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
