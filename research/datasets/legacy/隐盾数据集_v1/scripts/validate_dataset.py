"""Validate data and split integrity; this is not a model quality evaluation."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPLITS=('train','validation','test')

def read(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]

def spans_ok(text,entities):
    end=0
    for e in sorted(entities,key=lambda e:e['start']):
        assert isinstance(e['start'],int) and isinstance(e['end'],int)
        assert 0<=e['start']<e['end']<=len(text)
        assert text[e['start']:e['end']]==e['text']
        assert e['start']>=end, 'Overlapping spans'
        end=e['end']

def hash_text(text): return hashlib.sha256(text.encode()).hexdigest()

def check_target(row):
    t=row['target']
    assert t['send_allowed']==(t['preferred_action']!='PAUSE')
    if not t['send_allowed']:
        assert t['sanitized_text'] is None
        return
    assert isinstance(t['sanitized_text'],str) and t['sanitized_text']
    for e in row['entities']:
        if e['category'] in {'PERSON_NAME','PHONE','EMAIL','ID_CARD','BANK_CARD','API_KEY','STUDENT_ID','WECHAT','DORM','GRADE','SENSITIVE_ATTR'}:
            assert e['text'] not in t['sanitized_text'], 'Raw identifier remains in synthetic target'

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',type=Path,default=ROOT); args=ap.parse_args(); root=args.root
    stats=json.loads((root/'stats.json').read_text(encoding='utf-8'))
    families={s:set() for s in SPLITS}; groups={s:set() for s in SPLITS}; texts={s:set() for s in SPLITS}
    counts={}; sft_ids={s:set() for s in SPLITS}; entities_total=0
    for kind in ('ner','policy','dialogues'):
        counts[kind]={}
        for split in SPLITS:
            rows=read(root/kind/f'{split}.jsonl'); counts[kind][split]=len(rows)
            ids=set(); signatures=set(); actions=Counter(); categories=Counter()
            for r in rows:
                assert r['id'] not in ids; ids.add(r['id'])
                assert r['split']==split and r['human_reviewed'] is False
                families[split].add(r['template_family']); groups[split].add(r['source_case_id'])
                if kind=='dialogues':
                    assert len(r['turns'])==3
                    history=[]
                    person_values={e['text'] for t in r['turns'] for e in t['entities'] if e['category']=='PERSON_NAME'}
                    for t in r['turns']:
                        spans_ok(t['text'],t['entities']); entities_total+=len(t['entities'])
                        assert t['prior_outbound']==history, 'History contains a rejected turn or loses sent state'
                        check_target(t)
                        if t['target']['send_allowed']:
                            assert all(p not in t['target']['sanitized_text'] for p in person_values)
                            history.append(t['target']['sanitized_text'])
                        sft_ids[split].add(r['id']+'-T'+str(t['turn_id']))
                        texts[split].add(hash_text(t['text']))
                    signature=json.dumps([(t['text'],t['prior_outbound']) for t in r['turns']],ensure_ascii=False)
                else:
                    spans_ok(r['text'],r['entities']); entities_total+=len(r['entities'])
                    categories.update(e['category'] for e in r['entities'])
                    sft_ids[split].add(r['id']); texts[split].add(hash_text(r['text']))
                    signature=r['text'] if kind=='ner' else json.dumps([r['text'],r['task_description'],r['trusted_context'],r['recipient']],ensure_ascii=False)
                    if kind=='policy':
                        check_target(r); action=r['target']['preferred_action']; actions[action]+=1
                        if action=='LOCAL_AGGREGATE':
                            assert len({e['text'] for e in r['entities'] if e['category']=='PERSON_NAME'})==2
                        if action=='RETAIN': assert r['trusted_context']['exact_location_public'] is True
                assert signature not in signatures, f'Duplicate full input: {r["id"]}'
                signatures.add(signature)
            if kind=='ner': assert set(categories)==set(stats['categories'])
            if kind=='policy': assert set(actions)==set(stats['actions'])
    for a,b in [('train','validation'),('train','test'),('validation','test')]:
        assert not families[a]&families[b], 'Template family leakage'
        assert not groups[a]&groups[b], 'Source group leakage'
        assert not texts[a]&texts[b], 'Exact text crosses splits'
    for split in SPLITS:
        sft=read(root/'sft'/f'{split}.jsonl')
        assert {r['id'] for r in sft}==sft_ids[split]
        assert len(sft)==len(sft_ids[split])==stats['sft'][split]
        for r in sft: json.loads(r['output'])
        ner=read(root/'ner'/f'{split}.jsonl'); doccano=read(root/'doccano'/f'{split}.jsonl')
        assert len(ner)==len(doccano)
        for a,b in zip(ner,doccano):
            assert a['text']==b['text'] and a['id']==b['id']
            assert b['label']==[[e['start'],e['end'],e['category']] for e in a['entities']]
    public=read(root/'public/pii-bench-zh/external_test.jsonl'); ptexts=set()
    for r in public:
        spans_ok(r['text'],r['entities']); entities_total+=len(r['entities'])
        key=hash_text(r['text']); assert key not in ptexts; ptexts.add(key)
    assert all(not ptexts&texts[s] for s in SPLITS)
    proposed=read(root/'review/proposed_labels.jsonl')
    assert len(proposed)==stats['review_units'] and all(r['split']=='train' for r in proposed)
    report={'ok':True,'counts':counts,'all_checked_spans':entities_total,'public_rows_checked':len(public),
            'template_family_overlap':0,'source_group_overlap':0,'exact_text_overlap_across_splits':0,
            'public_custom_exact_text_overlap':0,'duplicate_full_inputs_within_each_split':0,
            'sft_schema_and_export_alignment':True,'public_span_check':True,
            'pause_and_history_checks':True,'human_gold_count':0,
            'limitations':'No semantic or real-world accuracy claim. Shared generation logic can still cause distribution bias; human review remains required.'}
    (root/'validation_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
