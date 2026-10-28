"""Plain-English help for the Mímir dock: tab headers, column and control tooltips, the guide.

Qt-free so tests can check the text. The rule: say what a thing is before its technical term.
"""

from __future__ import annotations

SECTIONS = ("What this shows", "Why use it", "What you will see", "How to read it")

TABS: dict[str, tuple[str, str, str, str]] = {
    "Summary": (
        "The size of the open Mímir store: how many measured values it holds and which "
        "experiments (sources) they came from.",
        "Check you opened the right file before you look at anything else, and see which "
        "experiments you can pick from.",
        "A few counts (records, runs, designs, metrics), then one row per source with its number "
        "of records and runs.",
        "A record is one measured value of one circuit. A run is one execution of the design "
        "flow (synthesis, packing, placement, routing) with one set of settings. A source is the "
        "experiment that made them.",
    ),
    "Design": (
        "Everything the store knows about one circuit: its measured values, the runs that made "
        "them, where the circuit came from, and the structures found in its HDL.",
        "Use it to look at one circuit in depth, or to find which run to look at next.",
        "Pick a circuit in the list on the left. Tabs show Metrics (value, unit, who measured it), "
        "Runs (double click a run to open it), Meta, Lineage and Structures.",
        "The level says where in the flow a value was measured (gate, lut, clb, routed ...). "
        "Colours in Meta and Lineage say how well the value is known: green given, grey default, "
        "orange default but not recorded, red unknown.",
    ),
    "Run": (
        "One run: the exact flow settings it used and the files it produced.",
        "Use it to find out how a number was obtained, and to fetch the output files.",
        "A table of flow parameters, a table of artifacts (output files, by hash), and a "
        "Fetch button. Select a run first: double click one in the Design tab.",
        "Parameter colours say whether a setting was given on the command line, left at its "
        "default, or is not known. Two runs only compare fairly when their settings are the same.",
    ),
    "Compare": (
        "How one configuration (a set of runs made with the same settings) does against another "
        "on one measured value, over the circuits both have.",
        "Use it to answer 'is setting A better than setting B' without reading every run.",
        "A table with one row per configuration, and a dot chart of the same numbers. Press "
        "'List configs' after typing a source prefix, then choose the base and the metric.",
        "The geometric mean ratio is the typical value divided by the base value: below 1 is "
        "smaller than the base, above 1 larger. MIXED means the rows mix tool versions or flow "
        "settings, so read that row with care.",
    ),
    "Plot": (
        "Every run as one dot: one measured value on the x axis, another on the y axis.",
        "Use it to see a trade-off, for example area against speed, across all circuits.",
        "A scatter plot. Hover over a dot to see which design and run it is. Log axes help when "
        "values span several orders of magnitude.",
        "Only runs that have both values are drawn. A cluster away from the others is worth "
        "opening in the Design tab.",
    ),
    "Structures": (
        "The pieces of HDL that look like a known building block (an adder, a multiplexer, a "
        "register word ...) and where those pieces ended up after synthesis and placement.",
        "Use it to ask whether the structures of the source code survive into the chip, and "
        "whether the slow parts are spread out or kept together.",
        "A table with one row per structure and level (lut, clb ...), and a scatter plot of "
        "spread against crit_share. Filters narrow it by design, run, level and kind.",
        "Level: the step of the flow the row describes (a lut is one logic cell, a clb a "
        "cluster of them). Spread: how far apart on the chip the pieces of the structure were "
        "placed (0 = together; larger = spread out). crit_share: the fraction of the critical "
        "path delay that the structure contributes. joined_with and lost_at_pass say where the "
        "structure was merged with another or disappeared. Top right of the plot: a spread-out "
        "structure that also sits on the critical path.",
    ),
    "Timing": (
        "How close to critical each path of a run is, and which pieces of the HDL those paths go "
        "through.",
        "Use it to find which lines and signals of your HDL set the speed of the chip, and to see "
        "how many other paths are almost as slow.",
        "A summary line, a histogram of path criticality, a table of the most critical objects "
        "(words, source lines, modules, structures), and a plot of near-critical paths against "
        "area. 'Open in source view' paints the HDL red (critical) to blue (not critical).",
        "Crit (criticality) is 1 minus slack divided by the clock period: 1.0 is the slowest "
        "path, 0 has lots of spare time. Near-critical means crit is at least theta; theta is "
        "0.90, 0.95 or 0.99 (the three counts). A bit strip lists crit per bit of a bus, most "
        "significant first. Exact or lower bound: the store says whether the clock period was "
        "found from all paths (exact) or only from a cut report, in which case crit is a lower "
        "bound.",
    ),
}

