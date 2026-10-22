"""GUI smoke tests; Qt runs offscreen."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import tempfile
import unittest
from pathlib import Path

HAVE_QT = importlib.util.find_spec("PySide6") is not None
ROOT = Path(__file__).parent.parent
SAMPLES = ROOT / "samples"
LOGS = ROOT / "tests" / "data" / "logs"

if HAVE_QT:
    from PySide6.QtCore import QCoreApplication, QSettings
    from PySide6.QtWidgets import QApplication, QTreeWidgetItem

    from wyrd.gui.mainwindow import MainWindow
    from wyrd.gui.messages import MessagesPane
    from wyrd.gui.sourceview import SourceView
    from wyrd.guimodel.logparse import parse_log

    _APP: QCoreApplication | None = None

    def setUpModule() -> None:
        global _APP
        _APP = QApplication.instance() or QApplication([])


def child_count(item: "QTreeWidgetItem", i: int) -> int:
    child = item.child(i)
    assert child is not None
    return child.childCount()


def window(tmp: Path) -> "MainWindow":
    settings = QSettings(str(tmp / "s.ini"), QSettings.Format.IniFormat)
    return MainWindow(settings, silent=True)


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class ShellTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_opens_samples(self) -> None:
        w = window(self.tmp)
        self.assertTrue(w.open_project(SAMPLES))
        tree = w.project_tree
        self.assertEqual(tree.topLevelItemCount(), 3)
        first = tree.topLevelItem(0)
        assert first is not None
        self.assertEqual(first.childCount(), 3)
        counts = [child_count(first, i) for i in range(3)]
        self.assertEqual(counts, [1, 3, 3])
        self.assertEqual(w.windowTitle(), "Wyrd III - samples")

    def test_state_persistence(self) -> None:
        w = window(self.tmp)
        w.open_project(SAMPLES)
        w.close()
        s = QSettings(str(self.tmp / "s.ini"), QSettings.Format.IniFormat)
        self.assertEqual(s.value("lastProject"), str(SAMPLES))
        s.setValue("recentProjects", [str(self.tmp / f"p{i}") for i in range(10)])
        s.sync()
        w2 = window(self.tmp)
        w2.open_project(SAMPLES)
        recent = w2.settings.value("recentProjects")
        self.assertEqual(len(recent), 8)
        self.assertEqual(recent[0], str(SAMPLES))

    def test_bad_toml_opens(self) -> None:
        d = self.tmp / "bad"
        d.mkdir()
        (d / "wyrd.toml").write_text("[project]\nname = 1\n", encoding="utf-8")
        w = window(self.tmp)
        self.assertTrue(w.open_project(d))
        self.assertIsNone(w.project)
        self.assertIn("wyrd.toml:", w.statusBar().currentMessage())

    def test_missing_toml(self) -> None:
        d = self.tmp / "empty"
        d.mkdir()
        self.assertFalse(window(self.tmp).open_project(d))


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class ViewerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_source_view(self) -> None:
        view = SourceView()
        src = SAMPLES / "designs" / "single" / "bm_DL_2_4_encoder.v"
        self.assertTrue(view.open_file(src, line=3))
        self.assertIn("module", view.text.toPlainText())
        self.assertEqual(view.text.textCursor().blockNumber(), 2)
        big = self.tmp / "big.v"
        big.write_bytes(b"a" * 2_000_001)
        self.assertFalse(view.open_file(big))
        self.assertTrue(view.text.toPlainText().startswith("Cannot show"))
        odd = self.tmp / "odd.v"
        odd.write_bytes(b"\xff\xfe module")
        self.assertTrue(view.open_file(odd))
        self.assertIn("module", view.text.toPlainText())

    def test_highlighter_formats(self) -> None:
        view = SourceView()
        view.open_file(SAMPLES / "designs" / "single" / "bm_DL_2_4_encoder.v")
        block = view.text.document().firstBlock()
        layout = block.layout()
        assert layout is not None
        found = False
        while block.isValid() and not found:
            layout = block.layout()
            assert layout is not None
            found = bool(layout.formats())
            block = block.next()
        self.assertTrue(found)

    def test_messages_pane(self) -> None:
        pane = MessagesPane()
        msgs = parse_log(LOGS / "odin3_sample.log")
        pane.set_messages(msgs, [self.tmp], [])
        self.assertEqual(pane.count(), 6)
        pane.filter.setCurrentText("Errors")
        self.assertEqual(pane.count(), 3)
        pane.filter.setCurrentText("All")
        got: list[tuple[Path, int]] = []
        pane.location_activated.connect(lambda p, n: got.append((p, n)))
        pane.table.cellDoubleClicked.emit(0, 0)
        self.assertEqual(got, [(msgs[0].log, 3)])


if __name__ == "__main__":
    unittest.main()
