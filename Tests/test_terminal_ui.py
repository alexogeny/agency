import os
import pty
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "Tools/agency-ui"
GIT_GET = ROOT / "Tools/git-get"
SCRATCH = Path(os.environ.get("AGENCY_TEST_SCRATCH", ROOT / ".cache/tests"))


class TerminalUiTests(unittest.TestCase):
    def run_ui(self, *arguments, check=True, environment=None):
        return subprocess.run(
            [UI, *arguments],
            check=check,
            text=True,
            capture_output=True,
            env={**os.environ, **(environment or {})},
        )

    def run_ui_tty(self, *arguments, environment=None, interrupt_after=None):
        master, slave = pty.openpty()
        child_environment = os.environ.copy()
        for name in ("AGENCY_UI", "AGENCY_MOTION", "CI", "NO_COLOR"):
            child_environment.pop(name, None)
        child_environment.update(environment or {})
        child_environment["TERM"] = "xterm-256color"
        process = subprocess.Popen(
            [UI, *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=slave,
            env=child_environment,
        )
        os.close(slave)
        if interrupt_after is not None:
            time.sleep(interrupt_after)
            process.send_signal(signal.SIGINT)
        output = bytearray()
        while True:
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            output.extend(chunk)
        os.close(master)
        stdout, _ = process.communicate(timeout=2)
        return process.returncode, stdout, output.decode()

    def test_plain_status_is_stable_and_colour_free(self):
        result = self.run_ui(
            "status",
            "phase",
            "Preparing workspace",
            environment={"AGENCY_UI": "plain"},
        )

        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "◇ Preparing workspace\n")
        self.assertNotIn("\x1b", result.stderr)

    def test_successful_run_collapses_captured_output(self):
        result = self.run_ui(
            "run",
            "--capture",
            "--label",
            "Preparing workspace",
            "--success",
            "Workspace ready",
            "--",
            sys.executable,
            "-c",
            "import sys; print('detail'); print('diagnostic', file=sys.stderr)",
            environment={"AGENCY_UI": "plain"},
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("◇ Preparing workspace", result.stderr)
        self.assertIn("✓ Workspace ready", result.stderr)
        self.assertNotIn("detail", result.stderr)
        self.assertNotIn("diagnostic", result.stderr)

    def test_passthrough_keeps_stdout_available_as_data(self):
        result = self.run_ui(
            "run",
            "--label",
            "Reading value",
            "--success",
            "Value ready",
            "--",
            sys.executable,
            "-c",
            "print('machine-value')",
            environment={"AGENCY_UI": "plain"},
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "machine-value\n")
        self.assertIn("✓ Value ready", result.stderr)

    def test_quiet_mode_suppresses_success_presentation(self):
        result = self.run_ui(
            "run",
            "--capture",
            "--label",
            "Preparing workspace",
            "--success",
            "Workspace ready",
            "--",
            sys.executable,
            "-c",
            "pass",
            environment={"AGENCY_UI": "quiet"},
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_failed_run_replays_output_and_preserves_status(self):
        result = self.run_ui(
            "run",
            "--capture",
            "--label",
            "Preparing workspace",
            "--failure",
            "Workspace preparation failed",
            "--",
            sys.executable,
            "-c",
            "import sys; print('partial'); print('broken', file=sys.stderr); raise SystemExit(7)",
            check=False,
            environment={"AGENCY_UI": "plain"},
        )

        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout, "partial\n")
        self.assertIn("broken", result.stderr)
        self.assertIn("✕ Workspace preparation failed", result.stderr)

    def test_tty_run_animates_then_settles_to_one_result(self):
        returncode, stdout, rendered = self.run_ui_tty(
            "run",
            "--capture",
            "--label",
            "Polishing output",
            "--success",
            "Output polished",
            "--",
            sys.executable,
            "-c",
            "import time; time.sleep(0.24)",
        )

        self.assertEqual(returncode, 0)
        self.assertEqual(stdout, b"")
        self.assertIn("\r", rendered)
        self.assertIn("\x1b[2K", rendered)
        self.assertIn("Polishing output", rendered)
        self.assertIn("✓", rendered)
        self.assertIn("Output polished", rendered)

    def test_reduced_motion_uses_static_phases_on_a_tty(self):
        returncode, _, rendered = self.run_ui_tty(
            "run",
            "--capture",
            "--label",
            "Preparing workspace",
            "--success",
            "Workspace ready",
            "--",
            sys.executable,
            "-c",
            "pass",
            environment={"AGENCY_MOTION": "reduce"},
        )

        self.assertEqual(returncode, 0)
        self.assertNotIn("\x1b[2K", rendered)
        self.assertIn("Preparing workspace", rendered)
        self.assertIn("Workspace ready", rendered)

    def test_interrupt_clears_animation_and_stops_the_child(self):
        returncode, _, rendered = self.run_ui_tty(
            "run",
            "--capture",
            "--label",
            "Waiting gracefully",
            "--",
            sys.executable,
            "-c",
            "import time; time.sleep(10)",
            interrupt_after=0.16,
        )

        self.assertEqual(returncode, 130)
        self.assertIn("\x1b[2K", rendered)
        self.assertIn("Cancelled Waiting gracefully", rendered)


class GitGetPresentationTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.workspace = Path(self.temporary.name)
        self.remote = self.workspace / "remote.git"
        self.seed = self.workspace / "seed"
        self.code = self.workspace / "code"
        self.git("init", "--bare", self.remote)
        self.git("init", "--initial-branch=main", self.seed)
        self.git("-C", self.seed, "config", "user.name", "Test Fixture")
        self.git(
            "-C",
            self.seed,
            "config",
            "user.email",
            "fixture@example.invalid",
        )
        self.git("-C", self.seed, "commit", "--allow-empty", "-m", "fixture")
        self.git("-C", self.seed, "remote", "add", "origin", self.remote)
        self.git("-C", self.seed, "push", "--set-upstream", "origin", "main")
        self.git("-C", self.remote, "symbolic-ref", "HEAD", "refs/heads/main")

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *arguments):
        return subprocess.run(
            ["git", *map(str, arguments)],
            check=True,
            text=True,
            capture_output=True,
        )

    def git_get(self):
        return subprocess.run(
            [GIT_GET, f"file://{self.remote}"],
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "AGENCY_UI": "plain",
                "CODE_ROOT": str(self.code),
                "PATH": f"{ROOT / 'Tools'}:{os.environ['PATH']}",
            },
        )

    def test_clone_and_update_have_compact_phased_output(self):
        clone = self.git_get()

        self.assertEqual(clone.returncode, 0, clone.stderr)
        self.assertEqual(clone.stdout, f"{self.code / 'remote'}\n")
        self.assertIn("◇ Adding remote", clone.stderr)
        self.assertIn("✓ remote is ready", clone.stderr)
        self.assertNotIn("Cloning into", clone.stderr)

        update = self.git_get()

        self.assertEqual(update.returncode, 0, update.stderr)
        self.assertEqual(update.stdout, f"{self.code / 'remote'}\n")
        self.assertIn("◇ Refreshing remote", update.stderr)
        self.assertIn("✓ remote is current", update.stderr)
        self.assertNotIn("Already up to date", update.stderr)


if __name__ == "__main__":
    unittest.main()
