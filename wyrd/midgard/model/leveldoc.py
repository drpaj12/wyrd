"""The level document of the level editor (spec 8.2): groups of 2 by 2 cells, Qt-free.

A port of the data side of LevelEditor's `MapGrid` and `MapEditor`. The map is a grid of groups,
each a 2 by 2 block of game cells; `groups[gx][gy]` has `gy == 0` at the bottom, as in the Java.
Group type names are the Java string values (what the image files and the XML use).
"""

from __future__ import annotations

from wyrd.midgard.model.grid import GridType
from wyrd.midgard.model.levelxml import CarSpec, IntersectionSpec, LevelData

# The order of GridTypeSelector.types. The three-way names are the string values of the Java
# constants (THREE_WAY_NSE holds "THREE_WAY_NSW" and so on), which the images and XML use.
GROUP_TYPES: tuple[str, ...] = (
    "STRAIGHT_NS",
    "STRAIGHT_NS_2",
    "STRAIGHT_NS_3",
    "STRAIGHT_EW",
    "STRAIGHT_EW_2",
    "CORNER_NW",
    "CORNER_SW",
    "CORNER_NE",
    "CORNER_SE",
    "FOUR_WAY",
    "FOUR_WAY_2",
    "THREE_WAY_NSW",
    "THREE_WAY_NEW",
    "THREE_WAY_NSE",
    "THREE_WAY_SEW",
    "NON_ROAD",
    "NON_ROAD_2",
)
# MapGrid.rotateTypes: the other types return themselves.
ROTATE_CYCLES: tuple[tuple[str, ...], ...] = (
    ("NON_ROAD", "NON_ROAD_2"),
    ("STRAIGHT_NS", "STRAIGHT_NS_2", "STRAIGHT_NS_3"),
    ("STRAIGHT_EW", "STRAIGHT_EW_2"),
    ("FOUR_WAY", "FOUR_WAY_2"),
)

# Cell types (top-left, top-right, bottom-left, bottom-right) of a group (getSmallerGridTypes).
_CELLS: dict[str, tuple[str, str, str, str]] = {
    "STRAIGHT_NS": (
        "STRAIGHT_ROAD_S2S",
        "STRAIGHT_ROAD_N2N",
        "STRAIGHT_ROAD_S2S",
        "STRAIGHT_ROAD_N2N",
    ),
    "STRAIGHT_EW": (
        "STRAIGHT_ROAD_W2W",
        "STRAIGHT_ROAD_W2W",
        "STRAIGHT_ROAD_E2E",
        "STRAIGHT_ROAD_E2E",
    ),
    "CORNER_NW": ("CORNER_ROAD_S2W", "STRAIGHT_ROAD_N2N", "STRAIGHT_ROAD_E2E", "CORNER_ROAD_E2N"),
    "CORNER_SW": ("STRAIGHT_ROAD_W2W", "CORNER_ROAD_N2W", "CORNER_ROAD_E2S", "STRAIGHT_ROAD_N2N"),
    "CORNER_NE": ("STRAIGHT_ROAD_S2S", "CORNER_ROAD_W2N", "CORNER_ROAD_S2E", "STRAIGHT_ROAD_E2E"),
    "CORNER_SE": ("CORNER_ROAD_W2S", "STRAIGHT_ROAD_W2W", "STRAIGHT_ROAD_S2S", "CORNER_ROAD_N2E"),
    "FOUR_WAY": ("INTER_TURN_S2WS", "INTER_TURN_W2NW", "INTER_TURN_E2SE", "INTER_TURN_N2EN"),
    "THREE_WAY_NSW": ("STRAIGHT_ROAD_S2S", "INTER_TURN_W2NW", "INTER_TURN_E2SE", "INTER_TURN_N2EN"),
    "THREE_WAY_NEW": ("INTER_TURN_S2WS", "STRAIGHT_ROAD_W2W", "INTER_TURN_E2SE", "INTER_TURN_N2EN"),
    "THREE_WAY_NSE": ("INTER_TURN_S2WS", "INTER_TURN_W2NW", "INTER_TURN_E2SE", "STRAIGHT_ROAD_N2N"),
    "THREE_WAY_SEW": ("INTER_TURN_S2WS", "INTER_TURN_W2NW", "STRAIGHT_ROAD_E2E", "INTER_TURN_N2EN"),
    "NON_ROAD": ("NON_ROAD", "NON_ROAD", "NON_ROAD", "NON_ROAD"),
}
_ALIASES = {
    "STRAIGHT_NS_2": "STRAIGHT_NS",
    "STRAIGHT_NS_3": "STRAIGHT_NS",
    "STRAIGHT_EW_2": "STRAIGHT_EW",
    "FOUR_WAY_2": "FOUR_WAY",
    "NON_ROAD_2": "NON_ROAD",
}
_BY_CELLS = {cells: name for name, cells in _CELLS.items()}
MIN_SIZE = 4


