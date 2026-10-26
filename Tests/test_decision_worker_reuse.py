from contextlib import contextmanager
import io
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from Tests.test_agency_decide_mcp import mcp, message

d = sys.modules['agency_decisions']
ROOT = Path(__file__).resolve().parents[1]
FAKE = '''import json, os, sys, time, hashlib
with open(os.environ['DECISION_TEST_STARTS'], 'a') as log:
    log.write(str(os.getpid()) + '\\n')
def classify(state):
    if state['task'].startswith('slow'):
        time.sleep(30)
    if state['task'] == 'crash':
        print('PRIVATE-STDERR', file=sys.stderr)
        sys.exit(3)
    return {'advisory':True, 'decision':'none', 'confidence':0.5,
            'task':state['task'], 'pid':os.getpid(),
            'usage':{'input_tokens':1,'output_tokens':1,'cost':0}}
if '--worker' in sys.argv:
    for line in sys.stdin:
        frame = json.loads(line)
        if frame['state']['task'] == 'invalid-json':
            print('PRIVATE-INVALID-JSON', flush=True)
        elif frame['state']['task'] == 'oversize':
            print('x' * 200000, flush=True)
        elif frame['state']['task'] == 'wrong-id':
            print(json.dumps({'id':-1,'ok':True,'result':classify(frame['state'])}),flush=True)
        else:
            result = classify(frame['state'])
            result['key_digest'] = hashlib.sha256(frame['api_key'].encode()).hexdigest()
            result['environment_has_key'] = 'OPENROUTER_API_KEY' in os.environ
            print(json.dumps({'id':frame['id'],'ok':True,'result':result}),flush=True)
else:
    print(json.dumps(classify(json.load(sys.stdin))))
'''


class DecisionWorkerReuseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fake = self.root / 'fake.py'
        self.fake.write_text(FAKE)
        self.log = self.root / 'starts'
        self.environment = mock.patch.dict(os.environ, {'OPENROUTER_API_KEY': 'fake-local-key',
                                         'DECISION_TEST_STARTS': str(self.log)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(mcp.close_classifier)

    def classify(self, task):
        return mcp.handle(message('tools/call', {'name':'classify',
                          'arguments':{'profile':'skill','state':{'task':task}}}))['result']

    def starts(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    @contextmanager
    def launcher_process(self, launcher, *arguments):
        command = [sys.executable, str(launcher), str(ROOT), str(self.fake), *arguments]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        try:
            yield process
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=3)

    def wait_for_workers(self, expected):
        deadline = time.monotonic() + 3
        while len(self.starts()) < expected and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(len(self.starts()), expected)

    def assert_worker_reaped(self, pid):
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pid), 0)

    def test_single_mcp_reuses_one_process_without_reusing_decisions(self):
        with mock.patch.object(mcp, 'CLI', self.fake):
            values = [self.classify(f'packet-{i}') for i in range(8)]
        self.assertTrue(all(not value.get('isError') for value in values))
        self.assertEqual([value['structuredContent']['task'] for value in values], [f'packet-{i}' for i in range(8)])
        self.assertTrue(all(value['structuredContent']['_agency_decisions']['decisions'] == 1 for value in values))
        self.assertEqual(len(self.starts()), 1)

    def test_batch_workers_are_bounded_and_reused_with_order_and_usage(self):
        manifest = {'items':[{'id':f'i{i}','profile':'skill','state':{'task':f'packet-{i}'}} for i in range(16)],
                    'max_calls':16,'concurrency':2}
        with mock.patch.object(d, 'CLI', self.fake):
            value = d.evaluate_batch(manifest)
        self.assertEqual(value['errors'], 0)
        self.assertEqual([row['result']['task'] for row in value['items']], [f'packet-{i}' for i in range(16)])
        self.assertEqual(value['usage']['input_tokens'], 16)
        self.assertLessEqual(len(self.starts()), 2)
        self.assertGreaterEqual(len(self.starts()), 1)
        for pid in self.starts():
            self.assert_worker_reaped(pid)

    def test_timeout_kills_worker_without_retry_then_next_request_recovers(self):
        with mock.patch.object(mcp, 'CLI', self.fake), mock.patch.object(mcp, 'CLASSIFY_TIMEOUT', .1):
            start = time.monotonic()
            failed = self.classify('slow')
            self.assertLess(time.monotonic() - start, 2)
            self.assertTrue(failed['isError'])
            self.assertEqual(len(self.starts()), 1)
            self.assert_worker_reaped(self.starts()[0])
            good = self.classify('next')
        self.assertFalse(good.get('isError', False))
        self.assertEqual(good['structuredContent']['task'], 'next')
        self.assertEqual(len(self.starts()), 2)

    def test_eof_reaps_worker_and_does_not_leak_stderr(self):
        request = message('tools/call', {'name':'classify','arguments':{'profile':'skill','state':{'task':'hello'}}})
        with mock.patch.object(mcp, 'CLI', self.fake):
            output = io.StringIO()
            mcp.serve(io.BytesIO((json.dumps(request)+'\n').encode()), output)
        self.assertNotIn('PRIVATE', output.getvalue())
        self.assertEqual(len(self.starts()), 1)
        self.assert_worker_reaped(self.starts()[0])

    def test_malformed_frames_are_bounded_errors_and_recover(self):
        with mock.patch.object(mcp, 'CLI', self.fake), mock.patch.object(mcp, 'CLASSIFY_TIMEOUT', .5):
            for task in ('oversize','wrong-id','crash','invalid-json'):
                with self.subTest(task=task):
                    result = self.classify(task)
                    self.assertTrue(result.get('isError'))
                    self.assertNotIn('PRIVATE', json.dumps(result))
            good = self.classify('recovered')
        self.assertFalse(good.get('isError', False))
        self.assertEqual(len(self.starts()), 5)

    def test_credentials_are_fresh_per_call_and_not_left_in_worker_environment(self):
        config = self.root/'agency'/'openrouter.json'
        config.parent.mkdir()
        os.environ.pop('OPENROUTER_API_KEY', None)
        with mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.root)}), mock.patch.object(mcp, 'CLI', self.fake):
            for key in ('first-private-key', 'second-private-key'):
                config.write_text(json.dumps({'api_key':key}))
                config.chmod(0o600)
                value = self.classify('fresh')['structuredContent']
                self.assertEqual(value['key_digest'], hashlib.sha256(key.encode()).hexdigest())
                self.assertFalse(value['environment_has_key'])
                self.assertNotIn(key, json.dumps(value))
        self.assertEqual(len(self.starts()), 1)

    def test_sigterm_reaps_active_single_and_batch_workers(self):
        launcher = self.root/'launch.py'
        launcher.write_text("""import importlib.machinery, importlib.util, signal, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1])/'Tools'))
loader=importlib.machinery.SourceFileLoader('server',str(Path(sys.argv[1])/'Tools/agency-decide-mcp'))
spec=importlib.util.spec_from_loader(loader.name,loader)
m=importlib.util.module_from_spec(spec);loader.exec_module(m)
m.CLI=Path(sys.argv[2])
import agency_decisions as d
d.CLI=m.CLI
signal.signal(signal.SIGTERM,m.terminate)
m.serve(sys.stdin.buffer,sys.stdout)
""")
        for operation in ('classify', 'classify_batch'):
            with self.subTest(operation=operation):
                self.log.unlink(missing_ok=True)
                if operation == 'classify':
                    arguments = {'profile':'skill','state':{'task':'slow'}}
                    expected = 1
                else:
                    arguments = {'items':[{'id':f'i{i}','profile':'skill','state':{'task':f'slow-{i}'}} for i in range(4)],
                                 'concurrency':2}
                    expected = 2
                request = message('tools/call', {'name':operation, 'arguments':arguments})
                with self.launcher_process(launcher) as process:
                    process.stdin.write(json.dumps(request)+'\n')
                    process.stdin.flush()
                    self.wait_for_workers(expected)
                    process.terminate()
                    output, errors = process.communicate(timeout=3)
                    self.assertEqual(process.returncode,0,errors)
                    self.assertNotIn('PRIVATE',output+errors)
                    for pid in self.starts():
                        self.assert_worker_reaped(pid)

    def test_cli_sigterm_reaps_batch_and_evaluation_workers_with_signal_status(self):
        launcher = self.root/'launch-cli.py'
        launcher.write_text("""import sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'Tools'))
import agency_decisions as d
d.CLI=Path(sys.argv[2])
operation=sys.argv[3]
sys.argv=['agency-decide',operation,'--input','-']
raise SystemExit(d.main())
""")
        for operation in ('classify-batch', 'evaluate'):
            with self.subTest(operation=operation):
                self.log.unlink(missing_ok=True)
                items=[{'id':f'i{i}','profile':'skill','state':{'task':f'slow-{i}'}} for i in range(4)]
                if operation == 'evaluate':
                    for item in items:
                        item['expected']='none'
                manifest={'items':items,'concurrency':2}
                with self.launcher_process(launcher, operation) as process:
                    process.stdin.write(json.dumps(manifest))
                    process.stdin.close()
                    process.stdin=None
                    self.wait_for_workers(2)
                    process.terminate()
                    output,errors=process.communicate(timeout=3)
                    self.assertEqual(process.returncode,143,errors)
                    self.assertNotIn('PRIVATE',output+errors)
                    for pid in self.starts():
                        self.assert_worker_reaped(pid)

    def test_actual_process_argv_excludes_credentials_and_request_state(self):
        original = subprocess.Popen
        with mock.patch.object(mcp, 'CLI', self.fake), mock.patch.object(d.subprocess, 'Popen', wraps=original) as started:
            value = self.classify('private-packet')
        self.assertFalse(value.get('isError',False))
        self.assertEqual(started.call_count,1)
        argv = started.call_args.args[0]
        environment = started.call_args.kwargs['env']
        self.assertEqual(argv,[sys.executable,str(self.fake),'--worker'])
        self.assertNotIn('fake-local-key',json.dumps(argv))
        self.assertNotIn('private-packet',json.dumps(argv))
        self.assertNotIn('OPENROUTER_API_KEY',environment)
        self.assertIs(started.call_args.kwargs['stderr'],subprocess.DEVNULL)
        self.assertTrue(started.call_args.kwargs['start_new_session'])

    def test_internal_frame_loop_is_offline_and_does_not_reuse_results(self):
        frames=[{'id':i,'profile':'skill','state':{'task':f'packet-{i}'},'api_key':f'private-key-{i}'} for i in range(2)]
        source=io.BytesIO(b''.join(json.dumps(frame).encode()+b'\n' for frame in frames))
        output=io.BytesIO()
        def evaluate(state, profile, api_key=None):
            self.assertEqual(profile,'skill')
            return {'advisory':True,'decision':'none','packet':state['task']}
        with mock.patch.object(d,'evaluate',side_effect=evaluate) as classifier:
            self.assertEqual(d.serve_classifications(source,output),0)
        self.assertEqual(classifier.call_count,2)
        self.assertEqual([call.kwargs['api_key'] for call in classifier.call_args_list], ['private-key-0','private-key-1'])
        values=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([v['id'] for v in values],[0,1])
        self.assertEqual([v['result']['packet'] for v in values],['packet-0','packet-1'])
        self.assertTrue(all(v['result']['_agency_decisions']['decisions']==1 for v in values))
        self.assertNotIn('private-key',output.getvalue().decode())
        for raw in (b'{invalid}\n', b'x'*(d.MAX_WORKER_FRAME+1), b'{}'):
            sink=io.BytesIO()
            with mock.patch.object(d,'evaluate') as classifier:
                self.assertEqual(d.serve_classifications(io.BytesIO(raw),sink),2)
            classifier.assert_not_called()
            self.assertEqual(sink.getvalue(),b'')


if __name__ == '__main__':
    unittest.main()
