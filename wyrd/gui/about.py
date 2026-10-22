"""About dialog: version, licence and the citation table."""

from __future__ import annotations

from importlib import metadata

from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wyrd.citations import Citation, load

HEADERS = ["Name", "Kind", "Role", "Reference", "Link"]


def _version() -> str:
    try:
        return metadata.version("wyrd")
    except metadata.PackageNotFoundError:
        return "unknown"


def _reference(c: Citation) -> str:
    head = c.authors
    if c.year is not None:
        head = f"{head} ({c.year})" if head else f"({c.year})"
    return ". ".join(p for p in (head, c.title, c.venue) if p)


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Wyrd III")
        self.header = QLabel(f"Wyrd III {_version()}\nMIT licence")
        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        items = load()
        self.table.setRowCount(len(items))
        for r, c in enumerate(items):
            for col, text in enumerate([c.name, c.kind, c.role, _reference(c), c.url]):
                self.table.setItem(r, col, QTableWidgetItem(text))
        layout = QVBoxLayout(self)
        layout.addWidget(self.header)
        layout.addWidget(self.table)
        self.resize(900, 500)
