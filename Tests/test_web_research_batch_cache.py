import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(os.environ.get('AGENCY_TEST_SCRATCH', ROOT / '.cache/tests'))
HARNESS = r'''
import assert from 'node:assert/strict';
const fixturePage = url => ({url, canonicalUrl: url, title: 'Fixture', text: 'Body', markdown: 'Body', html: '', published: '', byline: '', links: [], sources: []});
const fixtureUrls = Array.from({length: 10}, (_, i) => `https://fixture.test/${i}`);
const ix = pageIndexer();
for (const url of fixtureUrls) ix.write(fixturePage(url));
ix.close();
const setup = database();
setup.run("UPDATE pages SET fetched_at = '2026-01-01T00:00:00.000Z', refresh_after = '2050-01-01T00:00:00.000Z'");
setup.run('INSERT INTO page_aliases (request_url, page_url) VALUES (?, ?)', 'https://fixture.test/alias', fixtureUrls[0]);
setup.close();
Date.now = () => Date.parse('2026-01-02T00:00:00.000Z');
const originalDatabase = database;
const originalQuery = Database.prototype.query;
const originalRun = Database.prototype.run;
let counts = {opens: 0, closes: 0, queries: 0, setup: 0};
let failGet = false, failPrepare = false;
database = function() {
  counts.opens++;
  const db = originalDatabase();
  const close = db.close.bind(db);
  db.close = function(...args) {counts.closes++; return close(...args);};
  return db;
};
Database.prototype.query = function(sql, ...args) {
  counts.queries++;
  if (sql.startsWith('SELECT pages.*')) {
    if (failPrepare) throw new Error('forced prepare failure');
    const statement = originalQuery.call(this, sql, ...args);
    return {get(...values) {if (failGet) throw new Error('forced lookup failure'); return statement.get(...values);}};
  }
  return originalQuery.call(this, sql, ...args);
};
Database.prototype.run = function(...args) {counts.setup++; return originalRun.apply(this, args);};
const output = [];
console.log = value => output.push(JSON.parse(value));
let browserCalls = 0;
withBrowser = async function(options, callback) {
  assert.equal(counts.closes, counts.opens, 'cache reader must close before browser work');
  browserCalls++;
  return callback({});
};
navigateAndExtract = async function(browser, url) {
  if (url.endsWith('/failure')) throw new Error('fixture failure');
  if (url.endsWith('/partial')) return {...fixturePage(url), outcome: 'partial'};
  return fixturePage(url);
};
storedCapture = page => ({...page, capture_id: 'fixture-capture'});
async function batch(urls, args = []) {
  Bun.stdin.text = async () => JSON.stringify({urls});
  await commandScrapeMany([...args]);
  return output.at(-1);
}
const mode = Bun.argv[2];
if (mode === 'count') {
  const expected = fixtureUrls.map(url => cachedPage(url).page);
  counts = {opens: 0, closes: 0, queries: 0, setup: 0};
  assert.deepEqual(await batch(fixtureUrls), {pages: expected});
  assert.equal(counts.opens, 1, 'one database reader per batch');
  assert.equal(counts.closes, 1);
  assert.equal(counts.queries, 2, 'one schema query and one prepared lookup');
  assert.equal(browserCalls, 0);
} else if (mode === 'single') {
  const expected = cachedPage(fixtureUrls[0]);
  assert.equal(counts.opens, 1);
  assert.equal(counts.closes, 1);
  counts = {opens: 0, closes: 0, queries: 0, setup: 0};
  assert.deepEqual(await batch([fixtureUrls[0]]), {pages: [expected.page]});
  assert.equal(counts.opens, 1);
  assert.equal(counts.closes, 1);
} else if (mode === 'mixed') {
  const db = database();
  db.run("UPDATE pages SET refresh_after = '2020-01-01' WHERE url = ?", fixtureUrls[1]);
  db.run("UPDATE pages SET change_likelihood = 'immutable', refresh_after = NULL WHERE url = ?", fixtureUrls[2]);
  db.close();
  const result = await batch(['https://fixture.test/alias', fixtureUrls[1], fixtureUrls[2], 'https://fixture.test/missing', 'https://fixture.test/failure', 'https://fixture.test/partial']);
  assert.equal(result.pages[0].url, fixtureUrls[0]);
  assert.equal(result.pages[0].freshness.cache, 'fresh');
  assert.equal(result.pages[1].freshness.cache, 'stale');
  assert.equal(result.pages[2].freshness.cache, 'immutable');
  assert.equal(result.pages[3].freshness.cache, 'miss');
  assert.equal(result.pages[4].error.message, 'fixture failure');
  assert.equal(result.pages[5].outcome, 'partial');
  assert.equal(result.pages[5].freshness, undefined);
  assert.equal(browserCalls, 1);
} else if (mode === 'capture') {
  const result = await batch([fixtureUrls[0]], ['--capture']);
  assert.equal(counts.opens, 0);
  assert.equal(result.pages[0].capture_id, 'fixture-capture');
  assert.equal(browserCalls, 1);
} else {
  if (mode === 'prepare-error') failPrepare = true;
  else failGet = true;
  await assert.rejects(batch(fixtureUrls), /forced (lookup|prepare) failure/);
  assert.equal(counts.opens, 1);
  assert.equal(counts.closes, 1);
  assert.equal(browserCalls, 0);
}
'''


class BatchCacheTests(unittest.TestCase):
    def run_harness(self, mode):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            path = Path(directory) / 'batch.ts'
            source = (ROOT / 'Tools/web-research').read_text()
            self.assertEqual(source.count('\nconst args = Bun.argv.slice(2);'), 1)
            path.write_text(source.split('\nconst args = Bun.argv.slice(2);')[0] + HARNESS)
            result = subprocess.run(['bun', str(path), mode], capture_output=True, text=True,
                                    env={**os.environ, 'WEB_RESEARCH_DATA_DIR': str(Path(directory) / 'data')})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fully_cached_batch_uses_one_reader(self):
        self.run_harness('count')

    def test_single_page_and_standalone_api(self):
        self.run_harness('single')

    def test_alias_fresh_stale_immutable_missing_and_partial_failure(self):
        self.run_harness('mixed')

    def test_capture_bypasses_database(self):
        self.run_harness('capture')

    def test_reader_closes_on_errors(self):
        for mode in ('prepare-error', 'lookup-error'):
            with self.subTest(mode=mode):
                self.run_harness(mode)
