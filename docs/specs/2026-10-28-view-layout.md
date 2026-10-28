# Wyrd III window layout and View capabilities

Purpose (Peter 2026-10-28, testing the GUI): panels get squeezed (the Project area and its tabs
shrink to unreadable widths) and the user cannot size, hide, detach or maximise them. Serves W Q3.1
and W Q3.3 (what a person needs to see). Measure: every panel can be shown at a usable size on a
1920x1080 and a 1366x768 screen.

## Panels

Every panel is a `QDockWidget` with a stable object name (`dock-<name>`): Project (tree), Source,
Report, wyrd.toml (editor), Simulate, Messages, Flow, Timing, Schematic, Atlas, Mimir. There is no
central widget; the docks fill the window. Each dock can be resized, closed, re-opened from
View, floated (detached window) and re-docked anywhere. Nested docks and tabs are allowed
(`AllowNestedDocks`, `AllowTabbedDocks`, `GroupedDragging`).

## Maximise

View > "Maximise current panel" (F11, Ctrl+Shift+M) toggles. Maximising saves the window state,
hides every other panel and shows the current one alone; the same action restores. Double-click on
a dock title bar or on a dock tab does the same for that dock (on a floating dock the title
double-click keeps the Qt default: re-dock). The current panel is the dock holding the keyboard
focus, else the dock last given focus, else the dock under the mouse, else the largest dock shown (the current tab of a tab group; hidden tabs do not count). Closing while maximised saves
the layout from before the maximise.

## Presets

Pure data in `wyrd/guimodel/layoutspec.py` (no Qt). A preset is a list of groups (area, tabbed
docks, current tab, share of the window along the area's axis); docks in no group are parked tabbed
at the bottom and hidden, so View can reopen them.

- Project (default): Project tree left; Source, Report, wyrd.toml, Simulate tabbed right; Messages,
  Flow, Timing, Schematic, Atlas, Mimir tabbed at the bottom.
- Timing + source: Source left (large), Timing right; Messages bottom (small); rest hidden.
- Mimir explorer: Mimir left (large), Source right (secondary); rest hidden.
- Everything tabbed: all eleven docks in one tab group.

View > Layout lists the presets with a check mark on the active one (cleared when the user moves
docks; stored as `layout/preset`); View > "Reset layout" applies the default preset.

## Save and restore

On close the window stores `layout/state` = `saveState(LAYOUT_VERSION)` and `layout/version`
= LAYOUT_VERSION in `QSettings`, plus geometry. At start the state is restored only when the stored
version equals LAYOUT_VERSION and `restoreState` accepts it; otherwise the default preset applies.
The older `windowState` key is ignored (its docks differ). After a restore, a floating dock whose
frame is not inside any screen is moved onto the primary screen (`ViewLayout.ensure_on_screen`).

## Inside the panels

Dock contents have minimum sizes; panels with wide content (Report, Timing, Simulate, Mimir, Flow)
sit in a `QScrollArea` so a narrow dock scrolls instead of crushing its widgets. Splitters keep
visible handles and non-collapsible children. Tables stretch the last column; long labels elide with
the full text in the tooltip.

## Zoom

View > Zoom in / out / reset (Ctrl+=, Ctrl++, Ctrl+Shift+=, Ctrl+-, Ctrl+0; also Ctrl+wheel over a
text or table) changes a point-size offset (`view/zoom`, clamped to -4..+20) applied to every
plain-text editor, table, list and tree in the docks (not buttons, labels, menus, About headers).
The offset is saved when it changes and applied at start.

## Tooltips

Every control of the Mimir Design, Run, Compare and Plot tabs (and the shared table buttons) has a
tooltip. A test lists them.

## Screens and platform

Checked offscreen at 1366x768 and 1920x1080 with a screenshot per preset in
`/tmp/claude-1000/wlay-shots/`. The GUI launch scripts set `QT_QPA_PLATFORM=xcb` on WSLg because
Wayland crashed on maximise with an xdg_surface size error; the Python code is platform neutral and
never sets the platform itself. Documented in `docs/user/gui.md`.

## Tests

Layout save/restore round trip, bad version ignored, maximise toggle, presets apply, reset, zoom
persistence, tooltip coverage (all offscreen). The spec module `layoutspec` is tested without
PySide6.
