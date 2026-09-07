import contextlib
import io
import re
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest import mock


FENCES = runpy.run_path(str(Path(__file__).resolve().parents[1] / "Tools/docs-exec"))["fences"]


class DocsFenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.document = Path(self.temporary.name) / "examples.md"

    def test_closing_pattern_preparation_is_once_per_block(self):
        body = "print('example')\n" * 10000
        self.document.write_text(f"```python title=example\n{body}```\n")
        with mock.patch.object(re, "escape", wraps=re.escape) as escape:
            self.assertEqual(FENCES(self.document), {"example": body.encode()})
        self.assertEqual(escape.call_count, 1)

    def test_fence_markers_and_body_bytes(self):
        cases = [
            ("```py title=example\nbody\n```\n", b"body\n"),
            ("````py title='example'\n```\n~~~~\n`````\n", b"```\n~~~~\n"),
            (' \t~~~sh title="example"\nbody\n  ~~~~~\t \n', b"body\n"),
            ("~~~sh title=example\n```\n~~\n~~~~ trailing\n~~~\n", b"```\n~~\n~~~~ trailing\n"),
            ("```py title=example\r\nbody\r\n```\r\n", b"body\n"),
            ("```py title=example\n```", b""),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.document.write_bytes(source.encode())
                self.assertEqual(FENCES(self.document), {"example": expected})

    def test_multiple_named_blocks_and_unnamed_block(self):
        self.document.write_text(
            "prose\n```python\nignored\n```\n"
            "~~~sh title=first\none\n~~~\n"
            "````py title=second\ntwo\n````\n"
        )
        self.assertEqual(FENCES(self.document), {"first": b"one\n", "second": b"two\n"})

    def test_no_fences(self):
        self.document.write_text("plain prose\n")
        self.assertEqual(FENCES(self.document), {})

    def test_unclosed_and_duplicate_fences_fail(self):
        cases = [
            ("```py title=example\nbody\n", "unclosed code fence"),
            ("```py\nbody\n", "unclosed code fence"),
            ("```py title=example", "unclosed code fence"),
            ("```py title=example\n```\n~~~sh title=example\n~~~\n", "duplicate fenced block title 'example'"),
        ]
        for source, message in cases:
            with self.subTest(source=source):
                self.document.write_text(source)
                error = io.StringIO()
                with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                    FENCES(self.document)
                self.assertEqual(raised.exception.code, 1)
                self.assertIn(message, error.getvalue())
                self.assertIn(str(self.document), error.getvalue())


if __name__ == "__main__":
    unittest.main()
