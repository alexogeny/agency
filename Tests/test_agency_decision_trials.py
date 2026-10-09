import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('decision_trials', ROOT / 'Tools/agency_decision_trials.py')
d = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(d)
PROFILES = {'context', 'test-relevance'}


def pair(identifier='a', profile='context'):
    return {'id': identifier, 'profile': profile,
            'baseline': {'accepted': True, 'elapsed_ms': 100, 'cost': 2, 'repairs': 1},
            'jev': {'accepted': True, 'elapsed_ms': 80, 'cost': 3, 'repairs': 0,
                    'preparation_ms': 10, 'decision_ms': 5, 'overrides': 1,
                    'useful_corrections': 2}}


class TrialTests(unittest.TestCase):
    def test_trial_cohorts_preserve_versions_workload_and_missing_provenance(self):
        provenance = {'model': 'typesafe/jev-1.13-20260917', 'profile_version': '2',
                      'rubric_sha256': 'a' * 64, 'workload': 'claim-review-v1',
                      'baseline_model': 'reasoner-v1', 'assisted_model': 'reasoner-v1'}
        first = {**pair(), 'provenance': provenance}
        second = {**pair('b'), 'provenance': {**provenance, 'model': 'typesafe/jev-1.13-20260918'}}
        third = {**pair('c'), 'provenance': {**provenance, 'workload': 'claim-review-v2'}}
        fourth = {**pair('d'), 'provenance': {**provenance, 'rubric_sha256': 'b' * 64}}
        fifth = {**pair('e'), 'provenance': {**provenance, 'profile_version': '3'}}
        sixth = {**pair('f'), 'provenance': {**provenance, 'baseline_model': 'reasoner-v2'}}
        seventh = {**pair('g'), 'provenance': {**provenance, 'assisted_model': 'reasoner-v2'}}
        repeated = {**pair('repeat'), 'provenance': provenance}
        rows = [first, second, third, fourth, fifth, sixth, seventh, repeated, pair('legacy')]
        original = copy.deepcopy(rows)
        report = d.summarize_trials({'items': rows}, PROFILES)
        self.assertEqual(rows, original)
        self.assertEqual(len(report['by_cohort']), 8)
        self.assertEqual(report['by_cohort'][0]['provenance'], provenance)
        self.assertEqual(report['by_cohort'][0]['pair_ids'], ['a', 'repeat'])
        self.assertIsNone(report['by_cohort'][-1]['provenance'])
        self.assertFalse(report['overall']['provenance_complete'])
        self.assertEqual(report['overall']['provenance_missing_count'], 1)
        self.assertTrue(report['by_profile']['context']['mixed_provenance'])

    def test_reasoning_tokens_preserve_unknown_measurements(self):
        first, second = pair(), pair('b')
        first['baseline']['reasoning_tokens'] = 100
        second['baseline']['reasoning_tokens'] = 200
        first['jev']['reasoning_tokens'] = 50
        second['jev']['reasoning_tokens'] = None
        report = d.summarize_trials({'items': [first, second]}, PROFILES)['overall']
        self.assertEqual(report['baseline']['total_reasoning_tokens'], 300)
        self.assertEqual(report['baseline']['reasoning_tokens_per_accepted'], 150)
        self.assertIsNone(report['jev']['total_reasoning_tokens'])
        self.assertEqual(report['jev']['reasoning_tokens_missing_count'], 1)
        self.assertIsNone(report['mean_paired_delta']['reasoning_tokens'])
        second['jev']['reasoning_tokens'] = 0
        report = d.summarize_trials({'items': [first, second]}, PROFILES)['overall']
        self.assertEqual(report['mean_paired_delta']['reasoning_tokens'], -125)
        for invalid in (True, -1, 1.5, '1', float('inf')):
            first['jev']['reasoning_tokens'] = invalid
            with self.subTest(value=invalid), self.assertRaises(d.TrialError):
                d.summarize_trials({'items': [first]}, PROFILES)

    def test_provenance_is_complete_or_explicitly_unknown(self):
        for invalid in ({}, {'model': 'jev'}, None, 'version',
                        {'model': 'jev', 'profile_version': '1', 'rubric_sha256': 'bad',
                         'workload': 'test', 'baseline_model': 'r', 'assisted_model': 'r'}):
            with self.subTest(provenance=invalid), self.assertRaises(d.TrialError):
                d.summarize_trials({'items': [{**pair(), 'provenance': invalid}]}, PROFILES)
        legacy = d.summarize_trials({'items': [pair()]}, PROFILES)
        self.assertEqual(legacy['overall']['provenance_missing_count'], 1)
        self.assertIsNone(legacy['overall']['baseline']['total_reasoning_tokens'])

    def test_paired_summary_includes_failed_attempts_and_profile_groups(self):
        first, second = pair(), pair('b', 'test-relevance')
        second['baseline'].update(accepted=False, elapsed_ms=200, cost=4, repairs=3)
        second['jev'].update(elapsed_ms=120, cost=5, repairs=2)
        manifest = {'items': [first, second]}
        original = copy.deepcopy(manifest)
        report = d.summarize_trials(manifest, PROFILES)
        self.assertEqual(manifest, original)
        self.assertTrue(report['advisory'])
        self.assertEqual(report['pair_count'], 2)
        total = report['overall']
        self.assertEqual(total['pair_count'], 2)
        baseline, jev = total['baseline'], total['jev']
        self.assertEqual((baseline['accepted'], baseline['unaccepted'], baseline['acceptance_rate']), (1, 1, .5))
        self.assertEqual((jev['accepted'], jev['unaccepted'], jev['acceptance_rate']), (2, 0, 1))
        self.assertEqual((baseline['total_elapsed_ms'], baseline['mean_elapsed_ms']), (300, 150))
        self.assertEqual((baseline['total_repairs'], baseline['mean_repairs']), (4, 2))
        self.assertEqual((baseline['total_cost'], baseline['mean_cost']), (6, 3))
        self.assertEqual((baseline['cost_known_count'], baseline['cost_missing_count']), (2, 0))
        self.assertEqual(baseline['elapsed_ms_per_accepted'], 300)
        self.assertEqual(baseline['cost_per_accepted'], 6)
        self.assertEqual(jev['elapsed_ms_per_accepted'], 100)
        self.assertEqual(jev['cost_per_accepted'], 4)
        for metric, total_value in [('preparation_ms', 20), ('decision_ms', 10), ('overrides', 2), ('useful_corrections', 4)]:
            self.assertEqual(jev['total_' + metric], total_value)
            self.assertEqual(jev['mean_' + metric], total_value / 2)
        self.assertEqual(total['mean_paired_delta'], {'elapsed_ms': -50, 'repairs': -1, 'cost': 1, 'reasoning_tokens': None})
        self.assertEqual(set(report['by_profile']), PROFILES)
        self.assertEqual(report['by_profile']['context']['pair_count'], 1)
        self.assertNotIn('items', report)

    def test_missing_cost_is_not_zero_and_zero_acceptances_have_no_unit_cost(self):
        first, second = pair(), pair('b')
        first['baseline'].update(cost=None, accepted=False)
        second['baseline']['accepted'] = False
        for items in ([first, second], [second, first]):
            result = d.summarize_trials({'items': items}, PROFILES)['overall']
            self.assertEqual(result['baseline']['cost_known_count'], 1)
            self.assertEqual(result['baseline']['cost_missing_count'], 1)
            for key in ('total_cost', 'mean_cost', 'cost_per_accepted', 'elapsed_ms_per_accepted'):
                self.assertIsNone(result['baseline'][key])
            self.assertIsNone(result['mean_paired_delta']['cost'])
            self.assertEqual(result['jev']['total_cost'], 6)

    def test_all_validation_finishes_before_summary(self):
        invalid = pair('b')
        invalid['jev']['cost'] = -1
        with patch.object(d, '_summarize') as calculate:
            with self.assertRaises(d.TrialError):
                d.summarize_trials({'items': [pair(), invalid]}, PROFILES)
        calculate.assert_not_called()

    def test_rejects_bad_shapes_ids_profiles_and_limits(self):
        bad_manifests = [None, [], {}, {'items': []}, {'items': ()},
                         {'items': [pair()], 'extra': True}, {'items': [pair(), pair()]},
                         {'items': [pair(str(i)) for i in range(1025)]}]
        for key, value in [('id', ''), ('id', 'a' * 129), ('id', '../x'), ('id', True),
                           ('profile', 'missing'), ('profile', []), ('extra', 1), ('baseline', [])]:
            item = pair()
            item[key] = value
            bad_manifests.append({'items': [item]})
        missing = pair()
        del missing['jev']['overrides']
        bad_manifests.append({'items': [missing]})
        for manifest in bad_manifests:
            with self.subTest(manifest=str(manifest)[:150]), self.assertRaises(d.TrialError):
                d.summarize_trials(manifest, PROFILES)

    def test_numeric_validation_rejects_booleans_nonfinite_and_nonintegers(self):
        for arm in ('baseline', 'jev'):
            for key in pair()[arm]:
                if key == 'accepted':
                    values = [0, 1, None, 'true']
                elif key in ('repairs', 'overrides', 'useful_corrections'):
                    values = [True, -1, 1.5, None, '1']
                else:
                    values = [True, -1, float('nan'), float('inf'), -float('inf'), '1', 10 ** 1000]
                    if key != 'cost':
                        values.append(None)
                for value in values:
                    item = pair()
                    item[arm][key] = value
                    with self.subTest(arm=arm, key=key, value=str(value)[:30]), self.assertRaises(d.TrialError):
                        d.summarize_trials({'items': [item]}, PROFILES)

    def test_full_capacity_zero_values_and_overlapping_component_time(self):
        item = pair()
        item['jev'].update(elapsed_ms=1, preparation_ms=5, decision_ms=5)
        item['baseline'].update(elapsed_ms=0, cost=0, repairs=0)
        rows = [dict(item, id=str(index)) for index in range(1024)]
        self.assertEqual(d.summarize_trials({'items': rows}, PROFILES)['pair_count'], 1024)


if __name__ == '__main__':
    unittest.main()
