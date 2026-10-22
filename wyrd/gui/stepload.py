"""Background loading of step-log messages, so a big log never blocks the UI thread."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from wyrd.gui.sourceview import MAX_BYTES
from wyrd.guimodel.logparse import Message, parse_lines
from wyrd.guimodel.runs import step_dirs


def read_log_limited(path: Path) -> str:
    """Up to ``MAX_BYTES`` of ``path`` decoded; empty when it cannot be read."""
    if not path.is_file():
        return ""
    try:
        with path.open("rb") as handle:
            return handle.read(MAX_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return ""


def load_messages(run_dir: Path) -> tuple[list[Message], list[Path]]:
    """Messages of every step log under ``run_dir`` and the directories to search for sources."""
    seen: set[tuple[str, str, str, str | None, int | None]] = set()
    out: list[Message] = []
    search: list[Path] = []
    for step in step_dirs(run_dir):
        search += [step.path, step.path / "out"]
        for log in sorted(step.path.rglob("*.log")):
            for msg in parse_lines(read_log_limited(log).splitlines(), log):
                key = (msg.severity, msg.tool, msg.text, msg.file, msg.line)
                if key not in seen:
                    seen.add(key)
                    out.append(msg)
    return out, search


class LoadSignals(QObject):
    done = Signal(int, object, object)


class LoadTask(QRunnable):
    def __init__(self, generation: int, run_dir: Path, signals: LoadSignals) -> None:
        super().__init__()
        self.generation = generation
        self.run_dir = run_dir
        self.signals = signals

    def run(self) -> None:
        messages, search = load_messages(self.run_dir)
        self.signals.done.emit(self.generation, messages, search)
