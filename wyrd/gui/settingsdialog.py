"""Machine settings dialog generated from ``machine.FIELDS``."""

from __future__ import annotations

import tomllib
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from wyrd.guimodel import machine
from wyrd.guimodel.machine import Field, MachineValues

TABLES = ("tools", "resources", "defaults")
SPIN_MAX = 1_000_000


def _int_of(text: str) -> int:
    try:
        return max(0, min(int(text), SPIN_MAX))
    except ValueError:
        return 0


def _make_editor(f: Field, text: str) -> QWidget:
    if f.kind == "int":
        spin = QSpinBox()
        spin.setRange(0, SPIN_MAX)
        spin.setValue(_int_of(text))
        return spin
    if f.kind == "choice":
        combo = QComboBox()
        combo.addItems(list(f.choices))
        combo.setCurrentText(text)
        return combo
    return QLineEdit(text)


def _read_editor(w: QWidget) -> str:
    if isinstance(w, QSpinBox):
        return str(w.value())
    if isinstance(w, QComboBox):
        return w.currentText()
    assert isinstance(w, QLineEdit)
    return w.text().strip()


class SettingsDialog(QDialog):
    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.path = path
        self.editors: dict[str, QWidget] = {}
        self.error_label = QLabel("")
        current, note = self._start_values(path)
        self._extra = current.extra_tools
        col = QVBoxLayout(self)
        col.addWidget(QLabel(str(path)))
        for table in TABLES:
            col.addWidget(self._group(table, current))
        col.addWidget(self.error_label)
        self.error_label.setText(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        col.addWidget(buttons)

    @staticmethod
    def _start_values(path: Path) -> tuple[MachineValues, str]:
        try:
            return machine.read_values(path), ""
        except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as e:
            return machine.read_values(Path("/nonexistent/machine.toml")), f"{path}: {e}"

    def _group(self, table: str, current: MachineValues) -> QGroupBox:
        box = QGroupBox(table)
        form = QFormLayout(box)
        for f in (x for x in machine.FIELDS if x.table == table):
            editor = _make_editor(f, current.values.get(f.name, ""))
            self.editors[f.name] = editor
            form.addRow(f.key, editor)
        return box

    def values(self) -> MachineValues:
        return MachineValues(
            {name: _read_editor(w) for name, w in self.editors.items()}, dict(self._extra)
        )

    def accept(self) -> None:
        try:
            machine.save(self.path, self.values())
        except (ValueError, OSError) as e:
            self.error_label.setText(str(e))
            return
        super().accept()
