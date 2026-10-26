from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WEB_TOOL = ROOT / "Tools/web-research"
MCP_SERVER = ROOT / "Tools/web-research-mcp"
SCRATCH = Path(os.environ.get("AGENCY_TEST_SCRATCH", "/tmp"))
CLI_BOUNDARY = "\nconst args = Bun.argv.slice(2);"
MCP_BOUNDARY = '\nlet inputBuffer = "";'


def source_prefix(tool=WEB_TOOL, boundary=CLI_BOUNDARY):
    source = tool.read_text(encoding="utf-8")
    if source.count(boundary) != 1:
        raise AssertionError(f"Expected one fixture boundary in {tool}: {boundary!r}")
    return source.partition(boundary)[0]


@contextmanager
def fixture_directory():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
        yield Path(directory)


def fixture_environment(directory):
    return {**os.environ, "WEB_RESEARCH_DATA_DIR": str(directory / "data")}


def worker_frame(arguments, input_text=""):
    return json.dumps({"args": arguments, "input": input_text}) + "\n"


class WebResearchTestCase(unittest.TestCase):
    def run_harness(
        self,
        body,
        *,
        source=None,
        tool=WEB_TOOL,
        boundary=CLI_BOUNDARY,
        filename="fixture.ts",
        arguments=(),
        timeout=10,
    ):
        if source is None:
            source = source_prefix(tool, boundary)
        with fixture_directory() as directory:
            script = directory / filename
            script.write_text(source + body, encoding="utf-8")
            environment = fixture_environment(directory)
            result = subprocess.run(
                ["bun", script, *arguments],
                env=environment,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result
