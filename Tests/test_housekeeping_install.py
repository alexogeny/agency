import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HousekeepingInstallTests(unittest.TestCase):
    def test_missing_housekeeping_preserves_interactive_compiler(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bin_dir = root / '.local/bin'
            bin_dir.mkdir(parents=True)
            compiler = bin_dir / 'cc'
            compiler.write_text('#!/bin/sh\nprintf "compiler fixture\\n"\n')
            compiler.chmod(0o755)
            env = dict(os.environ, HOME=str(root), XDG_CONFIG_HOME=str(root / '.config'),
                       PATH=os.pathsep.join((str(bin_dir), '/usr/bin', '/bin')), TERM='xterm')
            result = subprocess.run(
                [shutil.which('fish'), '--no-config', '-i', '-c',
                 'source $argv[1]; command -sq housekeeping; and exit 9; '
                 'functions -q cc; and exit 7; '
                 'functions cleanup | string match --quiet "*housekeeping*"; and exit 8; '
                 'cc --version',
                 str(ROOT / 'config/fish/config.fish')],
                env=env, text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'compiler fixture\n')

    def test_installer_links_both_names_without_shadowing_compiler(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            command = '''set -euo pipefail
AGENCY_DIR=$1
AGENCY_PLATFORM=linux
source "$1/scripts/lib.sh"
source "$1/scripts/install-dry-run.sh"
agency_user_links apply
agency_plan_user_links
'''
            result = subprocess.run(['/bin/bash', '-c', command, 'bash', str(ROOT)],
                                    env=dict(os.environ, HOME=str(home)), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ('housekeeping', 'cleanup'):
                link = home / '.local/bin' / name
                self.assertEqual(link.resolve(), ROOT / 'Tools/housekeeping')
                self.assertIn(f'{link} -> {ROOT}/Tools/housekeeping', result.stdout)
            self.assertFalse((home / '.local/bin/cc').exists())
            self.assertNotIn(f'{home}/.local/bin/cc ->', result.stdout)

    def test_cc_is_interactive_only_and_forwards_quoted_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bin_dir = root / '.local/bin'
            bin_dir.mkdir(parents=True)
            tool = bin_dir / 'housekeeping'
            tool.write_text('#!/bin/sh\nprintf "<%s>\\n" "$@"\n')
            tool.chmod(0o755)
            sudo = bin_dir / 'sudo'
            sudo.write_text('#!/bin/sh\nexit 99\n')
            sudo.chmod(0o755)
            env = dict(os.environ, HOME=str(root), XDG_CONFIG_HOME=str(root / '.config'),
                       PATH=str(bin_dir) + os.pathsep + os.environ['PATH'], TERM='xterm')
            result = subprocess.run(['fish', '--no-config', '-i', '-c',
                                     'source $argv[1]; functions cleanup | string match --quiet "*pacman*"; and exit 9; cc "a directory" --plain; and cleanup "a directory" --plain',
                                     str(ROOT / 'config/fish/config.fish')],
                                    env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '<a directory>\n<--plain>\n' * 2)
            result = subprocess.run(['fish', '--no-config', '-c',
                                     'source $argv[1]; functions -q cc; and exit 7; command -s cc',
                                     str(ROOT / 'config/fish/config.fish')],
                                    env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('/cc', result.stdout)
            self.assertNotIn(str(bin_dir), result.stdout)


if __name__ == '__main__':
    unittest.main()
