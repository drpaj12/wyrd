"""Build a tiny synthetic Mimir v4 store from tests/data/mimir/schema_v4.sql (no real data)."""

import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).parent / "data" / "mimir" / "schema_v4.sql"
SRC = "exp-a"
ARCH = "arch1"


def _rec(
    design: str, source: str, level: str, metric: str, value: float, arm: str, seed: int
) -> tuple[object, ...]:
    return (design, source, "sha-" + design, "tc1", "", level, ARCH, seed, arm, "", metric, "",
            value, "u", "meas", "m1", f"data/{source}.jsonl:{seed}")  # fmt: skip


def build(path: Path, version: str = "4", timing: bool = False, paths: bool = False) -> Path:
    con = sqlite3.connect(path)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.execute("INSERT INTO meta VALUES ('schema_version', ?)", (version,))
    for d in ("d1", "d2", "d3"):
        con.execute("INSERT INTO design VALUES (?, 'h', 'hdl', 'suiteX', ?, 'o')", (f"s/{d}", d))
        con.execute("INSERT INTO design_source VALUES (?, ?, ?)", (SRC + "-1", d, f"s/{d}"))
        con.execute("INSERT INTO design_source VALUES (?, ?, ?)", (SRC + "-2", d, f"s/{d}"))
    con.execute("INSERT INTO design_meta VALUES ('s/d1', 'author', 'Ann', 'paper', 'primary')")
    con.execute(
        "INSERT INTO design_lineage VALUES ('s/d1', 1, 'SIS', 'rugged', '', 'readme', 'primary')"
    )
    con.execute(
        "INSERT INTO structure VALUES "
        "('s/d1', 'st1', 'adder', 'f.v:1', '', 'det', 0.9, 'r1', 'c1', 'block', '')"
    )
    con.execute(
        "INSERT INTO flow_config VALUES ('c1', 'exp-a-1/base', 'txt', 'reconstructed', 'full', 'o')"
    )
    for step, key, val, conf in (
        ("vpr", "seed", "1", "given"),
        ("vpr", "inner_num", "1", "default"),
        ("abc", "script", "", "unknown"),
    ):
        con.execute(
            "INSERT INTO flow_param VALUES ('c1', ?, ?, ?, ?, 'src')", (step, key, val, conf)
        )
    runs = [("r1", "d1", SRC + "-1", "base", 1), ("r2", "d2", SRC + "-1", "base", 1),
            ("r3", "d1", SRC + "-2", "alt", 1)]  # fmt: skip
    for rid, d, src, arm, seed in runs:
        con.execute(
            "INSERT INTO run VALUES (?, ?, 'c1', ?, ?, ?, ?, ?, '', 'vtr=x', NULL, 1.5, 100.0, "
            "'host1', 'o', 'tc1', 'sha-' || ?)",
            (rid, f"s/{d}", src, d, ARCH, seed, arm, d),
        )
    con.execute("INSERT INTO run_artifact VALUES ('r1', 'log', 'abc123')")
    vals = {("d1", "base"): 10.0, ("d2", "base"): 20.0, ("d3", "base"): 30.0,
            ("d1", "alt"): 5.0, ("d2", "alt"): 20.0, ("d3", "alt"): 60.0}  # fmt: skip
    for (d, arm), v in vals.items():
        src = SRC + ("-1" if arm == "base" else "-2")
        for s in (1, 2):
            con.execute(
                "INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                _rec(d, src, "routed", "vpr.cpd", v * s, arm, s),
            )
        con.execute(
            "INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            _rec(d, src, "clb", "vpr.logic_clbs", v * 2, arm, 1),
        )
    if timing or paths:
        add_v5(con)
    if paths:
        add_v6(con)
    con.commit()
    con.close()
    return path


V5_DDL = (
    """CREATE TABLE timing_run (
        run_id TEXT PRIMARY KEY, cpd_ns REAL, worst_slack_ns REAL, paths_requested INTEGER,
        paths_in_report INTEGER NOT NULL, paths_used INTEGER NOT NULL, max_req_ns REAL,
        dmax_source TEXT NOT NULL, pairs INTEGER NOT NULL, pairs_skipped INTEGER NOT NULL,
        last_crit REAL, trunc_090 INTEGER NOT NULL, trunc_095 INTEGER NOT NULL,
        trunc_099 INTEGER NOT NULL, n_endpoints_090 INTEGER NOT NULL,
        n_endpoints_095 INTEGER NOT NULL, n_endpoints_099 INTEGER NOT NULL,
        source_kind TEXT NOT NULL, source_sha256 TEXT NOT NULL, analysis_n INTEGER)""",
    """CREATE TABLE timing_path_hist (
        run_id TEXT NOT NULL, bin INTEGER NOT NULL, n INTEGER NOT NULL,
        PRIMARY KEY (run_id, bin))""",
    """CREATE TABLE timing_object (
        run_id TEXT NOT NULL, kind TEXT NOT NULL, object_key TEXT NOT NULL,
        bit INTEGER NOT NULL DEFAULT -1, via TEXT NOT NULL DEFAULT '',
        crit_max REAL NOT NULL, n_paths INTEGER NOT NULL, n_paths_090 INTEGER NOT NULL,
        n_paths_095 INTEGER NOT NULL, n_paths_099 INTEGER NOT NULL, delay_share_090 REAL,
        PRIMARY KEY (run_id, kind, object_key, bit))""",
)
WORD = "top/SIGNAL"


