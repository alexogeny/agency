import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Tools'))
import agency_browser as b
import agency_browser_downloads as d


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def manifest():
    return {'schema_version': 1, 'allowed_origins': ['https://example.com'], 'items': [
        {'id': 'guide', 'url': 'https://example.com/files/1?signature=private',
         'filename': 'Guide displayed name.pdf', 'expected_size': 3, 'path': 'notes/guide.pdf'},
        {'id': 'code', 'url': 'https://example.com/files/2',
         'filename': 'source.zip', 'expected_size': 4, 'path': 'code/source.zip'}]}


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'collection'
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def transfer(self, item, path):
        self.calls.append(item['id'])
        data = b'pdf' if item['id'] == 'guide' else b'code'
        path.write_bytes(data)
        return {'result': {'path': str(path), 'bytes': len(data), 'sha256': checksum(data)}, 'wait_seconds': 2.25}

    def test_batch_records_receipts_and_resumes_without_browser_calls(self):
        result = d.download_batch(manifest(), self.root, self.transfer)
        self.assertTrue(result['complete'])
        self.assertEqual(result['downloaded'], 2)
        self.assertEqual(self.calls, ['guide', 'code'])
        journal = self.root / d.JOURNAL
        self.assertEqual(stat.S_IMODE(journal.stat().st_mode), 0o600)
        records = [json.loads(line) for line in journal.read_text().splitlines()]
        self.assertEqual(records[-1]['wait_seconds'], 2.25)
        self.assertNotIn('signature', journal.read_text())
        again = d.download_batch(manifest(), self.root, Mock(side_effect=AssertionError('replayed download')))
        self.assertTrue(again['complete'])
        self.assertEqual(again['verified'], 2)
        self.assertEqual(again['downloaded'], 0)

    def test_failure_stops_queue_and_resume_keeps_completed_items(self):
        def failing(item, path):
            if item['id'] == 'code':
                raise b.Deferred('https://example.com/?signature=secret')
            return self.transfer(item, path)
        result = d.download_batch(manifest(), self.root, failing)
        self.assertFalse(result['complete'])
        self.assertEqual(result['error']['code'], 'deferred')
        self.assertEqual(result['pending'], 1)
        self.assertNotIn('secret', json.dumps(result))
        self.assertNotIn('secret', (self.root / d.JOURNAL).read_text())
        self.calls.clear()
        resumed = d.download_batch(manifest(), self.root, self.transfer)
        self.assertFalse(resumed['complete'])
        self.assertEqual(resumed['error']['code'], 'inspect_transfer')
        self.assertEqual(self.calls, [])
        resumed = d.download_batch(manifest(), self.root, self.transfer, retry_interrupted=True)
        self.assertTrue(resumed['complete'])
        self.assertEqual(self.calls, ['code'])

    def test_same_size_corruption_is_detected_without_overwrite(self):
        d.download_batch(manifest(), self.root, self.transfer)
        path = self.root / 'notes/guide.pdf'
        path.write_bytes(b'bad')
        result = d.download_batch(manifest(), self.root, Mock(side_effect=AssertionError('redownloaded corruption')))
        self.assertFalse(result['complete'])
        self.assertEqual(result['error']['code'], 'checksum_mismatch')
        self.assertEqual(path.read_bytes(), b'bad')
        path.write_bytes(b'pdf')
        repaired = d.download_batch(manifest(), self.root, Mock(side_effect=AssertionError('restored file fetched')))
        self.assertTrue(repaired['complete'])
        self.assertEqual(repaired['verified'], 2)

    def test_missing_completed_file_must_match_its_previous_checksum(self):
        d.download_batch(manifest(), self.root, self.transfer)
        path = self.root / 'notes/guide.pdf'
        path.unlink()
        def changed(item, target):
            target.write_bytes(b'bad')
            return {'result': {'path': str(target), 'bytes': 3, 'sha256': checksum(b'bad')}, 'wait_seconds': 0}
        result = d.download_batch(manifest(), self.root, changed)
        self.assertFalse(result['complete'])
        self.assertEqual(result['error']['code'], 'checksum_mismatch')
        self.assertEqual(path.read_bytes(), b'bad')
        path.write_bytes(b'pdf')
        restored = d.download_batch(manifest(), self.root, None, verify_only=True)
        self.assertTrue(restored['complete'])

    def test_offline_missing_check_cannot_clear_an_interrupted_transfer(self):
        transfer = Mock(side_effect=b.Deferred('still downloading'))
        d.download_batch(manifest(), self.root, transfer)
        missing = d.download_batch(manifest(), self.root, verify_only=True)
        self.assertEqual(missing['error']['code'], 'missing')
        transfer.reset_mock()
        resumed = d.download_batch(manifest(), self.root, transfer)
        self.assertEqual(resumed['error']['code'], 'inspect_transfer')
        transfer.assert_not_called()

    def test_malformed_transfer_receipt_stops_queue_without_exposing_contents(self):
        for outcome in (None, [], {'result': []}, {'result': {'bytes': True, 'url': '?secret=value'}}):
            with self.subTest(outcome=outcome):
                root = Path(self.tmp.name) / str(len(list(Path(self.tmp.name).iterdir())))
                result = d.download_batch(manifest(), root, lambda item, path: outcome)
                self.assertFalse(result['complete'])
                self.assertEqual(result['error']['code'], 'invalid_receipt')
                self.assertNotIn('secret', json.dumps(result))

    def test_existing_file_requires_known_hash_and_verify_only_never_downloads(self):
        self.root.mkdir()
        (self.root / 'notes').mkdir()
        (self.root / 'notes/guide.pdf').write_bytes(b'pdf')
        result = d.download_batch(manifest(), self.root, None, verify_only=True)
        self.assertFalse(result['complete'])
        self.assertEqual(result['error']['code'], 'existing_unverified')
        plan = manifest()
        plan['items'][0]['sha256'] = checksum(b'pdf')
        result = d.download_batch(plan, self.root, None, verify_only=True)
        self.assertFalse(result['complete'])
        self.assertEqual(result['verified'], 1)
        self.assertEqual(result['error']['code'], 'missing')
        (self.root / 'code').mkdir()
        (self.root / 'code/source.zip').write_bytes(b'code')
        plan['items'][1]['sha256'] = checksum(b'code')
        result = d.download_batch(plan, self.root, None, verify_only=True)
        self.assertTrue(result['complete'])
        self.assertEqual(result['verified_bytes'], 7)

    def test_manifest_preflight_rejects_unsafe_urls_paths_duplicates_and_empty_work(self):
        invalid = []
        for field, value in [('path', '../outside'), ('path', '/tmp/outside'), ('path', 'notes/../outside'),
                             ('path', 'notes\\outside'), ('path', d.JOURNAL),
                             ('filename', '../file.pdf'), ('filename', '.'), ('expected_size', True),
                             ('expected_size', -1), ('url', 'https://other.example/file'),
                             ('url', 'https://user:password@example.com/file'), ('sha256', 'not-a-hash')]:
            plan = manifest();plan['items'][0][field] = value;invalid.append(plan)
        plan = manifest();plan['items'] = [];invalid.append(plan)
        plan = manifest();plan['items'][1]['id'] = 'guide';invalid.append(plan)
        plan = manifest();plan['items'][1]['path'] = 'notes/guide.pdf';invalid.append(plan)
        plan = manifest();plan['allowed_origins'] = ['https://example.com/restricted'];invalid.append(plan)
        for plan in invalid:
            with self.subTest(plan=plan), self.assertRaises(b.BrowserError):
                d.download_batch(plan, self.root, Mock(side_effect=AssertionError('invalid work sent')))
        self.assertFalse(self.root.exists())

    def test_symlink_parent_and_leaf_are_rejected_without_outside_writes(self):
        self.root.mkdir();outside = Path(self.tmp.name) / 'outside';outside.mkdir()
        (self.root / 'notes').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(b.BrowserError):
            d.download_batch(manifest(), self.root, Mock(side_effect=AssertionError('symlink action sent')))
        self.assertEqual(list(outside.iterdir()), [])
        (self.root / 'notes').unlink();(self.root / 'notes').mkdir()
        external = outside / 'guide.pdf';external.write_bytes(b'old')
        (self.root / 'notes/guide.pdf').symlink_to(external)
        with self.assertRaises(b.BrowserError):
            d.download_batch(manifest(), self.root, Mock(side_effect=AssertionError('symlink action sent')))
        self.assertEqual(external.read_bytes(), b'old')

    def test_changed_item_identity_and_truncated_journal_stop_before_transfer(self):
        d.download_batch(manifest(), self.root, self.transfer)
        plan = manifest();plan['items'][0]['expected_size'] = 9
        with self.assertRaises(b.BrowserError):
            d.download_batch(plan, self.root, Mock(side_effect=AssertionError('changed identity sent')))
        with (self.root / d.JOURNAL).open('a') as stream:stream.write('{"partial":')
        with self.assertRaises(b.BrowserError):
            d.download_batch(manifest(), self.root, Mock(side_effect=AssertionError('broken journal ignored')))

    def test_signed_url_refresh_preserves_resource_identity_and_resume(self):
        d.download_batch(manifest(), self.root, self.transfer)
        plan = manifest();plan['items'][0]['url'] = 'https://example.com/files/1?signature=refreshed'
        result = d.download_batch(plan, self.root, Mock(side_effect=AssertionError('resumed file fetched')))
        self.assertTrue(result['complete'])
        self.assertEqual(result['verified'], 2)

    def test_second_runner_cannot_overlap_the_same_collection(self):
        def transfer(item, path):
            with self.assertRaises(b.Deferred):
                d.download_batch(manifest(), self.root, Mock(side_effect=AssertionError('overlapping action')))
            return self.transfer(item, path)
        self.assertTrue(d.download_batch(manifest(), self.root, transfer)['complete'])

    def test_bad_hash_receipt_preserves_file_and_stops_batch(self):
        plan = manifest();plan['items'][0]['sha256'] = checksum(b'pdf')
        def transfer(item, path):
            result = self.transfer(item, path)
            result['result']['sha256'] = checksum(b'bad')
            return result
        result = d.download_batch(plan, self.root, transfer)
        self.assertFalse(result['complete'])
        self.assertEqual(result['error']['code'], 'checksum_mismatch')
        self.assertEqual(self.calls, ['guide'])
        self.assertEqual((self.root / 'notes/guide.pdf').read_bytes(), b'pdf')

    def test_cli_dry_run_needs_no_session_and_creates_no_collection(self):
        path = Path(self.tmp.name) / 'manifest.json';path.write_text(json.dumps(manifest()))
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
        result = subprocess.run([str(ROOT / 'Tools/agency-browser'), 'download-batch', '--manifest', str(path),
                                 '--destination', str(self.root), '--dry-run'], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary['status'], 'planned')
        self.assertEqual(summary['files'], 2)
        self.assertNotIn('signature', result.stdout)
        self.assertFalse(self.root.exists())

    def test_cli_verify_only_and_completed_resume_need_no_session(self):
        d.download_batch(manifest(), self.root, self.transfer)
        path = Path(self.tmp.name) / 'manifest.json'
        path.write_text(json.dumps(manifest()))
        command = [str(ROOT / 'Tools/agency-browser'), 'download-batch', '--manifest', str(path),
                   '--destination', str(self.root)]
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
        for args in ([], ['--verify-only']):
            result = subprocess.run(command + args, capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['verified'], 2)
        (self.root / 'notes/guide.pdf').unlink()
        result = subprocess.run(command + ['--verify-only'], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'missing')

    def test_cli_batch_reuses_one_mcp_session_and_paces_browser_navigation(self):
        incoming = Path(self.tmp.name) / 'incoming'
        incoming.mkdir()
        plan = manifest()
        manifest_path = Path(self.tmp.name) / 'manifest.json'
        manifest_path.write_text(json.dumps(plan))
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append((data, self.headers.get('Mcp-Session-Id')))
                if data['method'] == 'notifications/initialized':
                    self.send_response(202)
                    self.end_headers()
                    return
                if data['method'] == 'initialize':
                    value = {'protocolVersion': '2025-06-18', 'capabilities': {},
                             'serverInfo': {'name': 'download-fixture', 'version': '1'}}
                else:
                    item = plan['items'][sum(row[0]['method'] == 'tools/call' for row in received) - 1]
                    (incoming / item['filename']).write_bytes(b'pdf' if item['id'] == 'guide' else b'code')
                    value = {'content': []}
                body = json.dumps({'jsonrpc': '2.0', 'id': data['id'], 'result': value}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Mcp-Session-Id', 'synthetic-download-session')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            session = Path(self.tmp.name) / 'session.json'
            command = [str(ROOT / 'Tools/agency-browser'), 'download-batch', '--manifest', str(manifest_path),
                       '--destination', str(self.root), '--download-directory', str(incoming),
                       '--session', str(session), '--endpoint', 'http://localhost:' + str(server.server_port) + '/mcp',
                       '--pace-state', str(Path(self.tmp.name) / 'pacing'), '--minimum', '0.1', '--jitter', '0', '--progress']
            result = subprocess.run(command, capture_output=True, text=True,
                                    env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)['complete'])
            self.assertEqual(json.loads(result.stdout)['downloaded'], 2)
            self.assertNotIn('signature', result.stdout + result.stderr)
            self.assertEqual(sum(row[0]['method'] == 'initialize' for row in received), 1)
            calls = [row for row in received if row[0]['method'] == 'tools/call']
            self.assertEqual(len(calls), 2)
            for index, (data, session_id) in enumerate(calls):
                self.assertEqual(session_id, 'synthetic-download-session')
                self.assertEqual(data['params']['name'], 'browser_run_code_unsafe')
                self.assertIn('page.goto(' + json.dumps(plan['items'][index]['url']), data['params']['arguments']['code'])
                self.assertNotIn('cookie', data['params']['arguments']['code'])
            receipts = [json.loads(line) for line in (self.root / d.JOURNAL).read_text().splitlines()]
            self.assertGreater(next(row['wait_seconds'] for row in receipts if row.get('id') == 'code' and row['status'] == 'downloaded'), 0)
            self.assertEqual(list(incoming.iterdir()), [])
            self.assertEqual((self.root / 'notes/guide.pdf').read_bytes(), b'pdf')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
