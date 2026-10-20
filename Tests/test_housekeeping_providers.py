import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from Tests.test_housekeeping import load_tool


class HousekeepingProviderTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.web = self.home / '.local/share/web-research/profiles'
        self.releases = self.home / '.codex/packages/app-server-daemon/releases'

    def write(self, path, data=b'fixture'):
        path = self.home / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def profile(self, name='task', **metadata):
        root = self.web / name
        self.write(root / 'cache2/entries/cache', b'x' * 8192)
        self.write(root / 'startupCache/startupCache.8.little', b'y' * 4096)
        self.write(root / 'cookies.sqlite', b'preserve cookies')
        self.write(root / 'storage/default/site/data', b'preserve site data')
        if metadata:
            value = dict(schema_version=1, owner='web-research', purpose='task', pinned=False,
                         last_used_at=time.time() - 40 * 86400, completed_at=time.time() - 40 * 86400)
            value.update(metadata)
            self.write(Path(str(root) + '.agency.json'), json.dumps(value).encode())
        return root

    def plan(self):
        helper = self.tool.project_helpers()
        with patch.object(helper, 'inspect_processes', return_value={'blocked': {}, 'uninspected_processes': 0}):
            return self.tool.cleanup_plan(self.tool.scan(self.home, home=self.home, mount_points=set()))

    def applications(self):
        return self.plan()['application_candidates']

    def test_nested_application_discovery_partitions_inventory_without_double_counting(self):
        self.profile()
        result = self.tool.scan(self.home, home=self.home, mount_points=set())
        paths = {Path(item['path']).name for item in result['proposals']}
        self.assertIn('cache2', paths)
        self.assertIn('startupCache', paths)
        self.assertEqual(sum(item['apparent_bytes'] for item in result['proposals']), result['totals']['apparent_bytes'])
        caches = [item for item in self.applications() if item['action'] == 'web-cache']
        self.assertEqual(len(caches), 2)
        self.assertTrue(all(item['selectable'] for item in caches))

    def test_legacy_profile_retained_and_whole_profile_requires_completed_unpinned_metadata(self):
        self.profile('legacy')
        self.profile('pinned', pinned=True)
        self.profile('recent', last_used_at=time.time())
        completed = self.profile('completed', pinned=False)
        profiles = {Path(item['path']).name: item for item in self.applications() if item['action'] == 'web-profile'}
        self.assertFalse(profiles['legacy']['selectable'])
        self.assertIn('metadata', profiles['legacy']['reason'])
        self.assertFalse(profiles['pinned']['selectable'])
        self.assertFalse(profiles['recent']['selectable'])
        self.assertTrue(profiles['completed']['selectable'])
        self.assertEqual(profiles['completed']['apparent_bytes'], sum(p.stat().st_size for p in completed.rglob('*') if p.is_file()))

    def test_live_or_unreadable_profile_lock_blocks_both_cache_and_profile(self):
        root = self.profile(pinned=False)
        self.write(Path(str(root) + '.lock'), str(os.getpid()).encode())
        self.assertTrue(all(not item['selectable'] for item in self.applications()))
        Path(str(root) + '.lock').write_text('unknown owner')
        self.assertTrue(all(not item['selectable'] for item in self.applications()))

    def test_dead_profile_lock_is_not_changed_by_planning(self):
        root = self.profile()
        lock = self.write(Path(str(root) + '.lock'), b'999999999')
        items = self.applications()
        self.assertEqual(lock.read_bytes(), b'999999999')
        self.assertTrue(any(item['action'] == 'web-cache' and item['selectable'] for item in items))

    def test_cache_removal_preserves_profile_content_and_rechecks_late_lock(self):
        root = self.profile()
        item = next(item for item in self.applications() if Path(item['path']).name == 'cache2')
        provider = self.tool.provider_helpers()
        helper = self.tool.project_helpers()
        with patch.object(helper, 'inspect_processes', return_value={'blocked': {}, 'uninspected_processes': 0}):
            provider.execute(item)
        self.assertFalse((root / 'cache2').exists())
        self.assertEqual((root / 'cookies.sqlite').read_bytes(), b'preserve cookies')
        self.assertTrue((root / 'startupCache').exists())
        item = next(item for item in self.applications() if Path(item['path']).name == 'startupCache')
        self.write(Path(str(root) + '.lock'), str(os.getpid()).encode())
        with self.assertRaisesRegex(RuntimeError, 'use|lock'):
            provider.execute(item)
        self.assertTrue((root / 'startupCache').exists())

    def test_whole_profile_rechecks_pinning_and_preserves_capture_store(self):
        root = self.profile(pinned=False)
        capture = self.write('.local/share/web-research/captures/evidence', b'keep capture')
        item = next(item for item in self.applications() if item['action'] == 'web-profile')
        metadata = Path(str(root) + '.agency.json')
        value = json.loads(metadata.read_text())
        value['pinned'] = True
        metadata.write_text(json.dumps(value))
        with self.assertRaisesRegex(RuntimeError, 'pinned'):
            self.tool.provider_helpers().execute(item)
        value['pinned'] = False
        metadata.write_text(json.dumps(value))
        with patch.object(self.tool.project_helpers(), 'inspect_processes', return_value={'blocked': {}, 'uninspected_processes': 0}):
            self.tool.provider_helpers().execute(item)
        self.assertFalse(root.exists())
        self.assertFalse(metadata.exists())
        self.assertEqual(capture.read_bytes(), b'keep capture')

    def test_codex_keeps_current_rollback_newer_and_running_releases(self):
        for version in ('0.1.0', '0.2.0', '0.3.0', '0.4.0', '0.5.0'):
            self.release(version)
        current = self.releases.parent / 'current'
        current.symlink_to(self.releases / '0.4.0-x86_64-unknown-linux-musl')
        helper = self.tool.project_helpers()
        running = str(self.releases / '0.1.0-x86_64-unknown-linux-musl')
        with patch.object(helper, 'inspect_processes', return_value={'blocked': {running: 'In active use: test process'}, 'uninspected_processes': 0}):
            plan = self.tool.cleanup_plan(self.tool.scan(self.home, home=self.home, mount_points=set()))
        eligible = [Path(item['path']).name for item in plan['application_candidates'] if item['selectable']]
        self.assertEqual(eligible, ['0.2.0-x86_64-unknown-linux-musl'])

    def release(self, version):
        root = self.releases / (version + '-x86_64-unknown-linux-musl')
        self.write(root / 'bin/codex', b'binary')
        self.write(root / 'codex-package.json', json.dumps(dict(layoutVersion=1, version=version,
                   target='x86_64-unknown-linux-musl', variant='codex', entrypoint='bin/codex')).encode())
        return root

    def test_release_name_without_installation_metadata_does_not_authorize_removal(self):
        fake = self.write(self.releases / '0.1.0-x86_64-unknown-linux-musl/authored.txt', b'source')
        self.release('0.2.0')
        current = self.release('0.3.0')
        (self.releases.parent / 'current').symlink_to(current)
        item = next(item for item in self.applications() if Path(item['path']) == fake.parent)
        self.assertFalse(item['selectable'])
        self.assertIn('metadata', item['reason'])

    def test_codex_current_change_before_execution_preserves_new_current(self):
        first = self.release('0.1.0')
        self.release('0.2.0')
        latest = self.release('0.3.0')
        current = self.releases.parent / 'current'
        current.symlink_to(latest)
        self.write(self.releases.parent / 'install.lock', b'')
        item = next(item for item in self.applications() if item['path'] == str(first))
        current.unlink()
        current.symlink_to(first)
        with self.assertRaisesRegex(RuntimeError, 'current'):
            self.tool.provider_helpers().execute(item)
        self.assertTrue((first / 'bin/codex').exists())

    def test_native_firefox_record_lock_blocks_cache_without_removing_stale_lock_file(self):
        root = self.profile()
        native = root / '.parentlock'
        native.write_bytes(b'')
        process = subprocess.Popen([os.sys.executable, '-B', '-c',
                                   'import fcntl,sys; f=open(sys.argv[1],"r+"); fcntl.lockf(f,fcntl.LOCK_EX); print("locked",flush=True); sys.stdin.read()', str(native)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'locked')
            self.assertTrue(all(not item['selectable'] for item in self.applications()))
        finally:
            process.communicate('', timeout=5)
        self.assertTrue(native.exists())
        self.assertTrue(any(item['selectable'] for item in self.applications() if item['action'] == 'web-cache'))

    def test_missing_codex_current_and_unknown_version_are_review_only(self):
        self.write(self.releases / '0.1.0-x86_64-unknown-linux-musl/codex')
        self.write(self.releases / 'unexpected/codex')
        self.assertTrue(all(not item['selectable'] for item in self.applications()))

    def test_application_identity_swap_and_nested_mount_are_rejected(self):
        root = self.profile()
        item = next(item for item in self.applications() if Path(item['path']).name == 'cache2')
        cache = Path(item['path'])
        cache.rename(root / 'old-cache')
        cache.mkdir()
        with self.assertRaisesRegex(RuntimeError, 'identity|changed'):
            self.tool.provider_helpers().execute(item)
        self.assertTrue((root / 'old-cache/entries/cache').exists())
        item['identity'] = {'device': cache.stat().st_dev, 'inode': cache.stat().st_ino}
        with patch.object(self.tool.project_helpers(), 'mount_paths', return_value={str(cache / 'nested')}):
            with self.assertRaisesRegex(RuntimeError, 'mount'):
                self.tool.provider_helpers().execute(item)

    def test_thumbnail_unknown_contents_are_review_only(self):
        self.write('.cache/thumbnails/normal/hash.png', b'png')
        item = next(item for item in self.applications() if item['action'] == 'thumbnails')
        self.assertTrue(item['selectable'])
        self.write('.cache/thumbnails/personal.txt', b'authored')
        item = next(item for item in self.applications() if item['action'] == 'thumbnails')
        self.assertFalse(item['selectable'])

    def test_overlapping_whole_profile_and_cache_selections_are_rejected(self):
        self.profile(pinned=False)
        items = [item for item in self.applications() if item['selectable']]
        report = self.tool.provider_helpers().report_actions(items)
        self.assertTrue(report['blocked'])
        self.assertTrue(all('overlap' in reason for reason in report['blocked'].values()))

    def test_read_only_cli_finds_providers_and_creates_no_lifecycle_metadata(self):
        root = self.profile()
        before = {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        result = subprocess.run([str(self.tool.__file__), str(self.home), '--dry-run', '--json'],
                                env=dict(os.environ, HOME=str(self.home)), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)['cleanup_plan']
        self.assertFalse(plan['executes_commands'])
        self.assertTrue(plan['application_candidates'])
        self.assertFalse(Path(str(root) + '.agency.json').exists())
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()})

    def test_cancelled_application_selection_cancels_all_cleanup(self):
        self.profile()
        plan = self.plan()
        with patch.object(self.tool, 'choose_projects', side_effect=KeyboardInterrupt), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.tool.apply_cleanup(plan), 130)
        self.assertTrue((self.web / 'task/cache2/entries/cache').exists())

    def test_overlapping_selection_reopens_picker_with_an_explanation(self):
        self.profile(pinned=False)
        plan = self.plan()
        selected = [item for item in plan['application_candidates'] if item['selectable']]
        with patch.object(self.tool, 'choose_projects', side_effect=[selected, []]) as choose, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.tool.apply_cleanup(plan), 0)
        self.assertIn('overlap', choose.call_args.kwargs['notice'].lower())
        self.assertTrue((self.web / 'task/cookies.sqlite').exists())

    def test_application_command_timeout_reports_stopped_cleanup_and_preserves_targets(self):
        self.profile()
        plan = self.plan()
        chosen = next(item for item in plan['application_candidates'] if item['action'] == 'web-cache')
        with patch.object(self.tool, 'choose_projects', return_value=[chosen]), \
             patch('builtins.input', return_value='yes'), \
             patch.object(self.tool.provider_helpers(), 'execute', side_effect=subprocess.TimeoutExpired('fixture', 1)), \
             contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'cleanup stopped'):
            self.tool.apply_cleanup(plan)
        self.assertTrue(Path(chosen['path']).exists())

    def test_refresh_can_enable_a_profile_cache_that_was_locked_during_dry_run(self):
        root = self.profile()
        lock = self.write(Path(str(root) + '.lock'), str(os.getpid()).encode())
        plan = self.plan()
        def choose(candidates, *, refresh, **options):
            caches = [item for item in candidates if item['action'] == 'web-cache']
            self.assertTrue(all(not item['selectable'] for item in caches))
            lock.unlink()
            updated = [item for item in refresh() if item['action'] == 'web-cache']
            self.assertTrue(all(item['selectable'] for item in updated))
            return []
        with patch.object(self.tool, 'choose_projects', side_effect=choose) as picker, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.tool.apply_cleanup(plan), 0)
        picker.assert_called_once()
        self.assertTrue((root / 'cache2/entries/cache').exists())

    def test_codex_removal_preserves_current_rollback_and_sessions(self):
        oldest = self.release('0.1.0')
        rollback = self.release('0.2.0')
        current = self.release('0.3.0')
        (self.releases.parent / 'current').symlink_to(current)
        self.write(self.releases.parent / 'install.lock', b'')
        sessions = self.write('.codex/sessions/preserved.jsonl', b'history')
        item = next(item for item in self.applications() if item['path'] == str(oldest))
        with patch.object(self.tool.project_helpers(), 'inspect_processes', return_value={'blocked': {}, 'uninspected_processes': 0}):
            self.tool.provider_helpers().execute(item)
        self.assertFalse(oldest.exists())
        self.assertTrue((current / 'bin/codex').exists())
        self.assertTrue((rollback / 'bin/codex').exists())
        self.assertEqual(sessions.read_bytes(), b'history')

    def test_pacman_preview_counts_native_candidates_and_never_elevates(self):
        cache = self.home / 'package-cache'
        archive = self.write(cache / 'demo-1.0-1-x86_64.pkg.tar.zst', b'archive')
        signature = self.write(Path(str(archive) + '.sig'), b'signature')
        item = dict(path=str(cache), identity={'device': cache.stat().st_dev, 'inode': cache.stat().st_ino})
        output = b'==> Candidate packages:\n' + b'\0'.join(os.fsencode(path) for path in (archive, signature)) + b'\0\n==> finished dry run: 1 candidates\n'
        provider = self.tool.provider_helpers()
        with patch.object(provider.shutil, 'which', return_value='/usr/bin/paccache'), \
             patch.object(provider.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, b'')) as run:
            preview = provider.pacman_preview(item, 2)
        self.assertEqual(preview['candidate_apparent_bytes'], len(b'archive') + len(b'signature'))
        self.assertEqual(len(preview['candidate_files']), 2)
        command = run.call_args.args[0]
        self.assertIn('-d', command)
        self.assertNotIn('sudo', command)
        self.assertNotIn('-r', command)
        self.assertEqual(preview['keep_versions'], 2)

    def test_pacman_preview_rejects_symlinks_and_foreign_candidates(self):
        archive = self.write('cache/demo-1-1-x86_64.pkg.tar.zst')
        item = dict(path=str(archive.parent), identity={'device': archive.stat().st_dev, 'inode': archive.parent.stat().st_ino})
        provider = self.tool.provider_helpers()
        for target in (self.home / 'outside/demo-1-1-x86_64.pkg.tar.zst', archive):
            if target == archive:
                archive.unlink()
                archive.symlink_to('/etc/passwd')
            output = b'==> Candidate packages:\n' + os.fsencode(target) + b'\0\n==> finished dry run: 1 candidates\n'
            with patch.object(provider.shutil, 'which', return_value='/usr/bin/paccache'), \
                 patch.object(provider.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, b'')), \
                 self.assertRaises(RuntimeError):
                provider.pacman_preview(item)

    def test_pacman_apply_replans_and_stops_on_changed_candidates_without_elevation(self):
        provider = self.tool.provider_helpers()
        item = dict(path='/var/cache/pacman/pkg', action='pacman', keep_versions=2, candidate_files=[{'path': 'old'}], sudo_gui='/usr/bin/sudo-gui')
        with patch.object(provider, 'report_actions', return_value={'blocked': {}, 'uninspected_processes': 0}), \
             patch.object(provider, 'pacman_preview', return_value={'candidate_files': [{'path': 'changed'}]}), \
             patch.object(provider.subprocess, 'run') as run, self.assertRaisesRegex(RuntimeError, 'changed'):
            provider.execute(item)
        run.assert_not_called()

    def test_pacman_native_manifest_allows_unrelated_inaccessible_download_directories(self):
        cache = self.home / 'fixture-cache'
        cache.mkdir()
        provider = self.tool.provider_helpers()
        item = dict(path='/var/cache/pacman/pkg', home=str(self.home), action='pacman', scan_complete=False,
                    native_plan_complete=True, identity={'device': cache.stat().st_dev, 'inode': cache.stat().st_ino})
        descriptor = os.open(cache, os.O_RDONLY | os.O_DIRECTORY)
        with patch.object(provider.projects, '_open_path', return_value=descriptor):
            self.assertEqual(provider._checked(item, set()), Path('/var/cache/pacman/pkg'))

    def test_pacman_selection_size_describes_candidates_and_keeps_full_cache_size_separate(self):
        provider = self.tool.provider_helpers()
        candidate = dict(provider=True, path='/var/cache/pacman/pkg', action='pacman', allocated_bytes=100000,
                         apparent_bytes=200000, files=100, scan_complete=True)
        preview = dict(candidate_files=[{'path': 'package'}], candidate_allocated_bytes=4096,
                       candidate_apparent_bytes=10, keep_versions=2, native_plan_complete=True)
        with patch.object(provider, 'pacman_preview', return_value=preview), \
             patch.object(provider.shutil, 'which', return_value='/usr/bin/sudo-gui'), \
             patch.object(provider, 'report_actions', return_value={'blocked': {}, 'uninspected_processes': 0}):
            item = provider.plan([candidate])[0]
        self.assertEqual(item['allocated_bytes'], 4096)
        self.assertEqual(item['apparent_bytes'], 10)
        self.assertEqual(item['cache_totals']['allocated_bytes'], 100000)

    def test_dry_run_text_exposes_process_inspection_gaps(self):
        self.profile()
        result = self.tool.scan(self.home, home=self.home, mount_points=set())
        with patch.object(self.tool.project_helpers(), 'inspect_processes', return_value={'blocked': {}, 'uninspected_processes': 5}):
            result['cleanup_plan'] = self.tool.cleanup_plan(result)
        text = self.tool.render(result, dry_run=True, verbose=True)
        self.assertIn('5 processes', text)


if __name__ == '__main__':
    unittest.main()
