import hashlib
import json
from contextlib import closing
from pathlib import Path
import runpy
import sqlite3
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
MODULE = runpy.run_path(str(ROOT / 'Tools' / 'repo-map'))
LANGUAGE = MODULE['file_language']
PARSE = MODULE['parse_facts']
CACHED = MODULE['cached_facts']


class RepoMapRuntimeShebangTests(unittest.TestCase):
    def test_bun_and_uv_script_shebangs(self):
        cases = [
            (b'#!/usr/bin/env bun', 'typescript'),
            (b'#!/usr/bin/env -S bun run', 'typescript'),
            (b'#!/opt/bin/bun', 'typescript'),
            (b'#!/usr/bin/env -S uv run --quiet --script', 'python'),
            (b'#!/usr/bin/env -S uv run --script', 'python'),
            (b'#!/opt/bin/uv run -q --script', 'python'),
        ]
        for line, expected in cases:
            for ending in (b'', b'\n', b'\r', b'\r\n'):
                with self.subTest(line=line, ending=ending):
                    self.assertEqual(LANGUAGE('tool', line + ending), expected)

    def test_existing_precedence_and_non_script_counterexamples(self):
        cases = [
            ('tool.py', b'#!/usr/bin/env bun', 'python'),
            ('tool.ts', b'#!/usr/bin/env -S uv run --script', 'typescript'),
            ('tool', b'#!/usr/bin/env bun python', 'python'),
            ('tool', b'#!/usr/bin/env bun bash', 'shell'),
            ('tool', b'#!/usr/bin/env uv run --script fish', 'fish'),
            ('tool', b'#!/usr/bin/env bunx', None),
            ('tool', b'#!/opt/bin/bundle', None),
            ('tool', b'#!/usr/bin/env echo bun', None),
            ('tool', b'#!/usr/bin/env uv run program --script', None),
            ('tool', b'#!/usr/bin/env uv run -- --script', None),
            ('tool', b'#!/usr/bin/env uv run --quiet program', None),
            ('tool', b'#!/usr/bin/env uv tool run --script', None),
            ('tool', b'#!/usr/bin/env uv --script', None),
            ('tool', b'#!/usr/bin/env uv run --scripted', None),
            ('tool', b'#!/usr/bin/env echo\nbun', None),
            ('tool', b'bun\n', None),
            ('tool', b'#!', None),
        ]
        for path, data, expected in cases:
            with self.subTest(path=path, data=data):
                self.assertEqual(LANGUAGE(path, data), expected)

    def test_repository_scripts_produce_real_imports_and_symbols(self):
        for name, language in [('report-build', 'python'), ('web-research', 'typescript'), ('web-research-mcp', 'typescript')]:
            with self.subTest(name=name):
                path = f'Tools/{name}'
                facts = PARSE(path, (ROOT / path).read_bytes(), 'file', 10_000_000)
                self.assertEqual(facts['language'], language)
                self.assertTrue(facts['imports'])
                if language == 'python':
                    self.assertTrue(facts['public_symbols'])
                    self.assertNotIn('parse_error', facts)

    def test_version_three_unclassified_cache_is_reparsed_then_reused(self):
        path = 'Tools/tool'
        data = b'#!/usr/bin/env bun\nimport { readFile } from "node:fs";\n'
        digest = hashlib.sha256(data).hexdigest()
        maximum = 8192
        cache_key = hashlib.sha256(f'{path}\0file\0{digest}\0{maximum}'.encode()).hexdigest()
        with closing(sqlite3.connect(':memory:')) as connection:
            connection.execute('CREATE TABLE facts (digest TEXT, parser_version INTEGER, facts_json TEXT, PRIMARY KEY (digest, parser_version))')
            connection.execute('INSERT INTO facts VALUES (?, ?, ?)', (cache_key, 3, json.dumps({'language': None, 'roles': []})))
            parser = Mock(wraps=PARSE)
            with patch.dict(CACHED.__globals__, parse_facts=parser):
                actual = CACHED(connection, path, data, 'file', digest, maximum, True)
                self.assertEqual(actual, PARSE(path, data, 'file', maximum))
                self.assertEqual(actual['language'], 'typescript')
                parser.assert_called_once()
                parser.reset_mock()
                self.assertEqual(CACHED(connection, path, data, 'file', digest, maximum, True), actual)
                parser.assert_not_called()
