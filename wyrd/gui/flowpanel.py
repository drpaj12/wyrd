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

from wyrd.gui.weakslot import weak
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
        self._token = 0
        self._start_wait = False
        self._armed_ms: int | None = None
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
        self._token += 1
        token = self._token
        self._armed_ms = None
        self._start_wait = False
        self.log.clear()
        self._tracker = FlowProgress()
        self._pending = b""
        self.progress.setRange(0, 0)
        self.status_label.setText("running")
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        on_stdout, on_stderr = weak(self._on_stdout), weak(self._on_stderr)
        on_finished, on_error = weak(self._on_finished), weak(self._on_error)
        proc.readyReadStandardOutput.connect(lambda: on_stdout(proc, token))
        proc.readyReadStandardError.connect(lambda: on_stderr(proc, token))
        proc.finished.connect(lambda code, status: on_finished(proc, token, code, status))
        proc.errorOccurred.connect(lambda err: on_error(proc, token, err))
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

    def _current(self, proc: QProcess, token: int) -> bool:
        """True when ``proc`` is the run started last; output of any other run is dropped."""
        return token == self._token and proc is self.process

    def reset(self) -> None:
        """Back to idle with an empty log; no effect while a flow runs."""
        if self.is_running():
            return
        self.log.clear()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.status_label.setText("idle")
        self._sync()

    def _on_stdout(self, proc: QProcess, token: int) -> None:
        if not self._current(proc, token):
            return
        self._pending += bytes(proc.readAllStandardOutput().data())
        *complete, self._pending = self._pending.split(b"\n")
        for raw in complete:
            for line in _lines(raw) or [""]:
                self._feed(line)

    def _on_stderr(self, proc: QProcess, token: int) -> None:
        if not self._current(proc, token):
            return
        for line in _lines(bytes(proc.readAllStandardError().data())):
            self._append(f"stderr: {line}")

    def _on_finished(
        self, proc: QProcess, token: int, code: int, status: QProcess.ExitStatus
    ) -> None:
        if not self._current(proc, token):
            return
        self._on_stdout(proc, token)
        self._on_stderr(proc, token)
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

    def _on_error(self, proc: QProcess, token: int, err: QProcess.ProcessError) -> None:
        if not self._current(proc, token):
            return
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
            self._cancel_when_started(proc, term_ms)
            return
        pid = int(proc.processId())
        if state != QProcess.ProcessState.Running or pid <= 0:
            return
        if self._armed_ms is not None and term_ms >= self._armed_ms:
            return  # escalation already armed at least as short; do not stack timers
        try:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            return
        self._armed_ms = term_ms
        self.status_label.setText("cancelling")
        QTimer.singleShot(term_ms, proc, lambda: FlowPanel._terminate(proc))
        QTimer.singleShot(term_ms + self.kill_ms, proc, lambda: FlowPanel._kill(proc))

    def _cancel_when_started(self, proc: QProcess, term_ms: int) -> None:
        if self._start_wait:
            return
        self._start_wait = True
        started_cancel = weak(self._started_cancel)
        proc.started.connect(lambda: started_cancel(proc, term_ms))

    def _started_cancel(self, proc: QProcess, term_ms: int) -> None:
        self._start_wait = False
        if proc is self.process:
            self._cancel(term_ms)

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
        fp_output, fp_finished, fp_error = (
            weak(self._fp_output),
            weak(self._fp_finished),
            weak(self._fp_error),
        )
        proc.readyReadStandardOutput.connect(lambda: fp_output(proc))
        proc.finished.connect(lambda code, _st: fp_finished(proc, code))
        proc.errorOccurred.connect(lambda err: fp_error(proc, err))
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
