"""Units, groups, clipboard, layers, alignment and track nodes."""

import unittest
from pathlib import Path

import core
from tests.samples import require_samples

require_samples()

ROOT = Path(__file__).resolve().parent.parent
MOTOR = ROOT / "Samples" / "motor ir2101.lay6"
HLDI = ROOT / "Samples" / "HLDI_ALL_PCB.lay6"


def board(path=MOTOR, index=0):
    return core.parse_project(path.read_bytes()).boards[index]


def loose(elements):
    """Objects outside any group or component."""
    return [i for i, o in enumerate(elements) if not core.group_ids(o) and not core.component_id(o)]


def present(value):
    assert value is not None
    return value


def first(elements, test):
    return next(i for i, obj in enumerate(elements) if test(obj))


class Units(unittest.TestCase):
    def test_click_selects_the_outermost_group(self):
        elements = board(HLDI).elements
        nested = first(elements, lambda obj: core.group_ids(obj) == [148, 214])
        unit = core.unit_of(elements, nested)
        self.assertGreater(len(unit), 1)
        for i in unit:
            obj = elements[i]
            self.assertTrue(core.outer_group(obj) == 214 or core.component_id(obj))

    def test_click_selects_the_whole_component(self):
        elements = board().elements
        unit = core.unit_of(elements, 0)
        self.assertEqual(unit, [i for i, o in enumerate(elements) if core.component_id(o) == 1])

    def test_units_split_a_selection(self):
        elements = board().elements
        loose = [
            i for i, o in enumerate(elements) if not core.group_ids(o) and not core.component_id(o)
        ]
        parts = core.units(elements, [0, *loose[:3]])
        self.assertEqual(len(parts), 4)


class Groups(unittest.TestCase):
    def test_group_and_ungroup(self):
        elements = list(board().elements)
        loose = [
            i for i, o in enumerate(elements) if not core.group_ids(o) and not core.component_id(o)
        ]
        chosen = loose[:3]
        gid = core.next_group_id(elements)
        for i, obj in core.grouped(elements, chosen).items():
            elements[i] = obj
        self.assertEqual({core.outer_group(elements[i]) for i in chosen}, {gid})
        self.assertEqual(core.unit_of(elements, chosen[0]), chosen)
        for i, obj in core.ungrouped(elements, chosen).items():
            elements[i] = obj
        self.assertEqual([elements[i].groups for i in chosen], [bytes(4)] * 3)

    def test_ungroup_keeps_inner_groups(self):
        elements = board(HLDI).elements
        nested = first(elements, lambda obj: core.group_ids(obj) == [148, 214])
        changed = core.ungrouped(elements, core.unit_of(elements, nested))
        self.assertEqual(core.group_ids(changed[nested]), [148])


class Clipboard(unittest.TestCase):
    def test_bytes_round_trip(self):
        elements = board().elements[:40]
        again = core.objects_from_bytes(core.objects_to_bytes(elements))
        self.assertEqual(
            [(o.kind, o.record, o.points, o.groups) for o in again],
            [(o.kind, o.record, o.points, o.groups) for o in elements],
        )

    def test_copies_get_new_groups_and_components(self):
        elements = board().elements
        unit = core.unit_of(elements, 0)
        copies = core.fresh_copies([elements[i] for i in unit], elements, 5, -1)
        self.assertEqual({core.component_id(o) for o in copies}, {2})
        self.assertAlmostEqual(copies[0].points[0][0] - elements[unit[0]].points[0][0], 5)
        existing = {g for o in elements for g in core.group_ids(o)}
        self.assertFalse({g for o in copies for g in core.group_ids(o)} & existing)

    def test_rejects_foreign_clipboard_data(self):
        with self.assertRaises(core.LayoutError):
            core.objects_from_bytes(b"hello world")


class LayersAndSides(unittest.TestCase):
    def test_pads_only_move_between_copper_sides(self):
        elements = board().elements
        pad = elements[first(elements, lambda o: o.kind == core.THT)]
        self.assertEqual(core.on_layer(pad, 2).layer, pad.layer)
        self.assertEqual(core.on_layer(pad, 3).layer, 3)

    def test_other_side_twice_restores(self):
        elements = board().elements
        unit = [elements[i] for i in core.unit_of(elements, 0)]
        flipped = core.to_other_side(unit)
        self.assertEqual([o.layer for o in flipped], [{1: 3, 2: 4}.get(o.layer) for o in unit])
        back = core.to_other_side(flipped)
        self.assertEqual([o.layer for o in back], [o.layer for o in unit])
        for old, new in zip(unit, back, strict=True):
            for (x0, y0), (x1, y1) in zip(old.points, new.points, strict=True):
                self.assertAlmostEqual(x0, x1, places=6)
                self.assertAlmostEqual(y0, y1, places=6)


class Alignment(unittest.TestCase):
    def test_snap_unit_to_grid(self):
        elements = list(board().elements)
        pad = core.new_pad(board(), 1, 10.37, -5.21, 1.6, 0.8)
        elements.append(pad)
        changed = core.snapped_to_grid(elements, [len(elements) - 1], 0.5)
        moved = changed[len(elements) - 1]
        self.assertEqual((moved.x, moved.y), (10.5, -5.0))

    def test_align_left_edges(self):
        b = board()
        pads = [core.new_pad(b, 1, x, -5, 1.6, 0.8) for x in (3.0, 7.0, 11.0)]
        elements = [*b.elements, *pads]
        indices = range(len(elements) - 3, len(elements))
        changed = core.aligned(elements, indices, "left")
        lefts = {round(core.bounds([obj])[0], 6) for obj in changed.values()}
        self.assertEqual(len(lefts), 1)
        self.assertEqual(core.aligned(elements, [len(elements) - 1], "left"), {})


class TrackNodes(unittest.TestCase):
    def setUp(self):
        self.track = core.new_track(board(), 1, [(0, 0), (5, 0), (5, 5), (10, 5)], 0.4)

    def test_remove_and_insert_node(self):
        self.assertEqual(
            present(core.without_node(self.track, 1)).points, [(0, 0), (5, 5), (10, 5)]
        )
        short = core.new_track(board(), 1, [(0, 0), (1, 0)], 0.4)
        self.assertIsNone(core.without_node(short, 0))
        added = core.with_node(self.track, (5, 2))
        self.assertEqual(added.points, [(0, 0), (5, 0), (5, 2), (5, 5), (10, 5)])

    def test_split_and_join(self):
        a, b = present(core.split_track(self.track, 2))
        self.assertEqual(a.points, [(0, 0), (5, 0), (5, 5)])
        self.assertEqual(b.points, [(5, 5), (10, 5)])
        self.assertIsNone(core.split_track(self.track, 0))
        self.assertEqual(present(core.joined_tracks(a, b)).points, self.track.points)
        self.assertEqual(present(core.joined_tracks(b, a)).points, self.track.points[::-1])
        other = core.new_track(board(), 3, [(10, 5), (20, 5)], 0.4)
        self.assertIsNone(core.joined_tracks(b, other))


if __name__ == "__main__":
    unittest.main()
