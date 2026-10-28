"""Plain-English help for every Wyrd panel and the Wyrd guide (Qt-free so tests can check it).

Same four parts as the Mímir tab headers (``mimirhelp.SECTIONS``). Say what a thing is before its
technical term. The guide text is mirrored in ``docs/user/gui.md`` (a test checks they agree).
"""

from __future__ import annotations

from wyrd.guimodel import layoutspec as ls
from wyrd.guimodel import mimirhelp

GUIDE_BEGIN = "<!-- wyrd-guide:begin -->"
GUIDE_END = "<!-- wyrd-guide:end -->"
GUIDE_MENU_TITLE = "Wyrd guide"

PANELS: dict[str, tuple[str, str, str, str]] = {
    ls.PROJECT: (
        "Your project as a tree: the designs (circuits) with their source files, the recipes "
        "(the steps the flow runs) and the architectures (the target chip descriptions).",
        "Find a file of your project quickly and open it, without a file dialog.",
        "Three groups: Designs (each with its files), Recipes (each with its steps) and Archs. "
        "The tree is empty until a project is open (File > Open Project).",
        "Double click a file to show it in the Source panel. A recipe is an ordered list of "
        "tools (for example synthesis then place and route); an arch is the chip the circuit "
        "is built on.",
    ),
    ls.SOURCE: (
        "The text of one Verilog file, read only, with syntax colours. When a timing run is loaded "
        "it can also paint the text hot (red) or cold (blue).",
        "Read the code that a message, a path or a table row points at, and see which parts of it "
        "decide the speed of the chip.",
        "The file name, the code, and a margin with a share per line. With hot/cold on you also "
        "see a colour bar (blue to red) with a theta line, coloured words, small strips under "
        "buses, and dotted underlines.",
        "Red means critical: the signal lies on a path that limits the clock speed. Blue means "
        "not critical: lots of spare time. The criticality (crit) is how close a path is to "
        "being the slowest one: 0 (blue) has lots of spare time, 1 (red) is the slowest. Theta "
        "is the near-critical threshold (0.90, 0.95 or 0.99): paths with crit at least theta "
        "count as near-critical. A bit strip under a bus word has one small box per bit, most "
        "significant bit first (the MSB first box in the Timing panel changes that), each "
        "coloured by that bit's crit. A dotted underline marks a bit whose index is unknown; "
        "such a bit is grey. Separately: the columns of a word are always found by matching its "
        "name on the line.",
    ),
    ls.REPORT: (
        "The results of the runs of your project: one tree entry per run and, for the selected "
        "run, its table of numbers, its log, or a comparison with another project.",
        "See whether a run worked, what it measured, and how it compares, without opening files.",
        "A tree of runs on the left; on the right a table of metrics (such as area and delay), "
        "a log page, and a compare page. A Floorplan button opens the chip layout of a run.",
        "A run is one execution of the flow with one set of settings. Select a run to load its "
        "messages and timing into the other panels. A failed run shows its log.",
    ),
    ls.EDITOR: (
        "The project file wyrd.toml: it says which designs, settings and recipes the runs use.",
        "Change what the project runs. The text is checked while you type.",
        "A text editor, a status line (the number of runs the file expands to, or the error) "
        "and a Save button.",
        "A green status gives the number of runs. A red status names the problem and its line; "
        "click it to jump there. Ctrl+S saves. After a valid save the project reloads.",
    ),
    ls.SIMULATE: (
        "Run a design in a simulator and watch its signals change over time, like a logic "
        "analyser.",
        "Check that a circuit does what you expect, step by step, before you build it.",
        "Controls (compile, step, run, reset), a table of signals with their values, a waveform "
        "and a list of diagnostics. Test vectors can be loaded or generated.",
        "A step is one clock tick. A waveform is a signal's value drawn against time. A "
        "vector is one set of input values to apply. Radix chooses how numbers are shown "
        "(binary, decimal, hexadecimal).",
    ),
    ls.MESSAGES: (
        "The warnings and errors that the tools printed when they ran the selected run.",
        "Find what went wrong, or what the tools were unsure about, and jump to the line.",
        "A table with the severity, the tool, the text, and the file and line when there is one.",
        "Errors stop a run, warnings do not. Double click a row that names a file to open it "
        "at that line in the Source panel.",
    ),
    ls.FLOW: (
        "The control for running your project's flow: the same as the wyrd run command.",
        "Start, watch and stop the runs from the window.",
        "Run, Cancel and Force controls, the number of jobs and the memory budget, a progress "
        "line and the output of the running steps.",
        "Jobs is how many runs go at once; the memory budget stops too many big runs from "
        "starting together. Force repeats runs that already finished OK. Cancel keeps finished "
        "runs.",
    ),
    ls.TIMING: (
        "The timing of the selected run: how long the slowest paths are and which parts of the "
        "HDL they go through.",
        "Find the signals, lines and modules that set the speed of the chip.",
        "A summary, a table of paths and objects, and controls that choose how the Source "
        "panel is coloured (by margin, hot/cold, or both) and which paths count.",
        "Slack is the spare time of a path: negative means the path is too slow. Crit is how "
        "close a path is to being the slowest one: 1 is the slowest, 0 has lots of spare time. "
        "It is 1 - slack / (the largest required time of its clock pair); when the worst slack "
        "is negative, all slacks are shifted so that the worst is 0. Near-critical means crit "
        "is at least theta. MSB first (a setting here) chooses the bit order of the bit strips. "
        "Click a coloured word in the Source panel to list its paths.",
    ),
    ls.SCHEMATIC: (
        "A drawing of the gates and wires of one module of a synthesised netlist.",
        "See the structure the tools built from your code.",
        "A module chooser, Open netlist and Draw buttons, and the drawing. Each gate is a box, "
        "each wire a line.",
        "A netlist is the circuit after synthesis, written as gates and wires. Large modules are "
        "drawn in pieces; use the scroll bars or zoom.",
    ),
    ls.ATLAS: (
        "A map of where the parts of the circuit were placed on the chip, and how that "
        "changed between two settings.",
        "See whether different placement settings put the logic in different places.",
        "File and design choosers, two arm choosers (A and B, the two settings compared), a "
        "scan button and grids of the chip.",
        "A placement is the position of every block on the chip grid. An arm is one setting of "
        "the experiment. Brighter cells hold more blocks or moved more between the arms.",
    ),
    ls.MIMIR: (
        "A viewer for a Mímir store, a database of measured values of many circuits: size, "
        "speed, and how the HDL turned into logic.",
        "Compare experiments, look at one circuit in depth, and send timing to the Source panel.",
        "A list of circuits on the left and tabs on the right: Summary, Design, Run, Compare, "
        "Plot, Structures, Timing. Each tab has its own About header.",
        "The store is opened read only: Wyrd never changes it. Start with File > Open Mímir "
        "store, then read the Summary tab. Click a circuit; the Current design line above the tabs "
        "names it. To see the colour of its HDL (red = slowest, blue = spare time) press Show "
        "HDL heat (hot/cold) beside that line; it is grey, with a tooltip, when the circuit "
        "has no timing. List entries marked 'timing' carry it.",
    ),
    ls.PATHS: (
        "The stored timing paths that run through the line, word or bit you clicked in the "
        "Source panel, and one chosen path walked step by step through the logic.",
        "The heat of a line says how critical it is; this panel says why: the paths that run "
        "through it.",
        "A cut-off setting, a table of paths (rank, crit, slack, start and end, number of "
        "nodes), Previous and Next buttons, an All paths through here box, and the steps of "
        "the chosen path. In the Source panel the path shows as numbered markers in the gutter "
        "with each step's delay; every line off the path is dimmed.",
        "Open a Mímir store, press Show HDL heat, then click a hot word or line. Choose a path: "
        "click a step to jump to its line (a step in another file opens that file). Crit is as "
        "in the Timing panel; only paths with crit at least the cut-off (0.90, 0.95, 0.99 or "
        "off) are shown, the rest are kept in the store but not drawn. All paths through here "
        "colours the lines of the near-critical paths through the click by the largest crit "
        "among them. A store written before schema 6 has no per-path data: the panel says so.",
    ),
}


