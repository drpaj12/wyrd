"""The Wyrd III main window: menus, docks, tabs, project state."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QProcess, QSettings, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from wyrd.bifrost import Backend
from wyrd.gui.about import AboutDialog
from wyrd.gui.adddesign import AddDesignDialog
from wyrd.gui.atlaspanel import AtlasPanel
from wyrd.gui.editor import TomlEditor
from wyrd.gui.flowpanel import FlowPanel
from wyrd.gui.helpbox import HelpBox
from wyrd.gui.messages import MessagesPane
from wyrd.gui.mimirguide import MimirGuideDialog
from wyrd.gui.mimirpanel import MimirPanel
from wyrd.gui.projecttree import ProjectTree
from wyrd.gui.reportview import ReportView
from wyrd.gui.schematicpanel import SchematicPanel
from wyrd.gui.settingsdialog import SettingsDialog
from wyrd.gui.simpanel import SimPanel
from wyrd.gui.sourceview import SourceView
from wyrd.gui.stepload import LoadSignals, LoadTask
from wyrd.gui.timingpanel import MODE_BOTH, MODE_HOT, MODE_MARGIN, TimingPanel
from wyrd.gui.viewlayout import ViewLayout, scrolled
from wyrd.gui.weakslot import weak
from wyrd.guimodel import heatsource, layoutspec, panelhelp
from wyrd.guimodel.floorplan import FloorplanPlan
from wyrd.guimodel.heat import HeatModel
from wyrd.guimodel.logparse import Message
from wyrd.guimodel.projmodel import project_tree
from wyrd.guimodel.runs import RunInfo
from wyrd.guimodel.tomledit import AddDesignError, add_design
from wyrd.project import ConfigError, Project, load_project
from wyrd.settings import load as load_settings
from wyrd.settings import machine_path

MAX_RECENT = 8
LOAD_WAIT_MS = 2000
NEEDS_PROJECT = (layoutspec.SOURCE, layoutspec.REPORT, layoutspec.SIMULATE)
#: Minimum content size per panel, and whether a narrow dock scrolls instead of shrinking it.
PANEL_MIN: dict[str, tuple[int, int, bool]] = {
    layoutspec.PROJECT: (160, 120, False),
    layoutspec.SOURCE: (320, 160, False),
    layoutspec.REPORT: (420, 260, True),
    layoutspec.EDITOR: (320, 160, False),
    layoutspec.SIMULATE: (520, 300, True),
    layoutspec.MESSAGES: (320, 100, False),
    layoutspec.FLOW: (360, 160, True),
    layoutspec.TIMING: (520, 240, True),
    layoutspec.SCHEMATIC: (240, 160, False),
    layoutspec.ATLAS: (240, 160, False),
    layoutspec.MIMIR: (640, 300, True),
}
MIDGARD_NEEDS = 'needs: pip install "wyrd[midgard]"'


def _start_detached(program: str, args: list[str]) -> bool:
    process = QProcess()
    process.setProgram(program)
    process.setArguments(args)
    result: object = process.startDetached()  # bool at runtime, tuple in the stubs
    return bool(result[0]) if isinstance(result, tuple) else bool(result)


class MainWindow(QMainWindow):
    init_finished = Signal(int)

    def __init__(
        self, settings: QSettings, silent: bool = False, sim_backend: Backend | None = None
    ) -> None:
        super().__init__()
        self.settings = settings
        self.source_picker: Callable[[str], Path | None] = self._ask_source
        self.silent = silent
        self.project: Project | None = None
        self.project_dir: Path | None = None
        self.project_tree = ProjectTree()
        self.source_view = SourceView()
        self.messages = MessagesPane()
        self.report_view = ReportView()
        self.flow = FlowPanel()
        self.timing = TimingPanel()
        self.schematic = SchematicPanel()
        self.atlas = AtlasPanel()
        self.mimir = MimirPanel(settings)
        self.editor = TomlEditor(silent)
        self.sim_panel = SimPanel(sim_backend)
        self.docks: dict[str, QDockWidget] = {}
        self.shown_panel: QWidget = self.editor
        self.viewlayout: ViewLayout | None = None
        self.recent_menu = QMenu("Recent", self)
        self.pool = QThreadPool(self)
        self._load_signals = LoadSignals(self)
        self._load_generation = 0
        self._roots_key: tuple[Path | None, int] | None = None
        self._roots: list[Path] = []
        self._init_proc: QProcess | None = None
        self._closing = False
        self._flow_error = ""
        self._pending_project: Path | None = None
        self._switch_actions: list[QAction] = []
        self._loads_stopped = False
        self.midgard_launcher: Callable[[str, list[str]], bool] = _start_detached
        self._build()
        self._restore()

    def _build(self) -> None:
        self.setWindowTitle("Wyrd III")
        self._build_docks()
        self._build_menus()
        self.project_tree.file_activated.connect(self.show_source)
        self.messages.location_activated.connect(self.show_source)
        self.mimir.store_opened.connect(self._remember_mimir)
        self.mimir.heat_requested.connect(self._on_mimir_heat)
        self.mimir.set_last(str(self.settings.value("lastMimirStore", "") or ""))
        self.sim_panel.location_activated.connect(self.show_source)
        self.timing.location_activated.connect(self.show_source)
        self.timing.heat_changed.connect(self._refresh_heat)
        self.source_view.text.heat_clicked.connect(self._on_heat_click)
        self.report_view.run_selected.connect(self._on_run_selected)
        self.report_view.floorplan_requested.connect(self._on_floorplan)
        self.flow.run_requested.connect(self._run_flow)
        self.flow.finished.connect(self._on_flow_finished)
        self.flow.error.connect(self._on_flow_error)
        self.flow.floorplan_error.connect(self._show_error)
        self.editor.saved.connect(self._on_saved)
        self._load_signals.done.connect(self._on_messages_loaded)

    def _on_saved(self) -> None:
        if self.project_dir is not None:
            self._load_model(self.project_dir)
            self.refresh_results()

    def _on_flow_finished(self, _code: int) -> None:
        pending, self._pending_project = self._pending_project, None
        if pending is not None and not self._closing:
            self._flow_error = ""
            self._set_switching(False)
            self.flow.reset()
            self._load(pending)
            return
        self._set_switching(False)
        self.refresh_results()
        if self._flow_error:
            self._show_error(self._flow_error)
            self._flow_error = ""
        if self._closing:
            QTimer.singleShot(0, self.close)

    def _on_flow_error(self, text: str) -> None:
        """Remember the failure; the finished signal that always follows shows it once."""
        self._flow_error = text

    def _set_switching(self, switching: bool) -> None:
        for act in self._switch_actions:
            act.setEnabled(not switching)
        self.recent_menu.setEnabled(not switching)
        self.refresh_results()

    def _show_error(self, text: str) -> None:
        self.statusBar().showMessage(text)
        msg = Message("error", "wyrd", text, None, None, None, Path(), 0)
        self.messages.set_messages([msg], [], [])

    def _settings_dialog(self) -> None:
        SettingsDialog(machine_path(), self).exec()

    def _about_dialog(self) -> None:
        AboutDialog(self).exec()

    def _add_design_dialog(self) -> None:
        if self.project_dir is None:
            return
        existing = set(self.project.designs) if self.project else set()
        dlg = AddDesignDialog(self.project_dir, existing, self)
        if dlg.exec() == AddDesignDialog.DialogCode.Accepted:
            self.apply_design(*dlg.result_values())

    def apply_design(self, name: str, files: list[str], top: str | None, sweep: bool) -> None:
        text = self.editor.text.toPlainText()
        try:
            new = add_design(text, name, files, top, sweep)
        except AddDesignError as e:
            self.statusBar().showMessage(str(e))
            new = e.text
        self.editor.set_text(new)
        self.show_panel(self.editor)

    def _run_flow(self) -> None:
        if self._pending_project is not None:
            return
        if self.project_dir is not None and self.project is not None:
            self.docks["Flow"].show()
            self.docks["Flow"].raise_()
            self._flow_error = ""
            self.flow.start(self.project_dir)

    def _on_floorplan(self, plan: FloorplanPlan) -> None:
        self.docks["Flow"].show()
        self.docks["Flow"].raise_()
        self.flow.start_floorplan(plan)

    def _start_midgard(self) -> None:
        if self.midgard_launcher(sys.executable, ["-m", "wyrd.midgard"]):
            self.statusBar().showMessage("Started Midgard III")
        else:
            self.statusBar().showMessage("Cannot start Midgard III")

    def _start_level_editor(self) -> None:
        if self.midgard_launcher(sys.executable, ["-m", "wyrd.midgard.editors.level_editor"]):
            self.statusBar().showMessage("Started Midgard III Level Editor")
        else:
            self.statusBar().showMessage("Cannot start Midgard III Level Editor")

    def _show_simulate(self) -> None:
        if self.project is None:
            self.statusBar().showMessage("Open a project to simulate")
            return
        self.show_panel(self.sim_panel)

    def show_source(self, path: Path, line: int | None = None) -> None:
        self.source_view.open_file(path, line)
        self._refresh_heat()
        self.show_panel(self.source_view)

    def _refresh_heat(self) -> None:
        path = self.source_view.path
        mode = self.timing.display_mode()
        if path is None:
            self.source_view.set_heat({})
            self.source_view.set_file_heat(None)
            return
        margin = mode in (MODE_MARGIN, MODE_BOTH)
        self.source_view.set_heat(self.timing.heat_for(path) if margin else {})
        fh = None
        if mode in (MODE_HOT, MODE_BOTH):
            fh = self.timing.file_heat_for(path, self.source_view.text.toPlainText())
        scope = self.timing.heat_scope()
        theta = scope.theta if scope.kind == "near" else None
        model = self.timing.heat_model()
        self.source_view.set_file_heat(fh, theta, model.notes if model is not None else None)

    def _vtr_env(self) -> dict[str, str]:
        """``VTR_ROOT`` from the machine settings, for store paths that name it."""
        try:
            root = load_settings(None, {}).vtr_root
        except (OSError, ValueError):
            return {}
        return {} if root is None else {"VTR_ROOT": str(root)}

    def _ask_source(self, guess: str) -> Path | None:
        """Ask for the source file when the store's path cannot be found (replaced in tests)."""
        name, _ = QFileDialog.getOpenFileName(
            self, "Where is the design's source file?", guess, "Verilog (*.v *.sv *.vh);;All (*)"
        )
        return Path(name) if name else None

    def _on_mimir_heat(self, model: object) -> None:
        """Show a Mímir timing model in the source view (near-critical scope)."""
        if not isinstance(model, HeatModel):
            return
        self.timing.set_roots(self._timing_roots())
        self.timing.extra_env = self._vtr_env()
        self.timing.use_heat_model(model)
        self.timing.scope.setCurrentIndex(2)
        self.timing.mode.setCurrentIndex(MODE_HOT)
        choice = heatsource.find_source(
            model, self.timing.extra_env, self.timing.resolve_source, self.timing.chosen
        )
        if choice.path is None:
            self.statusBar().showMessage(choice.message)
            picked = self.source_picker(choice.guess)
            if picked is None:
                return
            for n in model.known_names():
                if n == choice.name or Path(n).name == picked.name:
                    self.timing.choose_file(n, picked)
            choice = heatsource.SourceChoice(picked, str(picked), f"opened {picked}")
        assert choice.path is not None
        self.show_source(choice.path)
        self._focus_hottest()
        self.statusBar().showMessage(choice.message)

    def _focus_hottest(self) -> None:
        fh = self.source_view.text.file_heat
        if fh is None:
            return
        if fh.ranges:
            r = max(fh.ranges, key=lambda x: (x.crit, -x.line, -x.col_start))
            self.source_view.focus_token(r.line, r.col_start, r.col_end)
        elif fh.lines:
            line = max(fh.lines, key=lambda k: (fh.lines[k], -k))
            self.source_view.focus_token(line, 0, 0)

    def _guide_dialog(self) -> None:
        MimirGuideDialog(self).exec()

    def _on_heat_click(self, line: int, col: int) -> None:
        fh = self.source_view.text.file_heat
        if fh is None:
            return
        r = fh.range_at(line, col)
        paths = r.paths if r is not None else fh.line_paths.get(line, ())
        label = f"{r.word} (line {line})" if r is not None else f"line {line}"
        self.timing.show_paths(label, paths)
        self.show_panel(self.timing)

    def _panel_widgets(self) -> dict[str, QWidget]:
        return {
            layoutspec.PROJECT: self.project_tree,
            layoutspec.SOURCE: self.source_view,
            layoutspec.REPORT: self.report_view,
            layoutspec.EDITOR: self.editor,
            layoutspec.SIMULATE: self.sim_panel,
            layoutspec.MESSAGES: self.messages,
            layoutspec.FLOW: self.flow,
            layoutspec.TIMING: self.timing,
            layoutspec.SCHEMATIC: self.schematic,
            layoutspec.ATLAS: self.atlas,
            layoutspec.MIMIR: self.mimir,
        }

    def _wrap(self, name: str, widget: QWidget) -> QWidget:
        """The panel under its About header; wide panels sit in a scroll area."""
        width, height, scroll = PANEL_MIN[name]
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(HelpBox(name, panel=True, settings=self.settings))
        lay.addWidget(widget, 1)
        if scroll:
            return scrolled(content, width, height)
        content.setMinimumSize(width, height)
        return content

    def _build_docks(self) -> None:
        self.panels = self._panel_widgets()
        self.contents: dict[str, QWidget] = {}
        for name in layoutspec.PANELS:
            dock = QDockWidget(name, self)
            dock.setObjectName("dock-" + name.lower().replace("í", "i"))
            self.contents[name] = self._wrap(name, self.panels[name])
            dock.setWidget(self.contents[name])
            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
            self.docks[name] = dock
        self.viewlayout = ViewLayout(self, self.docks, self.settings)
        self.viewlayout.apply_preset(layoutspec.DEFAULT_PRESET)
        self.viewlayout.polish()

    def show_panel(self, widget: QWidget) -> None:
        """Bring the dock holding ``widget`` to the front (showing it when hidden)."""
        for name, panel in self.panels.items():
            if panel is widget:
                self.shown_panel = widget
                self.docks[name].show()
                self.docks[name].raise_()

    def set_all_about(self, shown: bool) -> None:
        for box in self.findChildren(HelpBox):
            box.set_shown(shown)

    def _action(
        self, menu: QMenu, text: str, slot: Callable[[], object], keys: str | None = None
    ) -> QAction:
        act = QAction(text, self)
        if keys:
            act.setShortcut(QKeySequence(keys))
        act.triggered.connect(lambda _checked=False: slot())  # triggered(bool) would pass a flag
        menu.addAction(act)
        return act

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("File")
        assert file_menu is not None
        self._switch_actions = [
            self._action(file_menu, "New Project...", self._new_project),
            self._action(file_menu, "Open Project...", self._open_dialog, "Ctrl+O"),
        ]
        file_menu.addMenu(self.recent_menu)
        self._action(file_menu, "Open Mímir store...", self._open_mimir)
        file_menu.addSeparator()
        self._action(file_menu, "Save wyrd.toml", self.editor.save, "Ctrl+S")
        self._action(file_menu, "Quit", self.close, "Ctrl+Q")
        project_menu = bar.addMenu("Project")
        assert project_menu is not None
        self.project_menu = project_menu
        self._switch_actions.append(
            self._action(project_menu, "Run flow", self._run_flow, "Ctrl+R")
        )
        self._action(project_menu, "Cancel", self.flow.cancel, "Ctrl+.")
        self._action(project_menu, "Refresh results", self.refresh_results, "F5")
        self._action(project_menu, "Add design...", self._add_design_dialog)
        self._action(project_menu, "Settings...", self._settings_dialog)
        tools_menu = bar.addMenu("Tools")
        assert tools_menu is not None
        self._action(tools_menu, "Simulate", self._show_simulate, "Ctrl+T")
        midgard = self._action(tools_menu, "Midgard III (Verilog Town)", self._start_midgard)
        if importlib.util.find_spec("pygame") is None:
            midgard.setEnabled(False)
            midgard.setToolTip(MIDGARD_NEEDS)
        self.midgard_action = midgard
        editor = self._action(tools_menu, "Midgard III Level Editor", self._start_level_editor)
        editor.setToolTip("Create or update a Midgard III level (needs no pygame)")
        view_menu = bar.addMenu("View")
        assert view_menu is not None
        assert self.viewlayout is not None
        self.viewlayout.build_menu(view_menu, self._action)
        about = view_menu.addMenu("About headers")
        assert about is not None
        self._action(about, "Show all About headers", lambda: self.set_all_about(True))
        self._action(about, "Hide all About headers", lambda: self.set_all_about(False))
        help_menu = bar.addMenu("Help")
        assert help_menu is not None
        self._action(help_menu, panelhelp.GUIDE_MENU_TITLE, self._guide_dialog)
        self._action(help_menu, "About", self._about_dialog)
        self._rebuild_recent()

    def _restore(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        assert self.viewlayout is not None
        if not self.viewlayout.restore():
            self.viewlayout.reset()

    def _recent(self) -> list[str]:
        value = self.settings.value("recentProjects")
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(v) for v in value]
        return []

    def _rebuild_recent(self) -> None:
        self.recent_menu.clear()
        for path in self._recent():
            act = self.recent_menu.addAction(path)
            if act is not None:
                act.setData(path)
                act.triggered.connect(self._open_recent)

    def _open_recent(self) -> None:
        # A bound method, not a lambda: a lambda holding self is kept by Qt and leaks the window.
        act = self.sender()
        if isinstance(act, QAction):
            self.open_project(Path(str(act.data())))

    def _remember(self, path: Path) -> None:
        text = str(path)
        recent = [text] + [r for r in self._recent() if r != text]
        self.settings.setValue("recentProjects", recent[:MAX_RECENT])
        self.settings.setValue("lastProject", text)
        self._rebuild_recent()

    def _warn(self, title: str, text: str) -> None:
        if not self.silent:
            QMessageBox.warning(self, title, text)

    def open_project(self, path: Path) -> bool:
        if self._pending_project is not None:
            return False
        toml = path / "wyrd.toml"
        if not toml.is_file():
            self._warn("Open Project", f"No wyrd.toml in {path}")
            return False
        if not self._confirm_stop_flow("Open another project"):
            return False
        if not self._confirm_discard():
            return False
        if self.flow.is_running():
            self._stop_then_load(path)
        else:
            self._load(path)
        return True

    def _stop_then_load(self, path: Path) -> None:
        """Cancel the running flow; the project loads when the flow has finished."""
        self._pending_project = path
        self._set_switching(True)
        self.statusBar().showMessage("stopping the current flow...")
        self.flow.cancel()
        self.flow.status_label.setText("stopping the current flow...")

    def _confirm_discard(self) -> bool:
        if self.silent or not self.editor.is_modified():
            return True
        answer = QMessageBox.question(
            self, "Unsaved changes", "wyrd.toml has unsaved changes. Discard them?"
        )
        return answer == QMessageBox.StandardButton.Yes

    def _load(self, path: Path) -> None:
        self.project_dir = path
        self.editor.load(path / "wyrd.toml")
        self._load_model(path)
        self._remember(path)
        self.refresh_results()

    def _load_model(self, path: Path) -> None:
        try:
            self.project = load_project(path / "wyrd.toml")
        except ConfigError as e:
            self.project = None
            self.project_tree.set_nodes(())
            self.sim_panel.set_project(None, None)
            self.statusBar().showMessage(str(e))
            self.setWindowTitle("Wyrd III")
        else:
            self.project_tree.set_nodes(project_tree(self.project))
            self.sim_panel.set_project(self.project, path)
            self.statusBar().clearMessage()
            self.setWindowTitle(f"Wyrd III - {self.project.name}")
        self._enable_tabs()

    def _enable_tabs(self) -> None:
        ok = self.project is not None
        for name in NEEDS_PROJECT:
            self.contents[name].setEnabled(ok)
        if not ok:
            self.show_panel(self.editor)

    def refresh_results(self) -> None:
        self.flow.set_can_run(self.project is not None and self._pending_project is None)
        self.report_view.set_project_dir(self.project_dir)

    def _on_run_selected(self, run: RunInfo | None) -> None:
        self._load_generation += 1
        generation = self._load_generation
        if run is None or self.project_dir is None:
            self.messages.clear()
            self.timing.set_run(None, [])
            self.schematic.set_run(None)
            return
        self.timing.set_run(run.run_dir, self._timing_roots())
        self.schematic.set_run(run.run_dir)
        task = LoadTask(generation, run.run_dir, self._load_signals)
        self.pool.start(task)

    def _timing_roots(self) -> list[Path]:
        """Project directory and design directories, computed once per project and cached."""
        key = (self.project_dir, id(self.project))
        if self._roots_key != key:
            roots = [self.project_dir] if self.project_dir is not None else []
            if self.project is not None:
                roots += [f.parent for d in self.project.designs.values() for f in d.files]
            self._roots_key, self._roots = key, roots
        return list(self._roots)

    def _on_messages_loaded(
        self, generation: int, messages: list[Message], step_search: list[Path]
    ) -> None:
        if generation != self._load_generation or self.project_dir is None:
            return
        search = [self.project_dir, *step_search]
        files = [f for d in self.project.designs.values() for f in d.files] if self.project else []
        self.messages.set_messages(messages, search, files)

    def _open_dialog(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Open Project")
        if chosen:
            self.open_project(Path(chosen))

    def _open_mimir(self) -> None:
        self.docks["Mímir"].show()
        self.docks["Mímir"].raise_()
        self.mimir.choose()

    def _remember_mimir(self, path: str) -> None:
        self.settings.setValue("lastMimirStore", path)

    def _new_project(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "New Project directory")
        if chosen:
            self.new_project(Path(chosen))

    def new_project(self, directory: Path) -> None:
        if self._init_proc is not None or self._pending_project is not None:
            return
        proc = QProcess(self)
        proc.setProgram(sys.executable)
        proc.setArguments(["-m", "wyrd.cli", "init", str(directory)])
        on_done, on_error = weak(self._on_init_done), weak(self._on_init_error)
        proc.finished.connect(lambda code, _st: on_done(directory, code))
        proc.errorOccurred.connect(lambda err: on_error(directory, err))
        self._init_proc = proc
        proc.start()

    def _on_init_error(self, directory: Path, err: QProcess.ProcessError) -> None:
        if err == QProcess.ProcessError.FailedToStart:
            self._on_init_done(directory, -1)

    def _on_init_done(self, directory: Path, code: int) -> None:
        if self._init_proc is None:
            return
        self._init_proc.deleteLater()
        self._init_proc = None
        if code == 0:
            self.open_project(directory)
        else:
            self._warn("New Project", f"Cannot create wyrd.toml in {directory}")
        self.init_finished.emit(code)

    def _confirm_stop_flow(self, what: str = "Quit") -> bool:
        """Ask whether a running flow may be cancelled; True when none runs or the user agrees."""
        if not self.flow.is_running() or self.silent:
            return True
        answer = QMessageBox.question(
            self, "Flow running", f"A flow is running. Cancel it? ({what})"
        )
        return answer == QMessageBox.StandardButton.Yes

    def _stop_loads(self) -> None:
        """Drop queued step-log loads and wait briefly for running ones, then stop listening."""
        if self._loads_stopped:
            return
        self._loads_stopped = True
        self._load_generation += 1
        self.pool.clear()
        self.pool.waitForDone(LOAD_WAIT_MS)
        self._load_signals.done.disconnect(self._on_messages_loaded)

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._closing:
            if not self._confirm_stop_flow() or not self._confirm_discard():
                event.ignore()
                return
            self._closing = True
            self._pending_project = None
        if self.flow.is_running():
            self.flow.shutdown()
            event.ignore()
            return
        self.flow.stop_floorplan()
        self.sim_panel.shutdown()
        self._stop_loads()
        self.settings.setValue("geometry", self.saveGeometry())
        if self.viewlayout is not None:
            self.viewlayout.save()
        self.settings.sync()
        super().closeEvent(event)
