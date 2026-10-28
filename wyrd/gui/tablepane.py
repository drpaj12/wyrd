"""A table with Copy and Export CSV, shared by the Mímir dock tabs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtGui import QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wyrd import mimirview
from wyrd.mimirview import Table

CONF_COLOURS = {
    "given": "#c9ecc9",
    "default": "#e2e2e2",
    "default-unrecorded": "#ffe2a8",
    "unknown": "#ffb8b8",
}
MORE_NOTE = " (cut at the row limit: filter by level to narrow; Export CSV writes all rows)"


class TablePane(QWidget):
    """A table with Copy and Export CSV."""

    def __init__(self, conf_column: str = "") -> None:
        super().__init__()
        self.table_data = Table("", (), [])
        self.full_query: Callable[[], Table] | None = None  # the same query without the row cap
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
        flag = t.columns.index("mixed") if "mixed" in t.columns else -1
        for i, r in enumerate(t.rows):
            colour = CONF_COLOURS.get(str(r[conf])) if conf >= 0 else None
            if flag >= 0 and r[flag] == "MIXED":
                colour = CONF_COLOURS["default-unrecorded"]
            for j, c in enumerate(r):
                item = QTableWidgetItem(mimirview.cell_text(c))
                if colour:
                    item.setBackground(QBrush(QColor(colour)))
                self.grid.setItem(i, j, item)
        self.grid.resizeColumnsToContents()
        self.note.setText(f"{len(t.rows)} rows" + (MORE_NOTE if t.more else ""))

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(mimirview.render_tsv(self.table_data))

    def export_csv(self, path: Path) -> None:
        """Write the table; a table cut by the row cap is re-queried without the cap."""
        t = self.table_data
        if t.more and self.full_query is not None:
            t = self.full_query()
        path.write_text(mimirview.render_csv(t), encoding="utf-8")

    def export_dialog(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV (*.csv)")
        if name:
            self.export_csv(Path(name))
