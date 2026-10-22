"""Add design dialog: name, files, top and sweep membership."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from wyrd.guimodel.tomledit import relative_files


class AddDesignDialog(QDialog):
    def __init__(self, root: Path, existing: set[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add design")
        self.root = root
        self.existing = existing
        self.name_edit = QLineEdit()
        self.files_list = QListWidget()
        self.top_edit = QLineEdit()
        self.sweep_box = QCheckBox("Add to [sweep] design")
        self.sweep_box.setChecked(True)
        self.error_label = QLabel("")
        add_files = QPushButton("Add files...")
        add_files.clicked.connect(self._pick_files)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("Files", self.files_list)
        form.addRow("", add_files)
        form.addRow("Top", self.top_edit)
        col = QVBoxLayout(self)
        col.addLayout(form)
        col.addWidget(self.sweep_box)
        col.addWidget(self.error_label)
        col.addWidget(buttons)

    def _pick_files(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileNames(
            self, "Design files", str(self.root), "Verilog (*.v *.sv *.vh *.svh);;All files (*)"
        )
        for rel in relative_files(self.root, [Path(c) for c in chosen]):
            self.files_list.addItem(rel)

    def _files(self) -> list[str]:
        out: list[str] = []
        for i in range(self.files_list.count()):
            item = self.files_list.item(i)
            if item is not None:
                out.append(item.text())
        return out

    def _problem(self) -> str:
        name = self.name_edit.text().strip()
        if not name:
            return "Name is required."
        if name in self.existing:
            return f"A design named '{name}' already exists."
        if not self._files():
            return "Add at least one file."
        return ""

    def accept(self) -> None:
        problem = self._problem()
        self.error_label.setText(problem)
        if not problem:
            super().accept()

    def result_values(self) -> tuple[str, list[str], str | None, bool]:
        top = self.top_edit.text().strip()
        return self.name_edit.text().strip(), self._files(), top or None, self.sweep_box.isChecked()
