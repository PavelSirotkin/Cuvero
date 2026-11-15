"""Output dialogs laid out like the original's: Gerber, Excellon, drill list, image export."""

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

import core
from core import drill, gerber

from .settings import read_bool, read_float, read_int, read_str
from .style import LAYERS, OPTIONS, VALUE_STYLE

# (file ending, label, colour layer)
GERBER_LAYERS = (
    ("copper_top", "C1 — медь сверху", 1),
    ("copper_bottom", "C2 — медь снизу", 3),
    ("silkscreen_top", "S1 — шелкография сверху", 2),
    ("silkscreen_bottom", "S2 — шелкография снизу", 4),
    ("copper_inner1", "I1 — медь внутри 1", 5),
    ("copper_inner2", "I2 — медь внутри 2", 6),
    ("soldermask_top", "C1 — паяльная маска", 1),
    ("soldermask_bottom", "C2 — паяльная маска", 3),
    ("smdmask_top", "C1 — трафарет пасты (SMD)", 1),
    ("smdmask_bot", "C2 — трафарет пасты (SMD)", 3),
    ("outline", "O — контур платы", 7),
)
INFO_STYLE = "color: #0000a0;"


def swatch(layer: int) -> QLabel:
    """A small colour box of a layer, as the original shows next to layer names."""
    label = QLabel()
    label.setFixedSize(18, 13)
    colour = "#ffffff" if layer == 7 else LAYERS[layer][1]
    label.setStyleSheet(f"background: {colour}; border: 1px solid #606060;")
    return label


def mm_field(value: float, minimum: float = -5.0, maximum: float = 5.0) -> QDoubleSpinBox:
    """Black value field with yellow digits and small arrows, like the original's."""
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(2)
    box.setSingleStep(0.05)
    box.setValue(value)
    box.setAlignment(Qt.AlignmentFlag.AlignRight)
    box.setFixedWidth(68)
    box.setStyleSheet(VALUE_STYLE)
    return box


def with_unit(box: QWidget, unit: str = "мм") -> QHBoxLayout:
    line = QHBoxLayout()
    line.setSpacing(4)
    line.addWidget(box)
    line.addWidget(QLabel(unit))
    line.addStretch()
    return line


def ok_cancel(dialog, ok_text="ОК"):
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    box.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


buttons = ok_cancel  # older name


def layer_has_objects(board: core.Board, ending: str) -> bool:
    elements = [obj for obj in board.elements if not core.is_hidden_label(obj)]
    plated = any(obj.kind == core.THT and obj.plated and obj.inner > 0 for obj in elements)
    if ending in ("copper_inner1", "copper_inner2"):
        return board.multilayer
    if ending in ("copper_top", "copper_bottom"):
        layer = 1 if ending == "copper_top" else 3
        return plated or any(obj.layer == layer for obj in elements)
    if ending.startswith("silkscreen"):
        layer = 2 if ending.endswith("top") else 4
        return any(obj.layer == layer for obj in elements)
    if ending == "outline":
        return any(obj.layer == 7 for obj in elements)
    side = 1 if ending.endswith("top") else 3
    if ending.startswith("smdmask"):
        return any(obj.kind == core.SMD and obj.layer == side for obj in elements)
    return any(
        obj.soldermask and (obj.layer == side or (obj.kind == core.THT and obj.plated))
        for obj in elements
    )


class EndingsDialog(QDialog):
    """File name endings of the Gerber layers."""

    def __init__(self, parent, endings: dict[str, str]):
        super().__init__(parent)
        self.setWindowTitle("Окончания имён файлов Gerber")
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        self.edits = {}
        for row, (ending, label, layer) in enumerate(GERBER_LAYERS):
            grid.addWidget(swatch(layer), row, 0)
            grid.addWidget(QLabel(label), row, 1)
            edit = QLineEdit(endings.get(ending, ending))
            grid.addWidget(edit, row, 2)
            self.edits[ending] = edit
        layout.addLayout(grid)
        line = QHBoxLayout()
        defaults = QPushButton("По умолчанию")
        defaults.clicked.connect(self.defaults)
        line.addWidget(defaults)
        line.addStretch()
        line.addWidget(ok_cancel(self))
        layout.addLayout(line)

    def defaults(self):
        for ending, edit in self.edits.items():
            edit.setText(ending)

    def endings(self) -> dict[str, str]:
        return {ending: edit.text().strip() or ending for ending, edit in self.edits.items()}


