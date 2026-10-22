import unittest
from pathlib import Path

from wyrd.guimodel.projmodel import project_tree
from wyrd.project import load_project

SAMPLES = Path(__file__).parent.parent / "samples"


class ProjModelTest(unittest.TestCase):
    def test_sample_tree(self) -> None:
        tree = project_tree(load_project(SAMPLES / "wyrd.toml"))
        self.assertEqual([n.label for n in tree], ["Designs", "Recipes", "Archs"])
        self.assertTrue(all(n.kind == "group" for n in tree))
        designs, recipes, archs = tree
        self.assertEqual(
            [d.label for d in designs.children], ["single", "multi (top: top)", "dsp (top: top)"]
        )
        self.assertTrue(all(d.kind == "design" for d in designs.children))
        multi = designs.children[1]
        self.assertEqual(
            [f.label for f in multi.children],
            [
                "designs/multi/src/arith/adder.v",
                "designs/multi/src/ctrl/pick.v",
                "designs/multi/src/top.v",
            ],
        )
        first = multi.children[0]
        self.assertEqual(first.kind, "file")
        self.assertIsNotNone(first.path)
        assert first.path is not None
        self.assertTrue(first.path.is_absolute())
        self.assertEqual([r.label for r in recipes.children], ["vtr"])
        self.assertEqual(
            [(s.kind, s.label) for s in recipes.children[0].children], [("step", "odin3-flow")]
        )
        self.assertEqual(
            [a.label for a in archs.children], ["EArch", "k6_frac_N10_frac_chain_mem32K_40nm"]
        )


if __name__ == "__main__":
    unittest.main()
