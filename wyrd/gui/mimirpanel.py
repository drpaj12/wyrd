"""The Mímir dock: browse a Mimir store read only (designs, runs, compare, plot). Spec:
docs/specs/2026-10-28-mimir-browser.md. Slow queries run on a worker thread; a token drops stale
results."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from wyrd import mimirview
from wyrd.gui.mimircharts import DotChart, ScatterChart
from wyrd.mimirview import MimirError, MimirView, Table

CONF_COLOURS = {
    "given": "#c9ecc9",
    "default": "#e2e2e2",
    "default-unrecorded": "#ffe2a8",
    "unknown": "#ffb8b8",
}
NO_STORE = "No Mímir store open. Use File > Open Mímir store... or the button below."
FETCH_TIP_MISSING = "The `mimir` command is not on PATH; install the mimir package to fetch."
LIST_LIMIT = 500


class TablePane(QWidget):
    """A table with Copy and Export CSV."""

    def __init__(self, conf_column: str = "") -> None:
        super().__init__()
        self.table_data = Table("", (), [])
        self.conf_column = conf_column
        self.grid = QTableWidget()
        self.grid.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.grid.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.copy_button = QPushButton("Copy")
        self.export_button = QPushButton("Export CSV...")
        self.note = QLabel("")
        row = QHBoxLayout()
        for w in (self.copy_button, self.export_button, self.note):
            row.addWidget(w)
        row.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(row)
        lay.addWidget(self.grid, 1)
        self.copy_button.clicked.connect(self.copy)
        self.export_button.clicked.connect(self.export_dialog)

    def set_table(self, t: Table) -> None:
        self.table_data = t
        self.grid.setSortingEnabled(False)
        self.grid.clear()
        self.grid.setColumnCount(len(t.columns))
        self.grid.setHorizontalHeaderLabels(list(t.columns))
        self.grid.setRowCount(len(t.rows))
        conf = t.columns.index(self.conf_column) if self.conf_column in t.columns else -1
        for i, r in enumerate(t.rows):
            colour = CONF_COLOURS.get(str(r[conf])) if conf >= 0 else None
            for j, c in enumerate(r):
                item = QTableWidgetItem(mimirview.cell_text(c))
                if colour:
                    item.setBackground(QBrush(QColor(colour)))
                self.grid.setItem(i, j, item)
        self.grid.resizeColumnsToContents()
        self.note.setText(f"{len(t.rows)} rows" + (" (more not shown)" if t.more else ""))

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(mimirview.render_tsv(self.table_data))

    def export_csv(self, path: Path) -> None:
        path.write_text(mimirview.render_csv(self.table_data), encoding="utf-8")

    def export_dialog(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV (*.csv)")
        if name:
            self.export_csv(Path(name))


class _Signals(QObject):
    done = Signal(int, str, object, float)  # token, key, result, seconds
    failed = Signal(int, str, str)


class _Task(QRunnable):
    def __init__(
        self, token: int, key: str, fn: Callable[[], object], signals: _Signals,
        current: Callable[[str], int],
    ) -> None:  # fmt: skip
        super().__init__()
        self.token, self.key, self.fn, self.signals, self.current = token, key, fn, signals, current

    def run(self) -> None:
        if self.token != self.current(self.key):
            return
        t0 = time.perf_counter()
        try:
            result = self.fn()
        except Exception as e:  # any failure must reach the panel
            self.signals.failed.emit(self.token, self.key, str(e))
        else:
            self.signals.done.emit(self.token, self.key, result, time.perf_counter() - t0)


class MimirPanel(QWidget):
    """Read-only browser for one Mimir store. `finished(key)` fires when a worker request ends."""

    finished = Signal(str)
    store_opened = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.view: MimirView | None = None
        self.last_path = ""
        self.timings: dict[str, float] = {}
        self.fetch_runner: Callable[[list[str]], int] = lambda argv: subprocess.run(argv).returncode
        self.fetch_dir: Callable[[], str] = self._ask_dir
        self._tokens: dict[str, int] = {}
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _Signals(self)
        self._signals.done.connect(self._on_done)
        self._signals.failed.connect(self._on_failed)
        self._current_run = ""
        self._make_widgets()
        self._layout()
        self._connect()
        self._set_fetch_enabled()

    # ---- widgets ----

    def _make_widgets(self) -> None:
        self.status = QLabel(NO_STORE)
        self.status.setWordWrap(True)
        self.open_button = QPushButton("Open Mímir store...")
        self.last_button = QPushButton("Reopen last")
        self.last_button.setEnabled(False)
        self.source = QComboBox()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("filter designs")
        self.designs = QListWidget()
        self.tabs = QTabWidget()
        self.summary_text = QPlainTextEdit()
        self.summary_text.setReadOnly(True)
        self.sources_pane = TablePane()
        self._make_design_widgets()
        self._make_run_widgets()
        self._make_compare_widgets()
        self._make_plot_widgets()

    def _make_design_widgets(self) -> None:
        self.design_label = QLabel("")
        self.design_tabs = QTabWidget()
        self.metrics_pane = TablePane()
        self.runs_pane = TablePane()
        self.meta_pane = TablePane("conf")
        self.lineage_pane = TablePane("conf")
        self.struct_pane = TablePane()
        for name, pane in (
            ("Metrics", self.metrics_pane), ("Runs", self.runs_pane),
            ("Meta", self.meta_pane), ("Lineage", self.lineage_pane),
            ("Structures", self.struct_pane),
        ):  # fmt: skip
            self.design_tabs.addTab(pane, name)

    def _make_run_widgets(self) -> None:
        self.run_label = QLabel("Select a run in the Design tab (double click).")
        self.run_label.setWordWrap(True)
        self.params_pane = TablePane("conf")
        self.artifacts_pane = TablePane()
        self.fetch_button = QPushButton("Fetch artifacts...")

    def _make_compare_widgets(self) -> None:
        self.cmp_prefix = QLineEdit()
        self.cmp_prefix.setPlaceholderText("source prefix, e.g. norns-placers-e10-")
        self.cmp_base = QComboBox()
        self.cmp_base.setEditable(True)
        self.cmp_metric = QComboBox()
        self.cmp_metric.setEditable(True)
        self.cmp_level = QComboBox()
        self.cmp_load = QPushButton("List configs")
        self.cmp_go = QPushButton("Compare")
        self.cmp_pane = TablePane()
        self.cmp_chart = DotChart()
        self.cmp_status = QLabel("")

    def _make_plot_widgets(self) -> None:
        self.plot_x = QComboBox()
        self.plot_y = QComboBox()
        self.plot_source = QComboBox()
        self.log_x = QCheckBox("log x")
        self.log_y = QCheckBox("log y")
        self.plot_go = QPushButton("Plot")
        self.chart = ScatterChart()
        self.hover = QLabel("")
        self.plot_status = QLabel("")

    def _layout(self) -> None:
        top = QHBoxLayout()
        top.addWidget(self.open_button)
        top.addWidget(self.last_button)
        top.addStretch(1)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        for w in (self.source, self.filter, self.designs):
            ll.addWidget(w)
        ll.setStretch(2, 1)
        self.tabs.addTab(self._summary_tab(), "Summary")
        self.tabs.addTab(self._design_tab(), "Design")
        self.tabs.addTab(self._run_tab(), "Run")
        self.tabs.addTab(self._compare_tab(), "Compare")
        self.tabs.addTab(self._plot_tab(), "Plot")
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left)
        split.addWidget(self.tabs)
        split.setStretchFactor(1, 1)
        lay = QVBoxLayout(self)
        lay.addWidget(self.status)
        lay.addLayout(top)
        lay.addWidget(split, 1)

    def _summary_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self.summary_text, 1)
        lay.addWidget(self.sources_pane, 2)
        return w

    def _design_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self.design_label)
        lay.addWidget(self.design_tabs, 1)
        return w

    def _run_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self.run_label)
        lay.addWidget(QLabel("Flow parameters (colour = how the value is known)"))
        lay.addWidget(self.params_pane, 3)
        lay.addWidget(QLabel("Artifacts"))
        lay.addWidget(self.artifacts_pane, 1)
        lay.addWidget(self.fetch_button)
        return w

    @staticmethod
    def _row(*items: QWidget | str) -> QHBoxLayout:
        row = QHBoxLayout()
        for it in items:
            row.addWidget(QLabel(it) if isinstance(it, str) else it)
        return row

    def _compare_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addLayout(self._row("Prefix", self.cmp_prefix, self.cmp_load))
        lay.addLayout(self._row("Base", self.cmp_base, "Metric", self.cmp_metric,
                                "Level", self.cmp_level, self.cmp_go))  # fmt: skip
        lay.addWidget(self.cmp_status)
        lay.addWidget(self.cmp_pane, 2)
        lay.addWidget(self.cmp_chart, 1)
        return w

    def _plot_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addLayout(self._row("x", self.plot_x, "y", self.plot_y, "source", self.plot_source,
                                self.log_x, self.log_y, self.plot_go))  # fmt: skip
        lay.addWidget(self.plot_status)
        lay.addWidget(self.chart, 1)
        lay.addWidget(self.hover)
        return w

    def _connect(self) -> None:
        self.open_button.clicked.connect(self.choose)
        self.last_button.clicked.connect(self._reopen)
        self.source.activated.connect(self.fill_designs)
        self.filter.textChanged.connect(self.fill_designs)
        self.designs.itemSelectionChanged.connect(self._design_selected)
        self.runs_pane.grid.cellDoubleClicked.connect(self._run_row_activated)
        self.fetch_button.clicked.connect(self.fetch)
        self.cmp_load.clicked.connect(self.list_configs)
        self.cmp_go.clicked.connect(self.compare)
        self.plot_go.clicked.connect(self.plot)
        self.log_x.toggled.connect(self._log_changed)
        self.log_y.toggled.connect(self._log_changed)
        self.chart.hovered.connect(self.hover.setText)

    # ---- workers ----

    def _current(self, key: str) -> int:
        return self._tokens.get(key, 0)

    def _submit(self, key: str, fn: Callable[[], object]) -> None:
        self._tokens[key] = self._tokens.get(key, 0) + 1
        self._pool.start(_Task(self._tokens[key], key, fn, self._signals, self._current))

    def _on_done(self, token: int, key: str, result: object, seconds: float) -> None:
        if token != self._tokens.get(key):
            return
        self.timings[key] = seconds
        handler = {
            "open": self._opened, "compare": self._compared, "plot": self._plotted,
            "configs": self._configs,
        }[key]  # fmt: skip
        handler(result)
        self.finished.emit(key)

    def _on_failed(self, token: int, key: str, reason: str) -> None:
        if token != self._tokens.get(key):
            return
        self.status.setText(f"{key}: {reason}")
        self.finished.emit(key)

    # ---- opening ----

    def set_last(self, path: str) -> None:
        self.last_path = path
        self.last_button.setEnabled(bool(path))
        self.last_button.setToolTip(path)

    def choose(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, "Open Mímir store", "", "SQLite (*.db *.sqlite);;All files (*)"
        )
        if name:
            self.open_store(Path(name))

    def _reopen(self) -> None:
        if self.last_path:
            self.open_store(Path(self.last_path))

    def open_store(self, path: Path) -> bool:
        """Check the file inline (cheap) and load the summary on the worker. False: not usable."""
        try:
            self.view = MimirView(path)
        except MimirError as e:
            self.view = None
            self.status.setText(str(e))
            return False
        self.status.setText(f"Reading {path.name} ...")
        view = self.view
        self._submit("open", lambda: (view.summary(), view.metric_names(), view.sources()))
        self.set_last(str(path))
        self.store_opened.emit(str(path))
        return True

    def _opened(self, result: object) -> None:
        assert isinstance(result, tuple)
        summary, metrics, sources = result
        assert self.view is not None
        self.status.setText(f"{self.view.path}  (schema version {summary.version}, read only)")
        counts = ", ".join(f"{k}={n}" for k, n in summary.counts.items())
        self.summary_text.setPlainText(
            f"{self.view.path.name}  {summary.size_bytes} bytes\nrows: {counts}\n"
            f"levels: {', '.join(summary.levels)}\ndistinct metrics: {summary.n_metrics}\n"
        )
        self.sources_pane.set_table(summary.sources)
        self.source.clear()
        self.source.addItems(["(all sources)", *sources])
        self.plot_source.clear()
        self.plot_source.addItems(["(all sources)", *sources])
        for combo in (self.cmp_metric, self.plot_x, self.plot_y):
            combo.clear()
            combo.addItems(metrics)
        if self.plot_y.count() > 1:
            self.plot_y.setCurrentIndex(1)
        self.cmp_level.clear()
        self.cmp_level.addItems(["", *summary.levels])
        self.fill_designs()

    # ---- design list and views (indexed, inline) ----

    def fill_designs(self) -> None:
        if self.view is None:
            return
        src = self.source.currentText()
        source = None if src in ("", "(all sources)") else src
        try:
            t = self.view.designs(source, self.filter.text().strip(), LIST_LIMIT)
        except MimirError as e:
            self.status.setText(str(e))
            return
        self.designs.clear()
        for s, name, _slug, _suite, n in t.rows:
            item = QListWidgetItem(f"{name}   [{s}]  {n} runs")
            item.setData(Qt.ItemDataRole.UserRole, (str(s), str(name)))
            self.designs.addItem(item)
        if t.more:
            self.designs.addItem(QListWidgetItem(f"... more than {LIST_LIMIT}; narrow the filter"))

    def _design_selected(self) -> None:
        items = self.designs.selectedItems()
        data = items[0].data(Qt.ItemDataRole.UserRole) if items else None
        if data:
            self.show_design(data[1], data[0])

    def show_design(self, name: str, source: str | None = None) -> None:
        if self.view is None:
            return
        try:
            d = self.view.design(name, source)
        except MimirError as e:
            self.status.setText(str(e))
            return
        self.design_label.setText(f"{d.name}  ({', '.join(d.sources)})")
        for pane, t in (
            (self.metrics_pane, d.metrics), (self.runs_pane, d.runs), (self.meta_pane, d.meta),
            (self.lineage_pane, d.lineage), (self.struct_pane, d.structures),
        ):  # fmt: skip
            pane.set_table(t)
        self.tabs.setCurrentIndex(1)

    def _run_row_activated(self, row: int, _col: int) -> None:
        rows = self.runs_pane.table_data.rows
        if 0 <= row < len(rows):
            self.show_run(str(rows[row][0]))

    def show_run(self, run_id: str) -> None:
        if self.view is None:
            return
        try:
            r = self.view.run(run_id)
        except MimirError as e:
            self.status.setText(str(e))
            return
        self._current_run = run_id
        h = r.header
        self.run_label.setText(
            f"run {run_id}: {h['design']}  {h['source']}  arch {h['arch']}  arm {h['arm']}  "
            f"seed {h['seed']}  tools {h['tool_commits']}  time {h['time_s']}  "
            f"peak RSS {h['peak_rss_mib']}  host {h['host']}\n"
            f"config {r.config.get('name', '?')} ({r.config.get('status', '?')}, "
            f"{r.config.get('text_kind', '?')})  origin {h['origin']}"
        )
        self.params_pane.set_table(r.params)
        self.artifacts_pane.set_table(r.artifacts)
        self._set_fetch_enabled()
        self.tabs.setCurrentIndex(2)

    # ---- fetch hook ----

    def _set_fetch_enabled(self) -> None:
        have = mimirview.mimir_on_path() is not None
        self.fetch_button.setEnabled(have and bool(self._current_run))
        self.fetch_button.setToolTip("" if have else FETCH_TIP_MISSING)

    def _ask_dir(self) -> str:
        return QFileDialog.getExistingDirectory(self, "Fetch artifacts into")

    def fetch(self) -> int | None:
        """Run `mimir fetch --run ID --db DB --out DIR` (no shell); returns its exit code."""
        if self.view is None or not self._current_run:
            return None
        out = self.fetch_dir()
        if not out:
            return None
        code = self.fetch_runner(mimirview.fetch_argv(self._current_run, self.view.path, Path(out)))
        self.status.setText(f"mimir fetch exited {code}")
        return code

    # ---- compare ----

    def list_configs(self) -> None:
        if self.view is None:
            return
        view, prefix = self.view, self.cmp_prefix.text().strip()
        self._submit("configs", lambda: view.config_labels(prefix))

    def _configs(self, result: object) -> None:
        assert isinstance(result, list)
        self.cmp_base.clear()
        self.cmp_base.addItems([str(x) for x in result])
        self.cmp_status.setText(f"{len(result)} configs under this prefix")

    def compare(self) -> None:
        if self.view is None:
            return
        view = self.view
        prefix, base = self.cmp_prefix.text().strip(), self.cmp_base.currentText().strip()
        metric, level = self.cmp_metric.currentText().strip(), self.cmp_level.currentText()
        self.cmp_status.setText("comparing ...")
        self._submit("compare", lambda: view.compare(prefix, base, metric, level or None))

    def _compared(self, result: object) -> None:
        assert isinstance(result, mimirview.Compare)
        self.cmp_pane.set_table(result.as_table())
        self.cmp_chart.set_rows(result.rows)
        self.cmp_status.setText(
            f"{len(result.rows)} configs; ratio < 1 is lower than {result.base}"
        )

    # ---- plot ----

    def plot(self) -> None:
        if self.view is None:
            return
        view = self.view
        x, y = self.plot_x.currentText(), self.plot_y.currentText()
        src = self.plot_source.currentText()
        source = None if src in ("", "(all sources)") else src
        self.plot_status.setText("plotting ...")
        self._submit("plot", lambda: (x, y, view.scatter(x, y, source)))

    def _plotted(self, result: object) -> None:
        assert isinstance(result, tuple)
        x, y, pts = result
        self.chart.set_points(pts, x, y)
        self.plot_status.setText(f"{len(pts)} designs")

    def _log_changed(self) -> None:
        self.chart.set_log(self.log_x.isChecked(), self.log_y.isChecked())
