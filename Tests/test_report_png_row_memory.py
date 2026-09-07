import unittest
import weakref
from unittest import mock

from Tests.test_report_png_perf import PdfImage, decode, png


class ReportPngRowMemoryTests(unittest.TestCase):
    def test_reconstructed_rows_are_not_retained_for_the_whole_image(self):
        stride = 256 * 3
        references = []
        peak = 0
        class TrackedRow(bytearray):
            def __init__(self, *args):
                nonlocal peak
                super().__init__(*args)
                if args == (stride,):
                    references.append(weakref.ref(self))
                    peak = max(peak, sum(reference() is not None for reference in references))
        data = png(256, 256, 2, (b'\0' + bytes((17, 34, 51)) * 256) * 256)
        with mock.patch.dict(PdfImage.read_png.__globals__, {'bytearray': TrackedRow}):
            image = decode(data)
        self.assertEqual(image.data, bytes((17, 34, 51)) * (256 * 256))
        self.assertLessEqual(peak, 2)
        self.assertTrue(references)
        self.assertTrue(all(reference() is None for reference in references))

    def test_mixed_filters_preserve_all_supported_colour_payloads(self):
        for colour_type, row, rgb, alpha, palette, transparency in (
            (0, bytes((17, 34)), bytes((17, 17, 17, 34, 34, 34)), b'', b'', b''),
            (2, bytes((17, 34, 51, 68, 85, 102)), bytes((17, 34, 51, 68, 85, 102)), b'', b'', b''),
            (3, bytes((0, 1)), bytes((17, 34, 51, 68, 85, 102)), bytes((128, 255)), bytes((17, 34, 51, 68, 85, 102)), bytes((128,))),
            (4, bytes((17, 128, 34, 255)), bytes((17, 17, 17, 34, 34, 34)), bytes((128, 255)), b'', b''),
            (6, bytes((17, 34, 51, 128, 68, 85, 102, 255)), bytes((17, 34, 51, 68, 85, 102)), bytes((128, 255)), b'', b''),
        ):
            channels = len(row) // 2
            encoded = bytearray()
            previous = bytes(len(row))
            for filter_type in (0, 1, 2, 3, 4):
                encoded.append(filter_type)
                for column, value in enumerate(row):
                    left = row[column - channels] if column >= channels else 0
                    above = previous[column]
                    upper_left = previous[column - channels] if column >= channels else 0
                    prediction = left + above - upper_left
                    distances = (abs(prediction - left), abs(prediction - above), abs(prediction - upper_left))
                    paeth = (left, above, upper_left)[distances.index(min(distances))]
                    predictor = (0, left, above, (left + above) // 2, paeth)[filter_type]
                    encoded.append((value - predictor) & 255)
                previous = row
            with self.subTest(colour_type=colour_type):
                image = decode(png(2, 5, colour_type, encoded, palette, transparency))
                self.assertEqual((image.data, image.alpha), (rgb * 5, alpha * 5))
                self.assertEqual((image.width, image.height, image.bits, image.colour_space, image.filter), (2, 5, 8, '/DeviceRGB', '/FlateDecode'))


if __name__ == '__main__':
    unittest.main()
