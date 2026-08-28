import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "Tools/sudo-gui"
SCRATCH = Path(os.environ.get("AGENCY_TEST_SCRATCH", ROOT / ".cache/tests"))


class SudoGuiTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.workspace = Path(self.temporary.name)
        self.bin = self.workspace / "bin"
        self.bin.mkdir()
        self.calls = self.workspace / "calls"
        self.calls.mkdir()
        self.config = self.workspace / "faillock.conf"
        self.config.write_text("deny = 3\nunlock_time = 600\nfail_interval = 900\n")

    def tearDown(self):
        self.temporary.cleanup()

    def write_executable(self, name, body):
        path = self.bin / name
        path.write_text(f"#!/usr/bin/env bash\nset -euo pipefail\n{body}\n")
        path.chmod(0o755)
        return path

    def environment(self, **values):
        return {
            **os.environ,
            "SUDO_GUI_KDIALOG": str(self.bin / "kdialog"),
            "SUDO_GUI_SUDO": str(self.bin / "sudo"),
            "SUDO_GUI_FAILLOCK": str(self.bin / "faillock"),
            "SUDO_GUI_FAILLOCK_CONFIG": str(self.config),
            "SUDO_GUI_TEST_CALLS": str(self.calls),
            **values,
        }

    def run_tool(self, *arguments, **environment):
        return subprocess.run(
            [TOOL, *arguments],
            text=True,
            capture_output=True,
            env=self.environment(**environment),
        )

    def test_one_password_dialog_authorizes_and_runs_same_session_command(self):
        self.write_executable(
            "kdialog",
            'printf "%s\\n" "$*" >> "$SUDO_GUI_TEST_CALLS/kdialog"\n'
            'if [[ " $* " == *" --password "* ]]; then printf "correct horse\\n"; fi',
        )
        self.write_executable("faillock", "exit 0")
        self.write_executable(
            "sudo",
            'printf "%s\\n" "$*" >> "$SUDO_GUI_TEST_CALLS/sudo"\n'
            'if [[ ${1:-} == -n ]]; then\n'
            '  [[ -e "$SUDO_GUI_TEST_CALLS/authorized" ]]\n'
            'elif [[ ${1:-} == -S ]]; then\n'
            '  IFS= read -r password\n'
            '  printf "%s" "$password" > "$SUDO_GUI_TEST_CALLS/password"\n'
            '  touch "$SUDO_GUI_TEST_CALLS/authorized"\n'
            'fi',
        )
        command = self.write_executable(
            "after-auth", 'printf "ran\\n" > "$SUDO_GUI_TEST_CALLS/command"'
        )

        result = self.run_tool("--", command)

        self.assertEqual(result.returncode, 0, result.stderr)
        dialogs = (self.calls / "kdialog").read_text().splitlines()
        self.assertEqual(sum("--password" in line for line in dialogs), 1)
        self.assertEqual((self.calls / "password").read_text(), "correct horse")
        self.assertEqual((self.calls / "command").read_text(), "ran\n")
        self.assertNotIn("correct horse", result.stdout + result.stderr)

    def test_cancel_does_not_call_sudo_with_a_password(self):
        self.write_executable("kdialog", "exit 1")
        self.write_executable("faillock", "exit 0")
        self.write_executable(
            "sudo",
            'printf "%s\\n" "$*" >> "$SUDO_GUI_TEST_CALLS/sudo"\nexit 1',
        )

        result = self.run_tool()

        self.assertEqual(result.returncode, 130)
        self.assertEqual((self.calls / "sudo").read_text().splitlines(), ["-n true"])

    def test_active_faillock_refuses_without_opening_password_dialog(self):
        now = subprocess.run(
            ["date", "+%F %T"], check=True, text=True, capture_output=True
        ).stdout.strip()
        self.write_executable(
            "faillock",
            'printf "user:\\nWhen Type Source Valid\\n"\n'
            f'printf "{now} TTY test V\\n%.0s" {{1..3}}',
        )
        self.write_executable(
            "kdialog", 'printf "called\\n" > "$SUDO_GUI_TEST_CALLS/kdialog"'
        )
        self.write_executable("sudo", "exit 1")

        result = self.run_tool()

        self.assertEqual(result.returncode, 75)
        self.assertFalse((self.calls / "kdialog").exists())
        self.assertIn("locked", result.stderr)


if __name__ == "__main__":
    unittest.main()
