import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HousekeepingInstallTests(unittest.TestCase):
    def test_installer_links_both_names_without_shadowing_compiler(self):
        installer = (ROOT / 'install.sh').read_text()
        for name in ('housekeeping', 'cleanup'):
            self.assertIn(f'"$AGENCY_DIR/Tools/housekeeping" "$HOME/.local/bin/{name}"', installer)
        self.assertNotIn('"$HOME/.local/bin/cc"', installer)
        plan = (ROOT / 'scripts/install-dry-run.sh').read_text()
        self.assertIn('    housekeeping\n', plan)
        self.assertIn('"$AGENCY_DIR/Tools/housekeeping" "$HOME/.local/bin/cleanup"', plan)

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
