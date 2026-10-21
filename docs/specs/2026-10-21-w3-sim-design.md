# W3: simulation in Wyrd (design)

Status: decisions 1 to 6 approved by Peter, 2026-10-21; the rest is the author's resolution of what
those decisions left open (Section 15 lists what Peter may still change). Plan:
`docs/plans/2026-10-21-w3-sim-plan.md`. Designed together with W4 (`docs/specs/2026-10-21-w4-verilog-town-design.md`):
the game's sensors and lights are this session's inputs and outputs. Builds on W1
(`docs/specs/2026-10-21-w1-runner-design.md`) and W2 (`docs/specs/2026-10-21-w2-gui-design.md`), and on
Odin III's S1 simulation API (`docs/specs/2026-10-21-s1-sim-api-design.md` in the Odin III repository, shipped in
Odin III v1.2).

## 1. Goal

Two things:

1. Bifrost, the simulation bridge (`wyrd.bifrost`): a Python session layer over Odin III's per-cycle simulator. A caller opens a set of Verilog
   files, gets named inputs and outputs, sets inputs, steps clocks, reads outputs, resets, records the values
   and writes a VCD file. Compile errors come back as structured diagnostics with `file:line`.
2. A simulation panel in the W2 GUI (vector-file editor, random-input run, a small built-in waveform view, an
   "Open in GTKWave" button).

The panel and Midgard (Verilog Town, W4) are both clients of Bifrost. (Wyrd-I and Midgard belong to the Yggdrasil software suite with Odin III and Loki.) Functional simulation only (2-state, no
timing).

## 2. Decisions

Approved by Peter (2026-10-21), encoded verbatim:

| # | Decision | Choice |
|---|---|---|
| 1 | What W3 builds | Bifrost, the simulation bridge (`wyrd.bifrost`), a session over S1: named inputs and outputs, step, reset, VCD |
| 2 | Clients | The GUI sim panel (vector-file editor, random-input run, small built-in waveform view, Open in GTKWave button) and W4 are both clients of `wyrd.bifrost` |
| 3 | Fidelity | Functional simulation only |
| 4 | Exception to W1 | Sim is the one exception to W1's "public commands only" (Section 3), because per-cycle interaction cannot be done through `odin3` or `odin3-flow` as processes |
| 5 | Packaging | `wyrd.bifrost` lives behind an optional extra `wyrd[sim]` that imports the odin3 binding; Wyrd core never imports odin3 |

Decided here (author):

| # | Decision | Choice |
|---|---|---|
| 6 | Backend seam | `wyrd.bifrost` talks to a small `Backend` protocol (Section 5.3). `Odin3Backend` is the only code that imports `odin3`; tests use a fake backend, so CI needs no Odin III |
| 7 | Compile flow | Exactly `read_verilog "f1" "f2"; proc; opt; lower` (S1 section 1), run through `odin3.Design.run_script` with the log captured. The top is the one Odin III chooses (the only module no other module instantiates); `BifrostSession.from_verilog(..., top=NAME)` picks another through `Design.simulate(NAME)` |
| 8 | Clocks | `step` ticks every clock together (S1 SC-2). `BifrostSession.set` refuses a clock; the caller never toggles one |
| 9 | Names | The S1 names: `.` separates hierarchy; a bit select is `name[3]`. A name Odin III does not know raises `NoSuchSignal` with the S1 hint about `(* keep *)` |
| 10 | Values | Unsigned Python ints, bit i of the int is bit i of the signal, any width. `BifrostSession.set` checks the range before the backend call |
| 11 | VCD | Wyrd writes its own VCD from the recording (S1 decision D-6: no VCD through the ABI). Format in Section 7.2 |
| 12 | Vector files | The `odin3-sim-vectors` text format of S1 (section 5 of the S1 spec), so a file made here replays with `odin3 -p "...; sim --vectors-in F"` and the other way round. Random runs use Python's `random.Random(seed)`, not Odin III's PRNG; a saved vector file is the way to repeat a run |
| 13 | Where in the GUI | A `Simulate` tab in the centre tab widget (after `wyrd.toml`), opened from a new `Tools` menu (`Simulate`, Ctrl+T). The new `Tools` menu also holds `Midgard (Verilog Town)` (W4) |
| 14 | CLI | A small `wyrd sim` command (Section 10) so the layer is usable and testable without a GUI |

