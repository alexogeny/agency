import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class ProcessInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.proc = self.root / 'proc'
        self.proc.mkdir()
        self.storage = load(ROOT / 'Tools/agency-storage', 'inspection_storage')
        self.projects = load(ROOT / 'Tools/housekeeping_projects.py', 'inspection_projects')
        self.watched = str(self.root / 'watched space')
        self.outside = str(self.root / 'outside')

    def process(self, pid='11', *, cwd=None, exe=None, fd=None, maps=None, cmdline=None, environ=None):
        process = self.proc / pid
        process.mkdir()
        (process / 'fd').mkdir()
        (process / 'comm').write_text('fixture\n')
        (process / 'cwd').symlink_to(cwd or self.outside)
        (process / 'exe').symlink_to(exe or self.outside + '/bin')
        if fd:
            (process / 'fd/3').symlink_to(fd)
        (process / 'maps').write_bytes(maps or b'')
        (process / 'cmdline').write_bytes(cmdline or b'')
        (process / 'environ').write_bytes(environ or b'')
        return process

    def inspect(self, *, all_users=False, ignore_own_arguments=False):
        original_path = Path
        original_scandir = os.scandir

        def mapped_path(value):
            return self.proc if str(value) == '/proc' else original_path(value)

        def scandir(value):
            return original_scandir(self.proc if str(value) == '/proc' else value)

        with patch.object(self.storage, 'Path', side_effect=mapped_path), \
             patch.object(os, 'scandir', side_effect=scandir), patch.object(os, 'getpid', return_value=900), \
             patch.object(os, 'getcwd', return_value=self.outside), \
             patch.object(sys, 'prefix', self.outside), patch.object(sys, 'argv', ['-c']):
            return (self.storage.active_users([self.watched], all_users=all_users),
                    self.projects.inspect_processes([self.watched], ignore_own_arguments=ignore_own_arguments))

    def test_cwd_fd_and_deleted_maps_keep_both_callers_blocked(self):
        for kind in ('cwd', 'fd', 'maps'):
            with self.subTest(kind=kind):
                values = {kind: self.watched + '/file'}
                if kind == 'maps':
                    values[kind] = ('0-1 r--p 0 00:00 0 ' + self.watched + ' (deleted)\n').encode()
                process = self.process(**values)
                storage, projects = self.inspect()
                self.assertEqual(storage, ['11 fixture'])
                self.assertIn(self.watched, projects['blocked'])
                self.assertEqual(projects['uninspected_processes'], 0)
                for child in (process / 'fd').iterdir():
                    child.unlink()
                (process / 'fd').rmdir()
                for child in process.iterdir():
                    child.unlink()
                process.rmdir()

    def test_storage_footprint_excludes_executable_arguments_and_environment(self):
        self.process(exe=self.watched + '/bin', cmdline=('--input=' + self.watched + '/file\0').encode(),
                     environ=('VIRTUAL_ENV=' + self.watched + '\0').encode())
        reads = []
        storage_files, project_files = [], []
        original_readlink = os.readlink
        storage_reader = self.storage.process_helpers['read_process_file']
        project_reader = self.projects.process_helpers['read_process_file']

        def readlink(path):
            reads.append(str(path))
            return original_readlink(path)

        def storage_read(path, **options):
            storage_files.append(Path(path).name)
            return storage_reader(path, **options)

        def project_read(path, **options):
            project_files.append(Path(path).name)
            return project_reader(path, **options)

        with patch.object(os, 'readlink', side_effect=readlink), \
             patch.dict(self.storage.process_helpers, read_process_file=storage_read), \
             patch.dict(self.projects.process_helpers, read_process_file=project_read):
            storage, projects = self.inspect()
        self.assertEqual(storage, [])
        reason = projects['blocked'][self.watched]
        self.assertIn('command path', reason)
        self.assertIn('VIRTUAL_ENV', reason)
        self.assertEqual(sum(path.endswith('/exe') for path in reads), 1)
        self.assertEqual(storage_files, ['comm', 'maps'])
        self.assertEqual(project_files, ['comm', 'maps', 'cmdline', 'environ'])

    def test_octal_maps_and_dot_normalization_remain_housekeeping_only(self):
        escaped = self.watched.replace(' ', r'\040') + '/nested/../file (deleted)'
        self.process(maps=('0-1 r--p 0 00:00 0 ' + escaped + '\n').encode())
        storage, projects = self.inspect()
        self.assertEqual(storage, [])
        self.assertIn('mapped file', projects['blocked'][self.watched])

    def test_storage_all_users_and_own_pid_exclusion_remain_independent(self):
        self.process(cwd=self.watched)
        self.process(pid='900', cwd=self.watched)
        with patch.object(os, 'getuid', return_value=os.getuid() + 1):
            storage, projects = self.inspect()
            self.assertEqual(storage, [])
            self.assertEqual(projects, {'blocked': {}, 'uninspected_processes': 0})
            storage, projects = self.inspect(all_users=True)
            self.assertEqual(storage, ['11 fixture'])
            self.assertEqual(projects, {'blocked': {}, 'uninspected_processes': 0})

    def test_own_argument_exclusion_does_not_hide_other_arguments_or_cwd(self):
        self.process(pid='900', cmdline=(self.watched + '/scan-target\0').encode())
        _, ordinary = self.inspect()
        _, excluded = self.inspect(ignore_own_arguments=True)
        self.assertIn(self.watched, ordinary['blocked'])
        self.assertEqual(excluded['blocked'], {})
        self.process(pid='12', cwd=self.outside, cmdline=('nested/' + '../watched space/file\0').encode())
        # Relative arguments resolve against the process cwd, rather than scanner cwd.
        process = self.proc / '12'
        (process / 'cwd').unlink()
        (process / 'cwd').symlink_to(str(self.root))
        (process / 'cmdline').write_bytes(b'nested/../watched space/file\0')
        _, excluded = self.inspect(ignore_own_arguments=True)
        self.assertIn(self.watched, excluded['blocked'])

    def test_permission_gaps_keep_distinct_fail_closed_policies(self):
        process = self.process()
        original = os.readlink

        def restricted(path):
            if Path(path) == process / 'cwd':
                raise PermissionError('fixture')
            return original(path)

        with patch.object(os, 'readlink', side_effect=restricted):
            storage, projects = self.inspect()
        self.assertEqual(storage, ['11 (cannot inspect process; run after logging out)'])
        self.assertEqual(projects, {'blocked': {}, 'uninspected_processes': 1})

    def test_disappearing_map_retains_each_callers_exit_policy(self):
        process = self.process(cwd=self.watched)
        (process / 'maps').unlink()
        storage, projects = self.inspect()
        self.assertEqual(storage, [])
        self.assertIn('cwd', projects['blocked'][self.watched])
        self.assertEqual(projects['uninspected_processes'], 0)

    def test_housekeeping_read_limit_does_not_expand_storage_policy(self):
        self.process(maps=b'x' * (self.projects.PROC_LIMIT + 1))
        storage, projects = self.inspect()
        self.assertEqual(storage, [])
        self.assertEqual(projects, {'blocked': {}, 'uninspected_processes': 1})

    def test_shared_readers_preserve_limits_normalization_and_map_modes(self):
        helper = load(ROOT / 'Tools/agency_processes.py', 'inspection_helpers')
        data = self.root / 'data'
        data.write_bytes(b'abcd')
        self.assertEqual(helper.read_process_file(data), b'abcd')
        self.assertEqual(helper.read_process_file(data, text=True), 'abcd')
        self.assertEqual(helper.read_process_file(data, limit=4), b'abcd')
        with self.assertRaisesRegex(OSError, 'size limit'):
            helper.read_process_file(data, limit=3)
        self.assertEqual(helper.normalize_path('/a/../b (deleted)'), '/a/../b')
        self.assertEqual(helper.normalize_path('/a/../b (deleted)', collapse_dots=True), '/b')
        encoded = b'0-1 r--p 0 00:00 0 /a\\040b (deleted)\n'
        self.assertEqual(list(helper.mapped_paths(encoded)), ['/a\\040b (deleted)'])
        self.assertEqual(list(helper.mapped_paths(encoded, decode_escapes=True)), ['/a b (deleted)'])

    def run_isolated_imports(self):
        self.process(cwd=self.watched)
        command = '''import importlib.machinery,importlib.util,os,sys
from pathlib import Path
from unittest.mock import patch
proc=Path(sys.argv[1])
watched=sys.argv[2]
original_scandir=os.scandir
def mapped_path(value):
 return proc if str(value)=='/proc' else Path(value)
def mapped_scandir(value):
 return original_scandir(proc if str(value)=='/proc' else value)
for index,path in enumerate(sys.argv[3:]):
 loader=importlib.machinery.SourceFileLoader('isolated'+str(index),path)
 spec=importlib.util.spec_from_loader(loader.name,loader)
 module=importlib.util.module_from_spec(spec)
 loader.exec_module(module)
 with patch.object(module,'Path',side_effect=mapped_path,create=True), patch.object(os,'scandir',side_effect=mapped_scandir), patch.object(os,'getpid',return_value=900), patch.object(sys,'argv',['-c']):
  if hasattr(module,'active_users'): assert module.active_users([watched])==['11 fixture']
  if hasattr(module,'inspect_processes'):
   result=module.inspect_processes([watched])
   assert watched in result['blocked'] and 'cwd' in result['blocked'][watched]
   assert result['uninspected_processes']==0
  if hasattr(module,'read_process_file'): assert module.read_process_file(proc/'11/comm',text=True).strip()=='fixture'
print('isolated imports passed')
'''
        return subprocess.run([sys.executable, '-I', '-B', '-c', command, str(self.proc), self.watched,
                                 str(ROOT / 'Tools/agency-storage'),
                                 str(ROOT / 'Tools/housekeeping_projects.py'), str(ROOT / 'Tools/agency_processes.py')],
                                cwd=self.root, text=True, capture_output=True)

    def test_imports_and_readers_work_from_isolated_cwd(self):
        result = self.run_isolated_imports()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('isolated imports passed', result.stdout)

    def test_isolated_import_check_never_reads_host_processes(self):
        original_run = subprocess.run

        def guarded_run(arguments, **options):
            arguments = list(arguments)
            source = arguments.index('-c') + 1
            guard = '''import os,pathlib
original_iterdir=pathlib.Path.iterdir
original_scandir=os.scandir
def guarded_iterdir(path, original_iterdir=original_iterdir):
 if str(path)=='/proc': raise PermissionError('host proc must not be inspected')
 return original_iterdir(path)
def guarded_scandir(path, original_scandir=original_scandir):
 if os.fspath(path)=='/proc': raise PermissionError('host proc must not be inspected')
 return original_scandir(path)
pathlib.Path.iterdir=guarded_iterdir
os.scandir=guarded_scandir
'''
            arguments[source] = guard + arguments[source]
            return original_run(arguments, **options)

        with patch.object(subprocess, 'run', side_effect=guarded_run):
            result = self.run_isolated_imports()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('isolated imports passed', result.stdout)
