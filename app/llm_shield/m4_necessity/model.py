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

from ..config import category_level, necessity_model_path, recipients, tasks
from ..schema import Action, Segment

# 决策模型路径来自统一的模型目录（config.necessity_model_path()）：
# 默认 <SHIELD_MODEL_DIR>/necessity_action.joblib，缺失时回退到项目内 models/。
# 不再写死路径，避免「模型到底放在哪个目录」这种问题。
MODEL_PATH = necessity_model_path()
ARTIFACT_TYPE = "llm-shield-action-policy"
SCHEMA_VERSION = 2
FEATURE_VERSION = 3
# 候选模型专用。活动权重仍是版本 3；score() 按权重里的版本选择构造函数。
FEATURE_VERSION_TASK = 4
FEATURE_VERSION_CONTEXT = 5
SCORED_ACTIONS = list(Action)

# 特征分隔符：把「策略结构化信号」与「原文内容」分开。
# 分隔符本身要足够特别，避免与正文撞车。
FEATURE_SPLIT = "[|SPLIT|]"
DEMAND_SPLIT = "[|DEMAND|]"
RAW_SPLIT = "[|RAW|]"
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


def _boundary_name(recipient_key: str) -> str:
    rec = recipients().get(recipient_key)
    kind = rec.get("type") if isinstance(rec, dict) else ""
    return {
        "EXTERNAL_MODEL": "external_generation",
        "VIEWER": "authorized_local_delivery",
        "EGRESS_TOOL": "public_release",
    }.get(str(kind), "unknown")


def _task_never_send(task_key: str) -> set:
    from ..m3_decide.constraints import _task_cfg
    task = _task_cfg(task_key)
    return set(task.get("never_send") or []) if isinstance(task, dict) else set()


def _ask_feature(task_description: str, categories: list) -> str:
    """把用户原话的每个字和类别绑在同一个词上。

    线性分类器看不到「类别 × 原话」的交互。绑在一起之后，
    同一句话作用在金额和姓名上会变成不同特征，三种需求也不会挤成同一条输入。
    """
    cat = "|".join(categories) or "NONE"
    ask = task_description.strip() if isinstance(task_description, str) else ""
    if not ask:
        return f"[X]{cat}|EMPTY"
    return " ".join(f"[X]{cat}|{ch}" for ch in ask if not ch.isspace())


def build_feature_text_v4(seg: Segment, task_key: str, recipient_key: str, *,
                           task_description: str = "", context: str = "",
                           identity_key: str = "") -> str:
    """版本 4 特征。版本 3 的构造函数保持不变，活动模型继续用版本 3。

    结构化部分补上既有的边界、发送权限、恢复权限和类别限制。
    用户原话单独放在需求段，不并进被置零的原文段。
    """
    from ..m1_access.identity import can_restore, check_provide, identity_max_level

    cats = sorted({s.category for s in seg.spans})
    rec = recipients().get(recipient_key)
    rec = rec if isinstance(rec, dict) else {}
    task = tasks().get(task_key)
    task = task if isinstance(task, dict) else {}
    cols = sorted({s.column for s in seg.spans if s.column})
    ceiling = min(identity_max_level(identity_key) if identity_key else 1,
                  int(rec.get("max_level", 1) or 1))
    levels = [category_level(cat) for cat in cats]
    top_level = max(levels) if levels else 0
    forbidden = set(rec.get("forbidden") or [])
    never = _task_never_send(task_key)
    banned = any(cat in forbidden or cat in never or category_level(cat) > ceiling for cat in cats)
    send_ok = bool(identity_key) and bool(recipient_key) and check_provide(identity_key, recipient_key)[0]
    ask = task_description.strip() if isinstance(task_description, str) else ""
    structured = [
        f"[SCHEMA]{FEATURE_VERSION_TASK}",
        "[CAT]" + ("|".join(cats) or "NONE"),
        "[TASK]" + task_key,
        "[RECIPIENT]" + recipient_key,
        "[ROLE]" + str(rec.get("type", "UNKNOWN")),
        "[TRUST]" + str(rec.get("trust", "unknown")),
        "[IDENTITY]" + identity_key,
        "[BOUNDARY]" + _boundary_name(recipient_key),
        "[SEND]" + ("1" if send_ok else "0"),
        "[RESTORE]" + ("1" if identity_key and recipient_key and can_restore(identity_key, recipient_key) else "0"),
        "[MAX]" + str(ceiling),
        "[CATLEVEL]" + str(top_level),
        "[BANNED]" + ("1" if banned else "0"),
        "[COL]" + ("|".join(cols) or seg.column or "NONE"),
        "[N]" + str(len(seg.spans)),
        "[CONF]" + f"{max([s.confidence for s in seg.spans], default=0.0):.2f}",
    ]
    demand = _ask_feature(ask, cats)
    content = [
        "[TASK_TEMPLATE]" + str(task.get("desc", "")),
        "[CONTEXT]" + (context or seg.context),
        "[TEXT]" + seg.text,
    ]
    return " ".join(structured) + " " + FEATURE_SPLIT + " " + demand + " " + DEMAND_SPLIT + " " + " ".join(content)


