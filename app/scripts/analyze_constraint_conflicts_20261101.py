"""只读归因：比较测试池标签、两份模型原始动作和硬约束最终动作。

不训练，不写权重，不改规则。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent
sys.path.insert(0, str(APP))

from llm_shield.campus_v11.magnitude import amount_precision
from llm_shield.m1_access.identity import can_restore, check_provide
from llm_shield.m2_detect.pipeline import attach_spans, segmentize
from llm_shield.m3_decide.constraints import check_hard, feasible_actions
from llm_shield.m3_decide.decision import decide_segment
from llm_shield.m4_necessity.model import NecessityModel
from llm_shield.schema import Action, Span

TEST = ROOT / "research/datasets/legacy" / "校园必要性盲标_20261101" / "返还" / "独立测试池"
OUT = APP / "outputs" / "campus_necessity_aligned_20261101" / "constraint_attribution.json"
MODELS = {
    "active": APP / "models" / "necessity_action.joblib",
    "aligned": APP / "models" / "necessity_action_campus_aligned_20261101.joblib",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def one_span(text: str, unit_id: str, start: int, end: int, category: str):
    span = Span(start, end, text[start:end], category, 1.0, detector="given_annotation", rule_id="constraint_attribution")
    segments = segmentize(text, [span])
    attach_spans(segments, [span], text)
    host = next(item for item in segments if item.start <= start and end <= item.end)
    host.seg_id = unit_id
    host.spans = [span]
    return host


def failed_rules(action: str, segment, row: dict) -> list[dict]:
    if action not in Action._value2member_map_ or not row["recipient_id"]:
        return []
    checks = check_hard(Action(action), segment, row["task_key"], row["recipient_id"], row["identity_key"])
    return [{"rule": item.rule, "detail": item.detail} for item in checks if not item.passed]


def main() -> None:
    before = {name: sha256(path) for name, path in MODELS.items()}
    loaded = {name: NecessityModel(path) for name, path in MODELS.items()}
    for name, model in loaded.items():
        if not model.available:
            raise SystemExit(f"{name} 不可用：{model.reason}")
    rows = []
    for path in sorted(TEST.glob("t*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for unit in document["units"]:
            row = {
                "unit_id": unit["unit_id"],
                "quote": unit["quote"],
                "category": unit["category"],
                "task_key": document["task_key"],
                "workflow_name": document["workflow_name"],
                "boundary_id": unit["boundary_id"],
                "recipient_id": unit["recipient_id"],
                "identity_key": unit["identity_key"],
                "user_task": unit["user_task"],
                "required_facts": unit["annotation"]["required_facts"],
                "text": document["text"],
                "start": unit["start"],
                "end": unit["end"],
                "gold": unit["annotation"]["canonical_action"],
            }
            segment = one_span(row["text"], row["unit_id"], row["start"], row["end"], row["category"])
            allowed, permission_reason = check_provide(row["identity_key"], row["recipient_id"])
            feasible = [
                action.value for action in feasible_actions(
                    segment, row["task_key"], row["recipient_id"], row["identity_key"])
            ]
            item = {
                "unit_id": row["unit_id"],
                "quote": row["quote"],
                "category": row["category"],
                "workflow_name": row["workflow_name"],
                "task_key": row["task_key"],
                "boundary_id": row["boundary_id"],
                "recipient_id": row["recipient_id"],
                "identity_key": row["identity_key"],
                "user_task": row["user_task"],
                "amount_precision": amount_precision(row["user_task"]) if row["category"] == "BUDGET" else None,
                "required_facts": row["required_facts"],
                "gold": row["gold"],
                "provide_allowed": allowed,
                "provide_reason": permission_reason,
                "recipient_can_restore": can_restore(row["identity_key"], row["recipient_id"]),
                "feasible_actions": feasible,
                "gold_blocked_by": failed_rules(row["gold"], segment, row),
            }
            for name, model in loaded.items():
                decision = decide_segment(
                    segment, row["task_key"], row["recipient_id"], row["identity_key"],
                    necessity_scorer=model.score, task_description=row["user_task"],
                )
                scores = {action.value: float(decision.necessity_scores.get(action.value, 0.0)) for action in Action}
                top = max(scores.values())
                winners = [action for action, prob in scores.items() if abs(prob - top) <= 1e-12]
                item[name] = {
                    "argmax": winners[0] if len(winners) == 1 else "TIE",
                    "pipeline": decision.action.value,
                    "reason": decision.reason,
                    "blocked_by": [
                        {"rule": check.rule, "detail": check.detail}
                        for check in decision.hard_checks if not check.passed
                    ],
                }
            rows.append(item)
    after = {name: sha256(path) for name, path in MODELS.items()}
    if after != before:
        raise SystemExit("归因过程中权重发生变化")
    changed = [
        row["unit_id"] for row in rows
        if row["active"]["argmax"] != row["active"]["pipeline"]
        or row["aligned"]["argmax"] != row["aligned"]["pipeline"]
    ]
    OUT.write_text(json.dumps({
        "weights_sha256": before,
        "weights_unchanged": True,
        "trained": False,
        "rules_modified": False,
        "units": len(rows),
        "hard_constraint_changed_units": changed,
        "rows": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("units", len(rows))
    print("changed", ",".join(changed))


if __name__ == "__main__":
    main()
