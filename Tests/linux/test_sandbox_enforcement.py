import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class BubblewrapEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(sys.platform, "linux", "Run this enforcement suite on Linux")
        self.assertNotEqual(os.geteuid(), 0, "Run these tests as an unprivileged user")
        self.assertIsNotNone(shutil.which("bwrap"))
        self.assertIsNotNone(shutil.which("pasta"))
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.outside = self.root / "outside"
        self.outside.write_text("host sentinel")

    def run_tool(self, command, *options):
        return subprocess.run(
            [ROOT / "Tools/sandbox", "--workspace", self.workspace, *options, "--", *command],
            text=True, capture_output=True, timeout=25,
        )

    def test_preload_environment_reaches_only_the_sandboxed_payload(self):
        node = shutil.which("node")
        self.assertIsNotNone(node)
        preload = self.workspace / "preload.cjs"
        marker = self.workspace / "preload-ran"
        preload.write_text(
            "const fs = require('node:fs');\n"
            f"fs.writeFileSync({str(marker)!r}, 'payload');\n"
            f"try {{ fs.writeFileSync({str(self.outside)!r}, 'sandbox write'); }}\n"
            "catch (error) { if (!['EPERM', 'EACCES', 'ENOENT', 'EROFS'].includes(error.code)) throw error; }\n"
        )
        for network in ([], ["--internet"]):
            with self.subTest(network=network):
                marker.unlink(missing_ok=True)
                options = [*network, "--set-env", f"NODE_OPTIONS=--require={preload}"]
                result = self.run_tool(["/bin/true"], *options)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(marker.exists())
                result = self.run_tool([node, "-e", "process.stdout.write('payload')"], *options)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(marker.read_text(), "payload")
                self.assertEqual(self.outside.read_text(), "host sentinel")

    def test_payload_signal_status_survives_offline_and_pasta_launchers(self):
        for network in ([], ["--internet"]):
            for number in (2, 9, 15):
                with self.subTest(network=network, signal=number):
                    result = self.run_tool(["/bin/bash", "-c", f"kill -{number} $$"], *network)
                    self.assertEqual(result.returncode, 128 + number, result.stderr)


if __name__ == "__main__":
    unittest.main()
