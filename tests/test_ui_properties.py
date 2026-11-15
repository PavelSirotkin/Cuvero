"""Stage 3 in the window: the properties panel, display units and the coordinate origin."""

import unittest

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

import core
from tests.ui_base import WindowTestCase


class PropertiesTest(WindowTestCase):
    def setUp(self):
        super().setUp()
        self.window.set_units(False)
        self.panel = self.window.properties

    def tearDown(self):
        self.window.set_units(False)
        super().tearDown()

    def pad_index(self):
        return next(
            i
            for i, e in enumerate(self.board.elements)
            if e.kind == core.THT and abs(e.x - 27.13) < 0.01
        )

    def test_pad_page_shows_values_like_the_original(self):
        self.window.view.select(self.pad_index())
        p = self.panel
        self.assertIs(p.pages.currentWidget(), p.pad_page)
        self.assertAlmostEqual(p.pad_x.mm(), 27.13, places=3)
        self.assertAlmostEqual(p.pad_y.mm(), 97.44, places=3)
        self.assertAlmostEqual(p.pad_diameter.mm(), 1.0)
        self.assertAlmostEqual(p.pad_drill.mm(), 0.5)
        self.assertTrue(p.pad_plated.isChecked())

    def test_edit_pad_in_the_panel_and_undo(self):
        index = self.pad_index()
        self.window.view.select(index)
        self.panel.pad_diameter.setValue(1.8)
        self.assertAlmostEqual(self.board.elements[index].outer, 0.9)
        self.panel.pad_x.setValue(30.0)
        self.assertAlmostEqual(self.board.elements[index].x, 30.0)
        self.assertAlmostEqual(self.panel.pad_diameter.mm(), 1.8)  # panel refreshed
        self.window.undo.undo()
        self.window.undo.undo()
        self.assertAlmostEqual(self.board.elements[index].outer, 0.5)
        self.assertAlmostEqual(self.board.elements[index].x, 27.13, places=4)

    def test_drill_larger_than_pad_is_refused(self):
        index = self.pad_index()
        self.window.view.select(index)
        self.panel.pad_drill.setValue(5.0)
        self.assertAlmostEqual(self.board.elements[index].inner, 0.25)
        self.assertAlmostEqual(self.panel.pad_drill.mm(), 0.5)

    def test_thermal_relief_in_the_panel(self):
        index = self.pad_index()
        self.window.view.select(index)
        thermal = self.panel.pad_thermal
        self.assertFalse(thermal.enabled.isChecked())
        thermal.enabled.setChecked(True)
        pad = self.board.elements[index]
        self.assertTrue(core.has_thermal(pad))
        self.assertEqual(pad.record[62:66], core.THERMAL_MARKER)
        self.assertAlmostEqual(pad.width, 1 / 3, places=6)
        self.assertEqual(bin(thermal.spokes.bits).count("1"), 4)
        thermal.spoke_toggled(2)  # a click on one of the squares
        self.assertEqual(core.thermal_directions(self.board.elements[index]), 0x51)
        thermal.slider.setValue(200)
        pad = self.board.elements[index]
        self.assertEqual(pad.rotation, 200)
        self.assertAlmostEqual(pad.width, 2 / 3, places=6)
        self.assertIn("0,67", thermal.width_label.text())
        thermal.single_layer.setChecked(True)
        thermal.layer.setCurrentIndex(1)  # C2 only
        thermal.spoke_toggled(0)
        mask = self.board.elements[index].start & 0xFFFFFFFF
        self.assertEqual(mask, 0x51515051)
        for _ in range(5):
            self.window.undo.undo()
        self.assertFalse(core.has_thermal(self.board.elements[index]))

    def test_mil_units(self):
        self.window.view.select(self.pad_index())
        self.window.set_units(True)
        self.assertEqual(self.panel.unit_labels[0].text(), "mil")
        self.assertAlmostEqual(self.panel.pad_diameter.value(), 1.0 / 0.0254, places=1)
        self.assertAlmostEqual(self.panel.pad_diameter.mm(), 1.0, places=3)
        self.assertIn("mil", self.window.coordinates.text() + self.window.hint.text())

    def test_mil_rounding_does_not_change_other_values(self):
        index = self.pad_index()
        self.window.view.select(index)
        self.window.set_units(True)
        self.panel.pad_drill.setValue(25.0)  # 0.635 mm
        pad = self.board.elements[index]
        self.assertEqual(pad.outer, 0.5)  # the diameter was not touched
        self.assertAlmostEqual(pad.inner * 2, 0.635, places=6)

    def test_ruler_corner_toggles_units(self):
        viewport = self.window.view.viewport()
        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=QPointF(5, 5).toPoint())
        self.assertTrue(self.window.units.mil)
        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=QPointF(5, 5).toPoint())
        self.assertFalse(self.window.units.mil)

    def test_track_page_and_multi_selection(self):
        elements = self.board.elements
        tracks = [
            i
            for i, e in enumerate(elements)
            if e.kind == core.LINE and len(core.unit_of(elements, i)) == 1
        ][:3]
        self.window.view.select(tracks[0])
        self.assertIs(self.panel.pages.currentWidget(), self.panel.track_page)
        self.window.view.set_selection(tracks)
        self.assertIs(self.panel.pages.currentWidget(), self.panel.multi_page)
        self.assertIn("Дорожка: 3", self.panel.multi_list.text())
        self.panel.multi_track_width.setValue(0.7)
        self.assertEqual({round(elements[i].width, 4) for i in tracks}, {0.7})
        self.window.undo.undo()  # one step for all tracks
        self.assertNotEqual({round(elements[i].width, 4) for i in tracks}, {0.7})

    def test_board_page_changes_the_board(self):
        self.window.view.select(None)
        self.assertIs(self.panel.pages.currentWidget(), self.panel.board_page)
        self.panel.board_width.setValue(55.0)
        self.assertEqual(self.window.boards[0].width, 55.0)
        self.assertEqual(self.panel.board_width.mm(), 55.0)
        self.window.undo.undo()
        self.assertEqual(self.window.boards[0].width, 40.0)

    def test_origin_moves_displayed_coordinates(self):
        index = self.pad_index()
        self.window.set_origin("top_left")
        self.assertEqual(self.window.view.origin, (0.0, 0.0))
        self.window.view.select(index)
        self.assertAlmostEqual(self.panel.pad_y.mm(), -2.56, places=3)
        self.window.undo.undo()
        self.assertEqual(self.window.view.origin, (0.0, -100.0))

    def test_polygon_hatching(self):
        w = self.window
        w.boards[0].elements.append(
            core.Element(
                core.POLYGON,
                layer=1,
                width=0.1,
                points=[(1, -1), (5, -1), (5, -5), (1, -5), (1, -1)],
                mirror_y=True,
            )
        )
        w.show_board(0)
        index = len(w.boards[0].elements) - 1
        w.view.select(index)
        self.assertIs(self.panel.pages.currentWidget(), self.panel.polygon_page)
        self.panel.polygon_hatched.setChecked(True)
        self.assertTrue(core.is_hatched(w.boards[0].elements[index]))
        self.panel.hatch_own.setChecked(True)
        self.panel.hatch_width.setValue(0.8)
        polygon = w.boards[0].elements[index]
        self.assertFalse(core.hatch_uses_outline(polygon))
        self.assertAlmostEqual(core.hatch_width(polygon), 0.8)


if __name__ == "__main__":
    unittest.main()
