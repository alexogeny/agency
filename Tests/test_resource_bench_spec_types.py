from contextlib import redirect_stderr
import io
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest


TOOL = Path(__file__).resolve().parents[1] / 'Tools' / 'resource-bench'
READ_SPEC = runpy.run_path(str(TOOL))['read_spec']
DIAGNOSTICS = {
    'cpu': 'cpu must be a non-negative integer',
    'runs': 'runs must be an integer of at least 3',
    'warmups': 'warmups must be an integer of at least 1',
    'sample_interval_ms': 'sample_interval_ms must be a positive integer',
}


class ResourceBenchSpecTypesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'benchmark.toml'

    def write(self, values):
        values = {'cpu': '0', **values}
        self.path.write_text('name = "fixture"\n' + '\n'.join(f'{key} = {value}' for key, value in values.items()) + '\n[baseline]\ncommand = ["unused"]\n[candidate]\ncommand = ["unused"]\n')

    def test_booleans_are_rejected_as_integer_settings(self):
        for field, message in DIAGNOSTICS.items():
            for boolean in ('true', 'false'):
                with self.subTest(field=field, value=boolean):
                    self.write({field: boolean})
                    error = io.StringIO()
                    with redirect_stderr(error), self.assertRaises(SystemExit) as caught:
                        READ_SPEC(self.path)
                    self.assertEqual(caught.exception.code, 2)
                    self.assertTrue(error.getvalue().endswith(message + '\n'))

    def test_integer_boundaries_and_defaults_are_preserved(self):
        for values, expected in [
            ({}, {'cpu': 0, 'runs': 7, 'warmups': 2, 'sample_interval_ms': 5}),
            ({'cpu': '2', 'runs': '3', 'warmups': '1', 'sample_interval_ms': '1'},
             {'cpu': 2, 'runs': 3, 'warmups': 1, 'sample_interval_ms': 1}),
        ]:
            self.write(values)
            spec = READ_SPEC(self.path)
            self.assertEqual({key: spec[key] for key in expected}, expected)
            self.assertTrue(all(type(spec[key]) is int for key in expected))

    def test_existing_invalid_numeric_diagnostics_are_preserved(self):
        for field, minimum in [('cpu', 0), ('runs', 3), ('warmups', 1), ('sample_interval_ms', 1)]:
            for value in (str(minimum - 1), str(float(minimum)), '"1"'):
                with self.subTest(field=field, value=value):
                    self.write({field: value})
                    error = io.StringIO()
                    with redirect_stderr(error), self.assertRaises(SystemExit) as caught:
                        READ_SPEC(self.path)
                    self.assertEqual(caught.exception.code, 2)
                    self.assertTrue(error.getvalue().endswith(DIAGNOSTICS[field] + '\n'))

    def test_cli_rejects_boolean_before_running_commands(self):
        self.write({'cpu': 'true'})
        result = subprocess.run([sys.executable, TOOL, self.path, '--dry-run'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertTrue(result.stderr.endswith(DIAGNOSTICS['cpu'] + '\n'))
