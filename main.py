"""Запуск редактора плат: python main.py [файл.lay6]"""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from ui.application import setup_application
from ui.main_window import MainWindow


def main():
    app = QApplication([sys.argv[0]])
    setup_application(app)
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        window.open_path(Path(sys.argv[1]))
    else:
        window.offer_recovery(None)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
