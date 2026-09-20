import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('daily_decisions', ROOT / 'Tools/agency_decisions.py')
d = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(d)


class DailyDecisionTests(unittest.TestCase):
    def test_daily_contracts_require_actual_evidence(self):
        contracts = {
            'test-relevance': ('change', 'test'),
            'claim-fit': ('claim', 'evidence'),
            'docs-verification/drift': ('documentation', 'implementation'),
            'babysit-pr/review': ('comment', 'context'),
            'babysit-pr/dependency': ('update', 'usage'),
        }
        for name, fields in contracts.items():
            with self.subTest(profile=name):
                self.assertIn(name, d.PROFILES)
                self.assertTrue(d.PROFILES[name]['review_required'])
                state = dict.fromkeys(fields, 'A concrete source excerpt.')
                request = d.build_request(state, name)
                self.assertIn('unsure', request['questions']['decision']['criteria'])
                for missing in fields:
                    with self.assertRaises(d.DecisionError):
                        d.build_request({k: v for k, v in state.items() if k != missing}, name)
