"""Direct-work and safety checks for coordination and decision runtime costs."""

import importlib.machinery
import importlib.util
import io
import json
import os
import random
import re
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest import mock

ROOT = Path(os.environ.get('AGENCY_SOURCE_ROOT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / 'Tools'))
import agency_decisions as decisions
import agency_decision_usage as usage
import agent_work_messages as messages

loader = importlib.machinery.SourceFileLoader('holistic_decide_mcp', str(ROOT / 'Tools/agency-decide-mcp'))
spec = importlib.util.spec_from_loader(loader.name, loader)
mcp = importlib.util.module_from_spec(spec)
loader.exec_module(mcp)


class DecisionWorkTests(unittest.TestCase):
    def test_evaluate_serializes_the_validated_provider_payload_once(self):
        labels = decisions.PROFILES['context']['criteria']
        choice = next(iter(labels))
        payload = {'model': decisions.MODEL, 'answers': {'decision': {
            'type': 'choice', 'choice': choice,
            'probabilities': {label: float(label == choice) for label in labels}}},
            'usage': {'input_tokens': 23, 'output_tokens': 1, 'cost': 0.001}}
        raw = json.dumps(payload).encode()
        captured = []

        def open_request(request, timeout):
            captured.append(request)
            stream = io.BytesIO(raw)
            stream.status = 200
            return stream

        opener = mock.Mock()
        opener.open.side_effect = open_request
        state = {'query': 'Inspect coordination ownership', 'passage': 'Evidence ' * 2000}
        original = json.loads(json.dumps(state))
        with mock.patch.object(decisions.urllib.request, 'build_opener', return_value=opener), \
             mock.patch.object(decisions.json, 'dumps', wraps=json.dumps) as encoded:
            value = decisions.evaluate(state, 'context', api_key='fixture-private-key')
        full_payloads = [call for call in encoded.call_args_list
                         if isinstance(call.args[0], dict) and set(call.args[0]) == {'model', 'state', 'questions'}]
        self.assertEqual(len(full_payloads), 1)
        self.assertEqual(len(captured), 1)
        self.assertEqual(json.loads(captured[0].data), decisions.build_request(state, 'context'))
        self.assertEqual(value['decision'], choice)
        self.assertEqual(value['usage'], payload['usage'])
        self.assertEqual(state, original)
        self.assertNotIn('fixture-private-key', json.dumps(value))

    def test_mcp_resolves_fresh_private_credential_once_per_classification(self):
        classifier = mock.Mock(cli=mcp.CLI)
        classifier.classify.return_value = {'advisory': True, 'decision': 'none'}
        environment = {name: value for name, value in os.environ.items() if name != 'OPENROUTER_API_KEY'}
        with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(mcp, '_classifier', classifier):
            for key in ('fixture-first-key', 'fixture-second-key'):
                with self.subTest(key=key), mock.patch.object(decisions, '_private_file',
                        return_value=json.dumps({'api_key': key})) as read:
                    value = mcp.call_tool('classify', {'profile': 'skill', 'state': {'task': 'review'}})
                    self.assertEqual(read.call_count, 1)
                    self.assertEqual(classifier.classify.call_args.args[2], key)
                    self.assertNotIn(key, json.dumps(value))
        self.assertEqual(classifier.classify.call_count, 2)

    def test_mcp_secure_credential_errors_are_generic_and_never_dispatch(self):
        environment = {name: value for name, value in os.environ.items() if name != 'OPENROUTER_API_KEY'}
        with mock.patch.dict(os.environ, environment, clear=True), \
             mock.patch.object(mcp.DecisionWorker, 'classify') as classify:
            for source in (None, decisions.DecisionError('fixture sensitive detail')):
                options = {'side_effect': source} if isinstance(source, Exception) else {'return_value': source}
                with self.subTest(source=source), mock.patch.object(decisions, '_private_file', **options):
                    with self.assertRaisesRegex(decisions.DecisionError,
                            '^OpenRouter credential is not configured securely\\.$'):
                        mcp.call_tool('classify', {'profile': 'skill', 'state': {'task': 'review'}})
        classify.assert_not_called()


class SnapshotWorkTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE fixture(value TEXT)')
        self.statements = []
        self.db.set_trace_callback(self.statements.append)

    def snapshot_statements(self):
        return [query for query in self.statements if query.startswith(('SAVEPOINT', 'RELEASE'))]

    def test_nested_read_boundaries_use_one_snapshot_pair(self):
        with messages.read_snapshot(self.db):
            self.assertTrue(self.db.in_transaction)
            with messages.read_snapshot(self.db):
                self.assertEqual(self.db.execute('SELECT COUNT(*) FROM fixture').fetchone()[0], 0)
            self.assertTrue(self.db.in_transaction)
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(len(self.snapshot_statements()), 2)

    def test_existing_writer_transaction_needs_no_read_savepoint(self):
        self.db.execute('BEGIN IMMEDIATE')
        self.db.execute("INSERT INTO fixture VALUES ('uncommitted')")
        with self.assertRaisesRegex(ValueError, 'fixture'):
            with messages.read_snapshot(self.db):
                self.assertEqual(self.db.execute('SELECT value FROM fixture').fetchone()[0], 'uncommitted')
                raise ValueError('fixture')
        self.assertTrue(self.db.in_transaction)
        self.assertEqual(self.snapshot_statements(), [])
        self.db.rollback()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM fixture').fetchone()[0], 0)


def receipt_oracle(value):
    """Original eager DFS, retained independently as a visitation-prefix oracle."""
    found, complete = {}, True
    pending, visits, parsed_bytes = [(value, 0)], 0, 0
    while pending:
        item, depth = pending.pop()
        visits += 1
        if depth > 12 or visits > 4096:
            complete = False
            break
        if isinstance(item, dict):
            if usage.MARKER in item:
                report = item[usage.MARKER]
                if (type(report) is dict and type(report.get('version')) is int and report['version'] == 1
                        and type(report.get('id')) is str and re.fullmatch(r'[0-9a-f]{32}', report['id'])
                        and type(report.get('created_ns')) is int
                        and all(type(report.get(key)) is int and 0 <= report[key] <= 1024
                                for key in ('decisions', 'errors', 'reused'))):
                    found[report['id']] = report
                else:
                    complete = False
                continue
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, str) and usage.MARKER in item:
            parsed_bytes += len(item)
            if parsed_bytes > 4 * usage.MAX_INPUT:
                complete = False
                break
            try:
                decoded = json.loads(item)
            except (ValueError, RecursionError):
                decoded = None
            if decoded is not None:
                pending.append((decoded, depth + 1))
            else:
                for line in item.splitlines():
                    if usage.MARKER not in line or not line.lstrip().startswith(('{', '[')):
                        continue
                    try:
                        decoded = json.loads(line)
                    except (ValueError, RecursionError):
                        complete = False
                        continue
                    pending.append((decoded, depth + 1))
    return found, complete


def fixed_receipt(identifier, decisions=1):
    return {usage.MARKER: {'version': 1, 'id': f'{identifier:032x}', 'created_ns': 1,
                           'decisions': decisions, 'errors': 0, 'reused': 0}}


class ReceiptWorkTests(unittest.TestCase):
    def test_wide_container_worklist_stays_bounded_and_keeps_original_prefix(self):
        value = [fixed_receipt(1)] + [0] * 100000 + [fixed_receipt(2)]
        peak = 0
        code = usage.receipts.__code__
        def trace(frame, event, arg):
            nonlocal peak
            if frame.f_code is code:
                peak = max(peak, len(frame.f_locals.get('pending', ())))
                return trace
            return None
        previous = sys.gettrace()
        sys.settrace(trace)
        try:
            actual = usage.receipts(value)
        finally:
            sys.settrace(previous)
        self.assertEqual(actual, receipt_oracle(value))
        self.assertEqual(set(actual[0]), {f'{2:032x}'})
        self.assertFalse(actual[1])
        self.assertLessEqual(peak, 14)

    def test_receipt_order_depth_and_visit_boundaries_match_original_dfs(self):
        duplicate = [fixed_receipt(1, 10), fixed_receipt(1, 20)]
        nested = fixed_receipt(3)
        for _ in range(13):
            nested = [nested]
        fixtures = [duplicate, nested, [0] * 4095, [0] * 4096,
                    {'first': fixed_receipt(1), 'last': fixed_receipt(1, 99)},
                    json.dumps(duplicate), 'prefix\n' + json.dumps(fixed_receipt(4)) + '\n{"_agency_decisions":',
                    {usage.MARKER: {'version': True}},
                    json.dumps(json.dumps(fixed_receipt(5)))]
        rng = random.Random(73)
        for _ in range(50):
            children = [fixed_receipt(rng.randrange(5), rng.randrange(100)),
                        [rng.randrange(10) for _ in range(rng.randrange(20))]]
            value = children
            for depth in range(rng.randrange(16)):
                value = {'child': value, 'other': rng.choice((None, False, 'plain'))} if depth % 2 else [value]
            fixtures.append(value)
        for index, value in enumerate(fixtures):
            with self.subTest(index=index):
                self.assertEqual(usage.receipts(value), receipt_oracle(value))
        self.assertEqual(usage.receipts(duplicate)[0][f'{1:032x}']['decisions'], 10)


if __name__ == '__main__':
    unittest.main()
