"""Undoable editing commands."""

from PySide6.QtGui import QUndoCommand

import core


class EditGeometry(QUndoCommand):
    """Replace objects by index: {index: (old, new)}."""

    def __init__(self, window, board, changes, selection, description):
        super().__init__(description)
        self.window, self.board, self.changes, self.selection = window, board, changes, selection

    def apply(self, which):
        elements = self.window.boards[self.board].elements
        for index, pair in self.changes.items():
            elements[index] = pair[which]
        if self.window.board_select.currentIndex() == self.board:
            self.window.show_board(self.board, refit=False, selection=self.selection)

    def undo(self):
        self.apply(0)

    def redo(self):
        self.apply(1)


class AddElements(QUndoCommand):
    """Append objects; undo removes them from the end, so other indices stay valid."""

    def __init__(self, window, board, elements, description):
        super().__init__(description)
        self.window, self.board, self.elements = window, board, list(elements)

    def show(self, selection):
        if self.window.board_select.currentIndex() == self.board:
            self.window.show_board(self.board, refit=False, selection=selection)

    def undo(self):
        del self.window.boards[self.board].elements[-len(self.elements) :]
        self.show(None)

    def redo(self):
        elements = self.window.boards[self.board].elements
        elements.extend(self.elements)
        self.show(list(range(len(elements) - len(self.elements), len(elements))))


class InsertBoard(QUndoCommand):
    """Insert a board at a position; undo removes it again."""

    def __init__(self, window, index, board, description=None):
        super().__init__(description or f"Новая плата «{board.name}»")
        self.window, self.index, self.board = window, index, board

    def redo(self):
        self.window.boards.insert(self.index, self.board)
        self.window.rebuild_tabs(self.index)

    def undo(self):
        del self.window.boards[self.index]
        self.window.rebuild_tabs(min(self.index, len(self.window.boards) - 1))


class AddBoard(InsertBoard):
    """Append a board as the last one."""

    def __init__(self, window, board):
        super().__init__(window, len(window.boards), board)


class RemoveBoard(QUndoCommand):
    def __init__(self, window, index):
        super().__init__(f"Удаление платы «{window.boards[index].name}»")
        self.window, self.index = window, index
        self.board = window.boards[index]

    def redo(self):
        del self.window.boards[self.index]
        self.window.rebuild_tabs(min(self.index, len(self.window.boards) - 1))

    def undo(self):
        self.window.boards.insert(self.index, self.board)
        self.window.rebuild_tabs(self.index)


class MoveBoard(QUndoCommand):
    def __init__(self, window, old, new):
        super().__init__(f"Перестановка платы «{window.boards[old].name}»")
        self.window, self.old, self.new = window, old, new

    def move(self, source, target):
        board = self.window.boards.pop(source)
        self.window.boards.insert(target, board)
        self.window.rebuild_tabs(target)

    def redo(self):
        self.move(self.old, self.new)

    def undo(self):
        self.move(self.new, self.old)


class ReplaceBoard(QUndoCommand):
    """Swap a board for a changed version of it: new name, size or layers."""

    def __init__(self, window, index, old, new, description):
        super().__init__(description)
        self.window, self.index, self.old, self.new = window, index, old, new

    def apply(self, board):
        window = self.window
        old = window.boards[self.index]
        same_size = (board.name, board.width, board.height) == (old.name, old.width, old.height)
        window.boards[self.index] = board
        if same_size and window.board_select.currentIndex() == self.index:
            # Only the objects changed (autorouter, external program): keep the zoom.
            window.show_board(self.index, refit=False)
        else:
            window.rebuild_tabs(self.index)

    def undo(self):
        self.apply(self.old)

    def redo(self):
        self.apply(self.new)


class RenameBoard(ReplaceBoard):
    def __init__(self, window, index, old, new):
        super().__init__(window, index, old, new, f"Имя платы «{new.name}»")


class SetProjectInfo(QUndoCommand):
    """Change title, author, company and comment stored at the end of the file."""

    def __init__(self, window, info):
        super().__init__("Сведения о проекте")
        self.window = window
        self.old = window.project.trailer
        self.new = core.with_project_info(window.project, info).trailer

    def redo(self):
        self.window.project.trailer = self.new

    def undo(self):
        self.window.project.trailer = self.old


class DeleteElements(QUndoCommand):
    """Remove objects; undo puts them back at their old positions."""

    def __init__(self, window, board, indices, description):
        super().__init__(description)
        self.window, self.board, self.indices = window, board, sorted(set(indices))
        self.removed = []
        self.connections = []

    def show(self, selection):
        if self.window.board_select.currentIndex() == self.board:
            self.window.show_board(self.board, refit=False, selection=selection)

    def redo(self):
        board = self.window.boards[self.board]
        # Air wires refer to object positions: renumber them before objects shift.
        changed = core.renumbered(board, self.indices)
        self.connections = [(i, board.elements[i]) for i in changed]
        for i, obj in changed.items():
            board.elements[i] = obj
        self.removed = core.delete_elements(board, self.indices)
        self.show(None)

    def undo(self):
        board = self.window.boards[self.board]
        core.restore_elements(board, self.removed)
        for i, obj in self.connections:
            board.elements[i] = obj
        self.show(list(self.indices))
