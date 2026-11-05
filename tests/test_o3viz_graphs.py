"""Graph planes (STG, CFG, DDG): readers, joins, layouts, the SCOAP join and the dump script."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from wyrd.o3viz import cells, graphs, nets

SP = "d.v:"
HDL_IDS = ["hdl:m", "hdl:sw", "hdl:c1", "hdl:c2", "hdl:sig.state", "hdl:sig.a"]
HDL_SRC = [
    [["d.v", "1.1-9.4"]],
    [["d.v", "3.1-8.5"]],
    [["d.v", "4.2-5.9"]],
    [["d.v", "6.2-7.9"]],
    [["d.v", "2.1-2.10"]],
    [["d.v", "2.12-2.20"]],
]


def cell_data() -> cells.CellData:
    cd = cells.CellData()
    cd.ids = ["cell:eq1", "cell:eq2", "cell:mux", "cell:ff"]
    cd.types = ["$eq", "$eq", "$pmux", "$dff"]
    cd.src = [
        [["d.v", "3.1-8.5"]],
        [["d.v", "3.1-8.5"]],
        [["d.v", "3.1-8.5"]],
        [["d.v", "1.1-9.4"]],
    ]
    cd.consts = {"cell:eq1": 0, "cell:eq2": 1}
    cd.bus = {"cell:ff": ("state", None, "own")}
    cd.ff = {"cell:ff"}
    return cd


def cfg_doc() -> dict[str, object]:
    nodes = [
        {
            "id": "p/entry",
            "kind": "entry",
            "label": "process",
            "src": [SP + "1.1-9.4"],
            "actions": [],
        },
        {"id": "p/sw0", "kind": "switch", "label": "switch \\state", "src": [SP + "3.1-8.5"]},
        {
            "id": "p/c1",
            "kind": "case",
            "label": "case 1'0",
            "compares": ["1'0"],
            "src": [SP + "4.2-5.9"],
            "actions": [{"lhs": "a", "rhs": "b"}],
        },
        {
            "id": "p/c2",
            "kind": "case",
            "label": "case 1'1",
            "compares": ["1'1"],
            "src": [SP + "6.2-7.9"],
        },
        {"id": "p/j0", "kind": "join", "label": "join", "src": []},
        {"id": "p/exit", "kind": "exit", "label": "exit", "src": []},
    ]
    edges = [
        ("p/entry", "p/sw0", "seq"),
        ("p/sw0", "p/c1", "control"),
        ("p/sw0", "p/c2", "control"),
        ("p/c1", "p/j0", "seq"),
        ("p/c2", "p/j0", "seq"),
        ("p/j0", "p/exit", "seq"),
    ]
    return {
        "modules": [
            {
                "name": "m",
                "graphs": [
                    {
                        "id": "p",
                        "nodes": nodes,
                        "edges": [
                            {"id": f"e{k}", "from": a, "to": b, "kind": kd, "label": "", "src": []}
                            for k, (a, b, kd) in enumerate(edges)
                        ],
                    }
                ],
            }
        ]
    }


def stg_doc() -> dict[str, object]:
    nodes = [
        {"id": "f/s0", "kind": "state", "label": "00", "code": "00", "reset": True, "src": []},
        {"id": "f/s1", "kind": "state", "label": "01", "code": "01", "reset": False, "src": []},
        {"id": "f/s2", "kind": "state", "label": "10", "code": "10", "reset": False, "src": []},
    ]
    es = [
        ("f/s0", "f/s1", "go"),
        ("f/s1", "f/s2", "1"),
        ("f/s2", "f/s0", "!go"),
        ("f/s0", "f/s0", "!go"),
    ]
    return {
        "modules": [
            {
                "name": "m",
                "graphs": [
                    {
                        "id": "f",
                        "label": "m.state",
                        "src": [SP + "1.1-9.4"],
                        "select_nodes": [{"node": 1, "src": [SP + "3.1-8.5"]}],
                        "nodes": nodes,
                        "edges": [
                            {
                                "id": f"e{k}",
                                "from": a,
                                "to": b,
                                "kind": "transition",
                                "label": c,
                                "cond_expr": c,
                                "src": [],
                            }
                            for k, (a, b, c) in enumerate(es)
                        ],
                    }
                ],
            }
        ]
    }


def ddg_doc() -> dict[str, object]:
    nodes = [
        {"id": "w1", "kind": "signal", "label": "a", "width": 1, "port": "in", "src": []},
        {"id": "w2", "kind": "signal", "label": "state", "width": 2, "port": "", "src": []},
        {"id": "w3", "kind": "signal", "label": "y", "width": 1, "port": "out", "src": []},
        {"id": "n9", "kind": "temp", "label": "$n9", "src": []},
    ]
    es = [
        ("w1", "n9", "data", False),
        ("n9", "w2", "data", True),
        ("w2", "w3", "data", False),
        ("w1", "w3", "control", False),
        ("w2", "w2", "data", True),
    ]
    return {
        "modules": [
            {
                "name": "m",
                "graphs": [
                    {
                        "id": "ddg",
                        "nodes": nodes,
                        "edges": [
                            {
                                "id": f"e{k}",
                                "from": a,
                                "to": b,
                                "kind": kd,
                                "seq": sq,
                                "via": 5,
                                "op": "$dff",
                                "label": "",
                                "src": [SP + "4.2-5.9"],
                            }
                            for k, (a, b, kd, sq) in enumerate(es)
                        ],
                    }
                ],
            }
        ]
    }


SCOAP = [
    {"id": 1, "name": "a", "cc0": 1, "cc1": 1, "co": 3, "wire": 1, "driver": 0},
    {"id": 2, "name": "state[0]", "cc0": 2, "cc1": 5, "co": 4, "wire": 2, "driver": 7},
    {"id": 3, "name": "state[1]", "cc0": 3, "cc1": 4, "co": 6, "wire": 2, "driver": 7},
    {"id": 4, "name": "y", "cc0": 10**18, "cc1": 9, "co": 0, "wire": 3, "driver": 8},
    {"id": 9, "name": "$n9", "cc0": 4, "cc1": 4, "co": 4, "wire": 0, "driver": 8},
]


def build(scoap: list[dict[str, Any]] | None = None) -> dict[str, graphs.GraphData]:
    docs = {"cfg": cfg_doc(), "stg": stg_doc(), "ddg": ddg_doc()}
    return graphs.build_all(docs, "m", HDL_IDS, HDL_SRC, cell_data(), scoap or [])


class ReadTests(unittest.TestCase):
    def test_each_kind_is_read(self) -> None:
        gd = build()
        self.assertEqual(sorted(gd), ["cfg", "ddg", "stg"])
        self.assertEqual(len(gd["stg"].ids), 3)
        self.assertEqual(len(gd["stg"].edges), 4)
        self.assertEqual(len(gd["cfg"].ids), 6)
        self.assertEqual(len(gd["ddg"].ids), 4)
        self.assertEqual(gd["stg"].metrics["is_reset"]["stg:f/s0"], 1.0)
        self.assertEqual(gd["ddg"].metrics["is_ff"], {"ddg:w2": 1.0})

    def test_other_modules_are_left_out(self) -> None:
        self.assertEqual(
            graphs.build_all({"cfg": cfg_doc()}, "other", HDL_IDS, HDL_SRC, None, []), {}
        )

    def test_ids_carry_the_plane(self) -> None:
        gd = build()
        for kind, g in gd.items():
            self.assertTrue(all(i.startswith(kind + ":") for i in g.ids))
            self.assertTrue(all(e[0] in g.ids and e[1] in g.ids for e in g.edges))


class LinkTests(unittest.TestCase):
    def test_cfg_case_joins_hdl_item_and_select_eq(self) -> None:
        links = set((a, b) for a, b, *_ in build()["cfg"].links)
        self.assertIn(("cfg:p/c1", "hdl:c1"), links)
        self.assertIn(("cfg:p/c1", "cell:eq1"), links)
        self.assertNotIn(("cfg:p/c1", "cell:eq2"), links)
        self.assertIn(("cfg:p/c2", "cell:eq2"), links)
        self.assertIn(("cfg:p/sw0", "cell:mux"), links)
        self.assertIn(("cfg:p/sw0", "hdl:sw"), links)

    def test_stg_state_links_register_and_next_state_logic(self) -> None:
        links = set((a, b) for a, b, *_ in build()["stg"].links if a == "stg:f/s1")
        self.assertIn(("stg:f/s1", "hdl:sig.state"), links)
        self.assertIn(("stg:f/s1", "hdl:sw"), links)
        self.assertIn(("stg:f/s1", "cell:ff"), links)
        self.assertIn(("stg:f/s1", "cell:mux"), links)

    def test_ddg_signal_joins_declared_signal(self) -> None:
        links = set((a, b) for a, b, *_ in build()["ddg"].links)
        self.assertIn(("ddg:w2", "hdl:sig.state"), links)
        self.assertIn(("ddg:w2", "cell:ff"), links)

    def test_const_value(self) -> None:
        self.assertEqual(graphs.const_value("4'0011"), 3)
        self.assertEqual(graphs.const_value("1'1"), 1)
        self.assertEqual(graphs.const_value("8'hFF"), 255)
        self.assertIsNone(graphs.const_value("a"))


class ScoapTests(unittest.TestCase):
    def test_signal_takes_worst_over_its_bits(self) -> None:
        m = build(SCOAP)["ddg"].metrics
        self.assertEqual(m["cc0"]["ddg:w2"], 3.0)
        self.assertEqual(m["cc1"]["ddg:w2"], 5.0)
        self.assertEqual(m["co"]["ddg:w2"], 6.0)

    def test_unreachable_is_no_value_and_temp_joins_by_net(self) -> None:
        m = build(SCOAP)["ddg"].metrics
        self.assertNotIn("ddg:w3", m["cc0"])
        self.assertEqual(m["cc1"]["ddg:w3"], 9.0)
        self.assertEqual(m["cc0"]["ddg:n9"], 4.0)

    def test_without_prov_rows_there_is_no_scoap(self) -> None:
        plain = [{"id": 1, "name": "a", "cc0": 1, "cc1": 1, "co": 1}]
        self.assertNotIn("cc0", build(plain)["ddg"].metrics)


class LayoutTests(unittest.TestCase):
    def test_layout_is_in_the_unit_square_and_layered(self) -> None:
        gd = build()
        for g in gd.values():
            self.assertEqual(set(g.layout), set(g.ids))
            for x, y in g.layout.values():
                self.assertTrue(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0)
        lay = gd["cfg"].layout
        self.assertLess(lay["cfg:p/entry"][1], lay["cfg:p/sw0"][1])
        self.assertLess(lay["cfg:p/sw0"][1], lay["cfg:p/c1"][1])
        self.assertLess(lay["cfg:p/c1"][1], lay["cfg:p/exit"][1])

    def test_stg_layers_by_distance_from_reset(self) -> None:
        lay = build()["stg"].layout
        self.assertEqual(lay["stg:f/s0"][1], 0.0)
        self.assertLess(lay["stg:f/s1"][1], lay["stg:f/s2"][1])

    def test_ddg_ports_at_the_ends(self) -> None:
        lay = build()["ddg"].layout
        self.assertEqual(lay["ddg:w1"][1], 0.0)
        self.assertEqual(lay["ddg:w3"][1], 1.0)

    def test_cycles_do_not_hang(self) -> None:
        lay = graphs.layers_dag(["a", "b", "c"], [("a", "b"), ("b", "c"), ("c", "b")])
        self.assertEqual(lay["a"], 0)
        self.assertGreaterEqual(lay["c"], 1)

    def test_place_in_box(self) -> None:
        p = graphs.place_in({"a": (0.0, 0.0), "b": (1.0, 1.0)}, [10, 20, 30, 60])
        self.assertEqual(p["a"], [11.0, 22.0])
        self.assertEqual(p["b"], [29.0, 58.0])


class ScriptTests(unittest.TestCase):
    def test_graph_commands_and_prov_flag(self) -> None:
        s = 'read_verilog x.v; proc; opt; write_blif -x "o.blif"'
        out = nets.extended_script(s, Path("/w"), ("cfg", "stg", "ddg"), "prov")
        self.assertLess(out.index("write_graph cfg"), out.index("proc;"))
        self.assertLess(out.index("proc;"), out.index("write_graph stg"))
        self.assertIn("write_graph ddg /w/ddg.json", out)
        self.assertIn("scoap --prov --out /w/scoap.json", out)

    def test_poorer_set_has_no_graph_and_plain_scoap(self) -> None:
        s = 'read_verilog x.v; proc; opt; write_blif -x "o.blif"'
        out = nets.extended_script(s, Path("/w"), (), "plain")
        self.assertNotIn("write_graph", out)
        self.assertIn("scoap --out", out)
        self.assertNotIn("--prov --out", out)


if __name__ == "__main__":
    unittest.main()


class ReaderTests(unittest.TestCase):
    def test_graph_files_and_scoap_rows_are_read(self) -> None:
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as t:
            w = Path(t)
            (w / "cfg.json").write_text(json.dumps(cfg_doc()))
            (w / "ddg.json").write_text(json.dumps(ddg_doc()))
            (w / "scoap.json").write_text(
                json.dumps({"modules": [{"name": "m", "nets": SCOAP}, {"name": "o", "nets": []}]})
            )
            g = nets.read_graphs(w)
            rows = nets.read_scoap_rows(w / "scoap.json", "m")
        self.assertEqual(sorted(g), ["cfg", "ddg"])
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[1]["wire"], 2)
        self.assertEqual(nets.read_scoap_rows(Path("/nonexistent/x.json"), "m"), [])


class PortNetTests(unittest.TestCase):
    def test_port_named_net_joins_by_name_when_it_recomputes(self) -> None:
        from wyrd.o3viz import blif

        nl = blif.Netlist()
        nl.primary_inputs = {"a", "b"}
        nl.inputs = {"y": ["a", "b"]}
        nl.covers = {"y": [("11", "1")]}  # y = a & b
        table = {"a": (1, 1, 5), "b": (1, 1, 5)}
        good = nets.Dumps("m", {}, {}, {}, None, {}, {}, {})
        good.scoap_nets = [{"name": "y", "wire": 4, "cc0": 2, "cc1": 3, "co": 0}]
        self.assertEqual(cells.join_by_name(good, nl, table), 1)
        self.assertEqual(table["y"], (2, 3, 0))
        bad = nets.Dumps("m", {}, {}, {}, None, {}, {}, {})
        bad.scoap_nets = [{"name": "y", "wire": 4, "cc0": 9, "cc1": 9, "co": 0}]
        t2 = {"a": (1, 1, 5), "b": (1, 1, 5)}
        self.assertEqual(cells.join_by_name(bad, nl, t2), 0)
        self.assertNotIn("y", t2)

    def test_no_prov_rows_no_name_join(self) -> None:
        from wyrd.o3viz import blif

        d = nets.Dumps("m", {}, {}, {}, None, {}, {}, {})
        d.scoap_nets = [{"name": "y", "cc0": 1, "cc1": 1, "co": 1}]
        self.assertEqual(cells.join_by_name(d, blif.Netlist(), {}), 0)
