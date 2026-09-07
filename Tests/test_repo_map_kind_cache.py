import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import Mock, patch


BUILD_MAP = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "Tools" / "repo-map")
)["build_map"]
GLOBALS = BUILD_MAP.__globals__


class RepoMapKindCacheTests(unittest.TestCase):
    def test_same_bytes_kind_transitions_invalidate_cached_facts(self):
        for initial_kind in ("symlink", "file"):
            with self.subTest(initial_kind=initial_kind), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                root = workspace / "repository"
                root.mkdir()
                item = root / "item"

                def create(kind):
                    if kind == "symlink":
                        item.symlink_to("hello")
                    else:
                        item.write_bytes(b"hello")

                create(initial_kind)
                parser = Mock(wraps=GLOBALS["parse_facts"])
                with patch.dict(os.environ, REPO_MAP_CACHE_DIR=str(workspace / "cache")), patch.dict(
                    GLOBALS, parse_facts=parser
                ):
                    initial = BUILD_MAP(root, [], 8192, True)
                    self.assertEqual(parser.call_count, 1)
                    parser.reset_mock()
                    self.assertEqual(initial, BUILD_MAP(root, [], 8192, True))
                    parser.assert_not_called()
                    item.unlink()
                    final_kind = "file" if initial_kind == "symlink" else "symlink"
                    create(final_kind)
                    expected = BUILD_MAP(root, [], 8192, False)
                    parser.reset_mock()
                    changed = BUILD_MAP(root, [], 8192, True)
                    self.assertEqual(changed, expected)
                    self.assertEqual(parser.call_count, 1)
                    self.assertEqual(len(changed["files"]), 1)
                    self.assertEqual(changed["files"][0]["kind"], final_kind)
                    self.assertEqual("symlink_target" in changed["files"][0], final_kind == "symlink")
                    parser.reset_mock()
                    self.assertEqual(changed, BUILD_MAP(root, [], 8192, True))
                    parser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
