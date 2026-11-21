"""Build an auditable comparison of saved experiments, without model selection on test."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
OUT = APP / 'outputs/context_model_comparison_20261031'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    paths = {
        'tfidf_text_only': APP / 'outputs/context_action_experiment_20261030_v3_privacy_only',
        'bert_chunks': APP / 'outputs/context_bert_experiment_20261030_v1',
        'bert_context_contrast': APP / 'outputs/context_bert_experiment_20261030_v2_contrast',
    }
    reports = {k: read(p / 'report.json') for k, p in paths.items()}
    reference = reports['bert_chunks']['protocol']
    summary = []
    for experiment, report in reports.items():
        for condition, result in report['results'].items():
            dev = result.get('development', result.get('new_development'))
            val = report['selected'][condition]['validation']
            assert {r['case_id'] for r in dev['rows']} == set(reference['development_cases'])
            assert {r['case_id'] for r in val['rows']} == set(reference['validation_cases'])
            summary.append({
                'experiment': experiment, 'condition': condition,
                'validation': {k: val[k] for k in ['n', 'correct', 'accuracy', 'macro_f1']},
                'development': {k: dev[k] for k in ['n', 'correct', 'accuracy', 'macro_f1']},
                'old_development': {k: result['old_development'][k] for k in ['n', 'correct', 'macro_f1']},
                'context_pair_both_correct': result['context_pairs']['both_correct'],
                'context_pair_count': result['context_pairs']['changed_target_pairs'],
                'report_path': str((paths[experiment] / 'report.json').relative_to(ROOT)),
            })
    # Keep the declared validation criterion; higher test accuracy never overrides it.
    chosen = max(summary, key=lambda r: (r['validation']['macro_f1'], r['validation']['accuracy']))
    assert chosen['experiment'] == 'bert_chunks' and chosen['condition'] == 'mixed'
    for experiment in ['bert_chunks', 'bert_context_contrast']:
        verified = read(paths[experiment] / 'verification.json')
        assert verified['passed'] and verified['all_inputs_and_active_models_unchanged']
    qa = read(APP / 'outputs/context_review_v4_1_qa_20261030/report.json')
    assert qa['passed'] and qa['cases'] == 122 and qa['human_reviews_created'] == 0
    junit = paths['bert_context_contrast'] / 'regression_related_20261031_retry.xml'
    suite = ET.parse(junit).getroot().find('testsuite')
    assert suite is not None and int(suite.attrib['failures']) == int(suite.attrib['errors']) == 0
    result = {
        'schema': 'context-action-comparison-v1', 'reported_date': '2026-10-31',
        'scope': 'reused_synthetic_development_not_blind_test',
        'data': '上下文长材料_v4_1_20261030', 'new_label_provenance': 'machine_draft',
        'rows': summary, 'preferred_offline_by_validation': chosen,
        'promotion_decision': 'do_not_promote_context_reversal_and_pause_fail',
        'production_promoted': False, 'related_tests_passed': int(suite.attrib['tests']),
        'reports_sha256': {k: hashlib.sha256((p / 'report.json').read_bytes()).hexdigest() for k, p in paths.items()},
    }
    write(OUT / 'comparison.json', result)
    cases = [json.loads(line) for line in (ROOT / 'research/datasets/legacy/上下文长材料_v4_1_20261030/cases.jsonl').read_text(encoding='utf-8').splitlines() if line]
    reviewed = []
    for case in cases:
        if case['split'] != 'test':
            continue
        predictions = {}
        for experiment, report in reports.items():
            for condition, evaluated in report['results'].items():
                dev = evaluated.get('development', evaluated.get('new_development'))
                row = next(r for r in dev['rows'] if r['case_id'] == case['case_id'])
                predictions[f'{experiment}/{condition}'] = {k: row[k] for k in ['predicted', 'correct']}
        reviewed.append({'case_id': case['case_id'], 'document_id': case['document_id'],
                         'target': case['target'], 'expected_machine_draft': case['annotation'],
                         'predictions': predictions, 'labels_changed_after_evaluation': False})
    write(OUT / 'development_case_comparison.json', reviewed)
    for experiment in ['bert_chunks', 'bert_context_contrast']:
        report = reports[experiment]
        write(paths[experiment] / 'checkpoint_manifest.json', {
            'format': 'trainable_last_four_bert_layers_and_action_head',
            'base_model': reference['base_model'], 'base_weight_sha256': reference['base_weight_sha256'],
            'separate_prefix_encoding': report['protocol'].get('separate_prefix_encoding', False),
            'action_order': next(iter(report['results'].values()))['development']['confusion']['true_rows_predicted_columns'],
            'checkpoints': {name: {k: row[k] for k in ['epoch', 'checkpoint', 'sha256', 'trainable_parameters']} for name, row in report['selected'].items()},
            'production_promoted': False,
            'note': 'Only trainable parameters are stored; verified pretrained base is required. Given targets; not a privacy detector.',
        })
    print(json.dumps({'rows': len(summary), 'preferred_offline': chosen, 'tests': result['related_tests_passed']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
