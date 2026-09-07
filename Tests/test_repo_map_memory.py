import concurrent.futures
import gc
import hashlib
import os
from pathlib import Path
import runpy
import tempfile
import threading
import unittest
import weakref
from unittest.mock import patch


BUILD_MAP = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "Tools" / "repo-map")
)["build_map"]
GLOBALS = BUILD_MAP.__globals__


class RawPayload(bytearray):
    pass


class RepoMapMemoryTests(unittest.TestCase):
    def retained_payload_peak(self, hold_completed_workers=False):
        paths = [Path(f"file{index:03}.py") for index in range(64)]
        references = []
        lock = threading.Lock()
        peak = 0
        release_workers = threading.Event()
        second_batch_ready = threading.Event()
        callback_timeouts = []
        held_paths = set(map(str, paths[:4]))
        cached_facts = GLOBALS["cached_facts"]
        invoke_callbacks = concurrent.futures.Future._invoke_callbacks

        def read_file(root, path):
            data = RawPayload(b"x" * (1024 * 1024))
            with lock:
                references.append(weakref.ref(data))
            if path == paths[9]:
                second_batch_ready.set()
            return str(path), data, "file", hashlib.sha256(data).hexdigest()

        def observe_facts(*args):
            nonlocal peak
            second_batch = hold_completed_workers and args[1] == str(paths[5])
            if second_batch:
                self.assertTrue(second_batch_ready.wait(5))
            # Collection excludes deferred reclamation from this retained-payload check.
            gc.collect()
            with lock:
                peak = max(peak, sum(reference() is not None for reference in references))
            if second_batch:
                release_workers.set()
            return cached_facts(*args)

        def hold_callback(future):
            # FINISHED futures can be consumed while workers still own their results.
            if hold_completed_workers and future._result[0] in held_paths:
                if not release_workers.wait(5):
                    with lock:
                        callback_timeouts.append(future._result[0])
            return invoke_callbacks(future)

        with (
            patch.dict(GLOBALS, visible_files=lambda root: paths, read_file=read_file,
                       cached_facts=observe_facts),
            patch.object(os, "cpu_count", return_value=1),
            patch.object(concurrent.futures.Future, "_invoke_callbacks", hold_callback),
        ):
            try:
                result = BUILD_MAP(Path("unused"), [], 8192, False)
            finally:
                release_workers.set()
        self.assertEqual(callback_timeouts, [])
        self.assertEqual([item["path"] for item in result["files"]], list(map(str, paths)))
        self.assertTrue(all(item["parse_skipped"] == "size" for item in result["files"]))
        self.assertEqual(len(references), len(paths))
        gc.collect()
        self.assertFalse(any(reference() is not None for reference in references))
        self.assertGreater(peak, 0)
        return peak

    def test_gc_settled_raw_payloads_are_bounded_by_worker_count(self):
        # One batch plus at most one completed result still held by each worker.
        self.assertLessEqual(self.retained_payload_peak(), 2 * 5)

    def test_gc_settled_payloads_include_completed_worker_results(self):
        self.assertEqual(self.retained_payload_peak(hold_completed_workers=True), 4 + 5)

    def test_map_contents_cache_and_symlinks_remain_equivalent(self):
        cache_database = GLOBALS["cache_database"]

        def open_cache():
            connection = cache_database()
            self.addCleanup(connection.close)
            return connection

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            root = workspace / "repository"
            root.mkdir()
            sources = {
                "main.py": b"import os\ndef run():\n    pass\n",
                "lib.ts": b"import thing from './thing';\n",
                "binary.dat": b"\x00binary",
                "large.txt": b"x" * 1024,
                "broken.py": b"def invalid(\n",
                "package.json": b'{"scripts":{"test":"check"}}',
                "AGENTS.md": b"Local instructions\n",
            }
            for name, data in sources.items():
                (root / name).write_bytes(data)
            (root / "link.py").symlink_to("main.py")
            with patch.dict(os.environ, REPO_MAP_CACHE_DIR=str(workspace / "cache")), patch.dict(
                GLOBALS, cache_database=open_cache
            ):
                uncached = BUILD_MAP(root, [], 512, False)
                with patch.dict(GLOBALS, parse_facts=unittest.mock.Mock(wraps=GLOBALS["parse_facts"])):
                    parser = GLOBALS["parse_facts"]
                    cold = BUILD_MAP(root, [], 512, True)
                    self.assertEqual(parser.call_count, 8)
                    parser.reset_mock()
                    warm = BUILD_MAP(root, [], 512, True)
                    parser.assert_not_called()
                self.assertEqual(cold, uncached)
                self.assertEqual(warm, uncached)
                self.assertEqual([item["path"] for item in warm["files"]], sorted([*sources, "link.py"]))
                by_path = {item["path"]: item for item in warm["files"]}
                self.assertEqual(by_path["link.py"]["symlink_target"], "main.py")
                self.assertEqual(by_path["binary.dat"]["parse_skipped"], "binary")
                self.assertEqual(by_path["large.txt"]["parse_skipped"], "size")
                self.assertIn("parse_error", by_path["broken.py"])
                self.assertEqual(by_path["lib.ts"]["imports"], [{"module": "./thing", "line": 1}])
                self.assertEqual(BUILD_MAP(root, ["main.py"], 512, True)["summary"]["files"], 1)
                (root / "main.py").write_bytes(b"import sys\n")
                changed = BUILD_MAP(root, [], 512, True)
                self.assertNotEqual(changed["tree_sha256"], warm["tree_sha256"])
                self.assertEqual(changed, BUILD_MAP(root, [], 512, False))

    def test_read_error_propagates_without_committing_cache(self):
        paths = [Path(f"file{index:03}.py") for index in range(12)]
        connection = unittest.mock.Mock()
        connection.execute.return_value.fetchone.return_value = None

        def read_file(root, path):
            if path == paths[7]:
                raise FileNotFoundError("disappeared file007.py")
            data = b"import os\n"
            return str(path), data, "file", hashlib.sha256(data).hexdigest()

        with patch.dict(GLOBALS, visible_files=lambda root: paths, read_file=read_file,
                        cache_database=lambda: connection):
            with patch.object(os, "cpu_count", return_value=1):
                with self.assertRaisesRegex(FileNotFoundError, "disappeared file007.py"):
                    BUILD_MAP(Path("unused"), [], 8192, True)
        connection.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
