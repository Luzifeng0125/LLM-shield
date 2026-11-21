"""独立验证活动权重和校园候选权重。不训练，不改权重，不改参考答案。

参考动作只来自冻结的 R0。先单独写出 reference.json，评分时若 R0 结果变化则中止。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
sys.path.insert(0, str(APP))

from llm_shield.campus_v11.r0 import decide as r0_decide
from llm_shield.m1_access.identity import check_provide
from llm_shield.m3_decide.decision import decide_segment
from llm_shield.m4_necessity.model import NecessityModel
from llm_shield.schema import Action

from eval_campus_necessity_baseline import ACTIONS, one_span_segment, resolve_task

CASES = ROOT / "research/datasets/legacy" / "校园必要性独立验证_20261101" / "cases.json"
REFERENCE = ROOT / "research/datasets/legacy" / "校园必要性独立验证_20261101" / "reference.json"
OUT = APP / "outputs" / "campus_necessity_independent_20261101"
ACTIVE = APP / "models" / "necessity_action.joblib"
CANDIDATE = APP / "models" / "necessity_action_campus_candidate.joblib"
ACTIVE_SHA = "cbfed4ca422a1a6d416ce1b5f488649816c261b6acc86ffc173887c8dfed1b9f"
CANDIDATE_SHA = "74902c5d9239eaffc0208891297d8f19b462910534fcc3a51e37b1997f3ee950"
PERMISSIONS = [
    {"source_id": "config/identities.yaml", "version": "identities-v0.1"},
    {"source_id": "config/recipients.yaml", "version": "recipients-v0.1"},
    {"source_id": "config/tasks.yaml", "version": "tasks-v0.1"},
    {"source_id": "config/rules.yaml", "version": "rules-v0.1"},
]
DISCLOSING = {"RETAIN", "PSEUDONYMIZE", "GENERALIZE"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases() -> dict:
    return json.loads(CASES.read_text(encoding="utf-8"))


def locate(text: str, quote: str) -> tuple[int, int]:
    start = text.find(quote)
    if start < 0 or text.find(quote, start + 1) >= 0:
        raise SystemExit(f"引用必须在原文中恰好出现一次: {quote}")
    return start, start + len(quote)


def runtime_for(unit: dict, quote: str) -> dict:
    recipient = unit.get("recipient_id") or ""
    workflow = unit.get("workflow_id") or ""
    return {
        "unit_id": unit["unit_id"],
        "policy_version": "campus-min-disclosure-v1.1",
        "boundary_id": unit["boundary_id"],
        "recipient_id": recipient,
        "identity_key": unit["identity_key"],
        "task_key": unit["task_key"],
        "purpose_id": unit["purpose_id"],
        "purpose_source": "user_explicit",
        "category": unit["category"],
        "confidence": 1.0,
        "workflow_id": workflow,
        "user_task": unit["user_task"],
        "target_text": quote,
        "trusted_permissions": PERMISSIONS,
    }


def production_gate(unit: dict, task_info: dict) -> str:
    recipient = unit.get("recipient_id") or ""
    if not recipient:
        return "recipient_missing"
    allowed, _why = check_provide(unit["identity_key"], recipient)
    if not allowed:
        return "identity_cannot_provide"
    if not task_info["online_model_invoked"]:
        return "task_not_online"
    return "invoke"


def freeze_reference(pack: dict) -> None:
    documents = {item["document_id"]: item["text"] for item in pack["documents"]}
    rows = []
    for unit in pack["units"]:
        text = documents[unit["document_id"]]
        start, end = locate(text, unit["quote"])
        runtime = runtime_for(unit, unit["quote"])
        if not runtime["recipient_id"]:
            r0 = {"final_action": Action.PAUSE.value, "reason_code": "unknown_recipient",
                  "rule_version": "not_called", "pause_kind": "clarification"}
        else:
            r0 = r0_decide(runtime)
        task_info = resolve_task(runtime)
        rows.append({
            "unit_id": unit["unit_id"],
            "document_id": unit["document_id"],
            "quote": unit["quote"],
            "category": unit["category"],
            "boundary_id": unit["boundary_id"],
            "recipient_id": runtime["recipient_id"],
            "identity_key": unit["identity_key"],
            "task_key": unit["task_key"],
            "workflow_id": runtime["workflow_id"],
            "user_task": unit["user_task"],
            "probe": unit["probe"],
            "fragment_start": start,
            "fragment_end": end,
            "policy_action": r0.get("final_action"),
            "policy_reason": r0.get("reason_code"),
            "policy_rule_version": r0.get("rule_version"),
            "policy_pause_kind": r0.get("pause_kind"),
            "online_model_invoked": task_info["online_model_invoked"],
            "model_task_key": task_info["model_task_key"],
            "production_gate": production_gate(unit, task_info),
        })
    payload = {
        "protocol": "campus-necessity-independent-v1",
        "reference_source": "frozen_r0_shared_core",
        "cases_sha256": sha256(CASES),
        "claim": "policy_reference_not_campus_accuracy",
        "units": rows,
    }
    REFERENCE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("reference", len(rows), REFERENCE)


def score_one(model: NecessityModel, text: str, unit: dict, ref: dict) -> dict:
    if ref["production_gate"] != "invoke":
        return {"called": False, "argmax": None, "pipeline_action": None,
                "pipeline_reason": ref["production_gate"], "probabilities": None}
    segment = one_span_segment(
        text, unit["unit_id"], ref["fragment_start"], ref["fragment_end"], unit["category"], 1.0)
    decision = decide_segment(
        segment, ref["model_task_key"], unit["recipient_id"], unit["identity_key"],
        necessity_scorer=model.score, task_description=unit["user_task"],
        confidence_policy=model.metadata.get("decision_thresholds"),
    )
    scores = {action: float(decision.necessity_scores.get(action, 0.0)) for action in ACTIONS}
    top = max(scores.values())
    winners = [action for action, prob in scores.items() if abs(prob - top) <= 1e-12]
    return {
        "called": True,
        "argmax": winners[0] if len(winners) == 1 else "TIE",
        "pipeline_action": decision.action.value,
        "pipeline_reason": decision.reason,
        "probabilities": scores,
    }


def agreement(rows: list[dict], key: str) -> dict:
    usable = [row for row in rows if row["production_gate"] == "invoke" and row[key]]
    matched = sum(row[key] == row["policy_action"] for row in usable)
    return {"n": len(usable), "matched": matched,
            "agreement": None if not usable else matched / len(usable)}


def leaks(rows: list[dict], pipeline_key: str) -> list[dict]:
    found = []
    for row in rows:
        action = row.get(pipeline_key)
        if action in DISCLOSING and row["policy_action"] in {"DELETE", "PAUSE"}:
            found.append({"unit_id": row["unit_id"], "policy": row["policy_action"],
                          "pipeline": action, "quote": row["quote"], "category": row["category"]})
    return found


def score_models() -> None:
    if not REFERENCE.exists():
        raise SystemExit("缺少已冻结的 reference.json")
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    if reference["cases_sha256"] != sha256(CASES):
        raise SystemExit("案例文件已变化，拒绝沿用旧参考答案")
    if sha256(ACTIVE) != ACTIVE_SHA or sha256(CANDIDATE) != CANDIDATE_SHA:
        raise SystemExit("活动权重或候选权重哈希与冻结值不一致，已中止")
    pack = load_cases()
    documents = {item["document_id"]: item["text"] for item in pack["documents"]}
    by_ref = {item["unit_id"]: item for item in reference["units"]}
    active = NecessityModel(ACTIVE)
    candidate = NecessityModel(CANDIDATE)
    if sha256(ACTIVE) != ACTIVE_SHA or sha256(CANDIDATE) != CANDIDATE_SHA:
        raise SystemExit("加载后权重哈希变化，已中止")
    rows = []
    for unit in pack["units"]:
        ref = by_ref[unit["unit_id"]]
        rerun = r0_decide(runtime_for(unit, unit["quote"])) if ref["recipient_id"] else {
            "final_action": Action.PAUSE.value, "reason_code": "unknown_recipient"}
        if rerun.get("final_action") != ref["policy_action"] or rerun.get("reason_code") != ref["policy_reason"]:
            raise SystemExit(f"{unit['unit_id']} 的 R0 与冻结参考不一致，已中止")
        text = documents[unit["document_id"]]
        active_score = score_one(active, text, unit, ref)
        candidate_score = score_one(candidate, text, unit, ref)
        row = dict(ref)
        row["active"] = active_score
        row["candidate"] = candidate_score
        row["active_argmax"] = active_score["argmax"]
        row["candidate_argmax"] = candidate_score["argmax"]
        row["active_pipeline"] = active_score["pipeline_action"]
        row["candidate_pipeline"] = candidate_score["pipeline_action"]
        rows.append(row)
    if sha256(ACTIVE) != ACTIVE_SHA or sha256(CANDIDATE) != CANDIDATE_SHA:
        raise SystemExit("评分后权重哈希变化，已中止且不覆盖报告")
    invoked = [row for row in rows if row["production_gate"] == "invoke"]
    summary = {
        "protocol": "campus-necessity-independent-v1",
        "claim": "independent_policy_agreement_not_campus_accuracy",
        "models_modified": False,
        "reference_modified_during_scoring": False,
        "active_sha256": ACTIVE_SHA,
        "candidate_sha256": CANDIDATE_SHA,
        "cases_sha256": sha256(CASES),
        "reference_sha256": sha256(REFERENCE),
        "counts": {
            "units": len(rows),
            "production_invoked": len(invoked),
            "not_invoked": [row["unit_id"] for row in rows if row["production_gate"] != "invoke"],
        },
        "active_argmax_vs_policy": agreement(rows, "active_argmax"),
        "candidate_argmax_vs_policy": agreement(rows, "candidate_argmax"),
        "active_pipeline_vs_policy": agreement(rows, "active_pipeline"),
        "candidate_pipeline_vs_policy": agreement(rows, "candidate_pipeline"),
        "active_pipeline_disclosure_against_delete_or_pause": leaks(rows, "active_pipeline"),
        "candidate_pipeline_disclosure_against_delete_or_pause": leaks(rows, "candidate_pipeline"),
    }
    pairs = []
    by_id = {row["unit_id"]: row for row in rows}
    for left_id, right_id in pack["association_pairs"]:
        left, right = by_id[left_id], by_id[right_id]
        pairs.append({
            "units": [left_id, right_id],
            "policy": [left["policy_action"], right["policy_action"]],
            "active": [left["active_argmax"], right["active_argmax"]],
            "candidate": [left["candidate_argmax"], right["candidate_argmax"]],
            "active_same": left["active_argmax"] == right["active_argmax"],
            "candidate_same": left["candidate_argmax"] == right["candidate_argmax"],
            "active_both_pseudonymize": left["active_argmax"] == right["active_argmax"] == "PSEUDONYMIZE",
            "candidate_both_pseudonymize": left["candidate_argmax"] == right["candidate_argmax"] == "PSEUDONYMIZE",
        })
    summary["association_pairs"] = pairs
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "predictions.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary["counts"], ensure_ascii=False))
    print("active", summary["active_argmax_vs_policy"])
    print("candidate", summary["candidate_argmax_vs_policy"])
    print("leaks", len(summary["active_pipeline_disclosure_against_delete_or_pause"]),
          len(summary["candidate_pipeline_disclosure_against_delete_or_pause"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="独立验证两个必要性权重")
    parser.add_argument("--freeze-reference", action="store_true")
    parser.add_argument("--score", action="store_true")
    args = parser.parse_args()
    if args.freeze_reference == args.score:
        raise SystemExit("只能选择 --freeze-reference 或 --score 之一")
    if args.freeze_reference:
        if REFERENCE.exists():
            raise SystemExit("参考答案已存在，拒绝覆盖")
        freeze_reference(load_cases())
        return
    score_models()


if __name__ == "__main__":
    main()
