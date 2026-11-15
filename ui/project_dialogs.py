"""Dialogs for boards and projects: board settings, project information, board choice, autosave."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import core

from .style import mm


def buttons_for(dialog: QDialog) -> QDialogButtonBox:
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


def size_box(value: float) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setDecimals(2)
    box.setRange(1.0, 2000.0)
    box.setSuffix(" мм")
    box.setValue(value)
    box.setMinimumWidth(120)
    return box


class BoardSettingsDialog(QDialog):
    """Name, work-area size and multilayer flag of one board."""

    def __init__(self, parent: QWidget, board: core.Board):
        super().__init__(parent)
        self.setWindowTitle("Настройка платы")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(board.name)
        self.name.setMaxLength(30)
        form.addRow("Имя:", self.name)
        self.width_box = size_box(board.width)
        self.height_box = size_box(board.height)
        form.addRow("Ширина рабочего поля:", self.width_box)
        form.addRow("Высота рабочего поля:", self.height_box)
        self.multilayer = QCheckBox("Многослойная плата (внутренние слои I1 и I2)")
        self.multilayer.setChecked(board.multilayer)
        form.addRow(self.multilayer)
        layout.addLayout(form)
        note = QLabel(
            "Рабочее поле отсчитывается от левого верхнего угла. Объекты за его\n"
            "пределами остаются на месте, их можно удалить через «Дополнительно»."
        )
        note.setStyleSheet("color: #606060;")
        layout.addWidget(note)
        layout.addWidget(buttons_for(self))

    def accept(self) -> None:
        if not self.name.text().strip():
            self.name.setFocus()
            return
        super().accept()

    def board(self, board: core.Board) -> core.Board:
        return core.board_settings(
            board,
            self.name.text().strip(),
            self.width_box.value(),
            self.height_box.value(),
            self.multilayer.isChecked(),
        )


class ProjectInfoDialog(QDialog):
    """Title, author, company and comment stored with the project."""

    def __init__(self, parent: QWidget, info: core.ProjectInfo):
        super().__init__(parent)
        self.setWindowTitle("Сведения о проекте")
        self.resize(460, 380)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.title = self.line(info.title)
        self.author = self.line(info.author)
        self.company = self.line(info.company)
        form.addRow("Название:", self.title)
        form.addRow("Автор:", self.author)
        form.addRow("Организация:", self.company)
        layout.addLayout(form)
        layout.addWidget(QLabel("Комментарий:"))
        self.comment = QPlainTextEdit(info.comment)
        layout.addWidget(self.comment, 1)
        self.counter = QLabel()
        self.counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.counter)
        self.comment.textChanged.connect(self.update_counter)
        self.update_counter()
        layout.addWidget(buttons_for(self))

    @staticmethod
    def line(text: str) -> QLineEdit:
        edit = QLineEdit(text)
        edit.setMaxLength(core.TEXT_LIMIT)
        return edit

    def update_counter(self) -> None:
        length = len(self.comment.toPlainText().replace("\n", "\r\n"))
        self.counter.setText(f"{length} из {core.COMMENT_LIMIT} знаков")
        self.counter.setStyleSheet("color: #c00000;" if length > core.COMMENT_LIMIT else "")

    def info(self) -> core.ProjectInfo:
        return core.ProjectInfo(
            self.title.text(),
            self.author.text(),
            self.company.text(),
            self.comment.toPlainText(),
        )


class BoardPickDialog(QDialog):
    """Choose which boards of another project to load."""

    def __init__(self, parent: QWidget, file_name: str, boards: list[core.Board]):
        super().__init__(parent)
        self.setWindowTitle("Загрузка плат из файла")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Платы в файле «{file_name}»:"))
        self.list = QListWidget()
        for board in boards:
            item = QListWidgetItem(
                f"{board.name}   ({mm(board.width, 1)} x {mm(board.height, 1)} мм, "
                f"объектов {len(board.elements)})"
            )
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(item)
        layout.addWidget(self.list, 1)
        layout.addWidget(buttons_for(self))

    def chosen(self) -> list[int]:
        return [
            row
            for row in range(self.list.count())
            if self.list.item(row).checkState() == Qt.CheckState.Checked
        ]


class AutosaveDialog(QDialog):
    def __init__(self, parent: QWidget, enabled: bool, minutes: int):
        super().__init__(parent)
        self.setWindowTitle("Автосохранение")
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox("Сохранять резервную копию проекта автоматически")
        self.enabled.setChecked(enabled)
        layout.addWidget(self.enabled)
        form = QFormLayout()
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 120)
        self.minutes.setSuffix(" мин")
        self.minutes.setValue(minutes)
        form.addRow("Интервал:", self.minutes)
        layout.addLayout(form)
        note = QLabel(
            "Копия пишется в служебную папку программы, а не рядом с файлом.\n"
            "Если программа закроется аварийно, при следующем открытии проекта\n"
            "будет предложено восстановить несохранённые изменения."
        )
        note.setStyleSheet("color: #606060;")
        layout.addWidget(note)
        self.enabled.toggled.connect(self.minutes.setEnabled)
        self.minutes.setEnabled(enabled)
        layout.addWidget(buttons_for(self))
