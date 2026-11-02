"""Red resource contracts from the expanded subsystem review.

Counters measure calls, characters copied/scanned, live payloads and read sizes.
External tools are stubbed: no network, real Git subprocess, PDF rendering, or
large image decoding is performed. These are acceptance budgets, not timings.
"""
import argparse
import contextlib
import csv
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import weakref

TOOLS = Path(__file__).resolve().parents[1] / 'Tools'
sys.path.insert(0, str(TOOLS))
import research_corpus_core as core
import web_research_owned_profiles as profiles


def load_tool(name):
    identity = 'budget_' + name.replace('-', '_')
    loader = importlib.machinery.SourceFileLoader(identity, str(TOOLS / name))
    spec = importlib.util.spec_from_loader(identity, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[identity] = module
    loader.exec_module(module)
    return module


report = load_tool('report-build')
documents = load_tool('document-inspect')
evidence = load_tool('evidence-review')
mapper = load_tool('repo-map')
work = load_tool('agent-work')


class ReadObserver:
    def __init__(self, stream, sizes):
        self.stream, self.sizes = stream, sizes

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def read(self, *args, **kwargs):
        data = self.stream.read(*args, **kwargs)
        self.sizes.append(len(data))
        return data


class AdditionalResourceBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def test_unmatched_html_end_tags_do_not_rescan_entire_open_stack(self):
        def workload(n):
            comparisons = 0

            class Tag(str):
                def __eq__(self, other):
                    nonlocal comparisons
                    comparisons += 1
                    return super().__eq__(other)

            parser = report.ReportHtmlParser()
            parser.feed('<div>' * n)
            for node in parser.stack:
                node.tag = Tag(node.tag)
            parser.feed('</unknown>' * n)
            self.assertEqual(len(parser.stack), n + 1)
            self.assertEqual(parser.root.children[0].tag, 'div')
            parser.feed('</div>' * n)
            self.assertEqual(len(parser.stack), 1)
            return comparisons

        small, large = workload(64), workload(128)
        self.assertLessEqual(large, small * 2.6,
                             f'Doubled HTML depth/closers compared tags {large}/{small} times')

    def test_pdf_span_merging_does_not_copy_growing_prefix_for_each_fragment(self):
        def workload(n):
            copied = 0

            class Text(str):
                def __add__(self, other):
                    nonlocal copied
                    copied += len(self) + len(other)
                    return Text(super().__add__(other))

            renderer = object.__new__(report.NativePdfRenderer)
            line = []
            for _ in range(n):
                renderer.append_line_span(line, {'text': Text('word '), 'style': 'regular'})
            self.assertEqual(''.join(span['text'] for span in line), 'word ' * n)
            return copied

        small, large = workload(64), workload(128)
        self.assertLessEqual(large, 2.6 * small,
                             f'Doubled fragments copied {large}/{small} characters')

    def test_png_dimensions_are_budgeted_before_decompression(self):
        path = self.base / 'oversized.png'
        header = struct.pack('>IIBBBBB', 16_777_217, 1, 8, 2, 0, 0, 0)
        # Header preflight must reject these dimensions before any decoder work.
        path.write_bytes(b'\x89PNG\r\n\x1a\n' + struct.pack('>I', len(header)) + b'IHDR' + header + b'\0' * 4)
        with patch.object(report.zlib, 'decompressobj', side_effect=ValueError('decoder reached')) as decoder:
            with self.assertRaises(ValueError):
                report.PdfImage(path)
        self.assertEqual(decoder.call_count, 0,
                         'Over-budget PNG dimensions reached the decompressor')

    def test_document_subprocesses_have_finite_deadlines(self):
        result = types.SimpleNamespace(returncode=0, stdout='Pages: 1\n', stderr='')
        with patch.object(documents.subprocess, 'run', return_value=result) as run:
            self.assertEqual(documents.checked_output(['pdfinfo', 'fixture.pdf'], 'failed'), result.stdout)
        timeout = run.call_args.kwargs.get('timeout')
        self.assertTrue(isinstance(timeout, (int, float)) and 0 < timeout <= 300,
                        f'Document subprocess has no bounded deadline: {timeout!r}')

    def test_git_repository_discovery_has_finite_deadline(self):
        result = types.SimpleNamespace(returncode=0, stdout='/fixture/repository\n')
        with patch.object(work.subprocess, 'run', return_value=result) as run:
            self.assertEqual(work.git_value(self.base, 'rev-parse', '--show-toplevel'), '/fixture/repository')
        timeout = run.call_args.kwargs.get('timeout')
        self.assertTrue(isinstance(timeout, (int, float)) and 0 < timeout <= 10,
                        f'Coordination Git discovery has no bounded deadline: {timeout!r}')

    def test_contact_sheet_limits_image_fan_in_per_invocation(self):
        pages = [(i, self.base / f'page-{i}.png') for i in range(128)]
        destination = self.base / 'sheet.png'
        with patch.object(documents, 'required_command', return_value='montage'), \
                patch.object(documents, 'checked_output', return_value='') as calls:
            documents.make_contact_sheet(pages, destination)
        commands = [call.args[0] for call in calls.call_args_list]
        self.assertTrue(commands)
        self.assertEqual(commands[-1][-1], str(destination))
        inputs = {str(path) for _, path in pages}
        self.assertEqual({arg for command in commands for arg in command if arg in inputs}, inputs)
        peak = max(sum(arg in inputs for arg in command) for command in commands)
        self.assertLessEqual(peak, 32, f'One montage invocation receives {peak} full-sized page images')

    def test_ocr_export_does_not_retain_every_page_body(self):
        refs = []
        peak = 0

        class Body(str):
            def rstrip(self, *args):
                return self if super().rstrip(*args) == self else Body(super().rstrip(*args))

        def ocr(command, failure):
            nonlocal peak
            body = Body((f'Page {len(refs)} ' + 'evidence ' * 1024).rstrip())
            refs.append(weakref.ref(body))
            peak = max(peak, sum(ref() is not None for ref in refs))
            return body

        destination = self.base / 'ocr.txt'
        pages = [(i, self.base / f'page-{i}.png') for i in range(16)]
        with patch.object(documents, 'required_command', return_value='tesseract'), \
                patch.object(documents, 'checked_output', side_effect=ocr):
            documents.extract_ocr(pages, destination, 'eng')
        self.assertEqual(destination.read_text(), '\n\f\n'.join(
            (f'Page {i} ' + 'evidence ' * 1024).rstrip() for i in range(16)) + '\n')
        self.assertEqual(len(refs), 16)
        self.assertLessEqual(peak, 2, f'OCR export retains {peak} full page bodies')

    def test_json_evidence_iterator_does_not_decode_all_records_before_yielding(self):
        path = self.base / 'records.json'
        path.write_text(json.dumps([{'title': f'Paper {i}', 'abstract': 'evidence ' * 1024} for i in range(32)]))
        refs = []
        peak = 0
        original = evidence.json.loads

        class Row(dict):
            pass

        def track(pairs):
            nonlocal peak
            row = Row(pairs)
            refs.append(weakref.ref(row))
            peak = max(peak, sum(ref() is not None for ref in refs))
            return row

        def decode(raw, **kwargs):
            return original(raw, object_pairs_hook=track, **kwargs)

        with patch.object(evidence.json, 'loads', side_effect=decode):
            titles = [row['title'] for row in evidence.iter_records(path, None)]
        self.assertEqual(titles, [f'Paper {i}' for i in range(32)])
        self.assertLessEqual(peak, 3, f'JSON evidence iterator retains {peak} decoded record bodies')

    def test_evidence_audit_retains_ids_instead_of_full_csv_rows(self):
        ledger = self.base / 'ledger.csv'
        with ledger.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=evidence.FIELDS)
            writer.writeheader()
            for i in range(32):
                writer.writerow({'source_id': f'source-{i}', 'title': f'Paper {i}',
                                 'duplicate_of': 'source-31' if i == 0 else '', 'notes': 'notes ' * 1024})
        refs = []
        peak = 0
        original = evidence.csv.DictReader

        class Row(dict):
            pass

        class Reader:
            def __init__(self, *args, **kwargs):
                self.reader = original(*args, **kwargs)

            @property
            def fieldnames(self):
                return self.reader.fieldnames

            def __iter__(self):
                nonlocal peak
                for value in self.reader:
                    row = Row(value)
                    refs.append(weakref.ref(row))
                    peak = max(peak, sum(ref() is not None for ref in refs))
                    yield row

        output = io.StringIO()
        with patch.object(evidence.csv, 'DictReader', Reader), contextlib.redirect_stdout(output):
            evidence.audit(argparse.Namespace(ledger=ledger, output=None, json=True))
        result = json.loads(output.getvalue())
        self.assertTrue(result['valid'])
        self.assertEqual(result['counts']['records'], 32)
        self.assertEqual(result['counts']['duplicates'], 1)
        self.assertLessEqual(peak, 3, f'Evidence audit retains {peak} complete rows including notes')

    def test_oversized_shebang_does_not_bypass_repo_map_parse_budget(self):
        relative = Path('extensionless-script')
        data = b'#!/usr/bin/python ' + b'x' * 262144
        (self.base / relative).write_bytes(data)
        name, retained, kind, digest, size = mapper.read_file(self.base, relative, max_bytes=1024)
        self.assertEqual((name, kind, size), (str(relative), 'file', len(data)))
        self.assertEqual(digest, hashlib.sha256(data).hexdigest())
        self.assertTrue(retained.startswith(b'#!'))
        self.assertLessEqual(len(retained), 1024,
                             f'Oversized shebang retained {len(retained)} bytes despite 1024-byte parse budget')

    def test_record_size_gate_precedes_whole_artifact_hash_read(self):
        root = self.base / 'corpus'
        root.mkdir()
        data = json.dumps({'padding': 'x' * 16384}).encode()
        path = root / 'record.json'
        path.write_bytes(data)
        entry = {'record_id': 'r', 'paths': {'json': path.name},
                 'hashes': {path.name: hashlib.sha256(data).hexdigest()}}
        sizes = []
        original = Path.open

        def observe(candidate, *args, **kwargs):
            stream = original(candidate, *args, **kwargs)
            return ReadObserver(stream, sizes) if candidate == path else stream

        with patch.object(core, 'MAX_BYTES', 1024), patch.object(Path, 'open', observe):
            with self.assertRaises(core.CorpusError) as caught:
                core.load_record(root, entry)
        self.assertEqual(caught.exception.code, 'response-too-large')
        self.assertLessEqual(max(sizes, default=0), 4097,
                             f'Oversized record read {max(sizes, default=0)} bytes before size rejection')

    def test_profile_process_inspection_bounds_cmdline_reads(self):
        proc = self.base / 'proc'
        process = proc / '123'
        process.mkdir(parents=True)
        cmdline = process / 'cmdline'
        cmdline.write_bytes(b'harmless-command\0' + b'x' * 262144)
        original_path, original_open = profiles.Path, Path.open
        sizes = []

        def path(value):
            return proc if value == '/proc' else original_path(value)

        def observe(candidate, *args, **kwargs):
            stream = original_open(candidate, *args, **kwargs)
            return ReadObserver(stream, sizes) if candidate == cmdline else stream

        with patch.object(profiles, 'Path', side_effect=path), patch.object(Path, 'open', observe):
            profiles.active_processes(self.base / 'profile')
            cmdline.write_bytes(b'/usr/bin/firefox\0' + b'x' * 262144
                                + b'\0--profile=' + os.fsencode(self.base / 'profile') + b'\0')
            with self.assertRaises(profiles.ProfileError) as caught:
                profiles.active_processes(self.base / 'profile')
            self.assertEqual(caught.exception.code, 'profile-active')
        self.assertTrue(sizes)
        self.assertLessEqual(max(sizes), 65536,
                             f'Profile inspection reads {max(sizes)} cmdline bytes into one allocation')


if __name__ == '__main__':
    unittest.main()
