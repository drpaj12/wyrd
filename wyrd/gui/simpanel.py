"""The Simulate tab: compile a design, step it, run vectors, look at waveforms (spec 11)."""

from __future__ import annotations

import itertools
import os
import shutil
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    QProcess,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from wyrd.bifrost import (
    Backend,
    BifrostSession,
    CompileError,
    Diagnostic,
    SimError,
    SimUnavailable,
    VectorError,
    VectorFile,
    default_backend,
    format_vectors,
    parse_vectors,
    session_ports,
    write_vcd,
)
from wyrd.bifrost import (
    Signal as SimSignal,
)
from wyrd.bifrost.vectors import data_ports, random_rows
from wyrd.gui.waveformview import WaveformView
from wyrd.guimodel.waveform import (
    format_value,
    parse_int_text,
    rows_from_recording,
    view_start,
)
from wyrd.project import Project

SIGNAL_HEADERS = ["Name", "Width", "Kind", "Value"]
DIAG_HEADERS = ["Severity", "Message", "Location"]
SPEEDS = ["1", "10", "100", "1000"]
TICK_MS = 50
TICKS_PER_SECOND = 1000 // TICK_MS
GTKWAVE_MISSING = "gtkwave not found; install it (for example: sudo apt install gtkwave)"
BAD_CELL = QColor(255, 200, 200)
CHUNK = 1000
MIN_RECORDING = 1_000_000
# A launcher returns None when the program started, else the reason it did not.
Launcher = Callable[[str, list[str]], str | None]


def _start_detached(program: str, args: list[str]) -> str | None:
    process = QProcess()
    process.setProgram(program)
    process.setArguments(args)
    if process.startDetached():
        return None
    return process.errorString() or "unknown error"


@dataclass
class _Job:
    """A long run, advanced CHUNK units per timer tick so the window stays responsive."""

    label: str
    total: int
    advance: Callable[[int], None]
    finish: Callable[[bool], None]
    done: int = 0


class _CompileSignals(QObject):
    done = Signal(int, object)
    failed = Signal(int, object)


class _CompileTask(QRunnable):
    def __init__(
        self,
        generation: int,
        files: list[Path],
        top: str | None,
        backend: Backend,
        signals: _CompileSignals,
    ) -> None:
        super().__init__()
        self.generation = generation
        self.files = files
        self.top = top
        self.backend = backend
        self.signals = signals

    def run(self) -> None:
        try:
            session = BifrostSession.from_verilog(self.files, top=self.top, backend=self.backend)
        except (SimError, ValueError, OSError) as e:
            self.signals.failed.emit(self.generation, e)
        else:
            self.signals.done.emit(self.generation, session)


def _spin(low: int, high: int, value: int) -> QSpinBox:
    box = QSpinBox()
    box.setRange(low, high)
    box.setValue(value)
    return box


