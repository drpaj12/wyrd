"""Shared Qt test helpers: one QApplication for the process and prompt widget disposal.

Import only when PySide6 is installed. A widget left alive to interpreter exit is deleted by
PySide during finalization, in no fixed order; tests dispose of their widgets instead.
"""

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QWidget

_APP: QCoreApplication | None = None


def qapp() -> QCoreApplication:
    """The process QApplication, made on first use and kept referenced for the whole run."""
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


def dispose(widget: QWidget) -> None:
    """Close the widget and delete it now (with its children), not at interpreter exit."""
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    QCoreApplication.processEvents()
