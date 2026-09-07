import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(os.environ.get('AGENCY_TEST_SCRATCH', ROOT / '.cache/tests'))
HARNESS = r'''
import assert from 'node:assert/strict';
let deletes = 0;
let failInsert = false;
const originalQuery = Database.prototype.query;
Database.prototype.query = function(sql, ...args) {
  const statement = originalQuery.call(this, sql, ...args);
  if (sql.startsWith('DELETE FROM pages_fts WHERE ')) {
    return {run(...values) {deletes++; return statement.run(...values);}};
  }
  if (sql === 'INSERT INTO pages_fts (url, title, text) VALUES (?, ?, ?)') {
    return {run(...values) {
      if (failInsert) throw new Error('forced FTS failure');
      return statement.run(...values);
    }};
  }
  return statement;
};
const page = (url, title, text, canonicalUrl = url) => ({
  url, canonicalUrl, title, text, markdown: text, html: '',
  published: '', byline: '', links: [], sources: []
});
const indexer = pageIndexer();
const db = database();
const matches = term => db.query('SELECT url FROM pages_fts WHERE pages_fts MATCH ? ORDER BY url').all(term).map(row => row.url);
const snapshot = () => ({
  pages: db.query('SELECT * FROM pages ORDER BY url').all(),
  fts: db.query('SELECT * FROM pages_fts ORDER BY url').all(),
  aliases: db.query('SELECT * FROM page_aliases ORDER BY request_url').all()
});
indexer.write(page('https://fixture.test/first', 'Oldtitle', 'oldbody'));
indexer.write(page('https://fixture.test/second', 'Other', 'otherbody'));
const insertDeletes = deletes;
assert.deepEqual(matches('oldbody'), ['https://fixture.test/first']);
assert.deepEqual(matches('Oldtitle'), ['https://fixture.test/first']);
assert.equal(db.query('SELECT count(*) AS n FROM pages_fts').get().n, 2);
const updated = indexer.write(page('https://fixture.test/alias#fragment', 'Newtitle', 'newbody', 'https://fixture.test/first'), 'https://fixture.test/request');
assert.equal(updated.changed, true);
assert.equal(deletes - insertDeletes, 1);
assert.deepEqual(matches('oldbody'), []);
assert.deepEqual(matches('Oldtitle'), []);
assert.deepEqual(matches('newbody'), ['https://fixture.test/first']);
assert.deepEqual(matches('Newtitle'), ['https://fixture.test/first']);
assert.equal(db.query('SELECT count(*) AS n FROM pages_fts').get().n, 2);
assert.equal(cachedPage('https://fixture.test/alias').page.text, 'newbody');
assert.equal(cachedPage('https://fixture.test/request').page.title, 'Newtitle');
const unchanged = indexer.write(page('https://fixture.test/first', 'Newtitle', 'newbody'));
assert.equal(unchanged.changed, false);
assert.equal(db.query('SELECT count(*) AS n FROM pages_fts').get().n, 2);
indexer.write(page('https://fixture.test/alias', 'Thirdtitle', 'thirdbody', 'https://fixture.test/third'));
assert.equal(cachedPage('https://fixture.test/alias').page.url, 'https://fixture.test/third');
assert.deepEqual(matches('thirdbody'), ['https://fixture.test/third']);
assert.deepEqual(matches('newbody'), ['https://fixture.test/first']);
const before = snapshot();
failInsert = true;
assert.throws(() => indexer.write(page('https://fixture.test/first', 'Broken', 'brokenbody'), 'https://fixture.test/failedalias'), /forced FTS failure/);
assert.deepEqual(snapshot(), before);
assert.throws(() => indexer.write(page('https://fixture.test/newfailed', 'Broken', 'brokenbody')), /forced FTS failure/);
assert.deepEqual(snapshot(), before);
indexer.close();
db.close();
console.log(JSON.stringify({insertDeletes, pages: before.pages.length, searchRows: before.fts.length, rollback: true}));
'''


class WebResearchIndexTests(unittest.TestCase):
    def run_harness(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            root = Path(directory)
            source = (ROOT / 'Tools/web-research').read_text()
            marker = '\nconst args = Bun.argv.slice(2);'
            self.assertEqual(source.count(marker), 1)
            script = root / 'index-test.ts'
            script.write_text(source.split(marker)[0] + HARNESS)
            env = dict(os.environ, WEB_RESEARCH_DATA_DIR=str(root / 'data'))
            result = subprocess.run(['bun', str(script)], env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

    def test_new_pages_do_not_delete_search_rows(self):
        self.assertEqual(self.run_harness()['insertDeletes'], 0)

    def test_search_updates_aliases_and_rollback(self):
        result = self.run_harness()
        self.assertEqual((result['pages'], result['searchRows'], result['rollback']), (3, 3, True))


if __name__ == '__main__':
    unittest.main()
