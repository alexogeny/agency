import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'Tools/research-corpus'

BACKEND = r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ['CORPUS_FIXTURE_LOG']).open('a') as log:
    log.write(json.dumps(args) + '\n')
changed = os.environ.get('CORPUS_FIXTURE_CHANGED') == '1'
if args[0] == 'search':
    print(json.dumps({'query': args[1], 'engine': 'federated', 'strategy': 'federated',
        'results': [{'title': 'Fixture source', 'url': 'https://example.test/article?id=paper',
                     'snippet': 'Discovery evidence only.'}],
        'attempts': [{'engine': 'fixture', 'outcome': 'searched', 'duration_ms': 1}]}))
elif args[0] == 'scrape':
    body = 'Updated evidence on uncertainty.' if changed else 'Retained evidence on uncertainty.'
    if os.environ.get('CORPUS_FIXTURE_ENCODED') == '1':
        body += (' https%3A%2F%2Fexample.test%2Fasset%3Fid%3Ddiagram%26sig%3DSYNTH_PERCENT'
                 r' https\u003a\u002f\u002fexample.test/asset?id=diagram\u0026sig=SYNTH_UNICODE')
    print(json.dumps({'title': 'Fixture source', 'url': args[1], 'canonicalUrl': args[1],
        'text': body, 'markdown': '# Fixture source\n\n' + body,
        'published': '24 Jun 2025', 'byline': 'Unverified extracted name',
        'links': ['https://example.test/asset?id=diagram&sig=synthetic-secret'],
        'access': {'state': 'public'}, 'quality': [],
        'provenance': {'byline': [{'source': 'rendered-dom', 'capture': 'fixture'}]},
        'truncated': {'text': False, 'markdown': False},
        'freshness': {'retrieval': 'live', 'retrieved_at': '2026-10-28T00:00:00Z',
                      'content_sha256': '1' * 64}}))
else:
    sys.exit('Unexpected backend operation')
