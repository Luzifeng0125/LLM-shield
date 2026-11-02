"""在 38 个已标注校园片段上记录当前必要性模型的基线。

不训练、不改权重、不改规则、不改参考答案。已知片段直接送入现有
decide_segment；不调用 GLiNER。接收方缺失时不编造接收方，模型不推理。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parents[1]
sys.path.insert(0, str(APP))

from llm_shield.campus_v11.pack import load_document
from llm_shield.campus_v11.r0 import decide as r0_decide
from llm_shield.config import campus_workflows, tasks
from llm_shield.m2_detect.pipeline import attach_spans, segmentize
from llm_shield.m3_decide.decision import decide_segment
from llm_shield.m4_necessity.model import NecessityModel
from llm_shield.schema import Action, Span

PACK = ROOT / "03_数据与人工复核" / "校园最小披露_校准首批_20261031"
OUT = APP / "outputs" / "campus_necessity_baseline_20261101"
MODEL = APP / "models" / "necessity_action.joblib"
ACTIONS = [item.value for item in Action]
TRACKED = [
    "delivery/app/models/necessity_action.joblib",
    "delivery/app/models/ACTIVE_MODELS.json",
    "delivery/app/config/tasks.yaml",
    "delivery/app/config/rules.yaml",
    "delivery/app/config/recipients.yaml",
    "delivery/app/config/identities.yaml",
    "delivery/app/config/campus_workflows_v1.1.yaml",
    "03_数据与人工复核/校园最小披露_校准首批_20261031/returns/calibration-return.json",
    "03_数据与人工复核/校园最小披露_校准首批_20261031/manifest.json",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_task(runtime: dict) -> dict:
    """选择送入模型的任务键，并标明在线入口是否真的会调用模型。"""
    workflows = campus_workflows().get("workflows") or {}
    known = tasks()
    task_key = runtime.get("task_key")
    workflow_id = runtime.get("workflow_id")
    workflow = workflows.get(workflow_id) if isinstance(workflow_id, str) else None
    reuses = workflow.get("reuses") if isinstance(workflow, dict) else None
    if isinstance(task_key, str) and task_key in known:
        return {"model_task_key": task_key, "task_key_source": "runtime_task_key",
                "online_model_invoked": True}
    if isinstance(reuses, str) and reuses in known:
        return {"model_task_key": reuses, "task_key_source": "workflow_reuses_template",
                "online_model_invoked": True}
    if workflow_id == "class_coordination" and isinstance(workflow, dict):
        return {"model_task_key": "class_coordination", "task_key_source": "online_campus_task",
                "online_model_invoked": True}
    if isinstance(workflow_id, str) and workflow_id:
        return {"model_task_key": workflow_id, "task_key_source": "workflow_id_not_online",
                "online_model_invoked": False}
    return {"model_task_key": "", "task_key_source": "missing", "online_model_invoked": False}


def one_span_segment(text: str, unit_id: str, start: int, end: int, category: str, confidence: float):
    span = Span(start, end, text[start:end], category, confidence, detector="given_annotation",
                rule_id="campus_baseline_l1")
    segments = segmentize(text, [span])
    attach_spans(segments, [span], text)
    host = next(item for item in segments if item.start <= start and end <= item.end)
    host.seg_id = unit_id
    host.spans = [span]
    return host


def matrix(rows: list, gold_key: str, pred_key: str) -> dict:
    labels = ACTIONS
    counts = {gold: {pred: 0 for pred in labels} for gold in labels}
    for row in rows:
        counts[row[gold_key]][row[pred_key]] += 1
    per_action = {}
    for action in labels:
        support = sum(counts[action].values())
        predicted = sum(item[action] for item in counts.values())
        hit = counts[action][action]
        per_action[action] = {
            "support": support,
            "predicted": predicted,
            "hit": hit,
            "recall": None if support == 0 else hit / support,
            "precision": None if predicted == 0 else hit / predicted,
        }
    matched = sum(row[gold_key] == row[pred_key] for row in rows)
    return {
        "n": len(rows),
        "matched": matched,
        "agreement": None if not rows else matched / len(rows),
        "labels": labels,
        "matrix_gold_rows_pred_cols": counts,
        "per_action": per_action,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="评测必要性模型，不改权重")
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    model_path = args.model
    out = args.out
    before = sha256(model_path)
    model = NecessityModel(model_path)
    if not model.available:
        raise SystemExit("必要性模型不可用：" + model.reason)
    if sha256(model_path) != before:
        raise SystemExit("推理过程中权重哈希发生变化，已中止")
    returns = json.loads((PACK / "returns" / "calibration-return.json").read_text(encoding="utf-8"))
    human = {item["decision_key"]: item["final_answer"]["canonical_action"] for item in returns["items"]}
    human_facts = {item["decision_key"]: item["final_answer"].get("required_facts", "") for item in returns["items"]}
    rows = []
    for folder in sorted((PACK / "documents").iterdir()):
        loaded = load_document(folder)
        text = loaded["document"]["runtime_input"]["text"]
        user_task = loaded["document"]["runtime_input"]["user_task"]
        labels = {item["information_unit_id"]: item for item in loaded["document"]["annotation"]["units"]}
        for runtime in loaded["runtime_units"]:
            unit_id = runtime["unit_id"]
            short = unit_id.split(":", 1)[1]
            label = labels[short]
            quote = label["quote"]
            start, end = label["start"], label["end"]
            if text[start:end] != quote:
                raise SystemExit(f"{unit_id} 标注位置与原文不一致")
            task_info = resolve_task(runtime)
            r0 = r0_decide(runtime)
            recipient = runtime.get("recipient_id")
            record = {
                "unit_id": unit_id,
                "document_id": folder.name,
                "workflow_id": runtime.get("workflow_id"),
                "runtime_task_key": runtime.get("task_key"),
                "user_task": user_task,
                "fragment": quote,
                "fragment_start": start,
                "fragment_end": end,
                "category": runtime.get("category"),
                "boundary_id": runtime.get("boundary_id"),
                "recipient_id": recipient,
                "identity_key": runtime.get("identity_key"),
                "purpose_id": runtime.get("purpose_id"),
                "human_assisted_action": human[unit_id],
                "human_required_facts": human_facts[unit_id],
                "draft_action": label.get("canonical_action"),
                "draft_required_facts": label.get("required_facts"),
                "counts_as_primary": label.get("counts_as_primary") is not False,
                "counterfactual": label.get("counterfactual") is True,
                "pause_group_id": label.get("pause_group_id"),
                "r0_action": r0.get("final_action"),
                "r0_reason": r0.get("reason_code"),
                "r0_rule_version": r0.get("rule_version"),
                **task_info,
                "model_called": False,
                "model_argmax": None,
                "pipeline_action": None,
                "pipeline_reason": None,
                "probabilities": None,
            }
            if not isinstance(recipient, str) or not recipient:
                record["model_skip_reason"] = "recipient_missing"
                rows.append(record)
                continue
            if not task_info["model_task_key"]:
                record["model_skip_reason"] = "task_missing"
                rows.append(record)
                continue
            segment = one_span_segment(text, unit_id, start, end, runtime["category"], float(runtime["confidence"]))
            record["segment_text"] = segment.text
            record["segment_context"] = segment.context
            decision = decide_segment(
                segment, task_info["model_task_key"], recipient, runtime["identity_key"],
                necessity_scorer=model.score, task_description=user_task,
                confidence_policy=model.metadata.get("decision_thresholds"),
            )
            scores = {action: float(decision.necessity_scores.get(action, 0.0))
                      for action in ACTIONS} if decision.necessity_scores else None
            if scores:
                top = max(scores.values())
                winners = [action for action, prob in scores.items() if abs(prob - top) <= 1e-12]
                record["model_argmax"] = winners[0] if len(winners) == 1 else "TIE"
            record["model_called"] = scores is not None
            record["pipeline_action"] = decision.action.value
            record["pipeline_reason"] = decision.reason
            record["probabilities"] = scores
            rows.append(record)
    if sha256(model_path) != before:
        raise SystemExit("写出结果前权重哈希发生变化，已中止且不覆盖报告")
    called = [row for row in rows if row["model_called"] and row["model_argmax"] in ACTIONS]
    primary = [row for row in called if row["counts_as_primary"] and not row["counterfactual"]]
    online = [row for row in primary if row["online_model_invoked"]]
    summary = {
        "protocol": {
            "name": "campus-necessity-baseline-v1",
            "claim": "assisted_label_agreement_not_accuracy",
            "model_action": "unique_highest_probability_before_hard_checks",
            "pipeline_action": "existing_decide_segment_after_hard_checks",
            "span_input": "given_annotation_single_span_on_online_sentence_segment",
            "context": "attach_spans_30_char_window",
            "task_description": "runtime_input.user_task",
            "excluded_from_model_matrix": "missing_recipient_or_task_or_non_primary_or_counterfactual",
            "gliner": "not_used",
            "trained": False,
            "rules_modified": False,
            "thresholds_modified": False,
        },
        "versions": {
            "model_path": str(model_path),
            "weights_sha256": before,
            "weights_sha256_after": sha256(model_path),
            "feature_version": model.metadata.get("feature_version"),
            "schema_version": model.metadata.get("schema_version"),
            "sklearn_version_recorded_in_artifact": model.metadata.get("sklearn_version"),
            "stored_validation_not_campus": model.metadata.get("validation"),
            "stored_limitation": model.metadata.get("limitation"),
            "decision_thresholds": model.metadata.get("decision_thresholds"),
            "input_pack": "03_数据与人工复核/校园最小披露_校准首批_20261031",
            "return_provenance": "human_assisted_not_independent",
            "file_sha256": {relative: sha256(ROOT / relative) for relative in TRACKED},
        },
        "counts": {
            "saved_units": len(rows),
            "model_called": len(called),
            "model_skipped": [row["unit_id"] for row in rows if not row["model_called"]],
            "primary_called": len(primary),
            "primary_online_task": len(online),
            "counterfactual_called": sum(row["counterfactual"] for row in called),
        },
        "agreement_vs_human_primary": matrix(primary, "human_assisted_action", "model_argmax"),
        "agreement_vs_r0_primary": matrix(primary, "r0_action", "model_argmax"),
        "agreement_vs_human_online_subset": matrix(online, "human_assisted_action", "model_argmax"),
        "agreement_vs_r0_online_subset": matrix(online, "r0_action", "model_argmax"),
        "pipeline_differs_from_argmax": [
            {"unit_id": row["unit_id"], "model_argmax": row["model_argmax"],
             "pipeline_action": row["pipeline_action"], "reason": row["pipeline_reason"]}
            for row in called if row["pipeline_action"] != row["model_argmax"]
        ],
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "predictions.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary["counts"], ensure_ascii=False))
    print("human", summary["agreement_vs_human_primary"]["matched"], "/", summary["agreement_vs_human_primary"]["n"])
    print("r0", summary["agreement_vs_r0_primary"]["matched"], "/", summary["agreement_vs_r0_primary"]["n"])
    print("online human", summary["agreement_vs_human_online_subset"]["matched"], "/",
          summary["agreement_vs_human_online_subset"]["n"])
    skipped = Counter(row.get("model_skip_reason") for row in rows if not row["model_called"])
    print("skipped", dict(skipped))


if __name__ == "__main__":
    main()
