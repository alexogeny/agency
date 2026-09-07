import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(os.environ.get('AGENCY_TEST_SCRATCH', ROOT / '.cache/tests'))
HARNESS = r'''
import assert from 'node:assert/strict';
const originalEntries = Object.entries;
let pairs = 0;
Object.entries = function(value) {const result = originalEntries(value); pairs += result.length; return result;};
if (Bun.argv[2] === 'count') {
  const input = JSON.parse(JSON.stringify(Object.fromEntries(Array.from({length:50000},(_,i)=>[i.toString(36),0]))));
  const result = sanitizedNetworkJson(input);
  assert.equal(Object.keys(result).length,100);
  assert.equal(pairs,0,'sanitizer must not materialize discarded entry pairs');
} else {
  assert.deepEqual(sanitizedNetworkJson({items:[null,true,42,'text',{password:'hidden',safe:'value'}],token:'hidden'}),{items:[true,42,'text',{safe:'value'}]});
  const input={token:'secret'};
  for(let i=0;i<100;i++) input['key'+i]=i;
  const result=sanitizedNetworkJson(input);
  assert.equal(Object.keys(result).length,99);
  assert.equal(result.key98,98);
  assert.equal(result.key99,undefined,'filtered keys still consume first100 cap');
  assert.deepEqual(Object.keys(sanitizedNetworkJson(JSON.parse('{"10":"ten","2":"two","z":1,"a":2}'))),['2','10','z','a']);
  assert.deepEqual(sanitizedNetworkJson({cookie:'x','set-cookie':'x',password:'x',passwd:'x',authorization:'x',api_key:'x',safe:'https://fixture.test/page?token=hidden&ok=1#fragment'}),{safe:'https://fixture.test/page?ok=1'});
  assert.equal(sanitizedNetworkJson('a\u0000b'+'x'.repeat(5000)).length,4000);
  const wide=sanitizedNetworkJson(Array.from({length:100},()=>Array(100).fill(1)));
  assert.equal(wide.length,20);
  assert.ok(wide.slice(0,19).every(row=>row.length===100));
  assert.equal(wide[19].length,79);
  let deep='leaf';
  for(let i=0;i<10;i++) deep={child:deep};
  let cut=sanitizedNetworkJson(deep);
  for(let i=0;i<8;i++) cut=cut.child;
  assert.deepEqual(cut,{});
  assert.equal(sanitizedNetworkJson(Array(101).fill(1)).length,100);
}
'''


class JsonEntriesTests(unittest.TestCase):
    def run_harness(self, mode):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            path = Path(directory) / 'entries.ts'
            source = (ROOT / 'Tools/web-research').read_text().split('\nconst args = Bun.argv.slice(2);')[0]
            path.write_text(source + HARNESS)
            result = subprocess.run(['bun', str(path), mode], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_discarded_entry_pairs_are_not_materialized(self):
        self.run_harness('count')

    def test_sanitizer_limits_order_and_redaction(self):
        self.run_harness('semantics')
