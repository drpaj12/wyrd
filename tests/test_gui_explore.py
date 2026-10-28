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
    from PySide6.QtCore import Qt

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


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class SummaryTextTest(unittest.TestCase):
    def text(self, **summary: object) -> str:
        from wyrd import mimirview
        from wyrd.gui.mimirexplore import summary_text

        return summary_text(mimirview.TimingRunInfo("r", "label", dict(summary), [0] * 20))

    def test_lower_bound_only_for_report(self) -> None:
        self.assertIn("lower bound (dmax from report)", self.text(dmax_source="report"))
        for kind in ("exhaustive", "full-report"):
            t = self.text(dmax_source=kind)
            self.assertIn("rit is exact", t)
            self.assertNotIn("lower bound", t)

    def test_truncation_unknown(self) -> None:
        self.assertIn("truncation unknown", self.text(trunc_090=-1, trunc_095=-1, trunc_099=-1))
        self.assertIn("not truncated", self.text(trunc_090=0, trunc_095=0, trunc_099=0))
        self.assertIn("TRUNCATED", self.text(trunc_090=1, trunc_095=0, trunc_099=0))

    def test_area_proxy(self) -> None:
        from wyrd.gui.mimirexplore import is_area

        self.assertTrue(is_area("vpr.logic_clbs"))
        self.assertTrue(is_area("synth.luts"))
        self.assertFalse(is_area("vpr.blocks"))
        self.assertFalse(is_area("block"))


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class CurrentDesignTest(unittest.TestCase):
    """The design list selection is the one current design of every tab."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.panel = MimirPanel()
        self.addCleanup(dispose, self.panel)
        db = mimir_fixture.build(self.dir / "s.db", version="5", timing=True)
        p = self.panel
        self.assertTrue(wait(p, "open", lambda: p.open_store(db)))
        self.drain()

    def drain(self) -> None:
        for _ in range(6):
            self.panel._pool.waitForDone()
            settle()

    def pick(self, name: str) -> None:
        p = self.panel
        for i in range(p.designs.count()):
            item = p.designs.item(i)
            data = item.data(Qt.ItemDataRole.UserRole) if item else None
            if data and data[1] == name:
                p.designs.setCurrentRow(i)
                break
        self.drain()

    def test_design_loads_every_tab(self) -> None:
        p = self.panel
        self.pick("d1")
        self.assertIn("d1", p.current_line.text())
        self.assertIn("d1", p.design_label.text())
        self.assertEqual(p.runs_pane.grid.rowCount(), 1)
        self.assertIn(p._current_run, ("r1", "r3"))
        self.assertEqual(p.params_pane.grid.rowCount(), 3)
        self.assertEqual(p.structs.design.currentText(), "s/d1")
        self.assertEqual(p.timing_tab.run.count(), 1)
        self.assertTrue(p.timing_tab.run.currentText().startswith("d1 / "))
        self.assertEqual(p.timing_tab.current_run(), "r1")
        self.assertEqual(p.chart.highlight, "d1")

    def test_timing_run_pick_sets_current_run(self) -> None:
        p = self.panel
        self.pick("d2")
        self.assertEqual(p.timing_tab.current_run(), "r2")
        self.assertEqual(p._current_run, "r2")
        self.assertIn("run r2", p.current_line.text())

    def test_nothing_for_a_design_is_said_plainly(self) -> None:
        p = self.panel
        self.pick("d3")
        self.assertIn("no timing data for d3", p.timing_tab.summary.text())
        self.assertIn("no structure data for d3", p.structs.status.text())
        self.assertIn("no runs of d3", p.run_label.text())

    def test_plot_ringed_and_store_switch_clears(self) -> None:
        p = self.panel
        self.pick("d1")
        self.assertTrue(wait(p, "plot", p.plot))
        self.assertEqual(len(p.chart.highlighted()), 1)
        self.assertIn("d1 is ringed", p.plot_status.text())
        db = mimir_fixture.build(self.dir / "t.db", version="5", timing=True)
        self.assertTrue(wait(p, "open", lambda: p.open_store(db)))
        self.drain()
        self.assertEqual(p.chart.highlight, "")
        self.assertIn("none", p.current_line.text())
        self.assertEqual(p._current_run, "")
