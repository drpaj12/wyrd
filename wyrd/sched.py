"""Run a project's runs under the memory budget and record the results (spec section 5)."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any

from wyrd.launch import Launcher, StepResult, SystemdLauncher, kill_group, make_launcher, wait_step
from wyrd.model import RunSpec
from wyrd.preflight import plan_run, run_arch_xml
from wyrd.project import Project
from wyrd.settings import Settings
from wyrd.steps import Step, tool_versions
from wyrd.store import Store, run_dir, run_key

_UNSET = object()


def estimate(
    store: Store, design: str, arch: str, step: str, is_vpr: bool, settings: Settings
) -> int:
    """Expected peak of a step: history times the factor (capped at the budget), else the default.

    Only a configured default larger than the whole budget can exceed the budget.
    """
    peak = store.peak_mem(design, arch, step)
    if peak:
        return min(int(peak * settings.history_factor), settings.mem_budget)
    return settings.vpr_mem if is_vpr else settings.other_mem


@dataclass(frozen=True)
class _Plan:
    run: RunSpec
    key: str
    directory: Path
    steps: tuple[Step, ...]


def _total_bytes(run: RunSpec) -> int:
    return sum(f.stat().st_size for f in run.design.files)


def _tools_of(steps: list[tuple[Step, list[str], dict[str, str]]]) -> set[str]:
    return {tool for step, _, _ in steps for tool in step.tools}


def _build_plans(project: Project, settings: Settings) -> list[_Plan]:
    planned = [(run, plan_run(run, settings)) for run in project.runs]
    versions = tool_versions(settings, sorted({t for _, p in planned for t in _tools_of(p)}))
    plans: dict[str, _Plan] = {}
    for run, plan in planned:
        argvs = [argv for _, argv, _ in plan]
        wanted = {t: versions[t] for t in _tools_of(plan)}
        key = run_key(run, run_arch_xml(settings, run), wanted, argvs)
        plans.setdefault(
            key, _Plan(run, key, run_dir(project.root, run, key), tuple(s for s, _, _ in plan))
        )
    return sorted(plans.values(), key=lambda p: _total_bytes(p.run))


def _write_cmd_sh(path: Path, cwd: Path, env: dict[str, str], argv: list[str]) -> None:
    lines = ["#!/bin/sh", f"cd {shlex.quote(str(cwd))}"]
    lines += [f"export {k}={shlex.quote(v)}" for k, v in sorted(env.items())]
    lines.append(shlex.join(argv))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o755)


def _note(step_dir: Path, text: str) -> None:
    with (step_dir / "stderr.log").open("a", encoding="utf-8") as err:
        err.write(text.rstrip("\n") + "\n")


class _Scheduler:
    def __init__(
        self, settings: Settings, store: Store, launcher: Launcher, log: Callable[[str], None]
    ) -> None:
        self.settings = settings
        self.store = store
        self.launcher = launcher
        self.log = log
        self.kill_is_oom = isinstance(launcher, SystemdLauncher)
        self.cond = threading.Condition()
        self.used = 0
        self.running: set[subprocess.Popen[bytes]] = set()
        self.cancel = threading.Event()
        self.results: dict[str, str] = {}

    def on_sigint(self, signum: int, frame: FrameType | None) -> None:
        self.cancel.set()
        with self.cond:
            for proc in list(self.running):
                kill_group(proc, signal.SIGKILL)
            self.cond.notify_all()

    def acquire(self, cap: int) -> bool:
        """Reserve `cap` bytes of budget; False when cancelled while waiting."""
        with self.cond:
            self.cond.wait_for(
                lambda: self.cancel.is_set() or self.used + cap <= self.settings.mem_budget
            )
            if self.cancel.is_set():
                return False
            self.used += cap
            return True

    def release(self, cap: int) -> None:
        with self.cond:
            self.used -= cap
            self.cond.notify_all()

    def execute(
        self, argv: list[str], env: dict[str, str], step_dir: Path, cap: int
    ) -> StepResult:
        full = {**os.environ, **env}
        try:
            proc = self.launcher.start(
                argv, full, step_dir, cap, step_dir / "stdout.log", step_dir / "stderr.log"
            )
        except OSError as exc:
            _note(step_dir, f"cannot start {argv[0] if argv else '(empty)'}: {exc}")
            return StepResult(127, 0.0, 0, "fail")
        with self.cond:
            self.running.add(proc)
            if self.cancel.is_set():
                kill_group(proc, signal.SIGKILL)
        try:
            return wait_step(proc, self.settings.step_timeout, self.kill_is_oom)
        finally:
            with self.cond:
                self.running.discard(proc)

    def attempt(
        self, argv: list[str], env: dict[str, str], step_dir: Path, cap: int
    ) -> StepResult | None:
        if not self.acquire(cap):
            return None
        try:
            return self.execute(argv, env, step_dir, cap)
        finally:
            self.release(cap)

    def step(self, plan: _Plan, n: int, step: Step) -> tuple[str, str]:
        run, key = plan.run, plan.key
        step_dir = plan.directory / f"{n}-{step.name}"
        step_dir.mkdir(parents=True)
        argv, env = step.command(run, step_dir, self.settings)
        _write_cmd_sh(step_dir / "cmd.sh", step_dir, env, argv)
        name = run.design.name
        cap = estimate(self.store, name, run.arch, step.name, step.is_vpr, self.settings)
        budget = self.settings.mem_budget
        if cap > budget:
            msg = f"estimated {cap} bytes exceeds the whole memory budget {budget}"
            _note(step_dir, msg)
            return "oom", msg
        res = self.attempt(argv, env, step_dir, cap)
        if res is not None and self.cancel.is_set() and res.outcome != "ok":
            return "cancelled", "cancelled"  # killed by us: not an oom, not recorded, no retry
        if res is not None and res.outcome == "oom":
            retry = int(cap * self.settings.oom_retry_factor)
            if retry <= self.settings.mem_budget:
                self.record(key, n, step, argv, step_dir, res)
                res = self.attempt(argv, env, step_dir, retry)
        if res is None:
            return "cancelled", "cancelled"
        if self.cancel.is_set() and res.outcome != "ok":
            return "cancelled", "cancelled"
        self.record(key, n, step, argv, step_dir, res)
        return self.finish_step(key, step, step_dir, res)

    def record(
        self, key: str, n: int, step: Step, argv: list[str], step_dir: Path, res: StepResult
    ) -> None:
        times = {"wall_s": res.wall_s, "peak_mem_bytes": res.peak_mem_bytes}
        (step_dir / "time.json").write_text(json.dumps(times), encoding="utf-8")
        self.store.add_step(key, n, step.name, argv, res.exit_code, res.wall_s, res.peak_mem_bytes)

    def finish_step(self, key: str, step: Step, step_dir: Path, res: StepResult) -> tuple[str, str]:
        if res.outcome != "ok":
            return res.outcome, f"step {step.name!r} exit code {res.exit_code}"
        try:
            self.store.add_metrics(key, step.name, step.collect(step_dir))
        except ValueError as exc:
            _note(step_dir, str(exc))
            return "fail", str(exc)
        return "ok", ""

    def run_one(self, plan: _Plan) -> None:
        if self.cancel.is_set():
            return
        if plan.directory.exists():
            shutil.rmtree(plan.directory)
        plan.directory.mkdir(parents=True)
        self.store.begin(plan.key, plan.run, plan.directory)
        status, msg = "ok", ""
        try:
            for n, step in enumerate(plan.steps):
                status, msg = self.step(plan, n, step)
                if status != "ok":
                    break
        except Exception as exc:  # a run must always end in a recorded status
            status, msg = "fail", f"{type(exc).__name__}: {exc}"
        self.store.finish(plan.key, status)
        self.results[plan.key] = status
        name = f"{plan.run.design.name}/{plan.run.arch}"
        self.log(f"{name} [{plan.key[:12]}] {status}" + (f": {msg}" if msg else ""))


def run_all(
    project: Project,
    settings: Settings,
    store: Store,
    force: bool,
    launcher: Launcher | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, str]:
    """Run every run of the project; return run key to final status.

    Runs already `ok` are reused unless `force`. Smallest inputs go first. A step starts only
    when its memory estimate fits the free budget. SIGINT kills the running groups and marks
    those runs `cancelled`; runs not yet started are left out of the result.
    """
    sched = _Scheduler(
        settings,
        store,
        launcher or make_launcher(settings.launcher),
        log or (lambda line: print(line, file=sys.stderr)),
    )
    todo: list[_Plan] = []
    for plan in _build_plans(project, settings):
        if not force and store.status(plan.key) == "ok":
            sched.results[plan.key] = "ok"
        else:
            todo.append(plan)
    previous: Any = _UNSET
    on_main = threading.current_thread() is threading.main_thread()
    if on_main:
        previous = signal.signal(signal.SIGINT, sched.on_sigint)
    try:
        with ThreadPoolExecutor(max_workers=settings.jobs) as pool:
            list(pool.map(sched.run_one, todo))
    finally:
        if on_main and previous is not _UNSET:
            signal.signal(signal.SIGINT, signal.SIG_DFL if previous is None else previous)
    return dict(sched.results)
