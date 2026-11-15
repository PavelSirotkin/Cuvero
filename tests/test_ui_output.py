"""Stage 5 in the window: Gerber, drill, milling, image, print, hole list and Gerber import."""

from pathlib import Path
from unittest import mock

from PySide6.QtGui import QImage, QPageLayout
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QFileDialog, QMessageBox

import core
from tests.ui_base import SAMPLE, WindowTestCase
from ui.export_dialogs import DrillDialog, GerberDialog, HoleListDialog, ImageDialog
from ui.import_dialog import GerberImportDialog
from ui.milling import MillingDialog
from ui.printing import PrintDialog

SAMPLES = SAMPLE.parent


class OutputTest(WindowTestCase):
    def folder(self) -> Path:
        path = Path(self.temp.name) / self.id().rsplit(".", 1)[-1]
        path.mkdir(exist_ok=True)
        return path

    def save_as(self, path):
        return mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(path), ""))

    def test_gerber_files(self):
        folder = self.folder()
        self.window.settings.setValue("gerber/folder", str(folder))
        # The dialog writes the files itself and stays open, like the original.
        with mock.patch.object(GerberDialog, "exec", lambda dialog: dialog.create_files()):
            self.window.export_gerber()
        names = sorted(p.name for p in folder.iterdir())
        self.assertIn("motor ir2101_copper_top.gbr", names)
        self.assertIn("motor ir2101_soldermask_bottom.gbr", names)
        self.assertNotIn("motor ir2101_copper_inner1.gbr", names)
        text = (folder / "motor ir2101_copper_top.gbr").read_text(encoding="utf-8")
        self.assertIn("%TF.FileFunction,Copper,L1,Top*%", text)

    def test_gerber_layers_without_objects_are_off(self):
        dialog = GerberDialog(
            self.window, self.window.settings, self.window.current_board(), "x", 1, Path(".")
        )
        self.assertFalse(dialog.layers["silkscreen_bottom"].isEnabled())
        self.assertFalse(dialog.layers["copper_inner1"].isEnabled())
        self.assertTrue(dialog.layers["copper_top"].isEnabled())

    def test_drill_file_matches_the_original(self):
        target = self.folder() / "out.DRL"
        with (
            mock.patch.object(DrillDialog, "exec", return_value=1),
            self.save_as(target),
            mock.patch.object(QMessageBox, "information"),
        ):
            self.window.export_drill()
        self.assertEqual(target.read_bytes(), (SAMPLES / "motor ir2101.DRL").read_bytes())

    def test_milling(self):
        target = self.folder() / "mill.plt"
        settings = self.window.settings
        settings.setValue("milling/drill_side", 1)
        settings.setValue("milling/save_list", True)
        settings.setValue("milling/register", 2)
        with (
            mock.patch.object(MillingDialog, "exec", return_value=1),
            self.save_as(target),
            mock.patch.object(QMessageBox, "information"),
        ):
            self.window.export_milling()
        text = target.read_text(encoding="ascii")
        self.assertTrue(text.startswith("IN;\nPA;\nSP1;"))
        self.assertGreater(text.count("PD"), 60)
        self.assertIn("SP3;", text)  # isolation, drilling, reference holes
        self.assertTrue(target.with_suffix(".txt").exists())

    def test_milling_job_order(self):
        settings = self.window.settings
        settings.setValue("milling/drill_side", 1)
        settings.setValue("milling/register", 0)
        settings.setValue("milling/bottom", False)
        dialog = MillingDialog(self.window, settings, self.window.current_board())
        self.assertEqual(dialog.current_order()[:2], ["iso_top", "drill_all"])
        moved = dialog.jobs_view.takeTopLevelItem(0)
        dialog.jobs_view.addTopLevelItem(moved)
        dialog.renumber()
        jobs = dialog.jobs()
        self.assertEqual([job.pen for job in jobs], [1, 2])
        self.assertTrue(jobs[0].drills and jobs[1].paths)

    def test_image_png_and_svg(self):
        folder = self.folder()
        self.window.settings.setValue("image/dpi", 300)
        for suffix in ("png", "svg"):
            with (
                mock.patch.object(ImageDialog, "exec", return_value=1),
                self.save_as(folder / f"board.{suffix}"),
                mock.patch.object(QMessageBox, "information"),
            ):
                self.window.export_image(suffix)
        image = QImage(str(folder / "board.png"))
        board = self.window.current_board()
        self.assertEqual(image.width(), round(board.width * 300 / 25.4))
        self.assertIn("<svg", (folder / "board.svg").read_text(encoding="utf-8"))

    def test_print_to_pdf(self):
        board = self.window.current_board()
        dialog = PrintDialog(self.window, self.window.settings, board, "t")
        dialog.layer_checks["C2"][0].setChecked(True)
        dialog.options["marks"].setChecked(True)
        dialog.center()
        extent = dialog.sheet().extent()
        page = dialog.preview.page
        self.assertAlmostEqual(extent.center().x(), page.width() / 2, delta=1)
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        target = self.folder() / "print.pdf"
        printer.setOutputFileName(str(target))
        printer.setPageOrientation(QPageLayout.Orientation.Portrait)
        dialog.paint(printer)
        self.assertGreater(target.stat().st_size, 1000)

    def test_hole_list(self):
        dialog = HoleListDialog(self.window, self.window.current_board())
        self.assertIn("64 x  0,50 мм", dialog.text)
        holes = len(core.holes(self.window.current_board()))
        self.assertTrue(dialog.text.rstrip().endswith(f"{holes} отв."))
        dialog.plated.setChecked(False)
        self.assertIn(" 0 отв.", dialog.text)

    def test_gerber_import_into_a_new_board(self):
        boards = len(self.window.boards)

        def fill(dialog):
            dialog.files[1].setText(str(SAMPLES / "motor ir2101_copper_top.gbr"))
            dialog.files[3].setText(str(SAMPLES / "motor ir2101_copper_bottom.gbr"))
            dialog.drill.setText(str(SAMPLES / "motor ir2101.DRL"))
            dialog.auto_format()
            dialog.update_picture()
            assert dialog.image is not None
            dialog.new_board.setChecked(True)
            return 1

        with (
            mock.patch.object(GerberImportDialog, "exec", fill),
            mock.patch.object(QMessageBox, "information"),
        ):
            self.window.import_gerber()
        self.assertEqual(len(self.window.boards), boards + 1)
        board = self.window.boards[-1]
        pads = [e for e in board.elements if e.kind == core.THT]
        self.assertEqual(len(pads), 64)  # every drill hole has its pad or a bare hole
        self.assertTrue(core.has_plane(board, 1))
        self.assertTrue(core.has_plane(board, 3))
        # Displayed coordinates stay those of the Gerber files.
        ox, oy = core.board_origin(board)
        first = pads[0]
        self.assertTrue(0 <= first.x - ox <= 40 and 75 <= first.y - oy <= 100)
        self.window.undo.undo()
        self.assertEqual(len(self.window.boards), boards)
