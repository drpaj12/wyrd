"""Command line, progress parsing and exit texts for running ``wyrd run`` from the GUI."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

_PLAN = re.compile(r"^plan: (\d+) to run, (\d+) reused$")
_RUN = re.compile(r"^(\S+/\S+) \[([0-9a-f]{12})\] (ok|fail|oom|timeout|cancelled)(?:: (.*))?$")


@dataclass(frozen=True)
class ProgressEvent:
    kind: str  # "plan" or "run"
    to_run: int = 0
    reused: int = 0
    name: str = ""
    key: str = ""
    status: str = ""
    message: str = ""


def run_argv(
    project_dir: Path, force: bool = False, jobs: int = 0, mem_budget: str = ""
) -> list[str]:
    """The program and arguments that run the project's flow with progress lines."""
    argv = [sys.executable, "-m", "wyrd.cli", "run", "--project", str(project_dir), "--progress"]
    if force:
        argv.append("--force")
    if jobs > 0:
        argv += ["--jobs", str(jobs)]
    if mem_budget:
        argv += ["--mem-budget", mem_budget]
    return argv


def parse_progress(line: str) -> ProgressEvent | None:
    """A plan or run event from one stdout line; None for any other line."""
    m = _PLAN.match(line)
    if m:
        return ProgressEvent("plan", to_run=int(m.group(1)), reused=int(m.group(2)))
    m = _RUN.match(line)
    if m:
        return ProgressEvent(
            "run", name=m.group(1), key=m.group(2), status=m.group(3), message=m.group(4) or ""
        )
    return None


class FlowProgress:
    """Counts finished runs against the planned total."""

    def __init__(self) -> None:
        self.total: int | None = None
        self.done = 0

    def feed(self, line: str) -> ProgressEvent | None:
        event = parse_progress(line)
        if event is None:
            return None
        if event.kind == "plan":
            self.total, self.done = event.to_run, 0
        else:
            self.done += 1
        return event

    def fraction(self) -> float | None:
        """Progress in 0..1; None before the plan line (busy)."""
        if self.total is None:
            return None
        if self.total == 0:
            return 1.0
        return min(self.done / self.total, 1.0)


def exit_text(code: int) -> str:
    texts = {0: "all runs ok", 1: "some runs not ok", 2: "configuration error (see log)"}
    return texts.get(code, f"exited with code {code}")
