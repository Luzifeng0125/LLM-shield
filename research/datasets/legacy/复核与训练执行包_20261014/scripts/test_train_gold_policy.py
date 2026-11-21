"""Software fixtures only: these are not human review or model-quality evidence."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train_gold_policy as policy


def target(action):
    return {"preferred_action": action, "acceptable_actions": [action],
            "send_allowed": action != "PAUSE", "sanitized_text": None if action == "PAUSE" else "ANSWER_ONLY_SENTINEL",
            "reason": "GOLD_REASON_SENTINEL"}


def base_record(unit_id, split, kind):
    return {
        "id": unit_id, "split": split, "kind": kind, "task": "meeting_minutes",
        "task_description": "请整理事项", "identity": "student_leader", "recipient": "external_model",
        "trusted_context": {"recipient_verified": True},
        "human_reviewed": True, "label_origin": "human_dual_review_adjudicated",
        "gold_schema_version": "review-1.0", "annotation_guideline_version": "1.0",
        "adjudicator": "SOFTWARE_FIXTURE", "adjudicated_date": "2026-10-16",
        "adjudication_reason": "FIXTURE_NOT_REAL_REVIEW", "source_kind": "software_fixture",
        "review_sha256": {"A": "a" * 64, "B": "b" * 64},
    }


def fixture_rows(split):
    rows = []
    for index, action in enumerate(policy.ACTIONS):
        row = base_record(f"{split}-policy-{index}", split, "policy")
        row.update(text=f"{split} 来源 {index} 事项内容", annotation={"entities": [], "target": target(action)})
        rows.append(row)
    dialogue = base_record(f"{split}-dialogue-1", split, "dialogue")
    dialogue["trusted_policy"] = {"pause_on_ambiguous_reference": True}
    dialogue["turns"] = [{"turn_id": i + 1, "text": f"{split} 会话第{i + 1}轮原文"} for i in range(3)]
    dialogue["annotation"] = {"turns": [
        {"turn_id": i + 1, "entities": [], "target": target(action)}
        for i, action in enumerate(["PSEUDONYMIZE", "PAUSE", "PSEUDONYMIZE"])]}
    rows.append(dialogue)
    ner = base_record(f"{split}-ner", split, "ner")
    ner.update(text=f"{split} 实体材料", annotation={"entities": []})
    rows.append(ner)
    return rows


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


class GoldPolicyTests(unittest.TestCase):
    def test_allowlist_is_invariant_to_all_gold_and_future_answers(self):
        row = fixture_rows("train")[-2]
        before = policy.feature_for(row, 1)
        changed = copy.deepcopy(row)
        changed["annotation"] = {"turns": "EVERY_GOLD_FIELD_REPLACED"}
        changed["target"] = "TOP_LEVEL_ANSWER_SENTINEL"
        changed["notes"] = "NOTES_SENTINEL"
        changed["id"] = "ID_SENTINEL"
        changed["split"] = "test"
        changed["turns"][2]["text"] = "FUTURE_TEXT_SENTINEL"
        self.assertEqual(before, policy.feature_for(changed, 1))
        self.assertIn(row["turns"][0]["text"], before)
        self.assertNotIn(row["turns"][2]["text"], before)
        self.assertNotIn("ANSWER_ONLY_SENTINEL", before)
        changed["turns"][0]["text"] = "CHANGED_PRIOR_USER_TEXT"
        self.assertNotEqual(before, policy.feature_for(changed, 1))

    def test_expansion_preserves_dialogue_and_skips_ner(self):
        samples = policy.action_samples(fixture_rows("train"))
        self.assertEqual(9, len(samples))
        turns = [s for s in samples if s["kind"] == "dialogue"]
        self.assertEqual([1, 2, 3], [s["turn_id"] for s in turns])
        self.assertEqual(1, len({s["source_unit_id"] for s in turns}))
        self.assertTrue(all(s["split"] == "train" for s in samples))

    def test_rejects_test_mixed_split_bad_signature_and_context_answers(self):
        with tempfile.TemporaryDirectory(prefix="policy_fixture_") as temporary:
            path = Path(temporary) / "gold.jsonl"
            for field, value in [("split", "test"), ("human_reviewed", False),
                                 ("adjudicator", ""), ("review_sha256", {"A": "bad", "B": "b" * 64}),
                                 ("trusted_context", {"preferred_action": "PAUSE"})]:
                with self.subTest(field=field):
                    rows = fixture_rows("train")
                    rows[0][field] = value
                    write_rows(path, rows)
                    with self.assertRaises(ValueError):
                        policy.load_gold(path, "train")
            with self.assertRaises(ValueError):
                policy.load_gold(path, "test")

    def test_rejects_duplicates_incomplete_dialogue_and_inconsistent_target(self):
        with tempfile.TemporaryDirectory(prefix="policy_fixture_") as temporary:
            path = Path(temporary) / "gold.jsonl"
            versions = []
            rows = fixture_rows("train")
            versions.append(rows + [copy.deepcopy(rows[0])])
            rows = fixture_rows("train")
            rows[-2]["annotation"]["turns"].pop()
            versions.append(rows)
            rows = fixture_rows("train")
            rows[policy.ACTIONS.index("PAUSE")]["annotation"]["target"]["send_allowed"] = True
            versions.append(rows)
            for rows in versions:
                write_rows(path, rows)
                with self.assertRaises(ValueError):
                    policy.load_gold(path, "train")

    def test_cross_split_id_text_and_dialogue_source_guards(self):
        train, validation = fixture_rows("train"), fixture_rows("validation")
        self.assertEqual(0, policy.check_separation(train, validation)["id_overlap"])
        variants = []
        changed = copy.deepcopy(validation)
        changed[0]["id"] = train[0]["id"]
        variants.append(changed)
        changed = copy.deepcopy(validation)
        changed[-1]["text"] = "  " + train[0]["text"].replace(" ", "\t") + "  "
        variants.append(changed)
        changed = copy.deepcopy(validation)
        changed[-2]["turns"] = copy.deepcopy(train[-2]["turns"])
        variants.append(changed)
        for changed in variants:
            with self.assertRaises(ValueError):
                policy.check_separation(train, changed)
        train[0]["source_document_id"] = "shared-source"
        validation[1]["document_id"] = "shared-source"
        with self.assertRaises(ValueError):
            policy.check_separation(train, validation)

    def test_shared_dialogue_turn_allowed_only_with_distinct_complete_input(self):
        train, validation = fixture_rows("train"), fixture_rows("validation")
        validation[-2]["turns"][1]["text"] = train[-2]["turns"][1]["text"]
        result = policy.check_separation(train, validation)
        self.assertEqual(1, result["isolated_dialogue_turn_text_overlap"])
        self.assertEqual(0, result["complete_expanded_input_feature_overlap"])
        # Matching first two user turns makes the second model input identical,
        # even if the complete three-turn dialogue still differs.
        validation[-2]["turns"][0]["text"] = train[-2]["turns"][0]["text"]
        with self.assertRaisesRegex(ValueError, "complete expanded input feature"):
            policy.check_separation(train, validation)

    def test_class_coverage_requires_all_actions_in_each_split(self):
        train = policy.action_samples(fixture_rows("train"))
        validation = policy.action_samples(fixture_rows("validation"))
        policy.check_class_coverage(train, validation)
        for missing_train in (True, False):
            filtered = [s for s in (train if missing_train else validation) if s["preferred_action"] != "RETAIN"]
            with self.assertRaises(ValueError):
                policy.check_class_coverage(filtered if missing_train else train,
                                            validation if missing_train else filtered)

    def test_metrics_distinguish_acceptable_action_pause_and_dialogue_action_only(self):
        samples = policy.action_samples(fixture_rows("validation"))
        predicted = [s["preferred_action"] for s in samples]
        delete_index = next(i for i, s in enumerate(samples) if s["preferred_action"] == "DELETE")
        samples[delete_index]["acceptable_actions"].append("GENERALIZE")
        predicted[delete_index] = "GENERALIZE"
        dialogue_pause = next(i for i, s in enumerate(samples) if s["kind"] == "dialogue" and s["preferred_action"] == "PAUSE")
        predicted[dialogue_pause] = "RETAIN"
        records = policy.prediction_records(samples, predicted, [[1 / 6] * 6 for _ in samples], policy.ACTIONS)
        result = policy.evaluate_predictions(records)
        self.assertEqual(7, result["preferred_accuracy"]["numerator"])
        self.assertEqual(8, result["acceptable_action_hit"]["numerator"])
        self.assertEqual({"numerator": 1, "denominator": 2, "rate": 0.5}, result["pause_false_allow_suggestion"])
        self.assertEqual(0, result["dialogue_all_preferred_actions_correct"]["numerator"])
        self.assertEqual(1, result["dialogue_all_preferred_actions_correct"]["denominator"])
        self.assertIn("not an outbound-safety", result["metrics_scope"])

    def test_full_fixture_fit_reload_no_test_read_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="policy_fixture_") as temporary:
            root = Path(temporary)
            train, validation, output = root / "train.jsonl", root / "validation.jsonl", root / "candidate"
            write_rows(train, fixture_rows("train"))
            write_rows(validation, fixture_rows("validation"))
            (root / "test_gold.jsonl").write_bytes(b"THIS FILE MUST NEVER BE READ OR PARSED\xff")
            metrics = policy.run(train, validation, output)
            self.assertEqual({"identical_labels_and_scores": True, "samples": 9}, metrics["reload_verification"])
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(policy.ARTIFACT_TYPE, manifest["artifact_type"])
            self.assertFalse(manifest["runtime_compatible"])
            self.assertFalse(manifest["test_read"])
            self.assertEqual({"train": 9, "validation": 9}, manifest["action_samples"])
            self.assertEqual(policy.sha256(train.read_bytes()), manifest["train"]["sha256"])
            self.assertEqual(9, len((output / "validation_predictions.jsonl").read_text(encoding="utf-8").splitlines()))
            original = (output / "manifest.json").read_bytes()
            with self.assertRaisesRegex(ValueError, "already exists"):
                policy.run(train, validation, output)
            self.assertEqual(original, (output / "manifest.json").read_bytes())
            with self.assertRaisesRegex(ValueError, "live models"):
                policy.run(train, validation, policy.LIVE_MODELS / "fixture_disallowed_output")


if __name__ == "__main__":
    unittest.main()
