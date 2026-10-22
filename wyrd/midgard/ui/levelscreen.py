"""The level screen: input, ticking, file watch and drawing (spec 5.3, 8, 9)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pygame

from wyrd.bifrost import SimUnavailable
from wyrd.midgard.model.car import Car
from wyrd.midgard.model.controllers import BuildResult, ControllerError, PlayerError
from wyrd.midgard.model.grid import Node
from wyrd.midgard.model.level import Level, Phase
from wyrd.midgard.model.levelxml import level_path, parse_level_file
from wyrd.midgard.model.traffic import TrafficControl
from wyrd.midgard.model.watch import FileWatcher, editor_command
from wyrd.midgard.ui import layers
from wyrd.midgard.ui.camera import Camera
from wyrd.midgard.ui.clockstrip import ClockStrip, draw_inspector, inspector_lines
from wyrd.midgard.ui.draw import draw_text
from wyrd.midgard.ui.game import Event, Game, Pos, Screen
from wyrd.midgard.ui.view import LEVEL_SIZE

CAMERA_H = 1380
EDITOR_COOLDOWN = 0.6
DONE_DELAY = 1.0
PAN_STEP = 3.0
PAN_KEYS = {
    pygame.K_LEFT: (-PAN_STEP, 0.0),
    pygame.K_RIGHT: (PAN_STEP, 0.0),
    pygame.K_UP: (0.0, PAN_STEP),
    pygame.K_DOWN: (0.0, -PAN_STEP),
}
ZOOM_IN_KEYS = (pygame.K_q, pygame.K_EQUALS)
ZOOM_OUT_KEYS = (pygame.K_a, pygame.K_MINUS)
FILE_CHANGED = "File changed: press R to restart with the new code"


class LevelScreen(Screen):
    logical_size = LEVEL_SIZE

    def __init__(self, game: Game, number: int) -> None:
        self.game = game
        self.number = number
        self.camera = Camera()
        self.strip = ClockStrip()
        self.recording = False
        self.world = pygame.Surface((1280, CAMERA_H))
        self.message = ""
        self.help_open = False
        self.done_timer = 0.0
        self.sim_unavailable: str | None = None
        self.mouse: Pos = None
        self.held: set[int] = set()
        self.last_real = (0.0, 0.0)
        self.last_editor_open = -1e9
        self._watch_acc = 0.0
        self._score_sent = False
        self._preview: Car | None = None
        self._preview_frames = 0
        self.built: BuildResult | None = None
        self._load()

    def _load(self) -> None:
        data = parse_level_file(level_path(self.number))
        self.level = Level(data, self.game.userdata.load_sensors(self.number))
        count = len(self.level.town.controls)
        self.errors: list[PlayerError] = []
        self.warnings: list[str] = []
        self.paths: list[Path] = self._level_files(count)
        self.watcher = FileWatcher(self.paths)
        n_cars = len(self.level.cars)
        self.car_frames = [layers.car_frame_index(self.number, k) for k in range(n_cars)]
        if self.files_ready:
            self.compile()

    def _level_files(self, count: int) -> list[Path]:
        userdata = self.game.userdata
        try:
            paths = userdata.ensure_level_files(self.number, count)
        except OSError as exc:
            self.files_ready = False
            self.message = f"Cannot create the level files: {exc}"
            return userdata.verilog_paths(self.number, count)
        self.files_ready = True
        return paths

    @property
    def phase(self) -> Phase:
        return self.level.phase

    # compile and start

    def _close_built(self) -> None:
        if self.built is not None:
            for c in self.built.controllers:
                if c is not None:
                    c.close()
        self.built = None

    def compile(self) -> None:
        self._close_built()
        self.errors = []
        self.warnings = []
        previous, self.sim_unavailable = self.sim_unavailable, None
        if previous is not None and self.message == previous:
            self.message = ""
        try:
            built = self.game.build(self.paths)
        except SimUnavailable as exc:
            self.sim_unavailable = self.message = str(exc)
            return
        self.built = built
        self.errors = list(built.errors)
        self.warnings = [d.raw for d in built.warnings]

    def try_start(self) -> None:
        if self.phase is not Phase.EDIT:
            return
        if not self.files_ready:
            return
        self.compile()
        built = self.built
        if self.sim_unavailable is not None or built is None:
            self.message = self.sim_unavailable or "Cannot start"
            return
        if not built.ok:
            self.message = "Fix the errors before starting"
            return
        try:
            self.level.start([c for c in built.controllers if c is not None])
        except ControllerError as exc:
            self.message = str(exc)
            return
        if self.recording:
            for c in self.level.controllers:
                c.start_recording()
        self.message = ""
        self.game.tick_clock.reset()

    def restart(self) -> None:
        self._close_built()
        self.help_open = False
        self.done_timer = 0.0
        self.message = ""
        self.recording = False
        self.camera = Camera()
        self._load()

    def close(self) -> None:
        self._close_built()

    # editor

    def open_editor(self, index: int) -> None:
        path = self.paths[index]
        self.last_editor_open = self.game.now()
        try:
            command = editor_command(path, os.environ, shutil.which)
        except ValueError as exc:
            self.message = f"MIDGARD_EDITOR: {exc}"
            return
        if command is None or not self.game.editor:
            self.message = f"Edit this file: {path}"
            return
        try:
            self.game.spawn(command)
        except OSError as exc:
            self.message = f"Cannot start the editor: {exc}"
            return
        self.message = f"Editing {path.name}"

    # input

    def handle_event(self, event: Event, pos: Pos) -> None:
        t = event.type
        if t == pygame.KEYDOWN:
            self.held.add(event.key)
            self._key(event.key)
        elif t == pygame.KEYUP:
            self.held.discard(event.key)
        elif t == pygame.MOUSEWHEEL:
            if self.camera_enabled():
                self.camera.wheel(-1 if event.y > 0 else 1 if event.y < 0 else 0)
        elif t == pygame.MOUSEMOTION:
            self._motion(event, pos)
        elif t == pygame.MOUSEBUTTONDOWN:
            self.mouse = pos
            if pos is not None and pos[1] < CAMERA_H:
                self.last_real = self.camera.to_world(*pos)
        elif t == pygame.MOUSEBUTTONUP:
            self.mouse = pos
            if pos is not None and pos[1] >= CAMERA_H and event.button == 1:
                if not self.help_open:
                    self._strip_click(pos)
            elif pos is not None:
                self._release(event.button, pos)

    def focus_lost(self) -> None:
        self.held.clear()

    def camera_enabled(self) -> bool:
        return not self.help_open and self.phase is not Phase.DONE

    def _key(self, key: int) -> None:
        actions = {
            pygame.K_s: self._key_start,
            pygame.K_p: self._key_pause,
            pygame.K_x: self._key_pause,
            pygame.K_h: self._key_help,
            pygame.K_r: self.restart,
            pygame.K_m: self._key_menu,
            pygame.K_c: self._key_clear,
            pygame.K_PERIOD: self._key_step,
            pygame.K_1: lambda: self._set_speed(1),
            pygame.K_2: lambda: self._set_speed(2),
            pygame.K_4: lambda: self._set_speed(4),
            pygame.K_v: self._key_record,
            pygame.K_e: self.export,
        }
        action = actions.get(key)
        if action is not None:
            action()

    def _key_start(self) -> None:
        if self.phase is Phase.EDIT:
            self.try_start()
        elif self.phase is Phase.PAUSE:
            self.level.toggle_pause()

    def _key_pause(self) -> None:
        if self.phase is Phase.RUN:
            self.level.toggle_pause()

    def _key_help(self) -> None:
        if self.phase in (Phase.EDIT, Phase.PAUSE):
            self.help_open = not self.help_open

    def _key_menu(self) -> None:
        if self.phase is Phase.EDIT:
            self.game.open_menu()

    def _key_clear(self) -> None:
        if self.phase is Phase.EDIT:
            self.level.editor.clear_all()
            self._save_sensors()

    def _set_speed(self, speed: int) -> None:
        self.game.speed = speed

    def _key_step(self) -> None:
        if self.phase is Phase.EDIT:
            self.try_start()
            self._pause_if_running()
        elif self.phase is Phase.PAUSE:
            try:
                self.level.step_once()
            except ControllerError as exc:
                self.message = str(exc)
                self._pause_if_running()

    def _pause_if_running(self) -> None:
        if self.phase is Phase.RUN:
            self.level.toggle_pause()

    def _key_record(self) -> None:
        self.recording = not self.recording
        if self.phase is Phase.EDIT:
            self.message = "Recording armed" if self.recording else "Recording off"
            return
        for c in self.level.controllers:
            if self.recording:
                c.start_recording()
            else:
                c.stop_recording()
        self.message = "Recording" if self.recording else "Recording stopped"

    def export(self) -> list[Path]:
        """Write one VCD per recorded intersection (PAUSE or DONE); return the paths."""
        if self.phase not in (Phase.PAUSE, Phase.DONE):
            return []
        folder = self.game.userdata.recordings_dir(self.number)
        paths: list[Path] = []
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for i, c in enumerate(self.level.controllers):
                if c.recording() is not None:
                    paths.append(folder / f"intersection_{i}.vcd")
                    c.export_vcd(paths[-1])
        except (OSError, ControllerError) as exc:
            self.message = f"Export failed: {exc}"
            return []
        names = ", ".join(str(p) for p in paths)
        self.message = f"Exported: {names}" if paths else "nothing recorded"
        return paths

    def _waveform(self) -> None:
        paths = self.export()
        if paths:
            self.game.open_waveform(paths[0])

    def _strip_click(self, pos: tuple[int, int]) -> None:
        actions = {
            "pause": self._key_pause_toggle,
            "step": self._key_step,
            "x1": lambda: self._set_speed(1),
            "x2": lambda: self._set_speed(2),
            "x4": lambda: self._set_speed(4),
            "rec": self._key_record,
            "export": self.export,
            "waveform": self._waveform,
        }
        name = self.strip.hit(pos)
        if name is not None:
            actions[name]()

    def _key_pause_toggle(self) -> None:
        if self.phase in (Phase.RUN, Phase.PAUSE):
            self.level.toggle_pause()

    def _motion(self, event: Event, pos: Pos) -> None:
        self.mouse = pos
        if pos is None or pos[1] >= CAMERA_H or not any(event.buttons):
            return
        if not self.camera_enabled():
            return
        self.camera.drag(self.last_real, self.camera.to_world(*pos))
        self.last_real = self.camera.to_world(*pos)

    def _node(self, ix: int, iy: int) -> Node | None:
        grid = self.level.town.grid
        if 0 <= ix < len(grid) and 0 <= iy < len(grid[ix]):
            return grid[ix][iy]
        return None

    def _release(self, button: int, pos: tuple[int, int]) -> None:
        if pos[1] >= CAMERA_H or self.help_open or self.phase is not Phase.EDIT:
            return
        tile = self.camera.tile_at(*pos)
        if tile is None:
            return
        if button == 1:
            self._left_release(*tile)
        elif button == 3:
            self.level.editor.right_release(*tile)
        self._save_sensors()

    def _left_release(self, ix: int, iy: int) -> None:
        editor = self.level.editor
        node = self._node(ix, iy)
        if editor.placing is None and node is not None and node.control is not None:
            if self.game.now() - self.last_editor_open >= EDITOR_COOLDOWN:
                self.open_editor(node.control.index)
            return
        editor.left_release(ix, iy)

    def _save_sensors(self) -> None:
        editor = self.level.editor
        if not editor.dirty:
            return
        editor.dirty = False
        error = self.game.userdata.save_sensors(self.number, self.level.sensors)
        if error:
            self.message = error

    # update

    def update(self, dt: float) -> None:
        self._camera_keys()
        self._tick(dt)
        self._poll_watch(dt)
        self._finish(dt)
        self._preview_frames += 1

    def _camera_keys(self) -> None:
        if not self.camera_enabled():
            return
        for key in self.held:
            if key in ZOOM_IN_KEYS:
                self.camera.key_zoom_in()
            elif key in ZOOM_OUT_KEYS:
                self.camera.key_zoom_out()
            elif key in PAN_KEYS:
                self.camera.pan(*PAN_KEYS[key])

    def _tick(self, dt: float) -> None:
        game = self.game
        if self.phase is not Phase.RUN:
            game.tick_clock.reset()
            return
        for _ in range(game.tick_clock.advance(dt, game.speed)):
            try:
                self.level.tick()
            except ControllerError as exc:
                self.level.toggle_pause()
                self.message = str(exc)
                return
            if self.phase is not Phase.RUN:
                return

    def _poll_watch(self, dt: float) -> None:
        self._watch_acc += dt
        if self._watch_acc < self.game.watch_interval:
            return
        self._watch_acc = 0.0
        if not self.watcher.poll():
            return
        if self.phase is Phase.EDIT:
            self.compile()
        else:
            self.message = FILE_CHANGED

    def _finish(self, dt: float) -> None:
        if self.phase is not Phase.DONE or self._score_sent:
            return
        self.done_timer += dt
        if self.done_timer >= DONE_DELAY:
            self._score_sent = True
            self.game.open_score_screen(self.number, self.level.result())

    # drawing

    def hover_node(self) -> Node | None:
        if self.mouse is None or self.mouse[1] >= CAMERA_H:
            return None
        tile = self.camera.tile_at(*self.mouse)
        return None if tile is None else self._node(*tile)

    def hover_control(self) -> TrafficControl | None:
        node = self.hover_node()
        if node is None or self.phase is not Phase.EDIT or self.level.editor.placing:
            return None
        return node.control

    def draw(self, surface: pygame.Surface) -> None:
        surface.fill((0, 0, 0))
        self._draw_world()
        self._blit_camera(surface)
        layers.draw_score_bar(surface, self.game.assets, self.level.result())
        self._draw_clock(surface)
        self._draw_status(surface)
        layers.draw_error_panel(surface, self.game.assets, self.errors)
        if self.help_open:
            layers.draw_help(surface, self.game.assets)

    def _draw_clock(self, surface: pygame.Surface) -> None:
        a, level, game = self.game.assets, self.level, self.game
        self.strip.draw(surface, a, level, game.speed, self.recording, level.controllers)
        if self.phase in (Phase.PAUSE, Phase.DONE):
            draw_inspector(surface, a, inspector_lines(level.controllers))

    def _draw_world(self) -> None:
        w, assets, level = self.world, self.game.assets, self.level
        w.fill((0, 0, 0))
        layers.draw_map(w, assets, self.number)
        layers.draw_sensors(w, assets, level.sensors)
        layers.draw_cars(w, assets, level.cars, self.car_frames)
        failed = {e.index for e in self.errors}
        layers.draw_signals(w, assets, level.town.controls, failed, self.hover_control())
        self._draw_placing(w)
        self._draw_preview(w)

    def _draw_placing(self, w: pygame.Surface) -> None:
        sensor = self.level.editor.placing
        if sensor is None or self.mouse is None or self.mouse[1] >= CAMERA_H:
            return
        world = self.camera.to_world(*self.mouse)
        tile = self.camera.tile_at(*self.mouse)
        valid = tile is not None and self.level.editor.valid_tile(*tile)
        layers.draw_placing(w, self.game.assets, sensor.number, world, valid)

    def _draw_preview(self, w: pygame.Surface) -> None:
        node = self.hover_node() if self.phase is Phase.PAUSE and not self.help_open else None
        car = None if node is None else node.car
        if car is not self._preview:
            self._preview = car
            self._preview_frames = 0
        if car is not None:
            layers.draw_path_preview(w, self.game.assets, car, self._preview_frames // 4)

    def _blit_camera(self, surface: pygame.Surface) -> None:
        left, bottom, width, height = self.camera.visible_rect()
        top = round(CAMERA_H - bottom - height)
        src = pygame.Rect(round(left), top, round(width), round(height))
        src = src.clip(self.world.get_rect())
        if src.size == (1280, CAMERA_H):
            surface.blit(self.world, (0, 0))
        elif src.width > 0 and src.height > 0:
            part = self.world.subsurface(src)
            surface.blit(pygame.transform.smoothscale(part, (1280, CAMERA_H)), (0, 0))

    def _draw_status(self, surface: pygame.Surface) -> None:
        tps = self.game.speed * self.game.tick_clock.ticks_per_second
        text = f"{self.phase.name}  {tps} ticks/s  {self.message}".rstrip()
        draw_text(surface, self.game.assets, text, (10, 104), 24, (255, 255, 255))
