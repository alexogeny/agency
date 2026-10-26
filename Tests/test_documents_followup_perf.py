import runpy
import struct
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch


MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'Tools/report-build'))
PdfImage = MODULE['PdfImage']


def png(width, height, pixels, colour_type=2):
    def chunk(kind, value):
        return (struct.pack('>I', len(value)) + kind + value
                + struct.pack('>I', zlib.crc32(kind + value)))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, colour_type, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


def image(data):
    result = PdfImage.__new__(PdfImage)
    result.path = Path('fixture.png')
    result.read_png(data)
    return result


class DocumentFollowupPerformanceTests(unittest.TestCase):
    def test_complete_unfiltered_rgb_rows_do_not_allocate_reconstruction_buffers(self):
        for width, height in ((16, 32), (71, 400), (23000, 2)):
            with self.subTest(width=width, height=height):
                initialized = []

                def allocate(value=b''):
                    initialized.append(value if isinstance(value, int) else len(value))
                    return bytearray(value)

                row = bytes((17, 34, 51)) * width
                with patch.dict(PdfImage.read_png.__globals__, bytearray=allocate):
                    result = image(png(width, height, (b'\0' + row) * height))
                self.assertEqual(result.data, row * height)
                # The initial previous row is sufficient for complete filter-0 rows.
                self.assertLessEqual(sum(initialized), width * 3)

    def test_unfiltered_decoded_rows_are_views_with_stable_previous_rows(self):
        width, height = 37, 800
        row = b'\x11\x22\x33' * width
        rows = []
        original = PdfImage.read_png_rows

        def capture(self, values, *args):
            def observed():
                for value in values:
                    rows.append(value)
                    yield value
            return original(self, observed(), *args)

        with patch.object(PdfImage, 'read_png_rows', capture):
            result = image(png(width, height, (b'\0' + row) * height))
        self.assertEqual(result.data, row * height)
        self.assertEqual(len(rows), height)
        self.assertTrue(all(isinstance(value, memoryview) for value in rows))
        self.assertTrue(all(bytes(value) == row for value in rows))

    def test_contiguous_encoded_rows_do_not_copy_into_joined_bytes(self):
        for colour_type, channels in ((2, 3), (6, 4)):
            with self.subTest(colour_type=colour_type):
                copied = []
                width, height = 64, 48
                stride = width * channels

                def view(value):
                    if isinstance(value, bytes) and len(value) == stride + 1:
                        copied.append(len(value))
                    return memoryview(value)

                pixels = (b'\0' + bytes(range(channels)) * width) * height
                with patch.dict(PdfImage.read_png.__globals__, memoryview=view):
                    result = image(png(width, height, pixels, colour_type))
                self.assertEqual(len(result.data), width * height * 3)
                self.assertEqual(sum(copied), 0)

    def test_truncated_final_unfiltered_row_keeps_zero_padding(self):
        result = image(png(2, 2, b'\0abcdef\0g'))
        self.assertEqual(result.data, b'abcdefg\0\0\0\0\0')


if __name__ == '__main__':
    unittest.main()
