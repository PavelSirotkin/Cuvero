"""Application-wide set-up: Russian texts of Qt's own dialogs and Russian number format."""

import contextlib
import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from version import VERSION

from .style import APP_NAME

RUSSIAN = QLocale(QLocale.Language.Russian, QLocale.Country.Russia)
ICON = Path(__file__).resolve().parent.parent / "icon.ico"
TRANSLATIONS = ICON.parent / "translations"


def install_russian(app: QApplication) -> bool:
    """Translate Qt's standard buttons and dialogs into Russian, whatever the system language.

    Returns False when the translation shipped with PySide6 cannot be found.
    """
    QLocale.setDefault(RUSSIAN)
    if app.property("russian_installed"):
        return True
    translator = QTranslator(app)
    # Qt's own folder when run from Python; a built program (build.py) carries the file
    # in "translations" next to it.
    folders = [QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath), str(TRANSLATIONS)]
    if not any(translator.load(RUSSIAN, "qtbase", "_", folder) for folder in folders):
        return False
    app.installTranslator(translator)
    app.setProperty("russian_installed", True)
    return True


def app_icon() -> QIcon:
    """The program's icon (empty if the file is missing)."""
    return QIcon(str(ICON)) if ICON.exists() else QIcon()


def own_taskbar_entry() -> None:
    """On Windows, group the windows under our own icon instead of the Python interpreter's."""
    if sys.platform == "win32":
        import ctypes

        with contextlib.suppress(AttributeError, OSError):
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_NAME)


def setup_application(app: QApplication) -> None:
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setWindowIcon(app_icon())
    own_taskbar_entry()
    install_russian(app)
