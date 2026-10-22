"""The player's files under the data directory (spec 10)."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path

from wyrd.midgard.model import ASSETS
from wyrd.midgard.model.scores import ScoreTable
from wyrd.midgard.model.sensors import SensorSet


def default_data_dir(env: Mapping[str, str], home: Path) -> Path:
    if env.get("MIDGARD_HOME"):
        return Path(env["MIDGARD_HOME"])
    if env.get("XDG_DATA_HOME"):
        return Path(env["XDG_DATA_HOME"]) / "midgard"
    return home / ".local" / "share" / "midgard"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _write(path: Path, text: str) -> str | None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as e:
        return f"cannot write {path}: {e.strerror or e}"
    return None


class UserData:
    def __init__(self, root: Path, package_assets: Path | None = None) -> None:
        self.root = root
        self.assets = package_assets if package_assets is not None else ASSETS

    def level_dir(self, n: int) -> Path:
        return self.root / f"Lv{n}"

    def verilog_path(self, n: int, i: int) -> Path:
        return self.level_dir(n) / "VerilogFiles" / f"Traffic_signal_set_{i}.v"

    def verilog_paths(self, n: int, count: int) -> list[Path]:
        return [self.verilog_path(n, i) for i in range(count)]

    def ensure_level_files(self, n: int, count: int) -> list[Path]:
        paths = self.verilog_paths(n, count)
        for p in paths:
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.assets / "starter.v", p)
        return paths

    def load_sensors(self, n: int) -> SensorSet:
        return SensorSet.from_text(_read(self.level_dir(n) / "sensorFile.txt"))

    def save_sensors(self, n: int, sensors: SensorSet) -> str | None:
        return _write(self.level_dir(n) / "sensorFile.txt", sensors.to_text())

    def load_scores(self, n: int) -> ScoreTable:
        return ScoreTable.from_text(_read(self.level_dir(n) / "high_score.txt"))

    def save_scores(self, n: int, table: ScoreTable) -> str | None:
        return _write(self.level_dir(n) / "high_score.txt", table.to_text())

    def recordings_dir(self, n: int) -> Path:
        return self.level_dir(n) / "recordings"
