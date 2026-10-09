import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('decision_contracts', ROOT / 'Tools/agency_decisions.py')
d = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(d)


class ContractTests(unittest.TestCase):
    def test_original_profiles_reject_missing_or_unstructured_evidence(self):
        fields = {'skill': ('task',), 'context': ('query', 'passage'),
                  'update': ('update', 'task_status'), 'research': ('claim', 'passage')}
        for profile, required in fields.items():
            state = dict.fromkeys(required, 'Concrete evidence.')
            self.assertEqual(d.build_request(state, profile)['state'], state)
            for invalid in ('legacy text', ['legacy text'], {'unrelated': 'text'},
                            *({**state, field: ''} for field in required),
                            *({k: v for k, v in state.items() if k != field} for field in required)):
                with self.subTest(profile=profile, state=invalid), self.assertRaises(d.DecisionError):
                    d.build_request(invalid, profile)

    def test_evaluation_fixture_covers_every_profile_and_multiple_labels(self):
        cases = json.loads((ROOT / 'Tests/fixtures/decisions.json').read_text())['items']
        self.assertEqual({case['profile'] for case in cases}, set(d.PROFILES))
        for profile in d.PROFILES:
            with self.subTest(profile=profile):
                self.assertGreaterEqual(len({case['expected'] for case in cases
                                             if case['profile'] == profile}), 2)

    def test_scope_requires_review_even_for_a_confident_result(self):
        labels = d.PROFILES['scope']['criteria']
        payload = {'model': d.MODEL, 'answers': {'decision': {
            'type': 'choice', 'choice': 'requested', 'confidence': 1,
            'probabilities': {key: float(key == 'requested') for key in labels}}},
            'usage': {'input_tokens': 10, 'output_tokens': 1}}
        self.assertTrue(d._validate_response(payload, 'scope')['review_required'])

    def test_shared_and_skill_owned_contracts_are_available(self):
        required = {'novelty', 'failure', 'scope', 'steering', 'feedback',
                    'assess/criterion', 'evidence-review/eligibility', 'comment-audit/purpose',
                    'performance-design/pattern', 'pr-writing/impact'}
        self.assertTrue(required <= d.PROFILES.keys())
        for name in required:
            self.assertIn('unsure', d.PROFILES[name]['criteria'])
            self.assertTrue(d.PROFILES[name]['required_fields'])

    def test_assessment_uses_exact_supplied_bands_and_requires_coverage(self):
        state = {'criterion': 'State the result and its limitation.',
                 'evidence': 'The result increased; the sample was small.',
                 'evidence_complete': True,
                 'bands': {'pass': 'States both result and limitation.', 'fail': 'Omits either.'}}
        request = d.build_request(state, 'assess/criterion')
        criteria = request['questions']['decision']['criteria']
        self.assertEqual({k: criteria[k] for k in state['bands']}, state['bands'])
        self.assertEqual(set(criteria), {'pass', 'fail', 'insufficient', 'unsure'})
        for mutation in ({'evidence_complete': 'yes'}, {'bands': {'unsure': 'pass'}},
                         {'bands': {'pass': ''}}, {'bands': ['pass', 'fail']}):
            with self.subTest(mutation=mutation), self.assertRaises(d.DecisionError):
                d.build_request({**state, **mutation}, 'assess/criterion')
        del state['evidence_complete']
        with self.assertRaises(d.DecisionError):
            d.build_request(state, 'assess/criterion')

    def test_missing_structured_evidence_is_rejected(self):
        for name in ('novelty', 'failure', 'scope', 'steering', 'feedback', 'evidence-review/eligibility'):
            with self.subTest(profile=name), self.assertRaises(d.DecisionError):
                d.build_request({'unrelated': 'text'}, name)

    def test_assessment_response_is_validated_against_this_request(self):
        state = {'criterion': 'Contains a limitation', 'evidence': 'Small sample.',
                 'evidence_complete': True, 'bands': {'met': 'Present', 'unmet': 'Absent'}}
        labels = d.build_request(state, 'assess/criterion')['questions']['decision']['criteria']
        payload = {'model': d.MODEL, 'answers': {'decision': {
            'type': 'choice', 'choice': 'met', 'probabilities': {k: float(k == 'met') for k in labels}}},
            'usage': {'input_tokens': 10, 'output_tokens': 1}}
        self.assertEqual(d._validate_response(payload, 'assess/criterion', labels)['decision'], 'met')
        payload['answers']['decision']['choice'] = 'distinction'
        with self.assertRaises(d.DecisionError):
            d._validate_response(payload, 'assess/criterion', labels)

    def test_synthetic_evaluation_cases_have_valid_contracts(self):
        cases = json.loads((ROOT / 'Tests/fixtures/decisions.json').read_text())['items']
        self.assertGreaterEqual(len(cases), 20)
        self.assertEqual(len({c['id'] for c in cases}), len(cases))
        for case in cases:
            with self.subTest(case=case['id']):
                labels = d.build_request(case['state'], case['profile'])['questions']['decision']['criteria']
                self.assertIn(case['expected'], labels)
        self.assertGreaterEqual(sum(c['profile'] == 'assess/criterion' for c in cases), 5)
