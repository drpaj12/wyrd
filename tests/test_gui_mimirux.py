"""Mímir dock fixes: timing under another source, current design, About toggle, heat button.

Qt runs offscreen. The synthetic store has design d1 under two sources, timing only under exp-a-1.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import tempfile
import unittest
from pathlib import Path

from tests import mimir_fixture

HAVE_QT = importlib.util.find_spec("PySide6") is not None

if HAVE_QT:
    from PySide6.QtCore import QCoreApplication, QSettings, Qt
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from tests.qt_helpers import dispose, qapp
    from tests.test_gui_mimir import settle, wait
    from wyrd.gui.helpbox import HelpBox
    from wyrd.gui.mainwindow import MainWindow
    from wyrd.gui.mimirpanel import HEAT_TIP_NO_ROWS, MimirPanel
    from wyrd.guimodel import layoutspec as ls
    from wyrd.guimodel.heat import HeatModel

    def setUpModule() -> None:
        qapp()


def drain(p: MimirPanel) -> None:
    for _ in range(6):
        p._pool.waitForDone()
        settle()


def pick(p: MimirPanel, name: str, source: str) -> None:
    for i in range(p.designs.count()):
        data = p.designs.item(i).data(Qt.ItemDataRole.UserRole)
        if data and tuple(data) == (source, name):
            p.designs.setCurrentRow(i)
            break
    else:
        raise AssertionError(f"{name} [{source}] not listed")
    drain(p)


def highlighted(p: MimirPanel) -> tuple[str, str]:
    items = p.designs.selectedItems()
    if not items:
        return ("", "")
    source, name = items[0].data(Qt.ItemDataRole.UserRole)
    return (str(source), str(name))


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class MimirUxTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = mimir_fixture.build(self.dir / "s.db", version="5", timing=True)
        self.ini = str(self.dir / "s.ini")
        self.panel = self.make()

    def make(self) -> MimirPanel:
        p = MimirPanel(QSettings(self.ini, QSettings.Format.IniFormat))
        self.addCleanup(dispose, p)
        p.show()
        return p

    def open(self, p: MimirPanel) -> None:
        self.assertTrue(wait(p, "open", lambda: p.open_store(self.db)))
        drain(p)

    def test_timing_falls_back_to_the_source_that_has_it(self) -> None:
        p = self.panel
        self.open(p)
        pick(p, "d1", "exp-a-2")
        text = p.timing_tab.summary.text()
        self.assertIn("Timing from source exp-a-1; the picked source exp-a-2 has none", text)
        self.assertEqual(p.timing_tab.current_run(), "r1")
        self.assertIn("Structures from source exp-a-1", p.structs.status.text())
        self.assertTrue(p.heat_button.isEnabled())
        self.assertEqual(p.current_line.text().split()[2], "d1")

    def test_list_marks_entries_with_timing(self) -> None:
        p = self.panel
        self.open(p)
        texts = {
            tuple(p.designs.item(i).data(Qt.ItemDataRole.UserRole)): p.designs.item(i).text()
            for i in range(p.designs.count())
        }
        self.assertTrue(texts[("exp-a-1", "d1")].endswith("timing"))
        self.assertFalse(texts[("exp-a-2", "d1")].endswith("timing"))
        self.assertFalse(texts[("exp-a-1", "d3")].endswith("timing"))

    def test_heat_button_states_and_tooltips(self) -> None:
        p = self.panel
        self.assertFalse(p.heat_button.isEnabled())
        self.open(p)
        self.assertFalse(p.heat_button.isEnabled())
        self.assertIn("Click a design", p.heat_button.toolTip())
        pick(p, "d3", "exp-a-1")
        self.assertFalse(p.heat_button.isEnabled())
        self.assertEqual(p.heat_button.toolTip(), HEAT_TIP_NO_ROWS)
        pick(p, "d1", "exp-a-1")
        self.assertTrue(p.heat_button.isEnabled())
        self.assertIn("hot", p.heat_button.toolTip())

    def test_heat_button_emits_a_model(self) -> None:
        p = self.panel
        self.open(p)
        pick(p, "d1", "exp-a-1")
        got: list[object] = []
        p.heat_requested.connect(got.append)
        self.assertTrue(wait(p, "trows", p.heat_button.click))
        self.assertEqual(len(got), 1)
        self.assertIsInstance(got[0], HeatModel)

    def test_refill_never_changes_the_current_design(self) -> None:
        p = self.panel
        self.open(p)
        pick(p, "d2", "exp-a-1")
        p.filter.setText("d")
        drain(p)
        self.assertEqual(highlighted(p), ("exp-a-1", "d2"))
        p.filter.setText("d3")  # d2 is no longer listed: nothing highlighted, design kept
        drain(p)
        self.assertEqual(highlighted(p), ("", ""))
        self.assertIn("d2", p.current_line.text())
        p.designs.setFocus(Qt.FocusReason.TabFocusReason)  # focus must not select row 0
        QCoreApplication.processEvents()
        drain(p)
        self.assertEqual(p._current_design, "d2")
        p.filter.setText("")
        drain(p)
        self.assertEqual(highlighted(p), ("exp-a-1", "d2"))
        p.source.setCurrentIndex(2)  # a source change refills as well
        p.fill_designs()
        drain(p)
        self.assertEqual(p._current_design, "d2")
        self.assertEqual(highlighted(p), ("", ""))

    def test_reopen_last_restores_design_and_source(self) -> None:
        p = self.panel
        self.open(p)
        pick(p, "d1", "exp-a-2")
        q = self.make()  # a new session with the same settings
        q.set_last(str(self.db))
        self.assertTrue(wait(q, "open", q.last_button.click))
        drain(q)
        self.assertEqual((q._current_source, q._current_design), ("exp-a-2", "d1"))
        self.assertEqual(highlighted(q), ("exp-a-2", "d1"))
        self.assertIn("d1", q.current_line.text())

    def test_plain_open_does_not_restore(self) -> None:
        p = self.panel
        self.open(p)
        pick(p, "d1", "exp-a-2")
        q = self.make()
        self.open(q)
        self.assertEqual(q._current_design, "")
        self.assertEqual(highlighted(q), ("", ""))


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class HelpBoxToggleTest(unittest.TestCase):
    def test_collapsed_box_keeps_its_button(self) -> None:
        host = QWidget()
        lay = QVBoxLayout(host)
        box = HelpBox("Timing")
        lay.addWidget(box)
        lay.addWidget(QWidget(), 1)
        host.resize(400, 300)
        host.show()
        self.addCleanup(dispose, host)
        for shown in (False, True, False):
            box.set_shown(shown)
            settle()
            self.assertGreater(box.toggle.height(), 0)
            self.assertGreaterEqual(box.height(), box.toggle.height())
        host.resize(300, 40)
        settle()
        self.assertGreater(box.toggle.height(), 0)

    def test_toggle_stays_after_small_resize_and_preset_switch(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings = QSettings(str(Path(tmp.name) / "s.ini"), QSettings.Format.IniFormat)
        w = MainWindow(settings, silent=True)
        w.resize(1366, 768)
        w.show()
        settle()

        def close() -> None:
            w._closing = True
            dispose(w)

        self.addCleanup(close)
        boxes = w.mimir.findChildren(HelpBox)
        self.assertGreater(len(boxes), 5)
        for box in boxes:
            box.set_shown(False)
        for preset in [p.name for p in ls.PRESETS]:
            assert w.viewlayout is not None
            w.viewlayout.apply_preset(preset)
            w.resize(900, 200)
            settle()
            if not w.mimir.isVisible():  # this preset parks the Mímir dock
                continue
            for i in range(w.mimir.tabs.count()):
                w.mimir.tabs.setCurrentIndex(i)
                settle()
                page = w.mimir.tabs.widget(i)
                assert page is not None
                for box in page.findChildren(HelpBox):
                    self.assertGreater(box.toggle.height(), 0, (preset, i))
                    self.assertTrue(box.toggle.isVisible(), (preset, i))


if __name__ == "__main__":
    unittest.main()
