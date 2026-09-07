import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(os.environ.get("AGENCY_TEST_SCRATCH", ROOT / ".cache/tests"))
HARNESS = r'''
import assert from "node:assert/strict";

const cases = [
  ["  Ordinary article\nSecond line  ", "Ordinary article\nSecond line"],
  ["", ""],
  [" \n\n\n ", ""],
  ["first\r\nsecond\r\n", "first\r\nsecond"],
  ["\u00a0head\u2003\n\u2003", "head"],
  ["first\n\n\n\n\nlast", "first\n\nlast"],
  ["first\n `` \nlast", "first\nlast"],
  ["first\r\n``\r\nlast\r\n", "first\r\nlast"],
  ["first\n\u2003``\u00a0\nlast", "first\nlast"],
  ["```python\nprint('hello')\n```", "```python\nprint('hello')\n```"],
  ["before ``code`` after", "before ``code`` after"],
  ["single `code` span", "single `code` span"],
  ["``", ""],
];
for (const [input, expected] of cases) {
  assert.equal(cleanExtractedMarkdown(input), expected);
}
const input = Array(10000).fill("Ordinary article text.").join("\n");
const originalSplit = String.prototype.split;
let calls = 0;
let items = 0;
String.prototype.split = function(separator: any, limit: any) {
  const result = originalSplit.call(this, separator, limit);
  if (separator === "\n") {
    calls++;
    items += result.length;
  }
  return result;
};
let result;
try {
  result = cleanExtractedMarkdown(input);
} finally {
  String.prototype.split = originalSplit;
}
assert.equal(result, input);
console.log(JSON.stringify({cases: cases.length, calls, items}));
'''


class WebResearchMarkdownTests(unittest.TestCase):
    def test_plain_markdown_does_not_materialize_line_items(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as temporary:
            workspace = Path(temporary)
            source = (ROOT / "Tools/web-research").read_text()
            marker = "\nconst args = Bun.argv.slice(2);"
            self.assertEqual(source.count(marker), 1)
            script = workspace / "markdown-test.ts"
            script.write_text(source.split(marker)[0] + HARNESS)
            result = subprocess.run(
                ["bun", str(script)],
                env=dict(os.environ, WEB_RESEARCH_DATA_DIR=str(workspace / "data")),
                text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads(result.stdout)
            self.assertEqual(evidence["cases"], 13)
            self.assertEqual(evidence["calls"], 0)
            self.assertEqual(evidence["items"], 0)


if __name__ == "__main__":
    unittest.main()
