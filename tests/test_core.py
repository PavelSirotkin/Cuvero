"""Tests of the file format core on the sample boards and the macro library."""

import unittest
from pathlib import Path

import core
from tests.samples import require_samples

require_samples()

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = sorted((ROOT / "Samples").glob("*.lay6")) + sorted((ROOT / "Verification").glob("*.lay6"))
MACROS = sorted(p for p in (ROOT / "MAKROS").rglob("*") if p.suffix.lower() == ".lmk")
DIP = ROOT / "MAKROS" / "Through-Hole (TH)" / "TH - DIL" / "14DIP300.LMK"


def sample(name="motor ir2101.lay6"):
    return core.parse_project((ROOT / "Samples" / name).read_bytes())


def reread(project):
    return core.parse_project(core.serialize(project))


class RoundTrip(unittest.TestCase):
    def test_unchanged_projects_are_written_byte_for_byte(self):
        self.assertTrue(SAMPLES)
        for path in SAMPLES:
            with self.subTest(path.name):
                data = path.read_bytes()
                self.assertEqual(core.serialize(core.parse_project(data)), data)


class NewObjects(unittest.TestCase):
    def test_track_pad_and_smd_survive_saving(self):
        project = sample()
        board = project.boards[0]
        count = len(board.elements)
        board.elements += [
            core.new_track(board, 3, [(1, 1), (5, 1), (5, 4)], 0.4),
            core.new_pad(board, 1, 10, 10, 1.6, 0.8, shape=2),
            core.new_smd(board, 1, 20, 10, 1.0, 1.5),
        ]
        added = reread(project).boards[0].elements[count:]
        self.assertEqual([obj.kind for obj in added], [core.LINE, core.THT, core.SMD])
        self.assertEqual(added[0].points, [(1, 1), (5, 1), (5, 4)])
        self.assertAlmostEqual(added[1].outer, 0.8)
        self.assertEqual(added[1].shape, 2)

    def test_resized_smd_keeps_its_centre(self):
        board = sample().boards[0]
        pad = core.resized_smd(core.new_smd(board, 1, 8, -5, 1.0, 1.5), 2.0, 1.0)
        xs = [x for x, _ in pad.points]
        ys = [y for _, y in pad.points]
        self.assertAlmostEqual(max(xs) - min(xs), 2.0)
        self.assertAlmostEqual(max(ys) - min(ys), 1.0)
        self.assertAlmostEqual(sum(xs) / 4, 8)


class Deleting(unittest.TestCase):
    def test_delete_and_restore_keep_positions(self):
        project = sample()
        board = project.boards[0]
        original = list(board.elements)
        removed = core.delete_elements(board, [5, 0, 40, 5])
        self.assertEqual([i for i, _ in removed], [0, 5, 40])
        self.assertEqual(len(board.elements), len(original) - 3)
        self.assertEqual(len(reread(project).boards[0].elements), len(board.elements))
        core.restore_elements(board, removed)
        self.assertEqual(board.elements, original)
        self.assertEqual(
            core.serialize(project), (ROOT / "Samples" / "motor ir2101.lay6").read_bytes()
        )

    def test_sample_boards_have_no_air_wires(self):
        # Only the original program's samples: boards saved for checking in Verification
        # (converted from other programs, say) may well carry air wires.
        for path in sorted((ROOT / "Samples").glob("*.lay6")):
            for board in core.parse_project(path.read_bytes()).boards:
                self.assertFalse(core.has_connections(board), f"{path.name}: {board.name}")


@unittest.skipUnless(MACROS, "no macro library in MAKROS")
class Macros(unittest.TestCase):
    def test_every_macro_loads(self):
        for path in MACROS:
            with self.subTest(path.name):
                self.assertIsInstance(core.load_macro(path), list)

    def test_bottom_side_swaps_layers(self):
        macro = core.load_macro(DIP)
        top = {obj.layer for obj in core.place_macro(macro, 0, 0, "top")}
        bottom = {obj.layer for obj in core.place_macro(macro, 0, 0, "bottom")}
        self.assertEqual({core.SIDE_SWAP.get(layer, layer) for layer in top}, bottom)

    def test_every_macro_becomes_one_component(self):
        project = sample()
        board = project.boards[0]
        base = list(board.elements)
        for path in MACROS:
            with self.subTest(path.name):
                placed = core.make_component(
                    board, core.place_macro(core.load_macro(path), 10, -10), path.stem
                )
                ids = {core.component_id(obj) for obj in placed}
                self.assertEqual(len(ids), 1)
                cid = ids.pop()
                self.assertGreater(cid, 0)
                labels = sorted(obj.shape for obj in placed if core.is_label(obj))
                self.assertEqual(labels, [core.COMPONENT_REF, core.COMPONENT_VALUE])
                self.assertTrue(core.component_package(placed, cid))
                board.elements = base + placed
                self.assertEqual(len(reread(project).boards[0].elements), len(board.elements))


class NewBoards(unittest.TestCase):
    def test_new_project_with_every_board_kind(self):
        project = core.new_project(core.board_from_dialog("Плата", "rect", 160, 100, 20))
        project.boards.append(core.board_from_dialog("Круглая", "round", 50, 50, 5))
        project.boards.append(core.board_from_dialog("Пустая", "empty", 100, 80))
        data = core.serialize(project)
        boards = core.parse_project(data).boards
        self.assertEqual([b.name for b in boards], ["Плата", "Круглая", "Пустая"])
        self.assertEqual([(b.width, b.height) for b in boards], [(200, 140), (60, 60), (100, 80)])
        self.assertEqual(boards[0].elements[0].points[0], (20, -20))
        self.assertEqual(boards[1].elements[0].kind, core.CIRCLE)
        self.assertEqual(core.serialize(core.parse_project(data)), data)

    def test_rename_board(self):
        project = sample()
        project.boards[0] = core.rename_board(project.boards[0], "Другое имя")
        self.assertEqual(reread(project).boards[0].name, "Другое имя")


if __name__ == "__main__":
    unittest.main()
