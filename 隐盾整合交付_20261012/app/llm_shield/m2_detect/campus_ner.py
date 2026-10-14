"""★ 校园领域预训练 NER 适配器（可插拔）。

对应架构 ② 的「领域预训练：校园公开文本继续预训练 → RoBERTa-campus，再微调敏感实体识别」。

设计：本类实现与 RegexDetector / EntityDetector 完全相同的 Detector 接口。
- 未训练权重时：available=False，detect() 返回空列表，主链路不受影响；
- 训练完权重放到 models/campus_ner 后：自动加载，把模型识别结果并入识别流水线。

因此「规则底座 ↔ 领域模型」是热替换关系，决策层及之后模块无需任何改动。
训练脚本见同目录 pretrain/。
"""
from __future__ import annotations

from typing import List, Optional

from ..config import ROOT
from ..schema import Span
from .base import Detector

DEFAULT_MODEL_DIR = ROOT / "models" / "campus_ner"

# 模型输出的 BIO 标签 → 系统内部类别
# 需与 pretrain/finetune_ner.py 中的 LABELS 保持一致
LABEL_TO_CATEGORY = {
    "NAME": "PERSON_NAME",
    "ORG": "ORG",
    "LOC": "LOCATION",
    "PHONE": "PHONE",
    "EMAIL": "EMAIL",
    "ID": "ID_CARD",
    "SID": "STUDENT_ID",
    "DORM": "DORM",
    "BUDGET": "BUDGET",
    "WECHAT": "WECHAT",
    "GRADE": "GRADE",
    "ATTR": "SENSITIVE_ATTR",
}


class CampusNERDetector(Detector):
    """校园领域 NER。权重缺失或依赖未装时优雅降级为空识别器。"""

    name = "campus_ner"

    def __init__(self, model_dir=None, device: Optional[str] = None):
        self.model_dir = model_dir or DEFAULT_MODEL_DIR
        self.device = device
        self.available = False
        self.reason = ""
        self.tokenizer = None
        self.model = None
        self.id2label: dict = {}
        self._try_load()

    def _try_load(self) -> None:
        if not self.model_dir.exists():
            self.reason = f"权重目录不存在: {self.model_dir}（先运行 pretrain/finetune_ner.py 训练）"
            return
        try:
            import torch  # noqa: F401
            from transformers import AutoModelForTokenClassification, AutoTokenizer
        except ImportError:
            self.reason = "未安装 torch/transformers，执行 pip install -r requirements-gpu.txt"
            return
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir))
            self.model = AutoModelForTokenClassification.from_pretrained(str(self.model_dir))
            if self.device is None:
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.model.to(self.device)
            self.model.eval()
            self.id2label = {int(k): v for k, v in self.model.config.id2label.items()}
            self.available = True
            self.reason = f"已加载 {self.model_dir.name} -> {self.device}"
        except Exception as exc:  # 加载失败不应打断主流程
            self.reason = f"加载失败: {exc}"
            self.available = False

    def detect(self, text: str, columns=None, rows=None) -> List[Span]:
        if not self.available or not text:
            return []
        return self._predict(text)

    def _predict(self, text: str, max_len: int = 512) -> List[Span]:
        """按 max_len 滑窗推理，解码 BIO，映射回原文字符偏移。"""
        import torch

        spans: List[Span] = []
        step = max_len - 64
        for offset in range(0, len(text), step):
            chunk = text[offset: offset + max_len]
            enc = self.tokenizer(
                list(chunk), is_split_into_words=True, truncation=True,
                max_length=max_len, return_tensors="pt",
            )
            # 必须在转成 dict 之前取出 word_ids：
            # tokenizer 返回的是 BatchEncoding，一旦被 {k: v.to(device)} 转成普通 dict，
            # word_ids() 方法就没了，所有 token 都映射不到字符下标，
            # 表现为「模型在预测但一个实体都不输出」。
            word_ids = enc.word_ids()
            enc = {k: v.to(self.device) for k, v in enc.items()}
            with torch.no_grad():
                logits = self.model(**enc).logits[0]
            preds = logits.argmax(-1).cpu().tolist()

            # 逐 token 解码 BIO
            current_label, current_start, current_end, current_conf = None, -1, -1, 0.0
            probs = torch.softmax(logits, -1)
            for i, pid in enumerate(preds):
                if i == 0 or i == len(preds) - 1:
                    continue  # [CLS] / [SEP]
                label = self.id2label.get(pid, "O")
                if label == "O":
                    if current_label:
                        spans.append(self._make_span(text, offset, current_label,
                                                     current_start, current_end, current_conf))
                    current_label, current_start, current_end, current_conf = None, -1, -1, 0.0
                    continue
                prefix, etype = label.split("-", 1) if "-" in label else ("B", label)
                # token → 字符偏移（中文按字切分，word_ids 与字符下标一致）
                char_idx = self._token_to_char(word_ids, i)
                if char_idx is None:
                    continue
                conf = float(probs[i][pid].cpu())
                if prefix == "B" or etype != current_label:
                    if current_label:
                        spans.append(self._make_span(text, offset, current_label,
                                                     current_start, current_end, current_conf))
                    current_label, current_start, current_end, current_conf = etype, char_idx, char_idx + 1, conf
                else:
                    current_end = char_idx + 1
                    current_conf = max(current_conf, conf)
            if current_label:
                spans.append(self._make_span(text, offset, current_label,
                                             current_start, current_end, current_conf))
            if offset + max_len >= len(text):
                break
        return spans

    @staticmethod
    def _token_to_char(word_ids, token_idx) -> Optional[int]:
        if word_ids is None:
            return None
        wid = word_ids[token_idx]
        return wid  # 中文逐字 tokenizer 下 word_id 即字符下标

    @staticmethod
    def _make_span(text: str, offset: int, label: str, start: int, end: int, conf: float) -> Span:
        abs_start, abs_end = offset + start, offset + end
        value = text[abs_start:abs_end]
        return Span(abs_start, abs_end, value, LABEL_TO_CATEGORY.get(label, "ORG"),
                    min(conf, 1.0), "campus_ner", f"ner_{label}")
