"""Read the VPR files a bundle needs: .place (xy), .net (clusters), setup timing report (slack)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Placement:
    grid: tuple[int, int]  # logic block array size (width, height) as VPR prints it
    xy: dict[str, tuple[int, int, int]]  # top-level block name -> (x, y, subblock)


@dataclass
class Cluster:
    name: str
    instance: str  # e.g. clb[3], io[0], memory[0]
    atoms: list[str] = field(default_factory=list)  # names of the blocks inside (not "open")

    @property
    def kind(self) -> str:
        return self.instance.split("[", 1)[0]


ARRAY = re.compile(r"Array size:\s*(\d+)\s*x\s*(\d+)")


def read_place(path: Path) -> Placement:
    grid = (0, 0)
    xy: dict[str, tuple[int, int, int]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = ARRAY.search(line)
        if m:
            grid = (int(m.group(1)), int(m.group(2)))
            continue
        if not line.strip() or line.startswith(("#", "Netlist_File")):
            continue
        cols = line.split("#", 1)[0].split()
        if len(cols) >= 4:
            xy[cols[0]] = (int(cols[1]), int(cols[2]), int(cols[3]))
    return Placement(grid=grid, xy=xy)


def read_net(path: Path) -> list[Cluster]:
    root = ET.parse(path).getroot()
    out: list[Cluster] = []
    for top in root.findall("block"):
        name = top.get("name", "")
        cl = Cluster(name=name, instance=top.get("instance", ""))
        seen: set[str] = set()
        for blk in top.iter("block"):
            n = blk.get("name", "open")
            if n != "open" and n not in seen:
                seen.add(n)
                cl.atoms.append(n)
        out.append(cl)
    return out


SLACK = re.compile(r"^slack \((?:MET|VIOLATED)\)\s+(-?[0-9.]+)")
POINT = re.compile(r"^(\S+?)\.\S+ \(")


@dataclass(frozen=True)
class AtomTiming:
    worst_slack: dict[str, float]  # atom name -> worst slack of the reported paths through it (ns)
    npaths: dict[str, int]  # atom name -> number of reported paths through it
    paths: int


def read_setup_report(path: Path) -> AtomTiming:
    worst: dict[str, float] = {}
    npaths: dict[str, int] = {}
    atoms: set[str] = set()
    paths = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#Path"):
            paths += 1
            atoms = set()
            continue
        m = POINT.match(line)
        if m:
            atoms.add(m.group(1))
            continue
        s = SLACK.match(line)
        if s:
            val = float(s.group(1))
            for a in atoms:
                worst[a] = min(val, worst.get(a, val))
                npaths[a] = npaths.get(a, 0) + 1
    return AtomTiming(worst_slack=worst, npaths=npaths, paths=paths)


@dataclass(frozen=True)
class SetupPath:
    n: int  # "#Path n" of the report
    slack: float  # ns
    start: str  # startpoint pin as printed
    end: str  # endpoint pin as printed
    atoms: list[str]  # atoms on the data path in order (clock network pins left out)


def read_setup_paths(path: Path) -> list[SetupPath]:
    """The reported setup paths: ordered atoms of the data-arrival part, one entry per `#Path`."""
    out: list[SetupPath] = []
    cur: dict[str, object] | None = None
    clock = ""
    in_data = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#Path"):
            cur = {"n": len(out) + 1, "start": "", "end": "", "atoms": []}
            in_data, clock = True, ""
            continue
        if cur is None:
            continue
        atoms = cur["atoms"]
        assert isinstance(atoms, list)
        if line.startswith("Startpoint:"):
            cur["start"] = line.split(":", 1)[1].split(" (", 1)[0].strip()
        elif line.startswith("Endpoint"):
            cur["end"] = line.split(":", 1)[1].split(" (", 1)[0].strip()
        elif line.startswith("data arrival time"):
            in_data = False
        elif line.startswith("clock ") and not clock:
            words = line.split()
            clock = words[1] if len(words) > 1 else ""
        else:
            s = SLACK.match(line)
            if s:
                out.append(
                    SetupPath(
                        int(str(cur["n"])),
                        float(s.group(1)),
                        str(cur["start"]),
                        str(cur["end"]),
                        list(atoms),
                    )
                )
                cur = None
                continue
            m = POINT.match(line)
            if m and in_data:
                atom = m.group(1)
                port = line.split(".", 1)[1] if "." in line else ""
                if port.startswith("clk") or (atom == clock and port.startswith("inpad")):
                    continue
                if not atoms or atoms[-1] != atom:
                    atoms.append(atom)
    return out
