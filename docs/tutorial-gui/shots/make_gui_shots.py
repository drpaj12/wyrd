"""Screenshots for the Wyrd III GUI tutorial, all from the real GUI driving real Odin III and VPR.

    QT_QPA_PLATFORM=offscreen python make_gui_shots.py WORK_DIR

Needs the same environment as the CLI tutorial's shots/make_shots.py: the wyrd venv (PySide6,
pygame-ce, odin3 with the simulation API), `odin3` and `odin3-flow` on PATH, PYTHONPATH and
ODIN3_LIB for the odin3 Python package, and VTR (the machine file takes it from vtr_root).
The machine file is the one `wyrd config init` writes into WORK_DIR (WYRD_CONFIG), never the
reader's own. Typical call:

    O=~/odin3-ws/odin3
    PATH=$O/build/release:$O/tools/flow:$PATH PYTHONPATH=$O/plugins/python \\
      ODIN3_LIB=$O/build/release/libodin3.so VTR_ROOT=~/odin3-ws/external/vtr-verilog-to-routing \\
      python make_gui_shots.py /tmp/claude-1000/guitut-work

Output: ../images/gt-*.png. Every picture is a grab of a live widget; the numbers in them are
those of the real runs. File and folder housekeeping is done here with the same steps the
tutorial shows as shell blocks. The tutorial's project sources are used in place from
docs/tutorial/project (they are not copied into the repository a second time).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSettings
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from wyrd.gui.adddesign import AddDesignDialog
from wyrd.gui.mainwindow import MainWindow
from wyrd.gui.settingsdialog import SettingsDialog

HERE = Path(__file__).resolve().parent
TUT = HERE.parent
IMAGES = TUT / "images"
CLI_PROJECT = TUT.parent / "tutorial" / "project"
SAMPLES = TUT.parent.parent / "samples"
SIZE = (1280, 800)
MARKER = ".wyrd-gui-tutorial-work"


def pump(app: QApplication, seconds: float = 0.3) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def wait(app: QApplication, cond: Callable[[], bool], timeout: float = 180.0) -> None:
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            raise TimeoutError("GUI step did not finish")
        app.processEvents()
        time.sleep(0.02)
    pump(app, 0.2)


def grab(widget: QWidget, name: str) -> None:
    app = QApplication.instance()
    if isinstance(app, QApplication):
        pump(app, 0.2)
    if not widget.grab().save(str(IMAGES / f"{name}.png")):
        raise OSError(f"cannot write {name}.png")
    print("shot", name)


def menu_shot(app: QApplication, win: MainWindow, title: str, name: str) -> None:
    """Open the named top-level menu and grab the popup."""
    for act in win.menuBar().actions():
        menu = act.menu()
        if isinstance(menu, QMenu) and act.text().replace("&", "") == title:
            menu.popup(QPoint(40, 40))
            pump(app, 0.3)
            grab(menu, name)
            menu.hide()
            return
    raise RuntimeError(f"no menu {title}")


def clear_root(root: Path) -> None:
    """Empty the work directory, but only one this script made (it holds MARKER) or an empty one."""
    if not root.exists():
        return
    resolved = root.resolve()
    if resolved in {Path("/"), Path.home().resolve(), Path.cwd().resolve()}:
        raise SystemExit(f"refusing to clear {resolved}")
    if any(resolved.iterdir()) and not (resolved / MARKER).is_file():
        raise SystemExit(f"refusing to clear {resolved}: not a tutorial work directory")
    shutil.rmtree(resolved)


def show_dock(win: MainWindow, name: str) -> None:
    win.docks[name].show()
    win.docks[name].raise_()


def select_run_child(win: MainWindow, app: QApplication, index: int) -> None:
    tree = win.report_view.tree
    item = tree.topLevelItem(1)
    if item is None:
        raise RuntimeError("no run in the report tree")
    item.setExpanded(True)
    child = item.child(index)
    if child is None:
        raise RuntimeError(f"run node has no child {index}")
    tree.setCurrentItem(child)
    pump(app, 1.0)


def main(root: Path) -> int:
    clear_root(root)
    root.mkdir(parents=True)
    (root / MARKER).write_text("", encoding="utf-8")
    IMAGES.mkdir(parents=True, exist_ok=True)
    cfg = root / "machine.toml"
    os.environ["WYRD_CONFIG"] = str(cfg)
    subprocess.run([sys.executable, "-m", "wyrd.cli", "config", "init"], check=True,
                   capture_output=True)
    # Shell housekeeping shown in the tutorial: the folder and the Verilog sources.
    demo = root / "demo"
    shutil.copytree(CLI_PROJECT / "src", demo / "src")
    app = QApplication([])
    win = MainWindow(QSettings(str(root / "gui.ini"), QSettings.Format.IniFormat), silent=True)
    win.resize(*SIZE)
    win.show()
    pump(app)
    grab(win, "gt-start")
    menu_shot(app, win, "File", "gt-menu-file")
    win.new_project(demo)
    wait(app, lambda: win.project_dir == demo)  # the template names a file that does not exist yet
    win.tabs.setCurrentWidget(win.editor)
    grab(win, "gt-new-project")
    design(app, win)
    settings(app, win, cfg)
    run_demo(app, win, demo)
    other = compare_demo(app, win, root, demo)
    simulate(app, win, demo)
    samples(app, win, root)
    menu_shot(app, win, "Tools", "gt-menu-tools")
    win.close()
    del other
    return 0


def design(app: QApplication, win: MainWindow) -> None:
    assert win.project_dir is not None
    menu_shot(app, win, "Project", "gt-menu-project")
    dlg = AddDesignDialog(win.project_dir, {"mydesign"}, win)
    dlg.name_edit.setText("counteradd")
    for f in ("src/add4.v", "src/counter.v", "src/top.v"):
        dlg.files_list.addItem(f)
    dlg.top_edit.setText("top")
    dlg.sweep_box.setChecked(True)
    dlg.show()
    grab(dlg, "gt-adddesign")
    win.apply_design(*dlg.result_values())
    dlg.close()
    grab(win, "gt-added")
    # Edit the placeholder design out and set the project name and architectures, as typing would.
    text = win.editor.text.toPlainText()
    text = text.replace('name = "myproject"', 'name = "counteradd"')
    text = text.replace('[[design]]\nname = "mydesign"\nfiles = ["CHANGE_ME.v"]\n# top = "top"\n\n',
                        "")
    text = text.replace('design = ["mydesign", "counteradd"]', 'design = ["counteradd"]')
    text = text.replace('arch = ["k6_frac_N10_frac_chain_mem32K_40nm"]',
                        'arch = ["k6_frac_N10_frac_chain_mem32K_40nm", "EArch"]')
    win.editor.set_text(text)
    pump(app, 1.0)
    grab(win, "gt-edited")
    win.editor.save()
    pump(app, 1.5)
    assert win.project is not None and list(win.project.designs) == ["counteradd"], "toml edit"
    win.tabs.setCurrentWidget(win.source_view)
    win.show_source(win.project_dir / "src" / "top.v")
    grab(win, "gt-source")


def settings(app: QApplication, win: MainWindow, cfg: Path) -> None:
    dlg = SettingsDialog(cfg, win)
    dlg.show()
    grab(dlg, "gt-settings")
    dlg.close()


def run_demo(app: QApplication, win: MainWindow, demo: Path) -> None:
    show_dock(win, "Flow")
    grab(win, "gt-flow-idle")
    win._run_flow()
    wait(app, lambda: win.flow.process is not None)
    grab(win, "gt-running")
    wait(app, lambda: not win.flow.is_running())
    win.refresh_results()
    pump(app, 1.5)
    win.tabs.setCurrentWidget(win.report_view)
    grab(win, "gt-flow-done")
    select_run_child(win, app, 0)
    grab(win, "gt-summary")
    win.report_view.tree.setCurrentItem(win.report_view.tree.topLevelItem(0))
    pump(app, 0.8)
    grab(win, "gt-allruns")
    run_item = win.report_view.tree.topLevelItem(1)
    assert run_item is not None
    step = run_item.child(1)
    assert step is not None
    step.setExpanded(True)
    log_item = step.child(0)
    assert log_item is not None
    win.report_view.tree.setCurrentItem(log_item)
    pump(app, 1.0)
    show_dock(win, "Messages")
    grab(win, "gt-log")
    print("messages", win.messages.count())
    win.messages.filter.setCurrentText("Warnings")
    pump(app, 0.5)
    grab(win, "gt-messages-warnings")
    if win.messages.count():
        win.messages.table.selectRow(0)
        win.messages._activated(0, 0)
        pump(app, 0.8)
        grab(win, "gt-messages-source")
    win.messages.filter.setCurrentText("All")


def compare_demo(app: QApplication, win: MainWindow, root: Path, demo: Path) -> Path:
    # Shell housekeeping: a copy of the project whose top.v has a registered output.
    other = root / "demo2"
    shutil.copytree(demo, other, ignore=shutil.ignore_patterns("runs", "*.vcd"))
    shutil.copy(CLI_PROJECT / "variants" / "top_registered.v", other / "src" / "top.v")
    win.open_project(other)
    wait(app, lambda: win.project is not None and win.project_dir == other)
    win.flow.force_box.setChecked(False)
    win._run_flow()
    wait(app, lambda: win.flow.process is not None)
    wait(app, lambda: not win.flow.is_running())
    win.refresh_results()
    pump(app, 1.5)
    win.tabs.setCurrentWidget(win.report_view)
    tree = win.report_view.tree
    compare_item = tree.topLevelItem(tree.topLevelItemCount() - 1)
    assert compare_item is not None
    tree.setCurrentItem(compare_item)
    pump(app, 0.8)
    grab(win, "gt-compare-empty")
    win.report_view.compare_with(demo)
    pump(app, 0.8)
    grab(win, "gt-compare")
    return other


def simulate(app: QApplication, win: MainWindow, demo: Path) -> None:
    win.open_project(demo)
    wait(app, lambda: win.project is not None and win.project_dir == demo)
    panel = win.sim_panel
    win.docks["Flow"].hide()
    win.docks["Messages"].hide()
    win.tabs.setCurrentWidget(panel)
    grab(win, "gt-sim-tab")
    panel.compile()
    wait(app, lambda: panel.session is not None)
    grab(win, "gt-sim-compiled")
    panel.set_input("rst", "1")
    panel._step(1)
    panel.set_input("rst", "0")
    panel.set_input("step", "9")
    panel._step(5)
    pump(app, 0.5)
    grab(win, "gt-sim-stepped")
    panel.set_input("step", "3")
    panel._step(10)
    pump(app, 0.5)
    grab(win, "gt-sim-waveform")


def samples(app: QApplication, win: MainWindow, root: Path) -> None:
    scratch = root / "samples"
    shutil.copytree(SAMPLES, scratch,
                    ignore=shutil.ignore_patterns("expected", "make-expected", "__pycache__"))
    win.open_project(scratch)
    wait(app, lambda: win.project is not None and win.project.name == "samples")
    win.tabs.setCurrentWidget(win.report_view)
    show_dock(win, "Flow")
    grab(win, "gt-samples-open")
    win.flow.force_box.setChecked(False)
    win._run_flow()
    wait(app, lambda: win.flow.process is not None)
    wait(app, lambda: not win.flow.is_running(), timeout=900.0)
    win.refresh_results()
    pump(app, 1.5)
    win.report_view.tree.setCurrentItem(win.report_view.tree.topLevelItem(0))
    pump(app, 1.0)
    grab(win, "gt-samples")


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
