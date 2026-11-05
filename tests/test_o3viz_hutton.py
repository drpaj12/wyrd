"""o3viz: Hutton and Kundarewich measures, min-cut partition, cluster matrices (hand-computed)."""

from __future__ import annotations

import unittest
from pathlib import Path

from wyrd.o3viz import blif, hutton

DATA = Path(__file__).resolve().parent / "data" / "o3viz"


def micro() -> blif.Netlist:
    """Two registers with feedback: n1 -> n2 -> q1 -> n3 -> n4 -> q2 -> n1 (q2, q1 also feed z)."""
    return blif.read_blif(DATA / "hutton" / "s.blif")


class TestHutton(unittest.TestCase):
    def test_delay_and_sequential_levels(self) -> None:
        nl = micro()
        lv = nl.levels()
        self.assertEqual(
            {n: lv[n] for n in ("n1", "n2", "q1", "n3", "n4", "q2", "z")},
            {"n1": 1, "n2": 2, "q1": 0, "n3": 1, "n4": 2, "q2": 0, "z": 1},
        )
        sl = hutton.seq_levels(nl)
        self.assertEqual(
            {n: sl[n] for n in ("n1", "n2", "q1", "n3", "n4", "q2", "z")},
            {"n1": 0, "n2": 0, "q1": 1, "n3": 1, "n4": 1, "q2": 2, "z": 1},
        )

    def test_sequential_level_of_a_constant_is_missing(self) -> None:
        nl = blif.Netlist(drivers={"k": "names"}, inputs={"k": []})
        self.assertEqual(hutton.seq_levels(nl), {})

    def test_latched_nodes_and_comb_fanout(self) -> None:
        nl = micro()
        self.assertEqual(hutton.latched_nodes(nl), {"n2", "n4"})
        cf = hutton.comb_fanout(nl)
        self.assertEqual(
            [cf[n] for n in ("n1", "n2", "q1", "n3", "n4", "q2", "z")], [1, 0, 3, 1, 0, 2, 0]
        )

    def test_whole_circuit_shapes(self) -> None:
        c = hutton.characterize(micro())
        self.assertEqual(c["nodes"], 7)
        self.assertEqual(c["dmax"], 2)
        self.assertEqual(c["pis"], 3)
        self.assertEqual(c["node_shape"], [2, 3, 2])
        self.assertEqual(c["input_shape"], [0, 6, 4])
        self.assertEqual(c["output_shape"], [2, 2, 2])
        self.assertEqual(c["po_shape"], [0, 1, 0])
        self.assertEqual(c["fanout"], [3, 2, 1, 1])
        self.assertEqual(c["edge_length"], [0, 6, 1])
        self.assertEqual((c["dff_edges"], c["block_edges"], c["pi_edges"]), (2, 0, 3))

    def test_selection_shapes(self) -> None:
        c = hutton.characterize(micro(), {"n1", "n2", "q2"})
        self.assertEqual(c["node_shape"], [1, 1, 1])
        self.assertEqual(c["edge_length"], [0, 2])
        self.assertEqual((c["dff_edges"], c["pi_edges"]), (0, 3))
