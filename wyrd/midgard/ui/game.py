"""The game object, the screen base class and the frame loop (spec 9)."""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import pygame

from wyrd.bifrost import Backend
from wyrd.midgard.model.clock import TickClock
from wyrd.midgard.model.controllers import BuildResult, build_controllers
from wyrd.midgard.model.level import LevelResult
from wyrd.midgard.model.userdata import UserData
from wyrd.midgard.ui.assets import Assets
from wyrd.midgard.ui.draw import Button
from wyrd.midgard.ui.view import MENU_SIZE, View, initial_window_size, present

DEFAULT_DESKTOP = (1920, 1080)
Event = pygame.event.Event
Pos = tuple[int, int] | None
_MOUSE = (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION)


class Screen:
    logical_size: tuple[int, int] = MENU_SIZE

    def handle_event(self, event: Event, pos: Pos) -> None:
        return None

    def update(self, dt: float) -> None:
        return None

    def draw(self, surface: pygame.Surface) -> None:
        return None

    def close(self) -> None:
        return None


class ButtonScreen(Screen):
    """A screen of clickable buttons: a release inside the button that took the press fires."""

    def __init__(self, game: Game) -> None:
        self.game = game
        self.buttons: dict[str, Button] = {}
        self.pressed: str | None = None
        self.hover: str | None = None

    def _at(self, pos: Pos) -> str | None:
        if pos is None:
            return None
        for name, button in self.buttons.items():
            if button.contains(pos):
                return name
        return None

    def handle_event(self, event: Event, pos: Pos) -> None:
        if event.type == pygame.MOUSEMOTION:
            self.hover = self._at(pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.hover = self.pressed = self._at(pos)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            hit, pressed = self._at(pos), self.pressed
            self.pressed = None
            if hit is not None and hit == pressed:
                self.on_button(hit)

    def on_button(self, name: str) -> None:
        return None

    def draw_buttons(self, surface: pygame.Surface) -> None:
        for name, button in self.buttons.items():
            state = "normal"
            if name == self.hover:
                state = "pressed" if name == self.pressed else "hover"
            button.draw(surface, self.game.assets, state)


def _desktop() -> tuple[int, int]:
    try:
        sizes = pygame.display.get_desktop_sizes()
    except pygame.error:
        return DEFAULT_DESKTOP
    return sizes[0] if sizes else DEFAULT_DESKTOP


class Game:
    def __init__(
        self,
        data_dir: Path,
        *,
        backend: Backend | None = None,
        build: Callable[[Sequence[Path]], BuildResult] | None = None,
        speed: int = 1,
        window_size: tuple[int, int] | None = None,
        editor: bool = True,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        pygame.display.init()
        pygame.font.init()
        size = window_size or initial_window_size(MENU_SIZE, _desktop())
        self.window = pygame.display.set_mode(size, pygame.RESIZABLE)
        self.backend = backend
        self.build: Callable[[Sequence[Path]], BuildResult] = build or self._default_build
        self.speed = speed
        self.editor = editor
        self.now = now
        self.userdata = UserData(data_dir)
        self.assets = Assets()
        self.tick_clock = TickClock()
        self.watch_interval = 0.5
        self.running = True
        self.status = ""
        self.open_waveform: Callable[[Path], bool] = self._no_waveform
        self.screen: Screen = Screen()
        self.view = View(MENU_SIZE)
        self.logical = pygame.Surface(MENU_SIZE)
        self.open_menu()

    def _default_build(self, paths: Sequence[Path]) -> BuildResult:
        return build_controllers(paths, self.backend)

    def _no_waveform(self, path: Path) -> bool:
        program = shutil.which("gtkwave")
        if program is not None:
            try:
                subprocess.Popen(
                    [program, str(path)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return True
            except OSError as exc:
                self.status = f"Could not start gtkwave: {exc}"
                return False
        self.status = f"Waveform: {path}"
        return False

    def _set_screen(self, screen: Screen) -> None:
        old = self.screen
        self.screen = screen
        old.close()
        self.view = View(screen.logical_size)
        self.logical = pygame.Surface(screen.logical_size)

    def open_menu(self) -> None:
        from wyrd.midgard.ui.menu import MainMenu

        self._set_screen(MainMenu(self))

    def open_level(self, n: int) -> None:
        from wyrd.midgard.ui.levelscreen import LevelScreen

        self.tick_clock.reset()
        self._set_screen(LevelScreen(self, n))

    def open_scores(self) -> None:
        from wyrd.midgard.ui.scorescreens import HighScoreScreen

        self._set_screen(HighScoreScreen(self))

    def open_credits(self) -> None:
        from wyrd.midgard.ui.scorescreens import CreditsScreen

        self._set_screen(CreditsScreen(self))

    def open_score_screen(self, n: int, result: LevelResult) -> None:
        from wyrd.midgard.ui.scorescreens import ScoreScreen

        self._set_screen(ScoreScreen(self, n, result))

    def to_window(self, pos: tuple[int, int]) -> tuple[int, int]:
        return self.view.to_window(pos, self.window.get_size())

    def _dispatch(self, event: Event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
            return
        pos: Pos = None
        if event.type in _MOUSE:
            pos = self.view.to_logical(event.pos, self.window.get_size())
        self.screen.handle_event(event, pos)

    def frame(self, dt: float, events: Sequence[Event]) -> None:
        surface = pygame.display.get_surface()
        if surface is not None:
            self.window = surface
        for event in events:
            self._dispatch(event)
        self.screen.update(dt)
        self.screen.draw(self.logical)
        present(self.logical, self.window, self.view)
        pygame.display.flip()

    def run(self) -> None:
        clock = pygame.time.Clock()
        while self.running:
            dt = clock.tick(60) / 1000
            self.frame(dt, pygame.event.get())
        self.close()

    def close(self) -> None:
        self.screen.close()
