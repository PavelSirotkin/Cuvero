"""Shared set-up for tests of the main window, run without a visible screen."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QStandardPaths  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core  # noqa: E402
from tests.samples import NO_SAMPLES, have_samples  # noqa: E402
from ui.application import setup_application  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "Samples" / "motor ir2101.lay6"
DIP = ROOT / "MAKROS" / "Through-Hole (TH)" / "TH - DIL" / "14DIP300.LMK"


class WindowTestCase(unittest.TestCase):
    """Opens the sample board in a fresh window; settings live in a temporary folder."""

    app: object
    temp: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls):
        if not have_samples():
            raise unittest.SkipTest(NO_SAMPLES)
        app = QApplication.instance() or QApplication([])
        assert isinstance(app, QApplication)
        setup_application(app)
        cls.app = app
        cls.temp = tempfile.TemporaryDirectory()
        # Keep the user's real settings and autosave folder untouched.
        QStandardPaths.setTestModeEnabled(True)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.window = MainWindow()
        # A modal dialog would block the tests; the one test of it switches it on.
        self.window.component_dialog_on_drop = False
        self.window.resize(1400, 900)
        self.window.show()
        self.window.open_path(SAMPLE)
        self.board = self.window.boards[0]
        self.count = len(self.board.elements)

    def tearDown(self):
        self.window.undo.setClean()
        self.window.close()

    def saved(self):
        path = Path(self.temp.name) / "saved.lay6"
        self.window.save_copy(path)
        return core.parse_project(path.read_bytes()).boards[0].elements
