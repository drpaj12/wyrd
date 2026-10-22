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
from wyrd.gui.projecttree import ProjectTree
from wyrd.guimodel.projmodel import project_tree
from wyrd.project import ConfigError, Project, load_project

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
            self.tabs.addTab(QWidget(), name)
        self.setCentralWidget(self.tabs)
        self._build_docks()
        self._build_menus()

    def _build_docks(self) -> None:
        previous: QDockWidget | None = None
        for name in ("Messages", "Flow"):
            dock = QDockWidget(name, self)
            dock.setObjectName(f"dock-{name.lower()}")
            dock.setWidget(QWidget())
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
        self._action(file_menu, "Quit", self.close, "Ctrl+Q")
        project_menu = bar.addMenu("Project")
        assert project_menu is not None
        self.project_menu = project_menu
        view_menu = bar.addMenu("View")
        assert view_menu is not None
        for dock in self.docks.values():
            view_menu.addAction(dock.toggleViewAction())
        self.help_menu = bar.addMenu("Help")
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
        self.project_dir = path
        try:
            self.project = load_project(toml)
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
        self.refresh_results()
        return True

    def refresh_results(self) -> None:
        """Reload result views; later tasks attach the report view here."""

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

    def closeEvent(self, event: QCloseEvent) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        self.settings.sync()
        super().closeEvent(event)
