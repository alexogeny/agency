import runpy
import unittest
from pathlib import Path


FILE_LANGUAGE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "Tools" / "repo-map")
)["file_language"]


class CountedBytes(bytes):
    def __new__(cls, value):
        instance = super().__new__(cls, value)
        instance.copied_bytes = 0
        return instance

    def splitlines(self, keepends=False):
        lines = super().splitlines(keepends)
        self.copied_bytes += sum(map(len, lines))
        return lines

    def __getitem__(self, index):
        result = super().__getitem__(index)
        if isinstance(index, slice):
            self.copied_bytes += len(result)
        return result


class RepoMapShebangTests(unittest.TestCase):
    def test_shebang_language_semantics(self):
        cases = [
            ("script", b"", None),
            ("script", b"#!", None),
            ("script", b"python\n", None),
            ("script", b"#!/usr/bin/python", "python"),
            ("script", b"#!/usr/bin/\xffpython\xfe", "python"),
            ("script", b"#!/bin/bash", "shell"),
            ("script", b"#!/bin/sh", "shell"),
            ("script", b"#!/usr/bin/fish", "fish"),
            ("script", b"#!/usr/bin/ruby", "ruby"),
            ("script", b"#!ruby bash python", "python"),
            ("script", b"#!ruby bash", "shell"),
            ("script.RS", b"#!/usr/bin/python", "rust"),
            ("script.py", b"", "python"),
        ]
        for separator in (b"\r", b"\n", b"\r\n"):
            cases.extend([
                ("script", b"#!ruby" + separator + b"python", "ruby"),
                ("script", b"#!" + separator + b"python", None),
            ])
        for separator in (b"\v", b"\f", b"\x1c", b"\x85"):
            cases.append(("script", b"#!ruby" + separator + b"python", "python"))
        for path, data, expected in cases:
            with self.subTest(path=path, data=data):
                self.assertEqual(FILE_LANGUAGE(path, data), expected)

    def test_shebang_extraction_copies_only_first_line(self):
        first_line = b"#!/usr/bin/env python3"
        for separator in (b"\r", b"\n", b"\r\n"):
            with self.subTest(separator=separator):
                data = CountedBytes(first_line + separator + b"x=1\n" * 10000)
                self.assertEqual(FILE_LANGUAGE("script", data), "python")
                self.assertLessEqual(data.copied_bytes, len(first_line))


if __name__ == "__main__":
    unittest.main()
