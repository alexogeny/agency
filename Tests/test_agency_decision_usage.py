import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'Tools/agency-decision-usage'


def report(identifier='a' * 32, decisions=1, errors=0, reused=0):
    return {'_agency_decisions': {'version': 1, 'id': identifier, 'created_ns': time.time_ns(),
            'decisions': decisions, 'errors': errors, 'reused': reused}}


class UsageHookTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = {**os.environ, 'XDG_RUNTIME_DIR': self.directory.name}

    def hook(self, event, session='s', turn='t', client='codex', **fields):
        payload = {'hook_event_name': event, 'session_id': session, **fields}
        if turn is not None:
            payload['turn_id'] = turn
        result = subprocess.run(['python3', str(HOOK), '--client', client],
                                input=json.dumps(payload), text=True, capture_output=True,
                                env=self.env, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_counts_nested_cli_and_mcp_results_once_and_resets_per_turn(self):
        self.hook('UserPromptSubmit', prompt='PRIVATE PROMPT')
        value = report(decisions=3, errors=1, reused=2)
        response = {'structuredContent': value,
                    'content': [{'type': 'text', 'text': json.dumps(value)}]}
        for _ in range(2):
            self.hook('PostToolUse', tool_name='mcp__agency-decide__classify_batch',
                      tool_response=response)
        self.hook('PostToolUse', tool_name='Bash', tool_response={
            'stdout': 'prefix\n' + json.dumps(report('b' * 32)) + '\n'})
        self.assertEqual(self.hook('Stop')['systemMessage'], 'Jev: 4 decisions · 1 error · 2 reused')
        self.assertEqual(self.hook('Stop')['systemMessage'], 'Jev: 4 decisions · 1 error · 2 reused')
        self.hook('UserPromptSubmit', turn='next')
        self.assertEqual(self.hook('Stop', turn='next')['systemMessage'], 'Jev: 0 decisions')
        saved = ''.join(p.read_text() for p in Path(self.directory.name).rglob('*.json'))
        self.assertNotIn('PRIVATE PROMPT', saved)
        self.assertNotIn('tool_response', saved)
        for path in Path(self.directory.name).rglob('*.json'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_sessions_and_late_turn_results_do_not_mix(self):
        for session in ('one', 'two'):
            self.hook('UserPromptSubmit', session=session)
        self.hook('PostToolUse', session='one', tool_name='Bash', tool_response=report())
        self.assertEqual(self.hook('Stop', session='two')['systemMessage'], 'Jev: 0 decisions')
        self.hook('UserPromptSubmit', session='one', turn='new')
        self.hook('PostToolUse', session='one', tool_name='Bash', tool_response=report('b' * 32))
        self.assertEqual(self.hook('Stop', session='one', turn='new')['systemMessage'], 'Jev: 0 decisions')

    def test_claude_prompt_boundaries_and_subagents(self):
        self.hook('UserPromptSubmit', turn=None, client='claude')
        self.hook('PostToolUse', turn=None, client='claude', tool_name='Bash', tool_response=report())
        self.hook('PostToolUse', turn=None, client='claude', agent_id='worker',
                  tool_name='Bash', tool_response=report('b' * 32))
        self.assertEqual(self.hook('Stop', turn=None, client='claude')['systemMessage'], 'Jev: 1 decision')
        self.hook('UserPromptSubmit', client='codex')
        self.assertEqual(self.hook('Stop', client='codex')['systemMessage'], 'Jev: 0 decisions')
        self.hook('UserPromptSubmit', turn=None, client='claude')
        self.assertEqual(self.hook('Stop', turn=None, client='claude')['systemMessage'], 'Jev: 0 decisions')

    def test_codex_subagent_prompt_cannot_reset_parent_turn(self):
        self.hook('UserPromptSubmit')
        self.hook('PostToolUse', tool_name='Bash', tool_response=report())
        self.hook('UserPromptSubmit', turn='child', agent_id='worker')
        self.hook('PostToolUse', turn='child', agent_id='worker', tool_name='Bash',
                  tool_response=report('b' * 32))
        self.assertEqual(self.hook('Stop')['systemMessage'], 'Jev: 1 decision')

    def test_parallel_reports_do_not_lose_updates(self):
        self.hook('UserPromptSubmit')
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: self.hook('PostToolUse', tool_name='Bash',
                tool_response=report(f'{i:032x}')), range(12)))
        self.assertEqual(self.hook('Stop')['systemMessage'], 'Jev: 12 decisions')

    def test_missing_start_and_missing_receipt_are_not_reported_as_zero(self):
        self.assertIn('unavailable', self.hook('Stop')['systemMessage'])
        self.hook('UserPromptSubmit')
        self.hook('PostToolUse', tool_name='mcp__agency-decide__classify',
                  tool_response={'content': [{'type': 'text', 'text': 'truncated'}]})
        self.assertIn('incomplete', self.hook('Stop')['systemMessage'])

    def test_input_is_not_counted_and_dry_run_does_not_count(self):
        self.hook('UserPromptSubmit')
        self.hook('PostToolUse', tool_name='Bash', tool_input=report(decisions=20),
                  tool_response=report(decisions=0))
        self.assertEqual(self.hook('Stop')['systemMessage'], 'Jev: 0 decisions')

    def test_partial_receipt_and_oversized_events_remain_incomplete(self):
        self.hook('UserPromptSubmit')
        self.hook('PostToolUse', tool_name='Bash', tool_response={
            'stdout': json.dumps(report()) + '\n{"_agency_decisions":'})
        self.assertIn('count incomplete', self.hook('Stop')['systemMessage'])
        self.hook('UserPromptSubmit', turn='new')
        output = self.hook('PostToolUse', turn='new', tool_name='Bash',
                           tool_response='x' * (1024 * 1024 + 1))
        self.assertIn('unavailable', output['systemMessage'])
        self.assertIn('count incomplete', self.hook('Stop', turn='new')['systemMessage'])

    def test_old_receipts_cannot_count_as_new_decisions(self):
        old = report()
        self.hook('UserPromptSubmit')
        self.hook('PostToolUse', tool_name='Bash', tool_response=old)
        self.assertEqual(self.hook('Stop')['systemMessage'], 'Jev: 0 decisions')

    def test_reading_counter_source_is_not_a_truncated_decision(self):
        self.hook('UserPromptSubmit')
        self.hook('PostToolUse', tool_name='Bash', tool_input={'command': 'cat Tools/agency_decision_usage.py'},
                  tool_response=(ROOT / 'Tools/agency_decision_usage.py').read_text())
        self.assertEqual(self.hook('Stop')['systemMessage'], 'Jev: 0 decisions')

    def test_next_prompt_recovers_from_interrupted_state_write(self):
        self.hook('UserPromptSubmit')
        state = next(Path(self.directory.name).rglob('*.json'))
        state.write_text('{"turn":')
        self.assertIn('unavailable', self.hook('Stop')['systemMessage'])
        self.hook('UserPromptSubmit', turn='next')
        self.hook('PostToolUse', turn='next', tool_name='Bash', tool_response=report())
        self.assertEqual(self.hook('Stop', turn='next')['systemMessage'], 'Jev: 1 decision')

    def test_symlink_state_directory_is_refused_without_writing_target(self):
        target = Path(self.directory.name) / 'target'
        target.mkdir()
        (Path(self.directory.name) / 'agency-decision-usage').symlink_to(target, target_is_directory=True)
        self.assertIn('unavailable', self.hook('UserPromptSubmit')['systemMessage'])
        self.assertEqual(list(target.iterdir()), [])


