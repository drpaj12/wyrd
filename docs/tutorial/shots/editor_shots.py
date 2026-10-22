"""Screenshots of the Midgard III Verilog editor and level editor windows (Qt, offscreen).

    QT_QPA_PLATFORM=offscreen python editor_shots.py DATA_DIR OUT_DIR

DATA_DIR is the Midgard data directory used by midgard_shots.py (it holds Lv1/VerilogFiles).
The Verilog editor compiles and simulates one cycle with the real Odin III.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from wyrd.midgard.editors import level_editor as le
from wyrd.midgard.editors import verilog_editor as ve
from wyrd.midgard.model.levelxml import level_path
from wyrd.midgard.model.vedit import EditorSession


def pump(app: QApplication, seconds: float = 0.3) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def grab(app: QApplication, widget: QWidget, out: Path, name: str) -> None:
    pump(app, 0.3)
    if not widget.grab().save(str(out / f"{name}.png")):
        raise OSError(f"cannot write {name}.png")
    print("shot", name)


def verilog_editor(app: QApplication, data: Path, out: Path) -> None:
    path = data / "Lv1" / "VerilogFiles" / "Traffic_signal_set_0.v"
    session = EditorSession(path)
    win = ve.VerilogEditorWindow(session, "Traffic_signal_set_0 - Level 1")
    win.resize(1100, 760)
    win.show()
    grab(app, win, out, "ve-open")
    win.do_verify()
    grab(app, win, out, "ve-verified")
    win.animation.boxes[6].setChecked(True)  # a car waits on the north entry (bit 6)
    win.do_simulate()
    grab(app, win, out, "ve-simulated")
    win.close()
    session.close()


def level_editor(app: QApplication, out: Path) -> None:
    start = le.StartDialog()
    start.show()
    grab(app, start, out, "le-start")
    start.close()
    win = le._open_window(le.StartResult(True, 0, 0, 0, level_path(1)))
    if win is None:
        raise RuntimeError("level 1 did not open in the level editor")
    win.resize(1000, 900)
    win.show()
    grab(app, win, out, "le-level1")
    win.close()


def main(data: Path, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    verilog_editor(app, data, out)
    level_editor(app, out)
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()))
