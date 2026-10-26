import os
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DecisionInstallTests(unittest.TestCase):
    def test_configured_hooks_consume_real_cli_and_stdio_mcp_receipts(self):
        for client in ('codex', 'claude'):
            with self.subTest(client=client), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                executable = home / '.local/bin/agency-decision-usage'
                executable.parent.mkdir(parents=True)
                executable.symlink_to(ROOT / 'Tools/agency-decision-usage')
                env = {**os.environ, 'HOME': directory, 'XDG_CONFIG_HOME': str(home / 'config'),
                       'XDG_RUNTIME_DIR': str(home / 'runtime')}
                env.pop('OPENROUTER_API_KEY', None)
                (home / 'runtime').mkdir()
                hooks = json.loads((ROOT / 'config' / client / 'hooks.json').read_text())['hooks']

                def dispatch(event, tool='', response=None, turn='one'):
                    payload = {'hook_event_name': event, 'session_id': 'acceptance',
                               'tool_name': tool, 'tool_response': response}
                    if client == 'codex':
                        payload['turn_id'] = turn
                    commands = [handler['command'] for group in hooks[event]
                                if re.search(group.get('matcher', ''), tool)
                                for handler in group['hooks'] if 'agency-decision-usage' in handler['command']]
                    self.assertEqual(len(commands), 1, (client, event, tool))
                    done = subprocess.run(commands[0], shell=True, input=json.dumps(payload),
                                          text=True, capture_output=True, env=env, timeout=5)
                    self.assertEqual(done.returncode, 0, done.stderr)
                    return json.loads(done.stdout)

                dispatch('UserPromptSubmit')
                state = {'query': 'Locate the parser.', 'passage': 'The parser is in parser.py.'}
                cli = [str(ROOT / 'Tools/agency-decide'), 'classify', '--profile', 'context', '--input', '-']
                dry = subprocess.run([*cli, '--dry-run'], input=json.dumps(state),
                                     text=True, capture_output=True, env=env, timeout=5)
                self.assertEqual(dry.returncode, 0, dry.stderr)
                dispatch('PostToolUse', 'Bash', {'stdout': dry.stdout})
                failed = subprocess.run(cli, input=json.dumps(state),
                                        text=True, capture_output=True, env=env, timeout=5)
                self.assertEqual(failed.returncode, 2)
                self.assertIn('credential', json.loads(failed.stderr)['error'])
                event = 'PostToolUseFailure' if client == 'claude' else 'PostToolUse'
                for _ in range(2):
                    dispatch(event, 'Bash', {'stderr': failed.stderr})

                requests = [
                    {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize'},
                    {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {
                        'name': 'classify', 'arguments': {'profile': 'context', 'state': state}}},
                    {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {
                        'name': 'classify_batch', 'arguments': {'items': [
                            {'id': 'a', 'profile': 'context', 'state': state}]}}},
                ]
                mcp = subprocess.run([str(ROOT / 'Tools/agency-decide-mcp')],
                                     input=''.join(json.dumps(request) + '\n' for request in requests),
                                     text=True, capture_output=True, env=env, timeout=5)
                self.assertEqual(mcp.returncode, 0, mcp.stderr)
                responses = [json.loads(line) for line in mcp.stdout.splitlines()]
                self.assertEqual(len(responses), 3)
                for name, response in zip(('classify', 'classify_batch'), responses[1:]):
                    self.assertTrue(response['result']['isError'])
                    for separator in ('-', '_'):
                        dispatch('PostToolUse', f'mcp__agency{separator}decide__{name}', response['result'])
                self.assertEqual(dispatch('Stop')['systemMessage'], 'Jev: 0 decisions · 3 errors')
                if client == 'codex':
                    self.assertEqual(dispatch('Interrupt')['systemMessage'], 'Jev: 0 decisions · 3 errors')
                dispatch('UserPromptSubmit', turn='two')
                self.assertEqual(dispatch('Stop', turn='two')['systemMessage'], 'Jev: 0 decisions')

    def test_dry_run_installs_decision_tools_without_creating_state(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            result = subprocess.run([ROOT / "install.sh", "--dry-run"], capture_output=True, text=True,
                                    env={**os.environ, "HOME": str(home)}, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ("agency-decide", "agency-decide-mcp", "agency-decision-usage"):
                self.assertIn(str(home / ".local/bin" / name), result.stdout)
            self.assertIn("agency-decide MCP", result.stdout)
            self.assertIn("decision-routing", result.stdout)
            self.assertIn("extensions/agency-decisions.ts", result.stdout)
            self.assertIn("OpenRouter local credential", result.stdout)
            self.assertEqual(list(home.iterdir()), [])

    def test_clients_observe_decisions_and_report_at_turn_end(self):
        for client in ('codex', 'claude'):
            hooks = json.loads((ROOT / 'config' / client / 'hooks.json').read_text())['hooks']
            for event in ('UserPromptSubmit', 'PostToolUse', 'Stop'):
                handlers = [handler for group in hooks[event] for handler in group['hooks']]
                self.assertTrue(any('agency-decision-usage' in h['command'] for h in handlers))
            self.assertTrue(hooks['SessionStart'])


if __name__ == "__main__":
    unittest.main()
