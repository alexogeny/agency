"""Inbox scaling checks with populated message and negotiation state."""

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Tools'))
import agent_work_messages as messages


def populated_inbox(connection, count=64, recipients=12):
    connection.row_factory = sqlite3.Row
    connection.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY, repo_id TEXT, status TEXT)')
    messages.schema(connection)
    connection.executemany('INSERT INTO tasks VALUES (?, ?, ?)',
                           [(f'task-{i:03}', 'fixture', 'active') for i in range(recipients)])
    for i in range(recipients - 1):
        connection.execute('INSERT INTO claim_requests VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                           (f'req-{i}', 'fixture', f'task-{i+1:03}', 1, '["src"]',
                            '[{"task_id":"task-000"}]', 'pending', 'review ownership',
                            '2026-10-26T00:00:00Z', None, None))
    for i in range(count):
        identity = f'message-{i:05}'
        connection.execute('''INSERT INTO work_messages
            (id,repo_id,sender,kind,request_id,body_json,created_at) VALUES(?,?,?,?,?,?,?)''',
                           (identity, 'fixture', 'task-001', 'broadcast', None,
                            json.dumps({'note': f'Progress {i}', 'paths': ['src/one', 'src/two']}),
                            '2026-10-26T00:00:00Z'))
        connection.executemany('''INSERT INTO message_deliveries
            (message_id,task_id,state,delivered_at,acknowledged_at,attempts) VALUES(?,?,?,?,?,?)''',
                              [(identity, f'task-{j:03}',
                                ('queued', 'delivered', 'acknowledged')[i % 3],
                                '2026-10-26T00:01:00Z' if i % 3 else None,
                                '2026-10-26T00:02:00Z' if i % 3 == 2 else None, i % 4)
                               for j in range(recipients)])
    connection.commit()


def reference_inbox(connection, task_id, limit=50, include_acknowledged=False):
    clause = '' if include_acknowledged else "AND d.state IN ('queued','delivered')"
    rows = connection.execute(f'''SELECT m.id,d.state,d.delivered_at,d.acknowledged_at
        FROM work_messages m JOIN message_deliveries d ON d.message_id=m.id
        WHERE d.task_id=? {clause} ORDER BY m.seq LIMIT ?''', (task_id, limit)).fetchall()
    result = []
    for row in rows:
        item = messages.message_record(connection, row['id'])
        item.update({key: row[key] for key in ('state', 'delivered_at', 'acknowledged_at')})
        result.append(item)
    return result


class CoordinationInboxTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        populated_inbox(self.db)

    def test_inbox_batches_database_crossings_with_nonempty_messages(self):
        expected = reference_inbox(self.db, 'task-000')
        statements = []
        self.db.set_trace_callback(statements.append)
        actual = messages.inbox(self.db, 'task-000')
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 43)
        self.assertEqual(len(actual[0]['recipients']), 12)
        selects = [query for query in statements if query.lstrip().upper().startswith('SELECT')]
        self.assertLessEqual(len(selects), 2, f'{len(selects)} SELECTs for {len(actual)} messages')

    def test_limits_acknowledgements_and_recipient_order_are_preserved(self):
        for limit, include in ((1, False), (17, True), (100, True), (0, True)):
            with self.subTest(limit=limit, include=include):
                self.assertEqual(messages.inbox(self.db, 'task-000', limit, include),
                                 reference_inbox(self.db, 'task-000', limit, include))
        self.assertEqual(messages.inbox(self.db, 'missing'), [])
        first = messages.inbox(self.db, 'task-000', 1)[0]
        self.assertEqual(first['recipients'], sorted(first['recipients']))
        self.assertTrue(all(set(item) == {'task_id', 'state', 'delivered_at',
                                         'acknowledged_at', 'attempts'}
                            for item in first['deliveries']))

    def test_inbox_keeps_one_snapshot_when_delivery_changes_during_read(self):
        for count in (1, 4):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'ledger.sqlite3'
                reader = sqlite3.connect(path)
                writer = sqlite3.connect(path)
                try:
                    reader.execute('PRAGMA journal_mode=WAL')
                    populated_inbox(reader, count=count, recipients=2)
                    changed = False

                    def change_delivery(query):
                        nonlocal changed
                        if changed or not query.lstrip().upper().startswith('SELECT'):
                            return
                        if 'FROM message_deliveries' in query:
                            changed = True
                            writer.execute("UPDATE message_deliveries SET attempts=99 WHERE message_id='message-00000'")
                            writer.commit()

                    reader.set_trace_callback(change_delivery)
                    result = messages.inbox(reader, 'task-000')
                    reader.set_trace_callback(None)
                    self.assertTrue(changed)
                    self.assertEqual(result[0]['deliveries'][0]['attempts'], 0)
                    self.assertEqual(messages.inbox(reader, 'task-000')[0]['deliveries'][0]['attempts'], 99)
                    self.assertFalse(reader.in_transaction)
                finally:
                    reader.close()
                    writer.close()

    def test_large_inbox_does_not_exceed_sqlite_variable_limit(self):
        self.db.close()
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        populated_inbox(self.db, count=1007, recipients=2)
        self.db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 1000)
        actual = messages.inbox(self.db, 'task-000', 1007, True)
        self.assertEqual(len(actual), 1007)
        self.assertEqual(actual, reference_inbox(self.db, 'task-000', 1007, True))


if __name__ == '__main__':
    unittest.main()
