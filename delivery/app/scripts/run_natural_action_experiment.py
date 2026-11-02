"""Frozen, local weak-supervision experiment on the requested AI first review.

No detector or external generator is called. The development holdout has already
been exposed during authoring/review; none of these data are a blind test.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import platform
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm_shield.m4_necessity.model import FEATURE_VERSION, NecessityModel
from llm_shield.m4_necessity.research import (
    ComparisonPolicy, annotation_for, calibrate, case_hash, evaluate, training_sample, validate_cases,
)
from scripts.natural_action_data import REPRESENTATION, audit_documents

APP = Path(__file__).resolve().parents[1]
PROJECT = APP.parents[1]
DEFAULT_PACK = PROJECT / '03_数据与人工复核/任务必要性复核_自然文档_v3_20261029'
DEFAULT_REVIEW = DEFAULT_PACK / 'AI初审_20261030/AI初审_全量138_待二审.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf8')).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def apply_ai_review(cases, review):
    """Apply bound labels only; never put review notes into feature fields."""
    validate_cases(cases)
    if (review.get('schema') != 'action-review-response-v1'
            or review.get('reviewer_kind') != 'ai' or review.get('human_reviewed') is not False):
        raise ValueError('本入口仅处理明确标记的AI初审草稿，不补造人工来源')
    source = {c['case_id']: c for c in cases}
    answers = {}
    for row in review['reviews']:
        cid = row['case_id']
        if cid not in source or cid in answers or row.get('case_sha256') != case_hash(source[cid]):
            raise ValueError('初审题号重复、未知或原题哈希不匹配')
        if row.get('reviewer_kind') != 'ai' or row.get('human_reviewed') is not False:
            raise ValueError('逐题AI来源标记不一致')
        a = row['annotation']
        if REPRESENTATION.get(a.get('action')) != a.get('minimum_representation'):
            raise ValueError('动作与最小表达矛盾')
        answers[cid] = copy.deepcopy(a)
    if set(answers) != set(source):
        raise ValueError('初审不完整，不静默删除未完成或困难题目')
    merged = []
    for original in cases:
        row = copy.deepcopy(original)
        row.pop('annotation', None)
        row['proposal'] = answers[row['case_id']]
        row['review'] = {'status': 'machine_draft', 'source': 'user_requested_ai_first_review_not_gold'}
        annotation_for(row, allow_drafts=True)
        assert case_hash(row) == case_hash(original)
        merged.append(row)
    return merged


def enrich(result):
    """Report numerator/denominator and classifier output separately from blocking."""
    rows = result['rows']
    for r in rows:
        r['raw_predicted'] = max(r['scores'], key=r['scores'].get)
        r['raw_matches_ai_label'] = r['raw_predicted'] == r['expected']
        r['raw_to_final_changed'] = r['raw_predicted'] != r['predicted']
    count = lambda pred: sum(pred(r) for r in rows)
    n = len(rows)
    non_pause = count(lambda r: r['predicted'] != 'PAUSE')
    expected_pause = count(lambda r: r['expected'] == 'PAUSE')
    predicted_pause = count(lambda r: r['predicted'] == 'PAUSE')
    correct_pause = count(lambda r: r['expected'] == r['predicted'] == 'PAUSE')
    result.update(
        matching=count(lambda r: r['acceptable']),
        raw_matching=count(lambda r: r['raw_matches_ai_label']),
        non_pause_count=non_pause,
        non_pause_errors=count(lambda r: r['predicted'] != 'PAUSE' and not r['acceptable']),
        expected_pause_count=expected_pause, predicted_pause_count=predicted_pause,
        expected_pause_recall=correct_pause / expected_pause if expected_pause else None,
        pause_precision=correct_pause / predicted_pause if predicted_pause else None,
        false_pause_count=predicted_pause - correct_pause,
        unexpected_retain_count=count(lambda r: r['predicted'] == 'RETAIN' and r['expected'] != 'RETAIN'),
        unexpected_delete_count=count(lambda r: r['predicted'] == 'DELETE' and r['expected'] != 'DELETE'),
        non_pause_is_not_business_completion=True,
    )
    by_action = {}
    for action in REPRESENTATION:
        selected = [r for r in rows if r['expected'] == action]
        by_action[action] = {'n': len(selected), 'matching': sum(r['acceptable'] for r in selected),
                             'predictions': dict(Counter(r['predicted'] for r in selected))}
    result['by_ai_action'] = by_action
    return result


def comparison_rows(full, ablated):
    return [{'case_id': a['case_id'], 'full': a['predicted'], 'ablated': b['predicted'],
             'changed_action': a['predicted'] != b['predicted'],
             'score_l1_delta': sum(abs(a['scores'].get(k, 0) - b['scores'].get(k, 0)) for k in REPRESENTATION)}
            for a, b in zip(full['rows'], ablated['rows'])]


def context_probes(cases, documents, models):
    by_doc = defaultdict(list)
    for d in documents:
        if d.get('context_pair_id'):
            by_doc[d['context_pair_id']].append(d)
    indexed = {c['case_id']: c for c in cases}
    probes = []
    for pid, docs in by_doc.items():
        a, b = docs
        for index in range(len(a['decisions'])):
            ca, cb = [indexed[f"{d['document_id']}-s{index+1:02d}"] for d in (a, b)]
            expected=[annotation_for(c,allow_drafts=True)['action'] for c in (ca,cb)]
            if expected[0] == expected[1]:
                continue
            assert ca['text'] == cb['text'] and ca['task_description'] == cb['task_description']
            row = {'pair_id': pid, 'case_ids': [ca['case_id'], cb['case_id']],
                   'split': ca['split'], 'expected': expected,
                   'scope': 'training_seen_context_diagnostic_not_generalization', 'models': {}}
            for name, model in models.items():
                full = enrich(evaluate(model, [ca, cb], allow_drafts=True))
                without = enrich(evaluate(model, [ca, cb], allow_drafts=True, ablation='no_context'))
                predictions = [r['predicted'] for r in full['rows']]
                raw = [r['raw_predicted'] for r in full['rows']]
                row['models'][name] = {
                    'predictions': predictions, 'raw_predictions': raw,
                    'both_match_ai_labels': all(r['acceptable'] for r in full['rows']),
                    'changes_action_with_context': predictions[0] != predictions[1],
                    'no_context_predictions': [r['predicted'] for r in without['rows']],
                    'full_score_l1_between_contexts': sum(abs(full['rows'][0]['scores'].get(k, 0)
                                                            - full['rows'][1]['scores'].get(k, 0)) for k in REPRESENTATION),
                    'rows': full['rows'],
                }
            probes.append(row)
    return probes


def calibrated_result(model, cases, thresholds):
    if thresholds is None:
        return {'status': 'not_evaluated_no_feasible_threshold', 'n': len(cases),
                'rows': [], 'deployment_eligible': False}
    return {'status': 'exploratory_same_validation_set', 'deployment_eligible': False,
            **enrich(evaluate(model, cases, allow_drafts=True, thresholds=thresholds))}


def run(pack: Path, review_path: Path, out: Path):
    if out.exists():
        raise ValueError('输出已存在，请使用新实验目录')
    source = [json.loads(s) for s in (pack/'cases.jsonl').read_text(encoding='utf8').splitlines() if s.strip()]
    documents = [json.loads(s) for s in (pack/'documents.jsonl').read_text(encoding='utf8').splitlines() if s.strip()]
    audit = audit_documents(documents)
    if not audit['passed']:
        raise ValueError('源文档审计未通过')
    review = json.loads(review_path.read_text(encoding='utf8'))
    cases = apply_ai_review(source, review)
    manifest = validate_cases(cases)
    active_path = APP/'models/necessity_action.joblib'
    active_manifest = APP/'models/ACTIVE_MODELS.json'
    before = {str(p): sha(p) for p in (active_path, active_manifest)}
    partitions = {s: [c for c in cases if c['split'] == s] for s in ('train', 'validation', 'test')}
    metadata = {
        'supervision': 'ai_first_review_weak_labels_not_human_gold',
        'input_cases_sha256': sha(pack/'cases.jsonl'), 'review_export_sha256': sha(review_path),
        'labels_sha256': canonical_sha([{'case_id': c['case_id'], 'annotation': c['proposal']} for c in cases]),
        'input_hash_chain_sha256': canonical_sha([case_hash(c) for c in cases]),
        'feature_version': FEATURE_VERSION, 'random_seed': 42,
        'selection_and_calibration': 'same_19_validation_rows_exploratory_not_independent_calibration',
        'threshold_search_policy': {'max_ai_action_error': .05, 'min_non_pause_coverage': .25},
        'test_scope': 'previously_exposed_synthetic_development_holdout_not_blind_test',
        'entity_input': 'provided_annotation_not_actual_gliner',
        'dependencies': {p: importlib.metadata.version(p) for p in ('scikit-learn','numpy','scipy','joblib')},
        'python': platform.python_version(),
        'code_hashes': {str(p.relative_to(APP)): sha(p) for p in [Path(__file__), APP/'llm_shield/m4_necessity/research.py',
                                                               APP/'llm_shield/m4_necessity/model.py',
                                                               APP/'llm_shield/m3_decide/decision.py', APP/'llm_shield/m3_decide/constraints.py']},
        'config_hashes': {p.name: sha(p) for p in sorted((APP/'config').glob('*.yaml'))},
        'production_promoted': False,
    }
    out.mkdir(parents=True)
    write_json(out/'input_manifest.json', {'manifest': manifest, **metadata, 'baseline_before': before,
                                          'source_files': {str(p): sha(p) for p in [pack/'documents.jsonl',pack/'manifest.json']}})
    (out/'cases_ai_reviewed_drafts.jsonl').write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in cases),encoding='utf8')
    shutil.copy2(active_path, out/'baseline_snapshot.joblib')
    baseline = NecessityModel(out/'baseline_snapshot.joblib')
    if not baseline.available:
        raise ValueError('活动模型快照不可用，不能省略基线')
    train = [training_sample(c,allow_drafts=True) for c in partitions['train']]
    valid = [training_sample(c,allow_drafts=True) for c in partitions['validation']]
    grid = []
    for weight in (.35, 1., 2.):
        model = NecessityModel(out/f'candidate_content_{weight:g}.joblib')
        fit = model.train(train,validation_samples=valid,content_weight=weight,training_metadata=metadata)
        if not fit['ok']:
            raise ValueError(fit['reason'])
        validation = enrich(evaluate(model,partitions['validation'],allow_drafts=True))
        grid.append({'weight':weight,'model':model,'validation':validation,'fit':fit})
    selected = max(grid,key=lambda g:(g['validation']['acceptable_action_rate'],g['validation']['macro_f1'],-g['weight']))
    model = selected['model']
    thresholds = calibrate(selected['validation'])
    freeze = {**metadata, 'selected_candidate':model.model_path.name, 'content_weight':selected['weight'],
              'validation_candidates':[{'weight':g['weight'],'model':g['model'].model_path.name,
                                        'evaluation':g['validation'],'training':g['fit']} for g in grid],
              'calibration_status':'exploratory_feasible' if thresholds is not None else 'failed/no_feasible_threshold',
              'thresholds':thresholds, 'candidate_sha256':sha(model.model_path),
              'frozen_before_development_holdout_utc':datetime.now(timezone.utc).isoformat()}
    write_json(out/'selection_frozen.json', freeze)
    test = partitions['test']
    results = {name: enrich(evaluate(m,test,allow_drafts=True)) for name,m in {
        'uniform':ComparisonPolicy('uniform'),'rule_teacher':ComparisonPolicy('rule_teacher'),
        'current':baseline,'candidate_unthresholded':model}.items()}
    results['candidate_no_task_text'] = enrich(evaluate(model,test,allow_drafts=True,ablation='no_task_text'))
    results['candidate_no_context'] = enrich(evaluate(model,test,allow_drafts=True,ablation='no_context'))
    results['candidate_calibrated'] = calibrated_result(model,test,thresholds)
    ablations = {k:comparison_rows(results['candidate_unthresholded'],results[k])
                 for k in ('candidate_no_task_text','candidate_no_context')}
    probes = context_probes(cases,documents,{'current':baseline,'candidate_unthresholded':model})
    validation_current = enrich(evaluate(baseline,partitions['validation'],allow_drafts=True))
    queue = []
    index = {c['case_id']: c for c in cases}
    feedback = defaultdict(list)
    for split, ev in [('validation', selected['validation']), ('development_holdout',results['candidate_unthresholded'])]:
        for row in ev['rows']:
            if not row['acceptable']:
                feedback[row['case_id']].append(f"{split}：候选判断 {row['predicted']}，AI初审为 {row['expected']}。")
                queue.append({'split':split,**row,'task_description':index[row['case_id']]['task_description'],
                              'text':index[row['case_id']]['text'], 'interpretation':'model_ai_label_disagreement_requires_contextual_review_not_auto_relabel'})
    for name, rows in ablations.items():
        for r in rows:
            if r['changed_action']:
                feedback[r['case_id']].append(f"输入敏感性 {name}：{r['full']} → {r['ablated']}。")
    for probe in probes:
        if not probe['models']['candidate_unthresholded']['both_match_ai_labels']:
            for cid in probe['case_ids']:
                feedback[cid].append('训练中见过的同文上下文对照仍未两题都匹配；重点核对职责/统计范围依据。')
    assisted = copy.deepcopy(review)
    for row in assisted['reviews']:
        extra = feedback.get(row['case_id'], [])
        row['experiment_feedback'] = extra
        if extra:
            row['priority'] = True
            row['review_note'] += ' 实验辅助：'+' '.join(extra)+' 请依据原文二审，模型预测不作为自动改标签的依据。'
    write_json(out/'review_feedback_ai_draft.json',assisted)
    template = PROJECT/'tools/maintenance/second_review_page.html'
    tasks = json.loads((pack/'review-task.json').read_text(encoding='utf8'))
    payload = json.dumps({'task':tasks,'draft':assisted},ensure_ascii=False).replace('<','\\u003c')
    (out/'打开实验辅助二审.html').write_text(template.read_text(encoding='utf8').replace('/*__PAYLOAD__*/',payload),encoding='utf8')
    after = {p:sha(p) for p in before}
    if after != before:
        raise RuntimeError('活动模型或清单发生变化')
    report = {**metadata, 'manifest':manifest, 'selected_candidate':model.model_path.name,
              'selected_weight':selected['weight'],'calibration_status':freeze['calibration_status'],
              'thresholds':thresholds,'results':results,'validation_current':validation_current,
              'validation_selected':selected['validation'],'inference_ablations':ablations,
              'ablation_definitions':{'no_task_text':'仅去具体用户要求，保留任务枚举及模板描述；未重训',
                                      'no_context':'去背景与全文，保留当前目标片段及具体任务；未重训'},
              'context_probes':probes,'review_feedback':{'model_ai_disagreements':len(queue),
                                                       'priority_cases':sum(r['priority'] for r in assisted['reviews'])},
              'active_files_before':before,'active_files_after':after,'active_files_unchanged':True}
    write_json(out/'disagreements.json',queue)
    write_json(out/'report.json',report)
    lines = ['# 自然文档动作候选开发实验', '', '标签为AI初审草稿，实体由题目提供；这些数字表示与AI标签的一致程度。',
             '训练101处、验证19处、开发留出18处。验证同时用于候选选择与探索性阈值，非独立校准。', '',
             f"选中内容权重：{selected['weight']}；阈值状态：{freeze['calibration_status']}。", '']
    for name, result in results.items():
        if 'matching' in result:
            lines.append(f"- {name}：匹配 {result['matching']}/{result['n']}，非暂停 {result['non_pause_count']}/{result['n']}，非暂停错 {result['non_pause_errors']}，误暂停 {result['false_pause_count']}。")
        else:
            lines.append(f"- {name}：未评估，验证集无可行阈值；不回退成无阈值通过。")
    lines.extend(['', '同文不同背景对照只在训练数据中出现，仅作诊断，不能证明泛化：'])
    for p in probes:
        got = p['models']['candidate_unthresholded']
        lines.append(f"- {p['pair_id']}：AI标签 {p['expected']}；候选 {got['predictions']}；两题均匹配 {got['both_match_ai_labels']}。")
    lines.extend(['', f"验证及开发留出共 {len(queue)} 处候选/AI初审分歧；辅助二审页重点项 {report['review_feedback']['priority_cases']} 处。",
                  '打开“打开实验辅助二审.html”可看到原初稿和实验提示；未自动改写标签。',
                  '活动权重和模型清单哈希前后一致。本次未调用真实识别或外部生成，未评估最终文案或真实业务完成。'])
    (out/'开始这里.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--pack',type=Path,default=DEFAULT_PACK)
    p.add_argument('--review',type=Path,default=DEFAULT_REVIEW)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--allow-drafts',action='store_true')
    args=p.parse_args()
    if not args.allow_drafts:
        p.error('必须显式 --allow-drafts；当前标签尚非人工确认')
    try:
        r=run(args.pack,args.review,args.out)
    except (ValueError,KeyError,OSError) as exc:
        p.error(str(exc))
    print(json.dumps({'selected':r['selected_candidate'],'calibration':r['calibration_status'],
                      'results':{k:{x:v[x] for x in ('n','matching','non_pause_count','non_pause_errors') if x in v}
                                 for k,v in r['results'].items()},'review_feedback':r['review_feedback'],
                      'active_files_unchanged':r['active_files_unchanged']},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
