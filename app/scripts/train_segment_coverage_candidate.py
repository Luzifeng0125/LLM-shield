"""Repair weak-training coverage with isolated fields; never relabel human gold."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from llm_shield.config import recipients, tasks
from llm_shield.m2_detect.entity_rules import EntityDetector
from llm_shield.m2_detect.pipeline import detect_all
from llm_shield.m2_detect.regex_rules import RegexDetector
from llm_shield.m4_necessity.model import MODEL_PATH, NecessityModel, build_feature_text
from llm_shield.m4_necessity.train import GEN_DIR, load_synthetic, synthetic_label
from llm_shield.schema import Segment, Span

FIELD_NAMES = {
    "PERSON_NAME": "姓名", "PHONE": "联系电话", "EMAIL": "邮箱", "WECHAT": "微信号",
    "STUDENT_ID": "学号", "DORM": "宿舍地址", "ID_CARD": "身份证号", "BANK_CARD": "银行卡号",
    "BUDGET": "金额", "GRADE": "成绩", "SENSITIVE_ATTR": "个人敏感情况", "API_KEY": "凭据",
    "ORG": "组织名称", "LOCATION": "活动地点",
}


def isolated_segments(case, spans):
    """At most one value per category/source; variants retain the source group."""
    selected = {}
    for span in spans:
        selected.setdefault(span.category, span)
    for category, span in sorted(selected.items()):
        for variant, prefix in enumerate((FIELD_NAMES[category] + "：", "本条登记的" + FIELD_NAMES[category] + "为")):
            text = prefix + span.text + "。"
            entity = Span(len(prefix), len(prefix) + len(span.text), span.text, category,
                          span.confidence, "synthetic_isolated_field")
            # One view contains nearby mixed fields; another only the current
            # field. Neither adds future turns or an annotation to model input.
            context = case["text"][:160] + "\n" + text if variant else text
            yield Segment(f"isolated_{category}_{variant}", text, 0, len(text), [entity], context=context)


def build_samples(cases):
    detectors = [RegexDetector(), EntityDetector()]
    baseline = load_synthetic(detectors=detectors)
    augmented = []
    for case in cases:
        spans = detect_all(case["text"], case.get("columns"), case.get("rows"), detectors=detectors)
        task_key = case["task"]
        identity = case.get("identity", "student_leader")
        description = case.get("user_instruction", "") or tasks()[task_key].get("desc", "")
        for segment in isolated_segments(case, spans):
            for recipient, config in recipients().items():
                if not isinstance(config, dict):
                    continue
                augmented.append({
                    "feature": build_feature_text(segment, task_key, recipient,
                                                  task_description=description, identity_key=identity),
                    "label": synthetic_label(segment, task_key, recipient, identity).value,
                    "source_case_id": case["case_id"], "source": "synthetic_rule_isolated_field",
                    "task": task_key, "recipient": recipient,
                })
    return baseline, augmented


def reviewed_entity_samples(rows):
    """Use train-only entity annotations as field values, with WEAK action labels.

    NER adjudication does not adjudicate these newly constructed action examples.
    Every task/recipient/view of a source stays in the same holdout group.
    """
    samples = []
    for row in rows:
        if row.get("split") != "train" or not row.get("human_reviewed"):
            raise ValueError("Only reviewed training entity rows are allowed")
        if row.get("origin_kind") != "ner":
            continue
        spans = []
        for entity in row["entities"]:
            start, end = entity["start"], entity["end"]
            if not 0 <= start < end <= len(row["text"]) or row["text"][start:end] != entity["text"]:
                raise ValueError("Entity offsets disagree with source text")
            spans.append(Span(start, end, entity["text"], entity["category"], 1.0, "reviewed_train_entity"))
        for segment in isolated_segments(row, spans):
            for task, task_config in tasks().items():
                if not isinstance(task_config, dict):
                    continue
                # Dedicated workflows do not send reviewed roster entities to
                # generation. Do not invent action labels for their local data.
                if task_config.get("workflow"):
                    continue
                for recipient, config in recipients().items():
                    if not isinstance(config, dict):
                        continue
                    samples.append({
                        "feature": build_feature_text(segment, task, recipient,
                                                      task_description=task_config.get("desc", ""),
                                                      identity_key="student_leader"),
                        "label": synthetic_label(segment, task, recipient, "student_leader").value,
                        "source_case_id": "reviewed_train:" + row["source_case_id"],
                        "source": "weak_rule_action_on_reviewed_train_entity",
                        "task": task, "recipient": recipient,
                    })
    return samples


def coverage(samples):
    counts = Counter((row["task"], row["recipient"],
                      row["feature"].partition("[CAT]")[2].partition(" [TASK]")[0], row["label"])
                     for row in samples)
    return [{"task": key[0], "recipient": key[1], "categories": key[2], "label": key[3], "samples": count}
            for key, count in sorted(counts.items())]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ner-train", type=Path,
                        help="Optional reviewed NER train.jsonl; action labels remain weak")
    args = parser.parse_args()
    out = args.out.resolve()
    live_dir = MODEL_PATH.parent.resolve()
    if out.exists() or out == live_dir or live_dir in out.parents:
        raise ValueError("Use a new experiment directory outside live app/models")
    path = GEN_DIR / "cases_dev.jsonl"
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    baseline, augmented = build_samples(cases)
    reviewed = []
    entity_source = None
    if args.ner_train:
        if args.ner_train.name != "train.jsonl":
            raise ValueError("Expected explicit NER train.jsonl, never validation/test")
        data = args.ner_train.read_bytes()
        reviewed = reviewed_entity_samples([json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()])
        entity_source = {"path": str(args.ner_train.resolve()), "sha256": hashlib.sha256(data).hexdigest(),
                         "samples": len(reviewed), "labels": "human NER values; rule-generated actions"}
    samples = baseline + augmented + reviewed
    out.mkdir(parents=True)
    (out / "samples.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in samples), encoding="utf-8")
    result = NecessityModel(out / "segment_action.joblib").train(samples)
    if not result.get("ok"):
        raise RuntimeError(result.get("reason"))
    model_file = out / "segment_action.joblib"
    report = {
        "status": "trained_candidate", "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_file": str(path), "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_cases": len(cases), "baseline_samples": len(baseline), "augmented_samples": len(augmented),
        "reviewed_train_entity_augmentation": entity_source,
        "split": "source_group_holdout; original and isolated variants share source_case_id",
        "validation": result["validation"], "classification_report": result["report"],
        "before_coverage": coverage(baseline), "after_coverage": coverage(samples),
        "artifact_path": str(model_file), "artifact_sha256": hashlib.sha256(model_file.read_bytes()).hexdigest(),
        "gold_used": bool(reviewed), "human_action_labels_used": False,
        "validation_gold_used": False, "test_used": False, "live_weights_replaced": False,
        "limitation": "Offline rule-labelled coverage experiment, not human-adjudicated action quality. No new cross-turn reasoning capability is established.",
    }
    (out / "training_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "source_cases", "baseline_samples", "augmented_samples", "validation", "artifact_path")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
