import csv
import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "Tools"
SCRATCH = Path(os.environ.get("AGENCY_TEST_SCRATCH", ROOT / ".cache/tests"))


class PromotedToolTests(unittest.TestCase):
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

    def test_document_inspect_renders_extracts_and_manifests(self):
        document = self.workspace / "sample.pdf"
        document.write_bytes(b"%PDF-1.4\nfixture\n")
        output = self.workspace / "inspection"
        self.executable(
            "pdfinfo",
            """
            #!/usr/bin/env python3
            print("Title: Fixture")
            print("Pages: 2")
            print("Page size: 612 x 792 pts (letter)")
            """,
        )
        self.executable(
            "pdftoppm",
            """
            #!/usr/bin/env python3
            import pathlib
            import sys
            prefix = pathlib.Path(sys.argv[-1])
            for page in (1, 2):
                prefix.with_name(f"{prefix.name}-{page}.png").write_bytes(
                    f"page-{page}".encode()
                )
            """,
        )
        self.executable(
            "pdftotext",
            """
            #!/usr/bin/env python3
            import pathlib
            import sys
            pathlib.Path(sys.argv[-1]).write_text("first page\\fsecond page\\n")
            """,
        )
        self.executable(
            "montage",
            """
            #!/usr/bin/env python3
            import pathlib
            import sys
            pathlib.Path(sys.argv[-1]).write_bytes(b"contact-sheet")
            """,
        )
        environment = {
            "PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}"
        }

        result = self.run_tool(
            "document-inspect", document, "--output", output, "--json", environment=environment
        )

        manifest = json.loads(result.stdout)
        self.assertEqual(manifest["schema"], "agency/document-inspection/1")
        self.assertEqual(manifest["document"]["pages"], 2)
        self.assertEqual([page["number"] for page in manifest["page_images"]], [1, 2])
        self.assertEqual((output / "document.txt").read_text(), "first page\fsecond page\n")
        self.assertTrue((output / "contact-sheet.png").is_file())
        self.assertEqual(json.loads((output / "manifest.json").read_text()), manifest)

    def test_docs_exec_extracts_named_fences_and_runs_cases(self):
        documentation = self.workspace / "guide.md"
        documentation.write_text(
            '```python title="example.py"\nprint("rose")\n```\n\n'
            '```python title="check.py"\n'
            'from pathlib import Path\n'
            'assert Path("example.py").read_text() == \'print("rose")\\n\'\n'
            '```\n'
        )
        manifest = self.workspace / "docs-exec.toml"
        manifest.write_text(
            "schema_version = 1\n\n"
            f'root = "{self.workspace}"\n\n'
            "[[case]]\n"
            'name = "guide"\n'
            'document = "guide.md"\n'
            'files = { "example.py" = "example.py", "check.py" = "check.py" }\n'
            f'command = ["{sys.executable}", "check.py"]\n'
        )
        output = self.workspace / "docs-results.json"

        result = self.run_tool("docs-exec", manifest, "--output", output, "--json")

        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], "agency/docs-exec/1")
        self.assertEqual(report["cases"][0]["status"], "passed")
        self.assertEqual(report["cases"][0]["files"][0]["path"], "check.py")
        self.assertEqual(json.loads(output.read_text()), report)

    def test_evidence_review_ingests_exact_duplicates_and_audits_decisions(self):
        source = self.workspace / "records.csv"
        with source.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["id", "title", "year", "doi"])
            writer.writeheader()
            writer.writerows(
                [
                    {
                        "id": "a",
                        "title": "A Useful Study",
                        "year": "2025",
                        "doi": "10.1/ABC",
                    },
                    {
                        "id": "b",
                        "title": "Different title",
                        "year": "2025",
                        "doi": "https://doi.org/10.1/abc",
                    },
                    {
                        "id": "c",
                        "title": "A useful study",
                        "year": "2024",
                        "doi": "",
                    },
                ]
            )
        ledger = self.workspace / "ledger.csv"

        self.run_tool(
            "evidence-review",
            "ingest",
            source,
            "--source",
            "SEARCH-1",
            "--output",
            ledger,
        )

        with ledger.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([row["source_id"] for row in rows], ["S001", "S002", "S003"])
        self.assertEqual(rows[1]["duplicate_of"], "S001")
        self.assertEqual(rows[2]["duplicate_of"], "S001")
        rows[0]["title_abstract_decision"] = "include"
        rows[1]["title_abstract_decision"] = "exclude"
        rows[1]["title_abstract_reason"] = "Duplicate record"
        rows[2]["title_abstract_decision"] = "exclude"
        rows[2]["title_abstract_reason"] = "Duplicate record"
        with ledger.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        audit = self.workspace / "audit.json"

        result = self.run_tool(
            "evidence-review", "audit", ledger, "--output", audit, "--json"
        )

        report = json.loads(result.stdout)
        self.assertTrue(report["valid"])
        self.assertEqual(report["counts"]["duplicates"], 2)
        self.assertEqual(report["counts"]["title_abstract"]["exclude"], 2)

    def test_perf_diagnose_parses_delimited_stat_output(self):
        self.executable(
            "perf",
            """
            #!/usr/bin/env python3
            import pathlib
            import sys
            if sys.argv[1:] == ["--version"]:
                print("perf version fixture")
                raise SystemExit
            destination = pathlib.Path(sys.argv[sys.argv.index("-o") + 1])
            destination.write_text(
                "12345;;instructions:u;1;100.00;metric;unit\\n"
                "67;;cache-misses:u;1;100.00;;\\n"
            )
            """,
        )
        output = self.workspace / "perf.json"
        environment = {
            "PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}"
        }

        result = self.run_tool(
            "perf-diagnose",
            "stat",
            "--event",
            "instructions:u",
            "--event",
            "cache-misses:u",
            "--output",
            output,
            "--json",
            "--",
            sys.executable,
            "-c",
            "print(1)",
            environment=environment,
        )

        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], "agency/perf-diagnose/stat/1")
        self.assertEqual(report["events"][0]["count"], 12345)
        self.assertEqual(report["events"][1]["name"], "cache-misses:u")
        self.assertEqual(report["claim_boundary"], "diagnostic-only")

    def test_comment_audit_classifies_python_comments_and_docstrings(self):
        source = self.workspace / "sample.py"
        source.write_text(
            'address = "https://example.com"\n'
            '#\n'
            '# --- helpers ------------------------------------------------\n'
            'def run():\n'
            '    """Previously performed the old operation."""\n'
            '    return address\n'
        )

        result = self.run_tool("comment-audit", source, "--json")

        report = json.loads(result.stdout)
        categories = [finding["category"] for finding in report["findings"]]
        self.assertEqual(categories, ["empty-comment", "decorative-comment", "history-narration"])
        self.assertEqual(report["summary"]["files_scanned"], 1)
        self.assertEqual(report["summary"]["findings"], 3)

    def test_document_inspect_refuses_populated_output(self):
        document = self.workspace / "sample.pdf"
        document.write_bytes(b"%PDF-1.4\n")
        output = self.workspace / "inspection"
        output.mkdir()
        (output / "stale.png").write_bytes(b"stale")

        result = self.run_tool(
            "document-inspect", document, "--output", output, check=False
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("not empty", result.stderr)
        self.assertEqual((output / "stale.png").read_bytes(), b"stale")

    def test_docs_exec_fails_when_a_declared_fence_is_missing(self):
        documentation = self.workspace / "guide.md"
        documentation.write_text('```python title="other.py"\npass\n```\n')
        manifest = self.workspace / "docs-exec.toml"
        manifest.write_text(
            "schema_version = 1\n\n"
            "[[case]]\n"
            'name = "missing"\n'
            'document = "guide.md"\n'
            'files = { "example.py" = "example.py" }\n'
            f'command = ["{sys.executable}", "example.py"]\n'
        )

        result = self.run_tool(
            "docs-exec",
            manifest,
            "--output",
            self.workspace / "result.json",
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("no fenced block", result.stderr)

    def test_evidence_review_audit_refuses_unreasoned_exclusion(self):
        ledger = self.workspace / "ledger.csv"
        row = dict.fromkeys(
            (
                "source_id",
                "title",
                "year",
                "authors",
                "doi",
                "url",
                "discovery_source",
                "discovery_record_id",
                "duplicate_of",
                "title_abstract_decision",
                "title_abstract_reason",
                "full_text_decision",
                "full_text_reason",
                "notes",
            ),
            "",
        )
        row.update(
            source_id="S001",
            title="Study",
            title_abstract_decision="exclude",
            full_text_decision="pending",
        )
        with ledger.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)

        result = self.run_tool(
            "evidence-review", "audit", ledger, "--json", check=False
        )

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertFalse(report["valid"])
        self.assertIn("require a reason", report["issues"][0]["message"])

    def test_perf_diagnose_refuses_an_empty_command(self):
        result = self.run_tool(
            "perf-diagnose",
            "stat",
            "--output",
            self.workspace / "perf.json",
            "--",
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("command is required", result.stderr)

    def test_comment_audit_can_fail_on_findings(self):
        source = self.workspace / "sample.py"
        source.write_text("#\n")

        result = self.run_tool(
            "comment-audit", source, "--fail-on-findings", check=False
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("empty-comment", result.stdout)


if __name__ == "__main__":
    unittest.main()