class GerberDialog(QDialog):
    """Gerber export: layers on the left, options on the right, output folder below.

    The dialog stays open after writing and lists the created files, like the original.
    """

    def __init__(self, parent, settings, board, project_name, boards, folder):
        super().__init__(parent)
        self.settings, self.board = settings, board
        self.boards = boards
        self.setWindowTitle("Экспорт Gerber")
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        layout.addLayout(top)

        group = QGroupBox("Слои")
        grid = QGridLayout(group)
        grid.setVerticalSpacing(7)
        self.layers: dict[str, QCheckBox] = {}
        for row, (ending, label, colour) in enumerate(GERBER_LAYERS):
            check = QCheckBox(label)
            available = layer_has_objects(board, ending)
            default = not ending.startswith(("smdmask", "copper_inner"))
            check.setChecked(available and read_bool(settings, f"gerber/use_{ending}", default))
            check.setEnabled(available)
            check.toggled.connect(self.update_states)
            grid.addWidget(swatch(colour), row, 0)
            grid.addWidget(check, row, 1)
            self.layers[ending] = check
        rows = len(GERBER_LAYERS)
        self.frame = QCheckBox("С рамкой (размер платы)")
        self.frame.setChecked(read_bool(settings, "gerber/frame", False))
        grid.addWidget(self.frame, rows, 1)
        grid.addWidget(QLabel("Имя файла:"), rows + 1, 0, 1, 2)
        names = QHBoxLayout()
        self.prefix = QLineEdit(project_name)
        endings_button = QPushButton("Окончания имён…")
        endings_button.clicked.connect(self.edit_endings)
        names.addWidget(self.prefix, 1)
        names.addWidget(endings_button)
        grid.addLayout(names, rows + 2, 0, 1, 2)
        top.addWidget(group, 3)

        right = QVBoxLayout()
        top.addLayout(right, 2)
        group = QGroupBox("Параметры")
        box = QVBoxLayout(group)
        self.mirror = QCheckBox("Зеркально")
        self.mirror.setChecked(read_bool(settings, "gerber/mirror", False))
        self.cut_holes = QCheckBox("Вырезать отверстия")
        self.punch = QCheckBox("Метка центра (0,15 мм)")
        holes = read_int(settings, "gerber/holes", 0)
        self.cut_holes.setChecked(holes > 0)
        self.punch.setChecked(holes == 1)
        self.cut_holes.toggled.connect(self.update_states)
        self.x2 = QCheckBox("Gerber X2 (атрибуты)")
        self.x2.setToolTip("Без галочки — обычный RS-274X без атрибутов, для старого оборудования")
        self.x2.setChecked(read_bool(settings, "gerber/x2", True))
        self.x2.toggled.connect(self.update_states)
        box.addWidget(self.mirror)
        box.addWidget(self.cut_holes)
        punch_line = QHBoxLayout()
        punch_line.addSpacing(18)
        punch_line.addWidget(self.punch)
        box.addLayout(punch_line)
        box.addWidget(self.x2)
        right.addWidget(group)

        self.mask_group = QGroupBox("Отступ паяльной маски")
        grid = QGridLayout(self.mask_group)
        self.mask_rows: dict[str, tuple[QCheckBox, QDoubleSpinBox]] = {}
        for row, (key, label, value) in enumerate(
            (("pads", "Площадки", 0.3), ("smd", "SMD-площадки", 0.1), ("other", "Прочее", 0.1))
        ):
            check = QCheckBox(label)
            check.setChecked(read_bool(settings, f"gerber/mask_{key}_on", True))
            field = mm_field(read_float(settings, f"gerber/mask_{key}", value))
            grid.addWidget(check, row, 0)
            grid.addLayout(with_unit(field), row, 1)
            self.mask_rows[key] = (check, field)
        self.mask_inverted = QCheckBox("Инвертировать")
        self.mask_inverted.setChecked(read_bool(settings, "gerber/mask_inverted", False))
        grid.addWidget(self.mask_inverted, 3, 0, 1, 2)
        right.addWidget(self.mask_group)

        self.paste_group = QGroupBox("Отступ трафарета пасты (SMD)")
        box = QVBoxLayout(self.paste_group)
        self.paste = mm_field(read_float(settings, "gerber/paste", 0.0))
        self.paste_inverted = QCheckBox("Инвертировать")
        self.paste_inverted.setChecked(read_bool(settings, "gerber/paste_inverted", False))
        box.addLayout(with_unit(self.paste))
        box.addWidget(self.paste_inverted)
        right.addWidget(self.paste_group)
        right.addStretch()
        self.about = QLabel()
        self.about.setWordWrap(True)
        right.addWidget(self.about)
        right.addStretch()

        layout.addWidget(QLabel("Папка вывода:"))
        folder_line = QHBoxLayout()
        folder_line.setSpacing(0)
        self.folder = QLabel(read_str(settings, "gerber/folder", "") or str(folder))
        self.folder.setStyleSheet(
            "background: #cce4f7; border: 1px solid #7a9cc6; padding: 4px; font-weight: bold;"
        )
        change = QPushButton("← Изменить…")
        change.clicked.connect(self.choose_folder)
        folder_line.addWidget(self.folder, 1)
        folder_line.addWidget(change)
        layout.addLayout(folder_line)
        self.created = QPlainTextEdit("Созданные файлы:")
        self.created.setReadOnly(True)
        self.created.setMinimumHeight(110)
        layout.addWidget(self.created)
        line = QHBoxLayout()
        line.addStretch()
        self.create_button = QPushButton("Создать файлы Gerber…")
        self.create_button.clicked.connect(self.create_files)
        close = QPushButton("Закрыть")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        for push in (self.create_button, close):
            push.setMinimumWidth(150)
            line.addWidget(push)
        layout.addLayout(line)
        self.endings = {
            ending: read_str(settings, f"gerber/name_{ending}", ending)
            for ending, _, _ in GERBER_LAYERS
        }
        self.update_states()

    def update_states(self, *_args):
        chosen = {ending for ending, check in self.layers.items() if check.isChecked()}
        self.frame.setEnabled("outline" in chosen)
        self.punch.setEnabled(self.cut_holes.isChecked())
        self.mask_group.setEnabled(bool(chosen & {"soldermask_top", "soldermask_bottom"}))
        self.paste_group.setEnabled(bool(chosen & {"smdmask_top", "smdmask_bot"}))
        self.create_button.setEnabled(bool(chosen))
        if self.x2.isChecked():
            kind = "Gerber X2 (расширенный RS-274X с атрибутами)"
        else:
            kind = "расширенный Gerber RS-274X"
        self.about.setText(f"Cuvero выводит {kind}.")

    def edit_endings(self):
        dialog = EndingsDialog(self, self.endings)
        if dialog.exec():
            self.endings = dialog.endings()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Папка для файлов Gerber", self.folder.text()
        )
        if folder:
            self.folder.setText(folder)

    def options(self) -> gerber.GerberOptions:
        def offset(key):
            check, box = self.mask_rows[key]
            return box.value() if check.isChecked() else None

        holes = "none"
        if self.cut_holes.isChecked():
            holes = "punch" if self.punch.isChecked() else "clear"
        return gerber.GerberOptions(
            x2=self.x2.isChecked(),
            mirror=self.mirror.isChecked(),
            frame=self.frame.isChecked() and self.frame.isEnabled(),
            holes=holes,
            mask_pads=offset("pads"),
            mask_smd=offset("smd"),
            mask_other=offset("other"),
            mask_inverted=self.mask_inverted.isChecked(),
            paste_offset=self.paste.value(),
            paste_inverted=self.paste_inverted.isChecked(),
            use_origin=OPTIONS.get("cam_origin", True),
        )

    def remember(self):
        s = self.settings
        s.setValue("gerber/x2", self.x2.isChecked())
        s.setValue("gerber/mirror", self.mirror.isChecked())
        s.setValue("gerber/frame", self.frame.isChecked())
        holes = 0
        if self.cut_holes.isChecked():
            holes = 1 if self.punch.isChecked() else 2
        s.setValue("gerber/holes", holes)
        for key, (check, box) in self.mask_rows.items():
            s.setValue(f"gerber/mask_{key}_on", check.isChecked())
            s.setValue(f"gerber/mask_{key}", box.value())
        s.setValue("gerber/mask_inverted", self.mask_inverted.isChecked())
        s.setValue("gerber/paste", self.paste.value())
        s.setValue("gerber/paste_inverted", self.paste_inverted.isChecked())
        s.setValue("gerber/folder", self.folder.text())
        for ending, check in self.layers.items():
            if check.isEnabled():
                s.setValue(f"gerber/use_{ending}", check.isChecked())
            s.setValue(f"gerber/name_{ending}", self.endings[ending])

    def write(self) -> list[Path]:
        """Write the chosen files; returns their paths."""
        folder = Path(self.folder.text())
        folder.mkdir(parents=True, exist_ok=True)
        options = self.options()
        written = []
        for ending, check in self.layers.items():
            if not check.isChecked():
                continue
            text = gerber.layer_gerber(self.board, ending, options)
            name = gerber.file_name(
                self.prefix.text(), self.board.name, self.endings[ending], self.boards
            )
            path = folder / name
            path.write_bytes(text.encode("utf-8"))
            written.append(path)
        return written

    def create_files(self):
        self.remember()
        try:
            written = self.write()
        except OSError as error:
            QMessageBox.warning(self, "Не удалось записать файлы", str(error))
            return
        self.created.setPlainText("Созданные файлы:\n" + "\n".join(p.name for p in written))


