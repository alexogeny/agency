import argparse
import csv
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


ns = runpy.run_path(str(Path(__file__).resolve().parents[1] / "Tools" / "evidence-review"))


class EvidenceReviewAuditCountsTests(unittest.TestCase):
    def test_normalize_each_decision_and_duplicate_once(self):
        counts = {'strip': 0, 'casefold': 0, 'get': 0}

        class Value(str):

            def strip(self, *args):
                counts['strip'] += 1
                return Value(super().strip(*args))

            def casefold(self):
                counts['casefold'] += 1
                return Value(super().casefold())

        class Row(dict):

            def get(self, *args):
                counts['get'] += 1
                return super().get(*args)
        original = csv.DictReader

        class Reader:

            def __init__(self, *args, **kwargs):
                self.reader = original(*args, **kwargs)

            @property
            def fieldnames(self):
                return self.reader.fieldnames

            def __iter__(self):
                for row in self.reader:
                    yield Row({key: Value(value) if isinstance(value, str) else value for key, value in row.items()})
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Path(temporary) / 'ledger.csv'
            with ledger.open('w', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=ns['FIELDS'])
                writer.writeheader()
                writer.writerow({'source_id': 'S001', 'title': ' Study ', 'title_abstract_decision': ' Include ', 'full_text_decision': ' PENDING '})
            output = io.StringIO()
            with patch.object(csv, 'DictReader', Reader), redirect_stdout(output):
                ns['audit'](argparse.Namespace(ledger=ledger, output=None, json=True))
            self.assertEqual(json.loads(output.getvalue())['counts'], {'records': 1, 'duplicates': 0, 'title_abstract': {'include': 1}, 'full_text': {'pending': 1}})
            self.assertEqual(counts, {'strip': 4, 'casefold': 2, 'get': 5})

    def test_counts_and_issue_order_for_unsupported_decisions_and_duplicates(self):
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Path(temporary) / "ledger.csv"
            with ledger.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=ns["FIELDS"])
                writer.writeheader()
                writer.writerows([
                    {"source_id": "S1", "title": "First", "title_abstract_decision": " INCLUDE ", "full_text_decision": " "},
                    {"source_id": "S2", "title": "", "duplicate_of": " missing ", "title_abstract_decision": " UNKNOWN ", "full_text_decision": " ExClUdE "},
                ])
            output = io.StringIO()
            with redirect_stdout(output), self.assertRaises(SystemExit) as error:
                ns["audit"](argparse.Namespace(ledger=ledger, output=None, json=True))
            self.assertEqual(error.exception.code, 1)
            report = json.loads(output.getvalue())
            self.assertFalse(report["valid"])
            self.assertEqual(report["counts"], {
                "records": 2, "duplicates": 1,
                "title_abstract": {"include": 1, "unknown": 1},
                "full_text": {"exclude": 1, "pending": 1},
            })
            self.assertEqual(report["issues"], [
                {"row": 3, "field": "title", "message": "title is empty"},
                {"row": 3, "field": "duplicate_of", "message": "unknown source_id: missing"},
                {"row": 3, "field": "title_abstract_decision", "message": "unsupported decision: unknown"},
                {"row": 3, "field": "full_text_reason", "message": "excluded records require a reason"},
            ])

    def test_empty_ledger_preserves_empty_counters(self):
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Path(temporary) / "ledger.csv"
            with ledger.open("w", newline="") as handle:
                csv.writer(handle).writerow(ns["FIELDS"])
            output = io.StringIO()
            with redirect_stdout(output):
                ns["audit"](argparse.Namespace(ledger=ledger, output=None, json=True))
            report = json.loads(output.getvalue())
            self.assertTrue(report["valid"])
            self.assertEqual(report["issues"], [])
            self.assertEqual(report["counts"], {"records": 0, "duplicates": 0, "title_abstract": {}, "full_text": {}})


if __name__ == "__main__":
    unittest.main()
