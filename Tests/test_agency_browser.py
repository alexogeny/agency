import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('browser', ROOT / 'Tools/agency_browser.py')
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.waits = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


SNAPSHOT = '''- main [ref=e1]:
  - link "Weekly modules" [ref=e2] [cursor=pointer]:
    - /url: /courses/1/modules
  - 'link "Assessment 2: Interview" [ref=f3e4] [cursor=pointer]':
    - /url: /courses/1/pages/interview
  - button "Delete submission" [ref=e8] [cursor=pointer]
'''


class BrowserTests(unittest.TestCase):
    def test_symlinked_cli_resolves_contracts_without_repository_caches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Tools').mkdir()
            (root / 'Skills/browser-workflow').mkdir(parents=True)
            for filename in ('agency-browser', 'agency_browser.py', 'agency_decisions.py'):
                shutil.copy2(ROOT / 'Tools' / filename, root / 'Tools' / filename)
            shutil.copy2(ROOT / 'Skills/browser-workflow/decisions.json',
                         root / 'Skills/browser-workflow/decisions.json')
            executable = root / 'installed-browser'
            executable.symlink_to(root / 'Tools/agency-browser')
            packet = b.prepare_packet(SNAPSHOT, 'https://example.com/courses/1', 'Read', ['e2'], 'Navigation')
            (root / 'packet.json').write_text(json.dumps(packet))
            env = {k: v for k, v in os.environ.items()
                   if k not in ('PYTHONDONTWRITEBYTECODE', 'PYTHONPYCACHEPREFIX')}
            result = subprocess.run([str(executable), 'choose', '--packet', str(root / 'packet.json'),
                                     '--dry-run'], capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            request = json.loads(result.stdout)
            self.assertEqual(set(request['questions']['decision']['criteria']), {'e2', 'done', 'unsure'})
            self.assertFalse(list(root.rglob('__pycache__')))

    def test_download_completion_ignores_existing_and_partial_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);c=Clock()
            old=root/'report.pdf';old.write_bytes(b'old')
            before=b.download_state(root,'report.pdf')
            partial=root/'report (1).pdf.crdownload';partial.write_bytes(b'new')
            def sleep(seconds):
                c.sleep(seconds)
                partial.rename(root/'report (1).pdf')
            completed=b.wait_for_download(root,'report.pdf',3,before,timeout=5,clock=c.time,sleep=sleep)
            self.assertEqual(completed.name,'report (1).pdf')
            self.assertEqual(old.read_bytes(),b'old')
            with self.assertRaises(b.Deferred):
                b.wait_for_download(root,'report.pdf',9,b.download_state(root,'report.pdf'),timeout=2,clock=c.time,sleep=c.sleep)

    def test_download_is_paced_until_completion_and_verified_in_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);incoming=root/'incoming';incoming.mkdir();c=Clock()
            client=b.MCPClient('http://localhost:8937/mcp')
            pacer=b.Pacer(root/'pacing',clock=c.time,sleep=c.sleep,jitter=0)
            def downloaded(tool,args):
                (incoming/'material.zip').write_bytes(b'zip')
                return {'content':[{'type':'text','text':'### Result\n{"started":true}'}]}
            with patch.object(client,'call',side_effect=downloaded) as call:
                out=client.download('https://example.com/files/1',root/'material.zip',incoming,'material.zip',3,pacer)
                self.assertEqual(call.call_count,1)
                self.assertEqual(out['result']['bytes'],3)
                self.assertEqual((root/'material.zip').read_bytes(),b'zip')
                self.assertFalse((incoming/'material.zip').exists())
            (root/'exists.zip').write_bytes(b'previous')
            with self.assertRaises(b.BrowserError):
                client.download('https://example.com/files/1',root/'exists.zip',incoming,'material.zip',3,pacer)

    def test_download_rejects_invalid_limits_before_navigation_and_preserves_racing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);incoming=root/'incoming';incoming.mkdir();c=Clock()
            client=b.MCPClient('http://localhost:8937/mcp')
            pacer=b.Pacer(root/'pacing',clock=c.time,sleep=c.sleep,jitter=0)
            for size,timeout in ((-1,5),(3,0),(True,5)):
                with patch.object(client,'call',side_effect=AssertionError('invalid request sent')):
                    with self.assertRaises(b.BrowserError):
                        client.download('https://example.com/files/1',root/'result.zip',incoming,'result.zip',size,pacer,timeout)
            def completed(tool,args):
                (incoming/'result.zip').write_bytes(b'new')
                (root/'result.zip').write_bytes(b'previous')
                return {'content':[]}
            with patch.object(client,'call',side_effect=completed), self.assertRaises(b.BrowserError):
                client.download('https://example.com/files/1',root/'result.zip',incoming,'result.zip',3,pacer)
            self.assertEqual((root/'result.zip').read_bytes(),b'previous')

    def test_packet_contains_only_explicit_reviewed_refs(self):
        p = b.prepare_packet(SNAPSHOT, 'https://example.com/courses/1', 'Read interview instructions',
                             ['e2', 'f3e4'], 'Course navigation only.')
        self.assertEqual(set(p['state']['candidates']), {'e2', 'f3e4'})
        self.assertNotIn('Delete', json.dumps(p['state']))
        self.assertEqual(p['targets']['f3e4']['url'], 'https://example.com/courses/1/pages/interview')
        self.assertEqual(p['state']['goal'], 'Read interview instructions')

    def test_malformed_refs_are_rejected_with_a_browser_error(self):
        for refs in ([{}], [1], ["e2", []]):
            with self.subTest(refs=refs), self.assertRaises(b.BrowserError):
                b.prepare_packet(SNAPSHOT, 'https://example.com', 'Read', refs, 'Navigation')

    def test_missing_duplicate_or_disabled_refs_are_rejected(self):
        for refs in (['e99'], ['e2', 'e2'], []):
            with self.subTest(refs=refs), self.assertRaises(b.BrowserError):
                b.prepare_packet(SNAPSHOT, 'https://example.com', 'Read', refs, 'Navigation')
        with self.assertRaises(b.BrowserError):
            b.prepare_packet(SNAPSHOT.replace('[ref=e2]', '[disabled] [ref=e2]'),
                             'https://example.com', 'Read', ['e2'], 'Navigation')

    def test_selection_is_bound_to_snapshot_and_never_turns_unsure_into_a_click(self):
        p = b.prepare_packet(SNAPSHOT, 'https://example.com/courses/1', 'Read', ['e2'], 'Navigation')
        choice = b.bind_selection(p, {'decision': 'e2', 'latency_ms': 125, 'advisory': True})
        self.assertEqual(b.validate_selection(choice, p, SNAPSHOT, p['page_url'])['target'], 'e2')
        for decision in ('unsure', 'done'):
            result = b.bind_selection(p, {'decision': decision, 'advisory': True})
            self.assertIsNone(result['target'])
            with self.assertRaises(b.BrowserError):
                b.validate_selection(result, p, SNAPSHOT, p['page_url'])
        for current, url in ((SNAPSHOT + '\n- button "New" [ref=e9]', p['page_url']),
                             (SNAPSHOT, 'https://other.example')):
            with self.assertRaises(b.BrowserError):
                b.validate_selection(choice, p, current, url)
        with self.assertRaises(b.BrowserError):
            b.bind_selection(p, {'decision': 'e8'})

    def test_binding_rejects_a_modified_target(self):
        p = b.prepare_packet(SNAPSHOT, 'https://example.com/courses/1', 'Read', ['e2'], 'Navigation')
        choice = b.bind_selection(p, {'decision': 'e2', 'advisory': True})
        choice['target'] = 'e8'
        with self.assertRaises(b.BrowserError):
            b.validate_selection(choice, p, SNAPSHOT, p['page_url'])

    def test_origin_ignores_paths_queries_and_fragments_and_normalizes_host(self):
        self.assertEqual(b.origin('https://EXAMPLE.com:443/a?secret=hidden#x'), 'https://example.com')
        for url in ('file:///tmp/a', 'https://user:pass@example.com', 'javascript:alert(1)'):
            with self.subTest(url=url), self.assertRaises(b.BrowserError):
                b.origin(url)

    def test_minimum_gap_and_jitter_survive_new_pacer_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            c = Clock()
            def pacer():
                return b.Pacer(Path(directory), minimum=2, jitter=3,
                               clock=c.time, sleep=c.sleep, random=lambda a,z: 1.25)
            hits = []
            for url in ('https://example.com/a', 'https://example.com/b', 'https://example.com/c'):
                pacer().run(url, lambda: hits.append(c.now))
            self.assertEqual(hits, [1000, 1003.25, 1006.5])
            self.assertEqual(c.waits, [3.25, 3.25])
            self.assertEqual(pacer().run('https://cdn.example/a', lambda: c.now)['wait_seconds'], 0)

    def test_shared_host_is_single_flight_and_failure_does_not_replay_action(self):
        with tempfile.TemporaryDirectory() as directory:
            c = Clock()
            p = b.Pacer(Path(directory), clock=c.time, sleep=c.sleep, random=lambda a,z: 0)
            other = b.Pacer(Path(directory), clock=c.time, sleep=c.sleep, random=lambda a,z: 0)
            def operation():
                with self.assertRaises(b.Deferred):
                    other.run('https://example.com', lambda: self.fail('overlapping operation ran'))
                raise b.ServiceError(429, '120')
            with self.assertRaises(b.ServiceError):
                p.run('https://example.com', operation)
            with self.assertRaises(b.Deferred):
                other.run('https://example.com', lambda: self.fail('cooldown was ignored'))
            self.assertEqual(c.waits, [])
            c.now += 120
            other.run('https://example.com', lambda: None)

    def test_503_backoff_is_exponential_and_success_resets_it(self):
        with tempfile.TemporaryDirectory() as directory:
            c = Clock()
            p = b.Pacer(Path(directory), minimum=2, jitter=0, backoff=5,
                        clock=c.time, sleep=c.sleep, random=lambda a,z: 0)
            def failed():
                raise b.ServiceError(503)
            for _ in range(2):
                with self.assertRaises(b.ServiceError):
                    p.run('https://example.com', failed)
            p.run('https://example.com', lambda: None)
            p.run('https://example.com', lambda: None)
            self.assertEqual(c.waits, [5, 10, 2])

    def test_retry_after_date_is_honored_and_invalid_values_use_backoff(self):
        self.assertEqual(b.retry_after('Thu, 01 Jan 1970 00:18:40 GMT', 1000), 120)
        self.assertEqual(b.retry_after('15', 1000), 15)
        self.assertIsNone(b.retry_after('bad', 1000))
        self.assertIsNone(b.retry_after('-2', 1000))
        self.assertIsNone(b.retry_after('9'*1000, 1000))

    def test_fetch_json_reports_hosted_rate_limit_to_pacer_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            c = Clock()
            pacer = b.Pacer(Path(directory), clock=c.time, sleep=c.sleep)
            client = b.MCPClient('http://localhost:8937/mcp')
            response = {'content':[{'type':'text','text':'### Result\n'+json.dumps({
                'status':429,'retry_after':'120','link':None,'data':{'error':'slow down'}})}]}
            with patch.object(client,'call',return_value=response) as call:
                with self.assertRaises(b.ServiceError):
                    client.fetch_json('https://example.com/api/course/1',pacer,'https://example.com/api/course/')
                self.assertEqual(call.call_count,1)
                with self.assertRaises(b.Deferred):
                    pacer.run('https://example.com',lambda:self.fail('cooldown lost'))
            with self.assertRaises(b.BrowserError):
                client.fetch_json('https://other.example/api/course/1',pacer,'https://example.com/api/course/')
            for path in ('../users','%2e%2e/users','x%2f..%2f..%2fusers','x\\..\\users'):
                fresh=b.Pacer(Path(directory)/'fresh',clock=c.time,sleep=c.sleep)
                with self.subTest(path=path), patch.object(client,'call',side_effect=AssertionError('out-of-scope request sent')):
                    with self.assertRaises(b.BrowserError):
                        client.fetch_json('https://example.com/api/course/'+path,fresh,'https://example.com/api/course/')

    def test_snapshot_file_is_resolved_inside_explicit_server_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'page.yml').write_text(SNAPSHOT)
            response={'content':[{'type':'text','text':'### Page\n- Page URL: https://example.com/courses/1\n### Snapshot\n- [Snapshot](page.yml)'}]}
            self.assertEqual(b.read_snapshot(response,root),(SNAPSHOT,'https://example.com/courses/1'))
            response['content'][0]['text']=response['content'][0]['text'].replace('page.yml','../private.yml')
            with self.assertRaises(b.BrowserError):
                b.read_snapshot(response,root)

    def test_click_reobserves_and_never_acts_on_a_stale_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            c=Clock()
            pacer=b.Pacer(Path(directory),clock=c.time,sleep=c.sleep,jitter=0)
            client=b.MCPClient('http://localhost:8937/mcp')
            packet=b.prepare_packet(SNAPSHOT,'https://example.com/courses/1','Read',['e2'],'Navigation')
            selection=b.bind_selection(packet,{'decision':'e2','advisory':True})
            response={'content':[{'type':'text','text':'### Page\n- Page URL: '+packet['page_url']+'\n### Snapshot\n```yaml\n'+SNAPSHOT+'```'}]}
            with patch.object(client,'call',return_value=response) as call:
                client.click(selection,packet,Path(directory),pacer)
                self.assertEqual([c.args[0] for c in call.call_args_list],['browser_snapshot','browser_click'])
                self.assertEqual(call.call_args_list[1].args[1]['target'],'e2')
            response['content'][0]['text']=response['content'][0]['text'].replace('Weekly modules','Different modules')
            with patch.object(client,'call',return_value=response) as call:
                with self.assertRaises(b.BrowserError):
                    client.click(selection,packet,Path(directory),pacer)
                self.assertEqual(call.call_count,1)

    def test_operation_errors_still_reserve_a_gap_and_do_not_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            c = Clock()
            p = b.Pacer(Path(directory), minimum=2, jitter=0, clock=c.time, sleep=c.sleep)
            calls = []
            def failed():
                calls.append(c.now)
                raise RuntimeError('failure')
            with self.assertRaises(RuntimeError):
                p.run('https://example.com', failed)
            p.run('https://example.com', lambda: calls.append(c.now))
            self.assertEqual(calls, [1000, 1002])

    def test_pacing_parameters_are_finite_and_have_safe_lower_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            for options in ({'minimum':0}, {'jitter':-1}, {'minimum':float('nan')}, {'backoff':0}):
                with self.subTest(options=options), self.assertRaises(b.BrowserError):
                    b.Pacer(Path(directory), **options)

    def test_sse_parsing_joins_multiline_data_and_matches_id(self):
        raw = b'event: message\ndata: {"jsonrpc":"2.0",\ndata: "id":3,"result":{"ok":true}}\n\n'
        self.assertEqual(b.parse_response(raw, 'text/event-stream', 3)['result'], {'ok':True})
        for raw in (b'data: {"id":4,"result":{}}\n\n', b'data: bad\n\n'):
            with self.assertRaises(b.BrowserError):
                b.parse_response(raw, 'text/event-stream', 3)

    def test_mcp_endpoint_is_loopback_only_and_rejects_credentials(self):
        for address in ('http://localhost:8937/mcp', 'http://127.0.0.1:8937/mcp'):
            b.MCPClient(address)
        for address in ('http://evil.example/mcp','http://user:pass@localhost/mcp','https://127.0.0.1/mcp?token=x'):
            with self.subTest(address=address), self.assertRaises(b.BrowserError):
                b.MCPClient(address)


