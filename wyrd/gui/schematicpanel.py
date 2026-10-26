"""The Schematic panel: draws a module or a fan-in cone of a netlist with netlistsvg (optional)."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QRunnable, Qt, QThreadPool, Signal
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
from wyrd.schematic import Netlist, Tools

NO_NETLIST = (
    "No netlist loaded. Open a Yosys-schema JSON file (odin3 write_json, after proc) or "
    "select a run that has one."
)
WHOLE = "(whole module)"
CONE_HINT = "net name, or file.v:LINE"


@dataclass(frozen=True)
class DrawJob:
    """Everything a draw needs, copied from the widgets so the worker never touches them."""

    netlist: Netlist
    module: str
    target: str
    limit: int
    tools: Tools | None
    work_dir: Path
    svg_name: str


def build_view(job: DrawJob) -> tuple[Netlist, str]:
    """The netlist part to draw and a note for the status line (raises SchematicError)."""
    text = job.target
    if not text:
        return schematic.module_view(job.netlist, job.module, job.limit), ""
    mod = schematic.modules_dict(job.netlist)[job.module]
    file, _, line = text.rpartition(":")
    if file and line.isdigit():
        seeds = schematic.seeds_of_line(mod, file, int(line))
    else:
        seeds = schematic.seeds_of_net(mod, text)
    view, cut = schematic.cone_view(job.netlist, job.module, seeds, job.limit)
    return view, f" (cone cut at {job.limit} cells)" if cut else " (cone)"


class _Signals(QObject):
    loaded = Signal(int, object, object)  # token, path (or None: no netlist), netlist
    drawn = Signal(int, object, str, int)  # token, svg bytes, status text, cells drawn
    failed = Signal(int, str)  # token, reason


class _LoadTask(QRunnable):
    """Find (for a run directory) and parse a netlist off the GUI thread."""

    def __init__(self, token: int, source: Path, is_run: bool, signals: _Signals) -> None:
        super().__init__()
        self.token, self.source, self.is_run, self.signals = token, source, is_run, signals

    def run(self) -> None:
        try:
            path = schematic.find_netlist(self.source) if self.is_run else self.source
            netlist = None if path is None else schematic.load_netlist(path)
        except Exception as e:  # any failure must reach the panel, or it stays busy forever
            self.signals.failed.emit(self.token, str(e))
        else:
            self.signals.loaded.emit(self.token, path, netlist)


class _DrawTask(QRunnable):
    """Cut the view, run netlistsvg and read the SVG off the GUI thread."""

    def __init__(self, token: int, job: DrawJob, signals: _Signals) -> None:
        super().__init__()
        self.token, self.job, self.signals = token, job, signals

    def run(self) -> None:
        job = self.job
        try:
            view, note = build_view(job)
            out = job.work_dir / job.svg_name
            schematic.render(view, out, job.tools, job.work_dir)
            data = out.read_bytes()
        except Exception as e:  # any failure must reach the panel, or it stays busy forever
            self.signals.failed.emit(self.token, str(e))
        else:
            cells = schematic.count_cells(view)
            text = f"{job.module}{note}: {cells} cells drawn."
            self.signals.drawn.emit(self.token, data, text, cells)




class SchematicPanel(QWidget):
    """Read-only schematic view; never raises on bad input, shows the reason in `status`.

    Finding and parsing the netlist and drawing run on a worker thread (QRunnable on a private
    QThreadPool, as simpanel.py); Draw is disabled while it runs and a token drops stale
    results.
    """

    finished = Signal(bool)  # a load or a draw ended: True when it succeeded

    def __init__(self, tools: Tools | None = None, auto_tools: bool = True) -> None:
        super().__init__()
        self._tools = schematic.find_tools() if auto_tools and tools is None else tools
        self._netlist: Netlist | None = None
        self._work = tempfile.TemporaryDirectory(prefix="wyrd-schem-")
        self.destroyed.connect(self._work.cleanup)
        self._token = 0
        self._busy = False
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _Signals(self)
        self._signals.loaded.connect(self._on_loaded)
        self._signals.drawn.connect(self._on_drawn)
        self._signals.failed.connect(self._on_failed)
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

    def is_busy(self) -> bool:
        """A load or a draw is running on the worker."""
        return self._busy

    def _start(self, message: str) -> int:
        """Begin background work: a new token makes every earlier result stale."""
        self._token += 1
        self._busy = True
        self.draw_button.setEnabled(False)
        self.status.setText(message)
        return self._token

    def _end(self) -> None:
        self._busy = False
        self.draw_button.setEnabled(self._netlist is not None)

    def set_run(self, run_dir: Path | None) -> None:
        """Look for the netlist of a run in the background; clear when there is none."""
        if run_dir is None:
            self._token += 1
            self._busy = False
            self._clear(NO_NETLIST)
            return
        self._netlist = None
        token = self._start("Looking for a netlist...")
        self._pool.start(_LoadTask(token, run_dir, True, self._signals))

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
        """Load a netlist file in the background; `finished` says when the module list is ready."""
        self._netlist = None
        token = self._start(f"Loading {path.name}...")
        self._pool.start(_LoadTask(token, path, False, self._signals))

    def _on_loaded(self, token: int, path: object, netlist: object) -> None:
        if token != self._token:
            return
        if not isinstance(path, Path) or not isinstance(netlist, dict):
            self._end()
            self._clear(NO_NETLIST)
            self.finished.emit(False)
            return
        self._netlist = netlist
        self.module.clear()
        for m in schematic.modules(netlist):
            self.module.addItem(f"{m.name} ({m.cells} cells)", m.name)
        self._end()
        self.status.setText(f"{path.name}: {self.module.count()} modules. Press Draw.")
        self.finished.emit(True)

    def _on_failed(self, token: int, reason: str) -> None:
        if token != self._token:
            return
        self._end()
        if self._netlist is None:
            self._clear(reason)
        else:
            self.status.setText(reason)
        self.finished.emit(False)

    def _on_drawn(self, token: int, data: object, text: str, cells: int) -> None:
        if token != self._token:
            return
        self._end()
        if not isinstance(data, bytes):
            return
        self.svg.load(QByteArray(data))
        if not self.svg.renderer().isValid():
            self.status.setText("netlistsvg wrote a drawing that cannot be displayed")
            self.finished.emit(False)
            return
        self.svg.setFixedSize(self.svg.renderer().defaultSize())
        self.status.setText(text)
        self.finished.emit(True)

    def draw(self) -> bool:
        """Start drawing the selected module or cone; True when started (the result comes by
        `finished`, a failure reason in `status`)."""
        name = self.module.currentData()
        if self._busy or self._netlist is None or not isinstance(name, str):
            return False
        if self._tools is None:
            self.status.setText(schematic.INSTALL_HINT)
            return False
        token = self._start(f"Drawing {name}...")
        job = DrawJob(
            self._netlist,
            name,
            self.target.text().strip(),
            self.max_cells.value(),
            self._tools,
            Path(self._work.name),
            f"view-{token}.svg",
        )
        self._pool.start(_DrawTask(token, job, self._signals))
        return True
