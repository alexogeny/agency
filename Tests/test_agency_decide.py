import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import urllib.error


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('agency_decisions', ROOT / 'Tools/agency_decisions.py')
decisions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(decisions)


def response(profile='context'):
    labels = decisions.PROFILES[profile]['criteria']
    first = next(iter(labels))
    return {'model': 'typesafe/jev-1.13-20260917',
            'answers': {'decision': {'type': 'choice', 'choice': first,
                         'probabilities': {label: float(label == first) for label in labels},
                         'confidence': 0.75}},
            'usage': {'input_tokens': 123, 'output_tokens': 9, 'cost': 0.0001}}


class DecisionsTests(unittest.TestCase):
    def network(self, payload):
        opener = MagicMock()
        stream = io.BytesIO(json.dumps(payload).encode())
        stream.status = 200
        opener.open.return_value = stream
        return patch.object(decisions.urllib.request, 'build_opener', return_value=opener), opener

    def test_profiles_have_version_and_exact_labels(self):
        self.assertEqual(set(decisions.PROFILES), {'skill', 'context', 'update', 'research'})
        self.assertEqual(set(decisions.PROFILES['skill']['criteria']), {
            'docs-verification', 'web-research', 'repo-map', 'perf-diagnosis',
            'benchmark', 'report-writing', 'none', 'unsure'})
        for profile in decisions.PROFILES.values():
            self.assertEqual(profile['version'], '1')
            self.assertTrue(profile['title'])
            self.assertTrue(profile['question'])
            self.assertIn('unsure', profile['criteria'])

    def test_valid_response_and_fixed_request(self):
        mock, opener = self.network(response())
        with mock:
            result = decisions.evaluate({'task': 'fix bug', 'candidate': 'trace'}, 'context', api_key='test-key')
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://openrouter.ai/api/alpha/decisions')
        self.assertEqual(request.get_method(), 'POST')
        body = json.loads(request.data)
        self.assertEqual(body['model'], 'typesafe/jev-1.13')
        self.assertEqual(body['questions']['decision']['type'], 'choice')
        self.assertEqual(result['decision'], 'relevant')
        self.assertEqual(result['confidence'], 0.75)
        self.assertTrue(result['advisory'])
        self.assertEqual(result['profile_version'], '1')
        self.assertGreaterEqual(result['latency_ms'], 0)
        self.assertEqual(result['usage'], response()['usage'])
        self.assertEqual(opener.open.call_count, 1)

    def test_absent_confidence_not_invented(self):
        payload = response()
        del payload['answers']['decision']['confidence']
        mock, _ = self.network(payload)
        with mock:
            self.assertIsNone(decisions.evaluate('x', 'context', api_key='test-key')['confidence'])

    def test_adversarial_responses_rejected(self):
        mutations = [
            lambda p: p['answers']['decision'].update(choice='execute-command'),
            lambda p: p['answers']['decision'].update(choice=['relevant']),
            lambda p: p['answers']['decision'].update(type='score'),
            lambda p: p['answers']['decision'].update(authority=True),
            lambda p: p['answers']['decision'].update(confidence=True),
            lambda p: p['answers']['decision'].update(confidence=float('nan')),
            lambda p: p['answers']['decision'].update(confidence=1.1),
            lambda p: p['answers']['decision']['probabilities'].update(relevant=0.2),
            lambda p: p['answers']['decision']['probabilities'].update(relevant=True),
            lambda p: p['answers']['decision']['probabilities'].update(relevant=-1),
            lambda p: p['answers']['decision']['probabilities'].update(extra=0),
            lambda p: p['answers']['decision']['probabilities'].pop('unsure'),
            lambda p: p['answers']['decision'].update(choice='irrelevant'),
            lambda p: p['answers'].update(other={}),
            lambda p: p.update(model='another/model'),
            lambda p: p.update(error={'message': 'secret'}),
            lambda p: p['usage'].update(cost=-1),
            lambda p: p['usage'].update(input_tokens=True),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                payload = response()
                mutate(payload)
                mock, _ = self.network(payload)
                with mock, self.assertRaises(decisions.DecisionError):
                    decisions.evaluate('x', 'context', api_key='test-key')

    def test_invalid_state_and_timeout_never_connect(self):
        for state in ['', {}, [], None, True, 1, {'x': float('nan')}, {'x': object()}, {1: 'x'}, 'x' * 100000]:
            with self.subTest(state_type=type(state)), patch.object(decisions.urllib.request, 'build_opener') as opener:
                with self.assertRaises(decisions.DecisionError):
                    decisions.evaluate(state, 'context', api_key='test-key')
                opener.assert_not_called()
        for timeout in [0, -1, 31, True, float('nan'), '10']:
            with self.subTest(timeout=timeout), self.assertRaises(decisions.DecisionError):
                decisions.evaluate('x', 'context', api_key='test-key', timeout=timeout)
        with self.assertRaises(decisions.DecisionError):
            decisions.evaluate('x', 'unknown', api_key='test-key')

    def test_missing_key_never_connects(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}, clear=True):
            self.assertFalse(decisions.key_available())
            with patch.object(decisions.urllib.request, 'build_opener') as opener:
                with self.assertRaises(decisions.DecisionError):
                    decisions.evaluate('x', 'context')
                opener.assert_not_called()

    def test_environment_key_precedence(self):
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'env-key'}):
            mock, opener = self.network(response())
            with mock:
                decisions.evaluate('x', 'context')
            self.assertEqual(opener.open.call_args.args[0].get_header('Authorization'), 'Bearer env-key')

    def test_secret_safe_network_errors_and_no_retries(self):
        for error in [urllib.error.URLError('test-secret'),
                      urllib.error.HTTPError('https://host/test-secret', 401, 'test-secret', {}, io.BytesIO(b'test-secret'))]:
            opener = MagicMock()
            opener.open.side_effect = error
            with patch.object(decisions.urllib.request, 'build_opener', return_value=opener):
                with self.assertRaises(decisions.DecisionError) as caught:
                    decisions.evaluate('x', 'context', api_key='test-secret')
                self.assertNotIn('test-secret', str(caught.exception))
                self.assertEqual(opener.open.call_count, 1)

    def test_redirect_handler_refuses_redirect(self):
        handler = decisions.NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, 'redirect', {}, 'https://attacker.invalid'))

    def test_malformed_oversized_and_duplicate_json(self):
        for data in [b'not-json', b'x' * 100000, b'{"answers":{},"answers":{}}', b'\xff', b'{"x":NaN}', b'{"x":Infinity}']:
            opener = MagicMock()
            stream = io.BytesIO(data)
            stream.status = 200
            opener.open.return_value = stream
            with patch.object(decisions.urllib.request, 'build_opener', return_value=opener):
                with self.assertRaises(decisions.DecisionError):
                    decisions.evaluate('x', 'context', api_key='test-key')

    def test_json_input_rejects_nonfinite_values(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'state.json'
            for raw in ['{"x":NaN}', '{"x":Infinity}', '{"x":1,"x":2}']:
                source.write_text(raw)
                with self.subTest(raw=raw), self.assertRaises(decisions.DecisionError):
                    decisions.read_input(str(source))

    def test_cli_symlink_profiles_doctor_and_dry_run(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'agency-decide'
            executable.symlink_to(ROOT / 'Tools/agency-decide')
            env = dict(os.environ, XDG_CONFIG_HOME=directory)
            env.pop('OPENROUTER_API_KEY', None)
            help_result = subprocess.run([str(executable), 'profiles', '--help'],
                                         text=True, capture_output=True, env=env, check=True)
            self.assertNotIn('--json', help_result.stdout)
            for args, input_text in [(['profiles'], ''), (['doctor'], ''),
                                     (['classify', '--profile', 'skill', '--input', '-', '--dry-run'], 'Verify README examples')]:
                done = subprocess.run([str(executable), *args], input=input_text, text=True, capture_output=True, env=env)
                self.assertEqual(done.returncode, 0, done.stderr)
                data = json.loads(done.stdout)
                if args[0] == 'doctor':
                    self.assertFalse(data['configured'])
                if args[0] == 'classify':
                    self.assertTrue(data['dry_run'])
                    self.assertEqual(data['request']['state'], input_text)
            done = subprocess.run([str(executable), 'classify', '--profile', 'context', '--input', '-'],
                                  input='input text', text=True, capture_output=True, env=env)
            self.assertNotEqual(done.returncode, 0)
            self.assertIn('error', json.loads(done.stderr))
            self.assertEqual(done.stdout, '')


if __name__ == '__main__':
    unittest.main()
