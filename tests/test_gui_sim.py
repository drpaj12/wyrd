"""Simulate tab tests; Qt runs offscreen and the simulator is the Python fake."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.fakes_sim import FakeBackend
from wyrd.bifrost.errors import SimUnavailable

HAVE_QT = importlib.util.find_spec("PySide6") is not None

if HAVE_QT:
    from PySide6.QtCore import QCoreApplication, QSettings
    from PySide6.QtWidgets import QApplication, QMenu

    from wyrd.gui.mainwindow import MainWindow
    from wyrd.gui.simpanel import SimPanel
    from wyrd.project import load_project

    _APP: QCoreApplication | None = None

    def setUpModule() -> None:
        global _APP
        _APP = QApplication.instance() or QApplication([])


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


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class SimPanelTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.backend = FakeBackend()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def opened(self, source: str = "module traffic") -> "MainWindow":
        d = project_dir(self.tmp, source)
        w = window(self.tmp, self.backend)
        self.assertTrue(w.open_project(d))
        self.addCleanup(w.sim_panel.close_session)
        return w

    def test_compile_fills_table(self) -> None:
        panel = self.opened().sim_panel
        self.assertTrue(panel.compile())
        self.assertEqual(panel.signals_table.rowCount(), 6)
        self.assertIn("Compiled", panel.status_label.text())
        panel.internal_box.setChecked(True)
        self.assertTrue(panel.compile())
        self.assertEqual(panel.signals_table.rowCount(), 8)

    def test_set_and_step(self) -> None:
        panel = self.opened().sim_panel
        self.assertTrue(panel.compile())
        self.assertTrue(panel.set_input("rst", "1"))
        panel.step_button.click()
        self.assertEqual(panel.value_text("light_ns"), "2")
        self.assertFalse(panel.set_input("car_ew", "0x2"))
        self.assertTrue(any(panel.cell_tooltips()))
        self.assertFalse(panel.set_input("light_ns", "1"))

    def test_random_run_and_waveform(self) -> None:
        panel = self.opened().sim_panel
        panel.compile()
        panel.random_cycles.setValue(16)
        panel.seed_box.setValue(3)
        panel.run_random_button.click()
        self.assertEqual(panel.waveform.sample_count, 17)
        self.assertEqual(len(panel.waveform.rows), 5)
        self.assertFalse(panel.waveform.grab().isNull())

    def test_vectors_error_line(self) -> None:
        panel = self.opened().sim_panel
        panel.compile()
        panel.vectors_edit.setPlainText("0 100\n1 xx1\n")
        panel.run_vectors_button.click()
        self.assertTrue(panel.status_label.text().startswith("<vectors>:2:"))
        self.assertEqual(panel.vectors_edit.textCursor().blockNumber(), 1)

    def test_diagnostics_click(self) -> None:
        panel = self.opened("SYNTAX_ERROR").sim_panel
        got: list[tuple[Path, int]] = []
        panel.location_activated.connect(lambda p, n: got.append((p, n)))
        self.assertFalse(panel.compile())
        self.assertEqual(panel.diagnostics_table.rowCount(), 1)
        panel.diagnostics_table.cellDoubleClicked.emit(0, 0)
        self.assertEqual(got, [(self.tmp / "traffic.v", 2)])

    def test_save_vcd(self) -> None:
        panel = self.opened().sim_panel
        panel.compile()
        panel.run_random_button.click()
        out = self.tmp / "o.vcd"
        panel.save_vcd(out)
        self.assertTrue(out.read_text(encoding="utf-8").startswith("$version wyrd sim $end"))

    def test_gtkwave(self) -> None:
        calls: list[tuple[str, list[str]]] = []

        def launcher(program: str, args: list[str]) -> bool:
            calls.append((program, args))
            return True

        d = project_dir(self.tmp)
        panel = SimPanel(self.backend, launcher)
        self.addCleanup(panel.close_session)
        panel.set_project(load_project(d / "wyrd.toml"), d)
        panel.compile()
        panel.run_random_button.click()
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
        panel.record_box.setChecked(False)
        panel.compile()
        with mock.patch.dict(os.environ, {"WYRD_GTKWAVE": "/bin/true"}):
            panel.gtkwave_button.click()
        self.assertEqual(len(calls), 1)

    def test_unavailable(self) -> None:
        with mock.patch(
            "wyrd.gui.simpanel.default_backend", side_effect=SimUnavailable("x is missing")
        ):
            panel = SimPanel(backend=None)
        self.assertFalse(panel.compile_button.isEnabled())
        self.assertEqual(panel.status_label.text(), "x is missing")

    def test_run_timer(self) -> None:
        panel = self.opened().sim_panel
        panel.compile()
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


if __name__ == "__main__":
    unittest.main()
