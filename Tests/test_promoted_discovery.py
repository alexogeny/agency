import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().with_name('test_promoted_tools.py')


class PromotedToolEntrypointTests(unittest.TestCase):
    def test_standalone_entrypoint_supports_isolated_python(self):
        with tempfile.TemporaryDirectory() as directory:
            for arguments in (('--help',), ('PromotedToolTests.test_perf_diagnose_refuses_an_empty_command',)):
                with self.subTest(arguments=arguments):
                    result = subprocess.run(
                        [sys.executable, '-I', '-B', str(SCRIPT), *arguments],
                        cwd=directory,
                        env={**os.environ, 'AGENCY_TEST_SCRATCH': directory},
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    if arguments == ('--help',):
                        self.assertIn('usage:', result.stdout)
                    else:
                        self.assertIn('Ran 1 test', result.stderr)
