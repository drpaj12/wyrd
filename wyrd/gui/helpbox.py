"""A collapsible plain-English header for a Mímir tab (text in ``wyrd.guimodel.mimirhelp``)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QToolButton, QVBoxLayout, QWidget

from wyrd.guimodel import mimirhelp


class HelpBox(QWidget):
    """Four short headed paragraphs: what this shows, why use it, what you see, how to read it."""

    def __init__(self, tab: str) -> None:
        super().__init__()
        self.tab = tab
        self.toggle = QToolButton()
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.toggle.setToolTip("Show or hide the explanation of this tab")
        self.body = QLabel(self._html(tab))
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.toggle)
        lay.addWidget(self.body)
        self.toggle.toggled.connect(self._toggled)
        self._toggled(True)

    @staticmethod
    def _html(tab: str) -> str:
        rows = zip(mimirhelp.SECTIONS, mimirhelp.TABS[tab], strict=True)
        return "".join(f"<p style='margin:2px 0'><b>{h}.</b> {t}</p>" for h, t in rows)

    def _toggled(self, shown: bool) -> None:
        self.body.setVisible(shown)
        self.toggle.setText(("\u25be " if shown else "\u25b8 ") + f"About the {self.tab} tab")
