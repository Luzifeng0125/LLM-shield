"""用已经暴露过的 40 条做诊断，不把它当作新的最终验证，也不据此再训练。"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parents[1]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sklearn.metrics import f1_score

from campus_task_labels_20261102 import executable_action
from llm_shield.m2_detect.pipeline import attach_spans, segmentize
from llm_shield.m3_decide.constraints import disclosed_categories
from llm_shield.m3_decide.decision import decide_segment
from llm_shield.m4_necessity.model import NecessityModel, build_feature_text_v4, split_feature_v4
from llm_shield.schema import Action, Segment, Span

TEST = ROOT / "03_数据与人工复核" / "校园必要性盲标_20261101" / "返还" / "独立测试池"
OUT = APP / "outputs" / "campus_necessity_task_20261102" / "diagnostic.json"
MODELS = {
    "active": APP / "models" / "necessity_action.joblib",
    "aligned": APP / "models" / "necessity_action_campus_aligned_20261101.joblib",
    "task": APP / "models" / "necessity_action_campus_task_20261102.joblib",
}
ACTIONS = [item.value for item in Action]

# 家族是诊断标准，不是训练时读到的原句。可执行动作必须和监督函数一致。
EXPECT = {
    "t01-u1": ("duty_who", "PSEUDONYMIZE"),
    "t01-u2": ("duty_who", "PSEUDONYMIZE"),
    "t01-u3": ("duty_who", "DELETE"),
    "t01-u4": ("duty_who", "DELETE"),
    "t01-u5": ("duty_who", "PSEUDONYMIZE"),
    "t01-u6": ("duty_who", "RETAIN"),
    "t01-u7": ("duty_who", "PAUSE"),
    "t02-u1": ("place_only", "DELETE"),
    "t02-u2": ("place_only", "RETAIN"),
    "t02-u3": ("place_only", "DELETE"),
    "t02-u4": ("place_only", "DELETE"),
    "t03-u1": ("count_org", "LOCAL_AGGREGATE"),
    "t03-u2": ("count_org", "LOCAL_AGGREGATE"),
    "t03-u3": ("count_org", "RETAIN"),
    "t03-u4": ("count_org", "DELETE"),
    "t03-u5": ("count_org", "DELETE"),
    "t04-u1": ("money_magnitude", "PSEUDONYMIZE"),
    "t04-u2": ("money_magnitude", "PSEUDONYMIZE"),
    "t04-u3": ("money_magnitude", "PAUSE"),
    "t04-u4": ("money_magnitude", "DELETE"),
    "t04-u5": ("money_magnitude", "DELETE"),
    "t05-u1": ("money_exact", "RETAIN"),
    "t05-u2": ("money_exact", "RETAIN"),
    "t05-u3": ("money_exact", "RETAIN"),
    "t06-u1": ("money_exact", "PSEUDONYMIZE"),
    "t06-u2": ("money_exact", "PSEUDONYMIZE"),
    "t06-u3": ("money_exact", "PAUSE"),
    "t07-u1": ("money_exact", "PSEUDONYMIZE"),
    "t07-u2": ("money_exact", "PAUSE"),
    "t08-u1": ("plain", "PSEUDONYMIZE"),
    "t08-u2": ("plain", "DELETE"),
    "t09-u1": ("plain", "DELETE"),
    "t09-u2": ("plain", "DELETE"),
    "t09-u3": ("plain", "DELETE"),
    "t10-u1": ("grade_omit", "RETAIN"),
    "t10-u2": ("grade_omit", "DELETE"),
    "t10-u3": ("grade_omit", "DELETE"),
    "t11-u1": ("plain", "DELETE"),
    "t11-u2": ("plain", "DELETE"),
    "t12-u1": ("duty_who", "PAUSE"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_rows() -> list[dict]:
    rows = []
    for path in sorted(TEST.glob("t*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for unit in document["units"]:
            family, executable = EXPECT[unit["unit_id"]]
            got = executable_action(
                family, document["task_key"], unit["category"], unit["recipient_id"], unit["identity_key"])
            if got != executable:
                raise SystemExit(f"{unit['unit_id']} 监督函数给出 {got}，诊断标准是 {executable}")
            rows.append({
                "unit_id": unit["unit_id"],
                "quote": unit["quote"],
                "category": unit["category"],
                "task_key": document["task_key"],
                "recipient_id": unit["recipient_id"],
                "identity_key": unit["identity_key"],
                "user_task": unit["user_task"],
                "text": document["text"],
                "start": unit["start"],
                "end": unit["end"],
                "historical": unit["annotation"]["canonical_action"],
                "family": family,
                "executable": executable,
            })
    if len(rows) != 40 or set(EXPECT) != {row["unit_id"] for row in rows}:
        raise SystemExit(f"诊断条目不是 40: {len(rows)}")
    return rows


def one_span(row: dict):
    span = Span(row["start"], row["end"], row["text"][row["start"]:row["end"]], row["category"], 1.0,
                detector="diagnostic", rule_id="task_20261102")
    segments = segmentize(row["text"], [span])
    attach_spans(segments, [span], row["text"])
    host = next(item for item in segments if item.start <= row["start"] and row["end"] <= item.end)
    host.seg_id = row["unit_id"]
    host.spans = [span]
    return host


def score(model: NecessityModel, row: dict) -> dict:
    decision = decide_segment(
        one_span(row), row["task_key"], row["recipient_id"], row["identity_key"],
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


def discloses(action: str, category: str) -> bool:
    if action in {"DELETE", "LOCAL_AGGREGATE", "PAUSE", "TIE"}:
        return False
    return category in disclosed_categories(Action(action), Segment(
        "d", category, 0, len(category), [Span(0, len(category), category, category)]))


def metrics(rows: list[dict], name: str, gold_key: str) -> dict:
    gold = [row[gold_key] for row in rows]
    argmax = [row[f"{name}_argmax"] for row in rows]
    pipeline = [row[f"{name}_pipeline"] for row in rows]
    labels = sorted(set(gold) | set(argmax))
    return {
        "argmax_accuracy": round(sum(a == g for a, g in zip(argmax, gold)) / len(rows), 4),
        "argmax_correct": sum(a == g for a, g in zip(argmax, gold)),
        "argmax_macro_f1": round(float(f1_score(gold, argmax, labels=labels, average="macro", zero_division=0)), 4),
        "pipeline_accuracy": round(sum(a == g for a, g in zip(pipeline, gold)) / len(rows), 4),
        "pipeline_correct": sum(a == g for a, g in zip(pipeline, gold)),
        "pipeline_macro_f1": round(float(f1_score(gold, pipeline, labels=sorted(set(gold) | set(pipeline)), average="macro", zero_division=0)), 4),
        "argmax_confusion": dict(Counter(f"{g}->{a}" for g, a in zip(gold, argmax) if g != a)),
        "pipeline_confusion": dict(Counter(f"{g}->{a}" for g, a in zip(gold, pipeline) if g != a)),
    }


def risks(rows: list[dict], name: str) -> dict:
    leaked = []
    blocked = []
    dropped = []
    for row in rows:
        final = row[f"{name}_pipeline"]
        target = row["executable"]
        if discloses(final, row["category"]) and not discloses(target, row["category"]):
            leaked.append(row["unit_id"])
        if target != "PAUSE" and final == "PAUSE":
            blocked.append(row["unit_id"])
        if target in {"RETAIN", "PSEUDONYMIZE", "GENERALIZE", "LOCAL_AGGREGATE"} and final == "DELETE":
            dropped.append(row["unit_id"])
    return {"unnecessary_disclosure": leaked, "needed_action_paused": blocked, "needed_action_deleted": dropped}


def probe_saved(model: NecessityModel) -> list[dict]:
    text = "费用是8600元。"
    host = Segment("probe", text, 0, len(text), [Span(0, len(text), text, "BUDGET", 1.0)])
    asks = ("这笔开支按核准数额保留。", "这笔开支只说明量级。", "这笔开支不要写。")
    rows = []
    for recipient in ("viewer_teacher", "external_model"):
        demands = []
        for ask in asks:
            feature = build_feature_text_v4(host, "meeting_minutes", recipient, task_description=ask, identity_key="student_leader")
            structured, demand, _ = split_feature_v4(feature)
            decision = decide_segment(host, "meeting_minutes", recipient, "student_leader", necessity_scorer=model.score, task_description=ask)
            demands.append(demand)
            scores = decision.necessity_scores
            top = max(scores, key=scores.get)
            rows.append({
                "recipient": recipient,
                "ask": ask,
                "argmax": top,
                "pipeline": decision.action.value,
            })
        if len(set(demands)) != 3 or len({item.partition("[|SPLIT|]")[0] for item in (
            build_feature_text_v4(host, "meeting_minutes", recipient, task_description=ask, identity_key="student_leader")
            for ask in asks)}) != 1:
            raise SystemExit("保存后的模型看到的三种需求输入不正确")
    return rows


def main() -> None:
    if any("盲标_20261102" in str(path) for path in MODELS.values()):
        raise SystemExit("诊断不能读取新的盲标")
    before = {name: sha256(path) for name, path in MODELS.items()}
    loaded = {name: NecessityModel(path) for name, path in MODELS.items()}
    for name, model in loaded.items():
        if not model.available:
            raise SystemExit(f"{name} 不可用：{model.reason}")
    rows = []
    for row in load_rows():
        item = {key: row[key] for key in (
            "unit_id", "task_key", "category", "recipient_id", "quote", "historical", "family", "executable")}
        for name, model in loaded.items():
            result = score(model, row)
            item[f"{name}_argmax"] = result["argmax"]
            item[f"{name}_pipeline"] = result["pipeline"]
        rows.append(item)
    after = {name: sha256(path) for name, path in MODELS.items()}
    if after != before:
        raise SystemExit("诊断过程中权重发生变化")
    summary = {
        "material": "20261101 独立测试池，已用于候选评价和归因，只作诊断",
        "not_final_validation": True,
        "weights_unchanged": True,
        "sha256": after,
        "historical": {name: metrics(rows, name, "historical") for name in MODELS},
        "executable": {name: metrics(rows, name, "executable") for name in MODELS},
        "risk": {name: risks(rows, name) for name in MODELS},
        "unseen_amount_probe": probe_saved(loaded["task"]),
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    brief = {
        "historical_argmax": {name: summary["historical"][name]["argmax_correct"] for name in MODELS},
        "executable_argmax": {name: summary["executable"][name]["argmax_correct"] for name in MODELS},
        "executable_macro_f1": {name: summary["executable"][name]["argmax_macro_f1"] for name in MODELS},
        "pipeline_executable": {name: summary["executable"][name]["pipeline_correct"] for name in MODELS},
        "risk": summary["risk"],
        "unseen_amount_probe": summary["unseen_amount_probe"],
    }
    print(json.dumps(brief, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
