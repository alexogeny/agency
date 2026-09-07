import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SERVER = Path(__file__).resolve().parents[1] / "Tools/web-research-mcp"
LEGACY_RENDER = r'''
function legacyRenderPage(reference: PageReference, lineno: number, budget: number) {
  const marker = "\n\n[truncated to response_length; use open with lineno to continue]";
  const maximum = Math.max(0, budget - marker.length);
  let rendered = "";
  let truncated = false;
  const append = (value: string) => {
    const remaining = maximum - rendered.length;
    if (value.length <= remaining) {
      rendered += value;
      return true;
    }
    rendered += value.slice(0, Math.max(0, remaining));
    truncated = true;
    return false;
  };
  append(`[${reference.ref_id}] ${reference.title}\n${reference.url}\n`);
  const links = Array.isArray(reference.page.links) ? reference.page.links : [];
  if (!truncated && links.length) {
    append("\nLinks\n");
    const linkBudget = Math.min(1_500, Math.floor(budget / 3));
    const linkStart = rendered.length;
    for (const [index, url] of links.slice(0, 100).entries()) {
      const value = `[${index + 1}] ${String(url)}\n`;
      if (rendered.length - linkStart + value.length > linkBudget) {
        append("[more links omitted]\n");
        break;
      }
      if (!append(value)) break;
    }
  }
  const jobs = Array.isArray(reference.page.jobs) ? reference.page.jobs : [];
  if (!truncated && jobs.length) {
    append("\nJobs\n");
    for (const [index, job] of jobs.slice(0, 50).entries()) {
      const details = [job.company, job.location, job.published || job.posting_age]
        .map(String)
        .filter(Boolean)
        .join(" · ");
      const value = `${index + 1}. ${String(job.title || "Untitled role")}\n   ${String(job.url || "")}${details ? `\n   ${details}` : ""}\n`;
      if (!append(value)) break;
    }
  }
  if (!truncated) append("\n");
  const content = String(reference.page.markdown || reference.page.text || "").trim();
  let cursor = 0;
  let currentLine = 1;
  let lastLine = 0;
  while (currentLine < lineno && cursor < content.length) {
    const separator = content.indexOf("\n", cursor);
    cursor = separator < 0 ? content.length : separator + 1;
    currentLine += 1;
  }
  while (!truncated && cursor <= content.length) {
    const separator = content.indexOf("\n", cursor);
    const end = separator < 0 ? content.length : separator;
    const complete = append(`${currentLine}: ${content.slice(cursor, end)}\n`);
    lastLine = currentLine;
    if (!complete) break;
    if (separator < 0) break;
    cursor = separator + 1;
    currentLine += 1;
  }
  return {
    text: truncated ? `${rendered.trimEnd()}${marker}` : rendered.trimEnd(),
    lineStart: lastLine ? lineno : 0,
    lineEnd: lastLine,
  };
}

'''
HARNESS = r'''
import assert from "node:assert/strict";
const guard = Bun.argv[2] === "guard";
const pages = [
  { markdown: "x".repeat(500000) },
  { markdown: "first\n" + "x".repeat(500000) + "\nlast" },
  { markdown: "\r\n  heading\r\n\r\nα😀 café\r\n last  \r\n" },
  { markdown: "", text: "fallback text" },
  { markdown: "   " },
  { markdown: "\n" },
  { markdown: "short\nnext" },
  { markdown: "😀".repeat(1000) },
  { markdown: "body", links: ["https://example.test/one", "https://example.test/" + "z".repeat(2000)] },
  { markdown: "body", jobs: [{ title: "Role", url: "https://example.test/job", company: "Org", location: "Here", published: "2026" }] },
];
let checked = 0;
for (const page of guard ? pages.slice(0, 2) : pages) {
  for (const budget of guard ? [1000] : [0, 1, 40, 63, 64, 65, 70, 80, 99, 100, 1000, 510000]) {
    for (const lineno of guard ? [1] : [1, 2, 3, 10, 100]) {
      for (const title of guard ? ["Fixture"] : ["Fixture", "T".repeat(200)]) {
        const reference = { ref_id: "fixture", title, url: "https://example.test/", page } as PageReference;
        maxBodyAppend = 0;
        const actual = renderPage(reference, lineno, budget);
        assert.deepStrictEqual(actual, legacyRenderPage(reference, lineno, budget));
        if (guard) assert.ok(maxBodyAppend <= budget + 20, `body append length ${maxBodyAppend} exceeds response budget ${budget}`);
        checked++;
      }
    }
  }
}
console.log(JSON.stringify({ checked }));
'''


class WebResearchMcpRenderBudgetTests(unittest.TestCase):
    def run_harness(self, guard):
        source = SERVER.read_text().split('\nlet inputBuffer = "";', 1)[0]
        anchor = '  const append = (value: string) => {'
        self.assertEqual(source.count(anchor), 1)
        source = source.replace(anchor, anchor + '\n    if (/^[0-9]+: /.test(value)) maxBodyAppend = Math.max(maxBodyAppend, value.length);')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / 'render.ts'
            script.write_text(source + '\nlet maxBodyAppend = 0;\n' + LEGACY_RENDER + HARNESS)
            result = subprocess.run(['bun', script, 'guard' if guard else 'equivalence'], capture_output=True, text=True,
                env={**os.environ, 'WEB_RESEARCH_DATA_DIR': str(root / 'data')})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['checked'], 2 if guard else 1200)

    def test_body_intermediate_is_bounded_by_response_budget(self):
        self.run_harness(True)

    def test_exact_legacy_output_across_budgets_offsets_and_unicode(self):
        self.run_harness(False)
