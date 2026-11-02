"""Metric and supervision checks; fixtures are software data, never human gold."""
import json

import pytest

from scripts.build_action_review import build_legacy_cases
from scripts.run_confirmed_action_retraining import ACTIONS, classification, run


def test_abstention_does_not_become_raw_classifier_success():
    rows = [{'expected': 'RETAIN', 'raw_predicted': 'RETAIN', 'predicted': 'PAUSE'}]
    raw = classification(rows, 'raw_predicted')
    final = classification(rows)
    assert raw['accuracy'] == 1 and final['accuracy'] == 0
    retain, pause = ACTIONS.index('RETAIN'), ACTIONS.index('PAUSE')
    assert final['confusion']['counts'][retain][pause] == 1
    assert final['per_action']['PAUSE']['support'] == 0


def test_exact_classification_does_not_count_a_permitted_alternative_as_exact():
    rows = [{'expected': 'GENERALIZE', 'predicted': 'DELETE', 'acceptable': True},
            {'expected': 'DELETE', 'predicted': 'DELETE', 'acceptable': True}]
    metrics = classification(rows)
    assert metrics['correct'] == 1 and metrics['accuracy'] == .5
    assert metrics['per_action']['GENERALIZE']['recall'] == 0
    assert metrics['per_action']['DELETE']['precision'] == .5


def test_draft_source_is_rejected_before_creating_a_training_directory(tmp_path):
    path = tmp_path/'automated_draft_fixture.jsonl'
    path.write_text(''.join(json.dumps(c, ensure_ascii=False)+'\n' for c in build_legacy_cases()), encoding='utf8')
    out = tmp_path/'must_not_train'
    with pytest.raises(ValueError, match='二审确认标签'):
        run(path, out)
    assert not out.exists()
