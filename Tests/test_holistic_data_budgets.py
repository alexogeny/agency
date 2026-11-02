"""Red acceptance contracts for data-workflow work amplification and budgets.

These isolate actual implementations with synthetic fixtures. They measure
verification reads, inspected entries, retained records and SQLite result bytes;
none assert elapsed time or execute a backend/network service.
"""
import io
import json
from pathlib import Path
import sqlite3
import sys
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch
import weakref

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Tools'))
import archive_verify
import agency_decisions as decisions
import research_corpus_core as core
import research_corpus_services as services
import sprite_atlas


class HolisticDataBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def corpus(self, runs=1, text='Evidence body'):
        root = self.base / 'corpus'
        root.mkdir()
        (root / 'records').mkdir()
        (root / 'software/shared').mkdir(parents=True)
        software_path = root / 'software/shared/processor.py'
        software_path.write_bytes(b'processor evidence\n' * 256)
        software = {'path': 'software/shared', 'hashes': {'processor.py': core.sha256(software_path.read_bytes())},
                    'runtime': {'python': 'fixture'}}
        record = {'schema': core.RECORD_SCHEMA, 'record_id': 'record-a', 'source_id': 'source-a',
                  'run_id': 'run-0', 'kind': 'source', 'created_at': '2026-11-02T00:00:00Z',
                  'title': 'Fixture', 'url': 'https://example.org/a', 'text': text, 'markdown': text,
                  'process': {'exit_code': 0, 'browser_released': True},
                  'extraction': {'coverage': 'full-public-extract'}, 'retrieval': {'access': 'public'},
                  'software': software, 'identities': {'sanitized_body_sha256': core.sha256(text.encode())},
                  'transformations': [{'version': core.SANITIZER_VERSION}]}
        entry = {'record_id': 'record-a', 'source_id': 'source-a', 'run_id': 'run-0', 'kind': 'source', 'paths': {}, 'hashes': {}}
        for kind, data in [('json', core.canonical_bytes(record)), ('text', (text + '\n').encode()), ('markdown', (text + '\n').encode())]:
            relative = f'records/record-a.{kind}'
            (root / relative).write_bytes(data)
            entry['paths'][kind] = relative
            entry['hashes'][relative] = core.sha256(data)
        manifest = {'schema': core.SCHEMA, 'corpus_id': 'fixture', 'active_run': 'run-0',
                    'protocol': {}, 'redaction_policy': core.SANITIZER_VERSION,
                    'sources': {'source-a': {'url': record['url']}}, 'records': [entry],
                    'runs': [{'run_id': f'run-{i}', 'software': software,
                              'recipe': {'schema': 'agency/research-recipe/1'}} for i in range(runs)]}
        core.atomic_json(root / 'manifest.json', manifest)
        core.atomic_json(root / 'journal/record-a.json', {'entry': entry})
        return root, entry, manifest

    def test_attempt_budget_does_not_rescan_all_prior_records_for_every_attempt(self):
        inspections = 0

        class Entry(dict):
            def __getitem__(self, key):
                nonlocal inspections
                inspections += key == 'run_id'
                return super().__getitem__(key)

        manifest = {'active_run': 'run-a', 'records': [], 'protocol': {'budgets': {'queries': 64}},
                    'runs': [{'run_id': 'run-a', 'recipe': {'stopping_decisions': []}}]}
        for _ in range(64):
            core._enforce_budget(self.base, manifest, 'queries')
            manifest['records'].append(Entry(run_id='run-a', kind='discovery'))
        with patch.object(core, 'atomic_json'):
            with self.assertRaises(core.CorpusError) as caught:
                core._enforce_budget(self.base, manifest, 'queries')
        self.assertEqual(caught.exception.code, 'budget-exhausted')
        self.assertEqual(manifest['runs'][0]['recipe']['stopping_decisions'][0]['observed_attempts'], 64)
        self.assertLessEqual(inspections, 4 * 64,
                             f'64 attempts inspected run identities {inspections} times')

    def test_audit_reuses_verification_of_identical_run_software(self):
        root, _, _ = self.corpus(runs=32)
        target = root / 'software/shared/processor.py'
        reads = 0
        original = Path.read_bytes

        def observe(path):
            nonlocal reads
            reads += path == target
            return original(path)

        with patch.object(Path, 'read_bytes', observe):
            result = services.audit_corpus(root)
        self.assertTrue(result['ok'], result['issues'])
        self.assertEqual(result['record_count'], 1)
        self.assertLessEqual(reads, 2, f'One shared software artifact was verified {reads} times')

    def test_audit_reads_each_sibling_once_for_integrity_and_consistency(self):
        root, entry, _ = self.corpus(text='retained evidence ' * 1024)
        target = root / entry['paths']['text']
        reads = 0
        original = Path.read_bytes

        def observe(path):
            nonlocal reads
            reads += path == target
            return original(path)

        with patch.object(Path, 'read_bytes', observe):
            result = services.audit_corpus(root)
        self.assertTrue(result['ok'], result['issues'])
        target.write_text('corrupted sibling\n')
        self.assertFalse(services.audit_corpus(root)['ok'])
        self.assertLessEqual(reads, 1, f'One text sibling was read {reads} times in one audit')

    def test_run_comparison_retains_latest_body_per_identity(self):
        refs = []
        peak = 0
        entries = [{'record_id': f'old-{i}', 'source_id': 'source-a', 'kind': 'source', 'run_id': 'old'} for i in range(32)]
        entries += [{'record_id': 'new-0', 'source_id': 'source-a', 'kind': 'source', 'run_id': 'new'}]

        class Record(dict):
            pass

        def load(root, entry):
            nonlocal peak
            record = Record(record_id=entry['record_id'], text=entry['record_id'] + ' evidence ' * 1024)
            refs.append(weakref.ref(record))
            peak = max(peak, sum(ref() is not None for ref in refs))
            return record

        manifest = {'runs': [{'run_id': 'old'}, {'run_id': 'new'}]}
        with patch.object(core, 'read_manifest', return_value=manifest), \
                patch.object(core, 'committed_records', return_value=entries), \
                patch.object(core, 'load_record', side_effect=load):
            result = services.compare_runs(self.base, 'old', 'new')
        self.assertEqual(len(refs), 33)
        self.assertEqual(len(result['changes']), 1)
        self.assertEqual(result['changes'][0]['old_record_id'], 'old-31')
        self.assertEqual(result['changes'][0]['new_record_id'], 'new-0')
        self.assertLessEqual(peak, 3, f'Comparison retained {peak} bodies for one shared identity')

    def test_index_query_does_not_transfer_full_document_for_line_numbers(self):
        root, _, _ = self.corpus(text='ordinary filler\n' * 8192 + 'needle evidence\n')
        db = self.base / 'index.sqlite'
        services.build_index(root, db)
        delivered = 0
        original = sqlite3.connect

        class Cursor:
            def __init__(self, cursor):
                self.cursor = cursor

            def __getattr__(self, name):
                return getattr(self.cursor, name)

            def fetchall(self):
                nonlocal delivered
                rows = self.cursor.fetchall()
                delivered += sum(len(value.encode()) for row in rows for value in row if isinstance(value, str))
                return rows

        class Connection:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, *args, **kwargs):
                return Cursor(self.connection.execute(*args, **kwargs))

            def close(self):
                self.connection.close()

        with patch.object(services.sqlite3, 'connect', side_effect=lambda *a, **kw: Connection(original(*a, **kw))):
            result = services.query_index(root, db, 'needle')
        self.assertEqual(len(result['hits']), 1)
        self.assertEqual(result['hits'][0]['line_start'], 8193)
        self.assertIn('[needle]', result['hits'][0]['snippet'])
        self.assertLessEqual(delivered, 4096, f'One short result transferred {delivered} SQLite string bytes')

    def test_invalid_decision_batch_cardinality_rejects_before_deep_traversal(self):
        manifest = {'items': [{'id': f'case-{i}', 'profile': 'unused', 'state': {'evidence': 'x'}} for i in range(1024)]}
        original = decisions._check_json
        with patch.object(decisions, '_check_json', wraps=original) as visits:
            with self.assertRaises(decisions.DecisionError) as caught:
                decisions.prepare_batch(manifest)
        self.assertIn('1 to 32', str(caught.exception))
        self.assertLessEqual(visits.call_count, 2,
                             f'Invalid batch cardinality traversed {visits.call_count} JSON nodes before rejecting')

    def test_archive_structural_errors_have_bounded_inspection_budget(self):
        visits = 0

        def members():
            nonlocal visits
            for i in range(4096):
                visits += 1
                yield tarfile.TarInfo(f'unexpected-{i}')

        with self.assertRaisesRegex(ValueError, 'unexpected path'):
            archive_verify.validate_archive(members(), self.base, {}, io.StringIO())
        self.assertLessEqual(visits, 32,
                             f'Archive with no expected entries inspected {visits} unexpected members')

    def test_sprite_padding_has_aggregate_output_pixel_budget(self):
        source = self.base / 'sprites.png'
        source.write_bytes(b'synthetic image input; image codec boundary is stubbed')
        pixels = {(x, y): (255, 0, 0, 255) for y in range(0, 16, 4) for x in range(0, 16, 4)}
        alpha = bytes(255 if (i % 16, i // 16) in pixels else 0 for i in range(256))

        class Original:
            width = height = 16
            size = (16, 16)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def convert(self, mode):
                return self

            def getchannel(self, channel):
                return types.SimpleNamespace(tobytes=lambda: alpha)

            def load(self):
                return pixels
        allocated = 0
        written = []

        class Crop:
            def __init__(self, size):
                self.size = size

            def load(self):
                return {}

            def save(self, path):
                written.append(path)

        def crop(mode, size, *args, **kwargs):
            nonlocal allocated
            allocated += size[0] * size[1]
            return Crop(size)

        names = [f'sprite-{i}' for i in range(16)]
        # Keep component detection, assignment, padding and crop allocation real;
        # stub only Pillow decoding/allocation so no huge images are allocated.
        pillow = types.ModuleType('PIL')
        pillow.Image = types.SimpleNamespace(open=lambda stream: Original(), new=crop)
        with patch.dict(sys.modules, {'PIL': pillow}):
            try:
                result = sprite_atlas.extract(source, self.base / 'output', names, 4, padding=1024)
            except ValueError as error:
                # Explicit aggregate-budget rejection is a valid future behavior.
                self.assertRegex(str(error).lower(), r'budget|pixels|output.*limit')
            else:
                self.assertEqual(len(result['crops']), len(names))
                self.assertEqual(len(written), len(names))
                self.assertEqual(result['unassigned_pixels'], 0)
        self.assertEqual(allocated, 0,
                         f'Over-budget extraction allocated {allocated} padded pixels before aggregate preflight rejection')
        self.assertEqual(written, [], 'Over-budget extraction must not publish partial sprite outputs')


if __name__ == '__main__':
    unittest.main()
