"""Help > Mímir guide: the walk-through from a store to a coloured source file."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QTextBrowser, QVBoxLayout, QWidget

from wyrd.guimodel import mimirhelp


class MimirGuideDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(mimirhelp.HELP_MENU_TITLE)
        self.resize(720, 640)
        self.browser = QTextBrowser()
        self.browser.setMarkdown(mimirhelp.GUIDE)
        lay = QVBoxLayout(self)
        lay.addWidget(self.browser)
