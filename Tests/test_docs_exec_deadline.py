import ctypes
import os
import runpy
import signal
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(os.environ.get('AGENCY_TEST_SCRATCH', ROOT / '.cache/tests'))
execute_case = runpy.run_path(str(ROOT / 'Tools/docs-exec'))['execute_case']


class DocsExecDeadlineTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.root = Path(self.temporary.name)
        (self.root / 'case').mkdir()
        (self.root / 'guide.md').write_text('```text title="input.txt"\nfixture\n```\n')
        self.libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        self.assertEqual(self.libc.prctl(37, ctypes.byref(previous), 0, 0, 0), 0)
        self.previous_subreaper = previous.value
        self.assertEqual(self.libc.prctl(36, 1, 0, 0, 0), 0)
        self.threads = set(threading.enumerate())

    def tearDown(self):
        pid_file = self.root / 'case' / 'child.pid'
        if pid_file.exists():
            pid = int(pid_file.read_text())
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
        self.libc.prctl(36, self.previous_subreaper, 0, 0, 0)
        self.temporary.cleanup()

    def run_case(self, source, timeout=0.1, maximum=1024):
        start = time.monotonic()
        result = execute_case({'name': 'fixture', 'document': 'guide.md', 'files': {'input.txt': 'input.txt'}, 'command': [sys.executable, '-c', source], 'timeout_seconds': timeout, 'max_output_bytes': maximum}, self.root, self.root / 'case')
        elapsed = time.monotonic() - start
        self.assertEqual(set(threading.enumerate()), self.threads)
        return result, elapsed

    def child_source(self, duration, ignore_term=False, detached=False):
        child = ('import signal,time; from pathlib import Path; '
                 + ('signal.signal(signal.SIGTERM, signal.SIG_IGN); ' if ignore_term else '')
                 + f'print("child ready", flush=True); Path("ready").write_text("ready"); time.sleep({duration})')
        return ('import subprocess,sys,time; from pathlib import Path; '
                f'child=subprocess.Popen([sys.executable,"-c",{child!r}], start_new_session={detached}); '
                'Path("child.pid").write_text(str(child.pid)); '
                '\nwhile not Path("ready").exists(): time.sleep(0.001)\n')

    def assert_child_reaped(self):
        pid = int((self.root / 'case' / 'child.pid').read_text())
        waited, _ = os.waitpid(pid, os.WNOHANG)
        self.assertEqual(waited, pid, 'fixture child is still running')
        (self.root / 'case' / 'child.pid').unlink()

    def test_exited_parent_with_inherited_pipes_hits_global_deadline(self):
        result, elapsed = self.run_case(self.child_source(0.8))
        self.assertEqual(result['status'], 'timed-out')
        self.assertEqual(result['returncode'], 0)
        self.assertLess(elapsed, 0.7)
        self.assert_child_reaped()

    def test_sigterm_ignoring_descendant_is_killed_after_parent_exits(self):
        result, elapsed = self.run_case(self.child_source(2, ignore_term=True), timeout=0.15)
        self.assertEqual(result['status'], 'timed-out')
        self.assertEqual(result['returncode'], 0)
        self.assertLess(elapsed, 1.3)
        self.assert_child_reaped()

    def test_detached_descendant_cannot_extend_pipe_cleanup(self):
        result, elapsed = self.run_case(self.child_source(1.5, detached=True))
        self.assertEqual(result['status'], 'timed-out')
        self.assertEqual(result['returncode'], 0)
        self.assertLess(elapsed, 1.1)
        self.assertEqual(result['stdout'], 'child ready\n')
        self.assertTrue(result['stdout_truncated'])
        self.assertTrue(result['stderr_truncated'])
        pid = int((self.root / 'case' / 'child.pid').read_text())
        self.assertEqual(os.waitpid(pid, os.WNOHANG), (0, 0))

    def test_ordinary_timeout(self):
        result, elapsed = self.run_case('import time; time.sleep(2)')
        self.assertEqual(result['status'], 'timed-out')
        self.assertLess(result['returncode'], 0)
        self.assertLess(elapsed, 0.8)

    def test_large_output_remains_bounded_without_deadlock(self):
        result, elapsed = self.run_case('import sys; sys.stdout.write("x" * 200000); sys.stderr.write("y" * 200000)', timeout=2)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['returncode'], 0)
        self.assertEqual(result['stdout'], 'x' * 1024)
        self.assertEqual(result['stderr'], 'y' * 1024)
        self.assertTrue(result['stdout_truncated'])
        self.assertTrue(result['stderr_truncated'])
        self.assertLess(elapsed, 2)

    def test_nonzero_exit_preserves_output_and_status(self):
        result, _ = self.run_case('import sys; print("out"); print("err", file=sys.stderr); sys.exit(7)', timeout=2)
        self.assertEqual((result['status'], result['returncode']), ('failed', 7))
        self.assertEqual((result['stdout'], result['stderr']), ('out\n', 'err\n'))
        self.assertFalse(result['stdout_truncated'])
        self.assertFalse(result['stderr_truncated'])

    def test_process_group_disappearing_during_termination_is_safe(self):
        killpg = os.killpg
        def disappeared(pid, signum):
            killpg(pid, signum)
            raise ProcessLookupError('fixture group exited during signal')
        with mock.patch.object(os, 'killpg', side_effect=disappeared):
            result, _ = self.run_case('import time; time.sleep(2)')
        self.assertEqual(result['status'], 'timed-out')


if __name__ == '__main__':
    unittest.main()
