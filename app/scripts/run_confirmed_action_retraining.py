"""Fresh local fits on confirmed labels, with the original grouped split frozen.

This trains the TF-IDF/logistic action classifier, not GLiNER or a generative LLM.
The reused development holdout is explicitly not an independent blind test.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import shutil
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm_shield.m4_necessity.field_research import (
    ARTIFACT_TYPE, FieldActionResearch, train_fields,
)
from llm_shield.m4_necessity.model import NecessityModel
from llm_shield.m4_necessity.research import (
    annotation_for, calibrate, case_hash, evaluate, training_sample,
    validate_cases, validate_review_provenance,
)
from scripts.run_natural_action_experiment import APP, canonical_sha, sha, write_json

ACTIONS = ['DELETE', 'GENERALIZE', 'LOCAL_AGGREGATE', 'PAUSE', 'PSEUDONYMIZE', 'RETAIN']


def now():
    return datetime.now(timezone.utc).isoformat()


def classification(rows, prediction_key='predicted'):
    from sklearn.metrics import classification_report, confusion_matrix, f1_score
    truth = [r['expected'] for r in rows]
    predictions = [r[prediction_key] for r in rows]
    correct = sum(a == b for a, b in zip(truth, predictions))
    return {'n': len(rows), 'correct': correct, 'accuracy': correct / len(rows) if rows else None,
            'macro_f1_all_six': float(f1_score(truth, predictions, labels=ACTIONS, average='macro', zero_division=0)),
            'per_action': {k: v for k, v in classification_report(
                truth, predictions, labels=ACTIONS, output_dict=True, zero_division=0).items() if k in ACTIONS},
            'confusion': {'row_true_column_predicted': ACTIONS,
                          'counts': confusion_matrix(truth, predictions, labels=ACTIONS).tolist()}}


def evaluate_confirmed(model, cases, thresholds=None):
    result = evaluate(model, cases, allow_drafts=False, thresholds=thresholds)
    for row in result['rows']:
        row['raw_predicted'] = max(row['scores'], key=row['scores'].get)
    result['raw_classifier'] = classification(result['rows'], 'raw_predicted')
    result['final_policy'] = classification(result['rows'])
    result['matching'] = sum(r['acceptable'] for r in result['rows'])
    result['non_pause_count'] = sum(r['predicted'] != 'PAUSE' for r in result['rows'])
    result['non_pause_errors'] = sum(r['predicted'] != 'PAUSE' and not r['acceptable'] for r in result['rows'])
    result['false_pause_count'] = sum(r['predicted'] == 'PAUSE' and r['expected'] != 'PAUSE' for r in result['rows'])
    return result


def learned_parameter_sha(model):
    """Hash fitted numbers/vocabulary, excluding changed provenance metadata."""
    pipe = model.pipeline
    digest = hashlib.sha256()
    features = pipe.named_steps['features']
    digest.update(json.dumps(features.transformer_weights, sort_keys=True).encode())
    arrays = []
    for name, branch in features.transformer_list:
        vectorizer = branch.named_steps['tfidf']
        digest.update(name.encode())
        digest.update(json.dumps(vectorizer.vocabulary_, sort_keys=True).encode())
        arrays.append(vectorizer.idf_)
    clf = pipe.named_steps['clf']
    digest.update(json.dumps(clf.classes_.tolist()).encode())
    arrays.extend([clf.coef_, clf.intercept_])
    for array in arrays:
        digest.update(str((array.shape, array.dtype.str)).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def previous_models():
    import joblib
    joint_dir = APP / 'outputs/natural_action_experiment_20261030_v1'
    field_dir = APP / 'outputs/field_action_experiment_20261030_v1'
    joint_selection = json.loads((joint_dir / 'selection_frozen.json').read_text(encoding='utf8'))
    field_selection = json.loads((field_dir / 'selection_frozen.json').read_text(encoding='utf8'))
    jp = joint_dir / joint_selection['selected_candidate']
    fp = field_dir / field_selection['candidate']
    if sha(jp) != joint_selection['candidate_sha256'] or sha(fp) != field_selection['candidate_sha256']:
        raise ValueError('旧候选与冻结哈希不符，不能比较')
    artifact = joblib.load(fp)
    if artifact.get('artifact_type') != ARTIFACT_TYPE:
        raise ValueError('旧字段分离候选格式不符')
    return {'joint': NecessityModel(jp), 'fields': FieldActionResearch(artifact['pipeline'], fp)}


def run(cases_path, out):
    if out.exists():
        raise ValueError('输出目录已存在，请使用新版本目录')
    cases = [json.loads(s) for s in cases_path.read_text(encoding='utf8').splitlines() if s.strip()]
    manifest = validate_cases(cases)
    for case in cases:
        if case.get('review', {}).get('status') != 'human_assisted_second_reviewed':
            raise ValueError('本入口只接收已导入的人工作为辅助二审确认标签')
        annotation_for(case, allow_drafts=False)
        validate_review_provenance(case)
    parts = {s: [c for c in cases if c['split'] == s] for s in ['train', 'validation', 'test']}
    old = previous_models()
    watched = [APP / 'models/necessity_action.joblib', APP / 'models/ACTIVE_MODELS.json', cases_path]
    watched += list({Path(c['review']['review_export_path']) for c in cases})
    watched += [m.model_path for m in old.values()]
    before = {str(p): sha(p) for p in watched}
    train = [training_sample(c, allow_drafts=False) for c in parts['train']]
    valid = [training_sample(c, allow_drafts=False) for c in parts['validation']]
    metadata = {'schema': 'confirmed-action-fresh-retraining-v1', 'started_utc': now(),
                'supervision': 'human_assisted_second_reviewed_not_independent_ab',
                'training_mode': 'fresh_tfidf_and_logistic_regression_fit_not_llm_finetuning',
                'warm_start': False, 'random_seed': 42, 'manifest': manifest,
                'case_file_sha256': sha(cases_path),
                'annotation_sha256': canonical_sha([{'case_id': c['case_id'], 'annotation': c['annotation']} for c in cases]),
                'case_hash_chain': canonical_sha([case_hash(c) for c in cases]),
                'fit_train_case_ids': [c['case_id'] for c in parts['train']],
                'validation_case_ids': [c['case_id'] for c in parts['validation']],
                'development_case_ids': [c['case_id'] for c in parts['test']],
                'split_unchanged': True, 'fit_uses_validation_or_development': False,
                'selection_scope': 'validation_only_same_grid_as_previous_round',
                'calibration_scope': 'same_validation_exploratory_not_independent',
                'evaluation_scope': 'previously_exposed_synthetic_development_holdout_not_blind_test',
                'entity_input': 'provided_annotation_not_actual_gliner',
                'label_counts': {s: dict(Counter(c['annotation']['action'] for c in p)) for s, p in parts.items()},
                'python': platform.python_version(),
                'dependencies': {p: importlib.metadata.version(p) for p in ['scikit-learn', 'numpy', 'scipy', 'joblib']},
                'production_promoted': False,
                'code_hashes': {str(p.relative_to(APP)): sha(p) for p in [Path(__file__),
                    APP/'llm_shield/m4_necessity/research.py', APP/'llm_shield/m4_necessity/model.py',
                    APP/'llm_shield/m4_necessity/field_research.py', APP/'llm_shield/m3_decide/decision.py',
                    APP/'llm_shield/m3_decide/constraints.py']},
                'config_hashes': {p.name: sha(p) for p in sorted((APP/'config').glob('*.yaml'))}}
    out.mkdir(parents=True)
    write_json(out/'input_manifest.json', {**metadata, 'input_hashes_before': before})
    shutil.copy2(cases_path, out/'confirmed_cases_snapshot.jsonl')
    shutil.copy2(APP/'models/necessity_action.joblib', out/'baseline_snapshot.joblib')
    baseline = NecessityModel(out/'baseline_snapshot.joblib')
    if not baseline.available:
        raise ValueError('当前模型快照不可用')
    fitted = {'joint': [], 'fields': []}
    for weight in [.35, 1., 2.]:
        path = out/f'joint_content_{weight:g}.joblib'
        model = NecessityModel(path)
        started = time.perf_counter()
        fit = model.train(train, validation_samples=valid, content_weight=weight, training_metadata=metadata)
        if not fit['ok']:
            raise ValueError(fit['reason'])
        fitted['joint'].append({'model': model, 'weights': {'content': weight},
            'fit_seconds': time.perf_counter()-started, 'fit_train_samples': len(train),
            'validation': evaluate_confirmed(model, parts['validation'])})
    for target, context in [(1., .5), (2., .5), (2., 1.), (3., 1.)]:
        started = time.perf_counter()
        model = train_fields(parts['train'], out/f'fields_target_{target:g}_context_{context:g}.joblib',
            target_weight=target, context_weight=context, metadata=metadata)
        fitted['fields'].append({'model': model, 'weights': {'target': target, 'context': context},
            'fit_seconds': time.perf_counter()-started, 'fit_train_samples': len(train),
            'validation': evaluate_confirmed(model, parts['validation'])})
    selected = {}
    freezes = {}
    for family, candidates in fitted.items():
        # Same ordering/tie break as the previous grids; never select on development results.
        chosen = max(candidates, key=lambda c: (c['validation']['acceptable_action_rate'],
            c['validation']['macro_f1'], *[-v for v in c['weights'].values()]))
        selected[family] = chosen
        model = chosen['model']
        freezes[family] = {'candidate': model.model_path.name, 'candidate_sha256': sha(model.model_path),
            'weights': chosen['weights'], 'learned_parameter_sha256': learned_parameter_sha(model),
            'validation': chosen['validation'], 'thresholds': calibrate(chosen['validation']),
            'grid': [{k: v for k, v in c.items() if k != 'model'} | {'candidate': c['model'].model_path.name}
                     for c in candidates]}
    write_json(out/'selection_frozen.json', {**metadata, 'frozen_before_development_utc': now(), 'selected': freezes})
    results = {'current': {'development': evaluate_confirmed(baseline, parts['test'])}}
    comparisons = {}
    for family, chosen in selected.items():
        model = chosen['model']
        results[family] = {'train_diagnostic': evaluate_confirmed(model, parts['train']),
                          'validation': chosen['validation'],
                          'development': evaluate_confirmed(model, parts['test'])}
        threshold = freezes[family]['thresholds']
        results[family]['development_with_threshold'] = (
            evaluate_confirmed(model, parts['test'], threshold) if threshold is not None else
            {'status': 'no_feasible_validation_threshold', 'rows': []})
        previous = evaluate_confirmed(old[family], parts['test'])
        results['previous_'+family] = {'development': previous}
        pairs = zip(results[family]['development']['rows'], previous['rows'])
        deltas = [max(abs(a['scores'].get(k, 0)-b['scores'].get(k, 0)) for k in ACTIONS) for a, b in pairs]
        comparisons[family] = {'previous_learned_parameter_sha256': learned_parameter_sha(old[family]),
            'new_learned_parameter_sha256': freezes[family]['learned_parameter_sha256'],
            'learned_parameters_identical': learned_parameter_sha(old[family]) == freezes[family]['learned_parameter_sha256'],
            'development_max_probability_delta': max(deltas),
            'new_fit_actually_performed': True}
    after = {p: sha(Path(p)) for p in before}
    if before != after:
        raise RuntimeError('训练期间原始输入、旧候选或活动模型发生变化')
    report = {**metadata, 'finished_utc': now(), 'fresh_fit_count': sum(map(len, fitted.values())),
              'selected': freezes, 'results': results, 'comparison_with_previous_fit': comparisons,
              'input_hashes_before': before, 'input_hashes_after': after, 'active_files_unchanged': True}
    write_json(out/'report.json', report)
    indexed = {c['case_id']: c for c in cases}
    mistakes = {family: [{**r, 'task_description': indexed[r['case_id']]['task_description'],
        'text': indexed[r['case_id']]['text'], 'required_facts': indexed[r['case_id']]['annotation']['required_facts']}
        for r in results[family]['development']['rows'] if not r['acceptable']] for family in selected}
    write_json(out/'misclassified_cases.json', mistakes)
    lines = ['# 复核后动作分类器实际重训', '',
        '使用138题已确认的单人人工辅助二审标签，实际新拟合7个TF-IDF/逻辑回归分类器。不是生成式大模型或GLiNER微调。',
        '冻结划分：训练101题、验证19题、开发留出18题；每次拟合只用101题。候选及阈值只按验证部分选定后再评估开发留出。',
        '18题材料之前已经使用过，以下是开发分类效果，不是独立盲测。每类留出仅1至6题；实体由题目提供，未测真实GLiNER和生成文案。', '']
    for name in ['current', 'joint', 'fields', 'previous_joint', 'previous_fields']:
        r = results[name]['development']
        raw = r['raw_classifier']
        lines.append(f"- {name}：原始分类准确率 {raw['correct']}/{raw['n']}（{raw['accuracy']:.2%}），六类macro-F1 {raw['macro_f1_all_six']:.4f}；约束后匹配 {r['matching']}/{r['n']}。")
    for family in selected:
        train_result = results[family]['train_diagnostic']['raw_classifier']
        val = results[family]['validation']['raw_classifier']
        lines += ['', f"## {family}", '', f"训练诊断 {train_result['correct']}/{train_result['n']}；验证 {val['correct']}/{val['n']}。训练诊断不作为泛化成绩。"]
        for action, score in results[family]['development']['raw_classifier']['per_action'].items():
            lines.append(f"- {action}：{int(score['support'])}题，precision {score['precision']:.3f}，recall {score['recall']:.3f}，F1 {score['f1-score']:.3f}。")
        calibrated = results[family]['development_with_threshold']
        if 'matching' in calibrated:
            lines.append(f"- 探索性阈值后匹配 {calibrated['matching']}/18，非暂停 {calibrated['non_pause_count']}题，其中错 {calibrated['non_pause_errors']}题；误暂停 {calibrated['false_pause_count']}题。这包含拒答策略效果，不能写成分类器本身的准确率。")
        else:
            lines.append('- 验证部分无可行暂停阈值。')
    lines += ['', '## 与上一轮的关系', '',
        '本次实际运行了7次新拟合；原人工修订主要是必要事实与理由，动作标签和模型输入未变。',
        *[f"- {family}：学习参数完全相同 {c['learned_parameters_identical']}；开发集最大概率差 {c['development_max_probability_delta']:.3g}。" for family, c in comparisons.items()],
        '模型文件的人工复核来源元数据是本轮新记录；不能仅因新文件哈希不同就说分类能力改变。',
        '活动模型、清单、原始复核文件和上一轮候选均未改写。检查点、混淆矩阵、逐题概率和错误明细分别见本目录joblib、report.json和misclassified_cases.json。']
    (out/'开始这里.md').write_text('\n'.join(lines)+'\n', encoding='utf8')
    print(json.dumps({'output': str(out), 'fresh_fit_count': report['fresh_fit_count'],
        'results': {k: v['development']['raw_classifier'] | {'per_action': None, 'confusion': None} for k, v in results.items()},
        'comparison': comparisons, 'active_files_unchanged': True}, ensure_ascii=False))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.cases, args.out)
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