def _structured_context(seg: Segment, task_key: str, recipient_key: str, identity_key: str, version: int) -> tuple:
    """版本 4 和版本 5 共用的短结构信号。权限来自现有配置，不新增规则。"""
    from ..m1_access.identity import can_restore, check_provide, identity_max_level

    cats = sorted({s.category for s in seg.spans})
    rec = recipients().get(recipient_key)
    rec = rec if isinstance(rec, dict) else {}
    cols = sorted({s.column for s in seg.spans if s.column})
    ceiling = min(identity_max_level(identity_key) if identity_key else 1,
                  int(rec.get("max_level", 1) or 1))
    levels = [category_level(cat) for cat in cats]
    forbidden = set(rec.get("forbidden") or [])
    never = _task_never_send(task_key)
    banned = any(cat in forbidden or cat in never or category_level(cat) > ceiling for cat in cats)
    send_ok = bool(identity_key) and bool(recipient_key) and check_provide(identity_key, recipient_key)[0]
    return [
        f"[SCHEMA]{version}",
        "[CAT]" + ("|".join(cats) or "NONE"),
        "[TASK]" + task_key,
        "[RECIPIENT]" + recipient_key,
        "[ROLE]" + str(rec.get("type", "UNKNOWN")),
        "[TRUST]" + str(rec.get("trust", "unknown")),
        "[IDENTITY]" + identity_key,
        "[BOUNDARY]" + _boundary_name(recipient_key),
        "[SEND]" + ("1" if send_ok else "0"),
        "[RESTORE]" + ("1" if identity_key and recipient_key and can_restore(identity_key, recipient_key) else "0"),
        "[MAX]" + str(ceiling),
        "[CATLEVEL]" + str(max(levels) if levels else 0),
        "[BANNED]" + ("1" if banned else "0"),
        "[COL]" + ("|".join(cols) or seg.column or "NONE"),
        "[N]" + str(len(seg.spans)),
        "[CONF]" + f"{max([s.confidence for s in seg.spans], default=0.0):.2f}",
    ], cats


def build_feature_text_v5(seg: Segment, task_key: str, recipient_key: str, *,
                           task_description: str = "", context: str = "",
                           identity_key: str = "") -> str:
    """版本 5。用户原话同时保留整句和「类别×每个字」。

    整句走字符 n-gram，用来辨认精确、量级、不需要这类说法。
    类别绑定用来避免同一句话把金额上的判断套到姓名上。
    原文片段仍单独成段，本轮候选把它的权重保持为 0。
    """
    structured, cats = _structured_context(seg, task_key, recipient_key, identity_key, FEATURE_VERSION_CONTEXT)
    task = tasks().get(task_key)
    task = task if isinstance(task, dict) else {}
    ask = task_description.strip() if isinstance(task_description, str) else ""
    raw = "[RAW]" + (ask if ask else "EMPTY")
    content = [
        "[TASK_TEMPLATE]" + str(task.get("desc", "")),
        "[CONTEXT]" + (context or seg.context),
        "[TEXT]" + seg.text,
    ]
    return " ".join(structured) + " " + FEATURE_SPLIT + " " + raw + " " + RAW_SPLIT + " " + _ask_feature(ask, cats) + " " + DEMAND_SPLIT + " " + " ".join(content)


def split_feature_v5(feature: str) -> tuple:
    """拆出版本 5 的结构化段、整句需求、类别绑定需求和原文段。"""
    structured, _, rest = feature.partition(FEATURE_SPLIT)
    raw, _, rest = rest.partition(RAW_SPLIT)
    cross, _, content = rest.partition(DEMAND_SPLIT)
    return structured, raw, cross, content


def split_feature_v4(feature: str) -> tuple:
    """拆出版本 4 的结构化段、需求段和原文段。"""
    structured, _, rest = feature.partition(FEATURE_SPLIT)
    demand, _, content = rest.partition(DEMAND_SPLIT)
    return structured, demand, content


class ModelUnavailableError(RuntimeError):
    """没有可用于动作决策的有效模型。"""


