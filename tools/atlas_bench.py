"""Time loading and drawing one atlas file in the Atlas panel (offscreen) and report peak RSS.

Usage: QT_QPA_PLATFORM=offscreen python tools/atlas_bench.py FILE [FILE_B]
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import resource
import sys
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from wyrd import atlas
from wyrd.gui.atlaspanel import AtlasPanel


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    app = QApplication.instance() or QApplication([])
    t0 = time.perf_counter()
    a = atlas.load_atlas(Path(argv[0]))
    load_s = time.perf_counter() - t0
    panel = AtlasPanel()
    panel.resize(900, 700)
    panel.show()
    panel.atlas_a = a
    if len(argv) > 1:
        panel.atlas_b = atlas.load_atlas(Path(argv[1]))
        panel.mode.setCurrentIndex(2)
    app.processEvents()
    for key in atlas.KEYS:
        panel.key.setCurrentText(key)
        panel.redraw()
        print(f"draw key={key:9s} {panel.last_draw_s * 1000:7.1f} ms")
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"{a.design} {a.arm} s{a.seed}: {len(a.clbs)} CLBs, {len(a.atoms)} atoms")
    print(f"load+validate {load_s * 1000:.1f} ms, peak RSS {rss_mb:.0f} MB")
    panel.close()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
