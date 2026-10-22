import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _imports_pyside(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name.startswith("PySide6") for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("PySide6"):
            return True
    return False


class QtFreeTest(unittest.TestCase):
    def test_no_pyside_outside_gui(self) -> None:
        gui = ROOT / "wyrd" / "gui"
        offenders = [
            str(p.relative_to(ROOT))
            for p in sorted((ROOT / "wyrd").rglob("*.py"))
            if gui not in p.parents and _imports_pyside(p)
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
