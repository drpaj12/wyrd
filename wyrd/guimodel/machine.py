"""Model of the machine settings form: fields, TOML rendering and validation (spec section 11)."""

from __future__ import annotations

import json
import re
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from wyrd import settings

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_INT = re.compile(r"^-?(0|[1-9][0-9]*)$")
_FLOAT = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$")


@dataclass(frozen=True)
class Field:
    table: str
    key: str
    kind: str  # str, int, float or choice
    choices: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return f"{self.table}.{self.key}"


FIELDS: tuple[Field, ...] = (
    Field("tools", "odin3", "str"),
    Field("tools", "odin3_flow", "str"),
    Field("tools", "vtr_root", "str"),
    Field("tools", "vpr_gui", "str"),
    Field("resources", "mem_budget", "str"),
    Field("resources", "jobs", "int"),
    Field("resources", "launcher", "choice", ("systemd", "plain")),
    Field("resources", "disk_min_free", "str"),
    Field("resources", "disk_check_path", "str"),
    Field("defaults", "vpr_mem", "str"),
    Field("defaults", "other_mem", "str"),
    Field("defaults", "history_factor", "float"),
    Field("defaults", "oom_retry_factor", "float"),
    Field("defaults", "step_timeout", "int"),
)


_OPTIONAL_TOOLS = ("vtr_root", "vpr_gui")


@dataclass
class MachineValues:
    values: dict[str, str]
    extra_tools: dict[str, str] = field(default_factory=dict)


def _default_texts() -> dict[str, str]:
    d = settings.default_values()
    tools = d["tools"]
    if not isinstance(tools, dict):
        raise TypeError("settings.default_values()['tools'] is not a table")
    out: dict[str, str] = {}
    for f in FIELDS:
        if f.table == "tools" and f.key not in _OPTIONAL_TOOLS:
            out[f.name] = str(tools.get(f.key, ""))
        else:
            val = d.get(f.key)
            out[f.name] = "" if val is None else str(val)
    return out


def _overlay(values: dict[str, str], extra: dict[str, str], data: dict[str, object]) -> None:
    known = {f.name for f in FIELDS}
    for table in ("tools", "resources", "defaults"):
        sub = data.get(table, {})
        if not isinstance(sub, dict):
            continue
        for key, val in sub.items():
            name = f"{table}.{key}"
            if name in known:
                values[name] = str(val)
            elif table == "tools" and isinstance(val, str):
                extra[str(key)] = val


def read_values(path: Path) -> MachineValues:
    """Defaults overlaid by the file at ``path``; a missing file gives the defaults.

    A file that is not valid TOML raises ``tomllib.TOMLDecodeError``.
    """
    values = _default_texts()
    extra: dict[str, str] = {}
    if path.is_file():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        _overlay(values, extra, data)
    return MachineValues(values, extra)


def _key(key: str) -> str:
    return key if _BARE_KEY.match(key) else json.dumps(key)


def _unsafe(text: str) -> bool:
    return any(c in text for c in "\n\r\"'")


def _line(f: Field, text: str) -> str:
    if _unsafe(text):
        raise ValueError(f"{f.key}: must not contain a newline or a quote")
    if f.kind in ("str", "choice"):
        return f"{f.key} = {json.dumps(text)}"
    pattern = _INT if f.kind == "int" else _FLOAT
    kind = "an integer" if f.kind == "int" else "a number"
    if not pattern.match(text.strip()):
        raise ValueError(f"{f.key}: must be {kind}, got {text!r}")
    return f"{f.key} = {text.strip()}"


def _extra_line(key: str, value: str) -> str:
    if _unsafe(key) or _unsafe(value):
        raise ValueError(f"tools.{key}: must not contain a newline or a quote")
    return f"{_key(key)} = {json.dumps(value)}"


def render(v: MachineValues) -> str:
    """TOML text of the settings; empty ``vtr_root`` and ``vpr_gui`` are left out.

    Raise ValueError for a number field that is empty or not a number, and for any value with a
    newline or a quote, so no value can inject TOML.
    """
    lines: list[str] = []
    for table in ("tools", "resources", "defaults"):
        if lines:
            lines.append("")
        lines.append(f"[{table}]")
        for f in (x for x in FIELDS if x.table == table):
            text = v.values.get(f.name, "")
            if f.key in _OPTIONAL_TOOLS and f.table == "tools" and not text:
                continue
            lines.append(_line(f, text))
        if table == "tools":
            lines += [_extra_line(k, x) for k, x in v.extra_tools.items()]
    return "\n".join(lines) + "\n"


def _choice_error(v: MachineValues) -> str | None:
    for f in FIELDS:
        if f.kind == "choice" and v.values.get(f.name, "") not in f.choices:
            return f"{f.key}: must be one of {', '.join(f.choices)}"
    return None


def validate(v: MachineValues) -> str | None:
    """The first error found in these values, or None when they are fine.

    Checks the launcher choice here (``settings.load`` does not), then the number and text
    rules of ``render``, then the error text ``settings.load`` gives.
    """
    bad = _choice_error(v)
    if bad:
        return bad
    try:
        text = render(v)
    except ValueError as e:
        return str(e)
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "machine.toml"
        probe.write_text(text, encoding="utf-8")
        try:
            settings.load(None, {}, machine_file=probe)
        except ValueError as e:
            return str(e)
    return None


def save(path: Path, v: MachineValues) -> None:
    """Write the settings to ``path`` after validating; raise ValueError with the reason."""
    error = validate(v)
    if error is not None:
        raise ValueError(error)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(v), encoding="utf-8")