GLOSSARY: dict[str, str] = {
    "run": "One execution of the design flow with one set of settings.",
    "config": "A set of runs made with the same settings (source and arm).",
    "level": "The step of the flow a value was measured at: gate, lut, ble, clb, placed, routed.",
    "structure": "A piece of HDL that matches a known building block, such as an adder.",
    "crit": "Criticality, 1 - slack / clock period. 1.0 is the slowest path, 0 has spare time.",
    "near-critical": "A path whose crit is at least theta.",
    "theta": "The near-critical threshold: 0.90, 0.95 or 0.99.",
    "spread": "How far apart on the chip the parts of a structure were placed.",
    "crit_share": "The fraction of the critical path delay a structure accounts for.",
    "exact": "The clock period came from all paths (exhaustive or the full report): crit is right.",
    "lower bound": "The clock period came from a cut report: the real crit may be higher.",
}

COLUMN_TIPS: dict[str, str] = {
    "source": "The experiment that produced the value.",
    "level": "The step of the flow where the value was measured (gate, lut, clb, routed ...).",
    "metric": "What was measured, for example vpr.cpd (critical path delay).",
    "value": "The measured number.",
    "unit": "Unit of the value.",
    "measurer": "The tool that measured it.",
    "origin": "Where the value was read from.",
    "arch": "The FPGA architecture file the run used.",
    "arm": "The variant of the experiment (a setting that was changed on purpose).",
    "seed": "The random seed of the run.",
    "bin": "Whether the value is in a bin (binned architecture).",
    "tool_commit": "The version of the tool that made the value.",
    "records": "Number of measured values.",
    "runs": "Number of runs.",
    "config": "A set of runs with the same settings.",
    "n designs": "How many circuits both this configuration and the base have.",
    "dropped (<=0 or non-numeric)": "Circuits left out because a value was not a positive number.",
    "duplicate rows merged": "Repeated measurements that were merged into one first.",
    "tool commits": "How many different tool versions are in the rows. More than 1 mixes versions.",
    "configs": "How many different flow settings are in the rows. More than 1 mixes settings.",
    "mixed": "MIXED when the row mixes tool versions or flow settings.",
    "structure_id": "The name the store gives this structure.",
    "kind": "What kind of building block it is (adder, mux, register word ...).",
    "n_luts": "Number of lookup tables (logic cells) the structure became.",
    "n_clbs": "Number of clusters of logic cells the structure became.",
    "bbox": "Bounding box on the chip of the placed parts: (x0,y0)-(x1,y1).",
    "spread": "How far apart on the chip the parts were placed. 0 is together.",
    "crit_share": "The fraction of the critical path delay this structure accounts for.",
    "joined_with": "Another structure this one was merged with when synthesis combined logic.",
    "lost_at_pass": "The synthesis step after which the structure could no longer be followed.",
    "object": "The HDL object: a signal word (module/name), a source line (file:line), a module "
    "or a structure.",
    "crit_max": "The highest criticality of any path through the object (1.0 is the slowest path).",
    "n_paths": "How many reported paths go through the object.",
    "n >= 0.90": "Paths through the object with crit at least 0.90 (near-critical, theta 0.90).",
    "n >= 0.95": "Paths through the object with crit at least 0.95.",
    "n >= 0.99": "Paths through the object with crit at least 0.99.",
    "delay share 0.90": "The share of the delay of the 0.90 near-critical paths in the object.",
    "via": "How the object was linked to the HDL: name (signal name), pad (port), line or span "
    "(by source line), json-id, declarator.",
    "bits (MSB first, crit)": "Crit of each bit of a bus, most significant bit first (bit:crit).",
}

