"""Additional red resource contracts, using synthetic inputs and direct counters.

Budgets allow streaming and indexed implementations; they make no latency or
production-load claims. Archive tests also cover untracked working-tree tools.
"""
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'Tools'
sys.path.insert(0, str(TOOLS))
import agency_browser_downloads as downloads
import agency_decision_usage as usage
import archive_verify

loader = importlib.machinery.SourceFileLoader('budget_agent_context', str(TOOLS / 'agent-context'))
spec = importlib.util.spec_from_loader(loader.name, loader)
context = importlib.util.module_from_spec(spec)
loader.exec_module(context)


class ResourceBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def test_download_path_validation_does_not_repeatedly_split_deep_paths(self):
        def workload(depth):
            scanned = 0

            class Destination(str):
                def split(self, *args, **kwargs):
                    nonlocal scanned
                    scanned += len(self)
                    return super().split(*args, **kwargs)

            path = Destination('/'.join(['dir'] * depth + ['file.bin']))
            manifest = {'schema_version': 1, 'allowed_origins': ['https://example.org'],
                        'items': [{'id': 'item', 'url': 'https://example.org/file.bin',
                                   'filename': 'file.bin', 'expected_size': 1, 'path': path}]}
            result = downloads.validate_manifest(manifest)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]['path'], path)
            self.assertEqual(result[0]['resource'], 'https://example.org/file.bin')
            # Preserve parent-conflict rejection while changing the path algorithm.
            manifest['items'].append({'id': 'parent', 'url': 'https://example.org/parent',
                                      'filename': 'dir', 'expected_size': 0, 'path': 'dir'})
            with self.assertRaisesRegex(downloads.BrowserError, 'parent'):
                downloads.validate_manifest(manifest)
            return scanned

        small, large = workload(64), workload(128)
        self.assertLessEqual(large, 2.6 * small,
                             f'Doubled path depth scanned {large}/{small} characters in split()')

    def test_archive_hardlinks_hash_each_source_inode_once(self):
        source = self.base / 'source'
        source.mkdir()
        payload = b'archive evidence\n' * 512
        first = source / 'file-00'
        first.write_bytes(payload)
        for index in range(1, 16):
            os.link(first, source / f'file-{index:02d}')
        # Integral-second times avoid tarfile's float-to-nanosecond rounding.
        for path in (first, source):
            os.utime(path, ns=(1_700_000_000_000_000_000,) * 2)
        archive_path = self.base / 'archive.tar'
        with tarfile.open(archive_path, 'w', format=tarfile.PAX_FORMAT) as archive:
            archive.add(source, arcname=source.name)
        hashed = 0
        original = archive_verify.digest_source

        def observe(path, expected):
            nonlocal hashed
            hashed += expected['size']
            return original(path, expected)

        with patch.object(archive_verify, 'digest_source', side_effect=observe):
            result = archive_verify.verify(source, archive_path)
        self.assertEqual(result['regular_files'], 16)
        self.assertEqual(result['logical_file_bytes'], 16 * len(payload))
        # Reusing content must still reject content that differs from the archive.
        first.write_bytes(b'x' * len(payload))
        with self.assertRaisesRegex(ValueError, 'content'):
            archive_verify.verify(source, archive_path)
        self.assertLessEqual(hashed, 2 * len(payload),
                             f'Hashed {hashed} source bytes for one {len(payload)}-byte inode')

    def test_archive_size_mismatch_stops_before_hashing_oversized_payload(self):
        source = self.base / 'source'
        source.mkdir()
        path = source / 'file'
        path.write_bytes(b'expected')
        expected = archive_verify.inventory(source)
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w', format=tarfile.PAX_FORMAT) as archive:
            member = archive.gettarinfo(str(path), arcname='source/file')
            member.size = 65536
            archive.addfile(member, io.BytesIO(b'x' * member.size))
        buffer.seek(0)
        hashed = 0

        def observe(stream):
            nonlocal hashed
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(8192), b''):
                hashed += len(block)
                digest.update(block)
            return digest.hexdigest()

        with tarfile.open(fileobj=buffer, mode='r|*') as archive, \
                patch.object(archive_verify, 'digest_stream', side_effect=observe):
            with self.assertRaisesRegex(ValueError, 'file size'):
                archive_verify.validate_archive(archive, source, expected, io.StringIO())
        self.assertLessEqual(hashed, 2 * path.stat().st_size,
                             f'Hashed {hashed} bytes despite a known archive-size mismatch')

    def test_instruction_audit_streams_documents_beyond_context_budget(self):
        project, home = self.base / 'project', self.base / 'codex'
        (project / '.git').mkdir(parents=True)
        home.mkdir()
        data = b'# Visible\n' + b'line\n' * 65536 + b'# Hidden\n'
        document = project / 'AGENTS.md'
        document.write_bytes(data)
        chunks = []
        original = Path.open

        class Observe:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                self.stream.__enter__()
                return self

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

            def __getattr__(self, name):
                return getattr(self.stream, name)

            def read(self, *args, **kwargs):
                value = self.stream.read(*args, **kwargs)
                chunks.append(len(value))
                return value

        def observe(path, *args, **kwargs):
            stream = original(path, *args, **kwargs)
            return Observe(stream) if path == document else stream

        with patch.object(Path, 'open', observe):
            result = context.audit(project, home)
        self.assertEqual(result['project_bytes']['selected'], len(data))
        self.assertEqual(result['project_bytes']['included'], context.DEFAULT_MAX_BYTES)
        self.assertTrue(result['truncated'])
        self.assertIn('# Hidden', result['truncation']['headings_hidden'])
        self.assertEqual(result['project_instructions'][0]['sha256'], hashlib.sha256(data).hexdigest())
        self.assertLessEqual(max(chunks, default=0), 65536,
                             f'Instruction audit materialized a {max(chunks, default=0)}-byte read')

    def test_receipt_visit_budget_also_bounds_embedded_json_parsing(self):
        lines = [json.dumps({usage.MARKER: {'version': 1, 'id': f'{index:032x}',
                 'created_ns': 1, 'decisions': 1, 'errors': 0, 'reused': 0}})
                 for index in range(5000)]
        payload = '\n'.join(lines)
        self.assertLess(len(payload), usage.MAX_INPUT)
        original = usage.json.loads
        with patch.object(usage.json, 'loads', wraps=original) as loads:
            found, complete = usage.receipts(payload)
        self.assertFalse(complete, 'Exhausting the traversal budget must be reported')
        self.assertTrue(found, 'Bounded parsing must retain valid receipts already visited')
        self.assertTrue(set(found).issubset({f'{index:032x}' for index in range(5000)}))
        self.assertLessEqual(loads.call_count, 4097,
                             f'Visit-limited receipt traversal still parsed JSON {loads.call_count} times')


if __name__ == '__main__':
    unittest.main()
