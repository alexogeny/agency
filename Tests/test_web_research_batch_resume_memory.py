import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(os.environ.get('AGENCY_TEST_SCRATCH', ROOT / '.cache/tests'))
HARNESS = r'''
import assert from 'node:assert/strict';
const output = join(dataRoot, 'fixture.ndjson');
mkdirSync(dataRoot, {recursive: true});
let wholeReads = 0, opens = 0, closes = 0, largestRead = 0, failRead = false;
function readSync(...args) {largestRead = Math.max(largestRead, args[3]); if (failRead) throw new Error("forced read failure"); return originalReadSync(...args);}
function readFileSync(...args) {if (args[0] === output) wholeReads++; return originalReadFileSync(...args);}
function openSync(...args) {if (args[0] === output) opens++; return originalOpenSync(...args);}
function closeSync(...args) {closes++; return originalCloseSync(...args);}
fail = message => {throw new Error(message);};
const record = (url, outcome = 'scraped', body = '') => JSON.stringify({schema: 'agency/web-page-result/1', requested_url: url, outcome, body});
const mode = Bun.argv[2];
if (mode === 'bounded') {
  writeFileSync(output, Array.from({length: 1000}, (_, i) => record(`https://fixture.test/${i}`, 'scraped', 'x'.repeat(1024))).join('\n'));
  assert.equal(completedBatchUrls(output, false).size, 1000);
  assert.equal(wholeReads, 0, 'resume must not materialize the entire file');
  assert.ok(largestRead <= 64 * 1024, 'reads must use bounded chunks');
  assert.equal(opens, 1);
  assert.equal(closes, 1);
} else if (mode === 'lines') {
  for (const offset of [65532, 65533, 65534, 65535, 65536]) {
    for (const suffix of [Buffer.from('😀é\r\nlast\r'), Buffer.from([0xf0, 0x28, 0x8c, 0x28, 10, 0xc3])]) {
      const bytes = Buffer.concat([Buffer.alloc(offset, 120), suffix]);
      writeFileSync(output, bytes);
      assert.deepEqual([...utf8FileLines(output)], bytes.toString('utf8').split(/\r?\n/));
    }
  }
  writeFileSync(output, 'first\nsecond\n');
  let before = closes;
  for (const line of utf8FileLines(output)) {assert.equal(line, 'first'); break;}
  assert.equal(closes - before, 1, 'early exit must close');
  before = closes;
  failRead = true;
  assert.throws(() => [...utf8FileLines(output)], /forced read failure/);
  assert.equal(closes - before, 1, 'read failure must close');
} else {
  const fixtures = ['', '\n\r\n  \n', record('first') + '\r\n\n' + record('second', 'failed') + '\n' + record('third', 'partial') + '\n' + record('first'),
    record('unicode-😀-é', 'scraped', 'x'.repeat(65500)) + '\r\n' + record('last'),
    record('long', 'scraped', 'x'.repeat(300000)), record('bare-cr') + '\r'];
  for (const fixture of fixtures) {
    writeFileSync(output, fixture);
    for (const retry of [false, true]) {
      const expected = new Set(fixture.split(/\r?\n/).filter(line => line.trim()).map(line => JSON.parse(line)).filter(row => !retry || row.outcome === 'scraped').map(row => row.requested_url));
      assert.deepEqual(completedBatchUrls(output, retry), expected);
    }
  }
  const invalidUtf8 = Buffer.concat([Buffer.from(record('prefix').slice(0,-1) + ',"extra":"'), Buffer.from([0xf0, 0x28, 0x8c, 0x28]), Buffer.from('"}\n')]);
  writeFileSync(output, invalidUtf8);
  assert.deepEqual(completedBatchUrls(output, false), new Set(['prefix']));
  for (const [fixture, error] of [
    [record('ok') + '\n\n{', 'invalid JSON on line 3'],
    ['\r\n{}', 'invalid record on line 2'],
    [record('a') + '\r' + record('b'), 'invalid JSON on line 1'],
  ]) {
    writeFileSync(output, fixture);
    const beforeOpen = opens, beforeClose = closes;
    assert.throws(() => completedBatchUrls(output, false), new RegExp(error));
    assert.equal(opens - beforeOpen, closes - beforeClose);
  }
}
'''


class BatchResumeMemoryTests(unittest.TestCase):
    def run_harness(self, mode):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            source = (ROOT / 'Tools/web-research').read_text().split('\nconst args = Bun.argv.slice(2);')[0]
            for name in ('readFileSync', 'openSync', 'closeSync', 'readSync'):
                source = source.replace(f'  {name},', f'  {name} as original{name[0].upper() + name[1:]},', 1)
            path = Path(directory) / 'resume.ts'
            path.write_text(source + HARNESS)
            result = subprocess.run(['bun', str(path), mode], capture_output=True, text=True,
                                    env={**os.environ, 'WEB_RESEARCH_DATA_DIR': str(Path(directory) / 'data')})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_resume_does_not_read_entire_file(self):
        self.run_harness('bounded')

    def test_record_semantics_boundaries_and_cleanup(self):
        self.run_harness('semantics')

    def test_line_iterator_utf8_boundaries_early_exit_and_read_failure(self):
        self.run_harness('lines')
