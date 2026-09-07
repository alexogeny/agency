import unittest
from unittest.mock import Mock

from Tests.test_report_font_perf import font


class ReportWidthCacheTests(unittest.TestCase):
    def test_repeated_text_reuses_unscaled_width_across_sizes(self):
        value = font()
        original = value.glyph
        value.glyph = Mock(side_effect=original)
        text = 'repeated text'
        total = sum(value.widths[original(ord(character))] for character in text)
        for size in (10, 20, 0, 12):
            self.assertEqual(value.width(text, size), total * size / value.units)
        self.assertEqual(value.glyph.call_count, len(text))

    def test_zero_width_is_cached(self):
        value = font()
        value.widths[0] = 0
        value.glyph = Mock(side_effect=value.glyph)
        self.assertEqual(value.width('\0', 10), 0)
        self.assertEqual(value.width('\0', 20), 0)
        self.assertEqual(value.glyph.call_count, 1)
        self.assertEqual(value.width('', 10), 0)

    def test_missing_glyph_width_preserves_encoding_fallback(self):
        value = font()
        text = chr(0x10FFFF)
        self.assertEqual(value.glyph(ord(text)), 0)
        self.assertEqual(value.width(text, 10), value.widths[0] * 10 / value.units)
        self.assertEqual(value.encode(text), f'{value.glyph(ord("?")):04X}')
        self.assertEqual(value.width(text, 20), value.widths[0] * 20 / value.units)

    def test_font_instances_keep_separate_widths(self):
        first, second = font(a_glyph=5), font(a_glyph=8)
        self.assertEqual(first.width('A', 10), 6)
        self.assertEqual(second.width('A', 10), 9)
        self.assertIsNot(first._width_cache, second._width_cache)

    def test_capacity_with_temporary_unique_strings(self):
        value = font()
        for index in range(1000):
            text = f'unique{index:08d}'
            expected = sum(value.widths[value.glyph(ord(character))] for character in text)
            self.assertEqual(value.width(text, 12), expected * 12 / value.units)
        self.assertEqual(len(value._width_cache), 256)
        self.assertIn('unique00000000', value._width_cache)
        self.assertNotIn('unique00000999', value._width_cache)
        self.assertEqual(value.width('unique00000000', 24), value._width_cache['unique00000000'] * 24 / value.units)
        self.assertEqual(len(value._width_cache), 256)

    def test_long_texts_do_not_consume_cache_capacity(self):
        value = font()
        for index in range(300):
            text = f'{index:04d}' + 'x' * 129
            expected = sum(value.widths[value.glyph(ord(character))] for character in text)
            self.assertEqual(value.width(text, 11), expected * 11 / value.units)
        self.assertEqual(value._width_cache, {})
        value.width('x' * 128, 10)
        value.width('x' * 129, 10)
        self.assertEqual(list(value._width_cache), ['x' * 128])
