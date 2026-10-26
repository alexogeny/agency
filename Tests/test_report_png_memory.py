import struct
import tracemalloc
import unittest
import zlib

from Tests.test_report_png_perf import PdfImage, decode, png
from Tests.test_report_stream_memory import PdfDocument


class ReportPngMemoryTests(unittest.TestCase):
    def test_peak_allocation_excludes_whole_decoded_image_and_payload_copies(self):
        for size in (256, 512, 512):
            data = png(size, size, 6, (b'\0' + bytes((17, 34, 51, 128)) * size) * size)
            tracemalloc.start()
            try:
                image = decode(data)
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
            self.assertEqual(image.data, bytes((17, 34, 51)) * (size * size))
            self.assertEqual(image.alpha, bytes((128,)) * (size * size))
            self.assertLess(peak, size * size * 5 + 300000)

    def test_pdf_image_streams_are_identical_to_compressing_expected_pixels(self):
        image = decode(png(2, 2, 6, (b'\0' + bytes((17, 34, 51, 128, 68, 85, 102, 255))) * 2))
        document = PdfDocument()
        image.pdf_object(document)
        expected = PdfImage.__new__(PdfImage)
        expected.width, expected.height = 2, 2
        expected.colour_space, expected.bits, expected.filter = '/DeviceRGB', 8, '/FlateDecode'
        expected.data = bytes((17, 34, 51, 68, 85, 102)) * 2
        expected.alpha = bytes((128, 255)) * 2
        reference = PdfDocument()
        expected.pdf_object(reference)
        self.assertEqual(document.objects, reference.objects)

    def test_compressed_stream_errors_are_checked_even_after_last_row(self):
        data = png(1, 1, 2, b'\0\x11\x22\x33')
        position = data.index(b'IDAT') - 4
        length = struct.unpack_from('>I', data, position)[0]
        truncated = data[:position] + struct.pack('>I', length - 1) + data[position + 4:position + 8 + length - 1] + data[position + 8 + length:]
        with self.assertRaises(zlib.error):
            decode(truncated)
        corrupt = bytearray(data)
        corrupt[position + 8 + length - 1] ^= 1
        with self.assertRaises(zlib.error):
            decode(bytes(corrupt))

    def test_extra_decoded_data_is_ignored_but_validated(self):
        image = decode(png(1, 1, 2, b'\0\x11\x22\x33' + b'x' * 200000))
        self.assertEqual(image.data, b'\x11\x22\x33')

    def test_rows_larger_than_inflate_blocks_preserve_pixels(self):
        width = 22000
        row = bytes((17, 34, 51, 128)) * width
        image = decode(png(width, 2, 6, (b'\0' + row) * 2))
        self.assertEqual(image.data, bytes((17, 34, 51)) * (width * 2))
        self.assertEqual(image.alpha, bytes((128,)) * (width * 2))

    def test_compression_errors_take_priority_over_row_errors(self):
        data = png(1, 1, 2, b'\x09\x11\x22\x33')
        position = data.index(b'IDAT') - 4
        length = struct.unpack_from('>I', data, position)[0]
        corrupt = bytearray(data)
        corrupt[position + 8 + length - 1] ^= 1
        with self.assertRaises(zlib.error):
            decode(bytes(corrupt))

    def test_split_idat_chunks_preserve_pixels_and_truncated_rows(self):
        data = png(2, 2, 2, b'\0\x11\x22\x33\x44\x55\x66\0\x77')
        position = data.index(b'IDAT') - 4
        length = struct.unpack_from('>I', data, position)[0]
        compressed = data[position + 8:position + 8 + length]
        parts = []
        for value in compressed:
            body = b'IDAT' + bytes((value,))
            parts.append(struct.pack('>I', 1) + body + struct.pack('>I', zlib.crc32(body)))
        split = data[:position] + b''.join(parts) + data[position + 12 + length:]
        self.assertEqual(decode(split).data, b'\x11\x22\x33\x44\x55\x66\x77\0\0\0\0\0')
