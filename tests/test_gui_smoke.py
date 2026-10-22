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

if HAVE_QT:
    from PySide6.QtCore import QCoreApplication, QSettings
    from PySide6.QtWidgets import QApplication, QTreeWidgetItem

    from wyrd.gui.mainwindow import MainWindow

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


if __name__ == "__main__":
    unittest.main()
