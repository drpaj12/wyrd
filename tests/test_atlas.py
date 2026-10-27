import gzip
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from wyrd import atlas
from wyrd.atlas import Atlas, AtlasError

DATA = Path(__file__).parent / "data" / "atlas"
STOCK = DATA / "diffeq1.stock.s1.json.gz"
HIND = DATA / "diffeq1.h1.s4.json.gz"


def tiny(**over: Any) -> dict[str, Any]:
    """Two CLBs on a 3x3 grid, three atoms."""
    base: dict[str, Any] = {
        "design": "d", "arm": "stock", "seed": 1, "grid": [3, 3],
        "cpd_ns": 1.0, "wirelength": 10.0, "chan_width": 4.0,
        "clbs": [
            {"id": 1, "type": "clb", "x": 0, "y": 0, "atoms": [0, 1]},
            {"id": 2, "type": "clb", "x": 1, "y": 2, "atoms": [2]},
        ],
        "atoms": [
            {"name": "a", "kind": "lut", "class": "SC", "construct": "f.v:1", "inst": "u",
             "word": "b:w", "bit": 0, "crit": 0.2, "pcrit": 0.9},
            {"name": "b", "kind": "latch", "class": "SC", "construct": "f.v:1", "inst": "u",
             "word": "b:w", "bit": 1, "crit": None, "pcrit": 0.1},
            {"name": "c", "kind": "lut", "class": "", "construct": "", "inst": "",
             "word": None, "bit": None, "crit": None, "pcrit": None},
        ],
    }  # fmt: skip
    base.update(over)
    return base


def swapped() -> dict[str, Any]:
    """tiny() with atom b moved to the other CLB."""
    d = tiny(arm="h1")
    d["clbs"][0]["atoms"] = [0]
    d["clbs"][1]["atoms"] = [1, 2]
    return d


