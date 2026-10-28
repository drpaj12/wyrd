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


def build(path: Path, version: str = "4") -> Path:
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
    con.commit()
    con.close()
    return path