'''


class ResearchCorpusIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.corpus = self.base / 'corpus'
        self.log = self.base / 'backend.ndjson'
        self.backend = self.base / 'backend'
        self.backend.write_text('#!' + sys.executable + '\n' + BACKEND)
        self.backend.chmod(0o700)
        self.environment = dict(os.environ, RESEARCH_CORPUS_WEB_COMMAND=str(self.backend),
                                PATH=str(ROOT / 'Tools') + os.pathsep + os.environ.get('PATH', ''),
                                CORPUS_FIXTURE_LOG=str(self.log), PYTHONDONTWRITEBYTECODE='1')
        self.protocol = self.base / 'protocol.json'
        self.protocol.write_text(json.dumps({
            'question': 'Fixture evidence', 'scope': 'example.test public pages',
            'source_classes': ['official'],
            'stopping_rule': 'one query and one opened source',
            'date_window': {'from': '2020-01-01', 'to': '2026-10-28'},
        }))

    def invoke(self, *arguments, expected=0, environment=None):
        result = subprocess.run([sys.executable, str(TOOL), *map(str, arguments)],
                                env=environment or self.environment, capture_output=True,
                                text=True, timeout=30)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def collect(self):
        self.invoke('init', self.corpus, '--protocol', self.protocol)
        self.invoke('discover', self.corpus, '--query', 'uncertainty site:example.test',
                    '--profile', 'fixture', '--operation-id', 'query-one')
        manifest = json.loads((self.corpus / 'manifest.json').read_text())
        self.assertEqual(len(manifest['sources']), 1)
        source_id = next(iter(manifest['sources']))
        self.invoke('open', self.corpus, '--source-id', source_id,
                    '--url', 'https://example.test/article?id=paper', '--profile', 'fixture')
        return source_id

    def test_complete_retained_workflow_relocates_and_reproduces_offline(self):
        self.collect()
        original = json.loads((self.corpus / 'manifest.json').read_text())
        self.assertEqual([r['kind'] for r in original['records']], ['discovery', 'source'])
        calls = self.log.read_bytes()
        database = self.base / 'generated' / 'index.sqlite'
        self.invoke('index', 'build', self.corpus, '--db', database)
        found = self.invoke('index', 'query', self.corpus, 'uncertainty', '--db', database)
        self.assertIn('example.test', json.dumps(found))
        audited = self.invoke('audit', self.corpus)
        self.assertNotIn('synthetic-secret', json.dumps(audited))
        relocated = self.base / 'relocated'
        shutil.copytree(self.corpus, relocated)
        self.backend.unlink()
        reproduced = self.base / 'reproduced'
        self.invoke('reproduce', relocated, '--offline', '--output', reproduced)
        self.assertEqual(self.log.read_bytes(), calls)
        for entry in original['records']:
            for relative in entry['paths'].values():
                self.assertEqual((relocated / relative).read_bytes(),
                                 (reproduced / relative).read_bytes())
        all_retained = '\n'.join(p.read_text() for p in relocated.rglob('*')
                                 if p.is_file() and p.suffix in {'.json', '.txt', '.md'})
        self.assertNotIn('synthetic-secret', all_retained)
        self.assertIn('id=paper', all_retained)

    def test_same_discovery_operation_does_not_repeat_backend(self):
        self.collect()
        calls = self.log.read_bytes()
        self.invoke('discover', self.corpus, '--query', 'uncertainty site:example.test',
                    '--profile', 'fixture', '--operation-id', 'query-one')
        self.assertEqual(self.log.read_bytes(), calls)

    def test_missing_artifact_is_rejected_without_live_repair(self):
        self.collect()
        manifest = json.loads((self.corpus / 'manifest.json').read_text())
        missing = self.corpus / manifest['records'][-1]['paths']['markdown']
        missing.unlink()
        calls = self.log.read_bytes()
        result = subprocess.run([sys.executable, str(TOOL), 'audit', str(self.corpus)],
                                env=self.environment, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.log.read_bytes(), calls)

    def test_envelope_keeps_source_access_and_unverified_bibliography(self):
        self.collect()
        manifest = json.loads((self.corpus / 'manifest.json').read_text())
        record = json.loads((self.corpus / manifest['records'][-1]['paths']['json']).read_text())
        self.assertEqual(record['retrieval']['access'], 'public')
        self.assertEqual(record['bibliography']['raw_date'], '24 Jun 2025')
        self.assertEqual(record['bibliography']['extracted_byline'], 'Unverified extracted name')
        self.assertIsNone(record['bibliography']['verified_authors'])
        self.assertEqual(record['extraction']['coverage'], 'unknown')
        self.assertEqual(record['identities']['source_evidence_sha256'], '1' * 64)
        self.assertGreater(record['transformations'][0]['changed_fields'], 0)
        recipe = manifest['runs'][0]['recipe']['queries'][0]
        self.assertEqual(recipe['absolute_date_window'],
                         {'from': '2020-01-01', 'to': '2026-10-28'})

    def test_live_rerun_keeps_prior_run_and_reports_changed_evidence(self):
        self.collect()
        old = json.loads((self.corpus / 'manifest.json').read_text())
        old_bytes = {p: (self.corpus / p).read_bytes()
                     for entry in old['records'] for p in entry['paths'].values()}
        changed = dict(self.environment, CORPUS_FIXTURE_CHANGED='1')
        result = self.invoke('rerun', self.corpus, '--from', old['active_run'],
                             '--profile', 'fixture', environment=changed)
        self.assertNotEqual(result['run_id'], old['active_run'])
        comparison = self.invoke('compare', self.corpus, '--old', old['active_run'],
                                 '--new', result['run_id'])
        self.assertIn('changed', json.dumps(comparison).lower())
        for relative, data in old_bytes.items():
            self.assertEqual((self.corpus / relative).read_bytes(), data)
        manifest = json.loads((self.corpus / 'manifest.json').read_text())
        newer = [r for r in manifest['records'] if r['run_id'] == result['run_id']]
        self.assertEqual([r['kind'] for r in newer], ['discovery', 'source'])
        source = json.loads((self.corpus / newer[-1]['paths']['json']).read_text())
        self.assertIn('Updated evidence', source['text'])

    def test_encoded_backend_urls_are_sanitized_before_every_export(self):
        self.environment['CORPUS_FIXTURE_ENCODED'] = '1'
        self.collect()
        manifest = json.loads((self.corpus / 'manifest.json').read_text())
        for entry in manifest['records']:
            for relative in entry['paths'].values():
                text = (self.corpus / relative).read_text()
                self.assertNotIn('SYNTH_PERCENT', text)
                self.assertNotIn('SYNTH_UNICODE', text)
        self.assertIn('id=diagram', (self.corpus / manifest['records'][-1]['paths']['text']).read_text())

    def mcp(self, command):
        request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                   'params': {'name': 'corpus', 'arguments': {'command': list(map(str, command))}}}
        result = subprocess.run(['bun', str(ROOT / 'Tools/web-research-mcp')],
                                input=json.dumps(request) + '\n', env=self.environment,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)['result']

    def test_cli_and_mcp_share_pending_gate_and_resume(self):
        self.invoke('init', self.corpus, '--protocol', self.protocol)
        crash = dict(self.environment, RESEARCH_CORPUS_CRASH_AT='text')
        self.invoke('discover', self.corpus, '--query', 'uncertainty', '--profile', 'fixture',
                    '--operation-id', 'interrupted', environment=crash, expected=1)
        calls = self.log.read_bytes()
        refused = self.mcp(['discover', self.corpus, '--query', 'next query', '--profile',
                            'fixture', '--operation-id', 'next'])
        self.assertTrue(refused['isError'])
        self.assertEqual(self.log.read_bytes(), calls)
        self.invoke('resume', self.corpus)
        resumed = self.mcp(['discover', self.corpus, '--query', 'uncertainty', '--profile',
                            'fixture', '--operation-id', 'interrupted'])
        self.assertFalse(resumed.get('isError', False))
        self.assertEqual(self.log.read_bytes(), calls)

    def test_owned_profile_lifecycle_uses_private_state_and_exact_temp_targets(self):
        self.invoke('init', self.corpus, '--protocol', self.protocol)
        environment = dict(self.environment,
                           RESEARCH_CORPUS_WEB_COMMAND=str(ROOT / 'Tools/web-research'),
                           WEB_RESEARCH_DATA_DIR=str(self.base / 'browser'),
                           XDG_STATE_HOME=str(self.base / 'state'))
        arguments = ['--owner-execution', 'integration-fixture',
                     '--authorization', 'authorized-temporary-fixture-only']
        created = self.invoke('profiles', 'create', self.corpus, *arguments,
                              '--purpose', 'Temporary offline integration fixture',
                              environment=environment)
        foreign = self.base / 'browser' / 'profiles' / 'unrelated'
        foreign.mkdir()
        (foreign / 'keep').write_text('preserve')
        self.invoke('profiles', 'close', self.corpus, *arguments, environment=environment)
        receipt = self.base / 'cleanup.json'
        self.invoke('profiles', 'cleanup', self.corpus, *arguments, '--receipt', receipt,
                    environment=environment)
        retained = json.loads(receipt.read_text())
        self.assertEqual(retained['outcome'], 'removed')
        self.assertTrue(retained['postcheck']['profile_absent'])
        self.assertTrue(retained['postcheck']['metadata_absent'])
        self.assertTrue((foreign / 'keep').is_file())
        self.assertFalse((self.base / 'browser' / 'profiles' / created['profile']).exists())
        self.assertFalse(any('nonce' in p.name for p in self.corpus.rglob('*')))
        replacement = self.invoke('profiles', 'create', self.corpus, *arguments,
                                  '--purpose', 'New temporary profile for a later run',
                                  environment=environment)
        self.assertNotEqual(replacement['profile'], created['profile'])
        self.invoke('profiles', 'cleanup', self.corpus, *arguments,
                    '--receipt', self.base / 'replacement-cleanup.json', environment=environment)

    def test_documented_query_budget_is_enforced_before_a_second_search(self):
        protocol = json.loads(self.protocol.read_text())
        protocol['budget'] = {'queries': 1, 'sources': 1}
        self.protocol.write_text(json.dumps(protocol))
        self.collect()
        calls = self.log.read_bytes()
        self.invoke('discover', self.corpus, '--query', 'another query', '--profile',
                    'fixture', '--operation-id', 'over-budget', expected=1)
        self.assertEqual(self.log.read_bytes(), calls)


if __name__ == '__main__':
    unittest.main()
