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


class LimitsTest(unittest.TestCase):
    def write(self, name: str, text: str | bytes, gz: bool = False) -> Path:
        t = Path(tempfile.mkdtemp(dir=self.tmp))
        p = t / name
        data = text.encode() if isinstance(text, str) else text
        if gz:
            with gzip.open(p, "wb") as f:
                f.write(data)
        else:
            p.write_bytes(data)
        return p

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = self._td.name

    def test_decompressed_cap(self) -> None:
        p = self.write("big.json.gz", b"[" + b"1," * 600 + b"1]", gz=True)
        old = atlas.MAX_JSON_BYTES
        atlas.MAX_JSON_BYTES = 1000
        try:
            with self.assertRaisesRegex(AtlasError, "MB of JSON"):
                atlas.load_atlas(p)
        finally:
            atlas.MAX_JSON_BYTES = old

    def test_file_cap(self) -> None:
        p = self.write("x.json", json.dumps(tiny()))
        old = atlas.MAX_FILE_BYTES
        atlas.MAX_FILE_BYTES = 10
        try:
            with self.assertRaisesRegex(AtlasError, "larger"):
                atlas.load_atlas(p)
        finally:
            atlas.MAX_FILE_BYTES = old

    def test_deep_nesting(self) -> None:
        p = self.write("deep.json", "[" * 200000 + "]" * 200000)
        with self.assertRaises(AtlasError):
            atlas.load_atlas(p)

    def test_counts_and_sizes(self) -> None:
        with self.assertRaises(AtlasError):
            atlas.parse_atlas(tiny(grid=[1001, 3]))
        with self.assertRaises(AtlasError):
            atlas.parse_atlas(tiny(clbs=[], atoms=[None] * (atlas.MAX_ATOMS + 1)))
        d = tiny()
        d["atoms"][0]["name"] = "x" * (atlas.MAX_STRING + 1)
        with self.assertRaises(AtlasError):
            atlas.parse_atlas(d)

    def test_non_finite(self) -> None:
        for bad in (float("nan"), float("inf")):
            d = tiny()
            d["atoms"][0]["crit"] = bad
            with self.assertRaisesRegex(AtlasError, "finite"):
                atlas.parse_atlas(d)
        p = self.write("nan.json", json.dumps(tiny()).replace("0.2", "NaN"))
        with self.assertRaises(AtlasError):
            atlas.load_atlas(p)


class FormatTest(unittest.TestCase):
    def test_shared_io_tile(self) -> None:
        d = tiny()
        d["clbs"] += [
            {"id": 3, "type": "io", "x": 2, "y": 2, "atoms": []},
            {"id": 4, "type": "io", "x": 2, "y": 2, "atoms": []},
        ]
        self.assertEqual(len(atlas.parse_atlas(d).clbs), 4)
        d["clbs"].append({"id": 5, "type": "clb", "x": 0, "y": 0, "atoms": []})
        with self.assertRaises(AtlasError):
            atlas.parse_atlas(d)

    def test_optional_labels_and_no_crit(self) -> None:
        d = tiny()
        for a in d["atoms"]:
            for k in ("construct", "inst", "class", "crit"):
                del a[k]
        a = atlas.parse_atlas(d)
        self.assertEqual((a.atoms[0].construct, a.atoms[0].inst, a.atoms[0].cls), ("", "", ""))
        self.assertIsNone(a.atoms[0].crit)
        atlas.summary_text(a)
        atlas.clb_colours(a, "crit")

    def test_run_of_path(self) -> None:
        r = atlas.run_of_path(Path("/x/d1/atlas/h2.s3.json.gz"))
        self.assertEqual((r.design, r.arm, r.seed) if r else None, ("d1", "h2", 3))
        r = atlas.run_of_path(Path("/x/d1.stock.s7.json"))
        self.assertEqual((r.design, r.arm, r.seed) if r else None, ("d1", "stock", 7))
        self.assertIsNone(atlas.run_of_path(Path("/x/odd.json")))


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
        self.assertIn("1 of 3 common atoms", atlas.diff_summary(a, b, atlas.DIFF_POSITION))
        self.assertIn("3 of 3 common atoms", atlas.diff_summary(a, b))

    def test_mate_changes(self) -> None:
        a, b = atlas.parse_atlas(tiny()), atlas.parse_atlas(swapped())
        self.assertEqual(atlas.mate_changes(a, b), {"a": 1.0, "b": 1.0, "c": 1.0})
        self.assertEqual(atlas.mate_changes(a, a), {"a": 0.0, "b": 0.0, "c": 0.0})

    def test_mates_differ_from_position(self) -> None:
        """Both CLBs swap places but keep their members: position changes, clustering does not."""
        d = tiny(arm="h1")
        d["clbs"][0].update(x=1, y=2)
        d["clbs"][1].update(x=0, y=0)
        a, b = atlas.parse_atlas(tiny()), atlas.parse_atlas(d)
        self.assertEqual(set(atlas.moved_atoms(a, b)), {"a", "b", "c"})
        self.assertEqual(sum(atlas.mate_changes(a, b).values()), 0.0)
        self.assertIn("0 of 3 common atoms", atlas.diff_summary(a, b))

    def test_partial_jaccard(self) -> None:
        d = tiny(arm="h1")
        d["atoms"].append(dict(d["atoms"][2], name="e"))
        d["atoms"].append(dict(d["atoms"][2], name="f"))
        d["clbs"][0]["atoms"] = [0, 1, 3]
        d["clbs"][1]["atoms"] = [2, 4]
        base = tiny()
        base["atoms"] = d["atoms"]
        base["clbs"][0]["atoms"] = [0, 1]
        base["clbs"][1]["atoms"] = [2, 3, 4]
        ch = atlas.mate_changes(atlas.parse_atlas(base), atlas.parse_atlas(d))
        self.assertAlmostEqual(ch["a"], 1 - 1 / 2)  # {b} vs {b,e}
        self.assertAlmostEqual(ch["c"], 1 - 1 / 2)  # {e,f} vs {f}

    def test_duplicate_names_reported(self) -> None:
        d = tiny()
        d["atoms"][2]["name"] = "a"
        a = atlas.parse_atlas(d)
        self.assertEqual(a.dup_atoms, 1)
        self.assertIn("2 atoms excluded", atlas.diff_summary(a, a))
        self.assertEqual(atlas.parse_atlas(tiny()).dup_atoms, 0)

    def test_samples(self) -> None:
        a, b = atlas.load_atlas(STOCK), atlas.load_atlas(HIND)
        moved = atlas.moved_atoms(a, b)
        self.assertLessEqual(len(moved), len(a.atoms))
