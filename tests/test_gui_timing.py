"""Timing panel and source heat margin; Qt runs offscreen. Fixture: tests/data/timing."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.helpers_results import make_results

HAVE_QT = importlib.util.find_spec("PySide6") is not None
DATA = Path(__file__).parent / "data" / "timing"
SOURCE = "bm_DL_BCD_adder.v"

if HAVE_QT:
    from PySide6.QtCore import QSettings

    from tests.qt_helpers import dispose, qapp
    from wyrd.gui.mainwindow import MainWindow
    from wyrd.gui.sourceview import SourceView
    from wyrd.gui.timingpanel import NO_ATTR, NO_RUN, TimingPanel

    def setUpModule() -> None:
        qapp()


def project(tmp: Path, with_attribution: bool = True) -> Path:
    root = tmp / "proj"
    root.mkdir()
    shutil.copy(Path(__file__).parent.parent / "samples" / "wyrd.toml", root / "wyrd.toml")
    shutil.copytree(Path(__file__).parent.parent / "samples" / "designs", root / "designs")
    run_dir = make_results(root)
    shutil.copy(DATA / SOURCE, root / SOURCE)
    if with_attribution:
        shutil.copytree(DATA / "out" / "timing", run_dir / "0-odin3-flow" / "out" / "timing")
    return run_dir


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class TimingPanelTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.panel = TimingPanel()
        self.addCleanup(dispose, self.panel)
        self.addCleanup(self._tmp.cleanup)

    def test_initial_message(self) -> None:
        self.assertEqual(self.panel.header.text(), NO_RUN)
        self.assertEqual(self.panel.heat_for(self.tmp / SOURCE), {})

    def test_fills_and_selects(self) -> None:
        run_dir = project(self.tmp)
        self.panel.set_run(run_dir, [self.tmp / "proj"])
        self.assertIn("216.48 MHz", self.panel.header.text())
        self.assertEqual(self.panel.statements.rowCount(), 3)
        self.assertEqual(self.panel.path.rowCount(), 5)
        got: list[tuple[Path, int]] = []
        self.panel.location_activated.connect(lambda p, n: got.append((p, n)))
        self.panel.statements.selectRow(0)
        self.assertEqual(got, [(self.tmp / "proj" / SOURCE, 15)])
        cell = self.panel.statements.item(0, 0)
        assert cell is not None
        self.assertEqual(cell.text(), "49.3%")
        self.panel.path.selectRow(0)  # an I/O port row opens nothing
        self.assertEqual(len(got), 1)
        self.panel.path.selectRow(3)
        self.assertEqual(got[-1][1], 16)

    def test_heat_scopes(self) -> None:
        run_dir = project(self.tmp)
        self.panel.set_run(run_dir, [self.tmp / "proj"])
        src = self.tmp / "proj" / SOURCE
        critical = self.panel.heat_for(src)
        self.assertEqual(sorted(critical), [15, 16, 19])
        self.panel.scope.setCurrentIndex(1)
        self.assertTrue(self.panel.top_n.isEnabled())
        self.panel.top_n.setValue(10)
        self.assertGreaterEqual(len(self.panel.heat_for(src)), 3)
        self.assertEqual(self.panel.heat_for(self.tmp / "other.v"), {})

    def test_missing_attribution(self) -> None:
        run_dir = project(self.tmp, with_attribution=False)
        self.panel.set_run(run_dir, [])
        self.assertEqual(self.panel.header.text(), NO_ATTR)
        self.assertFalse(self.panel.has_attribution())
        self.assertEqual(self.panel.statements.rowCount(), 0)

    def test_missing_attribution_shows_timing_log(self) -> None:
        run_dir = project(self.tmp, with_attribution=False)
        log = run_dir / "0-odin3-flow" / "out" / "timing" / "timing.log"
        log.parent.mkdir(parents=True)
        log.write_text("VPR report has no setup paths\n", encoding="utf-8")
        self.panel.set_run(run_dir, [])
        self.assertIn("VPR report has no setup paths", self.panel.header.text())
        self.assertNotIn("timing_attr = true", self.panel.header.text())

    def test_stale_source_warns(self) -> None:
        run_dir = project(self.tmp)
        src = self.tmp / "proj" / SOURCE
        att = run_dir / "0-odin3-flow" / "out" / "timing" / "attribution.json"
        os.utime(att, (1_000_000, 1_000_000))
        self.panel.set_run(run_dir, [self.tmp / "proj"])
        self.panel.statements.selectRow(0)
        self.assertIn("changed after the timing run", self.panel.note.text())
        os.utime(src, (900_000, 900_000))
        self.panel.statements.clearSelection()
        self.panel.statements.selectRow(1)
        self.assertEqual(self.panel.note.text(), "")

    def test_bad_attribution(self) -> None:
        run_dir = project(self.tmp)
        path = run_dir / "0-odin3-flow" / "out" / "timing" / "attribution.json"
        path.write_text(json.dumps({"schema_version": 9}), encoding="utf-8")
        self.panel.set_run(run_dir, [])
        self.assertIn("schema_version 9", self.panel.header.text())
        path.write_text("{", encoding="utf-8")
        self.panel.set_run(run_dir, [])
        self.assertIn("not valid JSON", self.panel.header.text())
        self.panel.set_run(None, [])
        self.assertEqual(self.panel.header.text(), NO_RUN)

    def test_missing_source_file(self) -> None:
        run_dir = project(self.tmp)
        self.panel.set_run(run_dir, [self.tmp / "nowhere"])
        self.panel.statements.selectRow(0)
        self.assertIn("Cannot find", self.panel.note.text())


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class HeatMarginTest(unittest.TestCase):
    def test_margin_follows_heat(self) -> None:
        view = SourceView()
        self.addCleanup(dispose, view)
        view.resize(600, 300)
        view.show()
        self.assertTrue(view.open_file(DATA / SOURCE, 15))
        self.assertEqual(view.text.heat_width(), 0)
        view.set_heat({15: 0.49, 16: 0.2})
        self.assertGreater(view.text.heat_width(), 0)
        self.assertFalse(view.grab().isNull())  # paints the margin
        view.set_heat({})
        self.assertEqual(view.text.heat_width(), 0)


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class SourceViewFailureTest(unittest.TestCase):
    def test_failed_read_clears_path_and_heat(self) -> None:
        view = SourceView()
        self.addCleanup(dispose, view)
        self.assertTrue(view.open_file(DATA / SOURCE))
        view.set_heat({15: 0.5})
        self.assertFalse(view.open_file(DATA / "missing.v"))
        self.assertIsNone(view.path)
        self.assertEqual(view.text.heat, {})


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class WindowTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_run_selection_shows_timing_and_heat(self) -> None:
        project(self.tmp)
        settings = QSettings(str(self.tmp / "s.ini"), QSettings.Format.IniFormat)
        w = MainWindow(settings, silent=True)
        self.addCleanup(dispose, w)
        self.assertTrue(w.open_project(self.tmp / "proj"))
        run = w.report_view.tree.topLevelItem(1)
        assert run is not None
        w.report_view.tree.setCurrentItem(run)
        self.assertTrue(w.timing.has_attribution())
        w.timing.statements.selectRow(0)
        self.assertEqual(w.source_view.path, self.tmp / "proj" / SOURCE)
        self.assertEqual(w.source_view.text.textCursor().blockNumber(), 14)
        self.assertEqual(sorted(w.source_view.text.heat), [15, 16, 19])
        all_runs = w.report_view.tree.topLevelItem(0)
        assert all_runs is not None
        w.report_view.tree.setCurrentItem(all_runs)
        self.assertFalse(w.timing.has_attribution())
        self.assertEqual(w.source_view.text.heat, {})


if __name__ == "__main__":
    unittest.main()
