"""Score, high-score and credits screens (spec 9.2)."""

from __future__ import annotations

import pygame

from wyrd.midgard.model.level import LevelResult
from wyrd.midgard.model.scores import ScoreTable
from wyrd.midgard.ui.draw import Button, draw_number, draw_text, draw_time, y_down
from wyrd.midgard.ui.game import ButtonScreen, Game
from wyrd.midgard.ui.menu import BACKGROUND, asset_button
from wyrd.midgard.ui.view import SCORE_SIZE

H = SCORE_SIZE[1]
LAST_LEVEL = 12
CREDITS = (
    ("Dr. Peter Jamieson", "Created the game design, and programmed many parts of the game\n"
     "including the Verilog Simulation and car movement and path planning."),
    ("Naoki Mizuno", "Built the XML level descriptions and a separate tool for level creation.\n"
     "Naoki is one of the main developers of the Beta release of verilogTown."),
    ("Boyu Zhang", "Built the standalone Verilog Editor and structured much of the game control.\n"
     "Boyu is one of the main developers of the Beta release of verilogTown."),
    ("Alex Williams", "Built the early version of the Verilog parser using ANTLR 4.0."),
    ("Josh Collins", "Built the early parts of the game including animation and level."),
    ("Lindsay Grace", "Collaborator on game design."),
    ("John-Rhys Garcia", "Main artist for tileset and vehicles."),
)
CREDIT_Y = ((1150, 1080), (950, 880), (750, 680), (550, 480), (420, 350), (290, 220), (160, 90))
NOTES = (
    "Ported to Python and pygame-ce as Midgard III (Yggdrasil), see NOTICE",
    "verilogTown, Jamieson, Grace, Mizuno, Zhang, ASEE 2017",
)


def back_button() -> Button:
    return asset_button("back", (30, y_down(45, 59, H), 160, 59))


