"""本地动作分类模型。缺少有效权重时不可用，不提供规则评分兜底。

TF-IDF + 逻辑回归用于验证模型决策链路，不等同于已训练的大语言模型。
规则生成的标签仅为启动基线；其验证分数不代表人工评估的决策质量。
"""
from __future__ import annotations

import hashlib
import threading
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from ..config import necessity_model_path, recipients, tasks
from ..schema import Action, Segment

# 决策模型路径来自统一的模型目录（config.necessity_model_path()）：
# 默认 <SHIELD_MODEL_DIR>/necessity_action.joblib，缺失时回退到项目内 models/。
# 不再写死路径，避免「模型到底放在哪个目录」这种问题。
MODEL_PATH = necessity_model_path()
ARTIFACT_TYPE = "llm-shield-action-policy"
SCHEMA_VERSION = 2
FEATURE_VERSION = 3
SCORED_ACTIONS = list(Action)

# 特征分隔符：把「策略结构化信号」与「原文内容」分开。
# 分隔符本身要足够特别，避免与正文撞车。
FEATURE_SPLIT = "[|SPLIT|]"
# 原文内容在 TF-IDF 里的权重（结构化信号固定为 1.0）。
# 动作应由「类别×任务×接收方×信任度」决定，原文只应做微调；
# 早先两者混在一条 char n-gram 串里，长原文的 n-gram 数量压倒结构化 token，
# 模型于是按「这段文字像什么」而不是「这是哪类信息、发给谁」来选动作。
CONTENT_WEIGHT = 0.35


def build_feature_text(seg: Segment, task_key: str, recipient_key: str, *,
                       task_description: str = "", context: str = "",
                       identity_key: str = "") -> str:
    """训练和推理共用特征，包含实际任务要求、身份和段落上下文。

    返回 ``结构化部分 [|SPLIT|] 内容部分``；两段在训练时分别向量化并加权
    （见 :data:`CONTENT_WEIGHT`）。

    特征包含输入原文，只在本地推理或训练使用，不应写入公开日志。
    """
    cats = sorted({s.category for s in seg.spans})
    rec = recipients().get(recipient_key, {})
    task = tasks().get(task_key, {})
    cols = sorted({s.column for s in seg.spans if s.column})
    # 结构化块只放**短**策略信号：动作由它们决定。
    # 任务描述等长文本一律归内容块——否则它们会像原文一样把 [CAT] 稀释掉
    # （实测：把 TASK_TEMPLATE/TASK_TEXT 留在结构化块里，ORG×project_intro
    #  会被误判成 GENERALIZE）。
    structured = [
        f"[SCHEMA]{FEATURE_VERSION}",
        "[CAT]" + ("|".join(cats) or "NONE"),
        "[TASK]" + task_key,
        "[RECIPIENT]" + recipient_key,
        "[ROLE]" + str(rec.get("type", "UNKNOWN")),
        "[TRUST]" + str(rec.get("trust", "unknown")),
        "[IDENTITY]" + identity_key,
        "[COL]" + ("|".join(cols) or seg.column or "NONE"),
        "[N]" + str(len(seg.spans)),
        "[CONF]" + f"{max([s.confidence for s in seg.spans], default=0.0):.2f}",
    ]
    content = [
        "[TASK_TEMPLATE]" + str(task.get("desc", "")),
        "[TASK_TEXT]" + (task_description or str(task.get("desc", ""))),
        "[CONTEXT]" + (context or seg.context),
        "[TEXT]" + seg.text,
    ]
    return " ".join(structured) + " " + FEATURE_SPLIT + " " + " ".join(content)


class ModelUnavailableError(RuntimeError):
    """没有可用于动作决策的有效模型。"""


def _sample_group(sample: dict, feature: str) -> str:
    for key in ("source_case_id", "case_id", "source_document_id", "document_id", "group_id"):
        if sample.get(key):
            return "document:" + str(sample[key])
    # 旧数据没有来源 ID 时，至少把相同原文的衍生样本放在同组。
    text = sample.get("source_text") or sample.get("text") or feature.partition("[TEXT]")[2]
    if not text:
        raise ValueError("训练样本缺少来源案例 ID 和可分组原文")
    return "text:" + hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _take_structured(texts):
    """取分隔符之前的部分：类别 / 任务 / 接收方 / 信任度等策略信号。"""
    return [t.partition(FEATURE_SPLIT)[0] for t in texts]


