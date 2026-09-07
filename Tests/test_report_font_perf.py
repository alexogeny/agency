import runpy
import struct
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TrueTypeFont = runpy.run_path(str(ROOT / 'Tools/report-build'))['TrueTypeFont']


class CountingMap(list):
    def __init__(self, values):
        super().__init__(values)
        self.probes = 0

    def __iter__(self):
        for value in super().__iter__():
            self.probes += 1
            yield value

    def __getitem__(self, index):
        self.probes += 1
        return super().__getitem__(index)


def font(format_number=12, a_glyph=5, question=True):
    groups = [(65, 66, a_glyph), (0x1F600, 0x1F600, 7)]
    if question:
        groups.insert(0, (63, 63, 3))
    if format_number == 4:
        groups = [(start, end, first - start, 0, 0, b'') for start, end, first in groups if start <= 0xFFFF]
    cmap = CountingMap(groups)
    head = bytearray(54)
    struct.pack_into('>H', head, 18, 1000)
    hhea = bytearray(36)
    struct.pack_into('>H', hhea, 34, 10)
    tables = {'head': head, 'hhea': hhea, 'maxp': struct.pack('>IH', 0, 10),
              'hmtx': b''.join(struct.pack('>HH', (i + 1) * 100, 0) for i in range(10))}
    path = mock.Mock()
    path.read_bytes.return_value = bytes(12)
    with mock.patch.object(TrueTypeFont, 'table', side_effect=tables.__getitem__), mock.patch.object(TrueTypeFont, 'read_cmap', return_value=(format_number, cmap)):
        return TrueTypeFont(path, 'Fixture')


class ReportFontTests(unittest.TestCase):
    def test_repeated_characters_reuse_cmap_lookups_including_zero(self):
        for format_number in (4, 12):
            for codepoint, expected in ((65, 5), (0x2603, 0), (0x1F600, 7 if format_number == 12 else 0)):
                with self.subTest(format=format_number, codepoint=codepoint):
                    value = font(format_number)
                    self.assertEqual(value.glyph(codepoint), expected)
                    probes = value.cmap.probes
                    for _ in range(20):
                        self.assertEqual(value.glyph(codepoint), expected)
                    self.assertEqual(value.cmap.probes, probes)

    def test_width_encoding_and_used_glyphs_preserve_fallback(self):
        for format_number, expected_width, expected_encoding, expected_used in (
            (12, 27, '000500030003000000070006', {5: 65, 3: 0x2603, 0: 0, 7: 0x1F600, 6: 66}),
            (4, 20, '000500030003000000030006', {5: 65, 3: 0x2603, 0: 0, 6: 66}),
        ):
            with self.subTest(format=format_number):
                value = font(format_number)
                text = 'A☃?\0😀B'
                for _ in range(2):
                    self.assertEqual(value.width(text, 10), expected_width)
                    self.assertEqual(value.encode(text), expected_encoding)
                    self.assertEqual(value.used, expected_used)
                self.assertEqual(value.width('', 10), 0)
                self.assertEqual(value.encode(''), '')

    def test_absent_question_mark_stays_zero(self):
        value = font(question=False)
        self.assertEqual(value.encode('☃?☃'), '000000000000')
        self.assertEqual(value.used, {0: 0x2603})
        probes = value.cmap.probes
        self.assertEqual(value.encode('☃?☃'), '000000000000')
        self.assertEqual(value.cmap.probes, probes)

    def test_fonts_do_not_share_mappings(self):
        first = font(a_glyph=5)
        second = font(a_glyph=8)
        self.assertEqual(first.glyph(65), 5)
        self.assertEqual(second.glyph(65), 8)
        self.assertEqual(first.glyph(65), 5)
        self.assertEqual((first.width('A', 10), second.width('A', 10)), (6, 9))

    def test_format_four_glyph_array_and_truncation(self):
        value = font(4)
        value.cmap = CountingMap([(65, 67, 1, 2, 0, b'\0\0\0\5\0\0')])
        for _ in range(2):
            self.assertEqual([value.glyph(point) for point in (65, 66, 67)], [6, 0, 0])


if __name__ == '__main__':
    unittest.main()
