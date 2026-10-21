"""Generic command steps: odin3, vpr, abc, shell."""

from __future__ import annotations

import re
from pathlib import Path

from wyrd.model import Metric, RunSpec
from wyrd.settings import Settings
from wyrd.steps import arch_xml, finite_number, need_vtr_root, read_json_object, tool_path

_PLACEHOLDER = re.compile(r"\{(files|top|arch_xml|step_dir|vtr_root)\}")


class CommandStep:
    """One generic step class; `use` selects the tool whose path replaces the first word."""

    def __init__(self, use: str, argv: list[str]) -> None:
        self.name = use
        self.is_vpr = use == "vpr"
        self.tools: tuple[str, ...] = () if use == "shell" else (use,)
        self._argv = argv

    def command(
        self, run: RunSpec, step_dir: Path, settings: Settings
    ) -> tuple[list[str], dict[str, str]]:
        words: list[str] = []
        for word in self._argv:
            words.extend(_expand(word, self.name, run, step_dir, settings))
        if words and self.tools:
            words[0] = tool_path(settings, self.name)
        return words, {}

    def collect(self, step_dir: Path) -> list[Metric]:
        data = read_json_object(step_dir / "metrics.json")
        if data is None:
            return []
        out: list[Metric] = []
        for key, value in data.items():
            number = finite_number(value)
            if number is not None:
                out.append(Metric(str(key), number))
        return out


def _expand(word: str, step: str, run: RunSpec, step_dir: Path, settings: Settings) -> list[str]:
    if word == "{files}":
        return [str(f) for f in run.design.files]

    def sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key == "files":
            raise ValueError(f"step {step!r}: {{files}} must be a whole argv word")
        if key == "top":
            if not run.design.top:
                raise ValueError(f"step {step!r}: {{top}} used but design has no top")
            return run.design.top
        if key == "arch_xml":
            return str(arch_xml(settings, run.arch))
        if key == "vtr_root":
            return str(need_vtr_root(settings))
        return str(step_dir)

    return [_PLACEHOLDER.sub(sub, word)]
