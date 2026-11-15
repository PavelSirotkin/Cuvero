"""The component dialog: name and value labels, package, comment, dissolving."""

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

import core

from .style import LAYERS

LABEL_LAYERS = (2, 4, 1, 3, 7)  # silk first, as the original offers them


class ComponentDialog(QDialog):
    DISSOLVE = 2  # result code: dissolve the component

    def __init__(self, parent, elements, cid):
        super().__init__(parent)
        self.setWindowTitle("Компонент")
        ref, value = core.component_labels(elements, cid)
        self.ref = elements[ref] if ref is not None else None
        self.value = elements[value] if value is not None else None
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        layout.addLayout(grid)
        grid.addWidget(QLabel("Видимый"), 0, 2)
        grid.addWidget(QLabel("Слой"), 0, 3)
        self.ref_text, self.ref_visible, self.ref_layer = self.label_row(
            grid, 1, "Обозначение:", self.ref
        )
        self.value_text, self.value_visible, self.value_layer = self.label_row(
            grid, 2, "Номинал:", self.value
        )
        grid.addWidget(QLabel("Высота текста:"), 3, 0)
        self.height_box = QDoubleSpinBox()
        self.height_box.setRange(*core.HEIGHT_RANGE)
        self.height_box.setDecimals(2)
        self.height_box.setSingleStep(0.1)
        self.height_box.setSuffix(" мм")
        self.height_box.setValue(self.ref.outer if self.ref else core.TEXT_HEIGHT)
        grid.addWidget(self.height_box, 3, 1)
        grid.addWidget(QLabel("Корпус:"), 4, 0)
        self.package = QLineEdit(core.component_package(elements, cid))
        grid.addWidget(self.package, 4, 1, 1, 3)
        grid.addWidget(QLabel("Комментарий:"), 5, 0)
        self.comment = QLineEdit(core.component_comment(self.ref) if self.ref else "")
        grid.addWidget(self.comment, 5, 1, 1, 3)
        angle = core.component_rotation(self.ref) if self.ref else 0.0
        grid.addWidget(QLabel("Поворот:"), 6, 0)
        grid.addWidget(QLabel(f"{angle:g}°"), 6, 1)
        dissolve = QPushButton("Расформировать компонент")
        dissolve.setToolTip("Объекты компонента станут обычными, обозначение и номинал удалятся")
        dissolve.clicked.connect(lambda: self.done(self.DISSOLVE))
        layout.addWidget(dissolve)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if self.ref is None or self.value is None:
            for widget in (self.ref_text, self.value_text, self.height_box):
                widget.setEnabled(False)

    def label_row(self, grid, row, caption, label):
        grid.addWidget(QLabel(caption), row, 0)
        text = QLineEdit(label.text if label else "")
        visible = QCheckBox()
        visible.setChecked(bool(label and label.filled))
        layer = QComboBox()
        for code in LABEL_LAYERS:
            layer.addItem(LAYERS[code][0], code)
        layer.setCurrentIndex(max(layer.findData(label.layer if label else 2), 0))
        grid.addWidget(text, row, 1)
        grid.addWidget(visible, row, 2)
        grid.addWidget(layer, row, 3)
        return text, visible, layer

    def edited(self):
        """New name and value labels, as (old label, new label) pairs."""
        result = []
        height = self.height_box.value()
        for label, text, visible, layer in (
            (self.ref, self.ref_text, self.ref_visible, self.ref_layer),
            (self.value, self.value_text, self.value_visible, self.value_layer),
        ):
            if label is None:
                continue
            code = layer.currentData()
            new = core.with_text(
                label,
                text=text.text(),
                height=height,
                layer=code,
                # Labels on the bottom side read correctly from below.
                mirror_x=code in (3, 4) if code != label.layer else None,
            )
            if new.shape == core.COMPONENT_REF:
                new = core.with_component_details(new, self.package.text(), self.comment.text())
            result.append((label, replace(new, filled=visible.isChecked())))
        return result
