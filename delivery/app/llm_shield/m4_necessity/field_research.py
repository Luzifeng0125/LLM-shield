"""Offline research: separate target/task/context features; never active loading."""
from pathlib import Path
from .. import config as C
from .model import FEATURE_SPLIT, build_feature_text

ARTIFACT_TYPE = 'offline-field-action-research'


def record(seg, task, recipient, *, task_description='', context='', identity_key=''):
    structured = build_feature_text(seg,task,recipient,identity_key=identity_key).partition(FEATURE_SPLIT)[0]
    return {'structured':structured,'target':seg.text,
            'task':str(C.tasks().get(task,{}).get('desc',''))+'\n'+task_description,
            'context':context or seg.context}


def take_structure(rows):
    return [r['structured'] for r in rows]


def take_target(rows):
    return [r['target'] for r in rows]


def take_task(rows):
    return [r['task'] for r in rows]


def take_context(rows):
    return [r['context'] for r in rows]


class FieldActionResearch:
    def __init__(self,pipeline,path):
        self.pipeline,self.model_path=pipeline,Path(path)

    def score(self,seg,task,recipient,**kwargs):
        values=self.pipeline.predict_proba([record(seg,task,recipient,**kwargs)])[0]
        return {str(k):float(v) for k,v in zip(self.pipeline.classes_,values)}


def train_fields(cases,path,*,target_weight,context_weight,metadata):
    import joblib
    from sklearn.pipeline import Pipeline,FeatureUnion
    from sklearn.preprocessing import FunctionTransformer
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from .research import segment_for,annotation_for,validate_review_provenance,REVIEWED_STATUSES
    selectors=[('structured',take_structure),('target',take_target),('task',take_task),('context',take_context)]
    branches=[(name,Pipeline([('take',FunctionTransformer(fn)),
                             ('tfidf',TfidfVectorizer(analyzer='char_wb',ngram_range=(2,4),min_df=1))]))
              for name,fn in selectors]
    weights={'structured':1.,'target':target_weight,'task':1.,'context':context_weight}
    pipe=Pipeline([('features',FeatureUnion(branches,transformer_weights=weights)),
                   ('clf',LogisticRegression(max_iter=1000,class_weight='balanced',random_state=42))])
    rows=[record(segment_for(c),c['task'],c['recipient'],task_description=c['task_description'],
                 context=c['context'],identity_key=c['identity']) for c in cases]
    labels=[]
    for c in cases:
        if c.get('review',{}).get('status') in REVIEWED_STATUSES:
            validate_review_provenance(c)
        labels.append(annotation_for(c,allow_drafts=True)['action'])
    pipe.fit(rows,labels)
    joblib.dump({'artifact_type':ARTIFACT_TYPE,'feature_version':'separate_fields_v1',
                 'pipeline':pipe,'weights':weights,'metadata':metadata,'production_promoted':False},path)
    return FieldActionResearch(pipe,path)
