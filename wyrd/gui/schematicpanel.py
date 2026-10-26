"""The Schematic panel: draws a module or a fan-in cone of a netlist with netlistsvg (optional)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from wyrd import schematic
from wyrd.schematic import Netlist, SchematicError, Tools

NO_NETLIST = (
    "No netlist loaded. Open a Yosys-schema JSON file (odin3 write_json, after proc) or "
    "select a run that has one."
)
WHOLE = "(whole module)"
CONE_HINT = "net name, or file.v:LINE"


class SchematicPanel(QWidget):
    """Read-only schematic view; never raises on bad input, shows the reason in `status`."""

    def __init__(self, tools: Tools | None = None, auto_tools: bool = True) -> None:
        super().__init__()
        self._tools = schematic.find_tools() if auto_tools and tools is None else tools
        self._netlist: Netlist | None = None
        self._work = tempfile.TemporaryDirectory(prefix="wyrd-schem-")
        self.destroyed.connect(self._work.cleanup)
        self.status = QLabel(NO_NETLIST)
        self.status.setWordWrap(True)
        self.module = QComboBox()
        self.target = QLineEdit()
        self.target.setPlaceholderText(CONE_HINT)
        self.max_cells = QSpinBox()
        self.max_cells.setRange(1, 5000)
        self.max_cells.setValue(schematic.DEFAULT_MAX_CELLS)
        self.max_cells.setPrefix("max cells ")
        self.open_button = QPushButton("Open netlist...")
        self.draw_button = QPushButton("Draw")
        self.svg = QSvgWidget()
        self._build()
        self.open_button.clicked.connect(self._choose)
        self.draw_button.clicked.connect(self.draw)
        self.draw_button.setEnabled(False)
        if self._tools is None:
            self.status.setText(f"{NO_NETLIST}\n{schematic.INSTALL_HINT}")

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        for w in (self.open_button, QLabel("Module"), self.module, QLabel("Cone of"), self.target):
            row.addWidget(w)
        row.addWidget(self.max_cells)
        row.addWidget(self.draw_button)
        layout.addLayout(row)
        scroll = QScrollArea()
        scroll.setWidget(self.svg)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(scroll, 1)

    def has_tools(self) -> bool:
        return self._tools is not None

    def set_run(self, run_dir: Path | None) -> None:
        """Load the netlist of a run if it has one; otherwise clear (never raises)."""
        found = None if run_dir is None else schematic.find_netlist(run_dir)
        if found is None:
            self._clear(NO_NETLIST)
        else:
            self.load(found)

    def _clear(self, message: str) -> None:
        self._netlist = None
        self.module.clear()
        self.draw_button.setEnabled(False)
        self.status.setText(message)

    def _choose(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Open netlist", "", "JSON (*.json)")
        if name:
            self.load(Path(name))

    def load(self, path: Path) -> None:
        """Load a netlist file and fill the module list; the top module is selected."""
        try:
            netlist = schematic.load_netlist(path)
        except SchematicError as e:
            self._clear(str(e))
            return
        self._netlist = netlist
        self.module.clear()
        for m in schematic.modules(netlist):
            self.module.addItem(f"{m.name} ({m.cells} cells)", m.name)
        self.draw_button.setEnabled(True)
        self.status.setText(f"{path.name}: {self.module.count()} modules. Press Draw.")

    def _view(self, netlist: Netlist, name: str) -> tuple[Netlist, str]:
        text = self.target.text().strip()
        limit = self.max_cells.value()
        if not text:
            return schematic.module_view(netlist, name, limit), ""
        mod = schematic.modules_dict(netlist)[name]
        file, _, line = text.rpartition(":")
        if file and line.isdigit():
            seeds = schematic.seeds_of_line(mod, file, int(line))
        else:
            seeds = schematic.seeds_of_net(mod, text)
        view, cut = schematic.cone_view(netlist, name, seeds, limit)
        return view, f" (cone cut at {limit} cells)" if cut else " (cone)"

    def draw(self) -> bool:
        """Draw the selected module or cone; the reason is shown in `status` when it fails."""
        name = self.module.currentData()
        if self._netlist is None or not isinstance(name, str):
            return False
        try:
            view, note = self._view(self._netlist, name)
            out = Path(self._work.name) / "view.svg"
            schematic.render(view, out, self._tools, Path(self._work.name))
            self.svg.load(QByteArray(out.read_bytes()))
        except SchematicError as e:
            self.status.setText(str(e))
            return False
        size = self.svg.renderer().defaultSize()
        self.svg.setFixedSize(size)
        self.status.setText(f"{name}{note}: {schematic.count_cells(view)} cells drawn.")
        return True
