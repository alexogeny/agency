import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'Tools/agency-decide-mcp'
LOADER = importlib.machinery.SourceFileLoader('agency_decide_mcp', str(SERVER))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
mcp = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(mcp)


def message(method, params=None, request_id=1):
    result = {'jsonrpc': '2.0', 'id': request_id, 'method': method}
    if params is not None:
        result['params'] = params
    return result


class DecisionMCPTests(unittest.TestCase):
    def test_profile_lookup_loads_only_the_requested_contract(self):
        result = mcp.handle(message('tools/call', {'name': 'profiles',
                            'arguments': {'profile': 'assess/criterion'}}))['result']
        self.assertEqual(set(result['structuredContent']['profiles']), {'assess/criterion'})

    def test_batch_reports_partial_failure_as_tool_error_without_losing_results(self):
        batch = {'items': [{'id': 'one', 'profile': 'context', 'state': 'x'}]}
        payload = {'advisory': True, 'errors': 1, 'items': [{'id': 'one', 'error': 'Unavailable'}]}
        with patch.object(mcp, 'evaluate_batch', return_value=payload) as run:
            result = mcp.handle(message('tools/call', {'name': 'classify_batch', 'arguments': batch}))['result']
        run.assert_called_once_with(batch)
        self.assertTrue(result['isError'])
        self.assertEqual(result['structuredContent'], payload)

    def test_initialize_list_and_profiles_offline(self):
        initialized = mcp.handle(message('initialize', {'protocolVersion': '2025-06-18'}))['result']
        self.assertEqual(initialized['protocolVersion'], '2025-06-18')
        self.assertEqual(initialized['serverInfo']['name'], 'agency-decide')
        tools = mcp.handle(message('tools/list'))['result']['tools']
        self.assertEqual({tool['name'] for tool in tools}, {'profiles', 'classify', 'classify_batch'})
        classify = next(tool for tool in tools if tool['name'] == 'classify')
        self.assertEqual(set(classify['inputSchema']['properties']), {'profile', 'state'})
        with patch.object(mcp.subprocess, 'run') as run:
            result = mcp.handle(message('tools/call', {'name': 'profiles', 'arguments': {}}))['result']
        run.assert_not_called()
        self.assertTrue(result['structuredContent']['advisory'])
        self.assertTrue({'skill', 'context', 'update', 'research', 'assess/criterion'} <= result['structuredContent']['profiles'].keys())

    def test_classify_subprocess_has_hard_timeout_and_no_secret_argv(self):
        payload = {'advisory': True, 'decision': 'none', 'confidence': 0.5}
        completed = subprocess.CompletedProcess([], 0, json.dumps(payload), '')
        with patch.object(mcp, 'key_available', return_value=True), patch.object(mcp.subprocess, 'run', return_value=completed) as run:
            result = mcp.handle(message('tools/call', {'name': 'classify', 'arguments': {'profile': 'skill', 'state': {'task': 'hello'}}}))['result']
        self.assertEqual(result['structuredContent'], payload)
        self.assertEqual(run.call_args.kwargs['timeout'], 10)
        self.assertEqual(json.loads(run.call_args.kwargs['input']), {'task': 'hello'})
        self.assertEqual(run.call_args.args[0][-5:], ['classify', '--profile', 'skill', '--input', '-'])
        self.assertFalse(result.get('isError', False))

    def test_invalid_args_and_missing_credential_are_tool_errors(self):
        arguments = [{}, {'profile': 'unknown', 'state': 'x'}, {'profile': 'skill', 'state': ''},
                     {'profile': 'skill', 'state': 'x', 'api_key': 'secret'},
                     {'profile': 'skill', 'state': True}, {'profile': 'skill', 'state': 'x'}]
        with patch.object(mcp, 'key_available', return_value=False), patch.object(mcp.subprocess, 'run') as run:
            for args in arguments:
                with self.subTest(args=args):
                    result = mcp.handle(message('tools/call', {'name': 'classify', 'arguments': args}))['result']
                    self.assertTrue(result['isError'])
                    self.assertNotIn('secret', json.dumps(result))
        run.assert_not_called()

    def test_worker_errors_timeout_and_stderr_never_leak(self):
        outcomes = [subprocess.CompletedProcess([], 2, '', 'secret-value'),
                    subprocess.CompletedProcess([], 0, 'secret-value', ''),
                    subprocess.TimeoutExpired(['secret-value'], 10), OSError('secret-value')]
        for outcome in outcomes:
            with self.subTest(outcome=type(outcome)):
                kwargs = {'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome}
                with patch.object(mcp, 'key_available', return_value=True), patch.object(mcp.subprocess, 'run', **kwargs):
                    result = mcp.handle(message('tools/call', {'name': 'classify', 'arguments': {'profile': 'skill', 'state': 'x'}}))['result']
                self.assertTrue(result['isError'])
                self.assertNotIn('secret-value', json.dumps(result))

    def test_real_worker_timeout_recovers_for_next_request(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = Path(directory) / 'slow.py'
            worker.write_text('import time\ntime.sleep(20)\n')
            started = time.monotonic()
            with patch.object(mcp, 'CLI', worker), patch.object(mcp, 'CLASSIFY_TIMEOUT', 0.1), patch.object(mcp, 'key_available', return_value=True):
                result = mcp.handle(message('tools/call', {'name': 'classify', 'arguments': {'profile': 'skill', 'state': 'x'}}))
            self.assertTrue(result['result']['isError'])
            self.assertLess(time.monotonic() - started, 2)
            self.assertEqual(mcp.handle(message('ping'))['result'], {})

    def test_protocol_errors_notifications_and_ping(self):
        for request, code in [(message('unknown'), -32601), ({'jsonrpc': '1.0', 'id': 1, 'method': 'ping'}, -32600),
                              (message('tools/call', {'name': 'unknown'}), -32602),
                              (message('tools/call', []), -32602),
                              (message('ping', request_id=True), -32600)]:
            self.assertEqual(mcp.handle(request)['error']['code'], code)
        self.assertEqual(mcp.handle(message('ping'))['result'], {})
        self.assertIsNone(mcp.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}))
        with patch.object(mcp.subprocess, 'run') as run:
            self.assertIsNone(mcp.handle({'jsonrpc': '2.0', 'method': 'tools/call', 'params': {'name': 'classify'}}))
        run.assert_not_called()

    def test_malformed_oversize_and_duplicate_lines_recover(self):
        lines = [b'bad-json\n', b'\xff\n', b'x' * (mcp.MAX_LINE_BYTES + 5) + b'\n',
                 b'{"jsonrpc":"2.0","id":1,"id":2,"method":"ping"}\n',
                 json.dumps(message('ping', request_id=8)).encode() + b'\n']
        output = io.StringIO()
        mcp.serve(io.BytesIO(b''.join(lines)), output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(responses), 5)
        self.assertTrue(all('error' in result for result in responses[:4]))
        self.assertEqual(responses[-1], {'jsonrpc': '2.0', 'id': 8, 'result': {}})

    def test_symlink_stdio_transport_and_no_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            link = Path(directory) / 'agency-decide-mcp'
            link.symlink_to(SERVER)
            env = dict(os.environ, XDG_CONFIG_HOME=directory)
            env.pop('OPENROUTER_API_KEY', None)
            requests = [message('initialize'), message('tools/list', request_id=2),
                        message('tools/call', {'name': 'classify', 'arguments': {'profile': 'skill', 'state': 'hello'}}, 3)]
            done = subprocess.run([str(link)], input=''.join(json.dumps(request) + '\n' for request in requests),
                                  text=True, capture_output=True, env=env, timeout=5)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stderr, '')
            responses = [json.loads(line) for line in done.stdout.splitlines()]
            self.assertEqual(len(responses), 3)
            self.assertTrue(responses[-1]['result']['isError'])


if __name__ == '__main__':
    unittest.main()
