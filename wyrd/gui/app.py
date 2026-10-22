"""Entry point of ``wyrd-gui``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from wyrd.gui.mainwindow import MainWindow


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wyrd-gui", description="Wyrd III GUI")
    p.add_argument("project", nargs="?", help="project directory holding wyrd.toml")
    return p


def _initial(arg: str | None, settings: QSettings) -> Path | None:
    if arg:
        return Path(arg)
    last = settings.value("lastProject")
    if isinstance(last, str) and (Path(last) / "wyrd.toml").is_file():
        return Path(last)
    return None


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    app = QApplication(sys.argv[:1])
    settings = QSettings("wyrd", "wyrd-gui")
    window = MainWindow(settings)
    start = _initial(args.project, settings)
    if start is not None:
        window.open_project(start)
    window.show()
    return app.exec()
