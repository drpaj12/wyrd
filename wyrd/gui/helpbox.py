"""A collapsible plain-English header for a panel or Mímir tab.

Text: ``wyrd.guimodel.panelhelp`` (panels) and ``wyrd.guimodel.mimirhelp`` (Mímir tabs). The
collapsed state of each header is kept in the ``QSettings`` passed to the constructor (none:
not remembered). A header starts expanded the first time and then keeps what the user chose.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from wyrd.guimodel import mimirhelp, panelhelp


class HelpBox(QWidget):
    """Four short headed paragraphs: what this shows, why use it, what you see, how to read it."""

    def __init__(self, tab: str, panel: bool = False, settings: QSettings | None = None) -> None:
        super().__init__()
        self.settings = settings
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
        self.label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.body = self.label
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self.toggle)
        lay.addWidget(self.label)
        self.toggle.toggled.connect(self._toggled)
        self._apply(self._stored())

    @staticmethod
    def _html(tab: str, panel: bool) -> str:
        if panel:
            return panelhelp.panel_html(tab)
        rows = zip(mimirhelp.SECTIONS, mimirhelp.TABS[tab], strict=True)
        return "".join(f"<p style='margin:2px 0'><b>{h}.</b> {t}</p>" for h, t in rows)

    def _stored(self) -> bool:
        if self.settings is None:
            return True
        return str(self.settings.value(self.key, "true")).lower() != "false"

    def is_shown(self) -> bool:
        return self.toggle.isChecked()

    def set_shown(self, shown: bool) -> None:
        """Show or hide the text; the choice is remembered."""
        self._apply(shown)
        if self.settings is not None:
            self.settings.setValue(self.key, "true" if shown else "false")

    def _apply(self, shown: bool) -> None:
        self.toggle.blockSignals(True)
        self.toggle.setChecked(shown)
        self.toggle.blockSignals(False)
        self._show(shown)

    def _toggled(self, shown: bool) -> None:
        self._show(shown)
        if self.settings is not None:
            self.settings.setValue(self.key, "true" if shown else "false")

    def _show(self, shown: bool) -> None:
        self.label.setVisible(shown)
        word = "panel" if self.panel else "tab"
        self.toggle.setText(("▾ " if shown else "▸ ") + f"About the {self.tab} {word}")
        self.updateGeometry()
