"""Find the HDL source of a Mímir timing model (Qt-free).

A store names source files as ``$VTR_ROOT/vtr_flow/benchmarks/verilog/x.v`` (the design's
``origin``) and in the ``file:line`` span keys. The variable is expanded from the environment, then
from the machine settings; the file may lie outside the project (it is only read, never written).
"""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from wyrd.guimodel.heat import HeatModel

_VAR = re.compile(r"\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))")


def variables(name: str) -> list[str]:
    return [a or b for a, b in _VAR.findall(name)]


def expand(name: str, extra: Mapping[str, str] | None = None) -> str:
    """``name`` with ``$VAR`` and ``${VAR}`` replaced (environment first, then ``extra``);
    a variable that is set nowhere stays as written."""
    env = {**(extra or {}), **os.environ}

    def sub(m: re.Match[str]) -> str:
        key = m.group(1) or m.group(2)
        return env.get(key, m.group(0))

    return os.path.expanduser(_VAR.sub(sub, name))


def unset(name: str, extra: Mapping[str, str] | None = None) -> list[str]:
    env = {**(extra or {}), **os.environ}
    return [v for v in variables(name) if v not in env]


@dataclass(frozen=True)
class SourceChoice:
    path: Path | None
    guess: str  # best guess for a file dialog
    message: str  # what is missing, or what was opened
    name: str = ""  # the model's name for the file that was found


def _usable(text: str) -> Path | None:
    p = Path(text)
    return p if p.is_absolute() and p.is_file() else None


def _ranked_names(model: HeatModel) -> list[str]:
    counts = Counter(f.file for f in model.facts if f.file is not None)
    return [n for n, _ in counts.most_common()]


def _missing_text(name: str, extra: Mapping[str, str] | None) -> str:
    lost = unset(name, extra)
    if lost:
        return f"{name}: the environment variable {', '.join(lost)} is not set"
    return f"{name}: no such file (expanded to {expand(name, extra)})"


def find_source(
    model: HeatModel,
    extra_env: Mapping[str, str] | None = None,
    resolve: Callable[[str], Path | None] | None = None,
    chosen: Mapping[str, Path] | None = None,
) -> SourceChoice:
    """The best source file for ``model``: a path the user chose, the design origin, the files of
    the span rows, then the project resolver. Reports exactly what is missing otherwise."""
    names = _ranked_names(model)
    candidates = list(dict.fromkeys(([model.origin] if model.origin else []) + names))
    for name in candidates:
        if chosen and name in chosen:
            return SourceChoice(chosen[name], str(chosen[name]), "chosen file", name)
        found = _usable(expand(name, extra_env))
        if found is None and resolve is not None:
            found = resolve(name)
        if found is not None:
            return SourceChoice(found, str(found), f"opened {found}", name)
    if not candidates:
        return SourceChoice(None, "", "the run has no source file in its span rows or origin")
    first = candidates[0]
    problems = "; ".join(_missing_text(n, extra_env) for n in dict.fromkeys(candidates[:3]))
    return SourceChoice(None, expand(first, extra_env), f"source not found: {problems}", first)

