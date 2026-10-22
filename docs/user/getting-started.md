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
