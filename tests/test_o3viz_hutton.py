"""o3viz: Hutton and Kundarewich measures, min-cut partition, cluster matrices (hand-computed)."""

from __future__ import annotations

import random
import unittest
from pathlib import Path
from typing import Any

from wyrd.o3viz import blif, circuit, hutton, partition

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
        self.assertEqual(c["nodes"], 10)
        self.assertEqual(c["dmax"], 2)
        self.assertEqual(c["pis"], 3)
        self.assertEqual(c["node_shape"], [5, 3, 2])
        self.assertEqual(c["input_shape"], [0, 6, 4])
        self.assertEqual(c["output_shape"], [5, 2, 2])
        self.assertEqual(c["po_shape"], [0, 1, 0])
        self.assertEqual(c["fanout"], [3, 5, 1, 1])
        self.assertEqual(c["edge_length"], [0, 8, 2])
        self.assertEqual((c["dff_edges"], c["block_edges"]), (2, 0))

    def test_selection_shapes(self) -> None:
        c = hutton.characterize(micro(), {"n1", "n2", "q2"})
        self.assertEqual(c["node_shape"], [1, 1, 1])
        self.assertEqual(c["edge_length"], [0, 2])
        self.assertEqual(c["dff_edges"], 0)


def two_blobs(n: int = 8) -> tuple[list[str], list[list[str]]]:
    """Two dense groups of n cells joined by one net."""
    cells = [f"a{i}" for i in range(n)] + [f"b{i}" for i in range(n)]
    nets: list[list[str]] = []
    for g in "ab":
        for i in range(n):
            nets.append([f"{g}{i}", f"{g}{(i + 1) % n}", f"{g}{(i + 3) % n}"])
    nets.append(["a0", "b0"])
    return cells, nets


class TestPartition(unittest.TestCase):
    def test_finds_the_bridge_and_is_deterministic(self) -> None:
        cells, nets = two_blobs()
        one = partition.partition(cells, nets, 2, seed=7)
        two = partition.partition(cells, nets, 2, seed=7)
        self.assertEqual(one, two)
        self.assertEqual(partition.cut_size(nets, one), 1)
        self.assertEqual(len({one[c] for c in cells if c[0] == "a"}), 1)

    def test_not_worse_than_a_random_split(self) -> None:
        cells, nets = two_blobs(40)
        rnd = random.Random(3)
        shuffled = cells[:]
        rnd.shuffle(shuffled)
        random_side = {c: int(i >= len(cells) // 2) for i, c in enumerate(shuffled)}
        got = partition.partition(cells, nets, 2)
        self.assertLess(partition.cut_size(nets, got), partition.cut_size(nets, random_side))

    def test_k_clusters_cover_every_cell(self) -> None:
        cells, nets = two_blobs(16)
        got = partition.partition(cells, nets, 5)
        self.assertEqual(set(got), set(cells))
        self.assertEqual(sorted(set(got.values())), [0, 1, 2, 3, 4])
        sizes = [list(got.values()).count(i) for i in range(5)]
        self.assertGreaterEqual(min(sizes), 2)

    def test_more_clusters_than_cells(self) -> None:
        got = partition.partition(["x", "y"], [["x", "y"]], 9)
        self.assertEqual(sorted(got.values()), [0, 1])


NETS = ["a", "b", "c", "n1", "n2", "q1", "n3", "n4", "q2", "z"]
OF = [0, 0, 0, 0, 0, 1, 1, 1, 1, 1]  # clusters {a b c n1 n2} and {q1 n3 n4 q2 z}


class TestClusters(unittest.TestCase):
    def test_comb_and_latched_matrices(self) -> None:
        comb, latched = circuit.matrices(micro(), NETS, OF, 2)
        self.assertEqual(comb, [[4, 0], [1, 5]])
        self.assertEqual(latched, [[0, 1], [0, 1]])

    def test_source_entry_inter_cluster_share(self) -> None:
        src = {"names": ["x", "y"], "construct": [None, None], "of": list(OF)}
        e = circuit.source_entry(micro(), NETS, src, "t", 2)
        self.assertEqual((e["edges"], e["inter_edges"]), (12, 2))
        self.assertEqual(e["sizes"], [5, 5])
        self.assertEqual(e["shape"], [[3, 1, 1], [2, 2, 1]])

    def test_unassigned_objects_get_a_last_cluster(self) -> None:
        src: dict[str, Any] = {"names": ["x"], "construct": [None], "of": [0, None]}
        self.assertEqual(circuit.complete(src), 2)
        self.assertEqual((src["names"][1], src["of"], src["unassigned"]), ("(none)", [0, 1], 1))

    def test_nmi_same_and_independent(self) -> None:
        self.assertEqual(circuit.nmi([0, 0, 1, 1], [5, 5, 7, 7]), 1.0)
        self.assertEqual(circuit.nmi([0, 0, 1, 1], [0, 1, 0, 1]), 0.0)
        self.assertIsNone(circuit.nmi([0, 0], [0, 1]))

    def test_mincut_clusters_cover_all_objects(self) -> None:
        got = circuit.mincut_clusters(micro(), [*NETS, None], 2)
        self.assertEqual(sorted(set(got["of"][:-1])), [0, 1])
        self.assertIsNone(got["of"][-1])

    def test_hdl_clusters_levels(self) -> None:
        h = circuit.Hdl(
            ["m", "b1", "b2", "i1", "i2"],
            ["module", "block", "block", "branch", "branch"],
            ["top", "b1", "b2", "i1", "i2"],
            [
                [["f.v", "1.1-9.1"]],
                [["f.v", "2.1-4.1"]],
                [["f.v", "5.1-8.1"]],
                [["f.v", "3.1-3.9"]],
                [["f.v", "6.1-7.9"]],
            ],
            {"b1": "m", "b2": "m", "i1": "b1", "i2": "b2"},
        )
        luts = ["x", "y", "z"]
        links = {"x": ["i1"], "y": ["b2"], "z": ["i1", "i2"]}
        blk = circuit.hdl_clusters(h, luts, links, "block")
        self.assertEqual(blk["construct"], ["b1", "b2"])
        self.assertEqual(blk["of"], [0, 1, 0])  # z reaches both blocks: smallest span wins
        self.assertEqual(blk["ambiguous"], 1)
        item = circuit.hdl_clusters(h, luts, links, "item")
        self.assertEqual(item["of"], [0, 1, 0])  # y has no item: falls back to its block
        self.assertEqual(item["fallback"], 1)
        mod = circuit.hdl_clusters(h, luts, links, "module")
        self.assertEqual(mod["of"], [0, 0, 0])

    def test_grid_layout_levels_across_bands_down(self) -> None:
        pos, labels = circuit.grid_layout(
            {"a": 0, "b": 1, "c": 1, "d": 0}, {"a": 0, "b": 0, "c": 1, "d": 1}, {}
        )
        self.assertEqual(pos["a"][0], pos["d"][0])
        self.assertLess(pos["a"][0], pos["b"][0])
        self.assertLess(pos["a"][1], pos["d"][1])
        self.assertEqual([x["text"] for x in labels if "band" not in x], ["L0", "L1"])