## 3. How this squares with W1 ("public commands only")

W1 decision 2: "Wyrd calls only public commands (`odin3`, `odin3-flow`, `vpr`, `abc`) and reads their files.
It never imports Odin III's Python." That rule stays true for everything W1 and W2 do: the runner, the
scheduler, the report and the flow panel never import `odin3`.

W3 is the exception, by Peter's W3/W4 decisions: a simulation that is stepped once per game tick, with a few
signals read and written per step, cannot go through a process per call. S1 exists to give that: one C call
per step and per read or write.

The exception is contained:

- `import odin3` appears in exactly one module, `wyrd/bifrost/backend.py`, inside a function (never at module
  level). A test (`test_odin3_only_in_backend`) walks every `wyrd/**/*.py` with `ast` and fails otherwise.
- `wyrd.bifrost` imports nothing from Qt or pygame, and `wyrd` imports `wyrd.bifrost` only from `wyrd/gui/`,
  `wyrd/guimodel/` (types only), `wyrd/town/` and `wyrd/cli.py` (the `sim` command, imported inside the
  command function). `import wyrd` and `wyrd run` work with no `odin3` installed.
- The dependency is declared only as the extra `sim = ["odin3>=1.2"]`. `[project] dependencies` stays `[]`.
- Without the extra, `Odin3Backend` raises `SimUnavailable` with the text
  `odin3 with the simulation API is not installed; run: pip install "wyrd[sim]" (needs Odin III 1.2 or later)`.

The plan updates `CLAUDE.md` ("Standard library only at runtime") and adds a dated note under W1 decision 2
that points here. W1's text is not rewritten.

## 4. What S1 gives (facts the design rests on)

From the S1 spec, which the plan's tests encode:

- The design must be lowered: `read_verilog design.v; proc; opt; lower` (S1 section 1). Without `lower` the
  open fails ("run `lower` first").
- Python API (S1 SP-1): `odin3.Design()`, `design.run_script(text)`, `design.simulate(top=None) -> Simulation`,
  `Simulation.signals() -> list[SignalInfo]` (`id, name, leaf, width, kind, msb, lsb, scope, obj, first_bit`; `kind`
  is `"input"`, `"clock"`, `"output"` or `"internal"`), `.signal(name) -> SignalInfo | None`, `.get(sig)`,
  `.set(sig, value)`, `sim[name]`, `.settle()`, `.step(cycles=1)`, `.reset()`, `.cycle`, `.close()`.
- One step is one cycle of every clock of the top together (SC-2): settle, rising edge, settle, falling edge,
  settle. Outputs read after the step are those after the last settle.
- `reset()` is power-on (SC-4): all values 0, cycle 0. It is not the design's reset input.
- A clock of an edge-triggered cell must be a top-level input port. A derived or gated clock is rejected at open.
- The design is frozen while a simulation is open; passes are refused (SA-11). Several simulations of one design
  may be open.
- Errors are `Odin3Error`; a missing name is `KeyError`; a value out of range is `ValueError` (SP-2, SP-3).
- Log records (`design.odin3.capture_log()`) are `(level, message)` with level 0 error, 1 warning, 2 info. A
  parse error reads, verified on 2026-10-21 with the Odin III 1.0.0 release build:
  `/tmp/x/bad.v:2:39: error: syntax: unexpected ';'`, then `pass read_verilog: failed: ODIN3_ERR_PARSE`, then
  `python: command 1: pass 'read_verilog' failed: ODIN3_ERR_PARSE`. A warning reads
  `/tmp/x/bad.v:2:13: warning: 'b' is implicitly declared`. A port declared in a body but missing from the
  header reads `Lv0/VerilogFiles/Traffic_signal_set_0.v:4:14: error: 'debug_port' is declared as a port but is
  not in the port list`.

