"""Acceptance: `wyrd table` on the samples equals `odin3-flow` run directly (samples/expected)."""

import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from wyrd import report

ROOT = Path(__file__).parent.parent
SAMPLES = ROOT / "samples"


def _wyrd(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "wyrd.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
        check=False,
    )


def _machine_file(path: Path, vtr_root: str, env: dict[str, str]) -> None:
    init = _wyrd(["config", "init"], env)
    if init.returncode != 0:
        raise RuntimeError(init.stderr)
    wanted = {
        "odin3": str(shutil.which("odin3")),
        "odin3_flow": str(shutil.which("odin3-flow")),
        "vtr_root": vtr_root,
    }
    lines = []
    seen: set[str] = set()
    tools_at: int | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0].strip()
        if key in wanted:
            seen.add(key)
            line = f'{key} = "{wanted[key]}"'
        lines.append(line)
        if line.strip() == "[tools]":
            tools_at = len(lines)
    missing = [f'{key} = "{value}"' for key, value in wanted.items() if key not in seen]
    if tools_at is None:  # no [tools] table at all
        lines += ["[tools]", *missing]
    else:  # keys config init left out (e.g. vtr_root without VTR_ROOT)
        lines[tools_at:tools_at] = missing
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _odin3_version() -> str:
    """The version of the odin3 the machine file names (the one on PATH)."""
    proc = subprocess.run([str(shutil.which("odin3")), "--version"], capture_output=True, text=True,
                          check=False)
    return proc.stdout.splitlines()[0] if proc.stdout else "unknown"


class SamplesMatch(unittest.TestCase):
    def test_samples_match(self) -> None:
        vtr_root = os.environ.get("VTR_ROOT", "")
        if shutil.which("odin3-flow") is None or shutil.which("odin3") is None:
            self.skipTest("odin3-flow and odin3 are not on PATH")
        if not vtr_root or not Path(vtr_root).is_dir():
            self.skipTest("VTR_ROOT is not set to a directory")
        expected = {
            arch.stem: json.loads(arch.read_text(encoding="utf-8"))
            for arch in sorted((SAMPLES / "expected").glob("*.json"))
        }
        version = {d["odin3_version"] for d in expected.values()}
        if version != {_odin3_version()}:
            self.skipTest(f"odin3 is {_odin3_version()!r}, expected files are from {version}")
        with tempfile.TemporaryDirectory() as tmp:
            self._compare(Path(tmp), vtr_root, expected)

    def _compare(self, tmp: Path, vtr_root: str, expected: dict[str, dict[str, object]]) -> None:
        config = tmp / "machine.toml"
        env = {**os.environ, "WYRD_CONFIG": str(config), "VTR_ROOT": vtr_root}
        _machine_file(config, vtr_root, env)
        project = tmp / "samples"
        skip = shutil.ignore_patterns("expected", "make-expected")
        shutil.copytree(SAMPLES, project, ignore=skip)
        ran = _wyrd(["run", "--project", str(project)], env)
        self.assertIn(ran.returncode, (0, 1), ran.stderr)
        table = _wyrd(["table", "--project", str(project), "--format", "csv"], env)
        self.assertEqual(table.returncode, 0, table.stderr)
        rows = list(csv.DictReader(io.StringIO(table.stdout)))
        self.assertEqual(len(rows), sum(len(v) - 1 for v in expected.values()))
        for row in rows:
            want = expected[row["arch"]][row["design"]]
            assert isinstance(want, dict)
            self._check_row(row, want)

    def _check_row(self, row: dict[str, str], want: dict[str, object]) -> None:
        label = f"{row['design']} on {row['arch']}"
        self.assertEqual(row["status"], want["status"], label)
        for name, value in want.items():
            if name == "status" or re.match(r"seconds\.", name):
                continue
            self.assertEqual(row[name], report.number(value), f"{label}: {name}")
        if want["status"] == "ok":
            extra = {k for k, v in row.items() if v and not k.startswith("seconds.")}
            known = {"design", "arch", "status", *want}
            self.assertEqual(extra - known, set(), label)


if __name__ == "__main__":
    unittest.main()
