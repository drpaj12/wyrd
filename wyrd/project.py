"""Load and validate ``wyrd.toml`` and expand its sweep into runs (W1 spec section 3)."""

from __future__ import annotations

import itertools
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from wyrd.model import Design, Recipe, RunSpec, StepSpec

_AXES = ("recipe", "design", "arch")


class ConfigError(Exception):
    """A project file error; ``str()`` is ``<path>:<line>: <msg>`` or ``<path>: <msg>``."""

    def __init__(self, path: Path, line: int | None, msg: str) -> None:
        self.path = path
        self.line = line
        self.msg = msg
        where = f"{path}:{line}" if line is not None else f"{path}"
        super().__init__(f"{where}: {msg}")


@dataclass(frozen=True)
class Project:
    """A loaded project: designs, recipes, run settings and the expanded runs."""

    root: Path
    name: str
    designs: dict[str, Design]
    recipes: dict[str, Recipe]
    run: dict[str, object]
    runs: tuple[RunSpec, ...]


class _Ctx:
    """The file being loaded, for errors with line numbers."""

    def __init__(self, path: Path, text: str) -> None:
        self.path = path
        self.text = text

    def err(self, key: str, msg: str, after: str | None = None) -> ConfigError:
        """Build a ConfigError at the first line matching ``key`` (after a ``[after]`` header)."""
        lines = self.text.splitlines()
        start = 0
        if after is not None:
            hdr = re.compile(rf"^\s*\[+\s*{re.escape(after)}\b")
            start = next((i for i, ln in enumerate(lines) if hdr.match(ln)), 0)
        pat = re.compile(rf"^\s*(\[+[^\]]*{re.escape(key)}|{re.escape(key)}\s*=)")
        for i in range(start, len(lines)):
            if pat.match(lines[i]):
                return ConfigError(self.path, i + 1, msg)
        return ConfigError(self.path, None, msg)


def _table(ctx: _Ctx, data: dict[str, object], key: str) -> dict[str, object]:
    val = data.get(key, {})
    if not isinstance(val, dict):
        raise ctx.err(key, f"'{key}' must be a table")
    return val


def _str_list(ctx: _Ctx, val: object, key: str, what: str) -> list[str]:
    if not isinstance(val, list) or not all(isinstance(v, str) for v in val):
        raise ctx.err(key, f"{what} must be a list of strings")
    return [str(v) for v in val]


def _load_design(ctx: _Ctx, root: Path, raw: object) -> Design:
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
        raise ctx.err("design", "each [[design]] needs a string 'name'")
    name = str(raw["name"])
    pats = _str_list(ctx, raw.get("files", []), "files", f"design '{name}' files")
    found: set[Path] = set()
    for pat in pats:
        found.update(p.resolve() for p in root.glob(pat) if p.is_file())
    if not found:
        raise ctx.err("files", f"design '{name}': files matches no files")
    top = raw.get("top")
    if top is not None and not isinstance(top, str):
        raise ctx.err("top", f"design '{name}': top must be a string")
    return Design(name=name, files=tuple(sorted(found)), top=top)


def _load_recipe(ctx: _Ctx, name: str, raw: object) -> Recipe:
    steps_raw = raw.get("steps") if isinstance(raw, dict) else None
    if not isinstance(steps_raw, list) or not steps_raw:
        raise ctx.err(name, f"recipe '{name}' needs a non-empty 'steps' list")
    steps: list[StepSpec] = []
    for s in steps_raw:
        if not isinstance(s, dict) or not isinstance(s.get("use"), str):
            raise ctx.err(name, f"recipe '{name}': each step needs a string 'use'")
        args = {k: v for k, v in s.items() if k != "use"}
        steps.append(StepSpec(use=str(s["use"]), args=args))
    return Recipe(name=name, steps=tuple(steps))


def _axis(
    ctx: _Ctx, sweep: dict[str, object], key: str, known: dict[str, object] | None
) -> list[str]:
    if key not in sweep:
        raise ctx.err("sweep", f"[sweep] needs '{key}'")
    vals = _str_list(ctx, sweep[key], key, f"[sweep] {key}")
    for v in vals:
        if known is not None and v not in known:
            raise ctx.err(key, f"[sweep] {key}: unknown {key} '{v}'", after="sweep")
    return vals


def _expand(
    ctx: _Ctx, designs: dict[str, Design], recipes: dict[str, Recipe], sweep: dict[str, object]
) -> tuple[RunSpec, ...]:
    rec = _axis(ctx, sweep, "recipe", dict(recipes))
    des = _axis(ctx, sweep, "design", dict(designs))
    arch = _axis(ctx, sweep, "arch", None)
    pkeys = [k for k in sweep if k not in _AXES]
    plists: list[list[object]] = []
    for k in pkeys:
        v = sweep[k]
        if not isinstance(v, list):
            raise ctx.err(k, f"[sweep] {k} must be a list", after="sweep")
        plists.append(list(v))
    runs = []
    for r, d, a in itertools.product(rec, des, arch):
        for combo in itertools.product(*plists):
            runs.append(RunSpec(designs[d], a, recipes[r], dict(zip(pkeys, combo, strict=True))))
    return tuple(runs)


def load_project(path: Path) -> Project:
    """Read ``path`` and return the validated project; raise ConfigError on any problem."""
    try:
        text = path.read_text()
    except OSError as e:
        raise ConfigError(path, None, f"cannot read project file: {e.strerror}") from e
    ctx = _Ctx(path, text)
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        m = re.search(r"\(at line (\d+)", str(e))
        raise ConfigError(path, int(m.group(1)) if m else None, str(e)) from e
    root = path.parent
    proj = _table(ctx, data, "project")
    name = proj.get("name")
    if not isinstance(name, str):
        raise ctx.err("project", "[project] needs a string 'name'")
    designs: dict[str, Design] = {}
    raw_designs = data.get("design", [])
    for raw in raw_designs if isinstance(raw_designs, list) else []:
        d = _load_design(ctx, root, raw)
        designs[d.name] = d
    recipes = {k: _load_recipe(ctx, k, v) for k, v in _table(ctx, data, "recipe").items()}
    runs = _expand(ctx, designs, recipes, _table(ctx, data, "sweep"))
    return Project(root, name, designs, recipes, dict(_table(ctx, data, "run")), runs)
