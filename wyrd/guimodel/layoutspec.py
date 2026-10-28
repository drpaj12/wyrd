"""Window layout presets and zoom limits as plain data (no Qt). Spec:
docs/specs/2026-10-28-view-layout.md."""

from __future__ import annotations

from dataclasses import dataclass

LAYOUT_VERSION = 2
ZOOM_MIN = -4
ZOOM_MAX = 20

PROJECT = "Project"
SOURCE = "Source"
REPORT = "Report"
EDITOR = "wyrd.toml"
SIMULATE = "Simulate"
MESSAGES = "Messages"
FLOW = "Flow"
TIMING = "Timing"
SCHEMATIC = "Schematic"
ATLAS = "Atlas"
MIMIR = "Mímir"
PATHS = "Paths"

#: Every panel, in tab order.
PANELS = (
    PROJECT, SOURCE, REPORT, EDITOR, SIMULATE, MESSAGES, FLOW, TIMING, SCHEMATIC, ATLAS, MIMIR,
    PATHS,
)  # fmt: skip
AREAS = ("left", "right", "bottom")


@dataclass(frozen=True)
class Group:
    """Tabbed docks in one area; ``share`` is the fraction of the window along the area's axis."""

    area: str
    docks: tuple[str, ...]
    current: str
    share: float


@dataclass(frozen=True)
class Preset:
    name: str
    groups: tuple[Group, ...]

    def shown(self) -> frozenset[str]:
        return frozenset(d for g in self.groups for d in g.docks)

    def parked(self) -> tuple[str, ...]:
        shown = self.shown()
        return tuple(p for p in PANELS if p not in shown)


_BOTTOM = (MESSAGES, FLOW, TIMING, SCHEMATIC, ATLAS, MIMIR, PATHS)

PRESETS: tuple[Preset, ...] = (
    Preset(
        "Project",
        (
            Group("left", (PROJECT,), PROJECT, 0.2),
            Group("right", (SOURCE, REPORT, EDITOR, SIMULATE), SOURCE, 0.8),
            Group("bottom", _BOTTOM, MESSAGES, 0.3),
        ),
    ),
    Preset(
        "Timing + source",
        (
            Group("left", (SOURCE,), SOURCE, 0.6),
            Group("right", (TIMING, PATHS), TIMING, 0.4),
            Group("bottom", (MESSAGES,), MESSAGES, 0.15),
        ),
    ),
    Preset(
        "Mímir explorer",
        (
            Group("left", (MIMIR,), MIMIR, 0.65),
            Group("right", (SOURCE, PATHS), SOURCE, 0.35),
        ),
    ),
    Preset("Everything tabbed", (Group("right", PANELS, SOURCE, 1.0),)),
)

DEFAULT_PRESET = PRESETS[0].name


def preset_named(name: str) -> Preset:
    for p in PRESETS:
        if p.name == name:
            return p
    raise KeyError(name)


def clamp_zoom(value: int) -> int:
    return max(ZOOM_MIN, min(ZOOM_MAX, value))


def parse_zoom(raw: object) -> int:
    """A stored zoom offset; anything unreadable is 0."""
    try:
        return clamp_zoom(int(str(raw)))
    except ValueError:
        return 0


def state_usable(version: object) -> bool:
    """True when a stored layout version equals the current one."""
    try:
        return int(str(version)) == LAYOUT_VERSION
    except ValueError:
        return False
