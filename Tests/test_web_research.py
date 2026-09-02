import json
import os
import sqlite3
import stat
import subprocess
import tempfile
import textwrap
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "Tools/web-research"
SCRATCH = Path(os.environ.get("AGENCY_TEST_SCRATCH", ROOT / ".cache/tests"))


class RenderedFixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"""<!doctype html>
<html>
  <head><title>Rendered fixture</title></head>
  <body>
    <main id="content"><p>Initial evidence</p></main>
    <script>
      setTimeout(() => {
        const host = document.createElement("section")
        const root = host.attachShadow({ mode: "open" })
        root.innerHTML = "<article><h1>Hydrated evidence</h1><p>Open shadow-root evidence.</p></article>"
        document.body.append(host)
      }, 25)
    </script>
  </body>
</html>
"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


@contextmanager
def rendered_fixture_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), RenderedFixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class WebResearchTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.workspace = Path(self.temporary.name)
        self.data_root = self.workspace / "web-data"

    def tearDown(self):
        self.temporary.cleanup()

    def executable(self, name, source):
        path = self.workspace / "bin" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(textwrap.dedent(source).lstrip())
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def environment(self, *, fake_firefox=True):
        environment = os.environ.copy()
        environment["WEB_RESEARCH_DATA_DIR"] = str(self.data_root)
        if fake_firefox:
            environment["PATH"] = f"{self.workspace / 'bin'}:{environment['PATH']}"
        return environment

    def run_tool(self, *arguments, check=True, environment=None):
        return subprocess.run(
            [str(TOOL), *map(str, arguments)],
            check=check,
            text=True,
            capture_output=True,
            env=environment or self.environment(),
        )

    def fake_firefox(self):
        return self.executable(
            "firefox",
            r'''
            #!/usr/bin/env bun
            import { appendFileSync } from "node:fs";

            const port = Number(Bun.argv[Bun.argv.indexOf("--remote-debugging-port") + 1]);
            if (process.env.FAKE_LAUNCH_MARKER) {
              appendFileSync(process.env.FAKE_LAUNCH_MARKER, "launch\n");
            }
            if (process.env.FAKE_PROFILE_MARKER) {
              const profile = Bun.argv[Bun.argv.indexOf("--profile") + 1];
              appendFileSync(process.env.FAKE_PROFILE_MARKER, profile + "\n");
            }
            let currentUrl = "about:blank";
            let remainingNavigationTimeouts = Number(process.env.FAKE_NAV_TIMEOUTS || "0");
            const page = () => JSON.stringify(process.env.FAKE_EMPTY_PAGE === "1" ? {
              title: "",
              url: currentUrl,
              canonicalUrl: process.env.FAKE_CANONICAL_URL || currentUrl,
              published: process.env.FAKE_PAGE_PUBLISHED || "",
              byline: "",
              text: "",
              markdown: "",
              html: "",
              links: [],
              sources: [],
              truncated: { text: false, markdown: false, html: false, links: false },
            } : {
              title: process.env.FAKE_PAGE_TITLE || "Rendered title",
              url: currentUrl,
              canonicalUrl: process.env.FAKE_CANONICAL_URL || currentUrl,
              published: process.env.FAKE_PAGE_PUBLISHED || "",
              byline: "",
              text: process.env.FAKE_PAGE_TEXT || "Repeated evidence block\n\nRepeated evidence block",
              markdown: process.env.FAKE_PAGE_TEXT || "Repeated evidence block\n\nRepeated evidence block",
              html: `<main><p>${process.env.FAKE_PAGE_TEXT || "Repeated evidence block"}</p></main>`,
              links: [],
              structured: {
                metadata: { "og:title": "Different structured title" },
                jsonLd: [],
              },
              sources: ["rendered-dom", "page-metadata"],
              truncated: { text: false, markdown: false, html: false, links: false },
            });
            Bun.serve({
              port,
              fetch(request, server) {
                if (server.upgrade(request)) return;
                return new Response("ready");
              },
              websocket: {
                message(socket, data) {
                  const request = JSON.parse(String(data));
                  let result = {};
                  if (request.method === "session.new") {
                    result = { capabilities: { browserVersion: "154.0-fixture" } };
                  } else if (request.method === "browsingContext.getTree") {
                    result = { contexts: [{ context: "fixture-context" }] };
                  } else if (request.method === "network.addDataCollector") {
                    result = { collector: "fixture-collector" };
                  } else if (request.method === "network.getData") {
                    result = {
                      bytes: {
                        type: "string",
                        value: JSON.stringify({ evidence: "network-only evidence" }),
                      },
                    };
                  } else if (request.method === "browsingContext.navigate") {
                    currentUrl = request.params.url;
                    if (remainingNavigationTimeouts > 0) {
                      remainingNavigationTimeouts -= 1;
                      if (process.env.FAKE_NETWORK_ONLY === "1") {
                        socket.send(JSON.stringify({
                          type: "event",
                          method: "network.responseCompleted",
                          params: {
                            context: "fixture-context",
                            request: {
                              request: "network-request",
                              url: currentUrl + "/api/data",
                            },
                            response: {
                              status: 200,
                              mimeType: "application/json",
                              headers: [],
                            },
                          },
                        }));
                      }
                      return;
                    }
                    const searchRateLimited = process.env.FAKE_ALL_SEARCH_RATE_LIMIT === "1" &&
                      ["html.duckduckgo.com", "search.brave.com", "www.bing.com"].includes(new URL(currentUrl).hostname);
                    if (currentUrl.includes("cool.example") || searchRateLimited) {
                      socket.send(JSON.stringify({
                        type: "event",
                        method: "network.responseCompleted",
                        params: {
                          context: "fixture-context",
                          request: { url: currentUrl },
                          response: {
                            status: 429,
                            headers: [{
                              name: "retry-after",
                              value: { type: "string", value: process.env.FAKE_RETRY_AFTER || "120" },
                            }],
                          },
                        },
                      }));
                    }
                  } else if (request.method === "script.evaluate") {
                    const expression = request.params.expression;
                    let value = page();
                    if (expression.includes("document.readyState")) {
                      const text = process.env.FAKE_EMPTY_PAGE === "1"
                        ? ""
                        : process.env.FAKE_PAGE_TEXT || "Repeated evidence block";
                      value = JSON.stringify({
                        readyState: "complete",
                        url: currentUrl,
                        title: process.env.FAKE_PAGE_TITLE || "Rendered title",
                        textLength: text.length,
                        scrollHeight: 500,
                        links: 0,
                        shadowRoots: 0,
                      });
                    } else if (expression.includes("challengeControl")) {
                      const cooling = currentUrl.includes("cool.example") ||
                        (process.env.FAKE_ALL_SEARCH_RATE_LIMIT === "1" &&
                          ["html.duckduckgo.com", "search.brave.com", "www.bing.com"].includes(new URL(currentUrl).hostname));
                      value = JSON.stringify({
                        title: cooling ? "Too Many Requests" : "Rendered title",
                        url: currentUrl,
                        text: cooling
                          ? "Rate limit exceeded. Please try again later."
                          : process.env.FAKE_EMPTY_PAGE === "1"
                            ? ""
                            : "Repeated evidence block",
                        challengeControl: false,
                        loginControl: false,
                        mainTextLength: cooling ? 0 : 48,
                        articleCount: cooling ? 0 : 1,
                        contentLinks: 0,
                        structuredDataChars: cooling ? 0 : 32,
                      });
                    } else if (expression.includes("const engine =") && process.env.FAKE_SEARCH_RESULTS_BY_ENGINE) {
                      const engine = expression.match(/const engine = "([^"]+)"/)?.[1] || "";
                      value = JSON.stringify(JSON.parse(process.env.FAKE_SEARCH_RESULTS_BY_ENGINE)[engine] || []);
                    } else if (expression.includes("const engine =") && process.env.FAKE_SEARCH_RESULTS) {
                      value = process.env.FAKE_SEARCH_RESULTS;
                    } else if (expression.includes("agencyScrollTarget")) {
                      value = JSON.stringify({ target: "document", moved: false });
                    }
                    result = { type: "success", result: { value } };
                  }
                  socket.send(JSON.stringify({ id: request.id, type: "success", result }));
                },
              },
            });
            await new Promise(() => {});
            ''',
        )

    def test_search_rejects_unknown_options_and_allows_literal_hyphen_terms(self):
        self.fake_firefox()
        environment = self.environment()
        environment["FAKE_SEARCH_RESULTS"] = json.dumps(
            [{"title": "Evidence", "url": "https://allowed.example/page", "snippet": ""}]
        )

        rejected = self.run_tool(
            "search",
            "bounded evidence",
            "--format",
            "json",
            check=False,
            environment=environment,
        )

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("unknown search option: --format", rejected.stderr)

        accepted = self.run_tool(
            "search",
            "bounded evidence",
            "--json",
            "--",
            "--literal-term",
            environment=environment,
        )
        self.assertEqual(
            json.loads(accepted.stdout)["query"],
            "bounded evidence --literal-term",
        )

    def test_search_domain_filter_is_strict_and_one_shot_profile_is_ephemeral(self):
        self.fake_firefox()
        profiles = self.workspace / "profiles"
        environment = self.environment()
        environment["FAKE_PROFILE_MARKER"] = str(profiles)
        environment["FAKE_SEARCH_RESULTS"] = json.dumps(
            [
                {
                    "title": "Off-domain result",
                    "url": "https://outside.example/page",
                    "snippet": "noise",
                },
                {
                    "title": "Allowed result",
                    "url": "https://sub.allowed.example/page",
                    "snippet": "evidence",
                },
            ]
        )

        result = self.run_tool(
            "search",
            "site:allowed.example bounded evidence",
            "--domain",
            "allowed.example",
            "--json",
            environment=environment,
        )

        report = json.loads(result.stdout)
        self.assertEqual(
            [item["url"] for item in report["results"]],
            ["https://sub.allowed.example/page"],
        )
        self.assertEqual(report["scope"]["domains"], ["allowed.example"])
        self.assertEqual(report["scope"]["site_qualifier"], "best-effort")
        profile = Path(profiles.read_text().strip())
        self.assertIn("ephemeral", profile.parts)
        self.assertFalse(profile.exists())

        queries = self.workspace / "queries.txt"
        queries.write_text("bounded evidence\n")
        output = self.workspace / "search.ndjson"
        self.run_tool(
            "search-batch",
            queries,
            "--output",
            output,
            "--engine",
            "duckduckgo",
            "--domain",
            "allowed.example",
            "--delay-ms",
            "0",
            "--jitter-ms",
            "0",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "domain-batch",
            environment=environment,
        )
        record = json.loads(output.read_text())
        self.assertEqual(
            [item["url"] for item in record["results"]],
            ["https://sub.allowed.example/page"],
        )
        self.assertEqual(record["scope"]["domains"], ["allowed.example"])

    def test_federated_search_reuses_browser_and_fuses_provider_rankings(self):
        self.fake_firefox()
        launches = self.workspace / "launches"
        environment = self.environment()
        environment["FAKE_LAUNCH_MARKER"] = str(launches)
        environment["FAKE_SEARCH_RESULTS_BY_ENGINE"] = json.dumps(
            {
                "duckduckgo": [
                    {
                        "title": "Shared from DuckDuckGo",
                        "url": "https://shared.example/evidence",
                        "snippet": "duck evidence",
                    },
                    {
                        "title": "Duck only",
                        "url": "https://duck.example/evidence",
                        "snippet": "duck only",
                    },
                ],
                "brave": [
                    {
                        "title": "Brave only",
                        "url": "https://brave.example/evidence",
                        "snippet": "brave only",
                    },
                    {
                        "title": "Shared from Brave",
                        "url": "https://shared.example/evidence",
                        "snippet": "brave evidence",
                    },
                ],
                "bing": [
                    {
                        "title": "Shared from Bing",
                        "url": "https://shared.example/evidence",
                        "snippet": "bing evidence",
                    }
                ],
            }
        )

        result = self.run_tool(
            "search",
            "federated evidence",
            "--strategy",
            "federated",
            "--limit",
            "5",
            "--json",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            environment=environment,
        )

        report = json.loads(result.stdout)
        self.assertEqual(report["engine"], "federated")
        self.assertEqual(report["strategy"], "federated")
        self.assertEqual(report["results"][0]["url"], "https://shared.example/evidence")
        self.assertEqual(
            [source["engine"] for source in report["results"][0]["sources"]],
            ["duckduckgo", "brave", "bing"],
        )
        self.assertEqual(len(report["attempts"]), 3)
        self.assertEqual(launches.read_text().splitlines(), ["launch"])

    def test_search_can_exclude_domains_without_weakening_allowed_domains(self):
        self.fake_firefox()
        environment = self.environment()
        environment["FAKE_SEARCH_RESULTS"] = json.dumps(
            [
                {
                    "title": "Excluded",
                    "url": "https://noise.allowed.example/page",
                    "snippet": "noise",
                },
                {
                    "title": "Retained",
                    "url": "https://good.allowed.example/page",
                    "snippet": "evidence",
                },
            ]
        )

        result = self.run_tool(
            "search",
            "bounded evidence",
            "--domain",
            "allowed.example",
            "--exclude-domain",
            "noise.allowed.example",
            "--json",
            environment=environment,
        )

        report = json.loads(result.stdout)
        self.assertEqual(
            [item["url"] for item in report["results"]],
            ["https://good.allowed.example/page"],
        )
        self.assertEqual(
            report["scope"]["excluded_domains"],
            ["noise.allowed.example"],
        )

    def test_navigation_timeout_returns_partial_evidence_and_can_retry(self):
        self.fake_firefox()
        environment = self.environment()
        environment["FAKE_NAV_TIMEOUTS"] = "1"

        partial = self.run_tool(
            "scrape",
            "https://partial.example/page",
            "--format",
            "json",
            "--navigation-timeout-ms",
            "1000",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "partial-navigation",
            environment=environment,
        )

        page = json.loads(partial.stdout)
        self.assertEqual(page["outcome"], "partial")
        self.assertEqual(page["constraint"], "navigation-timeout")
        self.assertEqual(page["failed_stage"], "navigation")
        self.assertIn("Repeated evidence block", page["text"])
        self.assertIn(
            "navigation-timeout",
            {observation["code"] for observation in page["quality"]},
        )

        environment["FAKE_NAV_TIMEOUTS"] = "1"
        retried = self.run_tool(
            "scrape",
            "https://partial.example/page",
            "--format",
            "json",
            "--navigation-timeout-ms",
            "1000",
            "--navigation-retries",
            "1",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "retried-navigation",
            environment=environment,
        )
        self.assertNotIn("outcome", json.loads(retried.stdout))

        urls = self.workspace / "partial-urls.txt"
        urls.write_text("https://partial.example/batch\n")
        output = self.workspace / "partial-pages.ndjson"
        environment["FAKE_NAV_TIMEOUTS"] = "1"
        batch = self.run_tool(
            "scrape-batch",
            urls,
            "--output",
            output,
            "--navigation-timeout-ms",
            "1000",
            "--delay-ms",
            "0",
            "--jitter-ms",
            "0",
            "--origin-delay-ms",
            "0",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "partial-navigation-batch",
            environment=environment,
        )
        self.assertEqual(json.loads(batch.stdout)["partial"], 1)
        record = json.loads(output.read_text())
        self.assertEqual(record["outcome"], "partial")
        self.assertEqual(record["failed_stage"], "navigation")
        health = [
            json.loads(line)
            for line in Path(f"{output}.health.ndjson").read_text().splitlines()
        ]
        self.assertEqual(health[-1]["outcome"], "partial")
        self.assertEqual(health[-1]["failed_stage"], "navigation")

        environment["FAKE_NAV_TIMEOUTS"] = "1"
        environment["FAKE_EMPTY_PAGE"] = "1"
        environment["FAKE_NETWORK_ONLY"] = "1"
        network_only = self.run_tool(
            "scrape",
            "https://partial.example/network-only",
            "--format",
            "json",
            "--capture-network-json",
            "--navigation-timeout-ms",
            "1000",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "partial-network-only",
            environment=environment,
        )
        network_page = json.loads(network_only.stdout)
        self.assertEqual(network_page["outcome"], "partial")
        self.assertEqual(network_page["network"][0]["body"]["evidence"], "network-only evidence")

    def test_batch_append_mode_verifies_the_unchanged_input_prefix(self):
        self.fake_firefox()
        urls = self.workspace / "urls.txt"
        urls.write_text("https://first.example/page\n")
        output = self.workspace / "pages.ndjson"
        environment = self.environment()

        self.run_tool(
            "scrape-batch",
            urls,
            "--output",
            output,
            "--delay-ms",
            "0",
            "--jitter-ms",
            "0",
            "--origin-delay-ms",
            "0",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "append-input",
            environment=environment,
        )
        urls.write_text(urls.read_text() + "https://second.example/page\n")

        rejected = self.run_tool(
            "scrape-batch",
            urls,
            "--output",
            output,
            "--resume",
            "--profile",
            "append-input",
            check=False,
            environment=environment,
        )
        self.assertIn("input fingerprint changed", rejected.stderr)
        self.assertIn("--append-input", rejected.stderr)

        resumed = self.run_tool(
            "scrape-batch",
            urls,
            "--output",
            output,
            "--resume",
            "--append-input",
            "--delay-ms",
            "0",
            "--jitter-ms",
            "0",
            "--origin-delay-ms",
            "0",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "append-input",
            environment=environment,
        )
        self.assertEqual(json.loads(resumed.stdout)["completed"], 1)
        self.assertEqual(len(output.read_text().splitlines()), 2)

        urls.write_text(
            "https://changed.example/page\n"
            "https://second.example/page\n"
            "https://third.example/page\n"
        )
        changed_prefix = self.run_tool(
            "scrape-batch",
            urls,
            "--output",
            output,
            "--resume",
            "--append-input",
            "--profile",
            "append-input",
            check=False,
            environment=environment,
        )
        self.assertIn("unchanged byte prefix", changed_prefix.stderr)

    def test_quality_flags_thin_and_title_mismatched_content_with_recovery(self):
        self.fake_firefox()
        environment = self.environment()
        environment["FAKE_PAGE_TITLE"] = "Requested Alpha Policy"
        environment["FAKE_PAGE_TEXT"] = (
            "Unrelated commerce card describing seasonal products and storefront offers. "
            "This body has no matching subject terms."
        )

        result = self.run_tool(
            "scrape",
            "https://quality.example/page",
            "--format",
            "json",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "quality-signals",
            environment=environment,
        )

        observations = {
            item["code"]: item for item in json.loads(result.stdout)["quality"]
        }
        self.assertIn("thin-content", observations)
        self.assertIn("title-body-mismatch", observations)
        self.assertIn("--interaction-steps", observations["thin-content"]["recommendation"])
        self.assertIn(
            "--capture-network-json",
            observations["title-body-mismatch"]["recommendation"],
        )

    def test_capture_format_error_includes_a_corrected_command(self):
        result = self.run_tool(
            "scrape",
            "https://capture.example/page",
            "--format",
            "markdown",
            "--capture",
            check=False,
        )

        self.assertIn("web-research scrape URL --format json --capture", result.stderr)

    def test_origin_health_survives_resume_without_launching_firefox(self):
        self.fake_firefox()
        launches = self.workspace / "launches"
        urls = self.workspace / "urls.txt"
        urls.write_text(
            "https://cool.example/one\n"
            "https://good.example/page\n"
            "https://cool.example/two\n"
        )
        output = self.workspace / "pages.ndjson"
        environment = self.environment()
        environment["FAKE_LAUNCH_MARKER"] = str(launches)
        environment["FAKE_RETRY_AFTER"] = "120"

        first = self.run_tool(
            "scrape-batch",
            urls,
            "--output",
            output,
            "--delay-ms",
            "0",
            "--jitter-ms",
            "0",
            "--origin-delay-ms",
            "0",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "health-fixture",
            check=False,
            environment=environment,
        )

        self.assertEqual(json.loads(first.stdout)["deferred"], 1)
        health = Path(f"{output}.health.ndjson")
        records = [json.loads(line) for line in health.read_text().splitlines()]
        self.assertEqual(records[0]["schema"], "agency/web-health-run/1")
        self.assertEqual(records[0]["profile"], "health-fixture")
        self.assertTrue(
            any(
                record.get("key") == "https://cool.example"
                and record.get("outcome") == "rate-limited"
                and record.get("cooldown_until")
                and record.get("retry_after_seconds") == 120
                for record in records
            )
        )
        self.assertEqual(launches.read_text().splitlines(), ["launch"])

        resumed = self.run_tool(
            "scrape-batch",
            urls,
            "--output",
            output,
            "--resume",
            "--delay-ms",
            "0",
            "--jitter-ms",
            "0",
            "--origin-delay-ms",
            "0",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "health-fixture",
            environment=environment,
        )

        self.assertEqual(json.loads(resumed.stdout)["deferred"], 1)
        self.assertEqual(launches.read_text().splitlines(), ["launch"])

    def test_provider_health_survives_search_resume(self):
        self.fake_firefox()
        launches = self.workspace / "launches"
        queries = self.workspace / "queries.txt"
        queries.write_text("bounded research query\n")
        output = self.workspace / "search.ndjson"
        environment = self.environment()
        environment["FAKE_LAUNCH_MARKER"] = str(launches)
        environment["FAKE_ALL_SEARCH_RATE_LIMIT"] = "1"

        first = self.run_tool(
            "search-batch",
            queries,
            "--output",
            output,
            "--delay-ms",
            "0",
            "--jitter-ms",
            "0",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "provider-health",
            check=False,
            environment=environment,
        )

        self.assertNotEqual(first.returncode, 0)
        health = Path(f"{output}.health.ndjson")
        records = [json.loads(line) for line in health.read_text().splitlines()]
        self.assertEqual(
            {record["key"] for record in records[1:]},
            {"duckduckgo", "brave", "bing"},
        )
        self.assertTrue(
            all(record["outcome"] == "rate-limited" for record in records[1:])
        )
        self.assertEqual(launches.read_text().splitlines(), ["launch"])

        resumed = self.run_tool(
            "search-batch",
            queries,
            "--output",
            output,
            "--resume",
            "--retry-failures",
            "--profile",
            "provider-health",
            environment=environment,
        )

        report = json.loads(resumed.stdout)
        self.assertEqual(report["deferred"], 1)
        self.assertTrue(report["stopped"])
        self.assertEqual(launches.read_text().splitlines(), ["launch"])

    def test_future_health_schema_is_refused_before_browser_launch(self):
        self.fake_firefox()
        launches = self.workspace / "launches"
        urls = self.workspace / "urls.txt"
        urls.write_text("https://good.example/page\n")
        output = self.workspace / "pages.ndjson"
        output.write_text("")
        Path(f"{output}.health.ndjson").write_text(
            json.dumps(
                {
                    "schema": "agency/web-health-run/2",
                    "command": "scrape-batch",
                    "profile": "health-fixture",
                    "input_sha256": "future",
                }
            )
            + "\n"
        )
        environment = self.environment()
        environment["FAKE_LAUNCH_MARKER"] = str(launches)

        result = self.run_tool(
            "scrape-batch",
            urls,
            "--output",
            output,
            "--resume",
            "--profile",
            "health-fixture",
            check=False,
            environment=environment,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported health checkpoint schema", result.stderr)
        self.assertFalse(launches.exists())

    def test_capture_replay_deduplicates_and_reports_provenance_quality(self):
        self.fake_firefox()
        launches = self.workspace / "launches"
        environment = self.environment()
        environment["FAKE_LAUNCH_MARKER"] = str(launches)

        captures = []
        for _ in range(2):
            result = self.run_tool(
                "scrape",
                "https://evidence.example/page?token=secret&view=full",
                "--format",
                "json",
                "--capture",
                "--scroll-steps",
                "1",
                "--wait-ms",
                "0",
                "--settle-ms",
                "0",
                "--profile",
                "capture-fixture",
                environment=environment,
            )
            page = json.loads(result.stdout)
            captures.append(page["capture_id"])
            self.assertNotIn("secret", result.stdout)
            self.assertTrue(page["provenance"]["text"])
            codes = {observation["code"] for observation in page["quality"]}
            self.assertIn("repeated-blocks", codes)
            self.assertIn("title-disagreement", codes)

        objects = list((self.data_root / "captures/objects").glob("*.json"))
        manifests = list((self.data_root / "captures/manifests").glob("*.json"))
        self.assertEqual(len(objects), 1)
        self.assertEqual(len(manifests), 2)
        self.assertNotIn("secret", objects[0].read_text())

        replayed = self.run_tool(
            "replay", captures[0], "--json", environment=environment
        )
        replay = json.loads(replayed.stdout)
        self.assertEqual(replay["capture_id"], captures[0])
        self.assertEqual(replay["text"], page["text"])
        self.assertEqual(launches.read_text().splitlines(), ["launch", "launch"])

        preview = json.loads(
            self.run_tool(
                "capture-gc",
                "--max-manifests",
                "1",
                "--json",
                environment=environment,
            ).stdout
        )
        self.assertFalse(preview["applied"])
        self.assertEqual(len(preview["removed_manifests"]), 1)
        self.assertEqual(len(list((self.data_root / "captures/manifests").glob("*.json"))), 2)

        applied = json.loads(
            self.run_tool(
                "capture-gc",
                "--max-manifests",
                "1",
                "--apply",
                "--json",
                environment=environment,
            ).stdout
        )
        removed_id = applied["removed_manifests"][0]
        remaining_id = next(capture for capture in captures if capture != removed_id)
        self.assertEqual(len(list((self.data_root / "captures/manifests").glob("*.json"))), 1)
        self.assertEqual(len(list((self.data_root / "captures/objects").glob("*.json"))), 1)
        missing = self.run_tool(
            "replay", removed_id, "--json", check=False, environment=environment
        )
        self.assertIn("capture manifest not found", missing.stderr)

        objects[0].write_text("{}\n")
        corrupt = self.run_tool(
            "replay", remaining_id, "--json", check=False, environment=environment
        )
        self.assertNotEqual(corrupt.returncode, 0)
        self.assertIn("capture object hash mismatch", corrupt.stderr)
        self.assertEqual(launches.read_text().splitlines(), ["launch", "launch"])

    def test_preflight_reuses_fresh_text_and_refreshes_expired_dynamic_page(self):
        self.fake_firefox()
        launches = self.workspace / "launches"
        environment = self.environment()
        environment["FAKE_LAUNCH_MARKER"] = str(launches)
        environment["FAKE_PAGE_TITLE"] = "Current Terms and Conditions"
        environment["FAKE_PAGE_TEXT"] = "Version one terms"
        arguments = (
            "scrape",
            "https://dynamic.example/terms",
            "--format",
            "json",
            "--preflight",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "preflight-dynamic",
        )

        first = json.loads(self.run_tool(*arguments, environment=environment).stdout)
        environment["FAKE_PAGE_TEXT"] = "Version two terms"
        second = json.loads(self.run_tool(*arguments, environment=environment).stdout)

        self.assertEqual(first["freshness"]["cache"], "miss")
        self.assertTrue(second["text"].startswith("Version one terms"))
        self.assertNotIn("Version two terms", second["text"])
        self.assertEqual(second["freshness"]["retrieval"], "local-index")
        self.assertEqual(second["freshness"]["change_likelihood"], "medium")
        self.assertEqual(launches.read_text().splitlines(), ["launch"])

        with sqlite3.connect(self.data_root / "index.sqlite") as connection:
            connection.execute(
                "UPDATE pages SET refresh_after = ? WHERE url = ?",
                ("2000-01-01T00:00:00.000Z", "https://dynamic.example/terms"),
            )

        refreshed = json.loads(self.run_tool(*arguments, environment=environment).stdout)

        self.assertTrue(refreshed["text"].startswith("Version two terms"))
        self.assertEqual(refreshed["freshness"]["retrieval"], "live")
        self.assertEqual(refreshed["freshness"]["cache"], "stale")
        self.assertTrue(refreshed["freshness"]["changed"])
        self.assertEqual(launches.read_text().splitlines(), ["launch", "launch"])

    def test_local_search_exposes_index_freshness_metadata(self):
        self.fake_firefox()
        environment = self.environment()
        environment["FAKE_PAGE_TITLE"] = "Current Terms and Conditions"
        environment["FAKE_PAGE_TEXT"] = "Renewal terms evidence"

        self.run_tool(
            "scrape",
            "https://dynamic.example/terms",
            "--format",
            "json",
            "--index",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "local-freshness",
            environment=environment,
        )
        result = json.loads(
            self.run_tool("local", "renewal", "--json", environment=environment).stdout
        )["results"][0]

        self.assertEqual(result["change_likelihood"], "medium")
        self.assertIsNotNone(result["refresh_after"])
        self.assertRegex(result["content_sha256"], r"^[0-9a-f]{64}$")

    def test_preflight_keeps_old_published_article_immutable(self):
        self.fake_firefox()
        launches = self.workspace / "launches"
        environment = self.environment()
        environment["FAKE_LAUNCH_MARKER"] = str(launches)
        environment["FAKE_PAGE_TITLE"] = "A 2003 research article"
        environment["FAKE_PAGE_PUBLISHED"] = "2003-05-14"
        environment["FAKE_PAGE_TEXT"] = "Original historical article"
        arguments = (
            "scrape",
            "https://archive.example/2003/article",
            "--format",
            "json",
            "--preflight",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "preflight-immutable",
        )

        first = json.loads(self.run_tool(*arguments, environment=environment).stdout)
        environment["FAKE_PAGE_TEXT"] = "Unexpected replacement"
        second = json.loads(self.run_tool(*arguments, environment=environment).stdout)

        self.assertEqual(first["freshness"]["change_likelihood"], "immutable")
        self.assertIsNone(first["freshness"]["refresh_after"])
        self.assertTrue(second["text"].startswith("Original historical article"))
        self.assertNotIn("Unexpected replacement", second["text"])
        self.assertEqual(second["freshness"]["retrieval"], "local-index")
        self.assertEqual(second["freshness"]["cache"], "immutable")
        self.assertEqual(launches.read_text().splitlines(), ["launch"])

    def test_preflight_resolves_requested_url_through_canonical_alias(self):
        self.fake_firefox()
        launches = self.workspace / "launches"
        environment = self.environment()
        environment["FAKE_LAUNCH_MARKER"] = str(launches)
        environment["FAKE_CANONICAL_URL"] = "https://canonical.example/article"
        environment["FAKE_PAGE_TEXT"] = "Canonical text"
        arguments = (
            "scrape",
            "https://alias.example/story",
            "--format",
            "json",
            "--preflight",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "preflight-alias",
        )

        self.run_tool(*arguments, environment=environment)
        cached = json.loads(self.run_tool(*arguments, environment=environment).stdout)

        self.assertEqual(cached["canonicalUrl"], "https://canonical.example/article")
        self.assertEqual(cached["freshness"]["retrieval"], "local-index")
        self.assertEqual(launches.read_text().splitlines(), ["launch"])

    def test_preflight_never_indexes_sensitive_alias_parameters(self):
        self.fake_firefox()
        environment = self.environment()

        self.run_tool(
            "scrape",
            "https://evidence.example/page?token=secret&view=full",
            "--format",
            "json",
            "--preflight",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "preflight-redaction",
            environment=environment,
        )

        with sqlite3.connect(self.data_root / "index.sqlite") as connection:
            aliases = [row[0] for row in connection.execute("SELECT request_url FROM page_aliases")]

        self.assertTrue(aliases)
        self.assertNotIn("secret", json.dumps(aliases))
        self.assertTrue(any("view=full" in alias for alias in aliases))

    def test_existing_index_schema_migrates_without_losing_pages(self):
        self.data_root.mkdir(parents=True)
        with sqlite3.connect(self.data_root / "index.sqlite") as connection:
            connection.execute(
                "CREATE TABLE pages (url TEXT PRIMARY KEY, title TEXT NOT NULL, text TEXT NOT NULL, markdown TEXT NOT NULL, fetched_at TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO pages VALUES (?, ?, ?, ?, ?)",
                (
                    "https://legacy.example/page",
                    "Legacy page",
                    "retained text",
                    "retained text",
                    "2025-01-01T00:00:00.000Z",
                ),
            )

        stats = json.loads(self.run_tool("stats", environment=self.environment()).stdout)
        with sqlite3.connect(self.data_root / "index.sqlite") as connection:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(pages)")
            }
            retained = connection.execute(
                "SELECT text FROM pages WHERE url = ?",
                ("https://legacy.example/page",),
            ).fetchone()[0]

        self.assertEqual(stats["pages"], 1)
        self.assertEqual(retained, "retained text")
        self.assertIn("change_likelihood", columns)
        self.assertIn("refresh_after", columns)
        self.assertIn("content_sha256", columns)

    def test_real_firefox_extracts_hydrated_open_shadow_root(self):
        environment = self.environment(fake_firefox=False)
        with rendered_fixture_server() as url:
            result = self.run_tool(
                "scrape",
                url,
                "--format",
                "json",
                "--wait-ms",
                "50",
                "--settle-ms",
                "500",
                "--profile",
                "rendered-regression-fixture",
                environment=environment,
            )

        page = json.loads(result.stdout)
        self.assertIn("Hydrated evidence", page["text"])
        self.assertIn("Open shadow-root evidence", page["text"])


if __name__ == "__main__":
    unittest.main()
