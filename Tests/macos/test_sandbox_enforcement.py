import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request


ROOT = Path(__file__).resolve().parents[2]


class SeatbeltEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(sys.platform, "darwin", "Run this enforcement suite on macOS")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.secret = self.root / "outside.txt"
        self.secret.write_text("outside sentinel")
        (self.workspace / "escape").symlink_to(self.secret)

    def sandbox(self, program, *options):
        return subprocess.run(
            [ROOT / "Tools/sandbox", "--workspace", self.workspace, "--ro", sys.base_prefix, *options,
             "--", sys.executable, "-c", program],
            env={**os.environ, "AGENCY_PRIVATE_SENTINEL": "must not leak"},
            capture_output=True, text=True, timeout=25,
        )

    def test_workspace_and_private_temp_work_but_siblings_and_secrets_are_denied(self):
        program = f'''
import json, os
from pathlib import Path
Path("output.txt").write_text("allowed")
Path(os.environ["TMPDIR"], "temporary.txt").write_text("allowed")
denied = []
for path, mode in [({str(self.secret)!r}, "r"), ({str(self.secret)!r}, "w"), ("escape", "r")]:
    try:
        with open(path, mode) as handle:
            handle.read() if mode == "r" else handle.write("unexpected")
    except PermissionError:
        denied.append(True)
    else:
        denied.append(False)
print(json.dumps({{"denied": denied, "secret": os.getenv("AGENCY_PRIVATE_SENTINEL"), "home": os.environ["HOME"]}}))
'''
        result = self.sandbox(program)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["denied"], [True, True, True])
        self.assertIsNone(output["secret"])
        self.assertNotEqual(output["home"], str(Path.home()))
        self.assertFalse(Path(output["home"]).exists())
        self.assertEqual((self.workspace / "output.txt").read_text(), "allowed")
        self.assertEqual(self.secret.read_text(), "outside sentinel")

    def test_explicit_readonly_grant_cannot_write(self):
        result = self.sandbox(
            f'from pathlib import Path; p=Path({str(self.secret)!r}); print(p.read_text()); p.write_text("no")',
            "--ro", str(self.secret),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "outside sentinel")
        self.assertIn("PermissionError", result.stderr)
        self.assertEqual(self.secret.read_text(), "outside sentinel")

    def test_readonly_workspace_blocks_writes(self):
        result = self.sandbox('open("no.txt", "w")', "--workspace-ro")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PermissionError", result.stderr)
        self.assertFalse((self.workspace / "no.txt").exists())

    def test_offline_blocks_a_reachable_host_listener(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                pass
            result = self.sandbox(
                f'import socket; socket.create_connection(("127.0.0.1", {port}), timeout=2)',
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PermissionError", result.stderr)

    def test_explicit_environment_and_exit_status_are_preserved(self):
        result = self.sandbox(
            'import os, sys; print(os.environ["AGENCY_EXPLICIT"]); sys.exit(7)',
            "--set-env", "AGENCY_EXPLICIT=literal $(text)",
        )
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(result.stdout.strip(), "literal $(text)")

    def test_node_preload_runs_only_inside_the_payload_sandbox(self):
        preload = self.workspace / "preload.cjs"
        inside = self.workspace / "preload-ran"
        preload.write_text(
            "const fs = require('node:fs');\n"
            f"fs.writeFileSync({str(inside)!r}, 'payload');\n"
            f"try {{ fs.writeFileSync({str(self.secret)!r}, 'escaped'); process.exit(91); }}\n"
            "catch (error) { if (error.code !== 'EPERM' && error.code !== 'EACCES') throw error; }\n"
        )
        options = ["--set-env", f"NODE_OPTIONS=--require={preload}"]
        result = self.sandbox('print("python payload")', *options)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(inside.exists(), "Node launcher executed the payload preload")
        self.assertEqual(self.secret.read_text(), "outside sentinel")
        result = subprocess.run(
            [ROOT / "Tools/sandbox", "--workspace", self.workspace, *options,
             "--", "node", "-e", "process.stdout.write('node payload')"],
            text=True, capture_output=True, timeout=25,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "node payload")
        self.assertEqual(inside.read_text(), "payload")
        self.assertEqual(self.secret.read_text(), "outside sentinel")

    def test_terminated_payload_never_reports_success(self):
        for number in (2, 9, 15):
            with self.subTest(signal=number):
                result = subprocess.run(
                    [ROOT / "Tools/sandbox", "--workspace", self.workspace, "--",
                     "/bin/bash", "-c", f"kill -{number} $$"],
                    text=True, capture_output=True, timeout=25,
                )
                self.assertEqual(result.returncode, 128 + number, result.stderr)

    def test_shell_startup_environment_cannot_run_before_isolation(self):
        startup = self.workspace / "startup.sh"
        marker = self.workspace / "startup-ran"
        startup.write_text(
            f"printf payload > {str(marker)!r}\n"
            f"if printf escaped > {str(self.secret)!r} 2>/dev/null; then exit 91; fi\n"
        )
        options = ["--set-env", f"BASH_ENV={startup}"]
        result = self.sandbox('print("python payload")', *options)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists(), "Launcher shell sourced the payload startup file")
        result = subprocess.run(
            [ROOT / "Tools/sandbox", "--workspace", self.workspace, *options,
             "--", "/bin/bash", "-c", "printf 'shell payload'"],
            text=True, capture_output=True, timeout=25,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marker.read_text(), "payload")
        self.assertEqual(self.secret.read_text(), "outside sentinel")

    def test_network_proxy_denies_by_default_and_honors_explicit_domain(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"reachable fixture")

            def log_message(self, *args):
                pass

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host = f"127.0.0.1:{server.server_port}"
                url = f"http://{host}/probe"
                with urllib.request.urlopen(url, timeout=2) as response:
                    self.assertEqual(response.read(), b"reachable fixture")
                requests.clear()
                program = f'import os, subprocess, sys; sys.exit(subprocess.run(["/usr/bin/curl", "--fail", "--silent", "--show-error", "--max-time", "3", "--noproxy", "", "--proxy", os.environ["HTTP_PROXY"], {url!r}]).returncode)'
                denied = self.sandbox(program)
                self.assertNotEqual(denied.returncode, 0)
                self.assertIn("403", denied.stderr)
                self.assertEqual(requests, [])
                allowed = self.sandbox(program, "--allow-domain", host)
                self.assertEqual(allowed.returncode, 0, allowed.stderr)
                self.assertEqual(allowed.stdout, "reachable fixture")
                self.assertEqual(requests, ["/probe"])
            finally:
                server.shutdown()
                thread.join(timeout=3)

    def test_explicit_writable_grant_and_closed_inherited_descriptor(self):
        with self.secret.open() as handle:
            descriptor = handle.fileno()
            result = subprocess.run(
                [ROOT / "Tools/sandbox", "--workspace", self.workspace,
                 "--ro", sys.base_prefix, "--rw", self.secret, "--", sys.executable, "-c",
                 f'import os; from pathlib import Path; Path({str(self.secret)!r}).write_text("authorized"); os.fstat({descriptor})'],
                pass_fds=(descriptor,), capture_output=True, text=True, timeout=25,
            )
        self.assertEqual(self.secret.read_text(), "authorized")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Bad file descriptor", result.stderr)


if __name__ == "__main__":
    unittest.main()
