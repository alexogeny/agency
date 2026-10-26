import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / "Tools/repo-map"))
BUILD_MAP = MODULE["build_map"]
GLOBALS = BUILD_MAP.__globals__


class MappingFollowupPerformanceTests(unittest.TestCase):
    def fixture(self, root):
        for name in ["picked/a.py", "picked/deep/b.ts", "picked-ish/other.py", "[literal]/a.py", ":magic/a.py", "space here/a.py", "café/a.py", "root.py"]:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# fixture\n")
        for index in range(200):
            path = root / f"outside/file{index:04}.py"
            path.parent.mkdir(exist_ok=True)
            path.write_text("# outside\n")
        (root / ".gitignore").write_text("ignored/\n")
        (root / "ignored").mkdir()
        (root / "ignored/secret.py").write_text("# ignored\n")
        (root / "link.py").symlink_to("picked/a.py")
        if (root / ".git").exists():
            subprocess.run(["git", "-C", root, "add", "--", ".gitignore", "picked/a.py"], check=True)
            subprocess.run(["git", "-C", root, "add", "--force", "--", "ignored/secret.py"], check=True)

    def test_scoped_maps_match_full_discovery_for_literal_names_and_overlaps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "--quiet", root], check=True)
            self.fixture(root)
            all_paths = GLOBALS["visible_files"](root)
            for scopes in [[], ["."], ["picked"], ["picked/"], ["picked", "picked/deep"],
                           ["[literal]"], [":magic"], ["space here"], ["café"], ["link.py"], ["ignored"], ["root.py"], ["missing"], ["picked-ish"]]:
                with self.subTest(scopes=scopes):
                    with patch.dict(GLOBALS, visible_files=lambda root, *args: all_paths):
                        expected = BUILD_MAP(root, scopes, 4096, False)
                    self.assertEqual(BUILD_MAP(root, scopes, 4096, False), expected)

    def test_narrow_scope_does_not_transfer_unrelated_git_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "--quiet", root], check=True)
            self.fixture(root)
            original = GLOBALS["run_git"]
            outputs = []

            def observe(*args, **kwargs):
                output = original(*args, **kwargs)
                if "ls-files" in args:
                    outputs.append(output)
                return output

            with patch.dict(GLOBALS, run_git=observe):
                result = BUILD_MAP(root, ["picked"], 4096, False)
            self.assertEqual([item["path"] for item in result["files"]], ["picked/a.py", "picked/deep/b.ts"])
            self.assertEqual(len(outputs), 1)
            self.assertEqual(sorted(outputs[0].split(b"\0")), [b"", b"picked/a.py", b"picked/deep/b.ts"])

    def test_non_git_fallback_keeps_scope_semantics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            result = BUILD_MAP(root, ["[literal]"], 4096, False)
            self.assertEqual([item["path"] for item in result["files"]], ["[literal]/a.py"])


if __name__ == "__main__":
    unittest.main()
