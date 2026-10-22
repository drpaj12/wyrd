from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from collections.abc import Callable, Sequence
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

HAVE_PYGAME = importlib.util.find_spec("pygame") is not None
if HAVE_PYGAME:
    import pygame

    from tests.fakes_midgard import FakeLightBackend
    from tests.test_midgard_level import CARS, INTERS
    from wyrd.bifrost import Backend, SimUnavailable
    from wyrd.midgard.app import main
    from wyrd.midgard.model.controllers import (
        BuildResult,
        ScriptedController,
        safe_controller,
    )
    from wyrd.midgard.model.level import Phase
    from wyrd.midgard.ui.game import Game
    from wyrd.midgard.ui.levelscreen import LevelScreen
    from wyrd.midgard.ui.menu import MainMenu
    from wyrd.midgard.ui.scorescreens import CreditsScreen, HighScoreScreen, ScoreScreen

SYNTAX = "SYNTAX_ERROR"


def setUpModule() -> None:
    if HAVE_PYGAME:
        pygame.display.init()
        pygame.font.init()


def tearDownModule() -> None:
    if HAVE_PYGAME:
        pygame.quit()


@unittest.skipUnless(HAVE_PYGAME, "pygame-ce is not installed")
class UiBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def make_game(
        self,
        build: Callable[[Sequence[Path]], BuildResult] | None = None,
        backend: Backend | None = None,
        speed: int = 4,
        data: Path | None = None,
    ) -> Game:
        game = Game(
            data or self.tmp,
            backend=backend or FakeLightBackend(),
            build=build,
            speed=speed,
            window_size=(640, 750),
            editor=False,
        )
        game.tick_clock.max_backlog = 100000
        self.addCleanup(game.close)
        return game

    def click(self, game: Game, pos: tuple[int, int], button: int = 1) -> None:
        wpos = game.to_window(pos)
        down = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=button, pos=wpos)
        up = pygame.event.Event(pygame.MOUSEBUTTONUP, button=button, pos=wpos)
        game.frame(0, [down, up])

    def key(self, game: Game, k: int) -> None:
        game.frame(0, [pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode="", scancode=0)])
        game.frame(0, [pygame.event.Event(pygame.KEYUP, key=k, mod=0, scancode=0)])

    def level_screen(self, game: Game) -> LevelScreen:
        assert isinstance(game.screen, LevelScreen)
        return game.screen

    def write_file(self, n: int, i: int, text: str) -> Path:
        p = self.tmp / f"Lv{n}" / "VerilogFiles" / f"Traffic_signal_set_{i}.v"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def run_to_score(self, game: Game, dt: float = 0.25) -> None:
        screen = self.level_screen(game)
        for _ in range(3000):
            game.frame(dt, [])
            if screen.level.phase is Phase.DONE:
                break
        self.assertIs(screen.level.phase, Phase.DONE)
        for _ in range(20):
            game.frame(0.1, [])
            if isinstance(game.screen, ScoreScreen):
                return
        self.fail("no score screen")


def scripted_build(paths: Sequence[Path]) -> BuildResult:
    return BuildResult([ScriptedController(safe_controller) for _ in paths], [], [])


class MenuTest(UiBase):
    def test_menu_to_level(self) -> None:
        game = self.make_game()
        self.assertIsInstance(game.screen, MainMenu)
        game.frame(0.016, [])
        self.click(game, (987, 545))
        screen = self.level_screen(game)
        self.assertEqual(screen.level.data.number, 3)
        self.assertTrue((self.tmp / "Lv3/VerilogFiles/Traffic_signal_set_0.v").exists())

    def test_every_level_loads_and_draws(self) -> None:
        game = self.make_game()
        for n in range(13):
            game.open_level(n)
            game.frame(0.016, [])
            screen = self.level_screen(game)
            self.assertEqual(len(screen.level.cars), CARS[n])
            self.assertEqual(len(screen.level.town.controls), INTERS[n])
            files = os.listdir(self.tmp / f"Lv{n}" / "VerilogFiles")
            self.assertEqual(len(files), INTERS[n])
            self.assertEqual(screen.errors, [])
            self.assertEqual(game.logical.get_size(), (1280, 1500))

    def test_high_score_and_credits_screens(self) -> None:
        game = self.make_game()
        self.click(game, (512 + 125, 1280 - 305 - 60 + 30))
        self.assertIsInstance(game.screen, HighScoreScreen)
        assert isinstance(game.screen, HighScoreScreen)
        self.assertEqual(game.screen.page, 1)
        game.frame(0.016, [])
        self.click(game, (1225, 1380 - 500 - 300 + 150))
        self.assertEqual(game.screen.page, 2)
        self.click(game, (30 + 80, 1380 - 45 - 59 + 29))
        self.assertIsInstance(game.screen, MainMenu)
        self.click(game, (512 + 125, 1280 - 205 - 60 + 30))
        self.assertIsInstance(game.screen, CreditsScreen)
        game.frame(0.016, [])
        self.click(game, (1160, 1310))
        self.assertIsInstance(game.screen, MainMenu)

    def test_app_main(self) -> None:
        code = main(
            ["--level", "1", "--data-dir", str(self.tmp), "--frames", "3", "--no-editor"]
        )
        self.assertEqual(code, 0)

    def test_status_line_and_window_resize(self) -> None:
        game = self.make_game()
        game.open_level(1)
        pygame.display.set_mode((50, 50), pygame.RESIZABLE)
        game.frame(0.016, [])
        game.frame(0.016, [pygame.event.Event(pygame.VIDEORESIZE, size=(50, 50), w=50, h=50)])


