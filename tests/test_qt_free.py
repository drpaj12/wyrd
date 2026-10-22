import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
BACKEND = ROOT / "wyrd" / "bifrost" / "backend.py"
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _is_odin3(name: str) -> bool:
    return name == "odin3" or name.startswith("odin3.")


def _module_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
        return [node.module]
    return []


def _walk(node: ast.AST, in_function: bool, out: list[tuple[int, str, bool]]) -> None:
    for name in _module_names(node):
        out.append((getattr(node, "lineno", 0), name, in_function))
    inside = in_function or isinstance(node, FUNCTIONS)
    for child in ast.iter_child_nodes(node):
        _walk(child, inside, out)


def imports_of(path: Path) -> list[tuple[int, str, bool]]:
    found: list[tuple[int, str, bool]] = []
    _walk(ast.parse(path.read_text(encoding="utf-8")), False, found)
    return found


class QtFreeTest(unittest.TestCase):
    def test_odin3_only_in_backend(self) -> None:
        bad: list[str] = []
        for path in sorted((ROOT / "wyrd").rglob("*.py")):
            for line, name, in_function in imports_of(path):
                if _is_odin3(name) and (path != BACKEND or not in_function):
                    bad.append(f"{path.relative_to(ROOT)}:{line}: import {name}")
        self.assertEqual(bad, [])

    def test_sim_is_qt_and_pygame_free(self) -> None:
        bad: list[str] = []
        for sub in ("bifrost", "guimodel"):
            for path in sorted((ROOT / "wyrd" / sub).rglob("*.py")):
                for line, name, _ in imports_of(path):
                    if name.split(".")[0] in ("PySide6", "pygame"):
                        bad.append(f"{path.relative_to(ROOT)}:{line}: import {name}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
