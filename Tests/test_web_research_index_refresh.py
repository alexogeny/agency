import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from Tests.test_web_research_index_perf import ROOT, SCRATCH


HARNESS = r'''
import assert from 'node:assert/strict';
let writes = 0;
let failInsert = false;
const originalQuery = Database.prototype.query;
Database.prototype.query = function(sql, ...args) {
  const statement = originalQuery.call(this, sql, ...args);
  if (sql.startsWith('DELETE FROM pages_fts WHERE ')) {
    return {run(...values) {writes++; return statement.run(...values);}};
  }
  if (sql === 'INSERT INTO pages_fts (url, title, text) VALUES (?, ?, ?)') {
    return {run(...values) {
      writes++;
      if (failInsert) throw new Error('forced FTS failure');
      return statement.run(...values);
    }};
  }
  return statement;
};
const page = i => ({url: `https://fixture.test/${i}`, canonicalUrl: `https://fixture.test/${i}`,
  title: 'Same', text: 'evidence', markdown: 'evidence', html: '', published: '', byline: '', links: [], sources: []});
const indexer = pageIndexer();
const db = database();
const snapshot = () => ({
  pages: db.query('SELECT * FROM pages ORDER BY url').all(),
  fts: db.query('SELECT * FROM pages_fts ORDER BY url').all(),
  aliases: db.query('SELECT * FROM page_aliases ORDER BY request_url').all()
});
const matches = term => db.query('SELECT url FROM pages_fts WHERE pages_fts MATCH ? ORDER BY url').all(term).map(row => row.url);
const ranked = () => db.query("SELECT url FROM pages_fts WHERE pages_fts MATCH 'evidence' ORDER BY rank").all().map(row => row.url);
indexer.write(page(0));
indexer.write(page(1));
const beforeOrder = ranked();
writes = 0;
const unchanged = indexer.write(page(0));
assert.equal(unchanged.changed, false);
const unchangedWrites = writes;
const afterOrder = ranked();
db.query("UPDATE pages SET fetched_at = '2000-01-01T00:00:00.000Z', refresh_after = NULL WHERE url = ?").run(page(0).url);
writes = 0;
const revised = {...page(0), markdown: 'new markdown only', byline: 'Updated author', published: '2001-01-01', links: ['https://fixture.test/link'], sources: ['fixture']};
const refreshed = indexer.write(revised, 'https://fixture.test/request', 'stale');
const markdownWrites = writes;
assert.equal(refreshed.changed, true);
assert.equal(refreshed.cache, 'stale');
const stored = db.query('SELECT * FROM pages WHERE url = ?').get(page(0).url);
assert.equal(stored.markdown, revised.markdown);
assert.equal(stored.byline, revised.byline);
assert.equal(stored.published, revised.published);
assert.equal(stored.links_json, JSON.stringify(revised.links));
assert.equal(stored.sources_json, JSON.stringify(revised.sources));
assert.equal(stored.content_sha256, contentHash(revised));
assert.equal(stored.fetched_at, refreshed.indexed_at);
assert.notEqual(stored.fetched_at, '2000-01-01T00:00:00.000Z');
assert.equal(stored.refresh_after, refreshed.refresh_after);
assert.equal(cachedPage('https://fixture.test/request').page.byline, revised.byline);
writes = 0;
const retitled = {...revised, title: 'Retitled'};
assert.equal(indexer.write(retitled).changed, false);
const titleWrites = writes;
assert.deepEqual(matches('Retitled'), [page(0).url]);
assert.deepEqual(matches('Same'), [page(1).url]);
writes = 0;
const retexted = {...retitled, text: 'replacementbody'};
assert.equal(indexer.write(retexted).changed, false);
const textWrites = writes;
assert.deepEqual(matches('replacementbody'), [page(0).url]);
assert.deepEqual(matches('evidence'), [page(1).url]);
writes = 0;
indexer.write(page(2));
const newWrites = writes;
const before = snapshot();
failInsert = true;
assert.throws(() => indexer.write({...retexted, text: 'failure'}, 'https://fixture.test/failed'), /forced FTS failure/);
assert.deepEqual(snapshot(), before);
assert.throws(() => indexer.write(page(3)), /forced FTS failure/);
assert.deepEqual(snapshot(), before);
assert.equal(before.pages.length, 3);
assert.equal(before.fts.length, 3);
db.close();
indexer.close();
console.log(JSON.stringify({unchangedWrites, markdownWrites, titleWrites, textWrites, newWrites, beforeOrder, afterOrder}));
'''


class WebResearchRefreshTests(unittest.TestCase):
    def run_harness(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            root = Path(directory)
            source = (ROOT / 'Tools/web-research').read_text()
            marker = '\nconst args = Bun.argv.slice(2);'
            self.assertEqual(source.count(marker), 1)
            script = root / 'refresh-test.ts'
            script.write_text(source.split(marker)[0] + HARNESS)
            result = subprocess.run(['bun', str(script)], env=dict(os.environ, WEB_RESEARCH_DATA_DIR=str(root / 'data')), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

    def test_unchanged_fields_skip_search_writes(self):
        result = self.run_harness()
        self.assertEqual((result['unchangedWrites'], result['markdownWrites']), (0, 0))

    def test_unchanged_refresh_preserves_tied_ranking(self):
        result = self.run_harness()
        self.assertEqual(result['beforeOrder'], ['https://fixture.test/0', 'https://fixture.test/1'])
        self.assertEqual(result['afterOrder'], result['beforeOrder'])

    def test_changed_fields_metadata_aliases_and_rollback(self):
        result = self.run_harness()
        self.assertEqual((result['titleWrites'], result['textWrites'], result['newWrites']), (2, 2, 1))


if __name__ == '__main__':
    unittest.main()
