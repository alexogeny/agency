import hashlib
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


BUILD_MAP = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "Tools" / "repo-map")
)["build_map"]


class RepoMapTreeKindTests(unittest.TestCase):
    def test_kind_transition_changes_tree_digest_but_not_content_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            root = workspace / "repository"
            root.mkdir()
            item = root / "item"
            item.symlink_to("hello")
            with patch.dict(os.environ, REPO_MAP_CACHE_DIR=str(workspace / "cache")):
                symlink = BUILD_MAP(root, [], 8192, False)
                self.assertEqual(symlink, BUILD_MAP(root, [], 8192, True))
                self.assertEqual(symlink, BUILD_MAP(root, [], 8192, True))
                item.unlink()
                item.write_bytes(b"hello")
                regular = BUILD_MAP(root, [], 8192, False)
                self.assertEqual(regular, BUILD_MAP(root, [], 8192, True))
                self.assertEqual(regular, BUILD_MAP(root, [], 8192, True))
            self.assertEqual(symlink["files"][0]["kind"], "symlink")
            self.assertEqual(regular["files"][0]["kind"], "file")
            content_digest = hashlib.sha256(b"hello").hexdigest()
            self.assertEqual(symlink["files"][0]["sha256"], content_digest)
            self.assertEqual(regular["files"][0]["sha256"], content_digest)
            self.assertNotEqual(symlink["tree_sha256"], regular["tree_sha256"])

    def test_creation_order_is_stable_and_path_content_changes_are_distinguished(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            first = workspace / "first"
            second = workspace / "second"
            first.mkdir()
            second.mkdir()
            names = ("alpha.txt", "beta.txt")
            for root, order in ((first, names), (second, reversed(names))):
                for name in order:
                    (root / name).write_bytes(name.encode())
            original = BUILD_MAP(first, [], 8192, False)
            self.assertEqual(original, BUILD_MAP(second, [], 8192, False))
            self.assertEqual([item["path"] for item in original["files"]], list(names))
            (second / "alpha.txt").rename(second / "gamma.txt")
            renamed = BUILD_MAP(second, [], 8192, False)
            self.assertNotEqual(original["tree_sha256"], renamed["tree_sha256"])
            (second / "gamma.txt").write_bytes(b"changed")
            changed = BUILD_MAP(second, [], 8192, False)
            self.assertNotEqual(renamed["tree_sha256"], changed["tree_sha256"])


if __name__ == "__main__":
    unittest.main()
