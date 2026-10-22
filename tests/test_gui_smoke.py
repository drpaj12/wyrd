"""GUI smoke tests; Qt runs offscreen."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import shutil
import sys
import tempfile
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

from tests.helpers_results import make_results

HAVE_QT = importlib.util.find_spec("PySide6") is not None
ROOT = Path(__file__).parent.parent
SAMPLES = ROOT / "samples"
LOGS = ROOT / "tests" / "data" / "logs"

if HAVE_QT:
    from PySide6.QtCore import QCoreApplication, QEventLoop, QSettings, QTimer, SignalInstance
    from PySide6.QtWidgets import QApplication, QTableWidget, QTreeWidgetItem

    from wyrd.gui.flowpanel import FlowPanel
    from wyrd.gui.mainwindow import MainWindow
    from wyrd.gui.messages import MessagesPane
    from wyrd.gui.sourceview import SourceView
    from wyrd.guimodel.floorplan import FloorplanPlan, plan_floorplan
    from wyrd.guimodel.logparse import parse_log
    from wyrd.model import Design, Recipe, RunSpec, StepSpec
    from wyrd.store import Store

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


def project_with_results(tmp: Path) -> Path:
    root = tmp / "proj"
    shutil.copytree(SAMPLES / "designs", root / "designs")
    shutil.copy(SAMPLES / "wyrd.toml", root / "wyrd.toml")
    make_results(root)
    return root


def find_child(item: "QTreeWidgetItem", text: str) -> "QTreeWidgetItem":
    for i in range(item.childCount()):
        child = item.child(i)
        if child is not None and child.text(0) == text:
            return child
    raise AssertionError(f"no child {text!r}")


def child_texts(item: "QTreeWidgetItem") -> list[str]:
    out: list[str] = []
    for i in range(item.childCount()):
        child = item.child(i)
        assert child is not None
        out.append(child.text(0))
    return out


def table_cells(table: "QTableWidget") -> list[list[str]]:
    out: list[list[str]] = []
    for r in range(table.rowCount()):
        row: list[str] = []
        for c in range(table.columnCount()):
            cell = table.item(r, c)
            row.append(cell.text() if cell else "")
        out.append(row)
    return out


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class ReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_report_tree_and_summary(self) -> None:
        root = project_with_results(self.tmp)
        w = window(self.tmp)
        self.assertTrue(w.open_project(root))
        tree = w.report_view.tree
        self.assertEqual(tree.topLevelItemCount(), 3)
        run = tree.topLevelItem(1)
        assert run is not None
        self.assertEqual(run.text(0), "single / EArch")
        self.assertEqual(child_texts(run), ["Summary", "Step 0: odin3-flow"])
        tree.setCurrentItem(find_child(run, "Summary"))
        page = w.report_view.pages.currentWidget()
        assert isinstance(page, QTableWidget)
        cells = table_cells(page)
        self.assertIn(["Fmax (MHz)", "181.8"], cells)

    def test_run_selection_fills_messages(self) -> None:
        root = project_with_results(self.tmp)
        w = window(self.tmp)
        w.open_project(root)
        run = w.report_view.tree.topLevelItem(1)
        assert run is not None
        w.report_view.tree.setCurrentItem(run)
        self.assertEqual(w.messages.count(), 8)
        button = w.report_view.floorplan_button
        self.assertFalse(button.isEnabled())
        run_info = w.report_view.current_run()
        assert run_info is not None
        self.assertEqual(button.toolTip(), plan_floorplan(run_info.run_dir))

    def test_compare(self) -> None:
        root = project_with_results(self.tmp)
        other = self.tmp / "other"
        other.mkdir()
        make_results(other)
        w = window(self.tmp)
        w.open_project(root)
        w.report_view.compare_with(other)
        header = table_cells(w.report_view.compare_table)[0]
        self.assertEqual(w.report_view.compare_table.columnCount(), len(header))
        self.assertGreater(w.report_view.compare_table.rowCount(), 0)

    def test_no_results(self) -> None:
        w = window(self.tmp)
        w.open_project(SAMPLES)
        tree = w.report_view.tree
        self.assertEqual(tree.topLevelItemCount(), 1)
        top = tree.topLevelItem(0)
        assert top is not None
        self.assertTrue(top.text(0).startswith("No results yet"))

    def test_missing_metrics_show_na(self) -> None:
        root = project_with_results(self.tmp)
        store = Store(root / "wyrd.db")
        recipe = Recipe("vtr", (StepSpec("odin3-flow"),))
        spec = RunSpec(Design("dsp", (root / "a.v",), None), "EArch", recipe)
        store.begin("b" * 64, spec, root / "runs" / "dsp")
        store.finish("b" * 64, "ok")
        w = window(self.tmp)
        w.open_project(root)
        tree = w.report_view.tree
        run = tree.topLevelItem(1)
        assert run is not None
        self.assertEqual(run.text(0), "dsp / EArch")
        tree.setCurrentItem(find_child(run, "Summary"))
        page = w.report_view.pages.currentWidget()
        assert isinstance(page, QTableWidget)
        cells = dict((r[0], r[1]) for r in table_cells(page))
        self.assertEqual(cells["Fmax (MHz)"], "n/a")
        self.assertEqual(cells["LUTs"], "n/a")


def wait_for(signal: "SignalInstance", ms: int = 8000) -> bool:
    """Run the event loop until ``signal`` fires; False when the guard timer expires first."""
    loop = QEventLoop()
    fired: list[bool] = []

    def done(*_args: object) -> None:
        fired.append(True)
        loop.quit()

    signal.connect(done)
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    return bool(fired)


def pump_until(cond: Callable[[], bool], ms: int = 5000) -> bool:
    """Run the event loop until ``cond()`` holds; False on timeout."""
    loop = QEventLoop()
    guard = QTimer()
    guard.setInterval(25)

    def check() -> None:
        if cond():
            loop.quit()

    guard.timeout.connect(check)
    guard.start()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    guard.stop()
    return cond()


STUB = (
    "import sys\n"
    "print('plan: 2 to run, 0 reused', flush=True)\n"
    "print('single/EArch [aaaaaaaaaaaa] ok', flush=True)\n"
    "sys.exit(1)\n"
)
SLEEPER = "import time\nprint('started', flush=True)\ntime.sleep(30)\n"


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class FlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_run_button_state(self) -> None:
        w = window(self.tmp)
        w.open_project(SAMPLES)
        self.assertTrue(w.flow.run_button.isEnabled())
        bad = self.tmp / "bad"
        bad.mkdir()
        (bad / "wyrd.toml").write_text("[project]\nname = 1\n", encoding="utf-8")
        w.open_project(bad)
        self.assertFalse(w.flow.run_button.isEnabled())

    def test_stub_run(self) -> None:
        panel = FlowPanel()
        argv = [sys.executable, "-c", STUB]
        with mock.patch("wyrd.gui.flowpanel.run_argv", return_value=argv):
            panel.start(self.tmp)
            self.assertTrue(panel.is_running())
            codes: list[int] = []
            panel.finished.connect(codes.append)
            self.assertTrue(wait_for(panel.finished))
        self.assertEqual(codes, [1])
        self.assertEqual(panel.status_label.text(), "some runs not ok")
        self.assertEqual(panel.progress.maximum(), 1000)
        self.assertEqual(panel.progress.value(), 500)
        self.assertIn("plan: 2 to run, 0 reused", panel.log.toPlainText())

    def test_cancel(self) -> None:
        panel = FlowPanel()
        argv = [sys.executable, "-c", SLEEPER]
        with mock.patch("wyrd.gui.flowpanel.run_argv", return_value=argv):
            panel.start(self.tmp)
        pump_until(lambda: "started" in panel.log.toPlainText())
        self.assertIn("started", panel.log.toPlainText())
        started = time.monotonic()
        panel.cancel()
        self.assertTrue(wait_for(panel.finished, 5000) or not panel.is_running())
        self.assertFalse(panel.is_running())
        self.assertLess(time.monotonic() - started, 5)

    def test_floorplan_early_exit(self) -> None:
        panel = FlowPanel()
        cwd = self.tmp / "run" / "floorplan"
        plan = FloorplanPlan(sys.executable, ("-c", "raise SystemExit(3)"), cwd, "rerun")
        panel.start_floorplan(plan)
        pump_until(lambda: "VPR exited early" in panel.log.toPlainText(), 3000)
        self.assertTrue(cwd.is_dir())
        self.assertIn("VPR exited early", panel.log.toPlainText())


if __name__ == "__main__":
    unittest.main()
