"""The main window."""

from dataclasses import replace
from math import hypot
from pathlib import Path

from PySide6.QtCore import QByteArray, QMimeData, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCursor, QKeySequence, QUndoStack
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QStyle,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import core
from version import VERSION

from .board_actions import BoardActions
from .board_view import BoardView, track_nodes
from .commands import AddElements, DeleteElements, EditGeometry, ReplaceBoard
from .component_dialog import ComponentDialog
from .connectivity import net_of
from .draw_dialogs import SpecialFormDialog, TextDialog
from .drc import DrcPanel, check
from .extras_actions import ExtrasActions
from .icons import pad_shape_icon, tool_icon
from .lists import ComponentExportDialog, ComponentsPanel, SelectorPanel
from .macro_panel import MacroPanel
from .options import apply_options
from .output_actions import OutputActions
from .overview import Overview
from .photo import PhotoBar, draw_photo
from .properties_panel import PropertiesPanel
from .render import PLANE, draw_board, point
from .settings import open_settings, read_bool, read_float, read_int, read_str
from .style import (
    APP_NAME,
    GRID_METRIC,
    GRID_STANDARD,
    LAYER_HINTS,
    LAYERS,
    OPTIONS,
    PAD_SHAPES,
    ROTATION_STEPS,
    THROUGH,
    TOOLS,
    mm,
)
from .template import (
    TemplateDialog,
    load_templates,
    save_templates,
    settings_key,
    template_item,
)
from .units import Units
from .widgets import LayerBar, SizeRow, separator, value_box


