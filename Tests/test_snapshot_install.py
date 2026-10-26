import configparser
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SnapshotPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.target = self.workspace / "snap-pac.ini"
        self.env = dict(os.environ, HOME=str(self.workspace),
                        AGENCY_BACKUP_ROOT=str(self.workspace / "backups"))

    def apply(self):
        return subprocess.run(
            ["bash", "-c", 'set -euo pipefail; AGENCY_DIR=$1; '
             'source "$1/scripts/lib.sh"; source "$1/scripts/configure-snapshots.sh"; '
             'agency_as_root() { "$@"; }; agency_configure_snapshots "$2"',
             "test", str(ROOT), str(self.target)],
            env=self.env, text=True, capture_output=True)

    def config(self):
        result = configparser.ConfigParser()
        result.read(self.target)
        return result

    def test_existing_root_policy_preserves_other_settings_and_comments(self):
        original = "# local policy\n[DEFAULT]\ndesc_limit = 90\n[root]\nsnapshot = True\ncleanup_algorithm = number\n[home]\nsnapshot = True\n"
        self.target.write_text(original)
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.config().getboolean("root", "snapshot"))
        self.assertTrue(self.config().getboolean("home", "snapshot"))
        self.assertEqual(self.config()["root"]["desc_limit"], "90")
        self.assertEqual(self.target.read_text(), original.replace("[root]\nsnapshot = True", "[root]\nsnapshot = False"))
        backups = list((self.workspace / "backups").rglob("snap-pac.ini"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), original)

    def test_missing_config_is_created_and_rerun_does_not_rewrite(self):
        first = self.apply()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertFalse(self.config().getboolean("root", "snapshot"))
        before = self.target.stat()
        second = self.apply()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual((self.target.stat().st_ino, self.target.stat().st_mtime_ns),
                         (before.st_ino, before.st_mtime_ns))
        self.assertFalse((self.workspace / "backups").exists())

    def test_commented_example_and_inherited_default_get_explicit_root_setting(self):
        self.target.write_text("# [root]\n# snapshot = True\n[DEFAULT]\nsnapshot = True\n[home]\nsnapshot = True")
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.config().getboolean("root", "snapshot"))
        self.assertTrue(self.config().getboolean("home", "snapshot"))
        self.assertIn("# snapshot = True", self.target.read_text())

    def test_root_without_explicit_snapshot_keeps_following_section(self):
        self.target.write_text("[root]\ndesc_limit=90\n[home]\nsnapshot=True\n")
        result = self.apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.config().getboolean("root", "snapshot"))
        self.assertTrue(self.config().getboolean("home", "snapshot"))

    def test_malformed_config_fails_without_writing_or_backing_up(self):
        original = "[root]\nsnapshot=True\nsnapshot=False\n"
        self.target.write_text(original)
        result = self.apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        self.assertEqual(self.target.read_text(), original)
        self.assertFalse((self.workspace / "backups").exists())

    def test_managed_policy_can_reenable_snapshots(self):
        policy = self.workspace / "policy.ini"
        policy.write_text("[root]\nsnapshot = True\n")
        self.target.write_text("[root]\nsnapshot = False\n")
        result = subprocess.run(["python", str(ROOT / "scripts/merge-snap-pac.py"),
                                 str(self.target), str(policy)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        config = configparser.ConfigParser()
        config.read_string(result.stdout)
        self.assertTrue(config.getboolean("root", "snapshot"))

    def test_policy_runs_before_linux_package_transactions(self):
        text = (ROOT / "install.sh").read_text()
        self.assertLess(text.index('agency_configure_snapshots'),
                        text.index('agency_as_root pacman -Rns'))
        self.assertLess(text.index('agency_configure_snapshots'),
                        text.index('agency_as_root pacman -Syu'))

    def test_dry_run_reports_policy_on_linux_only_without_changing_config(self):
        self.target.write_text("[root]\nsnapshot=True\n")
        for platform in ("linux", "macos"):
            with self.subTest(platform=platform):
                result = subprocess.run(["bash", str(ROOT / "install.sh"), "--dry-run", "--platform", platform],
                                        env=self.env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                if platform == "linux":
                    self.assertIn("/etc/snap-pac.ini", result.stdout)
                    self.assertLess(result.stdout.index("/etc/snap-pac.ini"), result.stdout.index("pacman -Syu"))
                else:
                    self.assertNotIn("snap-pac", result.stdout)
                self.assertEqual(self.target.read_text(), "[root]\nsnapshot=True\n")
                self.assertFalse((self.workspace / "backups").exists())


if __name__ == "__main__":
    unittest.main()
