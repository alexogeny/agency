import contextlib
import io
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from Tests.test_housekeeping import load_tool


class HousekeepingFlowTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_native_and_application_output_preserves_order_and_escapes_controls(self):
        for application in (False, True):
            with self.subTest(application=application):
                item = dict(path='/fixture/cache', action='uv', title='UV cache', executable='/fixture/uv',
                            allocated_bytes=20, selectable=True, provider=application, tradeoff='Regenerates')
                plan = dict(actions=[] if application else [item],
                            application_candidates=[item] if application else [])
                process = subprocess.CompletedProcess([], 0, 'alpha\nbeta\x1b[31m \n\n', 'warning\u202e\n')
                provider = SimpleNamespace(
                    report_actions=Mock(return_value={'blocked': {}, 'uninspected_processes': 0}),
                    execute=Mock(return_value=process),
                )
                output = io.StringIO()
                with patch('builtins.input', return_value='yes'), \
                     patch.object(self.tool, 'project_helpers', return_value=object()), \
                     patch.object(self.tool, 'provider_helpers', return_value=provider), \
                     patch.object(self.tool, 'choose_projects', return_value=[item]), \
                     patch.object(self.tool, 'verify_cache') as verify, \
                     patch.object(self.tool, 'run_cleanup_command', return_value=process) as run, \
                     contextlib.redirect_stdout(output):
                    self.assertEqual(self.tool.apply_cleanup(plan, colour=False), 0)
                self.assertIn('alpha\nbeta\\x1b[31m\nwarning\\u202e\n', output.getvalue())
                self.assertNotIn('\x1b', output.getvalue())
                self.assertNotIn('\u202e', output.getvalue())
                if application:
                    provider.execute.assert_called_once_with(item)
                    run.assert_not_called()
                    verify.assert_not_called()
                else:
                    run.assert_called_once()
                    provider.execute.assert_not_called()
                    self.assertEqual(verify.call_count, 3)

    def test_empty_command_output_does_not_add_blank_output_lines(self):
        item = dict(path='/fixture/cache', action='uv', title='UV cache', executable='/fixture/uv')
        output = io.StringIO()
        with patch('builtins.input', return_value='yes'), \
             patch.object(self.tool, 'verify_cache'), \
             patch.object(self.tool, 'run_cleanup_command', return_value=subprocess.CompletedProcess([], 0, ' \n\t', '')), \
             contextlib.redirect_stdout(output):
            self.assertEqual(self.tool.apply_cleanup({'actions': [item]}, colour=False), 0)
        self.assertEqual(output.getvalue().splitlines(), [
            'Cleaning: UV cache',
            'Completed 1 cache cleanup commands and 0 selected cleanup actions. Run housekeeping again to refresh usage.',
        ])

    def test_availability_distinguishes_blocked_refreshable_and_review_only_rows(self):
        items = [
            dict(path='/cleanup/blocked', selectable=True, reason='Original'),
            dict(path='/cleanup/refreshable', selectable=False, refreshable=True, reason='Refresh me'),
            dict(path='/cleanup/review', selectable=False, reason='Review only'),
        ]
        original = [dict(item) for item in items]
        helper = SimpleNamespace(report_projects=Mock(return_value={
            'blocked': {'/cleanup/blocked': 'New blocker'}, 'uninspected_processes': 0,
        }))
        with patch.object(self.tool, 'project_helpers', return_value=helper), \
             patch.object(self.tool, 'choose_projects', return_value=[]) as choose, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.tool.apply_cleanup({'root': '/cleanup', 'actions': [], 'project_candidates': items}), 0)
        candidates = choose.call_args.args[0]
        self.assertEqual([(item['selectable'], item['reason']) for item in candidates], [
            (False, 'New blocker'),
            (True, 'Availability and retention rechecked; choose explicitly.'),
            (False, 'Review only'),
        ])
        self.assertEqual(items, original)
