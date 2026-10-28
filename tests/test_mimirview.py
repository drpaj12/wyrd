"""Mimir browser model on a synthetic v4 store."""

import math
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import mimir_fixture
from wyrd import mimirview
from wyrd.mimirview import MimirError, MimirView


def edit(db: Path, *statements: str) -> None:
    """Change a temp copy of the synthetic store (never a real store)."""
    con = sqlite3.connect(db)
    for sql in statements:
        con.execute(sql)
    con.commit()
    con.close()


def record_sql(source: str, arm: str, design: str, value: float, level: str = "routed",
               commit: str = "tc1", origin: str = "o2", seed: int = 1) -> str:  # fmt: skip
    return (
        "INSERT INTO records VALUES "
        f"('{design}','{source}','sha','{commit}','','{level}','arch1',{seed},'{arm}','',"
        f"'vpr.cpd','',{value},'u','meas','m1','{origin}')"
    )


class ViewTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = mimir_fixture.build(self.dir / "s.db")
        self.v = MimirView(self.db)

    def test_summary(self) -> None:
        s = self.v.summary()
        self.assertEqual(s.version, "4")
        self.assertEqual(s.counts["records"], 18)
        self.assertEqual(s.counts["run"], 3)
        self.assertEqual([r[0] for r in s.sources.rows], ["exp-a-1", "exp-a-2"])
        self.assertEqual(s.levels, ["clb", "routed"])
        self.assertEqual(s.n_metrics, 2)

    def test_designs_filter(self) -> None:
        self.assertEqual(len(self.v.designs().rows), 6)
        self.assertEqual(len(self.v.designs(source="exp-a-1").rows), 3)
        self.assertEqual(len(self.v.designs(text="D2").rows), 2)
        t = self.v.designs(limit=2)
        self.assertEqual((len(t.rows), t.more), (2, True))
        self.assertEqual(self.v.designs(source="exp-a-1", text="d1").rows[0][4], 1)

    def test_design(self) -> None:
        d = self.v.design("d1")
        self.assertEqual(d.sources, ["exp-a-1", "exp-a-2"])
        self.assertEqual(len(d.metrics.rows), 6)
        self.assertEqual(len(d.runs.rows), 2)
        self.assertEqual(d.meta.rows[0][:2], ("author", "Ann"))
        self.assertEqual(d.lineage.rows[0][1], "SIS")
        self.assertEqual(d.structures.rows, [("adder", 1)])
        only = self.v.design("d1", source="exp-a-2")
        self.assertEqual(len(only.runs.rows), 1)
        with self.assertRaises(MimirError):
            self.v.design("nope")

    def test_run(self) -> None:
        r = self.v.run("r1")
        self.assertEqual(r.header["design"], "d1")
        self.assertEqual(r.config["name"], "exp-a-1/base")
        self.assertEqual([p[3] for p in r.params.rows], ["unknown", "default", "given"])
        self.assertEqual(r.artifacts.rows, [("log", "abc123")])
        with self.assertRaises(MimirError):
            self.v.run("zz")

    def test_compare(self) -> None:
        c = self.v.compare("exp-a-", "exp-a-1/base", "vpr.cpd")
        by = {r.label: r for r in c.rows}
        self.assertEqual(by["exp-a-1/base"].ratio, 1.0)
        self.assertEqual(by["exp-a-2/alt"].n, 3)
        self.assertAlmostEqual(
            by["exp-a-2/alt"].ratio or 0, math.exp((math.log(0.5) + 0 + math.log(2)) / 3)
        )
        self.assertIn("geomean", c.as_table().columns[3])
        self.assertEqual((by["exp-a-2/alt"].level, by["exp-a-2/alt"].dropped), ("routed", 0))
        self.assertEqual((by["exp-a-2/alt"].commits, by["exp-a-2/alt"].configs), (1, 1))
        self.assertFalse(by["exp-a-2/alt"].mixed)
        with self.assertRaises(MimirError):
            self.v.compare("exp-a-", "nope", "vpr.cpd")
        self.assertEqual(self.v.config_labels("exp-a-"), ["exp-a-1/base", "exp-a-2/alt"])
        self.assertEqual(
            self.v.metric_names(), ["vpr.cpd", "vpr.logic_clbs", "run.time_s", "run.peak_rss_mib"]
        )

    def test_scatter(self) -> None:
        sc = self.v.scatter("vpr.cpd", "vpr.logic_clbs", "exp-a-1")
        pts = sc.points
        self.assertEqual(len(pts), 3)
        self.assertEqual((pts[0].x, pts[0].y), (15.0, 20.0))
        self.assertFalse(sc.capped)

    def test_scatter_cap_note(self) -> None:
        with mock.patch.object(mimirview, "SCATTER_LIMIT", 2):
            sc = self.v.scatter("vpr.cpd", "vpr.logic_clbs")
        self.assertEqual((len(sc.points), sc.total, sc.capped), (2, 6, True))
        self.assertIn("capped at 2 of 6", sc.note)

    def test_scatter_same_arm_set(self) -> None:
        # a second arm with cpd only: it must not change the mean of x for (exp-a-1, d1)
        edit(self.db, record_sql("exp-a-1", "extra", "d1", 1000.0))
        pts = MimirView(self.db).scatter("vpr.cpd", "vpr.logic_clbs", "exp-a-1").points
        self.assertEqual((pts[0].x, pts[0].y), (15.0, 20.0))

    def test_compare_duplicates_merged(self) -> None:
        edit(
            self.db,
            record_sql("exp-a-2", "alt", "d1", 5.0),
            record_sql("exp-a-2", "alt", "d2", 20.0),
        )
        by = {
            r.label: r for r in MimirView(self.db).compare("exp-a-", "exp-a-1/base", "vpr.cpd").rows
        }
        self.assertEqual(by["exp-a-2/alt"].duplicates, 2)
        self.assertEqual(by["exp-a-2/alt"].n, 3)
        self.assertAlmostEqual(
            by["exp-a-2/alt"].ratio or 0, math.exp((math.log(0.5) + math.log(2)) / 3)
        )

    def test_compare_dropped_nonpositive(self) -> None:
        edit(self.db, "UPDATE records SET value = 0 WHERE source='exp-a-2' AND design='d3'")
        by = {
            r.label: r for r in MimirView(self.db).compare("exp-a-", "exp-a-1/base", "vpr.cpd").rows
        }
        self.assertEqual((by["exp-a-2/alt"].n, by["exp-a-2/alt"].dropped), (2, 1))
        self.assertIn(
            "dropped", self.v.compare("exp-a-", "exp-a-1/base", "vpr.cpd").as_table().columns[4]
        )

    def test_compare_flags_mixed(self) -> None:
        edit(self.db, record_sql("exp-a-1", "base", "d1", 10.0, commit="tc2"))
        by = {
            r.label: r for r in MimirView(self.db).compare("exp-a-", "exp-a-1/base", "vpr.cpd").rows
        }
        self.assertEqual(by["exp-a-1/base"].commits, 2)
        self.assertTrue(by["exp-a-1/base"].mixed)
        edit(
            self.db,
            "INSERT INTO run SELECT 'r9', slug, 'c2', source, design, arch, 2, arm, family, "
            "tool_commits, command_line, time_s, peak_rss_mib, host, origin, tool_commit, "
            "input_sha256 FROM run WHERE run_id='r3'",
        )
        by = {
            r.label: r for r in MimirView(self.db).compare("exp-a-", "exp-a-1/base", "vpr.cpd").rows
        }
        self.assertEqual(by["exp-a-2/alt"].configs, 2)
        self.assertTrue(by["exp-a-2/alt"].mixed)

    def test_compare_per_level(self) -> None:
        edit(self.db, record_sql("exp-a-1", "base", "d1", 40.0, level="placed"),
             record_sql("exp-a-2", "alt", "d1", 20.0, level="placed"))  # fmt: skip
        c = MimirView(self.db).compare("exp-a-", "exp-a-1/base", "vpr.cpd")
        self.assertTrue(c.multi_level)
        placed = {r.label: r for r in c.rows if r.level == "placed"}
        self.assertAlmostEqual(placed["exp-a-2/alt"].ratio or 0, 0.5)
        only = MimirView(self.db).compare("exp-a-", "exp-a-1/base", "vpr.cpd", "routed")
        self.assertFalse(only.multi_level)

    def test_prefix_boundary(self) -> None:
        edit(
            self.db,
            record_sql("exp-a-1x", "base", "d1", 1.0),
            record_sql("exp-ab", "base", "d1", 1.0),
            record_sql("exp-a", "base", "d1", 1.0),
        )
        v = MimirView(self.db)
        self.assertEqual(v.config_labels("exp-a-1"), ["exp-a-1/base", "exp-a-1x/base"])
        self.assertEqual(
            v.config_labels("exp-a-"), ["exp-a-1/base", "exp-a-1x/base", "exp-a-2/alt"]
        )
        self.assertEqual(v.config_labels("exp-a-1x"), ["exp-a-1x/base"])

    def test_runs_only_store(self) -> None:
        edit(self.db, "DELETE FROM records")
        v = MimirView(self.db)
        s = v.summary()
        self.assertEqual(s.note, mimirview.RUNS_ONLY_NOTE)
        self.assertEqual(v.config_labels("exp-a-"), ["exp-a-1/base", "exp-a-2/alt"])
        self.assertEqual(v.metric_names(), ["run.time_s", "run.peak_rss_mib"])
        edit(self.db, "UPDATE run SET time_s = 3.0 WHERE run_id='r3'")
        c = MimirView(self.db).compare("exp-a-", "exp-a-1/base", "run.time_s")
        by = {r.label: r for r in c.rows}
        self.assertEqual(by["exp-a-1/base"].ratio, 1.0)
        self.assertAlmostEqual(by["exp-a-2/alt"].ratio or 0, 2.0)  # 3.0 vs 1.5 on d1
        self.assertEqual(by["exp-a-2/alt"].level, "")

    def test_normal_store_has_no_note(self) -> None:
        self.assertEqual(self.v.summary().note, "")

    def test_like_wildcards_literal(self) -> None:
        self.assertEqual(len(self.v.designs(text="d_").rows), 0)
        self.assertEqual(len(self.v.designs(text="%").rows), 0)
        self.assertEqual(len(self.v.designs(text="D1").rows), 2)

    def test_special_path_and_no_new_files(self) -> None:
        odd = self.dir / "a#b%20c?d"
        odd.mkdir()
        db = mimir_fixture.build(odd / "s.db")
        before = sorted(os.listdir(odd))
        v = MimirView(db)
        v.summary()
        v.design("d1")
        v.compare("exp-a-", "exp-a-1/base", "vpr.cpd")
        v.scatter("vpr.cpd", "vpr.logic_clbs")
        self.assertEqual(sorted(os.listdir(odd)), before)
        self.assertFalse(v.wal_present)
        Path(f"{db}-wal").write_bytes(b"")
        self.assertTrue(v.wal_present)

    def test_design_level_filter(self) -> None:
        d = self.v.design("d1", level="clb")
        self.assertEqual({r[1] for r in d.metrics.rows}, {"clb"})
        self.assertEqual(len(self.v.design("d1", limit=0).metrics.rows), 6)

    def test_csv_truncated_note(self) -> None:
        t = self.v.designs(limit=2)
        self.assertTrue(mimirview.render_csv(t).endswith("# truncated at 2 rows\n"))
        self.assertNotIn("truncated", mimirview.render_csv(self.v.designs(limit=0)))

    def test_geomean_none(self) -> None:
        self.assertEqual(mimirview.geomean_ratio({"a": 0.0}, {"a": 1.0}), (0, None))

    def test_version_5_accepted_without_timing_tables(self) -> None:
        v = MimirView(mimir_fixture.build(self.dir / "v5.db", version="5"))
        self.assertEqual(v.version, "5")
        self.assertFalse(v.has_timing())
        self.assertEqual(v.timing_runs(), [])

    def test_version_6_accepted(self) -> None:
        v = MimirView(mimir_fixture.build(self.dir / "v6.db", version="6"))
        self.assertEqual(v.version, "6")

    def test_wrong_version_and_not_store(self) -> None:
        old = mimir_fixture.build(self.dir / "v3.db", version="3")
        with self.assertRaisesRegex(MimirError, "schema version 3"):
            MimirView(old)
        junk = self.dir / "junk.db"
        junk.write_text("not sqlite", encoding="utf-8")
        with self.assertRaisesRegex(MimirError, "not a Mimir store"):
            MimirView(junk)
        with self.assertRaises(MimirError):
            MimirView(self.dir / "missing.db")
        empty = self.dir / "e.db"
        sqlite3.connect(empty).close()
        with self.assertRaises(MimirError):
            MimirView(empty)

    def test_read_only(self) -> None:
        before = (self.db.read_bytes(), os.stat(self.db).st_mtime_ns)
        v = MimirView(self.db)
        v.summary()
        v.designs()
        v.design("d1")
        v.run("r1")
        v.compare("exp-a-", "exp-a-1/base", "vpr.cpd")
        v.scatter("vpr.cpd", "vpr.logic_clbs")
        self.assertEqual((self.db.read_bytes(), os.stat(self.db).st_mtime_ns), before)
        with self.assertRaises(MimirError):
            v._query("DELETE FROM records")

    def test_fetch_argv(self) -> None:
        self.assertEqual(
            mimirview.fetch_argv("r1", Path("a.db"), Path("out")),
            ["mimir", "fetch", "--run", "r1", "--db", "a.db", "--out", "out"],
        )

    def test_registry_optional(self) -> None:
        self.assertIsInstance(mimirview.metric_registry(), dict)




class ExploreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        db = mimir_fixture.build(Path(self._tmp.name) / "v5.db", timing=True)
        self.v = MimirView(db)

    def test_structures(self) -> None:
        self.assertEqual(self.v.structure_designs(), ["s/d1"])
        self.assertEqual(self.v.structure_filters("s/d1"), (["clb", "lut"], ["adder"]))
        t = self.v.structure_rows("s/d1")
        self.assertEqual(len(t.rows), 2)
        self.assertEqual(t.columns, mimirview.STRUCT_COLUMNS)
        lut = self.v.structure_rows("s/d1", level="lut", kind="adder", run="r1").rows
        self.assertEqual(lut[0][:4], ("st1", "adder", "lut", 3))
        self.assertEqual(lut[0][5], "(1,2)-(3,4)")
        self.assertEqual(self.v.structure_rows("s/d1", kind="mux").rows, [])
        pts = self.v.structure_scatter("s/d1").points
        self.assertEqual([(p.x, p.y) for p in pts], [(1.5, 0.8), (0.5, 0.9)])

    def test_timing_run(self) -> None:
        self.assertTrue(self.v.has_timing())
        self.assertEqual([r for r, _ in self.v.timing_runs()], ["r1", "r2"])
        info = self.v.timing_run("r1")
        self.assertEqual(info.hist[19], 4)
        self.assertEqual(info.hist[3], 7)
        self.assertEqual(info.summary["n_endpoints_090"], 4)
        self.assertEqual(info.summary["timing.nc_paths_090"], 4.0)
        with self.assertRaises(MimirError):
            self.v.timing_run("zz")

    def test_top_objects_with_bit_strip(self) -> None:
        t = self.v.timing_top_objects("r1", "word")
        self.assertEqual(len(t.rows), 1)
        self.assertEqual(t.rows[0][1], "top/SIGNAL")
        self.assertEqual(t.rows[0][-1], "2:1.000 0:0.970")
        self.assertEqual(len(self.v.timing_object_rows("r1")), 4)

    def test_timing_run_tolerates_missing_optional_columns(self) -> None:
        info = self.v.timing_run("r1")
        self.assertIn("req_spread_ns", info.missing)  # the fixture is a v5 store without it
        self.assertNotIn("req_spread_ns", info.summary)
        self.assertEqual(info.summary["dmax_source"], "report")

    def test_design_origin(self) -> None:
        self.assertEqual(self.v.design_origin("r1"), "o")
        self.assertEqual(self.v.design_origin("nope"), "")

    def test_word_bits_only_for_shown_words(self) -> None:
        with mock.patch.object(self.v, "_query", wraps=self.v._query) as q:
            self.v.timing_top_objects("r1", "word", 1)
        bit_sql = [c.args[0] for c in q.call_args_list if "bit >= 0" in c.args[0]]
        self.assertEqual(len(bit_sql), 1)
        self.assertIn("object_key IN (?)", bit_sql[0])
        with mock.patch.object(self.v, "_query", wraps=self.v._query) as q:
            self.v.timing_top_objects("r1", "span", 5)
        self.assertEqual([c for c in q.call_args_list if "bit >= 0" in c.args[0]], [])

    def test_bit_strip_limit_keeps_hottest(self) -> None:
        rows = [(b, b / 100) for b in range(20)]
        s = mimirview.bit_strip(rows, 3)
        self.assertEqual(s, "19:0.190 18:0.180 17:0.170")

    def test_run_scatter(self) -> None:
        pts = self.v.run_scatter("timing.nc_paths_090", "timing.nc_paths_090").points
        self.assertEqual(sorted(p.x for p in pts), [1.0, 4.0])


if __name__ == "__main__":
    unittest.main()
