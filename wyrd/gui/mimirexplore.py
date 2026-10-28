"""Structures and Timing tabs of the Mímir dock (spec 2026-10-28-heat-explore.md, section 4).

Read only. The tabs run their queries through ``submit(key, fn)`` of the dock (worker thread, a
token per key drops stale results) and get the result back in ``handle(key, result)``.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from wyrd import mimirview
from wyrd.gui.helpbox import HelpBox
from wyrd.gui.mimircharts import HistChart, ScatterChart
from wyrd.gui.tablepane import TablePane
from wyrd.guimodel import heatmimir, mimirhelp
from wyrd.mimirview import MimirView, Scatter, Table

Submit = Callable[[str, Callable[[], object]], None]
ALL = "(all)"
NO_TIMING = (
    "This store has no timing tables (schema 5, `mimir import-timing`). "
    "The hot/cold view needs them."
)
OBJECT_KINDS = ("word", "span", "module", "structure")
NC_METRICS = ("timing.nc_paths_090", "timing.nc_paths_095", "timing.nc_paths_099")
AREA_HINTS = ("lut", "clb")  # a LUT or CLB count is real area; anything else is a proxy
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

    def __init__(self, submit: Submit, settings: QSettings | None = None) -> None:
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
        self._loaded = False  # the design list has arrived
        self._sources: dict[str, set[str]] = {}
        self._pending: tuple[str, str] | None = None  # (source, design) asked for before that
        self._note = ""  # says the structures come from another source than the picked one
        lay = QVBoxLayout(self)
        lay.addWidget(HelpBox("Structures", settings=settings))
        lay.addLayout(_row("Design", self.design, "Run", self.run, "Level", self.level,
                           "Kind", self.kind))  # fmt: skip
        lay.addWidget(self.status)
        lay.addWidget(self.pane, 2)
        lay.addWidget(self.chart, 1)
        lay.addWidget(self.hover)
        self._tips({self.design: "design", self.run: "run", self.level: "level", self.kind: "kind"})
        self.chart.setToolTip(
            "One dot per structure row: x = spread (how far apart on the chip its parts were "
            "placed), y = crit_share (its part of the critical path delay)."
        )
        self.design.activated.connect(self._design_changed)
        for c in (self.run, self.level, self.kind):
            c.activated.connect(self.reload)
        self.chart.hovered.connect(self.hover.setText)

    @staticmethod
    def _tips(controls: dict[QWidget, str]) -> None:
        for w, key in controls.items():
            w.setToolTip(mimirhelp.CONTROL_TIPS[key])

    def handlers(self) -> dict[str, Callable[[object], None]]:
        return {"sdesigns": self._designs, "sfilters": self._filters, "sdata": self._data}

    def set_view(self, view: MimirView | None) -> None:
        self.view = view
        self._loaded, self._pending, self._sources = False, None, {}
        for c in (self.design, self.run, self.level, self.kind):
            _fill(c, [])
        self.pane.full_query = None
        self.pane.set_table(Table("", (), []))
        self.chart.set_points([], "", "")
        self.status.setText("Reading structures ...")
        if view is not None:
            self._submit(
                "sdesigns", lambda: (view.structure_designs(), view.structure_design_sources())
            )

    def _designs(self, result: object) -> None:
        assert isinstance(result, tuple)
        designs, self._sources = result
        self._loaded = True
        _fill(self.design, [str(x) for x in designs])
        if not designs:
            self.status.setText("This store has no structure_mapping rows.")
            return
        pending, self._pending = self._pending, None
        if pending is not None:
            self.select_design(pending[1], pending[0])
            return
        self._design_changed()

    def _match(self, names: list[str], name: str, source: str) -> str:
        """The store's design key ("suite/design") for (source, design): the name must match
        exactly or after the last "/", and, when the store says which sources ran it, the source
        must be one of them."""
        for n in names:
            if n != name and n.rsplit("/", 1)[-1] != name:
                continue
            known = self._sources.get(n)
            if not source or not known or source in known:
                return n
        return ""

    def select_design(self, name: str, source: str | None = None) -> None:
        """Show one design; say so in plain words when the store has no structures for it."""
        if self.view is None:
            return
        if not self._loaded:  # the list is still being read: apply this choice when it arrives
            self._pending = (source or "", name)
            return
        names = [self.design.itemText(i) for i in range(self.design.count())]
        found = self._match(names, name, source or "")
        self._note = ""
        if not found and source:  # the picked source has none: use any other source
            found = self._match(names, name, "")
            others = sorted(self._sources.get(found, set())) if found else []
            if others:
                self._note = (
                    f"Structures from source {', '.join(others)}; the picked source "
                    f"{source} has none. "
                )
        if not found:
            self.pane.full_query = None
            self.pane.set_table(Table("", (), []))
            self.chart.set_points([], "", "")
            self.status.setText(f"no structure data for {name} in this store")
            return
        self.design.setCurrentText(found)
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
        for combo, items in ((self.run, runs), (self.level, levels), (self.kind, kinds)):
            _fill(combo, [ALL, *items], combo.currentText())  # keep a pick that is still valid
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
            f"{self._note}{len(table.rows)} structure rows; "
            f"{len(scatter.points)} with spread and crit_share"
        )


class TimingTab(QWidget):
    """Per run: slack histogram, near-critical objects; across runs: counts against area."""

    heat_requested = Signal(object)  # a HeatModel from the run's timing_object rows
    run_changed = Signal(str)  # the user picked a run in the combo
    heat_ready = Signal(bool)  # the shown run can be opened as a hot/cold source view
    KEYS = ("truns", "tdata", "tscatter", "tmetrics", "trows")

    def __init__(self, submit: Submit, settings: QSettings | None = None) -> None:
        super().__init__()
        self._submit = submit
        self.view: MimirView | None = None
        self._run_ids: list[str] = []
        self._all_runs: list[tuple[str, str]] = []
        self._design = ""
        self._source = ""
        self._requested = ""  # the run whose data was last asked for
        self._note = ""  # says the runs come from another source than the picked one
        self.run = QComboBox()
        self.kind = QComboBox()
        self.kind.addItems(OBJECT_KINDS)
        self.summary = QLabel(NO_TIMING)
        self.summary.setWordWrap(True)
        self.hist = HistChart()
        self.pane = TablePane()
        self.open_button = QPushButton("Open in source view")
        self.open_button.setToolTip(mimirhelp.CONTROL_TIPS["open"])
        self.open_button.setEnabled(False)
        self.x_metric = QComboBox()
        self.y_metric = QComboBox()
        self.y_metric.addItems(NC_METRICS)
        self.go = QPushButton("Plot runs")
        self.chart = ScatterChart()
        self.hover = QLabel("")
        self.scatter_status = QLabel("")
        lay = QVBoxLayout(self)
        lay.addWidget(HelpBox("Timing", settings=settings))
        lay.addLayout(_row("Run", self.run, "Objects", self.kind, self.open_button))
        lay.addWidget(self.summary)
        lay.addWidget(self.hist, 1)
        lay.addWidget(self.pane, 2)
        lay.addLayout(_row("area x", self.x_metric, "near-critical y", self.y_metric, self.go))
        lay.addWidget(self.scatter_status)
        lay.addWidget(self.chart, 1)
        lay.addWidget(self.hover)
        for w, key in ((self.run, "run"), (self.kind, "objects"), (self.x_metric, "area x"),
                       (self.y_metric, "near-critical y")):  # fmt: skip
            w.setToolTip(mimirhelp.CONTROL_TIPS[key])
        self.hist.setToolTip(
            "Number of paths per criticality range, from 0 (spare time) to 1 (slowest path)."
        )
        self.go.setToolTip("Plot one dot per run: area on x, near-critical paths on y.")
        self.run.activated.connect(self._picked)
        self.kind.activated.connect(self.reload)
        self.go.clicked.connect(self.plot)
        self.open_button.clicked.connect(self.open_clicked)
        self.chart.hovered.connect(self.hover.setText)

    def handlers(self) -> dict[str, Callable[[object], None]]:
        return {"truns": self._runs, "tdata": self._data, "tscatter": self._plotted,
                "tmetrics": self._metrics, "trows": self._rows}  # fmt: skip

    def set_view(self, view: MimirView | None) -> None:
        self.view = view
        _fill(self.run, [])
        self._run_ids = []
        self._all_runs = []
        self._design, self._source, self._requested, self._note = "", "", "", ""
        self.pane.full_query = None
        self.pane.set_table(Table("", (), []))
        self.hist.set_counts([])
        self.chart.set_points([], "", "")
        self._set_open(False)
        self.summary.setText("Reading timing ..." if view is not None else NO_TIMING)
        if view is not None:
            self._submit("truns", lambda: (view.timing_runs(), view.metric_names()))

    def _runs(self, result: object) -> None:
        assert isinstance(result, tuple)
        runs, metrics = result
        self._all_runs = list(runs)
        if not runs:
            self._no_data()
            return
        self._fill_runs()
        area = [m for m in metrics if is_area(m)]
        _fill(self.x_metric, area or list(metrics))
        note = "" if area else "No LUT/CLB records in this store: x lists all metrics (a proxy)."
        self.scatter_status.setText(note)
        if self._run_ids:
            self.reload()
        else:
            self._no_data()

    def _set_open(self, enabled: bool) -> None:
        self.open_button.setEnabled(enabled)
        self.heat_ready.emit(enabled)

    def has_timing_for(self, design: str) -> bool:
        """True when some run of the design (any source) has timing."""
        return any(label.split(" / ")[0] == design for _, label in self._all_runs)

    def _wanted(self, label: str, any_source: bool = False) -> bool:
        """A run label is "design / source / arm / seed n [id]": match design and source fields."""
        if not self._design:
            return True
        fields = label.split(" / ")
        if fields[0] != self._design:
            return False
        if any_source or not self._source:
            return True
        return len(fields) > 1 and fields[1] == self._source

    def _fill_runs(self) -> None:
        runs = [r for r in self._all_runs if self._wanted(r[1])]
        self._note = ""
        if not runs and self._design and self._source:  # the picked source has none: use others
            runs = [r for r in self._all_runs if self._wanted(r[1], any_source=True)]
            others = sorted({r[1].split(" / ")[1] for r in runs if " / " in r[1]})
            if runs:
                self._note = (
                    f"Timing from source {', '.join(others)}; the picked source "
                    f"{self._source} has none."
                )
        self._run_ids = [r for r, _ in runs]
        _fill(self.run, [label for _, label in runs], self.run.currentText())

    def _no_data(self) -> None:
        self._requested = ""
        self.hist.set_counts([])
        self.pane.full_query = None
        self.pane.set_table(Table("", (), []))
        self._set_open(False)
        if self._design:
            self.summary.setText(f"no timing data for {self._design} in this store")
        else:
            self.summary.setText(NO_TIMING)

    def select_design(self, name: str, source: str | None = None) -> None:
        """List the runs of one (source, design) (all runs for "") and show the first/kept one."""
        self._design, self._source = name, source or ""
        if not self._all_runs:
            if self.view is not None and not self.summary.text().startswith("Reading"):
                self._no_data()
            return
        self._fill_runs()
        if self._run_ids:
            self.reload()
        else:
            self._no_data()

    def _picked(self) -> None:
        self.reload()
        self.run_changed.emit(self.current_run())

    def current_run(self) -> str:
        i = self.run.currentIndex()
        return self._run_ids[i] if 0 <= i < len(self._run_ids) else ""

    def select_run(self, run_id: str) -> None:
        if run_id not in self._run_ids:
            return
        index = self._run_ids.index(run_id)
        if index == self.run.currentIndex() and run_id == self._requested:
            return  # already showing it
        self.run.setCurrentIndex(index)
        self.reload()

    def reload(self) -> None:
        run_id = self.current_run()
        if self.view is None or not run_id:
            return
        view, kind = self.view, self.kind.currentText()
        self._requested = run_id
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
        self.summary.setText((self._note + "\n" if self._note else "") + summary_text(info))
        self._set_open(True)

    def plot(self) -> None:
        if self.view is None:
            return
        view, x, y = self.view, self.x_metric.currentText(), self.y_metric.currentText()
        self.scatter_status.setText("plotting ...")
        self._submit("tscatter", lambda: (x, y, view.run_scatter(x, y)))

    def _plotted(self, result: object) -> None:
        assert isinstance(result, tuple)
        x, y, sc = result
        proxy = not is_area(x)
        self.chart.set_points(sc.points, f"area proxy: {x}" if proxy else x, y)
        text = f"{len(sc.points)} runs with both metrics"
        note = f"; area proxy: {x} (not a LUT or CLB count)"
        self.scatter_status.setText(text + (note if proxy else ""))

    def _metrics(self, result: object) -> None:
        pass

    def open_clicked(self) -> None:
        run_id = self.current_run()
        if self.view is None or not run_id:
            return
        view = self.view

        def build() -> object:
            dmax = view.timing_run(run_id).summary.get("dmax_source")
            return heatmimir.model_from_objects(
                view.timing_object_rows(run_id), view.design_origin(run_id), str(dmax or ""),
                str(view.path), run_id,
            )

        self._submit("trows", build)

    def _rows(self, result: object) -> None:
        self.heat_requested.emit(result)


def is_area(metric: str) -> bool:
    """True for a LUT or CLB record; any other metric is only an area proxy."""
    return any(h in metric.lower() for h in AREA_HINTS)


def _exactness(dmax: object) -> str:
    if dmax == "report":
        return "crit is a lower bound (dmax from report)"
    if dmax in ("exhaustive", "full-report"):
        return f"crit is exact ({str(dmax).replace('-', ' ')})"
    return ""


def _truncation(s: dict[str, object]) -> str:
    states = [s.get(f"trunc_{k}") for k in ("090", "095", "099")]
    if all(v == -1 for v in states):
        return "truncation unknown"
    if any(v == 1 for v in states):
        return "TRUNCATED (near-critical counts are lower bounds)"
    if any(v == -1 for v in states):
        return "truncation unknown for some theta"
    return "not truncated"


def summary_text(info: mimirview.TimingRunInfo) -> str:
    s = info.summary

    def get(k: str) -> str:
        v = s.get(k)
        return "n/a" if v is None else f"{v:g}" if isinstance(v, int | float) else str(v)

    near = ", ".join(f">= {t}: {get(f'timing.nc_paths_{k}')}"
                     for t, k in (("0.90", "090"), ("0.95", "095"), ("0.99", "099")))  # fmt: skip
    exact = _exactness(s.get("dmax_source"))
    spread = f" Required-time spread {get('req_spread_ns')} ns." if "req_spread_ns" in s else ""
    missing = f" This store lacks: {', '.join(info.missing)}." if info.missing else ""
    return (
        f"{info.label}\nCPD {get('cpd_ns')} ns, worst slack {get('worst_slack_ns')} ns, "
        f"{get('paths_used')} of {get('paths_requested')} paths used ({_truncation(s)}). "
        f"Near-critical paths {near}. Source: {get('source_kind')}."
        + (f" {exact[0].upper()}{exact[1:]}." if exact else "")
        + spread
        + missing
    )
