"""识别流水线：组合多个识别器 → 重叠合并 → 切分为决策单元（Segment）。"""
from __future__ import annotations

import re
from dataclasses import replace
from functools import lru_cache
from typing import List, Optional, Tuple

from .. import config as cfg
from ..config import category_level
from ..schema import Segment, Span
from .base import Detector
from .campus_ner import CampusNERDetector
from .entity_rules import EntityDetector
from .gliner_ner import GLiNERDetector
from .regex_rules import RegexDetector
from .reviewed_ner import ReviewedNERDetector

# 句子切分符
_SENT_SPLIT_RE = re.compile(r"(?<=[。！？；;!?\n])")

# 昂贵检测器（GLiNER / campus NER）的模块级单例缓存。
# 这些模型加载约 10s、占 ~1.1GB 内存，绝不能每次请求都重建；
# RegexDetector / EntityDetector 零依赖、构造极轻，每次新建即可。
_gliner_singleton: Optional[GLiNERDetector] = None
_campus_singleton: Optional[CampusNERDetector] = None


class DetectionError(RuntimeError):
    """识别服务异常或结果无效；错误说明不含材料原文。"""


@lru_cache(maxsize=1)
def _reviewed_detector(model_dir: str, device: str, decoding: str = "greedy") -> ReviewedNERDetector:
    """人工 gold NER 候选检测器（按目录+设备缓存，避免重复加载）。"""
    if device not in {"cpu", "cuda"}:
        raise DetectionError("人工 gold NER 设备配置必须是 cpu 或 cuda")
    if decoding not in {"greedy", "bio_viterbi"}:
        raise DetectionError("人工 gold NER 解码配置无效")
    options = {"decoding": decoding} if decoding != "greedy" else {}
    detector = ReviewedNERDetector(model_dir, device=device, **options)
    if not detector.available:
        raise DetectionError("已启用的人工 gold NER 模型不可用，已暂停处理")
    return detector


def build_detectors(use_campus_ner: Optional[bool] = None,
                    use_gliner: Optional[bool] = None) -> List[Detector]:
    """构建识别器链。

    :param use_campus_ner: 是否接入 ★ 领域预训练 NER。
        传 None 时按配置决定（config.use_campus_ner()，默认关闭）——
        领域模型推理约 576ms/2000字，会超出「规则+识别路径 P95 ≤ 500ms」的指标，
        因此默认走规则底座，需要时再显式开启。
    :param use_gliner: 是否接入 GLiNER v3 语义实体识别（A 层）。
        传 None 时按配置决定（config.use_gliner()，默认关闭）——
        GLiNER 负责语义类+格式类（除身份证外的 13 类），身份证由正则权威判定。

    另有一条**独立于上述开关**的可选链路：人工 gold NER 候选模型。
    只要 ``SHIELD_REVIEWED_NER_MODEL_DIR`` 非空就会被接入（config.reviewed_ner_settings()），
    与 GLiNER 可同时开启，两者结果由 merge_spans 统一归并。
    """
    global _gliner_singleton, _campus_singleton

    if use_campus_ner is None:
        use_campus_ner = cfg.use_campus_ner()
    if use_gliner is None:
        use_gliner = cfg.use_gliner()

    detectors: List[Detector] = [RegexDetector(), EntityDetector(detect_org_location=not use_gliner)]
    reviewed_path, reviewed_device = cfg.reviewed_ner_settings()
    if reviewed_path:
        detectors.append(_reviewed_detector(reviewed_path, reviewed_device, cfg.reviewed_ner_decoding()))
    if use_campus_ner:
        if _campus_singleton is None:
            _campus_singleton = CampusNERDetector()
        ner = _campus_singleton
        if not ner.available:
            raise DetectionError("已启用的领域识别模型不可用，已暂停处理")
        detectors.append(ner)
    if use_gliner:
        if _gliner_singleton is None:
            _gliner_singleton = GLiNERDetector()
        gliner = _gliner_singleton
        if not gliner.available:
            raise DetectionError("已启用的 GLiNER 识别模型不可用，已暂停处理")
        detectors.append(gliner)
    return detectors


