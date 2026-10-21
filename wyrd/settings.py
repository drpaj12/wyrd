"""Machine settings with precedence: default < machine < project < cli."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

from wyrd.units import parse_bytes

PROJECT_KEYS = {"step_timeout"}

_SIZE_FIELDS = {"mem_budget", "disk_min_free", "vpr_mem", "other_mem"}
_TABLE_OF = {
    "tools": ("tools", "vtr_root"),
    "resources": ("mem_budget", "jobs", "launcher", "disk_min_free", "disk_check_path"),
    "defaults": ("vpr_mem", "other_mem", "history_factor", "oom_retry_factor", "step_timeout"),
}


@dataclass(frozen=True)
class Settings:
    tools: dict[str, str]
    vtr_root: Path | None
    mem_budget: int
    jobs: int
    launcher: str
    disk_min_free: int
    disk_check_path: Path
    vpr_mem: int
    other_mem: int
    history_factor: float
    oom_retry_factor: float
    step_timeout: int
    sources: dict[str, str]


def machine_path() -> Path:
    env = os.environ.get("WYRD_CONFIG")
    return Path(env) if env else Path.home() / ".config" / "wyrd" / "machine.toml"


def total_memory() -> int:
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 8 * 2**30


def is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def _defaults() -> dict[str, object]:
    vtr = os.environ.get("VTR_ROOT")
    return {
        "tools": {"odin3": "odin3", "odin3_flow": "odin3-flow"},
        "vtr_root": vtr if vtr else None,
        "mem_budget": "60%",
        "jobs": max(1, (os.cpu_count() or 2) // 2),
        "launcher": "systemd",
        "disk_min_free": "20G",
        "disk_check_path": "/mnt/c" if is_wsl() else "/",
        "vpr_mem": "4G",
        "other_mem": "2G",
        "history_factor": 1.25,
        "oom_retry_factor": 2.0,
        "step_timeout": 3600,
    }


def _flatten_machine(data: dict[str, object]) -> dict[str, object]:
    out: dict[str, object] = {}
    for table, keys in _TABLE_OF.items():
        sub = data.get(table, {})
        if not isinstance(sub, dict):
            raise ValueError(f"machine.toml: [{table}] must be a table")
        for k, v in sub.items():
            if k not in keys and not (table == "tools" and isinstance(v, str)):
                raise ValueError(f"machine.toml: unknown key {k!r} in [{table}]")
            out[k] = v
    return out


def _merge_tools(base: dict[str, str], value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("tools must be a table")
    merged = dict(base)
    merged.update({str(k): str(v) for k, v in value.items()})
    return merged


def _flat_tools(layer: dict[str, object]) -> dict[str, object]:
    """Split tool names out of a flattened machine layer."""
    tools = {k: v for k, v in layer.items() if k not in _all_keys()}
    rest = {k: v for k, v in layer.items() if k in _all_keys()}
    if tools:
        rest["tools"] = tools
    return rest


def _all_keys() -> set[str]:
    return {k for keys in _TABLE_OF.values() for k in keys if k != "tools"}


def _read_machine(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return _flat_tools(_flatten_machine(data))


def _size(name: str, value: object, total: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name}: bad size {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return parse_bytes(value, total)
    raise ValueError(f"{name}: bad size {value!r}")


def _as_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name}: expected an integer, got {value!r}")
    return value


def _as_float(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: expected a number, got {value!r}")
    return float(value)


def load(project_run: dict[str, object] | None, cli: dict[str, object]) -> Settings:
    """Resolve settings from defaults, machine file, project [run] and cli."""
    if project_run:
        bad = sorted(set(project_run) - PROJECT_KEYS)
        if bad:
            raise ValueError(f"project [run] may not set {', '.join(bad)}")
    total = total_memory()
    values = _defaults()
    sources = {k: "default" for k in values}
    layers = [
        ("machine", _read_machine(machine_path())),
        ("project", dict(project_run or {})),
        ("cli", {k: v for k, v in cli.items() if v is not None}),
    ]
    for source, layer in layers:
        for k, v in layer.items():
            if k not in values:
                raise ValueError(f"{source}: unknown setting {k!r}")
            values[k] = _merge_tools(values[k], v) if k == "tools" else v  # type: ignore[arg-type]
            sources[k] = source
    return _build(values, sources, total)


def _build(values: dict[str, object], sources: dict[str, str], total: int) -> Settings:
    tools = values["tools"]
    assert isinstance(tools, dict)
    vtr = values["vtr_root"]
    return Settings(
        tools=dict(tools),
        vtr_root=Path(str(vtr)) if vtr else None,
        mem_budget=_size("mem_budget", values["mem_budget"], total),
        jobs=max(1, _as_int("jobs", values["jobs"])),
        launcher=str(values["launcher"]),
        disk_min_free=_size("disk_min_free", values["disk_min_free"], total),
        disk_check_path=Path(str(values["disk_check_path"])),
        vpr_mem=_size("vpr_mem", values["vpr_mem"], total),
        other_mem=_size("other_mem", values["other_mem"], total),
        history_factor=_as_float("history_factor", values["history_factor"]),
        oom_retry_factor=_as_float("oom_retry_factor", values["oom_retry_factor"]),
        step_timeout=_as_int("step_timeout", values["step_timeout"]),
        sources=sources,
    )


def _toml_value(v: object) -> str:
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return str(v)


def write_machine_file(path: Path) -> None:
    """Write machine.toml with values detected on this machine."""
    d = _defaults()
    tools = d["tools"]
    assert isinstance(tools, dict)
    lines = ["[tools]"]
    lines += [f"{k} = {_toml_value(v)}" for k, v in tools.items()]
    if d["vtr_root"]:
        lines.append(f"vtr_root = {_toml_value(d['vtr_root'])}")
    for table in ("resources", "defaults"):
        lines += ["", f"[{table}]"]
        lines += [f"{k} = {_toml_value(d[k])}" for k in _TABLE_OF[table]]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def field_names() -> list[str]:
    return [f.name for f in fields(Settings) if f.name != "sources"]
