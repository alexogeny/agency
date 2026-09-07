import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(os.environ.get('AGENCY_TEST_SCRATCH', ROOT / '.cache/tests'))
HARNESS = r'''
import assert from 'node:assert/strict';
const phase = Bun.argv[2];
const originalRun = Database.prototype.run;
const originalQuery = Database.prototype.query;
const originalClose = Database.prototype.close;
const failure = new Error('forced initialization failure');
let closes = 0;
let opened;
Database.prototype.close = function(...args) {
  closes++;
  return originalClose.apply(this, args);
};
Database.prototype.run = function(sql, ...args) {
  opened = this;
  const matches = {
    journal: 'PRAGMA journal_mode', synchronous: 'PRAGMA synchronous',
    pages: 'CREATE TABLE IF NOT EXISTS pages ',
    legacy: 'ALTER TABLE pages ADD COLUMN published ',
    aliases: 'CREATE TABLE IF NOT EXISTS page_aliases ',
    fts: 'CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts ',
    rowid: 'ALTER TABLE pages ADD COLUMN fts_rowid ',
    mapping: 'UPDATE pages SET fts_rowid = '
  };
  if (matches[phase] && sql.startsWith(matches[phase])) throw failure;
  return originalRun.call(this, sql, ...args);
};
Database.prototype.query = function(sql, ...args) {
  opened = this;
  if (sql === 'PRAGMA table_info(pages)') {
    if (phase === 'schema-prepare') throw failure;
    if (phase === 'schema-read') return {all() {throw failure;}};
  }
  return originalQuery.call(this, sql, ...args);
};
if (phase === 'success') {
  const db = database();
  assert.equal(closes, 0);
  assert.deepEqual(db.query('SELECT 42 AS value').get(), {value: 42});
  assert.ok(db.query('PRAGMA table_info(pages)').all().some(column => column.name === 'fts_rowid'));
  db.close();
  assert.equal(closes, 1);
} else {
  assert.throws(() => database(), error => error === failure);
  assert.equal(closes, 1, phase + ' must close its connection exactly once');
  assert.throws(() => originalQuery.call(opened, 'SELECT 1').get());
}
'''


class DatabaseCleanupTests(unittest.TestCase):
    def run_harness(self, phase):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            path = Path(directory) / 'cleanup.ts'
            source = (ROOT / 'Tools/web-research').read_text()
            self.assertEqual(source.count('\nconst args = Bun.argv.slice(2);'), 1)
            path.write_text(source.split('\nconst args = Bun.argv.slice(2);')[0] + HARNESS)
            result = subprocess.run(['bun', str(path), phase], capture_output=True, text=True,
                                    env={**os.environ, 'WEB_RESEARCH_DATA_DIR': str(Path(directory) / 'data')})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_initialization_failures_close_connection_and_preserve_error(self):
        for phase in ('journal', 'synchronous', 'pages', 'schema-prepare', 'schema-read',
                      'legacy', 'aliases', 'fts', 'rowid', 'mapping'):
            with self.subTest(phase=phase):
                self.run_harness(phase)

    def test_success_returns_open_usable_connection(self):
        self.run_harness('success')
