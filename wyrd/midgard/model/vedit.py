"""Verilog editor logic, Qt-free (spec 8.1): port of VerilogEditor's button behaviour."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from wyrd.midgard.model import ASSETS
from wyrd.midgard.model.controllers import (
    Backend,
    ControllerError,
    LightController,
    MidgardController,
    SimError,
    build_controllers,
)

SAVE_OK = "Saving complete."
NOT_COMPILED = (
    "The Verilog code has not been successfully compiled yet.  "
    "Please click the check mark above and/or fix Verilog errors."
)
BAD_VECTOR = (
    "Simulation cycle not sucessful\n"
    "Missing Simulation vector or it vector isn't 10 characters (Hexidecimal digits) long."
)
LIGHT_WIDTH = 8
GENERAL_WIDTH = 30
_TEMPLATES = ("combinational", "sequential")
_CODE_NAMES = {0: "stop", 1: "forward", 2: "left", 3: "right", 4: "go"}
_DIRECTIONS = ("n", "s", "e", "w")


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    messages: tuple[str, ...]


@dataclass(frozen=True)
class SimResult:
    clock_cycle: int
    light: str
    general: str
    out: tuple[int, int, int, int]
    debug: int
    text: str


def load_template(name: str) -> str:
    if name not in _TEMPLATES:
        raise ValueError(f"unknown template: {name}")
    return (ASSETS / "templates" / f"{name}.v").read_text(encoding="utf-8")


def animation_image_names(out: tuple[int, int, int, int]) -> tuple[str, str, str, str]:
    names = [
        f"{_CODE_NAMES.get(code, 'stop')}_{d}" for code, d in zip(out, _DIRECTIONS, strict=True)
    ]
    return (names[0], names[1], names[2], names[3])


def _is_bits(text: str, width: int) -> bool:
    return len(text) == width and all(c in "01" for c in text)


def _error_message(line: int | None, col: int | None, message: str) -> str:
    if line is None:
        return f"Error: {message}"
    where = f"{line}:{col}" if col is not None else f"{line}"
    return f"Error at line {where}: {message}"


class EditorSession:
    def __init__(self, path: Path, backend: Backend | None = None) -> None:
        self.path = path
        self.backend = backend
        self.dirty = False
        self.cycle = 0
        self._controller: LightController | None = None
        self.text = self._read()

    def _read(self) -> str:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError:
            return load_template("combinational")
        return raw[:-1] if raw.endswith("\n") else raw

    def set_text(self, text: str) -> None:
        if text != self.text:
            self.dirty = True
        self.text = text

    def save(self) -> str:
        try:
            self.path.write_text(self.text + "\n", encoding="utf-8")
        except OSError as exc:
            return str(exc)
        self.dirty = False
        return SAVE_OK

    def _drop_controller(self) -> None:
        if self._controller is not None:
            self._controller.close()
            self._controller = None

    def _build(self, target: Path) -> tuple[VerifyResult, LightController | None]:
        messages = [f"Compiling {self.path}"]
        try:
            result = build_controllers([target], self.backend)
        except SimError as exc:
            return VerifyResult(False, (*messages, f"Error: {exc}")), None
        if result.errors:
            errs = [_error_message(e.line, e.col, e.message) for e in result.errors]
            return VerifyResult(False, (*messages, *errs)), None
        controller = result.controllers[0]
        if controller is None:
            return VerifyResult(False, (*messages, "Error: no controller")), None
        try:
            controller.start()
        except ControllerError as exc:
            controller.close()
            return VerifyResult(False, (*messages, f"Error: {exc}")), None
        return VerifyResult(True, (*messages, "Compile successful")), controller

    def _compile(self) -> VerifyResult:
        self.save()
        self._drop_controller()
        self.cycle = 0
        result, self._controller = self._build(self.path)
        return result

    def verify(self) -> VerifyResult:
        return self._compile()

    def check_unsaved(self) -> VerifyResult:
        """Compile the current text from a scratch copy; the file and the session state stay."""
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp) / self.path.name
            scratch.write_text(self.text + "\n", encoding="utf-8")
            result, controller = self._build(scratch)
            if controller is not None:
                controller.close()
        return result

    def reset(self) -> str:
        return "\n".join(self._compile().messages)

    def simulate(self, light: str, general: str) -> tuple[SimResult | None, str]:
        if not (_is_bits(light, LIGHT_WIDTH) and _is_bits(general, GENERAL_WIDTH)):
            return None, BAD_VECTOR
        controller = self._controller
        if controller is None:
            return None, NOT_COMPILED
        try:
            out = controller.step(int(light, 2), int(general, 2))
        except ControllerError as exc:
            return None, str(exc)
        self.cycle += 1
        debug = controller.read_debug() if isinstance(controller, MidgardController) else 0
        text = (
            f"Simulation Cycle\nClock Cycle:{self.cycle} Sensors Light: {light} "
            f"General Sensors: {general}\nOutN Val = {out[0]}\nOutS Val = {out[1]}\n"
            f"OutE Val = {out[2]}\nOutW Val = {out[3]}\nDebugVector = {debug:030b}"
        )
        return SimResult(self.cycle, light, general, out, debug, text), text

    def should_prompt_on_exit(self) -> bool:
        return self.dirty

    def close(self) -> None:
        self._drop_controller()
