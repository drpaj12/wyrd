# Getting started

## Requirements

- Python 3.11 or later. The runner (`wyrd`) uses only the standard library.
- Odin III 1.0 or later with `odin3` and `odin3-flow` on `PATH` (or named in the machine settings).
- A VTR checkout for the `vtr` flow: the `vpr` binary and the architecture files
  (`vtr_flow/arch/timing/<arch>.xml`). Its location is the `vtr_root` machine setting, taken from
  `$VTR_ROOT` when you create the settings file.
- On Linux and WSL, `systemd-run --user` if you keep the default `launcher = "systemd"` (memory
  caps). Without it set `launcher = "plain"`.

## Install

From a clone of the repository, in a virtual environment:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .                 # the runner and `wyrd`
.venv/bin/pip install -e ".[gui]"          # adds PySide6 for `wyrd-gui`
.venv/bin/pip install -e ".[sim]"          # adds odin3 >= 1.0.3 for simulation (Bifrost III)
.venv/bin/pip install -e ".[midgard]"      # pygame-ce, PySide6 and odin3 for Midgard III
```

`odin3` is not on PyPI: install its release wheel, or point `PYTHONPATH` at `odin3/plugins/python`
and `ODIN3_LIB` at `libodin3.so` of an Odin III build. On WSL the GUI windows appear through WSLg.

The entry points are `wyrd` (command line), `wyrd-gui`, `midgard` and `midgard-editor`.

## Machine settings

Tool locations and resource limits belong to the machine, not to a project. The file is
`~/.config/wyrd/machine.toml`, or the path in `$WYRD_CONFIG`.

```bash
wyrd config init     # write the file with values detected on this machine
wyrd config show     # print every effective setting and where it came from
```

`wyrd config init` refuses to overwrite an existing file (exit code 2). `wyrd config show` prints one
line per setting, for example `jobs = 6  (machine)`; the word in brackets is `default`, `machine`,
`project` or `cli`.

The file has three tables. Every key is optional; an unknown key or table is an error.

| Table | Key | Default | Meaning |
|---|---|---|---|
| `[tools]` | `odin3` | `"odin3"` | the Odin III binary |
| | `odin3_flow` | `"odin3-flow"` | the flow script |
| | `vtr_root` | `$VTR_ROOT` | the VTR checkout (`vpr` and the architecture files) |
| | `vpr_gui` | unset | a VPR built with graphics, used only by the GUI Floorplan button (see below); must be an executable file |
| `[resources]` | `mem_budget` | `"60%"` | memory all running steps may use together; a size or a percentage of RAM |
| | `jobs` | CPUs / 2 | runs in parallel (at least 1) |
| | `launcher` | `"systemd"` | `"systemd"` caps each step with `systemd-run --user --scope -p MemoryMax=`; anything else runs steps plainly |
| | `disk_min_free` | `"20G"` | least free space on `disk_check_path` before a run starts (an absolute size) |
| | `disk_check_path` | `"/mnt/c"` on WSL, else `"/"` | where free space is checked |
| `[defaults]` | `vpr_mem` | `"4G"` | memory estimate of a VPR step with no history |
| | `other_mem` | `"2G"` | memory estimate of any other step with no history |
| | `history_factor` | `1.25` | estimate = highest peak seen for the design, arch and step times this (at least 1.0) |
| | `oom_retry_factor` | `2.0` | a step killed for memory is retried once with this times the cap (at least 1.0) |
| | `step_timeout` | `3600` | seconds before a step is stopped |

Sizes are `4G`, `512M`, `60%` and so on (binary units). Further `[tools]` entries name extra
tools by key. A project may override only `step_timeout` (in its `[run]` table); the command-line
flags `--jobs` and `--mem-budget` override the machine file for one run.

The GUI edits the same file in Project > Settings.

## Floorplan viewer (VPR graphics)

The GUI Floorplan button runs VPR with `--disp on`. The VPR in a normal VTR build is compiled
without graphics (`-DNO_GRAPHICS`), so the viewer exits at once. To use the button, build a second
VPR with graphics (Qt6) and tell Wyrd III where it is. Batch runs and goldens keep using the
reference VPR from `vtr_root`; only the viewer uses the graphics one.

These steps were verified on Ubuntu 24.04 under WSL2 (VTR 9.0.0-dev).

1. Get Qt 6.9.3 or newer. VTR refuses an older Qt, and Ubuntu 24.04 ships Qt 6.4.2, so the
   `qt6-*-dev` packages are not enough there. Install a private Qt with aqtinstall (no sudo; about
   1.7 GB). `<qt>` is any directory you choose:

   ```bash
   python3 -m venv <qt>/aqt-venv
   <qt>/aqt-venv/bin/pip install aqtinstall==3.3.0
   <qt>/aqt-venv/bin/aqt install-qt linux desktop 6.9.3 linux_gcc_64 --outputdir <qt> --modules qtshadertools
   ```

   VTR's own `dev/ensure_qt6_sdk.sh` does the same, but it writes into the VTR source tree.

2. Configure and build only VPR, out of tree, from the same VTR source. `<dir>` is any build
   directory you choose:

   ```bash
   cmake -S $VTR_ROOT -B <dir> -DCMAKE_BUILD_TYPE=Release -DVPR_USE_EZGL=on -DCMAKE_PREFIX_PATH=<qt>/6.9.3/gcc_64
   cmake --build <dir> --target vpr -j6
   ```

   The binary is `<dir>/vpr/vpr`; it finds the Qt libraries through its run path.

3. Check that graphics are in. This prints `0` when `NO_GRAPHICS` is not defined:

   ```bash
   grep -c NO_GRAPHICS <dir>/vpr/CMakeFiles/vpr.dir/flags.make
   ```

4. Set the binary in `~/.config/wyrd/machine.toml` (or Project > Settings, `tools.vpr_gui`):

   ```toml
   [tools]
   vpr_gui = "<dir>/vpr/vpr"
   ```

   `wyrd config show` then lists `vpr_gui`. A path that is not an executable file is an error.

On WSL, WSLg shows the VPR window; no X server is needed on Windows 11. If `vpr_gui` is unset the
button uses the VPR named in the run's `vpr_stdout.log`.

Under WSLg, VPR prints warnings such as `libEGL warning: failed to get driver name for fd -1` and
`MESA: error: ZINK: failed to choose pdev`. They mean no GPU driver is visible, so drawing falls back
to software; the window works. Each click of Floorplan opens another VPR window.
