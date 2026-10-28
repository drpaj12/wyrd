"""Hot/cold source view and the Timing panel controls; Qt runs offscreen."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import tempfile
import unittest
from pathlib import Path

from tests.test_heat import BUS_SRC, bus_model
from wyrd.guimodel import heat, heatview

HAVE_QT = importlib.util.find_spec("PySide6") is not None

if HAVE_QT:
    from PySide6.QtCore import QSettings

    from tests.qt_helpers import dispose, qapp
    from wyrd.gui.mainwindow import MainWindow
    from wyrd.gui.sourceview import SourceView
    from wyrd.gui.timingpanel import TimingPanel

    def setUpModule() -> None:
        qapp()


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class SourceViewHeatTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.src = Path(self._tmp.name) / "top.v"
        self.src.write_text(BUS_SRC, encoding="utf-8")
        self.view = SourceView()
        self.addCleanup(dispose, self.view)
        self.assertTrue(self.view.open_file(self.src))

    def heat(self, kind: str = heat.SCOPE_CRITICAL) -> heatview.FileHeat:
        model = bus_model()
        return heatview.build_file_heat(model, model.select(heat.Scope(kind)), {"top.v"}, BUS_SRC)

    def test_selections_for_segments_and_lines(self) -> None:
        self.view.set_file_heat(self.heat(), 0.9)
        sels = self.view.text.extraSelections()
        # 1 line tint + 3 segments on the declaration + 3 segments on each of 3 uses
        self.assertEqual(len(sels), 1 + 3 + 9)
        colours = {
            s.format.background().color().name()
            for s in sels
            if not s.format.hasProperty(0x6000)  # not full width
        }
        self.assertIn(heatview.crit_hex(1.0), colours)
        self.assertIn(heatview.crit_hex(0.0), colours)
        self.assertTrue(self.view.legend.isVisibleTo(self.view))

    def test_clear(self) -> None:
        self.view.set_file_heat(self.heat())
        self.view.set_file_heat(None)
        self.assertEqual(self.view.text.extraSelections(), [])
        self.assertFalse(self.view.legend.isVisibleTo(self.view))

    def test_tooltip_text(self) -> None:
        self.view.set_file_heat(self.heat())
        fh = self.view.text.file_heat
        assert fh is not None
        r = fh.range_at(1, fh.ranges[0].col_start)
        assert r is not None
        self.assertIn("bits:", r.tooltip)


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class PanelHeatTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.panel = TimingPanel()
        self.addCleanup(dispose, self.panel)

    def test_scope_controls(self) -> None:
        self.assertEqual(self.panel.heat_scope().kind, heat.SCOPE_CRITICAL)
        self.panel.scope.setCurrentIndex(2)
        self.panel.theta.setCurrentIndex(1)
        sc = self.panel.heat_scope()
        self.assertEqual((sc.kind, sc.theta), (heat.SCOPE_NEAR, 0.95))
        self.assertTrue(self.panel.theta.isEnabled())
        self.assertFalse(self.panel.top_n.isEnabled())

    def test_use_model_and_paths_table(self) -> None:
        src = self.tmp / "top.v"
        src.write_text(BUS_SRC, encoding="utf-8")
        self.panel.use_heat_model(bus_model())
        fh = self.panel.file_heat_for(src, BUS_SRC)
        assert fh is not None
        self.assertEqual(fh.lines, {})  # file name top.v is not resolvable without roots
        self.panel.show_paths("SIGNAL", (1, 2))
        self.assertEqual(self.panel.hits.rowCount(), 2)
        item = self.panel.hits.item(0, 0)
        assert item is not None
        self.assertEqual(item.text(), "1")


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class WindowHeatTest(unittest.TestCase):
    def test_attribution_colours_source(self) -> None:
        from tests.test_gui_timing import SOURCE, project

        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            project(tmp)
            w = MainWindow(QSettings(str(tmp / "s.ini"), QSettings.Format.IniFormat), silent=True)
            self.addCleanup(dispose, w)
            self.assertTrue(w.open_project(tmp / "proj"))
            run = w.report_view.tree.topLevelItem(1)
            assert run is not None
            w.report_view.tree.setCurrentItem(run)
            w.timing.statements.selectRow(0)
            self.assertEqual(w.source_view.path, tmp / "proj" / SOURCE)
            fh = w.source_view.text.file_heat
            assert fh is not None
            self.assertIn(15, fh.lines)
            w.timing.scope.setCurrentIndex(2)
            w.timing.theta.setCurrentIndex(2)
            near = w.source_view.text.file_heat
            assert near is not None
            self.assertTrue(near.lines)
            w._on_heat_click(15, 0)
            self.assertGreaterEqual(w.timing.hits.rowCount(), 1)
            w.timing.mode.setCurrentIndex(1)
            self.assertIsNone(w.source_view.text.file_heat)
            self.assertTrue(w.source_view.text.heat)


if __name__ == "__main__":
    unittest.main()
