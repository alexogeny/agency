import unittest
from unittest import mock

from Tests.test_report_png_perf import PdfImage, decode, png


class CountingBytearray(bytearray):
    slices = 0

    def __getitem__(self, index):
        if isinstance(index, slice):
            type(self).slices += 1
        return super().__getitem__(index)


class ReportPngRgbTests(unittest.TestCase):
    def test_rgb_rows_avoid_per_pixel_slices(self):
        pixels = bytes((17, 34, 51)) * 64
        data = png(64, 64, 2, (b'\0' + pixels) * 64)
        CountingBytearray.slices = 0
        with mock.patch.dict(PdfImage.read_png.__globals__, {'bytearray': CountingBytearray}):
            image = decode(data)
        self.assertEqual(image.data, pixels * 64)
        self.assertEqual(CountingBytearray.slices, 0)

    def test_rgb_payload_and_metadata_for_every_filter(self):
        previous = bytes((10, 20, 30, 40, 50, 60))
        expected = bytes((20, 30, 40, 60, 70, 80))
        residuals = {
            0: expected,
            1: bytes((20, 30, 40, 40, 40, 40)),
            2: bytes((10, 10, 10, 20, 20, 20)),
            3: bytes((15, 20, 25, 30, 30, 30)),
            4: bytes((10, 10, 10, 20, 20, 20)),
        }
        for filter_type, residual in residuals.items():
            with self.subTest(filter=filter_type):
                image = decode(png(2, 2, 2, b'\0' + previous + bytes((filter_type,)) + residual))
                self.assertEqual(image.data, previous + expected)
                self.assertEqual((image.width, image.height, image.bits, image.alpha, image.colour_space, image.filter), (2, 2, 8, b'', '/DeviceRGB', '/FlateDecode'))

    def test_zero_sized_and_truncated_rgb_rows(self):
        for width, height, pixels, expected in (
            (0, 2, b'\0\0', b''),
            (2, 0, b'', b''),
            (2, 1, b'\0', bytes(6)),
            (2, 1, b'\0\x11\x22\x33\x44', b'\x11\x22\x33\x44\0\0'),
        ):
            with self.subTest(width=width, height=height, pixels=pixels):
                image = decode(png(width, height, 2, pixels))
                self.assertEqual((image.data, image.alpha), (expected, b''))


if __name__ == '__main__':
    unittest.main()
