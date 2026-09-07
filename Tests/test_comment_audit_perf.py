import contextlib
import io
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest import mock


AUDIT = runpy.run_path(str(Path(__file__).resolve().parents[1] / "Tools/comment-audit"))
PATHS = AUDIT["paths"]


class CommentAuditPathsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_unsupported_candidates_do_not_request_file_metadata(self):
        supported = self.root / "source.py"
        supported.touch()
        candidates = [self.root / f"document-{index}.md" for index in range(1000)]
        candidates.append(supported)
        for visible_only in (False, True):
            with self.subTest(visible_only=visible_only):
                with (
                    mock.patch.dict(PATHS.__globals__, {"git_visible": lambda root: candidates}),
                    mock.patch.object(Path, "rglob", return_value=iter(candidates)),
                    mock.patch.object(Path, "is_file", autospec=True, side_effect=Path.is_file) as is_file,
                ):
                    self.assertEqual(PATHS([self.root], visible_only), [supported])
                self.assertEqual(is_file.call_args_list, [mock.call(self.root), mock.call(supported)])

    def test_explicit_unsupported_file_is_retained(self):
        unsupported = self.root / "notes.md"
        unsupported.touch()
        for visible_only in (False, True):
            with self.subTest(visible_only=visible_only):
                self.assertEqual(PATHS([unsupported], visible_only), [unsupported])

    def test_directory_selection_preserves_sorting_deduplication_and_symlinks(self):
        source = self.root / "z-source.PY"
        source.touch()
        unsupported = self.root / "notes.md"
        unsupported.touch()
        directory = self.root / "directory.py"
        directory.mkdir()
        nested = directory / "a.py"
        nested.touch()
        alias = self.root / "alias.py"
        alias.symlink_to(source)
        unsupported_target_alias = self.root / "notes.py"
        unsupported_target_alias.symlink_to(unsupported)
        directory_alias = self.root / "directory-alias.py"
        directory_alias.symlink_to(directory, target_is_directory=True)
        missing = self.root / "missing.py"
        broken = self.root / "broken.py"
        broken.symlink_to(missing)
        candidates = [source, unsupported, directory, nested, alias, unsupported_target_alias,
                      directory_alias, missing, broken, source]
        expected = sorted([source, nested, unsupported])
        with mock.patch.dict(PATHS.__globals__, {"git_visible": lambda root: candidates}):
            self.assertEqual(PATHS([self.root], True), expected)
        self.assertEqual(PATHS([self.root], False), expected)
        with mock.patch.dict(PATHS.__globals__, {"git_visible": lambda root: None}):
            self.assertEqual(PATHS([self.root], True), expected)
        self.assertEqual(PATHS([alias, source, unsupported_target_alias], False), sorted([source, unsupported]))

    def test_missing_explicit_supported_path_fails(self):
        missing = self.root / "missing.py"
        for visible_only in (False, True):
            with self.subTest(visible_only=visible_only):
                error = io.StringIO()
                with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                    PATHS([missing], visible_only)
                self.assertEqual(raised.exception.code, 2)
                self.assertIn(f"target does not exist: {missing}", error.getvalue())


if __name__ == "__main__":
    unittest.main()
