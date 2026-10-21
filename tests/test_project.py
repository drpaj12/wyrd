"""Tests for wyrd.project."""

from __future__ import annotations

import os
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

SWEEP = '[sweep]\nrecipe = ["r"]\ndesign = ["d"]\narch = ["a"]\n'


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

    def _err(self, text: str, with_file: bool = True) -> ConfigError:
        with self.assertRaises(ConfigError) as cm:
            load_project(_write(text, with_file))
        return cm.exception

    def test_absolute_and_dotdot_patterns(self) -> None:
        outer = Path(tempfile.mkdtemp())
        (outer / "ext").mkdir()
        (outer / "ext" / "z.v").write_text("module z; endmodule\n")
        (outer / "ext" / "z.v.bak").write_text("")
        proj_dir = outer / "proj"
        proj_dir.mkdir()
        (proj_dir / "x.v").write_text("module x; endmodule\n")
        text = (BASE.replace('["x.v"]', f'["../ext/*.v", "{outer}/ext/z.v", "x.v"]')
                + SWEEP)
        path = proj_dir / "wyrd.toml"
        path.write_text(text)
        files = load_project(path).designs["d"].files
        self.assertEqual(files, (
            (outer / "ext" / "z.v").resolve(), (proj_dir / "x.v").resolve()))

    def test_env_var_expansion(self) -> None:
        outer = Path(tempfile.mkdtemp())
        (outer / "q.v").write_text("")
        os.environ["WYRD_T_DIR"] = str(outer)
        self.addCleanup(os.environ.pop, "WYRD_T_DIR", None)
        for form in ("${WYRD_T_DIR}", "$WYRD_T_DIR"):
            path = _write(BASE.replace('"x.v"', f'"{form}/q.v"') + SWEEP, False)
            files = load_project(path).designs["d"].files
            self.assertEqual(files, ((outer / "q.v").resolve(),))

    def test_unset_env_var(self) -> None:
        os.environ.pop("WYRD_T_UNSET", None)
        e = self._err(BASE.replace('"x.v"', '"${WYRD_T_UNSET}/q.v"') + SWEEP)
        self.assertIn("WYRD_T_UNSET", str(e))
        self.assertEqual(e.line, 6)

    def test_absolute_empty_match(self) -> None:
        e = self._err(BASE.replace('"x.v"', '"/nonexistent-wyrd/*.v"') + SWEEP)
        self.assertIn("/nonexistent-wyrd/*.v", str(e))
        self.assertIn("'d'", str(e))

    def test_duplicate_design(self) -> None:
        text = BASE.replace("[recipe.r]", '[[design]]\nname = "d"\nfiles = ["x.v"]\n\n[recipe.r]')
        e = self._err(text + SWEEP)
        self.assertIn("duplicate", str(e))
        self.assertEqual(e.line, 9)

    def test_empty_sweep_lists(self) -> None:
        for key in ("recipe", "design", "arch", "seed"):
            body = {"recipe": '["r"]', "design": '["d"]', "arch": '["a"]'}
            body["seed"] = "[1]"
            body[key] = "[]"
            sweep = "[sweep]\n" + "".join(f"{k} = {v}\n" for k, v in body.items())
            e = self._err(BASE + sweep)
            self.assertIn(key, str(e))
            self.assertIn("empty", str(e))
            self.assertEqual(e.line, 12 + list(body).index(key))

    def test_design_wrong_shape(self) -> None:
        tail = '[recipe.r]\nsteps = [{ use = "u" }]\n' + SWEEP
        self._err('[project]\nname = "t"\ndesign = "x"\n' + tail)
        self._err('[project]\nname = "t"\n[design]\nname = "d"\n' + tail)

    def test_wrong_types(self) -> None:
        for old, new in (('files = ["x.v"]', 'files = "x.v"'),
                         ('files = ["x.v"]', "files = [1]"),
                         ('files = ["x.v"]', 'files = ["x.v"]\ntop = 3'),
                         ('steps = [{ use = "odin3-flow" }]', "steps = [1]"),
                         ('steps = [{ use = "odin3-flow" }]', "steps = [{ use = 1 }]"),
                         ('steps = [{ use = "odin3-flow" }]', "steps = []")):
            self._err(BASE.replace(old, new) + SWEEP)

    def test_missing_required(self) -> None:
        self._err(BASE.replace('name = "t"', "") + SWEEP)
        e = self._err(BASE.replace('name = "d"', "") + SWEEP)
        self.assertEqual(e.line, 4)
        e = self._err(BASE.replace('files = ["x.v"]', "") + SWEEP)
        self.assertIn("files", str(e))

    def test_bad_utf8(self) -> None:
        path = _write(BASE + SWEEP)
        path.write_bytes(b'[project]\nname = "\xff\xfe"\n')
        with self.assertRaises(ConfigError):
            load_project(path)

    def test_line_lookup_from_header(self) -> None:
        # steps key appears earlier in an unrelated recipe and a design 'files' precedes.
        text = ('[project]\nname = "t"\n\n[[design]]\nname = "d1"\nfiles = ["x.v"]\n\n'
                '[[design]]\nname = "d2"\nfiles = "bad"\n\n'
                '[recipe.a]\nsteps = [{ use = "u" }]\n\n[recipe.b]\nsteps = []\n')
        e = self._err(text + SWEEP)
        self.assertEqual(e.line, 10)
        text = text.replace('files = "bad"', 'files = ["x.v"]')
        e = self._err(text + SWEEP)
        self.assertEqual(e.line, 16)

    def test_root_resolved(self) -> None:
        path = _write(BASE + SWEEP)
        rel = Path(os.path.relpath(path))
        self.assertEqual(load_project(rel).root, path.resolve().parent)


if __name__ == "__main__":
    unittest.main()
