from pathlib import Path
import re
import runpy
import unittest
from unittest.mock import patch
import zlib


MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "Tools" / "report-build"))


class ReportPdfCompressionTests(unittest.TestCase):
    def test_compressed_stream_uses_balanced_level_and_roundtrips(self):
        for data in (b"", bytes(range(256)) * 20):
            with self.subTest(size=len(data)):
                document = MODULE["PdfDocument"]()
                attributes = {"Type": "/Example", "Width": 12}
                with patch.object(zlib, "compress", wraps=zlib.compress) as compress:
                    identifier = document.stream(attributes, data, compress=True)
                compress.assert_called_once_with(data, 6)
                header, payload = document.objects[identifier].split(b"\nstream\n", 1)
                payload = payload.removesuffix(b"\nendstream")
                self.assertEqual(zlib.decompress(payload), data)
                self.assertIn(b"/Filter /FlateDecode", header)
                self.assertEqual(int(re.search(rb"/Length (\d+)", header)[1]), len(payload))
                self.assertEqual(attributes, {"Type": "/Example", "Width": 12})

    def test_uncompressed_stream_keeps_bytes_and_filter(self):
        document = MODULE["PdfDocument"]()
        data = b"\xff\xd8unchanged JPEG stream\xff\xd9"
        with patch.object(zlib, "compress", wraps=zlib.compress) as compress:
            identifier = document.stream({"Filter": "/DCTDecode"}, data)
        compress.assert_not_called()
        self.assertEqual(
            document.objects[identifier],
            f"<< /Filter /DCTDecode /Length {len(data)} >>\nstream\n".encode()
            + data + b"\nendstream",
        )

    def test_jpeg_image_does_not_recompress_payload(self):
        image = MODULE["PdfImage"].__new__(MODULE["PdfImage"])
        image.width, image.height = 2, 1
        image.colour_space, image.bits = "/DeviceRGB", 8
        image.filter, image.alpha = "/DCTDecode", b""
        image.data = b"\xff\xd8unchanged image bytes\xff\xd9"
        document = MODULE["PdfDocument"]()
        with patch.object(zlib, "compress", wraps=zlib.compress) as compress:
            identifier = image.pdf_object(document)
        compress.assert_not_called()
        self.assertIn(b"/Filter /DCTDecode", document.objects[identifier])
        self.assertTrue(document.objects[identifier].endswith(image.data + b"\nendstream"))


if __name__ == "__main__":
    unittest.main()
