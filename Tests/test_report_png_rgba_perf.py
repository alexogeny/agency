import unittest
from unittest import mock

from Tests.test_report_png_perf import PdfImage, decode, png


class ReportPngRgbaTests(unittest.TestCase):
    def test_rgba_slices_scale_with_rows(self):
        class Counted(bytearray):
            slices = 0
            def __getitem__(self, key):
                if isinstance(key, slice):
                    type(self).slices += 1
                return super().__getitem__(key)
        data = png(64, 64, 6, (b'\0' + bytes((17, 34, 51, 128)) * 64) * 64)
        with mock.patch.dict(PdfImage.read_png.__globals__, {'bytearray': Counted}):
            image = decode(data)
        self.assertEqual(image.data, bytes((17, 34, 51)) * 4096)
        self.assertEqual(image.alpha, bytes((128,)) * 4096)
        self.assertEqual(Counted.slices, 4 * 64)

    def test_payloads_and_metadata_across_filters_and_alpha(self):
        for colour_type, channels in ((2, 3), (6, 4)):
            for opaque in (False, True):
                row = bytes((i * 37 + 11) & 255 if i % channels != 3 or not opaque else 255 for i in range(7 * channels))
                expected_rgb = b''.join(row[i:i + 3] for i in range(0, len(row), channels)) * 3
                expected_alpha = b'' if channels == 3 or opaque else row[3::4] * 3
                for filter_type in range(5):
                    encoded = bytearray()
                    previous = bytes(len(row))
                    for _ in range(3):
                        encoded.append(filter_type)
                        for col, value in enumerate(row):
                            left = row[col - channels] if col >= channels else 0
                            above = previous[col]
                            upper_left = previous[col - channels] if col >= channels else 0
                            prediction = left + above - upper_left
                            distances = (abs(prediction - left), abs(prediction - above), abs(prediction - upper_left))
                            paeth = (left, above, upper_left)[distances.index(min(distances))]
                            encoded.append((value - (0, left, above, (left + above) // 2, paeth)[filter_type]) & 255)
                        previous = row
                    with self.subTest(colour=colour_type, opaque=opaque, filter=filter_type):
                        image = decode(png(7, 3, colour_type, encoded))
                        self.assertEqual((image.data, image.alpha), (expected_rgb, expected_alpha))
                        self.assertEqual((image.width, image.height, image.bits, image.colour_space, image.filter), (7, 3, 8, '/DeviceRGB', '/FlateDecode'))

    def test_empty_and_truncated_rows_keep_zero_padding(self):
        for width, height, pixels, rgb, alpha in (
            (0, 0, b'', b'', b''),
            (0, 2, b'\0\0', b'', b''),
            (1, 1, b'\0', bytes(3), b'\0'),
            (2, 1, b'\0\x11\x22\x33\x80\x44', b'\x11\x22\x33\x44\0\0', b'\x80\0'),
            (1, 1, b'\0\x11\x22\x33\xff', b'\x11\x22\x33', b''),
        ):
            with self.subTest(width=width, height=height, pixels=pixels):
                image = decode(png(width, height, 6, pixels))
                self.assertEqual((image.data, image.alpha), (rgb, alpha))


if __name__ == '__main__':
    unittest.main()