def panel_html(name: str) -> str:
    rows = zip(mimirhelp.SECTIONS, PANELS[name], strict=True)
    return "".join(f"<p style='margin:2px 0'><b>{h}.</b> {t}</p>" for h, t in rows)


def _chapter(name: str) -> str:
    rows = zip(mimirhelp.SECTIONS, PANELS[name], strict=True)
    parts = "\n\n".join(f"**{h}.** {t}" for h, t in rows)
    return f"### {name}\n\n{parts}"


def build_guide() -> str:
    """The Wyrd guide: every panel in turn, then the Mímir guide as the last chapter."""
    intro = (
        "## Wyrd guide\n\n"
        "Wyrd is a window onto your project: its files, its runs, what the tools said, how "
        "fast the circuit is, and what a Mímir store knows. Every part of the window is a "
        "panel. Each panel has an About header with the four parts below. View > Panels shows "
        "or hides a panel, View > Layout chooses a layout, F11 makes one panel fill the "
        "window, and zoom changes the size of the text in the code and text editors, logs, tables, "
        "lists and trees of every panel (Ctrl+= or Ctrl+Shift+= bigger, Ctrl+- smaller, Ctrl+0 "
        "normal, or hold Ctrl and turn the mouse wheel over a text or table). Buttons, labels, "
        "menus and the About headers keep their size."
    )
    chapters = "\n\n".join(_chapter(n) for n in ls.PANELS)
    return f"{intro}\n\n## The panels\n\n{chapters}\n\n{mimirhelp.GUIDE.strip()}\n"


GUIDE = build_guide()
