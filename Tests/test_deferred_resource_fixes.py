"""Further deferred resource fixes: direct counters, bounded synthetic fixtures.

Read budgets constrain the largest materialized chunk, not total bytes read.
All hashes, counter values, code blocks and conflict classifications must stay
correct. TypeScript tests execute the current ReferenceStore class in Bun with
only its filesystem boundary instrumented; they do not launch MCP or browsers.
"""
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'Tools'
sys.path.insert(0, str(TOOLS))
import session_archive


def tool(name):
    identity = 'deferred_' + name.replace('-', '_')
    loader = importlib.machinery.SourceFileLoader(identity, str(TOOLS / name))
    spec = importlib.util.spec_from_loader(identity, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[identity] = module
    loader.exec_module(module)
    return module


report = tool('report-build')
docs = tool('docs-exec')
setup = tool('repository-setup')
bench = tool('resource-bench')
perf = tool('perf-diagnose')


class ObserveReads:
    def __init__(self, stream, sizes):
        self.stream, self.sizes = stream, sizes

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __iter__(self):
        return iter(self.stream)

    def read(self, *args, **kwargs):
        data = self.stream.read(*args, **kwargs)
        self.sizes.append(len(data))
        return data


class DeferredResourceFixTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    @contextlib.contextmanager
    def reads(self, path):
        sizes = []
        original = Path.open

        def observe(candidate, *args, **kwargs):
            stream = original(candidate, *args, **kwargs)
            return ObserveReads(stream, sizes) if candidate == path else stream

        with patch.object(Path, 'open', observe):
            yield sizes

    def assert_chunk_budget(self, sizes):
        self.assertLessEqual(max(sizes, default=0), 65536,
                             f'Largest materialized read was {max(sizes, default=0)} bytes; budget is 65536')

    def test_format_four_font_lookup_does_not_scan_all_segments_per_new_glyph(self):
        def workload(n):
            visits = 0

            class Segments(list):
                def __iter__(self):
                    nonlocal visits
                    for value in super().__iter__():
                        visits += 1
                        yield value

            font = object.__new__(report.TrueTypeFont)
            font.cmap_format = 4
            font.cmap = Segments((i, i, 1, 0, 0, b'') for i in range(n))
            font._glyph_cache = {}
            self.assertEqual([font.glyph(i) for i in range(n)], list(range(1, n + 1)))
            before = visits
            self.assertEqual(font.glyph(n - 1), n)
            self.assertEqual(visits, before, 'Repeated glyphs must still use the cache')
            return visits

        small, large = workload(64), workload(128)
        self.assertLessEqual(large, 2.6 * small,
                             f'Doubled unique glyphs/segments visited {large}/{small} segments')

    def test_docs_fence_extraction_streams_unrelated_prose(self):
        path = self.base / 'README.md'
        path.write_text('prose\n' * 65536 + '\n```python title="example.py"\nprint(42)\n```\n')
        with self.reads(path) as sizes:
            blocks = docs.fences(path)
        self.assertEqual(blocks, {'example.py': b'print(42)\n'})
        self.assert_chunk_budget(sizes)

    def test_setup_conflict_hashing_streams_large_destination(self):
        destination = self.base / 'README.md'
        old, new = b'old content\n' * 32768, b'new content\n'
        destination.write_bytes(old)
        with self.reads(destination) as sizes:
            result = setup.classify_destination(self.base, Path('README.md'), new, 'abort')
        self.assertEqual(result['action'], 'conflict')
        self.assertEqual(result['current_sha256'], hashlib.sha256(old).hexdigest())
        self.assertEqual(result['proposed_sha256'], hashlib.sha256(new).hexdigest())
        self.assertEqual(destination.read_bytes(), old)
        self.assert_chunk_budget(sizes)

    def test_duplicate_bundle_entries_do_not_repeat_payload_reads(self):
        payload = b'template evidence\n' * 1024
        source = self.base / 'files/README.md'
        source.parent.mkdir()
        source.write_bytes(payload)
        record = {'path': 'files/README.md', 'sha256': hashlib.sha256(payload).hexdigest()}
        manifest = self.base / 'manifest.json'
        manifest.write_text(json.dumps({'schema': setup.SCHEMA, 'files': [record]}))
        self.assertEqual(setup.load_bundle(self.base), [(Path('README.md'), payload)])
        manifest.write_text(json.dumps({'schema': setup.SCHEMA, 'files': [record] * 32}))
        with self.reads(source) as sizes, contextlib.redirect_stderr(io.StringIO()):
            try:
                result = setup.load_bundle(self.base)
            except SystemExit as error:
                # Explicitly rejecting duplicate manifest paths is also valid.
                self.assertEqual(error.code, 2)
            else:
                self.assertTrue(result)
                self.assertEqual({str(path) for path, _ in result}, {'README.md'})
                self.assertTrue(all(data == payload for _, data in result))
        self.assertLessEqual(sum(sizes), 2 * len(payload),
                             f'Duplicate bundle paths reread {sum(sizes)} bytes for {len(payload)} unique bytes')

    def test_benchmark_result_equivalence_hash_streams_result_file(self):
        path = self.base / 'result.bin'
        payload = b'reproducible output\n' * 32768
        arm = {'command': ['synthetic-command'], 'result_file': 'result.bin'}

        def launch(*args):
            path.write_bytes(payload)
            return 0, b'', b'', None

        with patch.object(bench, 'launch_and_observe', side_effect=launch), self.reads(path) as sizes:
            result = bench.run_command(arm, self.base, 0, [], False, 5)
        self.assertEqual(result['output_sha256'], hashlib.sha256(payload).hexdigest())
        self.assertEqual(result['output_bytes'], len(payload))
        self.assertEqual(result['output_source'], str(path))
        self.assert_chunk_budget(sizes)

    def test_benchmark_perf_parser_streams_rows_it_discards(self):
        path = self.base / 'perf.tsv'
        path.write_text('1\t\tunrequested-event\n' * 16384 + '42\t\tinstructions:u\n')
        metric = {'event': 'instructions:u', 'name': 'instructions'}
        with self.reads(path) as sizes:
            result = bench.parse_perf(path, [metric])
        self.assertEqual(result, {'instructions': 42})
        self.assert_chunk_budget(sizes)

    def test_benchmark_json_metrics_do_not_materialize_unbounded_padding(self):
        path = self.base / 'metrics.json'
        path.write_text(json.dumps({'allocated': 42, 'padding': 'x' * 262144}))
        metric = {'source': 'json', 'key': 'allocated', 'name': 'allocated_bytes'}
        with self.reads(path) as sizes:
            result = bench.read_json_metrics({'metrics_file': path.name}, self.base, [metric])
        self.assertEqual(result, {'allocated_bytes': 42})
        self.assert_chunk_budget(sizes)

    def test_perf_metadata_probe_has_finite_deadline(self):
        completed = types.SimpleNamespace(returncode=0, stdout='perf version fixture\n')
        with patch.object(perf.subprocess, 'run', return_value=completed) as run:
            self.assertEqual(perf.command_output(['perf', '--version']), 'perf version fixture')
        timeout = run.call_args.kwargs.get('timeout')
        self.assertTrue(isinstance(timeout, (int, float)) and 0 < timeout <= 10,
                        f'Profiler metadata subprocess has unbounded timeout {timeout!r}')

    def test_perf_stat_parser_streams_counter_input(self):
        path = self.base / 'perf.stat'
        path.write_text('not a counter\n' * 32768 + '42;;instructions:u;;100\n')
        with self.reads(path) as sizes:
            result = perf.parse_stat(path)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], 'instructions:u')
        self.assertEqual(result[0]['count'], 42)
        self.assertTrue(result[0]['supported'])
        self.assert_chunk_budget(sizes)

    def test_session_manifest_verification_streams_manifest_digest(self):
        source, destination = self.base / 'source', self.base / 'backup'
        source.mkdir()
        destination.mkdir()
        path = destination / 'backup_manifest.json'
        entry = {'relative_path': 'session.jsonl', 'records': 1}
        data = json.dumps({'version': 1, 'source': str(source.resolve()),
                           'files': [entry], 'padding': 'x' * 262144}).encode()
        path.write_bytes(data)
        # This test isolates manifest processing; transcript verification has its
        # own tests and must still be invoked for every selected entry.
        with patch.object(session_archive, 'verify_one') as verify, self.reads(path) as sizes:
            result = session_archive.verify_directory(source, destination)
        self.assertEqual(verify.call_count, 1)
        self.assertEqual((result['files'], result['records'], result['complete']), (1, 1, True))
        self.assertEqual(result['manifest_sha256'], hashlib.sha256(data).hexdigest())
        self.assert_chunk_budget(sizes)

    def reference_store(self, scenario):
        source = (TOOLS / 'web-research-mcp').read_text()
        start = source.index('class ReferenceStore<')
        end = source.index('\nconst references =', start)
        implementation = source[start:end]
        harness = self.base / 'reference-store.ts'
        harness.write_text('''
import {mkdtempSync, writeFileSync as writeReal, readFileSync, existsSync, rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
let referenceDirectory = mkdtempSync(join(tmpdir(), 'red-reference-store-'));
let writes = 0;
function referencePath(key: string) { return join(referenceDirectory, key); }
function writeFileSync(...args: any[]) { writes++; return (writeReal as any)(...args); }
''' + implementation + '\ntry {\n' + scenario + '\n} finally { rmSync(referenceDirectory, {recursive:true,force:true}); }\n')
        bun = shutil.which('bun')
        self.assertIsNotNone(bun, 'Bun is required to exercise the TypeScript cache')
        completed = subprocess.run([bun, str(harness)], capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_spilling_reference_does_not_serialize_same_value_twice(self):
        result = self.reference_store('''
let encodes = 0;
const store = new ReferenceStore<any>(1024, value => { encodes++; return value; }, value => value, 'ref-');
const payload = {body: 'x'.repeat(4096)};
store.set('one', payload);
const setEncodes = encodes;
const disk = JSON.parse(readFileSync(referencePath('ref-one'), 'utf8'));
console.log(JSON.stringify({encodes:setEncodes, same:disk.body === payload.body, retained:store.retainedBytes}));
''')
        self.assertTrue(result['same'])
        self.assertEqual(result['retained'], 0)
        self.assertLessEqual(result['encodes'], 1,
                             f'One oversized reference serialized {result["encodes"]} times')

    def test_reloading_spilled_reference_does_not_rewrite_unchanged_disk_copy(self):
        result = self.reference_store('''
const store = new ReferenceStore<any>(1024, value => value, value => value, 'ref-');
const payload = {body:'x'.repeat(4096)};
store.set('one',payload);
writes=0;
let same=true;
for (let i=0;i<16;i++) same &&= store.get('one')?.body === payload.body;
console.log(JSON.stringify({writes, same}));
''')
        self.assertTrue(result['same'])
        self.assertEqual(result['writes'], 0,
                         f'Reloading immutable spilled reference rewrote it {result["writes"]} times')


if __name__ == '__main__':
    unittest.main()