class UsageReportTests(unittest.TestCase):
    def test_batch_report_counts_completed_unique_results(self):
        spec = importlib.util.spec_from_file_location('decision_usage', ROOT / 'Tools/agency_decision_usage.py')
        usage = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(usage)
        result = {'items': [
            {'result': {}, 'reused': False}, {'result': {}, 'reused': True},
            {'error': 'failed', 'reused': False}, {'error': 'failed', 'reused': True}],
            'dry_run': False}
        summary = usage.with_report(result)['_agency_decisions']
        self.assertEqual((summary['decisions'], summary['errors'], summary['reused']), (1, 1, 1))
        result.pop('_agency_decisions')
        result['dry_run'] = True
        self.assertEqual(usage.with_report(result)['_agency_decisions']['decisions'], 0)

    def test_batch_does_not_expose_replayable_worker_receipts(self):
        spec = importlib.util.spec_from_file_location('decision_usage', ROOT / 'Tools/agency_decision_usage.py')
        usage = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(usage)
        child = usage.with_report({'decision': 'relevant'})
        batch = usage.with_report({'items': [{'result': child, 'reused': False}], 'dry_run': False})
        self.assertNotIn('_agency_decisions', batch['items'][0]['result'])
        self.assertEqual(batch['_agency_decisions']['decisions'], 1)
