import importlib.machinery
import importlib.util
import json
import io
import contextlib
import os
import pty
import errno
import select
import time
import termios
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'Tools/housekeeping'


def load_tool():
    loader = importlib.machinery.SourceFileLoader('housekeeping', str(TOOL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class HousekeepingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def write(self, path, size=8192):
        result = self.home / path
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_bytes(b'x' * size)
        return result

    def scan(self, **kwargs):
        return self.tool.scan(self.home, home=self.home, **kwargs)

    def test_hardlinks_are_counted_once_and_symlinks_not_followed(self):
        original = self.write('one/data')
        (self.home / 'two').mkdir()
        os.link(original, self.home / 'two/link')
        (self.home / 'outside').symlink_to('/usr')
        result = self.scan()
        self.assertEqual(result['totals']['apparent_bytes'], 8192)
        self.assertEqual(result['hardlinks_deduplicated'], 1)
        self.assertEqual(result['symlinks_skipped'], 1)

    def test_mount_boundaries_including_same_device_bind_mounts(self):
        self.write('mounted/large')
        self.write('keep/small', 13)
        result = self.scan(mount_points={str(self.home / 'mounted')})
        self.assertEqual(result['totals']['apparent_bytes'], 13)
        self.assertEqual(result['mounts_skipped'], 1)

    def test_permission_failure_is_partial_and_reported(self):
        self.write('denied/data')
        original = os.open
        def opened(path, *args, **kwargs):
            if path == 'denied':
                raise PermissionError('fixture denied')
            return original(path, *args, **kwargs)
        with patch.object(self.tool.os, 'open', side_effect=opened):
            result = self.scan()
        self.assertTrue(result['partial'])
        self.assertGreater(result['warning_count'], 0)
        self.assertIn('denied', str(result['warnings']))

    def test_categories_commands_and_protected_data(self):
        for name in ['.cache/uv/data', '.bun/install/cache/data', '.cache/pip/data',
                     '.cache/thumbnails/data', '.cache/mozilla/firefox/profile/cache2/data',
                     '.cache/diamond/venv/data', 'Scratch/task/data',
                     'Code/demo/node_modules/data', '.codex/sessions/data',
                     '.mozilla/firefox/profile/data']:
            self.write(name)
        result = self.scan()
        candidates = {Path(c['path']).relative_to(self.home).as_posix(): c for c in result['proposals']}
        self.assertIn('uv cache prune', candidates['.cache/uv']['command'])
        self.assertIn('bun pm cache rm', candidates['.bun/install/cache']['command'])
        self.assertEqual(candidates['.cache/diamond/venv']['kind'], 'review')
        self.assertEqual(candidates['Scratch/task']['kind'], 'review')
        self.assertEqual(candidates['.codex']['kind'], 'review')
        self.assertEqual(candidates['.mozilla']['kind'], 'review')
        self.assertEqual(candidates['Code/demo/node_modules']['kind'], 'rebuild')
        self.assertTrue(all('rm -' not in (c['command'] or '') for c in result['proposals']))

    def test_unsafe_terminal_paths_have_no_executable_proposal(self):
        self.write(".cache/pip\x1b]52;c;secret\x07/data")
        self.write("Scratch/weird\n$(touch BAD)/data")
        result = self.scan()
        rendered = self.tool.render(result, limit=20, colour=False, verbose=True)
        self.assertNotIn('\x1b', rendered)
        self.assertNotIn('\x07', rendered)
        self.assertIn('\\n', rendered)
        for proposal in result['proposals']:
            if '\n' in proposal['path']:
                self.assertIsNone(proposal['command'])

    def test_json_cli_is_clean_and_read_only(self):
        item = self.write('.cache/pip/data')
        before = item.stat()
        result = subprocess.run([str(TOOL), str(self.home), '--json', '--limit', '2'], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['root'], str(self.home))
        self.assertIn('filesystem', payload)
        self.assertIn('reclaim', payload['size_note'])
        self.assertEqual(item.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(item.read_bytes(), b'x' * 8192)
        self.assertEqual(result.stderr, '')

    def test_symlink_root_rejected(self):
        link = self.home / 'link'
        link.symlink_to(self.home, target_is_directory=True)
        with self.assertRaises(OSError):
            self.tool.scan(link)

    def test_symlink_ancestor_of_root_rejected(self):
        self.write('real/nested/data')
        (self.home / 'alias').symlink_to(self.home / 'real', target_is_directory=True)
        with self.assertRaises(OSError):
            self.tool.scan(self.home / 'alias/nested')

    def test_different_device_is_omitted(self):
        self.write('mounted/large')
        original = os.fstat
        root_device = self.home.stat().st_dev
        def different_root(fd):
            value = original(fd)
            if value.st_ino == self.home.stat().st_ino:
                fields = list(value)
                fields[2] = root_device + 1
                return os.stat_result(fields)
            return value
        with patch.object(self.tool.os, 'fstat', side_effect=different_root):
            result = self.scan()
        self.assertEqual(result['totals']['files'], 0)
        self.assertEqual(result['mounts_skipped'], 1)

    def test_hardlink_tracking_cap_marks_truncation(self):
        first = self.write('first/data')
        second = self.write('second/data')
        os.link(first, self.home / 'first/link')
        os.link(second, self.home / 'second/link')
        with patch.object(self.tool, 'MAX_HARDLINKS', 1):
            result = self.scan()
        self.assertTrue(result['partial'])
        self.assertIn('Hardlink tracking limit', str(result['warnings']))
        self.assertEqual(result['totals']['files'], 1)

    def test_detail_caps_keep_totals_and_mark_partial(self):
        for name in ('a', 'b', 'c', 'd'):
            self.write(f'{name}/node_modules/data', 17)
        with patch.object(self.tool, 'MAX_GROUPS', 1):
            result = self.scan()
        self.assertTrue(result['partial'])
        self.assertEqual(result['totals']['apparent_bytes'], 68)
        self.assertEqual(len(result['proposals']), 1)
        self.assertEqual(sum(x['apparent_bytes'] for x in result['folders']), 68)

    def test_control_characters_are_escaped_in_warnings(self):
        result = self.scan()
        result['warnings'] = ['untrusted\x1b[2J\u202e\ntext']
        output = self.tool.render(result)
        self.assertNotIn('\x1b', output)
        self.assertNotIn('\u202e', output)

    def test_partial_cli_exit_and_interrupt(self):
        result = self.scan()
        result['partial'] = True
        with patch.object(self.tool, 'scan', return_value=result), contextlib.redirect_stdout(io.StringIO()) as output:
            code = self.tool.main(['--json'])
        self.assertEqual(code, 1)
        self.assertTrue(json.loads(output.getvalue())['partial'])
        with patch.object(self.tool, 'scan', side_effect=KeyboardInterrupt), contextlib.redirect_stderr(io.StringIO()) as error:
            code = self.tool.main(['--plain'])
        self.assertEqual(code, 130)
        self.assertIn('nothing changed', error.getvalue())

    def test_native_commands_quote_shell_metacharacters(self):
        path = self.home / "quote'$(touch BAD)" / '.cache/uv'
        candidate = self.tool.proposal(path, self.home / "quote'$(touch BAD)")
        import shlex
        command = shlex.split(candidate['command'])
        self.assertEqual(command, [f'UV_CACHE_DIR={path}', 'uv', 'cache', 'prune'])

    def test_actionable_cache_is_visible_beside_larger_review_candidates(self):
        self.write('Scratch/large/data', 65536)
        self.write('.cache/uv/data', 8192)
        self.write('.cache/pip/empty', 0)
        result = self.scan()
        output = self.tool.render(result, limit=1, verbose=True)
        self.assertIn('ACTIONABLE CACHE CLEANUP', output)
        self.assertIn('REVIEW BEFORE CLEANUP', output)
        self.assertIn('uv cache prune', output)
        self.assertIn('Review completed Scratch', output)
        self.assertNotIn('Purge pip', output)
        self.assertFalse(any(c['allocated_bytes'] == 0 and c['apparent_bytes'] == 0 for c in result['proposals']))

    def test_folder_breakdown_explains_dependencies_and_remaining_files(self):
        self.write('Code/api/.venv/pyvenv.cfg', 13)
        self.write('Code/api/.venv/lib/dependency.py', 20000)
        self.write('Code/web/package.json', 17)
        self.write('Code/web/node_modules/pkg/index.js', 30000)
        self.write('Code/api/main.py', 100)
        result = self.scan()
        code = next(folder for folder in result['folders'] if folder['name'] == 'Code')
        parts = code['breakdown']
        self.assertEqual(parts['python_environments']['apparent_bytes'], 20013)
        self.assertEqual(parts['node_dependencies']['apparent_bytes'], 30000)
        self.assertEqual(parts['other']['apparent_bytes'], 117)
        for metric in ('allocated_bytes', 'apparent_bytes', 'files'):
            self.assertEqual(sum(part[metric] for part in parts.values()), code[metric])
        output = self.tool.render(result, verbose=True)
        self.assertIn('Python environments', output)
        self.assertIn('Node dependencies', output)
        self.assertIn('Source & other files', output)
        self.assertIn('api/.venv', output)
        self.assertIn('web/node_modules', output)

    def test_breakdown_finds_environments_beneath_scratch_review_candidate(self):
        self.write('Scratch/task/work/.venv/pyvenv.cfg', 7)
        self.write('Scratch/task/work/.venv/lib/__pycache__/module.pyc', 8000)
        self.write('Scratch/task/evidence.json', 19)
        result = self.scan()
        scratch = next(folder for folder in result['folders'] if folder['name'] == 'Scratch')
        self.assertEqual(scratch['breakdown']['python_environments']['apparent_bytes'], 8007)
        self.assertEqual(scratch['breakdown']['other']['apparent_bytes'], 19)
        self.assertEqual(len(scratch['generated_directories']), 1)
        self.assertIn('pyvenv.cfg', scratch['generated_directories'][0]['evidence'])
        self.assertEqual(scratch['generated_directories'][0]['apparent_bytes'], 8007)

    def test_directory_names_and_symlinked_markers_are_not_proof_of_rebuildability(self):
        self.write('Code/art/target/source.svg', 10)
        self.write('Code/art/build/source.py', 11)
        self.write('Code/api/.venv/custom.py', 12)
        external = self.write('outside/pyvenv.cfg', 13)
        (self.home / 'Code/api/.venv/pyvenv.cfg').symlink_to(external)
        self.write('Code/rust/Cargo.toml', 14)
        self.write('Code/rust/target/debug/program', 15)
        result = self.scan()
        code = next(folder for folder in result['folders'] if folder['name'] == 'Code')
        self.assertNotIn('python_environments', code['breakdown'])
        self.assertEqual(code['breakdown']['possible_generated']['apparent_bytes'], 33)
        self.assertEqual(code['breakdown']['rust_build']['apparent_bytes'], 15)
        self.assertTrue(all('command' not in item for item in code['generated_directories']))

    def test_nested_dependencies_and_hardlinks_do_not_double_count_breakdown(self):
        payload = self.write('Code/web/node_modules/a/node_modules/b/index.js', 500)
        os.link(payload, payload.with_name('hardlink.js'))
        self.write('Code/web/source.ts', 100)
        result = self.scan()
        code = result['folders'][0]
        self.assertEqual(code['apparent_bytes'], 600)
        self.assertEqual(code['breakdown']['node_dependencies']['apparent_bytes'], 500)
        self.assertEqual(len(code['generated_directories']), 1)
        self.assertEqual(code['generated_directories'][0]['apparent_bytes'], 500)

    def test_possible_output_folder_does_not_hide_a_recognized_environment(self):
        self.write('Scratch/task/build/notes.md', 31)
        self.write('Scratch/task/build/.venv/pyvenv.cfg', 9)
        self.write('Scratch/task/build/.venv/lib/dependency.py', 9000)
        result = self.scan()
        scratch = result['folders'][0]
        self.assertEqual(scratch['breakdown']['possible_generated']['apparent_bytes'], 31)
        self.assertEqual(scratch['breakdown']['python_environments']['apparent_bytes'], 9009)
        self.assertEqual(sum(item['apparent_bytes'] for item in scratch['generated_directories']), 9040)

    def test_detail_limit_does_not_truncate_breakdown_totals(self):
        for name in ('one', 'two', 'three'):
            self.write(f'Code/{name}/.venv/pyvenv.cfg', 7)
        with patch.object(self.tool, 'MAX_GROUPS', 1):
            result = self.scan()
        code = result['folders'][0]
        self.assertEqual(code['breakdown']['python_environments']['apparent_bytes'], 21)
        self.assertEqual(len(code['generated_directories']), 1)
        self.assertIn('category totals still include', str(result['warnings']))

    def test_scanning_build_root_keeps_neighbor_manifest_evidence(self):
        self.write('Code/rust/Cargo.toml', 9)
        self.write('Code/rust/target/debug/program', 200)
        self.write('Code/web/package.json', 9)
        self.write('Code/web/.next/server/page.js', 300)
        for relative, category, count in [('Code/rust/target', 'rust_build', 200),
                                           ('Code/web/.next', 'build_output', 300)]:
            with self.subTest(relative=relative):
                result = self.tool.scan(self.home / relative, home=self.home)
                self.assertEqual(result['totals']['breakdown'][category]['apparent_bytes'], count)
                self.assertNotIn('possible_generated', result['totals']['breakdown'])

    def test_default_report_is_compact_and_verbose_retains_details(self):
        for number in range(12):
            self.write(f'Code/project-{number}/.venv/pyvenv.cfg', 7)
            self.write(f'Code/project-{number}/.venv/lib/package.py', 9000)
        self.write('.cache/uv/data', 50000)
        compact = subprocess.run([str(TOOL), str(self.home), '--plain'], capture_output=True, text=True)
        verbose = subprocess.run([str(TOOL), str(self.home), '--plain', '--verbose'], capture_output=True, text=True)
        self.assertEqual(compact.returncode, 0, compact.stderr)
        self.assertEqual(verbose.returncode, 0, verbose.stderr)
        self.assertLess(len(compact.stdout.splitlines()), 35)
        self.assertLess(len(compact.stdout), len(verbose.stdout))
        self.assertIn('Python environments', compact.stdout)
        self.assertIn('--dry-run', compact.stdout)
        self.assertIn('Python environments', verbose.stdout)

    def test_dry_run_reports_cache_scope_and_excludes_project_deletions(self):
        self.write('.cache/uv/data', 50000)
        self.write('.bun/install/cache/data', 7000)
        self.write('Code/project/.venv/pyvenv.cfg', 7)
        self.write('Code/project/.venv/lib/package.py', 9000)
        before = {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        result = subprocess.run([str(TOOL), str(self.home), '--dry-run', '--json'], capture_output=True, text=True,
                                env=dict(os.environ, HOME=str(self.home)))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        plan = data['cleanup_plan']
        self.assertFalse(plan['executes_commands'])
        self.assertEqual(len(plan['actions']), 2)
        self.assertTrue(all(item['kind'] == 'cache' for item in plan['actions']))
        self.assertTrue(all('.venv' not in item['path'] for item in plan['actions']))
        self.assertIn('unknown', plan['reclaimable_bytes_note'])
        self.assertGreater(plan['review_only_count'], 0)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()})

    def test_dry_run_with_only_environments_lists_unselected_candidates(self):
        self.write('Code/project/.venv/pyvenv.cfg', 7)
        result = subprocess.run([str(TOOL), str(self.home), '--dry-run', '--plain'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('No native cache actions', result.stdout)
        self.assertIn('Code/project/.venv', result.stdout)
        self.assertIn('unselected', result.stdout)
        self.assertIn('No commands executed', result.stdout)
        self.assertNotIn('WHERE THE SPACE IS', result.stdout)

    def test_apply_requires_a_terminal_and_does_not_run_on_piped_input(self):
        self.write('.cache/uv/data', 123)
        result = subprocess.run([str(TOOL), str(self.home), '--apply'], input='yes\n', capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('interactive terminal', result.stderr)
        self.assertEqual((self.home / '.cache/uv/data').stat().st_size, 123)

    def cache_plan(self):
        self.write('.cache/uv/data', 123)
        with patch.object(self.tool.shutil, 'which', return_value='/fixture/uv'):
            return self.tool.cleanup_plan(self.scan())

    def test_apply_cancel_never_invokes_a_cleanup_command(self):
        plan = self.cache_plan()
        with patch('builtins.input', return_value='no'), \
             patch.object(self.tool.subprocess, 'run', side_effect=AssertionError('cleanup ran')), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.tool.apply_cleanup(plan), 0)
        self.assertTrue((self.home / '.cache/uv/data').exists())

    def test_apply_uses_fixed_argv_and_scoped_cache_environment(self):
        plan = self.cache_plan()
        plan['actions'][0]['command'] = 'touch /must-not-run'
        with patch('builtins.input', return_value='yes'), \
             patch.object(self.tool.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'Pruned cache', '')) as run, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.tool.apply_cleanup(plan), 0)
        self.assertEqual(run.call_args.args[0], ['/fixture/uv', 'cache', 'prune'])
        self.assertEqual(run.call_args.kwargs['env']['UV_CACHE_DIR'], str(self.home / '.cache/uv'))
        self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_apply_refuses_replaced_cache_after_confirmation(self):
        plan = self.cache_plan()
        def confirm(*args):
            cache = self.home / '.cache/uv'
            cache.rename(cache.with_name('original'))
            cache.mkdir()
            return 'yes'
        with patch('builtins.input', side_effect=confirm), \
             patch.object(self.tool.subprocess, 'run', side_effect=AssertionError('changed cache used')), \
             self.assertRaisesRegex(RuntimeError, 'changed'):
            self.tool.apply_cleanup(plan)

    def test_apply_stops_after_a_failed_native_command(self):
        self.write('.bun/install/cache/data', 200)
        plan = self.cache_plan()
        with patch('builtins.input', return_value='yes'), \
             patch.object(self.tool.subprocess, 'run', return_value=subprocess.CompletedProcess([], 4, '', 'fixture failure')) as run, \
             contextlib.redirect_stdout(io.StringIO()), \
             self.assertRaisesRegex(RuntimeError, 'failed'):
            self.tool.apply_cleanup(plan)
        self.assertEqual(run.call_count, 1)

    def test_partial_cache_is_excluded_but_unrelated_partial_scan_allows_known_cache(self):
        self.write('.cache/uv/denied/data', 100)
        self.write('.cache/uv/visible', 200)
        real_open = os.open
        def opened(path, *args, **kwargs):
            if path == 'denied':
                raise PermissionError('fixture denied')
            return real_open(path, *args, **kwargs)
        with patch.object(self.tool.os, 'open', side_effect=opened):
            data = self.scan()
        plan = self.tool.cleanup_plan(data)
        self.assertEqual(plan['actions'], [])
        self.assertIn('incomplete', str(plan['blocked_actions']))
        self.write('Scratch/denied/data', 11)
        with patch.object(self.tool.os, 'open', side_effect=opened):
            # Remove only this fixture denial to isolate the unrelated warning.
            (self.home / '.cache/uv/denied').rename(self.home / '.cache/uv/readable')
            data = self.scan()
        with patch.object(self.tool.shutil, 'which', return_value='/fixture/uv'):
            plan = self.tool.cleanup_plan(data)
        self.assertTrue(data['partial'])
        self.assertEqual(len(plan['actions']), 1)

    def test_missing_native_tool_is_explicitly_excluded(self):
        self.write('.cache/uv/data', 100)
        with patch.object(self.tool.shutil, 'which', return_value=None):
            plan = self.tool.cleanup_plan(self.scan())
        self.assertEqual(plan['actions'], [])
        self.assertIn('unavailable', str(plan['blocked_actions']))

    def test_selected_executable_is_absolute_before_working_directory_changes(self):
        self.write('.cache/uv/data', 100)
        with patch.object(self.tool.shutil, 'which', return_value='./fixture-bin/uv'):
            plan = self.tool.cleanup_plan(self.scan())
        self.assertTrue(Path(plan['actions'][0]['executable']).is_absolute())

    def test_pip_cleanup_uses_isolated_python(self):
        arguments = self.tool.NATIVE_CLEANUPS['pip'][1]
        self.assertIn('-I', arguments)
        self.assertIn('-B', arguments)

    def test_apply_cancel_and_confirm_end_to_end_on_disposable_cache(self):
        cache_file = self.write('.cache/uv/data', 111)
        source = self.write('Code/project/main.py', 222)
        fake_bin = self.home / 'fixture-bin'
        fake_bin.mkdir()
        uv = fake_bin / 'uv'
        uv.write_text('#!/bin/sh\n[ "$1 $2" = "cache prune" ] || exit 9\nrm -- "$UV_CACHE_DIR/data"\n')
        uv.chmod(0o755)
        env = dict(os.environ, HOME=str(self.home), PATH=str(fake_bin) + os.pathsep + os.environ['PATH'])
        for answer, exists in ((b'no\n', True), (b'yes\n', False)):
            with self.subTest(answer=answer):
                master, slave = pty.openpty()
                process = subprocess.Popen([str(TOOL), str(self.home), '--apply', '--plain'],
                                           stdin=slave, stdout=slave, stderr=slave, env=env)
                os.close(slave)
                os.write(master, answer)
                output = b''
                try:
                    while True:
                        try:
                            block = os.read(master, 65536)
                        except OSError as error:
                            if error.errno != errno.EIO:
                                raise
                            break
                        if not block:
                            break
                        output += block
                finally:
                    os.close(master)
                    process.wait(timeout=10)
                self.assertEqual(process.returncode, 0, output.decode())
                self.assertIn(b'Command:', output)
                self.assertIn(b'[y/N]', output)
                self.assertEqual(cache_file.exists(), exists)
                self.assertEqual(source.stat().st_size, 222)

    def test_apply_rejects_a_hidden_plan_when_stdout_is_redirected(self):
        master, slave = pty.openpty()
        try:
            result = subprocess.run([str(TOOL), str(self.home), '--apply'], stdin=slave,
                                    capture_output=True, text=True, timeout=10)
        finally:
            os.close(slave)
            os.close(master)
        self.assertEqual(result.returncode, 2)
        self.assertIn('visible plan', result.stderr)

    def test_bun_cleanup_runs_in_temporary_empty_project(self):
        cache = self.write('.bun/install/cache/data', 123).parent
        fake_bun = self.home / 'bun-fixture'
        fake_bun.write_text('#!/bin/sh\n[ -f package.json ] || exit 9\n'
                            'if [ "$1 $2 $3" = "pm cache rm" ]; then rm -- "$BUN_INSTALL_CACHE_DIR/data"; '
                            'else printf "%s\\n" "$BUN_INSTALL_CACHE_DIR"; fi\n')
        fake_bun.chmod(0o755)
        with patch.object(self.tool.shutil, 'which', return_value=str(fake_bun)):
            plan = self.tool.cleanup_plan(self.scan())
        with patch('builtins.input', return_value='yes'), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.tool.apply_cleanup(plan), 0)
        self.assertFalse((cache / 'data').exists())
        self.assertFalse((self.home / 'package.json').exists())

    def test_apply_confirmation_never_hides_actions_behind_limit(self):
        self.write('.cache/uv/data', 100)
        self.write('.bun/install/cache/data', 200)
        with patch.object(self.tool.shutil, 'which', return_value='/fixture/tool'):
            data = self.scan()
            output = self.tool.render(data, limit=1, applying=True)
        self.assertIn(str(self.home / '.cache/uv'), output)
        self.assertIn(str(self.home / '.bun/install/cache'), output)
        self.assertEqual(output.count('Command:'), 2)

    def test_bun_wrong_reported_cache_path_stops_before_removal(self):
        self.write('.bun/install/cache/data', 100)
        with patch.object(self.tool.shutil, 'which', return_value='/fixture/bun'):
            plan = self.tool.cleanup_plan(self.scan())
        with patch('builtins.input', return_value='yes'), \
             patch.object(self.tool.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '/unrelated/cache\n', '')) as run, \
             contextlib.redirect_stdout(io.StringIO()), \
             self.assertRaisesRegex(RuntimeError, 'different cache'):
            self.tool.apply_cleanup(plan)
        self.assertEqual(run.call_count, 1)
        self.assertTrue((self.home / '.bun/install/cache/data').exists())

    def test_custom_cache_override_is_not_automatically_executable(self):
        custom = self.write('somewhere/data', 100).parent
        with patch.dict(os.environ, {'BUN_INSTALL_CACHE_DIR': str(custom)}):
            data = self.scan()
        plan = self.tool.cleanup_plan(data)
        self.assertEqual(plan['actions'], [])
        self.assertIn('manual review', plan['blocked_actions'][0]['reason'])

    def test_new_mount_below_cache_blocks_apply(self):
        plan = self.cache_plan()
        with patch.object(self.tool, 'mount_paths', return_value={str(self.home / '.cache/uv/mount')}), \
             patch.object(self.tool.subprocess, 'run', side_effect=AssertionError('cleanup ran')), \
             self.assertRaisesRegex(RuntimeError, 'mount boundary'):
            self.tool.apply_cleanup(plan)

    def test_code_dry_run_lists_project_environments_instead_of_hiding_them(self):
        self.write('Code/api/.venv/pyvenv.cfg', 10)
        self.write('Code/api/.venv/lib/dependency.py', 10000)
        self.write('Code/web/node_modules/pkg/index.js', 7000)
        self.write('Code/api/main.py', 123)
        result = self.tool.scan(self.home / 'Code', home=self.home)
        plan = self.tool.cleanup_plan(result)
        self.assertEqual(len(plan['project_candidates']), 2)
        output = self.tool.render(result, dry_run=True)
        self.assertIn('api/.venv', output)
        self.assertIn('web/node_modules', output)
        self.assertIn('Python environments', output)
        self.assertIn('Node dependencies', output)
        self.assertIn('selectable', output)
        self.assertTrue(all(item['selectable'] for item in plan['project_candidates']))
        self.assertEqual(plan['actions'], [])
        self.assertTrue((self.home / 'Code/api/main.py').exists())

    def test_project_preview_retains_full_json_and_marks_hidden_candidates(self):
        for number in range(3):
            self.write(f'Code/project-{number}/.venv/pyvenv.cfg', 10)
        result = self.tool.scan(self.home / 'Code', home=self.home)
        plan = self.tool.cleanup_plan(result)
        self.assertEqual(len(plan['project_candidates']), 3)
        output = self.tool.render(result, dry_run=True, limit=1)
        self.assertIn('2 more project', output)

    def project_plan(self):
        self.write('Code/api/.venv/pyvenv.cfg', 10)
        self.write('Code/web/node_modules/pkg/index.js', 9000)
        self.write('Code/api/main.py', 123)
        return self.tool.cleanup_plan(self.tool.scan(self.home / 'Code', home=self.home))

    def test_project_selection_is_explicit_and_can_be_cancelled(self):
        for selected_count in (0, 1):
            plan = self.project_plan()
            with patch.object(self.tool, 'choose_projects', return_value=plan['project_candidates'][:selected_count]), \
                 patch('builtins.input', return_value='no'), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(self.tool.apply_cleanup(plan), 0)
            self.assertTrue(all(Path(item['path']).is_dir() for item in plan['project_candidates']))

    def test_project_selection_removes_only_chosen_directory_after_confirmation(self):
        plan = self.project_plan()
        chosen, kept = plan['project_candidates']
        output = io.StringIO()
        with patch.object(self.tool, 'choose_projects', return_value=[chosen]), \
             patch('builtins.input', return_value='yes'), contextlib.redirect_stdout(output):
            self.assertEqual(self.tool.apply_cleanup(plan), 0)
        self.assertFalse(Path(chosen['path']).exists())
        self.assertTrue(Path(kept['path']).is_dir())
        self.assertEqual((self.home / 'Code/api/main.py').stat().st_size, 123)
        self.assertIn(chosen['path'], output.getvalue())

    def test_picker_offers_all_candidates_including_disabled_rows(self):
        plan = self.project_plan()
        plan['project_candidates'][0]['selectable'] = False
        with patch.object(self.tool, 'choose_projects', return_value=[]) as choose, \
             patch('builtins.input', side_effect=AssertionError('nothing to confirm')), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.tool.apply_cleanup(plan), 0)
        self.assertEqual([item['path'] for item in choose.call_args.args[0]],
                         [item['path'] for item in plan['project_candidates']])
        self.assertFalse(choose.call_args.args[0][0]['selectable'])
        self.assertTrue(all(Path(item['path']).is_dir() for item in plan['project_candidates']))

    def test_picker_cancellation_aborts_native_cache_actions_too(self):
        plan = self.cache_plan()
        plan['project_candidates'] = self.project_plan()['project_candidates']
        with patch.object(self.tool, 'choose_projects', side_effect=KeyboardInterrupt), \
             patch.object(self.tool, 'run_cleanup_command', side_effect=AssertionError('cleanup ran')), \
             patch('builtins.input', side_effect=AssertionError('cancelled picker')), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.tool.apply_cleanup(plan), 130)
        self.assertTrue((self.home / '.cache/uv/data').exists())

    def test_scanning_environment_itself_offers_root_for_selection(self):
        cfg = self.write('Code/api/.venv/pyvenv.cfg', 10)
        result = self.tool.scan(cfg.parent, home=self.home)
        plan = self.tool.cleanup_plan(result)
        self.assertEqual(len(plan['project_candidates']), 1)
        self.assertTrue(plan['project_candidates'][0]['selectable'])
        self.assertEqual(plan['project_candidates'][0]['path'], str(cfg.parent))

    def test_mount_inside_environment_makes_candidate_review_only(self):
        cfg = self.write('Code/api/.venv/pyvenv.cfg', 10)
        mounted = self.write('Code/api/.venv/mounted/data', 100).parent
        result = self.tool.scan(self.home / 'Code', home=self.home, mount_points={str(mounted)})
        plan = self.tool.cleanup_plan(result)
        self.assertFalse(plan['project_candidates'][0]['selectable'])

    def test_project_apply_selection_and_confirmation_in_real_terminal(self):
        cfg = self.write('Code/api/.venv/pyvenv.cfg', 10)
        source = self.write('Code/api/main.py', 123)
        other = self.write('Code/web/node_modules/pkg/index.js', 9000)
        installed = self.home / 'housekeeping'
        installed.symlink_to(TOOL)
        # Larger node_modules is first; Down selects the Python environment.
        for keys, answer, exists, status in ((b'\r', None, True, 0),
                                              (b'q', None, True, 130),
                                              (b'\x1b[B \r', b'no\n', True, 0),
                                              (b'\x1b[B \r', b'yes\n', False, 0)):
            with self.subTest(keys=keys, answer=answer):
                master, slave = pty.openpty()
                termios.tcsetwinsize(slave, (24, 100))
                process = subprocess.Popen([str(installed), str(self.home / 'Code'), '--apply', '--plain', '--limit=1'],
                                           stdin=slave, stdout=slave, stderr=slave,
                                           env=dict(os.environ, HOME=str(self.home), TERM='xterm-256color'))
                os.close(slave)
                output = bytearray()
                def read_until(marker):
                    deadline = time.monotonic() + 10
                    while marker not in output:
                        remaining = deadline - time.monotonic()
                        self.assertGreater(remaining, 0, output.decode(errors='replace'))
                        self.assertTrue(select.select([master], [], [], remaining)[0], output.decode(errors='replace'))
                        try:
                            block = os.read(master, 65536)
                        except OSError as error:
                            if error.errno == errno.EIO:
                                self.fail(output.decode(errors='replace'))
                            raise
                        self.assertTrue(block, output.decode(errors='replace'))
                        output.extend(block)
                try:
                    read_until(b'Space')
                    os.write(master, keys)
                    if answer is not None:
                        read_until(b'[y/N]')
                        # Selection alone has not removed anything.
                        self.assertTrue(cfg.exists())
                        self.assertTrue(other.exists())
                        os.write(master, answer)
                    read_until(b'Cancelled.' if status == 130 or answer == b'no\n' else
                               b'No cleanup selected.' if answer is None else b'Completed ')
                    process.wait(timeout=10)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=10)
                    os.close(master)
                self.assertEqual(process.returncode, status, output.decode(errors='replace'))
                self.assertEqual(cfg.exists(), exists)
                self.assertEqual(source.stat().st_size, 123)
                self.assertEqual(other.stat().st_size, 9000)
                if answer:
                    self.assertIn(str(cfg.parent).encode(), output)
                    self.assertIn(b'[y/N]', output)

    def test_project_changed_after_confirmation_returns_to_picker_before_native_actions(self):
        plan = self.cache_plan()
        plan['project_candidates'] = self.project_plan()['project_candidates']
        selected = Path(plan['project_candidates'][0]['path'])
        def confirm(*args):
            selected.rename(selected.with_name('original'))
            selected.mkdir()
            return 'yes'
        with patch.object(self.tool, 'choose_projects', side_effect=[[plan['project_candidates'][0]], KeyboardInterrupt]) as choose, \
             patch('builtins.input', side_effect=confirm), \
             patch.object(self.tool, 'run_cleanup_command', side_effect=AssertionError('native cleanup started')), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.tool.apply_cleanup(plan), 130)
        self.assertEqual(choose.call_count, 2)
        self.assertFalse(choose.call_args.args[0][0]['selectable'])
        self.assertIn('identity changed', choose.call_args.args[0][0]['reason'])
        self.assertTrue((self.home / '.cache/uv/data').exists())

    def test_new_process_inspection_gap_after_confirmation_preserves_selection(self):
        plan = self.project_plan()
        from unittest.mock import Mock
        helper = Mock()
        helper.report_projects.side_effect = [
            {'blocked': {}, 'uninspected_processes': 0},
            {'blocked': {}, 'uninspected_processes': 0},
            {'blocked': {}, 'uninspected_processes': 1},
        ]
        with patch.object(self.tool, 'project_helpers', return_value=helper), \
             patch.object(self.tool, 'choose_projects', side_effect=[[plan['project_candidates'][0]], KeyboardInterrupt]) as choose, \
             patch('builtins.input', return_value='yes'), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.tool.apply_cleanup(plan), 130)
        self.assertEqual(choose.call_args.kwargs['initial_selected'], (plan['project_candidates'][0]['path'],))
        self.assertIn('inspection changed', choose.call_args.kwargs['notice'])
        helper.remove_project.assert_not_called()

    def test_preflight_disables_busy_folder_before_picker(self):
        from unittest.mock import Mock
        plan = self.project_plan()
        busy, ready = plan['project_candidates']
        helper = Mock()
        helper.report_projects.side_effect = [
            {'blocked': {busy['path']: 'In active use: node (PID 123; open file)'}, 'uninspected_processes': 0},
            {'blocked': {}, 'uninspected_processes': 0},
            {'blocked': {}, 'uninspected_processes': 0},
        ]
        def choose(candidates, **kwargs):
            self.assertFalse(candidates[0]['selectable'])
            self.assertIn('node (PID 123', candidates[0]['reason'])
            self.assertTrue(candidates[1]['selectable'])
            self.assertTrue(callable(kwargs['refresh']))
            return [candidates[1]]
        with patch.object(self.tool, 'project_helpers', return_value=helper), \
             patch.object(self.tool, 'choose_projects', side_effect=choose), \
             patch('builtins.input', return_value='yes'), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.tool.apply_cleanup(plan), 0)
        self.assertEqual(helper.remove_project.call_args.args[0]['path'], ready['path'])
        helper.remove_project.assert_called_once()

    def test_busy_folder_after_selection_or_confirmation_preserves_other_checks(self):
        from unittest.mock import Mock
        for blocked_after_confirmation in (False, True):
            with self.subTest(after_confirmation=blocked_after_confirmation):
                plan = self.project_plan()
                busy, ready = plan['project_candidates']
                clean = {'blocked': {}, 'uninspected_processes': 0}
                blocked = {'blocked': {busy['path']: 'In active use: node (PID 123; open file)'},
                           'uninspected_processes': 0}
                helper = Mock()
                helper.report_projects.side_effect = ([clean, clean, blocked, clean, clean]
                                                     if blocked_after_confirmation else [clean, blocked, clean, clean])
                calls = []
                def choose(candidates, **kwargs):
                    calls.append(kwargs)
                    if len(calls) == 1:
                        return candidates
                    self.assertFalse(candidates[0]['selectable'])
                    self.assertIn(ready['path'], kwargs['initial_selected'])
                    self.assertIn('unavailable', kwargs['notice'])
                    return [candidates[1]]
                with patch.object(self.tool, 'project_helpers', return_value=helper), \
                     patch.object(self.tool, 'choose_projects', side_effect=choose), \
                     patch('builtins.input', return_value='yes') as confirm, \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(self.tool.apply_cleanup(plan), 0)
                self.assertEqual(len(calls), 2)
                self.assertEqual(confirm.call_count, 2 if blocked_after_confirmation else 1)
                self.assertEqual(helper.remove_project.call_args.args[0]['path'], ready['path'])
                helper.remove_project.assert_called_once()

    def test_native_interruption_does_not_claim_nothing_changed(self):
        plan = self.cache_plan()
        output = io.StringIO()
        with patch('builtins.input', return_value='yes'), \
             patch.object(self.tool, 'run_cleanup_command', side_effect=KeyboardInterrupt), \
             contextlib.redirect_stdout(output):
            self.assertEqual(self.tool.apply_cleanup(plan), 130)
        self.assertNotIn('Nothing changed', output.getvalue())
        self.assertIn('may have made changes', output.getvalue())

    def test_busy_recheck_after_cache_cleanup_keeps_choices_without_rerunning_cache(self):
        from unittest.mock import Mock
        plan = self.cache_plan()
        plan['project_candidates'] = self.project_plan()['project_candidates']
        busy, ready = plan['project_candidates']
        clean = {'blocked': {}, 'uninspected_processes': 0}
        blocked = {'blocked': {busy['path']: 'In active use: fixture (PID 123; cwd)'}, 'uninspected_processes': 0}
        helper = Mock()
        helper.report_projects.side_effect = [clean, clean, clean, blocked, clean, clean]
        with patch.object(self.tool, 'project_helpers', return_value=helper), \
             patch.object(self.tool, 'choose_projects', side_effect=[[busy, ready], [ready]]) as choose, \
             patch('builtins.input', return_value='yes') as confirm, \
             patch.object(self.tool, 'run_cleanup_command', return_value=subprocess.CompletedProcess([], 0, '', '')) as run, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.tool.apply_cleanup(plan), 0)
        run.assert_called_once()
        self.assertEqual(choose.call_args.kwargs['initial_selected'], (ready['path'],))
        self.assertIn('Run 0 cache', confirm.call_args.args[0])
        helper.remove_project.assert_called_once_with(ready)

    def test_busy_folder_is_disabled_in_terminal_before_safe_folder_cleanup(self):
        cfg = self.write('Code/api/.venv/pyvenv.cfg', 10)
        source = self.write('Code/api/main.py', 123)
        busy_file = self.write('Code/web/node_modules/pkg/index.js', 9000)
        busy = self.home / 'Code/web/node_modules'
        child = subprocess.Popen([self.tool.sys.executable, '-c', 'import time; time.sleep(30)'], cwd=busy)
        master, slave = pty.openpty()
        termios.tcsetwinsize(slave, (24, 140))
        process = subprocess.Popen([str(TOOL), str(self.home / 'Code'), '--apply', '--plain'],
                                   stdin=slave, stdout=slave, stderr=slave,
                                   env=dict(os.environ, HOME=str(self.home), TERM='xterm'))
        os.close(slave)
        output = bytearray()
        def read_until(marker):
            deadline = time.monotonic() + 10
            while marker not in output:
                remaining = deadline - time.monotonic()
                self.assertGreater(remaining, 0, output.decode(errors='replace'))
                self.assertTrue(select.select([master], [], [], remaining)[0], output.decode(errors='replace'))
                try:
                    block = os.read(master, 65536)
                except OSError as error:
                    if error.errno == errno.EIO:
                        self.fail(output.decode(errors='replace'))
                    raise
                self.assertTrue(block)
                output.extend(block)
        try:
            read_until(b'Space')
            self.assertIn(b'[-]', output)
            self.assertIn(f'PID {child.pid}'.encode(), output)
            self.assertIn(b'cwd', output)
            os.write(master, b' \x1b[B \r')
            read_until(b'[y/N]')
            self.assertTrue(cfg.exists())
            self.assertTrue(busy_file.exists())
            os.write(master, b'yes\n')
            read_until(b'Completed ')
            process.wait(timeout=10)
            self.assertEqual(process.returncode, 0, output.decode(errors='replace'))
            self.assertFalse(cfg.exists())
            self.assertTrue(busy_file.exists())
            self.assertTrue(source.exists())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            child.terminate()
            child.wait(timeout=10)
            os.close(master)

    def test_inspection_failure_after_cache_reports_completed_work(self):
        from unittest.mock import Mock
        plan = self.cache_plan()
        plan['project_candidates'] = self.project_plan()['project_candidates']
        clean = {'blocked': {}, 'uninspected_processes': 0}
        helper = Mock()
        helper.report_projects.side_effect = [clean, clean, clean, RuntimeError('Process inspection unavailable')]
        with patch.object(self.tool, 'project_helpers', return_value=helper), \
             patch.object(self.tool, 'choose_projects', return_value=[plan['project_candidates'][0]]), \
             patch('builtins.input', return_value='yes'), \
             patch.object(self.tool, 'run_cleanup_command', return_value=subprocess.CompletedProcess([], 0, '', '')), \
             contextlib.redirect_stdout(io.StringIO()), \
             self.assertRaisesRegex(RuntimeError, '1 cache commands completed'):
            self.tool.apply_cleanup(plan)
        helper.remove_project.assert_not_called()

    def test_review_only_candidate_explains_its_specific_restriction(self):
        self.write('Code/rust/Cargo.toml', 10)
        self.write('Code/rust/target/output', 100)
        plan = self.tool.cleanup_plan(self.tool.scan(self.home / 'Code', home=self.home))
        candidate = plan['project_candidates'][0]
        self.assertFalse(candidate['selectable'])
        self.assertIn('Rust build output', candidate['reason'])
        self.assertNotIn('incomplete', candidate['reason'])

    def test_preferences_plain_and_reduced_motion(self):
        with patch.dict(os.environ, {'AGENCY_MOTION': 'reduce'}, clear=True):
            self.assertFalse(self.tool.preferences(tty=True)[1])
        with patch.dict(os.environ, {'NO_COLOR': ''}, clear=True):
            self.assertFalse(self.tool.preferences(tty=True)[0])
        self.assertEqual(self.tool.preferences(tty=False), (False, False))


if __name__ == '__main__':
    unittest.main()
