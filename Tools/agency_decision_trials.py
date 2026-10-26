"""Validate and summarize offline paired task outcomes without storing evidence."""

import math
import re


class TrialError(ValueError):
    """A paired trial manifest cannot produce a valid report."""


_ARM_FIELDS = {'accepted', 'elapsed_ms', 'cost', 'repairs'}
_JEV_FIELDS = _ARM_FIELDS | {'preparation_ms', 'decision_ms', 'overrides', 'useful_corrections'}
_COUNTS = {'repairs', 'overrides', 'useful_corrections'}
_PROVENANCE_FIELDS = ('model', 'profile_version', 'rubric_sha256', 'workload',
                      'baseline_model', 'assisted_model')


def _validate_arm(arm, fields, location):
    if type(arm) is not dict or not fields <= set(arm) or set(arm) - fields - {'reasoning_tokens'}:
        raise TrialError(f'{location} requires the outcome fields and optional reasoning_tokens.')
    tokens = arm.get('reasoning_tokens')
    if tokens is not None and (type(tokens) is not int or tokens < 0 or tokens > 2 ** 53 - 1):
        raise TrialError(f'{location}.reasoning_tokens must be a nonnegative safe integer or null.')
    if type(arm['accepted']) is not bool:
        raise TrialError(f'{location}.accepted must be a boolean.')
    for field in fields - {'accepted'}:
        value = arm[field]
        if field == 'cost' and value is None:
            continue
        expected_types = (int,) if field in _COUNTS else (int, float)
        if type(value) not in expected_types or value < 0:
            raise TrialError(f'{location}.{field} must be a nonnegative number of the required type.')
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise TrialError(f'{location}.{field} must be finite and representable.')


def _cohort_key(item):
    provenance = item.get('provenance')
    if provenance is None:
        return item['profile'], None
    return (item['profile'], *(provenance[field] for field in _PROVENANCE_FIELDS))


def _summarize(items):
    count = len(items)
    known = sum('provenance' in item for item in items)
    summary = {'pair_count': count, 'provenance_complete': known == count,
               'provenance_known_count': known, 'provenance_missing_count': count - known,
               'mixed_provenance': len({_cohort_key(item) for item in items}) > 1}
    for name in ('baseline', 'jev'):
        arms = [item[name] for item in items]
        accepted = sum(arm['accepted'] for arm in arms)
        known_costs = [arm['cost'] for arm in arms if arm['cost'] is not None]
        total_cost = math.fsum(known_costs) if len(known_costs) == count else None
        result = {'accepted': accepted, 'unaccepted': count - accepted,
                  'acceptance_rate': accepted / count,
                  'total_cost': total_cost,
                  'mean_cost': total_cost / count if total_cost is not None else None,
                  'cost_known_count': len(known_costs),
                  'cost_missing_count': count - len(known_costs),
                  'cost_per_accepted': total_cost / accepted if accepted and total_cost is not None else None}
        tokens = [arm.get('reasoning_tokens') for arm in arms if arm.get('reasoning_tokens') is not None]
        total_tokens = sum(tokens) if len(tokens) == count else None
        result.update(reasoning_tokens_known_count=len(tokens), reasoning_tokens_missing_count=count - len(tokens),
                      total_reasoning_tokens=total_tokens,
                      mean_reasoning_tokens=total_tokens / count if total_tokens is not None else None,
                      reasoning_tokens_per_accepted=total_tokens / accepted
                      if accepted and total_tokens is not None else None)
        metrics = ('elapsed_ms', 'repairs')
        if name == 'jev':
            metrics += ('preparation_ms', 'decision_ms', 'overrides', 'useful_corrections')
        for metric in metrics:
            values = (arm[metric] for arm in arms)
            total = sum(values) if metric in _COUNTS else math.fsum(values)
            result['total_' + metric] = total
            result['mean_' + metric] = total / count
        result['elapsed_ms_per_accepted'] = result['total_elapsed_ms'] / accepted if accepted else None
        summary[name] = result
    summary['mean_paired_delta'] = {
        metric: math.fsum((item['jev'][metric] - item['baseline'][metric]) / count for item in items)
        if all(item[arm].get(metric) is not None for item in items for arm in ('baseline', 'jev')) else None
        for metric in ('elapsed_ms', 'repairs', 'cost', 'reasoning_tokens')}
    return summary


def summarize_trials(manifest, profiles):
    """Return advisory aggregate and cohort summaries for 1–1024 paired outcomes.

    ``profiles`` supplies the allowed profile names (a mapping or iterable).
    Elapsed time covers the full task, including preparation, decisions and
    repairs. Component times may overlap and are never added to elapsed time.
    Cost uses one caller-selected unit consistently across all attempts.
    """
    if type(manifest) is not dict or set(manifest) != {'items'}:
        raise TrialError('Trial manifest must contain exactly items.')
    items = manifest['items']
    if type(items) is not list or not 1 <= len(items) <= 1024:
        raise TrialError('Trial items must be a list containing 1–1024 pairs.')
    profile_names = set(profiles)
    identifiers = set()
    for index, item in enumerate(items):
        required = {'id', 'profile', 'baseline', 'jev'}
        if type(item) is not dict or not required <= set(item) or set(item) - required - {'provenance'}:
            raise TrialError(f'Trial item {index} requires id, profile, baseline, jev and optional provenance.')
        identifier = item['id']
        if type(identifier) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', identifier):
            raise TrialError(f'Trial item {index} needs a simple identifier of 1–128 characters.')
        if identifier in identifiers:
            raise TrialError(f'Trial item {index} repeats an identifier.')
        identifiers.add(identifier)
        if type(item['profile']) is not str or item['profile'] not in profile_names:
            raise TrialError(f'Trial item {index} uses an unknown profile.')
        if 'provenance' in item:
            provenance = item['provenance']
            if (type(provenance) is not dict or set(provenance) != set(_PROVENANCE_FIELDS)
                    or any(type(value) is not str or not value.strip() or len(value) > 256
                           for value in provenance.values())
                    or not re.fullmatch(r'[0-9a-f]{64}', provenance['rubric_sha256'])):
                raise TrialError(f'Trial item {index} needs complete provenance with a SHA-256 rubric hash.')
        _validate_arm(item['baseline'], _ARM_FIELDS, f'Trial item {index}.baseline')
        _validate_arm(item['jev'], _JEV_FIELDS, f'Trial item {index}.jev')

    groups = {}
    cohorts = {}
    for item in items:
        groups.setdefault(item['profile'], []).append(item)
        cohorts.setdefault(_cohort_key(item), []).append(item)
    try:
        return {'advisory': True, 'pair_count': len(items), 'overall': _summarize(items),
                'by_profile': {profile: _summarize(group) for profile, group in sorted(groups.items())},
                'by_cohort': [{'profile': group[0]['profile'], 'provenance': group[0].get('provenance'),
                               'pair_ids': [item['id'] for item in group], 'summary': _summarize(group)}
                              for group in cohorts.values()]}
    except OverflowError as error:
        raise TrialError('Trial totals exceed the supported numeric range.') from error
