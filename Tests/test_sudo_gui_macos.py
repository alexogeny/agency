import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_backend():
    loader = importlib.machinery.SourceFileLoader("sudo_gui_macos", str(ROOT / "Tools/sudo-gui-macos"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class MacSudoGuiTests(unittest.TestCase):
    def setUp(self):
        self.backend = load_backend()

    def test_custom_prompt_and_shell_arguments_are_data(self):
        prompt = 'Approve "literal" $(do-not-execute)\nsecond line'
        argument = "literal '; $(do-not-execute)"
        with patch.object(self.backend.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "ok\n", "")) as run:
            result = self.backend.authorize(["/usr/bin/printf", "%s", argument], prompt)
        self.assertEqual(result, 0)
        invocation = run.call_args.args[0]
        self.assertEqual(invocation[:2], ["/usr/bin/osascript", "-"])
        self.assertEqual(invocation[-1], prompt)
        self.assertNotIn(prompt, run.call_args.kwargs["input"])
        actual = subprocess.run(["/bin/sh", "-c", invocation[-2]], capture_output=True, text=True)
        self.assertEqual(actual.returncode, 0, actual.stderr)
        self.assertEqual(actual.stdout, argument)

    def test_cancel_returns_130_and_never_retries(self):
        with patch.object(self.backend.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "execution error: User canceled. (-128)\n")) as run:
            result = self.backend.authorize(["/usr/bin/true"], "test")
        self.assertEqual(result, 130)
        self.assertEqual(run.call_count, 1)

    def test_command_failure_retains_exit_status(self):
        with patch.object(self.backend.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "execution error: command failed (7)\n")):
            self.assertEqual(self.backend.authorize(["/usr/bin/false"], "test"), 7)

    def test_sudo_options_cannot_silently_change_the_authorized_identity(self):
        for arguments in (["-u", "another-user", "id"], ["-S", "id"], ["-v"], []):
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    self.backend.sudo_arguments(arguments)
        self.assertEqual(self.backend.sudo_arguments(["--", "/usr/bin/id", "-u"]), ["/usr/bin/id", "-u"])

    def test_failed_authorization_latches_for_remaining_workflow(self):
        with tempfile.TemporaryDirectory() as temporary:
            failure = Path(temporary) / "failure"
            with patch.dict(self.backend.os.environ, {"SUDO_GUI_FAILURE_FILE": str(failure)}):
                with patch.object(self.backend, "authorize", return_value=130) as authorize:
                    self.assertEqual(self.backend.proxy(["/usr/bin/true"], "test"), 130)
                    self.assertEqual(self.backend.proxy(["/usr/bin/true"], "test"), 130)
                self.assertEqual(authorize.call_count, 1)

    def test_workflow_runs_as_user_with_only_path_sudo_redirected(self):
        with patch.object(self.backend.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(self.backend.workflow(["/bin/sh", "approved.sh"], "custom reason"), 0)
        self.assertEqual(run.call_args.args[0], ["/bin/sh", "approved.sh"])
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["SUDO_GUI_PROMPT"], "custom reason")
        self.assertEqual(environment["SUDO_GUI_PROXY_MODE"], "1")
        self.assertNotEqual(environment["HOME"], "/var/root")


if __name__ == "__main__":
    unittest.main()
