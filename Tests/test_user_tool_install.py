import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_INSTALLER = ROOT / "scripts/install-agent-clis.sh"
PYTHON_INSTALLER = ROOT / "scripts/install-python-tools.sh"
RUST_INSTALLER = ROOT / "scripts/install-rust.sh"
SCRATCH = Path(os.environ.get("AGENCY_TEST_SCRATCH", ROOT / ".cache/tests"))


class UserToolInstallTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.workspace = Path(self.temporary.name)
        self.bin = self.workspace / "bin"
        self.bin.mkdir()
        self.log = self.workspace / "commands.log"
        (self.bin / "bash").symlink_to("/usr/bin/bash")

    def tearDown(self):
        self.temporary.cleanup()

    def executable(self, name, source):
        path = self.bin / name
        path.write_text(textwrap.dedent(source).lstrip())
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def environment(self):
        return {
            **os.environ,
            "PATH": str(self.bin),
            "AGENCY_TEST_LOG": str(self.log),
            "AGENCY_UV_TOOL_PYTHON": "/usr/bin/python3",
        }

    def install_runner(self, name):
        self.executable(
            name,
            """
            #!/usr/bin/env bash
            printf '%s %s\n' "${0##*/}" "$*" >> "$AGENCY_TEST_LOG"
            """,
        )

    def installed_tools(self):
        for name in ("codex", "claude", "pi", "gantry", "thoreau", "podman-compose"):
            self.executable(name, "#!/usr/bin/env bash\nexit 0\n")

    def run_installer(self, installer, *arguments):
        return subprocess.run(
            [installer, *arguments],
            check=False,
            text=True,
            capture_output=True,
            env=self.environment(),
        )

    def test_existing_tools_are_retained_with_an_update_warning(self):
        self.installed_tools()
        self.install_runner("bun")
        self.install_runner("uv")

        agent_result = self.run_installer(AGENT_INSTALLER)
        python_result = self.run_installer(PYTHON_INSTALLER)

        self.assertEqual(agent_result.returncode, 0, agent_result.stderr)
        self.assertEqual(python_result.returncode, 0, python_result.stderr)
        self.assertFalse(self.log.exists())
        warning = agent_result.stdout + python_result.stdout
        for name in ("Codex", "Claude Code", "Pi", "Gantry", "Thoreau", "podman-compose"):
            self.assertIn(name, warning)
        self.assertIn("./install.sh --update", warning)

    def test_missing_tools_are_installed_without_requesting_an_upgrade(self):
        self.install_runner("bun")
        self.install_runner("uv")

        agent_result = self.run_installer(AGENT_INSTALLER)
        python_result = self.run_installer(PYTHON_INSTALLER)

        self.assertEqual(agent_result.returncode, 0, agent_result.stderr)
        self.assertEqual(python_result.returncode, 0, python_result.stderr)
        log = self.log.read_text()
        self.assertIn("bun add --global @openai/codex @anthropic-ai/claude-code", log)
        self.assertIn(
            "bun add --global --ignore-scripts @earendil-works/pi-coding-agent",
            log,
        )
        self.assertIn("uv tool install --python /usr/bin/python3", log)
        self.assertNotIn("--upgrade", log)

    def test_update_reinstalls_managed_tools(self):
        self.installed_tools()
        self.install_runner("bun")
        self.install_runner("uv")

        agent_result = self.run_installer(AGENT_INSTALLER, "--update")
        python_result = self.run_installer(PYTHON_INSTALLER, "--update")

        self.assertEqual(agent_result.returncode, 0, agent_result.stderr)
        self.assertEqual(python_result.returncode, 0, python_result.stderr)
        log = self.log.read_text()
        self.assertIn("bun add --global @openai/codex @anthropic-ai/claude-code", log)
        self.assertIn(
            "bun add --global --ignore-scripts @earendil-works/pi-coding-agent",
            log,
        )
        self.assertEqual(log.count("uv tool install"), 3)
        self.assertEqual(log.count("--upgrade"), 3)

    def test_existing_stable_rust_is_retained_with_an_update_warning(self):
        self.executable(
            "rustup",
            """
            #!/usr/bin/env bash
            printf 'rustup %s\n' "$*" >> "$AGENCY_TEST_LOG"
            if [[ $* == 'toolchain list' ]]; then
              printf 'stable-x86_64-unknown-linux-gnu (active, default)\n'
            fi
            """,
        )

        result = self.run_installer(RUST_INSTALLER)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().splitlines(), ["rustup toolchain list"])
        self.assertIn("stable Rust", result.stdout)
        self.assertIn("./install.sh --update", result.stdout)

    def test_update_refreshes_existing_stable_rust(self):
        self.executable(
            "rustup",
            """
            #!/usr/bin/env bash
            printf 'rustup %s\n' "$*" >> "$AGENCY_TEST_LOG"
            if [[ $* == 'toolchain list' ]]; then
              printf 'stable-x86_64-unknown-linux-gnu (active, default)\n'
            fi
            """,
        )

        result = self.run_installer(RUST_INSTALLER, "--update")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.log.read_text().splitlines(),
            ["rustup toolchain list", "rustup update stable"],
        )

    def test_stable_rust_becomes_default_when_the_step_is_incomplete(self):
        self.executable(
            "rustup",
            """
            #!/usr/bin/env bash
            printf 'rustup %s\n' "$*" >> "$AGENCY_TEST_LOG"
            if [[ $* == 'toolchain list' ]]; then
              printf 'nightly-x86_64-unknown-linux-gnu (active, default)\n'
            fi
            """,
        )

        result = self.run_installer(RUST_INSTALLER)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.log.read_text().splitlines(),
            ["rustup toolchain list", "rustup default stable"],
        )


if __name__ == "__main__":
    unittest.main()
