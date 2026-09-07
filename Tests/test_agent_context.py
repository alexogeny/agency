import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "Tools/agent-context"
SCRATCH = Path(os.environ.get("AGENCY_TEST_SCRATCH", ROOT / ".cache/tests"))


class AgentContextTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.workspace = Path(self.temporary.name)
        self.codex_home = self.workspace / "codex"
        self.codex_home.mkdir()
        self.project = self.workspace / "project"
        (self.project / ".git").mkdir(parents=True)
        self.cwd = self.project / "pkg" / "feature"
        self.cwd.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def run_context(self, *arguments, check=True):
        return subprocess.run(
            [TOOL, "codex", self.cwd, *arguments],
            check=check,
            text=True,
            capture_output=True,
            env={**os.environ, "CODEX_HOME": str(self.codex_home)},
        )

    def payload(self, *arguments):
        return json.loads(self.run_context(*arguments, "--json").stdout)

    def test_selects_global_and_root_to_cwd_precedence(self):
        (self.codex_home / "AGENTS.md").write_text("global fallback\n")
        (self.codex_home / "AGENTS.override.md").write_text("global override\n")
        (self.project / "AGENTS.md").write_text("# Root\n")
        (self.project / "pkg" / "AGENTS.md").write_text("# Ignored\n")
        (self.project / "pkg" / "AGENTS.override.md").write_text("# Package\n")
        (self.cwd / "AGENTS.override.md").write_text("")
        (self.cwd / "AGENTS.md").write_text("# Feature\n")

        payload = self.payload()

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["client"], "codex")
        self.assertEqual(
            [Path(item["path"]).name for item in payload["global_instructions"]],
            ["AGENTS.override.md"],
        )
        self.assertEqual(
            [Path(item["path"]).name for item in payload["project_instructions"]],
            ["AGENTS.md", "AGENTS.override.md"],
        )
        self.assertFalse(payload["truncated"])

    def test_trusted_project_config_overrides_instruction_settings(self):
        (self.codex_home / "config.toml").write_text(
            'project_doc_max_bytes = 100\n'
            'project_doc_fallback_filenames = ["USER.md"]\n'
            f'[projects.{json.dumps(str(self.project))}]\n'
            'trust_level = "trusted"\n'
        )
        project_config = self.project / ".codex" / "config.toml"
        project_config.parent.mkdir()
        project_config.write_text(
            'project_doc_max_bytes = 8\n'
            'project_doc_fallback_filenames = ["PROJECT.md"]\n'
        )
        (self.project / "USER.md").write_text("# User fallback\n")
        selected = self.project / "PROJECT.md"
        selected.write_text("# Project fallback\n")

        payload = self.payload()

        self.assertEqual(payload["config"]["project_doc_max_bytes"], 8)
        self.assertEqual(
            payload["config"]["project_doc_fallback_filenames"], ["PROJECT.md"]
        )
        self.assertEqual(
            [Path(item["path"]) for item in payload["project_instructions"]],
            [selected.resolve()],
        )
        self.assertEqual(payload["project_bytes"]["included"], 8)
        self.assertTrue(payload["truncated"])

    def test_configured_project_root_markers_control_ancestor_search(self):
        marker = self.workspace / "WORKSPACE_ROOT"
        marker.write_text("")
        workspace_instructions = self.workspace / "AGENTS.md"
        workspace_instructions.write_text("# Workspace\n")
        project_instructions = self.project / "AGENTS.md"
        project_instructions.write_text("# Project\n")
        (self.codex_home / "config.toml").write_text(
            'project_root_markers = ["WORKSPACE_ROOT"]\n'
        )

        payload = self.payload()

        self.assertEqual(Path(payload["project_root"]), self.workspace.resolve())
        self.assertEqual(
            [Path(item["path"]) for item in payload["project_instructions"]],
            [workspace_instructions.resolve(), project_instructions.resolve()],
        )
        self.assertEqual(payload["config"]["project_root_markers"], ["WORKSPACE_ROOT"])

        (self.codex_home / "config.toml").write_text("project_root_markers = []\n")
        (self.cwd / "AGENTS.md").write_text("# Current directory\n")

        payload = self.payload()

        self.assertEqual(Path(payload["project_root"]), self.cwd.resolve())
        self.assertEqual(
            [Path(item["path"]) for item in payload["project_instructions"]],
            [(self.cwd / "AGENTS.md").resolve()],
        )

    def test_untrusted_project_omits_project_instructions(self):
        (self.codex_home / "AGENTS.md").write_text("# Global\n")
        (self.codex_home / "config.toml").write_text(
            f'[projects.{json.dumps(str(self.project))}]\n'
            'trust_level = "untrusted"\n'
        )
        (self.project / "AGENTS.md").write_text("# Untrusted project\n")
        (self.cwd / "AGENTS.md").write_text("# Untrusted child\n")

        payload = self.payload()

        self.assertEqual(len(payload["global_instructions"]), 1)
        self.assertEqual(payload["project_instructions"], [])
        self.assertEqual(payload["project_bytes"]["selected"], 0)
        self.assertFalse(payload["truncated"])

    def test_honors_fallbacks_and_reports_exact_truncation(self):
        (self.codex_home / "config.toml").write_text(
            'project_doc_max_bytes = 12\n'
            'project_doc_fallback_filenames = ["GUIDANCE.md"]\n'
            'api_key = "do-not-print-me"\n'
        )
        (self.project / "GUIDANCE.md").write_text("# First\nabc\n")
        nested = self.project / "pkg" / "GUIDANCE.md"
        nested.write_text("# Visible\n## Hidden\nsecret\n")
        (self.cwd / "GUIDANCE.md").write_text("# Deeper hidden\n")

        result = self.run_context("--json", check=False)
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(payload["config"]["project_doc_max_bytes"], 12)
        self.assertEqual(
            payload["config"]["project_doc_fallback_filenames"], ["GUIDANCE.md"]
        )
        self.assertTrue(payload["truncated"])
        self.assertEqual(Path(payload["truncation"]["path"]), nested)
        self.assertEqual(payload["truncation"]["byte_offset"], 0)
        self.assertEqual(payload["truncation"]["line"], 1)
        self.assertEqual(
            payload["truncation"]["headings_hidden"],
            ["# Visible", "## Hidden", "# Deeper hidden"],
        )
        self.assertNotIn("do-not-print-me", result.stdout)

    def test_partial_file_cut_reports_hidden_headings_and_check_failure(self):
        (self.codex_home / "config.toml").write_text("project_doc_max_bytes = 11\n")
        document = self.project / "AGENTS.md"
        document.write_text("# Seen\nabc\n## Hidden\n")

        result = self.run_context("--json", "--check", check=False)
        payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["truncation"]["path"], str(document.resolve()))
        self.assertEqual(payload["truncation"]["byte_offset"], 11)
        self.assertEqual(payload["truncation"]["line"], 3)
        self.assertEqual(payload["truncation"]["headings_hidden"], ["## Hidden"])

    def test_check_succeeds_without_truncation_and_plain_report_is_concise(self):
        (self.project / "AGENTS.md").write_text("# Small\n")

        result = self.run_context("--check")

        self.assertIn("Codex instruction context", result.stdout)
        self.assertIn("project: 1 file, 8/32768 bytes", result.stdout)
        self.assertIn("truncation: none", result.stdout)
        self.assertLess(len(result.stdout.splitlines()), 12)

    def test_reports_duplicate_selected_content(self):
        content = "# Same\n"
        global_document = self.codex_home / "AGENTS.md"
        project_document = self.project / "AGENTS.md"
        global_document.write_text(content)
        project_document.write_text(content)

        payload = self.payload()

        self.assertEqual(
            payload["duplicates"],
            [[str(global_document.resolve()), str(project_document.resolve())]],
        )

    def test_rejects_unsupported_client_without_traceback(self):
        result = subprocess.run(
            [TOOL, "claude", self.cwd],
            check=False,
            text=True,
            capture_output=True,
            env={**os.environ, "CODEX_HOME": str(self.codex_home)},
        )

        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
