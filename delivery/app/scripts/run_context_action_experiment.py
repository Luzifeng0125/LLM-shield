"""Test contextual data value with equal model families and frozen scene splits."""
from __future__ import annotations
import argparse
import json
import sys
import time
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import joblib
from sklearn.metrics import accuracy_score,classification_report,confusion_matrix,f1_score
from llm_shield.m4_necessity.context_research import ARTIFACT_TYPE,model_input,pipeline
from llm_shield.m4_necessity.research import validate_review_provenance
from scripts.build_context_review import ACTIONS,digest
from scripts.run_natural_action_experiment import APP,sha,write_json

def load(path): return [json.loads(s) for s in path.read_text(encoding='utf8').splitlines() if s.strip()]

def convert_old(c):
    validate_review_provenance(c)
    return {'case_id':c['case_id'],'document_id':c['document_id'],'scenario_group':c['template_group'],
        'split':c['split'],'text':c['text'],'target':c['text'], 'entity_type':' '.join(sorted({e['category'] for e in c['entities']})),
        'context':c['context'],'task_description':c['task_description'],'annotation':c['annotation'],
        'review':c['review']}

def score(model,cases,ablation='full'):
    inputs=[model_input(c,ablation) for c in cases]; truth=[c['annotation']['action'] for c in cases]
    probs=model.predict_proba(inputs); pred=model.classes_[probs.argmax(axis=1)]
    rows=[{'case_id':c['case_id'],'document_id':c['document_id'],'expected':y,'predicted':str(p),
        'correct':y==p,'scores':{str(k):float(v) for k,v in zip(model.classes_,ps)}} for c,y,p,ps in zip(cases,truth,pred,probs)]
    by_doc=defaultdict(list)
    for r in rows: by_doc[r['document_id']].append(r['correct'])
    return {'n':len(cases),'correct':int(sum(r['correct'] for r in rows)),
        'accuracy':float(accuracy_score(truth,pred)),'macro_f1':float(f1_score(truth,pred,labels=ACTIONS,average='macro',zero_division=0)),
        'class_report':classification_report(truth,pred,labels=ACTIONS,output_dict=True,zero_division=0),
        'confusion':{'true_rows_predicted_columns':ACTIONS,'counts':confusion_matrix(truth,pred,labels=ACTIONS).tolist()},
        'all_targets_correct_documents':sum(all(v) for v in by_doc.values()),'documents':len(by_doc),'rows':rows}

def contrast(cases,result):
    pairs=defaultdict(lambda:defaultdict(list)); indexed={r['case_id']:r for r in result['rows']}
    for c in cases:
        if c.get('context_pair_id'): pairs[c['context_pair_id']][c['target']].append(c)
    rows=[]
    for pid,targets in pairs.items():
        for target,items in targets.items():
            if len(items)==2 and items[0]['annotation']['action']!=items[1]['annotation']['action']:
                predictions=[indexed[c['case_id']]['predicted'] for c in items]
                rows.append({'pair_id':pid,'target':target,'case_ids':[c['case_id'] for c in items],
                    'expected':[c['annotation']['action'] for c in items],'predictions':predictions,
                    'both_correct':all(indexed[c['case_id']]['correct'] for c in items),
                    'changed_with_context':predictions[0]!=predictions[1]})
    return {'changed_target_pairs':len(rows),'both_correct':sum(r['both_correct'] for r in rows),'rows':rows}