def base_type(name: str) -> str:
    """`FOUR_WAY_2` -> `FOUR_WAY`: the type without its texture variant."""
    return _ALIASES.get(name, name)


def _is_intersection(name: str) -> bool:
    return name.startswith(("THREE_WAY", "FOUR_WAY"))


def _blocks_edge(name: str, side: str) -> bool:
    """MapEditor.check*StartsEnds: an intersection that touches this edge makes the level invalid.

    Every four-way does; a three-way does when its name contains the edge letter (the regexes
    `THREE_WAY_(?![^S]{3})` and friends), because the Java names are the opposite of the game's.
    """
    if name.startswith("FOUR_WAY"):
        return True
    return name.startswith("THREE_WAY_") and side in name[len("THREE_WAY_") :]


def _opens_north(name: str) -> bool:
    return name.startswith("STRAIGHT_NS") or name.startswith("CORNER_N")


def _opens_south(name: str) -> bool:
    return name.startswith("STRAIGHT_NS") or name.startswith("CORNER_S")


def _opens_east(name: str) -> bool:
    return name.startswith("STRAIGHT_EW") or name in ("CORNER_NE", "CORNER_SE")


def _opens_west(name: str) -> bool:
    return name.startswith("STRAIGHT_EW") or name in ("CORNER_NW", "CORNER_SW")


Point = tuple[int, int]


