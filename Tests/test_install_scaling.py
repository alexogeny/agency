import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InstallScalingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.environment = {**os.environ, 'HOME': str(self.home)}

    def shell(self, command, *arguments):
        return subprocess.run(['/bin/bash', '-c', command, 'bash', *map(str, arguments)],
                              env=self.environment, text=True, capture_output=True)

    def test_standalone_installers_find_library_from_basename_and_quoted_paths(self):
        tools = tempfile.TemporaryDirectory()
        self.addCleanup(tools.cleanup)
        binaries = Path(tools.name)
        actions = binaries / 'actions'
        for tool in ('pacman', 'git', 'curl', 'gpg', 'makepkg', 'yay', 'h2load', 'sudo'):
            stub = binaries / tool
            stub.write_text('#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$AGENCY_INSTALL_ACTION_LOG"\nexit 97\n')
            stub.chmod(0o755)
        self.environment.update(PATH=f'{binaries}:/usr/bin:/bin', AGENCY_INSTALL_ACTION_LOG=str(actions))
        for name in ('install-1password.sh', 'install-yay-h2load.sh'):
            for cwd, path in ((ROOT / 'scripts', name), (ROOT, Path('scripts') / name),
                              (self.home, ROOT / 'scripts' / name)):
                with self.subTest(name=name, cwd=str(cwd)):
                    result = subprocess.run(['/bin/bash', str(path), '--invalid'], cwd=cwd,
                                            env=self.environment, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn('Usage:', result.stderr)
                    self.assertNotIn('lib.sh:', result.stderr)
                    self.assertEqual(list(self.home.iterdir()), [])
            copied_scripts = self.home / 'checkout with spaces/scripts'
            copied_scripts.mkdir(parents=True, exist_ok=True)
            for source_name in (name, 'lib.sh'):
                (copied_scripts / source_name).write_bytes((ROOT / 'scripts' / source_name).read_bytes())
            result = subprocess.run(['/bin/bash', str(copied_scripts / name), '--invalid'], cwd=self.home,
                                    env=self.environment, text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('Usage:', result.stderr)
            self.assertEqual({path.name for path in self.home.iterdir()}, {'checkout with spaces'})
            for path in copied_scripts.iterdir():
                path.unlink()
            copied_scripts.rmdir()
            copied_scripts.parent.rmdir()
        self.assertFalse(actions.exists())

    def test_actual_managed_links_match_preview_on_both_platforms(self):
        apply = (ROOT / 'install.sh').read_text().split('agency_prepare_scratch\n', 1)[1].split('agency_merge_agent_hooks ', 1)[0]
        for platform in ('linux', 'macos'):
            home = self.home / platform
            home.mkdir()
            self.environment['HOME'] = str(home)
            command = '''set -euo pipefail
AGENCY_DIR=$1
AGENCY_PLATFORM=$2
platform=$2
source "$1/scripts/lib.sh"
'''
            result = self.shell(command + apply, ROOT, platform)
            self.assertEqual(result.returncode, 0, result.stderr)
            actual = {str(path): str(path.resolve()) for path in home.rglob('*')
                      if path.is_symlink() and str(path.resolve()).startswith(str(ROOT) + '/')}
            preview = self.shell(command + '''
source "$1/scripts/install-dry-run.sh"
agency_plan_user_links
''', ROOT, platform)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            planned = {}
            for line in preview.stdout.splitlines():
                match = re.match(r'  \[[^]]+\] (.*?) -> (.*)', line)
                if match and match[2].startswith(str(ROOT) + '/'):
                    planned[match[1]] = match[2]
            self.assertEqual(actual, planned)
            for name in ('agent-work-hook', 'agent-work-watch', 'agent-work-bridge'):
                self.assertIn(str(home / '.local/bin' / name), actual)
            self.assertIn(str(home / '.pi/agent/extensions/agency-work.ts'), actual)
            self.assertEqual(actual[str(home / '.codex/agents/coordinated-worker.toml')], str(ROOT / 'Agents/codex/coordinated-worker.toml'))
            self.assertEqual(actual[str(home / '.claude/agents/coordinated-worker.md')], str(ROOT / 'Agents/claude/coordinated-worker.md'))
            self.assertEqual(str(home / '.local/bin/housekeeping') in actual, platform == 'linux')
            for destination in ('.agents/skills', '.claude/skills', '.pi/agent/skills'):
                self.assertTrue((home / destination).is_dir())
                for skill in (ROOT / 'Skills').iterdir():
                    if skill.is_dir():
                        self.assertEqual((home / destination / skill.name).resolve(), skill)

    def packages(self, size=8, update=False, failure='', external=False):
        project = self.home / 'project'
        project.mkdir(exist_ok=True)
        names = [f'formula{index}' for index in range(size - 1)] + ['reviewed/tap/tool']
        (project / 'packages-macos.txt').write_text('\n'.join(names) + '\n')
        installed = [name for index, name in enumerate(names) if index % 2 == 0] + ['unmanaged']
        (self.home / 'formula-inventory').write_text('\n'.join(installed) + '\n')
        (self.home / 'cask-inventory').write_text('' if external else 'firefox\n1password\n1password-cli\n')
        for name in ('calls', 'mutations'):
            (self.home / name).unlink(missing_ok=True)
        source = ROOT / 'scripts/install-macos.sh'
        if external:
            for app in ('Firefox.app', '1Password.app'):
                (self.home / 'Applications' / app).mkdir(parents=True, exist_ok=True)
            source = self.home / 'install-macos.sh'
            source.write_text((ROOT / 'scripts/install-macos.sh').read_text().replace('/Applications/$app', '$HOME/Applications/$app'))
        command = r'''set -euo pipefail
source "$1"
AGENCY_DIR=$2
failure=$3
external=$4
command() {
  if [[ $* == '-v op' && $external == true ]]; then return 0; fi
  builtin command "$@"
}
brew() {
  local brew_fixture_entry
  printf '%s\n' "$*" >> "$HOME/calls"
  case "$*" in
    'list --formula') [[ $failure != formula ]] || return 11; cat "$HOME/formula-inventory" ;;
    'list --cask') [[ $failure != cask ]] || return 12; cat "$HOME/cask-inventory" ;;
    'list --formula '*)
      while IFS= read -r brew_fixture_entry; do [[ ${brew_fixture_entry##*/} != "$3" ]] || return 0; done < "$HOME/formula-inventory"
      return 1 ;;
    'list --cask '*)
      while IFS= read -r brew_fixture_entry; do [[ $brew_fixture_entry != "$3" ]] || return 0; done < "$HOME/cask-inventory"
      return 1 ;;
    '--prefix rustup') printf '/brew/opt/rustup\n' ;;
    *) printf '%s\n' "$*" >> "$HOME/mutations" ;;
  esac
}
agency_install_macos_packages "$5"
'''
        result = self.shell(command, source, project, failure, str(external).lower(), str(update).lower())
        calls = (self.home / 'calls').read_text().splitlines()
        mutations = (self.home / 'mutations').read_text().splitlines() if (self.home / 'mutations').exists() else []
        return result, calls, mutations, names, installed

    def test_brew_inventory_calls_are_bounded_and_actions_preserve_update_semantics(self):
        for size in (8, 16, 32, 16, 9):
            for update in (False, True):
                with self.subTest(size=size, update=update):
                    result, calls, mutations, names, installed = self.packages(size, update)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual([call for call in calls if call.startswith('list ')], ['list --formula', 'list --cask'])
                    expected = ['install --formula ' + ' '.join(name for name in names if name not in installed)]
                    if update:
                        expected.append('upgrade --formula ' + ' '.join(name for name in names if name in installed))
                        expected.extend('upgrade --cask ' + name for name in ('firefox', '1password', '1password-cli'))
                    expected.append('install --cask font-fantasque-sans-mono-nerd-font')
                    self.assertEqual(mutations, expected)

    def test_managed_link_paths_are_literal_data(self):
        project = self.home / 'project with spaces'
        (project / 'scripts').mkdir(parents=True)
        source = 'source $(touch unexpected-command)'
        target = 'target `touch unexpected-command`'
        (project / source).write_text('fixture')
        (project / 'scripts/managed-user-links.tsv').write_text(f'all\t{source}\t{target}\n')
        command = '''set -euo pipefail
source "$1/scripts/lib.sh"
AGENCY_DIR=$2
cd "$HOME"
agency_user_links apply
'''
        result = self.shell(command, ROOT, project)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.home / target).resolve(), project / source)
        self.assertFalse((self.home / 'unexpected-command').exists())

    def test_brew_inventory_failure_stops_before_mutation(self):
        for failure, status in (('formula', 11), ('cask', 12)):
            with self.subTest(failure=failure):
                result, calls, mutations, _, _ = self.packages(failure=failure)
                self.assertEqual(result.returncode, status)
                self.assertIn('inventory', result.stderr)
                self.assertEqual(mutations, [])
                self.assertEqual(calls, ['list --formula'] + (['list --cask'] if failure == 'cask' else []))

    def test_external_apps_and_op_are_preserved_even_with_update(self):
        for update in (False, True):
            result, _, mutations, _, _ = self.packages(update=update, external=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual([line for line in mutations if '--cask' in line], ['install --cask font-fantasque-sans-mono-nerd-font'])
            self.assertIn('Keeping existing /Applications/Firefox.app', result.stdout)
            self.assertIn('Keeping existing 1Password CLI', result.stdout)

    def test_shared_pinned_recipe_clone_rejects_unreviewed_heads_and_failures(self):
        command = r'''set -euo pipefail
source "$1/scripts/lib.sh"
mode=$2
git() {
  printf '%s\n' "$*" >> "$HOME/git-calls"
  if [[ $1 == clone ]]; then [[ $mode != clone-failure ]] || return 7; return 0; fi
  if [[ $3 == cat-file ]]; then [[ $mode != missing-commit ]]; return; fi
  if [[ $3 == rev-parse ]]; then
    if [[ $mode == head-change ]]; then printf 'unreviewed\n'; else printf 'reviewed\n'; fi
    return
  fi
  return 99
}
clone_pinned_recipe example reviewed "$HOME/recipe"
'''
        for mode, status, message in (('success', 0, ''), ('clone-failure', 7, ''),
                                      ('missing-commit', 1, 'review and update the pin'),
                                      ('head-change', 1, 'does not match pinned revision')):
            with self.subTest(mode=mode):
                (self.home / 'git-calls').unlink(missing_ok=True)
                result = self.shell(command, ROOT, mode)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertIn(message, result.stderr)
                calls = (self.home / 'git-calls').read_text().splitlines()
                self.assertEqual(calls[0], f'clone --depth 1 https://aur.archlinux.org/example.git {self.home}/recipe')
                self.assertFalse(any('fetch' in call or 'checkout' in call or 'reset' in call for call in calls))
