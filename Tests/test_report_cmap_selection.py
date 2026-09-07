import itertools
from pathlib import Path
import runpy
import struct
import unittest


TrueTypeFont = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "Tools" / "report-build")
)["TrueTypeFont"]


def subtable(format_number, glyph):
    if format_number == 12:
        return struct.pack(">HHIIIIII", 12, 0, 28, 0, 1, 65, 65, glyph)
    if format_number == 4:
        return (
            struct.pack(">7H", 4, 32, 0, 4, 4, 1, 0)
            + struct.pack(">5H", 65, 0xFFFF, 0, 65, 0xFFFF)
            + struct.pack(">hhHH", glyph - 65, 1, 0, 0)
        )
    return struct.pack(">H", format_number)


def font(records):
    offset = 4 + len(records) * 8
    headers = []
    bodies = []
    for platform, encoding, format_number, glyph in records:
        body = subtable(format_number, glyph)
        headers.append(struct.pack(">HHI", platform, encoding, offset))
        bodies.append(body)
        offset += len(body)
    data = struct.pack(">HH", 0, len(records)) + b"".join(headers + bodies)
    value = TrueTypeFont.__new__(TrueTypeFont)
    value.name = "Fixture"
    value.data = data
    value.tables = {"cmap": (0, len(data))}
    return value


class ReportCmapSelectionTests(unittest.TestCase):
    def assert_selected(self, records, format_number, glyph):
        value = font(records)
        value.cmap_format, value.cmap = value.read_cmap()
        self.assertEqual(value.cmap_format, format_number)
        self.assertEqual(value._lookup_glyph(65), glyph)

    def test_priority_levels_ignore_record_order(self):
        priority_order = [
            (0, 0, 4, 11),
            (3, 1, 4, 22),
            (0, 4, 12, 33),
            (3, 10, 12, 44),
        ]
        for count in range(1, 5):
            selected = priority_order[count - 1]
            for records in itertools.permutations(priority_order[:count]):
                with self.subTest(records=records):
                    self.assert_selected(records, selected[2], selected[3])

    def test_equal_scores_preserve_first_record(self):
        pairs = [
            ((0, 0, 4, 17), (1, 0, 4, 29)),
            ((3, 1, 4, 17), (3, 10, 4, 29)),
            ((0, 4, 12, 17), (3, 1, 12, 29)),
            ((3, 10, 12, 17), (3, 10, 12, 29)),
        ]
        for pair in pairs:
            for records in (pair, pair[::-1]):
                with self.subTest(records=records):
                    self.assert_selected(records, records[0][2], records[0][3])

    def test_unsupported_formats_are_ignored_or_rejected(self):
        unsupported = [(3, 10, format_number, 0) for format_number in (0, 6, 10, 14)]
        supported = (0, 0, 4, 17)
        for records in ([*unsupported, supported], [supported, *unsupported]):
            with self.subTest(records=records):
                self.assert_selected(records, 4, 17)
        for records in ([], unsupported):
            with self.subTest(records=records):
                with self.assertRaisesRegex(ValueError, "font has no Unicode cmap: Fixture"):
                    font(records).read_cmap()


if __name__ == "__main__":
    unittest.main()
