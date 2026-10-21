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
        if isinstance(explicit, list):
            covered = set(explicit)
        else:
            patterns = setuptools["packages"]["find"]["include"]
            covered = {n for n in found if any(fnmatch.fnmatchcase(n, p) for p in patterns)}
        self.assertEqual(found - covered, set())


if __name__ == "__main__":
    unittest.main()