class DrillDialog(QDialog):
    """Excellon export, laid out like the original's."""

    # (format, inch, unit, note); the original lists 3.2 mm, 3.3 mm and 2.4 inch.
    FORMATS = (
        ("3.2", False, "мм", "(формат 3.2)"),
        ("3.3", False, "мм", "(формат 3.3)"),
        ("2.4", True, "дюймы", "(формат 2.4)"),
    )

    def __init__(self, parent, settings):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Экспорт Excellon")
        layout = QVBoxLayout(self)
        note = QLabel("Сверловка выводится в формате EXCELLON.")
        note.setStyleSheet(INFO_STYLE)
        layout.addWidget(note)

        group = QGroupBox("Выбор")
        box = QVBoxLayout(group)
        self.unplated = QCheckBox("Простые отверстия")
        self.plated = QCheckBox("Металлизированные отверстия")
        self.unplated.setChecked(read_bool(settings, "drill/unplated", True))
        self.plated.setChecked(read_bool(settings, "drill/plated", True))
        box.addWidget(self.unplated)
        box.addWidget(self.plated)
        layout.addWidget(group)

        group = QGroupBox("Сверлить…")
        box = QVBoxLayout(group)
        self.side = QButtonGroup(group)
        for index, label in enumerate(
            (
                "Сверху (по умолчанию)",
                "Снизу (зеркально по X, как Gerber)",
                "Снизу (зеркально по X, как HPGL)",
            )
        ):
            button = QRadioButton(label)
            self.side.addButton(button, index)
            box.addWidget(button)
        side = self.side.button(read_int(settings, "drill/side", 0)) or self.side.button(0)
        side.setChecked(True)
        self.sort = QCheckBox("Упорядочить отверстия")
        self.sort.setChecked(read_bool(settings, "drill/sort", True))
        box.addWidget(self.sort)
        layout.addWidget(group)

        group = QGroupBox("Единицы")
        grid = QGridLayout(group)
        self.format = QButtonGroup(group)
        for index, (_, _, unit, note_text) in enumerate(self.FORMATS):
            button = QRadioButton(unit)
            self.format.addButton(button, index)
            grid.addWidget(button, index, 0)
            hint = QLabel(note_text)
            hint.setStyleSheet(INFO_STYLE)
            grid.addWidget(hint, index, 1)
        chosen = self.format.button(read_int(settings, "drill/format2", 1))
        (chosen or self.format.button(1)).setChecked(True)
        self.leading = QCheckBox("Убрать ведущие нули")
        self.leading.setChecked(read_bool(settings, "drill/strip_zeros", False))
        self.point = QCheckBox("С десятичной точкой")
        self.point.setChecked(read_bool(settings, "drill/point", True))
        grid.addWidget(self.leading, 3, 0, 1, 2)
        grid.addWidget(self.point, 4, 0, 1, 2)
        layout.addWidget(group)

        group = QGroupBox("Особые параметры")
        box = QVBoxLayout(group)
        self.m71 = QCheckBox("M71/72 вместо METRIC/INCH")
        self.no_g90 = QCheckBox("Без кода G90")
        self.no_comments = QCheckBox("Без комментариев")
        for key, widget in (
            ("m71", self.m71),
            ("no_g90", self.no_g90),
            ("no_comments", self.no_comments),
        ):
            widget.setChecked(read_bool(settings, f"drill/{key}", False))
            box.addWidget(widget)
        layout.addWidget(group)
        layout.addWidget(ok_cancel(self))

    def options(self) -> drill.DrillOptions:
        fmt, inch, _, _ = self.FORMATS[self.format.checkedId()]
        return drill.DrillOptions(
            format=fmt,
            inch=inch,
            leading_zeros=not self.leading.isChecked(),
            decimal_point=self.point.isChecked(),
            plated=self.plated.isChecked(),
            unplated=self.unplated.isChecked(),
            side=("top", "bottom_gerber", "bottom_hpgl")[self.side.checkedId()],
            sort=self.sort.isChecked(),
            use_origin=OPTIONS.get("cam_origin", True),
            m71=self.m71.isChecked(),
            comments=not self.no_comments.isChecked(),
            g90=not self.no_g90.isChecked(),
        )

    def remember(self):
        s = self.settings
        s.setValue("drill/format2", self.format.checkedId())
        s.setValue("drill/strip_zeros", self.leading.isChecked())
        s.setValue("drill/point", self.point.isChecked())
        s.setValue("drill/unplated", self.unplated.isChecked())
        s.setValue("drill/plated", self.plated.isChecked())
        s.setValue("drill/sort", self.sort.isChecked())
        s.setValue("drill/side", self.side.checkedId())
        s.setValue("drill/m71", self.m71.isChecked())
        s.setValue("drill/no_comments", self.no_comments.isChecked())
        s.setValue("drill/no_g90", self.no_g90.isChecked())


