"""一次任务上下文对照实验。训练后立即比较，不再第二次拟合。

不读取 31 条空白盲标，不用 40 条诊断材料训练，不改活动权重，不改硬约束。
配对案例是机制诊断，不是人工测试成绩。
"""
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

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import FunctionTransformer

from campus_task_labels_20261102 import (
    CALIBRATION_LEDGER,
    SPAN_TEXT,
    executable_action,
)
from eval_campus_necessity_task_20261102 import EXPECT
from llm_shield.m2_detect.pipeline import attach_spans, segmentize
from llm_shield.m3_decide.constraints import disclosed_categories
from llm_shield.m3_decide.decision import decide_segment
from llm_shield.m4_necessity.model import (
    ARTIFACT_TYPE,
    FEATURE_VERSION_CONTEXT,
    SCHEMA_VERSION,
    NecessityModel,
    _char_vectorizer,
    _take_content_v5,
    _take_cross,
    _take_raw,
    _take_structured,
    build_feature_text_v5,
    split_feature_v5,
)
from llm_shield.schema import Action, Segment, Span

CALIBRATION = ROOT / "03_数据与人工复核" / "校园必要性盲标_20261101" / "返还" / "校准池"
DIAGNOSTIC = ROOT / "03_数据与人工复核" / "校园必要性盲标_20261101" / "返还" / "独立测试池"
ACTIVE = APP / "models" / "necessity_action.joblib"
ALIGNED = APP / "models" / "necessity_action_campus_aligned_20261101.joblib"
TASK = APP / "models" / "necessity_action_campus_task_20261102.joblib"
OUT = APP / "models" / "necessity_action_campus_context_20261102.joblib"
SIDE = APP / "models" / "necessity_action_campus_context_20261102.json"
OUT_DIR = APP / "outputs" / "campus_context_20261102"
BLOCKED = ("收据", "发票", "账单", "原数字", "粗略印象", "语气正式")

