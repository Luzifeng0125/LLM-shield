"""Software fixtures only; never load the sealed test dataset."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import evaluate_gold_ner as evaluation


def entity(start=0, end=2, category='PERSON_NAME', text='小王'):
    return {'start': start, 'end': end, 'category': category, 'text': text}


def gold(ident='N1', entities=None):
    return {'id': ident, 'text': '小王来了', 'split': 'validation', 'kind': 'ner', 'batch': 'fixture',
            'annotation': {'entities': [entity()] if entities is None else entities},
            'human_reviewed': True, 'label_origin': 'human_dual_review_adjudicated',
            'source_kind': 'synthetic', 'gold_schema_version': 'review-1.0',
            'annotation_guideline_version': '1.0', 'adjudicator': 'SOFTWARE_FIXTURE',
            'adjudicated_date': '2026-10-16', 'adjudication_reason': 'Not a human annotation',
            'review_sha256': {'A': 'a' * 64, 'B': 'b' * 64}}


def dump(path, rows):
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')


class GoldEvaluationTests(unittest.TestCase):
    def test_strict_boundaries_categories_and_negative_false_positives(self):
        rows = [gold('correct'), gold('boundary'), gold('category'),
                gold('negative_fp', []), gold('negative_clean', [])]
        predictions = {'correct': [entity()], 'boundary': [entity(end=1, text='小')],
                       'category': [entity(category='ORG')], 'negative_fp': [entity()], 'negative_clean': []}
        report, predictions_out, errors = evaluation.score(rows, predictions)
        self.assertEqual((report['micro']['tp'], report['micro']['fp'], report['micro']['fn']), (1, 3, 2))
        self.assertAlmostEqual(report['micro']['f1'], 2 / 7)
        self.assertEqual(report['exact_document_match'], {'numerator': 2, 'denominator': 5, 'rate': 0.4})
        self.assertEqual(report['negative_false_positive'],
                         {'numerator': 1, 'denominator': 2, 'rate': 0.5, 'false_positive_entities': 1})
        self.assertEqual(len(predictions_out), 5)
        self.assertEqual({row['id'] for row in errors}, {'boundary', 'category', 'negative_fp'})

    def test_all_fourteen_categories_and_no_support_are_explicit(self):
        report, _, _ = evaluation.score([gold()], {'N1': [entity()]})
        self.assertEqual(len(report['per_category']), 14)
        self.assertEqual(len(report['categories_without_gold_support']), 13)
        self.assertFalse(report['per_category']['PHONE']['has_gold_support'])
        self.assertEqual(report['per_category']['PHONE']['gold_entities'], 0)
        self.assertIsNone(report['negative_false_positive']['rate'])

    def test_invalid_predictions_are_refused_not_dropped(self):
        invalid = [[entity(start=True)], [entity(end=9)], [entity(category='UNKNOWN')],
                   [entity(text='wrong')], [entity(), entity()],
                   [entity(), entity(start=1, end=3, text='王来')],
                   [{**entity(), 'confidence': float('nan')}]]
        for predictions in invalid:
            with self.subTest(predictions=predictions), self.assertRaises(ValueError):
                evaluation.score([gold()], {'N1': predictions})

    def test_prediction_ids_must_match_all_and_only_ner(self):
        with tempfile.TemporaryDirectory(prefix='gold_eval_fixture_') as tmp:
            path = Path(tmp) / 'predictions.jsonl'
            for incoming in ([{'id': 'other', 'entities': []}],
                             [{'id': 'N1', 'entities': []}, {'id': 'N1', 'entities': []}],
                             [{'id': 'N1', 'entities': []}, {'id': 'policy', 'entities': []}]):
                dump(path, incoming)
                with self.assertRaises(ValueError):
                    evaluation.load_predictions(path, [gold()])
            dump(path, [{'id': 'N1', 'entities': [entity()]}])
            self.assertEqual(evaluation.load_predictions(path, [gold()]), {'N1': [entity()]})

    def test_sealed_filename_is_rejected_before_any_read(self):
        with patch.object(evaluation, 'read_jsonl') as read:
            for name in ('test_gold.jsonl', 'train_gold.jsonl'):
                with self.assertRaises(ValueError):
                    evaluation.load_gold(Path(name))
            read.assert_not_called()

    def test_validation_gold_schema_and_reference_gate(self):
        with tempfile.TemporaryDirectory(prefix='gold_eval_fixture_') as tmp:
            path = Path(tmp) / 'validation_gold.jsonl'
            expected = Path(tmp) / 'reference.jsonl'
            valid = gold()
            reference = {k: v for k, v in valid.items() if k not in evaluation.PROVENANCE}
            reference.update(reviewer='A', reviewed=False, notes='')
            dump(expected, [reference])
            dump(path, [valid])
            all_rows, selected = evaluation.load_gold(path, expected)
            self.assertEqual(len(all_rows), 1)
            self.assertEqual(selected[0]['id'], 'N1')
            variants = []
            for key, value in [('split', 'test'), ('id', 'UNKNOWN'), ('kind', 'unknown'),
                               ('text', 'changed'), ('human_reviewed', False), ('unknown_field', True)]:
                changed = copy.deepcopy(valid)
                changed[key] = value
                variants.append([changed])
            invalid_span = copy.deepcopy(valid)
            invalid_span['annotation']['entities'][0]['start'] = -1
            variants.extend([[valid, valid], [invalid_span]])
            for variant in variants:
                dump(path, variant)
                with self.subTest(variant=variant), self.assertRaises(ValueError):
                    evaluation.load_gold(path, expected)

    def test_duplicate_json_fields_are_refused(self):
        with tempfile.TemporaryDirectory(prefix='gold_eval_fixture_') as tmp:
            path = Path(tmp) / 'prediction.jsonl'
            path.write_text('{"id":"N1","id":"N2","entities":[]}\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                evaluation.read_jsonl(path)

    def test_no_overwrite_before_any_dataset_is_opened(self):
        with tempfile.TemporaryDirectory(prefix='gold_eval_fixture_') as tmp:
            with patch.object(evaluation, 'load_gold') as read:
                with self.assertRaises(ValueError):
                    evaluation.evaluate(Path('validation_gold.jsonl'), Path('app'), Path(tmp))
                read.assert_not_called()

    def test_prediction_artifact_round_trips(self):
        rows = [gold()]
        _, predictions, _ = evaluation.score(rows, {'N1': [entity()]})
        with tempfile.TemporaryDirectory(prefix='gold_eval_fixture_') as tmp:
            path = Path(tmp) / 'predictions.jsonl'
            evaluation.write_jsonl(path, predictions)
            self.assertEqual(evaluation.load_predictions(path, rows), {'N1': [entity()]})
            with self.assertRaises(FileExistsError):
                evaluation.write_jsonl(path, predictions)


if __name__ == '__main__':
    unittest.main()
