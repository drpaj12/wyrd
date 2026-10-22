# W4: Midgard III (Verilog Town) in pygame-ce (design)

Status: decisions 1 to 8 approved by Peter, 2026-10-21 (the names Midgard III, Bifrost III and Yggdrasil too); the rest is
the author's resolution of everything those decisions left open (Section 17 lists what Peter may still change).
Amended 2026-10-21 (branch `docs/w4-faithful`, Peter: "a close replication of the original game"): the fidelity principle
(Section 2), game time (5.9), the starter files corrected (7.3), the Verilog editor window and the level editor
(8.1, 8.2), zoom and pan (9.3), the clock strip (9.4), the font (11), and the questions (17).
Plan: `docs/plans/2026-10-21-w4-verilog-town-plan.md`. Designed together with W3
(`docs/specs/2026-10-21-w3-sim-design.md`): the game's sensors and lights are the session's inputs and outputs.
Midgard III belongs to the Yggdrasil software suite (Odin III, Wyrd III, Loki III, Midgard III).

## 1. Goal

Port the game verilogTown (Jamieson, Grace, Mizuno, Zhang, ASEE 2017; MIT) to Python and pygame-ce as
**Midgard III (Verilog Town)**: a city of cars and intersections where the player writes a Verilog module per
traffic light and the lights are driven by Odin III's simulator through Bifrost III (`wyrd.bifrost`, W3). All 13
levels (Lv0 the tutorial, Lv1 to Lv12), cars, lights, sensors, scoring, high scores, level select, the Verilog
editor window and the level editor. The mechanics are
ported from the Java source method by method (Section 5), so a level plays as it did in the original.

Not in W4: Android, HTML/GWT, the telemetry server, the Java Verilog interpreter (Section 14).

## 2. Decisions

**Governing principle (Peter, 2026-10-21).** Midgard III is a close replication of the original verilogTown; where a
port choice differs from the original's behaviour, look and feel, the original wins. Only these differ, each for a
stated reason:

1. No telemetry and no online leaderboard (the server is gone; the original `verilogTownServer` only received result
   and usage records, default `127.0.0.1:32150`). The local high-score files stay.
2. Odin III through Bifrost III replaces the Java Verilog interpreter (`VerilogSimulator`); the semantics the game
   observes are kept (5.9, 7.2). The starter files and templates carry the one-line `debug_port` header fix, because
   the originals do not compile under Odin III (7.3).
3. The font: Chiller (Microsoft, commercial) is replaced by an OFL look-alike (Section 11).
4. Android and HTML/GWT launchers are out of scope.
5. Game time (Peter's one deliberate improvement, 2026-10-21; the original's timing was confusing and frame-rate
   dependent): one game tick is one rising clock edge of the player's module; the world advances in whole ticks from a
   fixed-step accumulator; speed controls change wall time only; scores are counted in ticks (5.9).
6. The window: resizable with the aspect ratio kept (the original stretched the picture over a fixed 600 by 600
   window), plus the clock strip of 5.9 and 9.4 under the level.
7. Visual-only items deferred to a follow-up (turn arcs, the sliding help and finish overlays; Question 9), and
   small defect fixes listed in Section 13.
8. The per-user data directory, key presses handled as events (the Java polled keys every frame), and an external
   editor as an extra beside the built-in editor.

Every default below was checked against the Java and either matches it or is one of the items above (Section 13).

Approved by Peter (2026-10-21), encoded verbatim:

| # | Decision | Choice |
|---|---|---|
| 1 | Name | The game is **Midgard III** (also called Verilog Town). Command `midgard`, extra `wyrd[midgard]`, package `wyrd.midgard`, GUI menu "Midgard III (Verilog Town)", window title "Midgard III". The original verilogTown is credited everywhere (Jamieson, Grace, Mizuno, Zhang, ASEE 2017, MIT) |
| 2 | Packaging | Extra `wyrd[midgard]` (pygame-ce), command `midgard`, and a menu entry in the W2 GUI |
| 3 | Content | Cars, lights, sensors, scoring, high scores, level select, no Android/HTML. Levels: all 13 (Lv0 tutorial and Lv1 to Lv12; see Question 6). **Changed by Peter, 2026-10-21: the level editor is in scope** (decision 20; the earlier choice was "no level editor") |
| 4 | Clocking | One Bifrost III step per game tick |
| 5 | Player Verilog | Compiled at level start; errors shown in the game with `file:line` |
| 6 | Editing | The original's Verilog editor window, ported with PySide6 (decision 19, Section 8.1); the external editor, a file watch and reload remain as an extra |
| 7 | Assets | The original images and level files are reused, copied into `wyrd/midgard/assets` with the MIT notice; sizes are listed in Section 11 |
| 8 | Tests | Headless with the SDL dummy video driver: every level loads, and a scripted controller drives a level |

Decided here (author), each with its reason:

