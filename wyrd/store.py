"""Run keys, run directories and the per-project results database ``wyrd.db`` (spec section 4)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from wyrd.model import Metric, RunSpec

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    key TEXT PRIMARY KEY, design TEXT, arch TEXT, recipe TEXT, params TEXT,
    status TEXT, started TEXT, ended TEXT, run_dir TEXT);
CREATE TABLE IF NOT EXISTS steps (
    key TEXT, n INTEGER, step TEXT, argv TEXT, exit_code INTEGER, wall_s REAL,
    peak_mem_bytes INTEGER, PRIMARY KEY (key, n));
CREATE TABLE IF NOT EXISTS metrics (
    key TEXT, step TEXT, name TEXT, value REAL, unit TEXT);
CREATE INDEX IF NOT EXISTS metrics_key ON metrics (key);
PRAGMA user_version = 1;
"""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


_STATUSES = frozenset({"ok", "fail", "oom", "timeout", "cancelled"})


def _norm(name: str, value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list | tuple):
        return [_norm(name, item) for item in value]
    raise TypeError(f"param {name!r}: unsupported type {type(value).__name__}")


def _norm_params(params: dict[str, object]) -> dict[str, object]:
    """Params as JSON-safe values: scalars, Path as str, list/tuple as list; else TypeError."""
    return {name: _norm(name, value) for name, value in params.items()}


def run_key(
    spec: RunSpec,
    arch_xml: Path | None,
    tool_versions: dict[str, str],
    resolved_argv: list[list[str]],
) -> str:
    """SHA-256 over names, resolved argv, input file hashes, arch hash, tool versions, params."""
    payload = {
        "design_name": spec.design.name,
        "arch_name": spec.arch,
        "recipe_name": spec.recipe.name,
        "argv": resolved_argv,
        "files": {str(path): _sha256_file(path) for path in spec.design.files},
        "arch": _sha256_file(arch_xml) if arch_xml is not None else None,
        "tools": tool_versions,
        "params": _norm_params(spec.params),
    }
    text = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def run_dir(root: Path, spec: RunSpec, key: str) -> Path:
    """The directory of one run: ``root/runs/<design>/<arch>/<key[:12]>``."""
    return root / "runs" / spec.design.name / spec.arch / key[:12]


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    """The SQLite index of a project's runs. One short-lived connection per call."""

    _read_only = False

    @classmethod
    def open_readonly(cls, path: Path) -> Store:
        """Open an existing database read-only: no directory creation, no PRAGMA, no schema."""
        store = cls.__new__(cls)
        store.path = path
        store._read_only = True
        return store

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        if self._read_only:
            uri = f"file:{quote(str(self.path))}?mode=ro"
            return sqlite3.connect(uri, timeout=30, uri=True)
        return sqlite3.connect(self.path, timeout=30)

    def _exec(self, sql: str, args: tuple[object, ...] = ()) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(sql, args)

    def _query(self, sql: str, args: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
        with closing(self._connect()) as conn:
            return conn.execute(sql, args).fetchall()

    def begin(self, key: str, spec: RunSpec, run_dir: Path) -> None:
        """Start (or restart) a run; drops the key's old steps and metrics atomically."""
        params = json.dumps(_norm_params(spec.params), sort_keys=True)
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM steps WHERE key = ?", (key,))
            conn.execute("DELETE FROM metrics WHERE key = ?", (key,))
            conn.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    key,
                    spec.design.name,
                    spec.arch,
                    spec.recipe.name,
                    params,
                    "running",
                    _now(),
                    None,
                    str(run_dir),
                ),
            )

    def finish(self, key: str, status: str) -> None:
        if status not in _STATUSES:
            raise ValueError(f"bad status {status!r}")
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "UPDATE runs SET status = ?, ended = ? WHERE key = ?", (status, _now(), key)
            )
            if cur.rowcount == 0:
                raise KeyError(key)

    def add_step(
        self,
        key: str,
        n: int,
        step: str,
        argv: list[str],
        exit_code: int,
        wall_s: float,
        peak_mem_bytes: int | None,
    ) -> None:
        self._exec(
            "INSERT OR REPLACE INTO steps VALUES (?,?,?,?,?,?,?)",
            (key, n, step, json.dumps(argv), exit_code, wall_s, peak_mem_bytes),
        )

    def add_metrics(self, key: str, step: str, metrics: list[Metric]) -> None:
        with closing(self._connect()) as conn, conn:
            conn.executemany(
                "INSERT INTO metrics VALUES (?,?,?,?,?)",
                [(key, step, m.name, m.value, m.unit) for m in metrics],
            )

    def status(self, key: str) -> str | None:
        rows = self._query("SELECT status FROM runs WHERE key = ?", (key,))
        return str(rows[0][0]) if rows else None

    def peak_mem(self, design: str, arch: str, step: str) -> int | None:
        rows = self._query(
            "SELECT MAX(s.peak_mem_bytes) FROM steps s JOIN runs r ON r.key = s.key "
            "WHERE r.design = ? AND r.arch = ? AND s.step = ?",
            (design, arch, step),
        )
        value = rows[0][0]
        return int(value) if isinstance(value, int) else None

    def rows(self) -> list[dict[str, object]]:
        """One dict per run: the runs columns plus one entry per metric name.

        A metric whose name equals a runs column is stored as ``metric.<name>``. When several
        steps report the same metric name, the later step (higher step n) wins; the order is an
        explicit ORDER BY on the step number, then insertion order.
        """
        with closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            runs = [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY design, arch, key")]
            for row in runs:
                columns = set(row)
                for m in conn.execute(
                    "SELECT m.name, m.value FROM metrics m LEFT JOIN steps s "
                    "ON s.key = m.key AND s.step = m.step WHERE m.key = ? "
                    "ORDER BY COALESCE(s.n, 0), m.rowid",
                    (row["key"],),
                ):
                    name = m["name"]
                    row[f"metric.{name}" if name in columns else name] = m["value"]
        return runs
