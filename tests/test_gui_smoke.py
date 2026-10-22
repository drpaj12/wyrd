"""GUI smoke tests; Qt runs offscreen."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import shutil
import sys
import tempfile
import time
import tomllib
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
    from PySide6.QtCore import (
        QCoreApplication,
        QEventLoop,
        QProcess,
        QSettings,
        QTimer,
        SignalInstance,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QDialog,
        QFileDialog,
        QLineEdit,
        QMessageBox,
        QSpinBox,
        QTableWidget,
        QTreeWidgetItem,
    )

    from wyrd.gui.about import AboutDialog
    from wyrd.gui.adddesign import AddDesignDialog
    from wyrd.gui.flowpanel import FlowPanel
    from wyrd.gui.mainwindow import MainWindow
    from wyrd.gui.messages import MessagesPane
    from wyrd.gui.settingsdialog import SettingsDialog
    from wyrd.gui.sourceview import SourceView
    from wyrd.gui.stepload import load_messages, read_log_limited
    from wyrd.guimodel.floorplan import FloorplanPlan, plan_floorplan
    from wyrd.guimodel.logparse import parse_log
    from wyrd.guimodel.tomledit import validate_text
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


def live_window(tmp: Path) -> "MainWindow":
    """A window that asks (QMessageBox patched by the test) instead of staying silent."""
    settings = QSettings(str(tmp / "s.ini"), QSettings.Format.IniFormat)
    return MainWindow(settings, silent=False)


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
        self.assertTrue(w.tabs.isTabEnabled(2))
        self.assertIs(w.tabs.currentWidget(), w.editor)
        diag = validate_text(d / "wyrd.toml", w.editor.text.toPlainText()).diagnostic
        assert diag is not None and diag.line is not None
        self.assertTrue(w.editor.status.text().startswith(f"line {diag.line}: "))

    def test_open_while_flow_runs_asks(self) -> None:
        w = live_window(self.tmp)
        w.open_project(SAMPLES)
        other = copy_project(self.tmp)
        with (
            mock.patch.object(w.flow, "is_running", return_value=True),
            mock.patch.object(w.flow, "cancel") as cancel,
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No),
        ):
            self.assertFalse(w.open_project(other))
            self.assertEqual(w.project_dir, SAMPLES)
            cancel.assert_not_called()
        with (
            mock.patch.object(w.flow, "is_running", return_value=True),
            mock.patch.object(w.flow, "cancel") as cancel,
            mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
        ):
            self.assertTrue(w.open_project(other))
            self.assertEqual(w.project_dir, SAMPLES)  # not loaded until the flow finishes
            cancel.assert_called_once()
        self.assertEqual(w.flow.status_label.text(), "stopping the current flow...")
        self.assertFalse(w.flow.run_button.isEnabled())
        self.assertFalse(w.open_project(SAMPLES))  # second switch refused while pending
        w._on_flow_finished(0)
        self.assertEqual(w.project_dir, other)
        self.assertTrue(w.flow.run_button.isEnabled())

    def test_close_with_dirty_editor_asks(self) -> None:
        w = live_window(self.tmp)
        w.open_project(copy_project(self.tmp))
        w.editor.text.setPlainText("x = 1\n")
        with mock.patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.No
        ) as ask:
            self.assertFalse(w.close())
            ask.assert_called_once()
        self.assertIsNone(w.settings.value("geometry"))
        with mock.patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            self.assertTrue(w.close())
        self.assertIsNotNone(w.settings.value("geometry"))

    def test_switch_project_while_flow_runs_real_process(self) -> None:
        w = window(self.tmp)
        w.open_project(SAMPLES)
        argv = [sys.executable, "-c", OLD_RUN]
        with mock.patch("wyrd.gui.flowpanel.run_argv", return_value=argv):
            w.flow.start(self.tmp)
        assert w.flow.process is not None
        old_pid = int(w.flow.process.processId())
        self.assertTrue(pump_until(lambda: "old-run-output" in w.flow.log.toPlainText()))
        other = copy_project(self.tmp)
        self.assertTrue(w.open_project(other))
        self.assertEqual(w.project_dir, SAMPLES)
        self.assertEqual(w.flow.status_label.text(), "stopping the current flow...")
        self.assertFalse(w.flow.run_button.isEnabled())
        self.assertFalse(w.open_project(SAMPLES))
        self.assertTrue(pump_until(lambda: w.project_dir == other, 10000))
        self.assertFalse(w.flow.is_running())
        with self.assertRaises(ProcessLookupError):
            os.kill(old_pid, 0)
        for _ in range(10):
            QCoreApplication.processEvents()
        self.assertNotIn("old-run-output", w.flow.log.toPlainText())
        self.assertEqual(w.messages.count(), 0)
        self.assertEqual(w.flow.progress.value(), 0)
        self.assertEqual(w.flow.status_label.text(), "idle")
        self.assertTrue(w.flow.run_button.isEnabled())

    def test_stale_run_is_ignored(self) -> None:
        panel = FlowPanel()
        argv = [sys.executable, "-c", STUB]
        with mock.patch("wyrd.gui.flowpanel.run_argv", return_value=argv):
            panel.start(self.tmp)
            old, old_token = panel.process, panel._token
            self.assertTrue(wait_for(panel.finished))
            panel.start(self.tmp)
        assert old is not None
        codes: list[int] = []
        panel.finished.connect(codes.append)
        panel._on_stdout(old, old_token)
        panel._on_finished(old, old_token, 0, QProcess.ExitStatus.NormalExit)
        panel._on_error(old, old_token, QProcess.ProcessError.FailedToStart)
        self.assertEqual(codes, [])
        self.assertTrue(wait_for(panel.finished))
        self.assertEqual(codes, [1])

    def test_repeated_cancel_does_not_stack(self) -> None:
        panel = FlowPanel()
        argv = [sys.executable, "-c", SLEEPER]
        with mock.patch("wyrd.gui.flowpanel.run_argv", return_value=argv):
            panel.start(self.tmp)
        pump_until(lambda: "started" in panel.log.toPlainText())
        with (
            mock.patch("wyrd.gui.flowpanel.QTimer.singleShot") as shot,
            mock.patch("wyrd.gui.flowpanel.os.kill") as kill,
        ):
            panel.cancel()
            panel.cancel()
            panel.cancel()
            self.assertEqual(shot.call_count, 2)
            self.assertEqual(kill.call_count, 1)
        panel.cancel_button.setEnabled(True)
        panel.shutdown()  # a shorter escalation may still be added once
        self.assertTrue(pump_until(lambda: not panel.is_running(), 8000))

    def test_crash_error_shown_once(self) -> None:
        w = window(self.tmp)
        w.open_project(SAMPLES)
        argv = [sys.executable, "-c", CRASHER]
        with (
            mock.patch("wyrd.gui.flowpanel.run_argv", return_value=argv),
            mock.patch.object(w, "_show_error") as show,
        ):
            w.flow.start(self.tmp)
            self.assertTrue(pump_until(lambda: not w.flow.is_running()))
            for _ in range(10):
                QCoreApplication.processEvents()
        self.assertEqual(show.call_count, 1)

    def test_close_stops_step_loads(self) -> None:
        w = window(self.tmp)
        w.open_project(SAMPLES)
        self.assertTrue(w.close())
        with mock.patch.object(w.messages, "set_messages") as put:
            w._load_signals.done.emit(w._load_generation, [], [])
            put.assert_not_called()

    def test_open_discard_prompt(self) -> None:
        w = live_window(self.tmp)
        w.open_project(copy_project(self.tmp))
        w.editor.text.setPlainText("x = 1\n")
        with mock.patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.No
        ):
            self.assertFalse(w.open_project(SAMPLES))
        self.assertTrue(w.editor.is_modified())

    def test_close_waits_for_stubborn_flow(self) -> None:
        w = window(self.tmp)
        w.open_project(SAMPLES)
        w.flow.close_term_ms = 200
        w.flow.kill_ms = 200
        argv = [sys.executable, "-c", STUBBORN]
        with mock.patch("wyrd.gui.flowpanel.run_argv", return_value=argv):
            w.flow.start(self.tmp)
        pump_until(lambda: "ready" in w.flow.log.toPlainText())
        self.assertFalse(w.close())
        self.assertIsNone(w.settings.value("geometry"))
        self.assertTrue(pump_until(lambda: w.settings.value("geometry") is not None, 8000))
        self.assertFalse(w.flow.is_running())

    def test_new_project_runs_init_off_thread(self) -> None:
        w = window(self.tmp)
        target = self.tmp / "fresh"
        target.mkdir()
        codes: list[int] = []
        w.init_finished.connect(codes.append)
        with mock.patch.object(QFileDialog, "getExistingDirectory", return_value=str(target)):
            w._new_project()
        self.assertTrue(pump_until(lambda: bool(codes), 8000))
        self.assertEqual(codes, [0])
        self.assertTrue((target / "wyrd.toml").is_file())
        self.assertEqual(w.project_dir, target)

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
        binary = self.tmp / "blob.v"
        binary.write_bytes(b"abc\0def")
        self.assertFalse(view.open_file(binary))
        self.assertIn("binary", view.text.toPlainText())
        self.assertFalse(view.open_file(self.tmp))
        fifo = self.tmp / "pipe.v"
        os.mkfifo(fifo)
        self.assertFalse(view.open_file(fifo))
        self.assertIn("not a regular file", view.text.toPlainText())
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
        self.assertTrue(pump_until(lambda: w.messages.count() == 8))
        self.assertEqual(w.messages.count(), 8)
        button = w.report_view.floorplan_button
        self.assertFalse(button.isEnabled())
        run_info = w.report_view.current_run()
        assert run_info is not None
        self.assertEqual(button.toolTip(), plan_floorplan(run_info.run_dir))

    def test_big_step_log_is_bounded(self) -> None:
        run = self.tmp / "run"
        step = run / "0-odin3-flow"
        step.mkdir(parents=True)
        log = step / "odin3.log"
        line = b"odin3: warning: a.v:1: thing\n"
        log.write_bytes(line * (3_000_000 // len(line) + 1))
        self.assertLessEqual(len(read_log_limited(log)), 2_000_000)
        messages, search = load_messages(run)
        self.assertGreater(len(messages), 0)
        self.assertIn(step, search)
        self.assertEqual(read_log_limited(self.tmp), "")

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
STUBBORN = (
    "import signal, time\n"
    "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "print('ready', flush=True)\n"
    "time.sleep(60)\n"
)
OLD_RUN = (
    "import sys, time\n"
    "try:\n"
    "    while True:\n"
    "        print('old-run-output', flush=True)\n"
    "        time.sleep(0.05)\n"
    "except KeyboardInterrupt:\n"
    "    print('late old-run-output', flush=True)\n"
    "    time.sleep(0.5)\n"
    "    print('later old-run-output', flush=True)\n"
)
CRASHER = "import os, signal\nprint('x', flush=True)\nos.kill(os.getpid(), signal.SIGKILL)\n"
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

    def test_cancel_guard_when_starting(self) -> None:
        panel = FlowPanel()
        fake = mock.MagicMock()
        fake.state.return_value = QProcess.ProcessState.Starting
        fake.processId.return_value = 0
        panel.process = fake
        with mock.patch("wyrd.gui.flowpanel.os.kill") as kill:
            panel.cancel()
            kill.assert_not_called()
        fake.state.return_value = QProcess.ProcessState.Running
        with mock.patch("wyrd.gui.flowpanel.os.kill") as kill:
            panel.cancel()
            kill.assert_not_called()
        fake.processId.return_value = 4321
        with mock.patch("wyrd.gui.flowpanel.os.kill", side_effect=ProcessLookupError) as kill:
            panel.cancel()
            kill.assert_called_once()
        self.assertNotEqual(panel.status_label.text(), "cancelling")

    def test_failed_to_start(self) -> None:
        panel = FlowPanel()
        panel.set_can_run(True)
        codes: list[int] = []
        errors: list[str] = []
        panel.finished.connect(codes.append)
        panel.error.connect(errors.append)
        argv = [str(self.tmp / "no-such-program")]
        with mock.patch("wyrd.gui.flowpanel.run_argv", return_value=argv):
            panel.start(self.tmp)
        self.assertTrue(pump_until(lambda: bool(codes)))
        self.assertEqual(codes, [-1])
        self.assertEqual(len(errors), 1)
        self.assertEqual(panel.status_label.text(), "failed to start")
        self.assertEqual(panel.progress.maximum(), 1000)
        self.assertTrue(panel.run_button.isEnabled())
        self.assertFalse(panel.cancel_button.isEnabled())
        self.assertIn("failed to start", panel.log.toPlainText())

    def test_failed_to_start_shows_in_messages(self) -> None:
        w = window(self.tmp)
        w.open_project(SAMPLES)
        argv = [str(self.tmp / "no-such-program")]
        with mock.patch("wyrd.gui.flowpanel.run_argv", return_value=argv):
            w.flow.start(self.tmp)
        self.assertTrue(pump_until(lambda: w.messages.count() == 1))
        self.assertEqual(w.messages.count(), 1)
        self.assertIn("failed to start", w.statusBar().currentMessage())

    def test_floorplan_missing_program(self) -> None:
        panel = FlowPanel()
        errors: list[str] = []
        panel.floorplan_error.connect(errors.append)
        plan = FloorplanPlan(str(self.tmp / "no-vpr"), (), self.tmp / "fp", "rerun")
        panel.start_floorplan(plan)
        self.assertTrue(pump_until(lambda: bool(errors)))
        self.assertIn("Cannot start the floorplan viewer", errors[0])

    def test_floorplan_single_instance_and_stop(self) -> None:
        panel = FlowPanel()
        plan = FloorplanPlan(sys.executable, ("-c", SLEEPER), self.tmp / "fp", "rerun")
        panel.start_floorplan(plan)
        first = panel.floorplan_process
        self.assertTrue(pump_until(panel.floorplan_running))
        panel.start_floorplan(plan)
        self.assertIs(panel.floorplan_process, first)
        self.assertIn("already running", panel.log.toPlainText())
        panel.stop_floorplan()
        self.assertTrue(pump_until(lambda: not panel.floorplan_running()))

    def test_floorplan_early_exit(self) -> None:
        panel = FlowPanel()
        cwd = self.tmp / "run" / "floorplan"
        plan = FloorplanPlan(sys.executable, ("-c", "raise SystemExit(3)"), cwd, "rerun")
        panel.start_floorplan(plan)
        pump_until(lambda: "VPR exited early" in panel.log.toPlainText(), 3000)
        self.assertTrue(cwd.is_dir())
        self.assertIn("VPR exited early", panel.log.toPlainText())


def copy_project(tmp: Path) -> Path:
    root = tmp / "edit"
    shutil.copytree(SAMPLES / "designs", root / "designs")
    shutil.copy(SAMPLES / "wyrd.toml", root / "wyrd.toml")
    return root


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class EditorTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_editor_valid(self) -> None:
        w = window(self.tmp)
        w.open_project(SAMPLES)
        self.assertTrue(w.editor.validate_now().ok)
        self.assertEqual(w.editor.status.text(), "Valid: 6 runs")

    def test_editor_error_line(self) -> None:
        w = window(self.tmp)
        w.open_project(SAMPLES)
        text = (SAMPLES / "wyrd.toml").read_text(encoding="utf-8").replace(
            'name = "samples"', "name = 1"
        )
        w.editor.text.setPlainText(text)
        result = w.editor.validate_now()
        expected = validate_text(SAMPLES / "wyrd.toml", text)
        assert result.diagnostic is not None and expected.diagnostic is not None
        self.assertEqual(result.diagnostic.line, expected.diagnostic.line)
        self.assertTrue(w.editor.status.text().startswith("line "))
        self.assertEqual(len(w.editor.text.extraSelections()), 1)

    def test_save_roundtrip(self) -> None:
        root = copy_project(self.tmp)
        w = window(self.tmp)
        w.open_project(root)
        saved: list[bool] = []
        w.editor.saved.connect(lambda: saved.append(True))
        text = w.editor.text.toPlainText().replace("step_timeout = 3600", "step_timeout = 7200")
        w.editor.text.setPlainText(text)
        self.assertTrue(w.editor.is_modified())
        self.assertTrue(w.editor.save())
        self.assertEqual((root / "wyrd.toml").read_text(encoding="utf-8"), text)
        self.assertEqual(saved, [True])
        self.assertFalse(w.editor.is_modified())
        w.editor.text.setPlainText("[project]\nname = 1\n")
        self.assertTrue(w.editor.save())
        self.assertEqual((root / "wyrd.toml").read_text(encoding="utf-8"), "[project]\nname = 1\n")

    def test_add_design_dialog(self) -> None:
        root = copy_project(self.tmp)
        dlg = AddDesignDialog(root, {"single"})
        dlg.name_edit.setText("single")
        dlg.files_list.addItem("x.v")
        dlg.accept()
        self.assertNotEqual(dlg.result(), QDialog.DialogCode.Accepted)
        self.assertNotEqual(dlg.error_label.text(), "")
        dlg.name_edit.setText("newd")
        dlg.accept()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dlg.result_values(), ("newd", ["x.v"], None, True))
        w = window(self.tmp)
        w.open_project(root)
        before = w.editor.text.toPlainText()
        w.apply_design(*dlg.result_values())
        self.assertNotEqual(w.editor.text.toPlainText(), before)
        self.assertIn('name = "newd"', w.editor.text.toPlainText())
        self.assertTrue(w.editor.is_modified())
        self.assertIs(w.tabs.currentWidget(), w.editor)

    def test_save_keeps_editor_state(self) -> None:
        root = copy_project(self.tmp)
        w = window(self.tmp)
        w.open_project(root)
        text = w.editor.text.toPlainText().replace("step_timeout = 3600", "step_timeout = 7200")
        w.editor.text.setPlainText(text)
        cursor = w.editor.text.textCursor()
        cursor.setPosition(10)
        cursor.insertText("# note\n")
        w.editor.text.setTextCursor(cursor)
        pos = cursor.position()
        with mock.patch.object(w.editor, "load") as reload:
            self.assertTrue(w.editor.save())
            reload.assert_not_called()
        self.assertEqual(w.editor.text.textCursor().position(), pos)
        self.assertTrue(w.editor.text.document().isUndoAvailable())
        self.assertIsNotNone(w.project)

    def test_unreadable_toml_refuses_save(self) -> None:
        d = self.tmp / "latin"
        d.mkdir()
        (d / "wyrd.toml").write_bytes(b"[project]\nname = '\xff'\n")
        w = window(self.tmp)
        w.open_project(d)
        self.assertIn("Cannot read", w.editor.status.text())
        self.assertFalse(w.editor.save())
        self.assertEqual((d / "wyrd.toml").read_bytes(), b"[project]\nname = '\xff'\n")
        self.assertIn("not loaded", w.editor.status.text())

    def test_unsaved_edits_do_not_block_open(self) -> None:
        w = window(self.tmp)
        w.open_project(copy_project(self.tmp))
        w.editor.text.setPlainText("x = 1\n")
        self.assertTrue(w.open_project(SAMPLES))
        self.assertFalse(w.editor.is_modified())


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class DialogsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_settings_dialog(self) -> None:
        path = self.tmp / "cfg" / "machine.toml"
        dlg = SettingsDialog(path)
        self.assertIsInstance(dlg.editors["resources.jobs"], QSpinBox)
        combo = dlg.editors["resources.launcher"]
        assert isinstance(combo, QComboBox)
        self.assertEqual([combo.itemText(i) for i in range(combo.count())], ["systemd", "plain"])
        combo.setCurrentText("plain")
        dlg.accept()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["resources"]["launcher"], "plain")

    def test_settings_dialog_rejects_bad_value(self) -> None:
        path = self.tmp / "machine.toml"
        dlg = SettingsDialog(path)
        edit = dlg.editors["defaults.history_factor"]
        assert isinstance(edit, QLineEdit)
        edit.setText("abc")
        dlg.accept()
        self.assertNotEqual(dlg.result(), QDialog.DialogCode.Accepted)
        self.assertNotEqual(dlg.error_label.text(), "")
        self.assertFalse(path.exists())

    def test_about(self) -> None:
        dlg = AboutDialog()
        self.assertEqual(dlg.table.rowCount(), 14)
        cell = dlg.table.item(0, 0)
        assert cell is not None
        self.assertEqual(cell.text(), "VTR (Verilog-to-Routing)")


if __name__ == "__main__":
    unittest.main()