S1 was not built when this spec was written (Odin III 1.0.0 only). The adapter is written against the S1 spec
and plan; its first run against a real S1 build is Task 8 of the plan.

## 5. The `wyrd.bifrost` API

Python 3.11, standard library only. All names are importable from `wyrd.bifrost`.

### 5.1 Types (`wyrd/bifrost/types.py`, `errors.py`)

```python
Kind = Literal["input", "clock", "output", "internal"]

@dataclass(frozen=True)
class Signal:
    name: str          # full name, "." separated
    width: int         # bits, >= 1
    kind: Kind
    msb: int = 0
    lsb: int = 0

@dataclass(frozen=True)
class Diagnostic:
    severity: Literal["error", "warning"]
    message: str       # text after the location, without "error: " / "warning: "
    file: str | None   # as Odin III printed it
    line: int | None   # 1-based
    col: int | None    # 1-based
    raw: str           # the whole log message
```

Exceptions, all subclasses of `SimError(Exception)`:

| Class | Raised when |
|---|---|
| `SimUnavailable` | `odin3` cannot be imported, or its binding has no `Simulation` (Section 3 text; an old binding says `needs Odin III 1.2 or later`) |
| `CompileError` | the compile step fails; attribute `diagnostics: tuple[Diagnostic, ...]` (errors and warnings, in log order); `str()` is the first error as `file:line:col: message`, else the first error message |
| `NoSuchSignal` | a name is not in the simulated netlist; attribute `name`; `str()` is the S1 SP-3 text `NAME: not in the simulated netlist (a pass may have removed it: mark it (* keep *) in the HDL, or see BifrostSession.signals())` |
| `SignalKindError` | `set` on a signal that is not an `input`; the text names the kind, for a clock `clock 'clk' is stepped, not set` |
| `ValueRangeError` (also `ValueError`) | `set` with a negative value or `>= 2**width` |
| `SessionClosed` (also `RuntimeError`) | any method of a closed session |
| `VectorError` | a vector file does not parse (Section 8); attributes `line: int`, `message: str`; `str()` is `LINE: message` |

### 5.2 `BifrostSession` (`wyrd/bifrost/session.py`)

```python
class BifrostSession:
    @classmethod
    def from_verilog(cls, files: Sequence[str | Path], *, top: str | None = None,
                     backend: Backend | None = None) -> BifrostSession
    @property
    def sources(self) -> tuple[Path, ...]
    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]        # warnings of the compile; errors raise
    @property
    def signals(self) -> tuple[Signal, ...]                # the listed signals (S1 SA-4)
    @property
    def inputs(self) -> tuple[Signal, ...]                 # kind "input", port order
    @property
    def clocks(self) -> tuple[Signal, ...]                 # kind "clock"
    @property
    def outputs(self) -> tuple[Signal, ...]                # kind "output", port order
    @property
    def cycle(self) -> int
    @property
    def closed(self) -> bool
    def signal(self, name: str) -> Signal                  # NoSuchSignal; cached
    def has_signal(self, name: str) -> bool
    def get(self, name: str) -> int
    def set(self, name: str, value: int) -> None           # SignalKindError, ValueRangeError, NoSuchSignal
    def get_many(self, names: Iterable[str]) -> dict[str, int]
    def set_many(self, values: Mapping[str, int]) -> None  # checks every item first, then sets all
    def step(self, cycles: int = 1) -> None                # cycles >= 0, else ValueError
    def settle(self) -> None
    def reset(self) -> None                                # power-on; the recording, if any, restarts
    def close(self) -> None                                # idempotent
    def __enter__(self) -> BifrostSession; def __exit__(...) -> None
    # recording and runs, Sections 6 and 8
    def start_recording(self, names: Sequence[str] | None = None,
                        max_samples: int = 1_000_000) -> Recording
    def stop_recording(self) -> Recording | None
    @property
    def recording(self) -> Recording | None
    @property
    def recording_full(self) -> bool
    def run_vectors(self, vectors: VectorFile, names: Sequence[str] | None = None) -> Recording
    def run_random(self, cycles: int, seed: int = 0, names: Sequence[str] | None = None) -> Recording
```

