"""o3viz: BLIF and VPR file readers, exporter, anchors, server and CLI on a tiny fixture run."""

from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from wyrd import cli
from wyrd.o3viz import anchors, blif, export, serve, vprfiles

DATA = Path(__file__).resolve().parent / "data" / "o3viz"
FLOW = DATA / "flow"


def run_export(out: Path) -> dict[str, Any]:
    return export.export_bundle(FLOW, out, "test:t", [DATA / "src"])


class TestReaders(unittest.TestCase):
    def test_blif_levels_fanout_edges(self) -> None:
        nl = blif.read_blif(FLOW / "odin3" / "t.blif")
        lv = nl.levels()
        self.assertEqual([lv[n] for n in ("hl1", "hq", "hl2", "y")], [1, 0, 1, 2])
        self.assertEqual(nl.fanout()["a"], 2)
        self.assertEqual(nl.fanout()["hq"], 1)
        self.assertIn(("hl1", "hq", "latch"), nl.edges())

    def test_blif_continuation_and_comments(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.blif"
            p.write_text(".names a \\\n b c  # note\n11 1\n.subckt ram addr[0]=a out=o\n")
            nl = blif.read_blif(p)
        self.assertEqual(nl.inputs["c"], ["a", "b"])
        self.assertEqual(nl.drivers["o"], "subckt")

    def test_place_net_timing(self) -> None:
        pl = vprfiles.read_place(FLOW / "vpr" / "run" / "t.place")
        self.assertEqual(pl.grid, (3, 3))
        self.assertEqual(pl.xy["hl2"], (2, 1, 0))
        cl = vprfiles.read_net(FLOW / "vpr" / "run" / "t.net")
        self.assertEqual([c.kind for c in cl], ["clb", "clb", "io"])
        self.assertEqual(cl[0].atoms, ["hl1", "hq"])
        tm = vprfiles.read_setup_report(FLOW / "vpr" / "run" / "report_timing.setup.rpt")
        self.assertEqual(tm.paths, 2)
        self.assertEqual(tm.worst_slack["hl2"], -0.5)
        self.assertEqual(tm.npaths["hl1"], 1)


class TestPathsAndDepth(unittest.TestCase):
    def test_setup_paths_in_order_without_clock_network(self) -> None:
        ps = vprfiles.read_setup_paths(FLOW / "vpr" / "run" / "report_timing.setup.rpt")
        self.assertEqual([p.n for p in ps], [1, 2])
        self.assertEqual(ps[0].atoms, ["hq", "hl2", "out:y"])
        self.assertEqual((ps[0].start, ps[0].end), ("hq.Q[0]", "out:y.outpad[0]"))
        self.assertEqual(ps[0].slack, -0.5)
        self.assertEqual(ps[1].atoms, ["hl1"])

    def test_real_report_shape_skips_capture_clock(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            rpt = Path(d) / "r.rpt"
            rpt.write_text(
                "#Path 1\nStartpoint: a.Q[0] (.latch clocked by clk)\n"
                "Endpoint  : b.D[0] (.latch clocked by clk)\n"
                "clock clk (rise edge)   0 0\nclock source latency   0 0\n"
                "clk.inpad[0] (.input)   0 0\na.clk[0] (.latch)   0 0\n"
                "a.Q[0] (.latch) [clock-to-output]   0 0\nx.in[0] (.names)   0 0\n"
                "x.out[0] (.names)   0 0\nb.D[0] (.latch)   0 0\n"
                "data arrival time   1\n\nclock clk (rise edge)  0 0\n"
                "clk.inpad[0] (.input)   0 0\nb.clk[0] (.latch)   0 0\n"
                "slack (MET)    2.5\n"
            )
            (p,) = vprfiles.read_setup_paths(rpt)
        self.assertEqual(p.atoms, ["a", "x", "b"])
        self.assertEqual(p.slack, 2.5)

    def test_bundle_paths_json(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "b.o3viz"
            man = run_export(out)
            self.assertEqual(man["paths"], 2)
            pj = json.loads((out / "paths.json").read_text())
            self.assertEqual(pj["source"], "vpr report_timing.setup.rpt")
            first = pj["paths"][0]
            self.assertEqual(first["slack"], -0.5)
            self.assertEqual(first["lut"], ["luts:t/hq", "luts:t/hl2"])
            self.assertEqual(first["placed"], ["placed:hq", "placed:hl2", "placed:out:y"])

    def test_depth_on_every_plane(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "b.o3viz"
            man = run_export(out)
            m = next(x for x in man["metrics"] if x["name"] == "logic_level")
            self.assertEqual(m["planes"], ["hdl", "lut", "clb", "placed"])
            pl = {
                p: json.loads((out / "planes" / f"{p}.json").read_text())
                for p in ("hdl", "lut", "clb", "placed")
            }

            def lv(p: str, oid: str) -> float | None:
                val: float | None = pl[p]["metrics"]["logic_level"][pl[p]["ids"].index(oid)]
                return val

            # cluster 1 holds hl1 (level 1) and hq (level 0): max is 1
            self.assertEqual(
                lv("clb", "clb:" + vprfiles.read_net(FLOW / "vpr/run/t.net")[0].name), 1.0
            )
            self.assertEqual(lv("placed", "placed:hl2"), 1.0)
            lut_lv = dict(zip(pl["lut"]["ids"], pl["lut"]["metrics"]["logic_level"], strict=True))
            rows = json.loads((out / "links.json").read_text())["rows"]
            order = [i for p in ("hdl", "lut", "clb", "placed") for i in pl[p]["ids"]]
            for h in pl["hdl"]["ids"]:
                below = [
                    lut_lv[order[b]]
                    for a, b, _k, _c in rows
                    if order[a] == h and lut_lv.get(order[b]) is not None
                ]
                self.assertEqual(lv("hdl", h), float(max(below)) if below else None, h)
            # an I/O cluster has no measured depth: null, never a made-up zero
            io = [c for c in vprfiles.read_net(FLOW / "vpr/run/t.net") if c.kind == "io"][0]
            self.assertIsNone(lv("clb", "clb:" + io.name))


class TestAnchors(unittest.TestCase):
    def test_spread_inside_tile(self) -> None:
        pos = anchors.tile_spread({(2, 3): ["b", "a", "c"]})
        self.assertEqual(set(pos), {"a", "b", "c"})
        for x, y in pos.values():
            self.assertTrue(1.6 <= x <= 2.4 and 2.6 <= y <= 3.4)

    def test_centroid_and_fallback(self) -> None:
        pos, un = anchors.placement_anchor(
            ["top", "bot"],
            {"top": ["u", "v", "w"], "bot": ["a", "b"]},
            [("u", "a"), ("u", "b")],
            {"a": (0.0, 0.0), "b": (2.0, 2.0)},
            (5.0, 5.0),
            fallback={"v": (1.0, 1.0)},
        )
        self.assertEqual(pos["top"]["u"], (1.0, 1.0))
        self.assertEqual(pos["top"]["v"], (1.0, 1.0))
        self.assertEqual(pos["top"]["w"], (5.0, 5.0))
        self.assertEqual(un, ["w"])


class TestAnchorsM2(unittest.TestCase):
    def test_tidy_tree(self) -> None:
        ids = ["r", "a", "b", "c"]
        pos = anchors.tidy_tree(ids, {"a": "r", "b": "r", "c": "a"})
        self.assertEqual(pos["r"][1], 0.0)
        self.assertLess(pos["c"][1], pos["a"][1])
        self.assertEqual(pos["r"][0], (pos["c"][0] + pos["b"][0]) / 2)

    def test_column_layout_orders_by_key(self) -> None:
        pos = anchors.column_layout({"a": 0, "b": 0, "c": 1}, {"a": 2.0, "b": -1.0})
        self.assertLess(pos["b"][0] + pos["b"][1], pos["a"][0] + pos["a"][1])
        self.assertGreater(pos["c"][0], pos["a"][0])

    def test_strip_moves_only_unanchored(self) -> None:
        pos = {"p": {"a": (1.0, 1.0), "b": (3.0, 3.0), "z": (2.0, 2.0)}}
        out = anchors.strip_unanchored(pos, ["z"])
        self.assertEqual(out["p"]["a"], (1.0, 1.0))
        self.assertLess(out["p"]["z"][1], 1.0)

    def test_top_down_takes_deepest_ancestor(self) -> None:
        pos, un = anchors.top_down_anchor(
            ["h", "l"],
            {"h": ["root", "leaf"], "l": ["x", "y"]},
            [("root", "x"), ("leaf", "x"), ("root", "y")],
            {"root": (0.0, 0.0), "leaf": (4.0, -2.0)},
            "h",
            {"root": 0, "leaf": 2},
            (9.0, 9.0),
        )
        self.assertEqual(un, [])
        self.assertTrue(abs(pos["l"]["x"][0] - 4.0) <= 0.45)
        self.assertTrue(abs(pos["l"]["y"][0]) <= 0.45)


class TestExport(unittest.TestCase):
    def test_circuit_columns_and_clusters(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "b.o3viz"
            man = run_export(out)
            lut = json.loads((out / "planes" / "lut.json").read_text())
            at = {i: k for k, i in enumerate(lut["ids"])}
            m = lut["metrics"]
            hq = at["luts:t/hq"]
            self.assertEqual(m["logic_level"][at["luts:t/hl2"]], 1.0)
            self.assertEqual(m["seq_level"][at["luts:t/hq"]], 1.0)
            self.assertEqual(m["is_latched"][at["luts:t/hl1"]], 1.0)
            self.assertIsNone(m["is_po"][at["luts:t/hl2"]])
            self.assertEqual(m["logic_level"][hq], 0.0)
            cl = json.loads((out / "clusters.json").read_text())
            self.assertIn("mincut", cl["sources"])
            for src in cl["sources"].values():
                self.assertEqual(len(src["of"]), len(lut["ids"]))
                k = src["k"]
                self.assertEqual(len(src["comb"]), k)
                self.assertEqual(
                    sum(map(sum, src["comb"])) + sum(map(sum, src["latched"])), src["edges"]
                )
            self.assertEqual(man["circuit"]["sources"], cl["order"])
            kund = json.loads((out / "anchors" / "kundarewich-mincut.json").read_text())
            self.assertFalse(kund["ff_attached"])

    def test_four_anchors_cover_every_object(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "b.o3viz"
            man = run_export(out)
            for name in ("ast", "level", "pipeline", "placement", "hutton", "hutton_seq"):
                self.assertIn(name, man["anchors"])
            for a in list(man["anchors"]):
                anc = json.loads((out / "anchors" / f"{a}.json").read_text())
                self.assertEqual(len(anc["bounds"]), 4)
                for p in list(man["planes"]):
                    ids = json.loads((out / "planes" / f"{p}.json").read_text())["ids"]
                    self.assertEqual(sorted(anc["pos"][p]), sorted(ids), f"{a}/{p}")

    def test_stage_metric(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "b.o3viz"
            run_export(out)
            lut = json.loads((out / "planes" / "lut.json").read_text())
            self.assertEqual(lut["metrics"]["stage"][lut["ids"].index("luts:t/hq")], 1.0)
            self.assertEqual(lut["metrics"]["stage"][lut["ids"].index("luts:t/hl2")], 1.0)
            self.assertEqual(lut["metrics"]["stage"][lut["ids"].index("luts:t/hl1")], 0.0)

    def test_bundle_schema(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "b.o3viz"
            man = run_export(out)
            self.assertEqual(man["planes"], ["hdl", "lut", "clb", "placed"])
            self.assertEqual(json.loads((out / "manifest.json").read_text()), man)
            for p in ("hdl", "lut", "clb", "placed"):
                pl = json.loads((out / "planes" / f"{p}.json").read_text())
                n = len(pl["ids"])
                for col in ("kind", "type", "origin", "name", "src"):
                    self.assertEqual(len(pl[col]), n)
                for vals in pl["metrics"].values():
                    self.assertEqual(len(vals), n)
            self.assertTrue((out / "hdl" / "t.v").is_file())
            self.assertIn("t.v", json.loads((out / "manifest.json").read_text())["inputs"])

    def test_metrics_values(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "b.o3viz"
            run_export(out)
            lut = json.loads((out / "planes" / "lut.json").read_text())
            i = lut["ids"].index("luts:t/hl2")
            self.assertEqual(lut["metrics"]["logic_level"][i], 1.0)
            self.assertEqual(lut["metrics"]["slack_worst"][i], -0.5)
            self.assertEqual(lut["metrics"]["weakest_confidence"][i], 2.0)
            j = lut["ids"].index("luts:t/hq")
            self.assertEqual(lut["metrics"]["logic_level"][j], 0.0)

    def test_bottom_plane_is_vpr_grid_and_all_placed(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "b.o3viz"
            run_export(out)
            anc = json.loads((out / "anchors" / "placement.json").read_text())
            placed = json.loads((out / "planes" / "placed.json").read_text())
            for pid, (x, y) in anc["pos"]["placed"].items():
                if pid == "placed:hl2":
                    self.assertTrue(abs(x - 2) <= 0.4 and abs(y - 1) <= 0.4)
            for p, ids in anc["pos"].items():
                self.assertEqual(
                    len(ids), len(json.loads((out / "planes" / f"{p}.json").read_text())["ids"])
                )
            self.assertEqual(len(anc["pos"]["placed"]), len(placed["ids"]))

    def test_every_linked_object_has_position(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "b.o3viz"
            run_export(out)
            anc = json.loads((out / "anchors" / "placement.json").read_text())["pos"]
            have = {i for plane in anc.values() for i in plane}
            order = [
                i
                for p in ("hdl", "lut", "clb", "placed")
                for i in json.loads((out / "planes" / f"{p}.json").read_text())["ids"]
            ]
            rows = json.loads((out / "links.json").read_text())["rows"]
            self.assertTrue(rows)
            for a, b, _k, _c in rows:
                self.assertIn(order[a], have)
                self.assertIn(order[b], have)

    def test_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a", Path(d) / "b"
            run_export(a)
            run_export(b)
            names = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
            self.assertEqual(names, sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file()))
            for n in names:
                self.assertEqual((a / n).read_bytes(), (b / n).read_bytes(), str(n))

    def test_missing_prov_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as d, self.assertRaises(export.ExportError):
            export.export_bundle(Path(d), Path(d) / "o", "x", [])

    def test_no_home_path_in_bundle(self) -> None:
        needle = "/home" + "/"
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "b.o3viz"
            run_export(out)
            for p in out.rglob("*"):
                if p.is_file():
                    self.assertNotIn(needle, p.read_text(encoding="utf-8"), str(p))


class TestServeAndCli(unittest.TestCase):
    def test_serve_viewer_and_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "b.o3viz"
            run_export(out)
            srv = serve.make_server(out, 0)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{srv.server_address[1]}"
            try:
                man = json.loads(urllib.request.urlopen(base + "/bundle/manifest.json").read())
                self.assertEqual(man["benchmark"], "test:t")
                self.assertIn(b"o3viz", urllib.request.urlopen(base + "/").read())
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(base + "/bundle/../../etc/passwd")
            finally:
                srv.shutdown()
                srv.server_close()

    def test_cli_export_and_serve_errors(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "b.o3viz"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli.main(
                    ["viz", "export", str(FLOW), "--out", str(out), "--src", str(DATA / "src")]
                )
            self.assertEqual(rc, 0)
            self.assertIn("planes hdl 3, lut 3, clb 3, placed 4", buf.getvalue())
            with redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(["viz", "serve", d]), 2)
                self.assertEqual(cli.main(["viz", "export", d, "--out", str(Path(d) / "x")]), 2)


if __name__ == "__main__":
    unittest.main()