def _sample_group(sample: dict, feature: str) -> str:
    for key in ("split_group_id", "source_case_id", "case_id", "source_document_id", "document_id", "group_id"):
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
    """取分隔符之后的部分：上下文与原文。版本 3 使用。"""
    return [t.partition(FEATURE_SPLIT)[2] for t in texts]


def _take_demand(texts):
    """版本 4：用户任务原话，位于两个分隔符之间。"""
    return [t.partition(FEATURE_SPLIT)[2].partition(DEMAND_SPLIT)[0] for t in texts]


def _take_content_after_demand(texts):
    """版本 4：原文段。需求段已经单独取出。"""
    return [t.partition(DEMAND_SPLIT)[2] for t in texts]


def _take_raw(texts):
    """版本 5：用户原话整句。"""
    return [t.partition(FEATURE_SPLIT)[2].partition(RAW_SPLIT)[0] for t in texts]


def _take_cross(texts):
    """版本 5：类别和原话每个字的绑定。"""
    return [t.partition(RAW_SPLIT)[2].partition(DEMAND_SPLIT)[0] for t in texts]


def _take_content_v5(texts):
    """版本 5：原文段。"""
    return [t.partition(DEMAND_SPLIT)[2] for t in texts]


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
            self.reason = "未找到模型决策权重；请取得获准的本机权重，按 app/models/ACTIVE_MODELS.json 核对摘要，并检查 SHIELD_ACTION_MODEL_PATH"
            return
        try:
            import joblib
            artifact = joblib.load(self.model_path)
            if not isinstance(artifact, dict):
                raise ValueError("旧版或无元信息模型")
            if (artifact.get("artifact_type") != ARTIFACT_TYPE
                    or artifact.get("schema_version") != SCHEMA_VERSION
                    or artifact.get("feature_version") not in {FEATURE_VERSION, FEATURE_VERSION_TASK, FEATURE_VERSION_CONTEXT}):
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
        version = self.metadata.get("feature_version")
        if version == FEATURE_VERSION_CONTEXT:
            feature = build_feature_text_v5(seg, task_key, recipient_key,
                                            task_description=task_description,
                                            context=context, identity_key=identity_key)
        elif version == FEATURE_VERSION_TASK:
            feature = build_feature_text_v4(seg, task_key, recipient_key,
                                            task_description=task_description,
                                            context=context, identity_key=identity_key)
        elif version == FEATURE_VERSION:
            feature = build_feature_text(seg, task_key, recipient_key,
                                         task_description=task_description,
                                         context=context, identity_key=identity_key)
        else:
            raise ModelUnavailableError("动作模型特征版本不支持")
        try:
            probabilities = self.pipeline.predict_proba([feature])[0]
            classes = list(self.pipeline.classes_)
            if len(probabilities) != len(classes):
                raise ValueError("概率与类别长度不匹配")
            return {str(c): float(p) for c, p in zip(classes, probabilities)}
        except Exception as exc:
            raise ModelUnavailableError("动作模型推理失败") from exc

    def train(self, samples: List[dict], out_path: Optional[Path] = None, *,
              validation_samples: Optional[List[dict]] = None,
              content_weight: float = CONTENT_WEIGHT,
              training_metadata: Optional[dict] = None) -> dict:
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
            import math
            if (isinstance(content_weight, bool) or not isinstance(content_weight, (int, float))
                    or not math.isfinite(content_weight) or not 0 <= content_weight <= 10):
                raise ValueError("内容权重必须为 0 到 10 的有限数值")
            provided_validation = validation_samples is not None
            if provided_validation and not validation_samples:
                raise ValueError("显式验证集不能为空")
            validation_start = len(samples)
            samples = list(samples) + list(validation_samples or [])
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
            if provided_validation:
                train_idx = list(range(validation_start))
                valid_idx = list(range(validation_start, len(samples)))
                if set(groups[i] for i in train_idx) & set(groups[i] for i in valid_idx):
                    raise ValueError("训练与验证存在来源/模板组重叠")
                if set(labels[i] for i in valid_idx) - set(labels[i] for i in train_idx):
                    raise ValueError("验证集含训练未覆盖的动作，请补充训练来源")
                if set(features[i] for i in train_idx) & set(features[i] for i in valid_idx):
                    raise ValueError("训练与验证存在重复特征")
                split = (train_idx, valid_idx)
            else:
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
                ], transformer_weights={"structured": 1.0, "content": content_weight})),
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
                "split": "frozen_group_validation" if provided_validation else "source_group_holdout",
                "accuracy": round(accuracy, 4),
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
                "content_weight": content_weight,
                "training_metadata": training_metadata or {},
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
