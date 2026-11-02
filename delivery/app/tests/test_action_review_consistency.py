import copy
import pytest
from llm_shield.m4_necessity.research import annotation_for,case_hash
from scripts.build_action_review import build_legacy_cases
from scripts.merge_action_reviews import merge_reviews


def response(case,role):
    return {'schema':'action-review-response-v1','role':role,'reviewer':'test-human-'+role,
            'reviews':[{'case_id':case['case_id'],'case_sha256':case_hash(case),
                        'annotation':copy.deepcopy(case['proposal'])}]}


def test_same_action_with_different_required_relationship_is_not_human_consensus():
    cases=build_legacy_cases()
    a,b=response(cases[1],'A'),response(cases[1],'B')
    b['reviews'][0]['annotation']['required_facts']='仅讨论主题，不区分任何负责人'
    merged,status=merge_reviews(cases,a,b)
    assert status['reviewed']==0
    assert merged[1]['review']['status']!='human_reviewed'
    assert len(status['disagreements'])==1
    assert 'facts_require_adjudication' in status['disagreements'][0]['reasons']


def test_different_wording_is_pending_interpretation_not_automatically_called_wrong():
    cases=build_legacy_cases()
    a,b=response(cases[1],'A'),response(cases[1],'B')
    b['reviews'][0]['annotation']['required_facts']='负责人代号与每项工作、完成时间的关系'
    _,status=merge_reviews(cases,a,b)
    assert status['reviewed']==0
    assert status['disagreements'][0]['semantic_equivalence']=='unverified'


def test_explicit_adjudication_can_resolve_the_required_fact_difference():
    cases=build_legacy_cases()
    a,b=response(cases[1],'A'),response(cases[1],'B')
    b['reviews'][0]['annotation']['required_facts']='仅讨论主题'
    decision=response(cases[1],'adjudication')
    merged,status=merge_reviews(cases,a,b,decision)
    assert status['reviewed']==1
    assert merged[1]['review']['adjudicator']=='test-human-adjudication'


def test_delete_original_representation_is_rejected_before_gold_import():
    case=build_legacy_cases()[0]
    case['proposal']['minimum_representation']='original'
    with pytest.raises(ValueError,match='表达'):
        annotation_for(case,allow_drafts=True)