# 补充句只覆盖校准池里没有拉开的对照。配对诊断句不在这里。
SUPPLEMENT = [
    ("money_exact", "meeting_minutes", "BUDGET", "viewer_teacher", "student_leader", "花费按精确原样留下。"),
    ("money_exact", "meeting_minutes", "BUDGET", "viewer_teacher", "student_leader", "金额按核准后的账面数字保留。"),
    ("money_exact", "meeting_minutes", "BUDGET", "external_model", "student_leader", "花费按精确原样留下。"),
    ("money_exact", "meeting_minutes", "BUDGET", "external_model", "student_leader", "金额按核准后的账面数字保留。"),
    ("money_exact", "meeting_minutes", "BUDGET", "viewer_peer", "student_leader", "花费按精确原样留下。"),
    ("money_exact", "meeting_minutes", "BUDGET", "egress_tool_public", "student_leader", "金额按核准后的账面数字保留。"),
    ("money_magnitude", "meeting_minutes", "BUDGET", "viewer_teacher", "student_leader", "费用给一个大概范围。"),
    ("money_magnitude", "meeting_minutes", "BUDGET", "viewer_teacher", "student_leader", "只把费用写到大致量级。"),
    ("money_magnitude", "meeting_minutes", "BUDGET", "external_model", "student_leader", "费用给一个大概范围。"),
    ("money_magnitude", "meeting_minutes", "BUDGET", "external_model", "student_leader", "只把费用写到大致量级。"),
    ("money_magnitude", "meeting_minutes", "BUDGET", "viewer_peer", "student_leader", "费用给一个大概范围。"),
    ("money_magnitude", "meeting_minutes", "BUDGET", "egress_tool_public", "student_leader", "只把费用写到大致量级。"),
    ("money_drop", "meeting_minutes", "BUDGET", "viewer_teacher", "student_leader", "不要把金额写进去。"),
    ("money_drop", "meeting_minutes", "BUDGET", "viewer_teacher", "student_leader", "开支和这次整理没有关系。"),
    ("money_drop", "meeting_minutes", "BUDGET", "external_model", "student_leader", "不要把金额写进去。"),
    ("money_drop", "meeting_minutes", "BUDGET", "external_model", "student_leader", "开支和这次整理没有关系。"),
    ("money_drop", "meeting_minutes", "BUDGET", "viewer_peer", "student_leader", "不要把金额写进去。"),
    ("money_drop", "meeting_minutes", "BUDGET", "egress_tool_public", "student_leader", "开支和这次整理没有关系。"),
    ("duty_who", "class_coordination", "PERSON_NAME", "external_model", "student_leader", "把每件事分别由谁完成写出来。"),
    ("duty_who", "class_coordination", "PERSON_NAME", "viewer_teacher", "student_leader", "把每件事分别由谁完成写出来。"),
    ("duty_who", "class_coordination", "PERSON_NAME", "viewer_peer", "student_leader", "把每件事分别由谁完成写出来。"),
    ("duty_who", "class_coordination", "PERSON_NAME", "egress_tool_public", "student_leader", "把每件事分别由谁完成写出来。"),
    ("duty_who", "meeting_minutes", "PERSON_NAME", "external_model", "student_leader", "人员和事项要能对上。"),
    ("duty_who", "meeting_minutes", "PERSON_NAME", "viewer_teacher", "student_leader", "人员和事项要能对上。"),
    ("count_org", "class_coordination", "PERSON_NAME", "external_model", "student_leader", "只统计人数，不点名。"),
    ("count_org", "class_coordination", "PERSON_NAME", "egress_tool_public", "student_leader", "做成人数汇总，不点名。"),
    ("place_only", "class_coordination", "PERSON_NAME", "external_model", "student_leader", "介绍里不用出现具体的人。"),
    ("place_only", "class_coordination", "PERSON_NAME", "viewer_teacher", "student_leader", "不需要知道是哪一位。"),
    ("duty_who", "class_coordination", "PERSON_NAME", "external_model", "external_partner", "请帮外部模型改这份名单。"),
    ("money_exact", "meeting_minutes", "BUDGET", "external_model", "external_partner", "花费按精确原样留下。"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lone(category: str, text: str | None = None) -> Segment:
    body = text or SPAN_TEXT[category]
    span = Span(0, len(body), body, category, 1.0, detector="context_supplement")
    return Segment("supplement", body, 0, len(body), [span], context=body)


def from_document(row: dict) -> Segment:
    span = Span(row["start"], row["end"], row["text"][row["start"]:row["end"]], row["category"], 1.0,
                detector="calibration_reuse", rule_id="context_20261102")
    segments = segmentize(row["text"], [span])
    attach_spans(segments, [span], row["text"])
    host = next(item for item in segments if item.start <= row["start"] and row["end"] <= item.end)
    host.seg_id = row["unit_id"]
    host.spans = [span]
    return host


def training_rows() -> list[dict]:
    ledger = {item["unit_id"]: item for item in CALIBRATION_LEDGER}
    rows = []
    for path in sorted(CALIBRATION.glob("c*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for unit in document["units"]:
            entry = ledger[unit["unit_id"]]
            if not unit["recipient_id"]:
                continue
            got = executable_action(
                entry["family"], document["task_key"], unit["category"], unit["recipient_id"], unit["identity_key"])
            if got != entry["executable"]:
                raise SystemExit(f"{unit['unit_id']} 台账和监督函数不一致")
            host = from_document({
                "unit_id": unit["unit_id"], "text": document["text"], "start": unit["start"],
                "end": unit["end"], "category": unit["category"],
            })
            rows.append({
                "source": "calibration",
                "unit_id": unit["unit_id"],
                "ask": unit["user_task"],
                "label": entry["executable"],
                "historical": unit["annotation"]["canonical_action"],
                "feature": build_feature_text_v5(
                    host, document["task_key"], unit["recipient_id"],
                    task_description=unit["user_task"], identity_key=unit["identity_key"]),
            })
    for family, task, category, recipient, identity, ask in SUPPLEMENT:
        rows.append({
            "source": "supplement",
            "unit_id": "",
            "ask": ask,
            "label": executable_action(family, task, category, recipient, identity),
            "historical": "",
            "feature": build_feature_text_v5(
                lone(category), task, recipient, task_description=ask, identity_key=identity),
        })
    # 只谈金额的句子，不应把姓名留住。
    for ask in ("花费按精确原样留下。", "费用给一个大概范围。", "不要把金额写进去。"):
        for recipient in ("viewer_teacher", "external_model"):
            rows.append({
                "source": "supplement_cross",
                "unit_id": "",
                "ask": ask,
                "label": "DELETE",
                "historical": "",
                "feature": build_feature_text_v5(
                    lone("PERSON_NAME"), "meeting_minutes", recipient,
                    task_description=ask, identity_key="student_leader"),
            })
    return rows


PROBES = [
    {"group": "金额三种需求", "case_id": "A1", "task": "meeting_minutes", "category": "BUDGET",
     "text": "场地费是4300元。", "recipient": "viewer_teacher", "identity": "student_leader",
     "ask": "请按明细中的精确开支填写。", "family": "money_exact"},
    {"group": "金额三种需求", "case_id": "A2", "task": "meeting_minutes", "category": "BUDGET",
     "text": "场地费是4300元。", "recipient": "viewer_teacher", "identity": "student_leader",
     "ask": "请只说明开支的量级。", "family": "money_magnitude"},
    {"group": "金额三种需求", "case_id": "A3", "task": "meeting_minutes", "category": "BUDGET",
     "text": "场地费是4300元。", "recipient": "viewer_teacher", "identity": "student_leader",
     "ask": "这份纪要不用写开支。", "family": "money_drop"},
    {"group": "金额三种需求", "case_id": "A4", "task": "meeting_minutes", "category": "BUDGET",
     "text": "场地费是4300元。", "recipient": "external_model", "identity": "student_leader",
     "ask": "请按明细中的精确开支填写。", "family": "money_exact"},
    {"group": "金额三种需求", "case_id": "A5", "task": "meeting_minutes", "category": "BUDGET",
     "text": "场地费是4300元。", "recipient": "external_model", "identity": "student_leader",
     "ask": "请只说明开支的量级。", "family": "money_magnitude"},
    {"group": "金额三种需求", "case_id": "A6", "task": "meeting_minutes", "category": "BUDGET",
     "text": "场地费是4300元。", "recipient": "external_model", "identity": "student_leader",
     "ask": "这份纪要不用写开支。", "family": "money_drop"},
    {"group": "人员关系三种需求", "case_id": "B1", "task": "class_coordination", "category": "PERSON_NAME",
     "text": "温书宁负责开门。", "recipient": "external_model", "identity": "student_leader",
     "ask": "把值班分工写清楚，每件事能看到是谁做的。", "family": "duty_who"},
    {"group": "人员关系三种需求", "case_id": "B2", "task": "class_coordination", "category": "PERSON_NAME",
     "text": "温书宁负责开门。", "recipient": "external_model", "identity": "student_leader",
     "ask": "统计一下有几个人即可。", "family": "count_org"},
    {"group": "人员关系三种需求", "case_id": "B3", "task": "class_coordination", "category": "PERSON_NAME",
     "text": "温书宁负责开门。", "recipient": "external_model", "identity": "student_leader",
     "ask": "写一段对外介绍，不必提到具体同学。", "family": "place_only"},
    {"group": "本机查看与外部模型", "case_id": "C1", "task": "meeting_minutes", "category": "PERSON_NAME",
     "text": "温书宁负责记录。", "recipient": "viewer_teacher", "identity": "student_leader",
     "ask": "负责人要和事项对得上。", "family": "duty_who"},
    {"group": "本机查看与外部模型", "case_id": "C2", "task": "meeting_minutes", "category": "PERSON_NAME",
     "text": "温书宁负责记录。", "recipient": "external_model", "identity": "student_leader",
     "ask": "负责人要和事项对得上。", "family": "duty_who"},
    {"group": "要求保留但不能外发", "case_id": "D1", "task": "meeting_minutes", "category": "BUDGET",
     "text": "场地费是4300元。", "recipient": "external_model", "identity": "student_leader",
     "ask": "必须把精确金额原样交给外部模型。", "family": "money_exact"},
    {"group": "要求保留但不能外发", "case_id": "D2", "task": "meeting_minutes", "category": "BUDGET",
     "text": "场地费是4300元。", "recipient": "viewer_teacher", "identity": "student_leader",
     "ask": "必须把精确金额原样交给外部模型。", "family": "money_exact"},
    {"group": "同学与公开发布", "case_id": "E1", "task": "meeting_minutes", "category": "PERSON_NAME",
     "text": "温书宁负责记录。", "recipient": "viewer_peer", "identity": "student_leader",
     "ask": "负责人要和事项对得上。", "family": "duty_who"},
    {"group": "同学与公开发布", "case_id": "E2", "task": "class_coordination", "category": "PERSON_NAME",
     "text": "温书宁负责开门。", "recipient": "egress_tool_public", "identity": "student_leader",
     "ask": "把值班分工写清楚，每件事能看到是谁做的。", "family": "duty_who"},
]


def assert_separated(rows: list[dict]) -> None:
    asks = {row["ask"] for row in rows}
    probe_asks = {item["ask"] for item in PROBES}
    leaked = sorted(asks & probe_asks)
    if leaked:
        raise SystemExit("配对诊断句进入了训练集: " + "、".join(leaked))
    blob = "\n".join(row["ask"] for row in rows if row["source"] != "calibration")
    blocked = [item for item in BLOCKED if item in blob]
    if blocked:
        raise SystemExit("补充材料写入了诊断片段: " + "、".join(blocked))
    diagnostic_asks = set()
    for path in DIAGNOSTIC.glob("t*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        diagnostic_asks.add(document["user_task"])
        for unit in document["units"]:
            diagnostic_asks.add(unit["user_task"])
    overlap = sorted(asks & diagnostic_asks)
    if overlap:
        raise SystemExit("40 条诊断原话进入了训练集")
    if any("盲标_20261102" in row["ask"] for row in rows):
        raise SystemExit("训练集指向了新盲标")
    labels = set(row["label"] for row in rows)
    missing = {"DELETE", "LOCAL_AGGREGATE", "GENERALIZE", "PSEUDONYMIZE", "RETAIN", "PAUSE"} - labels
    if missing:
        raise SystemExit("训练动作缺类: " + ",".join(sorted(missing)))
    same_span = [row for row in rows if row["source"] == "supplement" and "花费按精确原样留下。" == row["ask"]]
    if len(same_span) < 2:
        raise SystemExit("同一金额说法没有覆盖不同接收方")


def fit(rows: list[dict]) -> Pipeline:
    pipeline = Pipeline([
        ("features", FeatureUnion([
            ("structured", Pipeline([
                ("take", FunctionTransformer(_take_structured)),
                ("tfidf", TfidfVectorizer(analyzer="word", token_pattern=r"\S+", ngram_range=(1, 3), min_df=1)),
            ])),
            ("raw", Pipeline([
                ("take", FunctionTransformer(_take_raw)),
                ("tfidf", _char_vectorizer()),
            ])),
            ("cross", Pipeline([
                ("take", FunctionTransformer(_take_cross)),
                ("tfidf", TfidfVectorizer(analyzer="word", token_pattern=r"\S+", ngram_range=(1, 2), min_df=1)),
            ])),
            ("content", Pipeline([
                ("take", FunctionTransformer(_take_content_v5)),
                ("tfidf", _char_vectorizer()),
            ])),
        ], transformer_weights={"structured": 1.0, "raw": 1.0, "cross": 2.0, "content": 0.0})),
        ("clf", LogisticRegression(max_iter=2000, C=1, class_weight="balanced", random_state=42)),
    ])
    pipeline.fit([row["feature"] for row in rows], [row["label"] for row in rows])
    return pipeline


def discloses(action: str, category: str) -> bool:
    if action in {"DELETE", "LOCAL_AGGREGATE", "PAUSE", "TIE", None}:
        return False
    return category in disclosed_categories(Action(action), Segment(
        "d", category, 0, len(category), [Span(0, len(category), category, category)]))


def top_two(scores: dict) -> list[dict]:
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [{"action": action, "probability": round(float(prob), 4)} for action, prob in ordered[:2]]


def run_case(models: dict, case: dict) -> dict:
    host = lone(case["category"], case["text"])
    expected = executable_action(case["family"], case["task"], case["category"], case["recipient"], case["identity"])
    item = {
        "group": case["group"], "case_id": case["case_id"], "ask": case["ask"],
        "category": case["category"], "recipient": case["recipient"], "text": case["text"],
        "reference_executable": expected, "reference_is_human": False,
    }
    features = [
        build_feature_text_v5(host, case["task"], case["recipient"], task_description=ask, identity_key=case["identity"])
        for ask in {row["ask"] for row in PROBES if row["text"] == case["text"] and row["recipient"] == case["recipient"]
                    and row["category"] == case["category"] and row["task"] == case["task"]}
    ]
    parts = [split_feature_v5(feature) for feature in features]
    item["raw_inputs_differ"] = len({part[1] for part in parts}) == len(parts)
    item["structured_same_within_recipient"] = len({part[0] for part in parts}) == 1
    for name, model in models.items():
        decision = decide_segment(
            host, case["task"], case["recipient"], case["identity"],
            necessity_scorer=model.score, task_description=case["ask"])
        scores = {action.value: float(decision.necessity_scores.get(action.value, 0.0)) for action in Action}
        item[name] = {
            "argmax": max(scores, key=scores.get),
            "pipeline": decision.action.value,
            "top": top_two(scores),
        }
    return item


def development_rows() -> list[dict]:
    rows = []
    for path in sorted(DIAGNOSTIC.glob("t*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for unit in document["units"]:
            family, executable = EXPECT[unit["unit_id"]]
            rows.append({
                "unit_id": unit["unit_id"],
                "text": document["text"],
                "start": unit["start"],
                "end": unit["end"],
                "category": unit["category"],
                "task_key": document["task_key"],
                "recipient_id": unit["recipient_id"],
                "identity_key": unit["identity_key"],
                "user_task": unit["user_task"],
                "historical": unit["annotation"]["canonical_action"],
                "executable": executable,
                "family": family,
            })
    if len(rows) != 40:
        raise SystemExit("诊断材料不是 40 条")
    return rows


def score_development(models: dict, rows: list[dict]) -> list[dict]:
    scored = []
    for row in rows:
        host = from_document(row)
        item = {key: row[key] for key in ("unit_id", "category", "historical", "executable")}
        for name, model in models.items():
            decision = decide_segment(
                host, row["task_key"], row["recipient_id"], row["identity_key"],
                necessity_scorer=model.score, task_description=row["user_task"])
            scores = {action.value: float(decision.necessity_scores.get(action.value, 0.0)) for action in Action}
            item[f"{name}_argmax"] = max(scores, key=scores.get)
            item[f"{name}_pipeline"] = decision.action.value
        scored.append(item)
    return scored


def summarize_development(rows: list[dict], name: str) -> dict:
    leaked = [row["unit_id"] for row in rows
              if discloses(row[f"{name}_pipeline"], row["category"]) and not discloses(row["executable"], row["category"])]
    return {
        "historical_argmax": sum(row[f"{name}_argmax"] == row["historical"] for row in rows),
        "executable_argmax": sum(row[f"{name}_argmax"] == row["executable"] for row in rows),
        "executable_pipeline": sum(row[f"{name}_pipeline"] == row["executable"] for row in rows),
        "constraint_rewrites": sum(row[f"{name}_argmax"] != row[f"{name}_pipeline"] for row in rows),
        "unnecessary_disclosure": leaked,
    }


def main() -> None:
    if OUT.resolve() in {ACTIVE.resolve(), ALIGNED.resolve(), TASK.resolve()}:
        raise SystemExit("拒绝覆盖已有权重")
    before = {path.name: sha256(path) for path in (ACTIVE, ALIGNED, TASK)}
    rows = training_rows()
    assert_separated(rows)
    pipeline = fit(rows)
    import joblib
    import sklearn
    artifact = {
        "artifact_type": ARTIFACT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "feature_version": FEATURE_VERSION_CONTEXT,
        "classes": [str(item) for item in pipeline.classes_],
        "pipeline": pipeline,
        "validation": {"not_campus_accuracy": True, "paired_cases_are_not_human_scores": True},
        "content_weight": 0.0,
        "raw_demand_weight": 1.0,
        "cross_demand_weight": 2.0,
        "training_metadata": {
            "calibration_rows": sum(row["source"] == "calibration" for row in rows),
            "supplement_rows": sum(row["source"] != "calibration" for row in rows),
            "label_counts": dict(Counter(row["label"] for row in rows)),
            "historical_labels_overwritten": False,
            "diagnostic_40_used_for_training": False,
            "blind_31_used": False,
        },
        "limitation": "单次实验。整句需求进入字符特征，原文片段权重为 0。配对案例由实验脚本生成，不是人工测试成绩。活动权重未替换。",
        "sklearn_version": sklearn.__version__,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, OUT)
    loaded = {
        "active": NecessityModel(ACTIVE),
        "aligned": NecessityModel(ALIGNED),
        "task": NecessityModel(TASK),
        "context": NecessityModel(OUT),
    }
    for name, model in loaded.items():
        if not model.available:
            raise SystemExit(f"{name} 不可用：{model.reason}")
    probes = [run_case(loaded, case) for case in PROBES]
    developed = score_development(loaded, development_rows())
    after = {path.name: sha256(path) for path in (ACTIVE, ALIGNED, TASK)}
    if after != before:
        raise SystemExit("已有权重在实验中发生变化")
    context_hits = sum(item["context"]["pipeline"] == item["reference_executable"] for item in probes)
    summary = {
        "single_fit": True,
        "rows": len(rows),
        "label_counts": dict(Counter(row["label"] for row in rows)),
        "probe_pipeline_hits": context_hits,
        "probe_total": len(probes),
        "probe_source": "ai_mechanism_cases_not_human_test",
        "development_40_not_used_for_training": True,
        "development": {name: summarize_development(developed, name) for name in loaded},
        "sha256": sha256(OUT),
        "active_sha256": after[ACTIVE.name],
        "weights_unchanged": True,
        "promoted": False,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "experiment.json").write_text(json.dumps({
        "summary": summary,
        "probes": probes,
        "development": developed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    SIDE.write_text(json.dumps({
        "status": "not_promoted",
        "trained_on": "2026-11-02",
        "path": "delivery/app/models/necessity_action_campus_context_20261102.joblib",
        "sha256": summary["sha256"],
        "active_sha256": summary["active_sha256"],
        "promoted": False,
        "feature_version": FEATURE_VERSION_CONTEXT,
        "content_weight": 0.0,
        "diagnostic_40_used_for_training": False,
        "reason": "一次任务上下文实验。配对案例不是人工测试成绩。活动权重未替换。",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for item in probes:
        print(item["case_id"], item["reference_executable"],
              {name: item[name]["pipeline"] for name in loaded})


if __name__ == "__main__":
    main()
