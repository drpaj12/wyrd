"""Checks before any run starts, and the per-project lock (spec section 5)."""

from __future__ import annotations

import fcntl
import os
import shutil
from pathlib import Path

from wyrd.model import RunSpec
from wyrd.project import Project
from wyrd.settings import Settings
from wyrd.steps import Step, arch_xml, get_step, tool_path

PLACEHOLDER_DIR = Path("{step_dir}")


class ProjectLocked(Exception):
    """Another `wyrd run` holds the project lock."""


def acquire_lock(root: Path) -> int:
    """Take an exclusive lock on ``root/.wyrd.lock``; return the open fd (closing it unlocks)."""
    fd = os.open(root / ".wyrd.lock", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        raise ProjectLocked("project is locked (another wyrd run holds .wyrd.lock)") from exc
    return fd


def plan_run(run: RunSpec, settings: Settings) -> list[tuple[Step, list[str], dict[str, str]]]:
    """Build every step of a run once, with a placeholder step directory.

    Raises ValueError or KeyError for bad recipe arguments or an unknown step.
    """
    out: list[tuple[Step, list[str], dict[str, str]]] = []
    for spec in run.recipe.steps:
        step = get_step(spec)
        argv, env = step.command(run, PLACEHOLDER_DIR, settings)
        out.append((step, argv, env))
    return out


def run_arch_xml(settings: Settings, run: RunSpec, argvs: list[list[str]]) -> Path | None:
    """The run's arch file when some step's command names it, else None."""
    try:
        xml = arch_xml(settings, run.arch)
    except ValueError:
        return None
    named = any(str(xml) in word for argv in argvs for word in argv)
    return xml if named else None


def _plan_messages(project: Project, settings: Settings) -> tuple[list[str], set[str]]:
    problems: list[str] = []
    tools: set[str] = set()
    for run in project.runs:
        try:
            plan = plan_run(run, settings)
        except KeyError as exc:
            problems.append(f"unknown step {exc.args[0]!r}")
            continue
        except ValueError as exc:
            problems.append(str(exc))
            continue
        for step, _, _ in plan:
            tools.update(step.tools)
        xml = run_arch_xml(settings, run, [argv for _, argv, _ in plan])
        if xml is not None and not xml.is_file():
            problems.append(f"arch file not found: {xml}")
    return problems, tools


def _resolves(path: str) -> bool:
    return shutil.which(path) is not None or Path(path).exists()


def _tool_messages(settings: Settings, tools: set[str]) -> list[str]:
    problems: list[str] = []
    for name in sorted(tools):
        try:
            path = tool_path(settings, name)
        except (ValueError, KeyError):
            continue  # already reported while planning (vtr_root) or not a setting
        if not _resolves(path):
            problems.append(f"tool {name!r} not found: {path}")
    return problems


def _disk_message(settings: Settings) -> list[str]:
    try:
        free = shutil.disk_usage(settings.disk_check_path).free
    except OSError as exc:
        return [f"cannot check disk space on {settings.disk_check_path}: {exc.strerror}"]
    if free < settings.disk_min_free:
        return [
            f"only {free} bytes free on {settings.disk_check_path}, "
            f"need {settings.disk_min_free} (disk_min_free)"
        ]
    return []


def preflight(project: Project, settings: Settings) -> list[str]:
    """Problems that stop a run before it starts; empty means ok. Makes no run directory."""
    problems, tools = _plan_messages(project, settings)
    problems += _tool_messages(settings, tools)
    if settings.vtr_root is not None and not settings.vtr_root.is_dir():
        problems.append(f"vtr_root not found: {settings.vtr_root}")
    if settings.launcher == "systemd" and shutil.which("systemd-run") is None:
        problems.append("launcher is systemd but systemd-run is not on PATH")
    problems += _disk_message(settings)
    return list(dict.fromkeys(problems))