def merge_spans(spans: List[Span], text: Optional[str] = None) -> List[Span]:
    """合并重叠片段。

    规则：
    - 同类别重叠 → 取**置信度更高**的那一个的精确边界（不再强制取并集）：
      模型（GLiNER）边界精确、词典/启发式边界偏宽（会把「的地点为/活动将在/这次承办
      单位叫」等引入词一并框入），并集会产生 FP；按置信度选精确者能同时兼顾
      格式类（正则置信 1.0 胜 GLiNER）与语义类（GLiNER ~0.9 胜词典 0.75-0.82）。
    - 跨类别重叠 → 对整个重叠区间采用更严格类别，绝不丢弃区间两端的原文。
    - 合并后的 text 始终对应原始字符区间；不修改识别器提供的对象。
    """
    if not spans:
        return []
    spans = [replace(span) for span in spans]
    for span in spans:
        if (not isinstance(span.start, int) or not isinstance(span.end, int)
                or span.start < 0 or span.end <= span.start
                or (text is not None and span.end > len(text))):
            raise DetectionError("识别结果的位置无效，已暂停处理")
        if text is not None:
            span.text = text[span.start:span.end]
        elif len(span.text) != span.end - span.start:
            raise DetectionError("识别结果的文本长度与位置不一致，已暂停处理")
    # A complete email token has one boundary. Digits in its local part are
    # not a separate telephone/student field, even if a numeric detector or
    # token classifier guessed a higher-sensitivity category for that slice.
    emails = [span for span in spans if span.detector == "regex" and span.category == "EMAIL"]
    spans = [span for span in spans if not (
        span.category in {"PHONE", "STUDENT_ID"}
        and any(email.start <= span.start and span.end <= email.end for email in emails))]
    spans.sort(key=lambda s: (s.start, -(s.end - s.start)))
    merged: List[Span] = [spans[0]]

    bans = set(cfg.rules().get("hard_constraints", {}).get("absolute_ban", []))
    direct = {"PERSON_NAME", "PHONE", "EMAIL", "STUDENT_ID", "WECHAT"}

    # 跨类别冲突时的检测器可信度：正则带格式/校验位验证（GB 11643、Luhn），
    # 是权威判定；模型是概率猜测。模型可能以更高的"自信"覆盖正则的正确结果
    # （实测 v3c 把身份证以 1.0 分判成 API_KEY，盖掉正则 0.99 的 ID_CARD）。
    # 语义类正则不做，因此该排序不会削弱 GLiNER 在语义类上的优势。
    _DETECTOR_RANK = {"regex": 3, "campus_ner": 2, "gliner": 2, "entity": 1}

    def priority(span: Span):
        return (span.category in bans, category_level(span.category),
                span.category in direct, _DETECTOR_RANK.get(span.detector, 0),
                span.confidence, span.end - span.start)

    for cur in spans[1:]:
        last = merged[-1]
        if cur.start >= last.end:
            merged.append(cur)
            continue
        # 存在重叠
        if last.category == cur.category:
            # 同类别：取置信度更高的精确边界（更紧者优先，兼顾精度）
            winner = max((last, cur), key=lambda s: (s.confidence, -(s.end - s.start)))
            merged[-1] = winner
            continue
        # 跨类别：取并集 + 更严格类别（安全优先，不丢原文）
        start, end = last.start, max(last.end, cur.end)
        union_text = (text[start:end] if text is not None else
                      last.text + cur.text[max(0, last.end - cur.start):])
        winner = max((last, cur), key=priority)
        merged[-1] = replace(winner, start=start, end=end, text=union_text,
                             confidence=max(last.confidence, cur.confidence))
    return merged


def detect_all(text: str, columns=None, rows=None,
               detectors: Optional[List[Detector]] = None) -> List[Span]:
    """跑完所有识别器并合并结果。"""
    detectors = detectors if detectors is not None else build_detectors()
    if not detectors:
        raise DetectionError("没有可用识别器，已暂停处理")
    all_spans: List[Span] = []
    for d in detectors:
        try:
            all_spans.extend(d.detect(text, columns=columns, rows=rows))
        except Exception:
            # 不能把识别失败等同于“没有敏感信息”；异常消息也可能包含输入原文。
            raise DetectionError("敏感信息识别器执行失败，已暂停处理") from None
    try:
        return merge_spans(all_spans, text)
    except DetectionError:
        raise
    except Exception:
        raise DetectionError("敏感信息识别结果无效，已暂停处理") from None


def segmentize(text: str, spans: Optional[List[Span]] = None) -> List[Segment]:
    """把正文切成决策单元（按句/换行）。"""
    segments: List[Segment] = []
    pos = 0
    for piece in _SENT_SPLIT_RE.split(text):
        if not piece:
            continue
        start = pos
        end = pos + len(piece)
        segments.append(Segment(
            seg_id=f"seg_{len(segments)}",
            text=piece, start=start, end=end,
        ))
        pos = end
    if not segments:
        segments.append(Segment("seg_0", text, 0, len(text)))
    if spans:
        # 列值、跨行实体可能包含句号/换行，不能被切成没有任何 span 的“干净”片段。
        joined: List[Segment] = []
        for segment in segments:
            if joined and any(span.start < segment.start < span.end for span in spans):
                previous = joined[-1]
                previous.end = segment.end
                previous.text = text[previous.start:previous.end]
            else:
                segment.seg_id = f"seg_{len(joined)}"
                joined.append(segment)
        segments = joined
    return segments


def attach_spans(segments: List[Segment], spans: List[Span],
                 text: Optional[str] = None, context_window: int = 30) -> None:
    """把全局坐标的 Span 挂到所属 Segment 上，并填充局部上下文。

    :param text: 全文。传入时 seg.context 取前后各 context_window 字的真实窗口，
        而非仅本段文本（此前 left/right 算了却没用，min() 是空操作，导致
        [CONTEXT] 永远等于 [TEXT]，"模型读上下文"形同虚设）。
    """
    if any(not any(segment.start <= span.start and span.end <= segment.end
                   for segment in segments) for span in spans):
        raise DetectionError("敏感实体未完整归属处理片段，已暂停处理")
    for seg in segments:
        seg.spans = [s for s in spans if s.start >= seg.start and s.end <= seg.end]
        if text is not None:
            ctx_start = max(0, seg.start - context_window)
            ctx_end = min(len(text), seg.end + context_window)
            seg.context = text[ctx_start:ctx_end]
        else:
            seg.context = seg.text  # 无全文时退化为本段文本（调用方可再注入）


def detect_and_segment(text: str, columns=None, rows=None,
                       detectors=None) -> Tuple[List[Span], List[Segment]]:
    """识别 + 分段，返回 (全局 spans, segments)。"""
    spans = detect_all(text, columns=columns, rows=rows, detectors=detectors)
    segments = segmentize(text, spans)
    attach_spans(segments, spans, text=text)
    return spans, segments