def run(pack,old_path,out):
    if out.exists(): raise ValueError('Use a new output directory')
    audit=json.loads((pack/'quality_report.json').read_text(encoding='utf8'))
    if not audit['passed']: raise ValueError('Corpus audit failed')
    new=load(pack/'cases.jsonl'); old_raw=load(old_path)
    old=[convert_old(c) for c in old_raw]
    parts={s:[c for c in new if c['split']==s] for s in ['train','validation','test']}
    old_parts={s:[c for c in old if c['split']==s] for s in ['train','validation','test']}
    watched=[pack/'cases.jsonl',pack/'documents.jsonl',old_path,APP/'models/necessity_action.joblib',APP/'models/ACTIVE_MODELS.json']
    before={str(p):sha(p) for p in watched}
    training={'old_confirmed_only':old_parts['train'],'new_context_drafts_only':parts['train'],
              'mixed_confirmed_and_drafts':old_parts['train']+parts['train']}
    # Selection uses only the NEW validation scene families, identical for all conditions.
    protocol={'schema':'context-action-data-ablation-v4','frozen_utc':datetime.now(timezone.utc).isoformat(),
        'new_reference':'machine_draft_not_human_gold','old_reference':'human_assisted_second_reviewed',
        'evaluation_scope':'synthetic_scene_development_reused_after_v1_not_independent_blind_test',
        'gold_entity_type_used_in_model_features':False,
        'model_type':'fresh_domain_neutral_tfidf_logistic_no_legacy_campus_task_enum',
        'not_current_production_model_comparison':True,'old_adapter':'legacy decision segment as target/text; original full context in prior',
        'grid':[{'C':c,'prior_weight':w} for c in [1.,10.,50.] for w in [1.,3.]],
        'selection':'new_validation_macro_f1_then_accuracy_then_smaller_C_and_prior_weight',
        'partitions':{s:[c['case_id'] for c in p] for s,p in parts.items()},
        'training_cases':{k:[c['case_id'] for c in v] for k,v in training.items()},
        'inputs_before':before,'production_promoted':False,
        'code_hashes':{str(p.relative_to(APP)):sha(p) for p in [Path(__file__),APP/'llm_shield/m4_necessity/context_research.py']}}
    out.mkdir(parents=True);write_json(out/'protocol_before_fit.json',protocol)
    selected={}; freezes={};started=time.perf_counter()
    for name,cases in training.items():
        if set(c['annotation']['action'] for c in cases)!=set(ACTIONS): raise ValueError(f'{name}: missing class')
        x=[model_input(c) for c in cases];y=[c['annotation']['action'] for c in cases]
        grid=[]
        for spec in protocol['grid']:
            model=pipeline(spec['C'],spec['prior_weight']);model.fit(x,y)
            val=score(model,parts['validation']);grid.append({'spec':spec,'validation':val,'model':model})
        chosen=max(grid,key=lambda g:(g['validation']['macro_f1'],g['validation']['accuracy'],-g['spec']['C'],-g['spec']['prior_weight']))
        selected[name]=chosen['model']; path=out/f'{name}.joblib'
        joblib.dump({'artifact_type':ARTIFACT_TYPE,'pipeline':chosen['model'],'protocol':protocol,
                    'training_condition':name,'selected':chosen['spec']},path)
        freezes[name]={'path':path.name,'sha256':sha(path),'selected':chosen['spec'],
            'validation':chosen['validation'],'grid':[{'spec':g['spec'],'validation':{k:v for k,v in g['validation'].items() if k!='rows'}} for g in grid]}
    write_json(out/'selection_before_development.json',{'selected':freezes,'at_utc':datetime.now(timezone.utc).isoformat()})
    best_name=max(freezes,key=lambda n:(freezes[n]['validation']['macro_f1'],freezes[n]['validation']['accuracy']))
    results={}
    for name,model in selected.items():
        result=score(model,parts['test'])
        results[name]={'new_development':result,'old_development':score(model,old_parts['test']),
            'context_pairs':contrast(parts['test'],result),
            'ablations':{a:score(model,parts['test'],a) for a in ['target_only','no_prior','no_context','no_request']}}
    # A category-only training majority exposes shortcuts without supplying task answers.
    counts=defaultdict(Counter)
    for c in training['mixed_confirmed_and_drafts']: counts[c['entity_type']][c['annotation']['action']]+=1
    global_majority=Counter(c['annotation']['action'] for c in training['mixed_confirmed_and_drafts']).most_common(1)[0][0]
    shortcut=[(counts[c['entity_type']].most_common(1)[0][0] if counts[c['entity_type']] else global_majority)==c['annotation']['action'] for c in parts['test']]
    after={p:sha(Path(p)) for p in before}
    if before!=after: raise ValueError('Input or active file changed')
    report={'protocol':protocol,'fit_count':18,'elapsed_seconds':time.perf_counter()-started,'selected':freezes,
        'preferred_condition_by_validation':best_name,'results':results,'category_majority_baseline':{'correct':sum(shortcut),'n':len(shortcut)},
        'inputs_after':after,'active_unchanged':True}
    write_json(out/'report.json',report)
    idx={c['case_id']:c for c in new}
    write_json(out/'errors.json',{name:[{**r,'target':idx[r['case_id']]['target'],'reason':idx[r['case_id']]['annotation']['reason']}
        for r in result['new_development']['rows'] if not r['correct']] for name,result in results.items()})
    lines=['# 长材料上下文语料：纯文本模型开发实验','','新语料为AI草稿标签，旧138题为单人人工辅助复核。新旧数据训练仅用各自train；统一按新validation选模型，后评估已使用过的新test。',
           '特征不使用人工实体类型，只使用任务文字、前序背景、全文、定位附近文字与目标原文。目标位置仍由题目提供，未评估自动识别。',
           '此处比较相同模型家族下的数据条件；旧数据适配基线不等于当前在线模型。当前执行器不支持这套跨行业语义的完整转换。','']
    for name,result in results.items():
        r=result['new_development'];v=freezes[name]['validation'];p=result['context_pairs']
        lines.append(f"- {name}：验证 {v['correct']}/{v['n']}，新场景开发 {r['correct']}/{r['n']}（{r['accuracy']:.1%}），macro-F1 {r['macro_f1']:.3f}；整篇全对 {r['all_targets_correct_documents']}/{r['documents']}；上下文翻转两题都对 {p['both_correct']}/{p['changed_target_pairs']}。")
    lines+=['',f'按验证选择的数据条件：{best_name}。', '去背景/只看片段消融、各类召回及旧开发集回退见report.json。不得按这次开发错例修改标签再宣称独立成绩；下一轮须记录新版本。']
    (out/'开始这里.md').write_text('\n'.join(lines),encoding='utf8')
    print(json.dumps({name:{k:r['new_development'][k] for k in ['n','correct','accuracy','macro_f1']} for name,r in results.items()},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--pack',type=Path,required=True);p.add_argument('--old-confirmed',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();run(a.pack,a.old_confirmed,a.out)
