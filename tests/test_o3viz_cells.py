"""o3viz M5: case items to cells, bus names, flip-flop cells (synthetic dumps, no tool needed)."""

from __future__ import annotations

import unittest
from typing import Any

from wyrd.o3viz import blif, cells, nets

SRC = [
    "module m(input clk, input [1:0] sel, output reg [3:0] q);",
    "reg [3:0] acc;",
    "always @(posedge clk)",
    "case (sel)",
    "  2'b00: acc <= 4'd1;",
    "  2'b01: if (q[0]) acc <= 4'd2; else acc <= 4'd3;",
    "  2'd2: acc <= 4'd4;",
    "endcase",
]


def hobj(oid: str, level: str, parent: str | None, span: str) -> dict[str, Any]:
    return {
        "id": oid,
        "attrs": {"level": level, "parent": parent},
        "src": [{"file": "m.v", "span": span}],
    }


HDL = {
    o["id"]: o
    for o in [
        hobj("hdl:c1", "module", None, "1.1-8.10"),
        hobj("hdl:c2", "stmt", "hdl:c1", "4.1-7.5"),
        hobj("hdl:c3", "branch", "hdl:c2", "5.3-5.25"),
        hobj("hdl:c4", "branch", "hdl:c2", "6.3-6.60"),
        hobj("hdl:c5", "stmt", "hdl:c4", "6.9-6.25"),
        hobj("hdl:c6", "branch", "hdl:c2", "7.3-7.22"),
    ]
}
PARENT = {k: v["attrs"]["parent"] for k, v in HDL.items() if v["attrs"]["parent"]}
TEXTS = {"m.v": SRC}


def eq(sel_bits: list[Any], const: list[str], out: int, span: str) -> dict[str, Any]:
    return {
        "type": "$eq",
        "attributes": {"src": f"m.v:{span}"},
        "port_directions": {"A": "input", "B": "input", "Y": "output"},
        "connections": {"A": sel_bits, "B": const, "Y": [out]},
    }


def dumps() -> nets.Dumps:
    proc_cells = {
        "m/$c1@m.v:1": eq([2, 3], ["0", "0"], 20, "4.1-7.5"),
        "m/$c2@m.v:1": eq([2, 3], ["1", "0"], 21, "4.1-7.5"),
        "m/$c3@m.v:1": eq([2, 3], ["0", "1"], 22, "4.1-7.5"),
        "m/$c4@m.v:1": {
            "type": "$pmux",
            "attributes": {"src": "m.v:4.1-7.5|m.v:5.3-5.25|m.v:6.3-6.60|m.v:7.3-7.22"},
            "port_directions": {"S": "input", "Y": "output"},
            "connections": {"S": [20, 21, 22], "Y": [10, 11, 12, 13]},
        },
        "m/$c5@m.v:1": {
            "type": "$mux",
            "attributes": {"src": "m.v:6.9-6.25"},
            "port_directions": {"S": "input", "Y": "output"},
            "connections": {"S": [4], "Y": [30]},
        },
        "m/acc.dff@m.v:2": {
            "type": "$dff",
            "attributes": {"src": "m.v:2.1-2.15"},
            "port_directions": {"D": "input", "Q": "output"},
            "connections": {"D": [10, 11, 12, 13], "Q": [40, 41, 42, 43]},
        },
    }
    mod = {
        "cells": proc_cells,
        "ports": {"clk": {"direction": "input"}},
        "netnames": {
            "clk": {"bits": [1]},
            "sel": {"bits": [2, 3]},
            "q": {"bits": [4, 5, 6, 7]},
            "m/acc@m.v:2": {"bits": [40, 41, 42, 43], "attributes": {"src": "m.v:2.1-2.15"}},
        },
    }
    return nets.Dumps("m", mod, {}, {}, {}, {}, {})


