"""Image and font loading with caches (spec 9.1). Needs a display mode for `convert_alpha`."""

from __future__ import annotations

from pathlib import Path

import pygame

from wyrd.midgard.model import ASSETS


class Assets:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else ASSETS
        self._images: dict[str, pygame.Surface] = {}
        self._fonts: dict[tuple[str, int], pygame.font.Font] = {}
        self._frames: list[pygame.Surface] | None = None
        self._transformed: dict[tuple[str, float, float], pygame.Surface] = {}

    def image(self, rel: str) -> pygame.Surface:
        cached = self._images.get(rel)
        if cached is None:
            path = self.root / rel
            if not path.is_file():
                raise FileNotFoundError(str(path))
            cached = pygame.image.load(str(path)).convert_alpha()
            self._images[rel] = cached
        return cached

    def transformed(self, rel: str, angle: float, scale: float) -> pygame.Surface:
        """Cached `rotozoom` of an image (counterclockwise degrees)."""
        key = (rel, angle, scale)
        out = self._transformed.get(key)
        if out is None:
            out = pygame.transform.rotozoom(self.image(rel), angle, scale)
            self._transformed[key] = out
        return out

    def level_map(self, n: int) -> pygame.Surface:
        return self.image(f"levels/Lv{n}/lv{n:02d}.png")

    def car_frames(self) -> list[pygame.Surface]:
        if self._frames is None:
            sheet = self.image("data/car_sheet.png")
            frames = [self.image("data/car_4.png"), self.image("data/car_5.png")]
            for row, col in ((0, 0), (0, 1), (1, 0), (1, 1)):
                frames.append(sheet.subsurface(pygame.Rect(col * 64, row * 64, 64, 64)).copy())
            self._frames = frames
        return self._frames

    def digit(self, n: int, kind: str) -> pygame.Surface:
        return self.image(f"data/{kind}_num_{n}.png")

    def _font(self, key: tuple[str, int]) -> pygame.font.Font:
        font = self._fonts.get(key)
        if font is None:
            name, size = key
            font = pygame.font.Font(name or None, size)
            self._fonts[key] = font
        return font

    def font(self, size: int) -> pygame.font.Font:
        return self._font(("", size))

    def credits_font(self, size: int) -> pygame.font.Font:
        return self._font((str(self.root / "fonts/Creepster-Regular.ttf"), size))
