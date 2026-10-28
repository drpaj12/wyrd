"""Mímir panel; Qt runs offscreen. Synthetic store from tests/mimir_fixture.py."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

from tests import mimir_fixture
from wyrd import mimirview

HAVE_QT = importlib.util.find_spec("PySide6") is not None

if HAVE_QT:
    from PySide6.QtCore import QCoreApplication, QEventLoop, Qt, QTimer
    from PySide6.QtGui import QGuiApplication

    from tests.qt_helpers import dispose, qapp
    from wyrd.gui import mimirpanel
    from wyrd.gui.mimircharts import DotChart, nice_ticks
    from wyrd.gui.mimirpanel import MimirPanel
    from wyrd.mimirview import CompareRow

    def setUpModule() -> None:
        qapp()

    def settle() -> None:
        """Let the worker finish and deliver its queued results to the panel."""
        for _ in range(3):
            QCoreApplication.processEvents()

    def wait(panel: MimirPanel, key: str, action: Callable[[], object], seconds: int = 30) -> bool:
        """Run `action`, then the event loop until a worker request `key` ends."""
        loop = QEventLoop()
        got: list[str] = []

        def done(k: str) -> None:
            if k == key:
                got.append(k)
                loop.quit()

        panel.finished.connect(done)
        QTimer.singleShot(0, action)
        QTimer.singleShot(seconds * 1000, loop.quit)
        loop.exec()
        panel.finished.disconnect(done)
        return bool(got)


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class MimirPanelTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.db = mimir_fixture.build(self.dir / "s.db")
        self.panel = MimirPanel()
        self.addCleanup(dispose, self.panel)

    def settled(self) -> MimirPanel:
        """Wait until every worker request has delivered its result."""
        self.panel._pool.waitForDone()
        settle()
        return self.panel

    def opened(self, db: Path | None = None) -> MimirPanel:
        p = self.panel
        target = db or self.db
        self.assertTrue(wait(p, "open", lambda: p.open_store(target)))
        return self.settled()

    def test_empty(self) -> None:
        self.assertIn("No Mímir store", self.panel.status.text())

    def test_open_lists_designs(self) -> None:
        p = self.opened()
        self.assertIn("schema version 4", p.status.text())
        self.assertEqual(p.designs.count(), 6)
        self.assertEqual(p.source.count(), 3)
        self.assertEqual(p.sources_pane.grid.rowCount(), 2)
        self.assertEqual(p.last_path, str(self.db))
        p.filter.setText("d2")
        self.assertEqual(self.settled().designs.count(), 2)

    def test_unsupported_version(self) -> None:
        old = mimir_fixture.build(self.dir / "v3.db", version="3")
        self.assertFalse(self.panel.open_store(old))
        self.assertIn("schema version 3", self.panel.status.text())
        self.assertIsNone(self.panel.view)
        self.assertEqual(self.panel.last_path, "")

    def test_failed_open_keeps_previous_store(self) -> None:
        p = self.opened()
        old = mimir_fixture.build(self.dir / "v3.db", version="3")
        self.assertFalse(p.open_store(old))
        assert p.view is not None
        self.assertEqual(p.view.path, self.db)
        self.assertEqual(p.last_path, str(self.db))
        self.assertEqual(p.designs.count(), 6)

    def test_design_and_run(self) -> None:
        p = self.opened()
        p.designs.setCurrentRow(0)
        self.settled()
        self.assertEqual(p.metrics_pane.grid.rowCount(), 3)
        self.assertEqual(p.runs_pane.grid.rowCount(), 1)
        p._run_row_activated(0, 0)
        self.settled()
        self.assertEqual(p.params_pane.grid.rowCount(), 3)
        colours = set()
        for i in range(3):
            item = p.params_pane.grid.item(i, 3)
            assert item is not None
            colours.add(item.background().color().name())
        self.assertEqual(len(colours), 3)
        self.assertEqual(p.artifacts_pane.grid.rowCount(), 1)

    def test_design_level_filter(self) -> None:
        p = self.opened()
        self.assertEqual(p.design_level.count(), 3)
        p.show_design("d1")
        self.assertEqual(self.settled().metrics_pane.grid.rowCount(), 6)
        p.design_level.setCurrentText("clb")
        p._refresh_design()
        self.assertEqual(self.settled().metrics_pane.grid.rowCount(), 2)

    def test_export_writes_all_rows_when_cut(self) -> None:
        p = self.opened()
        with mock.patch.object(mimirpanel, "ROW_LIMIT", 3):
            p.show_design("d1")
            self.settled()
        self.assertEqual(p.metrics_pane.grid.rowCount(), 3)
        self.assertIn("cut at the row limit", p.metrics_pane.note.text())
        out = self.dir / "m.csv"
        p.metrics_pane.export_csv(out)
        lines = out.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 7)
        self.assertFalse(any(x.startswith("#") for x in lines))

    def fetch_with(self, p: MimirPanel, code: str) -> None:
        p.argv_for = lambda run, db, out: [sys.executable, "-c", code]
        p.fetch_dir = lambda: "outdir"

    def test_fetch_runs_in_process_with_output(self) -> None:
        p = self.opened()
        self.assertFalse(p.fetch())  # no run selected
        p.show_run("r1")
        self.settled()
        self.fetch_with(p, "print('fetched ok')")
        codes: list[int] = []
        p.fetch_finished.connect(codes.append)
        loop = QEventLoop()
        p.fetch_finished.connect(lambda _c: loop.quit())
        QTimer.singleShot(30000, loop.quit)
        QTimer.singleShot(0, lambda: self.assertTrue(p.fetch()))
        loop.exec()
        self.assertEqual(codes, [0])
        self.assertIn("fetched ok", p.fetch_log.toPlainText())
        self.assertIn("exited 0", p.status.text())

    def test_fetch_cancel(self) -> None:
        p = self.opened()
        p.show_run("r1")
        self.settled()
        self.fetch_with(p, "import sys; sys.stdin.read()")
        codes: list[int] = []
        loop = QEventLoop()
        p.fetch_finished.connect(codes.append)
        p.fetch_finished.connect(lambda _c: loop.quit())
        QTimer.singleShot(30000, loop.quit)

        def start() -> None:
            self.assertTrue(p.fetch())
            self.assertFalse(p.fetch_button.isEnabled())
            self.assertTrue(p.cancel_button.isEnabled())
            p.cancel_fetch()

        QTimer.singleShot(0, start)
        loop.exec()
        self.assertEqual(codes, [-1])
        self.assertIn("cancelled", p.status.text())
        self.assertFalse(p.cancel_button.isEnabled())

    def test_compare(self) -> None:
        p = self.opened()
        p.cmp_prefix.setText("exp-a-")
        self.assertTrue(wait(p, "configs", p.list_configs))
        self.assertEqual(p.cmp_base.count(), 2)
        p.cmp_base.setCurrentIndex(0)
        p.cmp_metric.setCurrentText("vpr.cpd")
        self.assertTrue(wait(p, "compare", p.compare))
        self.assertEqual(p.cmp_pane.grid.rowCount(), 2)
        self.assertEqual(len(p.cmp_chart.rows), 2)

    def test_open_resets_previous_store_state(self) -> None:
        p = self.opened()
        p.cmp_prefix.setText("exp-a-")
        wait(p, "configs", p.list_configs)
        wait(p, "compare", p.compare)
        wait(p, "plot", p.plot)
        p.show_run("r1")
        self.settled()
        self.assertTrue(p._current_run)
        other = mimir_fixture.build(self.dir / "t.db")
        self.opened(other)
        self.assertEqual(p._current_run, "")
        self.assertEqual(p.cmp_pane.grid.rowCount(), 0)
        self.assertEqual((p.cmp_chart.rows, p.chart.points), ([], []))
        self.assertEqual((p.cmp_status.text(), p.plot_status.text()), ("", ""))
        self.assertEqual(p.params_pane.grid.rowCount(), 0)
        self.assertFalse(p.fetch_button.isEnabled())

    def test_stale_result_dropped_on_reopen(self) -> None:
        p = self.opened()
        p.cmp_prefix.setText("exp-a-")
        wait(p, "configs", p.list_configs)
        p.compare()  # in flight ...
        other = mimir_fixture.build(self.dir / "t.db")
        self.assertTrue(wait(p, "open", lambda: p.open_store(other)))
        self.settled()
        self.assertEqual(p.cmp_pane.grid.rowCount(), 0)  # ... its result was dropped

    def test_plot_and_hover(self) -> None:
        p = self.opened()
        p.plot_x.setCurrentText("vpr.cpd")
        p.plot_y.setCurrentText("vpr.logic_clbs")
        p.log_x.setChecked(True)
        self.assertTrue(wait(p, "plot", p.plot))
        self.assertEqual(len(p.chart.points), 6)
        self.assertEqual(p.plot_status.text(), "6 designs")
        p.chart.resize(300, 300)
        pt, sx, sy = p.chart.project(p.chart.usable())[0]
        near = p.chart.nearest(sx, sy)
        self.assertIsNotNone(near)
        self.assertEqual(near.label if near else "", pt.label)

    def test_plot_cap_note(self) -> None:
        p = self.opened()
        p.plot_x.setCurrentText("vpr.cpd")
        p.plot_y.setCurrentText("vpr.logic_clbs")
        with mock.patch.object(mimirview, "SCATTER_LIMIT", 4):
            self.assertTrue(wait(p, "plot", p.plot))
        self.assertIn("capped at 4 of 6", p.plot_status.text())

    def test_runs_only_store(self) -> None:
        db = mimir_fixture.build(self.dir / "r.db")
        con = sqlite3.connect(db)
        con.execute("DELETE FROM records")
        con.commit()
        con.close()
        p = self.opened(db)
        self.assertIn(mimirview.RUNS_ONLY_NOTE, p.summary_text.toPlainText())
        self.assertIn(mimirview.RUNS_ONLY_NOTE, p.cmp_status.text())
        names = [p.cmp_metric.itemText(i) for i in range(p.cmp_metric.count())]
        self.assertEqual(names, ["run.time_s", "run.peak_rss_mib"])
        p.cmp_prefix.setText("exp-a-")
        wait(p, "configs", p.list_configs)
        p.cmp_base.setCurrentIndex(0)
        p.cmp_metric.setCurrentText("run.time_s")
        self.assertTrue(wait(p, "compare", p.compare))
        self.assertEqual(p.cmp_pane.grid.rowCount(), 2)

    def test_metric_tooltips_from_registry(self) -> None:
        with mock.patch.object(mimirview, "metric_registry", lambda: {"vpr.cpd": "critical path"}):
            p = self.opened()
        tip = p.cmp_metric.itemData(0, Qt.ItemDataRole.ToolTipRole)
        self.assertEqual(p.cmp_metric.itemText(0), "vpr.cpd")
        self.assertEqual(tip, "critical path")
        self.assertEqual(p.plot_x.itemData(0, Qt.ItemDataRole.ToolTipRole), "critical path")

    def test_copy_and_export(self) -> None:
        p = self.opened()
        p.show_design("d1")
        self.settled()
        p.metrics_pane.copy()
        self.assertTrue(QGuiApplication.clipboard().text().startswith("source\tlevel"))
        out = self.dir / "m.csv"
        p.metrics_pane.export_csv(out)
        self.assertEqual(len(out.read_text(encoding="utf-8").splitlines()), 7)

    def test_read_only_and_no_new_files(self) -> None:
        before = (self.db.read_bytes(), self.db.stat().st_mtime_ns)
        files = sorted(os.listdir(self.dir))
        p = self.opened()
        p.show_design("d1")
        self.settled()
        p.show_run("r1")
        self.settled()
        p.cmp_prefix.setText("exp-a-")
        wait(p, "configs", p.list_configs)
        wait(p, "compare", p.compare)
        self.assertEqual((self.db.read_bytes(), self.db.stat().st_mtime_ns), before)
        self.assertEqual(sorted(os.listdir(self.dir)), files)

    def test_wal_note(self) -> None:
        Path(f"{self.db}-wal").write_bytes(b"")
        p = self.opened()
        self.assertIn("-wal", p.status.text())


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class DotChartTest(unittest.TestCase):
    def rows(self, n: int, label: str = "norns-r7/net_known") -> list[CompareRow]:
        return [CompareRow(f"{label}{i}", "routed", 3, 0.5 + i / 100) for i in range(n)]

    def test_long_label_elided_single_line(self) -> None:
        c = DotChart()
        self.addCleanup(dispose, c)
        c.set_rows(self.rows(3, "norns-r7-with-a-very-long-experiment-name/arm_with_long_suffix_"))
        c.resize(300, 200)
        text = c.display_label(0)
        self.assertIn("\u2026", text)
        self.assertNotIn("\n", text)
        self.assertLessEqual(c.fontMetrics().horizontalAdvance(text), c.label_width())
        self.assertLessEqual(c.label_width(), 120)

    def test_label_column_fits_short_labels(self) -> None:
        c = DotChart()
        self.addCleanup(dispose, c)
        c.set_rows(self.rows(2))
        c.resize(900, 200)
        self.assertEqual(c.display_label(0), c.labels[0])

    def test_height_grows_with_rows(self) -> None:
        c = DotChart()
        self.addCleanup(dispose, c)
        c.set_rows(self.rows(40))
        self.assertGreaterEqual(c.minimumHeight(), 40 * 18)
        c.set_rows(self.rows(40), multi_level=True)
        self.assertTrue(c.labels[0].endswith("[routed]"))

    def test_nice_ticks(self) -> None:
        t = nice_ticks(0.83, 1.17, 5)
        self.assertGreaterEqual(len(t), 3)
        self.assertTrue(all(0.83 <= v <= 1.17 for v in t))
        self.assertEqual(nice_ticks(0.0, 100.0, 5), [0.0, 20.0, 40.0, 60.0, 80.0, 100.0])
        self.assertEqual(nice_ticks(2.0, 2.0), [2.0])


if __name__ == "__main__":
    unittest.main()