Rules:

- `from_verilog` raises `CompileError` (nothing is left open) or returns an open session. Relative paths are
  made absolute with `Path.resolve()` before the backend sees them, so diagnostics carry absolute paths. An
  empty `files` is `ValueError`; a missing file is `CompileError` with one diagnostic (`file` the path, `line`
  `None`, text `cannot read file`), found by the session before any backend call.
- `step(cycles)` with no recording is one backend call. With a recording on, it loops one cycle at a time and
  appends one sample per cycle.
- `set_many` is one validation pass followed by the sets, so a bad item leaves every value unchanged.
- `close()` closes the backend handle and the compiled design (S1 SP-4 order: the simulation first). The
  session is also closed by garbage collection through the backend objects' own `ffi.gc`.
- Performance: a step is one backend call; `get` and `set` use the name-to-`Signal` cache and one backend
  call. A few signals per step at 60 steps per second is required by W4 (S1's own target).

### 5.3 Backend protocol (`wyrd/bifrost/backend.py`)

```python
class SimHandle(Protocol):
    def signals(self) -> Sequence[Signal]
    def signal(self, name: str) -> Signal | None
    def get(self, name: str) -> int                 # KeyError for an unknown name
    def set(self, name: str, value: int) -> None    # KeyError unknown; ValueError out of range
    def settle(self) -> None
    def step(self, cycles: int) -> None
    def reset(self) -> None
    @property
    def cycle(self) -> int
    def close(self) -> None

class CompiledDesign(Protocol):
    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]
    def open(self, top: str | None) -> SimHandle
    def close(self) -> None

class Backend(Protocol):
    def compile(self, files: Sequence[Path]) -> CompiledDesign   # CompileError on failure

def default_backend() -> Backend            # Odin3Backend(); SimUnavailable at construction when odin3 is missing
def odin3_available() -> bool               # True when odin3 imports and has Simulation
```

`Odin3Backend.compile`: `design = odin3.Design()`; `script = "read_verilog " + " ".join(f'"{p}"') + "; proc;
opt; lower"`; run with `with design.odin3.capture_log() as records` around `design.run_script(script)`; on
`odin3.Odin3Error` raise `CompileError(parse_log(records))`; a path containing a double quote is a
`CompileError` (`odin3` cannot take it). `open(top)` is `design.simulate(top)`; an unknown top name (`ValueError`
from odin3) becomes `CompileError` with the message. Each odin3 `SignalInfo` becomes a `Signal`.
`Odin3Error` raised by a step or access becomes `SimError(str(e))`.

### 5.4 Diagnostics (`wyrd/bifrost/diagnostics.py`)

`parse_log(records: Iterable[tuple[int, str]]) -> tuple[Diagnostic, ...]`. A record is kept when its level is
0 or 1. Located form, `re.match` on the message:

`^(?P<file>.+?):(?P<line>\d+)(?::(?P<col>\d+))?: (?:(?P<sev>error|warning): )?(?P<msg>.*)$`

The severity is `sev` when present, else from the level. Records of level 0 or 1 that do not match are kept
with `file`, `line`, `col` `None` and `severity` from the level, except the two noise forms that only repeat a
located error: a message starting `pass ` and containing `: failed: `, and a message starting `python: command `.
Level 2 and above is dropped.

## 6. Recording (`wyrd/bifrost/record.py`)

```python
@dataclass(frozen=True)
class Recording:
    names: tuple[str, ...]
    widths: tuple[int, ...]
    cycles: tuple[int, ...]                  # the session cycle number of each sample
    samples: tuple[tuple[int, ...], ...]     # samples[i][j] is the value of names[j] at cycles[i]
    clocks: tuple[str, ...]                  # clock names of the session, for the VCD
```

`BifrostSession.start_recording(names=None)` takes sample 0 at once (the current cycle, normally 0 after open or
reset). `names=None` records every input and output, clocks excluded. Names are checked with `signal()` (so
`NoSuchSignal` surfaces early) and may include internal signals. Each `step` appends one sample after the cycle:
the values read are the inputs as currently set (the ones the cycle used) and the outputs and internals after
the last settle. `Recording` is immutable: `session.recording` and `stop_recording()` return a snapshot built
from the live sample lists at the moment of the call. When `max_samples` samples are held, recording stops by
itself (later steps are not recorded; `BifrostSession.recording_full` is `True`). `reset()` with a recording on
discards the samples and takes a new sample 0.

## 7. Waveform data and VCD

### 7.1 `wyrd/guimodel/waveform.py` (Qt-free)

```python
@dataclass(frozen=True) class Segment:  start: int; end: int; value: int    # [start, end) in sample indexes
@dataclass(frozen=True) class WaveRow:  name: str; width: int; values: tuple[int, ...]
def rows_from_recording(rec: Recording) -> list[WaveRow]
def segments(values: Sequence[int]) -> list[Segment]       # consecutive equal values merged; empty input gives []
def format_value(value: int, width: int, radix: Literal["hex", "dec", "bin"]) -> str
def parse_int_text(text: str, width: int) -> int           # "17", "0x1f", "0b101", "1_000"; ValueError out of range or bad
```

`format_value`: `bin` is `width` digits with leading zeros; `hex` is `ceil(width/4)` digits, no prefix; `dec` plain.

### 7.2 `wyrd/bifrost/vcd.py`

`write_vcd(rec: Recording, path: Path, top: str = "top") -> None` and `vcd_text(rec, top) -> str` (the writer
is a pure function; the file write is atomic: write `path.with_suffix(path.suffix + ".tmp")`, then
`os.replace`).

```
$version wyrd sim $end
$timescale 1ns $end
$scope module <top> $end
$var wire <width> <code> <leaf>[ [<width-1>:0]] $end      (range only for width > 1)
$upscope $end                                               (nested scopes for "." in names, Section below)
$enddefinitions $end
```

Hierarchical names are split at `.`: all but the last part become nested `$scope module` blocks (an explicit
stack, no recursion); the variables of a scope are declared before its child scopes, scopes in order of first
appearance. Codes: variables are numbered in recording order with the clocks first; the k-th (k from 0) has k in
base 94 with digits `!`..`~`, least significant digit first, as S1 SW-2. Names have every byte outside `!`..`~` replaced by `_`.

Times (one cycle is 10 time units, as S1 SW-3). `#0` holds `$dumpvars` with sample 0 for every variable and
each clock at 0. For sample i at session cycle c (c >= 1): `#(10c-8)` (that is 10(c-1)+2) the input values of that
sample; `#(10c-5)` each clock 1; `#(10c-5)` the output and internal values; `#(10c)` each clock 0. A time is
written only when some variable changed there; a variable is written only when its value differs from its
last written value; width 1 as `0<code>` or `1<code>`, wider as `b<bits MSB first> <code>`. Limit: values are
sampled once per step, so a combinational output is shown changing at the rising edge, not at the input change.
The test for this text uses the traffic fixture (plan Task 5).

## 8. Vector files (`wyrd/bifrost/vectors.py`)

```python
@dataclass(frozen=True)
class VectorFile:
    rows: tuple[tuple[int, ...], ...]   # rows[c][k] is the value of the k-th data port at cycle c

def session_ports(session: BifrostSession) -> tuple[tuple[Signal, ...], tuple[Signal, ...]]
    # (the input and clock signals in port order, the output signals in port order)
def parse_vectors(text: str, ports: Sequence[Signal], outputs: Sequence[Signal] = (),
                  name: str = "<vectors>") -> VectorFile
def format_vectors(vf: VectorFile, ports: Sequence[Signal], outputs: Sequence[Signal] = (), *,
                   recording: Recording | None = None, title: str = "wyrd", seed: int = 0) -> str
def random_vectors(ports: Sequence[Signal], cycles: int, seed: int) -> VectorFile
```

`ports` holds every input and clock signal in port order (what the header lists); the data ports are those of
kind `"input"`, and `VectorFile.rows` has one value per data port.

Format: exactly the S1 SV-2 format, with the Wyrd title. Header lines (written by `format_vectors`, optional on
read): `# wyrd seed S cycles N`, then for each of `ports` in order `# input NAME W` (kind `input`) or
`# clock NAME 0` (kind `clock`; Wyrd clock ports are one bit), then `# output NAME W` per output port. Vector lines: `CYCLE INPUTS [OUTPUTS]`, words separated by blanks or tabs;
`CYCLE` is the decimal count of vector lines before it; `INPUTS` is the bits of every input port in port
order, each port MSB first, as `0` and `1` (`-` when the design has no input port); `OUTPUTS` is written only
when `recording` is given (the values of the output ports in the sample after the step of row `c`, that is
`recording.samples[c + 1]`, MSB first) and is ignored on read.

Reading, per S1 SV-2 and SV-3: lines end in LF (a CR before it is dropped); blank lines are skipped; a `#`
line is a comment, except `# input`, `# clock`, `# output` lines which, when present, must equal the lines
`format_vectors` would write for `ports` and the session's outputs (otherwise `VectorError`:
`port line `LINE` does not match the design: expected `EXPECTED``); a vector line must have two or three
words (`expected `<cycle> <inputs> [<outputs>]``), the cycle must equal the count of vector lines so far
(`expected cycle K, found `W``), `INPUTS` must be exactly W bits of 0 and 1 (`expected W input bits of 0 and 1,
found `WORD``), or `-` when W is 0 (`expected `-`: the design has no input bit`). The file is parsed whole
before any cycle runs. Limit: 2^20 lines (`VectorError` `more than 1048576 vector lines`).

