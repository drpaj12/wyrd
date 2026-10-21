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


if __name__ == "__main__":
    unittest.main()
