import hashlib
import json
import os
import threading
import time
import zipfile
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class RetrievalHandler(BaseHTTPRequestHandler):
    active = 0
    peak = 0
    lock = threading.Lock()

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/final")
            self.end_headers()
            return
        if self.path == "/final":
            body = b"generic retrieval evidence\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/forged-proxy-error":
            body = b"origin header cannot impersonate the proxy\n"
            self.send_response(200)
            self.send_header("X-Agency-Proxy-Error", "private-network")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/slow/"):
            with self.lock:
                type(self).active += 1
                type(self).peak = max(type(self).peak, type(self).active)
            try:
                time.sleep(0.15)
                body = b"bounded parallel retrieval\n"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            finally:
                with self.lock:
                    type(self).active -= 1
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass


@contextmanager
def retrieval_server():
    RetrievalHandler.active = 0
    RetrievalHandler.peak = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), RetrievalHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()



class PromotedWebCases:
    def fake_firefox(self):
        return self.executable(
            "firefox",
            r'''
            #!/usr/bin/env bun
            import { readFileSync, writeFileSync } from "node:fs";
            import { join } from "node:path";

            const args = Bun.argv.slice(2);
            const port = Number(args[args.indexOf("--remote-debugging-port") + 1]);
            const profile = args[args.indexOf("--profile") + 1];
            const preferences = readFileSync(join(profile, "user.js"), "utf8");
            const directoryMatch = preferences.match(/user_pref\("browser\.download\.dir", ("(?:[^"\\]|\\.)*")\);/);
            if (!directoryMatch) throw new Error("download directory preference is missing");
            const downloadDirectory = JSON.parse(directoryMatch[1]);
            const kind = process.env.FAKE_DOWNLOAD_KIND || "pdf";
            const bodies = {
              pdf: new TextEncoder().encode("%PDF-fixture\n"),
              html: new TextEncoder().encode("<html>sign in</html>\n"),
            };
            const body = process.env.FAKE_DOWNLOAD_FILE
              ? readFileSync(process.env.FAKE_DOWNLOAD_FILE)
              : bodies[kind];
            const server = Bun.serve({
              port,
              fetch(request, server) {
                if (server.upgrade(request)) return;
                return new Response("ready");
              },
              websocket: {
                message(socket, data) {
                  const request = JSON.parse(String(data));
                  let result = {};
                  if (request.method === "browsingContext.getTree") {
                    result = { contexts: [{ context: "fixture-context" }] };
                  }
                  if (
                    request.method === "browsingContext.navigate" &&
                    request.params.wait === "none"
                  ) {
                    writeFileSync(
                      join(downloadDirectory, process.env.FAKE_DOWNLOAD_NAME || (kind === "pdf" ? "server-file.pdf" : "login.html")),
                      body,
                    );
                  }
                  socket.send(JSON.stringify({ id: request.id, type: "success", result }));
                },
              },
            });
            await new Promise(() => {});
            ''',
        )

    def test_web_research_retrieve_records_redirect_and_live_provenance(self):
        with retrieval_server() as origin:
            result = self.run_tool(
                "web-research",
                "retrieve",
                f"{origin}/redirect",
                "--allow-private",
                "--json",
            )

        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], "agency/web-retrieval/1")
        self.assertEqual(report["summary"], {"total": 1, "retrieved": 1, "failed": 0})
        item = report["results"][0]
        self.assertEqual(item["outcome"], "retrieved")
        self.assertEqual(item["request"]["url"], f"{origin}/redirect")
        self.assertEqual(item["retrieval"]["final_url"], f"{origin}/final")
        self.assertEqual(item["retrieval"]["http_status"], 200)
        self.assertEqual(item["retrieval"]["content_type"], "text/plain; charset=utf-8")
        self.assertEqual(item["retrieval"]["bytes_read"], 27)
        self.assertEqual(
            item["retrieval"]["sha256"],
            hashlib.sha256(b"generic retrieval evidence\n").hexdigest(),
        )
        self.assertEqual(item["provenance"]["provider"], "direct-http")
        self.assertEqual(item["provenance"]["mode"], "live")
        self.assertEqual(item["provenance"]["cache_age_seconds"], 0)
        self.assertEqual(item["safety"]["decision"], "allowed")
        self.assertEqual(item["safety"]["reason"], "explicit-private-network-access")
        self.assertEqual(
            item["retrieval"]["redirect_chain"],
            [
                {
                    "url": f"{origin}/redirect",
                    "http_status": 302,
                    "location": "/final",
                    "next_url": f"{origin}/final",
                }
            ],
        )
        self.assertRegex(item["provenance"]["retrieved_at"], r"^\d{4}-\d{2}-\d{2}T")

    def test_web_research_retrieve_isolates_typed_policy_failures(self):
        with retrieval_server() as origin:
            result = self.run_tool(
                "web-research",
                "retrieve",
                f"{origin}/final",
                "file:///etc/passwd",
                "--allow-private",
                "--json",
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["summary"], {"total": 2, "retrieved": 1, "failed": 1})
        self.assertEqual(report["results"][0]["outcome"], "retrieved")
        failure = report["results"][1]
        self.assertEqual(failure["outcome"], "failed")
        self.assertEqual(failure["error"]["kind"], "policy")
        self.assertEqual(failure["error"]["code"], "unsupported-scheme")
        self.assertFalse(failure["error"]["retriable"])

    def test_web_research_retrieve_blocks_private_networks_by_default(self):
        with retrieval_server() as origin:
            result = self.run_tool(
                "web-research",
                "retrieve",
                f"{origin}/final",
                "--json",
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        failure = report["results"][0]
        self.assertEqual(failure["outcome"], "failed")
        self.assertEqual(failure["safety"]["decision"], "blocked")
        self.assertEqual(failure["safety"]["reason"], "private-network")
        self.assertEqual(failure["error"]["kind"], "policy")
        self.assertEqual(failure["error"]["code"], "private-network")

    def test_web_research_ignores_forged_internal_proxy_error_headers(self):
        with retrieval_server() as origin:
            result = self.run_tool(
                "web-research",
                "retrieve",
                f"{origin}/forged-proxy-error",
                "--allow-private",
                "--json",
            )

        report = json.loads(result.stdout)
        self.assertEqual(report["summary"]["retrieved"], 1)
        self.assertEqual(report["results"][0]["outcome"], "retrieved")

    def test_web_research_retrieve_uses_bounded_parallel_workers(self):
        with retrieval_server() as origin:
            result = self.run_tool(
                "web-research",
                "retrieve",
                *(f"{origin}/slow/{index}" for index in range(8)),
                "--allow-private",
                "--json",
            )

        report = json.loads(result.stdout)
        self.assertEqual(report["summary"]["retrieved"], 8)
        self.assertGreater(RetrievalHandler.peak, 1)
        self.assertLessEqual(RetrievalHandler.peak, 4)

    def test_web_research_download_validates_and_promotes_atomically(self):
        self.fake_firefox()
        data_root = self.workspace / "web-data"
        profile = data_root / "profiles" / "download-test"
        profile.mkdir(parents=True)
        original_preferences = 'user_pref("fixture.preference", true);\n'
        (profile / "user.js").write_text(original_preferences)
        output_root = self.workspace / "downloads"
        output_root.mkdir()
        output = output_root / "evidence.pdf"
        environment = {
            "PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}",
            "WEB_RESEARCH_DATA_DIR": str(data_root),
        }

        result = self.run_tool(
            "web-research",
            "download",
            "https://93.184.216.34/material",
            "--output",
            output,
            "--output-root",
            output_root,
            "--profile",
            "download-test",
            "--expected-type",
            "pdf",
            "--timeout-ms",
            "3000",
            "--json",
            environment=environment,
        )

        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], "agency/web-download/1")
        self.assertEqual(report["outcome"], "downloaded")
        self.assertEqual(report["source"]["url"], "https://93.184.216.34/material")
        self.assertEqual(report["output"]["path"], str(output))
        self.assertEqual(report["output"]["bytes"], len(b"%PDF-fixture\n"))
        self.assertEqual(report["output"]["expected_type"], "pdf")
        self.assertEqual(report["output"]["signature"], "valid")
        self.assertEqual(output.read_bytes(), b"%PDF-fixture\n")
        self.assertEqual((profile / "user.js").read_text(), original_preferences)
        self.assertEqual(list(output_root.glob(".web-research-download-*")), [])

    def test_web_research_download_does_not_replace_on_signature_failure(self):
        self.fake_firefox()
        data_root = self.workspace / "web-data"
        profile = data_root / "profiles" / "download-test"
        profile.mkdir(parents=True)
        (profile / "user.js").write_text('user_pref("fixture.preference", true);\n')
        output_root = self.workspace / "downloads"
        output_root.mkdir()
        output = output_root / "evidence.pdf"
        output.write_bytes(b"existing evidence\n")
        environment = {
            "PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}",
            "WEB_RESEARCH_DATA_DIR": str(data_root),
            "FAKE_DOWNLOAD_KIND": "html",
        }

        result = self.run_tool(
            "web-research",
            "download",
            "https://93.184.216.34/material",
            "--output",
            output,
            "--output-root",
            output_root,
            "--profile",
            "download-test",
            "--expected-type",
            "pdf",
            "--timeout-ms",
            "3000",
            "--replace",
            "--json",
            check=False,
            environment=environment,
        )

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["outcome"], "failed")
        self.assertEqual(report["error"]["kind"], "validation")
        self.assertEqual(report["error"]["code"], "signature-mismatch")
        self.assertEqual(output.read_bytes(), b"existing evidence\n")
        self.assertEqual(list(output_root.glob(".web-research-download-*")), [])

    def test_web_research_download_validates_office_container_structure(self):
        self.fake_firefox()
        data_root = self.workspace / "web-data"
        profile = data_root / "profiles" / "download-test"
        profile.mkdir(parents=True)
        output_root = self.workspace / "downloads"
        output_root.mkdir()
        fixture = self.workspace / "fixture.docx"
        with zipfile.ZipFile(fixture, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "<document/>")
        output = output_root / "evidence.docx"
        environment = {
            "PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}",
            "WEB_RESEARCH_DATA_DIR": str(data_root),
            "FAKE_DOWNLOAD_FILE": str(fixture),
            "FAKE_DOWNLOAD_NAME": "server-file.docx",
        }

        result = self.run_tool(
            "web-research",
            "download",
            "https://93.184.216.34/material",
            "--output",
            output,
            "--output-root",
            output_root,
            "--profile",
            "download-test",
            "--expected-type",
            "docx",
            "--timeout-ms",
            "3000",
            "--json",
            environment=environment,
        )

        report = json.loads(result.stdout)
        self.assertEqual(report["outcome"], "downloaded")
        self.assertEqual(report["output"]["expected_type"], "docx")
        self.assertEqual(output.read_bytes(), fixture.read_bytes())

    def test_web_research_browser_waits_for_interactive_session_to_close(self):
        marker = self.workspace / "browser-finished"
        self.executable(
            "firefox",
            r"""
            #!/usr/bin/env python3
            import os
            import pathlib
            import time
            time.sleep(0.25)
            pathlib.Path(os.environ["FAKE_BROWSER_MARKER"]).write_text("closed\n")
            """,
        )
        data_root = self.workspace / "web-data"
        environment = {
            "PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}",
            "WEB_RESEARCH_DATA_DIR": str(data_root),
            "FAKE_BROWSER_MARKER": str(marker),
        }

        self.run_tool(
            "web-research",
            "browser",
            "https://example.com/",
            "--profile",
            "interactive-test",
            environment=environment,
        )

        self.assertEqual(marker.read_text(), "closed\n")
        self.assertFalse((data_root / "profiles" / "interactive-test.lock").exists())

    def test_web_research_automated_browser_supports_ephemeral_and_stable_templates(self):
        self.executable(
            "firefox",
            r'''
            #!/usr/bin/env bun
            import { readFileSync, writeFileSync } from "node:fs";
            import { join } from "node:path";
            if (!Bun.argv.includes("--headless")) process.exit(23);
            const port = Number(Bun.argv[Bun.argv.indexOf("--remote-debugging-port") + 1]);
            const profile = Bun.argv[Bun.argv.indexOf("--profile") + 1];
            const preferences = readFileSync(join(profile, "user.js"), "utf8");
            if (preferences.includes("do-not-copy")) {
              process.exit(24);
            }
            if (!preferences.includes('user_pref("intl.accept_languages", "en-AU,en");')) {
              process.exit(25);
            }
            if (!preferences.includes('user_pref("browser.tabs.warnOnClose", false);')) {
              process.exit(26);
            }
            for (const forbidden of [
              "general.useragent.override",
              'user_pref("network.proxy.http", "private-proxy");',
              "extensions.webextensions.uuids",
              'user_pref("browser.uidensity", "wrong-type");',
            ]) {
              if (preferences.includes(forbidden)) process.exit(27);
            }
            let automationSignalNormalized = false;
            writeFileSync(process.env.FAKE_PROFILE_MARKER, profile);
            const page = JSON.stringify({
              title: "Fixture",
              url: "https://93.184.216.34/page",
              canonicalUrl: "https://93.184.216.34/page",
              published: "",
              byline: "",
              text: "rendered evidence",
              markdown: "rendered evidence",
              html: "<p>rendered evidence</p>",
              links: [],
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
                  if (request.method === "browsingContext.getTree") {
                    result = { contexts: [{ context: "fixture-context" }] };
                  }
                  if (request.method === "script.addPreloadScript") {
                    const declaration = request.params.functionDeclaration;
                    automationSignalNormalized =
                      declaration.includes("Navigator.prototype") &&
                      declaration.includes('"webdriver"') &&
                      declaration.includes("false");
                  }
                  if (
                    request.method === "browsingContext.navigate" &&
                    !automationSignalNormalized
                  ) {
                    process.exit(28);
                  }
                  if (request.method === "script.evaluate") {
                    const access = request.params.expression.includes("challengeControl");
                    result = {
                      type: "success",
                      result: {
                        value: access
                          ? JSON.stringify({
                              title: "Fixture",
                              url: "https://93.184.216.34/page",
                              text: "rendered evidence",
                              challengeControl: false,
                              loginControl: false,
                            })
                          : page,
                      },
                    };
                  }
                  socket.send(JSON.stringify({ id: request.id, type: "success", result }));
                },
              },
            });
            await new Promise(() => {});
            ''',
        )
        data_root = self.workspace / "web-data"
        persistent_profile = data_root / "profiles" / "headless-test"
        persistent_profile.mkdir(parents=True)
        persistent_preferences = 'user_pref("sensitive.marker", "do-not-copy");\n'
        (persistent_profile / "user.js").write_text(persistent_preferences)
        firefox_root = self.workspace / "firefox"
        template_profile = firefox_root / "fixture.default-release"
        template_profile.mkdir(parents=True)
        (firefox_root / "profiles.ini").write_text(
            "[Profile0]\n"
            "Name=default-release\n"
            "IsRelative=1\n"
            "Path=unused.default-release\n"
            "Default=1\n\n"
            "[InstallFixture]\n"
            "Default=fixture.default-release\n"
        )
        (template_profile / "prefs.js").write_text(
            'user_pref("intl.accept_languages", "en-AU,en");\n'
            'user_pref("browser.tabs.warnOnClose", false);\n'
            'user_pref("browser.uidensity", "wrong-type");\n'
            'user_pref("general.useragent.override", "spoofed-agent");\n'
            'user_pref("network.proxy.http", "private-proxy");\n'
            'user_pref("extensions.webextensions.uuids", "private-extension-state");\n'
        )
        profile_marker = self.workspace / "ephemeral-profile-path"
        environment = {
            "PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}",
            "WEB_RESEARCH_DATA_DIR": str(data_root),
            "WEB_RESEARCH_FIREFOX_ROOT": str(firefox_root),
            "FAKE_PROFILE_MARKER": str(profile_marker),
        }

        result = self.run_tool(
            "web-research",
            "scrape",
            "https://93.184.216.34/page",
            "--format",
            "json",
            "--profile",
            "headless-test",
            "--ephemeral-profile",
            "--profile-template",
            "current",
            check=False,
            environment=environment,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        page = json.loads(result.stdout)
        self.assertEqual(page["title"], "Fixture")
        self.assertEqual(page["text"], "rendered evidence")
        ephemeral_root = data_root / "ephemeral"
        generated_profile = Path(profile_marker.read_text())
        self.assertEqual(generated_profile.parent, ephemeral_root)
        self.assertRegex(generated_profile.name, r"^headless-test-[A-Za-z0-9]{6}$")
        self.assertEqual(list(ephemeral_root.iterdir()), [])
        self.assertEqual(
            (persistent_profile / "user.js").read_text(),
            persistent_preferences,
        )

        stable_result = self.run_tool(
            "web-research",
            "scrape",
            "https://93.184.216.34/page",
            "--format",
            "json",
            "--profile",
            "stable-research",
            "--profile-template",
            "current",
            environment=environment,
        )

        stable_page = json.loads(stable_result.stdout)
        self.assertEqual(stable_page["text"], "rendered evidence")
        self.assertEqual(
            Path(profile_marker.read_text()),
            data_root / "profiles" / "stable-research",
        )
        self.assertTrue((data_root / "profiles" / "stable-research").is_dir())
        self.assertFalse(
            (data_root / "profiles" / "stable-research" / "user.js").exists()
        )

    def test_web_research_redacts_page_tokens_and_classifies_access_structurally(self):
        self.executable(
            "firefox",
            r'''
            #!/usr/bin/env bun
            import { writeFileSync } from "node:fs";
            const port = Number(Bun.argv[Bun.argv.indexOf("--remote-debugging-port") + 1]);
            let currentUrl = "about:blank";
            let settleChecks = 0;
            const contentPage = JSON.stringify({
              title: "Just a Moment",
              url: "https://www.reddit.com/r/firefox/?view=hot&solution=proof&js_challenge=1&token=secret#posts",
              canonicalUrl: "https://www.reddit.com/r/firefox/?view=hot&token=secret",
              published: "",
              byline: "",
              text: "A legitimate article about a song.",
              markdown: "A legitimate article about a song.\n\n``\n``\n\nUseful ending.",
              html: "<p>A legitimate article about a song.</p>",
              links: [
                "https://www.reddit.com/r/firefox/comments/1?sort=top&access_token=secret",
                "https://www.reddit.com/r/firefox/new/?view=compact",
              ],
            });
            const loginPage = JSON.stringify({
              title: "Sign Up | Example",
              published: "",
              byline: "",
              text: "Join this service. Email. Password.",
              markdown: "Join this service.",
              html: "<p>Join this service.</p>",
              links: [],
            });
            const emptyPage = JSON.stringify({
              title: "",
              url: "https://www.reddit.com/r/firefox/",
              canonicalUrl: "https://www.reddit.com/r/firefox/",
              published: "",
              byline: "",
              text: "",
              markdown: "",
              html: "",
              links: [],
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
                  if (request.method === "browsingContext.getTree") {
                    result = { contexts: [{ context: "fixture-context" }] };
                  }
                  if (request.method === "browsingContext.navigate") {
                    currentUrl = request.params.url;
                  }
                  if (request.method === "script.evaluate") {
                    const expression = request.params.expression;
                    let value = currentUrl.includes("/login") ? loginPage : contentPage;
                    if (currentUrl.includes("/empty")) value = emptyPage;
                    if (expression.includes("document.readyState")) {
                      settleChecks += 1;
                      value = JSON.stringify({
                        readyState: "complete",
                        textLength: settleChecks === 1 ? 10 : 20,
                        scrollHeight: 500,
                        links: 2,
                      });
                    }
                    if (expression.includes("const phrases")) {
                      value = JSON.stringify({ blocked: !currentUrl.includes("/login") });
                    }
                    if (expression.includes("challengeControl")) {
                      value = JSON.stringify(currentUrl.includes("/rate-limit") ? {
                        title: "Too Many Requests",
                        url: "https://www.reddit.com/r/firefox/",
                        text: "Rate limit exceeded. Please try again later.",
                        challengeControl: false,
                        loginControl: false,
                        mainTextLength: 0,
                        articleCount: 0,
                        contentLinks: 0,
                      } : currentUrl.includes("/login") ? {
                        challengeControl: false,
                        loginControl: true,
                      } : {
                        title: "Just a Moment",
                        url: "https://en.wikipedia.org/wiki/Just_a_Moment",
                        text: "Just a Moment may refer to several songs and albums.",
                        challengeControl: false,
                        loginControl: false,
                      });
                    }
                    if (
                      expression.includes("const candidates") &&
                      settleChecks < 3
                    ) {
                      writeFileSync(process.env.FAKE_EARLY_EXTRACTION, String(settleChecks));
                      process.exit(31);
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
        environment = {
            "PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}",
            "WEB_RESEARCH_DATA_DIR": str(self.workspace / "web-data"),
            "FAKE_EARLY_EXTRACTION": str(self.workspace / "early-extraction"),
        }

        content = self.run_tool(
            "web-research",
            "scrape",
            "https://93.184.216.34/content",
            "--format",
            "json",
            "--wait-ms",
            "0",
            "--settle-ms",
            "1000",
            "--max-content-chars",
            "32",
            "--max-links",
            "1",
            "--profile",
            "access-test",
            environment=environment,
        )

        page = json.loads(content.stdout)
        self.assertEqual(
            page["url"], "https://www.reddit.com/r/firefox/?view=hot"
        )
        self.assertEqual(
            page["canonicalUrl"], "https://www.reddit.com/r/firefox/?view=hot"
        )
        self.assertEqual(
            page["links"],
            [
                "https://www.reddit.com/r/firefox/comments/1?sort=top",
            ],
        )
        self.assertNotIn("secret", content.stdout)
        self.assertLessEqual(len(page["text"]), 32)
        self.assertLessEqual(len(page["markdown"]), 32)
        self.assertLessEqual(len(page["html"]), 32)
        self.assertEqual(
            page["truncated"],
            {"text": True, "markdown": True, "html": True, "links": True},
        )
        self.assertFalse((self.workspace / "early-extraction").exists())

        login = self.run_tool(
            "web-research",
            "scrape",
            "https://93.184.216.34/login",
            "--format",
            "json",
            "--profile",
            "access-test",
            environment=environment,
            check=False,
        )

        self.assertNotEqual(login.returncode, 0)
        self.assertIn("interactive login required", login.stderr)
        self.assertNotIn("opaque-secret", login.stderr)

        rate_limited = self.run_tool(
            "web-research",
            "scrape",
            "https://93.184.216.34/rate-limit",
            "--format",
            "json",
            "--profile",
            "access-test",
            environment=environment,
            check=False,
        )
        self.assertNotEqual(rate_limited.returncode, 0)
        self.assertIn("origin rate limited", rate_limited.stderr)

        empty = self.run_tool(
            "web-research",
            "scrape",
            "https://93.184.216.34/empty",
            "--format",
            "json",
            "--profile",
            "access-test",
            environment=environment,
            check=False,
        )

        self.assertNotEqual(empty.returncode, 0)
        self.assertIn("page did not expose extractable content", empty.stderr)

    def test_web_research_preserves_soft_gated_virtualized_evidence(self):
        self.executable(
            "firefox",
            r'''
            #!/usr/bin/env bun
            const port = Number(Bun.argv[Bun.argv.indexOf("--remote-debugging-port") + 1]);
            let currentUrl = "about:blank";
            let scrollStep = 0;
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
                  if (request.method === "browsingContext.getTree") {
                    result = { contexts: [{ context: "fixture-context" }] };
                  }
                  if (request.method === "browsingContext.navigate") {
                    currentUrl = request.params.url;
                    scrollStep = 0;
                  }
                  if (request.method === "script.evaluate") {
                    const expression = request.params.expression;
                    let value = "";
                    if (expression.includes("document.readyState")) {
                      value = JSON.stringify({
                        readyState: "complete",
                        url: currentUrl,
                        title: "Public profile",
                        textLength: 1200,
                        scrollHeight: 1000 + scrollStep * 1000,
                        links: 20,
                        shadowRoots: 0,
                      });
                    } else if (expression.includes("challengeControl")) {
                      value = JSON.stringify({
                        title: "Public profile",
                        url: currentUrl,
                        text: "Sign in to see more. Public profile evidence remains visible.",
                        challengeControl: false,
                        loginControl: true,
                        mainTextLength: 1200,
                        articleCount: 5,
                        contentLinks: 20,
                      });
                    } else if (expression.includes("window.scrollTo")) {
                      scrollStep += 1;
                    } else if (expression.includes("const candidates")) {
                      value = JSON.stringify({
                        title: "Public profile",
                        url: currentUrl,
                        canonicalUrl: currentUrl,
                        published: "",
                        byline: "",
                        text: `Shared introduction\n\nVirtual item ${scrollStep}`,
                        markdown: `Shared introduction\n\nVirtual item ${scrollStep}`,
                        html: `<article>Virtual item ${scrollStep}</article>`,
                        links: [`https://93.184.216.34/item-${scrollStep}`],
                        structured: {
                          metadata: {
                            "og:title": "Public profile",
                            description: "Public evidence from metadata",
                          },
                          jsonLd: [{ "@type": "Person", name: "Public Person" }],
                        },
                        sources: ["rendered-dom", "page-metadata", "json-ld"],
                      });
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
        environment = {
            "PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}",
            "WEB_RESEARCH_DATA_DIR": str(self.workspace / "web-data"),
        }

        result = self.run_tool(
            "web-research",
            "scrape",
            "https://93.184.216.34/public-profile",
            "--format",
            "json",
            "--scroll-steps",
            "2",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "adaptive-evidence",
            environment=environment,
        )

        page = json.loads(result.stdout)
        self.assertEqual(page["access"]["state"], "soft-login")
        self.assertEqual(page["captures"], 3)
        for item in range(3):
            self.assertEqual(page["text"].count(f"Virtual item {item}"), 1)
            self.assertIn(
                f"https://93.184.216.34/item-{item}", page["links"]
            )
        self.assertEqual(page["text"].count("Shared introduction"), 1)
        self.assertEqual(
            page["structured"]["jsonLd"],
            [{"@type": "Person", "name": "Public Person"}],
        )
        self.assertEqual(
            page["sources"], ["rendered-dom", "page-metadata", "json-ld"]
        )

    def test_web_research_interacts_scrolls_containers_and_captures_network_json(self):
        self.executable(
            "firefox",
            r'''
            #!/usr/bin/env bun
            const port = Number(Bun.argv[Bun.argv.indexOf("--remote-debugging-port") + 1]);
            let currentUrl = "about:blank";
            let expanded = false;
            let scrolled = false;
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
                  if (request.method === "browsingContext.getTree") {
                    result = { contexts: [{ context: "fixture-context" }] };
                  } else if (request.method === "network.addDataCollector") {
                    result = { collector: "collector-1" };
                  } else if (request.method === "network.getData") {
                    result = {
                      bytes: {
                        type: "string",
                        value: JSON.stringify({
                          items: [{ name: "Network item" }],
                          token: "secret",
                          next: "https://93.184.216.34/api/feed?token=secret&view=full",
                        }),
                      },
                    };
                  } else if (request.method === "browsingContext.navigate") {
                    currentUrl = request.params.url;
                    socket.send(JSON.stringify({
                      type: "event",
                      method: "network.responseCompleted",
                      params: {
                        context: "fixture-context",
                        request: {
                          request: "request-1",
                          url: "https://93.184.216.34/api/feed?view=full&token=secret",
                        },
                        response: { status: 200, mimeType: "application/json" },
                      },
                    }));
                  } else if (request.method === "script.evaluate") {
                    const expression = request.params.expression;
                    let value = "";
                    if (expression.includes("document.readyState")) {
                      value = JSON.stringify({
                        readyState: "complete",
                        url: currentUrl,
                        title: "Dynamic fixture",
                        textLength: expanded ? 200 : 100,
                        scrollHeight: 1000,
                        links: 2,
                        shadowRoots: 0,
                      });
                    } else if (expression.includes("challengeControl")) {
                      value = JSON.stringify({
                        title: "Dynamic fixture",
                        url: currentUrl,
                        text: "Public evidence",
                        challengeControl: false,
                        loginControl: false,
                        mainTextLength: 800,
                        articleCount: 2,
                        contentLinks: 2,
                      });
                    } else if (expression.includes("agencyInteractionCandidate")) {
                      if (!expanded) {
                        expanded = true;
                        value = JSON.stringify({ kind: "expand", label: "Show more" });
                      } else {
                        value = "";
                      }
                    } else if (expression.includes("agencyScrollTarget")) {
                      scrolled = true;
                      value = JSON.stringify({ target: "container", moved: true });
                    } else if (expression.includes("const candidates")) {
                      const items = ["Initial evidence"];
                      if (expanded) items.push("Expanded evidence");
                      if (scrolled) items.push("Container evidence");
                      value = JSON.stringify({
                        title: "Dynamic fixture",
                        url: currentUrl,
                        canonicalUrl: currentUrl,
                        published: "",
                        byline: "",
                        text: items.join("\n\n"),
                        markdown: items.join("\n\n"),
                        html: `<main>${items.join(" ")}</main>`,
                        links: [],
                        sources: ["rendered-dom"],
                      });
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
        environment = {
            "PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}",
            "WEB_RESEARCH_DATA_DIR": str(self.workspace / "web-data"),
        }

        result = self.run_tool(
            "web-research",
            "scrape",
            "https://93.184.216.34/dynamic",
            "--format",
            "json",
            "--interaction-steps",
            "1",
            "--scroll-steps",
            "1",
            "--capture-network-json",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "dynamic-evidence",
            environment=environment,
        )

        page = json.loads(result.stdout)
        self.assertEqual(page["state"], "public-content")
        self.assertEqual(page["captures"], 3)
        self.assertIn("Expanded evidence", page["text"])
        self.assertIn("Container evidence", page["text"])
        self.assertEqual(
            page["actions"],
            [{"kind": "expand", "label": "Show more", "changed": True}],
        )
        self.assertEqual(page["scroll_targets"], ["container"])
        self.assertEqual(page["network"][0]["body"]["items"][0]["name"], "Network item")
        self.assertNotIn("token", page["network"][0]["body"])
        self.assertEqual(
            page["network"][0]["body"]["next"],
            "https://93.184.216.34/api/feed?view=full",
        )
        self.assertIn("network-json", page["sources"])
        self.assertNotIn("secret", result.stdout)

    def test_web_research_scrape_batch_interleaves_origins(self):
        navigations = self.workspace / "batch-navigations"
        self.executable(
            "firefox",
            r'''
            #!/usr/bin/env bun
            import { appendFileSync } from "node:fs";
            const port = Number(Bun.argv[Bun.argv.indexOf("--remote-debugging-port") + 1]);
            let currentUrl = "about:blank";
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
                  if (request.method === "browsingContext.getTree") {
                    result = { contexts: [{ context: "fixture-context" }] };
                  }
                  if (request.method === "browsingContext.navigate") {
                    currentUrl = request.params.url;
                    appendFileSync(process.env.FAKE_NAV_MARKER, currentUrl + "\n");
                  }
                  if (request.method === "script.evaluate") {
                    const expression = request.params.expression;
                    let value = JSON.stringify({
                      title: "Fixture",
                      url: currentUrl,
                      canonicalUrl: currentUrl,
                      published: "",
                      byline: "",
                      text: "evidence",
                      markdown: "evidence",
                      html: "<p>evidence</p>",
                      links: [],
                    });
                    if (expression.includes("document.readyState")) {
                      value = JSON.stringify({
                        readyState: "complete",
                        url: currentUrl,
                        title: "Fixture",
                        textLength: 8,
                        scrollHeight: 500,
                        links: 0,
                        shadowRoots: 0,
                      });
                    } else if (expression.includes("challengeControl")) {
                      value = JSON.stringify({
                        title: "Fixture",
                        url: currentUrl,
                        text: "evidence",
                        challengeControl: false,
                        loginControl: false,
                      });
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
        urls = self.workspace / "mixed-origins.txt"
        urls.write_text(
            "https://a.example/1\n"
            "https://a.example/2\n"
            "https://b.example/1\n"
            "https://c.example/1\n"
            "https://b.example/2\n"
        )
        output = self.workspace / "mixed-pages.ndjson"
        environment = {
            "PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}",
            "WEB_RESEARCH_DATA_DIR": str(self.workspace / "web-data"),
            "FAKE_NAV_MARKER": str(navigations),
        }

        self.run_tool(
            "web-research",
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
            "origin-interleave",
            environment=environment,
        )

        self.assertEqual(
            navigations.read_text().splitlines(),
            [
                "https://a.example/1",
                "https://b.example/1",
                "https://c.example/1",
                "https://a.example/2",
                "https://b.example/2",
            ],
        )

    def test_web_research_scrape_batch_preserves_discovery_on_hard_gate(self):
        self.executable(
            "firefox",
            r'''
            #!/usr/bin/env bun
            const port = Number(Bun.argv[Bun.argv.indexOf("--remote-debugging-port") + 1]);
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
                  if (request.method === "browsingContext.getTree") {
                    result = { contexts: [{ context: "fixture-context" }] };
                  }
                  if (request.method === "script.evaluate") {
                    const expression = request.params.expression;
                    let value = "";
                    if (expression.includes("document.readyState")) {
                      value = JSON.stringify({
                        readyState: "complete",
                        url: "https://gate.example/authwall",
                        title: "Sign in",
                        textLength: 40,
                        scrollHeight: 500,
                        links: 1,
                        shadowRoots: 0,
                      });
                    } else if (expression.includes("challengeControl")) {
                      value = JSON.stringify({
                        title: "Sign in",
                        url: "https://gate.example/authwall?token=secret",
                        text: "Sign in to continue",
                        challengeControl: false,
                        loginControl: true,
                        mainTextLength: 40,
                        articleCount: 0,
                        contentLinks: 1,
                      });
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
        discovery = self.workspace / "discovery.ndjson"
        discovery.write_text(
            json.dumps(
                {
                    "schema": "agency/web-search-result/1",
                    "query": "public organization evidence",
                    "outcome": "searched",
                    "engine": "bing",
                    "results": [
                        {
                            "title": "Public organization",
                            "url": "https://gate.example/public",
                            "snippet": "Public evidence discovered before source extraction.",
                        }
                    ],
                }
            )
            + "\n"
        )
        output = self.workspace / "partial-pages.ndjson"
        environment = {
            "PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}",
            "WEB_RESEARCH_DATA_DIR": str(self.workspace / "web-data"),
        }

        summary = self.run_tool(
            "web-research",
            "scrape-batch",
            discovery,
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
            "partial-evidence",
            environment=environment,
        )

        report = json.loads(summary.stdout)
        record = json.loads(output.read_text())
        self.assertEqual(report["partial"], 1)
        self.assertEqual(report["failed"], 0)
        self.assertEqual(record["outcome"], "partial")
        self.assertEqual(record["constraint"], "hard-login")
        evidence = record["evidence"][0]
        self.assertEqual(evidence["source"], "search-result")
        self.assertEqual(evidence["query"], "public organization evidence")
        self.assertEqual(evidence["engine"], "bing")
        self.assertEqual(evidence["title"], "Public organization")
        self.assertEqual(evidence["url"], "https://gate.example/public")
        self.assertEqual(
            evidence["snippet"],
            "Public evidence discovered before source extraction.",
        )
        self.assertEqual(evidence["provenance"]["snippet"][0]["source"], "search-result")
        self.assertEqual(evidence["quality"][0]["code"], "search-snippet-only")
        self.assertNotIn("secret", output.read_text())

        resumed = self.run_tool(
            "web-research",
            "scrape-batch",
            discovery,
            "--output",
            output,
            "--resume",
            "--profile",
            "partial-evidence",
            environment=environment,
        )
        self.assertEqual(json.loads(resumed.stdout)["pending"], 0)
        self.assertEqual(len(output.read_text().splitlines()), 1)

    def test_web_research_auto_search_reuses_firefox_and_falls_back_to_bing(self):
        launches = self.workspace / "firefox-launches"
        navigations = self.workspace / "firefox-navigations"
        self.executable(
            "firefox",
            r'''
            #!/usr/bin/env bun
            import { appendFileSync } from "node:fs";
            appendFileSync(process.env.FAKE_LAUNCH_MARKER, "launch\n");
            const port = Number(Bun.argv[Bun.argv.indexOf("--remote-debugging-port") + 1]);
            let currentUrl = "about:blank";
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
                  if (request.method === "browsingContext.getTree") {
                    result = { contexts: [{ context: "fixture-context" }] };
                  }
                  if (request.method === "browsingContext.navigate") {
                    currentUrl = request.params.url;
                    appendFileSync(
                      process.env.FAKE_NAV_MARKER,
                      new URL(currentUrl).hostname + "\n",
                    );
                  }
                  if (request.method === "script.evaluate") {
                    const expression = request.params.expression;
                    const challenged = !currentUrl.includes("bing.com");
                    let value = JSON.stringify([]);
                    if (expression.includes("const phrases")) {
                      value = JSON.stringify({ blocked: challenged });
                    }
                    if (expression.includes("challengeControl")) {
                      value = JSON.stringify({
                        title: challenged ? "Checking your browser" : "Search",
                        url: currentUrl,
                        text: challenged ? "Verify you are human while checking your browser" : "Results",
                        challengeControl: challenged,
                        loginControl: false,
                      });
                    }
                    if (expression.includes('const engine = "bing"')) {
                      value = JSON.stringify([{
                        title: "Result",
                        url: "https://developer.mozilla.org/en-US/docs/Web/WebDriver/BiDi",
                        snippet: "Primary documentation",
                      }]);
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
        environment = {
            "PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}",
            "WEB_RESEARCH_DATA_DIR": str(self.workspace / "web-data"),
            "FAKE_LAUNCH_MARKER": str(launches),
            "FAKE_NAV_MARKER": str(navigations),
        }

        result = self.run_tool(
            "web-research",
            "search",
            "Firefox WebDriver BiDi",
            "--engine",
            "auto",
            "--limit",
            "5",
            "--json",
            "--profile",
            "search-fallback",
            environment=environment,
        )

        report = json.loads(result.stdout)
        self.assertEqual(report["engine"], "bing")
        self.assertEqual(report["results"][0]["title"], "Result")
        self.assertEqual(launches.read_text().splitlines(), ["launch"])

        queries = self.workspace / "queries.txt"
        output = self.workspace / "results.ndjson"
        queries.write_text("alpha\nbeta\ngamma\nalpha\n")
        output.write_text(
            json.dumps(
                {
                    "schema": "agency/web-search-result/1",
                    "query": "alpha",
                    "outcome": "searched",
                    "engine": "bing",
                    "results": [],
                }
            )
            + "\n"
        )
        navigations.write_text("")

        batch = self.run_tool(
            "web-research",
            "search-batch",
            queries,
            "--output",
            output,
            "--resume",
            "--limit",
            "5",
            "--delay-ms",
            "0",
            "--jitter-ms",
            "0",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--profile",
            "search-fallback",
            environment=environment,
        )

        summary = json.loads(batch.stdout)
        records = [json.loads(line) for line in output.read_text().splitlines()]
        self.assertEqual(summary["completed"], 2)
        self.assertEqual(summary["resumed"], 1)
        self.assertEqual([record["query"] for record in records], ["alpha", "beta", "gamma"])
        self.assertEqual([record["engine"] for record in records[1:]], ["bing", "bing"])
        self.assertEqual(
            navigations.read_text().splitlines(),
            [
                "html.duckduckgo.com",
                "search.brave.com",
                "www.bing.com",
                "www.bing.com",
            ],
        )
        self.assertEqual(launches.read_text().splitlines(), ["launch", "launch"])

        resumed = self.run_tool(
            "web-research",
            "search-batch",
            queries,
            "--output",
            output,
            "--resume",
            "--delay-ms",
            "0",
            "--jitter-ms",
            "0",
            "--profile",
            "search-fallback",
            environment=environment,
        )

        resumed_summary = json.loads(resumed.stdout)
        self.assertEqual(resumed_summary["pending"], 0)
        self.assertEqual(launches.read_text().splitlines(), ["launch", "launch"])

    def test_web_research_crawl_bounds_and_deduplicates_the_frontier(self):
        launches = self.workspace / "crawl-firefox-launches"
        self.executable(
            "firefox",
            r'''
            #!/usr/bin/env bun
            import { appendFileSync } from "node:fs";
            appendFileSync(process.env.FAKE_LAUNCH_MARKER, "launch\n");
            const port = Number(Bun.argv[Bun.argv.indexOf("--remote-debugging-port") + 1]);
            let currentUrl = "https://93.184.216.34/";
            const page = () => {
              const url = new URL(currentUrl);
              const root = url.pathname === "/";
              return JSON.stringify({
                title: root ? "Root" : url.pathname.slice(1).toUpperCase(),
                url: currentUrl,
                canonicalUrl: currentUrl,
                published: "",
                byline: "",
                text: root ? "root evidence" : "child evidence",
                markdown: root ? "root evidence" : "child evidence",
                html: root ? "<p>root evidence</p>" : "<p>child evidence</p>",
                links: root ? [
                  "https://93.184.216.34/a?utm_source=one",
                  "https://93.184.216.34/a?utm_source=two#fragment",
                  "https://93.184.216.34/b",
                  "https://93.184.216.34/c",
                  "https://93.184.216.34/d",
                ] : [],
              });
            };
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
                  if (request.method === "browsingContext.getTree") {
                    result = { contexts: [{ context: "fixture-context" }] };
                  }
                  if (request.method === "browsingContext.navigate") {
                    currentUrl = request.params.url;
                  }
                  if (request.method === "script.evaluate") {
                    const expression = request.params.expression;
                    let value = page();
                    if (expression.startsWith("fetch(")) value = "";
                    if (expression.includes("document.readyState")) {
                      value = JSON.stringify({
                        readyState: "complete",
                        url: currentUrl,
                        title: "Fixture",
                        textLength: 20,
                        scrollHeight: 500,
                        links: 5,
                        shadowRoots: 0,
                      });
                    }
                    if (expression.includes("challengeControl")) {
                      value = JSON.stringify({
                        title: "Fixture",
                        url: currentUrl,
                        text: "evidence",
                        challengeControl: false,
                        loginControl: false,
                      });
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
        data_root = self.workspace / "web-data"
        environment = {
            "PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}",
            "WEB_RESEARCH_DATA_DIR": str(data_root),
            "FAKE_LAUNCH_MARKER": str(launches),
        }

        result = self.run_tool(
            "web-research",
            "crawl",
            "https://93.184.216.34/",
            "--limit",
            "10",
            "--depth",
            "1",
            "--max-queue",
            "3",
            "--links-per-page",
            "10",
            "--max-query-params",
            "4",
            "--delay-ms",
            "0",
            "--wait-ms",
            "0",
            "--settle-ms",
            "0",
            "--json",
            "--profile",
            "crawl-bounds",
            environment=environment,
        )

        report = json.loads(result.stdout)
        self.assertEqual(
            [page["url"] for page in report["pages"]],
            [
                "https://93.184.216.34/",
                "https://93.184.216.34/a",
                "https://93.184.216.34/b",
            ],
        )
        self.assertEqual(report["summary"]["indexed"], 3)
        self.assertTrue(report["summary"]["frontier_truncated"])

        stats = self.run_tool(
            "web-research", "stats", environment=environment
        )
        self.assertEqual(json.loads(stats.stdout)["pages"], 3)

        urls = self.workspace / "urls.txt"
        output = self.workspace / "pages.ndjson"
        urls.write_text(
            "https://93.184.216.34/\n"
            "https://93.184.216.34/a\n"
            "https://93.184.216.34/b\n"
            "https://93.184.216.34/a\n"
        )
        output.write_text(
            json.dumps(
                {
                    "schema": "agency/web-page-result/1",
                    "requested_url": "https://93.184.216.34/",
                    "outcome": "scraped",
                    "page": {"url": "https://93.184.216.34/"},
                }
            )
            + "\n"
        )

        batch = self.run_tool(
            "web-research",
            "scrape-batch",
            urls,
            "--output",
            output,
            "--resume",
            "--index",
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
            "crawl-bounds",
            environment=environment,
        )

        batch_summary = json.loads(batch.stdout)
        page_records = [json.loads(line) for line in output.read_text().splitlines()]
        self.assertEqual(batch_summary["completed"], 2)
        self.assertEqual(batch_summary["resumed"], 1)
        self.assertEqual(
            [record["requested_url"] for record in page_records],
            [
                "https://93.184.216.34/",
                "https://93.184.216.34/a",
                "https://93.184.216.34/b",
            ],
        )
        self.assertEqual(launches.read_text().splitlines(), ["launch", "launch"])

        resumed = self.run_tool(
            "web-research",
            "scrape-batch",
            urls,
            "--output",
            output,
            "--resume",
            "--delay-ms",
            "0",
            "--jitter-ms",
            "0",
            "--profile",
            "crawl-bounds",
            environment=environment,
        )
        self.assertEqual(json.loads(resumed.stdout)["pending"], 0)
        self.assertEqual(launches.read_text().splitlines(), ["launch", "launch"])

    def test_web_research_frame_extraction_is_origin_bounded_and_redacted(self):
        self.executable(
            "firefox",
            r'''
            #!/usr/bin/env bun
            const port = Number(Bun.argv[Bun.argv.indexOf("--remote-debugging-port") + 1]);
            const topPage = JSON.stringify({
              title: "Top",
              url: "https://93.184.216.34/page",
              canonicalUrl: "https://93.184.216.34/page",
              published: "",
              byline: "",
              text: "top evidence",
              markdown: "top evidence",
              html: "<p>top evidence</p>",
              links: [],
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
                  if (request.method === "browsingContext.getTree") {
                    result = {
                      contexts: [{
                        context: "top",
                        url: "https://93.184.216.34/page",
                        children: [
                          { context: "same", url: "https://93.184.216.34/frame?token=secret", children: [] },
                          { context: "cross", url: "https://readings.example/item?auth=secret", children: [] },
                        ],
                      }],
                    };
                  }
                  if (request.method === "script.evaluate") {
                    const access = request.params.expression.includes("challengeControl");
                    const context = request.params.target.context;
                    let value = topPage;
                    if (access) {
                      value = JSON.stringify({
                        title: "Top",
                        url: "https://93.184.216.34/page",
                        text: "top evidence",
                        challengeControl: false,
                        loginControl: false,
                      });
                    }
                    if (context === "same") {
                      value = JSON.stringify({ title: "Frame", text: "frame evidence" });
                    }
                    if (context === "cross") process.exit(29);
                    result = { type: "success", result: { value } };
                  }
                  socket.send(JSON.stringify({ id: request.id, type: "success", result }));
                },
              },
            });
            await new Promise(() => {});
            ''',
        )
        environment = {
            "PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}",
            "WEB_RESEARCH_DATA_DIR": str(self.workspace / "web-data"),
        }

        result = self.run_tool(
            "web-research",
            "scrape",
            "https://93.184.216.34/page",
            "--format",
            "json",
            "--profile",
            "frame-test",
            "--include-frames",
            environment=environment,
        )

        page = json.loads(result.stdout)
        extracted, skipped = page["frames"]
        self.assertEqual(extracted["status"], "extracted")
        self.assertEqual(extracted["origin"], "https://93.184.216.34")
        self.assertEqual(extracted["path"], "/frame")
        self.assertEqual(extracted["title"], "Frame")
        self.assertEqual(extracted["text"], "frame evidence")
        self.assertEqual(extracted["provenance"]["text"][0]["source"], "frame")
        self.assertEqual(
            skipped,
            {
                "status": "skipped",
                "reason": "cross-origin",
                "origin": "https://readings.example",
                "path": "/item",
            },
        )
        self.assertNotIn("secret", result.stdout)
