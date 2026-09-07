import os
import queue
import runpy
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(os.environ.get('AGENCY_TEST_SCRATCH', ROOT / '.cache/tests'))
BENCH = runpy.run_path(str(ROOT / 'Tools/resource-bench'))
process_tree = BENCH['process_tree']
process_tree_memory = BENCH['process_tree_memory']


class ResourceBenchThreadChildrenTests(unittest.TestCase):
    def test_child_spawned_by_live_background_thread_is_included(self):
        children = queue.Queue()
        release = threading.Event()
        errors = []

        def spawn():
            try:
                with subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']) as child:
                    try:
                        children.put(child)
                        release.wait(10)
                    finally:
                        child.terminate()
                        child.wait(timeout=5)
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=spawn)
        thread.start()
        try:
            child = children.get(timeout=5)
            self.assertIsNone(child.poll())
            pids = process_tree(os.getpid())
            self.assertIn(os.getpid(), pids)
            self.assertIn(child.pid, pids)
            self.assertEqual(len(pids), len(set(pids)))
        finally:
            release.set()
            thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def fixture(self, children, memory=None):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for (pid, tid), values in children.items():
            task = root / str(pid) / 'task' / str(tid)
            task.mkdir(parents=True, exist_ok=True)
            if values is not None:
                (task / 'children').write_text(' '.join(map(str, values)))
        for pid, (rss, pss) in (memory or {}).items():
            process = root / str(pid)
            process.mkdir(exist_ok=True)
            (process / 'smaps_rollup').write_text(f'Rss: {rss} kB\nPss: {pss} kB\n')

        def mapped_path(value):
            return root / Path(value).relative_to('/proc')

        return mock.patch.dict(process_tree.__globals__, {'Path': mapped_path})

    def test_threads_duplicate_children_and_nested_processes(self):
        with self.fixture({(1, 1): [2], (1, 11): [2, 3], (2, 2): [], (2, 22): [3], (3, 3): [1]}):
            pids = process_tree(1)
        self.assertEqual(set(pids), {1, 2, 3})
        self.assertEqual(len(pids), 3)
        self.assertEqual(pids[0], 1)

    def test_missing_thread_children_and_exited_process_are_tolerated(self):
        with self.fixture({(1, 1): [], (1, 11): None, (1, 12): [2]}):
            self.assertEqual(set(process_tree(1)), {1, 2})
            self.assertEqual(process_tree(999), [999])

    def test_single_threaded_processes(self):
        with self.fixture({(1, 1): [2], (2, 2): []}):
            self.assertEqual(process_tree(1), [1, 2])

    def test_memory_totals_include_worker_thread_child_once(self):
        with self.fixture({(1, 1): [], (1, 11): [2, 2], (2, 2): []}, {1: (10, 5), 2: (120, 80)}):
            totals = process_tree_memory(1)
        self.assertEqual(totals, {'rss': 130 * 1024, 'pss': 85 * 1024, 'processes': 2})


if __name__ == '__main__':
    unittest.main()