Limit of the format: a port that mixes clock bits with data bits (S1 fixture `mixclk.v`) is one `input` signal
to Wyrd, and Wyrd's vector line holds all its bits; S1's format leaves the clock bits of such a port out.
Wyrd does not handle that case and cannot detect it through S1's `kind`; the README says so.

`BifrostSession.run_vectors(vf, names=None)`: `reset()` is not called (the caller decides); starts a recording, then
for each row `set_many` the ports and `step(1)`; returns the recording, and leaves it as the session's
recording. `BifrostSession.run_random(cycles, seed, names)` is `run_vectors(random_vectors(ports, cycles, seed))`.
`random_vectors` uses `random.Random(seed)` and `rng.getrandbits(width)` per port per cycle in port order.

## 9. What W4 uses

W4 uses only: `BifrostSession.from_verilog` (one per intersection, file list of one), `diagnostics`/`CompileError`
(file:line shown in the game), `inputs`/`outputs`/`signal`/`has_signal` (port check), `set`, `get`, `step(1)`,
`reset`, `close`, and the `Backend` seam (tests inject a fake). It never uses recording. Contract kept for W4:
per tick one `set` per input that changed, one `step(1)`, four `get`s; a session opens in the power-on state;
sessions of different files are independent.

## 10. `wyrd sim` (command line)

