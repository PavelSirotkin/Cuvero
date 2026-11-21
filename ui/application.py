"""Application-wide set-up: Russian texts of Qt's own dialogs and Russian number format."""

import contextlib
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QLibraryInfo, QLocale, QObject, QTranslator
from PySide6.QtGui import QIcon, QKeyEvent
from PySide6.QtWidgets import QApplication, QDoubleSpinBox

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


class DecimalPoint(QObject):
    """Number fields take a point as well as a comma: a point typed into a field with
    decimals becomes the field's decimal sign (a comma in Russian), so the point key
    of an English keyboard layout or of the number pad works too."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt)
        if (
            event.type() == QEvent.Type.KeyPress
            and isinstance(watched, QDoubleSpinBox)
            and isinstance(event, QKeyEvent)
            and event.text() in (".", ",")
        ):
            sign = watched.locale().decimalPoint()
            if event.text() != sign:
                key = QKeyEvent(
                    QEvent.Type.KeyPress, event.key(), event.modifiers(), sign, event.isAutoRepeat()
                )
                QApplication.sendEvent(watched, key)
                return True
        return super().eventFilter(watched, event)


def accept_decimal_point(app: QApplication) -> None:
    if app.property("decimal_point_installed"):
        return
    point = DecimalPoint(app)  # the application owns it, so it lives as long
    app.installEventFilter(point)
    app.setProperty("decimal_point_installed", True)


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
    accept_decimal_point(app)
