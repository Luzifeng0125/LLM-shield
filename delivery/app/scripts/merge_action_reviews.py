"""Import actual A/B reviews; missing/disputed answers never become human gold."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from llm_shield.m4_necessity.research import annotation_for, case_hash, validate_cases


def _reject_explicit_machine_review(response):
    """Legacy human exports have no kind field; reject affirmative draft evidence.

    A role letter or a non-empty reviewer name is not evidence that an AI draft
    became an independent human review. Do not inspect previous provenance:
    a person may legitimately review a draft and keep that history.
    """
    reviewer = response.get("reviewer", "")
    kind = response.get("reviewer_kind", "")
    if isinstance(reviewer, dict):
        kind = reviewer.get("kind", kind)
        reviewer = reviewer.get("id", "")
    draft_name = any(marker in str(reviewer) for marker in
                     ("AI更正稿", "AI草稿", "AI预复核", "Codex-AI", "待二审"))
    if (str(kind).strip().lower() in {"ai", "machine", "model"}
            or draft_name
            or response.get("supervision") in {"ai_pre_review_not_human_gold", "machine_draft_not_gold"}
            or response.get("review_status") in {"ai_pre_review_pending_human", "machine_draft"}
            or response.get("human_reviewed") is False):
        raise ValueError("AI 草稿或待二审材料不能作为真实人工复核导入")


def _responses(response, cases, expected_role):
    _reject_explicit_machine_review(response)
    if (response.get("schema") != "action-review-response-v1"
            or response.get("role") != expected_role
            or not isinstance(response.get("reviewer"), str) or not response["reviewer"].strip()):
        raise ValueError("标注者或复核角色无效")
    rows = {}
    for row in response["reviews"]:
        _reject_explicit_machine_review(row)
        case_id = row["case_id"]
        if (case_id not in cases or case_id in rows
                or row.get("case_sha256") != case_hash(cases[case_id])):
            raise ValueError("题目版本、案例编号或来源哈希不匹配")
        probe = {**cases[case_id], "annotation": row["annotation"], "review": {"status": "human_reviewed"}}
        annotation_for(probe, allow_drafts=False)
        rows[case_id] = row["annotation"]
    return rows


def merge_reviews(cases, review_a, review_b, adjudication=None):
    validate_cases(cases)
    by_id = {case["case_id"]: case for case in cases}
    if str(review_a.get("reviewer", "")).strip() == str(review_b.get("reviewer", "")).strip():
        raise ValueError("A/B 必须由两位不同的真实标注者独立填写")
    a, b = _responses(review_a, by_id, "A"), _responses(review_b, by_id, "B")
    resolved = _responses(adjudication, by_id, "adjudication") if adjudication else {}
    merged, pending, disputed = [], [], []
    def key(annotation):
        return (annotation["action"], annotation["minimum_representation"], tuple(sorted(annotation["allowed_actions"])))
    def differences(left, right):
        reasons = []
        if key(left) != key(right):
            reasons.append("action_or_representation_disagreement")
        if ' '.join(left['required_facts'].split()) != ' '.join(right['required_facts'].split()):
            # Free-text equivalence is unknown, not proof that either human is wrong.
            reasons.append("facts_require_adjudication")
        return reasons
    for case in cases:
        row = copy.deepcopy(case)
        row.pop("annotation", None)
        row["review"] = {"status": "awaiting_human_review"}
        cid = case["case_id"]
        if cid not in a or cid not in b:
            pending.append(cid)
        elif differences(a[cid], b[cid]) and cid not in resolved:
            disputed.append({"case_id": cid, "a": a[cid], "b": b[cid],
                             "reasons": differences(a[cid], b[cid]),
                             "semantic_equivalence": "unverified"})
        else:
            row["annotation"] = resolved.get(cid, a[cid])
            row["review"] = {"status": "human_reviewed", "reviewers": [review_a["reviewer"], review_b["reviewer"]],
                             "case_sha256": case_hash(case), "a": a[cid], "b": b[cid],
                             "adjudicator": adjudication["reviewer"] if cid in resolved else None}
        merged.append(row)
    return merged, {"reviewed": sum(c.get("review", {}).get("status") == "human_reviewed" for c in merged),
                    "pending": pending, "disagreements": disputed}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--a", type=Path, required=True)
    parser.add_argument("--b", type=Path, required=True)
    parser.add_argument("--adjudication", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("输出目录已存在，请使用新的目录")
    try:
        cases = [json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line.strip()]
        load = lambda path: json.loads(path.read_text(encoding="utf-8"))
        merged, summary = merge_reviews(cases, load(args.a), load(args.b), load(args.adjudication) if args.adjudication else None)
        args.out.mkdir(parents=True)
        (args.out / "reviewed_cases.jsonl").write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in merged) + "\n", encoding="utf-8")
        (args.out / "review_status.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"reviewed": summary["reviewed"], "pending": len(summary["pending"]),
                          "disagreements": len(summary["disagreements"])}, ensure_ascii=False))
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
