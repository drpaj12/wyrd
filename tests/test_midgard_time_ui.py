from __future__ import annotations

import importlib.util
import random
import unittest
from collections.abc import Callable, Sequence
from pathlib import Path

from tests.test_midgard_ui import UiBase, scripted_build

HAVE_PYGAME = importlib.util.find_spec("pygame") is not None
if HAVE_PYGAME:
    import pygame

    from tests.fakes_midgard import FakeLightBackend
    from wyrd.midgard.model.controllers import (
        BuildResult,
        ScriptedController,
        safe_controller,
    )
    from wyrd.midgard.model.level import LevelResult, Phase
    from wyrd.midgard.ui.clockstrip import BUTTONS, inspector_lines
    from wyrd.midgard.ui.game import Game
    from wyrd.midgard.ui.levelscreen import LevelScreen

Trace = list[tuple[int, int, int, int, tuple[int, int, int, int]]]


def setUpModule() -> None:
    if HAVE_PYGAME:
        pygame.display.init()
        pygame.font.init()


def tearDownModule() -> None:
    if HAVE_PYGAME:
        pygame.quit()


@unittest.skipUnless(HAVE_PYGAME, "pygame-ce is not installed")
class TimeBase(UiBase):
    def start_level(
        self, speed: int = 4, backend: FakeLightBackend | None = None
    ) -> tuple[Game, LevelScreen, FakeLightBackend]:
        backend = backend or FakeLightBackend()
        game = self.make_game(backend=backend, speed=speed)
        game.open_level(1)
        return game, self.level_screen(game), backend

    def advance(self, game: Game, ticks: int) -> None:
        game.frame(ticks / (60 * game.speed), [])

    def started(self, game: Game, ticks: int = 0) -> None:
        self.key(game, pygame.K_s)
        self.advance(game, ticks)
        self.key(game, pygame.K_p)

    def press(self, game: Game, key: int) -> None:
        self.key(game, key)

    def strip_click(self, game: Game, screen: LevelScreen, name: str) -> None:
        x, y, w, h = screen.strip.rects[name]
        self.click(game, (x + w // 2, y + h // 2))


class SpeedTest(TimeBase):
    def test_speed_keys_and_buttons(self) -> None:
        game, screen, _ = self.start_level(speed=1)
        self.assertEqual(screen.strip.title(screen.level, 1), "Tick 0  00:00  1x")
        for key, want in ((pygame.K_2, 2), (pygame.K_4, 4), (pygame.K_1, 1)):
            self.key(game, key)
            self.assertEqual(game.speed, want)
        self.strip_click(game, screen, "x2")
        self.assertEqual(game.speed, 2)
        self.assertEqual(sorted(screen.strip.rects), sorted(BUTTONS))
        self.assertIsNone(screen.strip.hit((5, 5)))
        x, y, w, h = screen.strip.rects["x4"]
        self.assertEqual(screen.strip.hit((x + 1, y + 1)), "x4")
        game.frame(0.016, [])

    def test_title_phases(self) -> None:
        game, screen, _ = self.start_level()
        self.started(game, 3)
        self.assertEqual(screen.strip.title(screen.level, 4), "Tick 3  00:00  PAUSED")
        self.key(game, pygame.K_s)
        self.assertEqual(screen.strip.title(screen.level, 4), "Tick 3  00:00  4x")


class StepTest(TimeBase):
    def test_step_is_exactly_one_edge(self) -> None:
        game, screen, backend = self.start_level()
        self.started(game, 5)
        handles = backend.live()
        self.assertEqual(len(handles), 2)
        n0 = [len(h.log) for h in handles]
        t0 = screen.level.ticks
        speed = game.speed
        self.key(game, pygame.K_PERIOD)
        self.assertEqual(screen.level.ticks, t0 + 1)
        self.assertEqual([len(h.log) for h in handles], [n + 1 for n in n0])
        for _ in range(5):
            self.key(game, pygame.K_PERIOD)
        self.assertEqual(screen.level.ticks, t0 + 6)
        self.assertEqual([len(h.log) for h in handles], [n + 6 for n in n0])
        self.assertEqual(game.speed, speed)
        self.strip_click(game, screen, "step")
        self.assertEqual(screen.level.ticks, t0 + 7)

    def test_step_ignored_in_run(self) -> None:
        game, screen, _ = self.start_level()
        self.key(game, pygame.K_s)
        self.key(game, pygame.K_PERIOD)
        self.assertEqual(screen.level.ticks, 0)
        self.assertIs(screen.level.phase, Phase.RUN)

    def test_pause_means_no_ticks(self) -> None:
        game, screen, _ = self.start_level()
        self.started(game, 5)
        t0 = screen.level.ticks
        for _ in range(3):
            game.frame(5.0, [])
        self.assertEqual(screen.level.ticks, t0)
        self.assertIs(screen.level.phase, Phase.PAUSE)

    def test_step_from_edit_starts_paused(self) -> None:
        game, screen, backend = self.start_level()
        self.key(game, pygame.K_PERIOD)
        self.assertIs(screen.level.phase, Phase.PAUSE)
        self.assertEqual(screen.level.ticks, 0)
        handles = backend.live()
        self.assertEqual([len(h.log) for h in handles], [1, 1])
        self.key(game, pygame.K_PERIOD)
        self.assertEqual(screen.level.ticks, 1)

    def test_pause_button(self) -> None:
        game, screen, _ = self.start_level()
        self.key(game, pygame.K_s)
        self.strip_click(game, screen, "pause")
        self.assertIs(screen.level.phase, Phase.PAUSE)
        self.strip_click(game, screen, "pause")
        self.assertIs(screen.level.phase, Phase.RUN)


class DeterminismTest(TimeBase):
    def traced_game(self, speed: int, dt: Callable[[], float]) -> tuple[Trace, LevelResult, int]:
        trace: Trace = []

        def build(paths: Sequence[Path]) -> BuildResult:
            ctls = []
            for i, _ in enumerate(paths):

                def fn(light: int, general: int, i: int = i) -> tuple[int, int, int, int]:
                    out = safe_controller(light, general)
                    trace.append((i, len(trace), light, general, out))
                    return out

                ctls.append(ScriptedController(fn))
            return BuildResult(list(ctls), [], [])

        game = self.make_game(build=build, speed=speed, data=self.tmp / f"s{speed}")
        game.tick_clock.max_backlog = 10**6
        game.open_level(1)
        screen = self.level_screen(game)
        self.key(game, pygame.K_s)
        frames = 0
        while screen.level.phase is not Phase.DONE and frames < 20000:
            frames += 1
            game.frame(dt(), [])
        self.assertIs(screen.level.phase, Phase.DONE)
        return trace, screen.level.result(), frames

    def test_speed_does_not_change_outcome_ui(self) -> None:
        runs = [self.traced_game(s, lambda: 0.05) for s in (1, 2, 4)]
        for trace, result, _ in runs[1:]:
            self.assertEqual(trace, runs[0][0])
            self.assertEqual(result, runs[0][1])
        self.assertLess(runs[2][2] * 3, runs[0][2])

    def test_determinism_frame_rates_ui(self) -> None:
        rng = random.Random(7)
        schedules: list[Callable[[], float]] = [
            lambda: 1 / 60,
            lambda: 1 / 30,
            lambda: 1 / 144,
            lambda: rng.uniform(0.001, 0.2),
        ]
        logs: list[list[list[tuple[int, int, int]]]] = []
        results: list[LevelResult] = []
        for k, schedule in enumerate(schedules):
            backend = FakeLightBackend()
            game = self.make_game(backend=backend, speed=4, data=self.tmp / f"f{k}")
            game.tick_clock.max_backlog = 10**6
            game.open_level(1)
            screen = self.level_screen(game)
            self.key(game, pygame.K_s)
            frames = 0
            while screen.level.phase is not Phase.DONE and frames < 200000:
                frames += 1
                game.frame(schedule(), [])
            self.assertIs(screen.level.phase, Phase.DONE)
            logs.append([h.log for h in backend.live()])
            results.append(screen.level.result())
        for log, result in zip(logs[1:], results[1:], strict=True):
            self.assertEqual(log, logs[0])
            self.assertEqual(result, results[0])


class InspectorTest(TimeBase):
    def test_inspector_in_pause(self) -> None:
        game, screen, _ = self.start_level()
        self.assertEqual(inspector_lines(screen.level.controllers), [])
        self.key(game, pygame.K_s)
        self.assertEqual(
            inspector_lines(screen.level.controllers), ["0: no step yet", "1: no step yet"]
        )
        self.advance(game, 3)
        self.key(game, pygame.K_p)
        lines = inspector_lines(screen.level.controllers)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("0: sensor_light="))
        self.assertIn("N=", lines[0])
        self.assertIn("general=0x", lines[0])
        game.frame(0.016, [])

    def test_inspector_names(self) -> None:
        c = ScriptedController(lambda a, b: (0, 1, 4, 6))
        c.step(0b00010000, 0xAB)
        (line,) = inspector_lines([c])
        self.assertEqual(
            line,
            "0: sensor_light=00010000 general=0x000000ab N=Stop S=Forward E=Go W=Stop(6)",
        )


class RecordTest(TimeBase):
    def test_record_and_export(self) -> None:
        game, screen, _ = self.start_level()
        self.key(game, pygame.K_v)
        self.key(game, pygame.K_s)
        self.advance(game, 10)
        self.key(game, pygame.K_p)
        ctls = screen.level.controllers
        recs = [c.recording() for c in ctls]
        self.assertEqual([len(r.samples) for r in recs if r is not None], [11, 11])
        self.key(game, pygame.K_e)
        for i in range(2):
            path = self.tmp / f"Lv1/recordings/intersection_{i}.vcd"
            self.assertIn("sensor_light", path.read_text(encoding="utf-8"))
        self.assertIn("intersection_0.vcd", screen.message)
        self.key(game, pygame.K_v)
        self.assertTrue(all(c.recording() is None for c in ctls))
        self.key(game, pygame.K_e)
        self.assertEqual(screen.message, "nothing recorded")

    def test_record_button_after_start(self) -> None:
        game, screen, _ = self.start_level()
        self.started(game, 2)
        self.strip_click(game, screen, "rec")
        self.assertTrue(all(c.recording() is not None for c in screen.level.controllers))
        self.strip_click(game, screen, "rec")
        self.assertTrue(all(c.recording() is None for c in screen.level.controllers))

    def test_waveform_button(self) -> None:
        game, screen, _ = self.start_level()
        opened: list[Path] = []

        def stub(path: Path) -> bool:
            opened.append(path)
            return True

        game.open_waveform = stub
        self.strip_click(game, screen, "waveform")
        self.assertEqual(opened, [])
        self.key(game, pygame.K_v)
        self.started(game, 4)
        self.strip_click(game, screen, "waveform")
        self.assertEqual(opened, [self.tmp / "Lv1/recordings/intersection_0.vcd"])
        self.assertTrue(opened[0].exists())

    def test_export_button(self) -> None:
        game, screen, _ = self.start_level()
        self.key(game, pygame.K_v)
        self.started(game, 4)
        self.strip_click(game, screen, "export")
        self.assertTrue((self.tmp / "Lv1/recordings/intersection_1.vcd").exists())


class ScriptedTimeTest(TimeBase):
    def test_scripted_build_still_works(self) -> None:
        game = self.make_game(build=scripted_build)
        game.open_level(1)
        self.key(game, pygame.K_v)
        self.key(game, pygame.K_s)
        self.key(game, pygame.K_p)
        self.key(game, pygame.K_e)
        self.assertEqual(self.level_screen(game).message, "nothing recorded")


if __name__ == "__main__":
    unittest.main()
