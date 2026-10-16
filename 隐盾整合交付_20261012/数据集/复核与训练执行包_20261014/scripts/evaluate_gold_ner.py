"""Evaluate the current rule/context detector on human-reviewed synthetic validation gold.

This command never evaluates the sealed test split. It does not train a model,
score policy/dialogue decisions, or measure real-world privacy accuracy.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import re
import sys
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

# Support the project's isolated Windows Python runtime as a standalone CLI.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_workflow as workflow

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / '批次' / '02_独立验证' / '复核员A' / '空白复核表.jsonl'
CATEGORIES = tuple(sorted(workflow.CATS))
PROVENANCE = {'label_origin', 'human_reviewed', 'adjudicator', 'adjudicated_date',
              'adjudication_reason', 'review_sha256', 'gold_schema_version',
              'annotation_guideline_version', 'source_kind'}
IGNORED_FORM_FIELDS = {'annotation', 'reviewer', 'reviewed', 'notes', 'review_audit'}


def ensure(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        ensure(key not in result, f'Duplicate JSON field: {key}')
        result[key] = value
    return result


def read_jsonl(path):
    rows = []
    for number, line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line, object_pairs_hook=unique_object)
            ensure(isinstance(row, dict), 'JSONL rows must be objects')
        except (ValueError, TypeError) as exc:
            raise ValueError(f'{Path(path).name}:{number}: {exc}') from exc
        rows.append(row)
    ensure(rows, f'Empty JSONL: {Path(path).name}')
    return rows


def index(rows, description):
    result = {}
    for row in rows:
        ident = row.get('id')
        ensure(isinstance(ident, str) and bool(ident.strip()), f'{description}: invalid ID')
        ensure(ident not in result, f'{description}: duplicate ID {ident}')
        result[ident] = row
    return result


def validate_entities(text, entities, *, prediction=False):
    ensure(isinstance(text, str), 'Text must be a string')
    ensure(isinstance(entities, list), 'Entities must be a list')
    normalized, seen = [], set()
    for entity in entities:
        ensure(isinstance(entity, dict), 'Entity must be an object')
        required = {'start', 'end', 'category'}
        allowed = required | {'text', 'confidence', 'detector', 'rule_id', 'column', 'row_index'}
        ensure(required <= set(entity) <= allowed if prediction else
               set(entity) == required | {'text'}, 'Invalid entity fields')
        start, end, category = entity['start'], entity['end'], entity['category']
        ensure(type(start) is int and type(end) is int and 0 <= start < end <= len(text),
               'Invalid Unicode character offsets')
        ensure(isinstance(category, str) and category in CATEGORIES, 'Unknown entity category')
        ensure('text' not in entity or entity['text'] == text[start:end], 'Entity text/offset mismatch')
        if 'confidence' in entity:
            value = entity['confidence']
            ensure(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1,
                   'Invalid prediction confidence')
        key = start, end, category
        ensure(key not in seen, 'Duplicate entity')
        seen.add(key)
        normalized.append({'start': start, 'end': end, 'text': text[start:end], 'category': category})
    normalized.sort(key=lambda e: (e['start'], e['end'], e['category']))
    ensure(all(left['end'] <= right['start'] for left, right in zip(normalized, normalized[1:])),
           'Overlapping entities are not supported by review-1.0')
    return normalized


def load_gold(path, expected_path=EXPECTED):
    path = Path(path)
    # Reject the actual sealed filename before opening any content. Renamed files
    # are additionally rejected by split and by the frozen validation ID set.
    ensure(path.name == 'validation_gold.jsonl', 'Only validation_gold.jsonl may be evaluated')
    rows = read_jsonl(path)
    ensure(all(row.get('split') == 'validation' for row in rows),
           'Only validation split is permitted; train/test evaluation is forbidden')
    expected = index(read_jsonl(expected_path), 'frozen validation forms')
    ensure(all(row.get('split') == 'validation' for row in expected.values()),
           'Frozen reference must contain validation only')
    actual = index(rows, 'gold')
    ensure(set(actual) == set(expected), 'Gold IDs must exactly match the frozen validation batch')
    for ident, row in actual.items():
        original = expected[ident]
        immutable = {key: value for key, value in original.items() if key not in IGNORED_FORM_FIELDS}
        ensure(set(row) in (set(immutable) | PROVENANCE | {'annotation'},
                            set(immutable) | PROVENANCE | {'annotation', 'review_audit'}),
               f'{ident}: unknown or missing gold fields')
        ensure(all(row[key] == value for key, value in immutable.items()),
               f'{ident}: original text, context, kind, or batch changed')
        ensure(row['kind'] in {'ner', 'policy', 'dialogue'}, f'{ident}: unknown kind')
        ensure(row['label_origin'] == 'human_dual_review_adjudicated'
               and row['human_reviewed'] is True and row['source_kind'] == 'synthetic',
               f'{ident}: expected human-adjudicated synthetic labels')
        ensure(row['gold_schema_version'] == 'review-1.0'
               and row['annotation_guideline_version'] == '1.0', f'{ident}: unsupported gold version')
        for key in ('adjudicator', 'adjudicated_date', 'adjudication_reason'):
            ensure(isinstance(row[key], str) and bool(row[key].strip()), f'{ident}: missing {key}')
        ensure(date.fromisoformat(row['adjudicated_date']).isoformat() == row['adjudicated_date'],
               f'{ident}: invalid adjudicated date')
        hashes = row['review_sha256']
        ensure(isinstance(hashes, dict) and set(hashes) == {'A', 'B'} and
               all(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)
                   for value in hashes.values()), f'{ident}: invalid review hashes')
        try:
            workflow.validate_annotation(row, row['annotation'])
            if row['kind'] == 'dialogue':
                for source, annotation in zip(row['turns'], row['annotation']['turns']):
                    validate_entities(source['text'], annotation['entities'])
            else:
                validate_entities(row['text'], row['annotation']['entities'])
            if 'review_audit' in row:
                ensure(isinstance(row['review_audit'], dict) and set(row['review_audit']) == {'A', 'B'},
                       'Review audit must contain A and B')
                for reviewer, audit in row['review_audit'].items():
                    workflow.validate_review_audit({'reviewer': reviewer, 'reviewed': True,
                                                    'review_audit': audit})
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f'{ident}: invalid annotation or audit: {exc}') from exc
    selected = [row for row in rows if row['kind'] == 'ner']
    ensure(selected, 'No NER validation units')
    return rows, selected


def load_predictions(path, rows):
    incoming = index(read_jsonl(path), 'predictions')
    ensure(set(incoming) == {row['id'] for row in rows},
           'Prediction IDs must match every NER validation ID, with no extras')
    result = {}
    for row in rows:
        item = incoming[row['id']]
        ensure({'id', 'entities'} <= set(item) <= {'id', 'entities', 'text_sha256', 'split'},
               f'{row["id"]}: invalid prediction fields')
        ensure(item.get('split', 'validation') == 'validation', 'Predictions must use validation split')
        ensure(item.get('text_sha256', text_hash(row['text'])) == text_hash(row['text']),
               f'{row["id"]}: prediction text hash mismatch')
        result[row['id']] = validate_entities(row['text'], item['entities'], prediction=True)
    return result


def current_detector(app):
    app = Path(app).resolve(strict=True)
    ensure((app / 'llm_shield' / 'm2_detect' / 'pipeline.py').is_file(), 'Invalid --app directory')
    sys.path.insert(0, str(app))
    pipeline = importlib.import_module('llm_shield.m2_detect.pipeline')
    ensure(Path(pipeline.__file__).resolve() == app / 'llm_shield' / 'm2_detect' / 'pipeline.py',
           'A different llm_shield package is already imported')
    # Explicitly freeze the baseline to rules/context. No model weights are
    # needed and .env cannot silently turn this into a different experiment.
    detectors = [pipeline.RegexDetector(), pipeline.EntityDetector()]
    files = sorted((app / 'llm_shield').rglob('*.py')) + sorted((app / 'config').glob('*.yaml'))
    metadata = {'mode': 'current_rule_context_detector', 'campus_ner_enabled': False,
                'detectors': [type(detector).__name__ for detector in detectors],
                'app_path': str(app),
                'source_sha256': {str(path.relative_to(app)): sha256(path) for path in files}}

    def predict(text):
        return [span.to_dict() for span in pipeline.detect_and_segment(text, detectors=detectors)[0]]

    return predict, metadata


def metrics(tp, fp, fn):
    return {'tp': tp, 'fp': fp, 'fn': fn, 'gold_entities': tp + fn, 'predicted_entities': tp + fp,
            'precision': tp / (tp + fp) if tp + fp else 0.0,
            'recall': tp / (tp + fn) if tp + fn else 0.0,
            'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0}


def score(rows, predictions):
    ensure(set(predictions) == {row['id'] for row in rows}, 'Incomplete prediction set')
    tp, fp, fn = Counter(), Counter(), Counter()
    exact = negatives = negative_fp_documents = negative_fp_entities = 0
    prediction_rows, errors = [], []
    for row in rows:
        gold = validate_entities(row['text'], row['annotation']['entities'])
        predicted = validate_entities(row['text'], predictions[row['id']], prediction=True)
        key = lambda entity: (entity['start'], entity['end'], entity['category'])
        gold_set, predicted_set = {key(e) for e in gold}, {key(e) for e in predicted}
        matched, extra, missing = gold_set & predicted_set, predicted_set - gold_set, gold_set - predicted_set
        tp.update(entity[2] for entity in matched)
        fp.update(entity[2] for entity in extra)
        fn.update(entity[2] for entity in missing)
        exact += int(gold_set == predicted_set)
        if not gold:
            negatives += 1
            negative_fp_documents += bool(predicted)
            negative_fp_entities += len(predicted)
        prediction_rows.append({'id': row['id'], 'split': 'validation',
                                'text_sha256': text_hash(row['text']), 'entities': predicted})
        if extra or missing:
            errors.append({'id': row['id'], 'text': row['text'], 'gold_entities': gold,
                           'predicted_entities': predicted,
                           'false_positives': [e for e in predicted if key(e) in extra],
                           'false_negatives': [e for e in gold if key(e) in missing]})
    report = {'documents': len(rows), 'gold_entity_count': sum(tp.values()) + sum(fn.values()),
              'micro': metrics(sum(tp.values()), sum(fp.values()), sum(fn.values())),
              'per_category': {category: {**metrics(tp[category], fp[category], fn[category]),
                                         'has_gold_support': tp[category] + fn[category] > 0}
                               for category in CATEGORIES},
              'exact_document_match': {'numerator': exact, 'denominator': len(rows),
                                       'rate': exact / len(rows) if rows else None},
              'negative_false_positive': {'numerator': negative_fp_documents, 'denominator': negatives,
                                          'rate': negative_fp_documents / negatives if negatives else None,
                                          'false_positive_entities': negative_fp_entities},
              'categories_without_gold_support': [c for c in CATEGORIES if tp[c] + fn[c] == 0],
              'coverage_note': 'Zero-support categories have not been validated; zero-division scores are 0.'}
    return report, prediction_rows, errors


def write_jsonl(path, rows):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')


def evaluate(data, app, out, predictions=None):
    out = Path(out)
    ensure(not out.exists(), f'Refusing to overwrite output directory: {out}')
    started = time.perf_counter()
    all_rows, rows = load_gold(data)
    if predictions is not None:
        predicted = load_predictions(predictions, rows)
        model = {'mode': 'provided_predictions', 'predictions_path': str(Path(predictions).resolve()),
                 'predictions_sha256': sha256(predictions), 'detector_identity': 'not independently verified'}
    else:
        predict, model = current_detector(app)
        predicted = {}
        for row in rows:
            try:
                predicted[row['id']] = validate_entities(row['text'], predict(row['text']), prediction=True)
            except Exception as exc:
                raise ValueError(f'{row["id"]}: detector failed or returned invalid output ({type(exc).__name__}); '
                                 'no evaluation artifacts written') from exc
    report, prediction_rows, errors = score(rows, predicted)
    report.update(schema_version='gold-ner-evaluation-1.0',
                  evaluated_at_utc=datetime.now(timezone.utc).isoformat(), split='validation', kind='ner',
                  evaluation_scope='human-adjudicated synthetic validation NER only',
                  model=model, data_path=str(Path(data).resolve()), data_sha256=sha256(data),
                  frozen_validation_forms_sha256=sha256(EXPECTED),
                  label_origin='human_dual_review_adjudicated', source_kind='synthetic',
                  review_sha256=sorted({(r['review_sha256']['A'], r['review_sha256']['B']) for r in rows}),
                  total_gold_units=len(all_rows), excluded_units_by_kind=dict(Counter(
                      row['kind'] for row in all_rows if row['kind'] != 'ner')),
                  matching='Exact Unicode code-point (start, end, category); no partial credit',
                  elapsed_seconds=round(time.perf_counter() - started, 3),
                  python_version=sys.version.split()[0], sealed_test_evaluated=False,
                  note=('Current rule/context baseline when model.mode=current_rule_context_detector. '
                        'Not a newly trained NER score, real-world privacy accuracy, policy score, '
                        'dialogue score, or end-to-end safety result. Human review provenance is '
                        'declared by the supplied export; signatures are not independently authenticated.'))
    out.mkdir(parents=True, exist_ok=False)
    write_jsonl(out / 'predictions.jsonl', prediction_rows)
    write_jsonl(out / 'errors.jsonl', errors)
    report['artifact_sha256'] = {name: sha256(out / name) for name in ('predictions.jsonl', 'errors.jsonl')}
    with (out / 'summary.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--app', type=Path, default=ROOT.parents[1] / 'app')
    parser.add_argument('--out', required=True, type=Path, help='New directory; existing paths are refused')
    parser.add_argument('--split', choices=['validation'], default='validation')
    parser.add_argument('--predictions', type=Path, help='Offline JSONL: all NER validation IDs and entities')
    args = parser.parse_args()
    try:
        report = evaluate(args.data, args.app, args.out, args.predictions)
    except (ValueError, KeyError, TypeError, OSError, ImportError) as exc:
        parser.exit(2, f'Refused: {exc}\n')
    print(json.dumps({key: report[key] for key in ('split', 'documents', 'micro', 'exact_document_match',
                                                 'negative_false_positive')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
