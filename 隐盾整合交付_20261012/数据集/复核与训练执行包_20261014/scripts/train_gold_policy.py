"""Offline whole-request / dialogue-turn action baseline from adjudicated gold.

This is a TF-IDF + logistic-regression experiment, NOT the app's segment policy
model and NOT a small language model. It never reads a test split, generates
outbound text, or installs weights in the running app.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
import unicodedata

# Support the project's isolated Windows Python runtime as a standalone CLI.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_workflow as review


ROOT = Path(__file__).resolve().parents[1]
LIVE_MODELS = ROOT.parents[1] / "app" / "models"
ARTIFACT_TYPE = "yindun-gold-whole-request-turn-action-baseline"
ARTIFACT_VERSION = 1
FEATURE_VERSION = 1
ACTIONS = sorted(review.ACTIONS)
CONTEXT_KEYS = {"exact_location_public", "recipient_verified"}
POLICY_KEYS = {
    "allow_identity_restoration_to_cloud", "avoid_unique_award_linkage",
    "keep_alias_consistent", "pause_on_ambiguous_reference",
}
SOURCE_ID_KEYS = (
    "source_id", "source_case_id", "source_document_id", "document_id",
    "conversation_id", "dialogue_id", "group_id",
)
LIMITATIONS = [
    "Whole-request / dialogue-turn TF-IDF + logistic regression, not the deployed segment action model or an LLM.",
    "Only preferred/acceptable action classification is evaluated; no entity detection, sanitized text generation, outbound safety, or end-to-end success is measured.",
    "A non-PAUSE prediction is only a classifier suggestion, never permission to send data.",
    "Dialogue inputs contain earlier user text only, not actual outbound history, gold prior actions, aliases, or sanitized answers.",
    "Synthetic source text remains synthetic after human review; small validation counts do not establish production safety.",
    "Task descriptions and trusted policy flags may strongly cue labels; template/source diversity limits generalization.",
    "Exact IDs, declared source IDs, whole non-dialogue texts, whole dialogues, and complete input features are checked across splits; missing source provenance prevents proving semantic/template independence.",
    "Repeated isolated dialogue turns are reported, not treated as identical samples when their complete prior user context or trusted context differs.",
    "Validation is used for this fixed candidate's reporting; no test data is read. Repeated candidate selection makes validation a development set.",
    "Gold signatures and review hashes are structural provenance checks, not proof that a human actually reviewed each record.",
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def stable_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def normalized_text(text):
    return " ".join(unicodedata.normalize("NFKC", text).split())


def source_texts(row):
    return [turn["text"] for turn in row["turns"]] if row["kind"] == "dialogue" else [row["text"]]


def _validate_context(row):
    for name in ("task", "task_description", "identity", "recipient"):
        if name in row:
            require(isinstance(row[name], str), f"{row['id']}: {name} must be a string")
    for name, allowed in (("trusted_context", CONTEXT_KEYS), ("trusted_policy", POLICY_KEYS)):
        if name in row:
            context = row[name]
            require(isinstance(context, dict), f"{row['id']}: {name} must be an object")
            require(set(context) <= allowed,
                    f"{row['id']}: unsupported {name} keys; review and version the input allowlist")
            require(all(type(value) is bool for value in context.values()),
                    f"{row['id']}: trusted context values must be booleans")


def load_gold(path, expected_split):
    """Load one explicit train/validation file; never discover sibling files."""
    require(expected_split in {"train", "validation"}, "Only train and validation are supported")
    path = Path(path).resolve()
    raw = path.read_bytes()
    rows = []
    for number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            require(isinstance(row, dict), "row must be an object")
            require(isinstance(row.get("id"), str) and row["id"].strip(), "missing ID")
            require(row.get("split") == expected_split,
                    f"split must be {expected_split}; test and mixed splits are forbidden")
            require(row.get("kind") in {"ner", "policy", "dialogue"}, "unknown kind")
            require(row.get("gold_schema_version") == "review-1.0", "unsupported gold schema")
            require(isinstance(row.get("annotation_guideline_version"), str)
                    and row["annotation_guideline_version"].strip(), "missing guideline version")
            require(row.get("human_reviewed") is True and
                    row.get("label_origin") == "human_dual_review_adjudicated", "not adjudicated gold")
            for name in ("adjudicator", "adjudicated_date", "adjudication_reason", "source_kind"):
                require(isinstance(row.get(name), str) and row[name].strip(), f"missing {name}")
            hashes = row.get("review_sha256")
            require(isinstance(hashes, dict) and set(hashes) == {"A", "B"}
                    and all(isinstance(v, str) and re.fullmatch(r"[0-9a-fA-F]{64}", v) for v in hashes.values()),
                    "missing or invalid A/B review hashes")
            if row["kind"] == "dialogue":
                require(isinstance(row.get("turns"), list) and row["turns"], "empty dialogue")
                turn_ids = [turn.get("turn_id") for turn in row["turns"]]
                require(all(type(t) is int and t > 0 for t in turn_ids)
                        and turn_ids == sorted(set(turn_ids)), "turn IDs must be positive, unique, and ordered")
            require(all(isinstance(text, str) and normalized_text(text) for text in source_texts(row)),
                    "source text must be nonempty")
            _validate_context(row)
            review.validate_annotation(row, row["annotation"])
            rows.append(row)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f"{path.name}:{number}: {exc}") from exc
    require(rows, f"{path.name}: empty gold file")
    require(len({r['id'] for r in rows}) == len(rows), f"{path.name}: duplicate IDs")
    versions = {r["annotation_guideline_version"] for r in rows}
    require(len(versions) == 1, f"{path.name}: mixed guideline versions")
    metadata = {
        "path": str(path), "sha256": sha256(raw), "bytes": len(raw),
        "split": expected_split, "gold_units": len(rows),
        "units_by_kind": dict(sorted(Counter(r["kind"] for r in rows).items())),
        "guideline_version": next(iter(versions)),
        "source_kinds": dict(sorted(Counter(r["source_kind"] for r in rows).items())),
    }
    return rows, metadata


def check_separation(train, validation):
    require({r["annotation_guideline_version"] for r in train}
            == {r["annotation_guideline_version"] for r in validation}, "guideline versions differ between splits")
    train_ids = {r["id"] for r in train}
    valid_ids = {r["id"] for r in validation}
    require(not train_ids & valid_ids, "ID overlap across train/validation")
    def declared_ids(rows):
        result = set()
        for row in rows:
            for key in SOURCE_ID_KEYS:
                if key in row:
                    require(isinstance(row[key], (str, int)) and not isinstance(row[key], bool)
                            and str(row[key]).strip(), f"{row['id']}: invalid {key}")
                    result.add(str(row[key]))
        return result
    train_sources, valid_sources = declared_ids(train), declared_ids(validation)
    require(not train_sources & valid_sources, "declared source/document/conversation ID overlap across splits")
    train_texts = {normalized_text(r["text"]) for r in train if r["kind"] != "dialogue"}
    valid_texts = {normalized_text(r["text"]) for r in validation if r["kind"] != "dialogue"}
    require(not train_texts & valid_texts, "whole non-dialogue source text overlap across train/validation")
    def dialogue_hashes(rows):
        return {sha256(stable_json([normalized_text(t) for t in source_texts(r)]).encode("utf-8"))
                for r in rows if r["kind"] == "dialogue"}
    require(not dialogue_hashes(train) & dialogue_hashes(validation), "whole dialogue overlap across splits")
    def input_features(rows):
        return {sample["feature"] for sample in action_samples(rows)}
    require(not input_features(train) & input_features(validation), "complete expanded input feature overlap across splits")
    train_turns = {normalized_text(t) for r in train if r["kind"] == "dialogue" for t in source_texts(r)}
    valid_turns = {normalized_text(t) for r in validation if r["kind"] == "dialogue" for t in source_texts(r)}
    return {
        "id_overlap": 0, "declared_source_id_overlap": 0,
        "whole_non_dialogue_text_overlap": 0, "whole_dialogue_overlap": 0,
        "complete_expanded_input_feature_overlap": 0,
        "isolated_dialogue_turn_text_overlap": len(train_turns & valid_turns),
        "declared_source_ids": {"train": len(train_sources), "validation": len(valid_sources)},
        "method": "NFKC + collapsed whitespace for whole-text/dialogue comparison; complete input feature exact comparison; isolated turn overlap reported; no random turn split",
        "semantic_or_template_independence_proven": False,
    }


def feature_for(row, turn_index=None):
    """Strict allowlist: never inspect any annotation, target, ID, or split."""
    payload = {
        key: row[key] for key in ("task", "task_description", "identity", "recipient") if key in row
    }
    for key in ("trusted_context", "trusted_policy"):
        if key in row:
            payload[key] = dict(row[key])
    if turn_index is None:
        payload["text"] = row["text"]
        payload["prior_user_texts"] = []
    else:
        payload["text"] = row["turns"][turn_index]["text"]
        payload["prior_user_texts"] = [t["text"] for t in row["turns"][:turn_index]]
    return stable_json(payload)


def action_samples(rows):
    result = []
    for row in rows:
        if row["kind"] == "ner":
            continue
        targets = row["annotation"]["turns"] if row["kind"] == "dialogue" else [row["annotation"]]
        for index, annotation in enumerate(targets):
            is_dialogue = row["kind"] == "dialogue"
            turn_id = row["turns"][index]["turn_id"] if is_dialogue else None
            target = annotation["target"]
            result.append({
                "sample_id": f"{row['id']}#turn-{turn_id}" if is_dialogue else row["id"],
                "source_unit_id": row["id"], "kind": row["kind"], "split": row["split"],
                "turn_id": turn_id, "feature": feature_for(row, index if is_dialogue else None),
                "preferred_action": target["preferred_action"],
                "acceptable_actions": list(target["acceptable_actions"]),
            })
    require(result, "No action gold units")
    require(len({r['sample_id'] for r in result}) == len(result), "Expanded sample ID collision")
    return result


def check_class_coverage(train_samples, validation_samples):
    counts = {}
    for name, samples in (("train", train_samples), ("validation", validation_samples)):
        labels = Counter(s["preferred_action"] for s in samples)
        require(set(labels) == set(ACTIONS), f"{name} lacks action classes: {sorted(set(ACTIONS) - set(labels))}")
        counts[name] = dict(sorted(labels.items()))
    return counts


def prediction_records(samples, predictions, probabilities, classes):
    records = []
    for sample, predicted, probs in zip(samples, predictions, probabilities):
        records.append({
            **sample, "predicted_action": str(predicted),
            "preferred_correct": predicted == sample["preferred_action"],
            "acceptable_hit": predicted in sample["acceptable_actions"],
            "pause_false_allow_suggestion": sample["preferred_action"] == "PAUSE" and predicted != "PAUSE",
            "class_scores_uncalibrated": {str(c): float(p) for c, p in zip(classes, probs)},
        })
    return records


def fraction(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else None}


def evaluate_predictions(records):
    from sklearn.metrics import classification_report, confusion_matrix, f1_score
    truth = [r["preferred_action"] for r in records]
    predicted = [r["predicted_action"] for r in records]
    dialogue_ids = sorted({r["source_unit_id"] for r in records if r["kind"] == "dialogue"})
    dialogue_results = []
    for unit_id in dialogue_ids:
        turns = [r for r in records if r["source_unit_id"] == unit_id]
        dialogue_results.append({
            "source_unit_id": unit_id, "turns": len(turns),
            "all_preferred_actions_correct": all(r["preferred_correct"] for r in turns),
            "all_actions_acceptable": all(r["acceptable_hit"] for r in turns),
        })
    result = {
        "evaluation_split": "validation", "samples": len(records),
        "preferred_accuracy": fraction(sum(r["preferred_correct"] for r in records), len(records)),
        "preferred_macro_f1": float(f1_score(truth, predicted, labels=ACTIONS, average="macro", zero_division=0)),
        "acceptable_action_hit": fraction(sum(r["acceptable_hit"] for r in records), len(records)),
        "pause_false_allow_suggestion": fraction(
            sum(r["pause_false_allow_suggestion"] for r in records), sum(label == "PAUSE" for label in truth)),
        "nonpause_false_pause_suggestion": fraction(
            sum(r["preferred_action"] != "PAUSE" and r["predicted_action"] == "PAUSE" for r in records),
            sum(label != "PAUSE" for label in truth)),
        "dialogue_all_preferred_actions_correct": fraction(
            sum(r["all_preferred_actions_correct"] for r in dialogue_results), len(dialogue_results)),
        "dialogue_all_actions_acceptable": fraction(
            sum(r["all_actions_acceptable"] for r in dialogue_results), len(dialogue_results)),
        "dialogue_results": dialogue_results,
        "classification_report": classification_report(truth, predicted, labels=ACTIONS, output_dict=True, zero_division=0),
        "confusion_matrix": {"labels": ACTIONS, "rows": "gold", "columns": "prediction",
                             "counts": confusion_matrix(truth, predicted, labels=ACTIONS).tolist()},
        "metrics_scope": "Action labels only; a dialogue action pass is not an outbound-safety or end-to-end dialogue pass.",
        "test_read": False, "limitations": LIMITATIONS,
    }
    return result


def _write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _write_jsonl(path, rows):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(stable_json(row) + "\n")


def run(train_path, validation_path, output_path):
    output = Path(output_path).resolve()
    require(not output.exists(), f"Output already exists; refusing overwrite: {output}")
    require(not output.is_relative_to(LIVE_MODELS.resolve()), "Output must be outside the app's live models directory")
    require(Path(train_path).resolve() != Path(validation_path).resolve(), "Train and validation files must differ")
    train, train_meta = load_gold(train_path, "train")
    validation, valid_meta = load_gold(validation_path, "validation")
    separation = check_separation(train, validation)
    train_samples, valid_samples = action_samples(train), action_samples(validation)
    class_counts = check_class_coverage(train_samples, valid_samples)

    import joblib
    import numpy as np
    import sklearn
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    parameters = {"analyzer": "char", "ngram_range": [2, 4], "min_df": 1,
                  "class_weight": "balanced", "C": 1.0, "max_iter": 2000, "random_state": 42}
    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char", ngram_range=(2, 4), min_df=1)),
        ("classifier", LogisticRegression(class_weight="balanced", C=1.0, max_iter=2000, random_state=42)),
    ])
    pipeline.fit([s["feature"] for s in train_samples], [s["preferred_action"] for s in train_samples])
    valid_features = [s["feature"] for s in valid_samples]
    predictions = pipeline.predict(valid_features)
    probabilities = pipeline.predict_proba(valid_features)
    records = prediction_records(valid_samples, predictions, probabilities, pipeline.classes_)
    metrics = evaluate_predictions(records)
    artifact = {
        "artifact_type": ARTIFACT_TYPE, "artifact_version": ARTIFACT_VERSION,
        "feature_schema_version": FEATURE_VERSION, "classes": list(pipeline.classes_),
        "pipeline": pipeline, "source_sha256": {"train": train_meta["sha256"], "validation": valid_meta["sha256"]},
        "runtime_compatible": False, "unit_of_prediction": "whole_request_or_dialogue_turn", "limitations": LIMITATIONS,
    }
    output.mkdir(parents=True, exist_ok=False)
    joblib.dump(artifact, output / "request_turn_policy_experiment.joblib")
    reloaded = joblib.load(output / "request_turn_policy_experiment.joblib")
    require(reloaded["artifact_type"] == ARTIFACT_TYPE and reloaded["artifact_version"] == ARTIFACT_VERSION,
            "Reloaded artifact metadata differs")
    require(np.array_equal(predictions, reloaded["pipeline"].predict(valid_features))
            and np.allclose(probabilities, reloaded["pipeline"].predict_proba(valid_features), rtol=0, atol=0),
            "Reloaded predictions differ; output is incomplete")
    metrics["reload_verification"] = {"identical_labels_and_scores": True, "samples": len(valid_samples)}
    _write_jsonl(output / "training_records.jsonl", train_samples)
    _write_jsonl(output / "validation_predictions.jsonl", records)
    _write_jsonl(output / "validation_errors.jsonl", [r for r in records if not r["preferred_correct"]])
    _write_json(output / "metrics.json", metrics)
    manifest = {
        "status": "complete", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifact_type": ARTIFACT_TYPE, "artifact_version": ARTIFACT_VERSION,
        "feature_schema_version": FEATURE_VERSION, "gold_schema_version": "review-1.0",
        "runtime_compatible": False, "train": train_meta, "validation": valid_meta,
        "action_samples": {"train": len(train_samples), "validation": len(valid_samples)},
        "class_counts": class_counts, "separation_checks": separation, "parameters": parameters,
        "versions": {"python": platform.python_version(), "sklearn": sklearn.__version__, "joblib": joblib.__version__},
        "code_sha256": sha256(Path(__file__).read_bytes()),
        "validator_sha256": sha256(Path(review.__file__).read_bytes()),
        "reload_verification": metrics["reload_verification"], "test_read": False,
        "feature_fields": ["text", "task", "task_description", "identity", "recipient",
                           "trusted_context", "trusted_policy", "prior_user_texts"],
        "forbidden_feature_sources": ["annotation", "target", "gold history", "sanitized_text",
                                      "future turns", "review notes", "IDs", "split", "labels"],
        "files": {p.name: sha256(p.read_bytes()) for p in output.iterdir() if p.is_file()},
        "limitations": LIMITATIONS,
    }
    _write_json(output / "manifest.json", manifest)
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", required=True, type=Path)
    parser.add_argument("--validation", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="New experiment directory outside app/models; existing paths are refused")
    args = parser.parse_args()
    try:
        metrics = run(args.train, args.validation, args.out)
    except (OSError, ValueError, ImportError) as exc:
        parser.exit(2, f"Refused / failed: {exc}\n")
    print(json.dumps({"out": str(args.out.resolve()), "action_samples": metrics["samples"],
                      "preferred_accuracy": metrics["preferred_accuracy"],
                      "preferred_macro_f1": metrics["preferred_macro_f1"],
                      "acceptable_action_hit": metrics["acceptable_action_hit"],
                      "pause_false_allow_suggestion": metrics["pause_false_allow_suggestion"],
                      "dialogue_all_preferred_actions_correct": metrics["dialogue_all_preferred_actions_correct"],
                      "scope": metrics["metrics_scope"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
