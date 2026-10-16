"""Software fixtures only. None of these annotations constitute human review."""
import copy
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
import warnings
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_reviewed_gold as prep


def fixture_target(marker='SOFTWARE_FIXTURE_OUTPUT'):
    return {'preferred_action': 'RETAIN', 'acceptable_actions': ['RETAIN'],
            'send_allowed': True, 'sanitized_text': marker, 'reason': 'SOFTWARE FIXTURE ONLY'}


def fixture_rows():
    result = {}
    for split, (batch, _) in prep.BATCHES.items():
        path = prep.ROOT / '批次' / batch / '复核员A' / '空白复核表.jsonl'
        originals = prep.parse_jsonl(path.read_bytes(), str(path))
        result[split] = []
        for original in originals:
            row = {key: value for key, value in original.items() if key not in prep.FORM_ONLY}
            if row['kind'] == 'dialogue':
                annotation = {'turns': [{'turn_id': turn['turn_id'], 'entities': [],
                                         'target': fixture_target()} for turn in row['turns']]}
            else:
                annotation = {'entities': []}
                if row['kind'] == 'policy':
                    annotation['target'] = fixture_target()
            row.update(annotation=annotation, label_origin='human_dual_review_adjudicated',
                       human_reviewed=True, adjudicator='SOFTWARE_FIXTURE_NOT_HUMAN',
                       adjudicated_date='2026-10-16', adjudication_reason='SOFTWARE TEST ONLY',
                       review_sha256={'A': 'a' * 64, 'B': 'b' * 64},
                       gold_schema_version='review-1.0', annotation_guideline_version='1.0',
                       source_kind='synthetic')
            result[split].append(row)
    return result


class PrepareReviewedGoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = fixture_rows()

    def archive(self, root, rows=None, extras=None, filename='fixture.zip'):
        path = root / filename
        rows = self.rows if rows is None else rows
        members = {}
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('gold/', b'')
            for split, values in rows.items():
                # Deliberately non-default BOM/newlines/order to verify byte preservation.
                data = ('\ufeff' + '\r\n'.join(json.dumps(row, ensure_ascii=False) for row in values) + '\r\n').encode('utf-8')
                name = f'gold/{split}_gold.jsonl'
                members[name] = data
                archive.writestr(name, data)
            for name, data in (extras or []):
                archive.writestr(name, data)
        return path, members

    def test_complete_preparation_preserves_bytes_and_seals_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive, members = self.archive(root)
            out = root / 'ready'
            result = prep.prepare(archive, out)
            self.assertEqual({s: r['units'] for s, r in result['splits'].items()},
                             {'train': 128, 'validation': 92, 'test': 92})
            for name, data in members.items():
                self.assertEqual((out / name).read_bytes(), data)
                self.assertEqual(result['archive_members'][name]['sha256'], prep.sha256(data))
            self.assertEqual(result['provenance']['status'], 'self-described')
            self.assertFalse(result['provenance']['independent_human_review_verified'])
            self.assertTrue(result['splits']['test']['excluded_from_training_and_evaluation'])
            self.assertEqual((out / 'source/gold.zip').read_bytes(), archive.read_bytes())
            self.assertNotIn('label_coverage', result['splits']['test'])
            self.assertNotIn('kind_counts', result['splits']['test'])
            self.assertEqual(sorted(p.relative_to(out).as_posix() for p in out.rglob('*test*')),
                             ['gold/test_gold.jsonl'])
            for split in ('train', 'validation'):
                ner = prep.parse_jsonl((out / 'ner' / f'{split}.jsonl').read_bytes(), 'ner')
                bio = prep.parse_jsonl((out / 'bio' / f'{split}.jsonl').read_bytes(), 'bio')
                sft = prep.parse_jsonl((out / 'sft' / f'{split}.jsonl').read_bytes(), 'sft')
                expected = sum(len(r['turns']) if r['kind'] == 'dialogue' else 1 for r in self.rows[split])
                self.assertEqual((len(ner), len(bio), len(sft)), (expected,) * 3)
                for raw, encoded in zip(ner, bio):
                    self.assertEqual(''.join(encoded['tokens']), raw['text'])
                    self.assertEqual(len(encoded['tokens']), len(encoded['ner_tags']))
                    self.assertEqual(raw['source_kind'], 'synthetic')
                    self.assertIn('source_case_id', raw)
                    self.assertIn('origin_kind', raw)
            with self.assertRaises(ValueError):
                prep.prepare(archive, out)

    def test_unsafe_and_duplicate_zip_members_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index, name in enumerate(['../escape.py', 'gold/../escape.py', 'gold\\train_gold.jsonl',
                                          '/gold/train_gold.jsonl', 'gold/run.py', 'gold/train_gold.jsonl']):
                with self.subTest(name=name), warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    archive, _ = self.archive(root, extras=[(name, b'print("never execute")')], filename=f'bad{index}.zip')
                    out = root / f'bad{index}'
                    with self.assertRaises(ValueError):
                        prep.prepare(archive, out)
                    self.assertFalse(out.exists())
            link = zipfile.ZipInfo('gold/train_gold.jsonl')
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive = root / 'link.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr(link, b'../../sensitive')
                for split in ('validation', 'test'):
                    output.writestr(f'gold/{split}_gold.jsonl', b'')
            with self.assertRaises(ValueError):
                prep.read_archive(archive)

    def test_json_parser_rejects_duplicate_keys_and_nonfinite_numbers(self):
        for invalid in (b'{"id":"a","id":"b"}', b'{"value": NaN}', b'[]'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                prep.parse_jsonl(invalid, 'fixture')

    def test_immutable_provenance_and_annotation_contracts(self):
        cases = [
            ('text', 'changed'), ('split', 'test'), ('kind', 'policy'), ('batch', 'other'),
            ('id', 'not-in-batch'), ('human_reviewed', 1), ('source_kind', 'real'),
            ('label_origin', 'weak'), ('adjudicator', ''), ('adjudicated_date', ''),
            ('adjudication_reason', ''), ('gold_schema_version', '2'),
            ('annotation_guideline_version', '2'), ('review_sha256', {'A': 'x', 'B': 'b' * 64}),
            ('review_sha256', {'A': 'c' * 64, 'B': 'b' * 64}),
            ('annotation', {'entities': [{'start': -1, 'end': 1, 'text': 'x', 'category': 'PERSON_NAME'}]}),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                rows = copy.deepcopy(self.rows['train'])
                rows[0][key] = value
                with self.assertRaises((ValueError, KeyError, TypeError)):
                    prep.validate_split(rows, 'train')
        rows = copy.deepcopy(self.rows['train'])
        rows[1]['id'] = rows[0]['id']
        with self.assertRaises(ValueError):
            prep.validate_split(rows, 'train')
        rows = copy.deepcopy(self.rows['train'])
        dialogue = next(r for r in rows if r['kind'] == 'dialogue')
        dialogue['annotation']['turns'][0]['turn_id'] = 999
        with self.assertRaises(ValueError):
            prep.validate_split(rows, 'train')
        rows = copy.deepcopy(self.rows['train'])
        policy = next(r for r in rows if r['kind'] == 'policy')
        policy['annotation']['target']['preferred_action'] = 'PAUSE'
        with self.assertRaises(ValueError):
            prep.validate_split(rows, 'train')

    def test_unicode_bio_spans_and_whitespace_round_trip(self):
        row = {'id': 'fixture', 'text': ' \t😀小王\n', 'entities': [
            {'start': 3, 'end': 5, 'text': '小王', 'category': 'PERSON_NAME'}]}
        result = prep.bio_row(row)
        self.assertEqual(result['tokens'], [' ', '\t', '😀', '小', '王', '\n'])
        self.assertEqual(result['ner_tags'], ['O', 'O', 'O', 'B-PERSON_NAME', 'I-PERSON_NAME', 'O'])
        self.assertEqual([prep.BIO_LABELS[n] for n in result['label_ids']], result['ner_tags'])
        self.assertEqual(len(prep.CATEGORIES), 14)
        self.assertEqual(len(prep.BIO_LABELS), 29)

    def test_sft_history_never_contains_current_targets_or_future_turns(self):
        dialogue = copy.deepcopy(next(r for r in self.rows['train'] if r['kind'] == 'dialogue'))
        for index, (turn, ann) in enumerate(zip(dialogue['turns'], dialogue['annotation']['turns'])):
            turn['text'] = f'UNIQUE_USER_TURN_{index}'
            ann['target'] = fixture_target(f'UNIQUE_GOLD_TARGET_{index}')
        rows = list(prep.sft_rows([dialogue]))
        for index, row in enumerate(rows):
            payload = json.loads(row['input'])
            self.assertEqual(payload['history'], dialogue['turns'][:index])
            self.assertEqual(payload['text'], dialogue['turns'][index]['text'])
            self.assertNotIn('UNIQUE_GOLD_TARGET_', row['input'])
            for future in dialogue['turns'][index + 1:]:
                self.assertNotIn(future['text'], row['input'])
            self.assertEqual(row['history_mode'], 'prior_user_inputs_only')
            self.assertEqual(json.loads(row['messages'][-1]['content'])['sanitized_text'], f'UNIQUE_GOLD_TARGET_{index}')
        policy = next(r for r in self.rows['train'] if r['kind'] == 'policy')
        sample = next(prep.sft_rows([policy]))
        self.assertNotIn('entities', json.loads(sample['input']))
        self.assertNotIn('target', json.loads(sample['input']))

    def test_overlap_distinguishes_common_turns_from_full_units(self):
        rows = copy.deepcopy(self.rows)
        train_dialogue = next(r for r in rows['train'] if r['kind'] == 'dialogue')
        val_dialogue = next(r for r in rows['validation'] if r['kind'] == 'dialogue')
        val_dialogue['turns'][0]['text'] = train_dialogue['turns'][0]['text']
        result = prep.check_overlap(rows)
        self.assertGreater(result['pairs']['train:validation']['individual_dialogue_turn_texts'], 0)
        replacement = copy.deepcopy(train_dialogue)
        replacement['id'] = val_dialogue['id']
        replacement['trusted_policy'] = {'different_configuration': True}
        rows['validation'][rows['validation'].index(val_dialogue)] = replacement
        with self.assertRaises(ValueError):
            prep.check_overlap(rows)
        rows = copy.deepcopy(self.rows)
        rows['validation'][0]['text'] = rows['train'][0]['text']
        with self.assertRaises(ValueError):
            prep.check_overlap(rows)

    def test_optional_decisions_exact_match_and_rejection(self):
        decisions = []
        for row in self.rows['train']:
            decisions.append({key: row[key] for key in ('id', 'kind', 'split') + prep.SIGNATURE_FIELDS} |
                             {'approved': True, 'final_annotation': row['annotation']})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'decisions.jsonl'
            path.write_bytes(prep.jsonl_bytes(decisions))
            self.assertEqual(prep.check_decisions(path, self.rows['train'])['matched_train_units'], 128)
            decisions[0]['final_annotation'] = {'entities': [{'wrong': 'fields'}]}
            path.write_bytes(prep.jsonl_bytes(decisions))
            with self.assertRaises(ValueError):
                prep.check_decisions(path, self.rows['train'])


if __name__ == '__main__':
    unittest.main()