class TestCaseItems(unittest.TestCase):
    def test_eq_with_constant_links_to_its_item_only(self) -> None:
        sel = cells.select_items(dumps().proc["cells"], HDL, PARENT, TEXTS)
        self.assertEqual(sel["m/$c1@m.v:1"], "hdl:c3")
        self.assertEqual(sel["m/$c2@m.v:1"], "hdl:c4")
        self.assertEqual(len(sel), 3)

    def test_label_forms(self) -> None:
        self.assertEqual(cells.label_value("  2'b01: x"), 1)
        self.assertEqual(cells.label_value("  2'd2: x"), 2)
        self.assertEqual(cells.label_value("  3: x"), 3)
        self.assertIsNone(cells.label_value("  default: x"))

    def test_three_cell_roles(self) -> None:
        d = dumps()
        cd = cells.build_cells(d, HDL, PARENT, TEXTS, [])
        by_cell: dict[str, set[str]] = {}
        for h, c, _k, _q in cd.links:
            by_cell.setdefault(c, set()).add(h)
        # the select of item 0 links to its item and the chain, not to the siblings
        self.assertIn("hdl:c3", by_cell["cell:$c1"])
        self.assertNotIn("hdl:c4", by_cell["cell:$c1"])
        self.assertIn("hdl:c2", by_cell["cell:$c1"])
        # the pmux serves every item
        self.assertTrue({"hdl:c3", "hdl:c4", "hdl:c6"} <= by_cell["cell:$c4"])
        # the mux of the inner if is inside item 1 only
        self.assertIn("hdl:c5", by_cell["cell:$c5"])
        self.assertNotIn("hdl:c3", by_cell["cell:$c5"])
        self.assertEqual(cd.selects, 3)


class TestBusesAndFlops(unittest.TestCase):
    def test_flop_cell_and_signal(self) -> None:
        cd = cells.build_cells(dumps(), HDL, PARENT, TEXTS, [])
        self.assertIn("cell:acc.dff", cd.ff)
        self.assertEqual(cd.bus["cell:acc.dff"], ("acc", None, "own"))
        sig = {s.name: s for s in cd.signals}
        self.assertEqual(sig["acc"].kind, "reg")
        self.assertEqual(sig["acc"].width, 4)
        self.assertEqual(sig["acc"].decl, ["m.v", "2.1-2.15"])
        self.assertEqual(sig["clk"].kind, "input")

    def test_bus_of_a_cone_comes_from_the_unique_named_sink(self) -> None:
        cd = cells.build_cells(dumps(), HDL, PARENT, TEXTS, [])
        # the pmux drives the D of acc: it has no own name but feeds only acc
        self.assertEqual(cd.bus["cell:$c4"][0], "acc")
        self.assertEqual(cd.bus["cell:$c4"][2], "cone")

    def test_bit_names_prefer_ports(self) -> None:
        names = cells.bit_names(dumps().proc, "m")
        self.assertEqual(names[3], ("sel", 1))
        self.assertEqual(names[42], ("acc", 2))

    def test_port_bus_parse(self) -> None:
        self.assertEqual(cells.port_bus("return_val[24]"), ("return_val", 24, "own"))
        self.assertIsNone(cells.port_bus("h22bzdbddcd"))
        self.assertIsNone(cells.port_bus("gnd"))

    def test_lut_bus_through_the_net_number_offset(self) -> None:
        nl = blif.Netlist()
        nl.drivers = {"hq": "latch", "hl": "names"}
        nl.inputs = {"hq": ["hl"], "hl": ["hq"]}
        full = {"hq": "m/$n12@m.v:2", "hl": "m/$n20@m.v:2"}
        gates = {
            "cells": {
                "d": {"type": "$_DFF_P_", "connections": {"Q": [10], "D": [18], "C": [1]}},
                "l": {"type": "$lut", "connections": {"A": [10], "Y": [18]}},
            },
            "netnames": {"m/acc@m.v:2": {"bits": [10]}},
        }
        d = nets.Dumps("m", {}, {}, gates, {}, {}, full)
        table, note = cells.lut_buses(d, nl)
        self.assertEqual(table["hq"], ("acc", 0, "own"))
        self.assertEqual(table["hl"][0], "acc")
        self.assertIn("verified", note)

    def test_decl_line_found_by_regex(self) -> None:
        self.assertEqual(cells.decl_of("acc", TEXTS, ""), ["m.v", "2.1-2.15"])
        self.assertIsNone(cells.decl_of("nope", TEXTS, ""))


if __name__ == "__main__":
    unittest.main()
