"""Offline evidence-boundary and exact disposable-profile regressions."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'Tools/web-research'


class CorpusEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {**os.environ, 'WEB_RESEARCH_DATA_DIR': str(self.root / 'data')}

    def run_tool(self, *args, payload=None):
        return subprocess.run(['bun', str(TOOL), *args], input=json.dumps(payload) if payload else None,
                              env=self.env, text=True, capture_output=True, timeout=15)

    def create(self):
        auth = {'reference': 'synthetic-authorization', 'owner_execution': 'synthetic-execution', 'disposable': True}
        result = self.run_tool('profile-create', payload={'schema': 'agency/owned-profile-request/1',
            'owner_execution': 'synthetic-execution', 'purpose': 'offline fixture', 'mode': 'persistent', 'authorization': auth})
        self.assertEqual(result.returncode, 0, result.stderr)
        handle = json.loads(result.stdout)
        return handle, {'handle': handle, 'owner_execution': 'synthetic-execution', 'authorization': auth}

    def test_index_only_missing_is_typed_read_only(self):
        result = self.run_tool('scrape', 'https://example.test/doc', '--format', 'json', '--from-index')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'index-unavailable')
        self.assertFalse((self.root / 'data').exists())

    def test_exact_owned_cleanup_and_nonce_authorization_guards(self):
        handle, request = self.create()
        profile = Path(handle['canonical_path'])
        other = profile.parent / 'unrelated'
        other.mkdir()
        (other / 'keep').write_text('keep')
        bad = {**request, 'handle': {**handle, 'nonce': 'incorrect'}}
        result = self.run_tool('profile-cleanup', payload=bad)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'profile-identity-mismatch')
        self.assertTrue(profile.exists())
        bad = {**request, 'authorization': {**request['authorization'], 'reference': 'other'}}
        self.assertNotEqual(self.run_tool('profile-cleanup', payload=bad).returncode, 0)
        result = self.run_tool('profile-close', payload=request)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_tool('profile-cleanup', payload=request)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt['outcome'], 'removed')
        self.assertTrue(receipt['postcheck']['profile_absent'])
        self.assertTrue(receipt['postcheck']['metadata_absent'])
        self.assertTrue((other / 'keep').exists())

    def test_owned_cleanup_refuses_active_lock_and_symlink(self):
        handle, request = self.create()
        profile = Path(handle['canonical_path'])
        lock = Path(str(profile) + '.lock')
        lock.write_text(str(os.getpid()))
        result = self.run_tool('profile-cleanup', payload=request)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'profile-active')
        lock.unlink()
        profile.rmdir()
        destination = self.root / 'protected'
        destination.mkdir()
        profile.symlink_to(destination, target_is_directory=True)
        result = self.run_tool('profile-cleanup', payload=request)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(destination.exists())

    def test_owned_cleanup_refuses_replacement_directory_with_copied_metadata(self):
        handle, request = self.create()
        selected = Path(handle['canonical_path'])
        original = selected.with_name(selected.name + '-original')
        selected.rename(original)
        selected.mkdir()
        (selected / 'preserve').write_text('Different directory at the same name')
        result = self.run_tool('profile-cleanup', payload=request)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'profile-identity-mismatch')
        self.assertTrue((selected / 'preserve').is_file())
        self.assertTrue(original.is_dir())

    def test_real_worker_protocol_closes_valid_owned_handle(self):
        _, request = self.create()
        frame = {'args': ['profile-close'], 'input': json.dumps(request)}
        result = subprocess.run(['bun', str(TOOL), 'worker'], input=json.dumps(frame) + '\n',
                                env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertNotIn('error', response)
        self.assertTrue(response['result']['closed'])

    def test_recursive_sanitizer_encoded_embedded_fields_and_selectors(self):
        module = ROOT / 'Tools/web_research_evidence.ts'
        fixture = {'secret': {'value': 'SYNTH_OBJECT'}, 'api_token': ['SYNTH_ARRAY'],
                   'nested': [{'url': 'https://example.test/doc?id=stable&sig=SYNTH_SIG',
            'body': '<a href="https://example.test/doc?id=stable&amp;signature=SYNTH_HTML">x</a> '
                    r'https:\/\/example.test\/doc?id=stable\u0026token=SYNTH_ESC '
                    'https%3A%2F%2Fexample.test%2Fdoc%3Fid%3Dstable%26sig%3DSYNTH_PERCENT',
            'authorization': 'SYNTH_FIELD',
            'other': 'https%253A%252F%252Fexample.test%252Fdoc%253Fid%253Dstable%2526sig%253DSYNTH_DOUBLE '
                     'https&#58;&#47;&#47;example.test/doc?id=stable&amp;sig=SYNTH_ENTITY'}]}
        script = self.root / 'sanitize.ts'
        script.write_text('import { sanitizeEvidence } from ' + json.dumps(str(module)) + ';\n'
                          'console.log(JSON.stringify(sanitizeEvidence(JSON.parse(await Bun.stdin.text()))));\n')
        result = subprocess.run(['bun', str(script)], input=json.dumps(fixture), text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertNotIn('SYNTH_', result.stdout)
        self.assertIn('id=stable', result.stdout)
        self.assertEqual(value['redaction']['version'], 'agency/evidence-sanitizer/1')
        self.assertGreaterEqual(value['redaction']['count'], 5)

    def test_index_only_preserves_evidence_and_never_migrates_legacy(self):
        source = TOOL.read_text().split('\nconst originalConsoleLog =', 1)[0]
        script = self.root / 'cache-fixture.ts'
        script.write_text(source + r"""
