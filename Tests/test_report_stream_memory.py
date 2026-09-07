from pathlib import Path
import runpy
import tracemalloc
import unittest
import zlib


PdfDocument = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'Tools' / 'report-build'))['PdfDocument']


class ReportStreamMemoryTests(unittest.TestCase):
    def test_large_stream_peak_excludes_second_payload_copy(self):
        data = b'x' * (1024 * 1024)
        document = PdfDocument()
        tracemalloc.start()
        try:
            identifier = document.stream({'Type': '/XObject'}, data)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual(len(document.objects[identifier]), 1048630)
        self.assertLess(peak, len(data) + 10000)

    def test_stream_and_pdf_bytes_preserve_payload_and_attributes(self):
        for data in [b'', b'hello', bytes(range(256)) * 16, bytes(range(256)) * 4096]:
            for compress in [False, True]:
                for attributes in [{}, {'Type': '/XObject'}, {'Filter': '/DCTDecode', 'Width': 10}]:
                    with self.subTest(size=len(data), compress=compress, attributes=attributes):
                        original = dict(attributes)
                        payload = zlib.compress(data, 6) if compress else data
                        expected_attributes = {**attributes, 'Filter': '/FlateDecode'} if compress else attributes
                        entries = ' '.join(f'/{key} {value}' for key, value in expected_attributes.items())
                        expected = f'<< {entries} /Length {len(payload)} >>\nstream\n'.encode() + payload + b'\nendstream'
                        document = PdfDocument()
                        identifier = document.stream(attributes, data, compress)
                        self.assertEqual(document.objects[identifier], expected)
                        self.assertEqual(attributes, original)
                        reference = PdfDocument()
                        self.assertEqual(reference.add(expected), identifier)
                        self.assertEqual(document.build(identifier), reference.build(identifier))
