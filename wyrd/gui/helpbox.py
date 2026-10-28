"""A collapsible plain-English header for a panel or Mímir tab.

Text: ``wyrd.guimodel.panelhelp`` (panels) and ``wyrd.guimodel.mimirhelp`` (Mímir tabs). The
collapsed state of each header is kept in ``HelpBox.settings`` (set by the main window).
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QLabel, QScrollArea, QToolButton, QVBoxLayout, QWidget

from wyrd.guimodel import mimirhelp, panelhelp

BODY_MAX_HEIGHT = 150


class HelpBox(QWidget):
    """Four short headed paragraphs: what this shows, why use it, what you see, how to read it."""

    settings: QSettings | None = None

    def __init__(self, tab: str, panel: bool = False) -> None:
        super().__init__()
        self.tab = tab
        self.panel = panel
        self.key = ("about/panel/" if panel else "about/tab/") + tab
        self.toggle = QToolButton()
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        kind = "panel" if panel else "tab"
        self.toggle.setToolTip(f"Show or hide the explanation of this {kind}")
        self.label = QLabel(self._html(tab, panel))
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.body = QScrollArea()
        self.body.setWidgetResizable(True)
        self.body.setFrameShape(QScrollArea.Shape.NoFrame)
        self.body.setMaximumHeight(BODY_MAX_HEIGHT)
        self.body.setWidget(self.label)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.toggle)
        lay.addWidget(self.body)
        self.toggle.toggled.connect(self._toggled)
        self.set_shown(self._stored())

    @staticmethod
    def _html(tab: str, panel: bool) -> str:
        if panel:
            return panelhelp.panel_html(tab)
        rows = zip(mimirhelp.SECTIONS, mimirhelp.TABS[tab], strict=True)
        return "".join(f"<p style='margin:2px 0'><b>{h}.</b> {t}</p>" for h, t in rows)

    def _stored(self) -> bool:
        if HelpBox.settings is None:
            return True
        return str(HelpBox.settings.value(self.key, "true")).lower() != "false"

    def is_shown(self) -> bool:
        return self.toggle.isChecked()

    def set_shown(self, shown: bool) -> None:
        self.toggle.setChecked(shown)
        self._toggled(shown)

    def _toggled(self, shown: bool) -> None:
        self.body.setVisible(shown)
        word = "panel" if self.panel else "tab"
        self.toggle.setText(("▾ " if shown else "▸ ") + f"About the {self.tab} {word}")
        if HelpBox.settings is not None:
            HelpBox.settings.setValue(self.key, "true" if shown else "false")
