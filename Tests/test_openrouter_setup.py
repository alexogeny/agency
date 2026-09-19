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
        self.environment = patch.dict(os.environ, {'XDG_CONFIG_HOME': self.directory.name}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.config = Path(self.directory.name) / 'agency/openrouter.json'

    def write_reference(self, reference='op://My Vault/OpenRouter/API Key'):
        self.config.parent.mkdir(exist_ok=True)
        self.config.write_text(json.dumps({'secret_reference': reference}))
        self.config.chmod(0o600)

    def fake_op(self, items=None, fields=None):
        if items is None:
            items = [{'title': 'OpenRouter', 'id': 'item-id', 'vault': {'id': 'vault-id'}}]
        if fields is None:
            fields = [{'id': 'api-field', 'label': 'API Key', 'type': 'CONCEALED', 'value': ''}]
        return patch.object(decisions.subprocess, 'run', side_effect=[
            subprocess.CompletedProcess([], 0, json.dumps(items), ''),
            subprocess.CompletedProcess([], 0, json.dumps({'fields': fields}), '')])

    def test_interactive_setup_allows_desktop_auth_with_longer_bound(self):
        with self.fake_op() as run:
            result = decisions.setup_credentials(interactive=True)
        self.assertEqual(result['status'], 'configured')
        for call in run.call_args_list:
            self.assertEqual(call.kwargs['timeout'], 30)
            self.assertNotIn('OP_BIOMETRIC_UNLOCK_ENABLED', call.kwargs['env'])

    def test_empty_api_key_field_persists_reference_only(self):
        with self.fake_op() as run:
            result = decisions.setup_credentials()
        self.assertEqual(result['status'], 'configured')
        self.assertFalse(result['credential_verified'])
        self.assertEqual(json.loads(self.config.read_text()), {'secret_reference': 'op://vault-id/item-id/api-field'})
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs['timeout'], 5)
            self.assertIs(call.kwargs['stdin'], subprocess.DEVNULL)
            self.assertEqual(call.kwargs['env']['OP_BIOMETRIC_UNLOCK_ENABLED'], 'false')
            self.assertNotIn('--reveal', call.args[0])

    def test_missing_duplicate_items_fail_closed(self):
        for items in [[], [{'title': 'OpenRouter', 'id': 'one'}, {'title': 'OpenRouter', 'id': 'two'}]]:
            with self.subTest(items=items), self.fake_op(items=items):
                result = decisions.setup_credentials()
                self.assertEqual(result['status'], 'skipped')
                self.assertIn('OpenRouter', result['message'])
                self.assertFalse(self.config.exists())

    def test_section_identifier_with_spaces_round_trips(self):
        with self.fake_op(fields=[{'id': 'api-field', 'label': 'API Key',
                                  'section': {'id': 'Section 1.2'}, 'value': 'PRIVATE_API_KEY'}]):
            result = decisions.setup_credentials()
        self.assertEqual(result['status'], 'configured')
        reference = 'op://vault-id/item-id/Section 1.2/api-field'
        self.assertEqual(json.loads(self.config.read_text()), {'secret_reference': reference})
        self.assertNotIn('PRIVATE_API_KEY', self.config.read_text() + json.dumps(result))
        with patch.object(decisions.subprocess, 'run',
                          return_value=subprocess.CompletedProcess([], 0, 'test-key\n', '')) as run:
            self.assertEqual(decisions._read_key(), 'test-key')
        self.assertEqual(run.call_args.args[0], ['op', 'read', reference])

    def test_section_identifier_cannot_inject_reference_components(self):
        for section in ('extra/path', 'section?attribute=value', 'section\nname'):
            with self.subTest(section=section), self.fake_op(fields=[
                {'id': 'api-field', 'label': 'API Key', 'section': {'id': section}}
            ]):
                self.assertEqual(decisions.setup_credentials()['status'], 'skipped')
                self.assertFalse(self.config.exists())

    def test_login_password_is_not_api_key(self):
        with self.fake_op(fields=[{'id': 'password', 'label': 'password', 'type': 'CONCEALED', 'value': 'PRIVATE'}]):
            result = decisions.setup_credentials()
        self.assertEqual(result['status'], 'skipped')
        self.assertIn('API Key', result['message'])
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertFalse(self.config.exists())

    def test_doctor_and_dry_run_never_invoke_op(self):
        self.write_reference()
        with patch.object(decisions.subprocess, 'run') as run, patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertTrue(decisions.key_available())
            self.assertEqual(decisions.main(['doctor']), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result['credential_source'], '1password')
            self.assertFalse(result['credential_verified'])
            decisions.setup_credentials(dry_run=True)
            run.assert_not_called()
        self.config.unlink()
        with patch.object(decisions.subprocess, 'run') as run:
            decisions.setup_credentials(dry_run=True)
            run.assert_not_called()
            self.assertFalse(self.config.exists())

    def test_reference_spaces_passed_as_single_argument(self):
        self.write_reference()
        with patch.object(decisions.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'test-key\n', '')) as run:
            self.assertEqual(decisions._read_key(), 'test-key')
        self.assertEqual(run.call_args.args[0], ['op', 'read', 'op://My Vault/OpenRouter/API Key'])
        self.assertEqual(run.call_args.kwargs['timeout'], 5)

    def test_invalid_reference_and_unsafe_file_rejected(self):
        for ref in ['$(touch /tmp/wrong)', 'https://host/key', 'op://vault/item', 'op://vault/item/key\n', 'op://vault/item/key?x=1']:
            self.write_reference(ref)
            with self.subTest(reference=ref), patch.object(decisions.subprocess, 'run') as run:
                self.assertFalse(decisions.key_available())
                with self.assertRaises(decisions.DecisionError):
                    decisions._read_key()
                run.assert_not_called()
        self.write_reference()
        self.config.chmod(0o644)
        self.assertFalse(decisions.key_available())

    def test_precedence_never_resolves_lower_sources(self):
        self.write_reference()
        with patch.object(decisions.subprocess, 'run') as run:
            with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'env-key'}):
                self.assertEqual(decisions._read_key(), 'env-key')
                self.assertEqual(decisions._read_key('explicit-key'), 'explicit-key')
            self.assertEqual(decisions.setup_credentials()['status'], 'already-configured')
            run.assert_not_called()

    def test_locked_missing_timeout_are_redacted(self):
        self.write_reference()
        for failure in [FileNotFoundError('SECRET'), subprocess.TimeoutExpired(['op'], 5, output='SECRET'),
                        subprocess.CompletedProcess([], 1, 'SECRET', 'SECRET')]:
            options = {'side_effect': failure} if isinstance(failure, Exception) else {'return_value': failure}
            with self.subTest(failure=type(failure)), patch.object(decisions.subprocess, 'run', **options):
                with self.assertRaises(decisions.DecisionError) as caught:
                    decisions._read_key()
                self.assertNotIn('SECRET', str(caught.exception))
        self.config.unlink()
        with patch.object(decisions.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, 'SECRET', 'SECRET')):
            result = decisions.setup_credentials()
            self.assertEqual(result['status'], 'skipped')
            self.assertNotIn('SECRET', json.dumps(result))

    def test_empty_api_key_fails_before_provider_call(self):
        self.write_reference()
        with patch.object(decisions.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')), \
                patch.object(decisions.urllib.request, 'build_opener') as opener:
            with self.assertRaisesRegex(decisions.DecisionError, 'field is empty'):
                decisions.evaluate('test', 'context')
            opener.assert_not_called()

    def test_ambiguous_api_fields_do_not_write(self):
        with self.fake_op(fields=[{'id': 'a', 'label': 'API Key'}, {'id': 'b', 'label': 'api_key'}]):
            self.assertEqual(decisions.setup_credentials()['status'], 'skipped')
        self.assertFalse(self.config.exists())

    def test_section_identifiers_and_values_never_persist(self):
        with self.fake_op(fields=[{'id': 'api-field', 'label': 'api_key', 'section': {'id': 'section-id'},
                                  'value': 'PRIVATE_API_KEY'}]):
            result = decisions.setup_credentials()
        self.assertEqual(json.loads(self.config.read_text())['secret_reference'],
                         'op://vault-id/item-id/section-id/api-field')
        self.assertNotIn('PRIVATE_API_KEY', json.dumps(result) + self.config.read_text())

    def test_fake_cli_setup_and_doctor(self):
        executable = Path(self.directory.name) / 'op'
        executable.write_text("""#!/usr/bin/env python3
import json
import sys
if sys.argv[1:3] == ['item', 'list']:
    print(json.dumps([{'title': 'OpenRouter', 'id': 'item', 'vault': {'id': 'vault'}}]))
elif sys.argv[1:3] == ['item', 'get']:
    print(json.dumps({'fields': [{'id': 'key', 'label': 'API Key', 'value': 'PRIVATE_KEY'}]}))
else:
    print('PRIVATE_KEY', file=sys.stderr)
    sys.exit(1)
""")
        executable.chmod(0o700)
        environment = dict(os.environ, PATH=self.directory.name + os.pathsep + os.defpath)
        result = subprocess.run(['/bin/bash', str(ROOT / 'scripts/configure-openrouter.sh')],
                                env=environment, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'configured')
        self.assertNotIn('PRIVATE_KEY', result.stdout + result.stderr + self.config.read_text())
        executable.write_text('#!/bin/sh\nexit 88\n')
        result = subprocess.run([os.sys.executable, str(ROOT / 'Tools/agency-decide'), 'doctor'],
                                env=environment, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['configured'])

    def test_cli_does_not_print_secret(self):
        self.write_reference()
        with patch.object(decisions.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, 'SECRET', 'SECRET')), \
                patch('sys.stderr', new_callable=io.StringIO) as error, patch('sys.stdout', new_callable=io.StringIO) as output, \
                patch.object(decisions, 'read_input', return_value='test'):
            self.assertEqual(decisions.main(['classify', '--profile', 'context', '--input', '-']), 2)
            self.assertEqual(output.getvalue(), '')
            self.assertNotIn('SECRET', error.getvalue())


if __name__ == '__main__':
    unittest.main()
