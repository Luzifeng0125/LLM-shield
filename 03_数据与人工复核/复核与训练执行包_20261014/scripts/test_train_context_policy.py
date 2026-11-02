"""Software fixtures; no added labels or claims about model generalization."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train_context_policy as context
from test_train_gold_policy import fixture_rows, write_rows


def grouped_fixtures(split):
    result = []
    for number in range(3):
        for row in fixture_rows(split):
            row["id"] += f"-replica-{number}"
            if row["kind"] == "dialogue":
                for turn in row["turns"]:
                    turn["text"] += f" source {number}"
            else:
                row["text"] += f" source {number}"
            result.append(row)
    return result


class ContextPolicyTests(unittest.TestCase):
    def test_allowlist_ignores_targets_ids_future_and_unknown_flags(self):
        row = fixture_rows("train")[-2]
        before = context.channels_for(row, 1)
        altered = copy.deepcopy(row)
        altered.update(annotation={"turns": "ANSWER"}, target="ANSWER", id="ANSWER",
                       split="test", notes="ANSWER", weak_label="ANSWER")
        altered["turns"][2]["text"] = "FUTURE_ANSWER"
        altered["trusted_policy"]["preferred_action"] = "ANSWER"
        self.assertEqual(before, context.channels_for(altered, 1))
        self.assertNotIn("ANSWER", " ".join(before))

    def test_history_and_current_text_stay_in_separate_channels(self):
        row = fixture_rows("train")[-2]
        before = context.channels_for(row, 1)
        self.assertIn(row["turns"][0]["text"], before[1])
        self.assertNotIn(row["turns"][0]["text"], before[0])
        altered = copy.deepcopy(row)
        altered["turns"][0]["text"] = "OTHER_HISTORY"
        after = context.channels_for(altered, 1)
        self.assertEqual([before[i] for i in (0, 2, 3)], [after[i] for i in (0, 2, 3)])
        self.assertNotEqual(before[1], after[1])
        altered = copy.deepcopy(row)
        altered["turns"][1]["text"] = "OTHER_CURRENT"
        after = context.channels_for(altered, 1)
        self.assertEqual(before[1:], after[1:])
        self.assertNotEqual(before[0], after[0])

    def test_missing_flag_and_explicit_false_are_distinct(self):
        row = fixture_rows("train")[-2]
        before = context.channels_for(row, 1)
        row["trusted_policy"]["allow_identity_restoration_to_cloud"] = False
        after = context.channels_for(row, 1)
        self.assertEqual(before[:3], after[:3])
        self.assertIn("trusted_policy.allow_identity_restoration_to_cloud=missing", before[3])
        self.assertIn("trusted_policy.allow_identity_restoration_to_cloud=false", after[3])

    def test_grouping_keeps_whole_dialogues_and_transitive_sources_together(self):
        rows = fixture_rows("train")
        rows[0]["source_id"] = "shared-a"
        rows[1]["document_id"] = "shared-a"
        rows[1]["conversation_id"] = "shared-b"
        rows[-2]["source_document_id"] = "shared-b"
        samples = context.action_samples(rows)
        grouped = dict(zip([r["sample_id"] for r in samples], context.source_groups(rows, samples)))
        same = [sample for sample in samples
                if sample["source_unit_id"] in {rows[0]["id"], rows[1]["id"], rows[-2]["id"]}]
        self.assertEqual(5, len(same))
        self.assertEqual(1, len({grouped[sample["sample_id"]] for sample in same}))

    def test_fit_group_diagnostics_reload_and_no_test_read(self):
        with tempfile.TemporaryDirectory(prefix="context_policy_fixture_") as temporary:
            root = Path(temporary)
            train, validation, output = root / "train.jsonl", root / "validation.jsonl", root / "candidate"
            write_rows(train, grouped_fixtures("train"))
            write_rows(validation, grouped_fixtures("validation"))
            (root / "test_gold.jsonl").write_bytes(b"MUST_NOT_BE_READ\xff")
            metrics = context.run(train, validation, output)
            self.assertEqual({"identical_labels_and_scores": True, "samples": 27}, metrics["reload_verification"])
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(context.ARTIFACT_TYPE, manifest["artifact_type"])
            self.assertFalse(manifest["runtime_compatible"])
            self.assertFalse(manifest["test_read"])
            self.assertEqual(0, manifest["validation_passes_for_candidate_selection"])
            self.assertEqual(context.CHANNEL_WEIGHTS, manifest["parameters"]["channel_weights"])
            diagnostics = json.loads((output / "train_group_diagnostics.json").read_text(encoding="utf-8"))
            self.assertFalse(diagnostics["used_for_hyperparameter_selection"])
            self.assertEqual("train_group_out_of_fold", diagnostics["aggregate"]["evaluation_split"])
            for fold in diagnostics["folds"]:
                self.assertFalse(set(fold["train_groups"]) & set(fold["holdout_groups"]))
            records = [json.loads(line) for line in (output / "train_group_predictions.jsonl").read_text(encoding="utf-8").splitlines()]
            for unit_id in {r["source_unit_id"] for r in records}:
                self.assertEqual(1, len({r["diagnostic_fold"] for r in records if r["source_unit_id"] == unit_id}))
            for name, digest in manifest["files"].items():
                self.assertEqual(digest, context.base.sha256((output / name).read_bytes()))
            with self.assertRaisesRegex(ValueError, "already exists"):
                context.run(train, validation, output)
            with self.assertRaisesRegex(ValueError, "live models"):
                context.run(train, validation, context.base.LIVE_MODELS / "fixture_context_disallowed")


if __name__ == "__main__":
    unittest.main()
