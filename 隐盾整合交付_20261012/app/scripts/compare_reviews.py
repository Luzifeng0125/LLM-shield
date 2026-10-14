"""比较两份独立复核记录，输出分歧与裁决模板。未裁决或有疑问时不输出最终质量分数。"""
import argparse
import json
from pathlib import Path

CHOICES = {'leak': {'yes', 'no', 'uncertain'}, 'utility': {'0', '1', '2', 'na'},
           'false_pause': {'yes', 'no', 'na', 'uncertain'}}


def validate_review(review):
    if not review.get('complete') or not review.get('reviewer', '').strip():
        raise ValueError('复核记录尚未完成或缺少复核者代号')
    records = review.get('records', [])
    ids = [r.get('unit_id') for r in records]
    if not ids or None in ids or len(ids) != len(set(ids)):
        raise ValueError('复核单元为空或重复')
    for record in records:
        if any(record.get(k) not in values for k, values in CHOICES.items()):
            raise ValueError('包含空判断或未知选项')
        if not record.get('viewed_result') or any(not record.get(k, '').strip()
                for k in ('required_facts', 'forbidden_facts', 'notes')):
            raise ValueError('缺少原文判断或证据说明')
    return {r['unit_id']: r for r in records}


def compare_reviews(a, b):
    left, right = validate_review(a), validate_review(b)
    if a['reviewer'].strip().casefold() == b['reviewer'].strip().casefold():
        raise ValueError('必须由两位不同的复核者独立填写')
    if not a.get('evidence_hash') or a['evidence_hash'] != b.get('evidence_hash'):
        raise ValueError('证据指纹不一致，不能合并不同版本的判断')
    if left.keys() != right.keys():
        raise ValueError('复核单元不一致')
    conflicts, agreed = [], []
    for unit_id in left:
        x, y = left[unit_id], right[unit_id]
        fields = [k for k in CHOICES if x[k] != y[k] or 'uncertain' in {x[k], y[k]}]
        if fields:
            conflicts.append({'unit_id': unit_id, 'fields': fields, 'review_a': x, 'review_b': y,
                              'final': {k: '' for k in CHOICES}, 'reason': ''})
        else:
            agreed.append({'unit_id': unit_id, **{k: x[k] for k in CHOICES}})
    return {'evidence_hash': a['evidence_hash'], 'reviewers': [a['reviewer'], b['reviewer']],
            'units': len(left), 'agreement_units': len(agreed),
            'agreement_rate': len(agreed) / len(left), 'pending_adjudication': len(conflicts),
            'agreed': agreed, 'conflicts': conflicts,
            'note': '一致率仅描述本批复核，不代表隐私准确率。裁决者还需抽查一致记录的原文依据。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('review_a', type=Path)
    parser.add_argument('review_b', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = compare_reviews(json.loads(args.review_a.read_text(encoding='utf-8-sig')),
                                 json.loads(args.review_b.read_text(encoding='utf-8-sig')))
    except (ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    # Do not overwrite signed human adjudication with a fresh blank template.
    with args.out.open('x', encoding='utf-8') as handle:
        json.dump({'arbitrator': '', **result}, handle, ensure_ascii=False, indent=2)
    print(json.dumps({k: result[k] for k in ('units', 'agreement_units', 'pending_adjudication')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
