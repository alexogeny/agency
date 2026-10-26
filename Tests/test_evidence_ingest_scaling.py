import argparse
import contextlib
import csv
import io
import json
from pathlib import Path
import runpy
import tempfile
import tracemalloc
import unittest
from unittest import mock

TOOL = Path(__file__).resolve().parents[1] / 'Tools/evidence-review'
evidence = runpy.run_path(str(TOOL))


class EvidenceIngestScalingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.args = argparse.Namespace(input=[], output=self.root/'out'/'ledger.csv', records_key=None,
                                      start=7, id_prefix='R', source='fixture', json=True)

    def run_ingest(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            evidence['ingest'](self.args)
        return json.loads(output.getvalue())

    def test_jsonl_reader_does_not_parse_next_record_before_current_is_written(self):
        path = self.root/'input.jsonl'
        path.write_text('\n'.join(json.dumps({'title':f'Study {i}'}) for i in range(512)))
        self.args.input = [path]
        parsed = written = 0
        original_loads = json.loads
        original_write = csv.DictWriter.writerow
        def loads(*args, **kwargs):
            nonlocal parsed
            parsed += 1
            return original_loads(*args, **kwargs)
        def write(writer, row):
            nonlocal written
            if row['source_id'] != 'source_id':
                written += 1
                self.assertLessEqual(parsed - written, 1)
            return original_write(writer, row)
        with mock.patch.object(json, 'loads', side_effect=loads), mock.patch.object(csv.DictWriter,'writerow',write):
            result = self.run_ingest()
        self.assertEqual(written, 512)
        self.assertEqual(result['records'], 512)

    def test_retained_input_allocation_does_not_grow_with_large_duplicate_records(self):
        for suffix in ('jsonl','csv'):
            with self.subTest(suffix=suffix):
                path = self.root/f'input.{suffix}'
                record = {'title':'Same','doi':'10.1/same','unused':'x'*4096}
                with path.open('w') as handle:
                    if suffix == 'jsonl':
                        for _ in range(2048):
                            handle.write(json.dumps(record)+'\n')
                    else:
                        writer = csv.DictWriter(handle,fieldnames=record)
                        writer.writeheader()
                        for _ in range(2048):
                            writer.writerow(record)
                self.args.input = [path]
                self.args.output = self.root/f'ledger-{suffix}.csv'
                tracemalloc.start()
                try:
                    result = self.run_ingest()
                    peak = tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()
                self.assertEqual(result['duplicates'], 2047)
                self.assertLess(peak, 1_000_000, f'{suffix} retained {peak} traced bytes')

    def test_late_parse_failure_or_empty_input_never_publishes_partial_ledger(self):
        path = self.root/'bad.jsonl'
        self.args.input = [path]
        for text, error in (('{"title":"valid"}\n{bad', json.JSONDecodeError), ('\n[]', SystemExit), ('\n', SystemExit)):
            with self.subTest(text=text):
                path.write_text(text)
                before = set(self.root.iterdir())
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(error):
                    self.run_ingest()
                self.assertFalse(self.args.output.exists())
                self.assertFalse(self.args.output.parent.exists())
                self.assertEqual(set(self.root.iterdir()), before)

    def test_existing_output_is_never_overwritten(self):
        self.args.output.parent.mkdir()
        self.args.output.write_text('preserve')
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_ingest()
        self.assertEqual(self.args.output.read_text(), 'preserve')

    def test_publish_race_preserves_competing_destination_and_cleans_stage(self):
        path = self.root/'input.jsonl'
        path.write_text('{"title":"Valid"}\n')
        self.args.input = [path]
        real_link = evidence['ingest'].__globals__['os'].link
        def race(source, target):
            target.write_text('competing publisher')
            return real_link(source, target)
        with mock.patch.object(evidence['ingest'].__globals__['os'], 'link', side_effect=race), \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            self.run_ingest()
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(self.args.output.read_text(), 'competing publisher')
        self.assertFalse(any(path.name.startswith('.evidence-') for path in self.root.iterdir()))

    def test_mixed_file_order_bom_nested_json_dedup_and_output_permissions(self):
        csv_path = self.root/'one.csv'
        csv_path.write_text('\ufefftitle,doi\nAlpha study,https://doi.org/10.1/ABC\n')
        lines = self.root/'two.ndjson'
        lines.write_text('{"title":"ALPHA study!"}\n')
        nested = self.root/'three.json'
        nested.write_text('{"data":{"records":[null,{"title":"Beta","doi":"doi: 10.1/abc."},{"title":"Gamma"}]}}')
        self.args.input = [csv_path, lines, nested]
        self.args.records_key = 'data.records'
        result = self.run_ingest()
        with self.args.output.open(newline='') as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([row['source_id'] for row in rows], ['R007','R008','R009','R010'])
        self.assertEqual([row['duplicate_of'] for row in rows], ['', 'R007', 'R007', ''])
        self.assertEqual([row['title'] for row in rows], ['Alpha study','ALPHA study!','Beta','Gamma'])
        self.assertEqual(result['duplicates'], 2)
        reference = self.root/'normal-output'
        reference.write_text('reference')
        self.assertEqual(self.args.output.stat().st_mode & 0o777, reference.stat().st_mode & 0o777)

    def test_jsonl_bom_remains_a_parse_error_without_published_output(self):
        path = self.root/'bom.jsonl'
        path.write_text('\ufeff{"title":"BOM"}\n')
        self.args.input = [path]
        with self.assertRaises(json.JSONDecodeError):
            self.run_ingest()
        self.assertFalse(self.args.output.exists())
        self.assertFalse(self.args.output.parent.exists())


if __name__ == '__main__':
    unittest.main()
