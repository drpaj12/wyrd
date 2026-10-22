"""Load and validate ``wyrd.toml`` and expand its sweep into runs (W1 spec section 3)."""

from __future__ import annotations

import glob
import itertools
import os
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
        self.lines = text.splitlines()

    def _headers(self, pattern: str) -> list[int]:
        hdr = re.compile(pattern)
        return [i for i, ln in enumerate(self.lines) if hdr.match(ln)]

    def _block_key(self, start: int, key: str | None) -> int:
        """Line index of ``key =`` inside the block opened at ``start``; else ``start``."""
        if key is None:
            return start
        pat = re.compile(rf"^\s*[\"']?{re.escape(key)}[\"']?\s*=")
        for i in range(start + 1, len(self.lines)):
            if re.match(r"^\s*\[", self.lines[i]):
                break
            if pat.match(self.lines[i]):
                return i
        return start

    def _mk(self, idx: int | None, msg: str) -> ConfigError:
        return ConfigError(self.path, None if idx is None else idx + 1, msg)

    def err_header(self, pattern: str, key: str | None, msg: str, nth: int = 0) -> ConfigError:
        """Error at ``key`` inside the nth block whose header matches ``pattern``."""
        found = self._headers(pattern)
        if nth >= len(found):
            return self._mk(None, msg)
        return self._mk(self._block_key(found[nth], key), msg)

    def err_project(self, key: str | None, msg: str) -> ConfigError:
        return self.err_header(r"^\s*\[\s*project\s*\]", key, msg)

    def err_sweep(self, key: str | None, msg: str) -> ConfigError:
        return self.err_header(r"^\s*\[\s*sweep\s*\]", key, msg)

    def err_recipe(self, name: str, key: str | None, msg: str) -> ConfigError:
        q = re.escape(name)
        pat = rf"^\s*\[\s*recipe\s*\.\s*[\"']?{q}[\"']?\s*(\]|\.)"
        return self.err_header(pat, key, msg)

    def err_design(self, nth: int, key: str | None, msg: str) -> ConfigError:
        return self.err_header(r"^\s*\[\[\s*design\s*\]\]", key, msg, nth)

    def err_top(self, key: str, msg: str) -> ConfigError:
        """Error at a top-level ``key`` line or ``[key`` header."""
        pat = re.compile(rf"^\s*(\[+\s*{re.escape(key)}\b|{re.escape(key)}\s*=)")
        for i, ln in enumerate(self.lines):
            if pat.match(ln):
                return self._mk(i, msg)
        return self._mk(None, msg)


def _table(ctx: _Ctx, data: dict[str, object], key: str) -> dict[str, object]:
    val = data.get(key, {})
    if not isinstance(val, dict):
        raise ctx.err_top(key, f"'{key}' must be a table")
    return val


def _is_str_list(val: object) -> bool:
    return isinstance(val, list) and all(isinstance(v, str) for v in val)


_UNSET = re.compile(r"\$(\w+|\{[^}]*\})")


def _glob(root: Path, pattern: str) -> list[str] | str:
    """Expand ``pattern``; return matches, or the name of an unset variable."""
    pat = os.path.expandvars(pattern)
    m = _UNSET.search(pat)
    if m:
        return m.group(0)
    if not os.path.isabs(pat):
        pat = str(root / pat)
    return glob.glob(pat, recursive=True)


def _load_design(ctx: _Ctx, root: Path, nth: int, raw: object) -> Design:
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
        raise ctx.err_design(nth, "name", "each [[design]] needs a string 'name'")
    name = str(raw["name"])
    if "files" not in raw:
        raise ctx.err_design(nth, None, f"design '{name}' needs 'files'")
    pats = raw["files"]
    if not _is_str_list(pats):
        raise ctx.err_design(nth, "files", f"design '{name}' files must be a list of strings")
    found: set[Path] = set()
    for pat in pats:
        res = _glob(root, str(pat))
        if isinstance(res, str):
            raise ctx.err_design(
                nth, "files", f"design '{name}': environment variable {res} is not set"
            )
        found.update(Path(p).resolve() for p in res if os.path.isfile(p))
        if not res:
            raise ctx.err_design(
                nth, "files", f"design '{name}': files pattern '{pat}' matches no files"
            )
    if not found:
        raise ctx.err_design(nth, "files", f"design '{name}': files matches no files")
    top = raw.get("top")
    if top is not None and not isinstance(top, str):
        raise ctx.err_design(nth, "top", f"design '{name}': top must be a string")
    return Design(name=name, files=tuple(sorted(found)), top=top)


