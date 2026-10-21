"""Run keys, run directories and the per-project results database ``wyrd.db`` (spec section 4)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

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


def run_key(
    spec: RunSpec,
    arch_xml: Path | None,
    tool_versions: dict[str, str],
    resolved_argv: list[list[str]],
) -> str:
    """SHA-256 over the resolved argv, input file hashes, arch hash, tool versions and params."""
    payload = {
        "argv": resolved_argv,
        "files": {str(path): _sha256_file(path) for path in spec.design.files},
        "arch": _sha256_file(arch_xml) if arch_xml is not None else None,
        "tools": tool_versions,
        "params": spec.params,
    }
    text = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def run_dir(root: Path, spec: RunSpec, key: str) -> Path:
    """The directory of one run: ``root/runs/<design>/<arch>/<key[:12]>``."""
    return root / "runs" / spec.design.name / spec.arch / key[:12]


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    """The SQLite index of a project's runs. One short-lived connection per call."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def _exec(self, sql: str, args: tuple[object, ...] = ()) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(sql, args)

    def _query(self, sql: str, args: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
        with closing(self._connect()) as conn:
            return conn.execute(sql, args).fetchall()

    def begin(self, key: str, spec: RunSpec, run_dir: Path) -> None:
        self._exec(
            "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
            (
                key,
                spec.design.name,
                spec.arch,
                spec.recipe.name,
                json.dumps(spec.params, sort_keys=True, default=str),
                "running",
                _now(),
                None,
                str(run_dir),
            ),
        )

    def finish(self, key: str, status: str) -> None:
        self._exec("UPDATE runs SET status = ?, ended = ? WHERE key = ?", (status, _now(), key))

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
        with closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            runs = [dict(r) for r in conn.execute("SELECT * FROM runs ORDER BY design, arch, key")]
            for row in runs:
                for m in conn.execute(
                    "SELECT name, value FROM metrics WHERE key = ? ORDER BY rowid", (row["key"],)
                ):
                    row[m["name"]] = m["value"]
        return runs
