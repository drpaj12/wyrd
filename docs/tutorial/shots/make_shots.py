"""Regenerate the tutorial's screenshots and pasted command output, all from real runs.

    python make_shots.py WORK_DIR

Needs on this machine: the wyrd venv (PySide6, pygame-ce, odin3 with the simulation API), `odin3`
and `odin3-flow` on PATH, PYTHONPATH and ODIN3_LIB for the odin3 Python package, and VTR (the
machine file `wyrd config init` writes takes it from $VTR_ROOT). Typical call:

    O=~/odin3-ws/odin3
    PATH=$O/build/release:$O/tools/flow:$PATH PYTHONPATH=$O/plugins/python \\
      ODIN3_LIB=$O/build/release/libodin3.so VTR_ROOT=~/odin3-ws/external/vtr-verilog-to-routing \\
      python make_shots.py /tmp/claude-1000/wdoc-tutorial

Output: ../images/*.png (screenshots) and ../transcripts/*.txt (command output). WORK_DIR is
wiped first. In the transcripts WORK_DIR/demo is printed as ~/wyrd-demo and nothing else is
edited. The samples commands are shown with `--project samples` but run inside the copy, which
gives the same output.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TUTORIAL = HERE.parent
IMAGES = TUTORIAL / "images"
TRANSCRIPTS = TUTORIAL / "transcripts"


class Work:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.demo = root / "demo"
        self.env = dict(os.environ, WYRD_CONFIG=str(root / "machine.toml"))

    def run(self, argv: list[str], cwd: Path, name: str, shown: str | None = None) -> str:
        """Run argv, save `$ shown` and its output as transcripts/NAME.txt; return the output."""
        proc = subprocess.run(argv, cwd=cwd, env=self.env, capture_output=True, text=True,
                              check=False)
        text = (proc.stdout + proc.stderr).replace(str(self.demo), "~/wyrd-demo")
        text = text.replace(str(self.root / "machine.toml"), "~/.config/wyrd/machine.toml")
        line = shown if shown is not None else " ".join(argv)
        TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
        (TRANSCRIPTS / f"{name}.txt").write_text(f"$ {line}\n{text}", encoding="utf-8")
        print(f"transcript {name} (exit {proc.returncode})")
        return text


def wyrd(*args: str) -> list[str]:
    return [sys.executable, "-m", "wyrd.cli", *args]


def cli_part(w: Work) -> str:
    w.run(wyrd("config", "init"), w.root, "config-init", "wyrd config init")
    w.run(wyrd("config", "show"), w.root, "config-show", "wyrd config show")
    shutil.copytree(TUTORIAL / "project" / "src", w.demo / "src")
    w.run(wyrd("init", str(w.demo)), w.root, "init", "wyrd init ~/wyrd-demo")
    shutil.copy(TUTORIAL / "project" / "wyrd.toml", w.demo / "wyrd.toml")  # the edited file
    out = w.run(wyrd("run", "--progress"), w.demo, "run", "wyrd run --progress")
    w.run(wyrd("status"), w.demo, "status", "wyrd status")
    w.run(wyrd("table"), w.demo, "table", "wyrd table")
    w.run(wyrd("table", "--metrics", "luts,clbs,crit_path_ns"), w.demo, "table-small",
          "wyrd table --metrics luts,clbs,crit_path_ns")
    w.run(wyrd("table", "--metrics", "luts,clbs,crit_path_ns", "--format", "csv"), w.demo,
          "table-csv", "wyrd table --metrics luts,clbs,crit_path_ns --format csv")
    key = next(line.split()[-1] for line in out.splitlines() if line.startswith("ok "))
    w.run(wyrd("script", key), w.demo, "script", f"wyrd script {key}")
    w.run(["find", "runs", "-maxdepth", "4", "-not", "-path", "*/out/*"], w.demo, "run-dir",
          "find runs -maxdepth 4")
    summary = next(w.demo.glob("runs/*/EArch/*/0-odin3-flow/out/summary.json"))
    TRANSCRIPTS.joinpath("summary.txt").write_text(
        f"$ cat runs/counteradd/EArch/{summary.parts[-4]}/0-odin3-flow/out/summary.json\n"
        + summary.read_text(encoding="utf-8"), encoding="utf-8")
    return key


def fail_part(w: Work) -> None:
    """A module named like a hard cell: the real Odin III error, run straight from odin3-flow."""

    scratch = w.root / "bad"
    shutil.copytree(TUTORIAL / "project" / "src", scratch / "src")
    (scratch / "src" / "add4.v").rename(scratch / "src" / "adder.v")
    (scratch / "src" / "adder.v").write_text(
        (scratch / "src" / "adder.v").read_text(encoding="utf-8").replace("add4", "adder"),
        encoding="utf-8")
    top = scratch / "src" / "top.v"
    top.write_text(top.read_text(encoding="utf-8").replace("add4 ", "adder"), encoding="utf-8")
    files = ["src/adder.v", "src/counter.v", "src/top.v"]
    cmd = ["odin3-flow", *files, "--top", "top", "--target", "vtr", "--no-vpr", "--out", "out"]
    text = subprocess.run(cmd, cwd=scratch, env=w.env, capture_output=True, text=True,
                          check=False)
    log = (scratch / "out" / "odin3" / "odin3.log").read_text(encoding="utf-8").splitlines()
    errors = [line for line in log if "error" in line]
    shown = " ".join(cmd)
    body = (text.stdout + text.stderr).replace(str(scratch), ".")
    TRANSCRIPTS.joinpath("bad-module.txt").write_text(
        f"$ {shown}\n{body}$ grep error out/odin3/odin3.log\n"
        + "\n".join(e.replace(str(scratch), ".") for e in errors) + "\n", encoding="utf-8")
    print("transcript bad-module")


def compare_part(w: Work) -> None:
    """The same project with a registered output, run in demo2, compared with demo."""
    v2 = w.root / "demo2"
    shutil.copytree(w.demo / "src", v2 / "src")
    shutil.copy(w.demo / "wyrd.toml", v2 / "wyrd.toml")
    shutil.copy(TUTORIAL / "project" / "variants" / "top_registered.v", v2 / "src" / "top.v")
    w.run(wyrd("run"), v2, "run-v2", "wyrd run")
    w.run(wyrd("compare", "../wyrd-demo", ".", "--metrics", "luts,clbs,crit_path_ns"), v2,
          "compare", "wyrd compare ~/wyrd-demo ~/wyrd-demo2 --metrics luts,clbs,crit_path_ns")


def samples_part(w: Work) -> Path:
    """The shipped samples, run in a copy so the repository stays clean."""
    scratch = w.root / "samples"
    shutil.copytree(TUTORIAL.parent.parent / "samples", scratch,
                    ignore=shutil.ignore_patterns("expected", "make-expected", "__pycache__"))
    w.run(wyrd("run"), scratch, "samples-run", "wyrd run --project samples")
    w.run(wyrd("table", "--metrics", "luts,clbs,hard_blocks.memory,hard_blocks.mult_36"),
          scratch, "samples-table",
          "wyrd table --project samples --metrics luts,clbs,hard_blocks.memory,hard_blocks.mult_36")
    return scratch


def sim_part(w: Work) -> None:
    files = ["src/add4.v", "src/counter.v", "src/top.v"]
    w.run(wyrd("sim", *files, "--top", "top", "--random", "6", "--seed", "3",
               "--vcd", "counteradd.vcd", "--save-vectors", "counteradd.vec"),
          w.demo, "sim", "wyrd sim src/*.v --top top --random 6 --seed 3 --vcd counteradd.vcd "
          "--save-vectors counteradd.vec")
    vec = (w.demo / "counteradd.vec").read_text(encoding="utf-8")
    TRANSCRIPTS.joinpath("vectors.txt").write_text("$ cat counteradd.vec\n" + vec, encoding="utf-8")
    vcd = (w.demo / "counteradd.vcd").read_text(encoding="utf-8").splitlines()[:24]
    TRANSCRIPTS.joinpath("vcd.txt").write_text(
        "$ head -24 counteradd.vcd\n" + "\n".join(vcd) + "\n", encoding="utf-8")


def child(script: str, *args: str, env: dict[str, str]) -> None:
    subprocess.run([sys.executable, str(HERE / script), *args], check=True, env=env)


def main(root: Path) -> int:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    w = Work(root)
    IMAGES.mkdir(parents=True, exist_ok=True)
    cli_part(w)
    compare_part(w)
    samples = samples_part(w)
    child("gui_shots.py", str(w.demo), str(IMAGES), str(samples),
          env=dict(w.env, QT_QPA_PLATFORM="offscreen"))
    sim_part(w)
    fail_part(w)
    data = root / "midgard"
    sdl = dict(w.env, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    child("midgard_shots.py", str(data), str(IMAGES), env=sdl)
    child("editor_shots.py", str(data), str(IMAGES), env=dict(w.env, QT_QPA_PLATFORM="offscreen"))
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
