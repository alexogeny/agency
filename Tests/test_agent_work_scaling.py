import contextlib
import concurrent.futures
import datetime as dt
import types
import json
import os
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest import mock

from Tests import test_agent_work as base

sys.path.insert(0, str(base.ROOT / 'Tools'))
import agent_work_messages as messages


class ScalingTests(base.AgentWorkFixture, unittest.TestCase):
    def core(self):
        h = messages.load_core()
        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(os.environ, {'AGENT_WORK_STATE_DIR': str(self.state)}).start()
        return h

    def test_reachable_nested_transfer_has_bounded_coverage_work(self):
        scopes = ['/'.join(['src'] + ['child'] * i) for i in range(8)]
        args = ['start', '--task', 'Nested owner', '--json']
        for scope in scopes:
            args.extend(('--scope', scope))
        owner = json.loads(self.run_tool(*args).stdout)
        worker = self.start('Worker', 'tests')
        target = scopes[-1] + '/transferred'
        request = json.loads(self.run_tool('request-claim', worker['id'], target, '--json').stdout)
        granted = json.loads(self.run_tool('respond', owner['id'], request['id'], '--revision', '1',
                                          '--decision', 'yield', '--quiesced', '--json').stdout)
        self.assertEqual(granted['status'], 'granted')
        h = self.core()
        with contextlib.closing(h.database()) as db:
            task = h.task_record(db, owner['id'])
            self.assertEqual(len(messages.exclusions(db, owner['id'])), 8)
            with mock.patch.object(messages, 'contains', wraps=messages.contains) as counted:
                self.assertFalse(messages.can_write(h, db, task, [target]))
                calls = counted.call_count
            self.assertLess(calls, 1000, f'nested coverage required {calls} containment checks')
            self.assertTrue(messages.can_write(h, db, task, ['src/other']))
        denied = self.run_tool('check-write', owner['id'], target, '--json', check=False)
        self.assertEqual(denied.returncode, 3)
        self.assertFalse(json.loads(denied.stdout)['allowed'])

    def request_fixture(self, n):
        h = self.core()
        db = h.database()
        stamp = h.iso_time(h.utc_now() - dt.timedelta(minutes=2))
        for i in range(n + 1):
            identity = f'task-{i}'
            db.execute('''INSERT INTO tasks(id,repo_id,repo_root,task,worktree,scratch,started_at,
                deadline_at,heartbeat_at,status) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (identity, 'fixture', str(self.repo), identity, str(self.repo), str(self.workspace),
                 stamp, '2099-01-01T00:00:00Z', stamp, 'active'))
            db.execute('INSERT INTO claims VALUES (?,?)', (identity, f'src/{i}'))
            db.execute('INSERT INTO task_auth(task_id,token_hash) VALUES (?,?)',
                       (identity, messages.token_hash('fixture-token')))
        for i in range(n):
            db.execute('INSERT INTO claim_requests VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (f'req-{i}', 'fixture', f'task-{i+1}', 1, '["src"]',
                        json.dumps([{'task_id': 'task-0'}]), 'pending', 'fixture', stamp, None, None))
        db.commit()
        self.addCleanup(db.close)
        return h, db

    def test_attention_graph_and_sql_are_batched(self):
        h, db = self.request_fixture(128)
        queries = []
        db.set_trace_callback(queries.append)
        with mock.patch.object(messages.json, 'loads', wraps=json.loads) as loads:
            result = messages.attention(h, db, h.task_record(db, 'task-0'))
            parsed = loads.call_count
        self.assertEqual(len(result['pending_requests']), 128)
        self.assertTrue(all(not item['wait_cycle'] for item in result['pending_requests']))
        self.assertLess(parsed, 1000, f'{parsed} JSON values parsed for 128 requests')
        self.assertLess(len(queries), 20, f'{len(queries)} statements for 128 requests')

    def test_board_serialization_has_constant_database_crossings(self):
        h, db = self.request_fixture(64)
        rows = db.execute('SELECT * FROM tasks ORDER BY id').fetchall()
        queries = []
        db.set_trace_callback(queries.append)
        with mock.patch.object(messages.json, 'loads', wraps=json.loads) as loads:
            result = h.serialize_tasks(db, rows)
            parsed = loads.call_count
        self.assertEqual(len(result), 65)
        self.assertEqual(sum(len(item['pending_requests']) for item in result), 128)
        self.assertEqual(len(result[0]['claims']), 1)
        self.assertLess(len(queries), 20, f'{len(queries)} statements serializing 65 tasks')
        self.assertLess(parsed, 1500, f'{parsed} JSON values parsed serializing 65 tasks')

    def test_cycle_membership_excludes_tasks_only_leading_into_a_cycle(self):
        h, db = self.request_fixture(4)
        # 1 <-> 2, 3 -> 1, 4 -> 0. A path into a cycle is not itself a cycle.
        for request, owner in ((0, 'task-2'), (1, 'task-1'), (2, 'task-1')):
            db.execute('UPDATE claim_requests SET snapshot_json=? WHERE id=?',
                       (json.dumps([{'task_id': owner}]), f'req-{request}'))
        expected = {'task-0': False, 'task-1': True, 'task-2': True, 'task-3': False, 'task-4': False}
        for identity, cyclic in expected.items():
            self.assertEqual(messages.wait_cycle(db, identity), cyclic)
        records = messages.attention(h, db, h.task_record(db, 'task-1'))['pending_requests']
        self.assertEqual({item['requester']: item['wait_cycle'] for item in records},
                         {'task-1': True, 'task-2': True, 'task-3': False})

    def test_conflict_exclusions_are_prefetched(self):
        h, db = self.request_fixture(32)
        queries = []
        db.set_trace_callback(queries.append)
        conflicts = h.find_conflicts(db, 'fixture', ['.'] * 32)
        self.assertEqual(len(conflicts), 33 * 32)
        self.assertLess(len(queries), 5, f'{len(queries)} statements for claim pairs')

    def test_reopening_current_schema_does_not_migrate_or_scan_history(self):
        h, db = self.request_fixture(16)
        db.close()
        original = sqlite3.connect
        queries = []
        def connect(*args, **kwargs):
            connection = original(*args, **kwargs)
            connection.set_trace_callback(queries.append)
            return connection
        with mock.patch.object(sqlite3, 'connect', side_effect=connect):
            for _ in range(3):
                with contextlib.closing(h.database()) as reopened:
                    self.assertEqual(reopened.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 17)
        forbidden = [q for q in queries if any(word in q.upper() for word in
                     ('CREATE ', 'ALTER ', 'TABLE_INFO', 'LEFT JOIN TASK_AUTH', 'BEGIN IMMEDIATE'))]
        self.assertEqual(forbidden, [])

    def test_hole_union_coverage_preserves_partial_and_full_reacquisition(self):
        h, db = self.request_fixture(1)
        task = h.task_record(db, 'task-0')
        db.execute("DELETE FROM claims WHERE task_id='task-0'")
        db.executemany("INSERT INTO claims VALUES ('task-0',?)", [('src',), ('src/hole/back',), ('/outside',)])
        db.execute("INSERT INTO claim_exclusions VALUES ('task-0','src','src/hole')")
        self.assertFalse(messages.can_write(h, db, task, ['src']))
        self.assertFalse(messages.can_write(h, db, task, ['src/hole']))
        self.assertTrue(messages.can_write(h, db, task, ['src/hole/back/file']))
        self.assertTrue(messages.can_write(h, db, task, ['src/other', '/outside/file']))
        self.assertFalse(messages.can_write(h, db, task, ['/other']))
        db.execute("INSERT INTO claims VALUES ('task-0','src/hole')")
        self.assertTrue(messages.can_write(h, db, task, ['src']))
        db.execute("INSERT INTO claim_exclusions VALUES ('task-0','src/hole','src/hole/back/lost')")
        # The independent child claim still covers this second claim's hole.
        self.assertTrue(messages.can_write(h, db, task, ['src']))
        db.execute("INSERT INTO claim_exclusions VALUES ('task-0','src/hole/back','src/hole/back/lost')")
        self.assertFalse(messages.can_write(h, db, task, ['src']))
        db.execute("INSERT INTO claim_responses VALUES ('req-0',1,'task-0','yield','',NULL,'[]')")
        self.assertFalse(messages.can_write(h, db, task, ['src/other']))
        self.assertTrue(messages.can_write(h, db, task, ['/outside/file']))

    def test_deep_graph_duplicate_edges_and_self_cycles(self):
        edges = {str(i): [str(i + 1), str(i + 1)] for i in range(3000)}
        self.assertEqual(messages.cycle_members(edges), set())
        edges['3000'] = ['2999']
        edges['self'] = ['self', 'self']
        self.assertEqual(messages.cycle_members(edges), {'2999', '3000', 'self'})
        edges['3000'] = ['0']
        self.assertEqual(messages.cycle_members(edges), {str(i) for i in range(3001)} | {'self'})

    def test_unrelated_repository_does_not_increase_attention_parsing(self):
        h, db = self.request_fixture(8)
        task = h.task_record(db, 'task-0')
        def parsed_attention():
            with mock.patch.object(messages.json, 'loads', wraps=json.loads) as loads:
                result = messages.attention(h, db, task)
                return result, loads.call_count
        before, before_count = parsed_attention()
        for i in range(512):
            db.execute('INSERT INTO claim_requests VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (f'other-{i}', 'other-repo', 'task-1', 1, '["other"]',
                        '[{"task_id":"task-2"}]', 'pending', '', '2026-10-22', None, None))
        after, after_count = parsed_attention()
        self.assertEqual(after, before)
        self.assertEqual(after_count, before_count)

    def test_attention_snapshot_survives_concurrent_insert_and_revision(self):
        h, db = self.request_fixture(2)
        writer = sqlite3.connect(self.state / 'tasks.sqlite3')
        self.addCleanup(writer.close)
        changed = False
        def concurrent_write(query):
            nonlocal changed
            if changed or 'SELECT a.request_id' not in query:
                return
            changed = True
            writer.execute("UPDATE claim_requests SET revision=2 WHERE id='req-0'")
            writer.execute("INSERT INTO claim_responses VALUES ('req-0',2,'task-0','yield','new revision',NULL,'[]')")
            writer.execute("""INSERT INTO claim_requests VALUES ('new-request','fixture','task-1',1,
                '["src"]','[{"task_id":"task-0"}]','pending','','2026-10-22',NULL,NULL)""")
            writer.execute("INSERT INTO claim_responses VALUES ('new-request',1,'task-0','yield','new request',NULL,'[]')")
            writer.commit()
        db.set_trace_callback(concurrent_write)
        old = messages.attention(h, db, h.task_record(db, 'task-0'))
        db.set_trace_callback(None)
        self.assertTrue(changed)
        self.assertEqual({r['id'] for r in old['pending_requests']}, {'req-0', 'req-1'})
        self.assertEqual(next(r for r in old['pending_requests'] if r['id'] == 'req-0')['revision'], 1)
        self.assertTrue(all(not r['responses'] for r in old['pending_requests']))
        fresh = messages.attention(h, db, h.task_record(db, 'task-0'))
        self.assertEqual(len(fresh['pending_requests']), 3)
        updated = next(r for r in fresh['pending_requests'] if r['id'] == 'req-0')
        self.assertEqual(updated['revision'], 2)
        self.assertEqual(updated['responses'][0]['note'], 'new revision')
        self.assertEqual(len(fresh['paused_scopes']), 2)
        self.assertFalse(db.in_transaction)

    def test_read_snapshot_does_not_commit_callers_transaction(self):
        h, db = self.request_fixture(1)
        db.execute('BEGIN IMMEDIATE')
        db.execute("UPDATE claim_requests SET note='not committed' WHERE id='req-0'")
        result = messages.attention(h, db, h.task_record(db, 'task-0'))
        self.assertEqual(result['pending_requests'][0]['note'], 'not committed')
        self.assertTrue(db.in_transaction)
        db.rollback()
        self.assertEqual(messages.request_record(h, db, 'req-0')['note'], 'fixture')

    def test_old_binary_insert_after_version_upgrade_is_provisioned_once(self):
        h, db = self.request_fixture(1)
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], h.SCHEMA_VERSION)
        for identity, status in (('legacy-active', 'active'), ('legacy-terminal', 'complete')):
            db.execute('''INSERT INTO tasks(id,repo_id,repo_root,task,worktree,scratch,started_at,
                deadline_at,heartbeat_at,status) SELECT ?,repo_id,repo_root,task,worktree,scratch,
                started_at,deadline_at,heartbeat_at,? FROM tasks WHERE id='task-0' ''', (identity, status))
        db.commit()
        self.assertEqual(db.execute('SELECT task_id FROM legacy_auth_pending').fetchall()[0][0], 'legacy-active')
        with contextlib.closing(h.database()) as reopened:
            self.assertEqual(reopened.execute("SELECT legacy FROM task_auth WHERE task_id='legacy-active'").fetchone()[0], 1)
            self.assertIsNone(reopened.execute("SELECT 1 FROM task_auth WHERE task_id='legacy-terminal'").fetchone())
            self.assertEqual(reopened.execute('SELECT COUNT(*) FROM legacy_auth_pending').fetchone()[0], 0)
        credential = messages.credential_path(h, 'legacy-active')
        token = credential.read_text()
        self.assertEqual(credential.stat().st_mode & 0o777, 0o600)
        db.execute("UPDATE tasks SET status='active' WHERE id='legacy-terminal'")
        db.commit()
        with contextlib.closing(h.database()) as reopened:
            self.assertEqual(reopened.execute("SELECT legacy FROM task_auth WHERE task_id='legacy-terminal'").fetchone()[0], 1)
            self.assertEqual(reopened.execute('SELECT COUNT(*) FROM legacy_auth_pending').fetchone()[0], 0)
        self.assertEqual(credential.read_text(), token)

    def test_stale_board_batches_attention_reads(self):
        h, db = self.request_fixture(64)
        args = types.SimpleNamespace(after='1m', all_repos=True, repo=None, since=None, limit=100)
        queries = []
        db.set_trace_callback(queries.append)
        with mock.patch.object(h, 'database', return_value=db), mock.patch.object(h, 'emit') as emit:
            h.command_stale(args, True)
        result = emit.call_args.args[0]
        self.assertEqual(len(result), 65)
        self.assertEqual(sum(len(item['pending_requests']) for item in result), 128)
        self.assertLess(len(queries), 25)
        self.assertFalse(db.in_transaction)

    def test_read_commands_do_not_take_writer_lock_or_wake_watchers(self):
        h, db = self.request_fixture(1)
        sender = h.task_record(db, 'task-1')
        sent = messages.message(h, db, sender, 'broadcast', ['task-0'], {'note': 'retained'})
        db.commit()
        writer = sqlite3.connect(self.state / 'tasks.sqlite3')
        self.addCleanup(writer.close)
        writer.execute('BEGIN IMMEDIATE')
        db.execute('PRAGMA busy_timeout=0')
        for operation in ('inbox', 'message', 'request', 'check-write'):
            with self.subTest(operation=operation):
                args = types.SimpleNamespace(command=operation, task_id='task-0', limit=50,
                                             all=False, message_id=sent['id'], request_id='req-0', paths=['src/0'])
                with mock.patch.object(h, 'database', return_value=db), mock.patch.object(h, 'emit') as emit, \
                     mock.patch.object(messages, 'wake') as wake:
                    messages.command(h, args, True)
                self.assertTrue(emit.called)
                self.assertFalse(wake.called)
                self.assertFalse(db.in_transaction)

    def test_inspect_releases_snapshot_before_selection_and_refreshes_record(self):
        h, db = self.request_fixture(1)
        args = types.SimpleNamespace(task_id=None, task_option=None, all=True, all_repos=True,
                                     repo=None, since=None, limit=100)
        def select_task(*args, **kwargs):
            self.assertFalse(db.in_transaction)
            with sqlite3.connect(self.state / 'tasks.sqlite3') as writer:
                writer.execute("UPDATE tasks SET latest_note='changed during selection' WHERE id='task-0'")
            return types.SimpleNamespace(returncode=0, stdout='task-0\tselected')
        with mock.patch.object(h, 'database', return_value=db), mock.patch.object(h, 'emit') as emit, \
             mock.patch.object(sys.stdout, 'isatty', return_value=True), \
             mock.patch.object(h.shutil, 'which', return_value='/usr/bin/fzf'), \
             mock.patch.object(h.subprocess, 'run', side_effect=select_task):
            h.command_inspect(args, False)
        self.assertEqual(emit.call_args.args[0]['latest_note'], 'changed during selection')
        self.assertFalse(db.in_transaction)

    def test_delivery_batch_builds_request_graph_once(self):
        h, db = self.request_fixture(128)
        task = h.task_record(db, 'task-0')
        messages.register_session(h, db, task, 'codex', 'batch-fixture')
        for i in range(8):
            messages.message(h, db, h.task_record(db, f'task-{i+1}'), 'claim-request', ['task-0'],
                             {'note': 'fixture'}, request_id=f'req-{i}')
        db.commit()
        queries = []
        db.set_trace_callback(queries.append)
        with mock.patch.object(messages.json, 'loads', wraps=json.loads) as loads:
            batch = messages.reserve_batch(h, db, 'codex', 'batch-fixture')
            parsed = loads.call_count
        self.assertEqual(len(batch['items']), 8)
        self.assertTrue(all(f'req-{i}' in batch['context'] for i in range(8)))
        self.assertLess(parsed, 600)
        self.assertLess(len(queries), 25)
        attempts = db.execute("SELECT attempts,state FROM message_deliveries WHERE task_id='task-0'").fetchall()
        self.assertEqual([(row[0], row[1]) for row in attempts], [(1, 'queued')] * 8)
        db.rollback()

    def test_existing_message_schema_upgrade_is_atomic_under_concurrent_opens(self):
        h, db = self.request_fixture(1)
        db.execute('ALTER TABLE task_auth DROP COLUMN legacy')
        db.execute('PRAGMA user_version=0')
        db.commit()
        # This old schema has authenticated rows but no legacy flag. Concurrent
        # readers must observe either the old schema or the completed migration.
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.run_tool('status', 'task-0', '--json'), range(4)))
        self.assertTrue(all(json.loads(result.stdout)['id'] == 'task-0' for result in results))
        with contextlib.closing(h.database()) as upgraded:
            self.assertEqual(upgraded.execute('PRAGMA user_version').fetchone()[0], h.SCHEMA_VERSION)
            row = upgraded.execute("SELECT token_hash,legacy FROM task_auth WHERE task_id='task-0'").fetchone()
            self.assertEqual(tuple(row), (messages.token_hash('fixture-token'), 0))
            self.assertEqual(upgraded.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(upgraded.execute('SELECT COUNT(*) FROM legacy_auth_pending').fetchone()[0], 0)

    def test_disjoint_conflict_search_does_not_compare_every_pair(self):
        h, db = self.request_fixture(256)
        requested = [f'other/{i}' for i in range(512)]
        calls = 0
        original = h.claims_overlap
        def overlap(*args):
            nonlocal calls
            calls += 1
            return original(*args)
        with mock.patch.object(h, 'claims_overlap', side_effect=overlap):
            self.assertEqual(h.find_conflicts(db, 'fixture', requested), [])
        self.assertLess(calls, 1024, f'{calls} overlap checks for disjoint sets')
        # Prefix siblings and absolute/relative roots must remain separate.
        db.execute("INSERT INTO claims VALUES ('task-0','/external/a')")
        db.execute("INSERT INTO claim_exclusions VALUES ('task-0','/external/a','/external/a/hole')")
        requested = ['src/1/file', 'src/10', 'src/10x', '/external/a/file', '/external/a/hole/f', '.']
        expected = []
        ownership = messages.ownership_exclusions(db, 'fixture')
        rows = db.execute("""SELECT t.id,t.task,c.path FROM tasks t JOIN claims c ON c.task_id=t.id
            WHERE t.repo_id='fixture' AND t.status IN ('active','waiting')""").fetchall()
        for row in rows:
            for claim in requested:
                if messages.overlaps(h, db, row['id'], row['path'], claim, ownership=ownership):
                    expected.append({'task_id': row['id'], 'task': row['task'], 'existing': row['path'], 'requested': claim})
        self.assertEqual(h.find_conflicts(db, 'fixture', requested), expected)

    def test_batched_attention_retains_open_request_and_pause_order(self):
        h, db = self.request_fixture(3)
        db.execute("UPDATE claim_requests SET status='needs-review' WHERE id='req-2'")
        for identity in ('req-1', 'req-0'):
            db.execute("INSERT INTO claim_responses VALUES (?,1,'task-0','yield','',NULL,'[]')", (identity,))
        result = messages.attention(h, db, h.task_record(db, 'task-0'))
        self.assertEqual([item['id'] for item in result['pending_requests']], ['req-2', 'req-0', 'req-1'])
        self.assertEqual([item['request_id'] for item in result['paused_scopes']], ['req-1', 'req-0'])


if __name__ == '__main__':
    unittest.main()
