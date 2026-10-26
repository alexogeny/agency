import contextlib
import io
import json
import os
import sqlite3
import sys
import unittest
from unittest import mock

from Tests import test_agent_work as base

sys.path.insert(0, str(base.ROOT / 'Tools'))
import agent_work_messages as messages


class HookScalingTests(base.AgentWorkFixture, unittest.TestCase):
    def invoke_hook(self, payload, *, state_dir=None):
        output = io.StringIO()
        with mock.patch.dict(os.environ, {'AGENT_WORK_STATE_DIR': str(state_dir or self.state)}), \
             mock.patch.object(sys, 'argv', ['agent-work-hook', '--client', 'codex']), \
             mock.patch.object(sys, 'stdin', io.StringIO(json.dumps(payload))), \
             contextlib.redirect_stdout(output):
            self.assertEqual(messages.hook_main(), 0)
        return json.loads(output.getvalue())

    def test_unrelated_session_uses_no_schema_or_write_transaction(self):
        owner = self.start('Owner', 'src')
        h = messages.load_core()
        # A live writer must not block an unrelated lifecycle event. Setting the
        # probe connection's busy timeout to zero makes accidental locking fail.
        with sqlite3.connect(self.state / 'tasks.sqlite3') as writer:
            writer.execute('BEGIN IMMEDIATE')
            original = sqlite3.connect
            queries = []
            def connect(*args, **kwargs):
                kwargs['timeout'] = 0
                db = original(*args, **kwargs)
                db.set_trace_callback(queries.append)
                return db
            with mock.patch.object(messages, 'load_core', return_value=h), \
                 mock.patch.object(sqlite3, 'connect', side_effect=connect), \
                 mock.patch.object(h, 'database', wraps=h.database) as full_open:
                result = self.invoke_hook({'session_id': 'unrelated', 'cwd': str(self.repo)})
            self.assertEqual(result, {})
            self.assertEqual(full_open.call_count, 0)
            self.assertFalse(any(q.lstrip().upper().startswith(('BEGIN', 'UPDATE', 'INSERT', 'CREATE')) for q in queries))
        self.assertTrue(owner['id'])

    def test_forged_registration_does_not_enter_write_path(self):
        owner = self.start('Owner', 'src')
        h = messages.load_core()
        forged = {**owner, 'task_token': 'invalid'}
        with mock.patch.object(messages, 'load_core', return_value=h), \
             mock.patch.object(h, 'database', wraps=h.database) as full_open:
            self.assertEqual(self.invoke_hook({'session_id': 'forged', 'cwd': str(self.repo),
                                               'tool_response': {'stdout': json.dumps(forged)}}), {})
        self.assertEqual(full_open.call_count, 0)

    def test_relative_state_directory_remains_supported(self):
        self.start('Owner', 'src')
        prior = os.getcwd()
        try:
            os.chdir(self.workspace)
            self.assertEqual(self.invoke_hook({'session_id': 'relative'}, state_dir='state'), {})
        finally:
            os.chdir(prior)

    def test_registered_idle_session_does_not_take_a_writer_lock(self):
        owner = self.start('Owner', 'src')
        self.run_tool('session', owner['id'], '--client', 'codex', '--session', 'idle', '--json')
        h = messages.load_core()
        with sqlite3.connect(self.state / 'tasks.sqlite3') as writer:
            writer.execute('BEGIN IMMEDIATE')
            with mock.patch.object(messages, 'load_core', return_value=h), \
                 mock.patch.object(h, 'database', side_effect=AssertionError('idle event requested writer')):
                self.assertEqual(self.invoke_hook({'session_id': 'idle', 'cwd': str(self.repo)}), {})


if __name__ == '__main__':
    unittest.main()
