import unittest
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from check_float_placement import (
    AuditError, Box, Position, caption_at, figure_body, figure_priority_warnings, first_page_body_top, group_capacity,
    nearest_column,
    placement_flags, reference_order_errors, table_body, top_group,
    union,
)


PAGE_WIDTH = 595.276
PAGE_HEIGHT = 841.89
MAX_TOP_FRACTION = 0.67


class PlacementTests(unittest.TestCase):
    def test_first_reference_must_precede_table_in_reading_order(self):
        caption = Box(70, 58, 230, 69)
        body = Box(43, 74, 289, 130)
        position = Position(3, 0, 58)
        good, distance = placement_flags(position, caption, body, Position(2, 1, 690),
                                         PAGE_WIDTH, PAGE_HEIGHT, True)
        bad, _ = placement_flags(position, caption, body, Position(3, 1, 60),
                                 PAGE_WIDTH, PAGE_HEIGHT, True)
        self.assertTrue(all(good.values()))
        self.assertEqual(distance, 1)
        self.assertFalse(bad["R2 after reference"])

    def test_middle_of_column_and_overwide_body_are_detected(self):
        caption = Box(70, 358, 230, 369)
        rules = [Box(43, y, 301, y) for y in (374, 391, 441)]
        words = [Box(45, y, 80, y + 10) for y in (377, 400)]
        body = table_body(caption, rules, words, 0, PAGE_WIDTH, float("inf"))
        pos = Position(4, 0, 358)
        group = top_group([(pos, Box(caption.left, caption.top, body.right, body.bottom))],
                          words, pos.column, PAGE_WIDTH)
        flags, _ = placement_flags(pos, caption, body, Position(3, 1, 555),
                                   PAGE_WIDTH, PAGE_HEIGHT, pos in group)
        self.assertFalse(flags["R1 top group"])
        self.assertFalse(flags["R3 within column"])
        self.assertTrue(flags["R4 caption/body"])

    def test_missing_reference_fails(self):
        caption = Box(70, 58, 230, 69)
        flags, distance = placement_flags(Position(2, 0, 58), caption,
                                          Box(43, 74, 289, 130), None,
                                          PAGE_WIDTH, PAGE_HEIGHT, True)
        self.assertFalse(flags["R2 after reference"])
        self.assertIsNone(distance)

    def test_body_text_is_not_identified_as_caption_away_from_anchor(self):
        page = ET.fromstring("""
          <page><block xMin="60" yMin="120" xMax="210" yMax="130">
            <line xMin="60" yMin="120" xMax="210" yMax="130">
              <word>Table</word><word>6</word><word>shows</word>
            </line>
          </block></page>""")
        with self.assertRaisesRegex(AuditError, "found 0"):
            caption_at(page, "6", 100, 57)

    def test_missing_or_detached_body_fails(self):
        caption = Box(70, 58, 230, 69)
        for rules in ([], [Box(43, y, 289, y) for y in (100, 120, 160)]):
            with self.subTest(rules=rules):
                with self.assertRaisesRegex(AuditError, "R4"):
                    table_body(caption, rules, [], 0, PAGE_WIDTH, float("inf"))

    def test_single_table_at_top(self):
        pos = Position(4, 0, 58)
        extent = Box(44, 58, 289, 185)
        self.assertEqual(top_group([(pos, extent)], [], 0, PAGE_WIDTH), {pos: extent})

    def test_two_tables_share_one_top_group(self):
        first = Position(4, 0, 58)
        second = Position(4, 0, 204)
        entries = [(first, Box(44, 58, 289, 185)), (second, Box(44, 204, 289, 426))]
        other_column_text = Box(315, 187, 365, 197)
        group = top_group(entries, [other_column_text], 0, PAGE_WIDTH)
        self.assertEqual(list(group), [first, second])
        self.assertTrue(group_capacity(entries[1][1], PAGE_HEIGHT, MAX_TOP_FRACTION)[2])

    def test_body_text_between_tables_breaks_group(self):
        first, second = Position(4, 0, 58), Position(4, 0, 204)
        entries = [(first, Box(44, 58, 289, 185)), (second, Box(44, 204, 289, 426))]
        intervening_text = Box(70, 190, 100, 200)
        group = top_group(entries, [intervening_text], 0, PAGE_WIDTH)
        self.assertEqual(list(group), [first])

    def test_large_gap_does_not_count_as_group(self):
        first, second = Position(4, 0, 58), Position(4, 0, 244)
        entries = [(first, Box(44, 58, 289, 185)), (second, Box(44, 244, 289, 426))]
        self.assertEqual(list(top_group(entries, [], 0, PAGE_WIDTH)), [first])

    def test_reference_order_within_a_group(self):
        first, second = Position(4, 0, 58), Position(4, 0, 204)
        ref3, ref4 = Position(3, 1, 550), Position(3, 1, 610)
        self.assertEqual(reference_order_errors([first, second], {first: ref4, second: ref3}),
                         {second})
        self.assertFalse(reference_order_errors([first, second], {first: ref3, second: ref4}))

    def test_table_crosses_page_bottom(self):
        flags, _ = placement_flags(Position(4, 0, 58), Box(70, 58, 230, 69),
                                   Box(43, 74, 289, 850), Position(3, 1, 690),
                                   PAGE_WIDTH, PAGE_HEIGHT, True)
        self.assertFalse(flags["R3 within body height"])

    def test_table_rolls_to_next_column_when_group_is_full(self):
        first = Position(4, 0, 58)
        ref = Position(3, 1, 670)
        extent = Box(310, 58, 550, 245)
        self.assertTrue(nearest_column(2, ref, extent, {(4, 0): {first: Box(43, 58, 289, 480)}},
                                       PAGE_HEIGHT, MAX_TOP_FRACTION))
        self.assertFalse(nearest_column(2, ref, extent, {(4, 0): {first: Box(43, 58, 289, 185)}},
                                        PAGE_HEIGHT, MAX_TOP_FRACTION))


