"""Floorplan pictures for the GUI tutorial, made by VPR itself (no window grab).

A window grab of VPR's OpenGL window is black under WSLg. VPR can draw to a file instead: with
`--disp off` it renders offscreen and `--graphics_commands` saves PNGs. The command line is the
one the Floorplan button builds (wyrd.guimodel.floorplan.plan_floorplan) with the viewer options
replaced. The block and net views have no routing wires: VPR draws those only through the
Routing switch of the live window, which no command sets. The routed picture shows the critical
path (`set_cpd 7`), which is drawn from the routed design.

    python floorplan_shots.py VPR_GUI RUN_DIR OUT_DIR

RUN_DIR is a finished run directory (runs/<design>/<arch>/<hash>). Writes gt-fp-place.png,
gt-fp-nets.png and gt-fp-cpd.png into OUT_DIR.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from wyrd.guimodel.floorplan import FloorplanPlan, plan_floorplan

_VIEW = {"--disp", "--graphics_pause", "--route", "--max_router_iterations"}


def base_args(plan: FloorplanPlan) -> list[str]:
    """The plan's arguments without the viewer options, the route stage and its limit."""
    out: list[str] = []
    skip = 0
    for tok in plan.args:
        if skip:
            skip -= 1
        elif tok in ("--disp", "--graphics_pause", "--max_router_iterations"):
            skip = 1
        elif tok != "--route":
            out.append(tok)
    return out


def draw(vpr: str, args: list[str], commands: str, work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", LIBGL_ALWAYS_SOFTWARE="1")
    cmd = [vpr, *args, "--disp", "off", "--graphics_commands", commands]
    subprocess.run(cmd, cwd=work, env=env, check=True, capture_output=True, timeout=600)


def main(vpr: str, run_dir: Path, out: Path) -> int:
    plan = plan_floorplan(run_dir, Path(vpr))
    if isinstance(plan, str):
        print(plan, file=sys.stderr)
        return 1
    args = base_args(plan)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tutfp-") as tmp:
        place, routed = Path(tmp) / "place", Path(tmp) / "route"
        draw(vpr, args, "save_graphics place.png; set_nets 1; save_graphics nets.png", place)
        draw(vpr, [*args, "--route"], "set_cpd 7; save_graphics cpd.png", routed)
        (out / "gt-fp-place.png").write_bytes((place / "place.png").read_bytes())
        (out / "gt-fp-nets.png").write_bytes((place / "nets.png").read_bytes())
        (out / "gt-fp-cpd.png").write_bytes((routed / "cpd.png").read_bytes())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])))
