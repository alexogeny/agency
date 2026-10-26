import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CASES = (
    ('test_onepassword_install.py', 'OnePasswordInstallTests.test_existing_packages_are_retained_with_an_update_warning'),
    ('test_user_tool_install.py', 'UserToolInstallTests.test_existing_tools_are_retained_with_an_update_warning'),
    ('test_yay_h2load_install.py', 'YayH2loadInstallTests.test_existing_yay_and_h2load_are_only_verified'),
)


class InstallerFixtureEntrypointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def invoke(self, name, argument):
        return subprocess.run(
            [sys.executable, '-I', '-B', str(ROOT / 'Tests' / name), argument],
            cwd=self.directory, env=dict(os.environ, AGENCY_TEST_SCRATCH=str(self.directory)),
            capture_output=True, text=True,
        )

    def test_isolated_standalone_help_preserves_each_entrypoint(self):
        for name, _ in CASES:
            with self.subTest(script=name):
                result = self.invoke(name, '--help')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('usage:', result.stdout.lower())
                self.assertEqual(result.stderr, '')
                self.assertEqual(list(self.directory.iterdir()), [])

    def test_isolated_standalone_invocation_runs_one_existing_case(self):
        for name, case in CASES:
            with self.subTest(script=name):
                result = self.invoke(name, case)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('Ran 1 test', result.stderr)
                self.assertIn('OK', result.stderr)
                self.assertNotIn('skipped', result.stderr)
                self.assertEqual(list(self.directory.iterdir()), [])
