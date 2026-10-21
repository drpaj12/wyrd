# W4: Midgard III (Verilog Town) in pygame-ce (design)

Status: decisions 1 to 8 approved by Peter, 2026-10-21 (the names Midgard III, Bifrost III and Yggdrasil too); the rest is
the author's resolution of everything those decisions left open (Section 17 lists what Peter may still change).
Plan: `docs/plans/2026-10-21-w4-verilog-town-plan.md`. Designed together with W3
(`docs/specs/2026-10-21-w3-sim-design.md`): the game's sensors and lights are the session's inputs and outputs.
Midgard III belongs to the Yggdrasil software suite (Odin III, Wyrd III, Loki III, Midgard III).

## 1. Goal

Port the game verilogTown (Jamieson, Grace, Mizuno, Zhang, ASEE 2017; MIT) to Python and pygame-ce as
**Midgard III (Verilog Town)**: a city of cars and intersections where the player writes a Verilog module per
traffic light and the lights are driven by Odin III's simulator through Bifrost III (`wyrd.bifrost`, W3). Levels 1
to 12 (and the tutorial, level 0), cars, lights, sensors, scoring, high scores, level select. The mechanics are
ported from the Java source method by method (Section 5), so a level plays as it did in the original.

Not in W4: a level editor, Android, HTML/GWT, the telemetry server, the Java Verilog editor and simulator
(Section 14).

## 2. Decisions

Approved by Peter (2026-10-21), encoded verbatim:

| # | Decision | Choice |
|---|---|---|
| 1 | Name | The game is **Midgard III** (also called Verilog Town). Command `midgard`, extra `wyrd[midgard]`, package `wyrd.midgard`, GUI menu "Midgard III (Verilog Town)", window title "Midgard III". The original verilogTown is credited everywhere (Jamieson, Grace, Mizuno, Zhang, ASEE 2017, MIT) |
| 2 | Packaging | Extra `wyrd[midgard]` (pygame-ce), command `midgard`, and a menu entry in the W2 GUI |
| 3 | Content | Levels 1 to 12, cars, lights, sensors, scoring, high scores, level select; no level editor, no Android/HTML |
| 4 | Clocking | One Bifrost III step per game tick |
| 5 | Player Verilog | Compiled at level start; errors shown in the game with `file:line` |
| 6 | Editing | External editor, a file watch, and reload |
| 7 | Assets | The original images and level files are reused, copied into `wyrd/midgard/assets` with the MIT notice; sizes are listed in Section 11 |
| 8 | Tests | Headless with the SDL dummy video driver: every level loads, and a scripted controller drives a level |

Decided here (author), each with its reason:

| # | Decision | Reason |
|---|---|---|
| 9 | Engine and drawing are separate: `wyrd/midgard/model/` imports neither pygame nor Qt nor odin3; `wyrd/midgard/ui/` is the only pygame user (plus `app.py`) | Tests of the mechanics need no display |
| 10 | Tick rate: default 30 ticks per second, option `--tps N` (5 to 240), keys `[` and `]` halve and double the speed. Score time counts nominal seconds: `ticks // 25` | The Java loop ran one tick per rendered frame (its `Frame_Time_25 = 1 / 25` is integer division, 0), so the real rate was the frame rate; its comments say 25 per second. Nominal time keeps scores independent of speed |
| 11 | Per-user files (the player's Verilog, `sensorFile.txt`, `high_score.txt`) live in a user data directory (Section 10), copied from the package on first use; package assets are read-only | A wheel install cannot be written to |
| 12 | The shipped starter Verilog is the original stub with one fix: `debug_port` is added to the header port list | Odin III rejects the original (Section 7.3) |
| 13 | No telemetry: the original `LocalServer`, `userID.txt` and `server.conf` network code is not ported; the game opens no socket | The original sent results and usage to a remote host |
| 14 | The Chiller font (`CHILLER.TTF`) is not copied; numbers use the original digit images, other text uses pygame's bundled default font | Chiller is a commercial Microsoft font, not part of the MIT grant |
| 15 | Zoom and pan are dropped; the window scales the whole level to fit (Section 9.1) | The 1280 by 1380 logical level does not fit most screens; scaling replaces zoom |
| 16 | Turn arcs are not ported (the Java draws cars along arcs through corners; its game logic uses straight-line positions) | Visual only; the logic is ported exactly. Recorded as a deviation (Section 13) |
| 17 | The finish overlay and the score screen are one screen | The original drew the same numbers twice |
| 18 | The Tutorial (level 0, a button in the original menu) is included | Same engine, 1 intersection |

## 3. What the original is (read from the source, 2026-10-21)

Source: `verilogTown-master.zip` (MIT, `README.md`: "This project adopts MIT licensee"; each Java file carries the
MIT header, Copyright (c) 2014 Peter Jamieson, Naoki Mizuno, and Boyu Zhang; the zip has no separate LICENSE
file). About 27,000 lines of Java in these parts:

| Part (zip path under `VERILOG_TOWN/`) | Content | In W4 |
|---|---|---|
| `verilogTown` (libGDX game, 23 classes) | The game | Ported (Section 4) |
| `verilogTown-desktop` | `Main`: LwjglApplication, 600 by 600 window | `app.main` |
| `VerilogSimulator` (~11,000 lines with the ANTLR 4 generated `Verilog2001` parser, twice) | The game's own Verilog subset interpreter (`Parse`, `SimVisitor`, ...) | Replaced by Odin III through Bifrost III |
| `VerilogEditor` (Swing) | The in-house editor with a compile button | Replaced by an external editor (Section 8) |
| `LevelEditor` (Swing) | Level authoring | Not ported |
| `verilogTownServer`, `LocalServer` | Result and usage telemetry | Not ported |
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

All 54 shipped `Traffic_signal_set_I.v` files are byte-identical stubs except `Lv1/Traffic_lights_set_0.v` (a
working controller; used by W4 as the example and as the test oracle, Section 12). The main menu offers levels 1
to 12, Tutorial (level 0), High Score and Credits.

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
it appears. `TILE = 64`, `SPEED = 4` pixels per tick (so 16 ticks per tile), nominal ticks per second `25`.

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
seconds = ticks // 25            # ticks = number of ticks run in the RUN phase
```

`passed + failed == len(cars)` when the level is done and `success_raw >= forced_cars`. (The Java clamps
`passed` at 0 only in the score bar. A forced car that then crashes is counted in `failed` twice and its
success is missing from `passed`; ported as is.) There is no pass or fail verdict: the level ends when every
car is done; the score is `passed` cars and the time.

### 5.8 High scores

`high_score.txt`: ten lines `cars time`. A result `(passed, seconds)` is inserted when `passed >= 1`: the table is
sorted by cars descending then time ascending; the result goes before the first entry that it beats (more cars,
or the same cars and less time); an equal pair is not inserted; the table keeps ten entries; empty slots are
`0 0`. (The Java insert code duplicates an entry when the cars are equal and the time is less; not ported.)
A missing, short or garbled file reads as `0 0` rows. Levels 1 to 12 are shown on the high-score screen; level 0
has a file but no page.

## 6. Architecture

```
wyrd/midgard/
  __init__.py  __main__.py  app.py
  model/  grid.py levelxml.py townmap.py traffic.py sensors.py car.py logic.py level.py
          controllers.py scores.py userdata.py watch.py
  ui/     view.py assets.py draw.py menu.py levelscreen.py scorescreens.py game.py
  assets/ data/ ASSET_RESOURCES/ levels/ starter.v examples/ NOTICE MANIFEST.sha256
```

`Level` (model, no pygame) is the state machine of `LevelScreen`:

```python
class Phase(Enum): EDIT = 1; RUN = 2; PAUSE = 3; DONE = 4

@dataclass(frozen=True)
class LevelResult: passed: int; failed: int; crashed: int; forced: int; seconds: int; cars: int

class Level:
    def __init__(self, data: LevelData, sensors: SensorSet)
    phase: Phase; ticks: int; town: TownMap; cars: list[Car]; sensors: SensorSet; editor: SensorEditor
    def start(self, controllers: Sequence[LightController]) -> None   # EDIT -> RUN; resets controllers (Section 7.4)
    def toggle_pause(self) -> None                                    # RUN <-> PAUSE (ignored in EDIT, DONE)
    def tick(self) -> bool                                            # one LevelLogic.update when RUN; True when done
    def result(self) -> LevelResult
```

`LightController` (the seam between engine and Verilog):

```python
class LightController(Protocol):
    def start(self) -> None                                   # the reset sequence (7.4)
    def step(self, light_sensors: int, general_sensors: int) -> tuple[int, int, int, int]  # codes N, S, E, W
    def close(self) -> None
```

`ScriptedController(fn)` wraps a Python function (tests, the safe-controller oracle); `MidgardController` wraps a
`BifrostSession` (Section 7). `ui/game.py` `Game` owns the screen stack, the clock and the data directory.

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
declared as a port but is not in the port list`). The starter `assets/starter.v` is the original stub with the
header changed to `module light1 (clk, rst, outN, outS, outE, outW, sensor_light, general_sensors, debug_port);`
and three added comment lines (active-low reset; one step is one clock cycle; the output codes). With that
change all 54 shipped files compile and simulate under Odin III 1.0.0 (checked the same day). The example
`assets/examples/lv1_safe.v` is `Lv1/VerilogFiles/Traffic_lights_set_0.v` with the same header change.

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

