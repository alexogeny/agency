import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('evaluation_runtime', ROOT / 'Tools/agency_decisions.py')
d = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(d)


def case(index, state=None):
    return {'id': str(index), 'profile': 'context',
            'state': {'query': 'Find relevant context.', 'passage': str(index) if state is None else state},
            'expected': 'relevant'}


def result():
    return {'decision': 'relevant', 'advisory': True,
            'usage': {'input_tokens': 10, 'output_tokens': 1, 'cost': 0.001}}


class EvaluationTests(unittest.TestCase):
    def test_large_evaluation_preserves_order_and_one_credential_lookup(self):
        manifest = {'items': [case(i) for i in range(60)], 'max_calls': 60}
        with patch.object(d, '_read_key', return_value='key') as key, \
                patch.object(d, '_run_decision_worker', side_effect=lambda *args: result()) as worker, \
                patch.object(d, 'evaluate_batch', wraps=d.evaluate_batch) as batch:
            output = d.evaluate_cases(manifest)
        self.assertEqual(worker.call_count, 60)
        key.assert_called_once()
        self.assertEqual([len(c.args[0]['items']) for c in batch.call_args_list], [32, 28])
        self.assertEqual([r['id'] for r in output['items']], [str(i) for i in range(60)])
        self.assertEqual(output['evaluation']['total'], 60)
        self.assertEqual(output['evaluation']['correct'], 60)
        self.assertEqual(output['evaluation']['by_profile']['context']['correct'], 60)
        self.assertAlmostEqual(output['usage']['cost'], 0.06)

    def test_budget_is_shared_and_errors_stay_in_denominator(self):
        with patch.object(d, '_read_key', return_value='key'), \
                patch.object(d, '_run_decision_worker', side_effect=lambda *args: result()) as worker:
            output = d.evaluate_cases({'items': [case(i) for i in range(60)], 'max_calls': 35})
        self.assertEqual(worker.call_count, 35)
        self.assertEqual(output['attempted_calls'], 35)
        self.assertEqual(output['errors'], 25)
        self.assertEqual(output['evaluation']['accuracy'], 35 / 60)
        self.assertIsNone(output['usage']['cost'])

    def test_duplicate_after_chunk_boundary_is_reused_without_new_call(self):
        manifest = {'items': [case(i) for i in range(33)] + [case('copy', '0')], 'max_calls': 33}
        with patch.object(d, '_read_key', return_value='key'), \
                patch.object(d, '_run_decision_worker', side_effect=lambda *args: result()) as worker:
            output = d.evaluate_cases(manifest)
        self.assertEqual(worker.call_count, 33)
        self.assertTrue(output['items'][-1]['reused'])
        self.assertEqual(output['evaluation']['correct'], 34)

    def test_deadline_is_shared_across_chunks(self):
        now = [0.0]
        def worker(*args):
            now[0] += 0.2
            return result()
        with patch.object(d, '_read_key', return_value='key'), \
                patch.object(d.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(d, '_run_decision_worker', side_effect=worker) as run:
            output = d.evaluate_cases({'items': [case(i) for i in range(60)],
                                      'max_calls': 60, 'concurrency': 1, 'deadline_seconds': 7})
        self.assertLessEqual(run.call_count, 35)
        self.assertGreaterEqual(run.call_count, 32)
        self.assertGreater(output['errors'], 0)
        self.assertEqual(output['evaluation']['total'], 60)

    def test_large_evidence_is_chunked_by_bytes_too(self):
        manifest = {'items': [case(i, str(i) + 'x' * 60000) for i in range(8)]}
        with patch.object(d, '_read_key', return_value='key'), \
                patch.object(d, '_run_decision_worker', side_effect=lambda *args: result()), \
                patch.object(d, 'evaluate_batch', wraps=d.evaluate_batch) as batch:
            output = d.evaluate_cases(manifest)
        self.assertEqual(output['evaluation']['correct'], 8)
        self.assertGreater(batch.call_count, 1)
        for call in batch.call_args_list:
            self.assertLessEqual(len(json.dumps(call.args[0]).encode()), d.MAX_BATCH_BYTES)

    def test_invalid_late_case_rejects_everything_before_credentials(self):
        invalid = case(59)
        invalid['expected'] = 'invented'
        with patch.object(d, '_read_key') as key:
            with self.assertRaises(d.DecisionError):
                d.evaluate_cases({'items': [case(i) for i in range(59)] + [invalid], 'max_calls': 60})
        key.assert_not_called()

    def test_oversized_request_is_rejected_during_dry_run_before_credentials(self):
        state = {'criterion': 'Judge the supplied evidence.', 'evidence': 'x',
                 'evidence_complete': True, 'bands': {f'band{i}': 'b' * 4096 for i in range(8)}}
        state['evidence'] += 'x' * (d.MAX_INPUT_BYTES - len(json.dumps(state).encode()))
        self.assertEqual(len(json.dumps(state).encode()), d.MAX_INPUT_BYTES)
        manifest = {'items': [{'id': 'large', 'profile': 'assess/criterion',
                               'state': state, 'expected': 'band0'}]}
        with patch.object(d, '_read_key') as key:
            with self.assertRaisesRegex(d.DecisionError, 'Request exceeds'):
                d.evaluate_cases(manifest, dry_run=True)
        key.assert_not_called()

    def test_duplicate_ids_and_empty_evaluations_are_invalid(self):
        for items in ([], [case(0), case(0)]):
            with self.subTest(items=items), patch.object(d, '_read_key') as key:
                with self.assertRaises(d.DecisionError):
                    d.evaluate_cases({'items': items})
                key.assert_not_called()

    def test_provider_errors_and_unknown_cost_survive_aggregation(self):
        def worker(item, *args):
            if item['id'] == '33':
                raise d.DecisionError('Provider unavailable.')
            value = result()
            if item['id'] == '0':
                del value['usage']['cost']
            if item['id'] == '1':
                value['decision'] = 'irrelevant'
            return value
        with patch.object(d, '_read_key', return_value='key'), \
                patch.object(d, '_run_decision_worker', side_effect=worker):
            output = d.evaluate_cases({'items': [case(i) for i in range(34)], 'max_calls': 34})
        self.assertEqual(output['evaluation']['correct'], 32)
        self.assertEqual(output['evaluation']['errors'], 1)
        self.assertEqual(output['evaluation']['confusion']['context:relevant'],
                         {'relevant': 32, 'irrelevant': 1, 'error': 1})
        self.assertIsNone(output['usage']['cost'])
        self.assertFalse(output['usage_complete'])

    def test_repository_fixture_can_be_planned_offline_without_counting_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, 'XDG_CONFIG_HOME': directory}
            env.pop('OPENROUTER_API_KEY', None)
            done = subprocess.run([str(ROOT / 'Tools/agency-decide'), 'evaluate', '--input',
                                   str(ROOT / 'Tests/fixtures/decisions.json'), '--dry-run'],
                                  text=True, capture_output=True, env=env, timeout=5)
        self.assertEqual(done.returncode, 0, done.stderr)
        output = json.loads(done.stdout)
        self.assertEqual(len(output['items']), len(json.loads((ROOT / 'Tests/fixtures/decisions.json').read_text())['items']))
        self.assertEqual(output['errors'], 0)
        self.assertIsNone(output['evaluation']['accuracy'])
        self.assertEqual(output['attempted_calls'], 0)
        self.assertEqual(output['_agency_decisions']['decisions'], 0)

    def test_trial_cli_is_offline_and_does_not_count_as_jev_usage(self):
        manifest = {'items': [{'id': 'pair-1', 'profile': 'claim-fit',
                    'baseline': {'accepted': True, 'elapsed_ms': 1000, 'cost': None, 'repairs': 1},
                    'jev': {'accepted': False, 'elapsed_ms': 1200, 'cost': None, 'repairs': 2,
                            'preparation_ms': 100, 'decision_ms': 200, 'overrides': 1,
                            'useful_corrections': 0}}]}
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, 'XDG_CONFIG_HOME': directory}
            env.pop('OPENROUTER_API_KEY', None)
            done = subprocess.run([str(ROOT / 'Tools/agency-decide'), 'trial-report', '--input', '-'],
                                  input=json.dumps(manifest), text=True, capture_output=True, env=env, timeout=5)
        self.assertEqual(done.returncode, 0, done.stderr)
        output = json.loads(done.stdout)
        self.assertEqual(output['overall']['jev']['unaccepted'], 1)
        self.assertIsNone(output['overall']['jev']['cost_per_accepted'])
        self.assertNotIn('_agency_decisions', output)
        self.assertNotIn('items', output)

    def test_invalid_trial_cli_is_structured_error_without_decision_receipt(self):
        done = subprocess.run([str(ROOT / 'Tools/agency-decide'), 'trial-report', '--input', '-'],
                              input='{"items":[]}', text=True, capture_output=True, timeout=5)
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, '')
        output = json.loads(done.stderr)
        self.assertIn('error', output)
        self.assertNotIn('_agency_decisions', output)