class LevelDoc:
    def __init__(self, number: int, size_x: int, size_y: int) -> None:
        for size in (size_x, size_y):
            if size < MIN_SIZE or size % 2:
                raise ValueError(f"map size must be even and at least {MIN_SIZE}, got {size}")
        self.number = number
        self.size_x = size_x
        self.size_y = size_y
        self.read_from_xml = False
        self.groups: list[list[str]] = [["NON_ROAD"] * (size_y // 2) for _ in range(size_x // 2)]
        self.cars: list[CarSpec] = []
        self.starts: list[Point] = []
        self.ends: list[Point] = []

    # editing

    def _check_group(self, gx: int, gy: int) -> None:
        if not (0 <= gx < self.size_x // 2 and 0 <= gy < self.size_y // 2):
            raise ValueError(f"group ({gx}, {gy}) is outside the map")

    def set_type(self, gx: int, gy: int, type: str) -> None:
        self._check_group(gx, gy)
        if type not in GROUP_TYPES:
            raise ValueError(f"unknown group type {type!r}")
        self.groups[gx][gy] = type

    def rotate_type(self, gx: int, gy: int) -> None:
        self._check_group(gx, gy)
        current = self.groups[gx][gy]
        for cycle in ROTATE_CYCLES:
            if current in cycle:
                self.groups[gx][gy] = cycle[(cycle.index(current) + 1) % len(cycle)]
                return

    def clear_map(self) -> None:
        self.groups = [["NON_ROAD"] * (self.size_y // 2) for _ in range(self.size_x // 2)]
        self.starts, self.ends, self.cars = [], [], []

    # starts and ends

    def _edge_pairs(self) -> tuple[list[Point], list[Point]] | None:
        """Start and end cells on the border in the Java order (north, east, south, west)."""
        gw, gh = self.size_x // 2, self.size_y // 2
        top, right = self.size_y + 1, self.size_x + 1
        starts: list[Point] = []
        ends: list[Point] = []
        edges = (
            ("S", [self.groups[i][gh - 1] for i in range(gw)]),
            ("W", [self.groups[gw - 1][i] for i in range(gh - 1, -1, -1)]),
            ("N", [self.groups[i][0] for i in range(gw - 1, -1, -1)]),
            ("E", [self.groups[0][i] for i in range(gh)]),
        )
        # The letter tested in a three-way name is the one the Java regex of that edge uses.
        for side, names in edges:
            if any(_blocks_edge(n, side) for n in names):
                return None
        for i in range(gw):
            if _opens_north(self.groups[i][gh - 1]):
                starts.append((2 * i + 1, top))
                ends.append((2 * i + 2, top))
        for i in range(gh - 1, -1, -1):
            if _opens_east(self.groups[gw - 1][i]):
                starts.append((right, 2 * i + 2))
                ends.append((right, 2 * i + 1))
        for i in range(gw - 1, -1, -1):
            if _opens_south(self.groups[i][0]):
                starts.append((2 * i + 2, 0))
                ends.append((2 * i + 1, 0))
        for i in range(gh):
            if _opens_west(self.groups[0][i]):
                starts.append((0, 2 * i + 1))
                ends.append((0, 2 * i + 2))
        return starts, ends

    def populate_starts_ends(self) -> bool:
        """Recompute `starts` and `ends`; False when an intersection touches the edge.

        On a level created from scratch, a change of the starts empties the car list (the Java
        did this when `Edit Cars` was pressed). A level read from XML keeps its cars.
        """
        previous = list(self.starts)
        pairs = self._edge_pairs()
        if pairs is None:
            self.starts, self.ends = [], []
            return False
        self.starts, self.ends = pairs
        if not self.read_from_xml and previous != self.starts:
            self.cars = []
        return True

    # cars

    def add_car(self, start: Point, end: Point, delay: int) -> None:
        if delay < 1:
            raise ValueError("delay must be at least 1")
        if start not in self.starts:
            raise ValueError(f"{start} is not a start point")
        if end not in self.ends:
            raise ValueError(f"{end} is not an end point")
        self.cars.append(CarSpec(start, end, delay))

    def remove_car(self, index: int) -> None:
        del self.cars[index]

    # conversion

    def _edge_cell_type(self, pos: Point, is_start: bool) -> GridType:
        x, y = pos
        if x == 0:
            return GridType.START_WEDGE2E if is_start else GridType.END_W2WEDGE
        if y == 0:
            return GridType.START_SEDGE2N if is_start else GridType.END_S2SEDGE
        if x == self.size_x + 1:
            return GridType.START_EEDGE2W if is_start else GridType.END_E2EEDGE
        return GridType.START_NEDGE2S if is_start else GridType.END_N2NEDGE

    def to_level_data(self) -> LevelData:
        pairs = self._edge_pairs()
        if pairs is None:
            raise ValueError("Can't have intersections on the edge! Level is not saved.")
        starts, ends = pairs
        tiles: dict[Point, GridType] = {}
        for start, end in zip(starts, ends, strict=True):
            tiles[start] = self._edge_cell_type(start, True)
            tiles[end] = self._edge_cell_type(end, False)
        inters: list[IntersectionSpec] = []
        for gx in range(self.size_x // 2):
            for gy in range(self.size_y // 2):
                self._add_group(tiles, inters, gx, gy)
        inters.sort(key=lambda i: (-i.y, i.x))
        return LevelData(
            self.number, self.size_x + 2, self.size_y + 2, tiles, tuple(inters), tuple(self.cars)
        )

    def _add_group(
        self, tiles: dict[Point, GridType], inters: list[IntersectionSpec], gx: int, gy: int
    ) -> None:
        name = self.groups[gx][gy]
        cells = _CELLS[base_type(name)]
        x0, y0 = 2 * gx + 1, 2 * gy + 1
        spots = ((x0, y0 + 1), (x0 + 1, y0 + 1), (x0, y0), (x0 + 1, y0))
        for spot, cell in zip(spots, cells, strict=True):
            tiles[spot] = GridType[cell]
        if _is_intersection(name):
            inters.append(IntersectionSpec(base_type(name), spots[0][0], spots[0][1]))

    @classmethod
    def from_level_data(cls, data: LevelData) -> LevelDoc:
        doc = cls(data.number, data.size_x - 2, data.size_y - 2)
        doc.read_from_xml = True
        for gx in range(doc.size_x // 2):
            for gy in range(doc.size_y // 2):
                doc.groups[gx][gy] = _group_at(data, gx, gy)
        doc.cars = list(data.cars)
        doc.starts = [p for p, t in data.tiles.items() if t.name.startswith("START_")]
        doc.ends = [p for p, t in data.tiles.items() if t.name.startswith("END_")]
        return doc


def _group_at(data: LevelData, gx: int, gy: int) -> str:
    x0, y0 = 2 * gx + 1, 2 * gy + 1
    spots = ((x0, y0 + 1), (x0 + 1, y0 + 1), (x0, y0), (x0 + 1, y0))
    tl, tr, bl, br = (data.tiles.get(spot, GridType.NON_ROAD).name for spot in spots)
    group = _BY_CELLS.get((tl, tr, bl, br))
    if group is None:
        raise ValueError(
            f"cell {spots[0]} starts a 2 by 2 block ({tl}, {tr}, {bl}, {br}) "
            "that fits no group type"
        )
    return group
