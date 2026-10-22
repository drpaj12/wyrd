"""The Wyrd III main window: menus, docks, tabs, project state."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QTabWidget,
    QWidget,
)

from wyrd import cli
from wyrd.gui.about import AboutDialog
from wyrd.gui.adddesign import AddDesignDialog
from wyrd.gui.editor import TomlEditor
from wyrd.gui.flowpanel import FlowPanel
from wyrd.gui.messages import MessagesPane
from wyrd.gui.projecttree import ProjectTree
from wyrd.gui.reportview import ReportView
from wyrd.gui.settingsdialog import SettingsDialog
from wyrd.gui.sourceview import SourceView
from wyrd.guimodel.floorplan import FloorplanPlan
from wyrd.guimodel.logparse import Message, step_messages
from wyrd.guimodel.projmodel import project_tree
from wyrd.guimodel.runs import RunInfo, step_dirs
from wyrd.guimodel.tomledit import AddDesignError, add_design
from wyrd.project import ConfigError, Project, load_project
from wyrd.settings import machine_path

MAX_RECENT = 8
TAB_NAMES = ("Source", "Report", "wyrd.toml")


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings, silent: bool = False) -> None:
        super().__init__()
        self.settings = settings
        self.silent = silent
        self.project: Project | None = None
        self.project_dir: Path | None = None
        self.project_tree = ProjectTree()
        self.tabs = QTabWidget()
        self.source_view = SourceView()
        self.messages = MessagesPane()
        self.report_view = ReportView()
        self.flow = FlowPanel()
        self.editor = TomlEditor(silent)
        self.docks: dict[str, QDockWidget] = {}
        self.recent_menu = QMenu("Recent", self)
        self._build()
        self._restore()

    def _build(self) -> None:
        self.setWindowTitle("Wyrd III")
        left = QDockWidget("Project", self)
        left.setObjectName("dock-project")
        left.setWidget(self.project_tree)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left)
        for name in TAB_NAMES:
            self.tabs.addTab(self._tab_widget(name), name)
        self.setCentralWidget(self.tabs)
        self._build_docks()
        self._build_menus()
        self.project_tree.file_activated.connect(self.show_source)
        self.messages.location_activated.connect(self.show_source)
        self.report_view.run_selected.connect(self._on_run_selected)
        self.report_view.floorplan_requested.connect(self._on_floorplan)
        self.flow.run_requested.connect(self._run_flow)
        self.flow.finished.connect(lambda _code: self.refresh_results())
        self.editor.saved.connect(self._on_saved)

    def _on_saved(self) -> None:
        if self.project_dir is not None:
            self._load(self.project_dir)

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
        self.tabs.setCurrentWidget(self.editor)

    def _run_flow(self) -> None:
        if self.project_dir is not None and self.project is not None:
            self.docks["Flow"].show()
            self.docks["Flow"].raise_()
            self.flow.start(self.project_dir)

    def _on_floorplan(self, plan: FloorplanPlan) -> None:
        self.docks["Flow"].show()
        self.docks["Flow"].raise_()
        self.flow.start_floorplan(plan)

    def _tab_widget(self, name: str) -> QWidget:
        pages: dict[str, QWidget] = {
            "Source": self.source_view,
            "Report": self.report_view,
            "wyrd.toml": self.editor,
        }
        return pages[name]

    def show_source(self, path: Path, line: int | None = None) -> None:
        self.source_view.open_file(path, line)
        self.tabs.setCurrentWidget(self.source_view)

    def _build_docks(self) -> None:
        previous: QDockWidget | None = None
        for name in ("Messages", "Flow"):
            dock = QDockWidget(name, self)
            dock.setObjectName(f"dock-{name.lower()}")
            dock.setWidget(self.messages if name == "Messages" else self.flow)
            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
            if previous is not None:
                self.tabifyDockWidget(previous, dock)
            self.docks[name] = dock
            previous = dock

    def _action(
        self, menu: QMenu, text: str, slot: Callable[[], object], keys: str | None = None
    ) -> QAction:
        act = QAction(text, self)
        if keys:
            act.setShortcut(QKeySequence(keys))
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("File")
        assert file_menu is not None
        self._action(file_menu, "New Project...", self._new_project)
        self._action(file_menu, "Open Project...", self._open_dialog, "Ctrl+O")
        file_menu.addMenu(self.recent_menu)
        file_menu.addSeparator()
        self._action(file_menu, "Save wyrd.toml", self.editor.save, "Ctrl+S")
        self._action(file_menu, "Quit", self.close, "Ctrl+Q")
        project_menu = bar.addMenu("Project")
        assert project_menu is not None
        self.project_menu = project_menu
        self._action(project_menu, "Run flow", self._run_flow, "Ctrl+R")
        self._action(project_menu, "Cancel", self.flow.cancel, "Ctrl+.")
        self._action(project_menu, "Refresh results", self.refresh_results, "F5")
        self._action(project_menu, "Add design...", self._add_design_dialog)
        self._action(project_menu, "Settings...", self._settings_dialog)
        view_menu = bar.addMenu("View")
        assert view_menu is not None
        for dock in self.docks.values():
            view_menu.addAction(dock.toggleViewAction())
        help_menu = bar.addMenu("Help")
        assert help_menu is not None
        self._action(help_menu, "About", self._about_dialog)
        self._rebuild_recent()

    def _restore(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = self.settings.value("windowState")
        if state is not None:
            self.restoreState(state)

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
                act.triggered.connect(lambda _checked=False, p=path: self.open_project(Path(p)))

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
        toml = path / "wyrd.toml"
        if not toml.is_file():
            self._warn("Open Project", f"No wyrd.toml in {path}")
            return False
        if not self._confirm_discard():
            return False
        self._load(path)
        return True

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
        try:
            self.project = load_project(path / "wyrd.toml")
        except ConfigError as e:
            self.project = None
            self.project_tree.set_nodes(())
            self.statusBar().showMessage(str(e))
            self.setWindowTitle("Wyrd III")
        else:
            self.project_tree.set_nodes(project_tree(self.project))
            self.statusBar().clearMessage()
            self.setWindowTitle(f"Wyrd III - {self.project.name}")
        self._remember(path)
        self._enable_tabs()
        self.refresh_results()

    def _enable_tabs(self) -> None:
        ok = self.project is not None
        for i, name in enumerate(TAB_NAMES):
            self.tabs.setTabEnabled(i, ok or name == "wyrd.toml")
        if not ok:
            self.tabs.setCurrentWidget(self.editor)

    def refresh_results(self) -> None:
        self.flow.set_can_run(self.project is not None)
        self.report_view.set_project_dir(self.project_dir)

    def _on_run_selected(self, run: RunInfo | None) -> None:
        if run is None or self.project_dir is None:
            self.messages.clear()
            return
        steps = step_dirs(run.run_dir)
        messages: list[Message] = []
        search: list[Path] = [self.project_dir]
        for step in steps:
            messages.extend(step_messages(step.path))
            search += [step.path, step.path / "out"]
        files = [f for d in self.project.designs.values() for f in d.files] if self.project else []
        self.messages.set_messages(messages, search, files)

    def _open_dialog(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Open Project")
        if chosen:
            self.open_project(Path(chosen))

    def _new_project(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "New Project directory")
        if not chosen:
            return
        if cli.main(["init", chosen]) == 0:
            self.open_project(Path(chosen))
        else:
            self._warn("New Project", f"Cannot create wyrd.toml in {chosen}")

    def _confirm_stop_flow(self) -> bool:
        if not self.flow.is_running():
            return True
        if not self.silent:
            answer = QMessageBox.question(
                self, "Flow running", "A flow is running. Cancel it and quit?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        self.flow.cancel()
        if self.flow.process is not None:
            self.flow.process.waitForFinished(60000)
        return True

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._confirm_stop_flow() or not self._confirm_discard():
            event.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        self.settings.sync()
        super().closeEvent(event)
