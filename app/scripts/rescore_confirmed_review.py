"""Score frozen local artifacts against confirmed assisted labels, without refitting."""
import argparse
import json
import sys
from datetime import datetime,timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from llm_shield.m4_necessity.field_research import FieldActionResearch,ARTIFACT_TYPE
from llm_shield.m4_necessity.model import NecessityModel
from llm_shield.m4_necessity.research import (
    annotation_for,evaluate,training_sample,validate_cases,validate_review_provenance,
)
from scripts.run_natural_action_experiment import (
    APP,DEFAULT_PACK,DEFAULT_REVIEW,apply_ai_review,canonical_sha,enrich,sha,write_json,
)


def signature(cases, allow_drafts):
    return canonical_sha([{'case_id':c['case_id'],
                           **{k:v for k,v in training_sample(c,allow_drafts=allow_drafts).items() if k in {'feature','label'}}}
                          for c in cases])


def run(cases_path,out):
    import joblib
    if out.exists():raise ValueError('输出目录已存在，不覆盖历史结果')
    cases=[json.loads(s) for s in cases_path.read_text(encoding='utf8').splitlines()]
    manifest=validate_cases(cases)
    for c in cases:
        annotation_for(c,allow_drafts=False)
        validate_review_provenance(c)
    raw=[json.loads(s) for s in (DEFAULT_PACK/'cases.jsonl').read_text(encoding='utf8').splitlines()]
    old=apply_ai_review(raw,json.loads(DEFAULT_REVIEW.read_text(encoding='utf8')))
    same_all = signature(cases,False)==signature(old,True)
    same_train = signature([c for c in cases if c['split']=='train'],False)==signature([c for c in old if c['split']=='train'],True)
    if not same_all or not same_train:
        raise ValueError('训练特征或动作标签已改变，应另开训练实验；不能把旧模型当作重训结果')
    v3=APP/'outputs/natural_action_experiment_20261030_v1'
    fields=APP/'outputs/field_action_experiment_20261030_v1'
    s3=json.loads((v3/'selection_frozen.json').read_text(encoding='utf8'))
    sf=json.loads((fields/'selection_frozen.json').read_text(encoding='utf8'))
    p3,pf=v3/s3['selected_candidate'],fields/sf['candidate']
    if sha(p3)!=s3['candidate_sha256'] or sha(pf)!=sf['candidate_sha256']:
        raise ValueError('候选权重与冻结记录不匹配')
    tracked=[APP/'models/necessity_action.joblib',APP/'models/ACTIVE_MODELS.json',p3,pf,cases_path,
             Path(cases[0]['review']['review_export_path'])]
    before={str(p):sha(p) for p in tracked}
    artifact=joblib.load(pf)
    if artifact.get('artifact_type')!=ARTIFACT_TYPE:raise ValueError('字段候选类型不匹配')
    models={'current':NecessityModel(tracked[0]),'joint_content_candidate':NecessityModel(p3),
            'field_candidate':FieldActionResearch(artifact['pipeline'],pf)}
    if not models['current'].available or not models['joint_content_candidate'].available:
        raise ValueError('模型快照不可用')
    dev=[c for c in cases if c['split']=='test']
    results={name:enrich(evaluate(model,dev,allow_drafts=False)) for name,model in models.items()}
    results['field_candidate_with_frozen_threshold']=enrich(evaluate(models['field_candidate'],dev,allow_drafts=False,thresholds=sf['thresholds']))
    after={str(p):sha(p) for p in tracked}
    if before!=after:raise ValueError('复评过程中输入或模型发生变化')
    report={'schema':'confirmed-assisted-review-rescore-v1','at_utc':datetime.now(timezone.utc).isoformat(),
            'reference':'single_person_human_assisted_second_review_not_independent_ab',
            'manifest':manifest,'feature_action_signature_unchanged':same_all,
            'training_signature_unchanged':same_train,'retraining_performed':False,
            'mode':'frozen_model_rescore_no_fit_no_threshold_search',
            'model_training_supervision_remains':'previous_ai_first_review_weak_supervision',
            'evaluation_scope':'previously_exposed_synthetic_development_holdout_not_blind_test',
            'thresholds_reused':sf['thresholds'],'threshold_status':'exploratory_same_validation_not_independent_calibration',
            'inputs_and_models_before':before,'inputs_and_models_after':after,
            'production_promoted':False,'results':results,
            'code_hashes':{str(p.relative_to(APP)):sha(p) for p in [Path(__file__),APP/'llm_shield/m4_necessity/research.py']}}
    out.mkdir(parents=True)
    write_json(out/'report.json',report)
    lines=['# 人工辅助二审标签接入后的冻结模型复评','',
           '138处人工辅助二审已完整导入。动作标签与上次AI初审一致；19处必要事实或理由修订已保留。',
           '逐题训练特征和动作目标哈希相同，所以没有重复训练，也没有把旧权重改标为人工数据新训模型。',
           '以下仅按新接入的单人辅助二审参考标签重算原18处开发留出；材料已暴露，不是独立盲测。','']
    for name,r in results.items():
        lines.append(f"- {name}：匹配 {r['matching']}/{r['n']}；非暂停 {r['non_pause_count']}；非暂停错 {r['non_pause_errors']}；额外暂停 {r['false_pause_count']}。")
    lines += ['', '字段候选阈值沿用先前冻结值，没有按这份人工结果重新搜阈值。全部原件、案例和模型哈希前后一致。',
              '原模型训练来源仍是AI弱监督，不能由标签获确认倒推成当时已完成的人审训练，也不因此宣称现实零错误。',
              '下一轮影响训练的是新增情境、动作变更或特征设计，而不是再次拟合同一组数值输入。']
    (out/'开始这里.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps({'reference':report['reference'],'training_signature_unchanged':same_train,
                      'retraining_performed':False,'results':{k:{f:v[f] for f in ['n','matching','non_pause_count','non_pause_errors','false_pause_count']} for k,v in results.items()}},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--cases',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    try:run(a.cases,a.out)
    except (ValueError,KeyError,OSError) as exc:p.error(str(exc))
