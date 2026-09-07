import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
import assert from 'node:assert/strict';
const phase = Bun.argv[2];
const failQuery = phase.startsWith('query-') ? Number(phase.slice(6)) : -1;
const originalDatabase = database;
const originalQuery = Database.prototype.query;
const originalTransaction = Database.prototype.transaction;
const originalClose = Database.prototype.close;
const failure = new Error('forced indexer setup failure');
let prepared = 0, closes = 0, ready = false;
let opened, schemaError;
database = () => {
  opened = originalDatabase();
  if (phase === 'malformed') {
    opened.run('DROP TABLE pages_fts');
    opened.run('CREATE TABLE pages_fts (broken TEXT)');
  }
  ready = true;
  return opened;
};
Database.prototype.query = function(sql, ...args) {
  if (ready && ++prepared === failQuery) throw failure;
  try { return originalQuery.call(this, sql, ...args); }
  catch (error) { schemaError = error; throw error; }
};
Database.prototype.transaction = function(...args) {
  if (ready && phase === 'transaction') throw failure;
  return originalTransaction.apply(this, args);
};
Database.prototype.close = function(...args) {
  closes++;
  return originalClose.apply(this, args);
};
try {
  if (phase === 'success') {
    const indexer = pageIndexer();
    assert.equal(prepared, 7);
    assert.equal(closes, 0);
    const result = indexer.write({ url: 'https://fixture.test/page', canonicalUrl: 'https://fixture.test/page',
      title: 'Fixture', text: 'Searchable evidence', markdown: 'Searchable evidence',
      published: '', byline: '', links: [], sources: [], html: '' });
    assert.equal(result.retrieval, 'live');
    assert.deepEqual(originalQuery.call(opened, 'SELECT title, text FROM pages').all(), [{ title: 'Fixture', text: 'Searchable evidence' }]);
    assert.equal(originalQuery.call(opened, "SELECT count(*) AS count FROM pages_fts WHERE pages_fts MATCH 'Searchable'").get().count, 1);
    assert.equal(closes, 0);
    indexer.close();
    assert.equal(closes, 1);
  } else {
    let caught;
    try { pageIndexer(); } catch (error) { caught = error; }
    assert.equal(caught, phase === 'malformed' ? schemaError : failure);
    assert.ok(caught instanceof Error);
    assert.equal(closes, 1, 'failed indexer setup must close exactly once');
    assert.throws(() => originalQuery.call(opened, 'SELECT 1').get());
    if (phase === 'transaction') assert.equal(prepared, 7);
    if (failQuery > 0) assert.equal(prepared, failQuery);
  }
  console.log('ok');
} finally {
  if (opened && closes === 0) originalClose.call(opened);
}
'''


class WebResearchIndexerCleanupTests(unittest.TestCase):
    def run_phase(self, phase):
        source = (ROOT / 'Tools' / 'web-research').read_text()
        source = source.split('\nconst args = Bun.argv.slice(2);', 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / 'indexer.ts'
            script.write_text(source + HARNESS)
            result = subprocess.run(['bun', script, phase], capture_output=True, text=True, timeout=10,
                env={**os.environ, 'WEB_RESEARCH_DATA_DIR': str(root / 'data')})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, 'ok\n')

    def test_each_statement_prepare_failure_closes_and_preserves_original_error(self):
        for index in range(1, 8):
            with self.subTest(index=index):
                self.run_phase(f'query-{index}')

    def test_transaction_construction_failure_closes_and_preserves_error(self):
        self.run_phase('transaction')

    def test_actual_malformed_fts_schema_closes_connection(self):
        self.run_phase('malformed')

    def test_successful_write_leaves_connection_open_until_explicit_close(self):
        self.run_phase('success')
