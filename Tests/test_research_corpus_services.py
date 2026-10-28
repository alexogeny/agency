import csv
import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Tools'))
import research_corpus_services as services
from research_corpus_core import CorpusError


class CorpusServicesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'corpus'
        self.root.mkdir()
        self.manifest = {'schema': 'agency/research-corpus/1', 'corpus_id': 'test', 'active_run': 'run-a', 'protocol': {}, 'sources': {'s1': {'url': 'https://example.org/a'}}, 'runs': [{'run_id': 'run-a', 'recipe': {}, 'software': {}}], 'records': []}
        self.add_record('r1')

    def add_record(self, rid, text='Known telescope evidence', kind='source', run='run-a', source='s1'):
        record = {'schema': 'agency/research-record/1', 'record_id': rid, 'source_id': source, 'run_id': run, 'kind': kind, 'created_at': '2026-10-28T00:00:00Z', 'title': 'Example', 'url': 'https://example.org/a', 'payload': {}, 'text': text, 'markdown': text, 'extraction': {'coverage': 'abstract-only'}, 'retrieval': {'access': 'public'}, 'bibliography': {'raw_date': '24 Jun 2025', 'extracted_byline': 'Related author', 'field_provenance': {'byline': 'related-content'}}, 'process': {'exit_code': 0, 'browser_released': True}}
        paths = {}
        hashes = {}
        for key, suffix, data in [('json', '.json', json.dumps(record).encode()), ('text', '.txt', text.encode()), ('markdown', '.md', text.encode())]:
            relative = 'records/' + rid + suffix
            (self.root / 'records').mkdir(exist_ok=True)
            (self.root / relative).write_bytes(data)
            paths[key] = relative
            hashes[relative] = hashlib.sha256(data).hexdigest()
        self.manifest['records'].append({'record_id': rid, 'kind': kind, 'source_id': source, 'run_id': run, 'paths': paths, 'hashes': hashes})
        self.save()

    def save(self):
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest))

    def test_index_filters_and_provenance_and_rebuild(self):
        self.add_record('d1', kind='discovery', source=None)
        db = self.base / 'evidence.sqlite'
        result = services.build_index(self.root, db)
        self.assertEqual(result['document_count'], 2)
        hits = services.query_index(self.root, db, 'telescope')['hits']
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['source_id'], 's1')
        self.assertEqual(hits[0]['url'], 'https://example.org/a')
        self.assertEqual(hits[0]['coverage'], 'abstract-only')
        self.assertEqual(hits[0]['line_start'], 1)
        self.assertEqual(len(services.query_index(self.root, db, 'telescope', kind='discovery')['hits']), 1)
        self.manifest['records'] = self.manifest['records'][1:]
        self.save()
        services.build_index(self.root, db)
        self.assertEqual(services.query_index(self.root, db, 'telescope')['hits'], [])

    def test_failed_rebuild_preserves_generation_and_detects_mismatch(self):
        db = self.base / 'evidence.sqlite'
        services.build_index(self.root, db)
        original = db.read_bytes()
        path = self.root / self.manifest['records'][0]['paths']['text']
        path.write_bytes(b'\xff')
        entry = self.manifest['records'][0]
        relative = entry['paths']['text']
        entry['hashes'][relative] = hashlib.sha256(b'\xff').hexdigest()
        self.save()
        with self.assertRaises(CorpusError) as caught:
            services.build_index(self.root, db)
        self.assertEqual(caught.exception.code, 'invalid-utf8')
        self.assertEqual(db.read_bytes(), original)
        path.write_bytes(b'Known telescope evidence')
        sidecar = db.with_suffix(db.suffix + '.manifest.json')
        meta = json.loads(sidecar.read_text())
        meta['generation'] = 'wrong'
        sidecar.write_text(json.dumps(meta))
        with self.assertRaisesRegex(CorpusError, 'generation'):
            services.query_index(self.root, db, 'telescope')

    def test_invalid_query_missing_db_empty_and_limits(self):
        db = self.base / 'missing.sqlite'
        with self.assertRaises(CorpusError) as caught:
            services.query_index(self.root, db, 'x')
        self.assertEqual(caught.exception.code, 'index-unavailable')
        self.assertFalse(db.exists())
        services.build_index(self.root, db)
        for expression, limit in [('"', 10), ('x', 0), ('x', 1001)]:
            with self.assertRaises(CorpusError):
                services.query_index(self.root, db, expression, limit=limit)
        self.manifest['records'] = []
        self.save()
        with self.assertRaises(CorpusError):
            services.build_index(self.root, db)
        self.assertFalse(services.audit_corpus(self.root)['ok'])

    def test_audit_reports_tamper_and_missing_sibling(self):
        relative = self.manifest['records'][0]['paths']['markdown']
        (self.root / relative).unlink()
        result = services.audit_corpus(self.root)
        self.assertFalse(result['ok'])
        self.assertTrue(any(relative in json.dumps(item) for item in result['issues']))

    def test_screening_preserves_decisions_and_raw_provenance(self):
        old = self.base / 'old.csv'
        old.write_text('source_id,title_abstract_decision,title_abstract_reason,full_text_decision\ns1,exclude,Manual scope,pending\n')
        output = self.base / 'new.csv'
        services.reconcile_screening(self.root, old, output)
        with output.open() as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row['title_abstract_reason'], 'Manual scope')
        self.assertEqual(row['full_text_decision'], 'pending')
        self.assertEqual(row['authors'], '')
        self.assertEqual(row['year'], '')
        self.assertEqual(row['parsed_year'], '2025')
        self.assertEqual(row['extracted_byline'], 'Related author')
        self.assertEqual(row['verification_status'], 'pending')
        with self.assertRaises(CorpusError):
            services.reconcile_screening(self.root, old, output)

    def test_publication_failure_restores_both_generation_files(self):
        db = self.base / 'index.sqlite'
        services.build_index(self.root, db)
        original = db.read_bytes()
        sidecar = db.with_suffix('.sqlite.manifest.json')
        old_meta = sidecar.read_bytes()
        self.add_record('r2', text='Second observation')
        real = services.core().atomic_json
        def failed(path, value):
            real(path, value)
            raise OSError('synthetic directory fsync failure after rename')
        with patch.object(services.core(), 'atomic_json', failed):
            with self.assertRaisesRegex(OSError, 'synthetic'):
                services.build_index(self.root, db)
        self.assertEqual(db.read_bytes(), original)
        self.assertEqual(sidecar.read_bytes(), old_meta)
        self.assertEqual(len(services.query_index(self.root, db, 'telescope')['hits']), 1)

    def test_reader_during_rebuild_sees_valid_generation(self):
        db = self.base / 'index.sqlite'
        services.build_index(self.root, db)
        self.add_record('r2', text='More telescope evidence')
        with ThreadPoolExecutor(max_workers=2) as pool:
            build = pool.submit(services.build_index, self.root, db)
            read = pool.submit(services.query_index, self.root, db, 'telescope')
            self.assertIn(len(read.result()['hits']), (1, 2))
            self.assertEqual(build.result()['document_count'], 2)
        self.assertEqual(len(services.query_index(self.root, db, 'telescope')['hits']), 2)

    def test_match_lines_and_compare_drift(self):
        self.manifest['runs'].append({'run_id': 'run-b', 'recipe': {'changed': True}, 'software': {'new': True}})
        self.add_record('r2', text='First line\nChanged telescope body', run='run-b')
        db = self.base / 'index.sqlite'
        services.build_index(self.root, db)
        hits = services.query_index(self.root, db, 'Changed')['hits']
        self.assertEqual(hits[0]['line_start'], 2)
        self.assertEqual(hits[0]['line_end'], 2)
        result = services.compare_runs(self.root, 'run-a', 'run-b')
        self.assertTrue(result['software_changed'])
        self.assertTrue(result['recipe_changed'])
        self.assertIn('body', result['changes'][0]['fields'])
        self.manifest['records'] = [e for e in self.manifest['records'] if e['run_id'] != 'run-b']
        self.save()
        self.assertEqual(services.compare_runs(self.root, 'run-a', 'run-b')['changes'][0]['change'], 'removed')

    def test_verification_requires_inspected_field_alignment(self):
        bib = {'verified_authors': ['Related author'], 'authors_verification_status': 'verified', 'field_provenance': {'authors': {'origin': 'related-content', 'inspected': True, 'alignment_verified': True}}}
        self.assertFalse(services._verified_field(bib, 'authors'))
        bib['field_provenance']['authors']['origin'] = 'metadata'
        bib['field_provenance']['authors']['alignment_verified'] = False
        self.assertFalse(services._verified_field(bib, 'authors'))
        bib['field_provenance']['authors']['alignment_verified'] = True
        self.assertTrue(services._verified_field(bib, 'authors'))
        self.assertFalse(services._verified_field(bib, 'year'))

    def test_duplicate_candidates_do_not_remove_sources(self):
        self.manifest['sources']['s2'] = {'url': 'https://example.org/alias'}
        self.add_record('r2', source='s2')
        old = self.base / 'old.csv'
        old.write_text('source_id\n')
        output = self.base / 'new.csv'
        result = services.reconcile_screening(self.root, old, output)
        self.assertEqual(result['record_count'], 2)
        with output.open() as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]['duplicate_candidates'], 's2')
        self.assertEqual(rows[1]['duplicate_candidates'], 's1')
        self.assertTrue(all(not row['duplicate_of'] for row in rows))

    def test_dates_are_explicit_and_ambiguous_remains_unknown(self):
        self.assertEqual(services.parse_year('24 Jun 2025'), 2025)
        self.assertEqual(services.parse_year('2025-06-24'), 2025)
        self.assertIsNone(services.parse_year('06/07/2025'))
        self.assertIsNone(services.parse_year('unrelated 2025 mention'))

    def test_database_cannot_be_generated_inside_a_repository(self):
        project = self.base / 'project'
        project.mkdir()
        (project / '.git').mkdir()
        database = project / 'runtime' / 'corpus.sqlite'
        with self.assertRaises(services.core().CorpusError) as caught:
            services.build_index(self.root, database)
        self.assertEqual(caught.exception.code, 'unsafe-path')
        self.assertFalse(database.exists())

    def test_pending_intent_fails_audit_after_existing_commits(self):
        pending = self.root / 'pending'
        pending.mkdir()
        (pending / 'request.json').write_text('{"schema":"agency/research-intent/1"}')
        report = services.audit_corpus(self.root)
        self.assertTrue(any(issue['check'] == 'incomplete-checkpoint'
                            for issue in report['issues']))

    def test_local_documents_do_not_count_as_opened_sources(self):
        self.add_record('synthesis-one', text='Locally authored conclusion', kind='synthesis', source=None)
        result = services.audit_corpus(self.root)
        self.assertEqual(result['counts']['opened'], 1)

    def test_audit_verifies_observation_processor_not_only_run_processor(self):
        entry = self.manifest['records'][0]
        path = self.root / entry['paths']['json']
        record = json.loads(path.read_text())
        software = self.root / 'software' / 'observation'
        software.mkdir(parents=True)
        (software / 'processor.py').write_text('changed processor')
        record['software'] = {'schema': 'agency/research-software/1',
                              'path': 'software/observation',
                              'hashes': {'processor.py': 'incorrect'},
                              'runtime': {'python': 'fixture'}}
        path.write_text(json.dumps(record))
        entry['hashes'][entry['paths']['json']] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.save()
        result = services.audit_corpus(self.root)
        self.assertTrue(any(issue['check'] == 'software-hash' and issue.get('record_id') == 'r1'
                            for issue in result['issues']))


if __name__ == '__main__':
    unittest.main()
