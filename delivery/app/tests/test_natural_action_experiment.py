import copy
import json

import pytest

from llm_shield.m4_necessity.research import case_hash, training_sample
from scripts.run_natural_action_experiment import (
    DEFAULT_PACK, DEFAULT_REVIEW, apply_ai_review, calibrated_result,
)


def inputs():
    cases = [json.loads(s) for s in (DEFAULT_PACK/'cases.jsonl').read_text(encoding='utf8').splitlines()]
    review = json.loads(DEFAULT_REVIEW.read_text(encoding='utf8'))
    return cases, review


def test_applies_all_eight_review_changes_without_changing_inputs_or_human_status():
    cases, review = inputs()
    merged = apply_ai_review(cases, review)
    assert len(merged) == len(cases) == 138
    assert sum(a['proposal']['action'] != b['proposal']['action'] for a,b in zip(merged,cases)) == 8
    assert all(case_hash(a) == case_hash(b) for a,b in zip(merged,cases))
    assert all(c['review']['status'] == 'machine_draft' for c in merged)
    for a, b in zip(merged, cases):
        assert training_sample(a, allow_drafts=True)['feature'] == training_sample(b, allow_drafts=True)['feature']


@pytest.mark.parametrize('damage', ['missing','duplicate','hash','top_human','row_human','representation'])
def test_invalid_review_input_cannot_silently_train(damage):
    cases, review = inputs()
    if damage == 'missing':
        review['reviews'].pop()
    elif damage == 'duplicate':
        review['reviews'].append(copy.deepcopy(review['reviews'][0]))
    elif damage == 'hash':
        review['reviews'][0]['case_sha256'] = 'outdated'
    elif damage == 'top_human':
        review['human_reviewed'] = True
    elif damage == 'row_human':
        review['reviews'][0]['human_reviewed'] = True
    else:
        review['reviews'][0]['annotation']['minimum_representation'] = 'none'
    with pytest.raises(ValueError):
        apply_ai_review(cases, review)


def test_failed_calibration_never_runs_uncalibrated_candidate_as_if_accepted():
    result = calibrated_result(object(), [object(), object()], None)
    assert result['status'] == 'not_evaluated_no_feasible_threshold'
    assert result['n'] == 2 and result['rows'] == []
    assert result['deployment_eligible'] is False
    assert 'acceptable_action_rate' not in result
