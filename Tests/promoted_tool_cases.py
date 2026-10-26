import csv
import json
import os
import subprocess
import sys
import textwrap

from Tests.promoted_tool_support import TOOLS


class PromotedToolCases:
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

    def test_docs_exec_bounds_case_runtime_and_captured_output(self):
        documentation = self.workspace / "bounded.md"
        documentation.write_text('```text title="input.txt"\nfixture\n```\n')
        manifest = self.workspace / "docs-exec-bounded.toml"
        manifest.write_text(
            "schema_version = 1\n\n"
            f'root = "{self.workspace}"\n\n'
            "[[case]]\n"
            'name = "bounded"\n'
            'document = "bounded.md"\n'
            'files = { "input.txt" = "input.txt" }\n'
            f'command = ["{sys.executable}", "-c", '
            '"import sys,time; print(\'x\' * 10000); sys.stdout.flush(); time.sleep(2)"]\n'
            "timeout_seconds = 0.2\n"
            "max_output_bytes = 1024\n"
        )
        output = self.workspace / "bounded-results.json"

        result = self.run_tool(
            "docs-exec", manifest, "--output", output, "--json", check=False
        )

        report = json.loads(result.stdout)
        case = report["cases"][0]
        self.assertEqual(result.returncode, 1)
        self.assertEqual(case["status"], "timed-out")
        self.assertTrue(case["stdout_truncated"])
        self.assertLessEqual(len(case["stdout"].encode()), 1024)

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

    def test_resource_bench_keeps_direct_resource_wins_first_class(self):
        self.executable(
            "perf",
            """
            #!/usr/bin/env python3
            import pathlib
            import subprocess
            import sys

            if sys.argv[1:] == ["--version"]:
                print("perf version fixture")
                raise SystemExit
            destination = pathlib.Path(sys.argv[sys.argv.index("-o") + 1])
            events = [
                sys.argv[index + 1]
                for index, value in enumerate(sys.argv)
                if value == "-e"
            ]
            destination.write_text(
                "".join(f"100000\\t\\t{event}\\n" for event in events)
            )
            command = sys.argv[sys.argv.index("--") + 1 :]
            raise SystemExit(subprocess.run(command, check=False).returncode)
            """,
        )
        workload = self.executable(
            "measured-workload",
            """
            #!/usr/bin/env python3
            import json
            import os
            import pathlib

            pathlib.Path("metrics.json").write_text(
                json.dumps({"allocated_bytes": int(os.environ["ALLOCATED_BYTES"])})
            )
            print("equivalent output")
            """,
        )
        spec = self.workspace / "resource-bench.toml"
        spec.write_text(
            textwrap.dedent(
                f"""
                name = "allocation reduction"
                cpu = {min(os.sched_getaffinity(0))}
                runs = 3
                warmups = 1
                primary_metric = "allocated_bytes"

                [[metrics]]
                name = "instructions"
                source = "perf"
                event = "instructions:u"
                unit = "instructions"
                direction = "lower"

                [[metrics]]
                name = "allocated_bytes"
                source = "json"
                key = "allocated_bytes"
                unit = "bytes"
                direction = "lower"
                method = "fixture cumulative allocation counter"

                [baseline]
                command = ["{workload}"]
                cwd = "{self.workspace}"
                metrics_file = "metrics.json"
                environment = {{ ALLOCATED_BYTES = "8388608" }}

                [candidate]
                command = ["{workload}"]
                cwd = "{self.workspace}"
                metrics_file = "metrics.json"
                environment = {{ ALLOCATED_BYTES = "1048576" }}
                """
            ).lstrip()
        )
        output = self.workspace / "result.json"
        environment = {"PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}"}

        self.run_tool(
            "resource-bench", spec, "--output", output, environment=environment
        )

        report = json.loads(output.read_text())
        self.assertEqual(report["schema"], "agency/resource-bench/1")
        self.assertEqual(report["primary_metric"], "allocated_bytes")
        allocation = report["metrics"]["allocated_bytes"]
        self.assertEqual(
            allocation["method"], "fixture cumulative allocation counter"
        )
        self.assertEqual(allocation["absolute_change"], -7 * 1024 * 1024)
        self.assertEqual(allocation["improvement_percent"], 87.5)
        self.assertEqual(
            report["metrics"]["instructions"]["improvement_percent"], 0.0
        )

    def test_resource_bench_samples_process_tree_rss_and_pss(self):
        workload = self.executable(
            "memory-workload",
            """
            #!/usr/bin/env python3
            import os
            import time

            payload = bytearray(int(os.environ["PAYLOAD_BYTES"]))
            for offset in range(0, len(payload), 4096):
                payload[offset] = 1
            time.sleep(0.04)
            print("equivalent output")
            """,
        )
        spec = self.workspace / "memory-bench.toml"
        spec.write_text(
            textwrap.dedent(
                f"""
                name = "resident footprint reduction"
                cpu = {min(os.sched_getaffinity(0))}
                runs = 3
                warmups = 1
                sample_interval_ms = 2
                primary_metric = "peak_pss_bytes"

                [[metrics]]
                name = "peak_rss_bytes"
                source = "procfs"
                field = "rss"
                unit = "bytes"
                direction = "lower"

                [[metrics]]
                name = "peak_pss_bytes"
                source = "procfs"
                field = "pss"
                unit = "bytes"
                direction = "lower"

                [baseline]
                command = ["{workload}"]
                environment = {{ PAYLOAD_BYTES = "16777216" }}

                [candidate]
                command = ["{workload}"]
                environment = {{ PAYLOAD_BYTES = "1048576" }}
                """
            ).lstrip()
        )
        output = self.workspace / "memory-result.json"

        self.run_tool("resource-bench", spec, "--output", output)

        report = json.loads(output.read_text())
        pss = report["metrics"]["peak_pss_bytes"]
        rss = report["metrics"]["peak_rss_bytes"]
        self.assertGreater(pss["baseline"]["median"], pss["candidate"]["median"])
        self.assertGreater(rss["baseline"]["median"], rss["candidate"]["median"])
        self.assertEqual(pss["scope"], "benchmark process tree")
        self.assertTrue(all(item["procfs_samples"] for item in report["raw_order"]))

    def test_resource_bench_rejects_stale_json_metrics(self):
        workload = self.executable(
            "stale-metric-workload",
            """
            #!/usr/bin/env python3
            print("equivalent output")
            """,
        )
        (self.workspace / "metrics.json").write_text('{"allocated_bytes": 1}')
        spec = self.workspace / "stale-metric.toml"
        spec.write_text(
            textwrap.dedent(
                f"""
                name = "stale metric rejection"
                cpu = {min(os.sched_getaffinity(0))}
                runs = 3
                warmups = 1
                primary_metric = "allocated_bytes"

                [[metrics]]
                name = "allocated_bytes"
                source = "json"
                key = "allocated_bytes"
                unit = "bytes"
                method = "fixture cumulative allocation counter"

                [baseline]
                command = ["{workload}"]
                cwd = "{self.workspace}"
                metrics_file = "metrics.json"

                [candidate]
                command = ["{workload}"]
                cwd = "{self.workspace}"
                metrics_file = "metrics.json"
                """
            ).lstrip()
        )

        result = self.run_tool("resource-bench", spec, check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not change during the measured run", result.stderr)

    def test_resource_bench_rejects_stale_result_evidence(self):
        workload = self.executable(
            "metric-only-workload",
            """
            #!/usr/bin/env python3
            import pathlib
            import time

            pathlib.Path("metrics.json").write_text('{"operations": 1}')
            time.sleep(0.01)
            """,
        )
        (self.workspace / "result.txt").write_text("stale equivalent output")
        spec = self.workspace / "stale-result.toml"
        spec.write_text(
            textwrap.dedent(
                f"""
                name = "stale result rejection"
                cpu = {min(os.sched_getaffinity(0))}
                runs = 3
                warmups = 1
                primary_metric = "operations"

                [[metrics]]
                name = "operations"
                source = "json"
                key = "operations"
                unit = "operations"
                method = "fixture operation counter"

                [baseline]
                command = ["{workload}"]
                cwd = "{self.workspace}"
                result_file = "result.txt"
                metrics_file = "metrics.json"

                [candidate]
                command = ["{workload}"]
                cwd = "{self.workspace}"
                result_file = "result.txt"
                metrics_file = "metrics.json"
                """
            ).lstrip()
        )

        result = self.run_tool("resource-bench", spec, check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("result_file", result.stderr)
        self.assertIn("did not change during the run", result.stderr)

    def test_resource_bench_rejects_memory_samples_without_measured_child(self):
        self.executable(
            "perf",
            """
            #!/usr/bin/env python3
            import pathlib
            import sys
            import time

            if sys.argv[1:] == ["--version"]:
                print("perf version fixture")
                raise SystemExit
            destination = pathlib.Path(sys.argv[sys.argv.index("-o") + 1])
            destination.write_text("100000\\t\\tinstructions:u\\n")
            time.sleep(0.03)
            print("equivalent output")
            """,
        )
        spec = self.workspace / "missed-child.toml"
        spec.write_text(
            textwrap.dedent(
                f"""
                name = "missed child rejection"
                cpu = {min(os.sched_getaffinity(0))}
                runs = 3
                warmups = 1
                sample_interval_ms = 2
                primary_metric = "peak_pss_bytes"

                [[metrics]]
                name = "instructions"
                source = "perf"
                event = "instructions:u"
                unit = "instructions"

                [[metrics]]
                name = "peak_pss_bytes"
                source = "procfs"
                field = "pss"
                unit = "bytes"

                [baseline]
                command = ["python", "-c", "print('equivalent output')"]

                [candidate]
                command = ["python", "-c", "print('equivalent output')"]
                """
            ).lstrip()
        )
        environment = {"PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}"}

        result = self.run_tool(
            "resource-bench", spec, check=False, environment=environment
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("never observed the measured child process", result.stderr)

    def test_instruction_bench_resolves_resource_bench_through_its_symlink(self):
        installed = self.workspace / "installed" / "instruction-bench"
        installed.parent.mkdir()
        installed.symlink_to(TOOLS / "instruction-bench")

        result = subprocess.run(
            [installed, "--help"], text=True, capture_output=True, check=False
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("claim-matched resource metrics", result.stdout)

    def test_instruction_bench_preserves_its_instruction_only_json_schema(self):
        self.executable(
            "perf",
            """
            #!/usr/bin/env python3
            import pathlib
            import subprocess
            import sys

            if sys.argv[1:] == ["--version"]:
                print("perf version fixture")
                raise SystemExit
            destination = pathlib.Path(sys.argv[sys.argv.index("-o") + 1])
            destination.write_text("100000\\t\\tinstructions:u\\n")
            command = sys.argv[sys.argv.index("--") + 1 :]
            raise SystemExit(subprocess.run(command, check=False).returncode)
            """,
        )
        spec = self.workspace / "legacy-instruction-bench.toml"
        spec.write_text(
            textwrap.dedent(
                f"""
                name = "legacy instruction comparison"
                cpu = {min(os.sched_getaffinity(0))}
                runs = 3
                warmups = 1

                [baseline]
                command = ["python", "-c", "print('equivalent output')"]

                [candidate]
                command = ["python", "-c", "print('equivalent output')"]
                """
            ).lstrip()
        )
        installed = self.workspace / "installed" / "instruction-bench"
        installed.parent.mkdir()
        installed.symlink_to(TOOLS / "instruction-bench")
        environment = {
            **os.environ,
            "PATH": f"{self.workspace / 'bin'}:{os.environ['PATH']}",
        }

        result = subprocess.run(
            [installed, spec, "--json"],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema"], 1)
        self.assertEqual(report["metric"], "retired userspace instructions")
        self.assertEqual(report["baseline"]["samples"], [100000] * 3)
        self.assertIsInstance(report["baseline"]["samples"][0], int)
        self.assertEqual(report["raw_order"][0]["instructions"], 100000)
        self.assertNotIn("metrics", report)

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
