import hashlib
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MAPPER = runpy.run_path(str(ROOT / 'Tools/repo-map'))
CONTEXT = runpy.run_path(str(ROOT / 'Tools/agent-context'))


class DeveloperHolisticTests(unittest.TestCase):
    def test_oversized_mapper_payloads_are_bounded_without_losing_hashes_or_sizes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = b'x' * (2 * 1024 * 1024)
            sources = {'large.py': payload, 'large.bin': b'\0' + payload,
                       'executable': b'#!/usr/bin/env python3\n' + payload}
            for name, data in sources.items():
                (root / name).write_bytes(data)
            retained = []
            cached = MAPPER['cached_facts']

            def observe(*args, **kwargs):
                retained.append(len(args[2]))
                return cached(*args, **kwargs)

            with patch.dict(MAPPER['build_map'].__globals__, cached_facts=observe):
                result = MAPPER['build_map'](root, [], 8192, False)
            self.assertEqual(result['summary']['bytes'], sum(map(len, sources.values())))
            self.assertEqual(len(retained), 3)
            self.assertLessEqual(max(retained), 8193)
            for item in result['files']:
                self.assertEqual(item['sha256'], hashlib.sha256(sources[item['path']]).hexdigest())
                self.assertEqual(item['bytes'], len(sources[item['path']]))
                self.assertEqual(item['parse_skipped'], 'size')
                self.assertEqual(item['language'], None if item['path'] == 'large.bin' else 'python')

    def test_oversized_shebang_and_custom_parse_limit_preserve_language_and_facts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = {
                'long-command': b'#!' + b' ' * 10000 + b'python\r' + b'x' * 10000,
                'small.py': b'import os\n',
                'exact.py': b'#' + b'a' * 31,
                'over.py': b'#' + b'a' * 32,
            }
            for name, data in sources.items():
                (root / name).write_bytes(data)
            (root / 'alias').symlink_to('small.py')
            result = MAPPER['build_map'](root, [], 32, False)
            by_path = {item['path']: item for item in result['files']}
            self.assertEqual(by_path['long-command']['language'], 'python')
            self.assertEqual(by_path['long-command']['parse_skipped'], 'size')
            self.assertNotIn('parse_skipped', by_path['exact.py'])
            self.assertEqual(by_path['over.py']['parse_skipped'], 'size')
            self.assertEqual(by_path['small.py']['imports'], [{'module': 'os', 'line': 1}])
            self.assertEqual(by_path['alias']['symlink_target'], 'small.py')

    def test_context_only_decodes_hidden_heading_candidates(self):
        decoded = []

        class Line(bytes):
            def decode(self, *args, **kwargs):
                decoded.append(len(self))
                return super().decode(*args, **kwargs)

        class Data(bytes):
            def splitlines(self, *args, **kwargs):
                return [Line(line) for line in super().splitlines(*args, **kwargs)]

        content = Data(b'# Seen\r\n' + (b'Prose with invalid UTF-8: \xff and details.\n' * 300)
                       + b'## Hidden\r\n#\tNot a heading\n### Last\n')
        headings = CONTEXT['hidden_headings'](content, 8)
        self.assertEqual(headings, ['## Hidden', '### Last'])
        self.assertLessEqual(sum(decoded), len(b'## Hidden\r\n#\tNot a heading\n### Last\n'))


class MapperReadHintTests(unittest.TestCase):
    def test_small_file_does_not_allocate_the_whole_parse_limit(self):
        import tracemalloc
        mapper = runpy.run_path(str(ROOT / 'Tools/repo-map'))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = b'x' * (128 * 1024)
            (root / 'sample.py').write_bytes(payload)
            tracemalloc.start()
            try:
                value = mapper['read_file'](root, Path('sample.py'), 2 * 1024 * 1024)
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
            self.assertEqual(value[1], payload)
            self.assertLess(peak, 180_000, peak)

    def test_underestimated_open_file_size_does_not_truncate_content_or_hash(self):
        from types import SimpleNamespace
        mapper = runpy.run_path(str(ROOT / 'Tools/repo-map'))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = b'x' * (4 * 1024 * 1024)
            path = root / 'sample.py'
            path.write_bytes(payload)
            real = path.stat()
            hint = SimpleNamespace(st_size=0, st_mode=real.st_mode)
            with patch.object(mapper['os'], 'fstat', return_value=hint):
                value = mapper['read_file'](root, Path('sample.py'), 2 * 1024 * 1024)
            self.assertEqual(value[1], b'')
            self.assertEqual(value[3], hashlib.sha256(payload).hexdigest())
            self.assertEqual(value[4], len(payload))


    def test_short_raw_reads_preserve_small_and_oversized_files(self):
        mapper = runpy.run_path(str(ROOT / 'Tools/repo-map'))
        original = Path.open
        class ShortReader:
            def __init__(self, handle):
                self.handle = handle
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.handle.close()
            def fileno(self):
                return self.handle.fileno()
            def read(self, count):
                return self.handle.read(min(count, 7))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for length in (80, 400):
                with self.subTest(length=length):
                    payload = b'x' * length
                    (root / 'sample.py').write_bytes(payload)
                    with patch.object(Path, 'open', lambda path, *a, **kw: ShortReader(original(path, *a, **kw))):
                        value = mapper['read_file'](root, Path('sample.py'), 128)
                    self.assertEqual(value[1], payload if length <= 128 else b'')
                    self.assertEqual(value[3], hashlib.sha256(payload).hexdigest())
                    self.assertEqual(value[4], length)


if __name__ == '__main__':
    unittest.main()
