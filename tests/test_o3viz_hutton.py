"""o3viz: Hutton and Kundarewich measures, min-cut partition, cluster matrices (hand-computed)."""

from __future__ import annotations

import random
import unittest
from pathlib import Path

from wyrd.o3viz import blif, hutton, partition

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
