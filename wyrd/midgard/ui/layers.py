"""Drawing of the level layers (spec 9.1). Each function draws one layer on a surface."""

from __future__ import annotations

import random
from collections.abc import Sequence

import pygame

from wyrd.midgard.model.car import Car
from wyrd.midgard.model.controllers import PlayerError
from wyrd.midgard.model.grid import Direction, Node, SignalState
from wyrd.midgard.model.level import LevelResult
from wyrd.midgard.model.sensors import SensorSet
from wyrd.midgard.model.traffic import TrafficControl
from wyrd.midgard.ui.assets import Assets
from wyrd.midgard.ui.draw import draw_text, world_to_screen
from wyrd.midgard.ui.view import LEVEL_SIZE

SIGNAL_IMAGE = {
    SignalState.STOP: "data/stop_tran.png",
    SignalState.GO: "data/go_tran.png",
    SignalState.GO_LEFT: "data/go_left_tran.png",
    SignalState.GO_RIGHT: "data/go_right_tran.png",
    SignalState.GO_FORWARD: "data/go_forward_tran.png",
}
SIGNAL_ROTATION = {Direction.N: 0, Direction.S: 180, Direction.E: 270, Direction.W: 90}
CAR_ROTATION = {Direction.E: 0, Direction.N: 90, Direction.W: 180, Direction.S: 270}
CRASH_FRAME = 5
MAX_PANEL_LINES = 6
BAR_Y = 18
HELP_SIZE = (1280, 1380)


def tile_screen(node: Node) -> tuple[int, int]:
    """Logical top-left of a tile in the world surface."""
    return world_to_screen((node.x - 1) * 64, (node.y - 1) * 64)


def draw_map(surface: pygame.Surface, assets: Assets, number: int) -> None:
    surface.blit(assets.level_map(number), world_to_screen(0, 0, 1280))


def draw_sensors(surface: pygame.Surface, assets: Assets, sensors: SensorSet) -> None:
    for s in sensors.sensors:
        if s.placed:
            surface.blit(assets.image(f"data/sensor{s.number}.png"), tile_screen_xy(s.x, s.y))
    unused = sensors.unused_highest()
    rel = "data/sensor_non.png" if unused is None else f"data/sensor{unused.number}.png"
    surface.blit(assets.image(rel), world_to_screen(0, 0))


def tile_screen_xy(x: int, y: int) -> tuple[int, int]:
    return world_to_screen((x - 1) * 64, (y - 1) * 64)


