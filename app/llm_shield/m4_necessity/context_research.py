"""Domain-neutral contextual action research; no production execution adapter."""
from __future__ import annotations
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import FunctionTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

ARTIFACT_TYPE='offline-context-action-v4-text-only'

def requests(rows): return [r['request'] for r in rows]
def priors(rows): return [r['prior'] for r in rows]
def documents(rows): return [r['document'] for r in rows]
def locals_(rows): return [r['local'] for r in rows]
def targets(rows): return [r['target'] for r in rows]
def types_(rows): return [r['entity_type'] for r in rows]

def model_input(case,ablation='full'):
    """Explicit whitelist: labels, evidence, reason, scenario and source IDs excluded."""
    text,target=case['text'],case['target']
    positions=[]; start=0
    while True:
        pos=text.find(target,start)
        if pos<0: break
        positions.append(pos); start=pos+len(target)
    if 'target_occurrences' in case:
        positions=case['target_occurrences']
        if any(text[p:p+len(target)]!=target for p in positions): raise ValueError('Invalid selected target span')
    local='\n'.join(text[max(0,p-140):p+len(target)+140] for p in positions)
    row={'request':case['task_description'],'prior':case['context'],'document':text,
         'local':local,'target':target,'entity_type':case['entity_type']}
    if ablation=='target_only':
        row.update(request='',prior='',document='',local='')
    elif ablation=='no_prior': row['prior']=''
    elif ablation=='no_context': row.update(prior='',document='',local=target)
    elif ablation=='no_request': row['request']=''
    elif ablation!='full': raise ValueError(ablation)
    return row

def pipeline(c=1.,prior_weight=1.):
    selectors=[('request',requests),('prior',priors),('document',documents),
               ('local',locals_),('target',targets)]
    features=FeatureUnion([(name,Pipeline([('take',FunctionTransformer(fn)),
        ('tfidf',TfidfVectorizer(analyzer='char',ngram_range=(2,4),max_features=18000,sublinear_tf=True))]))
        for name,fn in selectors],transformer_weights={'request':1.,'prior':prior_weight,
        'document':.6,'local':2.,'target':1.})
    return Pipeline([('features',features),('clf',LogisticRegression(C=c,max_iter=2000,
        class_weight='balanced',random_state=42))])
