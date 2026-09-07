import csv
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest


TOOL = Path(__file__).resolve().parents[1] / "Tools" / "evidence-review"
FIELDS = runpy.run_path(str(TOOL))["FIELDS"]


class EvidenceReviewShortRowsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.ledger = Path(temporary.name) / "ledger.csv"

    def audit(self, fields, rows):
        with self.ledger.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(fields)
            writer.writerows(rows)
        result = subprocess.run(
            [sys.executable, str(TOOL), "audit", str(self.ledger), "--json"],
            text=True, capture_output=True,
        )
        self.assertEqual(result.stderr, "")
        return result.returncode, json.loads(result.stdout)

    def test_short_row_reports_missing_title_and_pending_decisions(self):
        status, report = self.audit(FIELDS, [["S001"]])
        self.assertEqual(status, 1)
        self.assertFalse(report["valid"])
        self.assertEqual(report["issues"], [{"row": 2, "field": "title", "message": "title is empty"}])
        self.assertEqual(report["counts"], {
            "records": 1, "duplicates": 0,
            "title_abstract": {"pending": 1}, "full_text": {"pending": 1},
        })

    def test_short_rows_match_explicit_empty_fields_in_issue_and_count_order(self):
        rows = [
            ["S001"],
            ["S002", "Study", "", "", "", "", "", "", "unknown", "exclude"],
            ["S003", "Study", "", "", "", "", "", "", "", "include", "", "exclude"],
        ]
        padded = [row + [""] * (len(FIELDS) - len(row)) for row in rows]
        expected = self.audit(FIELDS, padded)
        actual = self.audit(FIELDS, rows)
        self.assertEqual(actual, expected)
        self.assertEqual(actual[0], 1)
        self.assertEqual([issue["field"] for issue in actual[1]["issues"]],
                         ["title", "duplicate_of", "title_abstract_reason", "full_text_reason"])

    def test_missing_headers_keep_existing_issues_first(self):
        expected = self.audit(["source_id", "title"], [["S001", ""]])
        actual = self.audit(["source_id", "title"], [["S001"]])
        self.assertEqual(actual, expected)
        self.assertEqual(actual[0], 1)
        self.assertIsNone(actual[1]["issues"][0]["row"])
        self.assertTrue(actual[1]["issues"][0]["message"].startswith("missing fields:"))
        self.assertEqual(actual[1]["issues"][1]["field"], "title")

    def test_present_title_and_unscreened_decisions_remain_valid(self):
        row = ["S001", "Study"]
        expected = self.audit(FIELDS, [row + [""] * (len(FIELDS) - len(row))])
        actual = self.audit(FIELDS, [row])
        self.assertEqual(actual, expected)
        self.assertEqual(actual[0], 0)
        self.assertTrue(actual[1]["valid"])


if __name__ == "__main__":
    unittest.main()
