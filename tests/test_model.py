import unittest
from pathlib import Path

from wyrd.model import Design, Metric, Recipe, RunSpec, StepSpec


class ModelTest(unittest.TestCase):
    def test_runspec_fields(self) -> None:
        design = Design("d", (Path("/x/a.v"),), "top")
        recipe = Recipe("vtr", (StepSpec("odin3-flow", {"vpr": True}),))
        run = RunSpec(design, "EArch", recipe, {"seed": 1})
        self.assertEqual(run.design.files, (Path("/x/a.v"),))
        self.assertEqual(run.recipe.steps[0].use, "odin3-flow")
        self.assertEqual(Metric("luts", 12.0).unit, "")


if __name__ == "__main__":
    unittest.main()
