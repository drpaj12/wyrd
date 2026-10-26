"""Schematic back end (Qt-free). Fixtures: tests/data/schematic (Odin III write_json output)."""

import copy
import json
import stat
import tempfile
import unittest
from pathlib import Path
from typing import Any

from wyrd import schematic as sch

DATA = Path(__file__).parent / "data" / "schematic"
SRC = "bm_dag2_mod.v"


def fake_tool(directory: Path, fail: bool = False) -> sch.Tools:
    """A netlistsvg stand-in (a shell script) that copies the fixture SVG to the -o file."""
    script = directory / "netlistsvg"
    body = "exit 3" if fail else f'cp "{DATA / "mux.svg"}" "$3"'
    script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return sch.Tools(script, Path("/bin/sh"))


def modules_of(view: sch.Netlist) -> dict[str, Any]:
    mods = view["modules"]
    assert isinstance(mods, dict)
    return mods


class NetlistTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mux = sch.load_netlist(DATA / "mux.json")
        self.dag = sch.load_netlist(DATA / "dag2.json")

    def test_modules_top_first(self) -> None:
        mods = sch.modules(self.dag)
        self.assertEqual([m.name for m in mods][0], "bm_dag2_mod")
        self.assertTrue(mods[0].top)
        self.assertEqual(len(mods), 3)

    def test_module_view_makes_it_top(self) -> None:
        view = sch.module_view(self.dag, "a")
        self.assertEqual(list(modules_of(view)), ["a"])
        self.assertEqual(sch.modules(view)[0].name, "a")
        self.assertTrue(sch.modules(view)[0].top)

    def test_too_large(self) -> None:
        with self.assertRaises(sch.TooLarge) as cm:
            sch.module_view(self.dag, "bm_dag2_mod", max_cells=3)
        self.assertEqual((cm.exception.cells, cm.exception.limit), (6, 3))
        self.assertIn("fan-in cone", str(cm.exception))

    def test_unknown_module(self) -> None:
        with self.assertRaises(sch.SchematicError):
            sch.module_view(self.dag, "nope")

    def test_bad_file(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            bad = Path(t) / "x.json"
            bad.write_text("{}", encoding="utf-8")
            with self.assertRaises(sch.SchematicError):
                sch.load_netlist(bad)
            bad.write_text("not json", encoding="utf-8")
            with self.assertRaises(sch.SchematicError):
                sch.load_netlist(bad)
            with self.assertRaises(sch.SchematicError):
                sch.load_netlist(Path(t) / "missing.json")
            bad.write_text("[" * 200000, encoding="utf-8")
            with self.assertRaises(sch.SchematicError):
                sch.load_netlist(bad)


class ConeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dag = sch.load_netlist(DATA / "dag2.json")
        self.mod = sch._module(self.dag, "bm_dag2_mod")

    def test_seeds_of_net(self) -> None:
        self.assertEqual(sch.seeds_of_net(self.mod, "out0"), ["$c14"])

    def test_input_net_has_no_driver(self) -> None:
        with self.assertRaises(sch.SchematicError):
            sch.seeds_of_net(self.mod, "a_in")
        with self.assertRaises(sch.SchematicError):
            sch.seeds_of_net(self.mod, "nonet")

    def test_seeds_of_line(self) -> None:
        self.assertEqual(sch.seeds_of_line(self.mod, SRC, 33), ["top_a"])
        self.assertEqual(sch.seeds_of_line(self.mod, SRC, 37), ["$c14", "$c15"])
        with self.assertRaises(sch.SchematicError):
            sch.seeds_of_line(self.mod, SRC, 1)
        with self.assertRaises(sch.SchematicError):
            sch.seeds_of_line(self.mod, "other.v", 33)

    def test_cone_is_smaller_and_closed(self) -> None:
        view, cut = sch.cone_view(self.dag, "bm_dag2_mod", ["$c14"])
        self.assertFalse(cut)
        sub = modules_of(view)["bm_dag2_mod"]
        self.assertEqual(sorted(sub["cells"]), ["$c11", "$c14", "top_a", "top_b"])
        self.assertEqual(sub["attributes"]["top"], 1)
        outs = [n for n, p in sub["ports"].items() if p["direction"] == "output"]
        self.assertEqual(outs, ["out0[0]", "out0[1]"])
        made = {b for c in sub["cells"].values() for b in sch._split(c)[1]}
        ins = [p["bits"][0] for p in sub["ports"].values() if p["direction"] == "input"]
        self.assertFalse(set(ins) & made)

    def test_seeds_of_line_matches_on_path_boundary(self) -> None:
        mod: sch.Module = {
            "cells": {
                "c1": {"attributes": {"src": "dir/data.v:5.1-5.9"}},
                "c2": {"attributes": {"src": "a.v:5.1-5.9"}},
            }
        }
        self.assertEqual(sch.seeds_of_line(mod, "a.v", 5), ["c2"])
        self.assertEqual(sch.seeds_of_line(mod, "data.v", 5), ["c1"])
        self.assertEqual(sch.seeds_of_line(mod, "dir/data.v", 5), ["c1"])

    def test_inout_is_input_and_output(self) -> None:
        cell = {"port_directions": {"IO": "inout", "A": "input"}, "connections": {"IO": [3], "A": [4]}}
        self.assertEqual(sch._split(cell), ([3, 4], [3]))

    def test_seeds_beyond_limit_dropped_and_flagged(self) -> None:
        view, cut = sch.cone_view(self.dag, "bm_dag2_mod", ["$c14", "$c15"], max_cells=1)
        self.assertTrue(cut)
        sub = modules_of(view)["bm_dag2_mod"]
        self.assertEqual(list(sub["cells"]), ["$c14"])
        made = {b for c in sub["cells"].values() for b in sch._split(c)[1]}
        outs = [p["bits"][0] for p in sub["ports"].values() if p["direction"] == "output"]
        self.assertTrue(outs)
        self.assertTrue(set(outs) <= made)

    def test_views_do_not_mutate_the_netlist(self) -> None:
        before = copy.deepcopy(self.dag)
        sch.module_view(self.dag, "bm_dag2_mod")
        sch.module_view(self.dag, "a")
        sch.cone_view(self.dag, "bm_dag2_mod", ["$c14", "$c15"])
        sch.cone_view(self.dag, "bm_dag2_mod", ["$c14", "$c15"], max_cells=2)
        sch._wrap(self.dag, "a", sch._module(self.dag, "a"))
        self.assertEqual(self.dag, before)

    def test_cone_cut(self) -> None:
        view, cut = sch.cone_view(self.dag, "bm_dag2_mod", ["$c14", "$c15"], max_cells=2)
        self.assertTrue(cut)
        self.assertLessEqual(sch.count_cells(view), 2)

    def test_cone_json_roundtrips(self) -> None:
        view, _ = sch.cone_view(self.dag, "bm_dag2_mod", ["top_a"])
        self.assertEqual(json.loads(json.dumps(view)), view)


class RenderTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.mux = sch.load_netlist(DATA / "mux.json")

    def test_without_tool(self) -> None:
        with self.assertRaises(sch.ToolMissing) as cm:
            sch.render(self.mux, self.dir / "o.svg", None, self.dir)
        self.assertIn("npm install netlistsvg", str(cm.exception))

    def test_fake_tool(self) -> None:
        out = self.dir / "o.svg"
        sch.render(self.mux, out, fake_tool(self.dir), self.dir)
        self.assertTrue(out.read_text(encoding="utf-8").startswith("<svg"))
        self.assertEqual(json.loads((self.dir / "o.json").read_text()), self.mux)

    def test_tool_failure(self) -> None:
        with self.assertRaises(sch.SchematicError) as cm:
            sch.render(self.mux, self.dir / "o.svg", fake_tool(self.dir, fail=True), self.dir)
        self.assertIn("exit 3", str(cm.exception))

    def test_find_tools(self) -> None:
        self.assertIsNone(sch.find_tools({"PATH": str(self.dir)}))
        tool = fake_tool(self.dir)
        env = {"WYRD_NETLISTSVG": str(tool.netlistsvg), "WYRD_NODE": "/bin/sh"}
        found = sch.find_tools(env)
        assert found is not None
        self.assertEqual(found.netlistsvg, tool.netlistsvg.resolve())
        self.assertEqual(found.node, Path("/bin/sh").resolve())

    def test_find_tools_rejects_windows_and_non_executable(self) -> None:
        tool = fake_tool(self.dir)
        win = {"PATH": "/mnt/c/Program Files/nodejs", "WYRD_NETLISTSVG": str(tool.netlistsvg)}
        self.assertIsNone(sch.find_tools(win))
        for bad in ("/mnt/c/x/node", str(self.dir / "node.exe"), str(self.dir / "n.cmd")):
            env = {"WYRD_NETLISTSVG": str(tool.netlistsvg), "WYRD_NODE": bad}
            self.assertIsNone(sch.find_tools(env))
        plain = self.dir / "plain"
        plain.write_text("x", encoding="utf-8")
        plain.chmod(0o644)
        env = {"WYRD_NETLISTSVG": str(plain), "WYRD_NODE": "/bin/sh"}
        self.assertIsNone(sch.find_tools(env))

    def test_runs_found_node(self) -> None:
        """The node program is argv[0]; the script need not be executable or have a shebang."""
        script = self.dir / "nsvg.js"
        script.write_text(f'cp "{DATA / "mux.svg"}" "$3"\n', encoding="utf-8")
        out = self.dir / "o.svg"
        sch.render(self.mux, out, sch.Tools(script, Path("/bin/sh")), self.dir)
        self.assertTrue(out.is_file())

    def test_write_error_is_schematic_error(self) -> None:
        with self.assertRaises(sch.SchematicError):
            sch.render(self.mux, self.dir / "o.svg", fake_tool(self.dir), self.dir / "missing")

    def test_find_netlist(self) -> None:
        self.assertIsNone(sch.find_netlist(self.dir))
        (self.dir / "summary.json").write_text('{"modules": 1, "creator": 1}', encoding="utf-8")
        (self.dir / "other.json").write_text("{}", encoding="utf-8")
        out = self.dir / "step" / "out"
        out.mkdir(parents=True)
        (out / "a.json").write_bytes((DATA / "mux.json").read_bytes())
        self.assertEqual(sch.find_netlist(self.dir), out / "a.json")


@unittest.skipUnless(sch.find_tools(), "node and netlistsvg not installed")
class RealToolTest(unittest.TestCase):
    def test_micros_render(self) -> None:
        tools = sch.find_tools()
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            for name in ("mux", "dag2"):
                net = sch.load_netlist(DATA / f"{name}.json")
                out = tmp / f"{name}.svg"
                sch.render(sch.module_view(net, sch.modules(net)[0].name), out, tools, tmp)
                self.assertIn("<svg", out.read_text(encoding="utf-8")[:200])
            net = sch.load_netlist(DATA / "dag2.json")
            view, _ = sch.cone_view(net, "bm_dag2_mod", ["$c14"])
            sch.render(view, tmp / "cone.svg", tools, tmp)
            self.assertTrue((tmp / "cone.svg").stat().st_size > 500)


if __name__ == "__main__":
    unittest.main()
