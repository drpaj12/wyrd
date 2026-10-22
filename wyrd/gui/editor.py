"""The wyrd.toml editor tab with live validation."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from wyrd.guimodel.tomledit import Validation, validate_text

DEBOUNCE_MS = 400


class _StatusLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, ev: QMouseEvent) -> None:
        self.clicked.emit()
        super().mousePressEvent(ev)


class TomlEditor(QWidget):
    saved = Signal()

    def __init__(self, silent: bool = False) -> None:
        super().__init__()
        self.silent = silent
        self.path: Path | None = None
        self._saved_text = ""
        self._error_line: int | None = None
        self.text = QPlainTextEdit()
        self.text.setFont(QFont("monospace"))
        self.status = _StatusLabel("")
        self.save_button = QPushButton("Save")
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text)
        layout.addWidget(self.status)
        layout.addWidget(self.save_button)
        self._timer.timeout.connect(self.validate_now)
        self.text.textChanged.connect(self._timer.start)
        self.status.clicked.connect(self._goto_error)
        self.save_button.clicked.connect(self.save)

    def load(self, path: Path) -> None:
        self.path = path
        try:
            content = path.read_text(encoding="utf-8")
            note = ""
        except (OSError, UnicodeDecodeError) as e:
            content, note = "", f"Cannot read {path}: {e}"
        self._saved_text = content
        self.text.setPlainText(content)
        self._timer.stop()
        if note:
            self.status.setText(note)
        else:
            self.validate_now()

    def set_text(self, content: str) -> None:
        self.text.setPlainText(content)

    def is_modified(self) -> bool:
        return self.text.toPlainText() != self._saved_text

    def validate_now(self) -> Validation:
        self._timer.stop()
        path = self.path or Path("wyrd.toml")
        result = validate_text(path, self.text.toPlainText())
        self._show(result)
        return result

    def _show(self, result: Validation) -> None:
        diag = result.diagnostic
        if result.ok or diag is None:
            self._error_line = None
            self.status.setText(f"Valid: {result.runs} runs")
            self.status.setStyleSheet("color: #1a7f37")
            self.text.setExtraSelections([])
            return
        self._error_line = diag.line
        where = f"line {diag.line}: " if diag.line is not None else ""
        self.status.setText(where + diag.message)
        self.status.setStyleSheet("color: #b00020")
        self.text.setExtraSelections(self._selections(diag.line))

    def _selections(self, line: int | None) -> list[QTextEdit.ExtraSelection]:
        if line is None:
            return []
        block = self.text.document().findBlockByNumber(line - 1)
        if not block.isValid():
            return []
        sel = QTextEdit.ExtraSelection()
        sel.cursor = QTextCursor(block)
        sel.format.setBackground(QColor("#ffd6d6"))
        sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        return [sel]

    def _goto_error(self) -> None:
        if self._error_line is None:
            return
        block = self.text.document().findBlockByNumber(self._error_line - 1)
        if block.isValid():
            self.text.setTextCursor(QTextCursor(block))
            self.text.setFocus()

    def save(self) -> bool:
        if self.path is None:
            return False
        if not self.validate_now().ok and not self.silent:
            answer = QMessageBox.question(
                self, "Save wyrd.toml", "The file does not validate. Save anyway?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        content = self.text.toPlainText()
        try:
            self.path.write_text(content, encoding="utf-8")
        except OSError as e:
            self.status.setText(f"Cannot write {self.path}: {e.strerror or e}")
            return False
        self._saved_text = content
        self.saved.emit()
        return True
