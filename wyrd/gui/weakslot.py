"""Slots that do not keep their widget alive.

Qt holds a Python callable connected to a signal for as long as the connection exists. A lambda
that refers to a widget, connected to a signal of one of the widget's own children, keeps the
widget alive until interpreter exit, where PySide deletes it during finalization (a crash, exit
139). Connect a bound method directly where the signal arguments fit; otherwise wrap it with
`weak`.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable
from typing import ParamSpec

P = ParamSpec("P")


def weak(method: Callable[P, object]) -> Callable[P, None]:
    """Call the bound `method` while its object lives; the wrapper holds it only weakly."""
    ref = weakref.WeakMethod(method)

    def call(*args: P.args, **kwargs: P.kwargs) -> None:
        bound = ref()
        if bound is not None:
            bound(*args, **kwargs)

    return call
