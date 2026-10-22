"""Extra Midgard III pictures for the GUI tutorial: the help overlay (key H) and a sensor drag.

    SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python mg_gui_shots.py DATA_DIR OUT_DIR

The other Midgard pictures come from the CLI tutorial's shots/midgard_shots.py. Pictures are
saved from the game's own surface (game.logical); DATA_DIR is a fresh Midgard data directory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from wyrd.midgard.ui.game import Game
from wyrd.midgard.ui.levelscreen import LevelScreen

PILE = (32, 1348)
FROM_TILE = (5, 15)
TO_TILE = (5, 17)


def tile_pixel(ix: int, iy: int) -> tuple[int, int]:
    return ix * 64 - 32, 100 + 1280 - (iy * 64 - 32)


def save(game: Game, out: Path, name: str) -> None:
    pygame.image.save(game.logical, str(out / f"{name}.png"))
    print("shot", name)


def mouse(game: Game, kind: int, pos: tuple[int, int]) -> None:
    wpos = game.to_window(pos)
    if kind == pygame.MOUSEMOTION:
        ev = pygame.event.Event(kind, pos=wpos, rel=(0, 0), buttons=(0, 0, 0))
    else:
        ev = pygame.event.Event(kind, button=1, pos=wpos)
    game.frame(0.016, [ev])


def click(game: Game, pos: tuple[int, int]) -> None:
    mouse(game, pygame.MOUSEMOTION, pos)
    mouse(game, pygame.MOUSEBUTTONDOWN, pos)
    mouse(game, pygame.MOUSEBUTTONUP, pos)


def key(game: Game, k: int) -> None:
    game.frame(0.0, [pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode="", scancode=0)])
    game.frame(0.0, [pygame.event.Event(pygame.KEYUP, key=k, mod=0, scancode=0)])


def main(data: Path, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    pygame.display.init()
    pygame.font.init()
    game = Game(data, window_size=(960, 1100), editor=False, speed=1)
    game.frame(0.016, [])
    game.open_level(1)
    game.frame(0.016, [])
    screen = game.screen
    assert isinstance(screen, LevelScreen)
    key(game, pygame.K_h)
    if not screen.help_open:
        raise RuntimeError("H did not open the help overlay")
    save(game, out, "mg-help")
    key(game, pygame.K_h)
    if screen.help_open:
        raise RuntimeError("H did not close the help overlay")
    click(game, PILE)
    click(game, tile_pixel(*FROM_TILE))
    start = tile_pixel(*FROM_TILE)
    mouse(game, pygame.MOUSEMOTION, start)
    mouse(game, pygame.MOUSEBUTTONDOWN, start)
    mouse(game, pygame.MOUSEMOTION, tile_pixel(*TO_TILE))
    save(game, out, "mg-drag")
    mouse(game, pygame.MOUSEBUTTONUP, tile_pixel(*TO_TILE))
    save(game, out, "mg-dragged")
    game.close()
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()))
