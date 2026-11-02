"""Validation-only field-weight selection; reused holdout remains development-only."""
import argparse
import json
import sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from llm_shield.m4_necessity.field_research import train_fields
from llm_shield.m4_necessity.research import evaluate,calibrate,validate_cases,annotation_for,validate_review_provenance
from scripts.run_natural_action_experiment import (DEFAULT_PACK,DEFAULT_REVIEW,APP,apply_ai_review,
    write_json,sha,canonical_sha,enrich,comparison_rows,context_probes,calibrated_result)


def run(out,confirmed_cases=None):
    if out.exists():
        raise ValueError('不覆盖既有实验')
    input_path=confirmed_cases or DEFAULT_PACK/'cases.jsonl'
    cases=[json.loads(s) for s in input_path.read_text(encoding='utf8').splitlines()]
    if confirmed_cases:
        for c in cases:
            annotation_for(c,allow_drafts=False)
            validate_review_provenance(c)
        supervision='human_assisted_second_reviewed_not_independent_ab'
        review_sha=sorted({c['review']['review_export_sha256'] for c in cases})
    else:
        review=json.loads(DEFAULT_REVIEW.read_text(encoding='utf8'))
        cases=apply_ai_review(cases,review)
        supervision='ai_first_review_weak_labels_not_human_gold'
        review_sha=[sha(DEFAULT_REVIEW)]
    validate_cases(cases)
    docs=[json.loads(s) for s in (DEFAULT_PACK/'documents.jsonl').read_text(encoding='utf8').splitlines()]
    parts={s:[c for c in cases if c['split']==s] for s in ['train','validation','test']}
    active={str(p):sha(p) for p in [APP/'models/necessity_action.joblib',APP/'models/ACTIVE_MODELS.json']}
    metadata={'supervision':supervision,
              'review_exports_sha256':review_sha,'input_sha256':sha(input_path),
              'labels_sha256':canonical_sha([annotation_for(c,allow_drafts=not bool(confirmed_cases)) for c in cases]),'seed':42,
              'code_sha256':sha(Path(__file__)),
              'features_sha256':sha(APP/'llm_shield/m4_necessity/field_research.py'),
              'development_holdout_already_used_in_v1':True,'production_promoted':False}
    out.mkdir(parents=True)
    grid=[]
    for target,context in [(1.,.5),(2.,.5),(2.,1.),(3.,1.)]:
        model=train_fields(parts['train'],out/f'fields_target_{target:g}_context_{context:g}.joblib',
                            target_weight=target,context_weight=context,metadata=metadata)
        ev=enrich(evaluate(model,parts['validation'],allow_drafts=True))
        grid.append({'model':model,'target':target,'context':context,'validation':ev})
    chosen=max(grid,key=lambda g:(g['validation']['acceptable_action_rate'],g['validation']['macro_f1'],-g['target'],-g['context']))
    model=chosen['model']
    threshold=calibrate(chosen['validation'])
    frozen={**metadata,'candidate':model.model_path.name,'candidate_sha256':sha(model.model_path),
            'selected_weights':{'target':chosen['target'],'context':chosen['context']},
            'grid':[{'candidate':g['model'].model_path.name,'target':g['target'],'context':g['context'],
                     'evaluation':g['validation']} for g in grid],
            'thresholds':threshold,'calibration_status':'exploratory_same_validation' if threshold else 'failed/no_feasible_threshold',
            'frozen_before_holdout_utc':datetime.now(timezone.utc).isoformat()}
    write_json(out/'selection_frozen.json',frozen)
    results={name:enrich(evaluate(model,parts['test'],allow_drafts=True,ablation=mode))
             for name,mode in [('candidate_unthresholded','full'),('candidate_no_task_text','no_task_text'),('candidate_no_context','no_context')]}
    results['candidate_calibrated']=calibrated_result(model,parts['test'],threshold)
    probes=context_probes(cases,docs,{'field_candidate':model})
    previous=json.loads((APP/'outputs/natural_action_experiment_20261030_v1/report.json').read_text(encoding='utf8'))
    report={**metadata,'manifest':validate_cases(cases),'candidate':model.model_path.name,
            'selected_weights':frozen['selected_weights'],'thresholds':threshold,'calibration_status':frozen['calibration_status'],
            'results':results,'context_probes':probes,
            'inference_ablations':{k:comparison_rows(results['candidate_unthresholded'],results[k])
                                  for k in ['candidate_no_task_text','candidate_no_context']},
            'previous_reference':{'current':previous['results']['current'],
                                  'joint_content_candidate':previous['results']['candidate_unthresholded']},
            'active_files_unchanged':all(sha(p)==h for p,h in active.items()),'active_hashes':active}
    assert report['active_files_unchanged']
    write_json(out/'report.json',report)
    write_json(out/'disagreements.json',[r for r in results['candidate_unthresholded']['rows'] if not r['acceptable']])
    lines=['# 字段分离候选开发实验','',
           '目标片段、具体任务、背景全文分别向量化，避免目标片段被整篇材料淹没。标签来源：'+supervision+'。',
           '四组权重仅在19处验证判断上选择；18处开发留出已在上一轮使用，不称独立终测。','',
           f"选中 {model.model_path.name}；验证匹配 {chosen['validation']['matching']}/19。",
           f"探索性阈值状态：{frozen['calibration_status']}，候选选择与阈值仍共用验证集。",'']
    for k,v in results.items():
        if 'matching' in v:
            lines.append(f"- {k}：参考标签匹配 {v['matching']}/{v['n']}；非暂停错 {v['non_pause_errors']}；应暂停召回 {v['expected_pause_recall']}。")
        else: lines.append(f"- {k}：无可行阈值，不作为无阈值通过。")
    for p in probes:
        lines.append(f"- 训练内对照 {p['pair_id']}：{p['models']['field_candidate']['predictions']}，参考 {p['expected']}。")
    lines.extend(['','活动模型保持原版。候选使用独立离线artifact_type，在线加载器不接收此格式。',
                  '上下文对照在训练中见过，不证明未见情境泛化；标签获确认也不等于独立效果验收。'])
    (out/'开始这里.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps({'candidate':report['candidate'],'selected_weights':report['selected_weights'],
                      'calibration':report['calibration_status'],
                      'results':{k:{f:v[f] for f in ['matching','n','expected_pause_recall'] if f in v} for k,v in results.items()},
                      'probes':[{'pair':p['pair_id'],'predicted':p['models']['field_candidate']['predictions']} for p in probes]},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--allow-drafts',action='store_true')
    parser.add_argument('--confirmed-cases',type=Path,help='已导入且保有来源证据的人工辅助二审案例')
    a=parser.parse_args()
    if not a.allow_drafts and not a.confirmed_cases: parser.error('AI草稿须显式允许，或提供已确认二审案例')
    run(a.out,a.confirmed_cases)
