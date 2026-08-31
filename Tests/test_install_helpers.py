import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "scripts/lib.sh"
POWER = ROOT / "scripts/configure-power.sh"
INSTALLER = ROOT / "install.sh"
GIT_CONFIG = ROOT / "config/git/config"
CODEX_HOOKS = ROOT / "config/codex/hooks.json"
FIREFOX_POLICIES = ROOT / "firefox/policies.json"
PACKAGES = ROOT / "packages.txt"
SCRATCH = Path(os.environ.get("AGENCY_TEST_SCRATCH", ROOT / ".cache/tests"))


class GlobalAgentGuidanceTests(unittest.TestCase):
    def test_global_instructions_fit_context_budget(self):
        guidance = ROOT / "Agents/AGENTS.md"

        self.assertLessEqual(guidance.stat().st_size, 8 * 1024)

    def test_executable_code_changes_trigger_performance_preflight(self):
        guidance = (ROOT / "Agents/AGENTS.md").read_text()
        skill = (ROOT / "Skills/performance-design/SKILL.md").read_text()

        self.assertRegex(
            guidance,
            r"Whenever writing or modifying executable code, use "
            r"`performance-design`",
        )
        self.assertIn("For every executable-code change", skill)


class WorkstationManifestTests(unittest.TestCase):
    def test_shellcheck_and_firefox_are_native_packages(self):
        packages = {
            line.strip()
            for line in PACKAGES.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertIn("shellcheck", packages)
        self.assertIn("firefox", packages)

    def test_firefox_automatically_installs_the_1password_extension(self):
        policies = json.loads(FIREFOX_POLICIES.read_text())["policies"]
        extension = policies["ExtensionSettings"][
            "{d634138d-c276-4fc8-924b-40a0ea21d284}"
        ]

        self.assertEqual(extension["installation_mode"], "normal_installed")
        self.assertEqual(
            extension["install_url"],
            "https://addons.mozilla.org/firefox/downloads/latest/"
            "1password-x-password-manager/latest.xpi",
        )
        self.assertFalse(extension["updates_disabled"])


class InstallHelperTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.workspace = Path(self.temporary.name)
        self.home = self.workspace / "home"
        self.home.mkdir()
        self.backups = self.workspace / "backups"

    def tearDown(self):
        self.temporary.cleanup()

    def run_bash(self, command, *arguments, check=True, environment=None):
        shell_environment = os.environ.copy()
        shell_environment.update(
            {
                "HOME": str(self.home),
                "AGENCY_BACKUP_ROOT": str(self.backups),
            }
        )
        if environment:
            shell_environment.update(environment)
        return subprocess.run(
            ["bash", "-c", command, "bash", *map(str, arguments)],
            check=check,
            text=True,
            capture_output=True,
            env=shell_environment,
        )

    def test_regular_link_target_is_moved_to_backup(self):
        source = self.workspace / "source"
        source.write_text("managed\n")
        target = self.home / ".config/example"
        target.parent.mkdir()
        target.write_text("existing\n")

        self.run_bash(
            'source "$1"; agency_link "$2" "$3"', LIB, source, target
        )

        self.assertTrue(target.is_symlink())
        self.assertEqual(target.resolve(), source)
        self.assertEqual(
            (self.backups / "home/.config/example").read_text(), "existing\n"
        )

    def test_backup_root_is_created_before_privileged_descendants(self):
        self.run_bash('source "$1"; agency_ensure_backup_root', LIB)

        self.assertTrue(self.backups.is_dir())

    def test_existing_symlink_is_replaced_without_backup(self):
        source = self.workspace / "source"
        old_source = self.workspace / "old-source"
        source.write_text("managed\n")
        old_source.write_text("old\n")
        target = self.home / ".config/example"
        target.parent.mkdir()
        target.symlink_to(old_source)

        self.run_bash(
            'source "$1"; agency_link "$2" "$3"', LIB, source, target
        )

        self.assertEqual(target.resolve(), source)
        self.assertFalse(self.backups.exists())

    def test_regular_directory_target_is_moved_to_backup(self):
        source = self.workspace / "managed-directory"
        source.mkdir()
        target = self.home / ".config/example"
        target.mkdir(parents=True)
        (target / "existing.conf").write_text("existing\n")

        self.run_bash(
            'source "$1"; agency_link "$2" "$3"', LIB, source, target
        )

        self.assertTrue(target.is_symlink())
        self.assertEqual(target.resolve(), source)
        self.assertEqual(
            (self.backups / "home/.config/example/existing.conf").read_text(),
            "existing\n",
        )

    def test_existing_managed_link_is_unchanged(self):
        source = self.workspace / "source"
        source.write_text("managed\n")
        target = self.home / ".config/example"
        target.parent.mkdir()
        target.symlink_to(source)

        result = self.run_bash(
            'source "$1"; agency_link "$2" "$3"', LIB, source, target
        )

        self.assertEqual(target.resolve(), source)
        self.assertEqual(result.stdout, "")
        self.assertFalse(self.backups.exists())

    def test_existing_git_identity_is_imported(self):
        (self.home / ".gitconfig").write_text(
            "[user]\n"
            "\tname = Existing Person\n"
            "\temail = existing@example.invalid\n"
            "\tsigningKey = ABC123\n"
            '[credential "https://github.com"]\n'
            "\thelper = test-helper\n"
            "[pull]\n"
            "\trebase = false\n"
        )
        identity = self.home / ".config/git/identity"
        local_config = self.home / ".config/git/local"

        self.run_bash(
            'source "$1"; agency_install_git_identity "$2"', LIB, identity
        )
        self.run_bash(
            'source "$1"; agency_preserve_git_config "$2" "$3"',
            LIB,
            local_config,
            self.home / ".gitconfig",
        )
        self.run_bash(
            'source "$1"; agency_link "$2" "$3"; agency_link "$2" "$4"',
            LIB,
            GIT_CONFIG,
            self.home / ".gitconfig",
            self.home / ".config/git/config",
        )

        self.assertEqual(
            subprocess.run(
                ["git", "config", "--file", identity, "user.name"],
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip(),
            "Existing Person",
        )
        self.assertEqual(
            subprocess.run(
                ["git", "config", "--file", identity, "user.email"],
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip(),
            "existing@example.invalid",
        )
        self.assertEqual(
            subprocess.run(
                ["git", "config", "--global", "--includes", "pull.rebase"],
                check=True,
                text=True,
                capture_output=True,
                env={**os.environ, "HOME": str(self.home)},
            ).stdout.strip(),
            "true",
        )
        global_config = subprocess.run(
            [
                "git",
                "config",
                "--global",
                "--includes",
                "--show-origin",
                "--list",
            ],
            check=True,
            text=True,
            capture_output=True,
            env={**os.environ, "HOME": str(self.home)},
        ).stdout
        self.assertIn("test-helper", global_config)
        self.assertIn("Existing Person", global_config)
        self.assertEqual(stat.S_IMODE(identity.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(local_config.stat().st_mode), 0o600)

    def test_legacy_scratch_directory_is_migrated(self):
        legacy = self.home / "scratch"
        legacy.mkdir()
        (legacy / "probe.sh").write_text("reusable\n")

        self.run_bash('source "$1"; agency_prepare_scratch', LIB)

        canonical = self.home / "Scratch"
        self.assertFalse(legacy.exists())
        self.assertEqual((canonical / "probe.sh").read_text(), "reusable\n")

    def test_existing_scratch_directories_merge_without_overwriting_conflicts(self):
        legacy = self.home / "scratch"
        canonical = self.home / "Scratch"
        legacy.mkdir()
        canonical.mkdir()
        (legacy / "legacy.txt").write_text("legacy\n")
        (canonical / "canonical.txt").write_text("canonical\n")
        (legacy / "shared.txt").write_text("legacy shared\n")
        (canonical / "shared.txt").write_text("canonical shared\n")

        result = self.run_bash(
            'source "$1"; agency_prepare_scratch', LIB
        )

        self.assertFalse((legacy / "legacy.txt").exists())
        self.assertEqual((canonical / "legacy.txt").read_text(), "legacy\n")
        self.assertTrue((canonical / "canonical.txt").exists())
        self.assertEqual((canonical / "shared.txt").read_text(), "canonical shared\n")
        self.assertEqual((legacy / "shared.txt").read_text(), "legacy shared\n")
        self.assertIn("conflicting entry", result.stderr)

    def test_agent_hooks_are_merged_after_backing_up_existing_settings(self):
        target = self.home / ".codex/hooks.json"
        target.parent.mkdir(parents=True)
        target.write_text('{"theme": "preserved"}\n')

        first = self.run_bash(
            'source "$1"; agency_merge_agent_hooks "$2" "$3"',
            LIB,
            CODEX_HOOKS,
            target,
        )
        second = self.run_bash(
            'source "$1"; agency_merge_agent_hooks "$2" "$3"',
            LIB,
            CODEX_HOOKS,
            target,
        )

        self.assertIn('"theme": "preserved"', target.read_text())
        self.assertIn('"SessionStart"', target.read_text())
        self.assertEqual(
            (self.backups / "home/.codex/hooks.json").read_text(),
            '{"theme": "preserved"}\n',
        )
        self.assertIn("Backed up", first.stdout)
        self.assertEqual(second.stdout, "")


class LaptopDetectionTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.sysfs = Path(self.temporary.name) / "sys"

    def tearDown(self):
        self.temporary.cleanup()

    def detect(self):
        environment = os.environ.copy()
        environment["AGENCY_SYSFS_ROOT"] = str(self.sysfs)
        return subprocess.run(
            ["bash", "-c", 'source "$1"; detect_laptop', "bash", str(POWER)],
            text=True,
            capture_output=True,
            env=environment,
        )

    def configure(self):
        environment = os.environ.copy()
        environment["AGENCY_SYSFS_ROOT"] = str(self.sysfs)
        return subprocess.run(
            [
                "bash",
                "-c",
                (
                    'source "$1"; '
                    'agency_link() { printf "link=%s\\n" "$1"; }; '
                    'agency_as_root() { printf "root=%s\\n" "$*"; }; '
                    'systemctl() { :; }; '
                    'set_desktop_brightness() { printf "brightness=desktop\\n"; }; '
                    "configure_power"
                ),
                "bash",
                str(POWER),
            ],
            text=True,
            capture_output=True,
            env=environment,
        )

    def test_laptop_chassis_is_detected(self):
        chassis = self.sysfs / "class/dmi/id/chassis_type"
        chassis.parent.mkdir(parents=True)
        chassis.write_text("10\n")

        self.assertEqual(self.detect().returncode, 0)

        configured = self.configure()
        self.assertEqual(configured.returncode, 0, configured.stderr)
        self.assertIn("powerdevil-laptoprc", configured.stdout)
        self.assertIn("root=systemctl unmask", configured.stdout)
        self.assertNotIn("brightness=desktop", configured.stdout)

    def test_battery_is_detected_when_chassis_is_unknown(self):
        battery_type = self.sysfs / "class/power_supply/BAT0/type"
        battery_type.parent.mkdir(parents=True)
        battery_type.write_text("Battery\n")

        self.assertEqual(self.detect().returncode, 0)

    def test_desktop_without_battery_is_not_detected_as_laptop(self):
        chassis = self.sysfs / "class/dmi/id/chassis_type"
        chassis.parent.mkdir(parents=True)
        chassis.write_text("3\n")

        self.assertEqual(self.detect().returncode, 1)

        configured = self.configure()
        self.assertEqual(configured.returncode, 0, configured.stderr)
        self.assertIn("powerdevil-desktoprc", configured.stdout)
        self.assertIn("root=systemctl mask", configured.stdout)
        self.assertIn("brightness=desktop", configured.stdout)

    def test_absent_device_battery_does_not_select_laptop_policy(self):
        chassis = self.sysfs / "class/dmi/id/chassis_type"
        chassis.parent.mkdir(parents=True)
        chassis.write_text("3\n")
        battery = self.sysfs / "class/power_supply/hid-battery"
        battery.mkdir(parents=True)
        (battery / "type").write_text("Battery\n")
        (battery / "scope").write_text("Device\n")
        (battery / "present").write_text("0\n")

        self.assertEqual(self.detect().returncode, 1)
        configured = self.configure()
        self.assertIn("powerdevil-desktoprc", configured.stdout)


class DryRunTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.workspace = Path(self.temporary.name)
        self.home = self.workspace / "home"
        self.home.mkdir()
        self.sysfs = self.workspace / "sys"
        chassis = self.sysfs / "class/dmi/id/chassis_type"
        chassis.parent.mkdir(parents=True)
        chassis.write_text("10\n")
        existing = self.home / ".codex/AGENTS.md"
        existing.parent.mkdir(parents=True)
        existing.write_text("preserve me\n")
        claude_settings = self.home / ".claude/settings.json"
        claude_settings.parent.mkdir(parents=True)
        claude_settings.write_text('{"theme": "dark"}\n')

    def tearDown(self):
        self.temporary.cleanup()

    def snapshot(self):
        return {
            str(path.relative_to(self.home)): (
                "link" if path.is_symlink() else "dir" if path.is_dir() else path.read_bytes()
            )
            for path in self.home.rglob("*")
        }

    def test_dry_run_describes_actions_without_mutating_home(self):
        before = self.snapshot()
        result = subprocess.run(
            [INSTALLER, "--dry-run"],
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "HOME": str(self.home),
                "AGENCY_SYSFS_ROOT": str(self.sysfs),
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("DRY RUN", result.stdout)
        self.assertIn("backup + link", result.stdout)
        self.assertIn("merge hooks", result.stdout)
        self.assertIn("powerdevil-laptoprc", result.stdout)
        self.assertIn("pacman -Syu", result.stdout)
        self.assertIn("base-devel", result.stdout)
        self.assertIn("yay", result.stdout)
        self.assertIn("h2load", result.stdout)
        self.assertIn("shellcheck", result.stdout)
        self.assertIn("firefox", result.stdout)
        self.assertIn("1Password desktop", result.stdout)
        self.assertIn("1Password CLI", result.stdout)
        self.assertIn("1Password Firefox extension", result.stdout)
        self.assertIn("document-inspect", result.stdout)
        self.assertIn("docs-exec", result.stdout)
        self.assertIn("evidence-review", result.stdout)
        self.assertIn("perf-diagnose", result.stdout)
        self.assertIn("performance-design", result.stdout)
        self.assertIn("comment-audit", result.stdout)
        self.assertIn("No changes were made", result.stdout)

    def test_help_is_non_mutating(self):
        before = self.snapshot()
        result = subprocess.run(
            [INSTALLER, "--help"],
            text=True,
            capture_output=True,
            env={**os.environ, "HOME": str(self.home)},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("--dry-run", result.stdout)
        self.assertIn("--update", result.stdout)

    def test_update_can_be_combined_with_dry_run(self):
        before = self.snapshot()
        result = subprocess.run(
            [INSTALLER, "--dry-run", "--update"],
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "HOME": str(self.home),
                "AGENCY_SYSFS_ROOT": str(self.sysfs),
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("update installed CLIs", result.stdout)
        self.assertIn("update AUR tool", result.stdout)
        self.assertIn("1Password desktop", result.stdout)
        self.assertIn("1Password CLI", result.stdout)
        self.assertIn("Run ./install.sh --update", result.stdout)


if __name__ == "__main__":
    unittest.main()
