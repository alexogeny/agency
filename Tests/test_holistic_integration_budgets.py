"""Installation/configuration resource contracts from the holistic review.

Installer tests run the real shell script with network and filesystem commands
stubbed before the transfer. No installation or network access occurs.
"""
import contextlib
import importlib.util
import io
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Tools'))
import research_corpus_core as core
spec = importlib.util.spec_from_file_location('holistic_merge_hooks', ROOT / 'scripts/merge-agent-hooks.py')
hooks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hooks)


class ConfigurationAndInstallerBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def test_hook_merging_indexes_group_equality_instead_of_cross_comparing(self):
        def workload(n, existing):
            comparisons = 0

            class Group(dict):
                def __eq__(self, other):
                    nonlocal comparisons
                    comparisons += 1
                    return super().__eq__(other)

            def group(index, prefix):
                return Group(matcher=f'{prefix}-{index}', hooks=[{'type': 'command', 'command': f'{prefix}-{index}'}])

            target = {'hooks': {'Stop': [group(i, 'user') for i in range(n)] if existing else []}}
            fragment = {'hooks': {'Stop': [group(i, 'managed') for i in range(n)]}}
            with patch.object(hooks, 'load_json', side_effect=[target, fragment]):
                result = hooks.merged_config(self.base / 'target', self.base / 'fragment')
            commands = [item['hooks'][0]['command'] for item in result['hooks']['Stop']]
            self.assertEqual(commands, ([f'user-{i}' for i in range(n)] if existing else [])
                             + [f'managed-{i}' for i in range(n)])
            return comparisons

        cases = [(existing, workload(64, existing), workload(128, existing)) for existing in [False, True]]
        self.assertTrue(all(large <= 2.6 * small for _, small, large in cases),
                        f'Doubling hook groups caused superlinear equality checks: {cases}')

    def test_hook_check_does_not_parse_existing_configuration_twice(self):
        target, fragment = self.base / 'target.json', self.base / 'fragment.json'
        target.write_text(json.dumps({'hooks': {}, 'user_setting': 'x' * 131072}))
        fragment.write_text(json.dumps({'hooks': {'Stop': [{'hooks': [{'command': 'fixture'}]}]}}))
        reads = []
        original = hooks.load_json

        def observe(path, *args):
            if path == target:
                reads.append(path.stat().st_size)
            return original(path, *args)

        with patch.object(hooks, 'load_json', side_effect=observe), \
                patch.object(sys, 'argv', ['merge-agent-hooks', '--check', str(target), str(fragment)]):
            with self.assertRaises(SystemExit) as result:
                hooks.main()
        self.assertEqual(result.exception.code, 0)
        self.assertEqual(json.loads(target.read_text())['hooks'], {}, '--check must leave configuration untouched')
        self.assertLessEqual(len(reads), 1,
                             f'One check decoded the same {target.stat().st_size}-byte configuration {len(reads)} times')

    def test_manifest_size_limit_cannot_be_crossed_by_successful_publication(self):
        root = self.base / 'corpus'
        (root / 'pending').mkdir(parents=True)
        manifest = {'schema': core.SCHEMA, 'corpus_id': 'size-fixture', 'active_run': 'run-a',
                    'protocol': {}, 'sources': {}, 'operations': {}, 'records': [],
                    'runs': [{'run_id': 'run-a', 'recipe': {'queries': [], 'selections': []}}]}
        core.atomic_json(root / 'manifest.json', manifest)
        failure = None
        with patch.object(core, 'MAX_BYTES', 512):
            for index in range(16):
                record = {'schema': core.RECORD_SCHEMA, 'record_id': f'record-{index:04d}',
                          'kind': 'synthesis', 'source_id': None, 'run_id': 'run-a',
                          'text': 'Evidence', 'markdown': 'Evidence',
                          'created_at': '2026-11-02T00:00:00Z', 'process': {'exit_code': 0}}
                pending = {'record': record}
                core.atomic_json(root / 'pending/result.json', pending)
                try:
                    core._publish(root, pending)
                except core.CorpusError as error:
                    failure = error
                    break
        self.assertIsNotNone(failure, 'Fixture must actually reach the manifest byte ceiling')
        self.assertEqual(failure.code, 'response-too-large')
        # Existing committed state must remain readable by the same bounded reader.
        size = (root / 'manifest.json').stat().st_size
        self.assertLessEqual(size, 512 * 4,
                             f'Publication wrote an unreadable {size}-byte manifest above its 2048-byte reader limit')
        with patch.object(core, 'MAX_BYTES', 512):
            retained = core.read_manifest(root)
        self.assertGreater(len(retained['records']), 0)
        for entry in retained['records']:
            self.assertEqual(core.load_record(root, entry)['text'], 'Evidence')

    def font_download_arguments(self):
        binary = self.base / 'bin'
        binary.mkdir()
        scratch = self.base / 'download'
        scratch.mkdir()
        log = self.base / 'curl.json'
        stubs = {
            'mkdir': '#!/bin/sh\nexit 0\n',
            'mktemp': '#!/bin/sh\nprintf "%s\\n" "$RESOURCE_FONT_SCRATCH"\n',
            'curl': '#!' + sys.executable + '\nimport json,os,sys\nfrom pathlib import Path\nPath(os.environ["RESOURCE_CURL_LOG"]).write_text(json.dumps(sys.argv[1:]))\nraise SystemExit(23)\n',
        }
        for name, text in stubs.items():
            path = binary / name
            path.write_text(text)
            path.chmod(0o755)
        env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ.get('PATH', ''),
                   RESOURCE_FONT_SCRATCH=str(scratch), RESOURCE_CURL_LOG=str(log))
        completed = subprocess.run(['bash', str(ROOT / 'scripts/install-report-fonts.sh')],
                                   env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 23, completed.stderr)
        args = json.loads(log.read_text())
        self.assertIn('--output', args)
        self.assertTrue(args[args.index('--output') + 1].startswith(str(scratch)))
        self.assertTrue(any(arg.startswith('https://downloads.sourceforge.net/') for arg in args))
        return args

    def test_font_installer_download_has_transfer_and_connection_deadlines(self):
        args = self.font_download_arguments()
        def value(long, short=None):
            for option in (long, short):
                if option and option in args:
                    return float(args[args.index(option) + 1])
            return None
        total, connect = value('--max-time', '-m'), value('--connect-timeout')
        self.assertTrue(total is not None and connect is not None and 0 < connect <= total <= 300,
                        f'Font download is not time-budgeted: max-time={total}, connect-timeout={connect}')

    def test_homebrew_bootstrap_transfer_is_time_and_size_budgeted(self):
        scratch = self.base / 'bootstrap'
        scratch.mkdir()
        log = self.base / 'bootstrap-curl.log'
        # Source the real bootstrap function, then intercept its network boundary.
        shell = r'''
source "$1"
curl() { printf '%s\n' "$@" > "$RESOURCE_CURL_LOG"; return 23; }
mktemp() { printf '%s\n' "$RESOURCE_BOOTSTRAP_SCRATCH"; }
agency_bootstrap_homebrew
'''
        env = dict(os.environ, RESOURCE_CURL_LOG=str(log), RESOURCE_BOOTSTRAP_SCRATCH=str(scratch))
        result = subprocess.run(['bash', '-c', shell, 'bootstrap-test', str(ROOT / 'scripts/platform.sh')],
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Could not download', result.stderr)
        args = log.read_text().splitlines()
        self.assertIn('--proto', args)
        self.assertTrue(any(arg.startswith('https://raw.githubusercontent.com/Homebrew/install/') for arg in args))
        missing = [option for option in ('--max-time', '--connect-timeout', '--max-filesize') if option not in args]
        self.assertEqual(missing, [], f'Homebrew bootstrap download omits resource guards: {missing}')
        total = float(args[args.index('--max-time') + 1])
        connect = float(args[args.index('--connect-timeout') + 1])
        self.assertTrue(0 < connect <= total <= 300)
        self.assert_transfer_size(args[args.index('--max-filesize') + 1])

    def test_font_installer_download_has_archive_byte_limit(self):
        args = self.font_download_arguments()
        limit = args[args.index('--max-filesize') + 1] if '--max-filesize' in args else None
        self.assertIsNotNone(limit, 'Font archive transfer has no maximum byte size')
        self.assert_transfer_size(limit)

    def assert_transfer_size(self, value):
        match = re.fullmatch(r'(\d+)([kKmMgGtT]?)', value)
        self.assertIsNotNone(match, f'Invalid transfer size: {value}')
        power = 'kmgt'.find(match[2].lower()) + 1 if match[2] else 0
        limit = int(match[1]) * 1024 ** power
        self.assertTrue(0 < limit <= 128 * 1024 * 1024, f'Invalid or excessive transfer limit: {value}')


if __name__ == '__main__':
    unittest.main()