class HoleListDialog(QDialog):
    """Drill list as plain text, like the original's: count × diameter, then the total."""

    def __init__(self, parent, board):
        super().__init__(parent)
        self.board = board
        self.setWindowTitle("Отверстия")
        layout = QVBoxLayout(self)
        self.unplated = QCheckBox("Простые отверстия")
        self.plated = QCheckBox("Площадки с отверстием")
        for check in (self.unplated, self.plated):
            check.setChecked(True)
            check.toggled.connect(self.refresh)
            layout.addWidget(check)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        font = QFont("Courier New")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(10)
        self.view.setFont(font)
        layout.addWidget(self.view)
        line = QHBoxLayout()
        copy = QPushButton("В буфер обмена…")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.text))
        ok = QPushButton("ОК")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        line.addWidget(copy)
        line.addStretch()
        line.addWidget(ok)
        layout.addLayout(line)
        self.resize(250, 350)
        self.refresh()

    def refresh(self, *_args):
        counts: dict[float, int] = {}
        for diameter, _pad in core.holes(
            self.board, self.plated.isChecked(), self.unplated.isChecked()
        ):
            counts[diameter] = counts.get(diameter, 0) + 1
        rows = [f"{counts[d]:4d} x {d:5.2f} мм".replace(".", ",") for d in sorted(counts)]
        total = sum(counts.values())
        self.text = "\n".join([*rows, "-" * 16, f"{total:4d} отв."])
        self.view.setPlainText(self.text)


