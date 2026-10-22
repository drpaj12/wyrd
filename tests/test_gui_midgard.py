"""The Tools > Midgard III entry (Qt offscreen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

HAVE_QT = importlib.util.find_spec("PySide6") is not None
REAL_FIND_SPEC = importlib.util.find_spec
NAME = "Midgard III (Verilog Town)"

if HAVE_QT:
    from PySide6.QtCore import QCoreApplication, QSettings
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QApplication, QMenu

    from wyrd.gui.mainwindow import MainWindow, _start_detached

    _APP: QCoreApplication | None = None

    def setUpModule() -> None:
        global _APP
        _APP = QApplication.instance() or QApplication([])


def fake_find_spec(pygame_spec: object | None) -> Callable[..., Any]:
    def find(name: str, *args: Any) -> Any:
        if name == "pygame":
            return pygame_spec
        return REAL_FIND_SPEC(name, *args)

    return find


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class MidgardMenuTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def window(self, pygame_spec: object | None) -> "MainWindow":
        settings = QSettings(str(self.tmp / "s.ini"), QSettings.Format.IniFormat)
        with mock.patch("importlib.util.find_spec", fake_find_spec(pygame_spec)):
            w = MainWindow(settings, silent=True)
        self.addCleanup(w.close)
        return w

    def action(self, w: "MainWindow") -> "QAction":
        bar = w.menuBar()
        assert bar is not None
        for top in bar.actions():
            menu = top.menu()
            if isinstance(menu, QMenu) and top.text() == "Tools":
                for act in menu.actions():
                    if act.text() == NAME:
                        return act
        self.fail("no Midgard III action in the Tools menu")

    def test_enabled_and_launches(self) -> None:
        w = self.window(SimpleNamespace())
        calls: list[tuple[str, list[str]]] = []

        def launcher(program: str, args: list[str]) -> bool:
            calls.append((program, args))
            return True

        w.midgard_launcher = launcher
        act = self.action(w)
        self.assertTrue(act.isEnabled())
        act.trigger()
        self.assertEqual(calls, [(sys.executable, ["-m", "wyrd.midgard"])])
        self.assertEqual(w.statusBar().currentMessage(), "Started Midgard III")

    def test_launch_failure(self) -> None:
        w = self.window(SimpleNamespace())
        w.midgard_launcher = lambda program, args: False
        self.action(w).trigger()
        self.assertEqual(w.statusBar().currentMessage(), "Cannot start Midgard III")

    def test_default_launcher_reports_failure(self) -> None:
        self.assertFalse(_start_detached("/nonexistent/wyrd-no-such-program", []))

    def test_disabled_without_pygame(self) -> None:
        w = self.window(None)
        act = self.action(w)
        self.assertFalse(act.isEnabled())
        self.assertEqual(act.toolTip(), 'needs: pip install "wyrd[midgard]"')


if __name__ == "__main__":
    unittest.main()
