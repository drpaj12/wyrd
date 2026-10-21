import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from wyrd.model import Design, Metric, Recipe, RunSpec, StepSpec
from wyrd.store import Store, run_dir, run_key

ARGV = [["odin3-flow", "a.v"]]
VERSIONS = {"odin3": "1.0"}


def make_spec(src: Path, params: dict[str, object] | None = None) -> RunSpec:
    design = Design("d", (src,), "top")
    recipe = Recipe("vtr", (StepSpec("odin3-flow"),))
    return RunSpec(design, "EArch", recipe, params or {"seed": 1})


class KeyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root / "a.v"
        self.src.write_text("module a; endmodule\n")

    def test_key_stable(self) -> None:
        spec = make_spec(self.src)
        self.assertEqual(
            run_key(spec, None, VERSIONS, ARGV), run_key(spec, None, VERSIONS, ARGV)
        )

    def test_key_changes_with_file_content(self) -> None:
        spec = make_spec(self.src)
        before = run_key(spec, None, VERSIONS, ARGV)
        self.src.write_text("module a; wire w; endmodule\n")
        self.assertNotEqual(before, run_key(spec, None, VERSIONS, ARGV))

    def test_key_changes_with_tool_version(self) -> None:
        spec = make_spec(self.src)
        self.assertNotEqual(
            run_key(spec, None, VERSIONS, ARGV),
            run_key(spec, None, {"odin3": "1.1"}, ARGV),
        )

    def test_key_changes_with_arch_and_params_and_argv(self) -> None:
        spec = make_spec(self.src)
        arch = self.root / "arch.xml"
        arch.write_text("<arch/>")
        base = run_key(spec, None, VERSIONS, ARGV)
        self.assertNotEqual(base, run_key(spec, arch, VERSIONS, ARGV))
        self.assertNotEqual(base, run_key(make_spec(self.src, {"seed": 2}), None, VERSIONS, ARGV))
        self.assertNotEqual(base, run_key(spec, None, VERSIONS, [["odin3-flow", "b.v"]]))

    def test_same_files_different_design_names_do_not_collapse(self) -> None:
        recipe = Recipe("vtr", (StepSpec("odin3-flow"),))
        one = RunSpec(Design("one", (self.src,), "top"), "EArch", recipe, {"seed": 1})
        two = RunSpec(Design("two", (self.src,), "top"), "EArch", recipe, {"seed": 1})
        k1, k2 = run_key(one, None, VERSIONS, ARGV), run_key(two, None, VERSIONS, ARGV)
        self.assertNotEqual(k1, k2)
        store = Store(self.root / "wyrd.db")
        for key, spec in ((k1, one), (k2, two)):
            store.begin(key, spec, run_dir(self.root, spec, key))
            store.finish(key, "ok")
        self.assertEqual(sorted(str(r["design"]) for r in store.rows()), ["one", "two"])
        other_arch = RunSpec(one.design, "Other", recipe, {"seed": 1})
        other_recipe = RunSpec(one.design, "EArch", Recipe("x", recipe.steps), {"seed": 1})
        self.assertNotEqual(k1, run_key(other_arch, None, VERSIONS, ARGV))
        self.assertNotEqual(k1, run_key(other_recipe, None, VERSIONS, ARGV))

    def test_key_rejects_bad_param(self) -> None:
        spec = make_spec(self.src, {"seed": {1}})
        with self.assertRaisesRegex(TypeError, "seed"):
            run_key(spec, None, VERSIONS, ARGV)

    def test_key_path_and_tuple_params(self) -> None:
        a = make_spec(self.src, {"p": Path("x"), "t": (1, 2)})
        b = make_spec(self.src, {"p": "x", "t": [1, 2]})
        self.assertEqual(run_key(a, None, VERSIONS, ARGV), run_key(b, None, VERSIONS, ARGV))

    def test_run_dir_layout(self) -> None:
        spec = make_spec(self.src)
        key = "0123456789abcdef" * 4
        self.assertEqual(
            run_dir(self.root, spec, key), self.root / "runs" / "d" / "EArch" / "0123456789ab"
        )


class StoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.spec = make_spec(self.root / "a.v")
        self.store = Store(self.root / "wyrd.db")

    def test_store_roundtrip(self) -> None:
        self.assertIsNone(self.store.status("k1"))
        self.store.begin("k1", self.spec, self.root / "r")
        self.assertEqual(self.store.status("k1"), "running")
        self.store.add_step("k1", 1, "odin3-flow", ["odin3-flow", "a.v"], 0, 1.5, 100)
        self.store.add_metrics("k1", "odin3-flow", [Metric("luts", 12.0, "")])
        self.store.finish("k1", "ok")
        self.assertEqual(self.store.status("k1"), "ok")
        rows = self.store.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["luts"], 12.0)
        self.assertEqual(rows[0]["design"], "d")
        self.assertEqual(rows[0]["status"], "ok")

    def test_user_version(self) -> None:
        with closing(sqlite3.connect(self.root / "wyrd.db")) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_peak_mem_max(self) -> None:
        self.assertIsNone(self.store.peak_mem("d", "EArch", "odin3-flow"))
        for key, peak in (("k1", 100), ("k2", 300), ("k3", 200)):
            self.store.begin(key, self.spec, self.root / key)
            self.store.add_step(key, 1, "odin3-flow", [], 0, 1.0, peak)
        self.assertEqual(self.store.peak_mem("d", "EArch", "odin3-flow"), 300)
        self.assertIsNone(self.store.peak_mem("d", "EArch", "vpr"))

    def test_begin_clears_stale_rows(self) -> None:
        self.store.begin("k1", self.spec, self.root / "r")
        self.store.add_step("k1", 1, "odin3-flow", [], 0, 1.0, 10)
        self.store.add_metrics("k1", "odin3-flow", [Metric("luts", 1.0, "")])
        self.store.begin("k1", self.spec, self.root / "r")
        self.assertEqual(self.store.peak_mem("d", "EArch", "odin3-flow"), None)
        with closing(sqlite3.connect(self.root / "wyrd.db")) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM steps").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0], 0)

    def test_begin_rejects_bad_param(self) -> None:
        spec = make_spec(self.root / "a.v", {"seed": object()})
        with self.assertRaisesRegex(TypeError, "seed"):
            self.store.begin("k1", spec, self.root / "r")

    def test_begin_params_normalised(self) -> None:
        spec = make_spec(self.root / "a.v", {"p": Path("x"), "t": (1, "a"), "n": None})
        self.store.begin("k1", spec, self.root / "r")
        with closing(sqlite3.connect(self.root / "wyrd.db")) as conn:
            text = conn.execute("SELECT params FROM runs").fetchone()[0]
        self.assertEqual(json.loads(text), {"p": "x", "t": [1, "a"], "n": None})

    def test_wal_enabled(self) -> None:
        with closing(sqlite3.connect(self.root / "wyrd.db")) as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_rows_metric_name_clash_and_later_step_wins(self) -> None:
        self.store.begin("k1", self.spec, self.root / "r")
        self.store.add_step("k1", 1, "a", [], 0, 1.0, None)
        self.store.add_step("k1", 2, "b", [], 0, 1.0, None)
        # inserted out of order: step b (n=2) first, then a (n=1)
        self.store.add_metrics("k1", "b", [Metric("luts", 2.0, ""), Metric("status", 5.0, "")])
        self.store.add_metrics("k1", "a", [Metric("luts", 1.0, "")])
        row = self.store.rows()[0]
        self.assertEqual(row["luts"], 2.0)
        self.assertEqual(row["status"], "running")
        self.assertEqual(row["metric.status"], 5.0)

    def test_finish_validates(self) -> None:
        self.store.begin("k1", self.spec, self.root / "r")
        with self.assertRaises(ValueError):
            self.store.finish("k1", "bogus")
        with self.assertRaises(KeyError):
            self.store.finish("nope", "ok")
        self.store.finish("k1", "cancelled")
        self.assertEqual(self.store.status("k1"), "cancelled")


if __name__ == "__main__":
    unittest.main()
