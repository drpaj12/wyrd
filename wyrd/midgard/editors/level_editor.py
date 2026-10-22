"""The Midgard III level editor (spec 8.2), a PySide6 port of LevelEditor.

The level data and the drag rules live in `model/leveldoc.py`; this module draws them. It
imports no pygame. `midgard-editor` starts `main`.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QPaintEvent, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from wyrd.midgard.model import ASSETS
from wyrd.midgard.model.leveldoc import GROUP_TYPES, MIN_SIZE, LevelDoc, MapDrag
from wyrd.midgard.model.levelxml import CarSpec, LevelFormatError, write_level_xml

LEDIT = ASSETS / "editors" / "ledit"
DEFAULT_SIZE = 20
DEFAULT_CELL = 60
EDGE_SIZE = 15
EDGE_MESSAGE = "Can't have intersections on the edge! Level is not saved."
EDGE_MESSAGE_CARS = "Can't have intersections on the edge!"
DONE_MESSAGE = "Finished exporting"
XML_ERROR = "Error when exporting XML file"
IMAGE_ERROR = "Error when exporting map image"
DELAY_MESSAGE = "Please input delay for all cars"
SCREEN_MARGIN = 200


def tile_pixmap(type: str) -> QPixmap:
    return QPixmap(str(LEDIT / f"{type}.png"))


def render_map_image(doc: LevelDoc) -> QImage:
    """MapEditor.exportMapImage: every group drawn from its tile image, north at the top."""
    size = tile_pixmap(GROUP_TYPES[0]).width()
    gw, gh = doc.size_x // 2, doc.size_y // 2
    image = QImage(gw * size, gh * size, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    for gx in range(gw):
        for gy in range(gh):
            painter.drawPixmap(gx * size, (gh - 1 - gy) * size, tile_pixmap(doc.groups[gx][gy]))
    painter.end()
    return image


def export_level(doc: LevelDoc, xml_path: Path) -> list[str]:
    """Write the level XML and `lvNN.png` beside it; returns the messages for the user.

    A document read from a file and left unchanged is written back as the bytes it was read
    from, so hand-formatted shipped levels are not reformatted by an export without edits.
    """
    try:
        data = doc.to_level_data()
    except ValueError:
        return [EDGE_MESSAGE]
    text = doc.source_text if doc.source_text is not None and doc.matches_source() else None
    try:
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        with xml_path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text if text is not None else write_level_xml(data))
    except OSError:
        return [XML_ERROR]
    image = xml_path.parent / f"lv{doc.number:02d}.png"
    if not render_map_image(doc).save(str(image)):
        return [IMAGE_ERROR]
    return [DONE_MESSAGE]


def auto_cell_size(doc: LevelDoc) -> int:
    """MapEditor.setGridSize: shrink the cells when the screen is too small."""
    screen = QApplication.primaryScreen()
    if screen is None:
        return DEFAULT_CELL
    area = screen.size()
    by_width = 2 * (area.width() - 2 * EDGE_SIZE) // doc.size_x
    by_height = 2 * (area.height() - 2 * EDGE_SIZE - SCREEN_MARGIN) // doc.size_y
    return max(16, min(DEFAULT_CELL, by_width, by_height))


# start dialog


@dataclass(frozen=True)
class StartResult:
    update: bool
    number: int
    size_x: int
    size_y: int
    path: Path | None


class StartDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Midgard III Level Editor")
        self.create_radio = QRadioButton("Create")
        self.update_radio = QRadioButton("Update")
        self.create_radio.setChecked(True)
        self.level_edit = QLineEdit()
        self.x_edit = QLineEdit(str(DEFAULT_SIZE))
        self.y_edit = QLineEdit(str(DEFAULT_SIZE))
        self.path_edit = QLineEdit()
        self.chosen: StartResult | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(self.create_radio)
        form = QGridLayout()
        for row, (label, edit) in enumerate(
            (
                ("Level Number", self.level_edit),
                ("Map Size (X)", self.x_edit),
                ("Map Size (Y)", self.y_edit),
            )
        ):
            form.addWidget(QLabel(label), row, 0)
            form.addWidget(edit, row, 1)
        layout.addLayout(form)
        layout.addWidget(self.update_radio)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit)
        self.select_button = QPushButton("Select")
        self.select_button.clicked.connect(self.select_file)
        path_row.addWidget(self.select_button)
        layout.addLayout(path_row)
        buttons = QHBoxLayout()
        ok, cancel = QPushButton("OK"), QPushButton("Cancel")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def select_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select a level", "", "XML Files (*.xml)")
        if path:
            self.path_edit.setText(path)
            self.update_radio.setChecked(True)

    def _fail(self, title: str, text: str) -> None:
        QMessageBox.critical(self, title, text)

    def check(self) -> StartResult | None:
        """Check the input as LevelEditor.clickedOK did; shows the Java message on a problem."""
        if self.update_radio.isChecked():
            return self._update_result()
        return self._create_result()

    def _update_result(self) -> StartResult | None:
        path = Path(self.path_edit.text())
        if not self.path_edit.text() or not path.exists():
            self._fail("File not found", f"File: {self.path_edit.text()} not found")
            return None
        return StartResult(True, 0, 0, 0, path)

    def _create_result(self) -> StartResult | None:
        texts = [e.text().strip() for e in (self.level_edit, self.x_edit, self.y_edit)]
        if not all(texts):
            self._fail("Empty text field(s)", "Text fields must not be empty")
            return None
        try:
            number, size_x, size_y = (int(t) for t in texts)
        except ValueError:
            self._fail("Invalid map size", "Level number and map sizes must be numbers")
            return None
        sizes_ok = all(s >= MIN_SIZE and s % 2 == 0 for s in (size_x, size_y))
        if not sizes_ok or number < 0:
            self._fail(
                "Invalid map size",
                f"Both map sizes must be even numbers of at least {MIN_SIZE}!",
            )
            return None
        return StartResult(False, number, size_x, size_y, None)

    def accept(self) -> None:
        self.chosen = self.check()
        if self.chosen is not None:
            super().accept()


# map widgets


class GridTypeSelector(QDialog):
    """Pick a group type from the list, with a preview (GridTypeSelector.java)."""

    def __init__(self, current: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select the grid type")
        self.current = current
        self.combo = QComboBox()
        self.combo.addItems(list(GROUP_TYPES))
        self.combo.setCurrentText(current)
        self.preview = QLabel()
        self.combo.currentTextChanged.connect(self._show)
        self._show(current)
        layout = QVBoxLayout(self)
        layout.addWidget(self.combo)
        layout.addWidget(self.preview)
        row = QHBoxLayout()
        ok, cancel = QPushButton("OK"), QPushButton("Cancel")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addLayout(row)

    def _show(self, type: str) -> None:
        self.preview.setPixmap(tile_pixmap(type).scaled(120, 120))

    def choose(self) -> str:
        """Run the dialog; the chosen type, or the current one when cancelled."""
        if self.exec() == QDialog.DialogCode.Accepted:
            return self.combo.currentText()
        return self.current


class GroupWidget(QWidget):
    """One 2 by 2 group of cells; it only draws and forwards the mouse to its panel."""

    def __init__(self, panel: MapPanel, gx: int, gy: int) -> None:
        super().__init__(panel)
        self.panel = panel
        self.gx = gx
        self.gy = gy

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        type = self.panel.doc.groups[self.gx][self.gy]
        painter.drawPixmap(self.rect(), self.panel.pixmap(type))
        painter.setPen(QPen(Qt.GlobalColor.red))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.panel.group_press(self, event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.panel.group_move(self, event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.panel.group_release(self, event)


class MapPanel(QWidget):
    """The grid of groups with an edge strip around it; owns the drag state."""

    def __init__(self, doc: LevelDoc, cell_size: int) -> None:
        super().__init__()
        self.doc = doc
        self.cell_size = cell_size
        self.drag = MapDrag(doc)
        self._pixmaps: dict[str, QPixmap] = {}
        self._button = Qt.MouseButton.NoButton
        self._press_cell = (0, 0)
        gw, gh = doc.size_x // 2, doc.size_y // 2
        self.setFixedSize(gw * cell_size + 2 * EDGE_SIZE, gh * cell_size + 2 * EDGE_SIZE)
        self.cells: list[list[GroupWidget]] = []
        for gx in range(gw):
            column = []
            for gy in range(gh):
                cell = GroupWidget(self, gx, gy)
                cell.setGeometry(self._rect(gx, gy))
                column.append(cell)
            self.cells.append(column)

    def _rect(self, gx: int, gy: int) -> QRect:
        rows = self.doc.size_y // 2
        size = self.cell_size
        return QRect(EDGE_SIZE + gx * size, EDGE_SIZE + (rows - 1 - gy) * size, size, size)

    def pixmap(self, type: str) -> QPixmap:
        if type not in self._pixmaps:
            self._pixmaps[type] = tile_pixmap(type)
        return self._pixmaps[type]

    def refresh(self) -> None:
        for column in self.cells:
            for cell in column:
                cell.update()

    def _group_at(self, widget: QWidget, event: QMouseEvent) -> tuple[int, int]:
        spot = widget.mapTo(self, event.position().toPoint())
        size = self.cell_size
        gx = (spot.x() - EDGE_SIZE) // size
        row = (spot.y() - EDGE_SIZE) // size
        return gx, self.doc.size_y // 2 - 1 - row

    def group_press(self, widget: GroupWidget, event: QMouseEvent) -> None:
        self._button = event.button()
        self._press_cell = (widget.gx, widget.gy)
        if self._button in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            erase = self._button == Qt.MouseButton.RightButton
            self.drag.press(widget.gx, widget.gy, erase)

    def group_move(self, widget: GroupWidget, event: QMouseEvent) -> None:
        if not self.drag.active:
            return
        gx, gy = self._group_at(widget, event)
        self.drag.move_to(gx, gy)
        self.refresh()

    def group_release(self, widget: GroupWidget, event: QMouseEvent) -> None:
        gx, gy = self._group_at(widget, event)
        moved = self.drag.moved or (gx, gy) != self._press_cell
        self.drag.release()
        button, self._button = self._button, Qt.MouseButton.NoButton
        if not moved:
            self.click(widget, button)
        self.refresh()

    def click(self, widget: GroupWidget, button: Qt.MouseButton) -> None:
        doc, gx, gy = self.doc, widget.gx, widget.gy
        if button == Qt.MouseButton.LeftButton:
            doc.set_type(gx, gy, GridTypeSelector(doc.groups[gx][gy], self.window()).choose())
        elif button == Qt.MouseButton.MiddleButton:
            doc.rotate_type(gx, gy)
        elif button == Qt.MouseButton.RightButton:
            doc.set_type(gx, gy, "NON_ROAD")


class CarRow(QWidget):
    """One car: id, start and end choices, delay and a remove button (Car.java)."""

    def __init__(self, editor: CarEditor, doc: LevelDoc, spec: CarSpec | None) -> None:
        super().__init__()
        self.editor = editor
        self.id_label = QLabel()
        self.start_box = QComboBox()
        self.end_box = QComboBox()
        self.start_box.addItems(_labels(doc.starts))
        self.end_box.addItems(_labels(doc.ends))
        self.delay_edit = QLineEdit()
        self.delay_edit.setFixedWidth(60)
        remove = QPushButton("-")
        remove.setFixedWidth(24)
        remove.clicked.connect(self.remove)
        row = QHBoxLayout(self)
        for widget in (self.id_label, self.start_box, self.end_box, self.delay_edit, remove):
            row.addWidget(widget)
        if spec is not None:
            self._select(doc, spec)

    def _select(self, doc: LevelDoc, spec: CarSpec) -> None:
        for box, points, point in (
            (self.start_box, doc.starts, spec.start),
            (self.end_box, doc.ends, spec.end),
        ):
            if point not in points:
                box.addItem(f"? ({point[0]}, {point[1]})")
                box.setCurrentIndex(box.count() - 1)
            else:
                box.setCurrentIndex(points.index(point))
        self.delay_edit.setText(str(spec.delay))

    def remove(self) -> None:
        self.editor.remove_row(self)


def _labels(points: list[tuple[int, int]]) -> list[str]:
    return [f"{i} ({x}, {y})" for i, (x, y) in enumerate(points)]


class CarEditor(QDialog):
    """Edit the car list of a document; `Save` checks the list and writes it into `doc.cars`."""

    def __init__(self, doc: LevelDoc, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Cars")
        self.rows: list[CarRow] = []
        self._given = list(doc.cars)
        self._list = QVBoxLayout()
        self._list.setAlignment(Qt.AlignmentFlag.AlignTop)
        holder = QWidget()
        holder.setLayout(self._list)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        add = QPushButton("Add a Car")
        add.clicked.connect(self.add_car)
        save, cancel = QPushButton("Save"), QPushButton("Cancel")
        save.clicked.connect(self.save)
        cancel.clicked.connect(self.cancel)
        layout = QVBoxLayout(self)
        layout.addWidget(add, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(scroll)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self.resize(420, 600)
        for spec in doc.cars:
            self._append(spec)

    def _append(self, spec: CarSpec | None) -> None:
        row = CarRow(self, self.doc, spec)
        self.rows.append(row)
        self._list.addWidget(row)
        self._renumber()

    def _renumber(self) -> None:
        for i, row in enumerate(self.rows):
            row.id_label.setText(str(i))

    def add_car(self) -> None:
        self._append(None)

    def remove_row(self, row: CarRow) -> None:
        self.rows.remove(row)
        self._list.removeWidget(row)
        row.deleteLater()
        self._renumber()

    def _error(self, text: str) -> bool:
        QMessageBox.critical(self, "Error!", text)
        return False

    def _read(self) -> list[CarSpec] | str:
        specs: list[CarSpec] = []
        for row in self.rows:
            text = row.delay_edit.text().strip()
            if not text:
                return DELAY_MESSAGE
            if not text.isdigit() or int(text) < 1:
                return "The delay must be a whole number of at least 1"
            start = _point(row.start_box, self.doc.starts)
            end = _point(row.end_box, self.doc.ends)
            specs.append(CarSpec(start, end, int(text)))
        return specs

    def save(self) -> bool:
        specs = self._read()
        if isinstance(specs, str):
            return self._error(specs)
        clashes = _clashes(specs)
        if clashes:
            lines = "".join(f"Car {i} and {j}\n" for i, j in clashes)
            return self._error(
                "The following cars start at the same place at the same time:\n" + lines
            )
        self.doc.cars = specs
        self.accept()
        return True

    def cancel(self) -> None:
        self.doc.cars = list(self._given)
        self.reject()


def _point(box: QComboBox, points: list[tuple[int, int]]) -> tuple[int, int]:
    index = box.currentIndex()
    if index < len(points):
        return points[index]
    text = box.currentText()
    x, y = text.strip("? ()").split(",")
    return int(x), int(y)


def _clashes(specs: list[CarSpec]) -> list[tuple[int, int]]:
    return [
        (i, j)
        for i, a in enumerate(specs)
        for j, b in enumerate(specs)
        if i < j and a.start == b.start and a.delay == b.delay
    ]


class MapWindow(QMainWindow):
    def __init__(
        self,
        doc: LevelDoc,
        xml_path: Path,
        read_from_xml: bool,
        cell_size: int | None = None,
    ) -> None:
        super().__init__()
        self.doc = doc
        self.xml_path = xml_path
        self.read_from_xml = read_from_xml
        self.cell_size = cell_size if cell_size is not None else auto_cell_size(doc)
        self.setWindowTitle(f"Edit Level {doc.number}")
        self.panel = MapPanel(doc, self.cell_size)
        self.buttons: dict[str, QPushButton] = {}
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.panel, alignment=Qt.AlignmentFlag.AlignCenter)
        row = QHBoxLayout()
        row.addStretch()
        actions = (
            ("Clear Map", self.clear_map),
            ("Edit Cars", self.edit_cars),
            ("Export", self.export),
            ("Cancel", self.close),
        )
        for label, slot in actions:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, s=slot: s())
            self.buttons[label] = button
            row.addWidget(button)
        layout.addLayout(row)
        self.setCentralWidget(central)

    def clear_map(self) -> None:
        self.doc.clear_map()
        self.panel.refresh()

    def edit_cars(self) -> None:
        if not self.doc.populate_starts_ends():
            QMessageBox.critical(self, "Error", EDGE_MESSAGE_CARS)
            return
        CarEditor(self.doc, self).exec()

    def export(self) -> None:
        for message in export_level(self.doc, self.xml_path):
            if message == DONE_MESSAGE:
                QMessageBox.information(self, "Done", message)
            else:
                QMessageBox.critical(self, "Error", message)


def default_xml_path(number: int) -> Path:
    """Where `Create` writes: the layout of the original tool, under the current directory."""
    return Path.cwd() / "Levels" / f"Lv{number}" / "map" / f"lv{number:02d}.xml"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="midgard-editor", description="Midgard III level editor (create or update a level)."
    )
    p.add_argument("level", nargs="?", type=Path, help="a level XML file to update")
    return p


def _open_window(choice: StartResult) -> MapWindow | None:
    if choice.update and choice.path is not None:
        try:
            doc = LevelDoc.from_xml_file(choice.path)
        except (LevelFormatError, ValueError) as exc:
            QMessageBox.critical(None, "Cannot open the level", str(exc))
            return None
        return MapWindow(doc, choice.path, True)
    doc = LevelDoc(choice.number, choice.size_x, choice.size_y)
    return MapWindow(doc, default_xml_path(choice.number), False)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    if args.level is not None:
        choice: StartResult | None = StartResult(True, 0, 0, 0, args.level)
    else:
        dialog = StartDialog()
        choice = dialog.chosen if dialog.exec() == QDialog.DialogCode.Accepted else None
    if choice is None:
        return 0
    window = _open_window(choice)
    if window is None:
        return 2
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    sys.exit(main())
