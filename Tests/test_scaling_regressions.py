"""Red acceptance tests for bounded scaling; no wall-clock thresholds.

These contracts intentionally require implementation changes. In particular,
compact screening output needs a format change: the current per-row candidate
lists cannot meet a linear output budget for an all-duplicate corpus.
"""
import contextlib
import csv
import gc
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import weakref

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Tools'))
import research_corpus_core as core
import research_corpus_reproduce as reproduce
import research_corpus_services as services
import sprite_atlas


class ScalingRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def corpus(self, name, count):
        root = self.base / name
        (root / 'records').mkdir(parents=True)
        (root / 'pending').mkdir()
        manifest = {'schema': core.SCHEMA, 'corpus_id': name, 'active_run': 'run-a',
                    'protocol': {}, 'sources': {}, 'operations': {}, 'records': [],
                    'runs': [{'run_id': 'run-a', 'software': {},
                              'recipe': {'queries': [], 'selections': []}}]}
        for index in range(count):
            rid, sid = f'record-{index:04d}', f'source-{index:04d}'
            record = {'schema': core.RECORD_SCHEMA, 'record_id': rid, 'source_id': sid,
                      'run_id': 'run-a', 'kind': 'source', 'created_at': '2026-11-02T00:00:00Z',
                      'title': 'Shared duplicate title', 'url': f'https://example.org/{index}',
                      'text': f'Unique evidence {index} ' + 'body ' * 2048,
                      'markdown': 'Retained markdown', 'process': {'exit_code': 0},
                      'extraction': {}, 'retrieval': {}, 'bibliography': {}}
            paths, hashes = {}, {}
            for kind, content in [('json', core.canonical_bytes(record)),
                                  ('text', (record['text'] + '\n').encode()),
                                  ('markdown', (record['markdown'] + '\n').encode())]:
                relative = f'records/{rid}.{kind}'
                (root / relative).write_bytes(content)
                paths[kind], hashes[relative] = relative, core.sha256(content)
            manifest['records'].append({'record_id': rid, 'source_id': sid,
                                        'run_id': 'run-a', 'kind': 'source',
                                        'paths': paths, 'hashes': hashes})
        core.atomic_json(root / 'manifest.json', manifest)
        return root, manifest

    def test_publication_manifest_bytes_grow_near_linearly(self):
        def workload(count):
            root, _ = self.corpus(f'publication-{count}', 0)
            written = 0
            original = core._atomic_bytes

            def observe(path, data):
                nonlocal written
                if Path(path).name == 'manifest.json':
                    written += len(data)
                return original(path, data)

            with patch.object(core, '_atomic_bytes', side_effect=observe):
                for index in range(count):
                    record = {'schema': core.RECORD_SCHEMA, 'record_id': f'record-{index:04d}',
                              'kind': 'synthesis', 'source_id': None, 'run_id': 'run-a',
                              'text': 'Evidence', 'markdown': 'Evidence',
                              'created_at': '2026-11-02T00:00:00Z', 'process': {'exit_code': 0}}
                    pending = {'record': record}
                    core.atomic_json(root / 'pending/result.json', pending)
                    core._publish(root, pending)
            entries = core.committed_records(root)
            self.assertEqual(len(entries), count)
            for entry in entries:
                self.assertEqual(core.load_record(root, entry)['text'], 'Evidence')
            self.assertGreater(written, 0, 'Instrumentation must observe manifest writes')
            return written

        small, large = workload(16), workload(32)
        self.assertLessEqual(large, small * 2.6,
                             f'Doubling publications rewrote {large}/{small} manifest bytes')

    def test_duplicate_screening_output_grows_near_linearly(self):
        def workload(count):
            root, _ = self.corpus(f'screening-{count}', count)
            ledger, output = self.base / f'ledger-{count}.csv', self.base / f'out-{count}.csv'
            ledger.write_text('source_id\n', encoding='utf-8')
            result = services.reconcile_screening(root, ledger, output)
            with output.open(newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(result['record_count'], count)
            self.assertEqual({row['source_id'] for row in rows},
                             {f'source-{index:04d}' for index in range(count)})
            self.assertEqual(result['duplicate_candidate_count'], count)
            self.assertTrue(all(row['title_abstract_decision'] == 'pending' for row in rows))
            return output.stat().st_size

        small, large = workload(128), workload(256)
        self.assertLessEqual(large, small * 2.6,
                             f'Doubling duplicate sources emitted {large}/{small} CSV bytes')

    def test_enabled_fragment_assignment_avoids_exhaustive_distance_checks(self):
        count, fragments = 64, 64
        parts = [{'bbox': [i * 10, 0, i * 10 + 2, 2], 'area': 2,
                  'pixels': [i * 10, i * 10 + 1]} for i in range(count)]
        parts += [{'bbox': [i * 10 + 3, 0, i * 10 + 4, 1], 'area': 1,
                   'pixels': [i * 10 + 3]} for i in range(fragments)]
        checks = 0
        previous = sys.getprofile()

        def observe(frame, event, arg):
            nonlocal checks
            if event == 'call' and frame.f_code.co_name == 'distance' and frame.f_code.co_filename == sprite_atlas.__file__:
                checks += 1

        try:
            sys.setprofile(observe)
            result = sprite_atlas.arrange(parts, count, count, satellite_distance=2)
        finally:
            sys.setprofile(previous)
        self.assertEqual([part['pixels'] for part in result],
                         [[i * 10, i * 10 + 1, i * 10 + 3] for i in range(count)])
        self.assertGreater(checks, 0, 'Instrumentation must observe distance evaluations')
        self.assertLessEqual(checks, 8 * (count + fragments),
                             f'Fragment assignment evaluated distance {checks} times')

    def test_index_build_does_not_retain_all_text_bodies(self):
        root, manifest = self.corpus('index', 16)
        references = []
        peak = 0
        original = Path.read_text

        class Body(str):
            pass

        def observe(path, *args, **kwargs):
            nonlocal peak
            value = original(path, *args, **kwargs)
            if path.parent == root / 'records' and path.suffix == '.text':
                value = Body(value)
                references.append(weakref.ref(value))
                gc.collect()
                peak = max(peak, sum(ref() is not None for ref in references))
            return value

        db = self.base / 'index.sqlite'
        with patch.object(Path, 'read_text', observe):
            result = services.build_index(root, db)
        self.assertEqual(result['document_count'], 16)
        self.assertEqual(len(references), 16, 'Every text artifact must be read')
        hits = services.query_index(root, db, 'Unique', limit=20)['hits']
        self.assertEqual({hit['record_id'] for hit in hits},
                         {entry['record_id'] for entry in manifest['records']})
        self.assertLessEqual(peak, 2, f'Index build retained {peak} complete text bodies at once')

    def test_reproduction_fallback_run_lookup_is_linear(self):
        root, manifest = self.corpus('reproduction', 32)
        comparisons = 0

        class RunID(str):
            __hash__ = str.__hash__

            def __eq__(self, other):
                nonlocal comparisons
                comparisons += 1
                return super().__eq__(other)

        manifest['runs'] = [{'run_id': RunID(f'run-{i:04d}'),
                             'software': {'path': 'software/shared'}} for i in range(32)]
        for entry in manifest['records']:
            record = core.load_record(root, entry)
            record['run_id'] = 'run-0031'
            record.pop('software', None)
            core.atomic_json(root / entry['paths']['json'], record)
            entry['hashes'][entry['paths']['json']] = core.sha256((root / entry['paths']['json']).read_bytes())
            core.atomic_json(root / f'journal/{entry["record_id"]}.json', {'entry': entry})
        output = self.base / 'reproduced'
        output.mkdir()
        # Isolate lookup from full-package verification and the permanent audit
        # hook; retain real record loading, hash checks and artifact publication.
        with patch.object(reproduce, 'read_manifest', return_value=manifest), \
                patch.object(reproduce, '_verify', return_value=32), \
                patch.object(reproduce, '_software_refs', return_value=[]), \
                patch.object(sys, 'addaudithook'), contextlib.redirect_stdout(io.StringIO()) as report:
            reproduce._worker(root, output, 'software/shared')
        self.assertEqual(json.loads(report.getvalue())['verified_records'], 32)
        for entry in manifest['records']:
            for path in entry['paths'].values():
                self.assertEqual((output / path).read_bytes(), (root / path).read_bytes())
        self.assertGreater(comparisons, 0, 'Instrumentation must observe run identity lookup')
        self.assertLessEqual(comparisons, 4 * (32 + 32),
                             f'Fallback lookup compared run IDs {comparisons} times')


if __name__ == '__main__':
    unittest.main()
