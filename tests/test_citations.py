import tempfile
import unittest
from pathlib import Path

from wyrd import citations
from wyrd.citations import Citation, load, render_markdown

ROOT = Path(__file__).parent.parent
IDS = [
    "vtr", "odin2", "odin", "odin3", "abc", "yosys", "parmys", "slang", "qt", "pygame-ce",
    "verilog-town", "graphcrunch", "theryx", "gate-breaker",
]  # fmt: skip


class CitationsTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def _write(self, text: str) -> Path:
        path = self.dir / "c.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_ids(self) -> None:
        self.assertEqual([c.id for c in load()], IDS)

    def test_required_fields(self) -> None:
        for c in load():
            self.assertTrue(c.id and c.name)
            self.assertIn(c.kind, {"paper", "software", "project"})

    def test_bad_file(self) -> None:
        bad = self._write('[[item]]\nid = "x1"\nkind = "paper"\n')
        with self.assertRaises(ValueError) as cm:
            load(bad)
        self.assertIn("x1", str(cm.exception))
        item = '[[item]]\nid = "d"\nname = "D"\nkind = "paper"\n'
        with self.assertRaises(ValueError):
            load(self._write(item + item))

    def test_markdown_table(self) -> None:
        items = [
            Citation("a", "A", "paper", authors="X", year=2020, title="T", venue="V"),
            Citation("b", "B", "software", url="http://b"),
        ]
        lines = render_markdown(items).splitlines()
        self.assertIn("| Name | Kind | Role | Reference | Link |", lines)
        rows = [ln for ln in lines if ln.startswith(("| A", "| B"))]
        self.assertEqual(len(rows), 2)
        self.assertIn("X (2020). T. V.", render_markdown(items))

    def test_docs_in_sync(self) -> None:
        text = (ROOT / "docs" / "CITATIONS.md").read_text(encoding="utf-8")
        self.assertEqual(text, render_markdown(load()))

    def test_packaged(self) -> None:
        self.assertTrue((ROOT / "wyrd" / "data" / "citations.toml").is_file())
        self.assertTrue(callable(citations.main))


if __name__ == "__main__":
    unittest.main()
