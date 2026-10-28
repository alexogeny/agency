import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'Tools'
sys.path.insert(0, str(TOOLS))
import research_corpus_core as core
import web_research_owned_profiles as profiles


class CorpusReviewFixesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'corpus'
        protocol = self.base / 'protocol.json'
        protocol.write_text('{"scope":"Synthetic failure boundary checks"}')
        with patch.object(core, '_RUNTIME_IDENTITY', {'python': sys.version, 'fixture': True}):
            core.init_corpus(self.root, protocol)
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
                        XDG_STATE_HOME=str(self.base / 'state'))

    def test_live_rerun_refreshes_a_fresh_cache(self):
        state = {'cached': None, 'upstream': 'original'}
        calls = []
        def backend(args, request=None):
            calls.append(args)
            if args[0] == 'search':
                return {'query': args[1], 'results': [{'url': 'https://example.test/source'}]}, {'exit_code': 0}
            cached = '--preflight' in args and state['cached'] is not None
            body = state['cached'] if cached else state['upstream']
            state['cached'] = body
            return {'url': args[1], 'text': body, 'markdown': body,
                    'freshness': {'retrieval': 'local-index' if cached else 'live'}}, {'exit_code': 0}
        with patch.object(core, 'run_backend', side_effect=backend):
            core.discover(self.root, 'query', 'fixture', 'one')
            sid = next(iter(core.read_manifest(self.root)['sources']))
            core.open_source(self.root, sid, profile='fixture')
            old = core.read_manifest(self.root)['active_run']
            state['upstream'] = 'updated live body'
            core.rerun(self.root, old, 'fixture')
        record = core.load_record(self.root, core.committed_records(self.root)[-1])
        self.assertEqual(record['text'], 'updated live body')
        self.assertEqual(record['retrieval']['mode'], 'live')
        self.assertNotIn('--preflight', calls[-1])
        self.assertIn('--index', calls[-1])

    def test_private_handles_are_denied_after_argument_reordering(self):
        auth = {'reference': 'fixture-scope', 'owner_execution': 'fixture-owner', 'disposable': True}
        handle = {'schema': 'agency/owned-profile/1', 'profile': 'task-synthetic',
                  'owner_execution': 'fixture-owner', 'canonical_path': '/synthetic/private/profile',
                  'nonce': 'synthetic-private-nonce', 'authorization': auth}
        with patch.dict(os.environ, self.env), patch.object(core, 'run_backend', return_value=(handle, {'exit_code': 0})):
            core.profiles(self.root, 'create', 'fixture-owner', purpose='Fixture', authorization=auth)
        for options in (['--owner-execution', 'fixture-owner', '--authorization', 'fixture-scope'],
                        ['--owner-ex', 'fixture-owner', '--authoriz', 'fixture-scope']):
            with self.subTest(options=options):
                command = ['profiles', *options, 'handles', str(self.root)]
                request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                           'params': {'name': 'corpus', 'arguments': {'command': command}}}
                result = subprocess.run(['bun', str(TOOLS / 'web-research-mcp')],
                                        input=json.dumps(request) + '\n', env=self.env,
                                        text=True, capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                response = json.loads(result.stdout)['result']
                self.assertTrue(response.get('isError', False), result.stdout)
                self.assertNotIn('synthetic-private-nonce', result.stdout)
                self.assertNotIn('/synthetic/private/profile', result.stdout)

    def test_partial_cleanup_can_retry_metadata_only_and_refuses_replacement(self):
        data = self.base / 'browser'
        auth = {'reference': 'fixture-scope', 'owner_execution': 'fixture-owner', 'disposable': True}
        handle = profiles.operate('profile-create', {'schema': 'agency/owned-profile-request/1',
            'owner_execution': 'fixture-owner', 'purpose': 'Temporary fixture',
            'mode': 'persistent', 'authorization': auth}, data)
        request = {'handle': handle, 'owner_execution': 'fixture-owner', 'authorization': auth}
        metadata = Path(handle['canonical_path'] + '.agency.json')
        unlink = Path.unlink
        def fail_metadata(path, *args, **kwargs):
            if path == metadata:
                raise OSError('Synthetic metadata removal failure')
            return unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', fail_metadata):
            partial = profiles.operate('profile-cleanup', request, data)
        self.assertEqual(partial['outcome'], 'partial')
        self.assertFalse(Path(handle['canonical_path']).exists())
        replacement = Path(handle['canonical_path'])
        replacement.mkdir()
        (replacement / 'preserve').write_text('Foreign directory')
        with self.assertRaises(profiles.ProfileError):
            profiles.operate('profile-cleanup', request, data)
        self.assertTrue((replacement / 'preserve').is_file())
        (replacement / 'preserve').unlink()
        replacement.rmdir()
        result = profiles.operate('profile-cleanup', request, data)
        self.assertEqual(result['outcome'], 'removed')
        self.assertTrue(result['postcheck']['metadata_absent'])

    def test_missing_profile_without_cleanup_checkpoint_preserves_metadata(self):
        data = self.base / 'browser'
        auth = {'reference': 'fixture-scope', 'owner_execution': 'fixture-owner', 'disposable': True}
        handle = profiles.operate('profile-create', {'schema': 'agency/owned-profile-request/1',
            'owner_execution': 'fixture-owner', 'purpose': 'Temporary fixture',
            'mode': 'persistent', 'authorization': auth}, data)
        Path(handle['canonical_path']).rmdir()
        with self.assertRaises(profiles.ProfileError):
            profiles.operate('profile-cleanup', {'handle': handle,
                'owner_execution': 'fixture-owner', 'authorization': auth}, data)
        self.assertTrue(Path(handle['canonical_path'] + '.agency.json').is_file())

    @staticmethod
    def running(pid):
        try:
            os.kill(pid, 0)
            stat = Path('/proc') / str(pid) / 'stat'
            return not stat.exists() or stat.read_text().split(') ', 1)[1][0] != 'Z'
        except (ProcessLookupError, FileNotFoundError):
            return False

    def slow_backend(self):
        marker = self.base / 'backend.json'
        script = self.base / 'slow-backend'
        script.write_text('#!' + sys.executable + '\n'
            'import json,os,subprocess,sys,time\nfrom pathlib import Path\n'
            'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])\n'
            'Path(os.environ["CORPUS_CHILD_MARKER"]).write_text(json.dumps({"backend":os.getpid(),"child":child.pid,"group":os.getpgrp(),"supervisor":os.getppid()}))\n'
            'time.sleep(30)\nprint(json.dumps({"results":[]}))\n')
        script.chmod(0o700)
        return marker, dict(self.env, RESEARCH_CORPUS_WEB_COMMAND=str(script),
                            CORPUS_CHILD_MARKER=str(marker))

    def wait_marker(self, marker, process):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not marker.exists() and process.poll() is None:
            time.sleep(.025)
        self.assertTrue(marker.exists(), 'Owned backend did not start')
        return json.loads(marker.read_text())

    def verify_stopped(self, pids):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and any(self.running(pids[k]) for k in ('backend', 'child', 'supervisor')):
            time.sleep(.025)
        self.assertFalse(self.running(pids['backend']), 'Owned backend survived cancellation')
        self.assertFalse(self.running(pids['child']), 'Owned descendant survived cancellation')
        self.assertFalse(self.running(pids['supervisor']), 'Owned supervisor survived cancellation')

    def cleanup_processes(self, process, pids):
        if process.poll() is None:
            process.kill()
        if pids:
            try:
                os.killpg(pids['group'], signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.communicate(timeout=5)

    def test_killed_cli_stops_its_backend_and_descendants(self):
        marker, env = self.slow_backend()
        process = subprocess.Popen([sys.executable, str(TOOLS / 'research-corpus'), 'discover',
            str(self.root), '--query', 'fixture', '--profile', 'fixture', '--operation-id', 'cancel'],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        pids = None
        try:
            pids = self.wait_marker(marker, process)
            process.kill()
            process.wait(timeout=5)
            self.verify_stopped(pids)
            self.assertTrue((self.root / 'pending/request.json').is_file())
        finally:
            self.cleanup_processes(process, pids)

    def test_backend_deadline_stops_only_its_owned_group(self):
        marker, env = self.slow_backend()
        canary = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'])
        now = time.monotonic
        try:
            with patch.dict(os.environ, env), patch.object(core.time, 'monotonic',
                    side_effect=lambda: now() + (200 if marker.exists() else 0)):
                with self.assertRaises(core.CorpusError) as failure:
                    core.run_backend(['search', 'fixture'])
            self.assertTrue(failure.exception.details['process']['timed_out'])
            self.verify_stopped(json.loads(marker.read_text()))
            self.assertIsNone(canary.poll(), 'Cancellation touched an unrelated process')
        finally:
            canary.kill()
            canary.wait(timeout=5)

    def test_successful_backend_reaps_leftover_descendant_and_keeps_status(self):
        marker, env = self.slow_backend()
        script = Path(env['RESEARCH_CORPUS_WEB_COMMAND'])
        script.write_text(script.read_text().replace('time.sleep(30)\nprint(', 'print('))
        with patch.dict(os.environ, env):
            result, state = core.run_backend(['search', 'fixture'])
        self.assertEqual(result, {'results': []})
        self.assertEqual(state['exit_code'], 0)
        self.verify_stopped(json.loads(marker.read_text()))

    def test_mcp_exit_stops_owned_corpus_work(self):
        marker, env = self.slow_backend()
        process = subprocess.Popen(['bun', str(TOOLS / 'web-research-mcp')], env=env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'corpus',
            'arguments': {'command': ['discover', str(self.root), '--query', 'fixture',
                '--profile', 'fixture', '--operation-id', 'mcp-cancel']}}}
        pids = None
        try:
            process.stdin.write((json.dumps(request) + '\n').encode()); process.stdin.flush()
            pids = self.wait_marker(marker, process)
            process.terminate()
            process.wait(timeout=5)
            self.verify_stopped(pids)
        finally:
            self.cleanup_processes(process, pids)

    def test_mcp_deadline_stops_owned_corpus_work(self):
        marker, env = self.slow_backend()
        mcp = self.base / 'web-research-mcp'
        source = (TOOLS / 'web-research-mcp').read_text()
        deadline = 'const backendDeadlineMs = 150_000;'
        self.assertEqual(source.count(deadline), 1)
        mcp.write_text(source.replace(deadline, 'const backendDeadlineMs = 1_000;'))
        for name in ('research-corpus', 'web_research_evidence.ts'):
            (self.base / name).symlink_to(TOOLS / name)
        process = subprocess.Popen(['bun', str(mcp)], env=env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'corpus',
            'arguments': {'command': ['discover', str(self.root), '--query', 'fixture',
                '--profile', 'fixture', '--operation-id', 'mcp-timeout']}}}
        pids = None
        try:
            process.stdin.write((json.dumps(request) + '\n').encode())
            process.stdin.flush()
            pids = self.wait_marker(marker, process)
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertTrue(json.loads(stdout)['result']['isError'], stdout)
            self.verify_stopped(pids)
        finally:
            self.cleanup_processes(process, pids)


if __name__ == '__main__':
    unittest.main()
