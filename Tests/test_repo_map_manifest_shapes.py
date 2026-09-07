import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import Mock, patch


MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "Tools" / "repo-map"))
BUILD_MAP = MODULE["build_map"]
GLOBALS = BUILD_MAP.__globals__


class RepoMapManifestShapesTests(unittest.TestCase):
    def test_malformed_shapes_report_errors_without_aborting_map(self):
        cases = [
            (value, "package.json must contain a JSON object")
            for value in ([], None, "package", 42, True)
        ]
        cases.extend(
            ({field: value}, f"package.json field '{field}' must be an object")
            for field in ("dependencies", "devDependencies", "scripts")
            for value in ([], None, "wrong", 42, True)
        )
        cases.extend(
            ({"bin": value}, "package.json field 'bin' must be an object or string")
            for value in ([], None, 42, True)
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app.py").write_text("import json\n\ndef hello():\n    return 1\n")
            for document, message in cases:
                with self.subTest(document=document):
                    (root / "package.json").write_text(json.dumps(document))
                    result = BUILD_MAP(root, [], 10000, False)
                    self.assertEqual(result["summary"]["files"], 2)
                    self.assertEqual(result["manifests"], [{
                        "path": "package.json", "kind": "node", "commands": [],
                        "dependencies": [], "parse_error": message,
                    }])
                    source = next(item for item in result["files"] if item["path"] == "app.py")
                    self.assertEqual(source["imports"], [{"module": "json", "line": 1}])
                    self.assertEqual(source["public_symbols"], [{"name": "hello", "kind": "function", "line": 3}])

    def test_valid_manifest_shapes_preserve_facts(self):
        cases = [
            ({}, {"kind": "node", "commands": [], "dependencies": [], "entrypoints": []}),
            ({"name": "demo", "bin": "cli.js"}, {
                "kind": "node", "commands": [], "dependencies": [],
                "entrypoints": [{"name": "demo", "target": "cli.js"}],
            }),
            ({"bin": ""}, {
                "kind": "node", "commands": [], "dependencies": [],
                "entrypoints": [{"name": "package", "target": ""}],
            }),
            ({"dependencies": {"z": "1", "a": None}, "devDependencies": {"z": "2", "b": []},
              "scripts": {"z": "run z", "a": None}, "bin": {"z": "z.js", "a": "a.js"}}, {
                "kind": "node", "dependencies": ["a", "b", "z"],
                "commands": [{"name": "a", "command": None}, {"name": "z", "command": "run z"}],
                "entrypoints": [{"name": "a", "target": "a.js"}, {"name": "z", "target": "z.js"}],
            }),
        ]
        for document, expected in cases:
            with self.subTest(document=document):
                self.assertEqual(MODULE["manifest_facts"]("package.json", json.dumps(document)), expected)

    def test_shape_errors_and_valid_facts_cache_and_invalidate_normally(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            root = workspace / "repository"
            root.mkdir()
            manifest = root / "package.json"
            (root / "app.py").write_text("VALUE = 1\n")
            parser = Mock(wraps=GLOBALS["parse_facts"])
            with patch.dict(os.environ, REPO_MAP_CACHE_DIR=str(workspace / "cache")), patch.dict(GLOBALS, parse_facts=parser):
                for document in ({"scripts": []}, {"scripts": {"test": "run tests"}}):
                    manifest.write_text(json.dumps(document))
                    expected = BUILD_MAP(root, [], 10000, False)
                    parser.reset_mock()
                    cached = BUILD_MAP(root, [], 10000, True)
                    self.assertEqual(cached, expected)
                    self.assertGreater(parser.call_count, 0)
                    parser.reset_mock()
                    self.assertEqual(BUILD_MAP(root, [], 10000, True), expected)
                    parser.assert_not_called()

    def test_syntax_errors_keep_existing_parse_error_shape(self):
        result = MODULE["manifest_facts"]("package.json", "{")
        self.assertEqual(result["kind"], "node")
        self.assertEqual(result["commands"], [])
        self.assertEqual(result["dependencies"], [])
        self.assertIsInstance(result["parse_error"], str)


if __name__ == "__main__":
    unittest.main()
