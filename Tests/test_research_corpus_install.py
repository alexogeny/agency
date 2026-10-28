"""Public installed entrypoint and offline skill example interoperability."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class ResearchCorpusInstallTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, PATH=str(ROOT / 'Tools')
                                 + os.pathsep + os.environ.get('PATH', ''))
        environment.start()
        self.addCleanup(environment.stop)

    def test_managed_entrypoint_resolves_modules_via_installed_symlink(self):
        manifest = (ROOT / 'scripts/managed-user-links.tsv').read_text()
        self.assertIn('all\tTools/research-corpus\t.local/bin/research-corpus\n', manifest)
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory) / 'bin' / 'research-corpus'
            installed.parent.mkdir()
            installed.symlink_to(ROOT / 'Tools/research-corpus')
            result = subprocess.run([installed, '--help'], cwd=directory, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for command in ('index', 'audit', 'screening', 'reproduce', 'profiles'):
                self.assertIn(command, result.stdout)

    def test_synthetic_skill_workflow_and_relocated_archived_entrypoint(self):
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory) / 'demo'
            result = subprocess.run(['python3', ROOT / 'Skills/research-corpus/examples/offline-demo.py', task], text=True, capture_output=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(json.loads(result.stdout)['ok'])
            corpus = task / 'relocated'
            manifest = json.loads((corpus / 'manifest.json').read_text())
            archived = corpus / manifest['runs'][0]['software']['path'] / 'research-corpus'
            reproduction = subprocess.run(['python3', archived, 'reproduce', corpus, '--offline', '--output', task / 'archived-reproduction'], cwd=directory, text=True, capture_output=True)
            self.assertEqual(reproduction.returncode, 0, reproduction.stdout + reproduction.stderr)
            self.assertTrue(json.loads(reproduction.stdout)['ok'])


if __name__ == '__main__':
    unittest.main()
