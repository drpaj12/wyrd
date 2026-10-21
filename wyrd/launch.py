"""Starting step processes under a memory cap, and waiting for them (spec section 5)."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

KILL_GRACE_S = 10.0


class Launcher(Protocol):
    def start(
        self,
        argv: list[str],
        env: dict[str, str],
        cwd: Path,
        mem_cap: int,
        log_out: Path,
        log_err: Path,
    ) -> subprocess.Popen[bytes]: ...


@dataclass(frozen=True)
class StepResult:
    exit_code: int
    wall_s: float
    peak_mem_bytes: int
    outcome: str


def _spawn(
    argv: list[str], env: dict[str, str], cwd: Path, log_out: Path, log_err: Path
) -> subprocess.Popen[bytes]:
    with log_out.open("wb") as out, log_err.open("wb") as err:
        return subprocess.Popen(
            argv,
            env=env,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            start_new_session=True,
        )


class PlainLauncher:
    """Runs argv as is, in a new process group. The memory cap is not enforced."""

    def start(
        self,
        argv: list[str],
        env: dict[str, str],
        cwd: Path,
        mem_cap: int,
        log_out: Path,
        log_err: Path,
    ) -> subprocess.Popen[bytes]:
        return _spawn(argv, env, cwd, log_out, log_err)


class SystemdLauncher:
    """Runs argv in a transient systemd user scope with MemoryMax (no swap)."""

    def start(
        self,
        argv: list[str],
        env: dict[str, str],
        cwd: Path,
        mem_cap: int,
        log_out: Path,
        log_err: Path,
    ) -> subprocess.Popen[bytes]:
        prefix = [
            "systemd-run", "--user", "--scope", "--quiet",
            "-p", f"MemoryMax={mem_cap}", "-p", "MemorySwapMax=0",
        ]  # fmt: skip
        return _spawn([*prefix, *argv], env, cwd, log_out, log_err)


def make_launcher(name: str) -> Launcher:
    return SystemdLauncher() if name == "systemd" else PlainLauncher()


def _killpg(pgid: int, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, sig)


def kill_group(proc: subprocess.Popen[bytes], sig: int) -> None:
    """Signal the process group this module started for `proc`; never anything else."""
    if proc.returncode is None:
        _killpg(proc.pid, sig)


def _outcome(code: int, timed_out: bool, kill_is_oom: bool) -> str:
    if timed_out:
        return "timeout"
    if code == 0:
        return "ok"
    return "oom" if kill_is_oom and code == -signal.SIGKILL else "fail"


def wait_step(
    proc: subprocess.Popen[bytes], timeout: int, kill_is_oom: bool = False
) -> StepResult:
    """Wait for `proc`, enforcing `timeout`; report exit code, wall time and peak memory.

    Timeout: SIGTERM to the group, SIGKILL after 10 s. `kill_is_oom` says a SIGKILL
    that no timeout caused is the memory cap (systemd launcher).
    """
    start = time.monotonic()
    timed_out = threading.Event()
    timers: list[threading.Timer] = []

    def expire() -> None:
        try:
            done = os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        except OSError:
            return  # already reaped: it finished before the timeout
        if done is not None:
            return  # exited before the timeout fired; wait4 below reports its real status
        timed_out.set()
        kill_group(proc, signal.SIGTERM)
        hard = threading.Timer(KILL_GRACE_S, kill_group, (proc, signal.SIGKILL))
        hard.daemon = True
        timers.append(hard)
        hard.start()

    try:
        soft = threading.Timer(timeout, expire)
        soft.daemon = True
        timers.append(soft)
        soft.start()
        _, status, usage = os.wait4(proc.pid, 0)
        proc.returncode = os.waitstatus_to_exitcode(status)
    except BaseException:
        for timer in timers:
            timer.cancel()
        kill_group(proc, signal.SIGKILL)  # no-op once the child was reaped
        with contextlib.suppress(OSError):
            os.waitpid(proc.pid, 0)
        raise
    for timer in timers:
        timer.cancel()
    code = proc.returncode
    if timed_out.is_set():  # stragglers of the group we started
        _killpg(proc.pid, signal.SIGKILL)
    peak = usage.ru_maxrss * 1024
    outcome = _outcome(code, timed_out.is_set(), kill_is_oom)
    return StepResult(code, time.monotonic() - start, peak, outcome)


__all__ = [
    "Launcher", "PlainLauncher", "StepResult", "SystemdLauncher",
    "kill_group", "make_launcher", "wait_step",
]  # fmt: skip
