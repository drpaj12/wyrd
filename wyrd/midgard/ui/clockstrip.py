"""The clock strip under the level and the pause inspector (spec 9.4)."""

from __future__ import annotations

from collections.abc import Sequence

import pygame

from wyrd.midgard.model.controllers import LightController
from wyrd.midgard.model.level import Level, Phase
from wyrd.midgard.model.scores import format_time
from wyrd.midgard.ui.assets import Assets
from wyrd.midgard.ui.draw import draw_text

BUTTONS = ("pause", "step", "x1", "x2", "x4", "rec", "export", "waveform")
LABELS = {
    "pause": "Pause/Resume",
    "step": "Step",
    "x1": "1x",
    "x2": "2x",
    "x4": "4x",
    "rec": "Rec",
    "export": "Export VCD",
    "waveform": "Waveform",
}
WIDTHS = {
    "pause": 140,
    "step": 80,
    "x1": 50,
    "x2": 50,
    "x4": 50,
    "rec": 60,
    "export": 130,
    "waveform": 120,
}
STRIP_Y = 1380
BUTTON_Y = 1440
BUTTON_H = 44
FIRST_X = 480
GAP = 10
CODE_NAMES = ("Stop", "Forward", "Left", "Right", "Go")
HINT = "1 tick = 1 clock edge of your module"
TUTORIAL = (
    "The clk of your module rises once per tick; rst is low in the reset cycle;",
    "outputs are read after the edge; 60 ticks per second at 1x.",
)
SPEED_BUTTON = {1: "x1", 2: "x2", 4: "x4"}


def _layout() -> dict[str, tuple[int, int, int, int]]:
    rects: dict[str, tuple[int, int, int, int]] = {}
    x = FIRST_X
    for name in BUTTONS:
        rects[name] = (x, BUTTON_Y, WIDTHS[name], BUTTON_H)
        x += WIDTHS[name] + GAP
    return rects


def code_name(code: int) -> str:
    return CODE_NAMES[code] if 0 <= code < len(CODE_NAMES) else f"Stop({code})"


def inspector_lines(controllers: Sequence[LightController | None]) -> list[str]:
    lines: list[str] = []
    for i, c in enumerate(controllers):
        if c is None or c.last_inputs is None or c.last_outputs is None:
            lines.append(f"{i}: no step yet")
            continue
        light, general = c.last_inputs
        n, s, e, w = (code_name(code) for code in c.last_outputs)
        lines.append(
            f"{i}: sensor_light={light:08b} general=0x{general:08x} N={n} S={s} E={e} W={w}"
        )
    return lines


class ClockStrip:
    def __init__(self) -> None:
        self.rects = _layout()

    def hit(self, pos: tuple[int, int]) -> str | None:
        for name, (x, y, w, h) in self.rects.items():
            if x <= pos[0] <= x + w and y <= pos[1] <= y + h:
                return name
        return None

    def title(self, level: Level, speed: int) -> str:
        if level.phase is Phase.PAUSE:
            rate = "PAUSED"
        elif level.phase is Phase.DONE:
            rate = "DONE"
        else:
            rate = f"{speed}x"
        return f"Tick {level.ticks}  {format_time(level.ticks)}  {rate}"

    def draw(
        self,
        surface: pygame.Surface,
        assets: Assets,
        level: Level,
        speed: int,
        recording: bool,
        controllers: Sequence[LightController | None],
    ) -> None:
        surface.fill((0, 0, 0), pygame.Rect(0, STRIP_Y, 1280, 120))
        draw_text(surface, assets, self.title(level, speed), (10, STRIP_Y + 8), 34)
        self._draw_hints(surface, assets, level)
        on = {SPEED_BUTTON.get(speed, ""), "rec" if recording else ""}
        for name, rect in self.rects.items():
            self._draw_button(surface, assets, name, rect, name in on)
        if recording:
            self._draw_recording(surface, assets, controllers)

    def _draw_hints(self, surface: pygame.Surface, assets: Assets, level: Level) -> None:
        lines = [HINT]
        if level.data.number == 0 and level.phase is Phase.EDIT:
            lines += TUTORIAL
        for k, line in enumerate(lines):
            draw_text(surface, assets, line, (10, STRIP_Y + 46 + 22 * k), 20, (200, 200, 200))

    def _draw_button(
        self,
        surface: pygame.Surface,
        assets: Assets,
        name: str,
        rect: tuple[int, int, int, int],
        on: bool,
    ) -> None:
        fill = (150, 40, 40) if on and name == "rec" else (60, 90, 140) if on else (50, 50, 50)
        pygame.draw.rect(surface, fill, rect)
        pygame.draw.rect(surface, (200, 200, 200), rect, 1)
        label = assets.font(24).render(LABELS[name], True, (255, 255, 255))
        x, y, w, h = rect
        surface.blit(label, (x + (w - label.get_width()) // 2, y + (h - label.get_height()) // 2))

    def _draw_recording(
        self,
        surface: pygame.Surface,
        assets: Assets,
        controllers: Sequence[LightController | None],
    ) -> None:
        count = 0
        for c in controllers:
            rec = None if c is None else c.recording()
            if rec is not None:
                count = max(count, len(rec.samples))
        draw_text(surface, assets, f"REC {count} samples", (480, STRIP_Y + 10), 24, (255, 120, 120))


def draw_inspector(surface: pygame.Surface, assets: Assets, lines: Sequence[str]) -> None:
    if not lines:
        return
    panel = pygame.Surface((1180, 12 + 24 * len(lines)), pygame.SRCALPHA)
    panel.fill((20, 20, 20, 200))
    top = STRIP_Y - 8 - panel.get_height()
    surface.blit(panel, (80, top))
    for k, line in enumerate(lines):
        draw_text(surface, assets, line, (92, top + 6 + 24 * k), 22, (230, 230, 120))