class SimPanel(QWidget):
    location_activated = Signal(Path, int)

    def __init__(self, backend: Backend | None = None, launcher: Launcher | None = None) -> None:
        super().__init__()
        self.session: BifrostSession | None = None
        self.project: Project | None = None
        self.project_dir: Path | None = None
        self.launcher: Launcher = launcher if launcher is not None else _start_detached
        self._backend: Backend | None = backend
        self._available = True
        self._refreshing = False
        self._diag_targets: list[tuple[Path, int] | None] = []
        self._rows: list[SimSignal] = []
        self._record_names: list[str] | None = None
        self._last: tuple[VectorFile, int] | None = None
        self._job: _Job | None = None
        self._compiling = False
        self._compile_gen = 0
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._compile_signals = _CompileSignals(self)
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._job_timer = QTimer(self)
        self._job_timer.setInterval(0)
        self._build()
        self._wire()
        self._init_backend()
        self._update_enabled()

    # construction

    def _build(self) -> None:
        self.design_combo = QComboBox()
        self.top_edit = QLineEdit()
        self.top_edit.setPlaceholderText("top module (optional)")
        self.compile_button = QPushButton("Compile")
        self.status_label = QLabel("")
        self.progress_label = QLabel("")
        self.stop_button = QPushButton("Stop")
        self.step_button = QPushButton("Step")
        self.step_n_button = QPushButton("Step N")
        self.step_n_box = _spin(1, 100000, 10)
        self.run_button = QPushButton("Run")
        self.run_button.setCheckable(True)
        self.speed_box = QComboBox()
        self.speed_box.addItems(SPEEDS)
        self.speed_box.setCurrentText("10")
        self.reset_button = QPushButton("Reset")
        self.record_box = QCheckBox("Record")
        self.record_box.setChecked(True)
        self.internal_box = QCheckBox("Show internal signals")
        self.random_cycles = _spin(0, 1_000_000, 100)
        self.seed_box = _spin(0, 2**31 - 1, 0)
        self.run_random_button = QPushButton("Run random")
        self.run_vectors_button = QPushButton("Run vectors")
        self.radix_box = QComboBox()
        self.radix_box.addItems(["hex", "dec", "bin"])
        self.save_vcd_button = QPushButton("Save VCD...")
        self.save_vectors_button = QPushButton("Save vectors...")
        self.gtkwave_button = QPushButton("Open in GTKWave")
        self.signals_table = QTableWidget(0, len(SIGNAL_HEADERS))
        self.signals_table.setHorizontalHeaderLabels(SIGNAL_HEADERS)
        self.diagnostics_table = QTableWidget(0, len(DIAG_HEADERS))
        self.diagnostics_table.setHorizontalHeaderLabels(DIAG_HEADERS)
        self.diagnostics_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.vectors_edit = QPlainTextEdit()
        self.vectors_open = QPushButton("Open...")
        self.vectors_save = QPushButton("Save...")
        self.vectors_template = QPushButton("Generate template")
        self.waveform = WaveformView()
        self.view_tabs = QTabWidget()
        self._layout()

    def _row(self, *items: QWidget | str) -> QHBoxLayout:
        row = QHBoxLayout()
        for item in items:
            row.addWidget(QLabel(item) if isinstance(item, str) else item)
        row.addStretch(1)
        return row

    def _layout(self) -> None:
        scroll = QScrollArea()
        scroll.setWidget(self.waveform)
        scroll.setWidgetResizable(False)
        vectors = QWidget()
        vlay = QVBoxLayout(vectors)
        vlay.addLayout(self._row(self.vectors_open, self.vectors_save, self.vectors_template))
        vlay.addWidget(self.vectors_edit)
        self.view_tabs.addTab(scroll, "Waveform")
        self.view_tabs.addTab(vectors, "Vectors")
        self.view_tabs.addTab(self.diagnostics_table, "Diagnostics")
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.signals_table)
        split.addWidget(self.view_tabs)
        split.setStretchFactor(1, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(
            self._row("Design", self.design_combo, "Top", self.top_edit, self.compile_button)
        )
        layout.addWidget(self.status_label)
        layout.addLayout(self._row(self.progress_label, self.stop_button))
        layout.addWidget(split, 1)
        layout.addLayout(
            self._row(
                self.step_button,
                self.step_n_button,
                self.step_n_box,
                self.run_button,
                "speed",
                self.speed_box,
                self.reset_button,
                self.record_box,
                self.internal_box,
            )
        )
        layout.addLayout(
            self._row(
                "Random: cycles",
                self.random_cycles,
                "seed",
                self.seed_box,
                self.run_random_button,
                self.run_vectors_button,
            )
        )
        layout.addLayout(
            self._row(
                "Radix",
                self.radix_box,
                self.save_vcd_button,
                self.save_vectors_button,
                self.gtkwave_button,
            )
        )

    def _wire(self) -> None:
        self.compile_button.clicked.connect(self.compile)
        self.step_button.clicked.connect(lambda: self._step(1))
        self.step_n_button.clicked.connect(self._step_n)
        self.run_button.toggled.connect(self._run_toggled)
        self._timer.timeout.connect(self._tick)
        self._job_timer.timeout.connect(self._job_tick)
        self.stop_button.clicked.connect(self.stop_job)
        self._compile_signals.done.connect(self._compile_done)
        self._compile_signals.failed.connect(self._compile_failed)
        self.reset_button.clicked.connect(self._reset)
        self.run_random_button.clicked.connect(self._run_random)
        self.run_vectors_button.clicked.connect(self._run_vectors)
        self.radix_box.currentTextChanged.connect(self._radix_changed)
        self.internal_box.toggled.connect(self._fill_table)
        self.save_vcd_button.clicked.connect(self._save_vcd_dialog)
        self.save_vectors_button.clicked.connect(self._save_vectors_dialog)
        self.gtkwave_button.clicked.connect(self._open_gtkwave)
        self.vectors_open.clicked.connect(self._open_vectors)
        self.vectors_save.clicked.connect(self._save_vectors_text)
        self.vectors_template.clicked.connect(self._template)
        self.signals_table.itemChanged.connect(self._item_changed)
        self.diagnostics_table.cellDoubleClicked.connect(self._diag_activated)
        self.waveform.cursor_changed.connect(self._cursor_changed)

    def _init_backend(self) -> None:
        if self._backend is not None:
            return
        try:
            self._backend = default_backend()
        except SimUnavailable as e:
            self._available = False
            self.status_label.setText(str(e))

    def _session_controls(self) -> list[QWidget]:
        return [
            self.step_button,
            self.step_n_button,
            self.step_n_box,
            self.run_button,
            self.speed_box,
            self.reset_button,
            self.random_cycles,
            self.seed_box,
            self.run_random_button,
            self.run_vectors_button,
            self.save_vcd_button,
            self.save_vectors_button,
            self.gtkwave_button,
            self.vectors_template,
        ]

    def _always_controls(self) -> list[QWidget]:
        return [self.radix_box, self.vectors_edit, self.vectors_open, self.vectors_save]

    def _idle_controls(self) -> list[QWidget]:
        return [self.top_edit, self.design_combo, self.signals_table]

    def _setup_controls(self) -> list[QWidget]:
        # These only take effect at compile time, so they are locked while a session is live.
        return [self.record_box, self.internal_box]

    @property
    def busy(self) -> bool:
        return self._compiling or self._job is not None

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    def _update_enabled(self) -> None:
        idle = not self.busy
        live = self._available and self.session is not None and idle
        has_design = self.design_combo.count() > 0
        self.compile_button.setEnabled(self._available and has_design and idle)
        for widget in self._always_controls():
            widget.setEnabled(self._available)
        for widget in self._idle_controls():
            widget.setEnabled(self._available and idle)
        for widget in self._setup_controls():
            widget.setEnabled(self._available and idle and self.session is None)
        for widget in self._session_controls():
            widget.setEnabled(live)
        self.stop_button.setEnabled(self._job is not None)

    def wait(self, timeout: float = 10.0) -> bool:
        """Process events until compiling and runs have finished; False on timeout."""
        end = time.monotonic() + timeout
        while self.busy and time.monotonic() < end:
            QCoreApplication.processEvents()
            time.sleep(0.001)
        return not self.busy

    # project and session

    def set_project(self, project: Project | None, project_dir: Path | None) -> None:
        self.close_session()
        self.project = project
        self.project_dir = project_dir
        self.design_combo.clear()
        if project is not None:
            self.design_combo.addItems(list(project.designs))
        self._clear_views()
        self._update_enabled()

    def close_session(self) -> None:
        self._compile_gen += 1
        self._compiling = False
        self._drop_job()
        self.run_button.setChecked(False)
        session, self.session = self.session, None
        if session is not None:
            session.close()
        self._update_enabled()

    def _clear_views(self) -> None:
        self._rows = []
        self._last = None
        self._fill_table()
        self.waveform.set_rows([])

    def _design(self) -> tuple[str, list[Path], str | None] | None:
        if self.project is None:
            return None
        name = self.design_combo.currentText()
        design = self.project.designs.get(name)
        if design is None:
            return None
        top = self.top_edit.text().strip() or design.top or None
        return name, list(design.files), top

    def design_name(self) -> str:
        return self.design_combo.currentText() or "design"

    def compile(self) -> bool:
        """Start compiling in a worker thread; True if it started (see `wait`)."""
        self.close_session()
        self._clear_views()
        self._fill_diagnostics([])
        chosen = self._design()
        if chosen is None or self._backend is None:
            return False
        _name, files, top = chosen
        self._compiling = True
        self.status_label.setText("Compiling...")
        self._update_enabled()
        task = _CompileTask(self._compile_gen, files, top, self._backend, self._compile_signals)
        self._pool.start(task)
        return True

    def _compile_failed(self, generation: int, error: object) -> None:
        if generation != self._compile_gen:
            return
        self._compiling = False
        if isinstance(error, CompileError):
            self._fill_diagnostics(list(error.diagnostics))
            self.view_tabs.setCurrentWidget(self.diagnostics_table)
        self.status_label.setText(str(error))
        self._update_enabled()

    def _compile_done(self, generation: int, session: object) -> None:
        if not isinstance(session, BifrostSession):
            return
        if generation != self._compile_gen:
            session.close()
            return
        self._compiling = False
        self.session = session
        self._after_compile(session)

    def _after_compile(self, session: BifrostSession) -> None:
        self._fill_diagnostics(list(session.diagnostics))
        self._record_names = None
        if self.internal_box.isChecked():
            self._record_names = [s.name for s in session.signals if s.kind != "clock"]
        if self.record_box.isChecked():
            session.start_recording(self._record_names)
        self._fill_table()
        self._refresh_waveform()
        self.status_label.setText(f"Compiled: {len(session.signals)} signals")
        self._update_enabled()

    # tables

    def _shown_signals(self) -> list[SimSignal]:
        if self.session is None:
            return []
        internals = self.internal_box.isChecked()
        return [s for s in self.session.signals if s.kind != "internal" or internals]

    def _fill_table(self) -> None:
        self._rows = self._shown_signals()
        self._refreshing = True
        try:
            self.signals_table.setRowCount(len(self._rows))
            for r, sig in enumerate(self._rows):
                for c, text in enumerate([sig.name, str(sig.width), sig.kind, ""]):
                    item = QTableWidgetItem(text)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.signals_table.setItem(r, c, item)
        finally:
            self._refreshing = False
        self._refresh_values()

    def _text_of(self, value: int, width: int) -> str:
        return format_value(value, width, self.waveform.radix)

    def _cursor_values(self) -> tuple[int, dict[str, int]] | None:
        """The session cycle at the cursor sample and the recorded values there."""
        cursor = self.waveform.cursor_index
        if cursor is None or self.session is None:
            return None
        rec = self.session.recording
        if rec is None or cursor >= len(rec.samples):
            return None
        return rec.cycles[cursor], dict(zip(rec.names, rec.samples[cursor], strict=True))

    def _refresh_values(self) -> None:
        if self.session is None:
            return
        at = self._cursor_values()
        header = "Value" if at is None else f"Value @{at[0]}"
        self.signals_table.setHorizontalHeaderItem(3, QTableWidgetItem(header))
        self._refreshing = True
        try:
            for r, sig in enumerate(self._rows):
                item = self.signals_table.item(r, 3)
                if item is None:
                    continue
                value = self.session.get(sig.name) if at is None else at[1].get(sig.name)
                item.setText("" if value is None else self._text_of(value, sig.width))
                editable = sig.kind == "input" and at is None
                flags = item.flags() | Qt.ItemFlag.ItemIsEditable
                item.setFlags(flags if editable else flags & ~Qt.ItemFlag.ItemIsEditable)
        finally:
            self._refreshing = False

    def _row_of(self, name: str) -> int | None:
        for r, sig in enumerate(self._rows):
            if sig.name == name:
                return r
        return None

    def value_text(self, name: str) -> str:
        r = self._row_of(name)
        item = None if r is None else self.signals_table.item(r, 3)
        return "" if item is None else item.text()

    def cell_tooltips(self) -> list[str]:
        items = [self.signals_table.item(r, 3) for r in range(self.signals_table.rowCount())]
        return [i.toolTip() for i in items if i is not None]

    def _mark_cell(self, name: str, message: str) -> None:
        r = self._row_of(name)
        item = None if r is None else self.signals_table.item(r, 3)
        if item is None:
            return
        self._refreshing = True
        try:
            item.setBackground(BAD_CELL if message else QColor(0, 0, 0, 0))
            item.setToolTip(message)
        finally:
            self._refreshing = False

    def set_input(self, name: str, text: str) -> bool:
        if self.session is None:
            return False
        try:
            value = parse_int_text(text, self.session.signal(name).width)
            self.session.set(name, value)
        except (ValueError, SimError) as e:
            self._mark_cell(name, str(e))
            self.status_label.setText(str(e))
            self._refresh_values()
            return False
        self._mark_cell(name, "")
        self._refresh_values()
        return True

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._refreshing or item.column() != 3:
            return
        self.set_input(self._rows[item.row()].name, item.text())

    def _fill_diagnostics(self, diags: list[Diagnostic]) -> None:
        self._diag_targets = []
        self.diagnostics_table.setRowCount(len(diags))
        for r, d in enumerate(diags):
            where = "" if d.file is None else f"{d.file}:{d.line or 0}"
            for c, text in enumerate([d.severity, d.message, where]):
                self.diagnostics_table.setItem(r, c, QTableWidgetItem(text))
            self._diag_targets.append(None if d.file is None else (Path(d.file), d.line or 1))

    def _diag_activated(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._diag_targets):
            target = self._diag_targets[row]
            if target is not None:
                self.location_activated.emit(target[0], target[1])

    # stepping

    def _step(self, cycles: int) -> bool:
        if self.session is None:
            return False
        try:
            self.session.step(cycles)
        except (ValueError, SimError) as e:
            self.run_button.setChecked(False)
            self.status_label.setText(str(e))
            return False
        self._refresh_waveform()
        self._refresh_values()
        if self.session.recording_full:
            self.status_label.setText("recording full")
        return True

    def _step_n(self) -> None:
        session = self.session
        if session is None or self.busy:
            return
        self.run_button.setChecked(False)
        total = self.step_n_box.value()

        def finish(stopped: bool) -> None:
            self._refresh_waveform()
            self._refresh_values()
            if not stopped:
                full = session.recording_full
                self.status_label.setText("recording full" if full else f"stepped {total} cycles")

        self._start_job(_Job("Step N", total, session.step, finish))

    def _run_toggled(self, on: bool) -> None:
        self.run_button.setText("Pause" if on else "Run")
        if on and self.session is not None:
            self._timer.start()
        else:
            self._timer.stop()

    def _tick(self) -> None:
        speed = int(self.speed_box.currentText())
        self._step(max(1, speed // TICKS_PER_SECOND))

    def _reset(self) -> None:
        if self.session is None:
            return
        try:
            self.session.reset()
        except SimError as e:
            self.status_label.setText(str(e))
            return
        self._refresh_waveform()
        self._refresh_values()

    # long runs

    def _start_job(self, job: _Job) -> None:
        self._job = job
        self._show_progress()
        self._update_enabled()
        self._job_timer.start()

    def _show_progress(self) -> None:
        job = self._job
        self.progress_label.setText("" if job is None else f"{job.label}: {job.done}/{job.total}")

    def _drop_job(self) -> None:
        self._job_timer.stop()
        self._job = None
        self._show_progress()

    def _end_job(self, stopped: bool, error: str | None = None) -> None:
        job = self._job
        self._drop_job()
        if job is not None:
            job.finish(stopped)
            if stopped:
                self.status_label.setText(error or f"stopped at {job.done}/{job.total}")
        self._update_enabled()

    def stop_job(self) -> None:
        """End the long run in progress; what has been recorded so far stays."""
        self._end_job(True)

    def _job_tick(self) -> None:
        job = self._job
        if job is None:
            self._job_timer.stop()
            return
        count = min(CHUNK, job.total - job.done)
        try:
            if count:
                job.advance(count)
        except (ValueError, SimError) as e:
            self._end_job(True, str(e))
            return
        job.done += count
        if job.done >= job.total:
            self._end_job(False)
        else:
            self._show_progress()

    def _rows_job(
        self, label: str, rows: Iterator[tuple[int, ...]], total: int, seed: int, text: str
    ) -> None:
        session = self.session
        if session is None:
            return
        ports, _outputs = session_ports(session)
        names = [p.name for p in data_ports(ports)]
        done: list[tuple[int, ...]] = []
        try:
            session.reset()
            session.start_recording(self._record_names, max_samples=max(MIN_RECORDING, total + 1))
        except (ValueError, SimError) as e:
            self.status_label.setText(str(e))
            return

        def advance(count: int) -> None:
            for row in itertools.islice(rows, count):
                session.set_many(dict(zip(names, row, strict=True)))
                session.step(1)
                done.append(row)

        def finish(stopped: bool) -> None:
            self._last = (VectorFile(tuple(done)), seed)
            self._after_run(text if not stopped else f"{label}: {len(done)} of {total} cycles")

        self.run_button.setChecked(False)
        self._start_job(_Job(label, total, advance, finish))

    def _run_random(self) -> None:
        if self.session is None or self.busy:
            return
        cycles, seed = self.random_cycles.value(), self.seed_box.value()
        ports, _outputs = session_ports(self.session)
        text = f"random run: {cycles} cycles, seed {seed}"
        self._rows_job("Run random", random_rows(ports, seed), cycles, seed, text)

    def _run_vectors(self) -> None:
        if self.session is None or self.busy:
            return
        ports, outputs = session_ports(self.session)
        try:
            vf = parse_vectors(self.vectors_edit.toPlainText(), ports, outputs)
        except VectorError as e:
            self._show_vector_error(e)
            return
        text = f"vector run: {len(vf.rows)} cycles"
        self._rows_job("Run vectors", iter(vf.rows), len(vf.rows), 0, text)

    def _after_run(self, text: str) -> None:
        self._refresh_waveform()
        self._refresh_values()
        self.view_tabs.setCurrentIndex(0)
        self.status_label.setText(text)

    def _show_vector_error(self, error: VectorError) -> None:
        self.status_label.setText(str(error))
        block = self.vectors_edit.document().findBlockByNumber(max(0, error.line - 1))
        if block.isValid():
            self.vectors_edit.setTextCursor(QTextCursor(block))
        self.view_tabs.setCurrentIndex(1)

    # waveform

    def _refresh_waveform(self) -> None:
        rec = None if self.session is None else self.session.recording
        if rec is None:
            self.waveform.set_rows([])
            return
        start = view_start(len(rec.samples))
        self.waveform.set_rows(rows_from_recording(rec, start), start)

    def _radix_changed(self, radix: str) -> None:
        self.waveform.set_radix(radix)
        self._refresh_values()

    def _cursor_changed(self, _index: object) -> None:
        self._refresh_values()

    # files

    def _io_failed(self, what: str, path: Path | str, error: Exception) -> None:
        self.status_label.setText(f"could not {what} {path}: {error}")

    def save_vcd(self, path: Path) -> bool:
        rec = None if self.session is None else self.session.recording
        if rec is None:
            self.status_label.setText("nothing recorded")
            return False
        try:
            write_vcd(rec, path, self.design_name())
        except OSError as e:
            self._io_failed("save", path, e)
            return False
        self.status_label.setText(f"saved {path}")
        return True

    def _save_vcd_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save VCD", "", "VCD (*.vcd)")
        if path:
            self.save_vcd(Path(path))

    def _save_vectors_dialog(self) -> None:
        if self.session is None or self._last is None:
            self.status_label.setText("no vectors have been run")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save vectors", "", "Text (*.txt *.vec)")
        if path:
            self.save_vectors(Path(path))

    def save_vectors(self, path: Path) -> bool:
        if self.session is None or self._last is None:
            self.status_label.setText("no vectors have been run")
            return False
        ports, outputs = session_ports(self.session)
        vf, seed = self._last
        try:
            text = format_vectors(vf, ports, outputs, recording=self.session.recording, seed=seed)
            path.write_text(text, encoding="utf-8")
        except (OSError, ValueError) as e:
            self._io_failed("save", path, e)
            return False
        self.status_label.setText(f"saved {path}")
        return True

    def _open_vectors(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open vectors")
        if path:
            self.load_vectors(Path(path))

    def load_vectors(self, path: Path) -> bool:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            self._io_failed("open", path, e)
            return False
        self.vectors_edit.setPlainText(text)
        return True

    def _save_vectors_text(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save vector text")
        if path:
            self.save_vectors_text(Path(path))

    def save_vectors_text(self, path: Path) -> bool:
        try:
            path.write_text(self.vectors_edit.toPlainText(), encoding="utf-8")
        except OSError as e:
            self._io_failed("save", path, e)
            return False
        self.status_label.setText(f"saved {path}")
        return True

    def _template(self) -> None:
        if self.session is None:
            return
        ports, outputs = session_ports(self.session)
        zero = tuple(0 for p in ports if p.kind == "input")
        text = format_vectors(VectorFile((zero,) * 16), ports, outputs)
        self.vectors_edit.setPlainText(text)

    def gtkwave_program(self) -> str | None:
        return os.environ.get("WYRD_GTKWAVE") or shutil.which("gtkwave")

    def _open_gtkwave(self) -> None:
        program = self.gtkwave_program()
        if program is None:
            self.status_label.setText(GTKWAVE_MISSING)
            return
        rec = None if self.session is None else self.session.recording
        if rec is None or self.project_dir is None:
            self.status_label.setText("nothing recorded")
            return
        out = self.project_dir / "sim"
        vcd = out / f"{self.design_name()}.vcd"
        try:
            out.mkdir(exist_ok=True)
            write_vcd(rec, vcd, self.design_name())
        except OSError as e:
            self._io_failed("write", vcd, e)
            return
        error = self.launcher(program, [str(vcd)])
        if error is not None:
            self.status_label.setText(f"could not start {program}: {error}")
