"""Report tab: run tree plus Summary, All runs, Compare and log pages."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wyrd import report
from wyrd.gui.sourceview import read_limited
from wyrd.guimodel import runs
from wyrd.guimodel.floorplan import FloorplanPlan, plan_floorplan
from wyrd.guimodel.runs import RunInfo

ROLE_KIND = Qt.ItemDataRole.UserRole
ROLE_ARG = Qt.ItemDataRole.UserRole + 1
EMPTY_TEXT = "No results yet. Run the flow."
COMPARE_HINT = "Choose another project to compare."


def _fill(table: QTableWidget, rows: list[list[str]]) -> None:
    table.clear()
    head = rows[0] if rows else []
    body = rows[1:]
    width = max([len(head), *(len(r) for r in body)])
    table.setColumnCount(width)
    table.setRowCount(len(body))
    table.setHorizontalHeaderLabels(head if head else [""] * width)
    for r, row in enumerate(body):
        for c, text in enumerate(row):
            table.setItem(r, c, QTableWidgetItem(text))


class ReportView(QWidget):
    run_selected = Signal(object)
    floorplan_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.pages = QStackedWidget()
        self.table = QTableWidget()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.compare_table = QTableWidget()
        self.compare_label = QLabel(COMPARE_HINT)
        self.compare_button = QPushButton("Compare with project...")
        self.floorplan_button = QPushButton("Floorplan")
        self._build()
        self._rows: list[dict[str, object]] = []
        self._infos: list[RunInfo] = []
        self._root: Path | None = None
        self._last: RunInfo | None = None
        self._plan: FloorplanPlan | None = None
        self.tree.currentItemChanged.connect(self._on_item)
        self.compare_button.clicked.connect(self._choose_compare)
        self.floorplan_button.clicked.connect(self._on_floorplan)

    def _build(self) -> None:
        compare = QWidget()
        cl = QVBoxLayout(compare)
        cl.addWidget(self.compare_button)
        cl.addWidget(self.compare_label)
        cl.addWidget(self.compare_table)
        for page in (self.table, self.log, compare):
            self.pages.addWidget(page)
        self._compare_page = compare
        right = QWidget()
        rl = QVBoxLayout(right)
        top = QHBoxLayout()
        top.addWidget(self.floorplan_button)
        top.addStretch(1)
        rl.addLayout(top)
        rl.addWidget(self.pages)
        split = QSplitter()
        split.addWidget(self.tree)
        split.addWidget(right)
        split.setStretchFactor(1, 3)
        outer = QVBoxLayout(self)
        outer.addWidget(split)
        self.floorplan_button.setEnabled(False)

    def _item(self, text: str, kind: str, arg: object = None) -> QTreeWidgetItem:
        item = QTreeWidgetItem([text])
        item.setData(0, ROLE_KIND, kind)
        item.setData(0, ROLE_ARG, arg)
        return item

    def _message_only(self, text: str) -> None:
        self.tree.clear()
        self.tree.addTopLevelItem(self._item(text, "message"))
        self._infos = []

    def set_project_dir(self, root: Path | None) -> None:
        self._root = root
        self._rows = []
        self._last = None
        self.tree.blockSignals(True)
        self.tree.clear()
        try:
            rows = runs.load_rows(root) if root is not None else None
        except sqlite3.Error as e:
            self._message_only(f"Cannot read wyrd.db: {e}")
        else:
            if rows is None:
                self._message_only(EMPTY_TEXT)
            else:
                self._rows = rows
                self._populate()
        self.tree.blockSignals(False)
        self.run_selected.emit(None)
        self._update_floorplan()

    def _populate(self) -> None:
        self._infos = runs.run_infos(self._rows)
        self.tree.addTopLevelItem(self._item("All runs", "all"))
        for n, info in enumerate(self._infos):
            node = self._item(info.label, "run", n)
            node.addChild(self._item("Summary", "summary", n))
            for step in runs.step_dirs(info.run_dir):
                snode = self._item(f"Step {step.n}: {step.name}", "step", n)
                for log in runs.log_files(step.path):
                    snode.addChild(self._item(log.name, "log", str(log)))
                node.addChild(snode)
            self.tree.addTopLevelItem(node)
        self.tree.addTopLevelItem(self._item("Compare", "compare"))

    def current_run(self) -> RunInfo | None:
        item = self.tree.currentItem()
        while item is not None:
            if item.data(0, ROLE_KIND) in ("run", "summary", "step"):
                return self._infos[int(item.data(0, ROLE_ARG))]
            if item.data(0, ROLE_KIND) == "log":
                item = item.parent()
                continue
            return None
        return None

    def _on_item(self, item: QTreeWidgetItem | None, _prev: QTreeWidgetItem | None) -> None:
        if item is not None:
            self._show_page(item)
        run = self.current_run()
        self._update_floorplan()
        if run != self._last:
            self._last = run
            self.run_selected.emit(run)

    def _show_page(self, item: QTreeWidgetItem) -> None:
        kind = item.data(0, ROLE_KIND)
        if kind == "all":
            _fill(self.table, report.table(self._rows))
            self.pages.setCurrentWidget(self.table)
        elif kind == "summary":
            info = self._infos[int(item.data(0, ROLE_ARG))]
            _fill(self.table, [["Item", "Value"], *map(list, runs.summary_rows(info.row))])
            self.pages.setCurrentWidget(self.table)
        elif kind == "log":
            self._show_log(Path(str(item.data(0, ROLE_ARG))))
        elif kind == "compare":
            self.pages.setCurrentWidget(self._compare_page)

    def _show_log(self, path: Path) -> None:
        try:
            self.log.setPlainText(read_limited(path))
        except (OSError, ValueError) as e:
            self.log.setPlainText(f"Cannot show {path}: {e}")
        self.pages.setCurrentWidget(self.log)

    def _update_floorplan(self) -> None:
        run = self.current_run()
        self._plan = None
        if run is None:
            self.floorplan_button.setEnabled(False)
            self.floorplan_button.setToolTip("Select a run to show its floorplan.")
            return
        plan = plan_floorplan(run.run_dir)
        if isinstance(plan, FloorplanPlan):
            self._plan = plan
            self.floorplan_button.setToolTip("Show the VPR floorplan of this run.")
        else:
            self.floorplan_button.setToolTip(plan)
        self.floorplan_button.setEnabled(self._plan is not None)

    def _on_floorplan(self) -> None:
        if self._plan is not None:
            self.floorplan_requested.emit(self._plan)

    def _choose_compare(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Compare with project")
        if chosen:
            self.compare_with(Path(chosen))

    def compare_with(self, other: Path) -> None:
        try:
            rows = runs.load_rows(other)
        except sqlite3.Error as e:
            self.compare_label.setText(f"Cannot read wyrd.db: {e}")
            return
        if rows is None:
            self.compare_label.setText(f"No wyrd.db in {other}")
            return
        _fill(self.compare_table, report.compare(self._rows, rows))
        self.compare_label.setText("\n".join(report.unmatched(self._rows, rows)))
