"""Compile long contextual documents without forcing campus task enumerations."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.natural_action_data import _grams, _similarity

ACTIONS = ['DELETE','GENERALIZE','LOCAL_AGGREGATE','PAUSE','PSEUDONYMIZE','RETAIN']
INPUT_KEYS = ('document_id','scenario_group','split','domain','document_type','task_description','context','text','synthetic','context_pair_id')

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def masked(doc):
    text=doc['text']
    for target in sorted({d['target'] for d in doc['decisions']},key=len,reverse=True):
        text=text.replace(target,'实体')
    return re.sub(r'[\W\d_]+','',text)

def audit(documents, sources, history=()):
    errors=[]; groups={}; ids=set(); pairs=defaultdict(list); lengths=[]; actions=Counter(); types=Counter()
    source_ids={s['source_id'] for s in sources}
    leaks=[]; similarities=[]; editorial_cues=[]; repeated_targets=[]
    for d in documents:
        did=d['document_id']; lengths.append(len(d['text'])); types[d['document_type']]+=1
        if did in ids: errors.append(f'{did}: duplicate document')
        ids.add(did)
        if not d.get('synthetic'): errors.append(f'{did}: synthetic declaration missing')
        if d['split'] not in ['train','validation','test']: errors.append(f'{did}: split')
        if d['scenario_group'] in groups and groups[d['scenario_group']]!=d['split']: errors.append(f'{did}: group leakage')
        groups[d['scenario_group']]=d['split']
        if len(d['text'])<450: errors.append(f'{did}: document below 450 characters')
        if not d['context'].strip() or not d['task_description'].strip(): errors.append(f'{did}: empty context/request')
        if not d.get('source_ids') or not set(d['source_ids'])<=source_ids: errors.append(f'{did}: unverified source reference')
        for key in ('text','context','task_description'):
            if re.search(r'\b(?:DELETE|GENERALIZE|LOCAL_AGGREGATE|PAUSE|PSEUDONYMIZE|RETAIN)\b|本题应|正确动作|建议动作|标注答案',d[key]):
                errors.append(f'{did}: answer leak in {key}')
            if re.search(r'(不需要|无需|不要|不用|只需|必须|应当).{0,12}(姓名|手机号|身份证|具体地址|真实姓名)|(?:姓名|电话|地址).{0,8}(不出现|删去|删除|隐去|改成|替换为)',d[key]):
                editorial_cues.append({'document_id':did,'field':key,'requires_semantic_review':True})
        if re.search(r'(删除|保留|隐去|泛化|代号化|脱敏).{0,12}(姓名|电话|机构|地点|身份证)',d['task_description']):
            leaks.append(did)
        if len(d['decisions'])<3 or len({x['action'] for x in d['decisions']})<2: errors.append(f'{did}: insufficient mixed decisions')
        targets=set()
        for x in d['decisions']:
            actions[x['action']]+=1
            if x['action'] not in ACTIONS: errors.append(f'{did}: unknown action')
            if not x['target'] or x['target'] not in d['text'] or x['target'] in targets: errors.append(f'{did}: missing/duplicate target {x["target"]}')
            targets.add(x['target'])
            if x['target'] and d['text'].count(x['target'])>1:
                repeated_targets.append({'document_id':did,'target':x['target'],'occurrences':d['text'].count(x['target'])})
            for key in ('required_facts','reason'):
                if not isinstance(x.get(key),str) or not x[key].strip(): errors.append(f'{did}: missing {key}')
            if not isinstance(x.get('expected_rendering'),str) or (x['action'] not in ['DELETE','PAUSE'] and not x['expected_rendering'].strip()):
                errors.append(f'{did}: missing expected_rendering')
            if not x.get('evidence') or any(e not in d['text'] and e not in d['context'] for e in x['evidence']): errors.append(f'{did}: unsupported evidence {x["target"]}')
            if x['action']=='PAUSE' and not x.get('clarification_question'): errors.append(f'{did}: unspecified clarification')
        if d.get('context_pair_id'): pairs[d['context_pair_id']].append(d)
    allowed=set()
    for key,items in pairs.items():
        if len(items)!=2: errors.append(f'{key}: pair size'); continue
        a,b=items
        if any(a[k]!=b[k] for k in ['text','task_description','scenario_group','split']): errors.append(f'{key}: uncontrolled pair')
        if a['context']==b['context']: errors.append(f'{key}: unchanged context')
        at={x['target']:x['action'] for x in a['decisions']}; bt={x['target']:x['action'] for x in b['decisions']}
        if at.keys()!=bt.keys() or sum(at[t]!=bt[t] for t in at if t in bt)<2: errors.append(f'{key}: less than two changed labels')
        allowed.add(frozenset([a['document_id'],b['document_id']]))
    grams=[_grams(masked(d)) for d in documents]
    for i,a in enumerate(documents):
        for j,b in enumerate(documents[:i]):
            similarity=_similarity(grams[i],grams[j])
            if similarity>=.65 and frozenset([a['document_id'],b['document_id']]) not in allowed:
                errors.append(f'{a["document_id"]}/{b["document_id"]}: near duplicate')
                similarities.append({'a':a['document_id'],'b':b['document_id'],'similarity':similarity})
    old_grams=[_grams(re.sub(r'[\W\d_]+','',d['text'])) for d in history]
    overlap=[]
    for d in documents:
        score=max((_similarity(_grams(re.sub(r'[\W\d_]+','',d['text'])),g) for g in old_grams),default=0)
        if score>=.65: overlap.append(d['document_id'])
    if overlap: errors.append('historical near duplicates')
    if leaks: errors.append('request discloses field/action answer')
    if len(documents)<24 or len(types)<8: errors.append('insufficient document/genre diversity')
    if sorted(lengths)[len(lengths)//2]<800: errors.append('median document below 800 characters')
    if set(actions)!=set(ACTIONS): errors.append('six classes not covered')
    if {d['split'] for d in documents} != {'train','validation','test'}: errors.append('missing split')
    split_classes={s:dict(Counter(x['action'] for d in documents if d['split']==s for x in d['decisions'])) for s in ['train','validation','test']}
    if set(split_classes['train'])!=set(ACTIONS): errors.append('training split missing action class')
    return {'passed':not errors,'errors':errors,'documents':len(documents),'scenario_groups':len(groups),
        'domains':dict(Counter(d['domain'] for d in documents)),'document_types':dict(types),'decisions':sum(actions.values()),
        'actions':dict(actions),'splits':dict(Counter(d['split'] for d in documents)),
        'length':{'min':min(lengths),'median':sorted(lengths)[len(lengths)//2],'max':max(lengths)},
        'context_pairs':len(pairs),'instruction_leaks':leaks,'near_duplicates':similarities,'historical_overlap':overlap,
        'split_classes':split_classes,'editorial_cues_for_review':editorial_cues,'repeated_target_mentions_for_review':repeated_targets,
        'limits':'heuristic_screening_not_human_quality_approval; sources_are_inspiration_not_original_private_documents'}

def compile_cases(docs):
    rows=[]
    for d in docs:
        for i,x in enumerate(d['decisions'],1):
            # A named person may also occur inside a separately annotated complete roster.
            # The roster takes ownership of its full span; individual mentions outside it remain distinct.
            enclosing=[m.span() for other in d['decisions'] if len(other['target'])>len(x['target'])
                       for m in re.finditer(re.escape(other['target']),d['text'])]
            occurrences=[m.start() for m in re.finditer(re.escape(x['target']),d['text'])
                         if not any(a<=m.start() and m.end()<=b for a,b in enclosing)]
            if not occurrences: raise ValueError(f"{d['document_id']}: target entirely owned by a larger annotated span")
            row={k:d[k] for k in INPUT_KEYS if k in d}
            row.update(case_id=f"{d['document_id']}-s{i:02d}",target=x['target'],entity_type=x['entity_type'],
                       target_occurrences=occurrences,
                       target_scope='exact_mentions_excluding_larger_annotated_spans')
            # No label, source URL, scenario label, or review notes enter model_inputs().
            row['input_sha256']=digest(row)
            row['annotation']={k:v for k,v in x.items() if k not in ['target','entity_type']}
            row['review']={'status':'machine_draft','human_reviewed':False}
            rows.append(row)
    return rows

def run(source,out,history):
    if out.exists(): raise ValueError('Output exists; create a new version')
    docs=[d for p in sorted(source.glob('part_*.json')) for d in json.loads(p.read_text(encoding='utf-8-sig'))]
    sources=json.loads((source/'sources.json').read_text(encoding='utf8'))
    if isinstance(sources,dict): sources=sources['sources']
    old=[json.loads(s) for p in history for s in p.read_text(encoding='utf8').splitlines() if s.strip()]
    report=audit(docs,sources,old)
    if not report['passed']: raise ValueError(json.dumps(report,ensure_ascii=False))
    cases=compile_cases(docs); out.mkdir(parents=True)
    for name,rows in [('documents.jsonl',docs),('cases.jsonl',cases)]:
        (out/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf8')
    for name,value in [('quality_report.json',report),('sources.json',sources)]:
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    # The review form displays the whole document and context for each decision.
    public=[{k:v for k,v in c.items() if k not in ['annotation','review']} for c in cases]
    (out/'review-task.json').write_text(json.dumps({'schema':'context-review-v4','cases':public},ensure_ascii=False),encoding='utf8')
    template=(Path(__file__).with_name('context_review.html')).read_text(encoding='utf8')
    payload=json.dumps({'schema':'context-review-v4','cases':public},ensure_ascii=False).replace('<','\\u003c')
    (out/'打开复核.html').write_text(template.replace('/*PAYLOAD*/',payload),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--source',type=Path,required=True); p.add_argument('--out',type=Path,required=True)
    p.add_argument('--history',type=Path,action='append',default=[]); a=p.parse_args(); run(a.source,a.out,a.history)
