import hashlib
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "Tools" / "repo-map"))


class RepoMapFishTests(unittest.TestCase):
    def test_fish_shebang_is_reachable(self):
        for shebang in (b"#!/usr/bin/env fish", b"#!/usr/bin/fish"):
            with self.subTest(shebang=shebang):
                self.assertEqual(MODULE["file_language"]("script", shebang), "fish")

    def test_precedence_of_other_interpreters_is_preserved(self):
        for shebang, expected in (
            (b"#!python fish", "python"),
            (b"#!bash fish", "shell"),
            (b"#!/bin/bash", "shell"),
            (b"#!/bin/sh", "shell"),
            (b"#!/usr/bin/ruby", "ruby"),
        ):
            with self.subTest(shebang=shebang):
                self.assertEqual(MODULE["file_language"]("script", shebang), expected)
        self.assertEqual(MODULE["file_language"]("script.py", b"#!fish"), "python")

    def test_cached_shell_classification_is_invalidated(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            root = workspace / "repository"
            root.mkdir()
            data = b"#!/usr/bin/env fish\necho hello\n"
            (root / "script").write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            cache_digest = hashlib.sha256(f"script\0{digest}\0{8192}".encode()).hexdigest()
            with patch.dict(os.environ, REPO_MAP_CACHE_DIR=str(workspace / "cache")):
                connection = MODULE["cache_database"]()
                try:
                    connection.execute(
                        "INSERT INTO facts (digest, parser_version, facts_json) VALUES (?, ?, ?)",
                        (cache_digest, 1, json.dumps({"language": "shell", "roles": ["source"]})),
                    )
                    connection.commit()
                finally:
                    connection.close()
                cached = MODULE["build_map"](root, [], 8192, True)
                self.assertEqual(cached["files"][0]["language"], "fish")
                self.assertEqual(cached, MODULE["build_map"](root, [], 8192, False))
                self.assertEqual(cached, MODULE["build_map"](root, [], 8192, True))


if __name__ == "__main__":
    unittest.main()
