import os
from pathlib import Path
import pty
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StorageInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.checkout = self.root / 'checkout'
        (self.checkout / 'Tools').mkdir(parents=True)
        self.log = self.root / 'calls'
        tool = self.checkout / 'Tools/agency-storage'
        tool.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$CALL_LOG"\nexit "${TOOL_EXIT:-0}"\n')
        tool.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home),
                        XDG_CONFIG_HOME=str(self.home / '.config'),
                        AGENCY_DIR=str(self.checkout), CALL_LOG=str(self.log))

    def run_config(self, *args):
        return subprocess.run(
            ['bash', '-c', 'source "$1"; shift; agency_configure_storage "$@"',
             'test', str(ROOT / 'scripts/configure-storage.sh'), *args],
            env=self.env, text=True, capture_output=True, stdin=subprocess.DEVNULL)

    def configure(self):
        config = self.home / '.config/agency/storage.json'
        config.parent.mkdir(parents=True)
        config.write_text('{}')

    def test_unattended_without_configuration_skips(self):
        result = self.run_config()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('skip', result.stdout.lower())
        self.assertFalse(self.log.exists())

    def test_interactive_install_offers_setup(self):
        master, slave = pty.openpty()
        try:
            result = subprocess.run(
                ['bash', '-c', 'source "$1"; agency_configure_storage',
                 'test', str(ROOT / 'scripts/configure-storage.sh')],
                env=self.env, stdin=slave, stdout=slave, stderr=subprocess.PIPE,
                text=True, timeout=5)
        finally:
            os.close(slave)
            os.close(master)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text(), 'setup --interactive\n')

    def test_dry_run_propagates_failed_plan(self):
        self.env['TOOL_EXIT'] = '4'
        result = self.run_config('--dry-run')
        self.assertEqual(result.returncode, 4, result.stderr)

    def test_configured_rerun_checks_without_applying(self):
        self.configure()
        result = self.run_config()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text(), 'status\n')

    def test_configured_drift_fails_closed(self):
        self.configure()
        self.env['TOOL_EXIT'] = '3'
        result = self.run_config()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(self.log.read_text(), 'status\n')

    def test_dry_run_only_requests_plan(self):
        for configured in (False, True):
            with self.subTest(configured=configured):
                if configured:
                    self.configure()
                result = self.run_config('--dry-run')
                self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text(), 'setup --dry-run\nsetup --dry-run\n')

    def test_custom_config_home_uses_saved_status(self):
        config_home = self.root / 'custom-config'
        config = config_home / 'agency/storage.json'
        config.parent.mkdir(parents=True)
        config.write_text('{}')
        before = config.stat().st_mtime_ns
        self.env['XDG_CONFIG_HOME'] = str(config_home)
        result = self.run_config()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text(), 'status\n')
        self.assertEqual(config.stat().st_mtime_ns, before)
        self.assertEqual(config.read_text(), '{}')

    def test_broken_config_link_still_checks_and_fails_closed(self):
        config = self.home / '.config/agency/storage.json'
        config.parent.mkdir(parents=True)
        config.symlink_to(self.root / 'missing-config')
        self.env['TOOL_EXIT'] = '5'
        result = self.run_config()
        self.assertEqual(result.returncode, 5, result.stderr)
        self.assertEqual(self.log.read_text(), 'status\n')
        self.assertTrue(config.is_symlink())

    def run_scratch_plan(self):
        return subprocess.run(
            ['bash', '-c', 'source "$1"; agency_plan_scratch',
             'test', str(ROOT / 'scripts/install-dry-run.sh')],
            env=self.env, text=True, capture_output=True)

    def test_migrated_scratch_and_legacy_alias_are_unchanged(self):
        storage = self.root / 'storage'
        storage.mkdir()
        canonical = self.home / 'Scratch'
        legacy = self.home / 'scratch'
        canonical.symlink_to(storage, target_is_directory=True)
        legacy.symlink_to(canonical, target_is_directory=True)
        result = self.run_scratch_plan()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('unchanged', result.stdout)
        self.assertNotIn('warning', result.stdout)
        self.assertTrue(canonical.is_symlink())
        self.assertTrue(legacy.is_symlink())

    def test_different_legacy_link_retains_warning(self):
        canonical = self.home / 'Scratch'
        canonical.mkdir()
        other = self.root / 'different-scratch'
        other.mkdir()
        (self.home / 'scratch').symlink_to(other, target_is_directory=True)
        result = self.run_scratch_plan()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('scratch warning', result.stdout)
        self.assertNotIn('unchanged', result.stdout)

    def test_prepare_scratch_preserves_migrated_directory_and_legacy_alias(self):
        destination = self.root / 'storage-scratch'
        destination.mkdir()
        (self.home / 'Scratch').symlink_to(destination)
        (self.home / 'scratch').symlink_to(self.home / 'Scratch')
        result = subprocess.run(
            ['bash', '-c', 'source "$1"; agency_prepare_scratch',
             'test', str(ROOT / 'scripts/lib.sh')],
            env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual((self.home / 'Scratch').resolve(), destination)
        self.assertTrue((self.home / 'scratch').is_symlink())

    def test_installer_configures_storage_before_writing_scratch(self):
        installer = (ROOT / 'install.sh').read_text()
        self.assertLess(installer.index('agency_configure_storage\n'),
                        installer.index('\nagency_prepare_scratch\n'))
        self.assertIn('"$AGENCY_DIR/Tools/agency-storage" "$HOME/.local/bin/agency-storage"',
                      installer)
        dry_run = (ROOT / 'scripts/install-dry-run.sh').read_text()
        self.assertIn('agency_configure_storage --dry-run', dry_run)
        self.assertIn('    agency-storage\n', dry_run)


if __name__ == '__main__':
    unittest.main()
