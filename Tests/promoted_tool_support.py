import os
import stat
import subprocess
import tempfile
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "Tools"
SCRATCH = Path(os.environ.get("AGENCY_TEST_SCRATCH", ROOT / ".cache/tests"))


class PromotedToolFixture:
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.workspace = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def run_tool(self, name, *arguments, check=True, environment=None):
        tool_environment = os.environ.copy()
        if environment:
            tool_environment.update(environment)
        return subprocess.run(
            [str(TOOLS / name), *map(str, arguments)],
            check=check,
            text=True,
            capture_output=True,
            env=tool_environment,
        )

    def executable(self, name, source):
        path = self.workspace / "bin" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(textwrap.dedent(source).lstrip())
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path
