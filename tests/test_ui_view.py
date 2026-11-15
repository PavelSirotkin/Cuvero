"""Stage 6 in the window: exact planes, through-hole pads, photo view, mask, transparency,
zoom, overview and the background template."""

from pathlib import Path

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsPixmapItem

import core
from tests.ui_base import WindowTestCase
from ui.render import MASK_COLOR, plane_colour, plane_path
from ui.style import THROUGH, THROUGH_COLOR
from ui.template import Template, save_templates, settings_key


class ViewTest(WindowTestCase):
    def path_items(self, colour: QColor):
        return [
            item
            for item in self.window.view.scene().items()
            if isinstance(item, QGraphicsPathItem) and item.brush().color() == colour
        ]

    def test_plane_is_exact(self):
        board = self.board
        plane = plane_path(board, 1)
        pad = next(e for e in board.elements if e.kind == core.THT and e.clearance > 0)
        # The clearance ring around a pad is cut out of the plane.
        edge = QPointF(pad.x + pad.outer + pad.clearance / 2, -pad.y)
        self.assertFalse(plane.contains(edge))
        self.assertTrue(self.path_items(plane_colour(1)))
        # 60 % of the layer colour, as measured on the original's screen.
        self.assertEqual(plane_colour(1).name(), "#123f95")

    def test_through_pads_have_their_own_colour(self):
        w = self.window
        self.assertTrue(w.groups[THROUGH].isVisible())
        self.assertTrue(self.path_items(QColor(THROUGH_COLOR)))
        w.layer_bar.checks[3].setChecked(False)
        self.assertFalse(w.groups[THROUGH].isVisible())
        w.layer_bar.checks[3].setChecked(True)
        self.assertTrue(w.groups[THROUGH].isVisible())

    def test_photo_view(self):
        w = self.window
        w.mode_actions["photo"].trigger()
        self.assertTrue(w.photo_bar.isVisibleTo(w))
        self.assertEqual(w.groups, {})
        gold = QColor("#dcaa14")
        self.assertTrue(self.path_items(gold))
        w.photo_bar.side.button(1).setChecked(True)  # bottom, mirrored
        mirrored = [i for i in w.view.scene().items() if i.transform().m11() == -1]
        self.assertTrue(mirrored)
        w.mode_actions["edit"].trigger()
        self.assertFalse(w.photo_bar.isVisibleTo(w))
        self.assertIn(1, w.groups)

    def test_transparent_mode(self):
        w = self.window
        w.transparent_action.setChecked(True)
        self.assertAlmostEqual(w.groups[1].opacity(), 0.6)
        w.transparent_action.setChecked(False)
        self.assertAlmostEqual(w.groups[1].opacity(), 1.0)

    def test_mask_follows_the_active_side(self):
        w = self.window
        w.mask_action.setChecked(True)
        top = [item.path() for item in self.path_items(MASK_COLOR)]
        w.set_active_layer(3)
        self.assertEqual(w.mask_side(), 3)
        bottom = [item.path() for item in self.path_items(MASK_COLOR)]
        self.assertEqual(len(top), 1)
        self.assertNotEqual(top[0].elementCount(), bottom[0].elementCount())
        w.mask_action.setChecked(False)

    def test_zoom_selection_and_previous(self):
        w = self.window
        w.view.fit_board()
        before = w.view.transform().m11()
        pad = next(i for i, e in enumerate(self.board.elements) if e.kind == core.THT)
        w.view.select(pad)
        w.zoom_selection()
        self.assertGreater(w.view.transform().m11(), before * 3)
        w.view.zoom_previous()
        self.assertAlmostEqual(w.view.transform().m11(), before)
        w.zoom_objects_action.trigger()
        self.assertTrue(w.view.zoom_previous())

    def test_overview_draws(self):
        image = self.window.overview.grab().toImage()
        green = QColor("#00ff00").rgb()
        self.assertTrue(
            any(
                image.pixel(x, y) == green
                for x in range(0, image.width(), 3)
                for y in range(0, image.height(), 3)
            )
        )

    def test_template_under_the_board(self):
        w = self.window
        picture = Path(self.temp.name) / "scan.png"
        image = QImage(200, 100, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        for x in range(200):
            image.setPixelColor(x, 50, QColor("black"))
        image.save(str(picture))
        key = settings_key(w.path, self.board.name)
        save_templates(
            w.settings,
            key,
            {1: Template(str(picture), dpi=254, dx=50, dy=20), 2: Template(str(picture))},
        )
        w.show_board(w.current_board_index(), refit=False)
        (item,) = [i for i in w.view.scene().items() if isinstance(i, QGraphicsPixmapItem)]
        self.assertAlmostEqual(item.transform().m11(), 0.1)  # 254 dpi: 0.1 mm per pixel
        self.assertEqual((item.pos().x(), item.pos().y()), (5.0, -2.0))
        w.set_active_layer(3)
        (item,) = [i for i in w.view.scene().items() if isinstance(i, QGraphicsPixmapItem)]
        self.assertAlmostEqual(item.transform().m11(), 25.4 / 600)
        save_templates(w.settings, key, {})
