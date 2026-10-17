import copy
import pytest
from scripts.compare_reviews import compare_reviews
from scripts.run_review_trial import run_cases

def review(reviewer='A', leak='no'):
    return {'reviewer': reviewer, 'evidence_hash': 'same-evidence', 'complete': True, 'records': [{'unit_id': 'u1', 'leak': leak, 'utility': 'na', 'false_pause': 'na', 'required_facts': '人数', 'forbidden_facts': '电话', 'notes': '已检查完整上下文', 'viewed_result': True}]}

def test_disagreement_and_joint_uncertainty_require_arbitration():
    assert compare_reviews(review(), review('B', 'yes'))['pending_adjudication'] == 1
    assert compare_reviews(review(leak='uncertain'), review('B', 'uncertain'))['pending_adjudication'] == 1
    assert compare_reviews(review(), review('B'))['agreement_rate'] == 1

@pytest.mark.parametrize('change', ['hash', 'reviewer', 'empty', 'duplicate', 'draft'])
def test_invalid_pair_cannot_be_aggregated(change):
    b = review('B')
    if change == 'hash':
        b['evidence_hash'] = 'other-version'
    elif change == 'reviewer':
        b['reviewer'] = 'A'
    elif change == 'empty':
        b['records'][0]['notes'] = ''
    elif change == 'duplicate':
        b['records'].append(copy.deepcopy(b['records'][0]))
    elif change == 'draft':
        b['complete'] = False
    with pytest.raises(ValueError):
        compare_reviews(review(), b)

def test_trial_captures_sanitized_history_and_does_not_call_network(monkeypatch):
    import llm_shield.m7_egress.llm_client as adapter
    monkeypatch.setattr(adapter, 'OpenAICompatLLM', lambda *a: pytest.fail('Trial must stay offline'))
    records = run_cases([{'id': 'x', 'task': 'meeting_minutes', 'turns': ['负责人：张明。事项：准备海报。期限：周五。', '请沿用前面的负责人代号，期限改为下周一。']}])
    assert len(records) == 2
    assert all((not r['network_requested'] for r in records))
    assert all((r['response']['ok'] for r in records))
    assert len(records[1]['outgoing'][0]['messages']) == 4
    assert '张明' not in str(records[0]['outgoing'])
