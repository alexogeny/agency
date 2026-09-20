import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PiDecisionUsageTests(unittest.TestCase):
    def test_footer_tracks_a_user_run_across_model_turns_and_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(['bun', str(ROOT / 'Tests/fixtures/pi_decision_usage.ts')],
                capture_output=True, text=True, timeout=15, env={**os.environ,
                    'XDG_RUNTIME_DIR': directory,
                    'AGENCY_DECISION_USAGE_COMMAND': str(ROOT / 'Tools/agency-decision-usage')})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Pi usage lifecycle passed', result.stdout)
