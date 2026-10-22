"""The main menu (spec 9.2)."""

from __future__ import annotations

import pygame

from wyrd.midgard.ui.draw import Button, y_down
from wyrd.midgard.ui.game import ButtonScreen, Game
from wyrd.midgard.ui.view import MENU_SIZE

BACKGROUND = (199, 230, 199)
SIZE = MENU_SIZE[1]


def asset_button(base: str, rect: tuple[int, int, int, int], hover: str = "mouse_on") -> Button:
    prefix = f"ASSET_RESOURCES/{base}"
    return Button(rect, f"{prefix}_normal.png", f"{prefix}_{hover}.png", f"{prefix}_pressed.png")


def menu_rect(x: int, java_y: int) -> tuple[int, int, int, int]:
    return (x, y_down(java_y, 60, SIZE), 250, 60)


class MainMenu(ButtonScreen):
    logical_size = MENU_SIZE

    def __init__(self, game: Game) -> None:
        super().__init__(game)
        self.time = 0.0
        for i in range(12):
            rect = menu_rect(162 + (i % 3) * 350, 705 - 100 * (i // 3))
            self.buttons[f"level{i + 1}"] = asset_button(f"level{i + 1}", rect)
        self.buttons["tutorial"] = asset_button("tutorial", menu_rect(512, 805))
        self.buttons["high_score"] = asset_button("high_score", menu_rect(512, 305))
        self.buttons["credits"] = asset_button("credits", menu_rect(512, 205))

    def on_button(self, name: str) -> None:
        if name == "tutorial":
            self.game.open_level(0)
        elif name == "high_score":
            self.game.open_scores()
        elif name == "credits":
            self.game.open_credits()
        else:
            self.game.open_level(int(name.removeprefix("level")))

    def update(self, dt: float) -> None:
        self.time += dt

    def draw(self, surface: pygame.Surface) -> None:
        assets = self.game.assets
        surface.fill(BACKGROUND)
        title = assets.image("ASSET_RESOURCES/welcom_to_verilogtown.png")
        surface.blit(pygame.transform.smoothscale(title, (800, 200)), (200, y_down(950, 200, SIZE)))
        if int(self.time * 1.3) % 2 == 0:
            pick = assets.image("ASSET_RESOURCES/select_a_level.png")
            pick = pygame.transform.smoothscale(pick, (540, 120))
            surface.blit(pick, (370, y_down(850, 120, SIZE)))
        self.draw_buttons(surface)
