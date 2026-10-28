"""View capabilities of the main window: presets, maximise, saved layout, zoom, table polish.
Spec: docs/specs/2026-10-28-view-layout.md."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QFont, QHelpEvent, QKeySequence, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDockWidget,
    QHeaderView,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QTabBar,
    QTableView,
    QTabWidget,
    QToolTip,
    QTreeView,
    QWidget,
)

from wyrd.guimodel import layoutspec as spec

_AREAS = {
    "left": Qt.DockWidgetArea.LeftDockWidgetArea,
    "right": Qt.DockWidgetArea.RightDockWidgetArea,
    "bottom": Qt.DockWidgetArea.BottomDockWidgetArea,
}
_BASE_SIZE = "wyrdBaseSize"
_BASE_ROW = "wyrdBaseRow"
_HOOKED = "wyrdHooked"
ROW_PAD = 8
SPLIT_HANDLE = 6


def scrolled(content: QWidget, width: int, height: int) -> QScrollArea:
    """Wrap ``content`` so a narrow dock scrolls instead of crushing the widgets."""
    content.setMinimumSize(width, height)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setWidget(content)
    return area


class _CellTips(QObject):
    """Tooltip with the full text of a table or tree cell that has no tooltip of its own."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.ToolTip:
            return False
        view = watched.parent()
        if not isinstance(view, QAbstractItemView) or not isinstance(event, QHelpEvent):
            return False
        index = view.indexAt(event.pos())
        if not index.isValid() or index.data(Qt.ItemDataRole.ToolTipRole):
            return False
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if not text:
            return False
        QToolTip.showText(event.globalPos(), str(text), view)
        return True


