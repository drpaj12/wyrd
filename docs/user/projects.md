# Projects

A project is a directory with a `wyrd.toml`. Everything Wyrd writes (`runs/`, `wyrd.db`) goes into
the same directory, so a project is self-contained and can be copied or compared as a unit.

## Create one from scratch

```bash
mkdir mydesign && cd mydesign
mkdir src                         # put your .v files here
wyrd init                         # writes a commented wyrd.toml in the current directory
```

`wyrd init [DIR]` writes the template into `DIR/wyrd.toml` (`DIR` defaults to `.`) and refuses to
overwrite an existing file (exit code 2). The template has a placeholder design, `files =
["CHANGE_ME.v"]`; edit it before running. The GUI does the same with File > New Project.

A complete project:

```toml
[project]
name = "counteradd"

[[design]]
name = "counteradd"
files = ["src/*.v"]
top = "top"

[recipe.vtr]
steps = [{ use = "odin3-flow", target = "vtr", vpr = true }]

[sweep]
recipe = ["vtr"]
design = ["counteradd"]
arch = ["k6_frac_N10_frac_chain_mem32K_40nm", "EArch"]

[run]
step_timeout = 3600
```

## `[project]`

`name` is required and must be a string. It is the project name shown in the GUI title.

## `[[design]]`

One table per design.

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | the design's name; unique in the project |
| `files` | yes | a list of file names or glob patterns |
| `top` | no | the top module; passed as `--top` |

`files` entries are relative to the directory of `wyrd.toml`. Patterns use `glob` with `**`
recursion; `$VAR` and `${VAR}` are expanded from the environment (an unset variable is an error).
A pattern that matches nothing is an error. The matched files are made absolute, sorted and
de-duplicated. Without `top`, Odin III finds the top itself (the one module nothing instantiates).

## `[recipe.NAME]`

A recipe is an ordered list of steps; a failing step skips the rest of that run's steps.

```toml
[recipe.vtr]
steps = [{ use = "odin3-flow", target = "vtr", vpr = true }]
```

`use` names the step type:

| `use` | What it runs | Arguments |
|---|---|---|
| `odin3-flow` | the `odin3-flow` script: Odin III, then ABC mapping, then VPR | `target` (default `"vtr"`), `vpr` (`true`, the default, or `false`) |
| `odin3` | the `odin3` binary | `argv`: the command words |
| `vpr` | the `vpr` binary of `vtr_root` | `argv` |
| `abc` | the `abc` binary of `vtr_root` | `argv` |
| `shell` | any command | `argv` |

For `odin3`, `vpr`, `abc` the first word of `argv` is replaced by the tool's path from the machine
settings. Inside `argv` these placeholders are expanded: `{files}` (as a whole word: the design's
files), `{top}`, `{arch_xml}`, `{step_dir}` and `{vtr_root}`. A command step reports metrics by writing a
JSON object of numbers to `metrics.json` in its step directory. `odin3-flow` reports the keys of its
`summary.json` (see {doc}`running`). A step type from a Python plugin registered under the
entry-point group `wyrd.steps` can also be named in `use`.

## `[sweep]`

Every combination of the lists becomes one run.

| Key | Meaning |
|---|---|
| `recipe` | recipe names (required, a non-empty list) |
| `design` | design names (required) |
| `arch` | architecture names (required); an architecture `X` is the file `$VTR_ROOT/vtr_flow/arch/timing/X.xml` |
| any other key | a list of values; one more axis. The values are stored with the run, are part of its key and become columns of `wyrd table` |

The sample project sweeps 3 designs over 2 architectures, which is 6 runs.

## `[run]`

Experiment settings only. The one key allowed is `step_timeout` (seconds). Machine settings such as
`jobs` or `vtr_root` belong in `machine.toml` and are refused here.

## Errors

A problem in `wyrd.toml` is printed as `<path>:<line>: <message>` and exits with code 2, for
example `design 'x': files pattern 'src/*.v' matches no files`. The GUI's `wyrd.toml` tab validates the
same way while you type.
