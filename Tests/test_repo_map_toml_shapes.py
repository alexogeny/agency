import hashlib
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import Mock, patch


MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "Tools" / "repo-map"))
BUILD_MAP = MODULE["build_map"]


class RepoMapTomlShapesTests(unittest.TestCase):
    def test_malformed_tables_and_dependencies_do_not_abort_map(self):
        cases = [
            ("pyproject.toml", "project = []", "project", "a table"),
            ("pyproject.toml", "project = 4", "project", "a table"),
            ("pyproject.toml", '[project]\nscripts = []', "project.scripts", "a table"),
            ("pyproject.toml", '[project]\nscripts = "x"', "project.scripts", "a table"),
            ("Cargo.toml", "package = []", "package", "a table"),
            ("Cargo.toml", "package = 4", "package", "a table"),
        ]
        cases.extend(
            ("pyproject.toml", f"[project]\ndependencies = {value}", "project.dependencies", "an array of strings")
            for value in ('4', '"abc"', '["a", 1]', '[1]', '{}', '[{}]')
        )
        cases.extend(
            ("Cargo.toml", f"dependencies = {value}", "dependencies", "a table")
            for value in ('4', '[]', '"abc"')
        )
        for name, text, field, shape in cases:
            with self.subTest(name=name, text=text), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / name).write_text(text)
                (root / "app.py").write_text("import os\n")
                result = BUILD_MAP(root, [], 10000, False)
                self.assertEqual(result["summary"]["files"], 2)
                manifest = result["manifests"][0]
                self.assertEqual(manifest["parse_error"], f"{name} field '{field}' must be {shape}")
                self.assertEqual(manifest["commands"], [])
                self.assertEqual(manifest["dependencies"], [])
                source = next(item for item in result["files"] if item["path"] == "app.py")
                self.assertEqual(source["imports"], [{"module": "os", "line": 1}])

    def test_valid_facts_keep_existing_values_and_sorting(self):
        cases = [
            ("pyproject.toml", "", {"kind": "python", "commands": [], "dependencies": [], "requires_python": None}),
            ("pyproject.toml", '[project]\nrequires-python = ">=3.11"\ndependencies = ["z", "a", "a"]\n[project.scripts]\nz = "z:main"\na = 4', {
                "kind": "python", "requires_python": ">=3.11", "dependencies": ["a", "a", "z"],
                "commands": [{"name": "a", "command": 4}, {"name": "z", "command": "z:main"}],
            }),
            ("Cargo.toml", "", {"kind": "cargo", "commands": [], "dependencies": [], "package": None}),
            ("Cargo.toml", '[package]\nname = "demo"\n[dependencies]\nz = "1"\na = { version = "2" }', {
                "kind": "cargo", "commands": [], "dependencies": ["a", "z"], "package": "demo",
            }),
        ]
        for name, text, expected in cases:
            with self.subTest(name=name, text=text):
                self.assertEqual(MODULE["manifest_facts"](name, text), expected)

    def test_old_cached_malformed_facts_are_reparsed_and_then_hit_cache(self):
        cases = [
            ("pyproject.toml", '[project]\ndependencies = "ab"', {
                "kind": "python", "commands": [], "dependencies": ["a", "b"], "requires_python": None,
            }),
            ("Cargo.toml", 'dependencies = ["old"]', {
                "kind": "cargo", "commands": [], "dependencies": ["old"], "package": None,
            }),
        ]
        for name, text, stale_manifest in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary)
                root = workspace / "repository"
                root.mkdir()
                data = text.encode()
                (root / name).write_bytes(data)
                digest = hashlib.sha256(data).hexdigest()
                cache_key = hashlib.sha256(f"{name}\0file\0{digest}\0{10000}".encode()).hexdigest()
                stale = MODULE["parse_facts"](name, data, "file", 10000)
                stale["manifest"] = stale_manifest
                with patch.dict(os.environ, REPO_MAP_CACHE_DIR=str(workspace / "cache")):
                    connection = MODULE["cache_database"]()
                    try:
                        connection.execute(
                            "INSERT INTO facts (digest, parser_version, facts_json) VALUES (?, ?, ?)",
                            (cache_key, 2, json.dumps(stale)),
                        )
                        connection.commit()
                    finally:
                        connection.close()
                    result = BUILD_MAP(root, [], 10000, True)
                    self.assertIn("parse_error", result["manifests"][0])
                    self.assertEqual(result, BUILD_MAP(root, [], 10000, False))
                    parser = Mock(wraps=MODULE["parse_facts"])
                    with patch.dict(BUILD_MAP.__globals__, parse_facts=parser):
                        self.assertEqual(result, BUILD_MAP(root, [], 10000, True))
                    parser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
