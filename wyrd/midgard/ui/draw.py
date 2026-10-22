"""Drawing helpers shared by the screens (spec 9.1, 9.2)."""

from __future__ import annotations

import pygame

from wyrd.midgard.ui.assets import Assets

_TIME_OFFSETS = (0.0, 1.0, 1.77, 2.54, 3.54)


def world_to_screen(px: float, py: float, height: int = 64) -> tuple[int, int]:
    return round(px), 100 + 1280 - round(py) - height


def y_down(y: int, height: int, total: int) -> int:
    return total - y - height


class Button:
    def __init__(
        self, rect: tuple[int, int, int, int], normal: str, hover: str, pressed: str
    ) -> None:
        self.rect = rect
        self.images = {"normal": normal, "hover": hover, "pressed": pressed}

    def contains(self, pos: tuple[int, int]) -> bool:
        x, y, w, h = self.rect
        return x <= pos[0] <= x + w and y <= pos[1] <= y + h

    def draw(self, surface: pygame.Surface, assets: Assets, state: str) -> None:
        x, y, w, h = self.rect
        img = assets.image(self.images.get(state, self.images["normal"]))
        if img.get_size() != (w, h):
            img = pygame.transform.smoothscale(img, (w, h))
        surface.blit(img, (x, y))


def _blit_scaled(
    surface: pygame.Surface, img: pygame.Surface, pos: tuple[float, float], size: int
) -> None:
    if img.get_size() != (size, size):
        img = pygame.transform.smoothscale(img, (size, size))
    surface.blit(img, (round(pos[0]), round(pos[1])))


def draw_number(
    surface: pygame.Surface,
    assets: Assets,
    x: int,
    y: int,
    value: int,
    digits: int,
    size: int,
    gap: int,
    kind: str = "chiller",
) -> None:
    text = f"{max(0, min(value, 10**digits - 1)):0{digits}d}"
    for i, ch in enumerate(text):
        _blit_scaled(surface, assets.digit(int(ch), kind), (x + i * gap, y), size)


def draw_time(
    surface: pygame.Surface, assets: Assets, x: int, y: int, ticks: int, size: int, gap: int
) -> None:
    minutes, seconds = divmod(ticks // 60, 60)
    minutes = min(minutes, 99)
    cells = [
        assets.digit(minutes // 10, "chiller"),
        assets.digit(minutes % 10, "chiller"),
        assets.image("data/chiller_colon.png"),
        assets.digit(seconds // 10, "chiller"),
        assets.digit(seconds % 10, "chiller"),
    ]
    for img, k in zip(cells, _TIME_OFFSETS, strict=True):
        _blit_scaled(surface, img, (x + k * gap, y), size)


def draw_text(
    surface: pygame.Surface,
    assets: Assets,
    text: str,
    pos: tuple[int, int],
    size: int = 28,
    color: tuple[int, int, int] = (255, 255, 255),
) -> None:
    surface.blit(assets.font(size).render(text, True, color), pos)