## 9. The program

### 9.1 Window and drawing

`midgard [--level N] [--data-dir DIR] [--tps N] [--size WxH] [--no-editor]` (`--no-editor` never launches an
editor; tests). Entry: `midgard = "wyrd.midgard.app:main"` and `python -m wyrd.midgard`.

Each screen draws on its own logical surface: menu 1280 by 1280, level, score, high score and credits 1280 by 1380
(the map is 1280 by 1280 at logical y 100 to 1380 and the 100-pixel score bar is on top). The window is
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

`initial_window_size((1280, 1380), (1920, 1080)) == (890, 960)`; `(1280, 1380), (3840, 2160)` is `(1280, 1380)`.
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
| Level 1280x1380 | Section 9.1 | `S` start, then pause and resume; `P` pause; `H` help; `R` restart; `M` menu (EDIT only); `C` clear sensors (EDIT); `[` `]` speed; `Esc` menu in EDIT, pause in RUN; mouse: Section 5.3 and 8 |
| Score 1280x1380 | `level_finish.png` full size; level number (`chiller_num_*` 80x80 at `(578, 1088)` for one digit, `(545, 1088)` and `(595, 1088)` for two); passed three digits at x 725, 800, 875, y 660, size 75; failed y 420; time at y 895: digits at x 725, 790, colon 840, digits 895, 960; buttons 300x98: Main Menu `(150, 150)`, Try Again `(500, 150)`, Next Level `(850, 151)` (`*_normal/mouse_on/pressed.png`) | click; Next Level on level 12 goes to the menu |
| High scores 1280x1380 | title `local_high_score.png` `(260, 1130)` 750x280; labels `rank.png` `(180, 1037)`, `cars.png` `(560, 1037)`, `time.png` `(940, 1037)` 150x84; page for level L: label `score_levelL_pressed.png` at `(500, 1090)` 300x140; ten rows `j` at `y = 950 - 100 * j`: rank (2 digits) x 200, cars (3 digits) x 555, time x 905; digit size 55, gaps 53 (score) and 48 (time: offsets `0, 48, 1.77*48, 2.54*48, 3.54*48`); Back `(30, 45)` 160x59, Next `(1180, 500)` 90x300, Last `(10, 500)` 90x300 | click; the page changes at once (no slide) |
| Credits 1280x1280 | `credits.png` at `(450, 1160)` 360x110; the original text lines (names and roles) in the default font | click Back `(30, 45)` or `Esc` |

Credits text (from the Java): Dr. Peter Jamieson (game design, much programming incl. the Verilog simulation and
car movement and path planning); Naoki Mizuno (XML level descriptions, level creation tool, beta developer);
Boyu Zhang (standalone Verilog editor, game control structure, beta developer); Alex Williams (early Verilog
parser with ANTLR 4); Josh Collins (early game parts: animation and levels); Lindsay Grace (collaborator on
game design); John-Rhys Garcia (main artist for tileset and vehicles); plus the lines
`Ported to Python and pygame-ce as Midgard III (Yggdrasil), see NOTICE` and the citation
`verilogTown, Jamieson, Grace, Mizuno, Zhang, ASEE 2017`.

Frame loop (`Game.run`): `clock = pygame.time.Clock()`; each frame `dt = clock.tick(60) / 1000`; events; if the
level is RUN: `acc += dt * tps` and `while acc >= 1 and n < max_catchup: level.tick(); acc -= 1; n += 1`
(`max_catchup = 5`); draw; `pygame.display.flip()`. `Game.frame(dt, events)` is one iteration without
waiting (the tests call it). When the level becomes DONE the screen waits 1.0 s then opens the score screen,
which records the high score once (on construction).

## 10. Files the player owns