const page = {title:'Synthetic',url:'https://example.test/doc',canonicalUrl:'https://example.test/doc',
  published:'',byline:'',text:'abstract https://example.test/asset?id=stable&sig=SYNTH_CACHE',
  markdown:'abstract',html:'',links:[], access:{state:'soft-login'},quality:[{code:'abstract-only',fields:['text'],observation:'abstract'}],
  provenance:{text:[{source:'rendered-dom',capture:'fixture'}]},truncated:{text:true,markdown:false,html:false,links:false}};
indexPage(page, "https://example.test/doc?id=stable&password=SYNTH_ALIAS");
""")
        result = subprocess.run(['bun', str(script)], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        db_path = self.root / 'data/index.sqlite'
        result = self.run_tool('scrape', 'https://example.test/doc', '--format', 'json', '--from-index')
        self.assertEqual(result.returncode, 0, result.stderr)
        page = json.loads(result.stdout)
        self.assertEqual(page['access']['state'], 'soft-login')
        self.assertTrue(page['truncated']['text'])
        self.assertEqual(page['quality'][0]['code'], 'abstract-only')
        self.assertEqual(page['coverage'], 'unknown')
        self.assertNotIn('SYNTH_CACHE', result.stdout)
        self.assertGreaterEqual(page['redaction']['count'], 1)
        with closing(sqlite3.connect(db_path)) as connection, connection:
            row = connection.execute('select text from pages').fetchone()
            self.assertNotIn('SYNTH_CACHE', row[0])
            aliases = connection.execute('select request_url from page_aliases').fetchall()
            self.assertNotIn('SYNTH_ALIAS', repr(aliases))
            connection.execute("update pages set refresh_after='2000-01-01T00:00:00Z',change_likelihood='high'")
        before = db_path.read_bytes()
        result = self.run_tool('scrape', 'https://example.test/doc', '--format', 'json', '--from-index')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'index-stale')
        self.assertEqual(db_path.read_bytes(), before)
        with closing(sqlite3.connect(db_path)) as connection, connection:
            connection.execute("update pages set refresh_after='2999-01-01T00:00:00Z',evidence_json='{}'")
        before = db_path.read_bytes()
        result = self.run_tool('scrape', 'https://example.test/doc', '--format', 'json', '--from-index')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'index-legacy')
        self.assertEqual(db_path.read_bytes(), before)
        with closing(sqlite3.connect(db_path)) as connection, connection:
            connection.execute('alter table pages drop column evidence_json')
        before = db_path.read_bytes()
        result = self.run_tool('scrape', 'https://example.test/doc', '--format', 'json', '--from-index')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'index-legacy')
        self.assertEqual(db_path.read_bytes(), before)

    def test_worker_closes_only_exact_validated_owned_lease(self):
        handle, request = self.create()
        source = TOOL.read_text().split('\nconst originalConsoleLog =', 1)[0]
        script = self.root / 'worker-close.ts'
        script.write_text(source + '\nconst request = ' + json.dumps(request) + ';\n' + r"""
