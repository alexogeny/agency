import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRAPE_HARNESS = r'''
import assert from "node:assert/strict";
const NativeDate = Date;
const fixed = "2026-10-26T00:00:00.000Z";
globalThis.Date = class extends NativeDate {
  constructor(...values) { super(...(values.length ? values : [fixed])); }
  static now() { return NativeDate.parse(fixed); }
};
const originalFuse = fusePageCapture;
let fusions = 0;
fusePageCapture = (...values) => { fusions++; return originalFuse(...values); };
withBrowser = async (options, operation) => operation({});
freshnessPolicy = () => ({changeLikelihood:"medium", basis:["fixture"], refreshAfter:null});
let currentInput;
navigateAndExtract = async () => {
  const page = originalFuse(currentInput);
  pageCaptures.set(page, currentInput);
  return page;
};
const frame = {status:"extracted", origin:"https://example.test", path:"/frame", title:"Frame", text:"Frame evidence"};
extractFrames = async () => [frame];
storedCapture = (page, browser, frames) => {
  const input = pageCaptures.get(page);
  input.frames = frames;
  const result = fusePageCapture(captureInputForStorage(input), "stored");
  result.capture_id = "fixture-capture";
  return result;
};
const output = [];
const log = console.log;
console.log = value => output.push(JSON.parse(value));
const basePage = {title:"Fixture",url:"https://example.test/page",canonicalUrl:"https://example.test/page", published:"",byline:"",text:"Repeated evidence\n\nRepeated evidence",markdown:"Repeated evidence\n\nRepeated evidence",html:"<p>evidence</p>",links:["https://example.test/other"], sources:["rendered-dom"]};
for (const capture of [false, true]) for (const frames of [false, true]) {
  currentInput = {schema:"agency/web-capture-input/1",requested_url:basePage.url,options:{max_content_chars:2000000,max_links:2000},captures:[structuredClone(basePage)], access_states:["none"],actions:[],scroll_targets:[],network:[],frames:[]};
  const expectedInput = structuredClone(currentInput);
  expectedInput.frames = frames ? [frame] : [];
  const expected = capture ? originalFuse(captureInputForStorage(expectedInput), "stored") : originalFuse(expectedInput);
  if (capture) expected.capture_id = "fixture-capture";
  expected.freshness = {retrieval:"live", cache:"bypass",change_likelihood:"medium",basis:["fixture"],retrieved_at:fixed,indexed_at:null,refresh_after:null,content_sha256:contentHash(expected)};
  fusions = 0;
  const args = [basePage.url,"--format","json"];
  if (capture) args.push("--capture");
  if (frames) args.push("--include-frames");
  await commandScrape(args);
  assert.deepStrictEqual(output.at(-1), expected);
  if (Bun.argv[2] === "guard") assert.equal(fusions, capture || frames ? 1 : 0, "only re-fuse when frames or storage sanitization change the input");
}
console.log = log;
console.log(JSON.stringify({checked:output.length}));
'''
FIND_HARNESS = r'''
import assert from "node:assert/strict";
const page = {kind:"page",ref_id:"fixture",title:"Fixture",url:"https://example.test/page",page:{markdown:"MATCH\nother\nCAFÉ"},evidence:new Set()};
loadPages = async ids => ids.map(() => page);
const NativeMap = Map;
let maps = 0;
globalThis.Map = class extends NativeMap { constructor(...values) {super(...values);maps++;} };
const result = await performFind([{ref_id:"fixture",pattern:"match"}],"transient","");
globalThis.Map = NativeMap;
assert.equal(result.records[0].matches, 1);
assert.deepStrictEqual(result.records[0].lines, [1]);
assert.equal(result.rendered[0], "[fixture] match: 1 match\n1: MATCH");
assert.equal(maps, 0, "single-pattern find must avoid grouping and citation Maps");
console.log(JSON.stringify({checked:1}));
'''


class WebHolisticTests(unittest.TestCase):
    def run_harness(self, tool, marker, body, mode):
        source = (ROOT / tool).read_text()
        self.assertEqual(source.count(marker), 1)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.ts"
            path.write_text(source.split(marker)[0] + body)
            result = subprocess.run(["bun", path, mode], text=True, capture_output=True,
                                    env={**os.environ, "WEB_RESEARCH_DATA_DIR": str(Path(temporary) / "data")})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_scrape_output_matches_final_fusion_with_and_without_frames_and_capture(self):
        self.assertEqual(self.run_harness("Tools/web-research", "\nconst args = Bun.argv.slice(2);", SCRAPE_HARNESS, "equivalence"), {"checked":4})

    def test_scrape_does_not_repeat_unchanged_capture_fusion(self):
        self.assertEqual(self.run_harness("Tools/web-research", "\nconst args = Bun.argv.slice(2);", SCRAPE_HARNESS, "guard"), {"checked":4})

    def test_single_pattern_find_does_not_allocate_grouping_maps(self):
        self.assertEqual(self.run_harness("Tools/web-research-mcp", '\nlet inputBuffer = "";', FIND_HARNESS, "guard"), {"checked":1})


    def test_status_does_not_import_command_or_capture_subsystems(self):
        script = """
import runpy
import sys
module = runpy.run_path(sys.argv[1])
sys.argv = [sys.argv[1], 'status', 'note', 'Fixture']
assert module['main']() == 0
assert 'subprocess' not in sys.modules, 'status imported subprocess'
assert 'tempfile' not in sys.modules, 'status imported tempfile'
print('status passed')
"""
        result = subprocess.run([sys.executable, "-c", script, str(ROOT / "Tools/agency-ui")],
                                capture_output=True, text=True, env={**os.environ, "AGENCY_UI":"plain"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "status passed\n")
        self.assertEqual(result.stderr, "↳ Fixture\n")


class WebCommandDiagnosticsTests(unittest.TestCase):
    def helper(self):
        module = runpy.run_path(str(ROOT / "Tests/test_web_research.py"))
        return module["WebResearchTests"]()

    def test_failed_command_keeps_exception_and_bounded_output_context(self):
        helper = self.helper()
        failure = subprocess.CalledProcessError(
            9, ["fixture"], output="stdout-head" + "x" * 5000 + "stdout-tail",
            stderr="stderr-head" + "y" * 5000 + "stderr-tail",
        )
        with patch.object(subprocess, "run", side_effect=failure):
            with self.assertRaises(subprocess.CalledProcessError) as raised:
                helper.run_tool("scrape", environment={"FIXTURE": "1"})
        self.assertIs(raised.exception, failure)
        notes = "\n".join(getattr(failure, "__notes__", []))
        self.assertIn("stdout-tail", notes)
        self.assertIn("stderr-tail", notes)
        self.assertNotIn("stdout-head", notes)
        self.assertNotIn("stderr-head", notes)
        self.assertLess(len(notes), 8500)

    def test_success_and_unchecked_failure_pass_through(self):
        helper = self.helper()
        for status, check in ((0, True), (1, False)):
            with self.subTest(status=status, check=check):
                result = subprocess.CompletedProcess(["fixture"], status, "body", "context")
                with patch.object(subprocess, "run", return_value=result) as launch:
                    actual = helper.run_tool("scrape", check=check, environment={"FIXTURE": "1"})
                self.assertIs(actual, result)
                self.assertEqual(launch.call_args.kwargs["check"], check)


if __name__ == "__main__":
    unittest.main()
