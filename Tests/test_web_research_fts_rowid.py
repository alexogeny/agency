import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(os.environ.get("AGENCY_TEST_SCRATCH", ROOT / ".cache/tests"))
HARNESS = r'''
import assert from 'node:assert/strict';
const mode = Bun.argv[2];
const page = (i, text = `body${i}`) => ({
  url: `https://fixture.test/${i}`, canonicalUrl: `https://fixture.test/${i}`,
  title: `Heading ${i}`, text, markdown: text, html: '', published: '', byline: '', links: [], sources: []
});
const seedLegacy = () => {
  mkdirSync(dataRoot, {recursive: true});
  const db = new Database(join(dataRoot, 'index.sqlite'));
  db.run('CREATE TABLE pages (url TEXT PRIMARY KEY, title TEXT NOT NULL, text TEXT NOT NULL, markdown TEXT NOT NULL, fetched_at TEXT NOT NULL)');
  db.run("CREATE VIRTUAL TABLE pages_fts USING fts5(url UNINDEXED, title, text, tokenize='unicode61')");
  for (const [i, rowid] of [[0, 41], [1, 7], [2, 9007199254740993n]]) {
    const p = page(i);
    db.query('INSERT INTO pages VALUES (?, ?, ?, ?, ?)').run(p.url, p.title, p.text, p.markdown, '2025-01-01T00:00:00.000Z');
    db.query('INSERT INTO pages_fts (rowid, url, title, text) VALUES (?, ?, ?, ?)').run(rowid, p.url, p.title, p.text);
  }
  db.close();
};
const legacySnapshot = db => ({
  pages: db.query('SELECT url, title, text, markdown, fetched_at FROM pages ORDER BY url').all(),
  fts: db.query('SELECT CAST(rowid AS TEXT) AS rowid, url, title, text FROM pages_fts ORDER BY url').all()
});
const snapshot = db => ({
  pages: db.query('SELECT * FROM pages ORDER BY url').all(),
  fts: db.query('SELECT CAST(rowid AS TEXT) AS rowid, url, title, text FROM pages_fts ORDER BY url').all(),
  aliases: db.query('SELECT * FROM page_aliases ORDER BY request_url').all()
});
const verifyMappings = (db, count) => {
  assert.equal(db.query('SELECT count(*) AS n FROM pages JOIN pages_fts ON pages.fts_rowid = pages_fts.rowid AND pages.url = pages_fts.url').get().n, count);
  assert.equal(db.query('SELECT count(*) AS n FROM pages_fts').get().n, count);
};
if (mode === 'seed') {
  seedLegacy();
  const db = database();
  if (db.query('PRAGMA table_info(pages)').all().some(column => column.name === 'fts_rowid')) {
    db.run('ALTER TABLE pages DROP COLUMN fts_rowid');
  }
  db.close();
} else if (mode === 'lookup') {
  const original = Database.prototype.query;
  const deletions = [];
  Database.prototype.query = function(sql, ...args) {
    const statement = original.call(this, sql, ...args);
    if (sql.startsWith('DELETE FROM pages_fts WHERE ')) {
      return {run(...values) {deletions.push({sql, values}); return statement.run(...values);}};
    }
    return statement;
  };
  const writer = pageIndexer();
  for (let i = 0; i < 100; i++) writer.write(page(i));
  assert.equal(deletions.length, 0);
  writer.write(page(0, 'replacementbody'));
  assert.equal(deletions.length, 1);
  assert.equal(deletions[0].sql, 'DELETE FROM pages_fts WHERE rowid = ? AND url = ?');
  const db = database();
  const plan = db.query(`EXPLAIN QUERY PLAN ${deletions[0].sql}`).all(...deletions[0].values);
  assert(plan.some(row => /VIRTUAL TABLE INDEX .*=/u.test(row.detail)));
  assert.equal(db.query("SELECT count(*) AS n FROM pages_fts WHERE pages_fts MATCH 'body0'").get().n, 0);
  assert.equal(db.query("SELECT count(*) AS n FROM pages_fts WHERE pages_fts MATCH 'replacementbody'").get().n, 1);
  verifyMappings(db, 100);
  db.close(); writer.close();
} else if (mode === 'migration') {
  seedLegacy();
  let db = new Database(join(dataRoot, 'index.sqlite'));
  const before = legacySnapshot(db);
  db.close();
  db = database();
  assert.deepEqual(legacySnapshot(db), before);
  assert.deepEqual(db.query('SELECT CAST(fts_rowid AS TEXT) AS rowid FROM pages ORDER BY url').all(), before.fts.map(({rowid}) => ({rowid})));
  verifyMappings(db, 3);
  db.close();
} else if (mode === 'large_rowids') {
  seedLegacy();
  const original = Database.prototype.query;
  let fallbackDeletes = 0;
  Database.prototype.query = function(sql, ...args) {
    const statement = original.call(this, sql, ...args);
    if (sql === 'DELETE FROM pages_fts WHERE url = ?') {
      return {run(...values) {fallbackDeletes++; return statement.run(...values);}};
    }
    return statement;
  };
  const writer = pageIndexer();
  const db = database();
  for (const [i, text] of [[0, 'firstrevision'], [0, 'secondrevision'], [2, 'largestoriginal']]) {
    writer.write(page(i, text));
    verifyMappings(db, 3);
    assert.equal(db.query('SELECT CAST(fts_rowid AS TEXT) AS id FROM pages WHERE url = ?').get(page(i).url).id,
                 db.query('SELECT CAST(rowid AS TEXT) AS id FROM pages_fts WHERE url = ?').get(page(i).url).id);
  }
  assert.equal(fallbackDeletes, 0);
  db.close(); writer.close();
} else if (mode === 'migration_failure') {
  seedLegacy();
  let db = new Database(join(dataRoot, 'index.sqlite'));
  const before = legacySnapshot(db);
  db.run("CREATE TRIGGER reject_mapping BEFORE UPDATE ON pages BEGIN SELECT RAISE(ABORT, 'forced migration failure'); END");
  db.close();
  const close = Database.prototype.close;
  let closes = 0;
  Database.prototype.close = function(...args) {closes++; return close.apply(this, args);};
  try {assert.throws(() => database(), /forced migration failure/);}
  finally {Database.prototype.close = close;}
  assert.equal(closes, 1);
  db = new Database(join(dataRoot, 'index.sqlite'));
  assert(!db.query('PRAGMA table_info(pages)').all().some(column => column.name === 'fts_rowid'));
  assert.deepEqual(legacySnapshot(db), before);
  db.close();
} else if (mode === 'mixed_writers') {
  const writer = pageIndexer();
  writer.write(page(0)); writer.write(page(1));
  const db = database();
  const other = db.query('SELECT rowid, url, text FROM pages_fts WHERE url = ?').get(page(1).url);
  db.transaction(() => {
    db.query('DELETE FROM pages_fts WHERE url = ?').run(page(0).url);
    db.query('INSERT INTO pages_fts (url, title, text) VALUES (?, ?, ?)').run(page(0).url, 'Legacy', 'legacybody');
    db.query('UPDATE pages SET title = ?, text = ? WHERE url = ?').run('Legacy', 'legacybody', page(0).url);
  })();
  writer.write(page(0, 'currentbody'));
  assert.equal(db.query("SELECT count(*) AS n FROM pages_fts WHERE pages_fts MATCH 'legacybody'").get().n, 0);
  verifyMappings(db, 2);
  db.query('UPDATE pages SET fts_rowid = NULL WHERE url = ?').run(page(0).url);
  writer.write(page(0, 'missingmapping'));
  verifyMappings(db, 2);
  db.query('UPDATE pages SET fts_rowid = ? WHERE url = ?').run(other.rowid, page(0).url);
  writer.write(page(0, 'wrongmapping'));
  verifyMappings(db, 2);
  assert.deepEqual(db.query('SELECT rowid, url, text FROM pages_fts WHERE url = ?').get(page(1).url), other);
  assert.deepEqual(db.query('SELECT text FROM pages_fts WHERE url = ?').all(page(0).url), [{text: 'wrongmapping'}]);
  db.close(); writer.close();
} else if (mode === 'write_failure') {
  const writer = pageIndexer(); writer.write(page(0)); writer.write(page(1));
  const db = database();
  const before = snapshot(db);
  db.run("CREATE TRIGGER reject_mapping BEFORE UPDATE OF fts_rowid ON pages BEGIN SELECT RAISE(ABORT, 'forced mapping failure'); END");
  assert.throws(() => writer.write(page(0, 'broken'), 'https://fixture.test/failedalias'), /forced mapping failure/);
  assert.deepEqual(snapshot(db), before);
  assert.throws(() => writer.write(page(2)), /forced mapping failure/);
  assert.deepEqual(snapshot(db), before);
  db.close(); writer.close();
} else if (mode === 'race') {
  const [marker, go] = Bun.argv.slice(3);
  const original = Database.prototype.transaction;
  Database.prototype.transaction = function(fn) {
    const transaction = original.call(this, fn);
    return {immediate(...args) {
      writeFileSync(marker, 'old schema observed');
      const deadline = performance.now() + 5000;
      const signal = new Int32Array(new SharedArrayBuffer(4));
      while (!existsSync(go)) {
        assert(performance.now() < deadline, 'migration race deadline');
        Atomics.wait(signal, 0, 0, 10);
      }
      return transaction.immediate(...args);
    }};
  };
  const db = database();
  verifyMappings(db, 3);
  db.close();
} else {
  throw new Error(`unknown case ${mode}`);
}
console.log(JSON.stringify({checked: mode}));
'''


class WebResearchFtsRowidTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        source = (ROOT / "Tools/web-research").read_text()
        marker = "\nconst args = Bun.argv.slice(2);"
        self.assertEqual(source.count(marker), 1)
        self.script = self.root / "rowid.ts"
        self.script.write_text(source.split(marker, 1)[0] + HARNESS)
        self.environment = dict(os.environ, WEB_RESEARCH_DATA_DIR=str(self.root / "data"))

    def run_case(self, name):
        result = subprocess.run(["bun", str(self.script), name], env=self.environment,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"checked": name})

    def test_changed_pages_use_one_rowid_delete_and_new_pages_use_none(self):
        self.run_case("lookup")

    def test_migration_preserves_content_timestamps_and_exact_rowids(self):
        self.run_case("migration")

    def test_failed_migration_rolls_back_and_closes_its_connection(self):
        self.run_case("migration_failure")

    def test_large_rowids_stay_exact_during_updates(self):
        self.run_case("large_rowids")

    def test_old_writers_and_missing_or_wrong_mappings_recover(self):
        self.run_case("mixed_writers")

    def test_failed_mapping_write_rolls_back_pages_aliases_and_search(self):
        self.run_case("write_failure")

    def test_two_initializers_recheck_stale_schema_inside_the_transaction(self):
        self.run_case("seed")
        children = []
        try:
            for name in ("first", "second"):
                ready, go = self.root / f"{name}.ready", self.root / f"{name}.go"
                process = subprocess.Popen(["bun", str(self.script), "race", str(ready), str(go)],
                                           env=self.environment, text=True, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
                children.append((process, ready, go))
            deadline = time.monotonic() + 4
            while not all(ready.exists() for _, ready, _ in children):
                self.assertTrue(all(process.poll() is None for process, _, _ in children),
                                "both initializers must reach the migration transaction")
                self.assertLess(time.monotonic(), deadline, "initializers missed the schema barrier")
                time.sleep(0.01)
            for process, _, go in children:
                go.write_text("continue")
                output, error = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, error)
                self.assertEqual(json.loads(output), {"checked": "race"})
        finally:
            for process, _, _ in children:
                if process.poll() is None:
                    process.terminate()
                process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
