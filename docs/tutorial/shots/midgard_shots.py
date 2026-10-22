"""Screenshots of Midgard III for the tutorial, from the real game against real Odin III.

    SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python midgard_shots.py DATA_DIR OUT_DIR

DATA_DIR is a fresh Midgard data directory. The game runs level 1 with a Verilog file whose only
change from the starter is `debug_port = general_sensors`; a sensor is placed with the mouse
(click the pile, click a road tile). Pictures are saved from the game's own surface.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from wyrd.midgard.model.level import Phase
from wyrd.midgard.ui.game import Game
from wyrd.midgard.ui.levelscreen import LevelScreen
from wyrd.midgard.ui.scorescreens import ScoreScreen

HERE = Path(__file__).resolve().parent
PILE = (32, 1348)          # logical pixel inside the sensor pile (bottom-left tile)
SENSOR_TILE = (5, 15)      # a road tile that level 1's cars pass


def tile_pixel(ix: int, iy: int) -> tuple[int, int]:
    """Logical pixel at the centre of node tile (ix, iy); the map starts 100 px down."""
    return ix * 64 - 32, 100 + 1280 - (iy * 64 - 32)


def save(game: Game, out: Path, name: str) -> None:
    pygame.image.save(game.logical, str(out / f"{name}.png"))
    print("shot", name)


def click(game: Game, pos: tuple[int, int]) -> None:
    wpos = game.to_window(pos)
    down = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=wpos)
    up = pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=wpos)
    game.frame(0.016, [pygame.event.Event(pygame.MOUSEMOTION, pos=wpos, rel=(0, 0),
                                          buttons=(0, 0, 0)), down])
    game.frame(0.016, [up])


def key(game: Game, k: int) -> None:
    game.frame(0.0, [pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode="", scancode=0)])
    game.frame(0.0, [pygame.event.Event(pygame.KEYUP, key=k, mod=0, scancode=0)])


def level_screen(game: Game) -> LevelScreen:
    assert isinstance(game.screen, LevelScreen)
    return game.screen


def run_until(game: Game, cond: object, limit: int = 4000) -> None:
    for _ in range(limit):
        game.frame(0.05, [])
        if callable(cond) and cond():
            return
    raise TimeoutError("the level did not reach the wanted state")


def main(data: Path, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    pygame.display.init()
    pygame.font.init()
    game = Game(data, window_size=(960, 1100), editor=False, speed=4)
    game.frame(0.016, [])
    save(game, out, "mg-menu")
    game.open_level(1)
    game.frame(0.016, [])
    screen = level_screen(game)
    save(game, out, "mg-level-edit")
    click(game, PILE)
    hover = game.to_window(tile_pixel(*SENSOR_TILE))
    game.frame(0.016, [pygame.event.Event(pygame.MOUSEMOTION, pos=hover, rel=(0, 0),
                                          buttons=(0, 0, 0))])
    save(game, out, "mg-sensor-in-hand")
    click(game, tile_pixel(*SENSOR_TILE))
    save(game, out, "mg-sensor-placed")
    shutil_copy(HERE.parent / "midgard" / "Traffic_signal_set_0.v", screen.paths[0])
    for _ in range(3):
        game.frame(0.6, [])  # the file watch notices the edit and recompiles in the edit phase
    if screen.errors or screen.message:
        raise RuntimeError(f"unexpected message: {screen.message} {screen.errors}")
    key(game, pygame.K_s)
    if screen.phase is not Phase.RUN:
        raise RuntimeError(f"level did not start: {screen.message} {screen.errors}")

    def sensor_sees_a_car() -> bool:
        ctl = screen.level.controllers[0]
        return bool(ctl.last_inputs and ctl.last_inputs[1])

    run_until(game, sensor_sees_a_car)
    key(game, pygame.K_p)
    game.frame(0.016, [])
    save(game, out, "mg-run-paused")
    key(game, pygame.K_s)  # S resumes a paused level
    run_until(game, lambda: isinstance(game.screen, ScoreScreen)
              or screen.level.phase.name == "DONE")
    for _ in range(40):
        game.frame(0.1, [])
        if isinstance(game.screen, ScoreScreen):
            break
    save(game, out, "mg-score")
    game.close()
    pygame.quit()
    return 0


def shutil_copy(src: Path, dst: Path) -> None:
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()))
