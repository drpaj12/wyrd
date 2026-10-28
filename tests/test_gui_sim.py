"""Simulate tab tests; Qt runs offscreen and the simulator is the Python fake."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import gc
import importlib.util
import shutil
import tempfile
import time
import unittest
import weakref
from pathlib import Path
from typing import Any
from unittest import mock

from tests.fakes_sim import FakeBackend
from wyrd.bifrost.errors import SimUnavailable

HAVE_QT = importlib.util.find_spec("PySide6") is not None

if HAVE_QT:
    from PySide6.QtCore import QRect, QSettings
    from PySide6.QtWidgets import QApplication, QMenu, QPushButton, QWidget

    from tests.qt_helpers import dispose, qapp
    from wyrd.gui.mainwindow import MainWindow
    from wyrd.gui.simpanel import SimPanel
    from wyrd.project import load_project

    def setUpModule() -> None:
        qapp()


TOML = """[project]
name = "t"

[[design]]
name = "traffic"
files = ["traffic.v"]

[recipe.r]
steps = [{ use = "odin3-flow", target = "vtr", vpr = true }]

[sweep]
recipe = ["r"]
design = ["traffic"]
arch = ["k6"]
"""


def project_dir(tmp: Path, source: str = "module traffic") -> Path:
    (tmp / "wyrd.toml").write_text(TOML, encoding="utf-8")
    (tmp / "traffic.v").write_text(source + "\n", encoding="utf-8")
    return tmp


def window(tmp: Path, backend: FakeBackend) -> "MainWindow":
    settings = QSettings(str(tmp / "s.ini"), QSettings.Format.IniFormat)
    return MainWindow(settings, silent=True, sim_backend=backend)


def compiled(panel: "SimPanel") -> bool:
    """Compile and wait for the worker; True when a session came out."""
    started = panel.compile()
    return started and panel.wait() and panel.session is not None


def run_and_wait(panel: "SimPanel", button: "QPushButton") -> None:
    button.click()
    assert panel.wait()


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class SimPanelTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.backend = FakeBackend()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def own(self, widget: "QWidget") -> None:
        """Delete the widget when the test ends (cleanups run last-in first-out)."""
        self.addCleanup(dispose, widget)

    def panel(self, *args: Any) -> "SimPanel":
        panel = SimPanel(*args)
        self.own(panel)
        return panel

    def opened(self, source: str = "module traffic") -> "MainWindow":
        d = project_dir(self.tmp, source)
        w = window(self.tmp, self.backend)
        self.own(w)
        self.assertTrue(w.open_project(d))
        self.addCleanup(w.sim_panel.close_session)
        return w

    def test_compile_fills_table(self) -> None:
        panel = self.opened().sim_panel
        self.assertTrue(compiled(panel))
        self.assertEqual(panel.signals_table.rowCount(), 6)
        self.assertIn("Compiled", panel.status_label.text())
        panel.close_session()
        panel.internal_box.setChecked(True)
        self.assertTrue(compiled(panel))
        self.assertEqual(panel.signals_table.rowCount(), 8)

    def test_set_and_step(self) -> None:
        panel = self.opened().sim_panel
        self.assertTrue(compiled(panel))
        self.assertTrue(panel.set_input("rst", "1"))
        panel.step_button.click()
        self.assertEqual(panel.value_text("light_ns"), "2")
        self.assertFalse(panel.set_input("car_ew", "0x2"))
        self.assertTrue(any(panel.cell_tooltips()))
        self.assertFalse(panel.set_input("light_ns", "1"))

    def test_random_run_and_waveform(self) -> None:
        panel = self.opened().sim_panel
        compiled(panel)
        panel.random_cycles.setValue(16)
        panel.seed_box.setValue(3)
        run_and_wait(panel, panel.run_random_button)
        self.assertEqual(panel.waveform.sample_count, 17)
        self.assertEqual(len(panel.waveform.rows), 5)
        self.assertFalse(panel.waveform.grab().isNull())
        assert panel.session is not None
        for row in panel.waveform.rows:
            self.assertEqual(row.values[-1], panel.session.get(row.name), row.name)

    def test_vectors_error_line(self) -> None:
        panel = self.opened().sim_panel
        compiled(panel)
        panel.vectors_edit.setPlainText("0 100\n1 xx1\n")
        panel.run_vectors_button.click()
        self.assertTrue(panel.status_label.text().startswith("<vectors>:2:"))
        self.assertEqual(panel.vectors_edit.textCursor().blockNumber(), 1)

    def test_diagnostics_click(self) -> None:
        panel = self.opened("SYNTAX_ERROR").sim_panel
        got: list[tuple[Path, int]] = []
        panel.location_activated.connect(lambda p, n: got.append((p, n)))
        self.assertFalse(compiled(panel))
        self.assertEqual(panel.diagnostics_table.rowCount(), 1)
        panel.diagnostics_table.cellDoubleClicked.emit(0, 0)
        self.assertEqual(got, [(self.tmp / "traffic.v", 2)])

    def test_save_vcd(self) -> None:
        panel = self.opened().sim_panel
        compiled(panel)
        run_and_wait(panel, panel.run_random_button)
        out = self.tmp / "o.vcd"
        panel.save_vcd(out)
        self.assertTrue(out.read_text(encoding="utf-8").startswith("$version wyrd sim $end"))

    def test_gtkwave(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        def launcher(program: str, args: list[str]) -> str | None:
            calls.append((program, args))
            return None

        d = project_dir(self.tmp)
        panel = self.panel(self.backend, launcher)
        self.addCleanup(panel.close_session)
        panel.set_project(load_project(d / "wyrd.toml"), d)
        compiled(panel)
        run_and_wait(panel, panel.run_random_button)
        with mock.patch.dict(os.environ, {"WYRD_GTKWAVE": "/bin/true"}):
            panel.gtkwave_button.click()
        vcd = self.tmp / "sim" / "traffic.vcd"
        self.assertEqual(calls, [("/bin/true", [str(vcd)])])
        self.assertTrue(vcd.is_file())
        env = {k: v for k, v in os.environ.items() if k != "WYRD_GTKWAVE"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("shutil.which") as which:
            which.return_value = None
            panel.gtkwave_button.click()
        self.assertIn("gtkwave not found", panel.status_label.text())
        self.assertEqual(len(calls), 1)
        panel.close_session()
        panel.record_box.setChecked(False)
        compiled(panel)
        with mock.patch.dict(os.environ, {"WYRD_GTKWAVE": "/bin/true"}):
            panel.gtkwave_button.click()
        self.assertEqual(len(calls), 1)

    def test_unavailable(self) -> None:
        with mock.patch(
            "wyrd.gui.simpanel.default_backend", side_effect=SimUnavailable("x is missing")
        ):
            panel = self.panel(None)
        self.assertFalse(panel.compile_button.isEnabled())
        self.assertEqual(panel.status_label.text(), "x is missing")

    def test_run_timer(self) -> None:
        panel = self.opened().sim_panel
        compiled(panel)
        panel.speed_box.setCurrentText("1000")
        panel.run_button.click()
        end = time.monotonic() + 5
        app = QApplication.instance()
        assert app is not None
        while panel.session is not None and panel.session.cycle < 100 and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.005)
        panel.run_button.click()
        assert panel.session is not None
        self.assertGreaterEqual(panel.session.cycle, 100)
        self.assertEqual(panel.waveform.sample_count, panel.session.cycle + 1)

    def test_tools_menu(self) -> None:
        w = self.opened()
        bar = w.menuBar()
        assert bar is not None
        tools = [m for m in bar.findChildren(QMenu) if m.title() == "Tools"]
        self.assertEqual(len(tools), 1)
        menu = tools[0]
        sim = [a for a in menu.actions() if a.text() == "Simulate"]
        self.assertEqual(len(sim), 1)
        w.tabs.setCurrentWidget(w.editor)
        sim[0].trigger()
        self.assertIs(w.tabs.currentWidget(), w.sim_panel)

    def test_long_run_returns_control_and_stops(self) -> None:
        panel = self.opened().sim_panel
        compiled(panel)
        assert panel.session is not None
        panel.random_cycles.setValue(5000)
        panel.run_random_button.click()
        self.assertTrue(panel.busy)
        self.assertEqual(panel.session.cycle, 0)
        self.assertFalse(panel.run_random_button.isEnabled())
        self.assertFalse(panel.step_n_button.isEnabled())
        self.assertTrue(panel.stop_button.isEnabled())
        panel._job_tick()
        self.assertEqual(panel.session.cycle, 1000)
        self.assertEqual(panel.progress_label.text(), "Run random: 1000/5000")
        panel.stop_button.click()
        self.assertFalse(panel.busy)
        self.assertEqual(panel.session.cycle, 1000)
        self.assertTrue(panel.status_label.text().startswith("stopped at 1000/5000"))
        self.assertTrue(panel.run_random_button.isEnabled())
        self.assertFalse(panel.stop_button.isEnabled())
        self.assertEqual(panel.waveform.sample_count, 1001)
        out = self.tmp / "partial.txt"
        self.assertTrue(panel.save_vectors(out))
        self.assertEqual(len(out.read_text(encoding="utf-8").splitlines()), 1000 + 7)

    def test_step_n_runs_in_chunks(self) -> None:
        panel = self.opened().sim_panel
        compiled(panel)
        assert panel.session is not None
        panel.step_n_box.setValue(2500)
        panel.step_n_button.click()
        self.assertTrue(panel.busy)
        self.assertEqual(panel.session.cycle, 0)
        self.assertTrue(panel.wait())
        self.assertEqual(panel.session.cycle, 2500)
        self.assertEqual(panel.status_label.text(), "stepped 2500 cycles")
        self.assertEqual(panel.waveform.sample_count, 2501)

    def test_vector_run_in_chunks_matches_random(self) -> None:
        panel = self.opened().sim_panel
        compiled(panel)
        panel.random_cycles.setValue(2200)
        panel.seed_box.setValue(9)
        run_and_wait(panel, panel.run_random_button)
        assert panel.session is not None
        rows = panel.waveform.rows
        self.assertEqual(panel.waveform.sample_count, 2201)
        saved = self.tmp / "a.vec"
        self.assertTrue(panel.save_vectors(saved))
        panel.vectors_edit.setPlainText(saved.read_text(encoding="utf-8"))
        run_and_wait(panel, panel.run_vectors_button)
        self.assertEqual(panel.waveform.rows, rows)

    def test_compile_runs_in_worker(self) -> None:
        panel = self.opened().sim_panel
        self.assertTrue(panel.compile())
        self.assertTrue(panel.busy)
        self.assertIsNone(panel.session)
        self.assertFalse(panel.compile_button.isEnabled())
        self.assertTrue(panel.wait())
        self.assertIsNotNone(panel.session)
        self.assertTrue(panel.compile_button.isEnabled())

    def test_shutdown_waits_for_the_worker(self) -> None:
        panel = self.opened().sim_panel
        self.assertTrue(panel.compile())
        panel.shutdown()
        self.assertEqual(panel._pool.activeThreadCount(), 0)
        self.assertIsNone(panel.session)
        self.assertFalse(panel.busy)

    def test_dropped_panel_is_freed(self) -> None:
        # A signal connected to a lambda that holds the panel kept it alive to interpreter exit,
        # where PySide deleted it during finalization and crashed (exit 139).
        d = project_dir(self.tmp)
        panel = SimPanel(self.backend)
        panel.set_project(load_project(d / "wyrd.toml"), d)
        self.assertTrue(compiled(panel))
        panel.shutdown()
        ref = weakref.ref(panel)
        del panel
        gc.collect()
        self.assertIsNone(ref())

    def test_unexpected_compile_error_frees_panel(self) -> None:
        panel = self.opened().sim_panel
        with mock.patch(
            "wyrd.gui.simpanel.BifrostSession.from_verilog", side_effect=RuntimeError("boom")
        ):
            self.assertTrue(panel.compile())
            self.assertTrue(panel.wait())
        self.assertIsNone(panel.session)
        self.assertFalse(panel.busy)
        self.assertTrue(panel.compile_button.isEnabled())
        self.assertEqual(panel.status_label.text(), "boom")

    def test_stale_compile_is_dropped(self) -> None:
        panel = self.opened().sim_panel
        self.assertTrue(panel.compile())
        panel.set_project(None, None)
        end = time.monotonic() + 0.3
        app = QApplication.instance()
        assert app is not None
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.005)
        self.assertIsNone(panel.session)
        self.assertFalse(panel.busy)

    def test_setup_options_locked_while_live(self) -> None:
        panel = self.opened().sim_panel
        self.assertTrue(panel.record_box.isEnabled())
        compiled(panel)
        self.assertFalse(panel.record_box.isEnabled())
        self.assertFalse(panel.internal_box.isEnabled())
        panel.close_session()
        self.assertTrue(panel.record_box.isEnabled())
        self.assertTrue(panel.internal_box.isEnabled())

    def test_io_errors_are_reported(self) -> None:
        panel = self.opened().sim_panel
        compiled(panel)
        run_and_wait(panel, panel.run_random_button)
        missing = self.tmp / "nope" / "x"
        self.assertFalse(panel.save_vcd(missing))
        self.assertIn("could not save", panel.status_label.text())
        self.assertFalse(panel.save_vectors(missing))
        self.assertIn("could not save", panel.status_label.text())
        self.assertFalse(panel.save_vectors_text(missing))
        self.assertIn("could not save", panel.status_label.text())
        self.assertFalse(panel.load_vectors(missing))
        self.assertIn("could not open", panel.status_label.text())
        binary = self.tmp / "bin.vec"
        binary.write_bytes(b"\xff\xfe\x80")
        panel.vectors_edit.setPlainText("keep")
        self.assertFalse(panel.load_vectors(binary))
        self.assertIn("could not open", panel.status_label.text())
        self.assertEqual(panel.vectors_edit.toPlainText(), "keep")

    def test_gtkwave_failures(self) -> None:
        d = project_dir(self.tmp)
        panel = self.panel(self.backend, lambda program, args: "no such program")
        self.addCleanup(panel.close_session)
        panel.set_project(load_project(d / "wyrd.toml"), d)
        compiled(panel)
        with mock.patch.dict(os.environ, {"WYRD_GTKWAVE": "/bin/true"}):
            panel.gtkwave_button.click()
        self.assertIn("could not start /bin/true: no such program", panel.status_label.text())
        shutil.rmtree(d / "sim")
        (d / "sim").write_text("a file", encoding="utf-8")
        with mock.patch.dict(os.environ, {"WYRD_GTKWAVE": "/bin/true"}):
            panel.gtkwave_button.click()
        self.assertIn("could not write", panel.status_label.text())

    def test_vcd_name_falls_back_to_design(self) -> None:
        panel = self.opened().sim_panel
        compiled(panel)
        panel.design_combo.clear()
        self.assertEqual(panel.design_name(), "design")
        self.assertTrue(panel.save_vcd(self.tmp / "o.vcd"))
        self.assertIn("design", (self.tmp / "o.vcd").read_text(encoding="utf-8"))

    def test_cursor_header_uses_session_cycle(self) -> None:
        panel = self.opened().sim_panel
        compiled(panel)
        session = panel.session
        assert session is not None
        session.step(5)
        session.start_recording(None)
        session.step(3)
        panel._refresh_waveform()
        panel.waveform.cursor_index = 1
        panel._refresh_values()
        header = panel.signals_table.horizontalHeaderItem(3)
        assert header is not None
        self.assertEqual(header.text(), "Value @6")

    def test_long_recording_window(self) -> None:
        panel = self.opened().sim_panel
        compiled(panel)
        session = panel.session
        assert session is not None
        session.start_recording(None, max_samples=400_000)
        session.step(350_000)
        panel._refresh_waveform()
        view = panel.waveform
        self.assertEqual(view.sample_count, 350_001)
        self.assertEqual(view.first_sample, 250_001)
        self.assertEqual(len(view.rows[0].values), 100_000)
        self.assertIsNone(view.sample_at(0))
        x = 160 + 5 * view.cell_width
        self.assertEqual(view.sample_at(x), 250_006)
        self.assertEqual(view.rows[0].values[-1], session.get(view.rows[0].name))
        rec = session.recording
        assert rec is not None
        view.cursor_index = 250_006
        panel._refresh_values()
        header = panel.signals_table.horizontalHeaderItem(3)
        assert header is not None
        self.assertEqual(header.text(), f"Value @{rec.cycles[250_006]}")
        self.assertFalse(view.grab(QRect(0, 0, 400, 100)).isNull())
        self.assertFalse(view.grab(QRect(view.width() - 400, 0, 400, 100)).isNull())

    def test_set_project_none_closes_session_and_timer(self) -> None:
        panel = self.opened().sim_panel
        compiled(panel)
        panel.run_button.click()
        self.assertTrue(panel.running)
        panel.set_project(None, None)
        self.assertIsNone(panel.session)
        self.assertFalse(panel.running)
        self.assertFalse(panel.run_button.isChecked())

    def test_simulate_needs_project(self) -> None:
        w = window(self.tmp, self.backend)
        self.own(w)
        bar = w.menuBar()
        assert bar is not None
        menu = [m for m in bar.findChildren(QMenu) if m.title() == "Tools"][0]
        sim = [a for a in menu.actions() if a.text() == "Simulate"][0]
        before = w.tabs.currentWidget()
        sim.trigger()
        self.assertIs(w.tabs.currentWidget(), before)
        self.assertIn("Open a project", w.statusBar().currentMessage())


if __name__ == "__main__":
    unittest.main()
