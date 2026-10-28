"""Midgard III against a real Odin III (skipped when the simulation API is absent)."""

from __future__ import annotations

import random
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

from tests.test_midgard_level import INTERS, make_level, scripted
from wyrd.bifrost import Recording, odin3_available
from wyrd.midgard.model import ASSETS
from wyrd.midgard.model.clock import TickClock
from wyrd.midgard.model.controllers import (
    LightController,
    build_controllers,
    safe_controller,
)
from wyrd.midgard.model.level import Level, LevelResult, Phase
from wyrd.midgard.model.userdata import UserData

Trace = list[tuple[int, int, int, int, int, int, int]]


class Tracer:
    """Records every step of a real controller: tick, inputs and the four output codes."""

    def __init__(
        self, inner: LightController, level_ticks: Callable[[], int], trace: Trace
    ) -> None:
        self.inner = inner
        self.level_ticks = level_ticks
        self.trace = trace
        self.last_inputs: tuple[int, int] | None = None
        self.last_outputs: tuple[int, int, int, int] | None = None

    def start(self) -> None:
        self.inner.start()

    def step(self, light_sensors: int, general_sensors: int) -> tuple[int, int, int, int]:
        out = self.inner.step(light_sensors, general_sensors)
        self.trace.append((self.level_ticks(), light_sensors, general_sensors, *out))
        return out

    def close(self) -> None:
        self.inner.close()

    def start_recording(self) -> None:
        self.inner.start_recording()

    def stop_recording(self) -> None:
        self.inner.stop_recording()

    def recording(self) -> Recording | None:
        return self.inner.recording()

    def export_vcd(self, path: Path) -> None:
        self.inner.export_vcd(path)


@unittest.skipUnless(odin3_available(), "odin3 with the simulation API is not installed")
class RealOdin3Test(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.starter = ASSETS / "starter.v"

    def controllers(self, files: list[Path]) -> list[LightController]:
        result = build_controllers(files)
        self.assertEqual([str(e) for e in result.errors], [])
        built = [c for c in result.controllers if c is not None]
        for c in built:
            self.addCleanup(c.close)
        return built

    def test_starter_builds(self) -> None:
        files = []
        for k in range(3):
            f = self.tmp / f"s{k}.v"
            f.write_text(self.starter.read_text(encoding="utf-8"), encoding="utf-8")
            files.append(f)
        self.assertEqual(len(self.controllers(files)), 3)

    def test_starter_compiles_for_every_level(self) -> None:
        data = UserData(self.tmp)
        for n in range(13):
            files = data.ensure_level_files(n, INTERS[n])
            for c in self.controllers(files):
                c.close()

    def run_level1(self, files: list[Path], ticks: int = 20000) -> tuple[Level, Trace]:
        level = make_level(1)
        trace: Trace = []
        ctls = [Tracer(c, lambda: level.ticks, trace) for c in self.controllers(files)]
        level.start(ctls)
        for _ in range(ticks):
            if level.tick():
                break
        return level, trace

    def test_level1_starter_equals_scripted(self) -> None:
        data = UserData(self.tmp)
        files = data.ensure_level_files(1, INTERS[1])
        real, trace = self.run_level1(files)
        ref = make_level(1)
        ref_trace: list[tuple[int, int, int, int, int, int, int]] = []

        def wrap(light: int, general: int) -> tuple[int, int, int, int]:
            out = safe_controller(light, general)
            ref_trace.append((ref.ticks, light, general, *out))
            return out

        ref.start(scripted(ref, wrap))
        while not ref.tick():
            pass
        self.assertEqual(real.result().crashed, 0)
        self.assertEqual(real.result(), ref.result())
        self.assertEqual(sorted(trace), sorted(ref_trace))

    def test_constant_outputs_never_finish(self) -> None:
        files = []
        for k in range(2):
            f = self.tmp / f"c{k}.v"
            f.write_text(
                (ASSETS / "examples/constant_outputs.v").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            files.append(f)
        level, _ = self.run_level1(files, 3000)
        self.assertIs(level.phase, Phase.RUN)
        # constant (Left_only, Go, Stop, Right_only) lets some cars through but never finishes
        ref = make_level(1)
        ref.start(scripted(ref, lambda _light, _general: (2, 4, 0, 3)))
        for _ in range(3000):
            if ref.tick():
                break
        self.assertIs(ref.phase, Phase.RUN)
        self.assertEqual(level.result(), ref.result())

    def test_templates_compile(self) -> None:
        files = sorted((ASSETS / "templates").glob("*.v"))
        self.assertEqual(len(files), 2)
        self.assertEqual(len(self.controllers(files)), 2)

    def test_ticks_independent_of_frame_rate(self) -> None:
        data = UserData(self.tmp)
        files = data.ensure_level_files(1, INTERS[1])
        rng = random.Random(7)
        schedules: list[Callable[[], float]] = [
            lambda: 1 / 60,
            lambda: 1 / 30,
            lambda: 1 / 144,
            lambda: rng.uniform(0.001, 0.2),
        ]
        runs = [self.traced(files, s) for s in schedules]
        for trace, result in runs[1:]:
            self.assertEqual(trace, runs[0][0])
            self.assertEqual(result, runs[0][1])

    def traced(self, files: list[Path], dts: Callable[[], float]) -> tuple[Trace, LevelResult]:
        level = make_level(1)
        trace: Trace = []
        level.start([Tracer(c, lambda: level.ticks, trace) for c in self.controllers(files)])
        clock = TickClock(max_backlog=10**6)
        frames = 0
        while level.phase is not Phase.DONE and frames < 2_000_000:
            frames += 1
            for _ in range(clock.advance(dts(), 1)):
                if level.tick():
                    break
        return trace, level.result()

    def test_original_header_error(self) -> None:
        f = self.tmp / "orig.v"
        f.write_text(
            "module light1 (clk, rst, outN, outS, outE, outW, sensor_light, general_sensors);\n"
            "input clk, rst;\ninput [7:0] sensor_light;\ninput [29:0] general_sensors;\n"
            "output [2:0] outN, outS, outE, outW;\noutput [29:0] debug_port;\n"
            "assign outN = 0;\nassign outS = 0;\nassign outE = 0;\nassign outW = 0;\n"
            "assign debug_port = 0;\nendmodule\n",
            encoding="utf-8",
        )
        result = build_controllers([f])
        self.assertFalse(result.ok)
        self.assertIn(
            "'debug_port' is declared as a port but is not in the port list",
            result.errors[0].message,
        )

    def test_syntax_error_line(self) -> None:
        f = self.tmp / "bad.v"
        f.write_text(
            "module light1 (clk, rst);\ninput clk, rst;\n\n\nassign = ;\nendmodule\n",
            encoding="utf-8",
        )
        result = build_controllers([f])
        self.assertFalse(result.ok)
        self.assertEqual(result.errors[0].line, 5)


if __name__ == "__main__":
    unittest.main()
