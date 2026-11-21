"""训练校园必要性候选权重，不替换活动模型，也不读取 38 条辅助标签。

教师是当前 necessity_action.joblib。只改三类已经三方一致的在线动作：
活动通知的外部人名改为删除，班级协作的外部人名改为稳定代号，
会议纪要在任务只要求大致花费时把预算改为泛化。
结构化特征按整词编码，避免 activity_notice 和 activity_stats 的字符片段混在一起。
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, f1_score
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import FunctionTransformer

from llm_shield.m4_necessity.model import (
    ARTIFACT_TYPE,
    CONTENT_WEIGHT,
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
OUT = APP / "models" / "necessity_action_campus_candidate.joblib"

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
MAGNITUDE = ["只要大致花费。", "写出大约水平即可。", "保留量级，不要精确到元。", "说明大概花多少。", "写出大致水平就行。"]
EXACT = ["核对精确金额。", "保留到元的原数。", "按报价单逐项核算。", "需要准确数字。"]
GENERIC = "整理成可发送的文本。"


def segment(text: str, category: str) -> Segment:
    span = Span(0, len(text), text, category, 1.0, detector="synthetic_candidate")
    return Segment("synthetic", text, 0, len(text), [span], context=text)


def magnitude_request(description: str) -> bool:
    return any(token in description for token in ("大致", "大约", "量级", "大概"))


def exact_request(description: str) -> bool:
    return any(token in description for token in ("精确", "原数", "核算", "准确数字"))


def override(task: str, category: str, recipient: str, description: str, teacher: str) -> str:
    """只覆盖三方已经一致、且属于在线任务的动作。"""
    if task == "activity_notice" and category == "PERSON_NAME" and recipient in {"external_model", "egress_tool_public"}:
        return Action.DELETE.value
    if task == "activity_notice" and category == "DORM" and recipient == "external_model":
        return Action.DELETE.value
    if task == "class_coordination" and category == "PERSON_NAME" and recipient == "external_model":
        return Action.PSEUDONYMIZE.value
    if category in {"EMAIL", "PHONE"} and recipient in {"external_model", "egress_tool_public"}:
        return Action.DELETE.value
    if task == "meeting_minutes" and category == "BUDGET" and recipient == "external_model":
        if magnitude_request(description):
            return Action.GENERALIZE.value
        if exact_request(description):
            return Action.DELETE.value
    return teacher


def rows_for(model: NecessityModel, descriptions: list[str], source: str, case_prefix: str) -> list[dict]:
    rows = []
    for category, texts in TEXTS.items():
        for index, text in enumerate(texts):
            seg = segment(text, category)
            for task in TASKS:
                for recipient in RECIPIENTS:
                    for desc_index, description in enumerate(descriptions):
                        if category != "BUDGET" and description != GENERIC:
                            continue
                        if category == "BUDGET" and description == GENERIC:
                            continue
                        teacher = max(model.score(
                            seg, task, recipient, task_description=description, identity_key="student_leader"
                        ).items(), key=lambda item: item[1])[0]
                        label = override(task, category, recipient, description, teacher)
                        changed = label != teacher
                        feature = build_feature_text(
                            seg, task, recipient, task_description=description, identity_key="student_leader")
                        rows.append({
                            "feature": feature,
                            "label": label,
                            "source_case_id": f"{case_prefix}-{category}-{index}-{desc_index}",
                            "source": source,
                            "task": task,
                            "recipient": recipient,
                            "repeat": 40 if changed else 1,
                        })
    return rows


def fit(train: list[dict], valid: list[dict], out: Path) -> dict:
    samples = train + valid
    features = [row["feature"] for row in samples]
    labels = [row["label"] for row in samples]
    if any(not feature.startswith(f"[SCHEMA]{FEATURE_VERSION} ") or FEATURE_SPLIT not in feature for feature in features):
        raise ValueError("特征格式不符合当前版本")
    split = len(train)
    pipeline = Pipeline([
        ("features", FeatureUnion([
            ("structured", Pipeline([
                ("take", FunctionTransformer(_take_structured)),
                ("tfidf", TfidfVectorizer(analyzer="word", token_pattern=r"\S+", min_df=1)),
            ])),
            ("content", Pipeline([
                ("take", FunctionTransformer(_take_content)),
                ("tfidf", _char_vectorizer()),
            ])),
        ], transformer_weights={"structured": 1.0, "content": 0.15})),
        ("clf", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)),
    ])
    pipeline.fit(features[:split], labels[:split])
    predicted = pipeline.predict(features[split:])
    accuracy = float(pipeline.score(features[split:], labels[split:]))
    import joblib
    import sklearn
    artifact = {
        "artifact_type": ARTIFACT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "feature_version": FEATURE_VERSION,
        "classes": [str(item) for item in pipeline.classes_],
        "pipeline": pipeline,
        "validation": {
            "split": "synthetic_disjoint_texts",
            "accuracy": round(accuracy, 4),
            "macro_f1": round(float(f1_score(labels[split:], predicted, average="macro", zero_division=0)), 4),
            "train_samples": split,
            "validation_samples": len(valid),
            "label_sources": dict(Counter(row["source"] for row in samples)),
            "not_campus_accuracy": True,
        },
        "content_weight": 0.15,
        "training_metadata": {
            "teacher": "necessity_action.joblib",
            "campus_human_labels_used": False,
            "calibration_pack_used": False,
            "structured_analyzer": "word",
            "overrides": [
                "activity_notice external/public PERSON_NAME -> DELETE",
                "activity_notice external DORM -> DELETE",
                "class_coordination external PERSON_NAME -> PSEUDONYMIZE",
                "class_coordination external EMAIL -> DELETE",
                "meeting_minutes external BUDGET magnitude -> GENERALIZE",
                "meeting_minutes external BUDGET exact -> DELETE",
            ],
        },
        "limitation": "候选由活动模型蒸馏并只改三类已达成一致的动作。留出分不是校园准确率。未替换活动权重。",
        "sklearn_version": sklearn.__version__,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, out)
    print(classification_report(labels[split:], predicted, zero_division=0))
    print("saved", out)
    print("validation_accuracy", round(accuracy, 4))
    return artifact


def main() -> None:
    if OUT.resolve() == ACTIVE.resolve():
        raise SystemExit("拒绝覆盖活动权重")
    teacher = NecessityModel(ACTIVE)
    if not teacher.available:
        raise SystemExit(teacher.reason)
    train = []
    for row in rows_for(teacher, [GENERIC, MAGNITUDE[0], MAGNITUDE[4], EXACT[0]], "teacher_or_override", "train"):
        train.extend([row] * row["repeat"])
    valid_desc = [GENERIC, MAGNITUDE[1], EXACT[1]]
    # 验证文本与训练文本分开：rows_for 使用同一 TEXTS，因此改用后半描述并单独抽样会重复。
    # 这里用另一组描述，文本仍可能相同；分组不拿来当校园成绩。
    valid = rows_for(teacher, valid_desc, "teacher_or_override_valid", "valid")
    print("train", len(train), "valid", len(valid), "labels", dict(Counter(row["label"] for row in train)))
    fit(train, valid, OUT)


if __name__ == "__main__":
    main()
