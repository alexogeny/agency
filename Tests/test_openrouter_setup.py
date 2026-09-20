import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('decisions_setup', ROOT / 'Tools/agency_decisions.py')
decisions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(decisions)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        environment = patch.dict(os.environ, {'XDG_CONFIG_HOME': self.directory.name}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.config = Path(self.directory.name) / 'agency/openrouter.json'

    def write_config(self, value):
        self.config.parent.mkdir(exist_ok=True)
        self.config.write_text(json.dumps(value))
        self.config.chmod(0o600)

    def fake_op(self, items=None, fields=None):
        if items is None:
            items = [{'title': 'OpenRouter', 'id': 'item-id', 'vault': {'id': 'vault-id'}}]
        if fields is None:
            fields = [{'id': 'api-field', 'label': 'API Key', 'type': 'CONCEALED', 'value': 'test-key'}]
        def run(command, **options):
            if command[1:3] == ['item', 'list']:
                return subprocess.CompletedProcess(command, 0, json.dumps(items), '')
            visible = fields if '--reveal' in command else [
                {**field, 'value': '••••'} if field.get('type') == 'CONCEALED' else field
                for field in fields]
            return subprocess.CompletedProcess(command, 0, json.dumps({'fields': visible}), '')
        return patch.object(decisions.subprocess, 'run', side_effect=run)


    def test_setup_saves_private_key_and_runtime_never_calls_op(self):
        with self.fake_op() as run:
            result = decisions.setup_credentials()
        self.assertEqual(result['status'], 'configured')
        self.assertEqual(json.loads(self.config.read_text()), {'api_key': 'test-key'})
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.config.parent.stat().st_mode & 0o777, 0o700)
        self.assertNotIn('test-key', json.dumps(result))
        for call in run.call_args_list:
            self.assertEqual(call.kwargs['timeout'], 5)
            self.assertIs(call.kwargs['stdin'], subprocess.DEVNULL)
            self.assertEqual(call.kwargs['env']['OP_BIOMETRIC_UNLOCK_ENABLED'], 'false')
        with patch.object(decisions.subprocess, 'run') as run:
            self.assertEqual(decisions._read_key(), 'test-key')
            self.assertEqual(decisions._read_key(), 'test-key')
            self.assertEqual(decisions.setup_credentials()['status'], 'already-configured')
            run.assert_not_called()

    def test_environment_override_does_not_replace_persistent_setup(self):
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'temporary-key'}), self.fake_op():
            result = decisions.setup_credentials(interactive=True)
            self.assertEqual(result['status'], 'configured')
            self.assertEqual(result['credential_source'], 'file')
            self.assertEqual(decisions._read_key(), 'temporary-key')
        with patch.object(decisions.subprocess, 'run') as run:
            self.assertEqual(decisions._read_key(), 'test-key')
            run.assert_not_called()

    def test_setup_preserves_local_key_even_with_invalid_environment_override(self):
        self.write_config({'api_key': 'local-key'})
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': ''}), \
                patch.object(decisions.subprocess, 'run') as run:
            result = decisions.setup_credentials(interactive=True)
            self.assertEqual(result['status'], 'already-configured')
            self.assertEqual(result['credential_source'], 'file')
            run.assert_not_called()
        self.assertEqual(decisions._read_key(), 'local-key')

    def test_environment_override_does_not_skip_reference_import(self):
        self.write_config({'secret_reference': 'op://vault/item/key'})
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'temporary-key'}), \
                patch.object(decisions.subprocess, 'run',
                             return_value=subprocess.CompletedProcess([], 0, 'imported-key', '')) as run:
            result = decisions.setup_credentials(interactive=True)
            self.assertEqual(result['status'], 'configured')
            run.assert_called_once()
        self.assertEqual(decisions._read_key(), 'imported-key')

    def test_interactive_setup_allows_desktop_auth_only_for_import(self):
        with self.fake_op() as run:
            self.assertEqual(decisions.setup_credentials(interactive=True)['status'], 'configured')
        for call in run.call_args_list:
            self.assertEqual(call.kwargs['timeout'], 30)
            self.assertNotIn('OP_BIOMETRIC_UNLOCK_ENABLED', call.kwargs['env'])

    def test_empty_or_invalid_key_does_not_create_configuration(self):
        for value in ('', 'bad key', None):
            with self.subTest(value=value), self.fake_op(fields=[{'label': 'API Key', 'value': value}]):
                self.assertEqual(decisions.setup_credentials()['status'], 'skipped')
                self.assertFalse(self.config.exists())

    def test_missing_or_duplicate_items_fail_closed(self):
        for items in ([], [{'title': 'OpenRouter', 'id': 'one'}, {'title': 'OpenRouter', 'id': 'two'}]):
            with self.subTest(items=items), self.fake_op(items=items):
                result = decisions.setup_credentials()
            self.assertEqual(result['status'], 'skipped')
            self.assertFalse(self.config.exists())

    def test_password_and_ambiguous_api_fields_are_not_imported(self):
        for fields in ([{'label': 'password', 'value': 'SECRET'}],
                       [{'label': 'API Key', 'value': 'SECRET'}, {'label': 'api_key', 'value': 'SECRET'}]):
            with self.subTest(fields=len(fields)), self.fake_op(fields=fields):
                result = decisions.setup_credentials()
            self.assertEqual(result['status'], 'skipped')
            self.assertNotIn('SECRET', json.dumps(result))
            self.assertFalse(self.config.exists())

    def test_legacy_reference_is_imported_only_by_setup(self):
        reference = 'op://My Vault/OpenRouter/Section 1.2/API Key'
        self.write_config({'secret_reference': reference})
        with patch.object(decisions.subprocess, 'run') as run:
            self.assertFalse(decisions.key_available())
            with self.assertRaisesRegex(decisions.DecisionError, 'setup'):
                decisions._read_key()
            run.assert_not_called()
        with patch.object(decisions.subprocess, 'run',
                          return_value=subprocess.CompletedProcess([], 0, 'imported-key\n', '')) as run:
            result = decisions.setup_credentials(interactive=True)
        self.assertEqual(result['status'], 'configured')
        self.assertEqual(run.call_args.args[0], ['op', 'read', reference])
        self.assertEqual(json.loads(self.config.read_text()), {'api_key': 'imported-key'})
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('imported-key', json.dumps(result))

    def test_failed_import_preserves_existing_reference(self):
        self.write_config({'secret_reference': 'op://vault/item/key'})
        before = self.config.read_bytes()
        for failure in (FileNotFoundError('SECRET'), subprocess.TimeoutExpired(['op'], 5, output='SECRET'),
                        subprocess.CompletedProcess([], 1, 'SECRET', 'SECRET'),
                        subprocess.CompletedProcess([], 0, '', '')):
            options = {'side_effect': failure} if isinstance(failure, Exception) else {'return_value': failure}
            with self.subTest(failure=type(failure)), patch.object(decisions.subprocess, 'run', **options):
                result = decisions.setup_credentials()
            self.assertEqual(result['status'], 'skipped')
            self.assertNotIn('SECRET', json.dumps(result))
            self.assertEqual(self.config.read_bytes(), before)

    def test_invalid_reference_cannot_trigger_op(self):
        for reference in ('https://host/key', 'op://vault/item', 'op://vault/item/key\n', 'op://vault/item/key?x=1'):
            self.write_config({'secret_reference': reference})
            with self.subTest(reference=reference), patch.object(decisions.subprocess, 'run') as run:
                self.assertEqual(decisions.setup_credentials()['status'], 'skipped')
                run.assert_not_called()

    def test_failed_atomic_write_preserves_reference_and_removes_temporary_key(self):
        self.write_config({'secret_reference': 'op://vault/item/key'})
        before = self.config.read_bytes()
        with patch.object(decisions.subprocess, 'run',
                          return_value=subprocess.CompletedProcess([], 0, 'SECRET', '')), \
                patch.object(decisions.os, 'replace', side_effect=OSError('SECRET')):
            result = decisions.setup_credentials()
        self.assertEqual(result['status'], 'skipped')
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(list(self.config.parent.iterdir()), [self.config])

    def test_wrong_owner_is_rejected_without_vault_access(self):
        self.write_config({'api_key': 'SECRET'})
        with patch.object(decisions.os, 'getuid', return_value=os.getuid() + 1), \
                patch.object(decisions.subprocess, 'run') as run:
            self.assertFalse(decisions.key_available())
            self.assertEqual(decisions.setup_credentials()['status'], 'skipped')
            run.assert_not_called()

    def test_doctor_and_dry_run_never_invoke_op_or_expose_key(self):
        self.write_config({'api_key': 'SECRET'})
        with patch.object(decisions.subprocess, 'run') as run, patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(decisions.main(['doctor']), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result['credential_source'], 'file')
            self.assertTrue(result['credential_verified'])
            decisions.setup_credentials(dry_run=True)
            self.assertNotIn('SECRET', output.getvalue())
            run.assert_not_called()
        self.config.unlink()
        with patch.object(decisions.subprocess, 'run') as run:
            decisions.setup_credentials(dry_run=True)
            run.assert_not_called()
            self.assertFalse(self.config.exists())

    def test_unsafe_and_symlinked_credential_files_are_rejected(self):
        self.write_config({'api_key': 'SECRET'})
        self.config.chmod(0o644)
        with patch.object(decisions.subprocess, 'run') as run:
            self.assertFalse(decisions.key_available())
            self.assertEqual(decisions.setup_credentials()['status'], 'skipped')
            run.assert_not_called()
        target = self.config.with_name('target.json')
        self.config.rename(target)
        target.chmod(0o600)
        self.config.symlink_to(target)
        self.assertFalse(decisions.key_available())
        self.assertEqual(decisions.setup_credentials()['status'], 'skipped')
        self.assertEqual(json.loads(target.read_text()), {'api_key': 'SECRET'})

    def test_invalid_local_key_fails_before_provider_call(self):
        self.write_config({'api_key': ''})
        with patch.object(decisions.subprocess, 'run') as run, \
                patch.object(decisions.urllib.request, 'build_opener') as opener:
            with self.assertRaises(decisions.DecisionError):
                decisions.evaluate('test', 'context')
            opener.assert_not_called()
            run.assert_not_called()

    def test_precedence_and_local_key_rotation(self):
        self.write_config({'api_key': 'first-key'})
        with patch.object(decisions.subprocess, 'run') as run:
            with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'env-key'}):
                self.assertEqual(decisions._read_key(), 'env-key')
                self.assertEqual(decisions._read_key('explicit-key'), 'explicit-key')
            self.assertEqual(decisions._read_key(), 'first-key')
            self.write_config({'api_key': 'second-key'})
            self.assertEqual(decisions._read_key(), 'second-key')
            run.assert_not_called()

    def test_fake_cli_setup_then_fresh_process_without_op(self):
        executable = Path(self.directory.name) / 'op'
        executable.write_text("""#!/usr/bin/env python3
import json
import sys
if sys.argv[1:3] == ['item', 'list']:
    print(json.dumps([{'title': 'OpenRouter', 'id': 'item', 'vault': {'id': 'vault'}}]))
else:
    print(json.dumps({'fields': [{'label': 'API Key', 'value': 'PRIVATE_KEY'}]}))
""")
        executable.chmod(0o700)
        environment = dict(os.environ, PATH=self.directory.name + os.pathsep + os.defpath)
        result = subprocess.run(['/bin/bash', str(ROOT / 'scripts/configure-openrouter.sh')],
                                env=environment, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'configured')
        self.assertNotIn('PRIVATE_KEY', result.stdout + result.stderr)
        marker = Path(self.directory.name) / 'op-called'
        executable.write_text('#!/bin/sh\ntouch "$OP_MARKER"\nexit 88\n')
        environment['OP_MARKER'] = str(marker)
        script = 'import sys; sys.path.insert(0, sys.argv[1]); import agency_decisions as d; assert d._read_key() == "PRIVATE_KEY"; print("ready")'
        for _ in range(2):
            result = subprocess.run([os.sys.executable, '-c', script, str(ROOT / 'Tools')],
                                    env=environment, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'ready')
        self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
