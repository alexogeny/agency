import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install-1password.sh"
SCRATCH = Path(os.environ.get("AGENCY_TEST_SCRATCH", ROOT / ".cache/tests"))


class OnePasswordInstallTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.workspace = Path(self.temporary.name)
        self.home = self.workspace / "home"
        self.home.mkdir()
        self.bin = self.workspace / "bin"
        self.bin.mkdir()
        self.log = self.workspace / "commands.log"
        self.cli_installed = self.workspace / "cli-installed"
        for name in ("bash", "cat", "chmod", "find", "mkdir", "mktemp", "rm", "touch"):
            (self.bin / name).symlink_to(Path("/usr/bin") / name)

    def tearDown(self):
        self.temporary.cleanup()

    def executable(self, name, source):
        path = self.bin / name
        path.write_text(textwrap.dedent(source).lstrip())
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def environment(self):
        return {
            **os.environ,
            "HOME": str(self.home),
            "PATH": str(self.bin),
            "AGENCY_TEST_LOG": str(self.log),
            "AGENCY_TEST_CLI_INSTALLED": str(self.cli_installed),
            "AGENCY_TEST_BIN": str(self.bin),
        }

    def run_installer(self, *arguments):
        return subprocess.run(
            [INSTALLER, *arguments],
            check=False,
            text=True,
            capture_output=True,
            env=self.environment(),
        )

    def installed_commands(self):
        self.executable("1password", "#!/usr/bin/env bash\nexit 0\n")
        self.executable("op", "#!/usr/bin/env bash\nexit 0\n")

    def package_query(self, cli_installed):
        if cli_installed:
            self.cli_installed.touch()
        self.executable(
            "pacman",
            r"""
            #!/usr/bin/env bash
            printf 'pacman %s\n' "$*" >> "$AGENCY_TEST_LOG"
            if [[ ${1:-} == -Q && ${2:-} == 1password ]]; then
              exit 0
            fi
            if [[ ${1:-} == -Q && ${2:-} == 1password-cli ]]; then
              [[ -e $AGENCY_TEST_CLI_INSTALLED ]]
              exit
            fi
            exit 2
            """,
        )

    def build_tools(self):
        self.executable("curl", "#!/usr/bin/env bash\nprintf 'key fixture\\n'\n")
        self.executable("gpg", "#!/usr/bin/env bash\ncat >/dev/null\n")
        self.executable(
            "git",
            r"""
            #!/usr/bin/env bash
            set -euo pipefail
            printf 'git %s\n' "$*" >> "$AGENCY_TEST_LOG"
            if [[ ${1:-} == clone ]]; then
              target=${@: -1}
              mkdir -p "$target"
              printf 'pkgname=%s\n' "${target##*/}" > "$target/PKGBUILD"
              exit
            fi
            if [[ ${1:-} == -C && ${3:-} == cat-file ]]; then
              exit
            fi
            if [[ ${1:-} == -C && ${3:-} == rev-parse ]]; then
              if [[ $2 == */1password ]]; then
                printf '%s\n' e323d0d1f8dea6b75bb651ce14acc73904cd0326
              else
                printf '%s\n' b0d208821677a5dbb883a8b92f06a5c92b9e861a
              fi
              exit
            fi
            exit 2
            """,
        )
        self.executable(
            "makepkg",
            r"""
            #!/usr/bin/env bash
            printf 'makepkg cwd=%s args=%s\n' "$PWD" "$*" >> "$AGENCY_TEST_LOG"
            package=${PWD##*/}
            printf 'fixture\n' > "$PWD/$package-1-1-x86_64.pkg.tar.zst"
            """,
        )
        self.executable(
            "sudo",
            r"""
            #!/usr/bin/env bash
            if [[ ${1:-} == -n && ${2:-} == true ]]; then
              exit 0
            fi
            printf 'sudo %s\n' "$*" >> "$AGENCY_TEST_LOG"
            touch "$AGENCY_TEST_CLI_INSTALLED"
            if [[ $* == *1password-cli* ]]; then
              printf '#!/usr/bin/env bash\nexit 0\n' > "$AGENCY_TEST_BIN/op"
              chmod +x "$AGENCY_TEST_BIN/op"
            fi
            """,
        )

    def test_missing_cli_package_is_installed_even_when_commands_exist(self):
        self.installed_commands()
        self.package_query(cli_installed=False)
        self.build_tools()

        result = self.run_installer()

        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log.read_text()
        self.assertIn("aur.archlinux.org/1password-cli.git", log)
        self.assertIn("b0d208821677a5dbb883a8b92f06a5c92b9e861a", log)
        self.assertNotIn("aur.archlinux.org/1password.git", log)
        self.assertIn("sudo pacman -U --noconfirm", log)

    def test_missing_cli_command_rebuilds_its_installed_package(self):
        self.executable("1password", "#!/usr/bin/env bash\nexit 0\n")
        self.package_query(cli_installed=True)
        self.build_tools()

        result = self.run_installer()

        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log.read_text()
        self.assertIn("aur.archlinux.org/1password-cli.git", log)
        self.assertIn("b0d208821677a5dbb883a8b92f06a5c92b9e861a", log)
        self.assertNotIn("aur.archlinux.org/1password.git", log)
        self.assertNotIn("--needed", log)

    def test_existing_packages_are_retained_with_an_update_warning(self):
        self.installed_commands()
        self.package_query(cli_installed=True)
        for name in ("curl", "git", "gpg", "makepkg", "sudo"):
            self.executable(name, "#!/usr/bin/env bash\nexit 97\n")

        result = self.run_installer()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1Password desktop", result.stdout)
        self.assertIn("1Password CLI", result.stdout)
        self.assertIn("./install.sh --update", result.stdout)

    def test_update_rebuilds_both_packages(self):
        self.installed_commands()
        self.package_query(cli_installed=True)
        self.build_tools()

        result = self.run_installer("--update")

        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log.read_text()
        self.assertIn("aur.archlinux.org/1password.git", log)
        self.assertIn("aur.archlinux.org/1password-cli.git", log)
        self.assertIn("e323d0d1f8dea6b75bb651ce14acc73904cd0326", log)
        self.assertIn("b0d208821677a5dbb883a8b92f06a5c92b9e861a", log)
        self.assertEqual(log.count("sudo pacman -U --noconfirm"), 2)


if __name__ == "__main__":
    unittest.main()
