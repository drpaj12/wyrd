import fnmatch
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent


class PackagingTest(unittest.TestCase):
    def test_every_package_is_configured(self) -> None:
        cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        setuptools = cfg["tool"]["setuptools"]
        explicit = setuptools.get("packages")
        found = {
            ".".join(init.parent.relative_to(ROOT).parts)
            for init in (ROOT / "wyrd").rglob("__init__.py")
        }
        self.assertIn("wyrd.steps", found)
        self.assertIn("wyrd.bifrost", found)
        self.assertIn("wyrd.guimodel", found)
        self.assertIn("wyrd.gui", found)
        if isinstance(explicit, list):
            covered = set(explicit)
        else:
            patterns = setuptools["packages"]["find"]["include"]
            covered = {n for n in found if any(fnmatch.fnmatchcase(n, p) for p in patterns)}
        self.assertEqual(found - covered, set())

    def test_gui_extra_and_script(self) -> None:
        cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = cfg["project"]
        self.assertEqual(project["dependencies"], [])
        self.assertEqual(project["optional-dependencies"]["gui"], ["PySide6-Essentials>=6.6,<7"])
        self.assertEqual(project["gui-scripts"]["wyrd-gui"], "wyrd.gui.app:main")
        self.assertIn("data/*.toml", cfg["tool"]["setuptools"]["package-data"]["wyrd"])

    def test_sim_extra(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["optional-dependencies"]["sim"], ["odin3>=1.0.3"])
        self.assertEqual(project["dependencies"], [])

    def test_midgard_extra(self) -> None:
        cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = cfg["project"]
        extras = project["optional-dependencies"]
        self.assertEqual(extras["midgard"], ["pygame-ce>=2.5,<3", "odin3>=1.0.3", *extras["gui"]])
        self.assertEqual(project["gui-scripts"]["midgard-editor"],
                         "wyrd.midgard.editors.level_editor:main")
        self.assertEqual(project["gui-scripts"]["midgard"], "wyrd.midgard.app:main")
        data = cfg["tool"]["setuptools"]["package-data"]["wyrd"]
        self.assertIn("midgard/assets/**/*", data)
        self.assertIn("data/*.toml", data)
        self.assertEqual(project["dependencies"], [])
        patterns = cfg["tool"]["setuptools"]["packages"]["find"]["include"]
        for name in ("wyrd.midgard", "wyrd.midgard.model", "wyrd.midgard.ui"):
            self.assertTrue((ROOT / Path(*name.split(".")) / "__init__.py").exists(), name)
            self.assertTrue(any(fnmatch.fnmatchcase(name, p) for p in patterns), name)


if __name__ == "__main__":
    unittest.main()
