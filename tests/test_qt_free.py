import ast
import tempfile
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


_QT = ("PySide6", "shiboken6")
_GUI = "wyrd.gui"


def _is_qt(name: str) -> bool:
    return any(name == q or name.startswith(q + ".") for q in _QT)


def _is_gui(name: str) -> bool:
    return name == _GUI or name.startswith(_GUI + ".")


def _bad_module(name: str) -> bool:
    return _is_qt(name) or _is_gui(name)


def _import_from_bad(node: ast.ImportFrom) -> bool:
    module = node.module or ""
    if node.level == 0 and _bad_module(module):
        return True
    return node.level == 0 and module == "wyrd" and any(a.name == "gui" for a in node.names)


def _dynamic_bad(node: ast.Call) -> bool:
    func = node.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
    if name not in ("import_module", "__import__") or not node.args:
        return False
    arg = node.args[0]
    return isinstance(arg, ast.Constant) and isinstance(arg.value, str) and _bad_module(arg.value)


def _node_bad(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(_bad_module(a.name) for a in node.names)
    if isinstance(node, ast.ImportFrom):
        return _import_from_bad(node)
    return isinstance(node, ast.Call) and _dynamic_bad(node)


def _dynamic_odin3(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
    if name not in ("import_module", "__import__") or not node.args:
        return False
    arg = node.args[0]
    return isinstance(arg, ast.Constant) and isinstance(arg.value, str) and _is_odin3(arg.value)


def dynamic_odin3_imports(path: Path) -> list[int]:
    """Line numbers of import_module/__import__ calls naming odin3 by a string literal."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [getattr(n, "lineno", 0) for n in ast.walk(tree) if _dynamic_odin3(n)]


def imports_qt_or_gui(path: Path) -> bool:
    """True when the file imports Qt or ``wyrd.gui``, statically or by a string name."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(_node_bad(node) for node in ast.walk(tree))


def _midgard_violation(rel: Path, name: str) -> bool:
    top = rel.parts[0] if len(rel.parts) > 1 else rel.name
    root = name.split(".")[0]
    if root in ("socket", "urllib", "http", "requests"):
        return True
    if root == "pygame":
        return top not in ("ui", "app.py")
    if root == "PySide6":
        return top != "editors"
    if top == "model" and root == "odin3":
        return True
    is_bifrost = name == "wyrd.bifrost" or name.startswith("wyrd.bifrost.")
    return is_bifrost and top == "model" and rel.as_posix() != "model/controllers.py"


class QtFreeTest(unittest.TestCase):
    def test_no_pyside_outside_gui(self) -> None:
        gui = ROOT / "wyrd" / "gui"
        editors = ROOT / "wyrd" / "midgard" / "editors"
        offenders = [
            str(p.relative_to(ROOT))
            for p in sorted((ROOT / "wyrd").rglob("*.py"))
            if gui not in p.parents and editors not in p.parents and imports_qt_or_gui(p)
        ]
        self.assertEqual(offenders, [])

    def test_guard_flags_planted_examples(self) -> None:
        planted = [
            "import PySide6.QtWidgets",
            "from PySide6 import QtCore",
            "import shiboken6",
            "from shiboken6 import wrapInstance",
            "import wyrd.gui.app",
            "from wyrd.gui import app",
            "from wyrd import gui",
            "import importlib\nimportlib.import_module('PySide6.QtGui')",
            "__import__('shiboken6')",
            "import importlib as i\ni.import_module('wyrd.gui.main')",
        ]
        clean = [
            "import wyrd.guimodel.runs",
            "from wyrd.guimodel import runs",
            "from wyrd import report",
            "import importlib\nimportlib.import_module('json')",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for i, src in enumerate(planted):
                f = Path(tmp) / f"p{i}.py"
                f.write_text(src + "\n", encoding="utf-8")
                self.assertTrue(imports_qt_or_gui(f), src)
            for i, src in enumerate(clean):
                f = Path(tmp) / f"c{i}.py"
                f.write_text(src + "\n", encoding="utf-8")
                self.assertFalse(imports_qt_or_gui(f), src)

    def test_odin3_only_in_backend(self) -> None:
        bad: list[str] = []
        for path in sorted((ROOT / "wyrd").rglob("*.py")):
            for line, name, in_function in imports_of(path):
                if _is_odin3(name) and (path != BACKEND or not in_function):
                    bad.append(f"{path.relative_to(ROOT)}:{line}: import {name}")
            if path != BACKEND:
                bad += [
                    f"{path.relative_to(ROOT)}:{line}: dynamic import of odin3"
                    for line in dynamic_odin3_imports(path)
                ]
        self.assertEqual(bad, [])

    def test_odin3_guard_flags_dynamic_examples(self) -> None:
        planted = [
            "import importlib\nimportlib.import_module('odin3')",
            "import importlib\nimportlib.import_module('odin3.sim')",
            "__import__('odin3')",
        ]
        clean = ["import importlib\nimportlib.import_module('json')", "__import__('odin3x')"]
        with tempfile.TemporaryDirectory() as tmp:
            for i, src in enumerate(planted):
                f = Path(tmp) / f"p{i}.py"
                f.write_text(src + "\n", encoding="utf-8")
                self.assertTrue(dynamic_odin3_imports(f), src)
            for i, src in enumerate(clean):
                f = Path(tmp) / f"c{i}.py"
                f.write_text(src + "\n", encoding="utf-8")
                self.assertFalse(dynamic_odin3_imports(f), src)

    def test_sim_is_qt_and_pygame_free(self) -> None:
        bad: list[str] = []
        for sub in ("bifrost", "guimodel"):
            for path in sorted((ROOT / "wyrd" / sub).rglob("*.py")):
                for line, name, _ in imports_of(path):
                    if name.split(".")[0] in ("PySide6", "pygame"):
                        bad.append(f"{path.relative_to(ROOT)}:{line}: import {name}")
        self.assertEqual(bad, [])

    def test_midgard_import_rules(self) -> None:
        mid = ROOT / "wyrd" / "midgard"
        bad: list[str] = []
        for path in sorted(mid.rglob("*.py")):
            rel = path.relative_to(mid)
            for line, name, _ in imports_of(path):
                if _midgard_violation(rel, name):
                    bad.append(f"{path.relative_to(ROOT)}:{line}: import {name}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
