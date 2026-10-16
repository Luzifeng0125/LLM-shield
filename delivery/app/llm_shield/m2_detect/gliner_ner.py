"""GLiNER v3 识别器（可插拔）—— A 层语义实体检测。

对应 v3 架构 L2 识别层的模型部分。实现与 RegexDetector / EntityDetector /
CampusNERDetector 完全相同的 Detector 接口，可热替换。

设计要点
--------
1. **强制字符级中文分词**（CharSplitter）：GLiNER 默认 whitespace 分词会把整串
   中文当一个 token，导致实体边界错位。这是 v3 最关键的一处修正。
2. **只贡献语义类实体**（默认 PERSON_NAME / ORG / LOCATION / DORM / SENSITIVE_ATTR）：
   格式类（电话/邮箱/学号/证件/银行卡/密钥/微信/预算/成绩）由正则底座负责，
   避免证件号误报与重叠边界冲突。可通过 ``categories`` 参数调整。
3. **优雅降级**：模型缺失 / 依赖未装 / 加载失败时 available=False，detect() 返回
   空列表，主链路不受影响（与 CampusNERDetector 一致）。

模型：urchade/gliner_multi-v2.1（Apache-2.0）+ 人工 gold 微调。
实测（docs/评测报告-独立手写集field_v1.md）：独立手写集上 13 类 F1 0.8383、
语义 5 类 0.8777；同源旧 gold 上分别为 1.0000 / 0.9244（后者因旧集格式类取值
被模型背下模板，不代表真实泛化）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional

from .. import config as cfg
from ..schema import Span
from .base import Detector
from .char_splitter import CharSplitter

# GLiNER 中文标签 → 系统内部类别
LABEL_TO_CATEGORY = {
    "人名": "PERSON_NAME",
    "电话号码": "PHONE",
    "邮箱地址": "EMAIL",
    "学号": "STUDENT_ID",
    "身份证号": "ID_CARD",
    "银行卡号": "BANK_CARD",
    "密钥或密码": "API_KEY",
    "微信号或QQ号": "WECHAT",
    "预算金额": "BUDGET",
    "组织名称": "ORG",
    "地点场所": "LOCATION",
    "宿舍地址": "DORM",
    "成绩分数": "GRADE",
    "敏感个人属性": "SENSITIVE_ATTR",
}

# 13 类（除身份证外）——保留给需要显式全量推理的场景。
# 身份证号由正则（GB 11643 校验位）权威判定，避免 GLiNER 把 10 位学号误报成 18 位
# 身份证（微调模型在 test 上有 12 个 ID_CARD 误报，是唯一的 FP 来源）。
GLINER_CATEGORIES = tuple(c for c in LABEL_TO_CATEGORY.values() if c != "ID_CARD")

# 语义类：GLiNER 的**默认**覆盖范围。
# 依据 docs/评测报告-独立手写集field_v1.md 的实测：格式类（电话/邮箱/学号/银行卡/
# 密钥/微信/预算/成绩）交给概率模型会让精度下降（高敏类别 F1 0.865→0.770），
# 这些类别由带校验位的正则底座负责更稳；GLiNER 的净价值集中在语义类。
SEMANTIC_CATEGORIES = ("PERSON_NAME", "ORG", "LOCATION", "DORM", "SENSITIVE_ATTR")
_SEMANTIC_SET = set(SEMANTIC_CATEGORIES)


class GLiNERDetector(Detector):
    """GLiNER 语义实体识别器。"""

    name = "gliner"

    def __init__(
        self,
        model_dir: Optional[str] = None,
        threshold: float = 0.5,
        categories: Optional[Iterable[str]] = None,
        device: Optional[str] = None,
    ):
        self.model_dir = Path(model_dir) if model_dir else Path(cfg.gliner_model_dir())
        self.threshold = threshold
        # 默认只负责语义类：格式类由正则底座（含校验位）权威判定。
        # 实测（docs/评测报告-独立手写集field_v1.md）13 类标签一起推理时，
        # 模型在独立集上的 F1 0.8383、误报 45；收窄到语义 5 类后 F1 0.8777、
        # 误报 30，且高敏类别 F1 从 0.770 回到 0.857。需要显式覆盖时传
        # categories=GLINER_CATEGORIES 即可恢复 13 类。
        self.categories = set(categories) if categories is not None else set(SEMANTIC_CATEGORIES)
        self.device = device
        self.available = False
        self.reason = ""
        self.model = None
        # 分两趟推理：语义类一趟、格式类一趟，避免标签集过大导致标签竞争、
        # 稀释稀疏类别（如敏感属性）的分数而漏检。
        self.semantic_labels: List[str] = []
        self.format_labels: List[str] = []
        self._try_load()

    def _try_load(self) -> None:
        if not self.model_dir.exists():
            self.reason = f"权重目录不存在: {self.model_dir}（先用 gliner_train 训练，或用 SHIELD_GLINER_MODEL_DIR 指定）"
            return
        try:
            from gliner import GLiNER
        except ImportError:
            self.reason = "未安装 gliner，执行 pip install gliner peft"
            return
        try:
            self.model = GLiNER.from_pretrained(str(self.model_dir), load_tokenizer=True)
            # ★ 关键修复：换用字符级中文分词，避免实体边界错位
            self.model.data_processor.words_splitter = CharSplitter()
            import torch
            if self.device is None:
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.model.to(self.device)
            self.model.eval()
            self.semantic_labels = [lbl for lbl, cat in LABEL_TO_CATEGORY.items()
                                    if cat in self.categories and cat in _SEMANTIC_SET]
            self.format_labels = [lbl for lbl, cat in LABEL_TO_CATEGORY.items()
                                  if cat in self.categories and cat not in _SEMANTIC_SET]
            self.available = True
            self.reason = (f"已加载 {self.model_dir.name} -> {self.device}（语义类 {len(self.semantic_labels)} 个 + "
                           f"格式类 {len(self.format_labels)} 个标签，分两趟推理）")
        except Exception as exc:  # 加载失败不应打断主流程
            self.reason = f"加载失败: {exc}"
            self.available = False

    def detect(self, text: str, columns=None, rows=None) -> List[Span]:
        if not self.available or not text or not (self.semantic_labels or self.format_labels):
            return []
        # GLiNER 是双向编码器，配置 max_len（本项目 384 个 token）封顶；长文本需滑窗。
        # 窗口间重叠 32 个 token，避免实体被窗口边界切断；重复 span 由下游 merge_spans 去重。
        max_len = int(getattr(self.model.config, "max_len", 384))
        step = max(1, max_len - 32)
        spans: List[Span] = []
        seen = set()
        try:
            for offset in range(0, len(text), step):
                chunk = text[offset:offset + max_len]
                for label_group in (self.semantic_labels, self.format_labels):
                    if not label_group:
                        continue
                    out = self.model.predict_entities(chunk, label_group, threshold=self.threshold)
                    for p in out:
                        cat = LABEL_TO_CATEGORY.get(p.get("label"))
                        if cat is None or cat not in self.categories:
                            continue
                        start = offset + int(p["start"])
                        end = offset + int(p["end"])
                        key = (start, end, cat)
                        if key in seen:
                            continue
                        seen.add(key)
                        spans.append(Span(
                            start=start,
                            end=end,
                            text=text[start:end],
                            category=cat,
                            confidence=min(float(p.get("score", self.threshold)), 1.0),
                            detector="gliner",
                            rule_id="gliner_" + p.get("label", ""),
                        ))
                if offset + max_len >= len(text):
                    break
        except Exception:
            # 推理异常按"未检出"处理，不抛原异常（异常消息可能含输入原文）
            return []
        return spans
