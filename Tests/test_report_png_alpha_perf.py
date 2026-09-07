import unittest
from unittest.mock import patch

from Tests.test_report_png_perf import PdfImage, decode, png


class ReportPngAlphaTests(unittest.TestCase):
    def test_opaque_alpha_does_not_iterate_python_values(self):
        class Counted(bytearray):
            iterations = 0

            def __iter__(self):
                for value in super().__iter__():
                    type(self).iterations += 1
                    yield value

        data = png(64, 64, 6, (b"\0" + b"\x11\x22\x33\xff" * 64) * 64)
        with patch.dict(PdfImage.read_png.__globals__, bytearray=Counted):
            image = decode(data)
        self.assertEqual(image.data, b"\x11\x22\x33" * 4096)
        self.assertEqual(image.alpha, b"")
        self.assertEqual(Counted.iterations, 0)

    def test_alpha_omission_and_retention_across_formats(self):
        cases = [
            (6, b"\x11\x22\x33\xff\x44\x55\x66\xff", b"", b"", b""),
            (6, b"\x11\x22\x33\x80\x44\x55\x66\xff", b"", b"", b"\x80\xff"),
            (6, b"\x11\x22\x33\xff\x44\x55\x66\0", b"", b"", b"\xff\0"),
            (4, b"\x11\xff\x22\xff", b"", b"", b""),
            (4, b"\x11\xff\x22\x80", b"", b"", b"\xff\x80"),
            (0, b"\x11\x22", b"", b"", b""),
            (3, b"\0\x01", b"\x11\x22\x33\x44\x55\x66", b"\xff\xff", b""),
            (3, b"\0\x01", b"\x11\x22\x33\x44\x55\x66", b"\xff\x80", b"\xff\x80"),
        ]
        for colour, row, palette, transparency, alpha in cases:
            with self.subTest(colour=colour, row=row, transparency=transparency):
                image = decode(png(2, 1, colour, b"\0" + row, palette, transparency))
                self.assertEqual(image.alpha, alpha)
                self.assertEqual(len(image.data), 6)

    def test_first_translucent_pixel_skips_full_count(self):
        class Counted(bytearray):
            counts = 0

            def count(self, value, *args):
                type(self).counts += 1
                return super().count(value, *args)

        data = png(2, 1, 6, b"\0\x11\x22\x33\x80\x44\x55\x66\xff")
        with patch.dict(PdfImage.read_png.__globals__, bytearray=Counted):
            image = decode(data)
        self.assertEqual(image.alpha, b"\x80\xff")
        self.assertEqual(Counted.counts, 0)

    def test_empty_alpha_skips_opacity_scan(self):
        class Counted(bytearray):
            counts = 0

            def count(self, value, *args):
                type(self).counts += 1
                return super().count(value, *args)

        for width, height, colour, pixels in ((0, 0, 6, b""), (0, 2, 6, b"\0\0"), (1, 1, 2, b"\0\x11\x22\x33")):
            with self.subTest(width=width, height=height, colour=colour):
                with patch.dict(PdfImage.read_png.__globals__, bytearray=Counted):
                    image = decode(png(width, height, colour, pixels))
                self.assertEqual(image.alpha, b"")
        self.assertEqual(Counted.counts, 0)


if __name__ == "__main__":
    unittest.main()