class LoadTest(unittest.TestCase):
    def test_samples(self) -> None:
        for p in DATA.glob("*.json.gz"):
            a = atlas.load_atlas(p)
            self.assertGreater(len(a.clbs), 0)
            self.assertGreater(len(a.atoms), 0)

    def test_sample_fields(self) -> None:
        a = atlas.load_atlas(STOCK)
        self.assertEqual((a.design, a.arm, a.seed), ("diffeq1", "stock", 1))
        self.assertEqual(a.grid, (16, 16))
        self.assertEqual(len(a.clbs), 37)
        self.assertEqual(len(a.atoms), 622)

    def test_plain_json(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "x.json"
            p.write_text(json.dumps(tiny()), encoding="utf-8")
            self.assertEqual(atlas.load_atlas(p).design, "d")

    def test_bad_inputs(self) -> None:
        bad: list[dict[str, Any]] = [
            tiny(grid=[0, 3]),
            tiny(clbs=[{"id": 1, "type": "zzz", "x": 0, "y": 0, "atoms": []}]),
            tiny(clbs=[{"id": 1, "type": "clb", "x": 0, "y": 0, "atoms": [9]}]),
            tiny(clbs=[{"id": 1, "type": "clb", "x": 5, "y": 0, "atoms": []}]),
            tiny(clbs=[{"id": 1, "type": "clb", "x": 0, "y": 0, "atoms": [0, 1]},
                       {"id": 2, "type": "clb", "x": 1, "y": 0, "atoms": [1]}]),
            tiny(seed="one"),
        ]  # fmt: skip
        for d in bad:
            with self.assertRaises(AtlasError):
                atlas.parse_atlas(d)

    def test_unreadable(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "x.json.gz"
            p.write_bytes(b"not gzip")
            with self.assertRaises(AtlasError):
                atlas.load_atlas(p)
            with self.assertRaises(AtlasError):
                atlas.load_atlas(Path(t) / "missing.json")
            q = Path(t) / "y.json.gz"
            with gzip.open(q, "wt") as f:
                f.write("[1]")
            with self.assertRaises(AtlasError):
                atlas.load_atlas(q)


class RunsTest(unittest.TestCase):
    def test_flat_folder(self) -> None:
        runs = atlas.find_runs(DATA)
        self.assertEqual(atlas.designs_of(runs), ["ch_intrinsics", "diffeq1"])
        self.assertEqual(atlas.arms_of(runs, "diffeq1"), ["stock", "h1"])
        self.assertEqual(atlas.seeds_of(runs, "diffeq1", "h1"), [4])
        self.assertEqual(atlas.path_of(runs, "diffeq1", "h1", 4), HIND)
        self.assertIsNone(atlas.path_of(runs, "diffeq1", "h1", 5))

    def test_runs_root(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "or" / "atlas"
            d.mkdir(parents=True)
            for n in ("stock.s2.json.gz", "h10.s1.json.gz", "h2.s1.json.gz", "junk.txt"):
                (d / n).write_bytes(b"")
            runs = atlas.find_runs(Path(t))
            self.assertEqual(atlas.designs_of(runs), ["or"])
            self.assertEqual(atlas.arms_of(runs, "or"), ["stock", "h2", "h10"])
        self.assertEqual(atlas.find_runs(Path("/nonexistent-atlas-root")), [])


class SummaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.a: Atlas = atlas.parse_atlas(tiny())

    def test_counts(self) -> None:
        self.assertEqual(atlas.clb_counts_by_type(self.a), {"clb": 2})
        self.assertEqual(atlas.atoms_per_clb(self.a), {"min": 1.0, "mean": 1.5, "max": 2.0})

    def test_spread(self) -> None:
        self.assertEqual(atlas.spread(self.a, "word"), {"b:w": 1})
        self.assertEqual(atlas.spread(self.a, "construct"), {"f.v:1": 1})
        with self.assertRaises(ValueError):
            atlas.spread(self.a, "crit")

    def test_class_shares(self) -> None:
        s = atlas.class_shares(self.a)
        self.assertAlmostEqual(s["SC"], 2 / 3)
        self.assertAlmostEqual(s[atlas.NONE_LABEL], 1 / 3)

    def test_summary_text(self) -> None:
        self.assertIn("grid 3x3", atlas.summary_text(self.a))

    def test_real(self) -> None:
        a = atlas.load_atlas(STOCK)
        self.assertEqual(atlas.clb_counts_by_type(a), {"clb": 37})
        self.assertAlmostEqual(sum(atlas.class_shares(a).values()), 1.0)


class ColourTest(unittest.TestCase):
    def setUp(self) -> None:
        self.a = atlas.parse_atlas(tiny())

    def test_categorical(self) -> None:
        col = atlas.clb_colours(self.a, "word")
        self.assertEqual(col[1], atlas.PALETTE[0])
        self.assertEqual(col[2], atlas.UNLABELLED_COLOUR)

    def test_numeric(self) -> None:
        col = atlas.clb_colours(self.a, "pcrit")
        self.assertEqual(col[1], atlas.ramp_colour(0.9))
        self.assertEqual(col[2], atlas.UNLABELLED_COLOUR)
        self.assertNotEqual(atlas.ramp_colour(0.0), atlas.ramp_colour(1.0))
        self.assertEqual(atlas.ramp_colour(5.0), atlas.ramp_colour(1.0))

    def test_every_key(self) -> None:
        a = atlas.load_atlas(STOCK)
        for k in atlas.KEYS:
            self.assertEqual(len(atlas.clb_colours(a, k)), len(a.clbs))
        with self.assertRaises(ValueError):
            atlas.clb_colours(a, "nope")

    def test_empty_clb(self) -> None:
        d = tiny()
        d["clbs"][1]["atoms"] = []
        col = atlas.clb_colours(atlas.parse_atlas(d), "word")
        self.assertEqual(col[2], atlas.EMPTY_COLOUR)

    def test_clbs_with(self) -> None:
        self.assertEqual(atlas.clbs_with(self.a, "word", "b:w"), {1})
        self.assertEqual(atlas.clbs_with(self.a, "word", "zz"), set())

    def test_category_ties_are_alphabetical(self) -> None:
        d = tiny()
        d["atoms"][1]["word"] = "a:z"
        a = atlas.parse_atlas(d)
        self.assertEqual(atlas.clb_category(a, a.clbs[0], "word"), "a:z")


class HoverTest(unittest.TestCase):
    def test_text(self) -> None:
        a = atlas.parse_atlas(tiny())
        t = atlas.hover_text(a, a.clbs[0])
        self.assertIn("clb 1 at (0, 0): 2 atoms", t)
        self.assertIn("word b:w[0]", t)
        self.assertIn("pcrit 0.900", t)
        self.assertIn("crit -", t)

    def test_limit(self) -> None:
        a = atlas.parse_atlas(tiny())
        self.assertIn("... and 1 more", atlas.hover_text(a, a.clbs[0], limit=1))


class DiffTest(unittest.TestCase):
    def test_moved(self) -> None:
        a, b = atlas.parse_atlas(tiny()), atlas.parse_atlas(swapped())
        self.assertEqual(atlas.moved_atoms(a, b), {"b": ((0, 0), (1, 2))})
        self.assertEqual(atlas.moved_atoms(a, a), {})

    def test_share_and_colours(self) -> None:
        a, b = atlas.parse_atlas(tiny()), atlas.parse_atlas(swapped())
        moved = set(atlas.moved_atoms(a, b))
        self.assertEqual(atlas.moved_share(b, moved), {1: 0.0, 2: 0.5})
        col = atlas.diff_colours(b, moved)
        self.assertEqual(col[2], atlas.ramp_colour(0.5))
        self.assertEqual(col[1], atlas.ramp_colour(0.0))

    def test_summary(self) -> None:
        a, b = atlas.parse_atlas(tiny()), atlas.parse_atlas(swapped())
        self.assertIn("1 of 3 common atoms", atlas.diff_summary(a, b))

    def test_samples(self) -> None:
        a, b = atlas.load_atlas(STOCK), atlas.load_atlas(HIND)
        moved = atlas.moved_atoms(a, b)
        self.assertLessEqual(len(moved), len(a.atoms))
