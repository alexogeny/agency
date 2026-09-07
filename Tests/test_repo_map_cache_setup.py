import os
from pathlib import Path
import runpy
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch


CACHE_DATABASE = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'Tools' / 'repo-map'))['cache_database']


class TrackedConnection(sqlite3.Connection):
    closes = 0
    setup_error = None

    def close(self):
        self.closes += 1
        return super().close()

    def execute(self, *args):
        try:
            return super().execute(*args)
        except sqlite3.Error as error:
            self.setup_error = error
            raise


class RepoMapCacheSetupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, REPO_MAP_CACHE_DIR=temporary.name)
        environment.start()
        self.addCleanup(environment.stop)

    def test_schema_failure_closes_once_and_preserves_exception(self):
        failure = sqlite3.OperationalError('schema setup failed')
        connection = Mock()
        connection.execute.side_effect = failure
        with patch.object(sqlite3, 'connect', return_value=connection):
            with self.assertRaises(sqlite3.OperationalError) as caught:
                CACHE_DATABASE()
        self.assertIs(caught.exception, failure)
        connection.close.assert_called_once_with()
        connection.commit.assert_not_called()

    def test_real_sqlite_authorization_failure_closes_connection(self):
        connection = sqlite3.connect(':memory:', factory=TrackedConnection)
        connection.set_authorizer(lambda action, *args: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TABLE else sqlite3.SQLITE_OK)
        try:
            with patch.object(sqlite3, 'connect', return_value=connection):
                with self.assertRaises(sqlite3.DatabaseError) as caught:
                    CACHE_DATABASE()
            self.assertIs(caught.exception, connection.setup_error)
            self.assertEqual(connection.closes, 1)
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute('SELECT 1')
        finally:
            if not connection.closes:
                connection.close()

    def test_success_returns_open_connection_with_usable_schema(self):
        connection = CACHE_DATABASE()
        try:
            connection.execute('INSERT INTO facts VALUES (?, ?, ?)', ('digest', 4, '{}'))
            self.assertEqual(connection.execute('SELECT digest, facts_json FROM facts').fetchall(), [('digest', '{}')])
        finally:
            connection.close()

    def test_connect_failure_preserves_original_error(self):
        failure = sqlite3.OperationalError('cannot connect')
        with patch.object(sqlite3, 'connect', side_effect=failure):
            with self.assertRaises(sqlite3.OperationalError) as caught:
                CACHE_DATABASE()
        self.assertIs(caught.exception, failure)
