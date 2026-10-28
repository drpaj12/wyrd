"""Structures and Timing tabs of the Mímir dock (spec 2026-10-28-heat-explore.md, section 4).

Read only. The tabs run their queries through ``submit(key, fn)`` of the dock (worker thread, a
token per key drops stale results) and get the result back in ``handle(key, result)``.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from wyrd import mimirview
from wyrd.gui.mimircharts import HistChart, ScatterChart
from wyrd.gui.tablepane import TablePane
from wyrd.guimodel import heatmimir
from wyrd.mimirview import MimirView, Scatter, Table

Submit = Callable[[str, Callable[[], object]], None]
ALL = "(all)"
NO_TIMING = (
    "This store has no timing tables (schema 5, `mimir import-timing`). "
    "The hot/cold view needs them."
)
OBJECT_KINDS = ("word", "span", "module", "structure")
NC_METRICS = ("timing.nc_paths_090", "timing.nc_paths_095", "timing.nc_paths_099")
AREA_HINTS = ("lut", "clb", "block")
ROW_LIMIT = 500


def _row(*items: QWidget | str) -> QHBoxLayout:
    row = QHBoxLayout()
    for it in items:
        row.addWidget(QLabel(it) if isinstance(it, str) else it)
    row.addStretch(1)
    return row


def _fill(combo: QComboBox, items: list[str], keep: str = "") -> None:
    combo.blockSignals(True)
    combo.clear()
    combo.addItems(items)
    if keep in items:
        combo.setCurrentText(keep)
    combo.blockSignals(False)


def _opt(combo: QComboBox) -> str:
    text = combo.currentText()
    return "" if text in ("", ALL) else text


class StructuresTab(QWidget):
    """structure_mapping rows of a design with filters, and spread against crit_share."""

    KEYS = ("sdesigns", "sfilters", "sdata")

    def __init__(self, submit: Submit) -> None:
        super().__init__()
        self._submit = submit
        self.view: MimirView | None = None
        self.design = QComboBox()
        self.run = QComboBox()
        self.level = QComboBox()
        self.kind = QComboBox()
        self.status = QLabel("Open a store with structure_mapping rows.")
        self.pane = TablePane()
        self.chart = ScatterChart()
        self.hover = QLabel("")
        lay = QVBoxLayout(self)
        lay.addLayout(_row("Design", self.design, "Run", self.run, "Level", self.level,
                           "Kind", self.kind))  # fmt: skip
        lay.addWidget(self.status)
        lay.addWidget(self.pane, 2)
        lay.addWidget(self.chart, 1)
        lay.addWidget(self.hover)
        self.design.activated.connect(self._design_changed)
        for c in (self.run, self.level, self.kind):
            c.activated.connect(self.reload)
        self.chart.hovered.connect(self.hover.setText)

    def handlers(self) -> dict[str, Callable[[object], None]]:
        return {"sdesigns": self._designs, "sfilters": self._filters, "sdata": self._data}

    def set_view(self, view: MimirView | None) -> None:
        self.view = view
        for c in (self.design, self.run, self.level, self.kind):
            _fill(c, [])
        self.pane.full_query = None
        self.pane.set_table(Table("", (), []))
        self.chart.set_points([], "", "")
        self.status.setText("Reading structures ...")
        if view is not None:
            self._submit("sdesigns", view.structure_designs)

    def _designs(self, result: object) -> None:
        assert isinstance(result, list)
        _fill(self.design, [str(x) for x in result])
        if not result:
            self.status.setText("This store has no structure_mapping rows.")
            return
        self._design_changed()

    def select_design(self, name: str) -> None:
        self.design.setCurrentText(name)
        self._design_changed()

    def _design_changed(self) -> None:
        if self.view is None or not self.design.currentText():
            return
        view, design = self.view, self.design.currentText()
        self._submit(
            "sfilters", lambda: (view.structure_runs(design), *view.structure_filters(design))
        )

    def _filters(self, result: object) -> None:
        assert isinstance(result, tuple)
        runs, levels, kinds = result
        _fill(self.run, [ALL, *runs])
        _fill(self.level, [ALL, *levels])
        _fill(self.kind, [ALL, *kinds])
        self.reload()

    def reload(self) -> None:
        if self.view is None or not self.design.currentText():
            return
        view = self.view
        args = (self.design.currentText(), _opt(self.run), _opt(self.level), _opt(self.kind))
        self.pane.full_query = lambda: view.structure_rows(*args, limit=0)
        self._submit("sdata", lambda: (view.structure_rows(*args), view.structure_scatter(*args)))

    def _data(self, result: object) -> None:
        assert isinstance(result, tuple)
        table, scatter = result
        assert isinstance(table, Table) and isinstance(scatter, Scatter)
        self.pane.set_table(table)
        self.chart.set_points(scatter.points, "placement spread", "crit_share")
        self.status.setText(
            f"{len(table.rows)} structure rows; {len(scatter.points)} with spread and crit_share"
        )


class TimingTab(QWidget):
    """Per run: slack histogram, near-critical objects; across runs: counts against area."""

    heat_requested = Signal(object)  # a HeatModel from the run's timing_object rows
    KEYS = ("truns", "tdata", "tscatter", "tmetrics", "trows")

    def __init__(self, submit: Submit) -> None:
        super().__init__()
        self._submit = submit
        self.view: MimirView | None = None
        self._run_ids: list[str] = []
        self.run = QComboBox()
        self.kind = QComboBox()
        self.kind.addItems(OBJECT_KINDS)
        self.summary = QLabel(NO_TIMING)
        self.summary.setWordWrap(True)
        self.hist = HistChart()
        self.pane = TablePane()
        self.open_button = QPushButton("Open in source view")
        self.open_button.setToolTip(
            "Colour the HDL of the project by this run's near-critical objects; "
            "open the design's source file afterwards"
        )
        self.open_button.setEnabled(False)
        self.x_metric = QComboBox()
        self.y_metric = QComboBox()
        self.y_metric.addItems(NC_METRICS)
        self.go = QPushButton("Plot runs")
        self.chart = ScatterChart()
        self.hover = QLabel("")
        self.scatter_status = QLabel("")
        lay = QVBoxLayout(self)
        lay.addLayout(_row("Run", self.run, "Objects", self.kind, self.open_button))
        lay.addWidget(self.summary)
        lay.addWidget(self.hist, 1)
        lay.addWidget(self.pane, 2)
        lay.addLayout(_row("area x", self.x_metric, "near-critical y", self.y_metric, self.go))
        lay.addWidget(self.scatter_status)
        lay.addWidget(self.chart, 1)
        lay.addWidget(self.hover)
        self.run.activated.connect(self.reload)
        self.kind.activated.connect(self.reload)
        self.go.clicked.connect(self.plot)
        self.open_button.clicked.connect(self._open_clicked)
        self.chart.hovered.connect(self.hover.setText)

    def handlers(self) -> dict[str, Callable[[object], None]]:
        return {"truns": self._runs, "tdata": self._data, "tscatter": self._plotted,
                "tmetrics": self._metrics, "trows": self._rows}  # fmt: skip

    def set_view(self, view: MimirView | None) -> None:
        self.view = view
        _fill(self.run, [])
        self._run_ids = []
        self.pane.full_query = None
        self.pane.set_table(Table("", (), []))
        self.hist.set_counts([])
        self.chart.set_points([], "", "")
        self.open_button.setEnabled(False)
        self.summary.setText("Reading timing ..." if view is not None else NO_TIMING)
        if view is not None:
            self._submit("truns", lambda: (view.timing_runs(), view.metric_names()))

    def _runs(self, result: object) -> None:
        assert isinstance(result, tuple)
        runs, metrics = result
        self._run_ids = [r for r, _ in runs]
        if not runs:
            self.summary.setText(NO_TIMING)
            return
        _fill(self.run, [label for _, label in runs])
        area = [m for m in metrics if any(h in m.lower() for h in AREA_HINTS)]
        _fill(self.x_metric, area or list(metrics))
        note = "" if area else " No LUT/CLB records in this store: x lists all metrics."
        self.scatter_status.setText(note.strip())
        self.reload()

    def current_run(self) -> str:
        i = self.run.currentIndex()
        return self._run_ids[i] if 0 <= i < len(self._run_ids) else ""

    def select_run(self, run_id: str) -> None:
        if run_id in self._run_ids:
            self.run.setCurrentIndex(self._run_ids.index(run_id))
            self.reload()

    def reload(self) -> None:
        run_id = self.current_run()
        if self.view is None or not run_id:
            return
        view, kind = self.view, self.kind.currentText()
        self.pane.full_query = lambda: view.timing_top_objects(run_id, kind, 0)
        top = ROW_LIMIT
        self._submit(
            "tdata", lambda: (view.timing_run(run_id), view.timing_top_objects(run_id, kind, top))
        )

    def _data(self, result: object) -> None:
        assert isinstance(result, tuple)
        info, table = result
        assert isinstance(info, mimirview.TimingRunInfo) and isinstance(table, Table)
        self.hist.set_counts(info.hist)
        self.pane.set_table(table)
        self.summary.setText(summary_text(info))
        self.open_button.setEnabled(True)

    def plot(self) -> None:
        if self.view is None:
            return
        view, x, y = self.view, self.x_metric.currentText(), self.y_metric.currentText()
        self.scatter_status.setText("plotting ...")
        self._submit("tscatter", lambda: (x, y, view.run_scatter(x, y)))

    def _plotted(self, result: object) -> None:
        assert isinstance(result, tuple)
        x, y, sc = result
        self.chart.set_points(sc.points, x, y)
        self.scatter_status.setText(f"{len(sc.points)} runs with both metrics")

    def _metrics(self, result: object) -> None:
        pass

    def _open_clicked(self) -> None:
        run_id = self.current_run()
        if self.view is None or not run_id:
            return
        view = self.view
        self._submit("trows", lambda: heatmimir.model_from_objects(view.timing_object_rows(run_id)))

    def _rows(self, result: object) -> None:
        self.heat_requested.emit(result)


def summary_text(info: mimirview.TimingRunInfo) -> str:
    s = info.summary

    def get(k: str) -> str:
        v = s.get(k)
        return "n/a" if v is None else f"{v:g}" if isinstance(v, int | float) else str(v)

    near = ", ".join(f">= {t}: {get(f'timing.nc_paths_{k}')}"
                     for t, k in (("0.90", "090"), ("0.95", "095"), ("0.99", "099")))  # fmt: skip
    trunc = "TRUNCATED at 0.90 (counts are lower bounds)" if s.get("trunc_090") else "not truncated"
    return (
        f"{info.label}\nCPD {get('cpd_ns')} ns, worst slack {get('worst_slack_ns')} ns, "
        f"{get('paths_used')} of {get('paths_requested')} paths used ({trunc}). "
        f"Near-critical paths {near}. Source: {get('source_kind')}."
    )