| # | Decision | Reason |
|---|---|---|
| 9 | Engine and drawing are separate: `wyrd/midgard/model/` imports neither pygame nor Qt nor odin3; `wyrd/midgard/ui/` is the only pygame user (plus `app.py`) | Tests of the mechanics need no display |
| 10 | Game time | Section 5.9: 1 game tick = 1 rising clock edge of the player's module = 1 Bifrost III step. Base speed 60 ticks per second (what the Java did: one tick per rendered frame, vsync on, about 60 frames per second), fixed-step accumulator, speeds 1x, 2x, 4x, pause, single step; scores in ticks, shown also as seconds at 60 ticks per second. Peter's deliberate improvement on the original's frame-rate dependent timing | The Java ran one tick per rendered frame (its `Frame_Time_25 = 1 / 25` is integer division, 0); the frame rate was the libGDX default (Section 5.9). The documentation pages and Java comments say 25 ticks per second; Question 8 |
| 11 | Per-user files (the player's Verilog, `sensorFile.txt`, `high_score.txt`) live in a user data directory (Section 10), copied from the package on first use; package assets are read-only | A wheel install cannot be written to |
| 12 | The shipped starter Verilog is the original stub with one fix: `debug_port` is added to the header port list | Odin III rejects the original (Section 7.3) |
| 13 | No telemetry: the original `LocalServer`, `userID.txt` and `server.conf` network code is not ported; the game opens no socket | The original sent results and usage to a remote host |
| 14 | `CHILLER.TTF` (Microsoft, commercial; it is in the zip but not under the MIT grant) is not copied. The credits text (the only text the Java drew with Chiller) uses Creepster (SIL OFL 1.1), vendored with its licence; the digit images (`chiller_num_*.png`) are artwork and are copied | Licence. Section 11 |
| 15 | Zoom and pan are ported (wheel, `-` and `=`, `Q` and `A`, cursor keys, mouse drag; Section 9.3). The window also scales the picture to fit and keeps the aspect ratio (the original stretched it over 600 by 600) | The original wins; the letterbox is the stated deviation 6 |
| 16 | Turn arcs are not ported in W4 (the Java draws cars along arcs through corners with `init_animate_turn`; its game logic uses straight-line positions, which are ported exactly) | Visual only, about 400 lines of Java geometry. Stated deviation 7 and Question 9 (recommend a follow-up PR, W4.1) |
| 17 | The finish overlay and the score screen are one screen | The original drew the same numbers twice |
| 18 | The Tutorial (level 0, a button in the original menu) is included | Same engine, 1 intersection |
| 19 | The Verilog editor is a PySide6 window launched by the game as its own process (`python -m wyrd.midgard.editors.verilog_editor`), as the original launched `verilogEditor.jar` with `ProcessBuilder`. Its logic is Qt-free (`wyrd/midgard/model/vedit.py`). If PySide6 is missing the game uses the external editor (Section 8) | Peter, 2026-10-21 (scope update). A pygame in-window editor was considered and rejected: pygame has no text widget, so cursor, selection, undo, find and clipboard would be rebuilt by hand (about 1,000 lines more than the Qt code), and the original is a separate window anyway |
| 20 | The level editor is ported as a PySide6 tool: command `midgard-editor` and a Wyrd III `Tools` entry; it reads and writes the original level XML (Section 8.2) | Peter, 2026-10-21 (reverses the earlier "no level editor") |
| 21 | Scores, high scores and the high-score files count ticks (5.7, 5.8); seconds are `ticks // 60` | Decision 10 |

## 3. What the original is (read from the source, 2026-10-21)

Source: `verilogTown-master.zip` (MIT, `README.md`: "This project adopts MIT licensee"; each Java file carries the
MIT header, Copyright (c) 2014 Peter Jamieson, Naoki Mizuno, and Boyu Zhang; the zip has no separate LICENSE
file). About 27,000 lines of Java in these parts:

| Part (zip path under `VERILOG_TOWN/`) | Content | In W4 |
|---|---|---|
| `verilogTown` (libGDX game, 23 classes) | The game | Ported (Section 4) |
| `verilogTown-desktop` | `Main`: LwjglApplication, 600 by 600 window | `app.main` |
| `VerilogSimulator` (~11,000 lines with the ANTLR 4 generated `Verilog2001` parser, twice) | The game's own Verilog subset interpreter (`Parse`, `SimVisitor`, ...) | Replaced by Odin III through Bifrost III (stated deviation 2); read only to confirm what the game observes (7.2) |
| `VerilogEditor` (Swing, 8 classes, 47 files with images) | The in-house editor, launched by the game as its own window; templates `header/stop_light_combo.v` and `stop_light_seq.v` | Ported as a PySide6 window (Section 8.1) |
| `LevelEditor` (Swing, 10 classes, 31 files with 17 tile images) | Level authoring: create or update a level XML, edit the 2 by 2 tile groups, edit cars, export the XML and the map PNG | Ported as a PySide6 tool (Section 8.2) |
| `verilogTownServer` (4 classes), `LocalServer` | A socket server and client: per level result records (id, level, time, cars total, cars passed) and usage times (game total, editor) | Not ported (stated deviation 1); the local high-score screen keeps its fields |
| `verilogTown-android`, `verilogTown-html` | Other launchers (the Android module holds the shared `assets/`) | Not ported; assets reused |
| `Levels/Lv0..Lv12/` (top level of the zip) | `map/lvNN.xml`, `map/lvNN.png`, `VerilogFiles/Traffic_signal_set_I.v`, `sensorFile.txt`, `high_score.txt` | Maps reused (Section 11) |

Level facts, parsed from the 13 XML files: every map is `size_x="22" size_y="22"` (20 by 20 visible tiles; the
ring of tiles at index 0 and 21 holds invisible start and end tiles); cars and intersections per level:

| Level | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Cars | 18 | 10 | 20 | 34 | 30 | 16 | 26 | 19 | 30 | 34 | 40 | 40 | 25 |
| Intersections | 1 | 2 | 3 | 1 | 1 | 4 | 9 | 4 | 4 | 4 | 6 | 4 | 11 |

Smallest start delay per level (ticks): 50, 100, 100, 20, 10, 1, 10, 20, 10, 20, 20, 23, 100 (never 0, which
would never start; the loader rejects it, Section 5.6).

All 54 shipped `Traffic_signal_set_I.v` files are byte-identical (md5 `08deb0d4...`). They are a working combinational
controller (the "combinational template" the web page says every light starts with): when the four internal
sensors are clear, the first of N (bit 6), S (bit 4), E (bit 5), W (bit 7) with a waiting car gets Go and the
others Stop, and all four get Go when nobody waits; when the centre is occupied all Stop. `Lv1/VerilogFiles/
Traffic_lights_set_0.v` is the odd one out: constant outputs (`outN = Left_only`, `outW = Right_only`, `outS = Go`,
`outE = Stop`). (An earlier draft of this spec had the two swapped.) W4 uses the stub as the starter and the test
oracle (Section 12). The main menu offers levels 1 to 12, Tutorial (level 0), High Score and Credits; the Java
constant `level_num` is 12 and the zip holds `level13_*` button images but no level 13 map (Question 6).

## 4. Java classes and what each becomes

Package `com.me.myverilogTown` (all paths under `wyrd/midgard/`):

| Java class | Python | Notes |
|---|---|---|
| `GridType` (25 values) | `model/grid.py` `GridType(Enum)` | Same names; sets `END_TYPES`, `CORNER_TYPES`, `START_TYPES` |
| `Direction` | `model/grid.py` `Direction(Enum)` N, S, E, W | |
| `TrafficSignalState` | `model/grid.py` `SignalState(IntEnum)` | `STOP=0, GO_FORWARD=1, GO_LEFT=2, GO_RIGHT=3, GO=4, NO_SIGNAL=5`; `decode_signal(code)` |
| `IntersectionType`, `TrafficType` | strings `FOUR_WAY`, `THREE_WAY_NSE`, `THREE_WAY_SEW`, `THREE_WAY_NSW`, `THREE_WAY_NEW` in `model/levelxml.py` | `TrafficType` is unused in the original |
| `GridNode` | `model/grid.py` `Node` | `x, y, type, north, south, east, west, sensor, ending_counter, control, location, car` |
| `LevelXMLParser` (+ inner `Intersection`) | `model/levelxml.py` `parse_level_xml`, `LevelData` | Parsing only (no linking); linking in `townmap.py` |
| `VerilogTownMap` | `model/townmap.py` `TownMap` | Grid build, links, intersections, `find_path`, `get_turn`, `forced_cars`; the `cycle_signal*`, `crash_signal`, `display_traffic_lights` debug helpers are not ported |
| `TrafficControl` | `model/traffic.py` `TrafficControl` | Entry and internal nodes, `read_sensors`, `set_signals`, `signal_when`; the render methods move to `ui/draw.py` |
| `GeneralSensor` | `model/sensors.py` `Sensor` | `read()` is `readSensorInfo` as an int |
| (in `LevelScreen`) sensor placement, `sensorFile.txt` | `model/sensors.py` `SensorSet`, `SensorEditor` | |
| `Car` | `model/car.py` `Car` | Logic only; sprites and arcs are UI |
| `CarAnimateStates` | `model/car.py` `CarState(Enum)` STOPPED, MOVING | |
| `LevelLogic` | `model/logic.py` `LevelLogic` | `update` becomes `tick`; crash detection is `check_crashes` |
| `LevelScreen` (+ inner `InputHandler`) | `model/level.py` `Level` (state machine) and `ui/levelscreen.py` `LevelScreen` | Input, drawing, camera; camera dropped |
| `ScoreScreen` | `model/scores.py` `ScoreTable`, `ui/scorescreens.py` `ScoreScreen` | |
| `LocalHighScoreScreen`, `ScoreAndTimeTexture` | `ui/scorescreens.py` `HighScoreScreen`, `ui/draw.py` `draw_number`, `draw_time` | |
| `MainMenu`, `TextureButton` | `ui/menu.py` `MainMenu`, `ui/draw.py` `Button` | |
| `CreditsScreen` | `ui/scorescreens.py` `CreditsScreen` | Text in the default font |
| `VerilogTown` (Game), desktop `Main` | `ui/game.py` `Game`, `app.py` `main` | |
| `LocalServer`, `VerilogTown.readID/sendTotalTime` | not ported | Decision 13 |
| `myverilogTown` (libGDX template) | not ported | Unused |
| `VerilogSimulator.Parse` (`compileFileForGame`, `sim_cycle`) | `model/controllers.py` `MidgardController` over `BifrostSession` | Section 7 |
| `VerilogEditor` | external editor, `model/watch.py` | Section 8 |

## 5. Game mechanics (the port target)

All coordinates, formulas and orders below are those of the Java source. Python pseudocode is normative where
it appears. `TILE = 64`, `SPEED = 4` pixels per tick (so 16 ticks per tile), `TICKS_PER_SECOND = 60` (5.9).

### 5.1 Grid and level file

`grid[x][y]` is a `size_x` by `size_y` array of `Node`, `x` from the west, `y` from the south (y grows north).
Tile `(x, y)` is drawn at map pixel `((x - 1) * 64, (y - 1) * 64)` with the origin at the bottom-left of the
map picture; the visible tiles are `1..size-2`. Every node starts as `NON_ROAD`.

`lvNN.xml`: `<level lv="N"><map size_x size_y><grid x y><type>T</type>[<intersection>K</intersection>]</grid>...</map>
<cars><car><start x y/><end x y/><delay>D</delay></car>...</cars></level>`. A `<type>` sets the node type; an
`<intersection>` names the kind of the intersection whose upper-left internal tile is `(x, y)`. Unknown type text
is `NON_ROAD` (as the Java `getGridType` default).

Links (`setDestination`, once per node after all types are set); a link is `None` when the target is outside the
array:

| Type | Links |
|---|---|
| `START_SEDGE2N`, `STRAIGHT_ROAD_N2N`, `CORNER_ROAD_E2N`, `CORNER_ROAD_W2N` | north = `(x, y+1)` |
| `START_NEDGE2S`, `STRAIGHT_ROAD_S2S`, `CORNER_ROAD_W2S`, `CORNER_ROAD_E2S` | south = `(x, y-1)` |
| `START_EEDGE2W`, `STRAIGHT_ROAD_W2W`, `CORNER_ROAD_N2W`, `CORNER_ROAD_S2W` | west = `(x-1, y)` |
| `START_WEDGE2E`, `STRAIGHT_ROAD_E2E`, `CORNER_ROAD_N2E`, `CORNER_ROAD_S2E` | east = `(x+1, y)` |
| `INTER_TURN_S2WS` | west and south |
| `INTER_TURN_N2EN` | east and north |
| `INTER_TURN_E2SE` | south and east |
| `INTER_TURN_W2NW` | north and west |
| `END_*`, `NON_ROAD` | none |

Intersections: collect the `<intersection>` elements, sort by `y` descending then `x` ascending (index `i` of this
order is the signal index `i`, and the player file `Traffic_signal_set_i.v`), and for each `(kind, x, y)` build a
`TrafficControl` from these nodes: entry N `g[x+1][y-2]` (cars heading north), entry S `g[x][y+1]`, entry E
`g[x-1][y-1]`, entry W `g[x+2][y]`; internal upper-left `g[x][y]`, upper-right `g[x+1][y]`, lower-left
`g[x][y-1]`, lower-right `g[x+1][y-1]`. Entries present: `FOUR_WAY` N, S, E, W; `THREE_WAY_NSE` N, S, E;
`THREE_WAY_SEW` S, E, W; `THREE_WAY_NSW` N, S, W; `THREE_WAY_NEW` N, E, W. Each present entry node gets
`control` and `location` 0 (N), 1 (S), 2 (E), 3 (W); each internal node gets `location` 4. Level 1, control 0
(at `(5, 12)`): N `(6, 10)`, S `(5, 13)`, E `(4, 11)`, W `(7, 12)`, UL `(5, 12)` (`INTER_TURN_S2WS`), UR `(6, 12)`,
LL `(5, 11)`, LR `(6, 11)`.

Ending counters (numbering of the end tiles; used by sensors): `c = 0`; for `x` ascending over the top row
`y = size_y - 1`, each `END_N2NEDGE` gets `c`, `c += 1`; for `y` descending over the east column `x = size_x - 1`,
each `END_E2EEDGE`; for `x` descending over the bottom row `y = 0`, each `END_S2SEDGE`; for `y` ascending over
the west column `x = 0`, each `END_W2WEDGE`. Level 1: `(6,21)=0, (14,21)=1, (21,11)=2, (13,0)=3, (5,0)=4,
(0,12)=5`.

### 5.2 Signals

A `TrafficControl` holds four `SignalState`s (`facing_north` .. `facing_west`, all `STOP` at creation), the
signal for cars entering from that entry. `node.traffic_signal()` is `NO_SIGNAL` when `node.control is None` or
`node.location == -1`, else `control.signal_when(location)`, which is the matching facing state for locations 0
to 3 and `NO_SIGNAL` for 4 (internal). Light output codes: 0 STOP, 1 GO_FORWARD, 2 GO_LEFT, 3 GO_RIGHT, 4 GO;
codes 5 to 7 (the Java would crash) are decoded as STOP and the game shows a warning line
`Traffic_signal_set_I.v: output code 5 treated as STOP`.

### 5.3 Sensors

Light sensors (`read_traffic_signal`), 8 bits for one intersection, bit i is 1 when the node has a car:

| bit | 7 | 6 | 5 | 4 | 3 | 2 | 1 | 0 |
|---|---|---|---|---|---|---|---|---|
| node | entry W | entry N | entry E | entry S | internal LR | internal LL | internal UR | internal UL |

A missing entry reads 0. In the Verilog: `input [7:0] sensor_light`. Bit 6 means "a car waits on the entry where
north-bound cars come from".

General sensors: seven placeable sensors, numbers 0 to 6 (`sensorFile.txt`: seven lines `number x y`, `0 0` = not
placed). A placed sensor sits on a tile (`x`, `y` in node coordinates). Each reads 4 bits: `0000` when the tile has
no car, else `1` followed by the three low bits of the ending counter of the car's destination
(`car.end.ending_counter & 7`). The word is `general_sensors[29:0]`: sensor `k` occupies bits `4k+3 .. 4k`
(bit `4k+3` is "car present"), bits 29 and 28 are 0. In Python: `word = sum(read_k << (4 * k) for k in range(7))`.
(The Java builds the string `"00"` + sensor 6 .. sensor 0.) The word is the same for every intersection.

Placement (the original `LevelScreen`), before the simulation starts: the unused sensors wait in a pile drawn
at the bottom-left tile; a left-click release on the pile picks the highest-numbered unused sensor; the sensor
then follows the mouse; a release on a valid tile places it (and the file is saved); a left-click release on a
placed sensor picks it up to move it; a right-click release cancels a pick or, on a placed sensor, removes it;
key `C` removes all. Valid tile: not `NON_ROAD`, `control is None` (not an entry or internal tile), and no
sensor already there (the Java allowed stacking and lost one; Midgard III refuses). The mouse tile is
`(floor(map_x / 64) + 1, floor(map_y / 64) + 1)` for map pixel `(map_x, map_y)` (y up from the map bottom).

### 5.4 Cars

A car: `start`, `end`, `original_end`, `start_time` (ticks), `current` (node or `None`), `way_point`, `path`
(a stack: a Python list, top = last element), flags `started`, `done`, `crashed`, `forced_turned`, `direction`,
`animation_direction`, `state` (STOPPED at creation), and position `px, py` (map pixels, ints).

`direction` (set on arrival, `set_car_direction(frm, to)`): with `frm is None`: by the type of `to`:
`START_NEDGE2S` S, `START_SEDGE2N` N, `START_EEDGE2W` W, `START_WEDGE2E` E. Else by the type of `to`: corners
`W2S`, `E2S` give S; `N2E`, `S2E` give E; `N2W`, `S2W` give W; `E2N`, `W2N` give N. Else by position:
`to.x > frm.x` E, `<` W, `to.y > frm.y` N, `<` S.

`animation_direction(frm, to)` (direction of travel on screen): with `frm is None`: as `direction` for start
types. Else by the type of `frm`: corners `W2S`, `E2S` give S; `N2E`, `S2E` E; `N2W`, `S2W` W; `E2N`, `W2N` N;
else by position as above. (It uses the type of `frm`, `direction` the type of `to`: ported as is.)

`check_for_crash(a, b)`: with `ax0 = a.px + 10`, `ax1 = a.px + 54`, `ay0 = a.py + 10`, `ay1 = a.py + 54` and the
same for `b`, true when any of the four corners `(bx0,by0) (bx1,by0) (bx0,by1) (bx1,by1)` satisfies
`ax0 <= x <= ax1 and ay0 <= y <= ay1`.

### 5.5 Path finding

```
END_TYPES = {END_S2SEDGE, END_N2NEDGE, END_E2EEDGE, END_W2WEDGE}

def find_path(existing, start, end, car):           # existing: list | None
    queue = deque([start]); parent = {}             # parent[node] = node that enqueued it
    possible_end = None
    while queue:
        cur = queue.popleft()
        if possible_end is None and cur.type in END_TYPES: possible_end = cur
        for nb in (cur.north, cur.south, cur.east, cur.west):
            if nb is end: return back_traverse(existing, end, start, cur, parent)   # first match
        for nb in (cur.north, cur.south, cur.east, cur.west):
            if nb is not None and nb not in parent and nb is not start:
                queue.append(nb); parent[nb] = cur
    # no path to end: force the car to the first end tile the search reached
    car.end = possible_end
    if not car.forced_turned: town.forced_cars += 1
    car.forced_turned = True
    return find_path(existing, start, possible_end, car)

def back_traverse(existing, end, start, current, parent):
    path = existing if existing is not None else []
    path.append(end)
    if current is not start:
        node = current
        path.append(node); node = parent[node]
        while node is not start: path.append(node); node = parent[node]
    return path
```

The top of the stack (`path[-1]`) is the first node after `start`; the bottom is `end`. If no end tile was
reached (`possible_end is None`) the Java crashes; Midgard III marks the car done and failed (`forced_turned`
`True`, counted once in `forced_cars`, then `car.done = True`, `current = None`, node cleared). The `nb is not
start` test only differs from the Java (which does not mark `start`) in maps with a cycle back to `start`, which
none of the 13 maps has.

`set_path(car, to, via)`:

```
if via is None and car.way_point is None:
    car.path = find_path(None, to, car.end, car)
elif car.way_point is to:
    car.way_point = None
    car.path = find_path(None, to, car.end, car)
elif via is not None:
    car.way_point = via
    p = find_path(None, via, car.end, car)
    car.path = find_path(p, to, via, car)
else:
    p = find_path(None, car.way_point, car.end, car)
    car.path = find_path(p, to, car.way_point, car)
```

`get_turn(current, signal, direction) -> Node | None` (the node a forced turn must pass through; `None` when a
link is missing, which makes the car stop):

| signal | N | S | E | W |
|---|---|---|---|---|
| `GO_FORWARD` | `current.north.north.north` | `current.south.south.south` | `current.east.east.east` | `current.west.west.west` |
| `GO_LEFT` | `current.north.north.west.west` | `current.south.south.east.east` | `current.east.east.north.north` | `current.west.west.south.south` |
| `GO_RIGHT` | `current.north.east` | `current.south.west` | `current.east.south` | `current.west.north` |

(`direction` is the car's heading.) Level 1, from entry S `(5, 13)` heading south: forward `(5, 10)`, left `(7, 11)`,
right `(4, 12)`.

### 5.6 One game tick (`LevelLogic.update`)

```
def tick():
    time_step += 1
    general = general_word(sensors)                       # Section 5.3
    for i, tc in enumerate(town.controls):
        light = tc.read_sensors()                         # 8 bits
        n, s, e, w = controllers[i].step(light, general)  # one Bifrost III step each (Section 7)
        tc.set_signals(decode(n), decode(s), decode(e), decode(w))
    queue = [c for c in cars if c.start_time == time_step or c.running]   # running = started and not done
    for car in queue:                                      # in car order
        car.animate()                                      # if MOVING: px/py += SPEED along animation_direction
        if car.start_time == time_step:
            car_starts(car); car.state = MOVING
        elif car.at_next_grid():                           # px % 64 == 0 and py % 64 == 0
            if car.state != STOPPED:
                update_spot(car)                           # step onto the next path node
                if car.done:
                    done_count += 1; success_raw += 1; continue
            cur = car.current
            sig = cur.traffic_signal()
            if sig in (NO_SIGNAL, GO):
                car.state = MOVING; free_movement(car, cur)
            elif sig in (GO_RIGHT, GO_LEFT, GO_FORWARD):
                car.state = MOVING; forced_movement(car, cur, sig)
            elif sig == STOP:
                car.state = STOPPED
    check_crashes(cars)                                    # updates crash_count and done_count
    return done_count >= len(cars)
```

```
def car_starts(car):
    set_current_point(car, None, car.start)
    set_path(car, car.start, None)
    car.px, car.py = (car.current.x - 1) * 64, (car.current.y - 1) * 64
    car.animation_direction = animation_direction(None, car.current)
    car.started = True

def update_spot(car):
    nxt = car.path.pop()
    set_current_point(car, car.current, nxt)

def set_current_point(car, frm, to):
    car.direction = direction(frm, to)
    car.current = to
    if frm is not None: frm.car = None
    to.car = car
    if to is car.end or to.type in END_TYPES:               # reached an end (the right one or not)
        if frm is not None: frm.car = None
        to.car = None
        car.done = True; car.current = None

def free_movement(car, cur):
    nxt = car.path.pop()
    if car_in_front(car, nxt): car.path.append(nxt); car.state = STOPPED; return
    car.animation_direction = animation_direction(cur, nxt)
    set_path(car, cur, None)

def forced_movement(car, cur, sig):
    via = town.get_turn(cur, sig, car.direction)
    if via is None: car.state = STOPPED; return
    nxt = car.path.pop()
    if car_in_front(car, nxt): car.path.append(nxt); car.state = STOPPED; return
    car.animation_direction = animation_direction(cur, nxt)
    set_path(car, cur, via)

def car_in_front(car, nxt):
    other = nxt.car
    return other is not None and (other.direction == car.direction or other.current.type in CORNER_TYPES)

def check_crashes(cars):                                    # exact order, including the extra i += 1
    i = 0
    while i < len(cars):
        if cars[i].running:
            for j in range(i + 1, len(cars)):
                if cars[j].running and check_for_crash(cars[i], cars[j]):
                    cars[i].crash(); i += 1; cars[j].crash()
                    done_count += 2; crash_count += 2
                    break
        i += 1
```

`crash()` sets `current.car = None`, `crashed = True`, `done = True`, `current = None`.
`CORNER_TYPES` is the eight `CORNER_ROAD_*` types. A path pop on an empty stack cannot happen in the Java and is
a `RuntimeError` here. A car whose `start_time` is already past (a level file with delay 0) never starts; the
loader rejects `delay < 1` with a `LevelFormatError`.

Level state: `forced_cars` is on the map. The level is done when `done_count >= number of cars`.

### 5.7 Score and the end of a level

```
passed  = max(0, success_raw - forced_cars)
failed  = forced_cars + crash_count
ticks   = number of ticks run in the RUN phase         # the score time (5.9)
seconds = ticks // TICKS_PER_SECOND                    # shown as MM:SS beside the tick count
```

`passed + failed == len(cars)` when the level is done and `success_raw >= forced_cars`. (The Java clamps
`passed` at 0 only in the score bar. A forced car that then crashes is counted in `failed` twice and its
success is missing from `passed`; ported as is.) There is no pass or fail verdict: the level ends when every
car is done; the score is `passed` cars and the time in ticks.

### 5.8 High scores

`high_score.txt`: ten lines `cars time` where `time` is in ticks (the original stored whole seconds; deviation 5 and Question 8). A result `(passed, ticks)` is inserted when `passed >= 1`: the table is
sorted by cars descending then time ascending; the result goes before the first entry that it beats (more cars,
or the same cars and less time); an equal pair is not inserted; the table keeps ten entries; empty slots are
`0 0`. (The Java insert code duplicates an entry when the cars are equal and the time is less; not ported.)
A missing, short or garbled file reads as `0 0` rows. Levels 1 to 12 are shown on the high-score screen; level 0
has a file but no page.

### 5.9 Game time (Peter's design, 2026-10-21)

What the Java did (`LevelScreen.render`): `Frame_Time_25 = 1 / 25` is integer division and equals 0, so
`Next_Frame_Time >= Frame_Time_25` is true on every rendered frame: one `LevelLogic.update` per frame, whatever the
frame rate. `Main.java` sets only title, size and `useGL20`; the libGDX 0.9.9 `LwjglApplicationConfiguration`
defaults (read from the libGDX source on GitHub, 2026-10-21; the zip holds no libGDX jar, so the version is the
era's, not read from the project) are `vSyncEnabled = true` and `foregroundFPS = 61`, so the game ran at the display
refresh rate, normally 60 frames per second. The score time was `playTime += getDeltaTime()` on each tick frame:
wall-clock seconds of simulation, `(int)` truncated in `MM:SS`. Comments in `LevelLogic` ("a second of time at 25
FPS") and the web pages ("the game clock ticks at 25 Hz", the sequential template: 64 ticks, 2.56 s) describe an
intended 25 ticks per second that the code never did. Not verified against a running original.

Midgard III defines:

1. **One unit.** 1 game tick = exactly 1 rising edge of `clk` of the player's module = 1 `BifrostSession.step(1)` =
   1 `LevelLogic.update`. The original's two `sim_cycle` passes per tick (sequential pass and combinational pass of one
   clock) are one edge (7.2). Stated in the in-game help, the Tutorial text, and the README.
2. **Fixed step, deterministic.** The world advances in whole ticks from an accumulator that depends only on elapsed
   wall time and the speed, never on the render frame rate:
   `acc += dt * TICKS_PER_SECOND * speed; acc = min(acc, MAX_BACKLOG); n = int(acc + 1e-9); acc = max(acc - n, 0)` with
   `TICKS_PER_SECOND = 60`, `MAX_BACKLOG = 30` (a stall drops wall time, never part of a tick). The sequence of
   ticks, the Verilog inputs and outputs at each tick, and the score are a function of the level, the sensor
   placement and the Verilog only: the same on any machine and at any frame rate.
3. **Base speed.** 1x = 60 ticks per second, the apparent speed of the original. `TICKS_PER_SECOND` is the one
   constant to change if Peter prefers 25 (Question 8).
4. **Speed controls change wall time per tick only:** pause, single step (one tick), 1x, 2x (120 per second), 4x
   (240 per second). Keys and on-screen buttons in 9.4.
5. **Visible clock** (9.4): the tick counter; in PAUSE the current `sensor_light`, `general_sensors` and `outN outS
   outE outW` of each intersection; a Record toggle keeps a Bifrost III recording per intersection; export to VCD.
6. **Scores in ticks.** `LevelResult.ticks`; the score screen shows the tick count and `MM:SS` of `ticks // 60`; the
   high-score file stores ticks.

Arithmetic for the plan's numbers (ticks do not depend on the rate, so every tick-count in the tests is unchanged;
only seconds change): a car crossing level 1 alone is done on tick 337, so `seconds = 337 // 60 = 5` (337 / 60 =
5.617); the stop-and-go car of Task 5 is done on tick 409, `409 // 60 = 6`; a crash on tick 2 is `2 // 60 = 0`;
`format_time(7500) = "02:05"` (7500 // 60 = 125 s = 2 min 5 s). Under 25 ticks per second these would be 13 (337 //
25), 16, 0 and `"05:00"`.

## 6. Architecture

```
wyrd/midgard/
  __init__.py  __main__.py  app.py
  model/  grid.py levelxml.py townmap.py traffic.py sensors.py car.py logic.py level.py clock.py
          controllers.py scores.py userdata.py watch.py vedit.py leveldoc.py        (no pygame, no Qt)
  ui/     view.py camera.py assets.py draw.py menu.py levelscreen.py clockstrip.py scorescreens.py game.py
  editors/ verilog_editor.py level_editor.py                                         (PySide6 only here)
  assets/ data/ ASSET_RESOURCES/ levels/ editors/ vedit/ ledit/ fonts/ templates/ starter.v examples/ NOTICE MANIFEST.sha256
```

`Level` (model, no pygame) is the state machine of `LevelScreen`:

```python
class Phase(Enum): EDIT = 1; RUN = 2; PAUSE = 3; DONE = 4

@dataclass(frozen=True)
class LevelResult: passed: int; failed: int; crashed: int; forced: int; ticks: int; cars: int   # .seconds = ticks // 60

class Level:
    def __init__(self, data: LevelData, sensors: SensorSet)
    phase: Phase; ticks: int; town: TownMap; cars: list[Car]; sensors: SensorSet; editor: SensorEditor
    def start(self, controllers: Sequence[LightController]) -> None   # EDIT -> RUN; resets controllers (Section 7.4)
    def toggle_pause(self) -> None                                    # RUN <-> PAUSE (ignored in EDIT, DONE)
    def tick(self) -> bool                                            # one LevelLogic.update when RUN; True when done
    def step_once(self) -> bool                                       # PAUSE: exactly one tick, stays PAUSE (or DONE)
    def result(self) -> LevelResult
```

`LightController` (the seam between engine and Verilog):

```python
class LightController(Protocol):
    def start(self) -> None                                   # the reset sequence (7.4)
    def step(self, light_sensors: int, general_sensors: int) -> tuple[int, int, int, int]  # codes N, S, E, W
    def close(self) -> None
    last_inputs: tuple[int, int] | None                       # (sensor_light, general_sensors) of the last step
    last_outputs: tuple[int, int, int, int] | None            # codes N, S, E, W of the last step
    def start_recording(self) -> None                         # Bifrost III recording (no-op for scripted controllers)
    def recording(self) -> Recording | None
    def export_vcd(self, path: Path) -> None                  # wyrd.bifrost.vcd.write_vcd
```

`ScriptedController(fn)` wraps a Python function (tests, the safe-controller oracle); `MidgardController` wraps a
`BifrostSession` (Section 7). `model/clock.py` `TickClock` is the accumulator of 5.9. `ui/game.py` `Game` owns the screen stack, the clock and the data directory.

## 7. The Verilog interface

### 7.1 Ports of the player's module

One file per intersection, `Traffic_signal_set_I.v`, `I` the signal index. The module may have any name (the
original files use `light1`); Odin III chooses the top as the module no other module instantiates, so a file
may hold helper modules. Required ports (checked after compile):

| Port | Direction | Width | Meaning |
|---|---|---|---|
| `clk` | input | 1 | clock; Midgard III never sets it (one step ticks it) |
| `rst` | input | 1 | **active low**: 0 during the start-up cycle, 1 while playing |
| `sensor_light` | input | 8 | Section 5.3 |
| `general_sensors` | input | 30 | Section 5.3 |
| `outN` | output | 3 | signal for cars heading north (entry N) |
| `outS` | output | 3 | entry S |
| `outE` | output | 3 | entry E |
| `outW` | output | 3 | entry W |
| `debug_port` | output | 30 | optional; ignored |

Output codes: `Stop = 3'b000, Forward_only = 3'b001, Left_only = 3'b010, Right_only = 3'b011, Go = 3'b100`. A
missing or wrongly sized required port is a build error shown in the game (7.5); `clk` may be `input` or
`clock` in Bifrost III's view (a design with no sequential logic has no clock).

### 7.2 How the Java simulator was driven, and the mapping

Java, per tick and intersection: `sim_cycle("1", sensor_light, general_sensors)` twice; the first argument is
the value of port `rst`, `clk` is never read; the two calls are the sequential pass and the combinational pass
of one clock (`SimVisitor.next_sim_cycle` toggles them). At level start, after a successful compile, two calls
`sim_cycle("0", "00000000", "000...0")` reset every register (rst low). Outputs are read from the new values
after the second call.

Midgard III: one Bifrost III step is one full clock cycle (settle, rising edge, settle, falling edge, settle), the same
as the pair of passes. Per tick and intersection: `set sensor_light`, `set general_sensors` (only when they
changed), `step(1)`, `get outN`, `get outS`, `get outE`, `get outW`. The decoded codes go to
`TrafficControl.set_signals(N, S, E, W)` before cars move, as in `LevelLogic.update`.

### 7.3 Compile flow and the starter file

Bifrost III compiles with `read_verilog "file"; proc; opt; lower` (W3 decision 7). The shipped original files do not
compile under Odin III: `output [29:0] debug_port;` is declared in the body but is not in the header port list
(verified 2026-10-21 with Odin III 1.0.0: `Lv0/VerilogFiles/Traffic_signal_set_0.v:4:14: error: 'debug_port' is
declared as a port but is not in the port list`). The starter `assets/starter.v` is the original stub (the
"combinational template", a working controller, Section 3) with the header changed to `module light1 (clk, rst,
outN, outS, outE, outW, sensor_light, general_sensors, debug_port);` and three added comment lines (active-low
reset; one step is one clock cycle; the output codes). With that change all 54 shipped files compile and simulate
under Odin III 1.0.0 (checked the same day). `assets/examples/constant_outputs.v` is
`Lv1/VerilogFiles/Traffic_lights_set_0.v` with the same header change (a deliberately poor controller). The editor
templates `assets/templates/combinational.v` (`VerilogEditor/src/header/stop_light_combo.v` with the header fix) and
`sequential.v` (`stop_light_seq.v`, whose header already lists `debug_port`) are the two the original editor
offered in its Template menu. The earlier `examples/lv1_safe.v` is dropped: the starter has that logic.

Differences from the Java subset that a player may notice: Odin III accepts all synthesizable Verilog (instances,
`generate`, arrays, any vector width), where the Java subset had no instantiation and vectors up to 30 bits; it
rejects what the Java forgave (undeclared ports, syntax errors) and tells `file:line:col`. A clock must be the
top input `clk` (gated clocks are rejected by S1).

### 7.4 Start sequence

```
def MidgardController.start():
    session.reset()                       # power-on: every value 0, so rst = 0
    session.set("sensor_light", 0); session.set("general_sensors", 0)
    session.step(1)                       # the original's two passes with rst = "0": one clock cycle in reset
    session.set("rst", 1)
```

The lights stay `STOP` until the first tick (the Java did not apply the reset-cycle outputs).

### 7.5 Errors shown in the game

`build_controllers(paths, backend)` compiles every file independently (one `BifrostSession` per file) and returns
`BuildResult(controllers: list[LightController | None], errors: list[PlayerError])`. `PlayerError(index: int,
file: Path, line: int | None, col: int | None, message: str)`, shown as `Traffic_signal_set_I.v:LINE:COL:
message` (the first error of each failing file; up to 6 lines on screen, then `and N more`). Sources: compile
errors (every `error` diagnostic's first), a missing or wrongly sized port (`file`, line `None`: `port 'outW' is
missing` or `port 'sensor_light' must be an input of width 8, found input of width 4`), an unreadable file. A
failing intersection gets the `stop_compiled_failed` marker on its entries. If any file fails, the level stays in
EDIT. A `SimError` while running (it should not happen) pauses the level and shows `runtime error in
Traffic_signal_set_I.v: message`. `SimUnavailable` (no `odin3`) is shown once as one line:
`needs Odin III 1.0.3: pip install "wyrd[sim]"` and the game still lets the player place sensors and look.

## 8. Editing, file watch, reload

By default a click opens the editor window of 8.1. The bullets below are the external-editor path (kept as an extra,
and used when PySide6 is missing) and the file watch, which serves both.

- Click (left release) on a tile with `control` (an entry or internal tile) in EDIT, not placing a sensor, at
  least 0.6 s after the last open: open `<data>/Lv{N}/VerilogFiles/Traffic_signal_set_{i}.v` in the external
  editor and highlight that intersection's entries with `stop_tran_highlighted` while hovering.
- External editor command, first match: `$MIDGARD_EDITOR` (split with `shlex`) plus the path; `code` (VS Code,
  also works from WSL) plus the path; `xdg-open` plus the path; `wslview` plus the path. If none exists the
  status line says `Edit this file: <path>`. A terminal editor in `$EDITOR` is not used (the game has no
  terminal). Pure function `editor_command(path, env, which)`.
- File watch: every 0.5 s the game compares `(st_mtime_ns, st_size)` of the level's Verilog files (a missing file
  is a change). In EDIT a change recompiles all files at once (so errors appear when the file is saved); in
  RUN or PAUSE it shows `File changed: press R to restart with the new code` and changes nothing.
  Atomic-rename saves are handled (the identity is the stat of the path).
- Reload: `R` rebuilds the level from the files and the sensor file; sessions are closed and recompiled. Compile
  also runs at level load (errors visible at once) and again when `S` is pressed the first time.

### 8.1 The Verilog editor window (port of `VerilogEditor`, Peter's scope update)

Launch: a left release on a tile with a `control` in EDIT (not placing a sensor, at least 0.6 s after the last
open; the Java: `!simulation_started && isSimulationPaused`) starts `sys.executable -m
wyrd.midgard.editors.verilog_editor --file PATH --level N --name Traffic_signal_set_I` with `subprocess.Popen`
(the Java: `ProcessBuilder` on `verilogEditor.jar`); no second editor for the same file. Editing is locked while the
level runs (the click does nothing). Without PySide6 or on `--external-editor` / `MIDGARD_EDITOR` the external
editor of the bullets above is used. The window is a `QMainWindow`:

- Menus (`QMenuBar`, shortcuts of the Java, Ctrl): File: Save `S`, Verify `R`, Exit `E`; Edit: Undo `Z`, Redo `Y`,
  Search and Replace `F`; Simulate `M`: Simulate, Reset Simulation; Template: Combinational `1`, Sequential `2`.
  (The Java gave Verify and Reset Simulation the same accelerator `R`; Reset keeps no shortcut here.)
- Toolbar (images from `VerilogEditor/src/images`): save, verify (the check mark), undo, redo, search, simulate,
  reset; then the label `Internal Sensors:` and an 8-character binary field (`sensor_light`, default
  `00000000`), and the general sensors field(s) (the Java had six 5-bit fields; here one 30-bit binary field,
  default 30 zeros, stated in Question 12).
- Panel B: the source (monospaced `QPlainTextEdit` with line numbers and a keyword/comment highlighter after
  `SyntaxHighlighter`); Panel C: messages (read-only); the animation panel after `AnimationPanel`: the
  intersection picture (`animationImage.png`) with the four light images (`go_`, `left_`, `right_`, `forward_`,
  `stop_` plus `n s e w`) for the last simulation result.
- Messages (the Java strings): Save writes the file and shows `Saving complete.`; Verify writes the file, shows
  `Compiling <path>`, then compiles and shows `Compile successful` or the errors as `Error at line L:C: message`
  (from the first diagnostics of Bifrost III); after a successful compile the editor runs the reset (two
  `sim_cycle` passes in the Java, with `rst` low then high, which is `MidgardController.start()`, 7.4); Reset
  Simulation recompiles and resets; Simulate needs a successful compile (otherwise `The Verilog code has not been
  successfully compiled yet.  Please click the check mark above and/or fix Verilog errors.`) and 8 and 30 binary
  characters (otherwise `Simulation cycle not sucessful` plus the Java hint text, with its misspelling kept); a
  good Simulate runs **one clock cycle = one `step(1)`** (the Java's two `sim_cycle` calls) and prints `Simulation
  Cycle`, `Clock Cycle:N`, `Sensors Light: ...`, `General Sensors: ...`, `OutN Val = ..`, `OutS`, `OutE`, `OutW`
  and the debug vector (`debug_port`, 30 bits), and the animation panel shows the four lights.
- Exit (window close or File > Exit): compile first; if the text changed ask `Content changed. Do you want to save
  this file?` (Yes saves and closes, No closes, Cancel stays). Template menu: replaces the text with the template
  (the Java: loses the changes of that light; a confirm box is added only if the text changed).
- Logic in `model/vedit.py` (Qt-free, testable): `EditorSession(path, backend)` with `compile() -> VerifyResult`,
  `reset()`, `simulate(light: str, general: str) -> SimResult | str` (the error text), `format_result(...)`,
  `is_dirty`, `load_template(name)`; the window only wires widgets to it. It owns its own `BifrostSession`; the game
  re-compiles all files when the file changes (the watcher of Section 8) and shows `File changed` as before.
- Size: Java 1,004 lines plus 8 helper classes; Python about 450 lines of logic and tests plus 600 lines of Qt.

### 8.2 The level editor (port of `LevelEditor`, Peter's scope update)

Command `midgard-editor [LEVEL.xml]` (gui script, extra `wyrd[midgard]`) and the Wyrd III `Tools` entry `Midgard III
Level Editor`. It reads and writes the original level XML exactly:

- Start dialog (after `LevelEditor`): `Create` (level number, map size X and Y, both even and at least 4) or `Update`
  (file chooser for an existing `lvNN.xml`); buttons OK, Cancel, Select. Invalid sizes show `Invalid map size`.
- Map window `Edit Level N`: the visible map as a grid of 2 by 2 tile groups (`size / 2` per axis; the XML map is
  `size + 2` per axis with the invisible start and end ring). Left click on a group opens the type chooser (a combo
  box of the 17 group types of `MapGrid`: `STRAIGHT_NS`, `_2`, `_3`, `STRAIGHT_EW`, `_2`, the four `CORNER_*`,
  `FOUR_WAY`, `_2`, the four `THREE_WAY_*`, `NON_ROAD`, `_2`); middle click rotates the type; right click and right
  drag set `NON_ROAD`; dragging with the left button lays road and sets the entry and exit directions
  (`StateTracker`, `BorderGrid`); buttons `Clear Map`, `Edit Cars`, `Export`, `Cancel`. Intersections on the map
  edge are refused with `Can't have intersections on the edge!`.
- `Edit Cars` (after `CarEditor`): a table of cars (start, end chosen from the start and end points the map
  defines, delay), `Add a Car`, `Save`, `Cancel`; an empty delay shows `Please input delay for all cars`; changing the
  start points of a new level clears the cars (the Java rule); a delay of 0 is refused (a car with delay 0 never
  starts, 5.6).
- `Export` writes `lvNN.xml` (the Java `exportXML`: `<level lv="N"><map size_x size_y>` then the border start and end
  cells, then the group cells in the Java order, then `<cars>`) and the map picture `lvNN.png` rendered from the 17
  tile images of `LevelEditor/src/images` (`getBufferedImage`), then `Finished exporting`.
- Qt-free model `model/leveldoc.py`: `LevelDoc` (groups, cars, `from_level_data`, `to_level_data`,
  `populate_starts_ends`, `validate`), and `model/levelxml.py` gains `write_level_xml(data: LevelData) -> str` (the
  inverse of `parse_level_file`, keeping cell order). Tests: for all 13 shipped levels (and `samples/first_map.xml`)
  load, build a `LevelDoc`, write: the text equals the original file byte for byte; if a shipped file was edited
  by hand so that the Java editor would not reproduce it, the test compares `LevelData` instead and the report
  lists those levels. The map PNG is checked for size and tile placement, not pixel identity with the shipped PNGs.
- Size: Java 2,876 lines; Python about 500 lines of model and tests plus 900 lines of Qt.

## 9. The program

### 9.1 Window and drawing

`midgard [--level N] [--data-dir DIR] [--speed 1|2|4] [--size WxH] [--no-editor]` (`--no-editor` never launches an
editor; tests). Entry: `midgard = "wyrd.midgard.app:main"` and `python -m wyrd.midgard`.

Each screen draws on its own logical surface: menu 1280 by 1280; score, high score and credits 1280 by 1380; the level
1280 by 1500 (the map is 1280 by 1280 at logical y 100 to 1380, the 100-pixel score bar is on top, the 120-pixel
clock strip of 9.4 is at the bottom). The window is
resizable; the logical surface is scaled with `pygame.transform.smoothscale` to the largest size that keeps the
aspect ratio (letterbox, black bars) and mouse positions are mapped back:

```python
class View:
    def __init__(self, logical: tuple[int, int])
    def layout(self, window: tuple[int, int]) -> tuple[float, tuple[int, int]]   # scale, offset
    def to_logical(self, pos: tuple[int, int], window: tuple[int, int]) -> tuple[int, int] | None  # None in a bar
    def to_window(self, pos: tuple[int, int], window: tuple[int, int]) -> tuple[int, int]
def initial_window_size(logical: tuple[int, int], desktop: tuple[int, int]) -> tuple[int, int]
    # scale = min(1.0, (dw - 80) / lw, (dh - 120) / lh); (round(lw * scale), round(lh * scale))
```

`initial_window_size((1280, 1380), (1920, 1080)) == (890, 960)`; `(1280, 1380), (3840, 2160)` is `(1280, 1380)`; for the level
surface `(1280, 1500)` at `(1920, 1080)`: scale `min(1, 1840 / 1280, 960 / 1500) = 0.64`, size `(819, 960)`.
World to screen: a map pixel `(px, py)` of a tile-sized sprite is drawn at logical `(px, 100 + 1280 - py - 64)`.

Level screen content: map picture; sensors (placed ones at tile origin `((x-1)*64, (y-1)*64)`, the pile at the
bottom-left tile; `sensor_non.png` when none is left); cars (frame list: index 0 `car_4.png`, 1 `car_5.png`, 2 to 5 the cells of `car_sheet.png` cut into 2 by 2
cells of 64 by 64 in order (row 0, col 0), (0, 1), (1, 0), (1, 1); car number `k` of level `L` uses frame
`random.Random(L * 1000 + k).randrange(5)` (0 to 4), the crash frame is index 5, the skull; a car is rotated by
its `direction`: E 0, N 90, W 180, S 270 degrees counterclockwise); signals (one image per
entry: `stop_tran.png`, `go_tran.png`, `go_left_tran.png`, `go_right_tran.png`, `go_forward_tran.png` scaled 0.7
about the tile centre and rotated N 0, S 180, E 270, W 90); the score bar (check mark and three red digits for
`passed`, skull and three digits for `failed`, `TIME` letters and `MM` `:` `SS`, `press_h_for_help.png` at the
bottom right); the help overlay (`help_menu.png`, key `H`, EDIT or PAUSE); the error panel (Section 7.5); a status line.

### 9.2 Screens and input

| Screen | Content (logical px; the Java y-up origin is converted to y-down as `y_down = H - y - height`) | Input |
|---|---|---|
| Main menu 1280x1280 | background `(199, 230, 199)`; `welcom_to_verilogtown.png` at `(200, 950)` size 800x200; `select_a_level.png` blinking when `int(t * 1.3) % 2 == 0` at `(370, 850)` 540x120; level buttons 250x60 at `(162 + (i % 3) * 350, 705 - 100 * (i // 3))` for `i` 0 to 11 (`levelK_{normal,mouse_on,pressed}.png`, `K = i + 1`); Tutorial `(512, 805)`; High Score `(512, 305)`; Credits `(512, 205)` | click a button (release inside) |
| Level 1280x1500 (the 1280 by 1380 level of the Java plus the 120-pixel clock strip, 9.4) | Section 9.1 | Original keys (Java, and the web page where it differs): `S` start (EDIT, compiles first) or resume (PAUSE); `P` or `X` pause (RUN); `H` help, only when stopped; `R` restart; `M` menu, only before the start; `C` clear sensors (EDIT); zoom and pan 9.3. Added keys (5.9, 9.4): `.` single step, `1` `2` `4` speed, `V` record, `E` export VCD. `Esc` is not used (the Java has no such key). Mouse: Section 5.3 and 8 |
| Score 1280x1380 | `level_finish.png` full size; level number (`chiller_num_*` 80x80 at `(578, 1088)` for one digit, `(545, 1088)` and `(595, 1088)` for two); passed three digits at x 725, 800, 875, y 660, size 75; failed y 420; time at y 895 (`MM:SS` of `ticks // 60`): digits at x 725, 790, colon 840, digits 895, 960, and under it the line `N ticks` (default font, logical y_down `1380 - 895 - 75 + 83 = 493`, x 725); buttons 300x98: Main Menu `(150, 150)`, Try Again `(500, 150)`, Next Level `(850, 151)` (`*_normal/mouse_on/pressed.png`) | click; Next Level on level 12 goes to the menu |
| High scores 1280x1380 | title `local_high_score.png` `(260, 1130)` 750x280; labels `rank.png` `(180, 1037)`, `cars.png` `(560, 1037)`, `time.png` `(940, 1037)` 150x84; page for level L: label `score_levelL_pressed.png` at `(500, 1090)` 300x140; ten rows `j` at `y = 950 - 100 * j`: rank (2 digits) x 200, cars (3 digits) x 555, time x 905; digit size 55, gaps 53 (score) and 48 (time: offsets `0, 48, 1.77*48, 2.54*48, 3.54*48`); Back `(30, 45)` 160x59, Next `(1180, 500)` 90x300, Last `(10, 500)` 90x300 | click; the page changes at once (no slide) |
| Credits 1280x1380 (`CREDITS_SCREEN_WIDTH` 1280, `HEIGHT` 1380) | background `(0.78, 0.9, 0.78)` = `(199, 230, 199)`; `credits.png` at `(450, 1160)` 360x110; the original text lines (names and roles) in black Creepster 58 px (names) and 50 px (roles) at the Java positions (e.g. the first name at `(30, 1150)`, its role text at `(120, 1080)`); Back `(1080, 40)` 160x59 | click Back |

Credits text (from the Java): Dr. Peter Jamieson (game design, much programming incl. the Verilog simulation and
car movement and path planning); Naoki Mizuno (XML level descriptions, level creation tool, beta developer);
Boyu Zhang (standalone Verilog editor, game control structure, beta developer); Alex Williams (early Verilog
parser with ANTLR 4); Josh Collins (early game parts: animation and levels); Lindsay Grace (collaborator on
game design); John-Rhys Garcia (main artist for tileset and vehicles); plus the lines
`Ported to Python and pygame-ce as Midgard III (Yggdrasil), see NOTICE` and the citation
`verilogTown, Jamieson, Grace, Mizuno, Zhang, ASEE 2017`.

Frame loop (`Game.run`): `clock = pygame.time.Clock()`; each frame `dt = clock.tick(60) / 1000`; events; if the
level is RUN: `for _ in range(tick_clock.advance(dt, speed)): level.tick()` (5.9); draw; `pygame.display.flip()`. `Game.frame(dt, events)` is one iteration without
waiting (the tests call it). When the level becomes DONE the screen waits 1.0 s then opens the score screen,
which records the high score once (on construction). The Java frame loop is replaced by the fixed-step loop of 5.9: the frame rate is capped at 60, ticks are taken from `TickClock`.

### 9.3 Zoom and pan (port of `LevelScreen` camera code)

The level layer (map picture, sensors, cars, signals, path preview) is drawn through a camera; the score bar and
the clock strip are not. `Camera(zoom, x, y)` in `ui/camera.py`, world size `W = 1280`, `H = 1380` (the 1280 map and
the 100-pixel bar), start `zoom = 1`, centre `(640, 690)`. Ported constants and rules (all disabled while the help
overlay is open or the level is done):

- Mouse wheel up: `zoom = 0.2 if zoom - 0.04 < 0.2 else zoom - 0.04`; wheel down: `zoom = 1 if zoom + 0.04 > 1 else
  zoom + 0.04` (round to 6 decimals after each step).
- `=` or `Q` (zoom in), held: each frame `if zoom >= 0.1: zoom -= 0.02`; `-` or `A` (zoom out), held: each frame
  `if zoom != 1: zoom += 0.02` (as the Java; the border rule below does not clamp the zoom).
- Cursor keys, held: the centre moves 3 world pixels per frame (up is +y).
- Dragging with any mouse button moves the centre by `last_real - current_real` (world coordinates under the
  pointer), skipped while `last_real_x == 0 or last_real_y == 0`.
- After every change `limit_to_border`: `min_c = (W, H) * zoom / 2`, `max_c = (W, H) - min_c`;
  `x = clamp(x, min_c.x, max_c.x)`; `y = clamp(y, min_c.y, max_c.y - (1 - zoom) * 100)`.
- Mouse to world (also used for tile picking): `real_x = (cx - W*z/2) + (mx / win_w) * W*z`, `real_y = (cy - H*z/2)
  + (1 - my / win_h) * H*z`, both clamped at `W` and `H`; a position with `real_y <= 1280` picks the tile
  `(int(real_x / 64) + 1, int(real_y / 64) + 1)`.

At `zoom = 1` the mapping is the identity of Section 9.1, so every tile and click number there is unchanged.
Checks: `zoom = 0.2` gives `min_c = (128, 138)`, `max_c = (1152, 1242)` and the largest `y` is `1242 - 0.8 * 100 =
1162`; at `zoom = 1` the centre cannot leave `(640, 690)`. Keys and pan run per rendered frame (as in the Java);
this is display only and has no effect on the game ticks.

### 9.4 The clock strip

A 120-pixel strip under the level (logical `y_down` 1380 to 1500), black with white text in the default font:

- Left: `Tick N` (the tick counter), `MM:SS` of `N // 60`, the speed (`1x 2x 4x`, or `PAUSED`), and the line `1 tick = 1 clock edge of your module` (the Tutorial, level 0, shows a longer text in EDIT: the module's `clk` rises once per
  tick; `rst` is low in the reset cycle; outputs are read after the edge; 60 ticks per second at 1x).
- Buttons (rectangles with text): `Pause/Resume`, `Step`, `1x`, `2x`, `4x`, `Rec`, `Export VCD`, `Waveform`
  (equivalent to the keys of 9.2). `Step` and `.` work in PAUSE (and in EDIT, where they start the level paused at
  tick 0); the speed buttons work any time.
- In PAUSE (also in DONE) the inspector lists, per intersection `i`: `sensor_light` (8 bits, binary), `general_sensors`
  (30 bits, hex), `outN outS outE outW` (decimal codes with names `Stop Forward Left Right Go`) from
  `controller.last_inputs` and `last_outputs`.
- `Rec` toggles recording (`start_recording()` on every controller; on in EDIT arms it for the start). `Export VCD`
  (PAUSE or DONE) writes `<data>/Lv{N}/recordings/intersection_{i}.vcd` with `wyrd.bifrost.vcd.write_vcd` and shows
  the paths. `Waveform` opens the exported file with the same launcher W3 uses for its Open in GTKWave button
  (Question 15); if that is unavailable the status line shows the path.
- Speed and single step never change what the Verilog sees: tick `k` always gets the same inputs and returns the
  same outputs (tests in Task 6, 10 and 12).

## 10. Files the player owns

`<data>` is `$MIDGARD_HOME`, else `$XDG_DATA_HOME/midgard`, else `~/.local/share/midgard` (`--data-dir` wins). On
first load of level `N` the game creates `<data>/Lv{N}/VerilogFiles/Traffic_signal_set_{i}.v` from `starter.v`
for each missing `i`, and reads `Lv{N}/sensorFile.txt` and `Lv{N}/high_score.txt` when present (formats of the
original: seven lines `k x y`; ten lines `cars time`, the time column in ticks here). Writes: the sensor file after each placement or removal;
the high-score file after a level. A write error shows a status message and the game continues.

## 11. Assets and licence

Copied from `verilogTown-master.zip` by `tools/import_midgard_assets.py` (reads the zip with `zipfile`, writes
into `wyrd/midgard/assets`, and writes `MANIFEST.sha256`; the tool holds the include rule). Source paths in the zip:
images from `VERILOG_TOWN/verilogTown-android/assets/{data,ASSET_RESOURCES}/`; levels from `Levels/LvN/map/`.

| Group | Files | Bytes |
|---|---|---|
| `assets/data/` (cars, lights, sensors, digits, bar, overlays) | 55 | 1,342,253 |
| `assets/ASSET_RESOURCES/` (menu, buttons, labels, titles) | 82 | 2,628,922 |
| `assets/levels/LvN/lvNN.png` (13 maps) | 13 | 5,414,307 |
| `assets/levels/LvN/lvNN.xml` | 13 | 322,333 |
| `assets/editors/vedit/` (Verilog editor: save, verify, undo, redo, search, simulate, reset, `animationImage`, and `go_`, `left_`, `right_`, `forward_`, `stop_` times `n s e w`) | 28 | 52,822 |
| `assets/editors/ledit/` (level editor: the 17 tile images) | 17 | 211,001 |
| Total copied from the zip | 208 | 9,971,638 (about 9.5 MiB) |

Not from the zip: `assets/fonts/Creepster-Regular.ttf` and `OFL.txt` (below), the authored `starter.v`,
`examples/constant_outputs.v`, `templates/combinational.v`, `templates/sequential.v`, and the test fixture
`tests/data/midgard/first_map.xml` (`samples/first_map.xml`, 44,671 bytes).

Plus the authored files `starter.v`, `examples/constant_outputs.v`, `templates/*.v`, `NOTICE`, `MANIFEST.sha256` (a few KB) and the font (Creepster, about 50 KB). Excluded from
the zip's 225 PNG files: the level editor and Verilog editor icons (47), the Android launcher icons (3), the
development art in `asset_development/` (14 files, also JPEG and PSD), `level13_*` buttons, `car_sheet1.png`,
`testCar.png`, `libgdx.png`, `verilogTown.png`, `localHighScore.png`, and the `score_levelN_normal/mouse_on`
images (only the `_pressed` set is used). `CHILLER.TTF` is not copied (decision 14).

**Font.** The Java uses Chiller only on the credits screen (FreeType, 50 and 58 px, black); elsewhere it uses the
libGDX default (Arial) and the Chiller digit images. Chosen look-alike: **Creepster** by Font Diner, SIL Open Font
License 1.1, `Copyright (c) 2011, Font Diner, Inc (diner@fontdiner.com)`, Reserved Font Name "Creepster" (the file is
vendored unmodified, so the name is kept). Source: https://github.com/google/fonts/tree/main/ofl/creepster
(`Creepster-Regular.ttf`, `OFL.txt`; the directory and the licence text were fetched on 2026-10-21). Honest note:
Chiller is a condensed, spiky horror face; Creepster is a dripping horror display face and is the closest freely
licensed font known to the author, not an exact match (Question 13). It is vendored to `wyrd/midgard/assets/fonts/`
with `OFL.txt` and listed in `NOTICE`; `Assets.credits_font(size)` loads it with `pygame.font.Font(path, size)`;
all other text (clock strip, errors, status) is the pygame default font, because it is not original artwork and
must stay readable.

The package data glob is `midgard/assets/**/*`. `wyrd/midgard/assets/NOTICE` and the root `NOTICE` gain this text:
`wyrd midgard: the game design, level files and images come from verilogTown
(http://drpeterjamieson.com/verilogTown/, the address in the zip's README.md; MIT License, Copyright (c) 2014
Peter Jamieson, Naoki Mizuno, and Boyu Zhang; artwork credited to John-Rhys Garcia in the original credits). The
Python code is new. Citation: verilogTown, Jamieson, Grace, Mizuno, Zhang, ASEE 2017.` followed by the full MIT
licence text of the original Java headers (the text between `/*` and `*/` at the top of any `.java` file).

## 12. Packaging, CI, tests

- `pyproject.toml`: `[project.optional-dependencies] midgard = ["pygame-ce>=2.5,<3", "odin3>=1.0.3"]`;
  `[project.gui-scripts] midgard = "wyrd.midgard.app:main"`; `[tool.setuptools.package-data] wyrd = ["data/*.toml",
  "midgard/assets/**/*"]`. Every pygame-ce name used in the plan was checked on 2026-10-21 against pygame-ce
  2.5.8 (SDL 2.32.10) with `SDL_VIDEODRIVER=dummy`; `pygame-ce` ships `py.typed`, and `mypy --strict` accepted a probe
  using `set_mode`, `image.load().convert_alpha`, `transform.rotate`, `font.Font(None, n).render`, `event.get`.
  Midgard III calls `pygame.display.init()` and `pygame.font.init()` (not `pygame.init()`, so no audio device is
  opened).
- GUI: `MainWindow` gains the `Tools` > `Midgard III (Verilog Town)` action: `QProcess.startDetached(sys.executable,
  ["-m", "wyrd.midgard"])`; disabled with the tooltip `needs: pip install "wyrd[midgard]"` when
  `importlib.util.find_spec("pygame")` is `None`.
- CI: the `test` job runs all Qt-free and pygame-free tests (the UI tests skip without pygame); the new job
  `midgard` (3.12) runs `pip install . "pygame-ce>=2.5,<3"` and the UI tests with `SDL_VIDEODRIVER=dummy
  SDL_AUDIODRIVER=dummy`; the `lint` job also installs `pygame-ce>=2.5,<3`. (The extra `midgard` also needs
  `odin3>=1.0.3`, which has no release yet (odin3 is not on PyPI; CI installs the GitHub release wheel URL), so CI installs pygame-ce directly; W3 has the same arrangement.)
- Tests (`tests/test_midgard_*.py`): `grid`, `levelxml` (all 13 levels), `townmap`, `traffic_sensors`, `car_logic`,
  `level` (scripted controllers), `clock` (determinism), `camera`, `controllers` (fake Bifrost III backend), `scores`, `userdata_watch`, `assets`
  (manifest), `vedit`, `leveldoc` (round trips), `ui` (dummy driver: every level loads and draws; a click-through; a scripted level run), and
  `tests/test_midgard_odin3.py` (real Odin III through Bifrost III; skips without it). The oracle for the whole-level
  tests: `ScriptedController` implementing the logic of the starter (the original stub) (all STOP when any internal tile is
  occupied; else the first of N (bit 6), S (bit 4), E (bit 5), W (bit 7) that has a waiting car gets GO and the
  others STOP; all GO when nothing waits).

## 13. Deviations from the original (all intentional; each belongs to a numbered item of the principle in Section 2)

1 No telemetry, no online leaderboard (the web page's leaderboard was a server; the local high-score screen is kept).
2 Odin III replaces the Java Verilog interpreter (7.3); `debug_port` header fix in the starter and the combinational
template; Odin III accepts more Verilog than the Java subset. 3 Creepster instead of Chiller (Section 11).
4 No Android or HTML launchers. 5 Game time (5.9): ticks, fixed-step, speeds, step, clock strip, scores and
high-score files in ticks (the original stored seconds). 6 The window keeps the aspect ratio instead of stretching
to 600 by 600; the 120-pixel clock strip. 7 No turn arcs, no sliding help or finish overlay; the finish overlay is
merged into the score screen. 8 Defect fixes: the high-score insert without the duplicate quirk; sensor stacking
refused; output codes 5 to 7 decode as STOP; unreachable destinations with no end tile fail the car instead of
crashing; the BFS marks `start` visited; start delay below 1 rejected. 9 Settings in a user data directory; keys are
events, not polled (a held key no longer toggles every frame); no `Esc` key; an external editor as an extra;
one general-sensors field in the Verilog editor (Question 12). Replicated on purpose (checked in the Java): no
sound at all (no audio call or file in any module), the menu, level select, high scores, credits, key set,
mouse behaviour, signal and car images, zoom and pan, the Verilog editor and level editor.

## 14. Not in W4

Android or web; the server and any network; the Java Verilog interpreter and its limits; new levels (a 14th level);
a Verilog tutorial text beyond the editor templates and the Tutorial level; gamepad input; sound (the original has
none); turn arcs and slide animations (Question 9); changing the mechanics beyond Section 13.

## 15. The first run

First run with no `wyrd[sim]`: the menu works and levels load; pressing `S` shows the `SimUnavailable` line and
the level stays in EDIT. With `wyrd[sim]` and the starter files every level starts and the starter (a working
combinational controller, Section 3) lets cars through without crashes; the player improves the files in the editor
window or copies `examples/constant_outputs.v` to see cars queue. `S` starts at 1x; `.` single-steps.

## 16. Review of facts the port rests on

Read from the Java: `LevelLogic.java` (update order), `Car.java` (movement, crash box, direction rules),
`VerilogTownMap.java` (`findPath`, `get_turn`), `TrafficControl.java` (sensor bit order, entries),
`LevelXMLParser.java` (links, intersection order, entries), `LevelScreen.java` (sensors, keys, 7 sensors,
ending counters, compile and reset), `ScoreScreen.java` (high scores), `MainMenu.java`, `LocalHighScoreScreen.java`,
`CreditsScreen.java`, `GeneralSensor.java`, `Main.java` (window config), `VerilogEditor.java` and `AnimationPanel.java`, `LevelEditor` (`MapEditor`, `MapGrid`, `CarEditor`), `verilogTownServer`, `LocalServer.java`, `SimVisitor.java` and `Parse.java` (what `sim_cycle` does with `rst`,
the two passes, the output ports), `VERILOG_SUPPORTED.txt`. Web pages read 2026-10-21: game.html, download.html, combinational_template.html, sequential_template.html
(`verilog.html` returned 404). Not verified against a running original (no Java
runtime was used): the numbers of cars that pass on each level. The plan therefore tests invariants, not scores.

## 17. Questions for Peter, with recommendations (1 to 5 accepted by Peter, 2026-10-21; 6 to 15 open)

1. (Superseded by decision 10 and 5.9.) Tick rate 30 default is replaced by 60 ticks per second at 1x.
2. The Tutorial (level 0) is a menu button (decision 18). Recommend: keep. Note: game.html calls "Level 1" the tutorial;
   the Java and the menu have a separate Tutorial button for Lv0.
3. The artwork carries no separate licence in the zip (only the README's MIT statement and the credit to
   John-Rhys Garcia). Recommend: Peter, as an author, confirms the images are MIT; the NOTICE already credits the artist.
4. The starter file deviates from the original by the `debug_port` header fix. Recommend: keep; the original files do
   not compile under Odin III.
5. The `midgard` CI job installs pygame-ce directly until Odin III 1.0.3 has a GitHub release wheel. Recommend: switch to
   `pip install ".[midgard]"` then.
6. Levels: the zip has 13 maps (Lv0 to Lv12), the Java `level_num = 12` (menu buttons 1 to 12 plus Tutorial for Lv0),
   and `level13_normal/mouse_on/pressed.png` button images with no level 13 map or XML. Recommend: ship 13 levels, no
   level 13 (nothing to port); Peter may author one with the level editor later.
7. The level editor: the original repo ships it (`VERILOG_TOWN/LevelEditor`, a developer tool, not in the player
   download list of download.html). Recommend: port it as scoped (Peter's change, decision 20).
8. Base speed: code says about 60 ticks per second (decision 10); the web pages and Java comments say 25 Hz (the
   sequential template then flips lights every 2.56 s; at 60 it is every 1.07 s). Recommend: keep 60 as the 1x
   speed (what players saw), and keep `TICKS_PER_SECOND` as one constant; the 4x button and a possible 0.4x
   (not planned) cover the other. Peter may set 25.
9. Turn arcs (`init_animate_turn`, `init_animate_uturn`) and the sliding help and finish overlays are not in W4.
   Recommend: a follow-up PR W4.1 "visual fidelity" (about 500 lines plus tests), after W4 merges.
10. The web page lists keys `X` (pause), `Q` and `A` (zoom) that the Java does not have (`P`, `-` and `=`). Both sets
    are accepted; the help overlay (an original image) shows the Java set.
11. The Verilog editor in PySide6 instead of pygame (decision 19). Recommend: PySide6; the extra `wyrd[midgard]`
    pulls the same PySide6 pin as `wyrd[gui]`; without it the external-editor path remains.
12. General sensors input: the Java had six 5-bit fields; the port has one 30-bit field. Recommend: keep one field.
13. Font: Creepster (OFL) is an approximation of Chiller (Section 11). Recommend: accept; swap by replacing one file.
14. `verilog.html` (Understanding Verilog) returned 404; the README's link may have moved. Recommend: ignore; the
    Tutorial level and the templates carry the explanation.
15. The `Waveform` button needs W3's GTKWave launcher function. Recommend: W3 exposes `wyrd.bifrost.open_waveform(path)`;
    until then the strip shows the VCD path.
