"""Copy the Midgard III assets out of verilogTown-master.zip into wyrd/midgard/assets.

Usage: import_midgard_assets.py ZIP DEST
The zip is untrusted data: it is only read with zipfile, nothing in it is run.
"""

from __future__ import annotations

import hashlib
import re
import sys
import zipfile
from pathlib import Path

P = "verilogTown-master/"
ANDROID = P + "VERILOG_TOWN/verilogTown-android/assets/"
LEDIT = P + "VERILOG_TOWN/LevelEditor/src/images/"
VEDIT = P + "VERILOG_TOWN/VerilogEditor/src/images/"
EXTENSIONS = (".png", ".jpg", ".xml")
VEDIT_NAMES = frozenset(
    ["save", "verify", "undo", "redo", "search", "simulate", "reset", "animationImage"]
    + [f"{a}_{d}" for a in ("go", "left", "right", "forward", "stop") for d in "nsew"]
)
LEVEL_RE = re.compile(r"^Levels/Lv(\d+)/map/(lv\d\d\.(?:xml|png))$")
SCORE_SKIP_RE = re.compile(r"^score_level\d+_(?:normal|mouse_on)\.png$")
OLD_HEADER = "general_sensors);"
NEW_HEADER = "general_sensors, debug_port);"
STARTER_COMMENTS = (
    "// Midgard III: rst is active low (0 = reset). One simulation step is one clock cycle.\n"
    "// Output codes: Stop 3'b000, Forward_only 3'b001, Left_only 3'b010, Right_only 3'b011,"
    " Go 3'b100.\n"
    "// Inputs: sensor_light (see the diagram below), general_sensors (7 sensors of 4 bits each).\n"
)
HEADERS = P + "VERILOG_TOWN/VerilogEditor/src/header/"
AUTHORED_SOURCES = {
    "starter.v": (P + "Levels/Lv1/VerilogFiles/Traffic_signal_set_0.v", True),
    "examples/constant_outputs.v": (P + "Levels/Lv1/VerilogFiles/Traffic_lights_set_0.v", False),
    "templates/combinational.v": (HEADERS + "stop_light_combo.v", False),
}
SEQUENTIAL = ("templates/sequential.v", HEADERS + "stop_light_seq.v")


def _android(rest: str, name: str) -> str | None:
    if not name.endswith(EXTENSIONS) or "/" in name:
        return None
    if rest == "data":
        return None if name == "car_sheet1.png" else f"data/{name}"
    if name.startswith("level13_") or name in ("localHighScore.png", "verilogTown.png"):
        return None
    if SCORE_SKIP_RE.match(name):
        return None
    return f"ASSET_RESOURCES/{name}"


def include(member: str) -> str | None:
    """Destination path under the assets directory for a zip member, or None."""
    if member.startswith(ANDROID):
        rest, _, name = member[len(ANDROID):].partition("/")
        if rest in ("data", "ASSET_RESOURCES"):
            return _android(rest, name)
        return None
    m = LEVEL_RE.match(member[len(P):]) if member.startswith(P) else None
    if m:
        return f"levels/Lv{m.group(1)}/{m.group(2)}"
    if member.startswith(LEDIT) and member.endswith(".png") and "/" not in member[len(LEDIT):]:
        return "editors/ledit/" + member[len(LEDIT):]
    if member.startswith(VEDIT) and member.endswith(".png") and "/" not in member[len(VEDIT):]:
        name = member[len(VEDIT):]
        return "editors/vedit/" + name if name[:-4] in VEDIT_NAMES else None
    return None


def fix_header(text: str) -> str:
    return text.replace(OLD_HEADER, NEW_HEADER, 1)


def make_starter(java_free_text: str) -> str:
    return STARTER_COMMENTS + fix_header(java_free_text)


def authored(z: zipfile.ZipFile) -> dict[str, str]:
    """The four Verilog files written from the zip's originals."""
    out: dict[str, str] = {}
    for dest, (src, starter) in AUTHORED_SOURCES.items():
        text = z.read(src).decode("utf-8")
        out[dest] = make_starter(text) if starter else fix_header(text)
    out[SEQUENTIAL[0]] = z.read(SEQUENTIAL[1]).decode("utf-8")
    return out


def copy_all(z: zipfile.ZipFile, dest: Path) -> list[tuple[str, int, str]]:
    rows: list[tuple[str, int, str]] = []
    for info in z.infolist():
        target = include(info.filename)
        if target is None:
            continue
        data = z.read(info)
        out = dest / target
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        rows.append((hashlib.sha256(data).hexdigest(), len(data), target))
    return sorted(rows, key=lambda r: r[2])


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: import_midgard_assets.py ZIP DEST", file=sys.stderr)
        return 2
    dest = Path(argv[2])
    with zipfile.ZipFile(argv[1]) as z:
        rows = copy_all(z, dest)
        for rel, text in authored(z).items():
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="")
    lines = [f"{sha}  {size}  {path}\n" for sha, size, path in rows]
    (dest / "MANIFEST.sha256").write_text("".join(lines), encoding="utf-8")
    print(f"copied {len(rows)} files, {sum(r[1] for r in rows)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
