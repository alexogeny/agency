import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('decision_batches', ROOT / 'Tools/agency_decisions.py')
d = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(d)


def item(identifier, state='hello'):
    return {'id': identifier, 'profile': 'context', 'state': state}


def result():
    return {'advisory': True, 'decision': 'relevant', 'usage': {'input_tokens': 10, 'output_tokens': 1, 'cost': 0.001}}


class BatchTests(unittest.TestCase):
    def test_concurrency_is_bounded_and_output_preserves_input_order(self):
        active = peak = 0
        lock = threading.Lock()
        def worker(item, key, timeout):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02 if item['id'] == 'a' else 0.005)
            with lock:
                active -= 1
            return result()
        with patch.object(d, '_read_key', return_value='key'), patch.object(d, '_run_decision_worker', side_effect=worker):
            output = d.evaluate_batch({'items': [item(c, c) for c in 'abcde'], 'concurrency': 2})
        self.assertEqual(peak, 2)
        self.assertEqual([row['id'] for row in output['items']], list('abcde'))

    def test_deadline_prevents_queued_dispatch(self):
        with patch.object(d, '_read_key', return_value='key'), patch.object(d.time, 'monotonic', side_effect=[0, 6, 6]), \
                patch.object(d, '_run_decision_worker') as worker:
            output = d.evaluate_batch({'items': [item('a')], 'deadline_seconds': 5})
        worker.assert_not_called()
        self.assertEqual(output['attempted_calls'], 0)
        self.assertEqual(output['errors'], 1)

    def test_deduplicates_and_resolves_credentials_once(self):
        with patch.object(d, '_read_key', return_value='PRIVATE') as key, \
                patch.object(d, '_run_decision_worker', return_value=result()) as worker:
            output = d.evaluate_batch({'items': [item('a'), item('b'), item('c', 'different')]})
        self.assertEqual(worker.call_count, 2)
        key.assert_called_once()
        self.assertEqual([v['id'] for v in output['items']], ['a', 'b', 'c'])
        self.assertTrue(output['items'][1]['reused'])
        self.assertEqual(output['usage']['cost'], 0.002)
        self.assertNotIn('PRIVATE', json.dumps(output))

    def test_budget_and_invalid_items_cannot_start_extra_calls(self):
        with patch.object(d, '_read_key', return_value='key'), \
                patch.object(d, '_run_decision_worker', return_value=result()) as worker:
            output = d.evaluate_batch({'items': [item('a'), item('b', 'new'),
                {'id': 'c', 'profile': 'missing', 'state': 'x'}], 'max_calls': 1})
        self.assertEqual(worker.call_count, 1)
        self.assertIn('error', output['items'][1])
        self.assertIn('error', output['items'][2])
        self.assertEqual(output['errors'], 2)

    def test_invalid_manifest_rejected_before_credentials(self):
        for manifest in ({'items': []}, {'items': [item('a'), item('a')]},
                         {'items': [item('a')], 'concurrency': 20},
                         {'items': [item('a')], 'max_calls': True},
                         {'items': [item('a')], 'deadline_seconds': 1000},
                         {'items': [item('a')], 'api_key': 'SECRET'}):
            with self.subTest(manifest=manifest), patch.object(d, '_read_key') as key:
                with self.assertRaises(d.DecisionError):
                    d.evaluate_batch(manifest)
                key.assert_not_called()

    def test_partial_failure_remains_error(self):
        with patch.object(d, '_read_key', return_value='key'), \
                patch.object(d, '_run_decision_worker', side_effect=[d.DecisionError('Provider unavailable.'), result()]):
            output = d.evaluate_batch({'items': [item('a'), item('b', 'new')], 'concurrency': 1})
        self.assertEqual(output['errors'], 1)
        self.assertNotIn('result', output['items'][0])
        self.assertEqual(output['items'][1]['result']['decision'], 'relevant')

    def test_missing_cost_marks_successful_usage_incomplete(self):
        unknown = result()
        del unknown['usage']['cost']
        for outcomes in ([unknown], [result(), unknown], [unknown, result()]):
            with self.subTest(calls=len(outcomes)), patch.object(d, '_read_key', return_value='key'), \
                    patch.object(d, '_run_decision_worker', side_effect=outcomes):
                output = d.evaluate_batch({'items': [item(str(i), str(i)) for i in range(len(outcomes))],
                                           'concurrency': 1})
            self.assertEqual(output['errors'], 0)
            self.assertEqual(output['usage']['input_tokens'], 10 * len(outcomes))
            self.assertIsNone(output['usage']['cost'])
            self.assertFalse(output['usage_complete'])

    def test_known_zero_cost_is_complete(self):
        free = result()
        free['usage']['cost'] = 0
        with patch.object(d, '_read_key', return_value='key'), \
                patch.object(d, '_run_decision_worker', return_value=free):
            output = d.evaluate_batch({'items': [item('a')]})
        self.assertTrue(output['usage_complete'])
        self.assertEqual(output['usage']['cost'], 0)

    def test_worker_timeout_reaps_process_and_keeps_key_out_of_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = Path(directory) / 'slow.py'
            worker.write_text('import time\ntime.sleep(20)\n')
            started = time.monotonic()
            with patch.object(d, 'CLI', worker), self.assertRaises(d.DecisionError):
                d._run_decision_worker(item('a'), 'private-key', 0.1)
            self.assertLess(time.monotonic() - started, 2)
        with patch.object(d.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(result()), '')) as run:
            d._run_decision_worker(item('a'), 'private-key', 1)
        self.assertNotIn('private-key', str(run.call_args.args))
        self.assertEqual(run.call_args.kwargs['env']['OPENROUTER_API_KEY'], 'private-key')

    def test_evaluation_does_not_count_errors_as_correct_and_has_no_empty_pass(self):
        cases = {'items': [{**item('a'), 'expected': 'relevant'}, {**item('b', 'new'), 'expected': 'irrelevant'}]}
        with patch.object(d, '_read_key', return_value='key'), \
                patch.object(d, '_run_decision_worker', side_effect=[result(), d.DecisionError('Unavailable')]):
            output = d.evaluate_cases(cases)
        self.assertEqual(output['evaluation']['total'], 2)
        self.assertEqual(output['evaluation']['correct'], 1)
        self.assertEqual(output['evaluation']['errors'], 1)
        self.assertEqual(output['evaluation']['accuracy'], 0.5)
        with self.assertRaises(d.DecisionError):
            d.evaluate_cases({'items': []})

    def test_dry_run_cli_never_resolves_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, 'XDG_CONFIG_HOME': directory}
            env.pop('OPENROUTER_API_KEY', None)
            done = subprocess.run([str(ROOT / 'Tools/agency-decide'), 'classify-batch', '--input', '-', '--dry-run'],
                                  input=json.dumps({'items': [item('a')]}), text=True, capture_output=True, env=env, timeout=5)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(json.loads(done.stdout)['dry_run'])