def _load_recipe(ctx: _Ctx, name: str, raw: object) -> Recipe:
    steps_raw = raw.get("steps") if isinstance(raw, dict) else None
    if not isinstance(steps_raw, list) or not steps_raw:
        raise ctx.err_recipe(name, "steps", f"recipe '{name}' needs a non-empty 'steps' list")
    steps: list[StepSpec] = []
    for s in steps_raw:
        if not isinstance(s, dict) or not isinstance(s.get("use"), str):
            raise ctx.err_recipe(
                name, "steps", f"recipe '{name}': each step needs a string 'use'"
            )
        args = {k: v for k, v in s.items() if k != "use"}
        steps.append(StepSpec(use=str(s["use"]), args=args))
    return Recipe(name=name, steps=tuple(steps))


def _axis(
    ctx: _Ctx, sweep: dict[str, object], key: str, known: dict[str, object] | None
) -> list[str]:
    if key not in sweep:
        raise ctx.err_sweep(None, f"[sweep] needs '{key}'")
    val = sweep[key]
    if not isinstance(val, list) or not _is_str_list(val):
        raise ctx.err_sweep(key, f"[sweep] {key} must be a list of strings")
    if not val:
        raise ctx.err_sweep(key, f"[sweep] {key} must not be empty")
    vals = [str(v) for v in val]
    for v in vals:
        if known is not None and v not in known:
            raise ctx.err_sweep(key, f"[sweep] {key}: unknown {key} '{v}'")
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
            raise ctx.err_sweep(k, f"[sweep] {k} must be a list")
        if not v:
            raise ctx.err_sweep(k, f"[sweep] {k} must not be empty")
        plists.append(list(v))
    runs = []
    for r, d, a in itertools.product(rec, des, arch):
        for combo in itertools.product(*plists):
            runs.append(RunSpec(designs[d], a, recipes[r], dict(zip(pkeys, combo, strict=True))))
    return tuple(runs)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ConfigError(path, None, f"project file is not valid UTF-8: {e.reason}") from e
    except OSError as e:
        raise ConfigError(path, None, f"cannot read project file: {e.strerror}") from e


def load_project(path: Path, text: str | None = None) -> Project:
    """Validate the project at ``path``; raise ConfigError on any problem.

    ``text`` replaces the file content when given (an editor buffer); ``path`` still
    anchors relative file patterns and error messages.
    """
    if text is None:
        text = _read_text(path)
    ctx = _Ctx(path, text)
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        m = re.search(r"\(at line (\d+)", str(e))
        raise ConfigError(path, int(m.group(1)) if m else None, str(e)) from e
    root = path.resolve().parent
    proj = _table(ctx, data, "project")
    name = proj.get("name")
    if not isinstance(name, str):
        raise ctx.err_project(None, "[project] needs a string 'name'")
    designs: dict[str, Design] = {}
    raw_designs = data.get("design", [])
    if not isinstance(raw_designs, list) or not all(isinstance(d, dict) for d in raw_designs):
        raise ctx.err_top("design", "'design' must be an array of tables ([[design]])")
    for n, raw in enumerate(raw_designs):
        d = _load_design(ctx, root, n, raw)
        if d.name in designs:
            raise ctx.err_design(n, "name", f"duplicate design name '{d.name}'")
        designs[d.name] = d
    recipes = {k: _load_recipe(ctx, k, v) for k, v in _table(ctx, data, "recipe").items()}
    runs = _expand(ctx, designs, recipes, _table(ctx, data, "sweep"))
    return Project(root, name, designs, recipes, dict(_table(ctx, data, "run")), runs)
