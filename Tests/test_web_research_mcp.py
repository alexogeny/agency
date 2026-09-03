import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "Tools/web-research-mcp"
SCRATCH = Path(os.environ.get("AGENCY_TEST_SCRATCH", ROOT / ".cache/tests"))


class WebResearchMcpTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.workspace = Path(self.temporary.name)
        self.backend = self.workspace / "web-research"
        self.backend_log = self.workspace / "backend.ndjson"
        self.backend.write_text(
            textwrap.dedent(
                r'''
                #!/usr/bin/env bun
                import { appendFileSync } from "node:fs";
                const args = Bun.argv.slice(2);
                if (process.env.MCP_BACKEND_LOG) {
                  appendFileSync(process.env.MCP_BACKEND_LOG, JSON.stringify(args) + "\n");
                }
                if (args[0] === "search") {
                  console.log(JSON.stringify({
                    query: args[1],
                    engine: "federated",
                    strategy: "federated",
                    scope: { domains: [], excluded_domains: [], site_qualifier: "not-present" },
                    results: [{
                      title: "Terms",
                      url: "https://example.test/terms",
                      snippet: "Termination and renewal terms",
                      sources: [{ engine: "duckduckgo", rank: 1 }],
                    }],
                    attempts: [{ engine: "duckduckgo", outcome: "searched", duration_ms: 1 }],
                  }));
                } else if (args[0] === "search-many") {
                  const request = JSON.parse(await Bun.stdin.text());
                  console.log(JSON.stringify({ results: request.searches.map(item => ({
                    query: item.query,
                    engine: "federated",
                    strategy: item.strategy,
                    scope: { domains: item.domains, excluded_domains: item.excluded, site_qualifier: "not-present" },
                    results: item.query.includes("blocked result") ? [{
                      title: "Example result",
                      url: "https://challenge-required.example/page",
                      snippet: "Search-index description",
                      score: 0.032522,
                      sources: [
                        { engine: "duckduckgo", rank: 1 },
                        { engine: "brave", rank: 2 },
                      ],
                    }] : [{ title: "Terms", url: "https://example.test/terms", snippet: item.query }],
                    attempts: [{ engine: "duckduckgo", outcome: "searched", duration_ms: 1 }],
                  })) }));
                } else if (args[0] === "scrape") {
                  const target = args[1];
                  if (target.includes("challenge-required.example")) {
                    console.error("interactive challenge required");
                    process.exit(1);
                  }
                  console.log(JSON.stringify({
                    title: target.endsWith("privacy") ? "Privacy" : "Terms",
                    url: target,
                    canonicalUrl: target,
                    published: "2026-01-30",
                    byline: "",
                    text: target.endsWith("privacy")
                      ? "Privacy policy evidence"
                      : "Heading\nRenewal continues automatically.\nTermination requires notice.\n" + "Long evidence. ".repeat(1000),
                    markdown: target.endsWith("privacy")
                      ? "# Privacy\n\nPrivacy policy evidence"
                      : "# Heading\n\nRenewal continues automatically.\n\nTermination requires notice.\n\n" + "Long evidence. ".repeat(1000),
                    html: "",
                    links: ["https://example.test/privacy"],
                    sources: ["rendered-dom"],
                    freshness: {
                      retrieval: "live",
                      cache: "miss",
                      change_likelihood: "medium",
                      basis: ["legal-or-policy-document"],
                      indexed_at: "2026-09-02T00:00:00.000Z",
                      refresh_after: "2026-09-16T00:00:00.000Z",
                      content_sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    },
                    truncated: { text: false, markdown: false, html: false, links: false },
                  }));
                } else if (args[0] === "scrape-many") {
                  const request = JSON.parse(await Bun.stdin.text());
                  if (request.urls.length > 4 || request.urls.some(target => target.includes("batch-unstable"))) {
                    console.log("{invalid batch output");
                    process.exit(0);
                  }
                  console.log(JSON.stringify({
                    pages: request.urls.map(target => target.includes("account-required") ? {
                      url: target,
                      error: {
                        kind: "access",
                        code: "interactive-login-required",
                        message: "interactive login required",
                        retriable: false,
                      },
                    } : ({
                      title: target.endsWith("privacy") ? "Privacy" : "Terms",
                      url: target,
                      canonicalUrl: target,
                      published: "",
                      byline: "",
                      text: "Batched evidence",
                      markdown: "# Batched evidence",
                      html: "",
                      links: [],
                      jobs: target.endsWith("jobs") ? [{
                        title: "Platform Engineer",
                        url: "https://example.test/roles/platform-engineer",
                        company: "Example Company",
                        location: "Remote",
                        posting_age: "2 days ago",
                        published: "2026-08-31",
                        summary: "Build reliable systems.",
                      }] : [],
                      sources: ["rendered-dom"],
                      truncated: { text: false, markdown: false, html: false, links: false },
                    })),
                  }));
                } else if (args[0] === "local") {
                  console.log(JSON.stringify({
                    query: args[1],
                    results: [{
                      title: "Indexed terms",
                      url: "https://example.test/indexed",
                      snippet: "durable evidence",
                      score: -1,
                      retrieved_at: "2026-09-02T00:00:00.000Z",
                      change_likelihood: "low",
                      refresh_after: "2027-03-01T00:00:00.000Z",
                      content_sha256: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    }],
                  }));
                } else if (args[0] === "replay") {
                  console.log(JSON.stringify({
                    title: "Replayed terms",
                    url: "https://example.test/replayed",
                    canonicalUrl: "https://example.test/replayed",
                    published: "",
                    byline: "",
                    text: "Offline captured evidence",
                    markdown: "# Replayed terms\n\nOffline captured evidence",
                    html: "",
                    links: [],
                    capture_id: args[1],
                    sources: ["rendered-dom"],
                  }));
                } else {
                  console.error("unexpected backend command: " + args.join(" "));
                  process.exit(2);
                }
                '''
            ).lstrip()
        )
        self.backend.chmod(self.backend.stat().st_mode | stat.S_IXUSR)
        self.process = subprocess.Popen(
            [SERVER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={
                **os.environ,
                "WEB_RESEARCH_COMMAND": str(self.backend),
                "WEB_RESEARCH_DATA_DIR": str(self.workspace / "data"),
                "MCP_BACKEND_LOG": str(self.backend_log),
            },
        )

    def tearDown(self):
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()
        self.process.stderr.close()
        self.temporary.cleanup()

    def request(self, method, params=None, request_id=1):
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        response = self.process.stdout.readline()
        if not response:
            self.fail(self.process.stderr.read())
        return json.loads(response)

    def call(self, arguments, request_id=2):
        return self.request(
            "tools/call",
            {"name": "run", "arguments": arguments},
            request_id,
        )["result"]

    def test_initializes_and_exposes_native_shaped_run_contract(self):
        initialized = self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "fixture", "version": "1"},
            },
        )
        listed = self.request("tools/list", request_id=2)

        self.assertEqual(initialized["result"]["serverInfo"]["name"], "agency-web")
        tool = listed["result"]["tools"][0]
        self.assertEqual(tool["name"], "run")
        properties = tool["inputSchema"]["properties"]
        self.assertIn("search_query", properties)
        self.assertIn("open", properties)
        self.assertIn("find", properties)
        self.assertIn("click", properties)
        self.assertIn("response_length", properties)
        self.assertIn("evidence", properties)
        self.assertIn("local_query", properties)
        self.assertIn("replay", properties)
        self.assertIn("outputSchema", tool)
        self.assertFalse(tool["annotations"]["readOnlyHint"])

    def test_search_open_find_and_click_use_compact_stable_references(self):
        self.request("initialize", {"protocolVersion": "2025-06-18"})
        search = self.call(
            {
                "search_query": [{"q": "example terms"}],
                "response_length": "short",
            }
        )
        search_record = search["structuredContent"]["results"][0]
        search_ref = search_record["results"][0]["ref_id"]

        opened = self.call(
            {"open": [{"ref_id": search_ref}], "response_length": "short"},
            3,
        )
        page = opened["structuredContent"]["results"][0]
        self.assertEqual(page["title"], "Terms")
        self.assertEqual(page["citation"]["source_id"], page["ref_id"])
        self.assertEqual(page["citation"]["line_start"], 1)
        self.assertGreater(page["citation"]["line_end"], 1)
        self.assertEqual(
            opened["structuredContent"]["sources"][0]["content_sha256"],
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        self.assertLess(len(opened["content"][0]["text"]), 6000)
        self.assertIn("truncated", opened["content"][0]["text"])

        found = self.call(
            {"find": [{"ref_id": page["ref_id"], "pattern": "Termination"}]},
            4,
        )
        self.assertEqual(found["structuredContent"]["results"][0]["matches"], 1)
        self.assertEqual(
            found["structuredContent"]["results"][0]["citation"]["evidence_lines"],
            [5],
        )
        self.assertIn("Termination requires notice", found["content"][0]["text"])

        clicked = self.call(
            {"click": [{"ref_id": page["ref_id"], "id": 1}]},
            5,
        )
        clicked_page = clicked["structuredContent"]["results"][0]
        self.assertEqual(clicked_page["title"], "Privacy")
        self.assertEqual(clicked_page["url"], "https://example.test/privacy")

    def test_invalid_reference_is_a_tool_error_without_stopping_server(self):
        self.request("initialize", {"protocolVersion": "2025-06-18"})
        failed = self.call({"open": [{"ref_id": "missing"}]})
        listed = self.request("tools/list", request_id=3)

        self.assertTrue(failed["isError"])
        self.assertIn("unknown source reference", failed["content"][0]["text"])
        self.assertEqual(listed["result"]["tools"][0]["name"], "run")

    def test_local_index_and_capture_replay_are_first_class_operations(self):
        self.request("initialize", {"protocolVersion": "2025-06-18"})

        local = self.call({"local_query": [{"q": "renewal"}]})
        replayed = self.call({"replay": [{"capture_id": "capture-123"}]}, 3)

        local_result = local["structuredContent"]["results"][0]["results"][0]
        replay_result = replayed["structuredContent"]["results"][0]
        self.assertEqual(local_result["url"], "https://example.test/indexed")
        self.assertTrue(local_result["ref_id"].startswith("agency_search_"))
        self.assertEqual(local_result["change_likelihood"], "low")
        self.assertEqual(replay_result["capture_id"], "capture-123")
        self.assertIn("Offline captured evidence", replayed["content"][0]["text"])

    def test_cached_transient_page_can_be_promoted_to_capture_evidence(self):
        self.request("initialize", {"protocolVersion": "2025-06-18"})
        search = self.call({"search_query": [{"q": "example terms"}]})
        search_ref = search["structuredContent"]["results"][0]["results"][0]["ref_id"]
        opened = self.call({"open": [{"ref_id": search_ref}]}, 3)
        page_ref = opened["structuredContent"]["results"][0]["ref_id"]

        self.call({"open": [{"ref_id": page_ref}], "evidence": "capture"}, 4)

        calls = [json.loads(line) for line in self.backend_log.read_text().splitlines()]
        scrapes = [call for call in calls if call[0] == "scrape"]
        self.assertEqual(len(scrapes), 2)
        self.assertIn("--preflight", scrapes[0])
        self.assertNotIn("--capture", scrapes[0])
        self.assertIn("--capture", scrapes[1])

    def test_multiple_uncached_opens_share_one_backend_browser_batch(self):
        self.request("initialize", {"protocolVersion": "2025-06-18"})

        opened = self.call(
            {
                "open": [
                    {"ref_id": "https://example.test/terms"},
                    {"ref_id": "https://example.test/privacy"},
                ]
            }
        )

        self.assertEqual(len(opened["structuredContent"]["results"]), 2)
        calls = [json.loads(line) for line in self.backend_log.read_text().splitlines()]
        self.assertEqual([call[0] for call in calls], ["scrape-many"])

    def test_large_open_is_split_into_bounded_backend_batches(self):
        self.request("initialize", {"protocolVersion": "2025-06-18"})
        urls = [f"https://example.test/page-{index}" for index in range(8)]

        opened = self.call({"open": [{"ref_id": url} for url in urls]})

        self.assertNotIn("isError", opened)
        self.assertEqual(len(opened["structuredContent"]["results"]), 8)
        calls = [json.loads(line) for line in self.backend_log.read_text().splitlines()]
        self.assertEqual([call[0] for call in calls], ["scrape-many", "scrape-many"])

    def test_invalid_batch_falls_back_to_per_page_results(self):
        self.request("initialize", {"protocolVersion": "2025-06-18"})

        opened = self.call(
            {
                "open": [
                    {"ref_id": "https://example.test/page-one"},
                    {"ref_id": "https://batch-unstable.example/page"},
                    {"ref_id": "https://challenge-required.example/page"},
                    {"ref_id": "https://example.test/page-two"},
                ]
            }
        )

        self.assertNotIn("isError", opened)
        self.assertEqual(
            [result["type"] for result in opened["structuredContent"]["results"]],
            ["page", "page", "page_error", "page"],
        )
        self.assertEqual(
            opened["structuredContent"]["results"][2]["error"]["code"],
            "interactive-challenge-required",
        )
        calls = [json.loads(line) for line in self.backend_log.read_text().splitlines()]
        self.assertEqual(
            [call[0] for call in calls],
            ["scrape-many", "scrape", "scrape", "scrape", "scrape"],
        )

    def test_open_returns_per_page_errors_and_keeps_successful_pages(self):
        self.request("initialize", {"protocolVersion": "2025-06-18"})

        opened = self.call(
            {
                "open": [
                    {"ref_id": "https://example.test/page-one"},
                    {"ref_id": "https://account-required.example/page"},
                    {"ref_id": "https://example.test/jobs"},
                ]
            }
        )

        results = opened["structuredContent"]["results"]
        self.assertEqual([result["type"] for result in results], ["page", "page_error", "page"])
        self.assertEqual(results[1]["error"]["code"], "interactive-login-required")
        self.assertEqual(results[2]["jobs"][0]["title"], "Platform Engineer")
        self.assertEqual(len(opened["structuredContent"]["sources"]), 2)

    def test_blocked_search_result_retains_a_typed_index_snapshot(self):
        self.request("initialize", {"protocolVersion": "2025-06-18"})
        searched = self.call({"search_query": [{"q": "blocked result"}]})
        search_ref = searched["structuredContent"]["results"][0]["results"][0]["ref_id"]

        opened = self.call({"open": [{"ref_id": search_ref}]}, 3)

        result = opened["structuredContent"]["results"][0]
        snapshot = result["index_snapshot"]
        self.assertEqual(result["type"], "page_error")
        self.assertEqual(result["error"]["code"], "interactive-challenge-required")
        self.assertEqual(snapshot["type"], "index_snapshot")
        self.assertFalse(snapshot["page_verified"])
        self.assertEqual(snapshot["score"], 0.032522)
        self.assertEqual(snapshot["sources"][1], {"engine": "brave", "rank": 2})
        self.assertEqual(opened["structuredContent"]["sources"], [snapshot])
        self.assertIn("not page-verified", opened["content"][0]["text"])

    def test_multiple_searches_share_one_backend_browser_batch(self):
        self.request("initialize", {"protocolVersion": "2025-06-18"})

        searched = self.call(
            {"search_query": [{"q": "first"}, {"q": "second"}]}
        )

        self.assertEqual(len(searched["structuredContent"]["results"]), 2)
        calls = [json.loads(line) for line in self.backend_log.read_text().splitlines()]
        self.assertEqual([call[0] for call in calls], ["search-many"])


if __name__ == "__main__":
    unittest.main()
