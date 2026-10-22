"""Midgard III program entry (spec 9.1)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from wyrd.midgard.model.userdata import default_data_dir

FRAME_DT = 0.016


def _size(text: str) -> tuple[int, int]:
    try:
        w, h = text.lower().split("x")
        size = (int(w), int(h))
    except ValueError:
        raise argparse.ArgumentTypeError("size must look like 1280x1380") from None
    if size[0] < 1 or size[1] < 1:
        raise argparse.ArgumentTypeError("size must be positive")
    return size


def _level(text: str) -> int:
    n = int(text)
    if not 0 <= n <= 12:
        raise argparse.ArgumentTypeError("level must be 0 to 12")
    return n


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="midgard", description="Midgard III (Verilog Town)")
    p.add_argument("--level", type=_level, default=None)
    p.add_argument("--data-dir", type=Path, default=None)
    p.add_argument("--speed", type=int, choices=(1, 2, 4), default=1)
    p.add_argument("--size", type=_size, default=None)
    p.add_argument("--no-editor", action="store_true")
    p.add_argument("--frames", type=int, default=None)
    return p.parse_args(argv)


def _run(args: argparse.Namespace) -> int:
    import pygame

    from wyrd.midgard.ui.game import Game

    pygame.display.init()
    pygame.font.init()
    pygame.display.set_caption("Midgard III")
    data_dir = args.data_dir or default_data_dir(os.environ, Path.home())
    game = Game(
        data_dir,
        speed=args.speed,
        window_size=args.size,
        editor=not args.no_editor,
    )
    try:
        if args.level is not None:
            game.open_level(args.level)
        if args.frames is None:
            game.run()
        else:
            for _ in range(args.frames):
                game.frame(FRAME_DT, [])
    finally:
        game.close()
        pygame.quit()
    return 0


def _have_pygame() -> bool:
    try:
        import pygame
    except ImportError:
        return False
    return pygame is not None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not _have_pygame():
        print('needs: pip install "wyrd[midgard]"', file=sys.stderr)
        return 2
    return _run(args)