def _take_content(texts):
    """取分隔符之后的部分：上下文与原文。"""
    return [t.partition(FEATURE_SPLIT)[2] for t in texts]


def _char_vectorizer():
    """字符级 n-gram 向量化器（中文无需分词；char_wb 保证不跨词边界）。"""
    from sklearn.feature_extraction.text import TfidfVectorizer
    return TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)


class NecessityModel:
    def __init__(self, model_path: Optional[Path] = None):
        self.model_path = Path(model_path) if model_path else MODEL_PATH
        self.backend = "unavailable"
        self.pipeline = None
        self.metadata = {}
        self.reason = ""
        self._load()

    def _load(self) -> None:
        if not self.model_path.exists():
            self.reason = "未找到模型决策权重；请运行 python -m llm_shield.m4_necessity.train"
            return
        try:
            import joblib
            artifact = joblib.load(self.model_path)
            if not isinstance(artifact, dict):
                raise ValueError("旧版或无元信息模型")
            if (artifact.get("artifact_type") != ARTIFACT_TYPE
                    or artifact.get("schema_version") != SCHEMA_VERSION
                    or artifact.get("feature_version") != FEATURE_VERSION):
                raise ValueError("模型或特征版本不兼容")
            pipeline = artifact.get("pipeline")
            classes = [str(c) for c in pipeline.classes_]
            if (len(classes) < 2 or len(set(classes)) != len(classes)
                    or any(c not in Action._value2member_map_ for c in classes)
                    or classes != artifact.get("classes")
                    or not callable(getattr(pipeline, "predict_proba", None))):
                raise ValueError("模型动作类别元信息无效")
            self.pipeline = pipeline
            self.metadata = {k: v for k, v in artifact.items() if k != "pipeline"}
            self.backend = "sklearn"
            self.reason = f"已加载模型决策权重 {self.model_path.name}"
        except Exception as exc:
            self.reason = f"动作模型加载失败（{type(exc).__name__}）；暂停敏感材料处理"

    @property
    def available(self) -> bool:
        return self.backend == "sklearn" and self.pipeline is not None

    def score(self, seg: Segment, task_key: str, recipient_key: str, *,
              task_description: str = "", context: str = "",
              identity_key: str = "") -> Dict[str, float]:
        if not self.available:
            raise ModelUnavailableError(self.reason)
        feature = build_feature_text(seg, task_key, recipient_key,
                                     task_description=task_description,
                                     context=context, identity_key=identity_key)
        try:
            probabilities = self.pipeline.predict_proba([feature])[0]
            classes = list(self.pipeline.classes_)
            if len(probabilities) != len(classes):
                raise ValueError("概率与类别长度不匹配")
            return {str(c): float(p) for c, p in zip(classes, probabilities)}
        except Exception as exc:
            raise ModelUnavailableError("动作模型推理失败") from exc

    def train(self, samples: List[dict], out_path: Optional[Path] = None) -> dict:
        """按源案例分组留出验证集；拒绝旧特征和训练集冒充验证集。"""
        try:
            import joblib
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.metrics import classification_report, f1_score
            from sklearn.model_selection import GroupShuffleSplit
            from sklearn.pipeline import FeatureUnion, Pipeline
            from sklearn.preprocessing import FunctionTransformer
        except ImportError as exc:
            return {"ok": False, "reason": f"缺少训练依赖: {exc}"}
        if len(samples) < 20:
            return {"ok": False, "reason": f"样本量不足（{len(samples)} < 20）"}
        try:
            features = [s["feature"] for s in samples]
            labels = [s["label"] for s in samples]
            if any(not isinstance(f, str) or not f.startswith(f"[SCHEMA]{FEATURE_VERSION} ")
                   for f in features):
                raise ValueError("旧版特征不兼容，请从 cases_dev 重新构建训练样本")
            if any(label not in Action._value2member_map_ for label in labels):
                raise ValueError("训练样本含未知动作标签")
            if len(set(labels)) < 2:
                raise ValueError("至少需要两种动作标签")
            groups = [_sample_group(s, f) for s, f in zip(samples, features)]
            if len(set(groups)) < 4:
                raise ValueError("至少需要四个独立来源案例，不能用训练集报告验证准确率")
            split = None
            for train_idx, valid_idx in GroupShuffleSplit(
                    n_splits=100, test_size=0.25, random_state=42).split(features, labels, groups):
                if set(labels[i] for i in train_idx) == set(labels):
                    split = (train_idx, valid_idx)
                    break
            if split is None:
                raise ValueError("来源分组后无法保留全部训练类别，请补充各类别的独立案例")
            train_idx, valid_idx = split
            # 两路分量分别向量化后按权重拼接：结构化信号权重 1.0，原文内容 CONTENT_WEIGHT。
            # 这样「动作由类别×任务×接收方决定」这一策略事实不会被长原文的 n-gram 淹没。
            # 拆分函数必须定义在**模块级**，否则 joblib 序列化 pipeline 时会因为
            # 无法定位局部函数而失败。
            pipeline = Pipeline([
                ("features", FeatureUnion([
                    ("structured", Pipeline([("take", FunctionTransformer(_take_structured)),
                                             ("tfidf", _char_vectorizer())])),
                    ("content", Pipeline([("take", FunctionTransformer(_take_content)),
                                          ("tfidf", _char_vectorizer())])),
                ], transformer_weights={"structured": 1.0, "content": CONTENT_WEIGHT})),
                ("clf", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)),
            ])
            x_train = [features[i] for i in train_idx]
            y_train = [labels[i] for i in train_idx]
            x_valid = [features[i] for i in valid_idx]
            y_valid = [labels[i] for i in valid_idx]
            pipeline.fit(x_train, y_train)
            predictions = pipeline.predict(x_valid)
            accuracy = float(pipeline.score(x_valid, y_valid))
            report = classification_report(y_valid, predictions, zero_division=0)
            sources = dict(Counter(s.get("source", "unspecified") for s in samples))
            validation = {
                "split": "source_group_holdout", "accuracy": round(accuracy, 4),
                "macro_f1": round(float(f1_score(y_valid, predictions, average="macro", zero_division=0)), 4),
                "train_samples": len(train_idx), "validation_samples": len(valid_idx),
                "train_groups": len({groups[i] for i in train_idx}),
                "validation_groups": len({groups[i] for i in valid_idx}),
                "group_overlap": len({groups[i] for i in train_idx} & {groups[i] for i in valid_idx}),
                "unvalidated_classes": sorted(set(labels) - set(y_valid)),
                "label_sources": sources,
            }
            artifact = {
                "artifact_type": ARTIFACT_TYPE, "schema_version": SCHEMA_VERSION,
                "feature_version": FEATURE_VERSION,
                "classes": [str(c) for c in pipeline.classes_],
                "pipeline": pipeline, "validation": validation,
                "limitation": "规则/弱监督标签仅为启动基线，留出分数不代表真实决策质量；需要人工金标与跨模板测试。",
            }
            output = Path(out_path) if out_path else self.model_path
            import sklearn
            artifact["sklearn_version"] = sklearn.__version__
            output.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(artifact, output)
        except Exception as exc:
            return {"ok": False, "reason": f"训练失败: {exc}"}
        self.pipeline = pipeline
        self.backend = "sklearn"
        self.model_path = output
        self.metadata = {k: v for k, v in artifact.items() if k != "pipeline"}
        self.reason = f"已训练模型决策权重 {output.name}"
        return {"ok": True, "n": len(samples), "test_acc": round(accuracy, 4),
                "validation": validation, "report": report, "model_path": str(output)}


_MODEL: Optional[NecessityModel] = None
_MODEL_LOCK = threading.Lock()


def get_model() -> NecessityModel:
    global _MODEL
    selected_path = necessity_model_path().resolve()
    if _MODEL is None or _MODEL.model_path.resolve() != selected_path:
        with _MODEL_LOCK:
            if _MODEL is None or _MODEL.model_path.resolve() != selected_path:
                _MODEL = NecessityModel(selected_path)
    return _MODEL


def necessity_scorer(seg: Segment, task_key: str, recipient_key: str, *,
                     task_description: str = "", context: str = "",
                     identity_key: str = "") -> Dict[str, float]:
    return get_model().score(seg, task_key, recipient_key,
                             task_description=task_description,
                             context=context, identity_key=identity_key)
