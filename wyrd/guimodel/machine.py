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


@dataclass
class MachineValues:
    values: dict[str, str]
    extra_tools: dict[str, str] = field(default_factory=dict)


def _default_texts() -> dict[str, str]:
    d = settings.default_values()
    tools = d["tools"]
    assert isinstance(tools, dict)
    out: dict[str, str] = {}
    for f in FIELDS:
        if f.table == "tools" and f.key != "vtr_root":
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


def _line(f: Field, text: str) -> str:
    quoted = f.kind in ("str", "choice")
    return f"{f.key} = {json.dumps(text) if quoted else text}"


def render(v: MachineValues) -> str:
    """TOML text of the settings; empty ``vtr_root`` is left out."""
    lines: list[str] = []
    for table in ("tools", "resources", "defaults"):
        if lines:
            lines.append("")
        lines.append(f"[{table}]")
        for f in (x for x in FIELDS if x.table == table):
            text = v.values.get(f.name, "")
            if f.name == "tools.vtr_root" and not text:
                continue
            lines.append(_line(f, text))
        if table == "tools":
            lines += [f"{_key(k)} = {json.dumps(x)}" for k, x in v.extra_tools.items()]
    return "\n".join(lines) + "\n"


def _choice_error(v: MachineValues) -> str | None:
    for f in FIELDS:
        if f.kind == "choice" and v.values.get(f.name, "") not in f.choices:
            return f"{f.key}: must be one of {', '.join(f.choices)}"
    return None


def validate(v: MachineValues) -> str | None:
    """The error text ``settings.load`` gives for these values, or None when they are fine."""
    bad = _choice_error(v)
    if bad:
        return bad
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "machine.toml"
        probe.write_text(render(v), encoding="utf-8")
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
