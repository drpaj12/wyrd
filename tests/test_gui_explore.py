"""Structures and Timing tabs of the Mímir dock; Qt runs offscreen. Synthetic v5 store."""

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
    from tests.qt_helpers import dispose, qapp
    from tests.test_gui_mimir import settle, wait
    from wyrd.gui.mimirpanel import MimirPanel
    from wyrd.guimodel import heat
    from wyrd.guimodel.heat import HeatModel

    def setUpModule() -> None:
        qapp()


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class ExploreTabsTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.panel = MimirPanel()
        self.addCleanup(dispose, self.panel)

    def open(self, timing: bool) -> MimirPanel:
        db = mimir_fixture.build(self.dir / "s.db", version="5" if timing else "4", timing=timing)
        p = self.panel
        self.assertTrue(wait(p, "open", lambda: p.open_store(db)))
        p._pool.waitForDone()
        settle()
        return p

    def drain(self) -> None:
        self.panel._pool.waitForDone()
        settle()
        self.panel._pool.waitForDone()
        settle()

    def test_structures_tab(self) -> None:
        p = self.open(True)
        self.drain()
        s = p.structs
        self.assertEqual(s.design.currentText(), "s/d1")
        self.assertEqual(s.pane.grid.rowCount(), 2)
        s.level.setCurrentText("lut")
        s.reload()
        self.drain()
        self.assertEqual(s.pane.grid.rowCount(), 1)
        self.assertEqual(len(s.chart.points), 1)

    def test_timing_tab(self) -> None:
        p = self.open(True)
        self.drain()
        t = p.timing_tab
        self.assertEqual(t.run.count(), 2)
        self.assertEqual(t.hist.counts[19], 4)
        self.assertIn("Near-critical paths", t.summary.text())
        self.assertEqual(t.pane.grid.rowCount(), 1)
        self.assertTrue(t.open_button.isEnabled())
        self.assertEqual(t.x_metric.currentText(), "vpr.logic_clbs")  # area-like metric first
        t.plot()
        self.drain()
        self.assertEqual(len(t.chart.points), 2)

    def test_open_in_source_view_emits_model(self) -> None:
        p = self.open(True)
        self.drain()
        got: list[object] = []
        p.heat_requested.connect(got.append)
        p.timing_tab._open_clicked()
        self.drain()
        self.assertEqual(len(got), 1)
        model = got[0]
        assert isinstance(model, HeatModel)
        self.assertFalse(model.has_paths)
        self.assertTrue(model.select(heat.Scope(heat.SCOPE_NEAR)))

    def test_store_without_timing_shows_note(self) -> None:
        p = self.open(False)
        self.drain()
        self.assertIn("no timing tables", p.timing_tab.summary.text())
        self.assertEqual(p.timing_tab.run.count(), 0)
        self.assertEqual(p.structs.design.count(), 0)


if __name__ == "__main__":
    unittest.main()
