import shutil
import tempfile
import unittest
from pathlib import Path

from wyrd.guimodel import tomledit
from wyrd.guimodel.tomledit import AddDesignError, add_design, relative_files, validate_text
from wyrd.project import load_project

DATA = Path(__file__).parent / "data" / "proj_ok"


class TomlEditTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(DATA, self.root, dirs_exist_ok=True)
        self.path = self.root / "wyrd.toml"
        self.text = self.path.read_text(encoding="utf-8")

    def test_valid_text(self) -> None:
        v = validate_text(self.path, self.text)
        self.assertTrue(v.ok)
        self.assertEqual(v.runs, len(load_project(self.path).runs))
        self.assertIsNone(v.diagnostic)

    def test_broken_key_has_line_and_no_path(self) -> None:
        v = validate_text(self.path, self.text.replace('name = "', 'nme = "', 1))
        self.assertFalse(v.ok)
        assert v.diagnostic is not None
        self.assertIsInstance(v.diagnostic.line, int)
        self.assertNotIn(str(self.root), v.diagnostic.message)

    def test_syntax_error_line(self) -> None:
        bad = self.text.replace("[run]", "[run]\nbad = = 1", 1)
        want = bad.splitlines().index("bad = = 1") + 1
        v = validate_text(self.path, bad)
        assert v.diagnostic is not None
        self.assertEqual(v.diagnostic.line, want)

    def test_unset_variable(self) -> None:
        v = validate_text(self.path, self.text.replace("src/b.v", "$X_NOPE/b.v", 1))
        self.assertFalse(v.ok)

    def test_add_design_block_exact(self) -> None:
        got = add_design(self.text, "newd", ["a.v", "sub/b.v"], "t", False)
        want = '\n[[design]]\nname = "newd"\nfiles = ["a.v", "sub/b.v"]\ntop = "t"\n'
        self.assertEqual(got, self.text + want)
        no_top = add_design(self.text, "newd", ["a.v"], None, False)
        self.assertNotIn("top", no_top[len(self.text) :])
        bare = add_design("[project]", "n", ["a.v"], None, False)
        self.assertTrue(bare.startswith("[project]\n\n[[design]]"))

    def test_add_to_sweep_single_line(self) -> None:
        got = add_design(self.text, "newd", ["src/a.v"], None, True)
        self.assertIn('design = ["one", "two", "newd"]', got)
        v = validate_text(self.path, got)
        self.assertTrue(v.ok, v.diagnostic)
        names = {r.design.name for r in load_project(self.path, text=got).runs}
        self.assertIn("newd", names)

    def test_add_to_sweep_multi_line(self) -> None:
        multi = self.text.replace('design = ["one", "two"]', 'design = [\n  "one",\n  "two"\n]')
        got = add_design(multi, "newd", ["src/a.v"], None, True)
        self.assertTrue(validate_text(self.path, got).ok)
        trailing = self.text.replace('design = ["one", "two"]', 'design = [\n  "one",\n  "two",\n]')
        got2 = add_design(trailing, "newd", ["src/a.v"], None, True)
        self.assertTrue(validate_text(self.path, got2).ok)

    def test_sweep_not_found_keeps_block(self) -> None:
        text = '[project]\nname = "x"\nsweep = { design = ["a"] }\n'
        with self.assertRaises(AddDesignError) as cm:
            add_design(text, "newd", ["a.v"], None, True)
        self.assertIn("[[design]]", cm.exception.text)
        self.assertIn("Cannot edit [sweep] design automatically", str(cm.exception))

    def test_duplicate_name_is_reported_with_line(self) -> None:
        got = add_design(self.text, "one", ["src/a.v"], None, False)
        v = tomledit.validate_text(self.path, got)
        self.assertFalse(v.ok)
        assert v.diagnostic is not None
        self.assertIsNotNone(v.diagnostic.line)
        self.assertIn("duplicate", v.diagnostic.message)

    def test_relative_files(self) -> None:
        self.assertEqual(relative_files(self.root, [self.root / "x" / "a.v"]), ["x/a.v"])


if __name__ == "__main__":
    unittest.main()
