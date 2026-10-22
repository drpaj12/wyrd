"""Level XML reader (port of LevelXMLParser). Parsing only; linking is in townmap.py."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from wyrd.midgard.model.grid import END_TYPES, START_TYPES, GridType

INTERSECTION_KINDS = (
    "FOUR_WAY",
    "THREE_WAY_NSE",
    "THREE_WAY_SEW",
    "THREE_WAY_NSW",
    "THREE_WAY_NEW",
)
LEVEL_NUMBERS = tuple(range(13))
_LEVELS_DIR = Path(__file__).resolve().parent.parent / "assets" / "levels"


class LevelFormatError(Exception):
    """The level file is malformed."""


@dataclass(frozen=True)
class IntersectionSpec:
    kind: str
    x: int
    y: int


@dataclass(frozen=True)
class CarSpec:
    start: tuple[int, int]
    end: tuple[int, int]
    delay: int


@dataclass(frozen=True)
class LevelData:
    number: int
    size_x: int
    size_y: int
    tiles: dict[tuple[int, int], GridType]
    intersections: tuple[IntersectionSpec, ...]
    cars: tuple[CarSpec, ...]


def level_path(number: int) -> Path:
    return _LEVELS_DIR / f"Lv{number}" / f"lv{number:02d}.xml"


def _int_attr(elem: ET.Element, name: str) -> int:
    raw = elem.get(name)
    if raw is None:
        raise LevelFormatError(f"<{elem.tag}> lacks {name}")
    try:
        return int(raw)
    except ValueError:
        raise LevelFormatError(f"<{elem.tag}> {name}={raw!r} is not a number") from None


def _grid_type(text: str | None) -> GridType:
    try:
        return GridType[(text or "").strip()]
    except KeyError:
        return GridType.NON_ROAD


def _parse_grids(
    map_elem: ET.Element,
) -> tuple[dict[tuple[int, int], GridType], list[IntersectionSpec]]:
    tiles: dict[tuple[int, int], GridType] = {}
    inters: list[IntersectionSpec] = []
    for g in map_elem.findall("grid"):
        pos = (_int_attr(g, "x"), _int_attr(g, "y"))
        tiles[pos] = _grid_type(g.findtext("type"))
        kind = g.findtext("intersection")
        if kind is not None:
            kind = kind.strip()
            if kind not in INTERSECTION_KINDS:
                raise LevelFormatError(f"unknown intersection kind {kind!r} at {pos}")
            inters.append(IntersectionSpec(kind, pos[0], pos[1]))
    inters.sort(key=lambda i: (-i.y, i.x))
    return tiles, inters


def _point(elem: ET.Element | None, what: str) -> tuple[int, int]:
    if elem is None:
        raise LevelFormatError(f"car lacks <{what}>")
    return _int_attr(elem, "x"), _int_attr(elem, "y")


def _parse_car(c: ET.Element, size_x: int, size_y: int, index: int) -> CarSpec:
    start = _point(c.find("start"), "start")
    end = _point(c.find("end"), "end")
    for what, (x, y) in (("start", start), ("end", end)):
        if not (0 <= x < size_x and 0 <= y < size_y):
            raise LevelFormatError(f"car {index} {what} {(x, y)} is outside the map")
    try:
        delay = int((c.findtext("delay") or "").strip())
    except ValueError:
        raise LevelFormatError(f"car {index} delay is not a number") from None
    if delay < 1:
        raise LevelFormatError(f"car {index} delay must be at least 1 (got {delay})")
    return CarSpec(start, end, delay)


def _check_car_tiles(index: int, spec: CarSpec, tiles: dict[tuple[int, int], GridType]) -> None:
    start_type = tiles.get(spec.start, GridType.NON_ROAD)
    if start_type not in START_TYPES:
        raise LevelFormatError(
            f"car {index} starts at {spec.start}, which is not a start tile ({start_type.name})"
        )
    end_type = tiles.get(spec.end, GridType.NON_ROAD)
    if end_type not in END_TYPES:
        raise LevelFormatError(
            f"car {index} ends at {spec.end}, which is not an end tile ({end_type.name})"
        )


def parse_level_xml(text: str | bytes) -> LevelData:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise LevelFormatError(f"malformed level XML: {exc}") from exc
    map_elem = root.find("map")
    if map_elem is None:
        raise LevelFormatError("level has no <map>")
    size_x = _int_attr(map_elem, "size_x")
    size_y = _int_attr(map_elem, "size_y")
    tiles, inters = _parse_grids(map_elem)
    cars_elem = root.find("cars")
    car_elems = cars_elem.findall("car") if cars_elem is not None else []
    cars = tuple(_parse_car(c, size_x, size_y, i) for i, c in enumerate(car_elems))
    for index, spec in enumerate(cars):
        _check_car_tiles(index, spec, tiles)
    try:
        number = int(root.get("lv", "0"))
    except ValueError:
        raise LevelFormatError("level lv is not a number") from None
    return LevelData(number, size_x, size_y, tiles, tuple(inters), cars)


def parse_level_file(path: Path) -> LevelData:
    try:
        return parse_level_xml(path.read_bytes())
    except OSError as exc:
        raise LevelFormatError(f"cannot read {path}: {exc}") from exc


_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8" standalone="no"?>'


def _grid_xml(pos: tuple[int, int], tile: GridType, kind: str | None) -> str:
    inner = f"<intersection>{kind}</intersection>" if kind is not None else ""
    return f'<grid x="{pos[0]}" y="{pos[1]}">{inner}<type>{tile.name}</type></grid>'


def _car_xml(car: CarSpec) -> str:
    return (
        f'<car><start x="{car.start[0]}" y="{car.start[1]}"/>'
        f'<end x="{car.end[0]}" y="{car.end[1]}"/><delay>{car.delay}</delay></car>'
    )


def write_level_xml(data: LevelData) -> str:
    """The inverse of `parse_level_file`, in the layout the original level editor wrote.

    That is the Java `Transformer` output: one line, no whitespace between elements, no final
    newline. Cells keep the order of `data.tiles`; an `<intersection>` element precedes the
    `<type>` of the cell that holds it.
    """
    kinds = {(i.x, i.y): i.kind for i in data.intersections}
    grids = "".join(_grid_xml(pos, tile, kinds.get(pos)) for pos, tile in data.tiles.items())
    cars = "".join(_car_xml(c) for c in data.cars)
    cars_xml = f"<cars>{cars}</cars>" if cars else "<cars/>"
    return (
        f'{_XML_DECLARATION}<level lv="{data.number}">'
        f'<map size_x="{data.size_x}" size_y="{data.size_y}">{grids}</map>{cars_xml}</level>'
    )
