import importlib.machinery
import importlib.util
import json
import os
import io
import contextlib
import shutil
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'Tools/agency-storage'


def load_tool():
    loader = importlib.machinery.SourceFileLoader('agency_storage', str(TOOL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class StorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.storage = load_tool()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.destination = self.root / 'volume/cache'
        self.source = self.home / '.cache'
        self.source.mkdir()
        (self.source / 'payload').write_bytes(b'precious scratch data\0' * 100)
        os.link(self.source / 'payload', self.source / 'hardlink')
        (self.source / 'relative').symlink_to('payload')

    def test_fstab_preserves_existing_entries_and_is_idempotent(self):
        before = '# existing\nUUID=boot / btrfs defaults 0 0\n'
        after = self.storage.fstab_plan(before, 'abcd-1234', '/mnt/storage', 'btrfs')
        self.assertTrue(after.startswith(before))
        self.assertIn('UUID=abcd-1234 /mnt/storage btrfs', after)
        self.assertIn('x-systemd.automount', after)
        self.assertEqual(after, self.storage.fstab_plan(after, 'abcd-1234', '/mnt/storage', 'btrfs'))

    def test_fstab_refuses_conflicting_target_or_uuid(self):
        for content in ['UUID=other /mnt/storage btrfs defaults 0 0\n',
                        'UUID=abcd-1234 /existing btrfs defaults 0 0\n']:
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.storage.fstab_plan(content, 'abcd-1234', '/mnt/storage', 'btrfs')

    def test_fstab_rejects_injection_and_unsafe_mount(self):
        for uuid, mount in [('abc\nroot', '/mnt/storage'), ('abc', '/'), ('abc', '/mnt/../home'), ('abc', '/mnt/a b')]:
            with self.subTest(uuid=uuid, mount=mount), self.assertRaises(ValueError):
                self.storage.fstab_plan('', uuid, mount, 'btrfs')

    def test_migration_preserves_bytes_hardlinks_and_symlinks_and_reruns_noop(self):
        self.storage.migrate_folder(self.source, self.destination, lambda paths: [])
        self.assertTrue(self.source.is_symlink())
        self.assertEqual(self.source.resolve(), self.destination)
        self.assertEqual((self.source / 'payload').read_bytes(), b'precious scratch data\0' * 100)
        self.assertEqual((self.source / 'payload').stat().st_ino, (self.source / 'hardlink').stat().st_ino)
        self.assertTrue((self.source / 'relative').is_symlink())
        with patch.object(self.storage, 'run', side_effect=AssertionError('noop copied data')):
            self.storage.migrate_folder(self.source, self.destination, lambda paths: [])

    def test_active_source_is_not_switched(self):
        with self.assertRaisesRegex(RuntimeError, 'active'):
            self.storage.migrate_folder(self.source, self.destination, lambda paths: ['123 editor'])
        self.assertFalse(self.source.is_symlink())
        self.assertTrue((self.source / 'payload').is_file())

    def test_copy_failure_preserves_source(self):
        with patch.object(self.storage, 'run', side_effect=RuntimeError('copy failed')):
            with self.assertRaisesRegex(RuntimeError, 'copy failed'):
                self.storage.migrate_folder(self.source, self.destination, lambda paths: [])
        self.assertFalse(self.source.is_symlink())
        self.assertTrue((self.source / 'payload').exists())

    def test_refuses_unmanaged_destination_and_wrong_source_link(self):
        self.destination.mkdir(parents=True)
        (self.destination / 'unrelated').write_text('keep')
        with self.assertRaisesRegex(RuntimeError, 'destination'):
            self.storage.migrate_folder(self.source, self.destination, lambda paths: [])
        self.assertEqual((self.destination / 'unrelated').read_text(), 'keep')
        self.source.rename(self.home / 'original')
        self.source.symlink_to(self.home / 'original')
        with self.assertRaisesRegex(RuntimeError, 'link'):
            self.storage.migrate_folder(self.source, self.destination, lambda paths: [])

    def test_new_writer_after_copy_prevents_switch(self):
        calls = iter([[], ['123 editor']])
        with self.assertRaisesRegex(RuntimeError, 'active'):
            self.storage.migrate_folder(self.source, self.destination, lambda paths: next(calls))
        self.assertFalse(self.source.is_symlink())

    def test_unconfigured_dry_run_has_no_writes(self):
        result = subprocess.run([str(TOOL), 'setup', '--dry-run'], env={**os.environ, 'HOME': str(self.home)}, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('not configured', result.stdout)
        self.assertFalse((self.home / '.config').exists())

    def test_completed_setup_does_not_scan_processes_or_require_rsync(self):
        config = {'home': str(self.home), 'mount': '/mnt/storage', 'uid': os.getuid(), 'folders': ['cache']}
        with patch.object(self.storage, 'status', return_value={'unchanged': True}), \
             patch.object(self.storage, 'print_status'), \
             patch.object(self.storage, 'active_users', side_effect=AssertionError('scanned processes')), \
             patch.object(self.storage.shutil, 'which', return_value=None):
            self.storage.apply_setup(config)

    def test_custom_xdg_config_home_is_used(self):
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.root / 'config')}):
            self.assertEqual(self.storage.config_path(), self.root / 'config/agency/storage.json')

    def test_retry_does_not_restore_files_deleted_after_interrupted_copy(self):
        (self.source / 'removed').write_text('stale')
        calls = iter([[], ['123 editor']])
        with self.assertRaises(RuntimeError):
            self.storage.migrate_folder(self.source, self.destination, lambda paths: next(calls))
        (self.source / 'removed').unlink()
        self.storage.migrate_folder(self.source, self.destination, lambda paths: [])
        self.assertFalse((self.destination / 'removed').exists())

    def test_descendant_mount_prevents_migration(self):
        with patch.object(self.storage, 'nested_mounts', return_value=[str(self.source / 'mounted')]):
            with self.assertRaisesRegex(RuntimeError, 'mount'):
                self.storage.migrate_folder(self.source, self.destination, lambda paths: [])
        self.assertFalse(self.source.is_symlink())

    def test_new_writer_during_checksum_prevents_switch(self):
        calls = iter([[], [], ['123 editor']])
        with self.assertRaisesRegex(RuntimeError, 'active'):
            self.storage.migrate_folder(self.source, self.destination, lambda paths: next(calls))
        self.assertFalse(self.source.is_symlink())

    def test_removable_sibling_does_not_hide_internal_volume(self):
        disks = {'blockdevices': [
            {'rm': True, 'children': []},
            {'rm': False, 'uuid': 'internal', 'fstype': 'btrfs', 'path': '/dev/test', 'size': 100, 'mountpoints': []},
        ]}
        with patch.object(self.storage, 'run', return_value=json.dumps(disks)):
            self.assertEqual([item['uuid'] for item in self.storage.volumes()], ['internal'])

    def test_broken_config_link_is_an_error(self):
        config = self.home / '.config/agency/storage.json'
        config.parent.mkdir(parents=True)
        config.symlink_to(self.home / 'missing-config')
        with patch.dict(os.environ, {'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.home / '.config')}):
            with self.assertRaisesRegex(ValueError, 'config'):
                self.storage.load_config()

    def test_malformed_config_is_a_clear_error(self):
        config = self.home / '.config/agency/storage.json'
        config.parent.mkdir(parents=True)
        with patch.dict(os.environ, {'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.home / '.config')}):
            for content in ['[]', '{"version": 1}']:
                config.write_text(content)
                with self.subTest(content=content), self.assertRaises(ValueError):
                    self.storage.load_config()

    def test_empty_active_selection_does_not_inspect_any_process(self):
        with patch.object(self.storage.Path, 'iterdir', side_effect=AssertionError('process scan')):
            self.storage.assert_inactive([], self.storage.active_users)

    def test_cleanup_rejects_nested_mount_and_preserves_backup(self):
        self.storage.migrate_folder(self.source, self.destination, lambda paths: [])
        backup = self.storage.backup_path(self.source)
        with patch.object(self.storage, 'status', return_value={'unchanged': True}), \
             patch.object(self.storage, 'folder_paths', return_value=[('cache', self.source, self.destination)]), \
             patch.object(self.storage, 'nested_mounts', return_value=[str(backup / 'volume')]):
            with self.assertRaisesRegex(RuntimeError, 'mount'):
                self.storage.cleanup({}, apply=True)
        self.assertTrue((backup / 'payload').exists())

    def test_cleanup_detects_corrupt_destination_and_keeps_original(self):
        self.storage.migrate_folder(self.source, self.destination, lambda paths: [])
        (self.destination / 'payload').write_text('corrupt')
        with patch.object(self.storage, 'status', return_value={'unchanged': True}), \
             patch.object(self.storage, 'folder_paths', return_value=[('cache', self.source, self.destination)]), \
             patch.object(self.storage, 'privileged_active_users', return_value=[]):
            with self.assertRaisesRegex(RuntimeError, 'differs'):
                self.storage.cleanup({}, apply=True)
        self.assertTrue(self.storage.backup_path(self.source).is_dir())

    def test_verified_cleanup_removes_only_original_backup(self):
        self.storage.migrate_folder(self.source, self.destination, lambda paths: [])
        (self.destination / 'new-file').write_text('created after migration')
        os.utime(self.destination, (1800000000, 1800000000))
        with patch.object(self.storage, 'status', return_value={'unchanged': True}), \
             patch.object(self.storage, 'folder_paths', return_value=[('cache', self.source, self.destination)]), \
             patch.object(self.storage, 'privileged_active_users', return_value=[]):
            self.storage.cleanup({}, apply=True)
        self.assertFalse(self.storage.backup_path(self.source).exists())
        self.assertTrue((self.destination / 'new-file').exists())
        self.assertTrue((self.source / 'payload').exists())

    def test_actual_open_file_and_cwd_are_detected(self):
        child = subprocess.Popen([sys.executable, '-c',
            'import sys,time; f=open(sys.argv[1]); print("ready", flush=True); time.sleep(30)',
            str(self.source / 'payload')], stdout=subprocess.PIPE, text=True, cwd=self.source)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            blockers = self.storage.active_users([self.source])
            self.assertTrue(any(item.startswith(str(child.pid) + ' ') for item in blockers))
        finally:
            child.terminate()
            child.wait(timeout=5)
            child.stdout.close()

    def test_root_directory_setup_refuses_symlink_into_unrelated_data(self):
        volume = self.root / 'disk'
        volume.mkdir()
        unrelated = self.root / 'unrelated'
        unrelated.mkdir()
        (volume / 'agency').symlink_to(unrelated)
        with self.assertRaises(OSError):
            self.storage.prepare_user_directory(volume, os.getuid(), os.getgid())
        self.assertEqual(list(unrelated.iterdir()), [])

    def test_armed_automount_is_unchanged_without_accessing_destination(self):
        shutil.rmtree(self.source)
        destination = Path('/mnt/storage/agency') / str(os.getuid()) / 'cache'
        self.source.symlink_to(destination)
        config = {'home': str(self.home), 'mount': '/mnt/storage', 'uuid': 'abcd', 'fstype': 'btrfs', 'uid': os.getuid(), 'folders': ['cache']}
        fstab = self.storage.fstab_plan('', 'abcd', '/mnt/storage', 'btrfs')
        fixture = self.root / 'fstab'
        fixture.write_text(fstab)
        with patch.object(self.storage, 'FSTAB_PATH', fixture), \
             patch.object(self.storage, 'mount_matches', return_value=False), \
             patch.object(self.storage, 'automount_ready', return_value=True), \
             patch.object(self.storage.Path, 'is_dir', side_effect=AssertionError('accessed automount')):
            state = self.storage.status(config)
        self.assertTrue(state['unchanged'])
        self.assertTrue(state['automount_ready'])
        self.assertEqual(state['folders'][0]['state'], 'unchanged')

    def test_missing_storage_never_counts_as_unchanged(self):
        shutil.rmtree(self.source)
        destination = Path('/mnt/storage/agency') / str(os.getuid()) / 'cache'
        self.source.symlink_to(destination)
        config = {'home': str(self.home), 'mount': '/mnt/storage', 'uuid': 'abcd', 'fstype': 'btrfs', 'uid': os.getuid(), 'folders': ['cache']}
        fixture = self.root / 'fstab'
        fixture.write_text(self.storage.fstab_plan('', 'abcd', '/mnt/storage', 'btrfs'))
        with patch.object(self.storage, 'FSTAB_PATH', fixture), \
             patch.object(self.storage, 'mount_matches', return_value=False), \
             patch.object(self.storage, 'automount_ready', return_value=False):
            self.assertFalse(self.storage.status(config)['unchanged'])

    def test_saved_scratch_setup_can_add_cache_later(self):
        config = {'version': 1, 'home': str(self.home), 'uid': os.getuid(), 'uuid': 'abcd', 'mount': '/mnt/storage', 'fstype': 'btrfs', 'folders': ['scratch']}
        with patch.object(self.storage, 'load_config', return_value=config), \
             patch.object(self.storage, 'config_path', return_value=self.root / 'config/storage.json'), \
             patch.object(self.storage, 'status', return_value={'unchanged': False}), \
             patch.object(self.storage, 'print_status'), \
             patch.object(self.storage, 'apply_setup') as apply, \
             patch.object(sys, 'argv', ['agency-storage', 'setup', '--folders', 'scratch', 'cache', '--apply']):
            self.assertEqual(self.storage.main(), 0)
        self.assertEqual(apply.call_args.args[0]['folders'], ['scratch', 'cache'])
        self.assertTrue(apply.call_args.args[1])

    def test_healthy_cli_apply_creates_no_lock_or_config_writes(self):
        with patch.object(self.storage, 'load_config', return_value={'folders': ['cache', 'scratch']}), \
             patch.object(self.storage, 'config_path', side_effect=AssertionError('would create config lock')), \
             patch.object(self.storage, 'status', return_value={'unchanged': True}), \
             patch.object(self.storage, 'print_status'), \
             patch.object(self.storage, 'apply_setup', side_effect=AssertionError('would apply')), \
             patch.object(sys, 'argv', ['agency-storage', 'setup', '--apply']):
            self.assertEqual(self.storage.main(), 0)

    def test_mount_query_selects_visible_topmost_mount(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({'filesystems': [
            {'uuid': 'wrong-top', 'target': '/mnt/storage', 'fstype': 'btrfs', 'options': 'rw,subvolid=5'}
        ]}), '')
        with patch.object(self.storage.subprocess, 'run', return_value=result) as query:
            self.assertFalse(self.storage.mount_matches({'uuid': 'expected-underneath', 'mount': '/mnt/storage', 'fstype': 'btrfs'}))
        arguments = query.call_args.args[0]
        self.assertIn('--first-only', arguments)
        self.assertEqual(arguments[arguments.index('--direction') + 1], 'backward')
        self.assertIn('--nocanonicalize', arguments)

    def test_topmost_automount_never_reveals_lower_real_mount(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({'filesystems': [
            {'uuid': 'old', 'fstype': 'btrfs'}, {'uuid': None, 'fstype': 'autofs'}
        ]}), '')
        with patch.object(self.storage.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'Ambiguous'):
                self.storage.mount_info('/mnt/storage')

    def test_privileged_lock_does_not_follow_or_truncate_symlinks(self):
        victim = self.root / 'victim'
        victim.write_text('preserve these bytes')
        lock = self.root / 'lock'
        lock.symlink_to(victim)
        with self.assertRaises(OSError):
            self.storage.open_root_lock(lock)
        self.assertEqual(victim.read_text(), 'preserve these bytes')

    def test_wrong_filesystem_cannot_report_unchanged(self):
        with patch.object(self.storage, 'mount_info', return_value={'uuid': 'wrong', 'target': '/mnt/storage', 'fstype': 'btrfs', 'options': 'rw'}):
            self.assertFalse(self.storage.mount_matches({'uuid': 'expected', 'mount': '/mnt/storage', 'fstype': 'btrfs'}))

    def test_containers_selection_preserves_existing_podman_paths(self):
        config = {'home': str(self.home), 'mount': '/mnt/storage', 'uid': os.getuid(), 'folders': ['containers']}
        self.assertEqual(self.storage.folder_paths(config), [
            ('containers', self.home / '.local/share/containers',
             Path('/mnt/storage/agency') / str(os.getuid()) / 'containers')])

    def podman_info(self, graphroot=None):
        return json.dumps({'host': {'security': {'rootless': True}},
                           'store': {'graphRoot': str(graphroot or self.home / '.local/share/containers/storage')}})

    def test_podman_running_containers_prevent_migration(self):
        with patch.object(self.storage, 'run', side_effect=[self.podman_info(), 'running-container\n']):
            with self.assertRaisesRegex(RuntimeError, 'running containers'):
                self.storage.podman_preflight(self.home / '.local/share/containers')

    def test_podman_custom_graphroot_is_not_silently_left_on_root(self):
        with patch.object(self.storage, 'run', return_value=self.podman_info(self.home / 'other-storage')):
            with self.assertRaisesRegex(RuntimeError, 'graphRoot'):
                self.storage.podman_preflight(self.home / '.local/share/containers')

    def test_podman_overrides_are_rejected_before_queries(self):
        for name in ('CONTAINER_HOST', 'CONTAINER_CONNECTION', 'CONTAINERS_CONF',
                     'CONTAINERS_CONF_OVERRIDE', 'CONTAINERS_STORAGE_CONF', 'TMPDIR'):
            with self.subTest(name=name), patch.dict(os.environ, {name: '/unexpected'}), \
                 patch.object(self.storage, 'run', side_effect=AssertionError('queried with override')):
                with self.assertRaisesRegex(ValueError, 'override'):
                    self.storage.podman_preflight(self.home / '.local/share/containers')

    def test_podman_mounts_prevent_copy_even_without_running_containers(self):
        with patch.object(self.storage, 'run', side_effect=[self.podman_info(), '', '/mounted-overlay\n']):
            with self.assertRaisesRegex(RuntimeError, 'mounted'):
                self.storage.podman_preflight(self.home / '.local/share/containers')

    def test_container_copy_and_verification_use_user_namespace(self):
        calls = []

        def copy_command(arguments):
            calls.append(arguments)
            return self.storage.run(arguments)

        self.storage.migrate_folder(self.source, self.destination, lambda paths: [], command=copy_command)
        self.assertTrue(self.source.is_symlink())
        self.assertEqual(sum(command[0] == 'rsync' for command in calls), 2)
        self.assertTrue(any('--checksum' in command for command in calls))
        with patch.object(self.storage, 'run', return_value='') as run:
            self.storage.podman_copy(['rsync', 'source/', 'destination/'])
        run.assert_called_once_with(['podman', 'unshare', 'rsync', 'source/', 'destination/'])

    def test_podman_temp_config_preserves_other_settings_and_is_idempotent(self):
        config_root = self.home / '.config'
        existing = config_root / 'containers/containers.conf'
        existing.parent.mkdir(parents=True)
        existing.write_text('[engine]\nevents_logger = "file"\n')
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(config_root)}):
            self.storage.configure_podman(self.source)
            target = self.storage.podman_config_path()
            before = target.stat().st_mtime_ns
            self.storage.configure_podman(self.source)
            self.assertEqual(before, target.stat().st_mtime_ns)
            self.assertIn('image_copy_tmp_dir = "storage"', target.read_text())
        self.assertEqual(existing.read_text(), '[engine]\nevents_logger = "file"\n')

    def test_podman_config_conflict_is_preserved(self):
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.home / '.config')}):
            target = self.storage.podman_config_path()
            target.parent.mkdir(parents=True)
            target.write_text('unrelated content')
            with self.assertRaisesRegex(ValueError, 'Podman config'):
                self.storage.configure_podman(self.source)
            self.assertEqual(target.read_text(), 'unrelated content')

    def test_btrfs_destination_compression_policy_does_not_fail_copy_verification(self):
        for verify in (False, True):
            arguments = self.storage.rsync_arguments(self.source, self.destination, verify=verify)
            self.assertIn('--filter=-x btrfs.compression', arguments)
            self.assertIn('-aHAXx', arguments)

    def test_container_copy_uses_privileged_helper_after_releasing_namespace_bind(self):
        config = {'uuid': 'abcd', 'mount': '/mnt/storage', 'fstype': 'btrfs', 'uid': os.getuid()}
        with patch.object(self.storage, 'run', return_value='') as run:
            self.storage.migrate_containers(config, self.source)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][:2], ['podman', 'unshare'])
        self.assertIn('_release-container-bind', run.call_args_list[0].args[0])
        self.assertEqual(run.call_args.args[0][0], 'sudo')
        self.assertIn('_migrate-containers', run.call_args.args[0])

    def test_privileged_container_migration_refuses_unmounted_storage(self):
        with patch.object(self.storage.os, 'geteuid', return_value=0), \
             patch.object(self.storage, 'mount_matches', return_value=False), \
             patch.object(self.storage, 'migrate_folder', side_effect=AssertionError('copied onto root')):
            with self.assertRaisesRegex(RuntimeError, 'mount'):
                self.storage.root_migrate_containers('abcd', '/mnt/storage', 'btrfs', os.getuid())

    def test_podman_overlay_self_bind_is_released_before_copy(self):
        overlay = self.source / 'storage/overlay'
        parent = {'target': str(self.root), 'fsroot': '/@home', 'maj:min': '0:34'}
        mounted = {'target': str(overlay), 'fsroot': '/@home/home/.cache/storage/overlay', 'maj:min': '0:34'}
        with patch.object(self.storage, 'nested_mounts', return_value=[str(overlay)]), \
             patch.object(self.storage, 'run', side_effect=[json.dumps({'filesystems': [parent]}),
                                                          json.dumps({'filesystems': [mounted]}), '']) as run:
            self.storage.release_podman_bind(self.source)
        self.assertEqual(run.call_args.args[0], ['umount', '--', str(overlay)])

    def test_podman_foreign_bind_mount_is_preserved(self):
        overlay = self.source / 'storage/overlay'
        parent = {'target': str(self.root), 'fsroot': '/@home', 'maj:min': '0:34'}
        mounted = {'target': str(overlay), 'fsroot': '/unrelated', 'maj:min': '0:34'}
        with patch.object(self.storage, 'nested_mounts', return_value=[str(overlay)]), \
             patch.object(self.storage, 'run', side_effect=[json.dumps({'filesystems': [parent]}),
                                                          json.dumps({'filesystems': [mounted]})]) as run:
            with self.assertRaisesRegex(RuntimeError, 'self-bind'):
                self.storage.release_podman_bind(self.source)
        self.assertEqual(run.call_count, 2)

    def test_podman_nested_volume_mount_is_preserved(self):
        with patch.object(self.storage, 'nested_mounts', return_value=[str(self.source / 'storage/overlay/merged')]), \
             patch.object(self.storage, 'run', side_effect=AssertionError('must not unmount')):
            with self.assertRaisesRegex(RuntimeError, 'nested mounts'):
                self.storage.release_podman_bind(self.source)

    def test_automount_accepts_systemd_resolved_device_for_saved_uuid(self):
        config = {'uuid': 'abcd', 'mount': '/mnt/storage', 'fstype': 'btrfs'}
        result = subprocess.CompletedProcess([], 0, 'What=/dev/nvme1n1p1\nWhere=/mnt/storage\n', '')
        with patch.object(self.storage, 'mount_info', return_value={'fstype': 'autofs'}), \
             patch.object(self.storage.Path, 'is_block_device', return_value=True), \
             patch.object(self.storage, 'run', return_value='mnt-storage.mount'), \
             patch.object(self.storage.subprocess, 'run', return_value=result), \
             patch.object(self.storage.os.path, 'realpath', return_value='/dev/nvme1n1p1'):
            self.assertTrue(self.storage.automount_ready(config))

    def test_automount_rejects_a_different_resolved_device(self):
        config = {'uuid': 'abcd', 'mount': '/mnt/storage', 'fstype': 'btrfs'}
        result = subprocess.CompletedProcess([], 0, 'What=/dev/wrong\nWhere=/mnt/storage\n', '')
        with patch.object(self.storage, 'mount_info', return_value={'fstype': 'autofs'}), \
             patch.object(self.storage.Path, 'is_block_device', return_value=True), \
             patch.object(self.storage, 'run', return_value='mnt-storage.mount'), \
             patch.object(self.storage.subprocess, 'run', return_value=result), \
             patch.object(self.storage.os.path, 'realpath', side_effect=['/dev/wrong', '/dev/expected']):
            self.assertFalse(self.storage.automount_ready(config))

    def test_linked_containers_with_missing_download_config_are_not_complete(self):
        source = self.home / '.local/share/containers'
        destination = self.root / 'volume/agency' / str(os.getuid()) / 'containers'
        source.parent.mkdir(parents=True)
        destination.mkdir(parents=True)
        source.symlink_to(destination)
        config = {'home': str(self.home), 'mount': str(self.root / 'volume'), 'uuid': 'abcd',
                  'fstype': 'btrfs', 'uid': os.getuid(), 'folders': ['containers']}
        fixture = self.root / 'fstab'
        fixture.write_text('test fstab')
        with patch.object(self.storage, 'FSTAB_PATH', fixture), \
             patch.object(self.storage, 'mount_matches', return_value=True), \
             patch.object(self.storage, 'fstab_plan', return_value='test fstab'), \
             patch.object(self.storage, 'podman_config_ready', return_value=False):
            state = self.storage.status(config)
        self.assertFalse(state['unchanged'])
        self.assertEqual(state['folders'][0]['state'], 'Podman configuration pending')

    def test_effective_podman_override_cannot_report_healthy_storage(self):
        self.destination.mkdir(parents=True)
        (self.destination / 'storage/tmp').mkdir(parents=True)
        shutil.rmtree(self.source)
        self.source.symlink_to(self.destination)
        config = {'uuid': 'abcd', 'mount': '/mnt/storage', 'fstype': 'btrfs'}
        fixture = self.root / 'fstab'
        fixture.write_text('test fstab')
        info = json.loads(self.podman_info(self.source / 'storage'))
        info['store']['imageCopyTmpDir'] = '/var/tmp'
        with patch.object(self.storage, 'FSTAB_PATH', fixture), \
             patch.object(self.storage, 'mount_matches', return_value=True), \
             patch.object(self.storage, 'fstab_plan', return_value='test fstab'), \
             patch.object(self.storage, 'folder_paths', return_value=[('containers', self.source, self.destination)]), \
             patch.object(self.storage, 'podman_config_ready', return_value=True), \
             patch.object(self.storage, 'run', return_value=json.dumps(info)):
            state = self.storage.status(config)
        self.assertFalse(state['unchanged'])
        self.assertIn('download', state['folders'][0]['state'])

    def test_armed_podman_status_defers_query_without_claiming_verified(self):
        shutil.rmtree(self.source)
        self.source.symlink_to('/mnt/storage/agency/1000/containers')
        config = {'uuid': 'abcd', 'mount': '/mnt/storage', 'fstype': 'btrfs'}
        fixture = self.root / 'fstab'
        fixture.write_text('test fstab')
        with patch.object(self.storage, 'FSTAB_PATH', fixture), \
             patch.object(self.storage, 'mount_matches', return_value=False), \
             patch.object(self.storage, 'automount_ready', return_value=True), \
             patch.object(self.storage, 'fstab_plan', return_value='test fstab'), \
             patch.object(self.storage, 'folder_paths', return_value=[('containers', self.source, Path('/mnt/storage/agency/1000/containers'))]), \
             patch.object(self.storage, 'podman_config_ready', return_value=True), \
             patch.object(self.storage, 'run', side_effect=AssertionError('activated automount')):
            state = self.storage.status(config)
        self.assertFalse(state['unchanged'])
        self.assertTrue(state['automount_ready'])
        self.assertIn('verification pending', state['folders'][0]['state'])

    def test_privileged_scanner_checks_all_users_and_refuses_unprivileged_calls(self):
        with patch.object(sys, 'argv', ['agency-storage', '_active-users', '--', str(self.source)]), \
             patch.object(self.storage.os, 'geteuid', return_value=1000):
            with self.assertRaisesRegex(ValueError, 'requires root'):
                self.storage.main()
        with patch.object(sys, 'argv', ['agency-storage', '_active-users', '--', str(self.source)]), \
             patch.object(self.storage.os, 'geteuid', return_value=0), \
             patch.object(self.storage, 'active_users', return_value=['42 writer']) as users, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.storage.main()
        users.assert_called_once_with([self.source], all_users=True)
        self.assertEqual(json.loads(output.getvalue()), ['42 writer'])

    def test_generic_migration_uses_privileged_process_inspection(self):
        config = {'home': str(self.home), 'mount': str(self.root / 'volume'), 'uid': os.getuid(), 'folders': ['cache']}
        (self.root / 'volume/agency' / str(os.getuid())).mkdir(parents=True)
        state = {'unchanged': False, 'mounted': True, 'fstab_unchanged': True}
        with patch.object(self.storage, 'status', return_value=state), \
             patch.object(self.storage, 'print_status'), \
             patch.object(self.storage, 'mount_matches', return_value=True), \
             patch.object(self.storage, 'active_users', side_effect=AssertionError('unprivileged process inspection')), \
             patch.object(self.storage, 'run', return_value='[]') as run, \
             patch.object(self.storage, 'migrate_folder') as migrate:
            self.storage.apply_setup(config)
        self.assertEqual(run.call_args.args[0][0], 'sudo')
        self.assertIn('_active-users', run.call_args.args[0])
        self.assertEqual(migrate.call_args.kwargs['users'], self.storage.privileged_active_users)

    def test_container_cleanup_refuses_non_file_runtime_lock(self):
        (self.source / 'storage/storage.lock').mkdir(parents=True)
        (self.source / 'storage/storage.lock/payload').write_text('must not be excluded')
        self.storage.migrate_folder(self.source, self.destination, lambda paths: [])
        with patch.object(self.storage, 'status', return_value={'unchanged': True}), \
             patch.object(self.storage, 'folder_paths', return_value=[('containers', self.source, self.destination)]), \
             patch.object(self.storage, 'privileged_active_users', return_value=[]), \
             patch.object(self.storage, 'podman_preflight'), \
             patch.object(self.storage, 'run', side_effect=AssertionError('comparison must not exclude directory')):
            with self.assertRaisesRegex(RuntimeError, 'runtime lock'):
                self.storage.cleanup({}, apply=True)
        self.assertTrue((self.storage.backup_path(self.source) / 'storage/storage.lock/payload').is_file())

    def test_container_cleanup_ignores_only_runtime_lock_and_preserves_changed_data(self):
        (self.source / 'storage').mkdir()
        (self.source / 'storage/storage.lock').write_text('old runtime lock')
        self.storage.migrate_folder(self.source, self.destination, lambda paths: [])
        (self.destination / 'storage/storage.lock').write_text('updated runtime lock')
        real_run = self.storage.run
        commands = []

        def run(arguments, **kwargs):
            commands.append(arguments)
            if '_active-users' in arguments:
                return '[]'
            return real_run(arguments[1:] if arguments[0] == 'sudo' else arguments, **kwargs)

        with patch.object(self.storage, 'status', return_value={'unchanged': True}), \
             patch.object(self.storage, 'folder_paths', return_value=[('containers', self.source, self.destination)]), \
             patch.object(self.storage, 'active_users', return_value=[]), \
             patch.object(self.storage, 'podman_preflight'), \
             patch.object(self.storage, 'podman_idle'), \
             patch.object(self.storage, 'podman_copy', side_effect=AssertionError('cleanup initialized Podman again')), \
             patch.object(self.storage, 'run', side_effect=run):
            original = (self.destination / 'payload').read_bytes()
            (self.destination / 'payload').write_bytes(b'changed database')
            with self.assertRaisesRegex(RuntimeError, 'differs'):
                self.storage.cleanup({}, apply=True)
            self.assertTrue(self.storage.backup_path(self.source).exists())
            (self.destination / 'payload').write_bytes(original)
            shutil.copystat(self.storage.backup_path(self.source) / 'payload', self.destination / 'payload')
            self.storage.cleanup({}, apply=True)
        self.assertFalse(self.storage.backup_path(self.source).exists())
        self.assertTrue((self.destination / 'payload').exists())
        self.assertEqual((self.destination / 'storage/storage.lock').read_text(), 'updated runtime lock')
        self.assertTrue(any(command[:2] == ['sudo', 'rsync'] for command in commands))

    def test_podman_setup_creates_image_download_directory(self):
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.home / '.config')}):
            self.storage.configure_podman(self.source)
        self.assertTrue((self.source / 'storage/tmp').is_dir())

    def test_linked_container_configuration_can_be_repaired_without_stopping_containers(self):
        source = self.home / '.local/share/containers'
        destination = self.root / 'volume/agency' / str(os.getuid()) / 'containers'
        source.parent.mkdir(parents=True)
        destination.mkdir(parents=True)
        source.symlink_to(destination)
        config = {'home': str(self.home), 'mount': str(self.root / 'volume'), 'uuid': 'abcd',
                  'fstype': 'btrfs', 'uid': os.getuid(), 'folders': ['containers']}
        state = {'unchanged': False, 'mounted': True, 'fstab_unchanged': True}
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.home / '.config')}), \
             patch.object(self.storage, 'status', return_value=state), \
             patch.object(self.storage, 'print_status'), \
             patch.object(self.storage, 'mount_matches', return_value=True), \
             patch.object(self.storage, 'podman_preflight', side_effect=AssertionError('must not stop running containers')), \
             patch.object(self.storage, 'migrate_containers', side_effect=AssertionError('must not recopy')), \
             patch.object(self.storage, 'podman_download_issue', return_value=None):
            self.storage.apply_setup(config)
        self.assertTrue((destination / 'storage/tmp').is_dir())

    def test_missing_linked_container_data_is_not_replaced_with_empty_storage(self):
        source = self.home / '.local/share/containers'
        destination = self.root / 'volume/agency' / str(os.getuid()) / 'containers'
        source.parent.mkdir(parents=True)
        destination.parent.mkdir(parents=True)
        source.symlink_to(destination)
        config = {'home': str(self.home), 'mount': str(self.root / 'volume'), 'uuid': 'abcd',
                  'fstype': 'btrfs', 'uid': os.getuid(), 'folders': ['containers']}
        state = {'unchanged': False, 'mounted': True, 'fstab_unchanged': True}
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.home / '.config')}), \
             patch.object(self.storage, 'status', return_value=state), \
             patch.object(self.storage, 'print_status'), \
             patch.object(self.storage, 'mount_matches', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'missing'):
                self.storage.apply_setup(config)
        self.assertFalse(destination.exists())


if __name__ == '__main__':
    unittest.main()
