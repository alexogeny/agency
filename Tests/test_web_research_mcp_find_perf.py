import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1] / "Tools/web-research-mcp"
LINE_OBJECT = "{ line, lineno: lineIndex + 1 }"
HARNESS = r'''
import assert from "node:assert/strict";
const fixtures = await Bun.file(Bun.argv[2]).json();
const citation = {
  source_id: "fixture", title: "Fixture", url: "https://example.test/page",
  published: "", retrieved_at: "", content_sha256: "fixture-hash",
  change_likelihood: "unknown", refresh_after: "", retrieval: "unknown",
};
for (const fixture of fixtures) {
  const page: PageReference = {
    kind: "page", ref_id: "fixture", title: "Fixture", url: citation.url,
    page: { markdown: fixture.markdown, text: fixture.text,
            freshness: { content_sha256: "fixture-hash" } }, evidence: new Set(),
  };
  loadPages = async () => [page];
  lineObjects = 0;
  const result = await performFind([{ ref_id: "fixture", pattern: fixture.pattern }], "transient", "");
  const pattern = fixture.pattern.trim();
  const retained = fixture.expected.slice(0, 50);
  const numbers = retained.map(([lineno]) => lineno);
  const count = fixture.expected.length;
  assert.deepStrictEqual(result, {
    records: [{ type: "find", ref_id: "fixture", pattern, matches: count, lines: numbers,
                citation: { ...citation, evidence_lines: numbers } }],
    rendered: [`[fixture] ${pattern}: ${count} match${count === 1 ? "" : "es"}\n${retained.map(([lineno, line]) => `${lineno}: ${line}`).join("\n")}`.trim()],
  });
  assert.deepStrictEqual(sourceLedger(result.records), [citation]);
  if (fixture.max_objects !== undefined) {
    assert.equal(lineObjects, fixture.max_objects, "line object construction count");
  }
}
console.log(JSON.stringify({ checked: fixtures.length }));
'''


class WebResearchMcpFindTests(unittest.TestCase):
    def run_fixtures(self, fixtures, instrument=False):
        source = SERVER.read_text()
        self.assertEqual(source.count('\nlet inputBuffer = "";'), 1)
        source = source.split('\nlet inputBuffer = "";', 1)[0]
        if instrument:
            self.assertEqual(source.count(LINE_OBJECT), 1)
            source = source.replace(LINE_OBJECT, f"(lineObjects++, {LINE_OBJECT})")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "find.ts"
            script.write_text(source + "\nlet lineObjects = 0;\n" + HARNESS)
            fixture_path = root / "fixtures.json"
            fixture_path.write_text(json.dumps(fixtures))
            result = subprocess.run(["bun", script, fixture_path], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"checked": len(fixtures)})

    def test_line_object_construction_is_bounded_by_retained_matches(self):
        self.run_fixtures([
            {"markdown": "match\n" * 1000, "pattern": "match",
             "expected": [[index + 1, "match"] for index in range(1000)], "max_objects": 50},
            {"markdown": "other\n" * 1000, "pattern": "match", "expected": [], "max_objects": 0},
            {"markdown": "other\nmatch\nother", "pattern": "match",
             "expected": [[2, "match"]], "max_objects": 1},
        ], instrument=True)

    def test_find_preserves_records_rendering_and_source_ledger(self):
        self.run_fixtures([
            {"markdown": "nothing here", "pattern": "match", "expected": []},
            {"markdown": "match\n" * 60, "pattern": "match",
             "expected": [[index + 1, "match"] for index in range(60)]},
            {"markdown": "before\nMATCH one\n\nother\nmatch two\nafter", "pattern": "  match  ",
             "expected": [[2, "MATCH one"], [5, "match two"]]},
            {"markdown": "\r\n  heading\r\n\r\nMATCH\r\nother\r\nmatch  \r\n", "pattern": "match",
             "expected": [[3, "MATCH"], [5, "match"]]},
            {"markdown": "CAFÉ\ncafé\nCafe\nΚαφές", "pattern": "café",
             "expected": [[1, "CAFÉ"], [2, "café"]]},
            {"markdown": "\n \r\n", "pattern": "match", "expected": []},
            {"markdown": "", "text": "fallback MATCH", "pattern": "match",
             "expected": [[1, "fallback MATCH"]]},
        ])


if __name__ == "__main__":
    unittest.main()
