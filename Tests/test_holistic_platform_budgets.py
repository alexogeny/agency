"""Deferred platform/coordination resource contracts with deterministic counters.

No cleanup, storage migration, real process inspection, subprocess probe or sudo
operation runs. Resource assertions follow correctness checks on synthetic state.
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'Tools'
sys.path.insert(0, str(TOOLS))
import agent_work_messages as messages
import housekeeping_projects as projects
import housekeeping_picker as picker


def load_tool(name):
    loader = importlib.machinery.SourceFileLoader('platform_budget_' + name.replace('-', '_'), str(TOOLS / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


storage = load_tool('agency-storage')
system = load_tool('system-context')


class PlatformBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def test_deep_scope_index_does_not_copy_all_ancestor_prefixes(self):
        def workload(depth):
            copied = 0

            class Claim(str):
                def __getitem__(self, key):
                    nonlocal copied
                    result = super().__getitem__(key)
                    if isinstance(key, slice):
                        copied += len(result)
                    return result

            claim = Claim('/'.join(['src'] + ['child'] * depth))
            index = messages.ScopeIndex(['src', str(claim) + '/file', 'unrelated'])
            self.assertEqual(index.overlapping(claim), [0, 1])
            self.assertEqual(index.overlapping('elsewhere'), [])
            return copied

        small, large = workload(64), workload(128)
        self.assertLessEqual(large, small * 2.6,
                             f'Doubled scope depth copied {large}/{small} ancestor characters')

    def test_independent_owned_paths_do_not_scan_all_claims(self):
        def workload(count):
            connection = sqlite3.connect(':memory:')
            self.addCleanup(connection.close)
            connection.execute('CREATE TABLE claims(task_id TEXT, path TEXT)')
            paths = [f'area-{i:04d}' for i in range(count)]
            connection.executemany('INSERT INTO claims VALUES (?,?)', [('owner', path) for path in paths])
            h = types.SimpleNamespace(ACTIVE_STATES={'active'}, claims_overlap=lambda a, b: messages.contains(a, b) or messages.contains(b, a))
            task = {'id': 'owner', 'status': 'active'}
            with patch.object(messages, 'exclusions', return_value=[]), patch.object(messages, 'paused', return_value=[]), \
                    patch.object(messages, 'contains', wraps=messages.contains) as contains:
                self.assertTrue(messages.can_write(h, connection, task, [path + '/file' for path in paths]))
                calls = contains.call_count
                self.assertFalse(messages.can_write(h, connection, task, ['outside/file']))
            return calls

        small, large = workload(64), workload(128)
        self.assertLessEqual(large, small * 2.6,
                             f'Doubled independent paths/claims required {large}/{small} containment checks')

    def test_paused_scope_checks_index_disjoint_requested_paths(self):
        count = 64
        paths = [f'owned/{i:04d}' for i in range(count)]
        pauses = [{'request_id': f'request-{i}', 'paths': [f'paused/{i:04d}']} for i in range(count)]
        overlap = lambda a, b: messages.contains(a, b) or messages.contains(b, a)
        h = types.SimpleNamespace(claims_overlap=overlap, fail=lambda message, code: (_ for _ in ()).throw(ValueError(message)))
        with patch.object(messages, 'paused', return_value=pauses), \
                patch.object(h, 'claims_overlap', wraps=overlap) as compared:
            messages.assert_not_paused(h, None, 'owner', paths)
            calls = compared.call_count
            with self.assertRaisesRegex(ValueError, 'paused'):
                messages.assert_not_paused(h, None, 'owner', ['paused/0000/file'])
        self.assertLessEqual(calls, 8 * (count + count),
                             f'Disjoint paused/requested scopes required {calls} pair checks')

    def test_finishing_unrelated_tasks_does_not_reparse_every_request_snapshot(self):
        count = 32
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        connection.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY, repo_id TEXT, status TEXT)')
        messages.schema(connection)
        connection.executemany('INSERT INTO claim_requests(id,repo_id,status,snapshot_json,requester,revision,paths_json,note,created_at) VALUES (?,?,?,?,?,1,?,?,?)',
                               [(f'req-{i}', 'repo', 'pending', json.dumps([{'task_id': f'other-owner-{i}'}]), f'other-requester-{i}', '[]', '', '2026-11-02T00:00:00Z') for i in range(count)])
        connection.execute('INSERT INTO claim_requests(id,repo_id,status,snapshot_json,requester,revision,paths_json,note,created_at) VALUES (?,?,?,?,?,1,?,?,?)',
                           ('relevant', 'repo', 'pending', '[]', 'task-0', '[]', '', '2026-11-02T00:00:00Z'))
        connection.executemany('INSERT INTO work_sessions(task_id,client,session_id,capability,heartbeat_at) VALUES (?,?,?,?,?)',
                               [(f'task-{i}', 'codex', f'session-{i}', 'boundary', '2026-11-02T00:00:00Z') for i in range(count)])
        with patch.object(messages.json, 'loads', wraps=json.loads) as decode, \
                patch.object(messages, 'request_notice') as notice, \
                patch.object(messages, 'request_record', return_value={'id': 'relevant'}):
            for i in range(count):
                messages.finish_requests(types.SimpleNamespace(), connection, {'id': f'task-{i}', 'repo_id': 'repo'})
            calls = decode.call_count
        notice.assert_called_once()
        self.assertEqual(connection.execute("SELECT status FROM claim_requests WHERE id='relevant'").fetchone()[0], 'cancelled')
        self.assertEqual(connection.execute("SELECT count(*) FROM claim_requests WHERE status='pending'").fetchone()[0], count)
        self.assertEqual(connection.execute('SELECT count(*) FROM work_sessions').fetchone()[0], 0)
        self.assertLessEqual(calls, count * 4,
                             f'Finishing unrelated tasks decoded {calls} foreign request snapshots')

    def test_housekeeping_root_match_does_not_copy_each_ancestor_string(self):
        def workload(depth):
            processed = 0

            class Value(str):
                def rpartition(self, separator):
                    nonlocal processed
                    processed += len(self)
                    head, sep, tail = super().rpartition(separator)
                    return Value(head), sep, tail

            value = '/root/' + '/'.join(['child'] * depth)
            with patch.dict(projects.process_helpers, normalize_path=lambda value, **kwargs: Value(os.path.normpath(value))):
                self.assertEqual(list(projects._matching_roots(value, {'/root', '/unrelated'})), ['/root'])
                self.assertEqual(list(projects._matching_roots('relative/path', {'/root'})), [])
            return processed

        small, large = workload(64), workload(128)
        self.assertLessEqual(large, 2.6 * small,
                             f'Doubled path depth rescanned {large}/{small} ancestor characters')

    def test_terminal_middle_clipping_work_is_bounded_by_viewport(self):
        label = 'PREFIX-' + 'x' * 8192 + '-SUFFIX'
        with patch.object(picker, '_width', wraps=picker._width) as width:
            rendered = picker._middle(label, 32)
            calls = width.call_count
        self.assertLessEqual(len(rendered), 32)
        self.assertGreaterEqual(len(rendered), 29)
        self.assertTrue(rendered.startswith('PREFIX-'))
        self.assertTrue(rendered.endswith('-SUFFIX'))
        self.assertIn('...', rendered)
        self.assertLessEqual(calls, 32 * 8,
                             f'A 32-column label scanned {calls} character widths')

    def test_storage_blocker_scan_stops_after_matching_process_cwd(self):
        proc = self.base / 'proc'
        process = proc / '123'
        (process / 'fd').mkdir(parents=True)
        for i in range(64):
            (process / 'fd' / str(i)).touch()
        original_path = storage.Path
        links = []
        maps = []
        protected = self.base / 'protected'

        def link(path):
            links.append(path.name)
            return str(protected) if path.name == 'cwd' else '/unrelated'

        def read(path, **kwargs):
            if path.name == 'maps':
                maps.append(path)
                return ''
            return 'fixture-process\n'

        with patch.object(storage, 'Path', side_effect=lambda value: proc if value == '/proc' else original_path(value)), \
                patch.dict(storage.process_helpers, read_link=link, read_process_file=read):
            blocked = storage.active_users([protected])
        self.assertEqual(blocked, ['123 fixture-process'])
        self.assertLessEqual(len(links) + len(maps), 2,
                             f'Known cwd blocker still required {len(links)} link reads and {len(maps)} maps reads')

    def test_storage_mount_inspection_has_finite_deadline(self):
        payload = {'filesystems': [{'target': '/mnt/data', 'fstype': 'ext4', 'uuid': 'fixture'}]}
        result = types.SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr='')
        with patch.object(storage.subprocess, 'run', return_value=result) as run:
            self.assertEqual(storage.mount_info('/mnt/data'), payload['filesystems'][0])
        timeout = run.call_args.kwargs.get('timeout')
        self.assertTrue(isinstance(timeout, (int, float)) and 0 < timeout <= 10,
                        f'Read-only mount inspection has unbounded timeout {timeout!r}')

    def test_accelerator_cache_reads_do_not_materialize_unselected_padding(self):
        path = self.base / 'accelerator.json'
        path.write_text(json.dumps({'fingerprint': 'fixture', 'value': 'GPU fixture', 'padding': 'x' * 262144}))
        sizes = []
        original = Path.open

        class Reader:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                self.stream.__enter__()
                return self

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

            def __getattr__(self, name):
                return getattr(self.stream, name)

            def read(self, *args, **kwargs):
                value = self.stream.read(*args, **kwargs)
                sizes.append(len(value))
                return value

        def observe(candidate, *args, **kwargs):
            stream = original(candidate, *args, **kwargs)
            return Reader(stream) if candidate == path else stream

        with patch.object(Path, 'open', observe):
            self.assertEqual(system.read_accelerator_cache(path, 'fixture'), 'GPU fixture')
            self.assertIsNone(system.read_accelerator_cache(path, 'other'))
        self.assertLessEqual(max(sizes, default=0), 65536,
                             f'Accelerator cache materialized {max(sizes, default=0)} bytes in one read')


if __name__ == '__main__':
    unittest.main()