class ImageDialog(QDialog):
    """Bitmap export: resolution slider, size figures, black-and-white or colour."""

    STEPS = (75, 100, 150, 200, 300, 400, 600, 800, 1000, 1200, 1600, 2400)

    def __init__(self, parent, settings, width_mm, height_mm):
        super().__init__(parent)
        self.settings = settings
        self.width_mm, self.height_mm = width_mm, height_mm
        self.setWindowTitle("Экспорт изображения (все видимые слои)")
        layout = QHBoxLayout(self)
        group = QGroupBox("Разрешение")
        grid = QGridLayout(group)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, len(self.STEPS) - 1)
        dpi = read_int(settings, "image/dpi", 600)
        self.slider.setValue(min(range(len(self.STEPS)), key=lambda i: abs(self.STEPS[i] - dpi)))
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        grid.addWidget(self.slider, 0, 0, 1, 2)
        low, high = QLabel("низкое"), QLabel("высокое")
        for label in (low, high):
            label.setStyleSheet(INFO_STYLE)
        grid.addWidget(low, 1, 0)
        grid.addWidget(high, 1, 1, Qt.AlignmentFlag.AlignRight)
        self.figures = {}
        captions = (
            ("size", "Размер:"),
            ("dpi", "Разрешение:"),
            ("pixels", "Точек:"),
            ("memory", "Память:"),
        )
        for row, (key, caption) in enumerate(captions, 2):
            grid.addWidget(QLabel(caption), row, 0)
            value = QLabel()
            grid.addWidget(value, row, 1)
            self.figures[key] = value
        layout.addWidget(group, 1)
        right = QVBoxLayout()
        group = QGroupBox("Цвет")
        box = QVBoxLayout(group)
        self.mono = QRadioButton("Ч/Б")
        self.color = QRadioButton("Цветное")
        (self.mono if read_bool(settings, "image/mono", False) else self.color).setChecked(True)
        box.addWidget(self.mono)
        box.addWidget(self.color)
        right.addWidget(group)
        right.addStretch()
        ok = QPushButton("ОК")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        right.addWidget(ok)
        right.addWidget(cancel)
        layout.addLayout(right)
        self.slider.valueChanged.connect(self.update_figures)
        self.update_figures()

    def dpi(self) -> int:
        return self.STEPS[self.slider.value()]

    def image_size(self) -> QSize:
        scale = self.dpi() / 25.4
        return QSize(max(1, round(self.width_mm * scale)), max(1, round(self.height_mm * scale)))

    def update_figures(self, *_args):
        size = self.image_size()
        self.figures["size"].setText(
            f"{self.width_mm:.1f} × {self.height_mm:.1f} мм".replace(".", ",")
        )
        self.figures["dpi"].setText(f"{self.dpi()} точек на дюйм")
        self.figures["pixels"].setText(f"{size.width()} × {size.height()}")
        self.figures["memory"].setText(f"{size.width() * size.height() * 4 // 1024} КБ")

    def remember(self):
        self.settings.setValue("image/dpi", self.dpi())
        self.settings.setValue("image/mono", self.mono.isChecked())


MONO_LEVELS = bytes(255 if level > 24 else 0 for level in range(256))


def scene_image(scene, source: QRectF, size: QSize, mono: bool, background: QColor) -> QImage:
    image = QImage(size, QImage.Format.Format_RGB32)
    image.fill(background)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scene.render(painter, QRectF(0, 0, size.width(), size.height()), source)
    painter.end()
    if mono:
        # Everything drawn turns white on black, as a film for exposure.
        image = image.convertToFormat(QImage.Format.Format_Grayscale8)
        buffer = memoryview(image.bits())
        buffer[:] = bytes(buffer).translate(MONO_LEVELS)
    return image


def save_message(parent, paths):
    QMessageBox.information(
        parent,
        "Файлы созданы",
        "Записаны файлы:\n" + "\n".join(str(p) for p in paths),
    )
