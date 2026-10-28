"""Mímir panel; Qt runs offscreen. Synthetic store from tests/mimir_fixture.py."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

from tests import mimir_fixture

HAVE_QT = importlib.util.find_spec("PySide6") is not None

if HAVE_QT:
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtGui import QGuiApplication

    from tests.qt_helpers import dispose, qapp
    from wyrd.gui.mimirpanel import MimirPanel

    def setUpModule() -> None:
        qapp()

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

    def opened(self) -> MimirPanel:
        p = self.panel
        self.assertTrue(wait(p, "open", lambda: p.open_store(self.db)))
        return p

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
        self.assertEqual(p.designs.count(), 2)

    def test_unsupported_version(self) -> None:
        old = mimir_fixture.build(self.dir / "v3.db", version="3")
        self.assertFalse(self.panel.open_store(old))
        self.assertIn("schema version 3", self.panel.status.text())

    def test_design_and_run(self) -> None:
        p = self.opened()
        p.designs.setCurrentRow(0)
        self.assertEqual(p.metrics_pane.grid.rowCount(), 3)
        self.assertEqual(p.runs_pane.grid.rowCount(), 1)
        p._run_row_activated(0, 0)
        self.assertEqual(p.params_pane.grid.rowCount(), 3)
        colours = set()
        for i in range(3):
            item = p.params_pane.grid.item(i, 3)
            assert item is not None
            colours.add(item.background().color().name())
        self.assertEqual(len(colours), 3)
        self.assertEqual(p.artifacts_pane.grid.rowCount(), 1)

    def test_fetch_hook(self) -> None:
        p = self.opened()
        calls: list[list[str]] = []

        def runner(argv: list[str]) -> int:
            calls.append(argv)
            return 0

        p.fetch_runner = runner
        p.fetch_dir = lambda: "outdir"
        self.assertIsNone(p.fetch())  # no run selected
        p.show_run("r1")
        self.assertEqual(p.fetch(), 0)
        self.assertEqual(calls[0][:4], ["mimir", "fetch", "--run", "r1"])
        self.assertEqual(calls[0][-2:], ["--out", "outdir"])

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

    def test_plot_and_hover(self) -> None:
        p = self.opened()
        p.plot_x.setCurrentText("vpr.cpd")
        p.plot_y.setCurrentText("vpr.logic_clbs")
        p.log_x.setChecked(True)
        self.assertTrue(wait(p, "plot", p.plot))
        self.assertEqual(len(p.chart.points), 6)
        p.chart.resize(300, 300)
        pt, sx, sy = p.chart.project(p.chart.usable())[0]
        near = p.chart.nearest(sx, sy)
        self.assertIsNotNone(near)
        self.assertEqual(near.label if near else "", pt.label)

    def test_copy_and_export(self) -> None:
        p = self.opened()
        p.show_design("d1")
        p.metrics_pane.copy()
        self.assertTrue(QGuiApplication.clipboard().text().startswith("source\tlevel"))
        out = self.dir / "m.csv"
        p.metrics_pane.export_csv(out)
        self.assertEqual(len(out.read_text(encoding="utf-8").splitlines()), 7)

    def test_read_only(self) -> None:
        before = (self.db.read_bytes(), self.db.stat().st_mtime_ns)
        p = self.opened()
        p.show_design("d1")
        p.show_run("r1")
        self.assertEqual((self.db.read_bytes(), self.db.stat().st_mtime_ns), before)


if __name__ == "__main__":
    unittest.main()
