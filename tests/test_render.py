"""Drawing of thermal spokes in ground planes and of solder mask openings."""

import os
import unittest
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import core  # noqa: E402
from ui.render import point, soldermask_overlay, thermal_spokes  # noqa: E402


def board():
    return core.board_from_dialog("Проба", "empty", 30, 20)


class Render(unittest.TestCase):
    app: object

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_spokes_point_in_their_directions(self):
        pad = core.with_thermal(core.new_pad(board(), 1, 10, -10, 1.8, 0.8), True)
        spokes = thermal_spokes(pad, 1)
        assert spokes is not None
        reach = pad.outer + pad.clearance
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            self.assertTrue(spokes.contains(point(10 + dx * reach, -10 + dy * reach)))
        self.assertFalse(spokes.contains(point(10 + reach * 0.7, -10 + reach * 0.7)))
        # Without bit 2 (pointing along the pad's orientation, here to the right).
        fewer = core.with_thermal(pad, True, 0x51)
        spokes = thermal_spokes(fewer, 1)
        assert spokes is not None
        self.assertFalse(spokes.contains(point(10 + reach, -10)))
        self.assertTrue(spokes.contains(point(10 - reach, -10)))

    def test_no_spokes_without_thermal_relief(self):
        pad = core.new_pad(board(), 1, 10, -10, 1.8, 0.8)
        self.assertIsNone(thermal_spokes(pad, 1))

    def test_mask_opening_follows_the_flag(self):
        b = board()
        pad = core.new_pad(b, 1, 10, -10, 1.8, 0.8)
        b.elements.append(pad)
        centre = point(10.5, -10)
        self.assertFalse(soldermask_overlay(b).contains(centre))  # opening in the mask
        b.elements[0] = replace(pad, soldermask=False)
        self.assertTrue(soldermask_overlay(b).contains(centre))  # covered by the mask


if __name__ == "__main__":
    unittest.main()
