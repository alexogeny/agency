import unittest
from unittest.mock import patch

from Tests.test_report_png_perf import PdfImage, decode, png


class ReportPngGrayTests(unittest.TestCase):
    def test_channel_work_scales_with_rows(self):
        class Counted(bytearray):
            tuple_extends = 0
            appends = 0

            def extend(self, data):
                if isinstance(data, tuple):
                    type(self).tuple_extends += 1
                return super().extend(data)

            def append(self, value):
                type(self).appends += 1
                return super().append(value)

        for colour, pixel in ((0, b'\x11'), (4, b'\x11\x80')):
            data = png(64, 64, colour, (b'\x00' + pixel * 64) * 64)
            with patch.dict(PdfImage.read_png.__globals__, bytearray=Counted):
                image = decode(data)
            self.assertEqual(image.data, b'\x11' * 12288)
            self.assertEqual(image.alpha, b'\x80' * 4096 if colour == 4 else b'')
        self.assertEqual((Counted.tuple_extends, Counted.appends), (0, 0))

    def test_all_filters_opaque_and_translucent(self):
        for colour, channels in ((0, 1), (4, 2)):
            for opaque in (False, True):
                row = bytes(
                    (i * 37 + 11) & 255
                    if channels == 1 or i % 2 == 0 or not opaque else 255
                    for i in range(7 * channels)
                )
                expected_rgb = b''.join((bytes([row[i]]) * 3 for i in range(0, len(row), channels))) * 3
                expected_alpha = b'' if channels == 1 or opaque else row[1::2] * 3
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
                            encoded.append(value - (0, left, above, (left + above) // 2, paeth)[filter_type] & 255)
                        previous = row
                    with self.subTest(colour=colour, opaque=opaque, filter=filter_type):
                        image = decode(png(7, 3, colour, encoded))
                        self.assertEqual((image.data, image.alpha), (expected_rgb, expected_alpha))

    def test_zero_and_truncated_rows(self):
        for colour, pixels, rgb, alpha in ((0, b'\x00\x11', b'\x11' * 3 + b'\x00' * 3, b''), (4, b'\x00\x11\x80"', b'\x11' * 3 + b'"' * 3, b'\x80\x00')):
            image = decode(png(2, 1, colour, pixels))
            self.assertEqual((image.data, image.alpha), (rgb, alpha))
        for colour in (0, 4):
            for width, height, pixels in ((0, 0, b''), (0, 2, b'\x00\x00'), (2, 0, b'')):
                image = decode(png(width, height, colour, pixels))
                self.assertEqual((image.data, image.alpha), (b'', b''))


if __name__ == "__main__":
    unittest.main()
