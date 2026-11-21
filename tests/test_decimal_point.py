"""Number fields take a decimal point as well as a comma."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QSpinBox  # noqa: E402

from ui.application import setup_application  # noqa: E402


class DecimalPoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = QApplication.instance() or QApplication([])
        assert isinstance(app, QApplication)
        setup_application(app)

    def typed(self, keys: str) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setDecimals(3)
        box.setRange(0, 100)
        box.show()
        box.lineEdit().selectAll()
        QTest.keyClicks(box, keys)
        QTest.keyClick(box, Qt.Key.Key_Return)
        return box

    def test_point_and_comma(self):
        self.assertEqual(self.typed("1.5").value(), 1.5)
        self.assertEqual(self.typed("2,25").value(), 2.25)
        self.assertEqual(self.typed("3.75").text(), "3,750")  # shown with a comma

    def test_whole_number_fields_untouched(self):
        box = QSpinBox()
        box.show()
        box.lineEdit().selectAll()
        QTest.keyClicks(box, "12.")
        self.assertEqual(box.value(), 12)


if __name__ == "__main__":
    unittest.main()