class PlayTest(UiBase):
    def test_scripted_controller_drives_level(self) -> None:
        game = self.make_game(build=scripted_build)
        game.open_level(1)
        self.key(game, pygame.K_s)
        screen = self.level_screen(game)
        self.assertIs(screen.level.phase, Phase.RUN)
        self.run_to_score(game)
        score = game.screen
        assert isinstance(score, ScoreScreen)
        self.assertEqual(score.result.crashed, 0)
        self.assertGreaterEqual(score.result.passed, 1)
        first = (self.tmp / "Lv1/high_score.txt").read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(first, f"{score.result.passed} {score.result.ticks}")
        game.frame(0.016, [])
        self.click(game, (1000, 1380 - 151 - 49))
        self.assertEqual(self.level_screen(game).number, 2)

    def test_runtime_error_pauses(self) -> None:
        self.write_file(1, 0, "RUNTIME_ERROR")
        game = self.make_game()
        game.open_level(1)
        self.key(game, pygame.K_s)
        screen = self.level_screen(game)
        self.assertIs(screen.level.phase, Phase.RUN)
        game.frame(0.1, [])
        self.assertIs(screen.level.phase, Phase.PAUSE)
        self.assertTrue(screen.message.startswith("runtime error"))


class ErrorTest(UiBase):
    def test_compile_error_shown(self) -> None:
        path = self.write_file(2, 0, SYNTAX)
        self.write_file(2, 1, "module light1;")
        game = self.make_game()
        game.open_level(2)
        screen = self.level_screen(game)
        self.assertEqual(len(screen.errors), 1)
        self.assertEqual(screen.errors[0].line, 2)
        self.assertIs(screen.level.phase, Phase.EDIT)
        game.frame(0.016, [])
        self.key(game, pygame.K_s)
        self.assertIs(screen.level.phase, Phase.EDIT)
        path.write_text("module light1; // fixed", encoding="utf-8")
        game.frame(0.6, [])
        self.assertEqual(screen.errors, [])
        path.unlink()
        game.frame(0.6, [])
        self.assertEqual([e.message for e in screen.errors], ["cannot read file"])
        game.frame(0.016, [])

    def test_missing_port_shown(self) -> None:
        self.write_file(1, 0, "MISSING_OUTW")
        game = self.make_game()
        game.open_level(1)
        screen = self.level_screen(game)
        self.assertEqual([e.message for e in screen.errors], ["port 'outW' is missing"])
        self.key(game, pygame.K_s)
        self.assertIs(screen.level.phase, Phase.EDIT)

    def test_sim_unavailable(self) -> None:
        def build(paths: Sequence[Path]) -> BuildResult:
            raise SimUnavailable("needs Odin III 1.0.3")

        game = self.make_game(build=build)
        game.open_level(1)
        screen = self.level_screen(game)
        self.assertEqual(screen.sim_unavailable, "needs Odin III 1.0.3")
        game.frame(0.016, [])
        self.key(game, pygame.K_s)
        self.assertIs(screen.level.phase, Phase.EDIT)
        self.click(game, (32, 1348))
        self.assertIsNotNone(screen.level.editor.placing)


