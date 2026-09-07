import runpy
import unittest
from pathlib import Path

from Tests.test_report_font_perf import CountingMap, font


ROOT = Path(__file__).resolve().parents[1]
Renderer = runpy.run_path(str(ROOT / 'Tools/report-build'))['NativePdfRenderer']


def renderer(shared=False, empty=False):
    result = Renderer.__new__(Renderer)
    result.fonts = {style: font() for style in ('regular', 'bold', 'italic', 'bolditalic')}
    for value in result.fonts.values():
        value.cmap = CountingMap([(63, 63, 3), (65, 65, 5), (66, 66, 5), (0x1F600, 0x1F600, 7)])
    if shared:
        result.fonts['italic'] = result.fonts['regular']
    texts = [('regular', 'BA☃?BA\0😀' * 40), ('bold', 'AB?' * 30), ('italic', '?☃BA' * 30), ('bolditalic', '')]
    result.pages = [
        {'commands': [(style, 11, 20, 700 - i * 20, '' if empty else text, (0, 0, 0)) for i, (style, text) in enumerate(texts)],
         'numbered': numbered, 'images': [], 'lines': [], 'links': []}
        for numbered in (False, True, True)
    ]
    result.images = {}
    result.destinations = {}
    result.base_size = 11
    result.margin_bottom = 40
    return result


def texts_in_order(value):
    displayed = 0
    for page in value.pages:
        for style, _, _, _, text, _ in page['commands']:
            yield value.fonts[style], text
        if page['numbered']:
            displayed += 1
            yield value.fonts['regular'], str(displayed)


def reference_pdf(value):
    for selected, text in texts_in_order(value):
        selected.encode(text)
    return value.pdf()


class ReportPdfGlyphCollectionTests(unittest.TestCase):
    def test_first_pass_encodes_only_distinct_characters_per_font(self):
        value = renderer(shared=True)
        distinct = {}
        logical = 0
        for selected, text in texts_in_order(value):
            logical += len(text)
            distinct.setdefault(selected, set()).update(text)
        encoded_characters = 0
        for selected in set(value.fonts.values()):
            original = selected.encode
            def counted(text, original=original):
                nonlocal encoded_characters
                encoded_characters += len(text)
                return original(text)
            selected.encode = counted
        value.pdf()
        self.assertEqual(encoded_characters, logical + sum(map(len, distinct.values())))

    def test_exact_pdf_and_first_codepoint_mapping_match_original_collection(self):
        for shared in (False, True):
            with self.subTest(shared=shared):
                expected = renderer(shared=shared)
                expected_pdf = reference_pdf(expected)
                actual = renderer(shared=shared)
                self.assertEqual(actual.pdf(), expected_pdf)
                self.assertEqual({style: value.used for style, value in actual.fonts.items()}, {style: value.used for style, value in expected.fonts.items()})
                self.assertEqual(actual.fonts['regular'].used, {5: 66, 3: 0x2603, 0: 0, 7: 0x1F600})
                self.assertEqual(actual.fonts['bold'].used, {5: 65, 3: 63})
                self.assertEqual(actual.pdf(), expected_pdf)

    def test_empty_text_and_page_numbers_preserve_pdf_bytes(self):
        expected = renderer(empty=True)
        actual = renderer(empty=True)
        self.assertEqual(actual.pdf(), reference_pdf(expected))
        self.assertEqual(actual.fonts['regular'].used, {3: ord('1')})
        self.assertEqual(actual.fonts['bold'].used, {})


if __name__ == '__main__':
    unittest.main()
