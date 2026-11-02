"""用 2026-11-01 校准池的对齐标签训练一份新候选。

不读取独立测试池，不覆盖活动权重，也不覆盖已经冻结的校园候选。
训练句子是另写的短句。校准原文不进入训练集，只在训练结束后做迁移核对。
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

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import FunctionTransformer

from llm_shield.m2_detect.pipeline import attach_spans, segmentize
from llm_shield.m3_decide.decision import decide_segment
from llm_shield.m4_necessity.model import (
    ARTIFACT_TYPE,
    FEATURE_SPLIT,
    FEATURE_VERSION,
    SCHEMA_VERSION,
    NecessityModel,
    _char_vectorizer,
    _take_content,
    _take_structured,
    build_feature_text,
)
from llm_shield.schema import Action, Segment, Span

ACTIVE = APP / "models" / "necessity_action.joblib"
FROZEN = APP / "models" / "necessity_action_campus_candidate.joblib"
OUT = APP / "models" / "necessity_action_campus_aligned_20261101.joblib"
CALIBRATION = ROOT / "03_数据与人工复核" / "校园必要性盲标_20261101" / "返还" / "校准池"
FIT_OUT = APP / "outputs" / "campus_necessity_aligned_20261101" / "calibration_fit.json"

TEXTS = {
    "PERSON_NAME": ["赵启明到场。", "钱书宁负责海报。", "孙望舒核对名单。", "吴清和搬桌子。"],
    "PHONE": ["联系电话13911110001。", "手机13911110002。", "值班电话13911110003。", "临时号13911110004。"],
    "EMAIL": ["邮箱zhao@example.edu。", "收件qian@example.edu。", "公共信箱sun@example.edu。", "备份wu@example.edu。"],
    "ORG": ["主办方是读书会。", "单位是校团委。", "社团是辩论队。", "部门是学习部。"],
    "LOCATION": ["地点在文理楼。", "集合在图书馆。", "会议室在文科楼。", "场地在操场。"],
    "DORM": ["住在梅园1号楼。", "房间是兰园2号楼。", "宿舍在菊园3号楼。", "楼栋是荷园4号楼。"],
    "BUDGET": ["费用是8600元。", "报价2400元。", "开支9750元。", "预算是5300元。"],
    "GRADE": ["成绩是76分。", "得分是81分。", "测验是64分。", "作业是90分。"],
    "STUDENT_ID": ["学号2024110001。", "学号2024110002。", "学号2024110003。", "学号2024110004。"],
    "ID_CARD": ["证件110101199001011234。", "证件110101199002021235。", "证件110101199003031236。", "证件110101199004041237。"],
    "BANK_CARD": ["卡号6222020000000000111。", "卡号6222020000000000222。", "卡号6222020000000000333。", "卡号6222020000000000444。"],
    "API_KEY": ["密钥sk-test-aaaa。", "密钥sk-test-bbbb。", "密钥sk-test-cccc。", "密钥sk-test-dddd。"],
    "WECHAT": ["微信wx_alpha。", "微信wx_beta。", "微信wx_gamma。", "微信wx_delta。"],
    "SENSITIVE_ATTR": ["患有慢性胃病。", "正在复查血压。", "家庭收入偏低。", "近期睡眠不好。"],
}
TASKS = ["activity_notice", "activity_stats", "meeting_minutes", "project_intro", "class_coordination"]
RECIPIENTS = ["external_model", "viewer_teacher", "viewer_peer", "egress_tool_public"]
DESCRIPTION = "整理成可发送的文本。"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_calibration() -> list[dict]:
    if "独立测试池" in str(CALIBRATION):
        raise SystemExit("训练入口不能指向独立测试池")
    rows = []
    for path in sorted(CALIBRATION.glob("c*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("pool") != "calibration":
            raise SystemExit(f"{path.name} 不是校准池")
        for unit in document["units"]:
            action = unit["annotation"]["canonical_action"]
            if action not in Action._value2member_map_:
                raise SystemExit(f"{unit['unit_id']} 没有对齐动作")
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
                "action": action,
            })
    if len(rows) != 20:
        raise SystemExit(f"校准条目不是 20: {len(rows)}")
    return rows


def override_table(rows: list[dict]) -> tuple[dict, list[str]]:
    """同一任务、类别、接收方只能有一个对齐动作。接收方为空的条目不进入表。"""
    table = {}
    skipped = []
    for row in rows:
        if not row["recipient_id"]:
            skipped.append(row["unit_id"])
            continue
        key = (row["task_key"], row["category"], row["recipient_id"])
        previous = table.get(key)
        if previous is not None and previous != row["action"]:
            raise SystemExit(f"校准标签冲突: {key} {previous} / {row['action']}")
        table[key] = row["action"]
    return table, skipped


def segment(text: str, category: str) -> Segment:
    span = Span(0, len(text), text, category, 1.0, detector="synthetic_aligned")
    return Segment("synthetic", text, 0, len(text), [span], context=text)


def rows_for(model: NecessityModel, table: dict, texts_slice: slice, source: str) -> list[dict]:
    rows = []
    for category, texts in TEXTS.items():
        for index, text in enumerate(texts[texts_slice]):
            seg = segment(text, category)
            for task in TASKS:
                for recipient in RECIPIENTS:
                    teacher = max(model.score(
                        seg, task, recipient, task_description=DESCRIPTION, identity_key="student_leader"
                    ).items(), key=lambda item: item[1])[0]
                    label = table.get((task, category, recipient), teacher)
                    feature = build_feature_text(
                        seg, task, recipient, task_description=DESCRIPTION, identity_key="student_leader")
                    rows.append({
                        "feature": feature,
                        "label": label,
                        "task": task,
                        "category": category,
                        "recipient": recipient,
                        "source": source,
                        "changed": label != teacher,
                        "source_case_id": f"{source}-{category}-{index}",
                    })
    return rows


def fit(train: list[dict], valid: list[dict]) -> dict:
    pipeline = Pipeline([
        ("features", FeatureUnion([
            ("structured", Pipeline([
                ("take", FunctionTransformer(_take_structured)),
                ("tfidf", TfidfVectorizer(
                    analyzer="word", token_pattern=r"\S+", ngram_range=(1, 3), min_df=1)),
            ])),
            ("content", Pipeline([
                ("take", FunctionTransformer(_take_content)),
                ("tfidf", _char_vectorizer()),
            ])),
        ], transformer_weights={"structured": 1.0, "content": 0.0})),
        ("clf", LogisticRegression(max_iter=2000, C=10, random_state=42)),
    ])
    features = [row["feature"] for row in train]
    labels = [row["label"] for row in train]
    if any(FEATURE_SPLIT not in feature or not feature.startswith(f"[SCHEMA]{FEATURE_VERSION} ") for feature in features):
        raise SystemExit("特征版本不对")
    pipeline.fit(features, labels)
    valid_features = [row["feature"] for row in valid]
    valid_labels = [row["label"] for row in valid]
    predicted = pipeline.predict(valid_features)
    return {
        "pipeline": pipeline,
        "classes": [str(item) for item in pipeline.classes_],
        "validation_accuracy": float(pipeline.score(valid_features, valid_labels)),
        "validation_macro_f1": float(f1_score(valid_labels, predicted, average="macro", zero_division=0)),
    }


def one_span(text: str, unit_id: str, start: int, end: int, category: str) -> Segment:
    span = Span(start, end, text[start:end], category, 1.0, detector="given_annotation", rule_id="aligned_calibration")
    segments = segmentize(text, [span])
    attach_spans(segments, [span], text)
    host = next(item for item in segments if item.start <= start and end <= item.end)
    host.seg_id = unit_id
    host.spans = [span]
    return host


def score_units(model: NecessityModel, rows: list[dict]) -> list[dict]:
    scored = []
    for row in rows:
        if not row["recipient_id"]:
            scored.append({
                "unit_id": row["unit_id"], "gold": row["action"], "model_called": False,
                "model_argmax": None, "pipeline_action": None, "pipeline_reason": "recipient_missing",
            })
            continue
        segment_host = one_span(row["text"], row["unit_id"], row["start"], row["end"], row["category"])
        decision = decide_segment(
            segment_host, row["task_key"], row["recipient_id"], row["identity_key"],
            necessity_scorer=model.score, task_description=row["user_task"],
        )
        scores = {action: float(decision.necessity_scores.get(action, 0.0)) for action in Action}
        top = max(scores.values())
        winners = [action for action, prob in scores.items() if abs(prob - top) <= 1e-12]
        scored.append({
            "unit_id": row["unit_id"],
            "task_key": row["task_key"],
            "category": row["category"],
            "recipient_id": row["recipient_id"],
            "quote": row["quote"],
            "gold": row["action"],
            "model_called": True,
            "model_argmax": winners[0] if len(winners) == 1 else "TIE",
            "pipeline_action": decision.action.value,
            "pipeline_reason": decision.reason,
        })
    return scored


def main() -> None:
    if OUT.resolve() in {ACTIVE.resolve(), FROZEN.resolve()}:
        raise SystemExit("拒绝覆盖活动权重或已冻结候选")
    quotes = {row["quote"] for row in load_calibration()}
    blob = json.dumps(TEXTS, ensure_ascii=False)
    leaked = [quote for quote in quotes if quote and quote in blob]
    if leaked:
        raise SystemExit("合成训练句撞上校准原文: " + "、".join(leaked))
    before_active = sha256(ACTIVE)
    before_frozen = sha256(FROZEN)
    teacher = NecessityModel(ACTIVE)
    if not teacher.available:
        raise SystemExit(teacher.reason)
    calibration = load_calibration()
    table, skipped = override_table(calibration)
    train = []
    for row in rows_for(teacher, table, slice(0, 2), "train"):
        train.append(row)
    valid = rows_for(teacher, table, slice(2, 4), "valid")
    for row in train + valid:
        if any(quote and quote in row["feature"] for quote in quotes):
            raise SystemExit("训练特征写入了校准原文")
    fitted = fit(train, valid)
    import joblib
    import sklearn
    artifact = {
        "artifact_type": ARTIFACT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "feature_version": FEATURE_VERSION,
        "classes": fitted["classes"],
        "pipeline": fitted["pipeline"],
        "validation": {
            "split": "synthetic_disjoint_texts",
            "accuracy": round(fitted["validation_accuracy"], 4),
            "macro_f1": round(fitted["validation_macro_f1"], 4),
            "train_rows_after_repeat": len(train),
            "validation_rows": len(valid),
            "not_campus_accuracy": True,
            "test_pool_read": False,
        },
        "content_weight": 0.0,
        "training_metadata": {
            "teacher": "necessity_action.joblib",
            "label_source": "03_数据与人工复核/校园必要性盲标_20261101/返还/校准池",
            "calibration_units": 20,
            "calibration_units_in_override_table": 20 - len(skipped),
            "skipped_missing_recipient": skipped,
            "calibration_quotes_in_training_text": False,
            "test_pool_read": False,
            "structured_analyzer": "word_ngram_1_3",
            "override_table": [
                {"task_key": task, "category": category, "recipient_id": recipient, "action": action}
                for (task, category, recipient), action in sorted(table.items())
            ],
        },
        "limitation": "候选按校准池的任务、类别、接收方这一格学习对齐动作。结构化特征取相邻三个词，内容权重为 0。会议纪要发给外部模型的预算整格都是泛化，当前特征分不开粗略金额和精确金额。合成留出分不是校园准确率。活动权重未替换。",
        "sklearn_version": sklearn.__version__,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, OUT)
    if sha256(ACTIVE) != before_active or sha256(FROZEN) != before_frozen:
        OUT.unlink(missing_ok=True)
        raise SystemExit("训练过程改动了活动权重或已冻结候选")
    aligned = NecessityModel(OUT)
    if not aligned.available:
        raise SystemExit(aligned.reason)
    gold_rows = score_units(aligned, calibration)
    active_rows = score_units(teacher, calibration)
    called = [row for row in gold_rows if row["model_called"]]
    report = {
        "aligned_model_sha256": sha256(OUT),
        "active_model_sha256": sha256(ACTIVE),
        "frozen_candidate_sha256": sha256(FROZEN),
        "active_unchanged": sha256(ACTIVE) == before_active,
        "frozen_unchanged": sha256(FROZEN) == before_frozen,
        "test_pool_read": False,
        "skipped_missing_recipient": skipped,
        "override_count": len(table),
        "synthetic_validation_accuracy": round(fitted["validation_accuracy"], 4),
        "synthetic_validation_is_not_campus_accuracy": True,
        "calibration_argmax_matched": sum(row["gold"] == row["model_argmax"] for row in called),
        "calibration_called": len(called),
        "calibration_pipeline_matched": sum(row["gold"] == row["pipeline_action"] for row in called),
        "active_argmax_matched": sum(
            gold["gold"] == active["model_argmax"]
            for gold, active in zip(gold_rows, active_rows) if gold["model_called"]
        ),
        "units": [
            {
                "unit_id": gold["unit_id"],
                "gold": gold["gold"],
                "aligned_argmax": gold["model_argmax"],
                "aligned_pipeline": gold["pipeline_action"],
                "active_argmax": active["model_argmax"],
                "pipeline_reason": gold["pipeline_reason"],
            }
            for gold, active in zip(gold_rows, active_rows)
        ],
        "changed_label_counts": dict(Counter(row["label"] for row in train if row["changed"])),
    }
    FIT_OUT.parent.mkdir(parents=True, exist_ok=True)
    FIT_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "override_count": report["override_count"],
        "skipped": skipped,
        "synthetic_validation_accuracy": report["synthetic_validation_accuracy"],
        "calibration_argmax": f"{report['calibration_argmax_matched']}/{report['calibration_called']}",
        "calibration_pipeline": f"{report['calibration_pipeline_matched']}/{report['calibration_called']}",
        "active_argmax": f"{report['active_argmax_matched']}/{report['calibration_called']}",
        "aligned_sha256": report["aligned_model_sha256"],
        "weights_unchanged": report["active_unchanged"] and report["frozen_unchanged"],
    }, ensure_ascii=False, indent=2))
    misses = [row for row in report["units"] if row["aligned_argmax"] != row["gold"] and row["aligned_argmax"] is not None]
    print("argmax_misses", json.dumps(misses, ensure_ascii=False))


if __name__ == "__main__":
    main()
