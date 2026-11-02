"""用可执行监督标签训练一份任务需求候选。

先确认同一金额的三种需求进入不同的需求段，再拟合。
不读独立测试池，不改活动权重，不改硬约束，也不覆盖已有候选。
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
from sklearn.metrics import f1_score
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import FunctionTransformer

from campus_task_labels_20261102 import (
    ASKS,
    CALIBRATION_LEDGER,
    FAMILIES,
    IDENTITIES,
    RECIPIENTS,
    SPAN_TEXT,
    TASKS,
    check_ledger,
    executable_action,
)
from llm_shield.m4_necessity.model import (
    ARTIFACT_TYPE,
    DEMAND_SPLIT,
    FEATURE_SPLIT,
    FEATURE_VERSION_TASK,
    SCHEMA_VERSION,
    NecessityModel,
    _char_vectorizer,
    _take_content_after_demand,
    _take_demand,
    _take_structured,
    build_feature_text,
    build_feature_text_v4,
    split_feature_v4,
)
from llm_shield.schema import Segment, Span

ACTIVE = APP / "models" / "necessity_action.joblib"
FROZEN = APP / "models" / "necessity_action_campus_candidate.joblib"
ALIGNED = APP / "models" / "necessity_action_campus_aligned_20261101.joblib"
OUT = APP / "models" / "necessity_action_campus_task_20261102.joblib"
SIDE = APP / "models" / "necessity_action_campus_task_20261102.json"
OUT_DIR = APP / "outputs" / "campus_necessity_task_20261102"
CALIBRATION = ROOT / "03_数据与人工复核" / "校园必要性盲标_20261101" / "返还" / "校准池"
PROBE_AMOUNT = "费用是8600元。"
PROBE_ASKS = (
    "这笔开支按核准数额保留。",
    "这笔开支只说明量级。",
    "这笔开支不要写。",
)
BLOCKED_FRAGMENTS = (
    "收据", "发票", "账单", "原数字", "原数", "粗略印象", "语气正式",
    "柏景行", "俞清晏", "傅晚桐", "姜书迟", "倪星澜", "校登山社",
    "7350", "15280", "经管楼", "山脚校门",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def segment_for(category: str) -> Segment:
    text = SPAN_TEXT[category]
    span = Span(0, len(text), text, category, 1.0, detector="task_candidate")
    return Segment("synthetic", text, 0, len(text), [span], context=text)


def probe() -> dict:
    """同一金额、同一接收方，三种需求必须只改需求段。"""
    host = Segment("probe", PROBE_AMOUNT, 0, len(PROBE_AMOUNT), [
        Span(0, len(PROBE_AMOUNT), PROBE_AMOUNT, "BUDGET", 1.0, detector="probe")
    ])
    rows = []
    for ask in PROBE_ASKS:
        feature = build_feature_text_v4(
            host, "meeting_minutes", "external_model",
            task_description=ask, identity_key="student_leader")
        structured, demand, content = split_feature_v4(feature)
        old = build_feature_text(
            host, "meeting_minutes", "external_model",
            task_description=ask, identity_key="student_leader")
        rows.append({
            "ask": ask,
            "feature": feature,
            "structured": structured,
            "demand": demand,
            "content": content,
            "v3_structured": old.partition(FEATURE_SPLIT)[0],
            "v3_content": old.partition(FEATURE_SPLIT)[2],
        })
    demands = [row["demand"] for row in rows]
    structured_same = len({row["structured"] for row in rows}) == 1
    content_same = len({row["content"] for row in rows}) == 1
    demand_distinct = len(set(demands)) == 3
    v3_structured_same = len({row["v3_structured"] for row in rows}) == 1
    v3_content_distinct = len({row["v3_content"] for row in rows}) == 3
    markers = all(FEATURE_SPLIT in row["feature"] and DEMAND_SPLIT in row["feature"] for row in rows)
    permission = all(
        "[BOUNDARY]external_generation" in row["structured"]
        and "[RECIPIENT]external_model" in row["structured"]
        and "[SEND]1" in row["structured"]
        and "[RESTORE]0" in row["structured"]
        and "[BANNED]1" in row["structured"]
        for row in rows
    )
    not_training_asks = all(ask not in {item["train"] for item in ASKS.values()} | {item["valid"] for item in ASKS.values()}
                            for ask in PROBE_ASKS)
    ok = all((
        structured_same, content_same, demand_distinct, v3_structured_same,
        v3_content_distinct, markers, permission, not_training_asks,
        all(row["feature"].startswith(f"[SCHEMA]{FEATURE_VERSION_TASK} ") for row in rows),
        all(row["v3_structured"].startswith("[SCHEMA]3 ") for row in rows),
        "[BOUNDARY]" not in rows[0]["v3_structured"],
    ))
    return {
        "ok": ok,
        "structured_same": structured_same,
        "content_same": content_same,
        "demand_distinct": demand_distinct,
        "v3_structured_same": v3_structured_same,
        "v3_content_changes_but_old_candidate_zeroed_that_channel": v3_content_distinct,
        "permission_tokens_present": permission,
        "demands": demands,
        "asks": list(PROBE_ASKS),
    }


def iter_rows(split: str) -> list[dict]:
    rows = []
    for identity in IDENTITIES:
        for family in FAMILIES:
            ask = ASKS[family][split]
            for task in TASKS:
                for category in SPAN_TEXT:
                    host = segment_for(category)
                    for recipient in RECIPIENTS:
                        label = executable_action(family, task, category, recipient, identity)
                        feature = build_feature_text_v4(
                            host, task, recipient, task_description=ask, identity_key=identity)
                        rows.append({
                            "feature": feature,
                            "label": label,
                            "family": family,
                            "task": task,
                            "category": category,
                            "recipient": recipient,
                            "identity": identity,
                            "ask": ask,
                            "source_case_id": f"{split}-{identity}-{family}-{category}",
                        })
    return rows


def assert_clean(rows: list[dict], quotes: set[str]) -> None:
    features = [row["feature"] for row in rows]
    if len(features) != len(set(features)):
        raise SystemExit("训练特征出现重复，需求段没有分开样本")
    blob = "\n".join(features)
    leaked = [quote for quote in quotes if quote and quote in blob]
    if leaked:
        raise SystemExit("训练特征写入了校准原文: " + "、".join(leaked[:8]))
    blocked = [fragment for fragment in BLOCKED_FRAGMENTS if fragment in blob]
    if blocked:
        raise SystemExit("训练特征写入了诊断或校准片段: " + "、".join(blocked))
    if any(not feature.startswith(f"[SCHEMA]{FEATURE_VERSION_TASK} ") or DEMAND_SPLIT not in feature
           for feature in features):
        raise SystemExit("特征版本不对")


def fit(train: list[dict], valid: list[dict]) -> Pipeline:
    pipeline = Pipeline([
        ("features", FeatureUnion([
            ("structured", Pipeline([
                ("take", FunctionTransformer(_take_structured)),
                ("tfidf", TfidfVectorizer(analyzer="word", token_pattern=r"\S+", ngram_range=(1, 3), min_df=1)),
            ])),
            ("demand", Pipeline([
                ("take", FunctionTransformer(_take_demand)),
                ("tfidf", TfidfVectorizer(analyzer="word", token_pattern=r"\S+", ngram_range=(1, 3), min_df=1)),
            ])),
            ("content", Pipeline([
                ("take", FunctionTransformer(_take_content_after_demand)),
                ("tfidf", _char_vectorizer()),
            ])),
        ], transformer_weights={"structured": 1.0, "demand": 3.0, "content": 0.0})),
        ("clf", LogisticRegression(max_iter=2000, C=4, class_weight="balanced", random_state=42)),
    ])
    pipeline.fit([row["feature"] for row in train], [row["label"] for row in train])
    return pipeline


def predicted(pipeline: Pipeline, family: str, task: str, category: str,
              recipient: str, identity: str, split: str) -> str:
    feature = build_feature_text_v4(
        segment_for(category), task, recipient,
        task_description=ASKS[family][split], identity_key=identity)
    return str(pipeline.predict([feature])[0])


def gate(pipeline: Pipeline) -> list[dict]:
    expect = [
        ("money_exact", "meeting_minutes", "BUDGET", "viewer_teacher", "RETAIN"),
        ("money_magnitude", "meeting_minutes", "BUDGET", "viewer_teacher", "GENERALIZE"),
        ("money_drop", "meeting_minutes", "BUDGET", "viewer_teacher", "DELETE"),
        ("money_exact", "meeting_minutes", "BUDGET", "external_model", "PAUSE"),
        ("money_magnitude", "meeting_minutes", "BUDGET", "external_model", "PAUSE"),
        ("money_drop", "meeting_minutes", "BUDGET", "external_model", "DELETE"),
        ("plain", "meeting_minutes", "PERSON_NAME", "external_model", "PSEUDONYMIZE"),
        ("plain", "meeting_minutes", "PERSON_NAME", "viewer_teacher", "RETAIN"),
        ("duty_who", "class_coordination", "PERSON_NAME", "external_model", "PSEUDONYMIZE"),
        ("duty_who", "class_coordination", "LOCATION", "external_model", "DELETE"),
        ("place_only", "activity_notice", "LOCATION", "external_model", "RETAIN"),
        ("place_only", "activity_notice", "PERSON_NAME", "external_model", "DELETE"),
        ("duty_who", "class_coordination", "PERSON_NAME", "egress_tool_public", "PAUSE"),
        ("grade_omit", "coursework_grades", "GRADE", "viewer_teacher", "DELETE"),
        ("grade_omit", "coursework_grades", "PERSON_NAME", "viewer_teacher", "RETAIN"),
        ("count_org", "activity_stats", "PERSON_NAME", "external_model", "LOCAL_AGGREGATE"),
        ("money_exact", "meeting_minutes", "PERSON_NAME", "viewer_peer", "PSEUDONYMIZE"),
    ]
    rows = []
    for family, task, category, recipient, label in expect:
        got = predicted(pipeline, family, task, category, recipient, "student_leader", "valid")
        rows.append({"family": family, "task": task, "category": category, "recipient": recipient,
                     "identity": "student_leader", "expect": label, "got": got, "ok": got == label})
    got = predicted(pipeline, "duty_who", "class_coordination", "PERSON_NAME",
                    "external_model", "external_partner", "valid")
    rows.append({"family": "duty_who", "task": "class_coordination", "category": "PERSON_NAME",
                 "recipient": "external_model", "identity": "external_partner",
                 "expect": "PAUSE", "got": got, "ok": got == "PAUSE"})
    return rows


def load_quotes() -> set[str]:
    quotes = set()
    for path in CALIBRATION.glob("c*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        for unit in document["units"]:
            if unit.get("quote"):
                quotes.add(unit["quote"])
    return quotes


def main() -> None:
    if "独立测试池" in str(CALIBRATION):
        raise SystemExit("训练入口不能指向独立测试池")
    if OUT.resolve() in {ACTIVE.resolve(), FROZEN.resolve(), ALIGNED.resolve()}:
        raise SystemExit("拒绝覆盖活动权重或已有候选")
    mismatches = check_ledger()
    if mismatches:
        raise SystemExit("可执行标签和校准台账不一致: " + json.dumps(mismatches, ensure_ascii=False))
    report = probe()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "demand_probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "demands"}, ensure_ascii=False))
    if not report["ok"]:
        raise SystemExit("三种需求没有形成不同的有效输入，停止训练")
    if "--probe-only" in sys.argv:
        return
    before = {path.name: sha256(path) for path in (ACTIVE, FROZEN, ALIGNED)}
    calibration_hashes = {path.name: sha256(path) for path in sorted(CALIBRATION.glob("c*.json"))}
    quotes = load_quotes()
    train = iter_rows("train")
    valid = iter_rows("valid")
    assert_clean(train + valid, quotes)
    labels = Counter(row["label"] for row in train)
    if set(labels) != {"DELETE", "LOCAL_AGGREGATE", "GENERALIZE", "PSEUDONYMIZE", "RETAIN", "PAUSE"}:
        raise SystemExit(f"动作覆盖不全: {dict(labels)}")
    pipeline = fit(train, valid)
    valid_pred = pipeline.predict([row["feature"] for row in valid])
    valid_labels = [row["label"] for row in valid]
    accuracy = float(pipeline.score([row["feature"] for row in valid], valid_labels))
    macro = float(f1_score(valid_labels, valid_pred, average="macro", zero_division=0))
    checks = gate(pipeline)
    if any(not row["ok"] for row in checks):
        print(json.dumps([row for row in checks if not row["ok"]], ensure_ascii=False))
        raise SystemExit("留出说法没有达到可执行动作门槛，不保存候选")
    import joblib
    import sklearn
    artifact = {
        "artifact_type": ARTIFACT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "feature_version": FEATURE_VERSION_TASK,
        "classes": [str(item) for item in pipeline.classes_],
        "pipeline": pipeline,
        "validation": {
            "split": "heldout_demand_wording",
            "accuracy": round(accuracy, 4),
            "macro_f1": round(macro, 4),
            "train_rows": len(train),
            "validation_rows": len(valid),
            "not_campus_accuracy": True,
            "test_pool_read": False,
            "gate_passed": all(row["ok"] for row in checks),
            "gate_failed": [row for row in checks if not row["ok"]],
        },
        "content_weight": 0.0,
        "demand_weight": 3.0,
        "training_metadata": {
            "label_source": "executable_action_from_calibration_norm",
            "historical_labels_overwritten": False,
            "calibration_units_in_ledger": len(CALIBRATION_LEDGER),
            "calibration_quotes_in_training_text": False,
            "test_pool_read": False,
            "structured_analyzer": "word_ngram_1_3",
            "demand_analyzer": "category_char_word_ngram_1_3",
            "label_counts": dict(labels),
            "identities": list(IDENTITIES),
            "tasks": list(TASKS),
        },
        "limitation": "候选按用户任务原话和现有权限学习可执行动作。原话的每个字与类别绑在同一个词上，需求段权重为 3，原文段权重为 0。活动权重未替换。合成留出分不是校园准确率。外部、同学和公开发布的预算仍不可送出。",
        "sklearn_version": sklearn.__version__,
    }
    joblib.dump(artifact, OUT)
    loaded = NecessityModel(OUT)
    if not loaded.available or loaded.metadata.get("feature_version") != FEATURE_VERSION_TASK:
        raise SystemExit(loaded.reason)
    after = {path.name: sha256(path) for path in (ACTIVE, FROZEN, ALIGNED)}
    if after != before:
        raise SystemExit("活动权重或旧候选哈希发生变化")
    if {path.name: sha256(path) for path in sorted(CALIBRATION.glob("c*.json"))} != calibration_hashes:
        raise SystemExit("校准原件被改写")
    summary = {
        "probe_ok": True,
        "train_rows": len(train),
        "validation_accuracy": round(accuracy, 4),
        "validation_macro_f1": round(macro, 4),
        "label_counts": dict(labels),
        "gate_passed": sum(row["ok"] for row in checks),
        "gate_total": len(checks),
        "gate_failed": [row for row in checks if not row["ok"]],
        "sha256": sha256(OUT),
        "active_sha256": after[ACTIVE.name],
        "weights_unchanged": True,
        "historical_labels_overwritten": False,
    }
    (OUT_DIR / "train_fit.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    SIDE.write_text(json.dumps({
        "status": "not_promoted",
        "trained_on": "2026-11-02",
        "path": "delivery/app/models/necessity_action_campus_task_20261102.joblib",
        "sha256": summary["sha256"],
        "active_path": "delivery/app/models/necessity_action.joblib",
        "active_sha256": summary["active_sha256"],
        "promoted": False,
        "feature_version": FEATURE_VERSION_TASK,
        "test_pool_used_for_training": False,
        "reason": "任务需求进入独立特征通道。活动权重未替换。40 条诊断材料未用于训练。",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