class TransportTests(unittest.TestCase):
    def test_real_http_session_handshake_and_tool_call(self):
        received=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append((data,self.headers.get('Mcp-Session-Id')))
                if data['method']=='notifications/initialized':
                    self.send_response(202);self.end_headers();return
                value=({'protocolVersion':'2025-06-18','capabilities':{},'serverInfo':{'name':'fixture','version':'1'}}
                       if data['method']=='initialize' else {'content':[{'type':'text','text':'fixture result'}]})
                body=json.dumps({'jsonrpc':'2.0','id':data['id'],'result':value}).encode()
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.send_header('Mcp-Session-Id','private-fixture-session')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            client=b.MCPClient('http://localhost:'+str(server.server_port)+'/mcp')
            state=client.initialize()
            self.assertEqual(state['version'],'2025-06-18')
            self.assertEqual(client.call('browser_snapshot',{})['content'][0]['text'],'fixture result')
            self.assertEqual([item[0]['method'] for item in received],['initialize','notifications/initialized','tools/call'])
            self.assertIsNone(received[0][1])
            self.assertEqual(received[-1][1],'private-fixture-session')
        finally:
            server.shutdown();server.server_close();thread.join()


class CandidateContractTests(unittest.TestCase):
    def test_dynamic_browser_labels_use_inspected_candidates(self):
        import sys
        sys.path.insert(0, str(ROOT / 'Tools'))
        import agency_decisions as d
        state = {'goal':'Read interview instructions', 'context':'Assessment links',
                 'candidates': {'e2':'Open weekly modules', 'f3e4':'Open Assessment 2 Interview'}}
        request = d.build_request(state, 'browser-workflow/next-control')
        self.assertEqual(set(request['questions']['decision']['criteria']), {'e2','f3e4','done','unsure'})
        for candidates in ({}, {'unsure':'Click'}, {'e2':''}, {'bad ref':'Click'},
                           {f'e{i}':'Click' for i in range(33)}):
            with self.subTest(candidates=candidates), self.assertRaises(d.DecisionError):
                d.build_request({**state,'candidates':candidates}, 'browser-workflow/next-control')


if __name__ == '__main__':
    unittest.main()
