"""Checks before any run starts, and the per-project lock (spec section 5)."""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
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


def run_arch_xml(settings: Settings, run: RunSpec) -> Path | None:
    """The run's arch file (None when the run has no arch).

    Raises ValueError when vtr_root is not set.
    """
    return arch_xml(settings, run.arch) if run.arch else None


def _plan_messages(project: Project, settings: Settings) -> tuple[list[str], set[str]]:
    problems: list[str] = []
    tools: set[str] = set()
    for run in project.runs:
        try:
            xml = run_arch_xml(settings, run)
        except ValueError as exc:
            problems.append(str(exc))
        else:
            if xml is not None and not xml.is_file():
                problems.append(f"arch file not found: {xml}")
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
    return problems, tools


def _resolves(path: str, root: Path) -> bool:
    if "/" not in path:
        return shutil.which(path) is not None
    full = root / path  # an absolute path stays as it is
    return full.is_file() and os.access(full, os.X_OK)


def _tool_messages(settings: Settings, tools: set[str], root: Path) -> list[str]:
    problems: list[str] = []
    for name in sorted(tools):
        try:
            path = tool_path(settings, name)
        except (ValueError, KeyError):
            continue  # already reported while planning (vtr_root) or not a setting
        if not _resolves(path, root):
            problems.append(f"tool {name!r} not found or not executable: {path}")
    return problems


def _systemd_messages() -> list[str]:
    if shutil.which("systemd-run") is None:
        return ["launcher is systemd but systemd-run is not on PATH"]
    try:
        done = subprocess.run(
            ["systemd-run", "--user", "--scope", "--quiet", "true"],
            capture_output=True,
            timeout=5,
        )
        failure = "" if done.returncode == 0 else f"exit code {done.returncode}"
    except (OSError, subprocess.SubprocessError) as exc:
        failure = type(exc).__name__
    if failure:
        return [
            f"launcher is systemd but `systemd-run --user --scope` failed ({failure}); "
            'set launcher = "plain" in machine.toml to run without memory caps'
        ]
    return []


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
    problems += _tool_messages(settings, tools, project.root)
    if settings.vtr_root is not None and not settings.vtr_root.is_dir():
        problems.append(f"vtr_root not found: {settings.vtr_root}")
    if settings.launcher == "systemd":
        problems += _systemd_messages()
    problems += _disk_message(settings)
    return list(dict.fromkeys(problems))