CONTROL_TIPS: dict[str, str] = {
    "design": "Choose the circuit.",
    "run": "Choose one run (one execution of the flow).",
    "level": "Keep only rows of this step of the flow.",
    "kind": "Keep only this kind of structure or object.",
    "objects": "Which kind of HDL object to list: word (signal), span (source line), module, "
    "structure.",
    "area x": "The area measure for the x axis. Only LUT or CLB counts are real area; any other "
    "metric is a proxy and the plot says so.",
    "near-critical y": "Number of near-critical paths per run; theta is the 090, 095 or 099 in "
    "the name.",
    "open": "Paint the HDL of this run red (critical) to blue (not critical) in the source view.",
}

GUIDE_BEGIN = "<!-- guide:begin -->"
GUIDE_END = "<!-- guide:end -->"

GUIDE = """## Mímir guide: from a store to a coloured source file

Mímir is a database of measured values of circuits: how big they are, how fast, how their HDL
turned into logic. Wyrd shows it read only: it never changes the file.

### 1. Open a store

File > Open Mímir store... and choose a `.db` file. The Summary tab says what is in it: records
(measured values), runs (executions of the flow) and sources (experiments).

### 2. Pick a design

Choose a source and type in the filter box, then click a circuit. The Design tab fills in. Double
click a run in its Runs table to see exactly how the run was made (Run tab).

### 3. The Timing tab

Pick a run. The summary line gives the clock period (CPD), the worst slack and how many of the
reported paths were used. Criticality (crit) is 1 minus slack divided by the clock period: 1.0 is
the slowest path, 0 has plenty of spare time. A path is near-critical when its crit is at least
theta (0.90, 0.95 or 0.99). The histogram shows how many paths fall in each crit range; the
table lists the most critical HDL objects, with a bit strip for buses.

Exact or lower bound: when the summary says "crit is exact", the clock period was found from all
paths. When it says "crit is a lower bound (dmax from report)", it came from a cut report and the
true crit can only be higher.

### 4. Open in source view

Press "Open in source view". Wyrd finds the design's source from the store (the design's origin,
for example `$VTR_ROOT/vtr_flow/benchmarks/verilog/mkPktMerge.v`; `$VTR_ROOT` comes from your
environment or the machine settings), opens it read only, switches the Timing panel to
near-critical, and selects the hottest token. When the file cannot be found the status line
says exactly what is missing and a file dialog lets you pick it.

### 5. What red and blue mean

Red is critical (crit near 1), blue is not critical, light yellow is in between. A faint tint
on a whole line says the line is on a near-critical path. For a bus such as `D_OUT[141:0]` the
name is split into one coloured piece per bit, most significant bit first: a name of 6 letters
for 3 bits gives 2 letters per bit. When the name is shorter than the number of bits, a bit
strip under the name shows each bit and the name keeps the highest crit. A dotted underline
marks a bit that is unknown. Hover a token to see its crit and every bit.

### 6. Example: mkPktMerge

Open `lane3-structures.db`, pick `mkPktMerge`, choose a run in the Timing tab and press Open
in source view. The word `fi1__D_OUT` is a bus of at least 142 bits. Bits 134 and 141 have
crit 1.0 and bit 132 has 0.995: those bits set the speed of the chip, while many others sit
near 0.93. Click the token to list the paths through it in the Timing panel.

### 7. Structures tab

A structure is a piece of HDL that looks like a known building block (an adder, a multiplexer).
Each row says how many LUTs and CLBs it became, where it was placed (bbox), its spread (how far
apart its parts are) and crit_share (how much of the critical path it accounts for).
"""

HELP_MENU_TITLE = "Mímir guide"


def tab_help(tab: str) -> str:
    """The four headed paragraphs of a tab as HTML-free text."""
    texts = TABS[tab]
    return "\n".join(f"{h}: {t}" for h, t in zip(SECTIONS, texts, strict=True))


def column_tip(name: str) -> str:
    return COLUMN_TIPS.get(name, "")
