"""Software fixtures for BIO alignment and gold boundaries, not model evidence."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train_transformer_ner as ner


def entity(text, start, end, category="PERSON_NAME"):
    return {"start": start, "end": end, "text": text[start:end], "category": category}


def row(split, text="软件测试文本", origin="ner", entities=None):
    return {"id": split + "-fixture", "source_case_id": split + "-source", "split": split,
            "text": text, "entities": entities or [], "human_reviewed": True,
            "label_origin": "human_dual_review_adjudicated", "source_kind": "software_fixture",
            "origin_kind": origin}


class AlignmentTests(unittest.TestCase):
    def test_unicode_supplementary_codepoint_and_special_tokens(self):
        text = "🙂张三来"
        labels = ner.align_token_labels(text, [entity(text, 1, 3)],
                                        [(0, 0), (0, 1), (1, 2), (2, 3), (3, 4), (0, 0)])
        self.assertEqual(labels, [-100, 0, ner.LABEL2ID["B-PERSON_NAME"],
                                  ner.LABEL2ID["I-PERSON_NAME"], 0, -100])

    def test_adjacent_entities_get_separate_beginnings(self):
        text = "张三李四"
        labels = ner.align_token_labels(text, [entity(text, 0, 2), entity(text, 2, 4)],
                                        [(0, 1), (1, 2), (2, 3), (3, 4)])
        self.assertEqual([ner.BIO_LABELS[label] for label in labels],
                         ["B-PERSON_NAME", "I-PERSON_NAME", "B-PERSON_NAME", "I-PERSON_NAME"])

    def test_wordpieces_and_internal_whitespace(self):
        text = "联系ab cd"
        labels = ner.align_token_labels(text, [entity(text, 2, 7, "EMAIL")],
                                        [(0, 1), (1, 2), (2, 4), (5, 7)])
        self.assertEqual([ner.BIO_LABELS[label] for label in labels], ["O", "O", "B-EMAIL", "I-EMAIL"])

    def test_rejects_crossing_boundary_dropped_entity_and_truncation(self):
        text = "张三来"
        bad_offsets = [[(0, 3)], [(0, 1)], [(1, 2)], [(0, 0)], [(0, 1), (2, 3)]]
        for offsets in bad_offsets:
            with self.subTest(offsets=offsets), self.assertRaises(ValueError):
                ner.align_token_labels(text, [entity(text, 0, 2)], offsets)
        with self.assertRaisesRegex(ValueError, "Truncated"):
            ner.align_token_labels(text, [], [(0, 1)], truncated=True)

    def test_rejects_omitted_non_whitespace_inside_entity(self):
        text = "张X三"
        with self.assertRaisesRegex(ValueError, "dropped non-whitespace"):
            ner.align_token_labels(text, [entity(text, 0, 3)], [(0, 1), (2, 3)])

    def test_rejects_overlapping_annotations_and_bad_text(self):
        text = "张三"
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            ner.align_token_labels(text, [entity(text, 0, 2), entity(text, 1, 2)], [(0, 1), (1, 2)])
        bad = entity(text, 0, 2)
        bad["text"] = "假名"
        with self.assertRaisesRegex(ValueError, "offsets differ"):
            ner.align_token_labels(text, [bad], [(0, 1), (1, 2)])

    def test_encode_rejects_length_before_truncation(self):
        class FakeFastTokenizer:
            is_fast = True

            def __call__(self, text, **kwargs):
                assert kwargs["truncation"] is False
                return {"input_ids": [101, 1, 2, 102], "attention_mask": [1] * 4,
                        "offset_mapping": [(0, 0), (0, 1), (1, 2), (0, 0)]}
        with self.assertRaisesRegex(ValueError, "refusing truncation"):
            ner.encode_rows(FakeFastTokenizer(), [row("train", "测试")], 3)

    def test_alignment_roundtrips_through_application_bio_decoder(self):
        sys.path.insert(0, str(ner.APP))
        from eval.reviewed_ner import decode_bio
        text = "🙂张三ab cd"
        gold = [entity(text, 1, 3), entity(text, 3, 8, "EMAIL")]
        offsets = [(0, 0), (0, 1), (1, 2), (2, 3), (3, 5), (6, 8), (0, 0)]
        labels = ner.align_token_labels(text, gold, offsets)
        decoded = decode_bio(text, offsets, labels, id2label=ner.ID2LABEL)
        for result in decoded:
            result.pop("confidence")
        self.assertEqual(decoded, gold)


class GoldBoundaryTests(unittest.TestCase):
    def test_balancing_uses_document_support_and_preserves_negatives(self):
        common = [{"entities": [{"category": "PHONE"}] * 2} for _ in range(4)]
        rows = common + [{"entities": [{"category": "LOCATION"}]}] + [{"entities": []}]
        weights, support = ner.balanced_sample_weights(rows, 0.5)
        self.assertEqual(support, {"LOCATION": 1, "PHONE": 4})
        self.assertEqual(weights, [1.0, 1.0, 1.0, 1.0, 2.0, 1.0])
        self.assertEqual(ner.balanced_sample_weights(rows, 0)[0], [1.0] * 6)
        self.assertEqual(len(rows[0]["entities"]), 2)

    def test_balancing_rejects_invalid_power(self):
        for power in (-0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(power=power), self.assertRaises(ValueError):
                ner.balanced_sample_weights([{"entities": []}], power)

    def test_full_29_label_schema(self):
        self.assertEqual(len(ner.CATEGORIES), 14)
        self.assertEqual(len(ner.BIO_LABELS), 29)
        self.assertEqual(ner.LABEL2ID["O"], 0)

    def test_source_overlap_and_actual_full_input_overlap_rejected(self):
        a, b = row("train", "训练材料"), row("validation", "验证材料")
        self.assertEqual(ner.check_separation([a], [b])["exact_text_overlap_count"], 0)
        b["source_case_id"] = a["source_case_id"]
        with self.assertRaisesRegex(ValueError, "source_case_id"):
            ner.check_separation([a], [b])
        b = row("validation", a["text"])
        with self.assertRaisesRegex(ValueError, "Identical full NER input"):
            ner.check_separation([a], [b])

    def test_generic_unlabelled_dialogue_repeat_is_explicitly_reported(self):
        a, b = row("train", "接着说", "dialogue"), row("validation", "接着说", "dialogue")
        report = ner.check_separation([a], [b])
        self.assertEqual(report["exact_text_overlap_count"], 1)
        self.assertTrue(report["exact_text_overlaps"][0]["generic_dialogue_repeat"])

    def test_load_rejects_test_before_opening_and_non_gold(self):
        with self.assertRaisesRegex(ValueError, "Only train/validation"):
            ner.load_gold(Path("does_not_exist.jsonl"), "test")
        with self.assertRaisesRegex(ValueError, "test-named"):
            ner.load_gold(Path("sealed_test.jsonl"), "validation")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.jsonl"
            for field, value in (("split", "test"), ("human_reviewed", False),
                                 ("label_origin", "weak"), ("source_case_id", "")):
                bad = row("train")
                bad[field] = value
                path.write_text(json.dumps(bad), encoding="utf-8")
                with self.subTest(field=field), self.assertRaises(ValueError):
                    ner.load_gold(path, "train")

    def test_strict_entity_score_penalizes_boundary_and_category_errors(self):
        text = "张三来"
        source = row("validation", text, entities=[entity(text, 0, 2)])
        wrong = entity(text, 0, 1)
        report, _, errors = ner.score_predictions([source], [[wrong]])
        self.assertEqual(report["micro"]["f1"], 0)
        self.assertEqual(report["micro"]["fp"], 1)
        self.assertEqual(report["micro"]["fn"], 1)
        self.assertEqual(len(errors), 1)
        report, _, _ = ner.score_predictions([source], [[entity(text, 0, 2)]])
        self.assertEqual(report["micro"]["f1"], 1)


if __name__ == "__main__":
    unittest.main()
