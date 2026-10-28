"""The Paths panel: the stored paths through a clicked line, word or bit, and one path step by
step. Reads the schema 6 tables of a Mímir store (read only).
Spec: docs/specs/2026-10-28-path-view.md.
The panel emits ``selection_changed`` (the source view redraws) and ``step_activated`` (a file and
line to scroll to; the main window opens the file when it is not the one shown)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wyrd.guimodel import pathview
from wyrd.guimodel.pathview import Query
from wyrd.mimirview import MimirError, MimirView, PathList, PathNodeRow, PathRef

SETTING_KEY = "pathsCutoff"
NO_QUERY = "Click a hot word or line in the Source panel (Show HDL heat first)."
TOO_MANY = 500


def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    return t


def _fill(t: QTableWidget, rows: list[list[str]]) -> None:
    t.setRowCount(len(rows))
    for r, cells in enumerate(rows):
        for c, text in enumerate(cells):
            t.setItem(r, c, QTableWidgetItem(text))
    t.resizeColumnsToContents()




class PathsPanel(QWidget):
    selection_changed = Signal()
    step_activated = Signal(str, int)  # the span's file name as stored, and the line

    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.settings = settings
        self.view: MimirView | None = None
        self.run_id = ""
        self.label = ""
        self.queries: list[Query] = []
        self.refs: list[PathRef] = []
        self.nodes: list[PathNodeRow] = []  # the nodes of the chosen path
        self.union_paths: list[tuple[float | None, list[PathNodeRow]]] = []
        self.header = QLabel("")
        self.status = QLabel(NO_QUERY)
        self.status.setWordWrap(True)
        self.cutoff = QComboBox()
        self.cutoff.addItems(pathview.CUTOFF_LABELS)
        self.cutoff.setCurrentIndex(self._stored_index())
        self.table = _table(pathview.PATH_HEADERS)
        self.steps = _table(pathview.STEP_HEADERS)
        self.prev = QPushButton("Previous path")
        self.next = QPushButton("Next path")
        self.union = QCheckBox("All paths through here")
        self._build()
        self.table.itemSelectionChanged.connect(self._path_chosen)
        self.steps.itemSelectionChanged.connect(self._step_chosen)
        self.prev.clicked.connect(lambda: self._move(-1))
        self.next.clicked.connect(lambda: self._move(1))
        self.union.toggled.connect(self._union_toggled)
        self.cutoff.currentIndexChanged.connect(self._cutoff_changed)
        self._refresh_header()

    def _build(self) -> None:
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Near-critical cut-off:"))
        top.addWidget(self.cutoff)
        top.addWidget(self.header, 1)
        lay.addLayout(top)
        lay.addWidget(self.status)
        lay.addWidget(self.table, 2)
        row = QHBoxLayout()
        row.addWidget(self.prev)
        row.addWidget(self.next)
        row.addWidget(self.union)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(QLabel("Steps of the chosen path, start to end"))
        lay.addWidget(self.steps, 3)

    # ---- cut-off ----

    def _stored_index(self) -> int:
        if self.settings is None:
            return pathview.DEFAULT_CUTOFF_INDEX
        return pathview.cutoff_index(self.settings.value(SETTING_KEY, ""))

    def cutoff_value(self) -> float | None:
        return pathview.cutoff_at(self.cutoff.currentIndex())

    def _refresh_header(self) -> None:
        self.header.setText(pathview.cutoff_header(self.cutoff_value()))

    def _cutoff_changed(self) -> None:
        if self.settings is not None:
            self.settings.setValue(SETTING_KEY, self.cutoff.currentText())
        self._refresh_header()
        if self.queries:
            self._run_queries()
        else:
            self.selection_changed.emit()

    # ---- queries ----

    def clear(self) -> None:
        self.view, self.run_id, self.queries = None, "", []
        self._set_paths([], NO_QUERY)

    def show_for(self, store: str, run_id: str, label: str, queries: list[Query]) -> None:
        """List the paths through the object clicked; ``queries`` are tried in order."""
        try:
            if self.view is None or str(self.view.path) != store:
                self.view = MimirView(store)
        except MimirError as e:
            self._set_paths([], str(e))
            return
        self.run_id, self.label, self.queries = run_id, label, queries
        self._run_queries()

    def _run_queries(self) -> None:
        assert self.view is not None
        got = PathList([])
        try:
            for spans, word, bit in self.queries:
                got = self._ask(self.view, spans, word, bit)
                if got.paths or got.note:
                    break
        except MimirError as e:
            got = PathList([], str(e))
        self._set_paths(got.paths, got.note)

    def _ask(self, view: MimirView, spans: tuple[str, ...], word: str | None, bit: int | None
             ) -> PathList:  # fmt: skip
        """Paths through any of the spans (merged by index), most critical first."""
        cut = self.cutoff_value()
        if not spans:
            return view.paths_through(self.run_id, word=word, bit=bit, min_crit=cut)
        found: dict[int, PathRef] = {}
        for span in spans:
            got = view.paths_through(self.run_id, span=span, word=word, bit=bit, min_crit=cut)
            if got.note:
                return got
            found.update({p.index: p for p in got.paths})
        order = sorted(found.values(), key=lambda p: (p.crit is None, -(p.crit or 0.0), p.index))
        return PathList(order)

    def _set_paths(self, refs: list[PathRef], note: str) -> None:
        self.refs = refs[:TOO_MANY]
        more = f" (first {TOO_MANY})" if len(refs) > TOO_MANY else ""
        text = note or f"Paths through {self.label}: {len(refs)}{more}"
        cut = self.cutoff_value()
        if not refs and not note and cut is not None:
            text += f"; none with crit >= {cut:.2f}"
        self.status.setText(text)
        self.table.blockSignals(True)
        _fill(self.table, [
            pathview.path_cells(i + 1, r.crit, r.slack_ns, r.startpoint, r.endpoint, r.n_nodes)
            for i, r in enumerate(self.refs)
        ])  # fmt: skip
        self.table.blockSignals(False)
        self.nodes = []
        _fill(self.steps, [])
        self._load_union()
        self._buttons()
        if self.refs:
            self.table.selectRow(0)
        else:
            self.selection_changed.emit()

    # ---- the chosen path ----

    def _buttons(self) -> None:
        row = self.table.currentRow()
        self.prev.setEnabled(row > 0)
        self.next.setEnabled(0 <= row < len(self.refs) - 1)
        self.union.setEnabled(bool(self.refs))

    def _move(self, step: int) -> None:
        row = self.table.currentRow() + step
        if 0 <= row < len(self.refs):
            self.table.selectRow(row)

    def chosen(self) -> PathRef | None:
        row = self.table.currentRow()
        return self.refs[row] if 0 <= row < len(self.refs) else None

    def _path_chosen(self) -> None:
        ref = self.chosen()
        self.nodes = []
        if ref is not None and self.view is not None:
            try:
                self.nodes = self.view.path_detail(self.run_id, ref.index).nodes
            except MimirError as e:
                self.status.setText(str(e))
        _fill(self.steps, [pathview.step_cells(n) for n in self.nodes])
        self._buttons()
        self.selection_changed.emit()

    def _step_chosen(self) -> None:
        row = self.steps.currentRow()
        if not 0 <= row < len(self.nodes):
            return
        where = self.nodes[row].file_line
        if where is not None:
            self.step_activated.emit(where[0], where[1])

    # ---- union ----

    def _union_toggled(self) -> None:
        self._load_union()
        self.selection_changed.emit()

    def _load_union(self) -> None:
        self.union_paths = []
        if not self.union.isChecked() or self.view is None:
            return
        theta = pathview.union_theta(self.cutoff_value())
        for ref in self.refs:
            if ref.crit is not None and ref.crit >= theta - 1e-9:
                detail = self.view.path_detail(self.run_id, ref.index)
                self.union_paths.append((ref.crit, detail.nodes))

    def overlay(self, in_file: Callable[[str], bool]) -> pathview.Overlay | None:
        """The overlay for the open file: the union, or the chosen path, or nothing."""
        if self.union.isChecked() and self.union_paths:
            return pathview.union_overlay(self.union_paths, in_file, self.cutoff_value())
        ref = self.chosen()
        if ref is None or not self.nodes:
            return None
        return pathview.path_overlay(self.nodes, ref.crit, in_file, self.cutoff_value())
