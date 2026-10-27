"""The Atlas panel: a Norns round-7 placement drawn on the device grid, stock vs hindsight."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QRectF, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QBrush, QColor, QMouseEvent, QPen, QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from wyrd import atlas
from wyrd.atlas import Atlas, AtlasError, RunFile

CELL = 22
MODES = ("A only", "A | B side by side", "Difference (B vs A)")
NO_ATLAS = (
    "No atlas loaded. Open a Norns round-7 atlas file (.json.gz) or give the Norns run dir "
    "(runs/r7) and press Scan."
)
CACHE_LIMIT = 8


class GridView(QGraphicsView):
    """One device grid: a rectangle per CLB, hover text, optional highlight set."""

    hovered = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setMouseTracking(True)
        self.setMinimumSize(160, 160)
        self.atlas: Atlas | None = None
        self.extra: dict[int, str] = {}
        self.items_by_clb: dict[int, QGraphicsRectItem] = {}

    def show_atlas(
        self,
        a: Atlas | None,
        colours: dict[int, str],
        highlight: set[int],
        extra: dict[int, str] | None = None,
    ) -> None:
        """Redraw. `highlight` non-empty: those CLBs outlined, the rest faded."""
        self.atlas = a
        self.extra = extra or {}
        self.items_by_clb = {}
        scene = self.scene()
        scene.clear()
        if a is None:
            return
        w, h = a.grid
        scene.addRect(QRectF(0, 0, w * CELL, h * CELL), QPen(QColor("#888888")), QColor("#f4f4f4"))
        scene.setSceneRect(QRectF(-4, -4, w * CELL + 8, h * CELL + 8))
        for c in a.clbs:
            self.items_by_clb[c.id] = self._add_clb(a, c, colours.get(c.id, "#ffffff"), highlight)
        self._fit()

    def _add_clb(
        self, a: Atlas, c: atlas.Clb, colour: str, highlight: set[int]
    ) -> QGraphicsRectItem:
        x, y = c.x * CELL, (a.grid[1] - 1 - c.y) * CELL  # y = 0 is the bottom row
        item = QGraphicsRectItem(QRectF(x + 1, y + 1, CELL - 2, CELL - 2))
        fill = QColor(colour)
        pen = QPen(QColor("#555555"))
        if highlight:
            if c.id in highlight:
                pen = QPen(QColor("#000000"), 3)
                item.setZValue(1)
            else:
                fill.setAlpha(60)
        item.setBrush(QBrush(fill))
        item.setPen(pen)
        item.setData(0, c.id)
        self.scene().addItem(item)
        return item

    def _fit(self) -> None:
        self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit()

    def text_for(self, clb_id: int) -> str:
        """Hover text of a CLB (empty when unknown)."""
        if self.atlas is None:
            return ""
        clb = self.atlas.clb_by_id().get(clb_id)
        if clb is None:
            return ""
        extra = self.extra.get(clb_id, "")
        return atlas.hover_text(self.atlas, clb) + (f"\n{extra}" if extra else "")

    def clb_at(self, x: int, y: int) -> int | None:
        item = self.itemAt(x, y)
        value = item.data(0) if item is not None else None
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        super().mouseMoveEvent(event)
        pos = event.position().toPoint()
        cid = self.clb_at(pos.x(), pos.y())
        text = "" if cid is None else self.text_for(cid)
        self.viewport().setToolTip(text)
        self.hovered.emit(text)

    def render_check(self) -> QRect:
        """Force a full paint of the view (used to time drawing); the painted rectangle."""
        self.grab()
        return self.viewport().rect()


class _Signals(QObject):
    loaded = Signal(int, str, object, float)  # token, role, atlas, seconds
    failed = Signal(int, str)


class _LoadTask(QRunnable):
    def __init__(self, token: int, role: str, path: Path, signals: _Signals) -> None:
        super().__init__()
        self.token, self.role, self.path, self.signals = token, role, path, signals

    def run(self) -> None:
        t0 = time.perf_counter()
        try:
            a = atlas.load_atlas(self.path)
        except AtlasError as e:
            self.signals.failed.emit(self.token, str(e))
        except Exception as e:  # any failure must reach the panel, or it stays busy forever
            self.signals.failed.emit(self.token, f"{self.path.name}: {e}")
        else:
            self.signals.loaded.emit(self.token, self.role, a, time.perf_counter() - t0)


class AtlasPanel(QWidget):
    """Read-only atlas viewer; never raises on bad input, shows the reason in `status`.

    Loading runs on a worker thread (QRunnable on a private QThreadPool, as schematicpanel.py);
    a token drops stale results. `finished` fires when a request ends (True: drawn).
    """

    finished = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.runs: list[RunFile] = []
        self.atlas_a: Atlas | None = None
        self.atlas_b: Atlas | None = None
        self.last_load_s = 0.0
        self.last_draw_s = 0.0
        self._cache: dict[Path, Atlas] = {}
        self._token = 0
        self._pending: dict[str, Path] = {}
        self._paths: dict[str, Path] = {}
        self._load_s = 0.0
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _Signals(self)
        self._signals.loaded.connect(self._on_loaded)
        self._signals.failed.connect(self._on_failed)
        self._make_widgets()
        self._layout()
        self._connect()

    # ------------------------------------------------------------ widgets

    def _make_widgets(self) -> None:
        self.status = QLabel(NO_ATLAS)
        self.status.setWordWrap(True)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.hover_label = QLabel("")
        self.open_button = QPushButton("Open atlas file...")
        self.root_edit = QLineEdit()
        self.root_edit.setPlaceholderText("Norns run dir (runs/r7)")
        self.scan_button = QPushButton("Scan")
        self.design = QComboBox()
        self.arm_a = QComboBox()
        self.arm_b = QComboBox()
        self.seed = QComboBox()
        self.mode = QComboBox()
        self.mode.addItems(MODES)
        self.key = QComboBox()
        self.key.addItems(atlas.KEYS)
        self.values = QListWidget()
        self.clear_button = QPushButton("Clear highlight")
        self.view_a = GridView()
        self.view_b = GridView()
        self.label_a = QLabel("")
        self.label_b = QLabel("")
        for v, lab in ((self.view_a, self.label_a), (self.view_b, self.label_b)):
            v.hovered.connect(self.hover_label.setText)
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def _layout(self) -> None:
        top = QHBoxLayout()
        for w in (self.open_button, QLabel("Norns run dir"), self.root_edit, self.scan_button):
            top.addWidget(w)
        top.setStretch(2, 1)
        row = QHBoxLayout()
        pairs: list[tuple[str, QComboBox]] = [
            ("Design", self.design),
            ("A", self.arm_a),
            ("Seed", self.seed),
            ("B", self.arm_b),
            ("View", self.mode),
            ("Colour by", self.key),
        ]
        for text, combo in pairs:
            row.addWidget(QLabel(text))
            row.addWidget(combo)
        row.addStretch(1)
        grids = QSplitter(Qt.Orientation.Horizontal)
        for v, lab in ((self.view_a, self.label_a), (self.view_b, self.label_b)):
            box = QWidget()
            lay = QVBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(lab)
            lay.addWidget(v, 1)
            grids.addWidget(box)
        self._grids = grids
        side = QVBoxLayout()
        side.addWidget(QLabel("Highlight (by spread)"))
        side.addWidget(self.values, 1)
        side.addWidget(self.clear_button)
        middle = QHBoxLayout()
        middle.addWidget(grids, 1)
        middle.addLayout(side)
        layout = QVBoxLayout(self)
        for item in (self.status,):
            layout.addWidget(item)
        layout.addLayout(top)
        layout.addLayout(row)
        layout.addLayout(middle, 1)
        layout.addWidget(self.info)
        layout.addWidget(self.hover_label)

    def _connect(self) -> None:
        self.open_button.clicked.connect(self._choose)
        self.scan_button.clicked.connect(lambda: self.scan(Path(self.root_edit.text().strip())))
        self.design.activated.connect(lambda _i: self._design_changed())
        for combo in (self.arm_a, self.arm_b, self.seed):
            combo.activated.connect(lambda _i: self.request())
        self.mode.activated.connect(lambda _i: self.request())
        self.key.activated.connect(lambda _i: self._key_changed())
        self.values.itemSelectionChanged.connect(self.redraw)
        self.clear_button.clicked.connect(self.values.clearSelection)

    # ------------------------------------------------------------ choosing runs

    def _choose(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, "Open atlas", "", "Atlas (*.json *.json.gz);;All files (*)"
        )
        if name:
            self.open_file(Path(name))

    def scan(self, root: Path) -> int:
        """List the designs, arms and seeds under a run dir (or a folder of samples); returns
        the number of atlas files found and selects the first one."""
        self.runs = atlas.find_runs(root)
        if not self.runs:
            self.status.setText(f"No atlas files found under {root}.")
            return 0
        self._fill_designs(self.runs[0].design)
        self.status.setText(
            f"{len(self.runs)} atlas files, {len(atlas.designs_of(self.runs))} designs."
        )
        self.request()
        return len(self.runs)

    def open_file(self, path: Path) -> None:
        """Load one file as A (and list its sibling runs so B and the seed can be chosen)."""
        self.runs = []
        for base in (path.parent.parent.parent, path.parent):
            self.runs = atlas.find_runs(base)
            if any(r.path == path for r in self.runs):
                break
        match = next((r for r in self.runs if r.path == path), None)
        if match is None:
            self.runs = [*self.runs, *self._single(path)]
            match = next((r for r in self.runs if r.path == path), None)
        if match is None:
            self._paths = {"a": path}
            self._begin(path, None)
            return
        self._fill_designs(match.design, match.arm, match.seed)
        self.request()

    @staticmethod
    def _single(path: Path) -> list[RunFile]:
        try:
            a = atlas.load_atlas(path)
        except AtlasError:
            return []
        return [RunFile(a.design, a.arm, a.seed, path)]

    def _fill_designs(self, design: str, arm: str | None = None, seed: int | None = None) -> None:
        self.design.blockSignals(True)
        self.design.clear()
        self.design.addItems(atlas.designs_of(self.runs))
        self.design.setCurrentText(design)
        self.design.blockSignals(False)
        self._fill_arms(arm, seed)

    def _fill_arms(self, arm: str | None = None, seed: int | None = None) -> None:
        design = self.design.currentText()
        arms = atlas.arms_of(self.runs, design)
        for combo in (self.arm_a, self.arm_b, self.seed):
            combo.blockSignals(True)
            combo.clear()
        self.arm_a.addItems(arms)
        self.arm_b.addItems(arms)
        a = arm if arm in arms else arms[0]
        self.arm_a.setCurrentText(a)
        other = next((x for x in arms if x != a), a)
        self.arm_b.setCurrentText(other)
        seeds = atlas.seeds_of(self.runs, design, a)
        self.seed.addItems([str(s) for s in seeds])
        if seed is not None and seed in seeds:
            self.seed.setCurrentText(str(seed))
        for combo in (self.arm_a, self.arm_b, self.seed):
            combo.blockSignals(False)

    def _design_changed(self) -> None:
        self._fill_arms()
        self.request()

    def _paths_wanted(self) -> dict[str, Path]:
        """Role -> file for A and (if the view needs it) B; B uses the same seed, else its
        first seed."""
        design = self.design.currentText()
        seed = int(self.seed.currentText()) if self.seed.currentText() else 0
        out: dict[str, Path] = {}
        a = atlas.path_of(self.runs, design, self.arm_a.currentText(), seed)
        if a is not None:
            out["a"] = a
        if self.mode.currentIndex() > 0:
            arm_b = self.arm_b.currentText()
            seeds = atlas.seeds_of(self.runs, design, arm_b)
            b_seed = seed if seed in seeds else (seeds[0] if seeds else seed)
            b = atlas.path_of(self.runs, design, arm_b, b_seed)
            if b is not None:
                out["b"] = b
        return out

    # ------------------------------------------------------------ loading

    def request(self) -> None:
        """Load what the selections name (from the cache when possible), then draw."""
        wanted = self._paths_wanted()
        if "a" not in wanted:
            self.status.setText("No file for the selected design, arm and seed.")
            self.finished.emit(False)
            return
        self._paths = wanted
        self._begin(wanted["a"], wanted.get("b"))

    def _begin(self, a: Path, b: Path | None) -> None:
        self._token += 1
        self._load_s = 0.0
        self._pending = {}
        self.atlas_a = self._cache.get(a)
        self.atlas_b = self._cache.get(b) if b is not None else None
        for role, path in (("a", a), ("b", b)):
            if path is not None and path not in self._cache:
                self._pending[role] = path
                self._pool.start(_LoadTask(self._token, role, path, self._signals))
        if self._pending:
            self.status.setText(
                "Loading " + ", ".join(p.name for p in self._pending.values()) + "..."
            )
        else:
            self._render()

    def _on_loaded(self, token: int, role: str, a: object, seconds: float) -> None:
        if token != self._token or not isinstance(a, Atlas):
            return
        path = self._pending.pop(role, None)
        if path is None:
            return
        if len(self._cache) >= CACHE_LIMIT:
            self._cache.pop(next(iter(self._cache)))
        self._cache[path] = a
        self._load_s += seconds
        if role == "a":
            self.atlas_a = a
        else:
            self.atlas_b = a
        if not self._pending:
            self._render()

    def _on_failed(self, token: int, reason: str) -> None:
        if token != self._token:
            return
        self._pending = {}
        self.status.setText(reason)
        self.finished.emit(False)

    # ------------------------------------------------------------ drawing

    def _key_changed(self) -> None:
        self._fill_values()
        self.redraw()

    def _fill_values(self) -> None:
        self.values.blockSignals(True)
        self.values.clear()
        key = self.key.currentText()
        if self.atlas_a is not None and key in atlas.CATEGORICAL_KEYS:
            sp = atlas.spread(self.atlas_a, key)
            for v in atlas.category_order(self.atlas_a, key):
                item = QListWidgetItem(f"{v}  ({sp[v]} CLBs)")
                item.setData(Qt.ItemDataRole.UserRole, v)
                self.values.addItem(item)
        self.values.blockSignals(False)

    def selected_value(self) -> str | None:
        items = self.values.selectedItems()
        if not items:
            return None
        v = items[0].data(Qt.ItemDataRole.UserRole)
        return v if isinstance(v, str) else None

    def _render(self) -> None:
        self.last_load_s = self._load_s
        self._fill_values()
        self.redraw()
        self.finished.emit(self.atlas_a is not None)

    def _highlight(self, a: Atlas | None) -> set[int]:
        v = self.selected_value()
        key = self.key.currentText()
        if a is None or v is None or key not in atlas.CATEGORICAL_KEYS:
            return set()
        return atlas.clbs_with(a, key, v)

    def redraw(self) -> None:
        """Draw the current atlases for the chosen key, mode and highlight; sets last_draw_s."""
        t0 = time.perf_counter()
        a, b, mode, key = (
            self.atlas_a,
            self.atlas_b,
            self.mode.currentIndex(),
            self.key.currentText(),
        )
        if a is None:
            return
        self.view_b.setVisible(mode != 0)
        self.label_b.setVisible(mode != 0)
        if mode == 2 and b is not None:
            self._draw_diff(a, b)
        else:
            self._draw_one(self.view_a, self.label_a, a, key)
            if mode == 1 and b is not None:
                self._draw_one(self.view_b, self.label_b, b, key)
            self.info.setText(atlas.summary_text(a))
        self.view_a.render_check()
        if mode != 0:
            self.view_b.render_check()
        self.last_draw_s = time.perf_counter() - t0
        self.status.setText(
            f"{a.design}: {len(a.clbs)} CLBs; load {self.last_load_s * 1000:.0f} ms, "
            f"draw {self.last_draw_s * 1000:.0f} ms."
        )

    def _draw_one(self, view: GridView, label: QLabel, a: Atlas, key: str) -> None:
        label.setText(f"{a.arm} seed {a.seed}  CPD {_ns(a.cpd_ns)}  WL {_num(a.wirelength)}")
        view.show_atlas(a, atlas.clb_colours(a, key), self._highlight(a))

    def _draw_diff(self, a: Atlas, b: Atlas) -> None:
        moved = atlas.moved_atoms(a, b)
        names = set(moved)
        self._draw_one(self.view_a, self.label_a, a, self.key.currentText())
        self.label_b.setText(f"{b.arm} seed {b.seed}: CLBs shaded by share of moved atoms")
        extra = {c.id: _moved_lines(b, c, moved) for c in b.clbs}
        self.view_b.show_atlas(b, atlas.diff_colours(b, names), self._highlight(b), extra)
        self.info.setText(atlas.diff_summary(a, b))


def _moved_lines(
    b: Atlas, clb: atlas.Clb, moved: dict[str, tuple[tuple[int, int], tuple[int, int]]]
) -> str:
    lines = []
    for i in clb.atoms:
        name = b.atoms[i].name
        if name in moved:
            (x0, y0), _ = moved[name]
            lines.append(f"moved: {name} from ({x0}, {y0})")
    return "\n".join(lines[:8])


def _ns(v: float | None) -> str:
    return "-" if v is None else f"{v:.2f} ns"


def _num(v: float | None) -> str:
    return "-" if v is None else f"{v:.0f}"