def _blit_centred(surface: pygame.Surface, img: pygame.Surface, centre: tuple[int, int]) -> None:
    w, h = img.get_size()
    surface.blit(img, (centre[0] - w // 2, centre[1] - h // 2))


def draw_entry_marker(
    surface: pygame.Surface, assets: Assets, rel: str, node: Node, d: Direction
) -> None:
    x, y = tile_screen(node)
    _blit_centred(surface, assets.transformed(rel, SIGNAL_ROTATION[d], 0.7), (x + 32, y + 32))


def draw_signals(
    surface: pygame.Surface,
    assets: Assets,
    controls: Sequence[TrafficControl],
    failed: set[int],
    hover: TrafficControl | None,
) -> None:
    for control in controls:
        for d, node in control.entries.items():
            if node is None:
                continue
            draw_entry_marker(surface, assets, SIGNAL_IMAGE[control.facing[d]], node, d)
            if control.index in failed:
                draw_entry_marker(surface, assets, "data/stop_compiled_failed.png", node, d)
            if control is hover:
                draw_entry_marker(surface, assets, "data/stop_tran_highlighted.png", node, d)


def car_frame_index(number: int, k: int) -> int:
    return random.Random(number * 1000 + k).randrange(5)


def draw_cars(
    surface: pygame.Surface, assets: Assets, cars: Sequence[Car], frames: Sequence[int]
) -> None:
    images = assets.car_frames()
    for car, frame in zip(cars, frames, strict=True):
        if not car.started or (car.done and not car.crashed):
            continue
        img = images[CRASH_FRAME if car.crashed else frame]
        heading = car.animation_direction or car.direction
        if heading is not None:
            img = pygame.transform.rotate(img, CAR_ROTATION[heading])
        surface.blit(img, world_to_screen(car.px, car.py))


def draw_path_preview(
    surface: pygame.Surface, assets: Assets, car: Car, count: int
) -> None:
    rel = "data/red_dot.png" if car.forced_turned else "data/green_dot.png"
    img = assets.image(rel)
    for node in car.path[max(0, len(car.path) - count) :]:
        surface.blit(img, tile_screen(node))


def draw_placing(
    surface: pygame.Surface,
    assets: Assets,
    number: int,
    world: tuple[float, float],
    valid: bool,
) -> None:
    img = assets.image(f"data/sensor{number}.png").copy()
    img.set_alpha(166)
    pos = world_to_screen(world[0] - 32, world[1] - 32)
    surface.blit(img, pos)
    if not valid:
        surface.blit(assets.image("data/ban.png"), pos)


def draw_digits(
    surface: pygame.Surface, assets: Assets, x: int, value: int, digits: int
) -> None:
    text = f"{max(0, min(value, 10**digits - 1)):0{digits}d}"
    for i, ch in enumerate(text):
        pos = (x + 70 * i, BAR_Y)
        surface.blit(assets.image("data/border.png"), pos)
        surface.blit(assets.digit(int(ch), "red"), pos)


def draw_score_bar(surface: pygame.Surface, assets: Assets, result: LevelResult) -> None:
    bar = pygame.transform.smoothscale(assets.image("data/score_bar.jpg"), (1280, 100))
    surface.blit(bar, (0, 0))
    surface.blit(assets.image("data/checkmark.png"), (70, BAR_Y))
    draw_digits(surface, assets, 140, result.passed, 3)
    surface.blit(assets.image("data/skeleton.png"), (380, BAR_Y))
    draw_digits(surface, assets, 450, result.failed, 3)
    for i, letter in enumerate("TIME"):
        surface.blit(assets.image(f"data/Letter-{letter}.png"), (700 + 63 * i, BAR_Y))
    minutes, seconds = divmod(result.seconds, 60)
    cells = (
        (959, minutes // 10 % 10),
        (1029, minutes % 10),
        (1114, seconds // 10),
        (1184, seconds % 10),
    )
    for x, d in cells:
        pos = (x, BAR_Y)
        surface.blit(assets.image("data/border.png"), pos)
        surface.blit(assets.digit(d, "red"), pos)
    dot = assets.image("data/dot.png")
    surface.blit(dot, (1090, 22))
    surface.blit(dot, (1090, 46))
    help_img = pygame.transform.smoothscale(assets.image("data/press_h_for_help.png"), (400, 100))
    surface.blit(help_img, (900, LEVEL_SIZE[1] - 120 - 110))


def panel_lines(errors: Sequence[PlayerError]) -> list[str]:
    lines = [str(e) for e in errors[:MAX_PANEL_LINES]]
    if len(errors) > MAX_PANEL_LINES:
        lines.append(f"and {len(errors) - MAX_PANEL_LINES} more")
    return lines


def draw_error_panel(
    surface: pygame.Surface, assets: Assets, errors: Sequence[PlayerError]
) -> None:
    lines = panel_lines(errors)
    if not lines:
        return
    height = 12 + 30 * len(lines)
    panel = pygame.Surface((1240, height), pygame.SRCALPHA)
    panel.fill((20, 20, 20, 200))
    surface.blit(panel, (20, 134))
    for k, line in enumerate(lines):
        draw_text(surface, assets, line, (32, 140 + 30 * k), 28, (255, 120, 120))


def draw_help(surface: pygame.Surface, assets: Assets) -> None:
    img = pygame.transform.smoothscale(assets.image("data/help_menu.png"), HELP_SIZE)
    surface.blit(img, (0, 0))