```
wyrd sim FILE... [--top NAME] (--vectors FILE | --random N [--seed S]) [--vcd OUT.vcd] [--save-vectors FILE] [--csv]
```

- Compiles the files (`BifrostSession.from_verilog`), runs the vector file or N random cycles, prints one line per
  cycle `CYCLE: in1=V in2=V | out1=V out2=V` (names of the recorded inputs, then outputs; values in decimal;
  `CYCLE` is the cycle just completed, from 1), or with `--csv` a header `cycle,in1,in2,out1,out2` and one row
  per cycle; writes the VCD and the vector file when asked.
- Exit 0 ok; 2 for usage errors, compile errors (each diagnostic on stderr as `file:line:col: severity:
  message`), vector errors (`VectorError` text), and a missing `wyrd[sim]` (the `SimUnavailable` text).
- It is imported lazily: `wyrd run` etc. are unaffected.

## 11. The GUI simulation panel (`wyrd/gui/simpanel.py`, `waveformview.py`)

Added to the W2 window (`wyrd/gui/mainwindow.py`): tab `Simulate` after `wyrd.toml`; menu `Tools` with
`Simulate` (Ctrl+T, selects the tab) and (W4) `Midgard (Verilog Town)`. The tab is built even without the
extra; its controls are disabled with the `SimUnavailable` text in the status label.

