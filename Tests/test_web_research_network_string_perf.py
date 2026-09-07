import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(os.environ.get("AGENCY_TEST_SCRATCH", ROOT / ".cache/tests"))
HARNESS = r'''
import assert from 'node:assert/strict';
function referenceNetworkJson(value: unknown) {
  let nodes = 0;
  const visit = (item: unknown, depth: number): unknown => {
    nodes += 1;
    if (nodes > 2_000 || depth > 8 || item === null) return null;
    if (typeof item === "string") {
      const cleaned = terminalText(item).slice(0, 4_000);
      return /^https?:\/\//i.test(cleaned)
        ? redactedOutputUrl(cleaned)
        : cleaned;
    }
    if (typeof item === "number" || typeof item === "boolean") return item;
    if (Array.isArray(item)) {
      return item
        .slice(0, 100)
        .map((value) => visit(value, depth + 1))
        .filter((value) => value !== null);
    }
    if (typeof item !== "object") return null;
    const result: JsonObject = {};
    for (const key of Object.keys(item).slice(0, 100)) {
      if (
        sensitiveQueryParameter(key) ||
        /^(?:cookie|set-cookie|password|passwd|authorization)$/i.test(key)
      ) {
        continue;
      }
      const sanitized = visit((item as JsonObject)[key], depth + 1);
      if (sanitized !== null) result[key] = sanitized;
    }
    return result;
  };
  return visit(value, 0);
}

const fixtures = {
  'long-plain': 'x'.repeat(500000),
  'control-fallback': '\u0000x'.repeat(250000),
  'short-plain': 'Ordinary network response text.',
  'short-control': '\u0000Hello\u0007\u001f world\u007f\n\t',
  'url': 'https://user:pass@example.test/path?token=secret&topic=flowers#fragment',
};

const cases: unknown[] = [null, true, 42, '', 'x'.repeat(3999), 'x'.repeat(4000), 'x'.repeat(4001),
  'x'.repeat(3999)+'😀tail', 'x'.repeat(3998)+'😀tail', '\u0000'+'x'.repeat(3999)+'😀tail',
  '\u0000'.repeat(5000)+'tail'.repeat(3000), '😀漢字\u2028\u2029\u0085'.repeat(1000),
  'https://user:pass@example.test/?token=secret&topic=flowers#fragment',
  '\u0000https://user:pass@example.test/?access_token=secret&topic=flowers#fragment',
  { password: 'hidden', token: 'hidden', title: 'Title', nested: [fixtures['long-plain'], fixtures['short-control'], null, { url: fixtures.url }] },
  Array.from({length: 120}, (_,i)=>({title:String(i)})),
];
let nested: unknown = 'bottom'; for (let i=0;i<12;i++) nested={nested}; cases.push(nested);
let seed=123456789;
function next(){seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed;}
const alphabet=['a','Z',' ','\u0000','\u0007','\u000b','\u000c','\r','\n','\t','\u001f','\u007f','😀','漢','\ud800','\udc00','\u2028'];
for(let i=0;i<200;i++) {
  let text=''; const length=next()%7000;
  for(let j=0;j<length;j++) text+=alphabet[next()%alphabet.length];
  cases.push(text);
}
for(const value of cases) assert.deepEqual(sanitizedNetworkJson(value),referenceNetworkJson(value));

for (const value of Object.values(fixtures)) {
  assert.deepEqual(sanitizedNetworkJson(value), referenceNetworkJson(value));
}
assert.equal(sanitizedNetworkJson(fixtures.url), 'https://example.test/path?topic=flowers');
function measureSanitizer(value: unknown) {
  const original = terminalText;
  let calls = 0, units = 0;
  terminalText = (input: unknown) => {
    calls++;
    units += String(input).length;
    return original(input);
  };
  try { return { output: sanitizedNetworkJson(value), calls, units }; }
  finally { terminalText = original; }
}
const plain = measureSanitizer(fixtures['long-plain']);
assert.equal(plain.output, 'x'.repeat(4000));
assert.equal(plain.units, 4000);
assert.equal(plain.calls, 1);
const fallback = measureSanitizer(fixtures['control-fallback']);
assert.equal(fallback.output, 'x'.repeat(4000));
assert.equal(fallback.units, 504000);
assert.equal(fallback.calls, 2);
console.log(JSON.stringify({cases: cases.length + Object.keys(fixtures).length}));
'''


class WebResearchNetworkStringTests(unittest.TestCase):
    def test_bounded_prefix_preserves_network_json_semantics(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as temporary:
            workspace = Path(temporary)
            source = (ROOT / "Tools/web-research").read_text()
            marker = "\nconst args = Bun.argv.slice(2);"
            self.assertEqual(source.count(marker), 1)
            script = workspace / "network-string-test.ts"
            script.write_text(source.split(marker)[0] + HARNESS)
            result = subprocess.run(
                ["bun", str(script)],
                env=dict(os.environ, WEB_RESEARCH_DATA_DIR=str(workspace / "data")),
                text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"cases": 222})


if __name__ == "__main__":
    unittest.main()
