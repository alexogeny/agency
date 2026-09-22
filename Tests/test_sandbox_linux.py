import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LinuxSandboxLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.executable("uname", 'print("Linux")')
        self.executable("bwrap", '''import json, os, signal, sys
number = int(os.environ.get("SANDBOX_FIXTURE_SIGNAL", "0"))
if number:
    os.kill(os.getpid(), number)
print(json.dumps({"argv": sys.argv[1:], "launcher_node_options": os.getenv("NODE_OPTIONS")}))
''')
        self.executable("pasta", '''import os, sys
index = sys.argv.index("--")
os.execvp(sys.argv[index + 1], sys.argv[index + 1:])
''')

    def executable(self, name, source):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + source + "\n")
        path.chmod(0o755)

    def run_tool(self, *args, signal_number=0):
        environment = {
            **os.environ, "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "SANDBOX_FIXTURE_SIGNAL": str(signal_number),
        }
        environment.pop("NODE_OPTIONS", None)
        return subprocess.run(
            [shutil.which("bash"), ROOT / "Tools/sandbox", "--workspace", self.root,
             *args, "--", "/bin/true"],
            env=environment, text=True, capture_output=True, timeout=10,
        )

    def test_forwarded_environment_is_only_given_to_bwrap_as_payload_arguments(self):
        for options in ((), ("--internet",)):
            with self.subTest(options=options):
                result = self.run_tool(*options, "--set-env", "NODE_OPTIONS=--require=payload.cjs")
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                self.assertIsNone(data["launcher_node_options"])
                index = data["argv"].index("NODE_OPTIONS")
                self.assertEqual(data["argv"][index - 1:index + 2], ["--setenv", "NODE_OPTIONS", "--require=payload.cjs"])

    def test_launcher_does_not_convert_signals_to_success(self):
        for options in ((), ("--internet",)):
            for number in (9, 15):
                with self.subTest(options=options, signal=number):
                    result = self.run_tool(*options, signal_number=number)
                    self.assertEqual(result.returncode, -number, result.stderr)


if __name__ == "__main__":
    unittest.main()
