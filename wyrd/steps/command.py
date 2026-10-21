"""Generic command steps: odin3, vpr, abc, shell."""

from __future__ import annotations

import json
from pathlib import Path

from wyrd.model import Metric, RunSpec
from wyrd.settings import Settings
from wyrd.steps import arch_xml, tool_path


def _argv_template(run: RunSpec, use: str) -> list[str]:
    for spec in run.recipe.steps:
        if spec.use == use:
            raw = spec.args.get("argv")
            if isinstance(raw, list) and all(isinstance(w, str) for w in raw):
                return [str(w) for w in raw]
    raise ValueError(f"step {use!r}: args.argv must be a list of strings")


class CommandStep:
    """One generic step class; `use` selects the tool whose path replaces the first word."""

    def __init__(self, use: str, argv: list[str] | None = None) -> None:
        self.name = use
        self.is_vpr = use == "vpr"
        self.tools: tuple[str, ...] = () if use == "shell" else (use,)
        self._argv = argv

    def command(
        self, run: RunSpec, step_dir: Path, settings: Settings
    ) -> tuple[list[str], dict[str, str]]:
        template = self._argv if self._argv is not None else _argv_template(run, self.name)
        words: list[str] = []
        for word in template:
            words.extend(_expand(word, run, step_dir, settings))
        if words and self.tools:
            words[0] = tool_path(settings, self.name)
        return words, {}

    def collect(self, step_dir: Path) -> list[Metric]:
        path = step_dir / "metrics.json"
        if not path.is_file():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return []
        return [
            Metric(str(k), float(v))
            for k, v in data.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        ]


def _expand(word: str, run: RunSpec, step_dir: Path, settings: Settings) -> list[str]:
    if word == "{files}":
        return [str(f) for f in run.design.files]
    if "{arch_xml}" in word:
        word = word.replace("{arch_xml}", str(arch_xml(settings, run.arch)))
    if "{vtr_root}" in word:
        word = word.replace("{vtr_root}", str(settings.vtr_root))
    return [word.replace("{top}", run.design.top or "").replace("{step_dir}", str(step_dir))]
