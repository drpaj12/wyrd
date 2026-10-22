"""Logical surface to window mapping (spec 9.1)."""

from __future__ import annotations

import math

import pygame

MENU_SIZE = (1280, 1280)
SCORE_SIZE = (1280, 1380)
STRIP_HEIGHT = 120
LEVEL_SIZE = (1280, 1380 + STRIP_HEIGHT)
BAR_HEIGHT = 100
MAP_SIZE = 1280


class View:
    def __init__(self, logical: tuple[int, int]) -> None:
        self.logical = logical

    def layout(self, window: tuple[int, int]) -> tuple[float, tuple[int, int]]:
        lw, lh = self.logical
        ww, wh = max(1, window[0]), max(1, window[1])
        scale = min(ww / lw, wh / lh)
        return scale, (round((ww - lw * scale) / 2), round((wh - lh * scale) / 2))

    def to_logical(self, pos: tuple[int, int], window: tuple[int, int]) -> tuple[int, int] | None:
        scale, (ox, oy) = self.layout(window)
        x = math.floor((pos[0] - ox) / scale)
        y = math.floor((pos[1] - oy) / scale)
        if 0 <= x < self.logical[0] and 0 <= y < self.logical[1]:
            return x, y
        return None

    def to_window(self, pos: tuple[int, int], window: tuple[int, int]) -> tuple[int, int]:
        scale, (ox, oy) = self.layout(window)
        return round(pos[0] * scale) + ox, round(pos[1] * scale) + oy


def initial_window_size(logical: tuple[int, int], desktop: tuple[int, int]) -> tuple[int, int]:
    lw, lh = logical
    scale = min(1.0, (desktop[0] - 80) / lw, (desktop[1] - 120) / lh)
    return round(lw * scale), round(lh * scale)


def present(logical: pygame.Surface, window: pygame.Surface, view: View) -> None:
    ww, wh = window.get_size()
    scale, offset = view.layout((ww, wh))
    lw, lh = view.logical
    size = (max(1, round(lw * scale)), max(1, round(lh * scale)))
    window.fill((0, 0, 0))
    window.blit(pygame.transform.smoothscale(logical, size), offset)
