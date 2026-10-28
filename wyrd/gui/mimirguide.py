"""Help > Wyrd guide: every panel, then the walk-through from a Mímir store to a coloured file."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QTextBrowser, QVBoxLayout, QWidget

from wyrd.guimodel import panelhelp


class MimirGuideDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(panelhelp.GUIDE_MENU_TITLE)
        self.resize(760, 680)
        self.browser = QTextBrowser()
        self.browser.setMarkdown(panelhelp.GUIDE)
        lay = QVBoxLayout(self)
        lay.addWidget(self.browser)
