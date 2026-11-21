import math
import copy

import joblib
import pytest

from llm_shield.m4_necessity.field_research import FieldActionResearch, train_fields
from llm_shield.m4_necessity.model import NecessityModel
from llm_shield.m4_necessity.research import segment_for,case_hash
from scripts.build_action_review import build_legacy_cases


@pytest.fixture
def field_fixture(tmp_path):
    # Synthetic software fixture only; not evaluation data or a human label set.
    cases=build_legacy_cases()[:28]
    model=train_fields(cases,tmp_path/'field_fixture.joblib',target_weight=2.,context_weight=1.,
                       metadata={'source':'automated_test_not_human_gold'})
    return model,cases


def test_offline_artifact_cannot_be_loaded_as_active_action_model(field_fixture):
    model,_=field_fixture
    active=NecessityModel(model.model_path)
    assert not active.available


def test_saved_field_pipeline_preserves_six_action_probabilities(field_fixture):
    model,cases=field_fixture
    loaded=FieldActionResearch(joblib.load(model.model_path)['pipeline'],model.model_path)
    case=cases[1]
    kwargs={'task_description':case['task_description'],'context':case['context'],'identity_key':case['identity']}
    before=model.score(segment_for(case),case['task'],case['recipient'],**kwargs)
    after=loaded.score(segment_for(case),case['task'],case['recipient'],**kwargs)
    assert len(after)==6 and before==after
    assert all(math.isfinite(x) and x>=0 for x in after.values())
    assert abs(sum(after.values())-1)<1e-12


def test_confirmed_annotation_overrides_stale_machine_proposal_during_fit(tmp_path,monkeypatch):
    from sklearn.linear_model import LogisticRegression
    cases=build_legacy_cases()[:28]
    for c in cases:
        c['annotation']=copy.deepcopy(c['proposal'])
        c['review']={'status':'human_reviewed','reviewers':['AUTOMATED_FIXTURE_A','AUTOMATED_FIXTURE_B'],
                     'case_sha256':case_hash(c)}
    assert cases[1]['proposal']['action']=='PSEUDONYMIZE'
    cases[1]['annotation'].update(action='DELETE',allowed_actions=['DELETE'],minimum_representation='none',
                                   required_facts='主题即可，不需要负责人')
    captured=[]
    original=LogisticRegression.fit
    def fit(self,x,y,*args,**kwargs):
        captured.extend(y)
        return original(self,x,y,*args,**kwargs)
    monkeypatch.setattr(LogisticRegression,'fit',fit)
    train_fields(cases,tmp_path/'confirmed_fixture.joblib',target_weight=2.,context_weight=1.,metadata={'test_only':True})
    assert captured[1]=='DELETE'