def add_v5(con: sqlite3.Connection) -> None:
    """Timing rows for runs r1 and r2, structure_mapping rows for design s/d1."""
    for ddl in V5_DDL:
        con.execute(ddl)
    con.execute("UPDATE meta SET value = '5' WHERE key = 'schema_version'")
    for rid, n090 in (("r1", 4), ("r2", 1)):
        con.execute(
            "INSERT INTO timing_run VALUES (?, 5.0, -5.0, 100, 100, 100, 0.0, 'report', 1, 0, "
            "0.8, 0, 0, 0, ?, 1, 1, 'attribution', 'sha', NULL)",
            (rid, n090),
        )
        con.execute("INSERT INTO timing_path_hist VALUES (?, 19, ?)", (rid, n090))
        con.execute("INSERT INTO timing_path_hist VALUES (?, 3, 7)", (rid,))
    rows = [("span", "f.v:7", -1, "", 1.0), ("word", WORD, -1, "name", 1.0),
            ("word", WORD, 2, "name", 1.0), ("word", WORD, 0, "name", 0.97),
            ("module", "top", -1, "", 1.0)]  # fmt: skip
    for kind, key, bit, via, crit in rows:
        con.execute(
            "INSERT INTO timing_object VALUES ('r1', ?, ?, ?, ?, ?, 5, 4, 2, 1, NULL)",
            (kind, key, bit, via, crit),
        )
    for sid, lvl, luts, spread, crit in (("st1", "lut", 3, 0.5, 0.9), ("st1", "clb", 3, 1.5, 0.8)):
        con.execute(
            "INSERT INTO structure_mapping VALUES ('s/d1', ?, 'r1', ?, 'c1', 1, 1, 0, NULL, ?, "
            "NULL, NULL, NULL, 1, NULL, 'j', '', 1, 2, 3, 4, ?, ?)",
            (sid, lvl, luts, spread, crit),
        )
    for rid, metric, v in (("r1", "timing.nc_paths_090", 4.0), ("r2", "timing.nc_paths_090", 1.0)):
        d = "d1" if rid == "r1" else "d2"
        con.execute(
            "INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (d, SRC + "-1", "sha-" + d, "tc1", "", "routed", ARCH, 1, "base", "", metric, "",
             v, "n", "import-timing", "m1", "x"),
        )  # fmt: skip


V6_DDL = (
    """CREATE TABLE timing_path (
        run_id TEXT NOT NULL, path_index INTEGER NOT NULL, slack_ns REAL, arrival_ns REAL,
        required_ns REAL, crit REAL, startpoint TEXT NOT NULL, endpoint TEXT NOT NULL,
        n_nodes INTEGER NOT NULL, PRIMARY KEY (run_id, path_index))""",
    """CREATE TABLE timing_path_node (
        run_id TEXT NOT NULL, path_index INTEGER NOT NULL, step INTEGER NOT NULL,
        atom TEXT, block_type TEXT, pins TEXT, span TEXT, loc TEXT, module TEXT, word TEXT,
        bit INTEGER, word_via TEXT, category TEXT, cell_delay_ns REAL, net_delay_in_ns REAL,
        delay_ns REAL, PRIMARY KEY (run_id, path_index, step))""",
)
FILE = "$VTR_ROOT/d.v"
# (path_index, crit, slack, [(span line, module, word, bit, delay)]): paths 1 and 2 share line 10;
# path 3 is below 0.90 and leaves the file.
PATHS: tuple[tuple[int, float, float, tuple[tuple[str, str, str, int, float], ...]], ...] = (
    (1, 1.0, -2.0, ((f"{FILE}:10", "top", "a", 3, 1.0), (f"{FILE}:20", "top", "b", -1, 0.5))),
    (2, 0.8, -1.0, ((f"{FILE}:10", "top", "a", 3, 1.0), (f"{FILE}:30", "top", "c", -1, 0.25))),
    (3, 0.4, -0.5, ((f"{FILE}:10", "top", "a", 3, 1.0),
                    ("$VTR_ROOT/other.v:5", "sub", "z", -1, 2.0))),
)  # fmt: skip


def add_v6(con: sqlite3.Connection) -> None:
    """Per-path rows for run r1 of a v5 store (a synthetic design with two files)."""
    for ddl in V6_DDL:
        con.execute(ddl)
    con.execute("UPDATE meta SET value = '6' WHERE key = 'schema_version'")
    for idx, crit, slack, nodes in PATHS:
        con.execute(
            "INSERT INTO timing_path VALUES ('r1', ?, ?, 1.0, 0.0, ?, 'st (.latch clocked by c)', "
            "'en (.latch clocked by c)', ?)", (idx, slack, crit, len(nodes)),
        )  # fmt: skip
        for step, (span, mod, word, bit, delay) in enumerate(nodes, 1):
            con.execute(
                "INSERT INTO timing_path_node VALUES ('r1', ?, ?, 'at', '.names', '[]', ?, '', ?, "
                "?, ?, 'name', 'matched', 0.1, 0.2, ?)", (idx, step, span, mod, word, bit, delay),
            )  # fmt: skip
