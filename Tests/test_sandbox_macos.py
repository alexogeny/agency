import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "Tools/sandbox-macos"


class MacSandboxPlanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name).resolve()

    def run_plan(self, *args):
        return subprocess.run(
            [sys.executable, ADAPTER, "--workspace", self.workspace, "--dry-run", *args],
            text=True, capture_output=True,
        )

    def test_preview_is_offline_and_does_not_create_state(self):
        result = self.run_plan("--", "printf", "%s", "literal $(text)")
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["backend"], "macos-seatbelt-srt")
        self.assertEqual(plan["command"], ["printf", "%s", "literal $(text)"])
        self.assertEqual(plan["settings"]["filesystem"]["denyRead"], ["/"])
        self.assertEqual(plan["settings"]["network"]["allowedDomains"], [])
        self.assertIn(str(self.workspace), plan["settings"]["filesystem"]["allowWrite"])
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_readonly_workspace_and_domain_grant(self):
        result = self.run_plan("--workspace-ro", "--allow-domain", "example.com", "--", "true")
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertNotIn(str(self.workspace), plan["settings"]["filesystem"]["allowWrite"])
        self.assertEqual(plan["settings"]["network"]["allowedDomains"], ["example.com"])

    def test_unsupported_isolation_is_rejected_before_execution(self):
        for flag, value in (("--publish", "tcp:8080"), ("--name", "another-host")):
            with self.subTest(flag=flag):
                result = self.run_plan(flag, value, "--", "true")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Linux VM", result.stderr)

    def test_glob_shaped_paths_cannot_broaden_access(self):
        path = self.workspace / "wildcard[ab]"
        path.mkdir()
        result = self.run_plan("--rw", str(path), "--", "true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("glob", result.stderr)

    def test_unset_forwarded_variable_is_rejected(self):
        result = self.run_plan("--env", "AGENCY_TEST_UNSET_53E802", "--", "true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unset", result.stderr)

    def test_offline_conflicts_with_network_grants(self):
        result = self.run_plan("--no-internet", "--allow-domain", "example.com", "--", "true")
        self.assertNotEqual(result.returncode, 0)

    def test_macos_internet_requires_explicit_destinations(self):
        result = self.run_plan("--internet", "--", "true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--allow-domain", result.stderr)


if __name__ == "__main__":
    unittest.main()
