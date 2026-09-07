from contextlib import closing
import hashlib
import os
from pathlib import Path
import runpy
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, call, patch


BUILD_MAP = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "Tools" / "repo-map")
)["build_map"]
GLOBALS = BUILD_MAP.__globals__


class RepoMapCacheLifecycleTests(unittest.TestCase):
    def test_success_commits_then_closes_once(self):
        for paths in ([], [Path("file.py")]):
            with self.subTest(paths=paths):
                connection = Mock()
                with patch.dict(
                    GLOBALS,
                    visible_files=lambda root: paths,
                    read_file=lambda root, path: (str(path), b"", "file", "digest"),
                    cached_facts=lambda *args: {"roles": []},
                    cache_database=lambda: connection,
                ):
                    result = BUILD_MAP(Path("unused"), [], 8192, True)
                self.assertEqual(result["summary"]["files"], len(paths))
                self.assertEqual(connection.method_calls, [call.commit(), call.close()])

    def test_read_parse_and_commit_errors_close_and_preserve_exception(self):
        for phase in ("read", "parse", "commit"):
            with self.subTest(phase=phase):
                connection = Mock()
                error = RuntimeError(f"{phase} failed")
                reader = Mock(return_value=("file.py", b"", "file", "digest"))
                parser = Mock(return_value={"roles": []})
                if phase == "read":
                    reader.side_effect = error
                elif phase == "parse":
                    parser.side_effect = error
                else:
                    connection.commit.side_effect = error
                with patch.dict(
                    GLOBALS,
                    visible_files=lambda root: [Path("file.py")],
                    read_file=reader,
                    cached_facts=parser,
                    cache_database=lambda: connection,
                ):
                    with self.assertRaises(RuntimeError) as caught:
                        BUILD_MAP(Path("unused"), [], 8192, True)
                self.assertIs(caught.exception, error)
                connection.close.assert_called_once_with()
                if phase != "commit":
                    connection.commit.assert_not_called()

    def test_uncached_map_does_not_open_a_connection(self):
        factory = Mock()
        with patch.dict(
            GLOBALS, visible_files=lambda root: [], cache_database=factory
        ):
            result = BUILD_MAP(Path("unused"), [], 8192, False)
        self.assertEqual(result["summary"]["files"], 0)
        factory.assert_not_called()

    def test_later_batch_failure_releases_sqlite_lock_without_partial_commit(self):
        original_cache = GLOBALS["cache_database"]
        connections = []
        statements = []

        def open_cache():
            connection = original_cache()
            connections.append(connection)
            self.addCleanup(connection.close)
            connection.set_trace_callback(statements.append)
            return connection

        def read_file(root, path):
            if path.name == "file006.py":
                raise FileNotFoundError(path)
            data = b"import os\n"
            return str(path), data, "file", hashlib.sha256(data).hexdigest()

        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            paths = [Path(f"file{index:03}.py") for index in range(8)]
            with patch.dict(os.environ, REPO_MAP_CACHE_DIR=str(cache)), patch.dict(
                GLOBALS,
                visible_files=lambda root: paths,
                read_file=read_file,
                cache_database=open_cache,
            ), patch.object(os, "cpu_count", return_value=1):
                with self.assertRaises(FileNotFoundError):
                    BUILD_MAP(Path("unused"), [], 8192, True)
            self.assertTrue(any(statement.startswith("INSERT") for statement in statements))
            with closing(sqlite3.connect(cache / "facts.sqlite3", timeout=0)) as second:
                self.assertEqual(second.execute("SELECT COUNT(*) FROM facts").fetchone(), (0,))
                second.execute(
                    "INSERT INTO facts (digest, parser_version, facts_json) VALUES (?, ?, ?)",
                    ("probe", 1, "{}"),
                )
                second.commit()
            with self.assertRaises(sqlite3.ProgrammingError):
                connections[0].execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
