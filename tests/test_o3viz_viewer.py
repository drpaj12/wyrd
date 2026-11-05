"""o3viz viewer: vendored files are complete; headless smoke when Playwright and Chromium exist."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from wyrd.o3viz import export, serve

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests" / "data" / "o3viz"


class TestVendored(unittest.TestCase):
    def test_vendor_files_and_licence(self) -> None:
        v = serve.WEB / "vendor"
        for name in ("three.module.min.js", "OrbitControls.js", "three.LICENSE", "VERSIONS.txt"):
            self.assertTrue((v / name).is_file(), name)
        self.assertIn("MIT", (v / "three.LICENSE").read_text())

    def test_no_cdn_references(self) -> None:
        for name in ("index.html", "app.js"):
            text = (serve.WEB / name).read_text()
            self.assertNotIn("http://", text.replace("http://127", ""))
            self.assertNotIn("https://", text)


@unittest.skipUnless(shutil.which("node"), "needs node")
class TestExprJs(unittest.TestCase):
    def test_expression_language(self) -> None:
        r = subprocess.run(
            [
                "node",
                "--test",
                str(ROOT / "tests" / "js" / "expr.test.mjs"),
                str(ROOT / "tests" / "js" / "stats.test.mjs"),
                str(ROOT / "tests" / "js" / "select.test.mjs"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 0, r.stdout[-2000:])


@unittest.skipUnless(importlib.util.find_spec("playwright"), "needs playwright and chromium")
class TestSmoke(unittest.TestCase):
    def test_loads_without_console_errors(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "o3viz_shot", ROOT / "tools" / "o3viz_shot.py"
        )
        assert spec is not None and spec.loader is not None
        o3viz_shot = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(o3viz_shot)

        with tempfile.TemporaryDirectory() as d:
            bundle = Path(d) / "b.o3viz"
            export.export_bundle(DATA / "flow", bundle, "test:t", [DATA / "src"])
            shot = Path(d) / "s.png"
            errors = o3viz_shot.shoot(
                bundle,
                shot,
                "logic_level",
                "placed:hl2",
                evals=[
                    "window.__o3viz.addExpr('twice', 'fanout * 2')",
                    "window.__o3viz.addAgg('fanout', 'below', 'max')",
                    "window.__o3viz.setHeight('twice')",
                    "window.__o3viz.setAnchor('ast')",
                    "window.__o3viz.setAnchor('level')",
                    "window.__o3viz.setAnchor('pipeline')",
                    "window.__o3viz.setGroupMode('cluster')",
                    "window.__o3viz.setEdges('groups')",
                    "window.__o3viz.setGroupMode('')",
                    "window.__o3viz.setEdges('khop', 2)",
                    "window.__o3viz.setMorph('lut', 'clb', 0.5)",
                    "window.__o3viz.setView('placed')",
                    "window.__o3viz.discover()",
                    "window.__o3viz.brushAll('lut')",
                    "window.__o3viz.setView('stack')",
                ],
            )
            self.assertEqual(errors, [])
            self.assertGreater(shot.stat().st_size, 5000)

    def test_line_selection_paths_cone_depth(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "o3viz_shot", ROOT / "tools" / "o3viz_shot.py"
        )
        assert spec is not None and spec.loader is not None
        o3viz_shot = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(o3viz_shot)
        with tempfile.TemporaryDirectory() as d:
            bundle = Path(d) / "b.o3viz"
            export.export_bundle(DATA / "flow", bundle, "test:t", [DATA / "src"])
            out: list[Any] = []
            errors = o3viz_shot.shoot(
                bundle,
                Path(d) / "s.png",
                "",
                "",
                evals=[
                    # line 3 of t.v is `always @(posedge clk) q <= a & b;`
                    "window.__o3viz.selectLines('t.v', 3, 3)",
                    "window.__o3viz.planeCounts()",
                    "window.__o3viz.marksOf()",
                    "document.querySelectorAll('#srclines .ln').length",
                    "window.__o3viz.selectLines('t.v', 99, 99)",
                    "window.__o3viz.planeCounts()",
                    "window.__o3viz.showPath(0)",
                    "window.__o3viz.planeCounts()",
                    "window.__o3viz.S.mode.type",
                    "window.__o3viz.select('luts:t/hl2')",
                    "window.__o3viz.setCone('in', 3)",
                    "[...window.__o3viz.S.cone.nodes.keys()].sort()",
                    "window.__o3viz.setCone('in', 1)",
                    "[...window.__o3viz.S.cone.nodes.keys()].sort()",
                    "window.__o3viz.coverage('logic_level').map(c => c.measured)",
                    "window.__o3viz.focusPlane('placed')",
                    "window.__o3viz.S.focus",
                    "window.__o3viz.soloPlane('lut')",
                    "Object.values(window.__o3viz.S.vis)",
                ],
                results=out,
            )
            self.assertEqual(errors, [])
        self.assertEqual(out[0:1], [None])
        self.assertGreaterEqual(out[1]["hdl"], 1)
        self.assertGreaterEqual(out[1]["lut"], 1)
        self.assertIn("3", out[2]["t.v"])
        self.assertEqual(out[3], 5)  # five source lines
        self.assertEqual(out[5], {"hdl": 0, "lut": 0, "clb": 0, "placed": 0})
        self.assertEqual(out[7]["lut"], 2)  # path 1: hq, hl2
        self.assertEqual(out[8], "path")
        self.assertIn("luts:t/hl2", out[11])
        self.assertIn("luts:t/hq", out[11])  # fan-in reaches the flip-flop output and stops
        self.assertNotIn("luts:t/hl1", out[11])
        self.assertIn("luts:t/hq", out[13])
        self.assertEqual(out[16], "placed")
        self.assertEqual(out[18], [False, True, False, False])


if __name__ == "__main__":
    unittest.main()