class FigurePlacementTests(unittest.TestCase):
    position = Position(4, 0, 57)
    caption = Box(70, 160, 230, 170)
    image = Box(55, 57, 270, 152)
    reference = Position(3, 1, 670)

    def flags(self, image, reference):
        flags, _ = placement_flags(self.position, self.caption, image, reference,
                                   PAGE_WIDTH, PAGE_HEIGHT, True, kind="figure")
        return flags

    def test_figure_alone_at_top(self):
        body = figure_body(self.caption, [self.image], 0, PAGE_WIDTH)
        extent = union((self.caption, body))
        self.assertIn(self.position, top_group([(self.position, extent)], [], 0, PAGE_WIDTH))
        self.assertTrue(all(self.flags(body, self.reference).values()))

    def test_figure_and_table_form_top_group(self):
        later = Position(4, 0, 188)
        entries = [(self.position, union((self.caption, self.image))),
                   (later, Box(44, 188, 288, 290))]
        self.assertEqual(list(top_group(entries, [], 0, PAGE_WIDTH)), [self.position, later])

    def test_figure_priority_in_mixed_group(self):
        later = Position(4, 0, 188)
        group = [self.position, later]
        self.assertEqual(figure_priority_warnings(group, {self.position: "table", later: "figure"}), {later})
        self.assertFalse(figure_priority_warnings(group, {self.position: "figure", later: "table"}))

    def test_reference_must_precede_image_even_if_it_precedes_caption(self):
        self.assertFalse(self.flags(self.image, Position(4, 0, 120))["R2 after reference"])

    def test_text_between_figure_and_table_breaks_group(self):
        later = Position(4, 0, 188)
        entries = [(self.position, union((self.caption, self.image))),
                   (later, Box(44, 188, 288, 290))]
        words = [Box(70, 172, 150, 183)]
        self.assertEqual(list(top_group(entries, words, 0, PAGE_WIDTH)), [self.position])

    def test_figure_outside_column_width(self):
        self.assertFalse(self.flags(Box(38, 57, 294, 152), self.reference)["R3 within column"])

    def test_figure_outside_page_bottom(self):
        self.assertFalse(self.flags(Box(55, 57, 270, 845), self.reference)["R3 within body height"])

    def test_detached_figure_caption(self):
        with self.assertRaises(AuditError):
            figure_body(self.caption, [Box(55, 57, 270, 116)], 0, PAGE_WIDTH)

    def test_unidentified_or_ambiguous_body(self):
        for images in ([], [self.image, Box(60, 70, 265, 150)]):
            with self.subTest(images=images), self.assertRaises(AuditError):
                figure_body(self.caption, images, 0, PAGE_WIDTH)

    def test_large_figure_can_roll_to_later_column(self):
        occupied = {(4, 0): {self.position: Box(43, 57, 289, 460)}}
        extent = Box(311, 58, 547, 281)
        self.assertTrue(nearest_column(2, self.reference, extent, occupied, PAGE_HEIGHT, MAX_TOP_FRACTION))

    def test_body_top_after_full_width_abstract(self):
        start = SimpleNamespace(top=PAGE_HEIGHT - 325.3)
        reader = SimpleNamespace(named_destinations={"Doc-Start": start, "section.1": start},
                                 pages=[SimpleNamespace(mediabox=SimpleNamespace(height=PAGE_HEIGHT))],
                                 get_destination_page_number=lambda destination: 0)
        body_top = first_page_body_top(reader)
        position = Position(1, 1, body_top)
        extent = Box(311, body_top, 547, 475)
        self.assertAlmostEqual(body_top, 325.3)
        self.assertIn(position, top_group([(position, extent)], [], 1, PAGE_WIDTH, body_top))
        self.assertNotIn(position, top_group([(position, extent)], [], 1, PAGE_WIDTH))

    def test_previous_group_includes_latex_spacing_when_estimating_room(self):
        first = Position(4, 0, 58)
        ref = Position(3, 1, 670)
        occupied = {(4, 0): {first: Box(43, 58, 289, 420)}}
        extent = Box(310, 58, 550, 168)
        self.assertTrue(nearest_column(2, ref, extent, occupied, PAGE_HEIGHT, MAX_TOP_FRACTION))


if __name__ == "__main__":
    unittest.main()
