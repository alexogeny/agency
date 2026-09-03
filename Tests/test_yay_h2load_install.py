import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts/install-yay-h2load.sh"
SCRATCH = Path(os.environ.get("AGENCY_TEST_SCRATCH", ROOT / ".cache/tests"))


class YayH2loadInstallTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.workspace = Path(self.temporary.name)
        self.home = self.workspace / "home"
        self.home.mkdir()
        self.bin = self.workspace / "bin"
        self.bin.mkdir()
        self.log = self.workspace / "commands.log"
        for name in (
            "bash",
            "cat",
            "chmod",
            "dirname",
            "grep",
            "mkdir",
            "mktemp",
            "rm",
            "sed",
        ):
            (self.bin / name).symlink_to(Path("/usr/bin") / name)

    def tearDown(self):
        self.temporary.cleanup()

    def executable(self, name, source):
        path = self.bin / name
        path.write_text(textwrap.dedent(source).lstrip())
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def environment(self):
        return {
            **os.environ,
            "HOME": str(self.home),
            "PATH": str(self.bin),
            "AGENCY_TEST_BIN": str(self.bin),
            "AGENCY_TEST_LOG": str(self.log),
        }

    def run_installer(self, *arguments, check=True):
        return subprocess.run(
            [INSTALLER, *arguments],
            check=check,
            text=True,
            capture_output=True,
            env=self.environment(),
        )

    def test_builds_yay_as_user_and_patches_nghttp2_zlib_dependency(self):
        self.executable(
            "git",
            r"""
            #!/usr/bin/env bash
            set -euo pipefail
            printf 'git %s\n' "$*" >> "$AGENCY_TEST_LOG"
            if [[ ${1:-} == clone ]]; then
              target=${@: -1}
              mkdir -p "$target"
              if [[ $* == *nghttp2.git* ]]; then
                printf "pkgname=nghttp2\ndepends=('zlib>=1.2.3')\n" > "$target/PKGBUILD"
              else
                printf 'pkgname=yay\n' > "$target/PKGBUILD"
              fi
              exit
            fi
            if [[ ${1:-} == -C && ${3:-} == cat-file ]]; then
              exit
            fi
            if [[ ${1:-} == -C && ${3:-} == rev-parse ]]; then
              if [[ $2 == *yay.* ]]; then
                printf '%s\n' cb43f84828ab4f9700f7c6f9c6d7a923d4cfaff0
              else
                printf '%s\n' 2f11414698d4a0190de1681f817855d93e29fcd9
              fi
              exit
            fi
            if [[ ${1:-} == -C && ${3:-} == diff ]]; then
              printf '%s\n' 'diff --git a/PKGBUILD b/PKGBUILD'
              exit
            fi
            exit 2
            """,
        )
        self.executable(
            "makepkg",
            r"""
            #!/usr/bin/env bash
            set -euo pipefail
            printf 'makepkg cwd=%s args=%s uid=%s\n' "$PWD" "$*" "$EUID" >> "$AGENCY_TEST_LOG"
            if [[ $PWD == *yay.* ]]; then
              cat > "$AGENCY_TEST_BIN/yay" <<'YAY'
            #!/usr/bin/env bash
            set -euo pipefail
            printf 'yay %s\n' "$*" >> "$AGENCY_TEST_LOG"
            if [[ ${1:-} == --version ]]; then
              printf 'yay fixture\n'
              exit
            fi
            exit 96
            YAY
              chmod +x "$AGENCY_TEST_BIN/yay"
              exit
            fi
            grep -Fq "'zlib'" PKGBUILD
            ! grep -Fq "'zlib>=1.2.3'" PKGBUILD
            cat > "$AGENCY_TEST_BIN/h2load" <<'H2LOAD'
            #!/usr/bin/env bash
            printf 'h2load fixture\n'
            H2LOAD
            chmod +x "$AGENCY_TEST_BIN/h2load"
            """,
        )
        self.executable(
            "sudo",
            r"""
            #!/usr/bin/env bash
            printf 'sudo %s\n' "$*" >> "$AGENCY_TEST_LOG"
            exit 99
            """,
        )

        result = self.run_installer()

        log = self.log.read_text()
        self.assertIn("makepkg cwd=", log)
        self.assertIn("yay --version", log)
        self.assertNotIn("yay -S", log)
        self.assertIn("aur.archlinux.org/nghttp2.git", log)
        self.assertIn("cb43f84828ab4f9700f7c6f9c6d7a923d4cfaff0", log)
        self.assertIn("2f11414698d4a0190de1681f817855d93e29fcd9", log)
        self.assertNotIn("sudo ", log)
        self.assertIn("h2load fixture", result.stdout)

    def test_existing_yay_and_h2load_are_only_verified(self):
        self.executable(
            "yay",
            r"""
            #!/usr/bin/env bash
            printf 'yay %s\n' "$*" >> "$AGENCY_TEST_LOG"
            printf 'yay existing\n'
            """,
        )
        self.executable(
            "h2load",
            r"""
            #!/usr/bin/env bash
            printf 'h2load %s\n' "$*" >> "$AGENCY_TEST_LOG"
            printf 'h2load existing\n'
            """,
        )
        self.executable(
            "git",
            r"""
            #!/usr/bin/env bash
            exit 97
            """,
        )
        self.executable(
            "makepkg",
            r"""
            #!/usr/bin/env bash
            exit 98
            """,
        )

        result = self.run_installer()

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            self.log.read_text().splitlines(),
            ["yay --version", "h2load --version"],
        )
        self.assertIn("yay", result.stdout)
        self.assertIn("h2load", result.stdout)
        self.assertIn("./install.sh --update", result.stdout)

    def test_update_refreshes_existing_yay_and_h2load(self):
        self.executable(
            "yay",
            r"""
            #!/usr/bin/env bash
            printf 'yay %s\n' "$*" >> "$AGENCY_TEST_LOG"
            printf 'yay existing\n'
            """,
        )
        self.executable(
            "h2load",
            r"""
            #!/usr/bin/env bash
            printf 'h2load %s\n' "$*" >> "$AGENCY_TEST_LOG"
            printf 'h2load existing\n'
            """,
        )
        self.executable(
            "git",
            r"""
            #!/usr/bin/env bash
            set -euo pipefail
            printf 'git %s\n' "$*" >> "$AGENCY_TEST_LOG"
            if [[ ${1:-} == clone ]]; then
              target=${@: -1}
              mkdir -p "$target"
              if [[ $* == *nghttp2.git* ]]; then
                printf "pkgname=nghttp2\ndepends=('zlib>=1.2.3')\n" > "$target/PKGBUILD"
              else
                printf 'pkgname=yay\n' > "$target/PKGBUILD"
              fi
              exit
            fi
            if [[ ${1:-} == -C && ${3:-} == cat-file ]]; then
              exit
            fi
            if [[ ${1:-} == -C && ${3:-} == rev-parse ]]; then
              if [[ $2 == *yay.* ]]; then
                printf '%s\n' cb43f84828ab4f9700f7c6f9c6d7a923d4cfaff0
              else
                printf '%s\n' 2f11414698d4a0190de1681f817855d93e29fcd9
              fi
              exit
            fi
            if [[ ${1:-} == -C && ${3:-} == diff ]]; then
              printf '%s\n' 'diff --git a/PKGBUILD b/PKGBUILD'
              exit
            fi
            exit 2
            """,
        )
        self.executable(
            "makepkg",
            r"""
            #!/usr/bin/env bash
            set -euo pipefail
            printf 'makepkg cwd=%s args=%s\n' "$PWD" "$*" >> "$AGENCY_TEST_LOG"
            [[ $PWD == *yay.* ]] && exit
            grep -Fq "'zlib'" PKGBUILD
            ! grep -Fq "'zlib>=1.2.3'" PKGBUILD
            """,
        )

        result = self.run_installer("--update", check=False)

        self.assertEqual(
            result.returncode,
            0,
            result.stderr + "\n" + (self.log.read_text() if self.log.exists() else ""),
        )
        log = self.log.read_text()
        self.assertIn("cb43f84828ab4f9700f7c6f9c6d7a923d4cfaff0", log)
        self.assertIn("aur.archlinux.org/nghttp2.git", log)
        self.assertIn("2f11414698d4a0190de1681f817855d93e29fcd9", log)
        self.assertIn("makepkg cwd=", log)
        self.assertIn("h2load --version", log)


if __name__ == "__main__":
    unittest.main()
