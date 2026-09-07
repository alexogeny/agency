import argparse
from contextlib import redirect_stdout, redirect_stderr
import csv
import io
import json
from pathlib import Path
import runpy
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch


INGEST = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'Tools' / 'evidence-review'))['ingest']


class EvidenceReviewIngestMemoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.args = argparse.Namespace(output=self.root / 'out' / 'ledger.csv', input=[],
            records_key=None, start=7, id_prefix='R', source='fixture', json=True)

    def input(self, name, records):
        path = self.root / name
        path.write_text('\n'.join(json.dumps(record) for record in records))
        self.args.input.append(path)
        return path

    def run_ingest(self):
        output = io.StringIO()
        with redirect_stdout(output):
            INGEST(self.args)
        return output.getvalue()

    def test_normalized_rows_are_written_before_more_are_converted(self):
        self.input('records.jsonl', [{'title': f'Study {i}'} for i in range(1000)])
        converted = written = 0
        normalize = INGEST.__globals__['normalise_title']
        original = csv.DictWriter._dict_to_list

        def count_conversion(title):
            nonlocal converted
            converted += 1
            return normalize(title)

        def check_write(writer, row):
            nonlocal written
            if row['source_id'] != 'source_id':
                written += 1
                self.assertLessEqual(converted - written, 0)
            return original(writer, row)

        with patch.dict(INGEST.__globals__, normalise_title=count_conversion), patch.object(csv.DictWriter, '_dict_to_list', check_write):
            self.run_ingest()
        self.assertEqual((converted, written), (1000, 1000))

    def test_normalized_ledger_is_not_retained_after_writes(self):
        self.input('records.jsonl', [])
        records = [{'title': 'Same study', 'doi': '10.1/same'}] * 2000
        with patch.dict(INGEST.__globals__, load_records=lambda *args: records):
            tracemalloc.start()
            try:
                self.run_ingest()
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
        self.assertLess(peak, 500_000)

    def test_cross_file_duplicates_ids_fields_and_summary(self):
        self.input('one.jsonl', [{'title': ' First study! ', 'doi': 'https://doi.org/10.1/ABC', 'authors': ['A', 'B'], 'date': 'Jan 2024', 'id': 3}])
        self.input('two.jsonl', [{'article_title': 'Another', 'doi': 'DOI: 10.1/abc.'}, {'name': 'FIRST study'}, {'title': 'Unique', 'link': 'https://example.org'}])
        summary = json.loads(self.run_ingest())
        self.assertEqual(summary, {'records': 4, 'duplicates': 2, 'output': str(self.args.output)})
        with self.args.output.open(newline='') as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([r['source_id'] for r in rows], ['R007', 'R008', 'R009', 'R010'])
        self.assertEqual([r['duplicate_of'] for r in rows], ['', 'R007', 'R007', ''])
        self.assertEqual([rows[0][k] for k in ('title', 'doi', 'authors', 'year', 'discovery_record_id')], ['First study!', '10.1/abc', 'A; B', '2024', '3'])
        self.assertTrue(all(r['discovery_source'] == 'fixture' and r['full_text_decision'] == 'pending' for r in rows))

    def test_invalid_later_input_does_not_create_output(self):
        self.input('valid.jsonl', [{'title': 'Valid'}])
        bad = self.input('bad.jsonl', [])
        for text, error in (('{broken', json.JSONDecodeError), ('[]', SystemExit)):
            bad.write_text(text)
            with redirect_stderr(io.StringIO()), self.assertRaises(error):
                self.run_ingest()
            self.assertFalse(self.args.output.parent.exists())

    def test_empty_missing_and_existing_output(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_ingest()
        self.assertFalse(self.args.output.parent.exists())
        self.args.input = [self.root / 'missing.jsonl']
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_ingest()
        self.assertFalse(self.args.output.parent.exists())
        self.args.output.parent.mkdir()
        self.args.output.write_text('untouched')
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_ingest()
        self.assertEqual(self.args.output.read_text(), 'untouched')

    def test_plain_summary(self):
        self.input('one.jsonl', [{'title': 'Study'}])
        self.args.json = False
        self.assertEqual(self.run_ingest(), f'Wrote 1 records to {self.args.output}\n')
