import hashlib
import os
from pathlib import Path
import runpy
import tracemalloc
import unittest


HELPERS = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'Tools/agency_processes.py'))


class ProcessMapStreamingTests(unittest.TestCase):
    def test_map_reader_preserves_splitline_and_escape_semantics(self):
        for text in (False, True):
            separators = ['\n', '\r', '\r\n']
            if text:
                separators += ['\v', '\f', '\x1c', '\x1d', '\x1e', '\x85', '\u2028', '\u2029']
            for separator in separators:
                content = separator.join(['', 'short entry',
                    '0-1 r--p 0 00:00 0 /tmp/space name (deleted)',
                    r'0-1 r--p 0 00:00 0 /tmp/escaped\040name', ''])
                if not text:
                    content = content.encode()
                with self.subTest(text=text, separator=repr(separator)):
                    expected = [os.fsdecode(line.split(None, 5)[5]) for line in content.splitlines()
                                if len(line.split(None, 5)) == 6]
                    self.assertEqual(list(HELPERS['mapped_paths'](content)), expected)
                    if not text:
                        decoded = list(HELPERS['mapped_paths'](content, decode_escapes=True))
                        self.assertEqual(decoded, ['/tmp/space name (deleted)', '/tmp/escaped name'])

    def test_many_map_rows_do_not_retain_an_eager_line_list(self):
        count = 30000
        row = b'0-1 r--p 0 00:00 0 /tmp/lib/space name.so\n'
        content = row * count
        expected = hashlib.sha256(b'/tmp/lib/space name.so' * count).hexdigest()
        result = hashlib.sha256()
        tracemalloc.start()
        try:
            for path in HELPERS['mapped_paths'](content):
                result.update(os.fsencode(path))
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(result.hexdigest(), expected)
        self.assertLess(peak, 100000, f'parser retained {peak} bytes for an already resident maps input')

    def test_final_row_and_rejected_buffer_type_remain_consistent(self):
        row = b'0-1 r--p 0 00:00 0 /tmp/no-final-newline'
        self.assertEqual(list(HELPERS['mapped_paths'](row)), ['/tmp/no-final-newline'])
        with self.assertRaises(TypeError):
            list(HELPERS['mapped_paths'](bytearray(row)))


if __name__ == '__main__':
    unittest.main()
