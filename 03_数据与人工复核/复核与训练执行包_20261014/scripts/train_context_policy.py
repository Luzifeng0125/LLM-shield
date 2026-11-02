"""Fixed, offline four-channel request/turn classifier trained on reviewed gold.

Keeps current text, earlier user text, task metadata, and trusted flags separate.
Three-fold grouped diagnostics use training data only. Validation is scored once
after parameters are fixed; test data and deployed application weights are unused.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train_gold_policy as base

ARTIFACT_TYPE = "yindun-gold-context-request-turn-action"
ARTIFACT_VERSION = 2
FEATURE_VERSION = 2
CHANNELS = ["current_text", "prior_user_texts", "task_metadata", "trusted_flags"]
CHANNEL_WEIGHTS = {"current_text": 2.0, "prior_user_texts": 0.5,
                   "task_metadata": 1.0, "trusted_flags": 0.5}
PARAMETERS = {"analyzer": "char", "ngram_range": [2, 4], "min_df": 1,
              "class_weight": "balanced", "C": 1.0, "max_iter": 2000,
              "random_state": 42, "channel_weights": CHANNEL_WEIGHTS}
LIMITATIONS = base.LIMITATIONS + [
    "Four input channels preserve current/history roles, but the linear classifier does not model arbitrary logical interactions or maintain a disclosure ledger.",
    "Training diagnostics group whole conversations and linked declared sources; source template independence is not established.",
    "This is one fixed follow-up candidate motivated by baseline validation errors. It is not a fresh blind evaluation or an LLM fine-tune.",
]


def channels_for(row, turn_index=None):
    """Strict source allowlist; no IDs, annotations, labels, or future turns."""
    payload = json.loads(base.feature_for(row, turn_index))
    task = "\n".join(f"{key}: {payload[key]}" for key in
                     ("task", "task_description", "identity", "recipient") if key in payload)
    flags = []
    for key, allowed in (("trusted_context", base.CONTEXT_KEYS), ("trusted_policy", base.POLICY_KEYS)):
        values = payload.get(key, {})
        # Missing is distinct from false. Unknown fields are never features.
        for name in sorted(allowed):
            state = str(values[name]).lower() if name in values else "missing"
            flags.append(f"{key}.{name}={state}")
    return [payload["text"], "prior_user_texts\n" + "\n\n".join(payload["prior_user_texts"]),
            task or "task_metadata_missing", " ".join(flags)]


def action_samples(rows):
    samples = base.action_samples(rows)
    row_by_id = {row["id"]: row for row in rows}
    for sample in samples:
        row = row_by_id[sample["source_unit_id"]]
        index = next((i for i, turn in enumerate(row.get("turns", []))
                      if turn["turn_id"] == sample["turn_id"]), None)
        sample["channels"] = channels_for(row, index)
    return samples


def features(samples):
    import numpy as np
    return np.asarray([sample["channels"] for sample in samples], dtype=object)


def build_pipeline():
    from sklearn.compose import ColumnTransformer
    from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import Normalizer
    transformers = [
        (name, TfidfVectorizer(analyzer="char", ngram_range=(2, 4), min_df=1), index)
        for index, name in enumerate(CHANNELS[:3])
    ]
    transformers.append(("trusted_flags", Pipeline([
        ("onehot", CountVectorizer(binary=True, token_pattern=r"[^ ]+", lowercase=False)),
        ("normalize", Normalizer()),
    ]), 3))
    return Pipeline([
        ("channels", ColumnTransformer(transformers, transformer_weights=CHANNEL_WEIGHTS,
                                       sparse_threshold=1.0, remainder="drop")),
        ("classifier", LogisticRegression(class_weight="balanced", C=1.0, max_iter=2000, random_state=42)),
    ])


def source_groups(rows, samples):
    """Unite units sharing any declared source ID before grouping their turns."""
    parent = {row["id"]: row["id"] for row in rows}
    def find(unit):
        while parent[unit] != unit:
            parent[unit] = parent[parent[unit]]
            unit = parent[unit]
        return unit
    seen = {}
    for row in rows:
        for key in base.SOURCE_ID_KEYS:
            if key not in row:
                continue
            source = str(row[key])
            if source in seen:
                parent[find(row["id"])] = find(seen[source])
            else:
                seen[source] = row["id"]
    return [find(sample["source_unit_id"]) for sample in samples]


def grouped_diagnostics(rows, samples):
    """One fixed model; these out-of-fold predictions do not select parameters."""
    import numpy as np
    from sklearn.model_selection import StratifiedGroupKFold
    x = features(samples)
    y = np.asarray([sample["preferred_action"] for sample in samples])
    groups = np.asarray(source_groups(rows, samples))
    group_counts = {label: len(set(groups[y == label])) for label in base.ACTIONS}
    folds = min(3, min(group_counts.values()))
    base.require(folds >= 2, "Grouped diagnostics require at least two independent source groups per action")
    splitter = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=42)
    predictions = [None] * len(samples)
    fold_details = []
    for fold_number, (fit_index, holdout_index) in enumerate(splitter.split(x, y, groups), 1):
        fit_groups, holdout_groups = set(groups[fit_index]), set(groups[holdout_index])
        base.require(not fit_groups & holdout_groups, "Group leakage in training diagnostics")
        pipeline = build_pipeline()
        pipeline.fit(x[fit_index], y[fit_index])
        labels = pipeline.predict(x[holdout_index])
        scores = pipeline.predict_proba(x[holdout_index])
        records = base.prediction_records([samples[i] for i in holdout_index], labels, scores, pipeline.classes_)
        for index, record in zip(holdout_index, records):
            record["diagnostic_fold"] = fold_number
            predictions[index] = record
        fold_metrics = base.evaluate_predictions(records)
        fold_metrics["evaluation_split"] = "train_group_holdout"
        fold_metrics["limitations"] = LIMITATIONS
        fold_details.append({"fold": fold_number, "train_samples": len(fit_index),
                             "holdout_samples": len(holdout_index), "group_overlap": 0,
                             "train_groups": sorted(fit_groups), "holdout_groups": sorted(holdout_groups),
                             "train_class_counts": dict(sorted(Counter(y[fit_index]).items())),
                             "holdout_class_counts": dict(sorted(Counter(y[holdout_index]).items())),
                             "metrics": fold_metrics})
    base.require(all(record is not None for record in predictions), "Incomplete grouped diagnostics")
    metrics = base.evaluate_predictions(predictions)
    metrics["evaluation_split"] = "train_group_out_of_fold"
    metrics["limitations"] = LIMITATIONS
    return {"method": "StratifiedGroupKFold", "n_splits": folds, "shuffle": True,
            "random_state": 42, "used_for_hyperparameter_selection": False,
            "grouping": "whole source unit plus shared declared source IDs",
            "class_source_group_counts": group_counts, "folds": fold_details,
            "aggregate": metrics}, predictions


def compare_baseline(path, train_meta, valid_meta, records, metrics):
    path = Path(path).resolve()
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    base.require(manifest["artifact_type"] == base.ARTIFACT_TYPE, "Unexpected baseline artifact type")
    for split, meta in (("train", train_meta), ("validation", valid_meta)):
        base.require(manifest[split]["sha256"] == meta["sha256"], "Baseline gold input hash differs")
    previous = [json.loads(line) for line in (path / "validation_predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    base.require({r["sample_id"] for r in previous} == {r["sample_id"] for r in records},
                 "Baseline sample IDs differ")
    by_id = {r["sample_id"]: r for r in previous}
    for record in records:
        base.require(by_id[record["sample_id"]]["preferred_action"] == record["preferred_action"],
                     "Baseline preferred targets differ")
    old_metrics = base.evaluate_predictions(previous)
    names = ("preferred_accuracy", "preferred_macro_f1", "acceptable_action_hit", "pause_false_allow_suggestion",
             "nonpause_false_pause_suggestion", "dialogue_all_preferred_actions_correct")
    return {"baseline_directory": str(path), "same_gold_sha256": True,
            "comparison_scope": "same development validation, action classification only",
            "baseline": {name: old_metrics[name] for name in names},
            "context_v2": {name: metrics[name] for name in names},
            "fixed_preferred_errors": [r["sample_id"] for r in records
                                       if not by_id[r["sample_id"]]["preferred_correct"] and r["preferred_correct"]],
            "introduced_preferred_errors": [r["sample_id"] for r in records
                                            if by_id[r["sample_id"]]["preferred_correct"] and not r["preferred_correct"]]}


def run(train_path, validation_path, output_path, baseline_path=None):
    import joblib
    import numpy as np
    import sklearn
    output = Path(output_path).resolve()
    base.require(not output.exists(), f"Output already exists; refusing overwrite: {output}")
    base.require(not output.is_relative_to(base.LIVE_MODELS.resolve()), "Output must be outside the app's live models directory")
    base.require(Path(train_path).resolve() != Path(validation_path).resolve(), "Train and validation files must differ")
    train, train_meta = base.load_gold(train_path, "train")
    train_samples = action_samples(train)
    diagnostics, diagnostic_records = grouped_diagnostics(train, train_samples)
    pipeline = build_pipeline()
    pipeline.fit(features(train_samples), [r["preferred_action"] for r in train_samples])

    # The validation file is first opened after the fixed candidate is fitted.
    validation, valid_meta = base.load_gold(validation_path, "validation")
    separation = base.check_separation(train, validation)
    valid_samples = action_samples(validation)
    class_counts = base.check_class_coverage(train_samples, valid_samples)
    base.require(not {base.stable_json(r["channels"]) for r in train_samples}
                 & {base.stable_json(r["channels"]) for r in valid_samples},
                 "Complete structured feature overlap across train/validation")
    valid_features = features(valid_samples)
    labels, scores = pipeline.predict(valid_features), pipeline.predict_proba(valid_features)
    records = base.prediction_records(valid_samples, labels, scores, pipeline.classes_)
    metrics = base.evaluate_predictions(records)
    metrics["limitations"] = LIMITATIONS
    comparison = compare_baseline(baseline_path, train_meta, valid_meta, records, metrics) if baseline_path else None
    artifact = {"artifact_type": ARTIFACT_TYPE, "artifact_version": ARTIFACT_VERSION,
                "feature_schema_version": FEATURE_VERSION, "feature_channels": CHANNELS,
                "pipeline": pipeline, "classes": list(pipeline.classes_),
                "source_sha256": {"train": train_meta["sha256"], "validation": valid_meta["sha256"]},
                "runtime_compatible": False, "unit_of_prediction": "whole_request_or_dialogue_turn",
                "limitations": LIMITATIONS}
    output.mkdir(parents=True, exist_ok=False)
    model_path = output / "context_request_turn_policy.joblib"
    joblib.dump(artifact, model_path)
    reloaded = joblib.load(model_path)
    base.require(reloaded["artifact_type"] == ARTIFACT_TYPE and reloaded["artifact_version"] == ARTIFACT_VERSION,
                 "Reloaded artifact metadata differs")
    base.require(np.array_equal(labels, reloaded["pipeline"].predict(valid_features))
                 and np.allclose(scores, reloaded["pipeline"].predict_proba(valid_features), rtol=0, atol=0),
                 "Reloaded predictions differ; output is incomplete")
    metrics["reload_verification"] = {"identical_labels_and_scores": True, "samples": len(valid_samples)}
    base._write_jsonl(output / "training_records.jsonl", train_samples)
    base._write_json(output / "train_group_diagnostics.json", diagnostics)
    base._write_jsonl(output / "train_group_predictions.jsonl", diagnostic_records)
    base._write_jsonl(output / "validation_predictions.jsonl", records)
    base._write_jsonl(output / "validation_errors.jsonl", [r for r in records if not r["preferred_correct"]])
    base._write_json(output / "metrics.json", metrics)
    if comparison:
        base._write_json(output / "baseline_comparison.json", comparison)
    manifest = {
        "status": "complete", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifact_type": ARTIFACT_TYPE, "artifact_version": ARTIFACT_VERSION,
        "feature_schema_version": FEATURE_VERSION, "gold_schema_version": "review-1.0",
        "runtime_compatible": False, "train": train_meta, "validation": valid_meta,
        "action_samples": {"train": len(train_samples), "validation": len(valid_samples)},
        "class_counts": class_counts, "separation_checks": separation, "parameters": PARAMETERS,
        "candidate_selection": "One fixed architecture and fixed parameters; train-group CV is diagnostic only",
        "validation_passes_for_candidate_selection": 0, "validation_reporting_passes": 1,
        "feature_channels": CHANNELS,
        "feature_fields": ["text", "task", "task_description", "identity", "recipient",
                           "trusted_context", "trusted_policy", "prior_user_texts"],
        "forbidden_feature_sources": ["annotation", "target", "gold history", "sanitized_text",
                                      "future turns", "review notes", "IDs", "split", "labels"],
        "versions": {"python": platform.python_version(), "sklearn": sklearn.__version__, "joblib": joblib.__version__},
        "code_sha256": base.sha256(Path(__file__).read_bytes()),
        "baseline_helpers_sha256": base.sha256(Path(base.__file__).read_bytes()),
        "validator_sha256": base.sha256(Path(base.review.__file__).read_bytes()),
        "reload_verification": metrics["reload_verification"], "test_read": False,
        "files": {p.name: base.sha256(p.read_bytes()) for p in output.iterdir() if p.is_file()},
        "limitations": LIMITATIONS,
    }
    base._write_json(output / "manifest.json", manifest)
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", required=True, type=Path)
    parser.add_argument("--validation", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--baseline", type=Path, help="Existing baseline directory, used only for final reporting")
    args = parser.parse_args()
    try:
        metrics = run(args.train, args.validation, args.out, args.baseline)
    except (OSError, ValueError, ImportError) as exc:
        parser.exit(2, f"Refused / failed: {exc}\n")
    fields = ("samples", "preferred_accuracy", "preferred_macro_f1", "acceptable_action_hit",
              "pause_false_allow_suggestion", "nonpause_false_pause_suggestion",
              "dialogue_all_preferred_actions_correct", "reload_verification")
    print(json.dumps({"out": str(args.out.resolve()), **{key: metrics[key] for key in fields}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
