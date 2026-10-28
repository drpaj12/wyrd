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


class MimirView:
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
        per: dict[str, list[tuple[float, float]]] = {}
        for key in xs.keys() & ys.keys():
            s, _arm, d = key
            per.setdefault(f"{s}/{d}", []).append((xs[key], ys[key]))
        pts = [
            Point(k, sum(x for x, _ in v) / len(v), sum(y for _, y in v) / len(v))
            for k, v in sorted(per.items())
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
