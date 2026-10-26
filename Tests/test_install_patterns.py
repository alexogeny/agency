import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLERS = (
    'install-agent-clis.sh', 'install-python-tools.sh', 'install-rust.sh',
    'install-1password.sh', 'install-yay-h2load.sh',
)


class InstallerPatternTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / 'home with spaces'
        self.home.mkdir()
        self.backups = self.root / 'backups'
        self.environment = {**os.environ, 'HOME': str(self.home),
                            'AGENCY_BACKUP_ROOT': str(self.backups)}

    def test_all_installers_reject_invalid_flags_before_any_tool_action(self):
        binaries = self.root / 'bin'
        binaries.mkdir()
        actions = self.root / 'actions'
        for name in ('bun', 'uv', 'rustup', 'pacman', 'yay', 'git', 'curl',
                     'gpg', 'makepkg', 'sudo', 'op', '1password', 'h2load'):
            path = binaries / name
            path.write_text('#!/bin/bash\nprintf action >> "$INSTALL_TEST_ACTIONS"\nexit 99\n')
            path.chmod(0o755)
        environment = {**self.environment, 'PATH': str(binaries),
                       'INSTALL_TEST_ACTIONS': str(actions)}
        for name in INSTALLERS:
            for arguments in (('--invalid',), ('--update', 'extra'), ('', 'extra'),
                              ('--update', '--update')):
                with self.subTest(installer=name, arguments=arguments):
                    result = subprocess.run(['/bin/bash', name, *arguments],
                                            cwd=ROOT / 'scripts', env=environment,
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertEqual(result.stderr, f'Usage: {name} [--update]\n')
                    self.assertEqual(result.stdout, '')
                    self.assertFalse(actions.exists())
                    self.assertEqual(list(self.home.iterdir()), [])

    def run_link(self, kind, source, target):
        log = self.root / 'privileged-commands'
        log.unlink(missing_ok=True)
        command = '''set -euo pipefail
source "$1/scripts/lib.sh"
agency_as_root() {
  printf '%s\n' "$1" >> "$INSTALL_TEST_PRIVILEGED"
  "$@"
}
"$2" "$3" "$4"
'''
        result = subprocess.run(['/bin/bash', '-c', command, 'test', str(ROOT),
                                 kind, str(source), str(target)],
                                env={**self.environment, 'INSTALL_TEST_PRIVILEGED': str(log)},
                                text=True, capture_output=True)
        commands = log.read_text().splitlines() if log.exists() else []
        return result, commands

    def test_managed_link_backups_and_idempotency_match_for_both_runners(self):
        for kind in ('agency_link', 'agency_link_as_root'):
            for previous in ('file', 'directory', 'symlink', 'dangling'):
                with self.subTest(kind=kind, previous=previous):
                    source = self.root / f'managed {kind} {previous}'
                    source.write_text('managed')
                    target = self.home / kind / previous
                    target.parent.mkdir(exist_ok=True)
                    if previous == 'file':
                        target.write_text('preserve')
                    elif previous == 'directory':
                        target.mkdir()
                        (target / 'child').write_text('preserve')
                    else:
                        old = self.root / f'old-{kind}-{previous}'
                        if previous == 'symlink':
                            old.write_text('old')
                        target.symlink_to(old)
                    result, commands = self.run_link(kind, source, target)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(target.is_symlink())
                    self.assertEqual(target.resolve(), source)
                    backup = self.backups / 'home' / kind / previous
                    if previous in ('file', 'directory'):
                        retained = backup if previous == 'file' else backup / 'child'
                        self.assertEqual(retained.read_text(), 'preserve')
                    else:
                        self.assertFalse(backup.exists())
                    if kind == 'agency_link_as_root':
                        backup_commands = ['mkdir', 'mv'] if previous in ('file', 'directory') else []
                        self.assertEqual(commands, ['mkdir', *backup_commands, 'ln'])
                    else:
                        self.assertEqual(commands, [])
                    identity = target.lstat().st_ino, target.lstat().st_mtime_ns
                    result, commands = self.run_link(kind, source, target)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, '')
                    self.assertEqual((target.lstat().st_ino, target.lstat().st_mtime_ns), identity)
                    self.assertEqual(commands, ['mkdir'] if kind == 'agency_link_as_root' else [])

    def test_missing_link_source_does_not_touch_target_or_run_privileged_commands(self):
        for kind in ('agency_link', 'agency_link_as_root'):
            with self.subTest(kind=kind):
                target = self.home / kind
                target.write_text('preserve')
                result, commands = self.run_link(kind, self.root / 'missing', target)
                self.assertEqual(result.returncode, 1)
                self.assertIn('Managed link source does not exist', result.stderr)
                self.assertEqual(target.read_text(), 'preserve')
                self.assertEqual(commands, [])
                self.assertFalse(self.backups.exists())
