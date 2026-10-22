"""Screenshots of the Wyrd III GUI for the tutorial, from the real GUI against real Odin III.

    QT_QPA_PLATFORM=offscreen python gui_shots.py PROJECT_DIR OUT_DIR [SAMPLES_DIR]

PROJECT_DIR holds wyrd.toml and src/ (made by make_shots.py); it is run for real. Needs odin3,
odin3-flow and VTR_ROOT as `wyrd run` does, and the odin3 Python package for the Simulate tab.
No data is made up: every picture is a grab of a live widget.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QWidget

from wyrd.gui.adddesign import AddDesignDialog
from wyrd.gui.mainwindow import MainWindow
from wyrd.gui.settingsdialog import SettingsDialog
from wyrd.settings import machine_path

SIZE = (1280, 800)


def pump(app: QApplication, seconds: float = 0.3) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def wait(app: QApplication, cond: Callable[[], bool], timeout: float = 120.0) -> None:
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            raise TimeoutError("GUI step did not finish")
        app.processEvents()
        time.sleep(0.02)
    pump(app, 0.2)


def grab(widget: QWidget, out: Path, name: str) -> None:
    app = QApplication.instance()
    if isinstance(app, QApplication):
        pump(app, 0.2)
    if not widget.grab().save(str(out / f"{name}.png")):
        raise OSError(f"cannot write {name}.png")
    print("shot", name)


def samples_shot(app: QApplication, win: MainWindow, out: Path, samples: Path) -> None:
    win.open_project(samples)
    wait(app, lambda: win.project is not None and win.project.name == "samples")
    win.tabs.setCurrentWidget(win.report_view)
    win.docks["Flow"].show()
    win.docks["Flow"].raise_()
    win.refresh_results()
    pump(app, 1.0)
    grab(win, out, "gui-samples")


def main(project: Path, out: Path, samples: Path | None) -> int:
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    settings = QSettings(str(project.parent / "gui.ini"), QSettings.Format.IniFormat)
    win = MainWindow(settings, silent=True)
    win.resize(*SIZE)
    win.show()
    pump(app)
    grab(win, out, "gui-empty")
    win.open_project(project)
    wait(app, lambda: win.project is not None)
    win.show_source(project / "src" / "top.v")
    grab(win, out, "gui-open")
    win.tabs.setCurrentWidget(win.editor)
    grab(win, out, "gui-toml")
    dialogs(app, win, out)
    run_flow(app, win, out)
    simulate(app, win, out, project)
    if samples is not None:
        samples_shot(app, win, out, samples)
    return 0


def dialogs(app: QApplication, win: MainWindow, out: Path) -> None:
    assert win.project is not None and win.project_dir is not None
    add = AddDesignDialog(win.project_dir, set(win.project.designs), win)
    add.name_edit.setText("counter2")
    add.files_list.addItem("src/counter.v")
    add.top_edit.setText("counter")
    add.show()
    grab(add, out, "gui-adddesign")
    add.close()
    dlg = SettingsDialog(machine_path(), win)
    dlg.show()
    grab(dlg, out, "gui-settings")
    dlg.close()


def run_flow(app: QApplication, win: MainWindow, out: Path) -> None:
    win.docks["Flow"].show()
    win.docks["Flow"].raise_()
    win.flow.force_box.setChecked(True)  # the CLI already ran the project: re-run, do not reuse
    win._run_flow()
    wait(app, lambda: win.flow.process is not None)
    grab(win, out, "gui-running")
    wait(app, lambda: not win.flow.is_running())
    win.refresh_results()
    pump(app, 1.0)
    win.tabs.setCurrentWidget(win.report_view)
    grab(win, out, "gui-flow-done")
    tree = win.report_view.tree
    run_item = tree.topLevelItem(1)
    if run_item is None:
        raise RuntimeError("no run in the report tree")
    run_item.setExpanded(True)
    summary = run_item.child(0)
    step_item = run_item.child(1)
    if summary is None or step_item is None:
        raise RuntimeError("the run has no Summary or step node")
    tree.setCurrentItem(summary)
    pump(app, 1.0)
    grab(win, out, "gui-report")
    step_item.setExpanded(True)
    log_item = step_item.child(0)
    if log_item is None:
        raise RuntimeError("the step has no log node")
    tree.setCurrentItem(log_item)  # odin3.log
    pump(app, 1.0)
    win.docks["Messages"].show()
    win.docks["Messages"].raise_()
    grab(win, out, "gui-report-log")


def simulate(app: QApplication, win: MainWindow, out: Path, project: Path) -> None:
    panel = win.sim_panel
    win.docks["Flow"].hide()
    win.docks["Messages"].hide()
    win.tabs.setCurrentWidget(panel)
    grab(win, out, "gui-sim-tab")
    panel.compile()
    wait(app, lambda: panel.session is not None)
    grab(win, out, "gui-sim-compiled")
    panel.set_input("rst", "1")
    panel._step(1)
    panel.set_input("rst", "0")
    panel.set_input("step", "9")
    panel._step(5)
    pump(app, 0.5)
    grab(win, out, "gui-sim-stepped")
    panel.set_input("step", "3")
    panel._step(10)
    pump(app, 0.5)
    grab(win, out, "gui-sim-waveform")
    vcd = project / "counteradd-gui.vcd"
    if not panel.save_vcd(vcd):
        raise OSError("VCD not saved")
    print("vcd", vcd)


if __name__ == "__main__":
    extra = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else None
    sys.exit(main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), extra))