class MainWindow(QMainWindow, BoardActions, OutputActions, ExtrasActions):
    def __init__(self):
        super().__init__()
        self.settings = open_settings()
        apply_options(self.settings)
        self.boards: list[core.Board] = []
        self.groups = {}
        self.path: Path | None = None
        self.project: core.Project
        self.undo = QUndoStack(self)
        self.undo.setUndoLimit(max(int(OPTIONS["undo_limit"]), 1))
        self.resize(1400, 900)
        self.setWindowTitle(APP_NAME)

        self.units = Units(mil=read_bool(self.settings, "units/mil", False))
        self.coordinates = QLabel()
        self.coordinates.setMinimumWidth(130)
        self.coordinates.setText("X: —\nY: —")
        self.hint = QLabel()
        self.hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.view = BoardView(self.coordinates, self.hint)
        self.view.units = self.units
        self.view.units_clicked.connect(lambda: self.set_units(not self.units.mil))
        self.view.selected.connect(self.show_properties)
        self.view.moved.connect(self.edit_elements)
        self.view.created.connect(self.add_element)
        self.view.macro_dropped.connect(self.place_macro)
        self.view.context_requested.connect(self.context_menu)
        self.view.mask_clicked.connect(self.toggle_mask)
        self.view.picked.connect(self.picked)
        self.wire_start: int | None = None
        self.component_dialog_on_drop = True
        self.view.bend_changed.connect(self.show_bend)
        self.view.activated.connect(self.open_object_dialog)
        self.view.bend_mode = read_str(self.settings, "track/bend", core.BEND_45)
        if self.view.bend_mode not in core.BEND_MODES:
            self.view.bend_mode = core.BEND_45
        self.view.rect_filled = read_bool(self.settings, "rect/filled", False)

        self.view.route_clicked.connect(self.route_click)
        self.view.route_pads.connect(self.route_pads)
        self.view.placed.connect(self.put_down)
        self.build_actions()
        self.build_output_actions()
        self.build_extras_actions()
        self.build_menus()
        self.build_toolbar()
        tools = self.build_tool_panel()

        self.board_select = QTabBar()
        self.board_select.setAccessibleName("Выбор платы")
        self.board_select.setExpanding(False)
        self.board_select.setShape(QTabBar.Shape.TriangularSouth)
        self.board_select.currentChanged.connect(self.show_board)
        self.board_select.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        self.photo_bar = PhotoBar(self.settings, self.redraw_photo)
        self.photo_bar.hide()
        center_layout.addWidget(self.photo_bar)
        center_layout.addWidget(self.route_bar)
        center_layout.addWidget(self.view, 1)
        center_layout.addWidget(self.board_select)

        self.macros = MacroPanel(self.settings)
        self.macros.hidden.connect(lambda: self.macro_action.setChecked(False))
        self.macros.message.connect(self.hint.setText)
        self.macros.save_requested.connect(self.save_macro)
        self.properties = PropertiesPanel(self.units)
        self.properties.hidden.connect(lambda: self.properties_action.setChecked(False))
        self.properties.edited.connect(self.edit_elements)
        self.properties.board_edited.connect(self.replace_current_board)
        self.properties.component_requested.connect(self.edit_component)
        self.selector = SelectorPanel(self.settings)
        self.selector.select.connect(self.select_objects)
        self.components = ComponentsPanel(self.settings)
        self.components.select.connect(self.select_objects)
        self.components.renamed.connect(self.rename_component)
        self.components.export_requested.connect(self.export_components)
        self.drc = DrcPanel(self.settings)
        self.drc.run_requested.connect(self.run_drc)
        self.drc.chosen.connect(self.show_violation)
        self.drc.mark_all.connect(self.mark_violations)
        self.splitter = QSplitter()
        self.splitter.addWidget(center)
        # Side panels in the original's order.
        for panel in (self.selector, self.components, self.properties, self.drc, self.macros):
            self.splitter.addWidget(panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setCollapsible(0, False)
        self.splitter.setSizes([960, 170, 260, 250, 240, 200])
        for panel, toggle, key in (
            (self.selector, self.selector_action, "selector"),
            (self.components, self.components_action, "components"),
            (self.drc, self.drc_action, "drc"),
        ):
            panel.hidden.connect(lambda toggle=toggle: toggle.setChecked(False))
            toggle.toggled.connect(
                lambda on, panel=panel, key=key: self.toggle_panel(panel, key, on)
            )
            shown = read_bool(self.settings, f"{key}/visible", False)
            panel.setVisible(shown)
            toggle.setChecked(shown)
        shown = read_bool(self.settings, "properties/visible", True)
        self.properties.setVisible(shown)
        self.properties_action.setChecked(shown)
        visible = read_bool(self.settings, "macro/visible", True)
        self.macros.setVisible(visible)
        self.macro_action.setChecked(visible)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(tools)
        layout.addWidget(self.splitter, 1)
        self.setCentralWidget(root)
        self.build_status_bar()
        self.set_grid(read_float(self.settings, "grid", 0.1))
        for action in self.board_actions():
            if action is None:
                action = QAction(self)
                action.setSeparator(True)
            self.board_select.addAction(action)
        self.start_project(
            core.new_project(
                core.board_from_dialog("Новая плата", "empty", 160, 100, grid=self.view.grid)
            ),
            None,
        )

    # --- construction ---------------------------------------------------------

    def build_actions(self):
        style = self.style()
        self.build_file_actions()
        self.build_board_actions()
        self.quit_action = QAction("Выход", self)
        self.quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.quit_action.triggered.connect(self.close)
        self.undo_action = self.undo.createUndoAction(self, "Отменить")
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.redo_action = self.undo.createRedoAction(self, "Повторить")
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        self.delete_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_TrashIcon), "Удалить", self
        )
        self.delete_action.setShortcuts(
            [QKeySequence(QKeySequence.StandardKey.Delete), QKeySequence("Backspace")]
        )
        self.delete_action.setToolTip("Удалить выделенный объект или компонент (Del)")
        self.delete_action.setEnabled(False)
        self.delete_action.triggered.connect(lambda: self.delete_selection())
        self.rotation_step = read_float(self.settings, "rotate/angle", 90.0)
        self.rotate_action = QAction(tool_icon("rotate"), "", self)
        self.rotate_action.setShortcut(QKeySequence("Ctrl+R"))
        self.rotate_action.triggered.connect(self.rotate_selection)
        self.mirror_h_action = QAction(tool_icon("mirror_h"), "Отразить по горизонтали", self)
        self.mirror_h_action.setShortcut(QKeySequence("Ctrl+H"))
        self.mirror_h_action.setToolTip("Отразить выделенное слева направо (Ctrl+H)")
        self.mirror_h_action.triggered.connect(lambda: self.mirror_selection("x"))
        self.mirror_v_action = QAction(tool_icon("mirror_v"), "Отразить по вертикали", self)
        self.mirror_v_action.setShortcut(QKeySequence("Ctrl+T"))
        self.mirror_v_action.setToolTip("Отразить выделенное сверху вниз (Ctrl+T)")
        self.mirror_v_action.triggered.connect(lambda: self.mirror_selection("y"))

        def make_action(icon, text, shortcut, tip, slot):
            result = QAction(tool_icon(icon), text, self) if icon else QAction(text, self)
            if shortcut:
                result.setShortcut(QKeySequence(shortcut))
                tip = f"{tip} ({shortcut})"
            result.setToolTip(tip)
            result.triggered.connect(slot)
            return result

        self.copy_action = make_action(
            "copy", "Копировать", "Ctrl+C", "Копировать выделенное", self.copy_selection
        )
        self.cut_action = make_action(
            "cut", "Вырезать", "Ctrl+X", "Вырезать выделенное", self.cut_selection
        )
        self.paste_action = make_action(
            "paste", "Вставить", "Ctrl+V", "Вставить из буфера обмена под курсор", self.paste
        )
        self.duplicate_action = make_action(
            "duplicate", "Дублировать", "Ctrl+D", "Дублировать выделенное", self.duplicate_selection
        )
        self.select_all_action = make_action(
            None, "Выделить всё", "Ctrl+A", "Выделить все объекты видимых слоёв", self.select_all
        )
        self.group_action = make_action(
            "group",
            "Сгруппировать",
            "Ctrl+G",
            "Объединить выделенное в группу",
            self.group_selection,
        )
        self.ungroup_action = make_action(
            "ungroup",
            "Разгруппировать",
            "Ctrl+U",
            "Снять внешнюю группу с выделенного",
            self.ungroup_selection,
        )
        self.side_action = make_action(
            "side",
            "На другую сторону",
            "Ctrl+W",
            "Перенести выделенное на другую сторону платы",
            self.other_side_selection,
        )
        self.snap_action = make_action(
            "snap", "Выровнять по сетке", "", "Выровнять выделенное по сетке", self.snap_selection
        )
        self.align_menu = QMenu("Выровнять", self)
        self.align_menu.setIcon(tool_icon("align"))
        for align_mode, text in (
            ("left", "По левому краю"),
            ("right", "По правому краю"),
            ("top", "По верхнему краю"),
            ("bottom", "По нижнему краю"),
            ("vcenter", "По вертикальной оси"),
            ("hcenter", "По горизонтальной оси"),
        ):
            self.align_menu.addAction(text).triggered.connect(
                lambda _=False, m=align_mode: self.align_selection(m)
            )
        self.layer_menu = QMenu("На слой", self)
        for layer in (1, 2, 3, 4, 5, 6, 7):
            self.layer_menu.addAction(LAYER_HINTS[layer]).triggered.connect(
                lambda _=False, layer=layer: self.layer_selection(layer)
            )
        self.selection_actions = [
            self.delete_action,
            self.rotate_action,
            self.mirror_h_action,
            self.mirror_v_action,
            self.copy_action,
            self.cut_action,
            self.duplicate_action,
            self.group_action,
            self.ungroup_action,
            self.side_action,
            self.snap_action,
            self.align_menu.menuAction(),
            self.layer_menu.menuAction(),
        ]
        for action in self.selection_actions:
            action.setEnabled(False)
        self.rotation_menu = QMenu(self)
        self.rotation_menu.aboutToShow.connect(self.fill_rotation_menu)
        self.set_rotation_step(self.rotation_step)
        self.fit_action = QAction(tool_icon("fit"), "Масштаб: вся плата", self)
        self.fit_action.setShortcut(QKeySequence("F5"))
        self.fit_action.setToolTip("Показать всю плату (F5)")
        self.fit_action.triggered.connect(self.zoom_board)
        self.zoom_objects_action = QAction("Масштаб: все объекты", self)
        self.zoom_objects_action.triggered.connect(
            lambda: self.view.zoom_to(self.view.objects_rect())
        )
        self.zoom_selection_action = QAction("Масштаб: выделенное", self)
        self.zoom_selection_action.triggered.connect(self.zoom_selection)
        self.zoom_previous_action = QAction("Предыдущий масштаб", self)
        self.zoom_previous_action.setShortcut(QKeySequence("F4"))
        self.zoom_previous_action.triggered.connect(self.view.zoom_previous)
        self.zoom_menu = QMenu("Масштаб", self)
        self.zoom_menu.addActions(
            [
                self.zoom_previous_action,
                self.fit_action,
                self.zoom_objects_action,
                self.zoom_selection_action,
            ]
        )
        self.zoom_menu.aboutToShow.connect(
            lambda: self.zoom_selection_action.setEnabled(bool(self.view.members))
        )
        self.remove_wires_action = QAction("Удалить связи (воздушные линии)…", self)
        self.remove_wires_action.triggered.connect(self.remove_wires)
        self.template_action = QAction("Подложка-шаблон…", self)
        self.template_action.setToolTip("Скан платы в фоне для обрисовки")
        self.template_action.triggered.connect(self.edit_template)
        self.transparent_action = QAction(tool_icon("transparent"), "Прозрачный режим", self)
        self.transparent_action.setCheckable(True)
        self.transparent_action.setToolTip("Слои полупрозрачные: видно, что лежит под ними")
        self.transparent_action.setChecked(read_bool(self.settings, "view/transparent", False))
        self.transparent_action.toggled.connect(self.toggle_transparent)
        self.properties_action = QAction(tool_icon("properties"), "Свойства", self)
        self.properties_action.setCheckable(True)
        self.properties_action.setToolTip("Показать или скрыть панель свойств")
        self.properties_action.toggled.connect(self.toggle_properties)
        self.selector_action = QAction(tool_icon("selector"), "Селектор", self)
        self.selector_action.setToolTip("Показать или скрыть селектор: выделение по виду объектов")
        self.components_action = QAction(tool_icon("components"), "Компоненты", self)
        self.components_action.setToolTip("Показать или скрыть список компонентов")
        self.drc_action = QAction(tool_icon("drc"), "DRC", self)
        self.drc_action.setToolTip("Показать или скрыть панель проверки правил (DRC)")
        for action in (self.selector_action, self.components_action, self.drc_action):
            action.setCheckable(True)
        self.mask_action = QAction("Показывать паяльную маску", self)
        self.mask_action.setCheckable(True)
        self.mask_action.setToolTip("Накрыть плату маской и показать окна в ней")
        self.mask_action.setChecked(read_bool(self.settings, "view/soldermask", False))
        self.mask_action.toggled.connect(self.toggle_soldermask)
        self.units_action = QAction("Единицы: mil (1/1000 дюйма)", self)
        self.units_action.setCheckable(True)
        self.units_action.setToolTip("Переключить мм и mil; то же делает щелчок по углу линеек")
        self.units_action.toggled.connect(self.set_units)
        self.macro_action = QAction(tool_icon("macros"), "Макросы", self)
        self.macro_action.setCheckable(True)
        self.macro_action.setToolTip("Показать или скрыть панель макросов")
        self.macro_action.toggled.connect(self.toggle_macros)
        self.about_action = QAction("О программе…", self)
        self.about_action.triggered.connect(self.about)

        self.modes = QActionGroup(self)
        self.mode_actions: dict[str, QAction] = {}
        for icon, label, mode, shortcut, hint in TOOLS:
            action = QAction(tool_icon(icon), label, self)
            action.setCheckable(True)
            if mode is None:
                action.setEnabled(False)
                action.setToolTip(f"{label} — пока не реализовано")
            else:
                action.setShortcut(QKeySequence(shortcut))
                action.setToolTip(f"{hint} ({shortcut})")
                action.setStatusTip(hint)
                action.triggered.connect(lambda _=False, mode=mode: self.set_mode(mode))
                self.mode_actions[mode] = action
            self.modes.addAction(action)
        self.mode_actions["edit"].setChecked(True)

    def build_menus(self):
        bar = self.menuBar()
        file_menu = bar.addMenu("&Файл")
        self.fill_file_menu(file_menu, self.quit_action, self.fill_output_menu)
        edit_menu = bar.addMenu("&Правка")
        edit_menu.addActions([self.undo_action, self.redo_action])
        edit_menu.addSeparator()
        edit_menu.addActions(
            [
                self.copy_action,
                self.cut_action,
                self.paste_action,
                self.duplicate_action,
                self.delete_action,
            ]
        )
        edit_menu.addSeparator()
        edit_menu.addAction(self.select_all_action)
        board_menu = bar.addMenu("П&лата")
        self.fill_board_menu(board_menu)
        board_menu.addSeparator()
        board_menu.addMenu(self.zoom_menu)
        board_menu.aboutToShow.connect(self.update_board_actions)
        functions = bar.addMenu("Ф&ункции")
        functions.addActions([action for action in self.modes.actions() if action.isEnabled()])
        functions.addSeparator()
        functions.addActions([self.rotate_action, self.mirror_h_action, self.mirror_v_action])
        functions.addSeparator()
        functions.addActions([self.group_action, self.ungroup_action])
        functions.addSeparator()
        functions.addAction(self.side_action)
        functions.addMenu(self.layer_menu)
        functions.addSeparator()
        functions.addAction(self.snap_action)
        functions.addMenu(self.align_menu)
        functions.addSeparator()
        functions.addAction(self.tile_action)
        extras = bar.addMenu("&Дополнительно")
        extras.addAction(self.project_info_action)
        extras.addAction(self.holes_action)
        extras.addAction(self.template_action)
        extras.addSeparator()
        extras.addAction(self.remove_wires_action)
        extras.addSeparator()
        extras.addAction(self.delete_outside_action)
        extras.addSeparator()
        extras.addAction(self.wizard_action)
        extras.addSeparator()
        extras.addAction(self.textio_import_action)
        extras.addAction(self.textio_export_action)
        plugin_menu = extras.addMenu("Внешние программы")
        plugin_menu.aboutToShow.connect(lambda: self.fill_plugin_menu(plugin_menu))
        self.fill_plugin_menu(plugin_menu)
        options = bar.addMenu("&Настройки")
        options.addActions([self.properties_action, self.macro_action])
        options.addSeparator()
        options.addAction(self.mask_action)
        options.addAction(self.transparent_action)
        options.addAction(self.units_action)
        options.addSeparator()
        options.addAction(self.options_action)
        help_menu = bar.addMenu("&?")
        help_menu.addAction(self.about_action)

    def build_toolbar(self):
        toolbar = self.addToolBar("Основная")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        toolbar.addActions([self.new_action, self.open_action, self.save_action])
        toolbar.addSeparator()
        toolbar.addActions([self.undo_action, self.redo_action])
        toolbar.addSeparator()
        toolbar.addActions(
            [self.cut_action, self.copy_action, self.paste_action, self.delete_action]
        )
        toolbar.addSeparator()
        toolbar.addAction(self.duplicate_action)
        toolbar.addAction(self.rotate_action)
        rotate_button = toolbar.widgetForAction(self.rotate_action)
        if isinstance(rotate_button, QToolButton):
            rotate_button.setMenu(self.rotation_menu)
            rotate_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        toolbar.addActions([self.mirror_h_action, self.mirror_v_action])
        toolbar.addAction(self.align_menu.menuAction())
        align_button = toolbar.widgetForAction(self.align_menu.menuAction())
        if isinstance(align_button, QToolButton):
            align_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        toolbar.addAction(self.snap_action)
        toolbar.addSeparator()
        toolbar.addActions([self.group_action, self.ungroup_action, self.side_action])
        toolbar.addSeparator()
        zoom_button = QToolButton()
        zoom_button.setDefaultAction(self.fit_action)
        zoom_button.setMenu(self.zoom_menu)
        zoom_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        toolbar.addWidget(zoom_button)
        toolbar.addAction(self.transparent_action)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addActions(
            [
                self.selector_action,
                self.components_action,
                self.properties_action,
                self.drc_action,
                self.macro_action,
            ]
        )
        toolbar.setStyleSheet(
            "QToolBar { background: #ffffff; border-bottom: 1px solid #c8c8c8; spacing: 1px; }"
        )

    def build_tool_panel(self):
        panel = QWidget()
        panel.setFixedWidth(142)
        panel.setObjectName("tools")
        panel.setStyleSheet(
            "QWidget#tools QToolButton { color: #000090; padding: 2px;"
            " border: 1px solid transparent; }"
            " QWidget#tools QToolButton:checked { background: #cce8ff; border: 1px solid #99d1ff; }"
            " QWidget#tools QToolButton:hover { border: 1px solid #99d1ff; }"
            " QWidget#tools QToolButton:disabled { color: #9090a8; }"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(1)
        self.pad_shape = read_int(self.settings, "pad/shape", 1)
        for action in self.modes.actions():
            button = QToolButton()
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setIconSize(QSize(18, 18))
            button.setAutoRaise(True)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            if action is self.mode_actions["pad"]:
                menu = QMenu(button)
                shapes = QActionGroup(menu)
                for item in PAD_SHAPES:
                    if item is None:
                        menu.addSeparator()
                        continue
                    label, shape = item
                    shape_action = menu.addAction(pad_shape_icon(shape), label)
                    shape_action.setCheckable(True)
                    shape_action.setChecked(shape == self.pad_shape)
                    shapes.addAction(shape_action)
                    shape_action.triggered.connect(
                        lambda _=False, shape=shape: self.set_pad_shape(shape)
                    )
                button.setMenu(menu)
                button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
            if action is self.mode_actions.get("rect"):
                menu = QMenu(button)
                fills = QActionGroup(menu)
                for label, filled in (("Контур (дорожка)", False), ("Заливка (полигон)", True)):
                    fill_action = menu.addAction(label)
                    fill_action.setCheckable(True)
                    fill_action.setChecked(filled == self.view.rect_filled)
                    fills.addAction(fill_action)
                    fill_action.triggered.connect(
                        lambda _=False, filled=filled: self.set_rect_filled(filled)
                    )
                button.setMenu(menu)
                button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
            layout.addWidget(button)
        layout.addSpacing(4)
        layout.addWidget(separator())
        self.grid_button = QToolButton()
        self.grid_button.setIcon(tool_icon("grid"))
        self.grid_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.grid_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.grid_button.setAutoRaise(True)
        self.grid_button.setToolTip("Шаг сетки привязки")
        self.grid_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.grid_button.setMenu(self.grid_menu())
        layout.addWidget(self.grid_button)
        layout.addWidget(separator())
        self.track_size = SizeRow("track", "width", ["Ширина дорожки, мм"], self.settings)
        self.pad_size = SizeRow(
            "pad", "padsize", ["Диаметр площадки, мм", "Диаметр отверстия, мм"], self.settings
        )
        self.smd_size = SizeRow(
            "smd", "smdsize", ["Ширина SMD, мм", "Высота SMD, мм"], self.settings
        )
        self.track_size.changed.connect(self.apply_track_size)
        self.pad_size.changed.connect(self.apply_pad_size)
        self.smd_size.changed.connect(self.apply_smd_size)
        self.view.track_width = self.track_size.values()[0]
        for row in (self.track_size, self.pad_size, self.smd_size):
            layout.addWidget(row)
        swap = QToolButton()
        swap.setIcon(tool_icon("swap"))
        swap.setToolTip("Поменять ширину и высоту SMD местами")
        swap.setAutoRaise(True)
        swap.clicked.connect(
            lambda: self.smd_size.set_values(self.smd_size.values()[::-1], emit=True)
        )
        layout.addWidget(swap, 0, Qt.AlignmentFlag.AlignRight)
        layout.addStretch()
        self.overview = Overview(self.view)
        layout.addWidget(self.overview)
        return panel

    def grid_menu(self):
        menu = QMenu(self)
        group = QActionGroup(menu)
        self.grid_actions: dict[float, QAction] = {}

        def add(target, value, label):
            action = target.addAction(label)
            action.setCheckable(True)
            group.addAction(action)
            action.triggered.connect(lambda _=False: self.set_grid(value))
            self.grid_actions[value] = action

        standard = menu.addMenu("Дюймовая сетка")
        for value, label in GRID_STANDARD:
            add(standard, value, label)
        metric = menu.addMenu("Метрическая сетка")
        for value in GRID_METRIC:
            add(metric, value, f"{value:g} мм".replace(".", ","))
        menu.addSeparator()
        visible = menu.addAction("Показывать сетку")
        visible.setCheckable(True)
        visible.setChecked(read_bool(self.settings, "grid/visible", True))
        self.view.show_grid = visible.isChecked()
        visible.toggled.connect(self.set_grid_visible)
        return menu

    def build_status_bar(self):
        status = self.statusBar()
        status.setSizeGripEnabled(True)
        self.layer_bar = LayerBar()
        self.layer_bar.visibility.connect(self.set_layer)
        self.layer_bar.activated.connect(self.set_active_layer)
        self.layer_bar.set_active(self.view.active_layer)
        self.coordinates.setFrameShape(QFrame.Shape.Panel)
        self.coordinates.setFrameShadow(QFrame.Shadow.Sunken)
        self.coordinates.setContentsMargins(4, 0, 4, 0)
        status.addWidget(self.coordinates)
        status.addWidget(self.layer_bar)
        info = QToolButton()
        info.setText("?")
        info.setAutoRaise(True)
        info.setToolTip("Что означают слои")
        info.clicked.connect(self.show_layer_info)
        status.addWidget(info)
        plane_box = QFrame()
        plane_box.setFrameShape(QFrame.Shape.Panel)
        plane_box.setFrameShadow(QFrame.Shadow.Sunken)
        plane_layout = QHBoxLayout(plane_box)
        plane_layout.setContentsMargins(2, 1, 2, 1)
        self.plane_button = QToolButton()
        self.plane_button.setIcon(tool_icon("plane", 24))
        self.plane_button.setIconSize(QSize(24, 24))
        self.plane_button.setCheckable(True)
        self.plane_button.setToolTip(
            "Автозаливка: включить или выключить для активного медного слоя"
        )
        self.plane_button.toggled.connect(self.toggle_plane)
        plane_layout.addWidget(self.plane_button)
        self.clearance_box = value_box(read_float(self.settings, "clearance", 0.4), 0.0, 20.0)
        self.clearance_box.setToolTip(
            "Зазор до автозаливки, мм: для новых объектов и для выделенных сейчас"
        )
        self.clearance_box.valueChanged.connect(self.apply_clearance)
        plane_layout.addWidget(self.clearance_box)
        status.addWidget(plane_box)
        self.snap_button = QToolButton()
        self.rubber_button = QToolButton()
        for button, icon, tip, key in (
            (
                self.snap_button,
                "node_snap",
                "Привязка к центрам площадок и узлам дорожек при рисовании",
                "snap_nodes",
            ),
            (
                self.rubber_button,
                "rubber",
                "«Резиновая нить»: концы дорожек следуют за перемещаемыми площадками",
                "rubber",
            ),
        ):
            button.setIcon(tool_icon(icon, 24))
            button.setIconSize(QSize(24, 24))
            button.setToolTip(tip)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.toggled.connect(lambda on, key=key: self.set_drawing_aid(key, on))
            button.setChecked(read_bool(self.settings, f"view/{key}", False))
            status.addWidget(button)
        status.addWidget(self.hint, 1)

    # --- tool settings --------------------------------------------------------

    def set_mode(self, mode):
        mask_before = self.mask_shown()
        photo_before = self.view.mode == "photo"
        self.view.set_mode(mode)
        self.photo_bar.setVisible(mode == "photo")
        self.show_route_bar(mode)
        if self.boards and (photo_before or mode == "photo"):
            self.show_board(self.current_board_index(), refit=False)
        elif self.boards and self.mask_shown() != mask_before:
            # The mask tool shows the mask, so that its openings can be seen while editing.
            self.show_board(self.current_board_index(), refit=False)
        for _, _, tool_mode, _, hint in TOOLS:
            if tool_mode == mode:
                self.hint.setText(hint)

    def set_drawing_aid(self, key: str, on: bool) -> None:
        setattr(self.view, key, on)
        self.settings.setValue(f"view/{key}", on)

    def set_rect_filled(self, filled: bool) -> None:
        self.view.rect_filled = filled
        self.settings.setValue("rect/filled", filled)
        self.mode_actions["rect"].trigger()

    def show_bend(self, mode: str) -> None:
        self.settings.setValue("track/bend", mode)
        names = {core.BEND_45: "излом 45°", core.BEND_90: "излом 90°", core.FREE: "свободно"}
        self.hint.setText(f"Режим линии: {names[mode]} (пробел — следующий)")

    def picked(self, mode: str, index) -> None:
        """A click in the Connections or Test tool."""
        board = self.view.board
        if board is None:
            return
        if mode == "test":
            if index is None:
                self.view.highlight([])
                self.hint.setText("Щёлкните по меди, чтобы увидеть, что с ней связано")
                return
            net = net_of(board, index, OPTIONS["wires_in_test"])
            self.view.highlight(net)
            self.hint.setText(f"Электрически связано объектов: {len(net)}")
            return
        if index is None:
            self.wire_start = None
            self.view.set_wire_from(None)
            self.view.highlight([])
            self.hint.setText("Связь отменена: щёлкните первую площадку")
            return
        if self.wire_start is None or self.wire_start == index:
            self.wire_start = index
            self.view.highlight([index])
            self.view.set_wire_from(point(*core.centre_of(board.elements[index])))
            self.hint.setText("Щёлкните вторую площадку (или пустое место — отмена)")
            return
        start, self.wire_start = self.wire_start, None
        self.view.set_wire_from(None)
        changed = core.toggled_wire(board, start, index)
        added = index in core.wired_to(changed[start])
        self.edit_elements(changed, "Новая связь" if added else "Связь удалена")
        self.hint.setText("Связь протянута" if added else "Связь удалена")

    def remove_wires(self) -> None:
        board = self.view.board
        if board is None or not core.air_wires(board):
            self.hint.setText("На плате нет воздушных линий")
            return
        members = list(self.view.members)
        if members:
            changed = core.without_wires_of(board, members)
            description = "Удаление связей выделенного"
        else:
            answer = QMessageBox.question(self, "Связи", "Удалить все воздушные линии этой платы?")
            if answer != QMessageBox.StandardButton.Yes:
                return
            changed = core.without_wires_of(board, range(len(board.elements)))
            description = "Удаление всех связей"
        if changed:
            self.edit_elements(changed, description)

    def toggle_mask(self, index: int) -> None:
        obj = self.view.elements[index]
        if obj.kind not in (core.THT, core.SMD, core.LINE, core.POLYGON, core.CIRCLE):
            self.hint.setText("Окно в маске бывает у площадок, дорожек, полигонов и окружностей")
            return
        shown = "убрано" if obj.soldermask else "добавлено"
        self.hint.setText(f"Окно в маске {shown}. Ctrl+Z отменяет.")
        self.edit_elements(
            {index: replace(obj, soldermask=not obj.soldermask)}, f"Окно в маске {shown}"
        )

    def open_object_dialog(self, index: int) -> None:
        obj = self.view.elements[index]
        if core.component_id(obj):
            self.view.select(index)
            self.edit_component()
        elif obj.kind == core.STROKE_TEXT:
            self.edit_text(index)

    def edit_text(self, index: int) -> None:
        obj = self.view.elements[index]
        dialog = TextDialog(self, self.settings, obj, numbering=False)
        if not dialog.exec():
            return
        self.edit_elements({index: core.with_text(obj, **dialog.values())}, "Свойства текста")

    def edit_component(self) -> None:
        index = self.view.selection
        if index is None:
            return
        cid = core.component_id(self.view.elements[index])
        if not cid:
            self.hint.setText("Выделите компонент")
            return
        dialog = ComponentDialog(self, self.view.elements, cid)
        result = dialog.exec()
        if result == ComponentDialog.DISSOLVE:
            self.dissolve_component(cid)
            return
        if not result:
            return
        elements = self.view.elements
        edited = {}
        for old, new in dialog.edited():
            edited[next(i for i, obj in enumerate(elements) if obj is old)] = new
        self.edit_elements(edited, "Свойства компонента")

    def dissolve_component(self, cid: int) -> None:
        index = self.current_board_index()
        board = self.boards[index]
        changed, labels = core.dissolved(board.elements, cid)
        elements = [changed.get(i, obj) for i, obj in enumerate(board.elements)]
        elements = [obj for i, obj in enumerate(elements) if i not in set(labels)]
        self.undo.push(
            ReplaceBoard(
                self, index, board, replace(board, elements=elements), "Компонент расформирован"
            )
        )

    def set_pad_shape(self, shape):
        self.pad_shape = shape
        self.settings.setValue("pad/shape", shape)
        self.mode_actions["pad"].trigger()

    def set_grid(self, value):
        self.view.grid = value
        self.settings.setValue("grid", value)
        label = next((text.split(" (")[0] for v, text in GRID_STANDARD if v == value), None)
        self.grid_button.setText(label or f"{value:g} мм".replace(".", ","))
        if value in self.grid_actions:
            self.grid_actions[value].setChecked(True)
        self.view.viewport().update()

    def set_grid_visible(self, visible):
        self.view.show_grid = visible
        self.settings.setValue("grid/visible", visible)
        self.view.viewport().update()

    def set_active_layer(self, layer):
        ready = hasattr(self, "mask_action")
        before = (self.mask_side(), self.template_side()) if ready else None
        self.view.active_layer = layer
        self.layer_bar.set_active(layer)
        if hasattr(self, "plane_button"):
            self.update_plane_button()
        if ready and self.boards and (self.mask_side(), self.template_side()) != before:
            self.show_board(self.current_board_index(), refit=False)

    def template_side(self) -> int:
        """Board side of the template shown: 2 while a bottom layer is active."""
        return 2 if self.view.active_layer in (3, 4) else 1

    def templates_of(self, board):
        return load_templates(self.settings, settings_key(self.path, board.name))

    def edit_template(self) -> None:
        board = self.current_board()
        key = settings_key(self.path, board.name)
        dialog = TemplateDialog(self, load_templates(self.settings, key))
        dialog.exec()
        save_templates(self.settings, key, dialog.templates())
        self.show_board(self.current_board_index(), refit=False)

    def mask_side(self) -> int | None:
        """The side whose solder mask is shown: the active layer's side, or none."""
        if not self.mask_shown():
            return None
        return 3 if self.view.active_layer in (3, 4) else 1

    def toggle_transparent(self, on: bool) -> None:
        self.settings.setValue("view/transparent", on)
        if self.boards:
            self.show_board(self.current_board_index(), refit=False)

    def zoom_board(self) -> None:
        self.view.remember_view()
        self.view.fit_board()

    def zoom_selection(self) -> None:
        if self.view.members:
            self.view.zoom_to(self.view.objects_rect(set(self.view.members)))

    def toggle_panel(self, panel, key: str, visible: bool) -> None:
        panel.setVisible(visible)
        self.settings.setValue(f"{key}/visible", visible)
        if visible:
            self.refresh_lists()

    def refresh_lists(self) -> None:
        board = self.view.board
        if self.selector.isVisible():
            self.selector.show_board(board)
        if self.components.isVisible():
            self.components.show_board(board)

    def select_objects(self, indices) -> None:
        if self.view.board is None or not indices:
            return
        self.view.set_selection(list(indices), indices[0])
        self.view.zoom_to(self.view.objects_rect(set(self.view.members)))

    def rename_component(self, cid: int, field: str, text: str) -> None:
        ref, value = core.component_labels(self.view.elements, cid)
        index = ref if field == "name" else value
        if index is None:
            return
        label = self.view.elements[index]
        self.edit_elements(
            {index: core.with_text(label, text=text)},
            "Обозначение компонента" if field == "name" else "Номинал компонента",
        )

    def export_components(self) -> None:
        if self.view.board is None:
            return
        dialog = ComponentExportDialog(self, self.settings, self.view.board)
        dialog.exec()
        dialog.remember()

    def run_drc(self, window_only: bool) -> None:
        board = self.view.board
        if board is None:
            return
        area = None
        if window_only:
            area = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        violations = check(board, self.drc.rules(), area)
        self.drc.show_violations(violations)
        self.view.mark_points([v.position for v in violations])
        self.hint.setText(f"DRC: нарушений {len(violations)}")

    def show_violation(self, violation) -> None:
        position = violation.position
        self.view.zoom_to(QRectF(position.x() - 2.5, position.y() - 2.5, 5, 5))
        self.view.highlight(violation.objects)
        self.hint.setText(violation.text)

    def mark_violations(self) -> None:
        indices = sorted({i for v in self.drc.violations for i in v.objects})
        if indices:
            self.view.set_selection(indices, indices[0])

    def toggle_properties(self, visible):
        self.properties.setVisible(visible)
        self.settings.setValue("properties/visible", visible)

    def mask_shown(self) -> bool:
        return self.mask_action.isChecked() or self.view.mode == "mask"

    def toggle_soldermask(self, shown: bool) -> None:
        self.settings.setValue("view/soldermask", shown)
        if self.boards:
            self.show_board(
                self.current_board_index(), refit=False, selection=list(self.view.members)
            )

    def show_layer_info(self) -> None:
        text = "<br>".join(
            f"<b style='color:{LAYERS[layer][1]}; background:#000'>"
            f"&nbsp;{LAYERS[layer][0]}&nbsp;</b>"
            f" — {LAYER_HINTS[layer].split(' — ', 1)[1]}"
            for layer in (1, 2, 3, 4, 5, 6, 7)
        )
        QMessageBox.information(self, "Слои", text)

    def update_plane_button(self) -> None:
        board = self.view.board
        layer = self.view.active_layer
        copper = board is not None and layer in (1, 3, 5, 6)
        self.plane_button.setEnabled(copper)
        self.plane_button.blockSignals(True)
        self.plane_button.setChecked(bool(copper and board and core.has_plane(board, layer)))
        self.plane_button.blockSignals(False)

    def toggle_plane(self, on: bool) -> None:
        index = self.current_board_index()
        board = self.boards[index]
        layer = self.view.active_layer
        name = LAYERS[layer][0]
        self.undo.push(
            ReplaceBoard(
                self,
                index,
                board,
                core.with_plane(board, layer, on),
                f"Автозаливка {name} {'включена' if on else 'выключена'}",
            )
        )

    def apply_clearance(self, value: float) -> None:
        self.settings.setValue("clearance", value)
        targets = {
            i: replace(self.view.elements[i], clearance=value)
            for i in self.view.members
            if not core.is_hidden_label(self.view.elements[i])
        }
        if targets:
            self.edit_elements(targets, "Зазор до заливки")

    def set_units(self, mil: bool) -> None:
        if self.units.mil == mil:
            self.units_action.setChecked(mil)
            return
        self.units.mil = mil
        self.settings.setValue("units/mil", mil)
        self.units_action.setChecked(mil)
        self.properties.apply_units()
        self.view.viewport().update()
        self.hint.setText(f"Единицы: {self.units.suffix}")

    def replace_current_board(self, new, description: str) -> None:
        index = self.current_board_index()
        self.undo.push(ReplaceBoard(self, index, self.boards[index], new, description))

    def set_origin(self, where: str, position=None) -> None:
        board = self.boards[self.current_board_index()]
        if where == "top_left":
            x, y = 0.0, 0.0
        elif where == "bottom_left":
            x, y = 0.0, -board.height
        else:
            x, y = position
            if self.view.grid:
                x = round(x / self.view.grid) * self.view.grid
                y = round(y / self.view.grid) * self.view.grid
        self.replace_current_board(core.with_origin(board, x, y), "Начало координат")

    def toggle_macros(self, visible):
        self.macros.setVisible(visible)
        self.settings.setValue("macro/visible", visible)

    # --- editing --------------------------------------------------------------

    def selected_element(self, kinds):
        index = self.view.selection
        if index is None or self.view.board is None:
            return None, None
        obj = self.view.elements[index]
        return (index, obj) if obj.kind in kinds else (None, None)

    def apply_track_size(self):
        width = self.track_size.values()[0]
        self.view.track_width = width
        index, obj = self.selected_element((core.LINE, core.SEGMENT))
        if obj is not None and abs(obj.width - width) > 1e-9:
            self.edit_element(index, replace(obj, width=width), "Ширина дорожки")

    def apply_pad_size(self):
        diameter, drill = self.pad_size.values()
        index, obj = self.selected_element((core.THT,))
        if obj is None:
            return
        if drill >= diameter:
            self.hint.setText("Отверстие должно быть меньше площадки")
            return
        self.edit_element(
            index, replace(obj, outer=diameter / 2, inner=drill / 2), "Размер площадки"
        )

    def apply_smd_size(self):
        width, height = self.smd_size.values()
        index, obj = self.selected_element((core.SMD,))
        if obj is not None:
            self.edit_element(index, core.resized_smd(obj, width, height), "Размер SMD-площадки")

    def show_properties(self, index):
        board = self.view.board
        if hasattr(self, "properties"):
            self.properties.show_selection(board, self.view.members, index)
        for action in self.selection_actions:
            action.setEnabled(index is not None)
        if index is None or self.view.board is None:
            return
        obj = self.view.elements[index]
        parts = core.units(self.view.elements, self.view.members)
        if len(parts) > 1:
            self.hint.setText(
                f"Выделено: {len(parts)}, объектов {len(self.view.members)}. "
                "Shift+щелчок добавляет или убирает, перетаскивание двигает всё"
            )
            return
        cid = core.component_id(obj)
        if not cid and core.outer_group(obj) is not None:
            self.hint.setText(
                f"Группа: объектов {len(self.view.members)}. Ctrl+U снимает группировку"
            )
            return
        if cid:
            package = core.component_package(self.view.elements, cid)
            members = len(self.view.members)
            self.hint.setText(
                f"Компонент {package or cid}: объектов {members}. "
                "Перетаскивание двигает компонент целиком"
            )
            return
        if obj.kind in (core.LINE, core.SEGMENT):
            self.track_size.set_values((obj.width,))
            self.hint.setText(
                f"Дорожка: ширина {self.units.with_suffix(obj.width)}, "
                f"узлов {len(track_nodes(obj))}"
            )
        elif obj.kind == core.THT:
            self.pad_size.set_values((obj.outer * 2, obj.inner * 2))
            self.hint.setText(
                f"Площадка: ⌀ {self.units.with_suffix(obj.outer * 2)}, "
                f"отверстие {self.units.with_suffix(obj.inner * 2)}"
            )
        elif obj.kind == core.SMD:
            if len(obj.points) == 4:
                (x0, y0), (x1, y1), _, (x3, y3) = obj.points
                size = (hypot(x1 - x0, y1 - y0), hypot(x3 - x0, y3 - y0))
            else:
                size = (obj.outer, obj.inner)
            self.smd_size.set_values(size)
            self.hint.setText(
                f"SMD-площадка: {self.units.text(size[0])} x {self.units.with_suffix(size[1])}"
            )

    # --- stage 1: clipboard, groups, layers, alignment, nodes -----------------

    CLIPBOARD_MIME = "application/x-lay6-objects"

    def selection_objects(self) -> list[core.Element]:
        return [self.view.elements[i] for i in self.view.members]

    def current_board(self) -> core.Board:
        return self.boards[self.board_select.currentIndex()]

    def add_objects(self, objects: list[core.Element], description: str) -> None:
        self.undo.push(AddElements(self, self.board_select.currentIndex(), objects, description))

    def copy_selection(self) -> bool:
        objects = self.selection_objects()
        if not objects:
            return False
        data = QMimeData()
        data.setData(self.CLIPBOARD_MIME, QByteArray(core.objects_to_bytes(objects)))
        data.setText(f"Объекты платы: {len(objects)}")
        clipboard = QApplication.clipboard()
        clipboard.setMimeData(data)
        self.hint.setText(f"Скопировано объектов: {len(objects)}")
        return True

    def cut_selection(self) -> None:
        if self.copy_selection():
            self.delete_selection("Вырезание")

    def paste(self) -> None:
        data = QApplication.clipboard().mimeData()
        if data is None or not data.hasFormat(self.CLIPBOARD_MIME):
            self.hint.setText("В буфере обмена нет объектов платы")
            return
        try:
            objects = core.objects_from_bytes(bytes(data.data(self.CLIPBOARD_MIME).data()))
        except core.LayoutError as error:
            self.hint.setText(str(error))
            return
        if not objects:
            return
        dx = dy = 0.0
        cursor = self.view.viewport().mapFromGlobal(QCursor.pos())
        if self.view.viewport().rect().contains(cursor):
            # Centre the pasted objects under the cursor, keeping their grid alignment.
            target = self.view.mapToScene(cursor)
            cx, cy = core.centre(objects)
            dx, dy = target.x() - cx, -target.y() - cy
            if self.view.grid:
                dx = round(dx / self.view.grid) * self.view.grid
                dy = round(dy / self.view.grid) * self.view.grid
        copies = core.fresh_copies(objects, self.view.elements, dx, dy)
        self.add_objects(copies, f"Вставка: объектов {len(copies)}")

    def duplicate_selection(self) -> None:
        objects = self.selection_objects()
        if objects:
            step = 10 * (self.view.grid or 0.1)
            copies = core.fresh_copies(objects, self.view.elements, step, -step)
            self.add_objects(copies, f"Дублирование: объектов {len(copies)}")

    def select_all(self) -> None:
        visible = {layer for layer, check in self.layer_bar.checks.items() if check.isChecked()}
        indices = [
            i
            for i, obj in enumerate(self.view.elements)
            if obj.layer in visible and not core.is_hidden_label(obj)
        ]
        self.view.set_selection(indices)

    def group_selection(self) -> None:
        indices = self.view.members
        if len(core.units(self.view.elements, indices)) < 2:
            self.hint.setText("Для группы выделите хотя бы два объекта (Shift+щелчок или рамка)")
            return
        self.edit_elements(core.grouped(self.view.elements, indices), "Группировка")

    def ungroup_selection(self) -> None:
        changed = core.ungrouped(self.view.elements, self.view.members)
        if not changed:
            self.hint.setText("В выделении нет групп")
            return
        self.edit_elements(changed, "Разгруппировка")

    def other_side_selection(self) -> None:
        indices = self.view.members
        if indices:
            flipped = core.to_other_side(self.selection_objects())
            self.edit_elements(dict(zip(indices, flipped, strict=True)), "На другую сторону")

    def layer_selection(self, layer: int) -> None:
        indices = self.view.members
        moved = {i: core.on_layer(self.view.elements[i], layer) for i in indices}
        skipped = sum(1 for i in indices if moved[i].layer != layer)
        self.edit_elements(moved, f"На слой {LAYERS[layer][0]}")
        if skipped:
            self.hint.setText(f"Площадки остаются на меди: не перенесено объектов {skipped}")

    def snap_selection(self) -> None:
        grid = self.view.grid or 0.1
        self.edit_elements(
            core.snapped_to_grid(self.view.elements, self.view.members, grid),
            "Выравнивание по сетке",
        )

    def align_selection(self, mode: str) -> None:
        changed = core.aligned(self.view.elements, self.view.members, mode)
        if not changed:
            self.hint.setText("Для выравнивания выделите хотя бы два объекта")
            return
        self.edit_elements(changed, "Выравнивание")

    def selected_tracks(self) -> list[int]:
        return [i for i in self.view.members if self.view.elements[i].kind == core.LINE]

    def context_menu(self, position, node) -> None:
        menu = QMenu(self)
        index = self.view.selection
        track = (
            index
            if index is not None
            and len(self.view.members) == 1
            and self.view.elements[index].kind == core.LINE
            else None
        )
        if track is not None:
            obj = self.view.elements[track]
            if node is not None:
                menu.addAction("Удалить узел").triggered.connect(
                    lambda: self.remove_node(track, node)
                )
                menu.addAction("Выровнять узел по сетке").triggered.connect(
                    lambda: self.snap_node(track, node)
                )
                split = menu.addAction("Разрезать дорожку в этом узле")
                split.setEnabled(0 < node < len(obj.points) - 1)
                split.triggered.connect(lambda: self.split_at(track, node))
            else:
                menu.addAction("Добавить узел здесь").triggered.connect(
                    lambda: self.add_node(track, position)
                )
            menu.addAction("Выровнять все узлы по сетке").triggered.connect(self.snap_selection)
            menu.addSeparator()
        if index is not None and core.component_id(self.view.elements[index]):
            menu.addAction("Компонент…").triggered.connect(self.edit_component)
            menu.addSeparator()
        elif (
            index is not None
            and len(self.view.members) == 1
            and self.view.elements[index].kind == core.STROKE_TEXT
        ):
            menu.addAction("Свойства текста…").triggered.connect(lambda: self.edit_text(index))
            menu.addSeparator()
        if len(self.selected_tracks()) == 2 and len(self.view.members) == 2:
            menu.addAction("Соединить дорожки").triggered.connect(self.join_selected)
            menu.addSeparator()
        menu.addActions(
            [
                self.copy_action,
                self.cut_action,
                self.paste_action,
                self.duplicate_action,
                self.delete_action,
            ]
        )
        menu.addSeparator()
        menu.addActions([self.rotate_action, self.mirror_h_action, self.mirror_v_action])
        menu.addSeparator()
        menu.addActions([self.side_action])
        menu.addMenu(self.layer_menu)
        menu.addSeparator()
        menu.addActions([self.group_action, self.ungroup_action])
        menu.addSeparator()
        menu.addAction(self.snap_action)
        menu.addMenu(self.align_menu)
        menu.addSeparator()
        origin = menu.addMenu("Начало координат")
        origin.addAction("В левый верхний угол платы").triggered.connect(
            lambda: self.set_origin("top_left")
        )
        origin.addAction("В левый нижний угол платы").triggered.connect(
            lambda: self.set_origin("bottom_left")
        )
        origin.addAction("В точку щелчка").triggered.connect(
            lambda: self.set_origin("point", position)
        )
        menu.exec(QCursor.pos())

    def remove_node(self, index: int, node: int) -> None:
        changed = core.without_node(self.view.elements[index], node)
        if changed is None:
            self.hint.setText("У дорожки должно остаться хотя бы два узла")
            return
        self.edit_element(index, changed, "Удаление узла")

    def add_node(self, index: int, position) -> None:
        x, y = position
        if self.view.grid:
            x = round(x / self.view.grid) * self.view.grid
            y = round(y / self.view.grid) * self.view.grid
        self.edit_element(index, core.with_node(self.view.elements[index], (x, y)), "Новый узел")

    def snap_node(self, index: int, node: int) -> None:
        obj = self.view.elements[index]
        grid = self.view.grid or 0.1
        points = list(obj.points)
        x, y = points[node]
        points[node] = (round(round(x / grid) * grid, 6), round(round(y / grid) * grid, 6))
        self.edit_element(index, replace(obj, points=points), "Узел по сетке")

    def split_at(self, index: int, node: int) -> None:
        parts = core.split_track(self.view.elements[index], node)
        if parts is None:
            return
        first, second = parts
        self.undo.beginMacro("Разрезание дорожки")
        self.edit_element(index, first, "Разрезание дорожки")
        self.add_objects([second], "Разрезание дорожки")
        self.undo.endMacro()

    def join_selected(self) -> None:
        a, b = self.selected_tracks()
        joined = core.joined_tracks(self.view.elements[a], self.view.elements[b])
        if joined is None:
            self.hint.setText("Дорожки должны быть на одном слое и сходиться концами")
            return
        self.undo.beginMacro("Соединение дорожек")
        self.edit_elements({a: joined}, "Соединение дорожек")
        self.undo.push(
            DeleteElements(self, self.board_select.currentIndex(), [b], "Соединение дорожек")
        )
        self.undo.endMacro()

    def set_rotation_step(self, angle: float) -> None:
        self.rotation_step = angle
        self.settings.setValue("rotate/angle", angle)
        text = f"{angle:g}".replace(".", ",")
        self.rotate_action.setText(f"Повернуть на {text}°")
        self.rotate_action.setToolTip(
            f"Повернуть выделенное на {text}° по часовой стрелке (Ctrl+R). "
            "Угол выбирается стрелкой рядом с кнопкой"
        )

    def fill_rotation_menu(self) -> None:
        menu = self.rotation_menu
        menu.clear()
        for angle in ROTATION_STEPS:
            action = menu.addAction(f"{angle:g}°")
            action.setCheckable(True)
            action.setChecked(angle == self.rotation_step)
            action.triggered.connect(lambda _=False, angle=angle: self.set_rotation_step(angle))
        menu.addSeparator()
        menu.addAction("Другой угол…").triggered.connect(self.ask_rotation_step)

    def ask_rotation_step(self) -> None:
        angle, ok = QInputDialog.getDouble(
            self, "Угол поворота", "Угол, градусов:", self.rotation_step, 0.1, 359.9, 1
        )
        if ok:
            self.set_rotation_step(angle)

    def selected_group(self) -> tuple[list[int], list[core.Element]]:
        indices = list(self.view.members) if self.view.selection is not None else []
        return indices, [self.view.elements[i] for i in indices]

    def rotate_selection(self) -> None:
        indices, elements = self.selected_group()
        if elements:
            # Clockwise, like the macro rotation of classic layout editors.
            rotated = core.rotate_all(elements, -self.rotation_step)
            text = f"{self.rotation_step:g}".replace(".", ",")
            self.edit_elements(dict(zip(indices, rotated, strict=True)), f"Поворот на {text}°")

    def mirror_selection(self, axis: str) -> None:
        indices, elements = self.selected_group()
        if elements:
            mirrored = core.mirror_all(elements, axis)
            description = "Отражение по горизонтали" if axis == "x" else "Отражение по вертикали"
            self.edit_elements(dict(zip(indices, mirrored, strict=True)), description)

    def delete_selection(self, verb: str = "Удаление"):
        if self.view.draft is not None or self.view.selection is None:
            return
        board = self.view.board
        if board is None:
            return
        indices = list(self.view.members)
        cid = core.component_id(board.elements[self.view.selection])
        if cid:
            package = core.component_package(board.elements, cid)
            description = f"{verb} компонента {package}".rstrip()
        else:
            description = f"{verb}: объектов {len(indices)}"
        self.undo.push(DeleteElements(self, self.board_select.currentIndex(), indices, description))
        self.hint.setText(f"{description}: удалено объектов {len(indices)}")

    def edit_element(self, index, obj, description="Перемещение"):
        self.edit_elements({index: obj}, description)

    def edit_elements(self, edited, description="Перемещение"):
        elements = self.view.elements
        changes = {i: (elements[i], obj) for i, obj in edited.items() if elements[i] != obj}
        if changes:
            if len(edited) > 1 and description == "Перемещение":
                description = "Перемещение выделенного"
            self.undo.push(
                EditGeometry(
                    self,
                    self.board_select.currentIndex(),
                    changes,
                    list(self.view.members) or self.view.selection,
                    description,
                )
            )

    def add_element(self, mode, points):
        if self.view.board is None:
            return
        board = self.view.board
        layer = self.view.active_layer
        width = self.track_size.values()[0]
        clearance = self.clearance_box.value()
        index = self.board_select.currentIndex()
        if mode in ("circle", "rect", "zone", "special", "text"):
            if mode == "circle":
                (cx, cy), (x, y) = points
                diameter = 2 * hypot(x - cx, y - cy)
                new = [core.new_circle(board, layer, cx, cy, diameter, width)]
                description = "Новая окружность"
            elif mode == "rect":
                a, b = points
                new = [core.new_rectangle(board, layer, a, b, width, self.view.rect_filled)]
                description = "Новый прямоугольник"
            elif mode == "zone":
                new = [core.new_polygon(board, layer, points, width)]
                description = "Новый полигон"
            elif mode == "special":
                dialog = SpecialFormDialog(self, self.settings, width)
                if not dialog.exec():
                    return
                dialog.remember()
                ((x, y),) = points
                new = dialog.build(board, layer, x, y)
                description = "Спецформа"
            else:
                new_text = self.text_at(board, layer, points[0])
                if new_text is None:
                    return
                new = [new_text]
                description = "Новый текст"
            new = [replace(obj, clearance=clearance) for obj in new]
            self.undo.push(AddElements(self, index, new, description))
            return
        if mode == "track":
            element = core.new_track(board, layer, points, width)
            description = "Новая дорожка"
        else:
            # Pads belong to a copper side; any other active layer means the top side.
            layer = layer if layer in (1, 3) else 1
            ((x, y),) = points
            if mode == "pad":
                diameter, drill = self.pad_size.values()
                if drill >= diameter:
                    self.hint.setText("Отверстие должно быть меньше площадки")
                    return
                element = core.new_pad(board, layer, x, y, diameter, drill, self.pad_shape)
                description = "Новая площадка"
            else:
                width, height = self.smd_size.values()
                element = core.new_smd(board, layer, x, y, width, height)
                description = "Новая SMD-площадка"
        element = replace(element, clearance=self.clearance_box.value())
        self.undo.push(AddElements(self, self.board_select.currentIndex(), [element], description))

    def text_at(self, board, layer, position):
        """A new text from the text dialog, or None if cancelled or empty."""
        dialog = TextDialog(self, self.settings)
        if not dialog.exec():
            return None
        dialog.remember()
        values = dialog.values()
        if not values["text"].strip():
            self.hint.setText("Пустой текст не добавлен")
            return None
        if dialog.numbering.isChecked():
            values["text"] = core.numbered(values["text"], dialog.number.value())
            self.settings.setValue("text/number", dialog.number.value() + 1)
        # Texts on the bottom side are mirrored so that they read correctly from below.
        values["mirror_x"] = values["mirror_x"] != (layer in (3, 4))
        x, y = position
        return core.new_text(board, layer, x, y, **values)

    def save_macro(self):
        members = [
            i for i in sorted(self.view.members) if not core.is_hidden_label(self.view.elements[i])
        ]
        if self.view.board is None or not members:
            self.hint.setText("Выделите объекты, которые нужно сохранить как макрос")
            return
        folder = self.macros.folder() or str(Path.home())
        name, _ = QFileDialog.getSaveFileName(
            self, "Сохранить как макрос", folder, "Макросы (*.lmk)"
        )
        if not name:
            return
        path = Path(name).with_suffix(".lmk")
        elements = [self.view.elements[i] for i in members]
        try:
            path.write_bytes(core.macro_bytes(elements))
        except OSError as error:
            QMessageBox.warning(self, "Не удалось сохранить макрос", str(error))
            return
        self.hint.setText(f"Макрос сохранён: {path}")

    def place_macro(self, side, path, position, turns=0):
        if self.view.board is None:
            return
        try:
            elements = core.load_macro(Path(path))
        except (OSError, core.LayoutError) as error:
            QMessageBox.warning(self, "Не удалось загрузить макрос", f"{Path(path).name}\n{error}")
            return
        x, y = position
        placed = core.place_macro(elements, x, y, side)
        if not placed:
            return
        name = Path(path).stem
        if self.macros.as_component.isChecked():
            try:
                board = self.boards[self.board_select.currentIndex()]
                placed = core.make_component(board, placed, name, side)
            except core.LayoutError as error:
                QMessageBox.warning(self, "Не удалось создать компонент", str(error))
                return
            if turns % 4:
                placed = core.rotate_all(placed, -90 * (turns % 4))
            self.undo.push(
                AddElements(
                    self,
                    self.board_select.currentIndex(),
                    placed,
                    f"Компонент {name}",
                )
            )
            if self.component_dialog_on_drop:
                # As in the original: the new component's dialog opens right away
                # (after the drop has finished, so that it is not opened inside it).
                QTimer.singleShot(0, self.edit_component)
        else:
            self.undo.push(
                AddElements(
                    self,
                    self.board_select.currentIndex(),
                    core.rotate_all(core.strip_labels(placed), -90 * (turns % 4)),
                    f"Макрос {name}",
                )
            )

    # --- files ----------------------------------------------------------------

    def closeEvent(self, event):
        if self.can_discard():
            self.remove_autosave()
            event.accept()
        else:
            event.ignore()

    def about(self):
        QMessageBox.about(
            self,
            f"О программе «{APP_NAME}»",
            f"<b>{APP_NAME}</b><br>Версия {VERSION}<br><br>"
            "Редактор печатных плат в формате .lay6 и конвертер плат<br>"
            "Altium Designer, KiCad, Eagle и DipTrace.<br>"
            "Работает в Windows, Linux и macOS (Python, Qt).<br><br>"
            "Свободная программа, лицензия MIT.",
        )

    def show_board(self, index, *, refit=True, selection=None):
        if index < 0:
            return
        board = self.boards[index]
        self.view.select(None)
        self.view.set_measure(self.view.measuring)
        scene = self.view.scene()
        self.view.board = board
        self.view.origin = core.board_origin(board)
        scene.clear()
        # The marks of the test mode and of DRC were in the cleared scene.
        self.view.forget_scene_items()
        if self.view.mode == "photo":
            draw_photo(scene, board, self.photo_bar.options())
            self.groups, warnings = {}, set()
        else:
            self.groups, warnings = draw_board(
                scene, board, self.mask_side(), self.transparent_action.isChecked()
            )
            side = self.template_side()
            template = self.templates_of(board).get(side)
            item = template_item(template, side, board.height) if template else None
            if item is not None:
                scene.addItem(item)
        for layer, group in self.groups.items():
            available = layer not in (5, 6) or board.multilayer or bool(group.childItems())
            if layer in LAYER_HINTS:
                self.layer_bar.set_available(layer, available)
                group.setVisible(self.layer_bar.checks[layer].isChecked())
        self.update_through()
        if self.layer_bar.radios[self.view.active_layer].isHidden():
            self.set_active_layer(1)
        bounds = scene.itemsBoundingRect()
        margin = max(bounds.width(), bounds.height(), 1) * 0.035
        self.view.bounds = bounds.adjusted(-margin, -margin, margin, margin)
        scene.setSceneRect(self.view.bounds)
        self.hint.setToolTip("\n".join(sorted(warnings)))
        if refit:
            self.hint.setText(
                f"{board.name}: {mm(board.width, 1)} x {mm(board.height, 1)} мм"
                + ("   ⚠ " + "; ".join(sorted(warnings)) if warnings else "")
            )
            self.view.fit_board()
        self.update_board_actions()
        self.update_plane_button()
        self.refresh_lists()
        self.view.mark_points([])
        if isinstance(selection, list):
            self.view.set_selection(
                [i for i in selection if i < len(board.elements)],
                selection[0] if selection else None,
            )
        else:
            self.view.select(selection)

    def redraw_photo(self) -> None:
        if self.boards and self.view.mode == "photo":
            self.show_board(self.current_board_index(), refit=False)

    def update_through(self) -> None:
        """Through-hole pads have their own colour while both copper sides are shown;
        a ground plane is shown with its layer."""
        checks = self.layer_bar.checks
        if THROUGH in self.groups:
            self.groups[THROUGH].setVisible(checks[1].isChecked() and checks[3].isChecked())
        for layer in (1, 3, 5, 6):
            if PLANE + layer in self.groups:
                self.groups[PLANE + layer].setVisible(checks[layer].isChecked())

    def set_layer(self, layer, visible):
        if layer in self.groups:
            self.groups[layer].setVisible(visible)
            self.update_through()
            if not visible:
                self.view.select(None)
