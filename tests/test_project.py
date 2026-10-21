"""Tests for wyrd.project."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wyrd.project import ConfigError, load_project

DATA = Path(__file__).parent / "data" / "proj_ok"

BASE = """[project]
name = "t"

[[design]]
name = "d"
files = ["x.v"]

[recipe.r]
steps = [{ use = "odin3-flow" }]

"""


def _write(text: str, with_file: bool = True) -> Path:
    tmp = Path(tempfile.mkdtemp())
    if with_file:
        (tmp / "x.v").write_text("module x; endmodule\n")
    path = tmp / "wyrd.toml"
    path.write_text(text)
    return path


class ProjectTests(unittest.TestCase):
    def test_load_ok(self) -> None:
        proj = load_project(DATA / "wyrd.toml")
        self.assertEqual(proj.name, "tiny")
        self.assertEqual(proj.root, DATA)
        self.assertEqual(len(proj.runs), 4)
        got = [(r.recipe.name, r.design.name, r.arch) for r in proj.runs]
        self.assertEqual(
            got,
            [("vtr", "one", "k6"), ("vtr", "one", "EArch"), ("vtr", "two", "k6"),
             ("vtr", "two", "EArch")],
        )
        self.assertEqual(proj.run, {"step_timeout": 100})
        self.assertEqual(proj.recipes["vtr"].steps[0].use, "odin3-flow")
        self.assertEqual(proj.recipes["vtr"].steps[0].args, {"target": "vtr", "vpr": True})
        self.assertEqual(proj.designs["one"].top, "a")

    def test_files_glob_sorted(self) -> None:
        proj = load_project(DATA / "wyrd.toml")
        two = proj.designs["two"].files
        self.assertEqual(two, tuple(sorted((DATA / "src").glob("*.v"))))
        self.assertTrue(all(p.is_absolute() for p in two))
        self.assertEqual(len(two), 3)
        one = proj.designs["one"].files
        self.assertEqual(one, (DATA / "src" / "a.v", DATA / "src" / "b.v"))

    def test_empty_glob_is_config_error(self) -> None:
        path = _write(BASE.replace('"x.v"', '"nope/*.v"') + '[sweep]\nrecipe=["r"]\n'
                      'design=["d"]\narch=["a"]\n')
        with self.assertRaises(ConfigError) as cm:
            load_project(path)
        self.assertIn("d", str(cm.exception))
        self.assertIn("matches no files", str(cm.exception))

    def test_unknown_design_in_sweep(self) -> None:
        path = _write(BASE + '[sweep]\nrecipe = ["r"]\ndesign = ["zzz"]\narch = ["a"]\n')
        with self.assertRaises(ConfigError) as cm:
            load_project(path)
        self.assertEqual(cm.exception.line, 13)
        self.assertIn("zzz", str(cm.exception))
        self.assertTrue(str(cm.exception).startswith(f"{path}:13: "))

    def test_syntax_error_line(self) -> None:
        path = _write('[project]\nname = "t"\n\nbad = = 1\n')
        with self.assertRaises(ConfigError) as cm:
            load_project(path)
        self.assertEqual(cm.exception.line, 4)

    def test_param_sweep(self) -> None:
        path = _write(BASE + '[sweep]\nrecipe = ["r"]\ndesign = ["d"]\narch = ["a"]\n'
                      "seed = [1, 2]\n")
        proj = load_project(path)
        self.assertEqual(len(proj.runs), 2)
        self.assertEqual(proj.runs[0].params, {"seed": 1})
        self.assertEqual(proj.runs[1].params, {"seed": 2})

    def test_missing_file_no_line(self) -> None:
        with self.assertRaises(ConfigError) as cm:
            load_project(Path(tempfile.mkdtemp()) / "wyrd.toml")
        self.assertIsNone(cm.exception.line)


if __name__ == "__main__":
    unittest.main()
