import runpy
import struct
import unittest
import zlib
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PdfImage = runpy.run_path(str(ROOT / "Tools/report-build"))["PdfImage"]


def png(width, height, colour_type, pixels, palette=b"", transparency=b""):
    def chunk(kind, value):
        return (
            struct.pack(">I", len(value))
            + kind
            + value
            + struct.pack(">I", zlib.crc32(kind + value))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0))
        + chunk(b"PLTE", palette)
        + chunk(b"tRNS", transparency)
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def decode(data):
    image = PdfImage.__new__(PdfImage)
    image.path = Path("fixture.png")
    image.read_png(data)
    return image


class ReportPngTests(unittest.TestCase):
    def test_unfiltered_rows_do_not_enumerate_individual_bytes(self):
        data = png(64, 64, 2, (b"\0" + b"\x11\x22\x33" * 64) * 64)
        with mock.patch.dict(PdfImage.read_png.__globals__, {"enumerate": mock.Mock(wraps=enumerate)}) as namespace:
            image = decode(data)
            self.assertEqual(image.data, b"\x11\x22\x33" * 4096)
            namespace["enumerate"].assert_not_called()

    def test_supported_colour_types_and_alpha(self):
        cases = [
            (0, b"\x11\x22", b"", b"", b"\x11\x11\x11\x22\x22\x22", b""),
            (2, b"\x11\x22\x33\x44\x55\x66", b"", b"", b"\x11\x22\x33\x44\x55\x66", b""),
            (3, b"\x01\x00", b"\x11\x22\x33\x44\x55\x66", b"\x80", b"\x44\x55\x66\x11\x22\x33", b"\xff\x80"),
            (4, b"\x11\x80\x22\xff", b"", b"", b"\x11\x11\x11\x22\x22\x22", b"\x80\xff"),
            (6, b"\x11\x22\x33\x80\x44\x55\x66\xff", b"", b"", b"\x11\x22\x33\x44\x55\x66", b"\x80\xff"),
        ]
        for colour_type, row, palette, transparency, rgb, alpha in cases:
            with self.subTest(colour_type=colour_type):
                image = decode(png(2, 1, colour_type, b"\0" + row, palette, transparency))
                self.assertEqual((image.width, image.height, image.bits), (2, 1, 8))
                self.assertEqual((image.data, image.alpha), (rgb, alpha))
                self.assertEqual((image.colour_space, image.filter), ("/DeviceRGB", "/FlateDecode"))

    def test_filtered_rows_after_unfiltered_rows(self):
        previous = bytes((10, 20, 30, 40, 50, 60))
        expected = bytes((20, 30, 40, 60, 70, 80))
        residuals = {
            1: bytes((20, 30, 40, 40, 40, 40)),
            2: bytes((10, 10, 10, 20, 20, 20)),
            3: bytes((15, 20, 25, 30, 30, 30)),
            4: bytes((10, 10, 10, 20, 20, 20)),
        }
        for filter_type, residual in residuals.items():
            with self.subTest(filter_type=filter_type):
                pixels = b"\0" + previous + bytes((filter_type,)) + residual + b"\0" + previous
                self.assertEqual(decode(png(2, 3, 2, pixels)).data, previous + expected + previous)

    def test_opaque_alpha_is_omitted(self):
        self.assertEqual(decode(png(1, 1, 6, b"\0\x11\x22\x33\xff")).alpha, b"")

    def test_empty_dimensions_preserve_behavior(self):
        for width, height, pixels in [(0, 0, b""), (3, 0, b""), (0, 2, b"\0\x09")]:
            with self.subTest(width=width, height=height):
                image = decode(png(width, height, 2, pixels))
                self.assertEqual((image.data, image.alpha), (b"", b""))

    def test_truncated_final_row_is_zero_padded(self):
        for pixels in (b"\0", b"\0\x11", b"\0\x11\x22\x33\x44\x55"):
            with self.subTest(pixels=pixels):
                self.assertEqual(decode(png(2, 1, 2, pixels)).data, pixels[1:].ljust(6, b"\0"))

    def test_missing_row_filter_raises(self):
        for height, pixels in [(1, b""), (2, b"\0\x11")]:
            with self.subTest(height=height):
                with self.assertRaises(IndexError):
                    decode(png(2, height, 2, pixels))

    def test_invalid_filter_requires_a_source_byte(self):
        self.assertEqual(decode(png(1, 1, 2, b"\x09")).data, b"\0\0\0")
        with self.assertRaisesRegex(ValueError, "invalid PNG row filter"):
            decode(png(1, 1, 2, b"\x09\x11"))


if __name__ == "__main__":
    unittest.main()
