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
mkdirSync(dataRoot, {recursive:true});
const NativeSet = globalThis.Set;
let outcomeSets = 0;
globalThis.Set = class extends NativeSet {
  constructor(values) {
    super(values);
    if (Array.isArray(values) && values.join(',') === 'scraped,partial,failed') outcomeSets++;
  }
};
fail = message => {throw new Error(message);};
const record = (url, outcome) => JSON.stringify({schema:'agency/web-page-result/1',requested_url:url,outcome});
if (Bun.argv[2] === 'count') {
  writeFileSync(output, Array.from({length:1000},(_,i)=>record(`https://fixture.test/${i}`,'scraped')).join('\n'));
  assert.equal(completedBatchUrls(output,false).size,1000);
  assert.equal(outcomeSets,1,'outcome validator must be constructed once per call');
} else {
  const lines = ['scraped','partial','failed'].map(outcome=>record(outcome,outcome));
  writeFileSync(output,lines.join('\n'));
  assert.deepEqual([...completedBatchUrls(output,false)],['scraped','partial','failed']);
  assert.deepEqual([...completedBatchUrls(output,true)],['scraped']);
  for (const invalid of ['unknown',null,0,{},['scraped']]) {
    writeFileSync(output,lines[0]+'\n'+record('bad',invalid));
    assert.throws(()=>completedBatchUrls(output,false),/invalid record on line 2/);
  }
  writeFileSync(output,'\n');
  assert.equal(completedBatchUrls(output,false).size,0);
}
'''


class ResumeOutcomesTests(unittest.TestCase):
    def run_harness(self, mode):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            path = Path(directory) / 'outcomes.ts'
            source = (ROOT / 'Tools/web-research').read_text().split('\nconst args = Bun.argv.slice(2);')[0]
            path.write_text(source + HARNESS)
            result = subprocess.run(['bun', str(path), mode], capture_output=True, text=True,
                                    env={**os.environ, 'WEB_RESEARCH_DATA_DIR': str(Path(directory) / 'data')})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_one_outcome_set_per_call(self):
        self.run_harness('count')

    def test_outcomes_retry_and_invalid_records(self):
        self.run_harness('semantics')