class ViewLayout(QObject):
    """Owns the dock arrangement of one main window."""

    def __init__(
        self, window: QMainWindow, docks: dict[str, QDockWidget], settings: QSettings
    ) -> None:
        super().__init__(window)
        self.win = window
        self.docks = docks
        self.settings = settings
        self.preset = spec.DEFAULT_PRESET
        self.zoom = spec.parse_zoom(settings.value("view/zoom"))
        self._saved: QByteArray | None = None  # window state from before maximise
        self._last: QDockWidget | None = None
        self._tips = _CellTips(self)
        self._hook_pending = False
        window.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.GroupedDragging
        )
        window.setTabPosition(Qt.DockWidgetArea.AllDockWidgetAreas, QTabWidget.TabPosition.North)
        for dock in docks.values():
            dock.installEventFilter(self)
            dock.dockLocationChanged.connect(self._schedule_hook)
            dock.topLevelChanged.connect(self._schedule_hook)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.focusChanged.connect(self._focus_changed)

    # ---- presets ----

    @property
    def maximised(self) -> bool:
        return self._saved is not None

    def apply_preset(self, name: str) -> None:
        preset = spec.preset_named(name)
        self._saved = None
        for dock in self.docks.values():
            dock.setFloating(False)
            self.win.removeDockWidget(dock)
        firsts: dict[str, QDockWidget] = {}
        for group in preset.groups:
            firsts[group.area] = self._place(group, preset)
        self._park(preset, firsts.get("bottom"))
        self._size(preset, firsts)
        self.preset = name
        self._schedule_hook()

    def _place(self, group: spec.Group, _preset: spec.Preset) -> QDockWidget:
        first = self.docks[group.docks[0]]
        self.win.addDockWidget(_AREAS[group.area], first)
        first.show()
        for name in group.docks[1:]:
            self.win.tabifyDockWidget(first, self.docks[name])
            self.docks[name].show()
        self.docks[group.current].raise_()
        return first

    def _park(self, preset: spec.Preset, anchor: QDockWidget | None) -> None:
        for name in preset.parked():
            dock = self.docks[name]
            self.win.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
            if anchor is not None:
                self.win.tabifyDockWidget(anchor, dock)
            else:
                anchor = dock
            dock.hide()

    def _size(self, preset: spec.Preset, firsts: dict[str, QDockWidget]) -> None:
        shares = {g.area: g.share for g in preset.groups}
        side = [a for a in ("left", "right") if a in firsts]
        width, height = max(self.win.width(), 1), max(self.win.height(), 1)
        if len(side) == 2:
            self.win.resizeDocks(
                [firsts[a] for a in side],
                [int(width * shares[a]) for a in side],
                Qt.Orientation.Horizontal,
            )
        if "bottom" in firsts and side:
            share = shares["bottom"]
            self.win.resizeDocks(
                [firsts[side[0]], firsts["bottom"]],
                [int(height * (1 - share)), int(height * share)],
                Qt.Orientation.Vertical,
            )

    def reset(self) -> None:
        self.apply_preset(spec.DEFAULT_PRESET)

    # ---- maximise ----

    def current_dock(self) -> QDockWidget | None:
        focused = self._dock_of(QApplication.focusWidget())
        if focused is not None:
            return focused
        if self._last is not None and not self._last.isHidden():
            return self._last
        for dock in self.docks.values():
            if not dock.isHidden():
                return dock
        return None

    def _dock_of(self, widget: QWidget | None) -> QDockWidget | None:
        while widget is not None:
            if isinstance(widget, QDockWidget) and widget in self.docks.values():
                return widget
            widget = widget.parentWidget()
        return None

    def _focus_changed(self, _old: QWidget | None, new: QWidget | None) -> None:
        dock = self._dock_of(new)
        if dock is not None:
            self._last = dock

    def toggle_maximise(self, dock: QDockWidget | None = None) -> bool:
        """Maximise ``dock`` (default the current panel) or restore; True when maximised."""
        if self._saved is not None:
            saved, self._saved = self._saved, None
            self.win.restoreState(saved, spec.LAYOUT_VERSION)
            return False
        target = dock or self.current_dock()
        if target is None:
            return False
        self._saved = self.win.saveState(spec.LAYOUT_VERSION)
        target.setFloating(False)
        for other in self.docks.values():
            if other is not target:
                other.hide()
        target.show()
        target.raise_()
        self._last = target
        return True

    # ---- save and restore ----

    def save(self) -> None:
        state = self._saved if self._saved is not None else self.win.saveState(spec.LAYOUT_VERSION)
        self.settings.setValue("layout/version", spec.LAYOUT_VERSION)
        self.settings.setValue("layout/state", state)

    def restore(self) -> bool:
        """Restore the saved layout; False (and nothing changed) when absent, old or rejected."""
        if not spec.state_usable(self.settings.value("layout/version")):
            return False
        state = self.settings.value("layout/state")
        if state is None:
            return False
        ok = bool(self.win.restoreState(state, spec.LAYOUT_VERSION))
        if ok:
            self._schedule_hook()
        return ok

    # ---- title and tab double-click ----

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.MouseButtonDblClick or not isinstance(event, QMouseEvent):
            return False
        pos = event.position().toPoint()
        if isinstance(watched, QTabBar):
            return self._tab_double_click(watched, pos)
        if isinstance(watched, QDockWidget):
            inner = watched.widget()
            if watched.isFloating() or inner is None or pos.y() >= inner.y():
                return False
            self.toggle_maximise(watched)
            return True
        return False

    def _tab_double_click(self, bar: QTabBar, pos: QPoint) -> bool:
        index = bar.tabAt(pos)
        if index < 0:
            return False
        title = bar.tabText(index)
        for dock in self.docks.values():
            if dock.windowTitle() == title:
                self.toggle_maximise(dock)
                return True
        return False

    def _schedule_hook(self, *_args: object) -> None:
        if not self._hook_pending:
            self._hook_pending = True
            QTimer.singleShot(0, self.hook_tabbars)

    def hook_tabbars(self) -> None:
        """Catch double-clicks on the tab bars Qt makes for tabbed docks."""
        self._hook_pending = False
        for bar in self.win.findChildren(QTabBar):
            if bar.parent() is self.win and not bar.property(_HOOKED):
                bar.setProperty(_HOOKED, True)
                bar.installEventFilter(self)

    # ---- zoom ----

    def set_zoom(self, value: int) -> None:
        self.zoom = spec.clamp_zoom(value)
        self.settings.setValue("view/zoom", self.zoom)
        self.apply_zoom()

    def apply_zoom(self) -> None:
        for root in self.docks.values():
            for edit in root.findChildren(QPlainTextEdit):
                self._zoom_widget(edit)
            for view in root.findChildren(QAbstractItemView):
                self._zoom_widget(view)

    def _zoom_widget(self, w: QWidget) -> None:
        base = w.property(_BASE_SIZE)
        if base is None:
            base = w.font().pointSizeF()
            if base <= 0:
                return
            w.setProperty(_BASE_SIZE, base)
        font = QFont(w.font())
        font.setPointSizeF(float(base) + self.zoom)
        w.setFont(font)
        if isinstance(w, QTableView):
            self._zoom_rows(w)

    def _zoom_rows(self, table: QTableView) -> None:
        header = table.verticalHeader()
        if header is None:
            return
        if table.property(_BASE_ROW) is None:
            table.setProperty(_BASE_ROW, header.defaultSectionSize())
        if self.zoom == 0:
            header.setDefaultSectionSize(int(table.property(_BASE_ROW)))
        else:
            header.setDefaultSectionSize(table.fontMetrics().height() + ROW_PAD)

    # ---- polish ----

    def polish(self) -> None:
        """Tables stretch their last column and show full cell text; splitters keep handles."""
        for dock in self.docks.values():
            for table in dock.findChildren(QTableView):
                head = table.horizontalHeader()
                if isinstance(head, QHeaderView):
                    head.setStretchLastSection(True)
                table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
                table.viewport().installEventFilter(self._tips)
            for tree in dock.findChildren(QTreeView):
                tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
                tree.viewport().installEventFilter(self._tips)
            for split in dock.findChildren(QSplitter):
                split.setChildrenCollapsible(False)
                split.setHandleWidth(SPLIT_HANDLE)
        self.apply_zoom()

    # ---- menu ----

    def build_menu(self, view_menu: QMenu, add: Callable[..., QAction]) -> None:
        panels = view_menu.addMenu("Panels")
        assert panels is not None
        for dock in self.docks.values():
            panels.addAction(dock.toggleViewAction())
        layouts = view_menu.addMenu("Layout")
        assert layouts is not None
        for preset in spec.PRESETS:
            add(layouts, preset.name, self._preset_slot(preset.name))
        add(layouts, "Reset layout", self.reset)
        maxi = add(view_menu, "Maximise current panel", self.toggle_maximise)
        maxi.setShortcuts([QKeySequence("F11"), QKeySequence("Ctrl+Shift+M")])
        view_menu.addSeparator()
        zin = add(view_menu, "Zoom in", lambda: self.set_zoom(self.zoom + 1))
        zin.setShortcuts([QKeySequence("Ctrl+="), QKeySequence("Ctrl++")])
        add(view_menu, "Zoom out", lambda: self.set_zoom(self.zoom - 1), "Ctrl+-")
        add(view_menu, "Reset zoom", lambda: self.set_zoom(0), "Ctrl+0")

    def _preset_slot(self, name: str) -> Callable[[], None]:
        return lambda: self.apply_preset(name)
