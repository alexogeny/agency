import itertools
import unittest
from unittest import mock

from Tests.test_report_png_perf import PdfImage, decode, png


class ReportPngPaethTests(unittest.TestCase):
    def test_paeth_does_not_call_min_per_byte(self):
        row = bytes((17, 34, 51)) + bytes(3 * 31)
        pixels = b'\4' + row + (b'\4' + bytes(3 * 32)) * 31
        minimum = mock.Mock(wraps=min)
        with mock.patch.dict(PdfImage.read_png.__globals__, {'min': minimum}):
            image = decode(png(32, 32, 2, pixels))
        self.assertEqual(image.data, bytes((17, 34, 51)) * 1024)
        self.assertEqual(minimum.call_count, 0)

    def test_paeth_diverse_values_and_ties_preserve_first_nearest_predictor(self):
        winners = set()
        ties = set()
        values = (0, 1, 2, 63, 127, 128, 254, 255)
        for left, above, upper_left in itertools.product(values, repeat=3):
            prediction = left + above - upper_left
            distances = (abs(prediction - left), abs(prediction - above), abs(prediction - upper_left))
            nearest = distances.index(min(distances))
            winners.add(nearest)
            tied = tuple(i for i, distance in enumerate(distances) if distance == min(distances))
            if len(tied) > 1:
                ties.add(tied)
            expected = (left, above, upper_left)[nearest]
            pixels = bytes((0, upper_left, above, 4, (left - upper_left) & 255, 0))
            image = decode(png(2, 2, 0, pixels))
            with self.subTest(left=left, above=above, upper_left=upper_left):
                self.assertEqual(image.data, bytes(value for value in (upper_left, above, left, expected) for _ in range(3)))
        self.assertEqual(winners, {0, 1, 2})
        self.assertIn((0, 2), ties)
        self.assertIn((1, 2), ties)
        self.assertIn((0, 1, 2), ties)


if __name__ == '__main__':
    unittest.main()