Layout:

    +----------------------------------------------------------------------+
    | Design [combo]  Top [line edit, optional]  [Compile]   status label   |
    +-------------------------+--------------------------------------------+
    | Signals table           | [ Waveform | Vectors | Diagnostics ] tabs     |
    |  name width kind value  |                                              |
    |  (inputs editable)      |                                              |
    +-------------------------+--------------------------------------------+
    | [Step] [Step N: spin] [Run/Pause] speed [Reset] [x Record]              |
    | Random: cycles [spin] seed [spin] [Run random] [Run vectors]            |
    | Radix [hex|dec|bin] [Save VCD...] [Save vectors...] [Open in GTKWave]   |
    +----------------------------------------------------------------------+

- **Design combo**: the project's designs (`Project.designs`), filled by `set_project(project)`; with no project
  the combo is empty and `Compile` is disabled. `Top` empty means the design's own `top`, else Odin III's choice.
- **Compile**: closes any session, runs `BifrostSession.from_verilog(design.files, top=...)` (on the GUI thread; designs
  are small; the call takes milliseconds), fills the signals table, clears the recording. On `CompileError` the
  Diagnostics tab lists every diagnostic (columns Severity, Message, Location); double-click emits
  `location_activated(Path, int)` that `MainWindow` routes to `source_view.open_file` (the same route as the
  W2 Messages pane).
- **Signals table** (`QTableWidget`): one row per `signals` entry that is an input, clock, or output, then internals
  only when the check box `Show internal signals` is on. Columns `Name`, `Width`, `Kind`, `Value`. An input
  `Value` cell is editable; on commit `parse_int_text` then `BifrostSession.set`; an error turns the cell red with the
  message as tooltip and keeps the old value. Values refresh after every step, reset and compile.
- **Step / Step N / Run**: `Step` is `session.step(1)`; `Step N` is `step(n)` (n from the spin box, 1 to 100000);
  `Run` starts a `QTimer` that calls `step(1)` `speed` times per tick, 50 ms interval; speed choices 1, 10,
  100, 1000 cycles per second; `Pause` stops it. A step error stops the run and shows the message.
- **Reset** is `session.reset()` and clears the waveform.
- **Record** (default on): starts a recording at compile and keeps it (limit 1,000,000 samples, then the
  status label says `recording full`); the Waveform tab shows the whole recording and scrolls.
