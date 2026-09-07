import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


UI = Path(__file__).resolve().parents[1] / "Tools" / "agency-ui"


class TerminalUiSpawnErrorTests(unittest.TestCase):
    def run_ui(self, command, mode="plain", capture=False):
        arguments = [
            sys.executable, str(UI), "run", "--label", "Run fixture",
            "--failure", "Configured failure", "--success", "Fixture done",
            "--indent", "2",
        ]
        if capture:
            arguments.append("--capture")
        return subprocess.run(
            [*arguments, "--", *map(str, command)],
            env=dict(os.environ, AGENCY_UI=mode),
            text=True, capture_output=True, timeout=5,
        )

    def test_spawn_failures_match_capture_and_remain_visible_when_quiet(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            denied = root / "denied"
            denied.write_text("#!/bin/sh\nexit 0\n")
            denied.chmod(0o600)
            malformed = root / "malformed"
            malformed.write_text("not an executable format\n")
            malformed.chmod(0o700)
            for path in (root / "missing", denied, malformed):
                for mode in ("plain", "quiet"):
                    with self.subTest(path=path.name, mode=mode):
                        captured = self.run_ui([path], mode, capture=True)
                        actual = self.run_ui([path], mode)
                        self.assertEqual(captured.returncode, 127)
                        self.assertEqual(actual.returncode, 127)
                        self.assertEqual(actual.stdout, "")
                        self.assertNotIn("Traceback", actual.stderr)
                        self.assertIn("Configured failure:", actual.stderr)
                        self.assertIn(str(path), actual.stderr)
                        errors = [line for line in actual.stderr.splitlines() if "Configured failure:" in line]
                        self.assertEqual(errors, captured.stderr.splitlines())
                        self.assertTrue(errors[0].startswith("  "))
                        if mode == "quiet":
                            self.assertNotIn("Run fixture", actual.stderr)

    def test_successful_passthrough_preserves_stdout(self):
        result = self.run_ui([sys.executable, "-c", "print('machine-value')"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "machine-value\n")
        self.assertIn("Fixture done", result.stderr)

    def test_child_failure_keeps_exit_status_and_configured_message(self):
        result = self.run_ui([sys.executable, "-c", "raise SystemExit(5)"], mode="quiet")
        self.assertEqual(result.returncode, 5)
        self.assertIn("Configured failure", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
