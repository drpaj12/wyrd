"""The Timing panel: Fmax/CPD, ranked statements and the critical path of a run (read-only)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wyrd.guimodel import timing
from wyrd.guimodel.timing import Attribution, TimingError

STATEMENT_HEADERS = ["Share", "Delay (ns)", "Location", "Module", "Word"]
PATH_HEADERS = ["#", "Share", "Delay (ns)", "Location", "Module", "Word"]
NO_RUN = "Select a run in the Report tab to see its timing."
NO_ATTR = (
    "No timing attribution for this run. "
    'Use step { use = "odin3-flow", timing_attr = true } and run the flow.'
)
NO_ATTR_PREFIX = "No timing attribution for this run; the timing step reported: "
SCOPES = ("Critical path", "Top paths")
DEFAULT_TOP = 10


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    return table


def _set_row(table: QTableWidget, row: int, cells: list[str]) -> None:
    for col, text in enumerate(cells):
        table.setItem(row, col, QTableWidgetItem(text))


def percent(share: float) -> str:
    return f"{share * 100:.1f}%"


class TimingPanel(QWidget):
    location_activated = Signal(Path, int)
    heat_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.header = QLabel(NO_RUN)
        self.header.setWordWrap(True)
        self.note = QLabel("")
        self.statements = _table(STATEMENT_HEADERS)
        self.path = _table(PATH_HEADERS)
        self.scope = QComboBox()
        self.scope.addItems(SCOPES)
        self.top_n = QSpinBox()
        self.top_n.setRange(1, 1000)
        self.top_n.setValue(DEFAULT_TOP)
        self.top_n.setPrefix("N = ")
        self._build()
        self._att: Attribution | None = None
        self._att_path: Path | None = None
        self._resolver = timing.SourceResolver([])
        self._roots: list[Path] = []
        self._statement_targets: list[tuple[str, int]] = []
        self._path_targets: list[tuple[str | None, int | None]] = []
        self.statements.itemSelectionChanged.connect(self._statement_selected)
        self.path.itemSelectionChanged.connect(self._path_selected)
        self.scope.currentIndexChanged.connect(self._heat_changed)
        self.top_n.valueChanged.connect(self._heat_changed)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(self.header)
        layout.addWidget(QLabel("Statements that set the critical path (ranked)"))
        layout.addWidget(self.statements, 2)
        layout.addWidget(QLabel("Critical path, in order"))
        layout.addWidget(self.path, 2)
        row = QHBoxLayout()
        row.addWidget(QLabel("Heat margin in the source view:"))
        row.addWidget(self.scope)
        row.addWidget(self.top_n)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(self.note)

    def has_attribution(self) -> bool:
        return self._att is not None

    def set_run(self, run_dir: Path | None, roots: list[Path]) -> None:
        """Show the attribution of the run in ``run_dir`` (None clears); never raises."""
        self._roots = list(roots)
        self._att = None
        self._att_path = None
        self._resolver = timing.SourceResolver(self._roots)
        self.note.setText("")
        self._clear_tables()
        if run_dir is None:
            self.header.setText(NO_RUN)
        else:
            self._load(run_dir)
        self.heat_changed.emit()

    def _clear_tables(self) -> None:
        self.statements.setRowCount(0)
        self.path.setRowCount(0)
        self._statement_targets = []
        self._path_targets = []

    def _load(self, run_dir: Path) -> None:
        found = timing.find_attribution(run_dir)
        if found is None:
            reason = timing.missing_reason(run_dir)
            self.header.setText(NO_ATTR if reason is None else f"{NO_ATTR_PREFIX}{reason}")
            return
        try:
            att = timing.load_attribution(found)
        except TimingError as e:
            self.header.setText(f"Timing attribution cannot be shown: {e}")
            return
        self._att = att
        self._att_path = found
        self._resolver = timing.SourceResolver(self._roots, timing.source_hints(found))
        self._fill(att)

    def _fill(self, att: Attribution) -> None:
        fmax = "n/a" if att.fmax_mhz is None else f"{att.fmax_mhz:.2f} MHz"
        cpd = "n/a" if att.cpd_ns is None else f"{att.cpd_ns:.3f} ns"
        self.header.setText(
            f"{att.top}: Fmax {fmax}, critical path delay {cpd}, {att.paths_kept} paths attributed"
        )
        self.statements.setRowCount(len(att.statements))
        for row, s in enumerate(att.statements):
            cells = [percent(s.share), f"{s.delay_ns:.3f}", s.id, s.module, s.word or "-"]
            _set_row(self.statements, row, cells)
            self._statement_targets.append((s.file, s.line))
        self.path.setRowCount(len(att.critical_path))
        for row, e in enumerate(att.critical_path):
            where = "(I/O port)" if e.file is None else f"{e.file}:{e.line}"
            cells = [str(row + 1), percent(e.share), f"{e.delay_ns:.3f}", where, e.module]
            _set_row(self.path, row, [*cells, e.word or "-"])
            self._path_targets.append((e.file, e.line))
        self.statements.resizeColumnsToContents()
        self.path.resizeColumnsToContents()

    def _open(self, file: str | None, line: int | None) -> None:
        if file is None or line is None:
            return
        found = self._resolver.resolve(file)
        if found is None:
            self.note.setText(f"Cannot find {file} on disk.")
            return
        self.note.setText(self._stale_note(found))
        self.location_activated.emit(found, line)

    def _stale_note(self, source: Path) -> str:
        if self._att_path is None:
            return ""
        try:
            newer = source.stat().st_mtime > self._att_path.stat().st_mtime
        except OSError:
            return ""
        if not newer:
            return ""
        return f"Warning: {source.name} was changed after the timing run; line numbers may be off."

    def _statement_selected(self) -> None:
        row = self.statements.currentRow()
        if 0 <= row < len(self._statement_targets):
            self._open(*self._statement_targets[row])

    def _path_selected(self) -> None:
        row = self.path.currentRow()
        if 0 <= row < len(self._path_targets):
            self._open(*self._path_targets[row])

    def _heat_changed(self) -> None:
        self.top_n.setEnabled(self.scope.currentIndex() == 1)
        self.heat_changed.emit()

    def heat_for(self, path: Path) -> dict[int, float]:
        """Line to share for the source file ``path`` in the chosen scope; empty when none."""
        if self._att is None:
            return {}
        if self.scope.currentIndex() == 1:
            shares = timing.top_line_shares(self._att, self.top_n.value())
        else:
            shares = timing.critical_line_shares(self._att)
        return timing.file_shares(shares, path, self._resolver)