`<data>` is `$MIDGARD_HOME`, else `$XDG_DATA_HOME/midgard`, else `~/.local/share/midgard` (`--data-dir` wins). On
first load of level `N` the game creates `<data>/Lv{N}/VerilogFiles/Traffic_signal_set_{i}.v` from `starter.v`
for each missing `i`, and reads `Lv{N}/sensorFile.txt` and `Lv{N}/high_score.txt` when present (formats of the
original: seven lines `k x y`; ten lines `cars time`). Writes: the sensor file after each placement or removal;
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
| Total copied | 163 | 9,707,815 (about 9.3 MiB) |

Plus the authored files `starter.v`, `examples/lv1_safe.v`, `NOTICE`, `MANIFEST.sha256` (a few KB). Excluded from
the zip's 225 PNG files: the level editor and Verilog editor icons (47), the Android launcher icons (3), the
development art in `asset_development/` (14 files, also JPEG and PSD), `level13_*` buttons, `car_sheet1.png`,
`testCar.png`, `libgdx.png`, `verilogTown.png`, `localHighScore.png`, and the `score_levelN_normal/mouse_on`
images (only the `_pressed` set is used). `CHILLER.TTF` is not copied (decision 14).

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
  `level` (scripted controllers), `controllers` (fake Bifrost III backend), `scores`, `userdata_watch`, `assets`
  (manifest), `ui` (dummy driver: every level loads and draws; a click-through; a scripted level run), and
  `tests/test_midgard_odin3.py` (real Odin III through Bifrost III; skips without it). The oracle for the whole-level
  tests: `ScriptedController` implementing the logic of `lv1_safe.v` (all STOP when any internal tile is
  occupied; else the first of N (bit 6), S (bit 4), E (bit 5), W (bit 7) that has a waiting car gets GO and the
  others STOP; all GO when nothing waits).

## 13. Deviations from the original (all intentional)

Odin III replaces the Java Verilog interpreter (Section 7.3); `debug_port` fix; no zoom or pan; no turn arcs;
nominal time; no telemetry; no Chiller font; the finish overlay merged into the score screen; the high-score
insert without the duplicate quirk; sensor stacking refused; output codes 5 to 7 decode as STOP; unreachable
destinations with no end tile fail the car instead of crashing; the BFS marks `start` visited; start delay below
1 rejected; settings in a user data directory; an external editor instead of the Swing editor.

## 14. Not in W4

A level editor; Android or web; the server and any network; the Java Verilog editor and its animation panel;
multiplayer or sound; new levels; a Verilog tutorial text; gamepad input; changing the mechanics (turn
animation, tick rate semantics) beyond Section 13.

## 15. The first run

First run with no `wyrd[sim]`: the menu works and levels load; pressing `S` shows the `SimUnavailable` line and
the level stays in EDIT. With `wyrd[sim]` and the starter files every level starts: the starter holds constant
outputs (`outN = Left_only`, `outW = Right_only`, `outS = Go`, `outE = Stop`), so cars mostly queue and the level
does not finish; the player edits the files (or copies `examples/lv1_safe.v`). `S` with the unedited starter is
valid and runs until the player stops it.

## 16. Review of facts the port rests on

Read from the Java: `LevelLogic.java` (update order), `Car.java` (movement, crash box, direction rules),
`VerilogTownMap.java` (`findPath`, `get_turn`), `TrafficControl.java` (sensor bit order, entries),
`LevelXMLParser.java` (links, intersection order, entries), `LevelScreen.java` (sensors, keys, 7 sensors,
ending counters, compile and reset), `ScoreScreen.java` (high scores), `MainMenu.java`, `LocalHighScoreScreen.java`,
`CreditsScreen.java`, `GeneralSensor.java`, `SimVisitor.java` and `Parse.java` (what `sim_cycle` does with `rst`,
the two passes, the output ports), `VERILOG_SUPPORTED.txt`. Not verified against a running original (no Java
runtime was used): the numbers of cars that pass on each level. The plan therefore tests invariants, not scores.

## 17. Questions for Peter, with recommendations

1. Tick rate default 30 (decision 10). Recommend: keep; `[` and `]` change it in game.
2. The Tutorial (level 0) is a menu button (decision 18). Recommend: keep.
3. The artwork carries no separate licence in the zip (only the README's MIT statement and the credit to
   John-Rhys Garcia). Recommend: Peter, as an author, confirms the images are MIT; the NOTICE already credits the artist.
4. The starter file deviates from the original by the `debug_port` header fix. Recommend: keep; the original files do
   not compile under Odin III.
5. The `midgard` CI job installs pygame-ce directly until Odin III 1.0.3 has a GitHub release wheel. Recommend: switch to
   `pip install ".[midgard]"` then.
