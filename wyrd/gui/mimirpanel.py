"""The Mímir dock: browse a Mimir store read only (designs, runs, compare, plot). Spec:
docs/specs/2026-10-28-mimir-browser.md. Every store query runs on a worker thread; a token per
request kind drops stale results. `mimir fetch` runs in a QProcess with its output shown."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QRunnable, Qt, QThreadPool, Signal
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
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from wyrd import mimirview
from wyrd.gui.mimircharts import DotChart, ScatterChart
from wyrd.gui.mimirexplore import StructuresTab, TimingTab
from wyrd.gui.tablepane import TablePane
from wyrd.mimirview import MimirError, MimirView, Table

NO_STORE = "No Mímir store open. Use File > Open Mímir store... or the button below."
FETCH_TIP_MISSING = "The `mimir` command is not on PATH; install the mimir package to fetch."
LIST_LIMIT = 500
ROW_LIMIT = mimirview.DEFAULT_LIMIT  # rows per design table
RUN_TEXT = "Select a run in the Design tab (double click)."


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
    fetch_finished = Signal(int)
    heat_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.view: MimirView | None = None
        self.last_path = ""
        self.timings: dict[str, float] = {}
        self.argv_for: Callable[[str, Path, Path], list[str]] = mimirview.fetch_argv
        self.fetch_dir: Callable[[], str] = self._ask_dir
        self._proc: QProcess | None = None
        self._pending: MimirView | None = None
        self._design_key: tuple[str, str | None] | None = None
        self._notes = ""
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
        self.structs = StructuresTab(self._submit)
        self.timing_tab = TimingTab(self._submit)

    def _make_design_widgets(self) -> None:
        self.design_label = QLabel("")
        self.design_level = QComboBox()
        self.design_level.setToolTip("Show only metric records of this level")
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
        self.run_label = QLabel(RUN_TEXT)
        self.run_label.setWordWrap(True)
        self.params_pane = TablePane("conf")
        self.artifacts_pane = TablePane()
        self.fetch_button = QPushButton("Fetch artifacts...")
        self.cancel_button = QPushButton("Cancel fetch")
        self.cancel_button.setEnabled(False)
        self.fetch_log = QPlainTextEdit()
        self.fetch_log.setReadOnly(True)
        self.fetch_log.setMaximumHeight(110)

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
        self.cmp_scroll = QScrollArea()
        self.cmp_scroll.setWidgetResizable(True)
        self.cmp_scroll.setWidget(self.cmp_chart)
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
        self.tabs.addTab(self.structs, "Structures")
        self.tabs.addTab(self.timing_tab, "Timing")
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
        top = QHBoxLayout()
        top.addWidget(self.design_label, 1)
        top.addWidget(QLabel("Metrics level"))
        top.addWidget(self.design_level)
        lay.addLayout(top)
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
        row = QHBoxLayout()
        row.addWidget(self.fetch_button)
        row.addWidget(self.cancel_button)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(self.fetch_log)
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
        lay.addWidget(self.cmp_scroll, 1)
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
        self.cancel_button.clicked.connect(self.cancel_fetch)
        self.design_level.activated.connect(self._refresh_design)
        self.cmp_load.clicked.connect(self.list_configs)
        self.cmp_go.clicked.connect(self.compare)
        self.plot_go.clicked.connect(self.plot)
        self.log_x.toggled.connect(self._log_changed)
        self.log_y.toggled.connect(self._log_changed)
        self.chart.hovered.connect(self.hover.setText)
        self.timing_tab.heat_requested.connect(self.heat_requested)

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
            "configs": self._configs, "list": self._listed, "design": self._designed,
            "run": self._ran,
            **self.structs.handlers(), **self.timing_tab.handlers(),
        }[key]  # fmt: skip
        handler(result)
        self.finished.emit(key)

    def _on_failed(self, token: int, key: str, reason: str) -> None:
        if token != self._tokens.get(key):
            return
        if key == "open":
            self._pending = None
        self.status.setText(f"{key}: {reason}")
        self.finished.emit(key)

    def _invalidate(self) -> None:
        """Drop every request still in flight (their tokens no longer match)."""
        keys = ("open", "list", "design", "run", "configs", "compare", "plot")
        for key in (*keys, *StructuresTab.KEYS, *TimingTab.KEYS):
            self._tokens[key] = self._tokens.get(key, 0) + 1

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
        """Check the file (cheap), then read the summary on the worker. False: not usable.

        Nothing of the previous store changes until the new one has been read.
        """
        try:
            view = MimirView(path)
        except MimirError as e:
            self.status.setText(str(e))
            return False
        self._invalidate()
        self._pending = view
        self.status.setText(f"Reading {path.name} ...")
        self._submit(
            "open",
            lambda: (
                view.summary(), view.metric_names(), view.sources(), mimirview.metric_descriptions()
            ),
        )  # fmt: skip
        return True

    def _opened(self, result: object) -> None:
        assert isinstance(result, tuple) and self._pending is not None
        summary, metrics, sources, descriptions = result
        self.view, self._pending = self._pending, None
        self._reset()
        self.set_last(str(self.view.path))
        wal = "; a -wal file exists beside it, another process may have it open"
        self.status.setText(
            f"{self.view.path}  (schema version {summary.version}, read only"
            + (wal if self.view.wal_present else "")
            + ")"
        )
        counts = ", ".join(f"{k}={n}" for k, n in summary.counts.items())
        self._notes = summary.note
        self.summary_text.setPlainText(
            f"{self.view.path.name}  {summary.size_bytes} bytes\nrows: {counts}\n"
            f"levels: {', '.join(summary.levels)}\ndistinct metrics: {summary.n_metrics}\n"
            + (f"NOTE: {summary.note}\n" if summary.note else "")
        )
        self.cmp_status.setText(summary.note)
        self.sources_pane.set_table(summary.sources)
        self.source.clear()
        self.source.addItems(["(all sources)", *sources])
        self.plot_source.clear()
        self.plot_source.addItems(["(all sources)", *sources])
        for combo in (self.cmp_metric, self.plot_x, self.plot_y):
            combo.clear()
            combo.addItems(metrics)
            for i, name in enumerate(metrics):
                combo.setItemData(i, descriptions.get(name, ""), Qt.ItemDataRole.ToolTipRole)
        if self.plot_y.count() > 1:
            self.plot_y.setCurrentIndex(1)
        for combo, first in ((self.cmp_level, ""), (self.design_level, "")):
            combo.clear()
            combo.addItems([first, *summary.levels])
        self.structs.set_view(self.view)
        self.timing_tab.set_view(self.view if self.view.has_timing() else None)
        self.store_opened.emit(str(self.view.path))
        self.fill_designs()

    def _reset(self) -> None:
        """Clear everything that belonged to the previous store."""
        self.cancel_fetch()
        self._current_run, self._design_key, self._notes = "", None, ""
        self.designs.clear()
        self.design_label.setText("")
        for pane in (
            self.metrics_pane, self.runs_pane, self.meta_pane, self.lineage_pane,
            self.struct_pane, self.params_pane, self.artifacts_pane, self.cmp_pane,
        ):  # fmt: skip
            pane.full_query = None
            pane.set_table(Table("", (), []))
        self.run_label.setText(RUN_TEXT)
        self.fetch_log.clear()
        self.cmp_chart.set_rows([])
        self.cmp_base.clear()
        self.cmp_status.setText("")
        self.chart.set_points([], "", "")
        self.plot_status.setText("")
        self.hover.setText("")
        self._set_fetch_enabled()

    # ---- design list and views ----

    def fill_designs(self) -> None:
        if self.view is None:
            return
        view, text = self.view, self.filter.text().strip()
        src = self.source.currentText()
        source = None if src in ("", "(all sources)") else src
        self._submit("list", lambda: view.designs(source, text, LIST_LIMIT))

    def _listed(self, result: object) -> None:
        assert isinstance(result, Table)
        t = result
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
        view, level = self.view, self.design_level.currentText() or None
        self._design_key = (name, source)
        self._submit("design", lambda: (view, view.design(name, source, ROW_LIMIT, level), level))

    def _refresh_design(self) -> None:
        if self._design_key is not None:
            self.show_design(*self._design_key)

    def _designed(self, result: object) -> None:
        assert isinstance(result, tuple)
        view, d, level = result
        self.design_label.setText(f"{d.name}  ({', '.join(d.sources)})")
        source = self._design_key[1] if self._design_key else None
        self.metrics_pane.full_query = lambda: view.design(d.name, source, 0, level).metrics
        self.runs_pane.full_query = lambda: view.design(d.name, source, 0, level).runs
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
        view = self.view
        self._submit("run", lambda: view.run(run_id))

    def _ran(self, result: object) -> None:
        assert isinstance(result, mimirview.RunInfo)
        r = result
        self._current_run = r.run_id
        h = r.header
        self.run_label.setText(
            f"run {r.run_id}: {h['design']}  {h['source']}  arch {h['arch']}  arm {h['arm']}  "
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
        running = self._proc is not None
        self.fetch_button.setEnabled(have and bool(self._current_run) and not running)
        self.fetch_button.setToolTip("" if have else FETCH_TIP_MISSING)
        self.cancel_button.setEnabled(running)

    def _ask_dir(self) -> str:
        return QFileDialog.getExistingDirectory(self, "Fetch artifacts into")

    def fetch(self) -> bool:
        """Start `mimir fetch --run ID --db DB --out DIR` (QProcess, no shell); True: started."""
        if self.view is None or not self._current_run or self._proc is not None:
            return False
        out = self.fetch_dir()
        if not out:
            return False
        argv = self.argv_for(self._current_run, self.view.path, Path(out))
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.readyReadStandardOutput.connect(self._fetch_output)
        proc.finished.connect(self._fetch_done)
        proc.errorOccurred.connect(self._fetch_error)
        self._proc = proc
        self.fetch_log.setPlainText("$ " + " ".join(argv) + "\n")
        self.status.setText("mimir fetch running ...")
        proc.start(argv[0], argv[1:])
        self._set_fetch_enabled()
        return True

    def _fetch_output(self) -> None:
        if self._proc is not None:
            self._fetch_output_of(self._proc)

    def _fetch_done(self, code: int, status: QProcess.ExitStatus) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            self._fetch_output_of(proc)
            proc.deleteLater()
        crashed = status != QProcess.ExitStatus.NormalExit
        self.status.setText("mimir fetch cancelled" if crashed else f"mimir fetch exited {code}")
        self._set_fetch_enabled()
        self.fetch_finished.emit(-1 if crashed else code)

    def _fetch_output_of(self, proc: QProcess) -> None:
        text = bytes(proc.readAllStandardOutput().data()).decode(errors="replace").rstrip()
        if text:
            self.fetch_log.appendPlainText(text)

    def _fetch_error(self, error: QProcess.ProcessError) -> None:
        if error != QProcess.ProcessError.FailedToStart:
            return
        proc, self._proc = self._proc, None
        if proc is not None:
            proc.deleteLater()
        self.status.setText("mimir fetch failed to start")
        self.fetch_log.appendPlainText("failed to start")
        self._set_fetch_enabled()
        self.fetch_finished.emit(-1)

    def cancel_fetch(self) -> None:
        """Kill a running fetch (the finished handler reports it)."""
        if self._proc is not None:
            self._proc.kill()

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
        self.cmp_chart.set_rows(result.rows, result.multi_level)
        mixed = sum(1 for r in result.rows if r.mixed)
        self.cmp_status.setText(
            f"{len(result.rows)} rows; ratio < 1 is lower than {result.base}"
            + (f"; {mixed} MIXED (more than one tool commit or config)" if mixed else "")
            + (" (levels shown separately)" if result.multi_level else "")
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
        x, y, sc = result
        self.chart.set_points(sc.points, x, y)
        self.plot_status.setText(sc.note)

    def _log_changed(self) -> None:
        self.chart.set_log(self.log_x.isChecked(), self.log_y.isChecked())
