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
            'if [[ ${1:-} == -A ]]; then\n'
            '  password=$("$SUDO_ASKPASS")\n'
            '  printf "%s" "$password" > "$SUDO_GUI_TEST_CALLS/password"\n'
            '  touch "$SUDO_GUI_TEST_CALLS/authorized"\n'
            '  exit 0\n'
            'fi\n'
            'exit 1',
        )
        command = self.write_executable(
            "after-auth",
            'sudo privileged\n'
            'printf "ran\\n" > "$SUDO_GUI_TEST_CALLS/command"',
        )

        result = self.run_tool("--", command)

        self.assertEqual(result.returncode, 0, result.stderr)
        dialogs = (self.calls / "kdialog").read_text().splitlines()
        self.assertEqual(sum("--password" in line for line in dialogs), 1)
        self.assertEqual((self.calls / "password").read_text(), "correct horse")
        self.assertEqual((self.calls / "command").read_text(), "ran\n")
        self.assertNotIn("correct horse", result.stdout + result.stderr)

    def test_nopasswd_true_does_not_skip_authorization_for_requested_command(self):
        self.write_executable(
            "kdialog",
            'printf "%s\\n" "$*" >> "$SUDO_GUI_TEST_CALLS/kdialog"\n'
            'printf "correct horse\\n"',
        )
        self.write_executable("faillock", "exit 0")
        sudo = self.write_executable(
            "sudo",
            'printf "%s\\n" "$*" >> "$SUDO_GUI_TEST_CALLS/sudo"\n'
            'if [[ ${1:-} == -n && ${2:-} == true ]]; then exit 0; fi\n'
            'if [[ ${1:-} == -A ]]; then\n'
            '  password=$("$SUDO_ASKPASS")\n'
            '  printf "%s" "$password" > "$SUDO_GUI_TEST_CALLS/password"\n'
            '  touch "$SUDO_GUI_TEST_CALLS/command"\n'
            '  exit 0\n'
            'fi\n'
            'exit 77',
        )

        result = self.run_tool("--", sudo, "privileged")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.calls / "password").read_text(), "correct horse")
        self.assertTrue((self.calls / "command").exists())
        self.assertEqual(
            sum(
                "--password" in line
                for line in (self.calls / "kdialog").read_text().splitlines()
            ),
            1,
        )

    def test_requested_sudo_does_not_depend_on_a_validate_timestamp(self):
        self.write_executable(
            "kdialog",
            'printf "%s\\n" "$*" >> "$SUDO_GUI_TEST_CALLS/kdialog"\n'
            'printf "correct horse\\n"',
        )
        self.write_executable("faillock", "exit 0")
        sudo = self.write_executable(
            "sudo",
            'printf "%s\\n" "$*" >> "$SUDO_GUI_TEST_CALLS/sudo"\n'
            'if [[ ${1:-} == -n ]]; then exit 1; fi\n'
            'if [[ ${1:-} == -S ]]; then\n'
            '  IFS= read -r password\n'
            '  printf "%s" "$password" > "$SUDO_GUI_TEST_CALLS/validated"\n'
            '  exit 0\n'
            'fi\n'
            'if [[ ${1:-} == -A ]]; then\n'
            '  password=$("$SUDO_ASKPASS")\n'
            '  printf "%s" "$password" > "$SUDO_GUI_TEST_CALLS/password"\n'
            '  touch "$SUDO_GUI_TEST_CALLS/command"\n'
            '  exit 0\n'
            'fi\n'
            'exit 89',
        )

        result = self.run_tool("--", sudo, "privileged")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.calls / "password").read_text(), "correct horse")
        self.assertTrue((self.calls / "command").exists())
        self.assertFalse((self.calls / "validated").exists())

    def test_script_can_pass_nopasswd_probe_then_authorize_later_sudo(self):
        self.write_executable(
            "kdialog",
            'printf "%s\\n" "$*" >> "$SUDO_GUI_TEST_CALLS/kdialog"\n'
            'printf "correct horse\\n"',
        )
        self.write_executable("faillock", "exit 0")
        self.write_executable(
            "sudo",
            'printf "%s\\n" "$*" >> "$SUDO_GUI_TEST_CALLS/sudo"\n'
            'if [[ $* == "-A -n true" ]]; then exit 0; fi\n'
            'if [[ $* == "-A privileged" ]]; then\n'
            '  password=$("$SUDO_ASKPASS")\n'
            '  printf "%s" "$password" > "$SUDO_GUI_TEST_CALLS/password"\n'
            '  exit 0\n'
            'fi\n'
            'exit 1',
        )
        command = self.write_executable(
            "workflow",
            'sudo -n true\n'
            'sudo privileged\n'
            'touch "$SUDO_GUI_TEST_CALLS/command"',
        )

        result = self.run_tool("--", command)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.calls / "password").read_text(), "correct horse")
        self.assertTrue((self.calls / "command").exists())
        self.assertEqual(
            (self.calls / "sudo").read_text().splitlines(),
            ["-A -n true", "-A privileged"],
        )

    def test_existing_authorization_runs_without_a_dialog(self):
        self.write_executable(
            "kdialog", 'printf "called\\n" > "$SUDO_GUI_TEST_CALLS/kdialog"'
        )
        self.write_executable("faillock", "exit 0")
        sudo = self.write_executable(
            "sudo",
            'printf "%s\\n" "$*" > "$SUDO_GUI_TEST_CALLS/sudo"\n'
            'exit 0',
        )

        result = self.run_tool("--", sudo, "privileged")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.calls / "kdialog").exists())
        self.assertEqual((self.calls / "sudo").read_text(), "-A privileged\n")

    def test_sudo_retry_does_not_open_a_second_password_dialog(self):
        self.write_executable(
            "kdialog",
            'printf "%s\\n" "$*" >> "$SUDO_GUI_TEST_CALLS/kdialog"\n'
            'printf "wrong password\\n"',
        )
        self.write_executable("faillock", "exit 0")
        sudo = self.write_executable(
            "sudo",
            '"$SUDO_ASKPASS" >/dev/null\n'
            '"$SUDO_ASKPASS" >/dev/null',
        )

        result = self.run_tool("--", sudo, "privileged")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            sum(
                "--password" in line
                for line in (self.calls / "kdialog").read_text().splitlines()
            ),
            1,
        )
        self.assertIn("only one password attempt", result.stderr)

    def test_cancel_does_not_call_sudo_with_a_password(self):
        self.write_executable("kdialog", "exit 1")
        self.write_executable("faillock", "exit 0")
        self.write_executable(
            "sudo",
            'printf "%s\\n" "$*" >> "$SUDO_GUI_TEST_CALLS/sudo"\n'
            'if [[ ${1:-} == -A ]]; then "$SUDO_ASKPASS" >/dev/null; fi\n'
            'exit 1',
        )

        result = self.run_tool()

        self.assertEqual(result.returncode, 130)
        self.assertEqual(len((self.calls / "sudo").read_text().splitlines()), 1)

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
        self.write_executable(
            "sudo",
            'if [[ ${1:-} == -A ]]; then "$SUDO_ASKPASS" >/dev/null; fi\n'
            'exit 1',
        )

        result = self.run_tool()

        self.assertEqual(result.returncode, 75)
        self.assertFalse((self.calls / "kdialog").exists())
        self.assertIn("locked", result.stderr)


if __name__ == "__main__":
    unittest.main()
