"""对已经冻结的对齐候选做一次独立测试池核对。

这个脚本不训练，不写权重。测试池标签只在候选保存之后使用。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parents[1]
sys.path.insert(0, str(APP))

from llm_shield.m2_detect.pipeline import attach_spans, segmentize
from llm_shield.m3_decide.decision import decide_segment
from llm_shield.m4_necessity.model import NecessityModel
from llm_shield.schema import Action, Span

TEST = ROOT / "03_数据与人工复核" / "校园必要性盲标_20261101" / "返还" / "独立测试池"
OUT = APP / "outputs" / "campus_necessity_aligned_20261101" / "test_once.json"
MODELS = {
    "active": APP / "models" / "necessity_action.joblib",
    "frozen_candidate": APP / "models" / "necessity_action_campus_candidate.joblib",
    "aligned": APP / "models" / "necessity_action_campus_aligned_20261101.joblib",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_test() -> list[dict]:
    if TEST.name != "独立测试池":
        raise SystemExit("一次核对只能读取独立测试池")
    rows = []
    for path in sorted(TEST.glob("t*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("pool") != "test":
            raise SystemExit(f"{path.name} 不是独立测试池")
        for unit in document["units"]:
            action = unit["annotation"]["canonical_action"]
            if action not in Action._value2member_map_:
                raise SystemExit(f"{unit['unit_id']} 没有对齐动作")
            rows.append({
                "unit_id": unit["unit_id"],
                "quote": unit["quote"],
                "category": unit["category"],
                "task_key": document["task_key"],
                "workflow_name": document["workflow_name"],
                "recipient_id": unit["recipient_id"],
                "identity_key": unit["identity_key"],
                "user_task": unit["user_task"],
                "text": document["text"],
                "start": unit["start"],
                "end": unit["end"],
                "gold": action,
            })
    if len(rows) != 40:
        raise SystemExit(f"测试条目不是 40: {len(rows)}")
    return rows


def one_span(text: str, unit_id: str, start: int, end: int, category: str):
    span = Span(start, end, text[start:end], category, 1.0, detector="given_annotation", rule_id="aligned_test_once")
    segments = segmentize(text, [span])
    attach_spans(segments, [span], text)
    host = next(item for item in segments if item.start <= start and end <= item.end)
    host.seg_id = unit_id
    host.spans = [span]
    return host


def score(model: NecessityModel, row: dict) -> dict:
    if not row["recipient_id"] or not row["task_key"]:
        return {"argmax": None, "pipeline": None, "reason": "recipient_or_task_missing"}
    segment = one_span(row["text"], row["unit_id"], row["start"], row["end"], row["category"])
    decision = decide_segment(
        segment, row["task_key"], row["recipient_id"], row["identity_key"],
        necessity_scorer=model.score, task_description=row["user_task"],
    )
    scores = {action.value: float(decision.necessity_scores.get(action.value, 0.0)) for action in Action}
    top = max(scores.values())
    winners = [action for action, prob in scores.items() if abs(prob - top) <= 1e-12]
    return {
        "argmax": winners[0] if len(winners) == 1 else "TIE",
        "pipeline": decision.action.value,
        "reason": decision.reason,
    }


def main() -> None:
    before = {name: sha256(path) for name, path in MODELS.items()}
    loaded = {}
    for name, path in MODELS.items():
        model = NecessityModel(path)
        if not model.available:
            raise SystemExit(f"{name} 不可用：{model.reason}")
        loaded[name] = model
    rows = []
    for row in load_test():
        item = {
            "unit_id": row["unit_id"],
            "workflow_name": row["workflow_name"],
            "task_key": row["task_key"],
            "category": row["category"],
            "recipient_id": row["recipient_id"],
            "quote": row["quote"],
            "gold": row["gold"],
        }
        for name, model in loaded.items():
            result = score(model, row)
            item[f"{name}_argmax"] = result["argmax"]
            item[f"{name}_pipeline"] = result["pipeline"]
        rows.append(item)
    after = {name: sha256(path) for name, path in MODELS.items()}
    if after != before:
        raise SystemExit("核对过程中权重发生变化，不写出报告")
    def matched(key: str) -> int:
        return sum(row["gold"] == row[key] for row in rows if row[key])
    summary = {
        "protocol": "aligned-candidate-test-once-v1",
        "test_pool_used_for_training": False,
        "model_updated_after_this_run": False,
        "weights_sha256": before,
        "called": len(rows),
        "argmax_matched": {name: matched(f"{name}_argmax") for name in MODELS},
        "pipeline_matched": {name: matched(f"{name}_pipeline") for name in MODELS},
        "units": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "argmax_matched": summary["argmax_matched"],
        "pipeline_matched": summary["pipeline_matched"],
        "weights_unchanged": True,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