- **Random run**: `session.reset()`, then `run_random(cycles, seed)`; **Run vectors**: `reset()`, `parse_vectors` of the Vectors
  tab text (a `VectorError` shows `LINE: message` in the status label and moves the cursor to that line), then
  `run_vectors`. The Vectors tab is a `QPlainTextEdit` with `Open...`, `Save...`, and `Generate template` (the
  header plus 16 all-zero lines for the current ports) buttons, UTF-8.
- **Waveform view** (`WaveformView(QWidget)`): rows from `rows_from_recording`; name column 160 px, 24 px per
  sample (Ctrl+wheel zooms 8 to 64), horizontal scroll in a `QScrollArea`; width-1 rows are a high/low trace;
  wider rows are boxes per `Segment` with the value text in the chosen radix; a click on the plot sets a
  vertical cursor and the values at that sample show in the Value column header as `Value @N`. Painting uses
  `QPainter` only; the model is `waveform.py`.
- **Save VCD / Open in GTKWave**: `Save VCD...` asks for a path and calls `write_vcd`. `Open in GTKWave` writes
  `<project dir>/sim/<design>.vcd` (creates `sim/`), then `QProcess.startDetached(path_of_gtkwave, [vcd])`
  where the program is `os.environ["WYRD_GTKWAVE"]` or `shutil.which("gtkwave")`; when neither exists the status
  label says `gtkwave not found; install it (for example: sudo apt install gtkwave)`. Nothing is started
  when there is no recording.

No threads, no analysis beyond what `wyrd.bifrost` returns.

## 12. Packaging and CI

- `pyproject.toml`: `[project.optional-dependencies] sim = ["odin3>=1.2"]` (beside `gui`); `dependencies`
  stays `[]`.
- CI: the `test` job runs the whole suite without `odin3` (the real-backend tests skip, the fake-backend tests
  run). The `gui` job (W2) also runs `tests.test_gui_sim`. A new job `sim` (Python 3.12) installs `.` and
  `odin3>=1.2` and runs `python -m unittest tests.test_sim_odin3 -v`; it is `continue-on-error: true` until
  Odin III 1.2 is on the package index (remove that line then; open question 1).
- Local real run (before 1.2 is published): `PYTHONPATH=<odin3 worktree>/plugins/python
  ODIN3_LIB=<build>/libodin3.so`; `odin3_available()` then finds the module `odin3` (a single file) and the
  library.

## 13. Tests

- `tests/fakes_sim.py`: `FakeBackend`, a Python re-implementation of the S1 fixture `traffic.v` (spec S1 section
  10), the oracle for every Qt-free test below. `tests/test_sim_*.py`: `types`/`diagnostics`, `backend` (a fake
  `odin3` module in `sys.modules`), `session`, `record_vcd`, `vectors`, `cli`; `tests/test_waveform.py`;
  `tests/test_gui_sim.py` (offscreen Qt, skips without PySide6; injects `FakeBackend`); `tests/test_sim_odin3.py`
  (real S1, skips when `odin3_available()` is false).
- The real-backend test runs the S1 reference trace (section 10 of the S1 spec) through `BifrostSession` on
  `tests/data/sim/traffic.v` (text in the plan, the S1 fixture) and compares it with the same trace run
  through `FakeBackend`.

## 14. Not in W3

4-state values, X/Z, timing, delays, per-clock stepping (S1 later `odin3_simulation_step_clock`), forcing
internal nets, memory contents, schematic or RTL views (W5), assertions, testbench languages, a debugger,
VCD import, multi-design co-simulation, running the simulator in a thread or process, Windows-native builds.

## 15. Questions for Peter, with recommendations

1. When Odin III 1.2 is published, remove `continue-on-error` from the `sim` job. Recommend: yes, one-line change.
2. The Wyrd random run does not match `odin3 sim N SEED`'s numbers (different PRNG). Recommend: keep, and say so
   in the panel's tooltip; "Save vectors" makes a run repeatable in both tools.
3. The vector format cannot express a port mixing clock and data bits. Recommend: leave (no consumer; the rare
   case is documented).
