import importlib.util
import os
import mmap
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'Tools/housekeeping_projects.py'
spec = importlib.util.spec_from_file_location('housekeeping_projects', TOOL)
module = importlib.util.module_from_spec(spec)


class ProjectCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec.loader.exec_module(module)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = self.root / '.venv'
        self.env.mkdir()
        (self.env / 'pyvenv.cfg').write_text('home = /usr/bin\n')
        (self.env / 'payload').write_text('generated')
        (self.root / 'source.py').write_text('precious source')
        info = self.env.stat()
        self.item = {'path': str(self.env), 'category': 'python_environments',
                     'identity': {'device': info.st_dev, 'inode': info.st_ino}, 'scan_complete': True}

    def test_removes_selected_environment_and_preserves_source(self):
        result = module.validate_projects([self.item])
        self.assertIsInstance(result['uninspected_processes'], int)
        module.remove_project(self.item)
        self.assertFalse(self.env.exists())
        self.assertEqual((self.root / 'source.py').read_text(), 'precious source')
        self.assertEqual(list(self.root.iterdir()), [self.root / 'source.py'])

    def test_changed_identity_and_symlink_are_refused(self):
        self.env.rename(self.root / 'original')
        self.env.mkdir()
        with self.assertRaisesRegex(RuntimeError, 'identity'):
            module.validate_projects([self.item])
        self.env.rmdir()
        self.env.symlink_to(self.root / 'original', target_is_directory=True)
        with self.assertRaises(RuntimeError):
            module.remove_project(self.item)
        self.assertTrue((self.root / 'original/payload').exists())

    def test_symlink_ancestor_and_current_interpreter_are_refused(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            module.validate_projects([{**self.item, 'path': str(alias / '.venv')}])
        with patch.object(module.sys, 'prefix', str(self.env)):
            with self.assertRaisesRegex(RuntimeError, 'active'):
                module.validate_projects([self.item])

    def test_unsafe_recursive_removal_implementation_is_refused(self):
        with patch.object(module.shutil.rmtree, 'avoids_symlink_attacks', False):
            with self.assertRaisesRegex(RuntimeError, 'descriptor-safe'):
                module.remove_project(self.item)
        self.assertTrue((self.env / 'payload').exists())

    def test_mount_root_and_descendant_are_refused(self):
        for mount in (self.env, self.env / 'mounted'):
            with self.subTest(mount=mount), patch.object(module, 'mount_paths', return_value={str(mount)}):
                with self.assertRaisesRegex(RuntimeError, 'mount'):
                    module.validate_projects([self.item])

    def test_tracked_git_files_are_refused(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        subprocess.run(['git', '-C', str(self.root), 'add', '-f', '.venv/payload'], check=True)
        with self.assertRaisesRegex(RuntimeError, 'tracked'):
            module.validate_projects([self.item])
        self.assertTrue(self.env.exists())

    def test_ignored_environment_with_nested_git_repository_is_refused(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root / '.gitignore').write_text('.venv/\n')
        nested = self.env / 'editable-source'
        nested.mkdir()
        subprocess.run(['git', 'init', '-q', str(nested)], check=True)
        (nested / 'source.py').write_text('precious editable source')
        subprocess.run(['git', '-C', str(nested), 'add', 'source.py'], check=True)
        with self.assertRaisesRegex(RuntimeError, 'Git'):
            module.validate_projects([self.item])
        with self.assertRaisesRegex(RuntimeError, 'Git'):
            module.remove_project(self.item)
        self.assertTrue((nested / 'source.py').exists())

    def test_active_child_cwd_and_fd_are_refused(self):
        for use in ('cwd', 'fd'):
            arguments = [sys.executable, '-c', 'import time; time.sleep(30)']
            cwd = self.env if use == 'cwd' else self.root
            handle = open(self.env / 'payload') if use == 'fd' else None
            process = subprocess.Popen(arguments, cwd=cwd, pass_fds=(() if handle is None else (handle.fileno(),)))
            if handle:
                handle.close()
                handle = None
            try:
                with self.subTest(use=use), self.assertRaisesRegex(RuntimeError, 'active'):
                    module.validate_projects([self.item])
            finally:
                process.terminate()
                process.wait()
                if handle:
                    handle.close()

    def test_uninspectable_processes_are_counted(self):
        original = module._read_process_file
        def restricted(path):
            if str(path) == f'/proc/{os.getpid()}/environ':
                raise PermissionError('fixture restricted process')
            return original(path)
        with patch.object(module, '_read_process_file', side_effect=restricted):
            result = module.validate_projects([self.item])
        self.assertGreaterEqual(result['uninspected_processes'], 1)

    def test_virtual_env_of_active_child_is_detected(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                   env=dict(os.environ, VIRTUAL_ENV=str(self.env)), cwd=self.root)
        try:
            with self.assertRaisesRegex(RuntimeError, 'active'):
                module.validate_projects([self.item])
        finally:
            process.terminate()
            process.wait()

    def test_relative_command_argument_is_detected(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)', '.venv/payload'], cwd=self.root)
        try:
            with self.assertRaisesRegex(RuntimeError, 'active'):
                module.validate_projects([self.item])
        finally:
            process.terminate()
            process.wait()

    def test_git_errors_are_not_treated_as_untracked(self):
        with patch.object(module.subprocess, 'run', return_value=subprocess.CompletedProcess([], 128, b'', b'fatal: permission denied')):
            with self.assertRaisesRegex(RuntimeError, 'Git'):
                module.validate_projects([self.item])

    def test_batch_inspects_processes_once_and_rejects_overlaps(self):
        node = self.root / 'node_modules'
        node.mkdir()
        info = node.stat()
        item = {'path': str(node), 'category': 'node_dependencies', 'scan_complete': True,
                'identity': {'device': info.st_dev, 'inode': info.st_ino}}
        with patch.object(module, 'inspect_processes', return_value={'blocked': {}, 'uninspected_processes': 2}) as inspect:
            self.assertEqual(module.validate_projects([self.item, item]), {'uninspected_processes': 2})
        inspect.assert_called_once()
        with self.assertRaisesRegex(RuntimeError, 'overlap'):
            module.validate_projects([self.item, self.item])
        module.remove_project(item)
        self.assertFalse(node.exists())
        self.assertTrue(self.env.exists())

    def test_move_identity_race_preserves_unexpected_data(self):
        original = module.os.rename
        def changed(source, destination, **kwargs):
            original(self.env, self.root / 'saved-environment')
            self.env.mkdir()
            (self.env / 'precious').write_text('do not delete')
            return original(source, destination, **kwargs)
        with patch.object(module.os, 'rename', side_effect=changed):
            with self.assertRaisesRegex(RuntimeError, 'holding'):
                module.remove_project(self.item)
        holding = next(self.root.glob('.housekeeping-*'))
        self.assertEqual((holding / 'selected/precious').read_text(), 'do not delete')
        self.assertTrue((self.root / 'saved-environment/payload').exists())

    def node_item(self):
        node = self.root / 'node_modules'
        node.mkdir()
        info = node.stat()
        return {'path': str(node), 'category': 'node_dependencies', 'scan_complete': True,
                'identity': {'device': info.st_dev, 'inode': info.st_ino}}

    def test_report_maps_active_child_only_to_its_own_root(self):
        node = self.node_item()
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)', '--private-token=TOP_SECRET_VALUE'], cwd=self.env)
        try:
            report = module.report_projects([self.item, node])
            self.assertEqual(set(report['blocked']), {str(self.env)})
            reason = report['blocked'][str(self.env)]
            self.assertIn(str(process.pid), reason)
            self.assertIn('python', reason.lower())
            self.assertIn('cwd', reason)
            self.assertNotIn('TOP_SECRET_VALUE', str(report))
            self.assertNotIn('private-token', str(report))
            with self.assertRaisesRegex(RuntimeError, 'python'):
                module.validate_projects([self.item, node])
        finally:
            process.terminate()
            process.wait()

    def test_report_explains_open_and_mapped_files_without_exposing_contents(self):
        with open(self.env / 'payload', 'r+b') as handle:
            mapped = mmap.mmap(handle.fileno(), 0)
            try:
                report = module.report_projects([self.item])
                reason = report['blocked'][str(self.env)]
                self.assertIn('open file', reason)
                self.assertIn('mapped file', reason)
                self.assertIn(str(os.getpid()), reason)
                self.assertNotIn('generated', reason)
                self.assertNotIn(str(self.env / 'payload'), reason)
            finally:
                mapped.close()

    def test_report_explains_virtual_env_and_command_path(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)', '.venv/payload', '--token=NOT_FOR_REPORT'],
                                   env=dict(os.environ, VIRTUAL_ENV=str(self.env)), cwd=self.root)
        try:
            report = module.report_projects([self.item])
            reason = report['blocked'][str(self.env)]
            self.assertIn('command path', reason)
            self.assertIn('VIRTUAL_ENV', reason)
            self.assertNotIn('NOT_FOR_REPORT', reason)
            self.assertNotIn(str(self.env), reason)
        finally:
            process.terminate()
            process.wait()

    def test_report_retains_independent_structural_and_active_blockers(self):
        node = self.node_item()
        invalid = {**self.item, 'scan_complete': False}
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], cwd=node['path'])
        try:
            report = module.report_projects([invalid, node])
            self.assertEqual(set(report['blocked']), {str(self.env), node['path']})
            self.assertIn('incomplete', report['blocked'][str(self.env)])
            self.assertIn('cwd', report['blocked'][node['path']])
        finally:
            process.terminate()
            process.wait()

    def test_report_uses_one_proc_traversal_for_eligible_roots(self):
        node = self.node_item()
        original = module.os.scandir
        seen = []
        def counted(path):
            if path == '/proc':
                seen.append(path)
            return original(path)
        with patch.object(module.os, 'scandir', side_effect=counted):
            report = module.report_projects([self.item, node])
        self.assertEqual(report['blocked'], {})
        self.assertEqual(seen, ['/proc'])

    def test_report_supports_more_than_selection_limit(self):
        items = [{**self.item, 'path': str(self.root / f'project-{index}' / '.venv'), 'scan_complete': False} for index in range(129)]
        report = module.report_projects(items)
        self.assertEqual(len(report['blocked']), 129)
        with self.assertRaisesRegex(RuntimeError, '128'):
            module.validate_projects(items)

    def test_incomplete_and_marker_symlink_are_refused(self):
        with self.assertRaises(RuntimeError):
            module.validate_projects([{**self.item, 'scan_complete': False}])
        (self.env / 'pyvenv.cfg').unlink()
        (self.env / 'pyvenv.cfg').symlink_to(self.root / 'source.py')
        with self.assertRaisesRegex(RuntimeError, 'pyvenv'):
            module.validate_projects([self.item])

    def test_inner_symlink_does_not_delete_its_target(self):
        (self.env / 'linked').symlink_to(self.root / 'source.py')
        module.remove_project(self.item)
        self.assertEqual((self.root / 'source.py').read_text(), 'precious source')

    def test_failed_removal_preserves_holding_directory(self):
        with patch.object(module.shutil, 'rmtree', side_effect=OSError('fixture failure')) as remove:
            remove.avoids_symlink_attacks = True
            with self.assertRaisesRegex(RuntimeError, 'holding'):
                module.remove_project(self.item)
        self.assertFalse(self.env.exists())
        holding = list(self.root.glob('.housekeeping-*'))
        self.assertEqual(len(holding), 1)
        self.assertTrue((holding[0] / 'selected/payload').exists())


if __name__ == '__main__':
    unittest.main()