workerMode = true;
let stopped = 0;
stopBrowser = async () => { stopped++; };
workerBrowser = {key:'fixture',browser:{root:request.handle.canonical_path}} as any;
workerInput = JSON.stringify({...request,handle:{...request.handle,nonce:'incorrect'}});
try {await commandOwnedProfile('profile-close',[]);throw new Error('forged handle accepted');}
catch(error) {if(String(error).includes('forged handle accepted')) throw error;}
if(stopped !== 0 || !workerBrowser) throw new Error('forged identity closed a lease');
workerInput = JSON.stringify(request);
await commandOwnedProfile('profile-close',[]);
if(stopped !== 1 || workerBrowser) throw new Error('exact owned lease was not closed');
""")
        result = subprocess.run(['bun', str(script)], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['browser_released'])

    def test_mcp_corpus_forwards_authorization_before_backend_close(self):
        server = self.root / 'web-research-mcp'
        server.write_bytes((ROOT / 'Tools/web-research-mcp').read_bytes())
        (self.root / 'web_research_evidence.ts').write_bytes((ROOT / 'Tools/web_research_evidence.ts').read_bytes())
        corpus = self.root / 'research-corpus'
        backend = self.root / 'web-research'
        corpus.write_text("#!/usr/bin/env python3\nimport json,sys\n"
                          "print(json.dumps({'error':{'code':'cleanup-not-authorized'},'received':sys.argv[1:]}))\n"
                          "sys.exit(1)\n")
        backend.write_text("#!/usr/bin/env python3\nfrom pathlib import Path\nimport os\n"
                           "Path(os.environ['PROFILE_BACKEND_SENTINEL']).write_text('called')\n"
                           "print('{}')\n")
        corpus.chmod(0o700)
        backend.chmod(0o700)
        sentinel = self.root / 'backend-called'
        env = {**self.env, 'WEB_RESEARCH_COMMAND': str(backend), 'PROFILE_BACKEND_SENTINEL': str(sentinel)}
        command = ['profiles', 'cleanup', 'synthetic', '--owner-execution', 'WRONG', '--authorization', 'WRONG']
        frame = {'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'corpus','arguments':{'command':command}}}
        result = subprocess.run(['bun', str(server)], input=json.dumps(frame)+'\n', env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['result']['isError'])
        self.assertFalse(sentinel.exists(), 'Invalid caller authorization must not invoke backend close')
        # Capture the exact parser request independently of the rejected result.
        log = self.root / 'arguments.json'
        corpus.write_text("#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\n"
                          + 'Path(' + repr(str(log)) + ").write_text(json.dumps({'argv':sys.argv[1:],'input':json.load(sys.stdin)}))\n"
                          + "print('{}')\nsys.exit(1)\n")
        result = subprocess.run(['bun', str(server)], input=json.dumps(frame)+'\n', env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(json.loads(log.read_text()), {'argv': ['--mcp-plan'], 'input': {'command': command}})

    def test_mcp_corpus_uses_literal_vector_and_hides_private_handles(self):
        server = self.root / 'web-research-mcp'
        server.write_bytes((ROOT / 'Tools/web-research-mcp').read_bytes())
        (self.root / 'web_research_evidence.ts').write_bytes((ROOT / 'Tools/web_research_evidence.ts').read_bytes())
        corpus = self.root / 'research-corpus'
        corpus.write_text("#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps({'command':sys.argv[1:]}))\n")
        corpus.chmod(0o700)
        sentinel = self.root / 'shell-ran'
        command = ['index', 'query', 'synthetic', '$(touch ' + str(sentinel) + ')']
        frames = [{'jsonrpc':'2.0','id':1,'method':'tools/list'},
                  {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'corpus','arguments':{'command':command}}},
                  {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'corpus','arguments':{'command':['profiles','handles','synthetic']}}}]
        result = subprocess.run(['bun', str(server)], input=''.join(json.dumps(frame)+'\n' for frame in frames),
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        messages = [json.loads(line)['result'] for line in result.stdout.splitlines()]
        self.assertIn('corpus', [tool['name'] for tool in messages[0]['tools']])
        self.assertEqual(messages[1]['structuredContent']['command'], command)
        self.assertTrue(messages[2]['isError'])
        self.assertFalse(sentinel.exists())

    def test_owned_cleanup_retains_partial_receipt(self):
        handle, request = self.create()
        script = self.root / 'partial.py'
        script.write_text('import sys,json\nfrom pathlib import Path\nsys.path.insert(0,' + repr(str(ROOT / 'Tools')) + ')\n'
                          + 'import web_research_owned_profiles as profiles\nrequest=' + repr(request) + '\n'
                          + "original=Path.unlink\ndef unlink(self,*args,**kwargs):\n"
                          + "    if str(self).endswith('.agency.json'): raise OSError('synthetic failure')\n"
                          + "    return original(self,*args,**kwargs)\nPath.unlink=unlink\n"
                          + 'print(json.dumps(profiles.operate("profile-cleanup",request,Path(' + repr(str(self.root/'data')) + '))))\n')
        result = subprocess.run(['python3', str(script)], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt['outcome'], 'partial')
        self.assertTrue(receipt['postcheck']['profile_absent'])
        self.assertFalse(receipt['postcheck']['metadata_absent'])
        self.assertEqual(receipt['targets'][-1]['result'], 'failed')

    def test_character_continuation_covers_each_retained_character(self):
        source = (ROOT / 'Tools/web-research-mcp').read_text().split('\nlet inputBuffer = "";', 1)[0]
        script = self.root / 'continuation.ts'
        script.write_text(source + r"""
