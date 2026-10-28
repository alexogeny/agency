import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'Tools'
spec = importlib.util.spec_from_file_location('research_corpus_core', TOOLS / 'research_corpus_core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


class CorpusCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'corpus'
        self.protocol = Path(self.tmp.name) / 'protocol.json'
        self.protocol.write_text(json.dumps({'scope': 'synthetic research'}))
        core.init_corpus(self.root, self.protocol)

    def test_atomic_gate_resume_and_idempotency(self):
        payload = {'results': [{'url': 'https://example.org/a', 'title': 'Alpha'}]}
        with patch.object(core, 'run_backend', return_value=(payload, {'exit_code': 0})), patch.dict(os.environ, {'RESEARCH_CORPUS_CRASH_AT': 'text'}):
            with self.assertRaises(core.CorpusError):
                core.discover(self.root, 'alpha', 'fixture', 'first')
        with patch.object(core, 'run_backend') as backend:
            with self.assertRaises(core.CorpusError) as error:
                core.discover(self.root, 'beta', 'fixture', 'second')
            self.assertEqual(error.exception.code, 'export-pending')
            backend.assert_not_called()
        result = core.resume(self.root)
        self.assertEqual(len(result['records']), 1)
        with patch.object(core, 'run_backend') as backend:
            again = core.discover(self.root, 'alpha', 'fixture', 'first')
            backend.assert_not_called()
        self.assertEqual(again['record_id'], result['records'][0])
        entry = core.committed_records(self.root)[0]
        for name in entry['paths'].values():
            self.assertTrue(core.safe_path(self.root, name).is_file())

    def test_sanitize_nested_encoded_values_and_stable_sources(self):
        value = core.sanitize({'url': 'https://example.org/?doc=3&X-Amz-Signature=SYNTHETIC_SECRET', 'token': 'SYNTHETIC_SECRET', 'nested': ['https:\\/\\/example.org/?sig=SYNTHETIC_SECRET&amp;doc=4']})
        self.assertNotIn('SYNTHETIC_SECRET', json.dumps(value))
        self.assertIn('doc=3', value['url'])
        with patch.object(core, 'run_backend', return_value=({'results': [{'url': 'https://example.org/a'}]}, {'exit_code': 0})):
            core.discover(self.root, 'alpha', 'fixture', 'one')
            core.discover(self.root, 'beta', 'fixture', 'two')
        self.assertEqual(len(core.read_manifest(self.root)['sources']), 1)

    def test_path_and_hash_validation(self):
        with self.assertRaises(core.CorpusError):
            core.safe_path(self.root, '../escape')
        (self.root / 'link').symlink_to(self.protocol)
        with self.assertRaises(core.CorpusError):
            core.safe_path(self.root, 'link')

    def test_nonzero_process_retains_evidence(self):
        with patch.object(core, 'run_backend', return_value=({'text': 'retained body', 'url': 'https://example.org/a'}, {'exit_code': 7, 'browser_released': False})):
            result = core.open_source(self.root, 'source-a', 'https://example.org/a', 'fixture')
        record = core.load_record(self.root, core.committed_records(self.root)[0])
        self.assertEqual(record['process']['exit_code'], 7)
        self.assertEqual(record['extraction']['coverage'], 'unknown')
        self.assertEqual(result['status'], 'evidence-retained-process-failed')

    def test_every_export_crash_boundary_resumes_once(self):
        for stage in ['checkpoint', 'json', 'text', 'markdown', 'rename', 'before-manifest', 'manifest']:
            with self.subTest(stage=stage):
                root = Path(self.tmp.name) / stage
                core.init_corpus(root, self.protocol)
                with patch.object(core, 'run_backend', return_value=({'results': []}, {'exit_code': 0})), patch.dict(os.environ, {'RESEARCH_CORPUS_CRASH_AT': stage}):
                    with self.assertRaises(core.CorpusError):
                        core.discover(root, 'query', 'fixture', 'one')
                core.resume(root)
                core.resume(root)
                self.assertEqual(len(core.committed_records(root)), 1)
                self.assertEqual(len(list((root / 'journal').glob('*.json'))), 1)
                core.load_record(root, core.committed_records(root)[0])

    def test_intent_crash_never_repeats_search(self):
        with patch.object(core, 'run_backend') as backend, patch.dict(os.environ, {'RESEARCH_CORPUS_CRASH_AT': 'intent'}):
            with self.assertRaises(core.CorpusError):
                core.discover(self.root, 'query', 'fixture', 'one')
            backend.assert_not_called()
        with patch.object(core, 'run_backend') as backend:
            with self.assertRaises(core.CorpusError):
                core.discover(self.root, 'another', 'fixture', 'two')
            core.resume(self.root)
            backend.assert_not_called()
        record = core.load_record(self.root, core.committed_records(self.root)[0])
        self.assertEqual(record['payload']['outcome'], 'interrupted-unknown')
        self.assertIsNone(record['process']['exit_code'])

    def test_profile_handles_remain_private_and_exact(self):
        handle = {'schema': 'agency/owned-profile/1', 'owner_execution': 'fixture-owner', 'canonical_path': '/private/profile', 'nonce': 'fixture-nonce', 'authorization': {'reference': 'fixture-permission', 'owner_execution': 'fixture-owner', 'disposable': True}}
        with patch.dict(os.environ, {'XDG_STATE_HOME': str(Path(self.tmp.name) / 'private')}), patch.object(core, 'run_backend', return_value=(handle, {'exit_code': 0})):
            result = core.profiles(self.root, 'create', 'fixture-owner', authorization=handle['authorization'])
            self.assertNotIn('canonical_path', result)
            selected = core.profiles(self.root, 'handles', 'fixture-owner', authorization=handle['authorization'])['requests'][0]
            self.assertEqual(selected['handle'], handle)
            self.assertEqual(selected['authorization'], handle['authorization'])
            with self.assertRaises(core.CorpusError):
                core.profiles(self.root, 'handles', 'wrong-owner', authorization=handle['authorization'])
            with self.assertRaises(core.CorpusError):
                core.profiles(self.root, 'handles', 'fixture-owner', authorization={**handle['authorization'], 'reference': 'wrong'})
        self.assertNotIn('/private/profile', (self.root / 'manifest.json').read_text())

    def test_encoded_url_and_nested_signed_redirect_are_sanitized(self):
        text = 'https%3A%2F%2Fexample.org%2F%3Fdoc%3D4%26signature%3DSYNTHETIC_SECRET'
        self.assertNotIn('SYNTHETIC_SECRET', core.sanitize(text))
        text = 'https://example.org/?redirect=https%3A%2F%2Fexample.org%2F%3Fsig%3DSYNTHETIC_SECRET'
        self.assertNotIn('SYNTHETIC_SECRET', core.sanitize(text))

    def test_retained_mixed_document_is_committed_and_idempotent(self):
        document = Path(self.tmp.name) / 'synthesis.md'
        document.write_text('# Finding\n\nA retained synthesis. https://example.org/?sig=SYNTHETIC_SECRET')
        result = core.retain(self.root, document, 'synthesis', 'draft-one', 'markdown')
        again = core.retain(self.root, document, 'synthesis', 'draft-one', 'markdown')
        self.assertEqual(result['record_id'], again['record_id'])
        record = core.load_record(self.root, core.committed_records(self.root)[0])
        self.assertEqual(record['kind'], 'synthesis')
        self.assertNotIn('SYNTHETIC_SECRET', record['text'])

    def test_query_source_budgets_count_interrupted_attempts(self):
        manifest = core.read_manifest(self.root)
        manifest['protocol']['budgets'] = {'queries': 1, 'sources': 1}
        core.atomic_json(self.root / 'manifest.json', manifest)
        with patch.object(core, 'run_backend', return_value=({'results': []}, {'exit_code': 7})):
            core.discover(self.root, 'query', 'fixture', 'first')
        with patch.object(core, 'run_backend') as backend:
            with self.assertRaises(core.CorpusError) as error:
                core.discover(self.root, 'query', 'fixture', 'second')
            self.assertEqual(error.exception.code, 'budget-exhausted')
            backend.assert_not_called()
        decision = core.read_manifest(self.root)['runs'][0]['recipe']['stopping_decisions'][-1]
        self.assertEqual(decision['kind'], 'budget-exhausted')

    def test_manual_stop_blocks_live_work_and_rerun_clears_stop(self):
        with patch.object(core, 'run_backend', return_value=({'results': []}, {'exit_code': 0})):
            core.discover(self.root, 'query', 'fixture', 'first')
        original_run = core.read_manifest(self.root)['active_run']
        core.stop(self.root, 'Declared bounded search complete')
        with patch.object(core, 'run_backend') as backend:
            with self.assertRaises(core.CorpusError) as error:
                core.discover(self.root, 'query two', 'fixture', 'second')
            self.assertEqual(error.exception.code, 'run-stopped')
            with self.assertRaises(core.CorpusError):
                core.open_source(self.root, 'source-a', 'https://example.org/a', 'fixture')
            backend.assert_not_called()
        with patch.object(core, 'run_backend', return_value=({'results': []}, {'exit_code': 0})):
            result = core.rerun(self.root, original_run, 'fixture')
        self.assertNotEqual(result['run_id'], original_run)
        new = core.read_manifest(self.root)['runs'][-1]
        self.assertFalse(any(item['kind'] == 'manual-stop' for item in new['recipe']['stopping_decisions']))


if __name__ == '__main__':
    unittest.main()
