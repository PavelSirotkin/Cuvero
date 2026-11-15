"""Project information, active board and whole-board operations."""

import unittest
from pathlib import Path

import core
from tests.samples import require_samples

require_samples()

ROOT = Path(__file__).resolve().parent.parent
HLDI = ROOT / "Samples" / "HLDI_ALL_PCB.lay6"
MOTOR = ROOT / "Samples" / "motor ir2101.lay6"


def reread(project):
    return core.parse_project(core.serialize(project))


class Information(unittest.TestCase):
    def test_samples_have_empty_information(self):
        self.assertEqual(
            core.project_info(core.parse_project(MOTOR.read_bytes())), core.ProjectInfo()
        )

    def test_unchanged_information_keeps_the_bytes(self):
        data = HLDI.read_bytes()
        project = core.parse_project(data)
        same = core.with_project_info(project, core.project_info(project))
        self.assertEqual(core.serialize(same), data)

    def test_round_trip_with_cyrillic_and_lines(self):
        info = core.ProjectInfo("Драйвер мотора", "Павел", "Мастерская", "Строка 1\nСтрока 2")
        project = core.with_project_info(core.parse_project(MOTOR.read_bytes()), info)
        self.assertEqual(core.project_info(reread(project)), info)
        self.assertIn(b"\r\n", project.trailer)  # Windows line breaks inside the file

    def test_long_texts_are_cut_to_the_file_limits(self):
        info = core.ProjectInfo("Н" * 150, comment="к" * 3000)
        stored = core.project_info(
            core.with_project_info(core.parse_project(MOTOR.read_bytes()), info)
        )
        self.assertEqual(len(stored.title), core.TEXT_LIMIT)
        self.assertEqual(len(stored.comment), core.COMMENT_LIMIT)


class Planes(unittest.TestCase):
    def test_switching_a_plane_on_and_off(self):
        board = core.board_from_dialog("Пустая", "empty", 50, 40)
        self.assertFalse(core.has_plane(board, 1))
        on = core.with_plane(board, 1, True)
        self.assertTrue(core.has_plane(on, 1))
        self.assertFalse(core.has_plane(on, 3))
        project = core.new_project(on)
        again = reread(project).boards[0]
        self.assertTrue(core.has_plane(again, 1))
        self.assertFalse(core.has_plane(core.with_plane(again, 1, False), 1))


class Boards(unittest.TestCase):
    def test_active_board(self):
        project = core.parse_project(HLDI.read_bytes())
        self.assertEqual(core.active_board(project), 0)
        self.assertEqual(core.active_board(reread(core.with_active_board(project, 2))), 2)

    def test_board_settings(self):
        project = core.parse_project(MOTOR.read_bytes())
        project.boards[0] = core.board_settings(project.boards[0], "Мотор", 50.5, 30.25, True)
        board = reread(project).boards[0]
        self.assertEqual(
            (board.name, board.width, board.height, board.multilayer), ("Мотор", 50.5, 30.25, True)
        )

    def test_copied_board_is_independent(self):
        original = core.parse_project(MOTOR.read_bytes()).boards[0]
        copy = core.copied_board(original, "Копия")
        copy.elements.pop()
        self.assertEqual(len(copy.elements), len(original.elements) - 1)
        self.assertEqual(copy.name, "Копия")

    def test_single_board_project(self):
        project = core.parse_project(HLDI.read_bytes())
        single = reread(core.single_board_project(project, 2))
        self.assertEqual([b.name for b in single.boards], [project.boards[2].name])
        self.assertEqual(len(single.boards[0].elements), len(project.boards[2].elements))

    def test_objects_outside_the_work_area(self):
        board = core.parse_project(MOTOR.read_bytes()).boards[0]
        self.assertEqual(core.outside_work_area(board), [])
        board.elements.append(core.new_pad(board, 1, board.width + 10, -5, 1.6, 0.8))
        board.elements.append(core.new_pad(board, 1, board.width - 1, -5, 1.6, 0.8))
        self.assertEqual(core.outside_work_area(board), [len(board.elements) - 2])


if __name__ == "__main__":
    unittest.main()