class MouseTest(UiBase):
    def test_sensor_placement_by_mouse(self) -> None:
        game = self.make_game()
        game.open_level(1)
        screen = self.level_screen(game)
        self.click(game, (32, 1348))
        self.assertIs(screen.level.editor.placing, screen.level.sensors.sensors[6])
        game.frame(0.016, [pygame.event.Event(pygame.MOUSEMOTION, pos=game.to_window((288, 452)),
                                              rel=(0, 0), buttons=(0, 0, 0))])
        self.click(game, (288, 100 + 1280 - 14 * 64 - 64 + 32))
        sensor = screen.level.sensors.sensors[6]
        self.assertEqual((sensor.x, sensor.y), (5, 15))
        text = (self.tmp / "Lv1/sensorFile.txt").read_text(encoding="utf-8")
        self.assertTrue(text.endswith("6 5 15\n"))
        self.click(game, (32, 1348))
        self.assertIsNotNone(screen.level.editor.placing)
        self.click(game, (1 * 64 + 32, 1380 - 1 * 64 - 64 + 32))
        self.assertIsNotNone(screen.level.editor.placing)
        game.window.fill((0, 0, 0))
        bar = pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(0, 0))
        game.frame(0, [bar])

    def test_letterbox_click_ignored(self) -> None:
        game = self.make_game()
        game.open_level(1)
        screen = self.level_screen(game)
        pygame.display.set_mode((800, 750), pygame.RESIZABLE)
        game.frame(0, [])
        ww, wh = game.window.get_size()
        scale, (ox, oy) = game.view.layout((ww, wh))
        self.assertGreater(ox, 0)
        pos = (ox - 1, wh // 2)
        down = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)
        up = pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos)
        game.frame(0, [down, up])
        self.assertIsNone(screen.level.editor.placing)

    def test_keys(self) -> None:
        game = self.make_game()
        game.open_level(1)
        screen = self.level_screen(game)
        self.key(game, pygame.K_h)
        self.assertTrue(screen.help_open)
        self.key(game, pygame.K_h)
        self.assertFalse(screen.help_open)
        screen.level.sensors.sensors[0].x = 5
        screen.level.sensors.sensors[0].y = 15
        self.key(game, pygame.K_c)
        self.assertFalse(screen.level.sensors.sensors[0].placed)
        old = screen.level
        self.key(game, pygame.K_r)
        self.assertIsNot(screen.level, old)
        self.key(game, pygame.K_ESCAPE)
        self.assertIs(game.screen, screen)
        self.key(game, pygame.K_s)
        self.assertIs(screen.level.phase, Phase.RUN)
        self.key(game, pygame.K_m)
        self.assertIs(game.screen, screen)
        self.key(game, pygame.K_s)
        self.assertIs(screen.level.phase, Phase.RUN)
        self.key(game, pygame.K_p)
        self.assertIs(screen.level.phase, Phase.PAUSE)
        self.key(game, pygame.K_s)
        self.assertIs(screen.level.phase, Phase.RUN)
        self.key(game, pygame.K_x)
        self.assertIs(screen.level.phase, Phase.PAUSE)
        self.key(game, pygame.K_h)
        self.assertTrue(screen.help_open)
        self.key(game, pygame.K_h)

    def test_menu_key_in_edit(self) -> None:
        game = self.make_game()
        game.open_level(1)
        self.key(game, pygame.K_m)
        self.assertIsInstance(game.screen, MainMenu)

    def test_zoom_keys(self) -> None:
        game = self.make_game()
        game.open_level(1)
        screen = self.level_screen(game)
        down = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q, mod=0, unicode="q", scancode=0)
        game.frame(0, [down])
        self.assertEqual(screen.camera.zoom, 0.98)
        game.frame(0, [])
        self.assertEqual(screen.camera.zoom, 0.96)
        game.frame(0, [pygame.event.Event(pygame.KEYUP, key=pygame.K_q, mod=0, scancode=0)])
        self.assertEqual(screen.camera.zoom, 0.96)
        a = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=0, unicode="a", scancode=0)
        game.frame(0, [a])
        self.assertEqual(screen.camera.zoom, 0.98)

    def test_zoom_and_pan_in_level(self) -> None:
        game = self.make_game()
        game.open_level(1)
        screen = self.level_screen(game)
        game.frame(0, [pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1)])
        self.assertEqual(screen.camera.zoom, 0.96)
        self.click(game, (15, 1367))
        self.assertIsNotNone(screen.level.editor.placing)
        target = None
        for ly in range(100, 1300, 8):
            for lx in range(0, 1280, 8):
                tile = screen.camera.tile_at(lx, ly)
                if tile is not None and screen.level.editor.valid_tile(*tile):
                    target = (lx, ly, tile)
                    break
            if target:
                break
        assert target is not None
        self.click(game, (target[0], target[1]))
        sensor = screen.level.sensors.sensors[6]
        self.assertEqual((sensor.x, sensor.y), target[2])
        right = pygame.event.Event(
            pygame.KEYDOWN, key=pygame.K_RIGHT, mod=0, unicode="", scancode=0
        )
        game.frame(0, [right])
        self.assertEqual(screen.camera.x, 643.0)
        game.frame(0, [])
        self.assertEqual(screen.camera.x, 646.0)
        game.frame(0, [pygame.event.Event(pygame.KEYUP, key=pygame.K_RIGHT, mod=0, scancode=0)])
        self.key(game, pygame.K_h)
        before = screen.camera.zoom
        game.frame(0, [pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1)])
        self.assertEqual(screen.camera.zoom, before)


if __name__ == "__main__":
    unittest.main()