const page = addPageReference({title:'Long source',url:'https://example.test/long',markdown:'x'.repeat(10000)+'\ntail'});
loadPages = async () => [page];
let request:any = {ref_id:page.ref_id};
const delivered = [0,0];
let rounds = 0;
while (request) {
  const result = await callRun({open:[request],response_length:'short'});
  const delivery = result.structuredContent.results[0].delivery;
  for (const range of delivery.delivered_ranges) {
    if (range.character_start !== delivered[range.line-1]) throw new Error('continuation skipped/repeated source characters');
    delivered[range.line-1] = range.character_end;
  }
  request = delivery.continuation;
  if (++rounds > 10) throw new Error('continuation did not progress');
}
if(delivered[0] !== 10000 || delivered[1] !== 4) throw new Error('continuation lost source evidence');
console.log(JSON.stringify({rounds,delivered}));
""")
        result = subprocess.run(['bun', str(script)], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(json.loads(result.stdout)['rounds'], 1)

    def test_final_mcp_clipping_reports_omitted_body_and_continuation(self):
        source = (ROOT / 'Tools/web-research-mcp').read_text().split('\nlet inputBuffer = "";', 1)[0]
        script = self.root / 'mcp-fixture.ts'
        script.write_text(source + r"""
const pages = [addPageReference({title:'First',url:'https://example.test/first',markdown:'x'.repeat(20000)}),
               addPageReference({title:'Second',url:'https://example.test/second',markdown:'second retained body'})];
loadPages = async values => values.map(value => pages.find(p => p.ref_id === value));
const result = await callRun({open:pages.map(p=>({ref_id:p.ref_id})),response_length:'short'});
console.log(JSON.stringify(result));
""")
        result = subprocess.run(['bun', str(script)], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        records = json.loads(result.stdout)['structuredContent']['results']
        self.assertTrue(records[0]['delivery']['evidence_text_present'])
        self.assertTrue(records[0]['delivery']['transport_truncated'])
        self.assertGreater(records[0]['delivery']['continuation']['character_offset'], 0)
        self.assertFalse(records[1]['delivery']['evidence_text_present'])
        self.assertEqual(records[1]['citation']['line_start'], 0)
        self.assertEqual(records[1]['citation']['line_end'], 0)


if __name__ == '__main__':
    unittest.main()
