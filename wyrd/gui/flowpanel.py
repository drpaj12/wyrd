"""Flow panel: runs ``wyrd run`` and the VPR floorplan viewer as QProcess children."""

from __future__ import annotations

import os
import signal
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QProcess, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from wyrd.guimodel.floorplan import FloorplanPlan
from wyrd.guimodel.flowcmd import FlowProgress, exit_text, run_argv

CANCEL_GRACE_MS = 30000
CLOSE_TERM_MS = 10000
KILL_GRACE_MS = 5000
EARLY_EXIT_MS = 5000
EARLY_EXIT_TEXT = "VPR exited early; is this VPR built with graphics (Qt6)? See the log above."


def _lines(data: bytes) -> list[str]:
    return data.decode("utf-8", errors="replace").splitlines()


class FlowPanel(QWidget):
    run_requested = Signal()
    finished = Signal(int)
    error = Signal(str)
    floorplan_error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.run_button = QPushButton("Run")
        self.cancel_button = QPushButton("Cancel")
        self.force_box = QCheckBox("Force")
        self.jobs_box = QSpinBox()
        self.jobs_box.setRange(0, 256)
        self.jobs_box.setSpecialValueText("machine setting")
        self.budget_edit = QLineEdit()
        self.budget_edit.setPlaceholderText("machine setting")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.status_label = QLabel("idle")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.process: QProcess | None = None
        self.floorplan_process: QProcess | None = None
        self._tracker = FlowProgress()
        self._pending = b""
        self._can_run = False
        self._fp_clock = QElapsedTimer()
        self.term_ms = CANCEL_GRACE_MS
        self.close_term_ms = CLOSE_TERM_MS
        self.kill_ms = KILL_GRACE_MS
        self._build()
        self._sync()

    def _build(self) -> None:
        row = QHBoxLayout()
        for w in (self.run_button, self.cancel_button, self.force_box):
            row.addWidget(w)
        row.addWidget(QLabel("Jobs"))
        row.addWidget(self.jobs_box)
        row.addWidget(QLabel("Memory budget"))
        row.addWidget(self.budget_edit)
        row.addStretch(1)
        col = QVBoxLayout(self)
        col.addLayout(row)
        col.addWidget(self.progress)
        col.addWidget(self.status_label)
        col.addWidget(self.log)
        self.run_button.clicked.connect(self.run_requested)
        self.cancel_button.clicked.connect(self.cancel)

    def set_can_run(self, ok: bool) -> None:
        self._can_run = ok
        self._sync()

    def is_running(self) -> bool:
        return self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning

    def _sync(self) -> None:
        running = self.is_running()
        self.run_button.setEnabled(self._can_run and not running)
        self.cancel_button.setEnabled(running)

    def _append(self, line: str) -> None:
        self.log.appendPlainText(line)

    def start(self, project_dir: Path) -> None:
        if self.is_running():
            return
        argv = run_argv(
            project_dir,
            self.force_box.isChecked(),
            self.jobs_box.value(),
            self.budget_edit.text().strip(),
        )
        self.log.clear()
        self._tracker = FlowProgress()
        self._pending = b""
        self.progress.setRange(0, 0)
        self.status_label.setText("running")
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.readyReadStandardError.connect(self._on_stderr)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(lambda err: self._on_error(proc, err))
        self.process = proc
        proc.setProgram(argv[0])
        proc.setArguments(argv[1:])
        proc.start()
        self._sync()

    def _feed(self, line: str) -> None:
        self._append(line)
        self._tracker.feed(line)
        fraction = self._tracker.fraction()
        if fraction is None:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(fraction * 1000))

    def _on_stdout(self) -> None:
        if self.process is None:
            return
        self._pending += bytes(self.process.readAllStandardOutput().data())
        *complete, self._pending = self._pending.split(b"\n")
        for raw in complete:
            for line in _lines(raw) or [""]:
                self._feed(line)

    def _on_stderr(self) -> None:
        if self.process is None:
            return
        for line in _lines(bytes(self.process.readAllStandardError().data())):
            self._append(f"stderr: {line}")

    def _on_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        self._on_stdout()
        self._on_stderr()
        if self._pending:
            for line in _lines(self._pending):
                self._feed(line)
            self._pending = b""
        crashed = status == QProcess.ExitStatus.CrashExit
        self.status_label.setText("stopped" if crashed else exit_text(code))
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 1000)
        self._sync()
        self.finished.emit(code)

    def _on_error(self, proc: QProcess, err: QProcess.ProcessError) -> None:
        if err not in (QProcess.ProcessError.FailedToStart, QProcess.ProcessError.Crashed):
            return
        text = f"Flow {self._error_word(err)}: {proc.errorString()}"
        self._append(text)
        self.error.emit(text)
        if err == QProcess.ProcessError.FailedToStart:
            self.status_label.setText("failed to start")
            self.progress.setRange(0, 1000)
            self.progress.setValue(0)
            self._sync()
            self.finished.emit(-1)

    @staticmethod
    def _error_word(err: QProcess.ProcessError) -> str:
        return "failed to start" if err == QProcess.ProcessError.FailedToStart else "crashed"

    def cancel(self) -> None:
        self._cancel(self.term_ms)

    def shutdown(self) -> None:
        """Stop the flow for closing the window; escalates to terminate and kill."""
        self._cancel(self.close_term_ms)

    def _cancel(self, term_ms: int) -> None:
        proc = self.process
        if proc is None:
            return
        state = proc.state()
        if state == QProcess.ProcessState.Starting:
            proc.started.connect(lambda: self._cancel(term_ms))
            return
        pid = int(proc.processId())
        if state != QProcess.ProcessState.Running or pid <= 0:
            return
        try:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            return
        self.status_label.setText("cancelling")
        QTimer.singleShot(term_ms, proc, lambda: self._terminate(proc))
        QTimer.singleShot(term_ms + self.kill_ms, proc, lambda: self._kill(proc))

    @staticmethod
    def _terminate(proc: QProcess) -> None:
        if proc.state() != QProcess.ProcessState.NotRunning:
            proc.terminate()

    @staticmethod
    def _kill(proc: QProcess) -> None:
        if proc.state() != QProcess.ProcessState.NotRunning:
            proc.kill()

    def floorplan_running(self) -> bool:
        proc = self.floorplan_process
        return proc is not None and proc.state() != QProcess.ProcessState.NotRunning

    def stop_floorplan(self) -> None:
        proc = self.floorplan_process
        if proc is not None and self.floorplan_running():
            proc.kill()

    def start_floorplan(self, plan: FloorplanPlan) -> None:
        if self.floorplan_running():
            self._append("floorplan viewer is already running; close it first")
            return
        plan.cwd.mkdir(parents=True, exist_ok=True)
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.setWorkingDirectory(str(plan.cwd))
        proc.readyReadStandardOutput.connect(lambda: self._fp_output(proc))
        proc.finished.connect(lambda code, _st: self._fp_finished(proc, code))
        proc.errorOccurred.connect(lambda err: self._fp_error(proc, err))
        self.floorplan_process = proc
        self._append(f"floorplan ({plan.mode}): {plan.program} {' '.join(plan.args)}")
        self._fp_clock.start()
        proc.start(plan.program, list(plan.args))

    def _fp_error(self, proc: QProcess, err: QProcess.ProcessError) -> None:
        if err != QProcess.ProcessError.FailedToStart:
            return
        text = f"Cannot start the floorplan viewer: {proc.errorString()}"
        self._append(text)
        self.floorplan_error.emit(text)

    def _fp_output(self, proc: QProcess) -> None:
        for line in _lines(bytes(proc.readAllStandardOutput().data())):
            self._append(line)

    def _fp_finished(self, proc: QProcess, code: int) -> None:
        self._fp_output(proc)
        if code != 0 and self._fp_clock.elapsed() < EARLY_EXIT_MS:
            self._append(EARLY_EXIT_TEXT)
