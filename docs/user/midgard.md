# Midgard III (Verilog Town)

Midgard III is a close replication of the game verilogTown (Jamieson, Grace, Mizuno, Zhang, ASEE
2017). You write one Verilog module per traffic light; cars drive through a town; Odin III simulates
your modules. Where a choice differs from the original, the original wins; the deviations are listed in
section 13 of `docs/specs/2026-10-21-w4-verilog-town-design.md`.

```bash
pip install -e ".[midgard]"     # pygame-ce, PySide6 and odin3 >= 1.0.3
midgard                         # or: python -m wyrd.midgard, or GUI > Tools > Midgard III
```

`midgard` options:

| Option | Meaning |
|---|---|
| `--level N` | open level N (0 to 12) directly |
| `--data-dir DIR` | where your files live (see below) |
| `--speed {1,2,4}` | starting speed |
| `--size WxH` | window size, for example `960x1100` |
| `--no-editor` | do not open an editor on a click (the status line shows the file path) |
| `--frames N` | run N frames and exit (for tests) |

The menu offers levels 1 to 12, the Tutorial (level 0), High Score and Credits.

## Time

**1 game tick = 1 rising clock edge of your module.** At 1x the game runs 60 ticks per second; 2x and
4x only change wall time. The Verilog sees the same inputs at every tick whatever the speed. Scores are
counted in ticks, also shown as `MM:SS` at 60 ticks per second.

## Playing a level

A level starts in the **edit phase**. Look at the map, place sensors, edit the Verilog files of the
intersections, then press `S`.

| Key | Action |
|---|---|
| `S` | start (compiles first) or resume from pause |
| `P` or `X` | pause |
| `.` | single step (works in pause) |
| `1` `2` `4` | speed |
| `H` | help (only when stopped) |
| `R` | restart: reload the Verilog files and the sensors |
| `M` | back to the menu (before the start) |
| `C` | clear all sensors (edit phase) |
| `V` | record the signals; `E` export the VCD |
| `Q` / `A` or `=` / `-` | zoom; arrow keys pan; the mouse wheel zooms |

Under the map a clock strip shows the tick counter, the time, the speed and buttons (Pause/Resume,
Step, 1x, 2x, 4x, Rec, Export VCD, Waveform). In pause it lists, per intersection, the inputs of the
last tick (`sensor_light` in binary, `general_sensors` in hex) and the four outputs. Export VCD writes
`Lv<N>/recordings/intersection_<i>.vcd` in your data directory.

A level ends when every car is done. The score is the number of cars that got through and the time
in ticks; the ten best results per level are kept.

## Your files

The data directory is `$MIDGARD_HOME`, else `$XDG_DATA_HOME/midgard`, else `~/.local/share/midgard`
(`--data-dir` wins). On first use of level `N` the game creates there:

```text
Lv<N>/VerilogFiles/Traffic_signal_set_<i>.v   one per intersection, copied from the starter file
Lv<N>/sensorFile.txt                          seven lines "k x y"; "k 0 0" means sensor k is not placed
Lv<N>/high_score.txt                          ten lines "cars ticks"
```

## The Verilog module

Each file holds one module, `light1`. The game steps it through Bifrost III; a file that does not
compile, or lacks a port, keeps the level in the edit phase and shows the error with `file:line`.

| Port | Direction | Width | Meaning |
|---|---|---|---|
| `clk` | input | 1 | clock, stepped by the game |
| `rst` | input | 1 | active low: 0 during start-up, 1 while playing |
| `sensor_light` | input | 8 | the sensors of this intersection |
| `general_sensors` | input | 30 | the sensors you placed on the map |
| `outN` `outS` `outE` `outW` | output | 3 | signal for cars heading N, S, E, W |
| `debug_port` | output | 30 | optional; shown in the inspector |

Output codes: `0` Stop, `1` Forward only, `2` Left only, `3` Right only, `4` Go. Codes 5 to 7 act as
Stop.

`sensor_light` has one bit per place around the intersection, set when a car is there:

| bit | 7 | 6 | 5 | 4 | 3 | 2 | 1 | 0 |
|---|---|---|---|---|---|---|---|---|
| place | entry W | entry N | entry E | entry S | inside LR | inside LL | inside UR | inside UL |

Bit 6 means a car waits on the entry where north-bound cars come from.

`general_sensors` is the word of the seven sensors you place. Sensor `k` (0 to 6) occupies bits
`4k+3 .. 4k`; bits 29 and 28 are 0. A sensor reads `0000` when no car is on its tile; otherwise bit
`4k+3` is 1 and the three low bits are the low three bits of the ending counter of the car's
destination. The word is the same for every intersection of the level.

## Placing sensors

You have seven sensors, numbered 0 to 6. The unplaced ones wait in a pile on the bottom-left tile of
the map; the picture shows the highest-numbered one left, or an empty marker when none is left.
Placing works only before the start.

1. Click the pile: the highest-numbered unplaced sensor follows the mouse.
2. Click a road tile to place it. A tile is valid when it is a road, is not an entry or inside tile of an
   intersection and holds no sensor. The sensor file is saved at once. A bad tile keeps the sensor in your hand.
3. Click a placed sensor to pick it up and move it. Right-click cancels a pick, or removes the sensor under
   the mouse. `C` removes all.

The sensors are shown on the map during the run, and the pause strip shows the word the Verilog
receives.

## The Verilog editor

A click on an intersection (edit phase, no sensor in hand) opens the **Verilog editor window** for its
file (PySide6). It has a toolbar: Save, Verify (compile with Odin III), Undo, Redo, Search and replace,
Simulate and Reset. The two fields *Internal Sensors* (8 bits) and *General Sensors* (30 bits) feed
**Simulate**, which steps the module one clock cycle and prints the four outputs and the debug
vector in the *Error log*. The picture of the intersection has eight check boxes for `sensor_light` and shows the
lights after the step. The *Template* menu fills the file with a combinational or a sequential template.

If `MIDGARD_EDITOR` is set (a command, split like a shell line, plus the file path) the game opens that
editor instead of the window. With `--no-editor` it opens neither. The game watches the files: a save in the edit
phase recompiles; during a run it shows `File changed: press R to restart with the new code`.

## The level editor

```bash
midgard-editor [LEVEL.xml]
```

Without an argument a dialog asks you to create a level (map sizes must be even) or update one. The
editor shows the map as a grid; you set the tile types, edit the cars (**Edit Cars**) and **Export**
the level. `Create` writes `Lv<N>/map/lv<NN>.xml` under `<data>/levels/` and the map image; **Export As...**
picks another file, and the done message shows the paths. It is also in the GUI as Tools > Midgard III
Level Editor.

## Credit

The game, levels and artwork come from verilogTown (MIT licence), see `NOTICE` and
`docs/CITATIONS.md` in the repository. The font is Creepster (Font Diner, SIL OFL 1.1).
