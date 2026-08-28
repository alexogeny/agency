import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FISH_CONFIG = ROOT / "config/fish/config.fish"
SCRATCH = Path.home() / "Scratch"


class GitPullFunctionTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.workspace = Path(self.temporary.name)
        self.remote = self.workspace / "remote.git"
        self.seed = self.workspace / "seed"
        self.checkout = self.workspace / "checkout"
        self.home = self.workspace / "home"
        self.home.mkdir()

        self.git("init", "--bare", str(self.remote))
        self.git("init", "--initial-branch=main", str(self.seed))
        self.git("-C", str(self.seed), "config", "user.name", "Test Fixture")
        self.git("-C", str(self.seed), "config", "user.email", "fixture@example.invalid")
        self.git("-C", str(self.seed), "commit", "--allow-empty", "-m", "fixture")
        self.git("-C", str(self.seed), "remote", "add", "origin", str(self.remote))
        self.git("-C", str(self.seed), "push", "--set-upstream", "origin", "main")
        self.git("-C", str(self.remote), "symbolic-ref", "HEAD", "refs/heads/main")
        self.git("-C", str(self.seed), "switch", "-c", "test/pruned-upstream")
        self.git(
            "-C",
            str(self.seed),
            "push",
            "--set-upstream",
            "origin",
            "test/pruned-upstream",
        )
        self.git("clone", str(self.remote), str(self.checkout))
        self.git(
            "-C",
            str(self.checkout),
            "switch",
            "--track",
            "-c",
            "test/pruned-upstream",
            "origin/test/pruned-upstream",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *arguments, check=True):
        return subprocess.run(
            ["git", *arguments],
            check=check,
            text=True,
            capture_output=True,
        )

    def gpl(self):
        environment = os.environ.copy()
        environment["HOME"] = str(self.home)
        command = f"source {FISH_CONFIG}; cd {self.checkout}; gpl"
        return subprocess.run(
            ["fish", "--no-config", "--interactive", "--command", command],
            text=True,
            capture_output=True,
            env=environment,
        )

    def current_branch(self):
        return self.git(
            "-C", str(self.checkout), "branch", "--show-current"
        ).stdout.strip()

    def test_fast_forwards_existing_upstream_without_switching(self):
        result = self.gpl()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.current_branch(), "test/pruned-upstream")

    def test_deleted_upstream_switches_to_remote_default_and_keeps_local_branch(self):
        self.git(
            "-C",
            str(self.remote),
            "update-ref",
            "-d",
            "refs/heads/test/pruned-upstream",
        )
        self.git("-C", str(self.checkout), "branch", "-D", "main")

        result = self.gpl()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.current_branch(), "main")
        self.assertIn("was deleted; switching to 'main'", result.stdout)
        self.assertEqual(
            self.git(
                "-C", str(self.checkout), "rev-parse", "--abbrev-ref", "@{upstream}"
            ).stdout.strip(),
            "origin/main",
        )
        self.assertEqual(
            self.git(
                "-C",
                str(self.checkout),
                "show-ref",
                "--verify",
                "--quiet",
                "refs/heads/test/pruned-upstream",
                check=False,
            ).returncode,
            0,
        )


if __name__ == "__main__":
    unittest.main()
