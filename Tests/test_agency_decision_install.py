import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DecisionInstallTests(unittest.TestCase):
    def test_dry_run_installs_decision_tools_without_creating_state(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            result = subprocess.run([ROOT / "install.sh", "--dry-run"], capture_output=True, text=True,
                                    env={**os.environ, "HOME": str(home)}, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ("agency-decide", "agency-decide-mcp"):
                self.assertIn(str(home / ".local/bin" / name), result.stdout)
            self.assertIn("agency-decide MCP", result.stdout)
            self.assertIn("decision-routing", result.stdout)
            self.assertIn("OpenRouter local credential", result.stdout)
            self.assertEqual(list(home.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
