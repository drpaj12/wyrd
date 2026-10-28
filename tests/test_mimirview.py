"""Mimir browser model on a synthetic v4 store."""

import math
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests import mimir_fixture
from wyrd import mimirview
from wyrd.mimirview import MimirError, MimirView


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
        self.assertIn("geomean", c.as_table().columns[2])
        with self.assertRaises(MimirError):
            self.v.compare("exp-a-", "nope", "vpr.cpd")
        self.assertEqual(self.v.config_labels("exp-a-"), ["exp-a-1/base", "exp-a-2/alt"])
        self.assertEqual(self.v.metric_names(), ["vpr.cpd", "vpr.logic_clbs"])

    def test_scatter(self) -> None:
        pts = self.v.scatter("vpr.cpd", "vpr.logic_clbs", "exp-a-1")
        self.assertEqual(len(pts), 3)
        self.assertEqual((pts[0].x, pts[0].y), (15.0, 20.0))

    def test_geomean_none(self) -> None:
        self.assertEqual(mimirview.geomean_ratio({"a": 0.0}, {"a": 1.0}), (0, None))

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


if __name__ == "__main__":
    unittest.main()