class ScoreScreen(ButtonScreen):
    logical_size = SCORE_SIZE

    def __init__(self, game: Game, number: int, result: LevelResult) -> None:
        super().__init__(game)
        self.number = number
        self.result = result
        table = game.userdata.load_scores(number)
        self.rank = table.insert(result.passed, result.ticks)
        self.save_error = None
        if self.rank is not None:
            self.save_error = game.userdata.save_scores(number, table)
        if self.save_error:
            game.status = self.save_error
        self.buttons["main_menu"] = asset_button("main_menu", (150, y_down(150, 98, H), 300, 98))
        self.buttons["try_again"] = asset_button("try_again", (500, y_down(150, 98, H), 300, 98))
        self.buttons["next_level"] = asset_button("next_level", (850, y_down(151, 98, H), 300, 98))

    def on_next(self) -> None:
        if self.number >= LAST_LEVEL:
            self.game.open_menu()
        else:
            self.game.open_level(self.number + 1)

    def on_button(self, name: str) -> None:
        if name == "main_menu":
            self.game.open_menu()
        elif name == "try_again":
            self.game.open_level(self.number)
        else:
            self.on_next()

    def draw(self, surface: pygame.Surface) -> None:
        assets = self.game.assets
        bg = pygame.transform.smoothscale(assets.image("data/level_finish.png"), SCORE_SIZE)
        surface.blit(bg, (0, 0))
        self._draw_level_number(surface)
        r = self.result
        draw_number(surface, assets, 725, y_down(660, 75, H), r.passed, 3, 75, 75)
        draw_number(surface, assets, 725, y_down(420, 75, H), r.failed, 3, 75, 75)
        draw_time(surface, assets, 725, y_down(895, 75, H), r.ticks, 75, 65)
        ticks_pos = (725, y_down(895, 75, H) + 83)
        draw_text(surface, assets, f"{r.ticks} ticks", ticks_pos, 28, (0, 0, 0))
        self.draw_buttons(surface)

    def _draw_level_number(self, surface: pygame.Surface) -> None:
        a = self.game.assets
        n = self.number
        y = y_down(1088, 80, H)
        xs = [(578, n)] if n < 10 else [(545, n // 10), (595, n % 10)]
        for x, d in xs:
            surface.blit(pygame.transform.smoothscale(a.digit(d, "chiller"), (80, 80)), (x, y))


class HighScoreScreen(ButtonScreen):
    logical_size = SCORE_SIZE

    def __init__(self, game: Game) -> None:
        super().__init__(game)
        self.page = 1
        self.table = ScoreTable()
        self.buttons["back"] = back_button()
        self.buttons["next"] = Button(
            (1180, y_down(500, 300, H), 90, 300),
            "ASSET_RESOURCES/next_normal.png",
            "ASSET_RESOURCES/next_hover.png",
            "ASSET_RESOURCES/next_pressed.png",
        )
        self.buttons["last"] = Button(
            (10, y_down(500, 300, H), 90, 300),
            "ASSET_RESOURCES/last_normal.png",
            "ASSET_RESOURCES/last_hover.png",
            "ASSET_RESOURCES/last_pressed.png",
        )
        self._load()

    def _load(self) -> None:
        self.table = self.game.userdata.load_scores(self.page)

    def on_button(self, name: str) -> None:
        if name == "back":
            self.game.open_menu()
            return
        step = 1 if name == "next" else -1
        self.page = min(LAST_LEVEL, max(1, self.page + step))
        self._load()

    def _blit(self, surface: pygame.Surface, rel: str, x: int, java_y: int, w: int, h: int) -> None:
        img = pygame.transform.smoothscale(self.game.assets.image(rel), (w, h))
        surface.blit(img, (x, y_down(java_y, h, H)))

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill(BACKGROUND)
        self._blit(surface, "ASSET_RESOURCES/local_high_score.png", 260, 1130, 750, 280)
        self._blit(surface, "ASSET_RESOURCES/rank.png", 180, 1037, 150, 84)
        self._blit(surface, "ASSET_RESOURCES/cars.png", 560, 1037, 150, 84)
        self._blit(surface, "ASSET_RESOURCES/time.png", 940, 1037, 150, 84)
        label = f"ASSET_RESOURCES/score_level{self.page}_pressed.png"
        self._blit(surface, label, 500, 1090, 300, 140)
        a = self.game.assets
        for j, (cars, ticks) in enumerate(self.table.entries):
            y = y_down(950 - 100 * j, 55, H)
            draw_number(surface, a, 200, y, j + 1, 2, 55, 53)
            draw_number(surface, a, 555, y, cars, 3, 55, 53)
            draw_time(surface, a, 905, y, ticks, 55, 48)
        self.draw_buttons(surface)


class CreditsScreen(ButtonScreen):
    logical_size = SCORE_SIZE

    def __init__(self, game: Game) -> None:
        super().__init__(game)
        self.buttons["back"] = asset_button("back", (1080, y_down(40, 59, H), 160, 59))

    def on_button(self, name: str) -> None:
        self.game.open_menu()

    def draw(self, surface: pygame.Surface) -> None:
        a = self.game.assets
        surface.fill(BACKGROUND)
        logo = pygame.transform.smoothscale(a.image("ASSET_RESOURCES/credits.png"), (360, 110))
        surface.blit(logo, (450, y_down(1160, 110, H)))
        black = (0, 0, 0)
        for (name, role), (name_y, role_y) in zip(CREDITS, CREDIT_Y, strict=True):
            surface.blit(a.credits_font(58).render(name, True, black), (30, H - name_y))
            for k, line in enumerate(role.split("\n")):
                text = a.credits_font(50).render(line, True, black)
                surface.blit(text, (120, H - role_y + 40 * k))
        for k, line in enumerate(NOTES):
            surface.blit(a.font(28).render(line, True, black), (120, 60 + 30 * k))
        self.draw_buttons(surface)
