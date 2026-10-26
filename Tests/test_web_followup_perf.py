import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "Tools/web-research-mcp"
HARNESS = r'''
import assert from "node:assert/strict";
const fixtures = [
  { ref_id: "one", markdown: "\r\n  Heading\r\nCAFÉ match\r\nOther\r\nmatch TWO\r\n", patterns: ["match", "  café  ", "absent", "TWO"] },
  { ref_id: "two", markdown: "MATCH\n".repeat(120), patterns: ["match", "absent", "MATCH"] },
  { ref_id: "empty", markdown: " \n ", patterns: ["missing"] },
  { ref_id: "fallback", markdown: "", text: "Fallback MATCH", patterns: ["fallback", "match"] },
];
const items = fixtures.flatMap(f => f.patterns.map(pattern => ({ ref_id: f.ref_id, pattern })));
// Interleave pages so grouping cannot change response order.
items.sort((a, b) => a.pattern.localeCompare(b.pattern));
const pages = new Map(fixtures.map(f => [f.ref_id, {
  kind: "page", ref_id: f.ref_id, title: f.ref_id, url: `https://example.test/${f.ref_id}`,
  page: { markdown: f.markdown, text: f.text }, evidence: new Set(),
}]));
loadPages = async ids => ids.map(id => pages.get(id));
const originalCitation = pageCitation;
let citations = 0;
pageCitation = page => { citations++; return originalCitation(page); };
const lower = String.prototype.toLocaleLowerCase;
let folds = 0;
String.prototype.toLocaleLowerCase = function(...args) { folds++; return lower.apply(this, args); };
const actual = await performFind(items, "transient", "");
String.prototype.toLocaleLowerCase = lower;
pageCitation = originalCitation;
const expected = { records: [], rendered: [] };
for (const item of items) {
  const page = pages.get(item.ref_id);
  const pattern = item.pattern.trim();
  const lines = String(page.page.markdown || page.page.text || "").trim().split(/\r?\n/);
  const matches = lines.map((line, index) => ({ line, lineno: index + 1 }))
    .filter(({ line }) => line.toLocaleLowerCase().includes(pattern.toLocaleLowerCase()));
  const retained = matches.slice(0, 50);
  const numbers = retained.map(match => match.lineno);
  expected.records.push({ type: "find", ref_id: page.ref_id, pattern, matches: matches.length,
    lines: numbers, citation: { ...pageCitation(page), evidence_lines: numbers } });
  expected.rendered.push(`[${page.ref_id}] ${pattern}: ${matches.length} match${matches.length === 1 ? "" : "es"}\n${retained.map(({ line, lineno }) => `${lineno}: ${line}`).join("\n")}`.trim());
}
assert.deepStrictEqual(actual, expected);
assert.deepStrictEqual(sourceLedger(actual.records), sourceLedger(expected.records));
if (Bun.argv[2] === "guard") {
  const pageLines = fixtures.reduce((count, f) => count + String(f.markdown || f.text || "").trim().split(/\r?\n/).length, 0);
  assert.equal(folds, items.length + pageLines, "fold each page line once per batch");
  assert.equal(citations, pages.size, "hash citation content once per page per batch");
}
console.log(JSON.stringify({ checked: items.length }));
'''


class WebFollowupPerformanceTests(unittest.TestCase):
    def run_harness(self, mode):
        source = SERVER.read_text().split('\nlet inputBuffer = "";', 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "find.ts"
            script.write_text(source + "\n" + HARNESS)
            result = subprocess.run(["bun", script, mode], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"checked": 10})

    def test_grouped_find_preserves_output_and_citations(self):
        self.run_harness("equivalence")

    def test_grouped_find_folds_and_hashes_each_page_once(self):
        self.run_harness("guard")


if __name__ == "__main__":
    unittest.main()
