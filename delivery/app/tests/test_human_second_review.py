import copy
import json

import pytest

from llm_shield.m4_necessity.research import (annotation_for,case_hash,training_sample,validate_review_provenance)
from scripts.build_action_review import build_legacy_cases
from scripts.import_human_second_review import check_response,import_review


def inputs():
    cases=build_legacy_cases()
    response={'schema':'action-review-response-v1','role':'human_second_review',
        'reviewer':'AUTOMATED_TEST_FIXTURE_NOT_REAL_HUMAN','reviewer_kind':'human_assisted',
        'human_reviewed':True,'review_status':'human_second_review_complete',
        'independent_blind_review':False,'machine_suggestions_consulted_before_decisions':True,
        'human_confirmed_case_ids':[c['case_id'] for c in cases],
        'reviews':[{'case_id':c['case_id'],'case_sha256':case_hash(c),
                    'annotation':copy.deepcopy(c['proposal']),'human_confirmed':True,
                    'human_reviewed':True,'reviewer_kind':'human_assisted',
                    'ai_review_status':'ai_first_review_pending_human'} for c in cases]}
    return cases,response


def test_current_confirmation_can_preserve_historic_ai_pending_state():
    cases,response=inputs()
    _,confirmed=check_response(cases,response)
    assert len(confirmed)==336
    assert response['reviews'][0]['ai_review_status']=='ai_first_review_pending_human'


@pytest.mark.parametrize('damage',['duplicate','hash','list','row','blind','ai','representation','incomplete'])
def test_wrong_version_or_faked_completion_cannot_be_imported(damage):
    cases,r=inputs()
    if damage=='duplicate':r['reviews'].append(copy.deepcopy(r['reviews'][0]))
    elif damage=='hash':r['reviews'][0]['case_sha256']='stale'
    elif damage=='list':r['human_confirmed_case_ids'].pop()
    elif damage=='row':r['reviews'][0]['human_confirmed']=False
    elif damage=='blind':r['independent_blind_review']=True
    elif damage=='ai':r['reviewer_kind']='ai'
    elif damage=='representation':r['reviews'][0]['annotation']['minimum_representation']='original'
    else:r['reviews'].pop()
    with pytest.raises(ValueError):check_response(cases,r)


def test_unconfirmed_rows_stay_pending_even_in_a_supplied_partial_file():
    cases,r=inputs()
    r.update(human_reviewed=False,reviewer_kind='mixed_ai_human_pending',review_status='human_second_review_partial')
    row=r['reviews'][-1]
    row.update(human_confirmed=False,human_reviewed=False,reviewer_kind='ai')
    r['human_confirmed_case_ids'].pop()
    _,confirmed=check_response(cases,r)
    assert len(confirmed)==335 and cases[-1]['case_id'] not in confirmed


def test_import_preserves_bytes_and_supports_confirmed_training_without_two_reviewers(tmp_path):
    cases,r=inputs()
    cp,rp=tmp_path/'cases.jsonl',tmp_path/'response.json'
    cp.write_text('\n'.join(json.dumps(c,ensure_ascii=False) for c in cases),encoding='utf8')
    rp.write_text(json.dumps(r,ensure_ascii=False),encoding='utf8')
    out=tmp_path/'receipt'
    receipt=import_review(cp,rp,out)
    assert receipt['confirmed']==336 and receipt['independent_ab_consensus_cases']==0
    assert (out/'原始二审导出.json').read_bytes()==rp.read_bytes()
    imported=json.loads((out/'confirmed_cases.jsonl').read_text(encoding='utf8').splitlines()[0])
    assert len(imported['review']['reviewers'])==1
    assert annotation_for(imported,allow_drafts=False)==imported['annotation']
    assert training_sample(imported,allow_drafts=False)['source']=='human_assisted_second_reviewed'
    imported['annotation']['reason']='changed after confirmation'
    with pytest.raises(ValueError,match='哈希'):
        validate_review_provenance(imported)


def test_assisted_review_cannot_be_used_with_missing_source_evidence():
    cases,_=inputs()
    case=cases[0]
    case.update(annotation=case['proposal'],review={'status':'human_assisted_second_reviewed'})
    with pytest.raises(ValueError,match='来源'):
        training_sample(case,allow_drafts=False)


@pytest.mark.parametrize('damage',['summary','supplement_ids','supplement_reviewer'])
def test_confirmation_supplement_must_match_final_rows(damage):
    cases,r=inputs()
    if damage=='summary':r['summary']={'human_confirmed':1}
    else:
        r['provenance_correction']={'reviewer':r['reviewer'],'corrected_case_ids':[cases[0]['case_id']],
                                   'basis':'Synthetic test of a user-declared correction, not real human evidence.'}
        if damage=='supplement_ids':r['provenance_correction']['corrected_case_ids']=['unknown']
        else:r['provenance_correction']['reviewer']='different-test-reviewer'
    with pytest.raises(ValueError):check_response(cases,r)
