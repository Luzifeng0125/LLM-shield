import copy

from llm_shield.m5_utility.estimator import estimate
from llm_shield.schema import Action, Decision


def test_single_person_with_stable_code_is_not_penalized_for_being_single():
    decisions = [Decision('s', Action.PSEUDONYMIZE, ['PERSON_NAME'])]
    before = copy.deepcopy(decisions)
    result = estimate('人员甲负责周五提交活动海报。', 'meeting_minutes', decisions=decisions)
    assert result['warnings'] == []
    assert result['completeness'] == 1.0
    assert result['notes']
    assert decisions == before


def test_explicit_zero_is_valid_but_missing_count_is_not_zero():
    zero = estimate('活动已结束。', 'activity_stats', {'person_count':0})
    missing = estimate('活动已结束。', 'activity_stats')
    assert zero['checks']['COUNT']['status'] == 'pass'
    assert missing['checks']['COUNT']['status'] == 'fail'
    assert len(missing['warnings']) == 1


def test_unknown_task_is_not_automatically_complete():
    result = estimate('未知任务内容。', 'not-defined')
    assert result['completeness'] is None and not result['evaluated']
    assert result['checks']['TASK']['status'] == 'not_applicable'


def test_authorized_real_name_can_satisfy_responsibility_identifier_check():
    result = estimate('张明负责周五完成海报。', 'meeting_minutes',
                      decisions=[Decision('s', Action.RETAIN, ['PERSON_NAME'])])
    assert result['checks']['PERSON_ROLE']['status'] == 'pass'
    assert not result['warnings']


def test_notice_missing_public_facts_requests_facts_instead_of_inventing_them():
    result = estimate('', 'activity_notice')
    assert result['evaluated'] and result['completeness'] == 0
    assert any('补充' in w for w in result['warnings'])


def test_count_is_not_a_causal_relationship_or_human_utility_score():
    result = estimate('人员甲。', 'meeting_minutes')
    assert result['checks']['PERSON_ROLE']['status'] == 'pass'
    assert result['checks']['TASK_ITEM']['status'] == 'fail'
    assert result['checks']['DEADLINE']['status'] == 'fail'
    assert result['scope'] == 'local_completeness_hint_not_human_utility'
